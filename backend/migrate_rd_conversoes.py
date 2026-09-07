"""Fase 1 da integração com o RD Station — a tabela `rd_conversoes`.

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python migrate_rd_conversoes.py

É idempotente (`CREATE TABLE IF NOT EXISTS`, índices `IF NOT EXISTS`, CHECK por DROP + ADD).
Pode rodar de novo sem efeito.

------------------------------------------------------------------------------------------
O QUE ESTA MIGRAÇÃO DESTRAVA
------------------------------------------------------------------------------------------
Em 18/08/2026 o formulário nativo da landing page substituiu o formulário do RD Station. O
lead passou a ir direto para o nosso backend e para a Exact, e o RD deixou de receber a
conversão que acorda os fluxos de automação de e-mail de cada pós. Nada quebrou visivelmente
— os e-mails só pararam de sair.

MEDIDO no RECON de 07/09/2026: **363 submissões com e-mail desde 18/08** que o RD nunca viu,
espalhadas por 13 dos 14 cursos da allowlist.

Esta tabela é a fila que devolve esse evento. A decisão (o que enviar) fica separada do envio
(quando enviar) porque o ponto de escrita é o meio do fluxo de agendamento, entre o commit do
`Agendamento` e o `BoxesAdd` que reserva o horário — um POST síncrono ali somaria a latência
do RD ao tempo que o visitante espera, e um timeout do RD viraria falha de agendamento.

------------------------------------------------------------------------------------------
POR QUE A UNIQUE É `(chave, conversion_identifier)` E NÃO `agendamento_id`
------------------------------------------------------------------------------------------
O fluxo de duas etapas da LP grava DUAS linhas em `agendamentos` para UMA submissão: o
`POST /lead` cria a primeira (`lead_criado`) e o `POST /agendar` cria a segunda (`agendado`),
com ids diferentes. Medido: 101 dos 124 e-mails repetidos desde 18/08 são exatamente esse par,
107 deles em menos de 30 minutos. Uma UNIQUE por `agendamento_id` deixaria as duas passarem e
a mesma pessoa apareceria no RD como duas conversões.

`chave` é `email:<normalizado>` ou `tel:<dígitos>` — a pessoa, não a tentativa.

------------------------------------------------------------------------------------------
CHECK EM `status`, MAS NÃO EM `conversion_identifier`
------------------------------------------------------------------------------------------
O CHECK de `status` é construído a partir de `RD_STATUS` (`app/models.py`), padrão de
`migrate_espontaneo.py:145-172`: as duas definições nascem da mesma lista, e divergir faz o
INSERT falhar na hora em vez de gravar um status que ninguém drena.

`conversion_identifier` e `sub_source` ficam SEM CHECK e SEM FK, pela lição de
`migrate_agendamentos_subsource.py:26-27`: o mapa vive em `rd_conversoes.json`, e um curso
novo não pode exigir migração. Um CHECK desatualizado viraria erro no meio de um agendamento
real — que é exatamente o que esta integração não pode custar.

------------------------------------------------------------------------------------------
NÃO COPIEI O RITUAL DE `migrate_message_autoria`
------------------------------------------------------------------------------------------
Lá há `lock_timeout`, FK `NOT VALID` + `VALIDATE` e índices `CONCURRENTLY`, porque a tabela
era quente, com 32 mil linhas e o webhook escrevendo. Aqui a tabela NÃO EXISTE: não há lock a
disputar, não há linha a varrer, não há escritor a bloquear. Repetir a cerimônia seria
imitação, não cuidado.

------------------------------------------------------------------------------------------
SEM BACKFILL NESTA MIGRAÇÃO
------------------------------------------------------------------------------------------
As 363 submissões anteriores entram por `backfill_rd_conversoes.py`, que é script separado,
tem `--dry-run` por padrão e SÓ ENFILEIRA — quem envia é o drenador, e só quando
`RD_ENVIO_ENABLED=true`. Misturar backfill com DDL tiraria de quem roda a chance de olhar a
fila antes de ela virar tráfego.

------------------------------------------------------------------------------------------
NÃO ALTERA COMPORTAMENTO POR SI SÓ
------------------------------------------------------------------------------------------
Criar a tabela não liga nada. O enfileiramento passa a gravar linhas assim que o código novo
subir, e o drenador nasce com `RD_ENVIO_ENABLED` em `false`: as linhas ficam `pendente` e
NENHUMA chamada ao RD acontece até o operador ligar o gate no `.env`. Esta migração não
envia mensagem, não toca `nat_config` nem `auto_welcome_config`, e não altera `agendamentos`.
"""
import asyncio

from sqlalchemy import text

from app.database import engine
from app.models import RD_STATUS

TABELA = "rd_conversoes"

DDL = """
CREATE TABLE IF NOT EXISTS rd_conversoes (
    id                    BIGSERIAL   PRIMARY KEY,
    chave                 TEXT        NOT NULL,
    conversion_identifier TEXT        NOT NULL,
    agendamento_id        BIGINT,
    sub_source            VARCHAR(100),
    payload               JSONB,
    status                VARCHAR(20) NOT NULL DEFAULT 'pendente',
    motivo                TEXT,
    tentativas            INTEGER     NOT NULL DEFAULT 0,
    run_at                TIMESTAMP   NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    resposta              TEXT,
    created_at            TIMESTAMP   NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    enviado_em            TIMESTAMP
)
"""

# Espelha RD_STATUS de app/models.py. Construído, não digitado: uma constante nova em Python
# sem a migração correspondente falha no INSERT, que é o alarme certo.
CHECK_NOME = "rd_conversoes_status_valido"
CHECK_SQL = ("CHECK (status IN (" + ", ".join(f"'{s}'" for s in RD_STATUS) + "))")

INDICES = {
    # A idempotência. `IF NOT EXISTS` para a migração poder rodar de novo; um índice único
    # sobre tabela vazia é instantâneo.
    "ux_rd_conversoes_chave_ident":
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_rd_conversoes_chave_ident "
        "ON rd_conversoes (chave, conversion_identifier)",
    # A consulta do drenador, e só ela: `status='pendente' AND run_at <= agora ORDER BY run_at`.
    # PARCIAL de propósito — `enviado` e `skipped` são terminais e crescem para sempre, e um
    # índice completo carregaria o histórico inteiro numa busca que só olha a cauda viva.
    "ix_rd_conversoes_pendente":
        "CREATE INDEX IF NOT EXISTS ix_rd_conversoes_pendente "
        "ON rd_conversoes (run_at) WHERE status = 'pendente'",
}


async def migrar():
    async with engine.begin() as conn:
        ja_existia = (await conn.execute(text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = :t"), {"t": TABELA})).scalar()
        print(f"BEFORE — {TABELA} existe: {bool(ja_existia)}")

        await conn.execute(text(DDL))
        print(f"  CREATE TABLE IF NOT EXISTS {TABELA}")

        # DROP + ADD porque o Postgres não tem ALTER CONSTRAINT para CHECK. Dentro da mesma
        # transação do `engine.begin()`: ou a tabela fica com o CHECK novo, ou com o velho —
        # nunca sem CHECK nenhum. Mesmo ritual de migrate_acao_skipped.py:40-49.
        await conn.execute(text(
            f"ALTER TABLE {TABELA} DROP CONSTRAINT IF EXISTS {CHECK_NOME}"))
        await conn.execute(text(
            f"ALTER TABLE {TABELA} ADD CONSTRAINT {CHECK_NOME} {CHECK_SQL}"))
        print(f"  {CHECK_NOME} {CHECK_SQL}")

        for nome, ddl in INDICES.items():
            await conn.execute(text(ddl))
            print(f"  {ddl}")

        print(f"\nAFTER — {TABELA}:")
        for nome, tipo, nulo, padrao in (await conn.execute(text("""
                SELECT column_name, data_type, is_nullable, coalesce(column_default,'')
                FROM information_schema.columns
                WHERE table_name = :t ORDER BY ordinal_position"""), {"t": TABELA})).all():
            print(f"  coluna {nome:<22} {tipo:<28} nullable={nulo:<3} default={padrao}")

        for (nome,) in (await conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename = :t "
                "ORDER BY indexname"), {"t": TABELA})).all():
            print(f"  índice {nome}")

        for nome, definicao in (await conn.execute(text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                f"WHERE conrelid = '{TABELA}'::regclass AND contype = 'c'"))).all():
            print(f"  CHECK  {nome} {definicao}")

        linhas = (await conn.execute(text(f"SELECT count(*) FROM {TABELA}"))).scalar()
        print(f"\nOK: {linhas} linha(s) — 0 é o esperado (sem backfill nesta migração).")
        print("Nenhum comportamento alterado por esta migração: o envio nasce desligado "
              "(RD_ENVIO_ENABLED=false).")


if __name__ == "__main__":
    asyncio.run(migrar())
