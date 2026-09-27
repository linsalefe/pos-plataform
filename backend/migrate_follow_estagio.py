"""Follow automático por estágio da Exact — as tabelas `follow_estagio_envios` e `..._cursor`.

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python migrate_follow_estagio.py

É idempotente (`CREATE TABLE IF NOT EXISTS`, índices `IF NOT EXISTS`, CHECK por DROP + ADD,
cursor por `ON CONFLICT DO NOTHING`). Pode rodar de novo sem efeito — inclusive o cursor, que
NÃO é reinicializado numa segunda passada (ver a seção sobre isso).

==========================================================================================
O QUE ESTA MIGRAÇÃO DESTRAVA
==========================================================================================
O processo comercial prevê nove follows por lead, e quem os manda hoje é um humano
selecionando leads na tela de Automações. MEDIDO no recon de 27/09
(`RECON_FOLLOW_AUTOMATICO_20260927.md` §1.4): das 1 255 entradas em estágio de follow do
funil 18535 nos últimos 30 dias, **só 35 % a 51 % foram seguidas de um template em 24 h** — e
o `" Follows 9"`, a despedida, saiu em **2 % (1 de 63)**.

Não é um buraco de sistema: é o calendário de quem seleciona. Estas tabelas são o que permite
o arrasto do card na Exact virar o gatilho, em vez de a lista da semana.

==========================================================================================
POR QUE A UNIQUE É `(lead_exact_id, estagio_id)` E NÃO INCLUI `evento_id`
==========================================================================================
É a regra de negócio inteira num índice: **uma vez por estágio por lead, para sempre**.

§4.3 do recon: 28 pares (lead, estágio) se repetem em 30 dias, em 20 leads, e o padrão é o
vaivém do fim da escada (`Follows 9 -> Follows 8 -> Follows 9`, observado em 17-18/09 num
lote). Incluir `evento_id` na UNIQUE faria a reentrada passar, e o lead receberia a despedida
do `mensagem_follow9` duas vezes em 32 horas.

A UNIQUE **não é parcial**. A de `nat_scheduled_actions` é
(`WHERE status = 'pendente'`), e ali está certo — mas aqui a linha executada tem de continuar
bloqueando, senão "para sempre" dura só até o envio.

==========================================================================================
CHECK EM `status`, NADA MAIS
==========================================================================================
O CHECK é construído a partir de `FE_STATUS` (`app/models.py`), padrão de
`migrate_rd_conversoes.py:97-99`: as duas definições nascem da mesma lista, e divergir faz o
INSERT falhar na hora em vez de gravar um status que ninguém drena.

`estagio_id` e `template` ficam **SEM CHECK e SEM FK**, pela lição de
`migrate_rd_conversoes.py` e de `migrate_agendamentos_subsource.py:26-27`: o mapa vive em
`follow_estagios.json`, e mudar um template ou corrigir um id não pode exigir migração. Um
CHECK desatualizado viraria erro no meio de um envio real.

==========================================================================================
O CURSOR NASCE EM `MAX(id)`, NUNCA EM 0 — E É O PONTO MAIS IMPORTANTE DAQUI
==========================================================================================
`follow_estagio_cursor.ultimo_evento_id` é inicializado com o `MAX(id)` de
`exact_stage_events` **no momento em que esta migração roda**.

Com 0, a primeira passada do job varreria o histórico inteiro e enfileiraria um follow para
cada entrada em estágio já ocorrida — **1 255 só nos últimos 30 dias**, para leads que já
foram descartados, já compraram ou já receberam a despedida. O gate
`FOLLOW_ESTAGIO_ENABLED=false` não protege disso: ele segura o ENVIO enquanto estiver fechado,
mas o dia em que abrisse o cursor ainda estaria em 0 e a enxurrada sairia então.

`ON CONFLICT (id) DO NOTHING`: rodar a migração de novo **não move o cursor**. Se movesse,
uma segunda execução pularia os eventos ocorridos entre as duas — e o operador que roda
`migrate` duas vezes por hábito não tem como saber que perdeu um dia de follows.

Para reprocessar de propósito (um teste, um estágio novo), é um UPDATE explícito à mão. Que é
como deve ser: baixar a marca d'água é decisão, não efeito colateral de rodar um script.

==========================================================================================
NÃO ALTERA COMPORTAMENTO POR SI SÓ
==========================================================================================
Criar as tabelas não liga nada. O job (`app/follow_estagio.py`) nasce com
`FOLLOW_ESTAGIO_ENABLED` em `false`: ele não lê eventos, não insere linha e não envia nada até
o operador abrir o gate no `.env`. Com `FOLLOW_ESTAGIO_SOMENTE_TELEFONES` preenchido, só os
telefones da lista entram.

Esta migração **não** envia mensagem, **não** toca `nat_config` (o
`follow_enabled = false` que desliga o `follow_20h` do agente é um UPDATE separado, no
CHECKPOINT da sprint, de propósito — ela desliga uma régua que já existe e isso merece uma
decisão explícita), **não** toca `auto_welcome_config`, `exact_leads`, `exact_stage_events`
nem `messages`.

==========================================================================================
SEM O RITUAL DE `migrate_message_autoria`
==========================================================================================
Lá há `lock_timeout`, FK `NOT VALID` + `VALIDATE` e índices `CONCURRENTLY`, porque a tabela
era quente, com 32 mil linhas e o webhook escrevendo. Aqui as duas tabelas NÃO EXISTEM: não há
lock a disputar, não há linha a varrer, não há escritor a bloquear. O único SELECT em tabela
existente é um `MAX(id)` sobre o índice primário de `exact_stage_events`. Repetir a cerimônia
seria imitação, não cuidado.
"""
import asyncio

from sqlalchemy import text

from app.database import engine
from app.models import FE_STATUS

TABELA = "follow_estagio_envios"
TABELA_CURSOR = "follow_estagio_cursor"

DDL = """
CREATE TABLE IF NOT EXISTS follow_estagio_envios (
    id            BIGSERIAL    PRIMARY KEY,
    lead_exact_id BIGINT       NOT NULL,
    telefone      VARCHAR(30),
    estagio_id    INTEGER      NOT NULL,
    estagio_nome  VARCHAR(50),
    template      VARCHAR(512) NOT NULL,
    evento_id     BIGINT,
    status        VARCHAR(20)  NOT NULL DEFAULT 'pendente',
    motivo        TEXT,
    resposta      TEXT,
    created_at    TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    enviado_em    TIMESTAMP
)
"""

DDL_CURSOR = """
CREATE TABLE IF NOT EXISTS follow_estagio_cursor (
    id               INTEGER   PRIMARY KEY,
    ultimo_evento_id BIGINT    NOT NULL DEFAULT 0,
    atualizado_em    TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
)
"""

# Espelha FE_STATUS de app/models.py. Construído, não digitado.
CHECK_NOME = "follow_estagio_envios_status_valido"
CHECK_SQL = "CHECK (status IN (" + ", ".join(f"'{s}'" for s in FE_STATUS) + "))"

INDICES = {
    # A REGRA DE NEGÓCIO: uma vez por estágio por lead, para sempre. Não é parcial — ver a
    # seção sobre isso no cabeçalho.
    "ux_follow_estagio_lead_estagio":
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_follow_estagio_lead_estagio "
        "ON follow_estagio_envios (lead_exact_id, estagio_id)",
    # A consulta do drenador, e só ela. PARCIAL de propósito: `enviado`, `skipped` e `falhou`
    # são terminais e crescem para sempre (~42 linhas/dia esperadas), e um índice completo
    # carregaria o histórico numa busca que só olha a cauda viva.
    "ix_follow_estagio_pendente":
        "CREATE INDEX IF NOT EXISTS ix_follow_estagio_pendente "
        "ON follow_estagio_envios (id) WHERE status = 'pendente'",
    # Para a auditoria do teste e do relatório futuro: "o que saiu neste estágio?".
    "ix_follow_estagio_estagio_created":
        "CREATE INDEX IF NOT EXISTS ix_follow_estagio_estagio_created "
        "ON follow_estagio_envios (estagio_id, created_at DESC)",
}


async def migrar():
    async with engine.begin() as conn:
        for t in (TABELA, TABELA_CURSOR):
            ja = (await conn.execute(text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name = :t"), {"t": t})).scalar()
            print(f"BEFORE — {t} existe: {bool(ja)}")

        await conn.execute(text(DDL))
        print(f"  CREATE TABLE IF NOT EXISTS {TABELA}")
        await conn.execute(text(DDL_CURSOR))
        print(f"  CREATE TABLE IF NOT EXISTS {TABELA_CURSOR}")

        # DROP + ADD porque o Postgres não tem ALTER CONSTRAINT para CHECK. Dentro da mesma
        # transação do `engine.begin()`: ou a tabela fica com o CHECK novo, ou com o velho —
        # nunca sem CHECK nenhum. Mesmo ritual de migrate_rd_conversoes.py:150-155.
        await conn.execute(text(
            f"ALTER TABLE {TABELA} DROP CONSTRAINT IF EXISTS {CHECK_NOME}"))
        await conn.execute(text(
            f"ALTER TABLE {TABELA} ADD CONSTRAINT {CHECK_NOME} {CHECK_SQL}"))
        print(f"  {CHECK_NOME} {CHECK_SQL}")

        for ddl in INDICES.values():
            await conn.execute(text(ddl))
            print(f"  {ddl}")

        # ------------------------------------------------------------------------------
        # A MARCA D'ÁGUA. `MAX(id)` e não 0 — ver a seção no cabeçalho.
        # ------------------------------------------------------------------------------
        # `coalesce(..., 0)` cobre a base vazia (um ambiente novo, um dump limpo): ali 0 é o
        # valor certo, porque não há histórico para varrer.
        maximo = (await conn.execute(text(
            "SELECT coalesce(max(id), 0) FROM exact_stage_events"))).scalar()
        print(f"\n  exact_stage_events: MAX(id) = {maximo}")

        # ON CONFLICT DO NOTHING: uma segunda execução NÃO move o cursor. Baixar a marca
        # d'água é decisão explícita (UPDATE à mão), não efeito de rodar o script de novo.
        await conn.execute(text(
            "INSERT INTO follow_estagio_cursor (id, ultimo_evento_id) VALUES (1, :m) "
            "ON CONFLICT (id) DO NOTHING"), {"m": maximo})
        atual = (await conn.execute(text(
            "SELECT ultimo_evento_id, atualizado_em FROM follow_estagio_cursor "
            "WHERE id = 1"))).first()
        print(f"  cursor id=1 -> ultimo_evento_id = {atual[0]} (atualizado {atual[1]})")
        if atual[0] != maximo:
            print(f"  ℹ️  o cursor JÁ existia em {atual[0]} e NÃO foi movido para {maximo} — "
                  f"{maximo - atual[0]} evento(s) serão processados na próxima passada.")

        print(f"\nAFTER — {TABELA}:")
        for nome, tipo, nulo, padrao in (await conn.execute(text("""
                SELECT column_name, data_type, is_nullable, coalesce(column_default,'')
                FROM information_schema.columns
                WHERE table_name = :t ORDER BY ordinal_position"""), {"t": TABELA})).all():
            print(f"  coluna {nome:<15} {tipo:<28} nullable={nulo:<3} default={padrao}")

        for t in (TABELA, TABELA_CURSOR):
            for (nome,) in (await conn.execute(text(
                    "SELECT indexname FROM pg_indexes WHERE tablename = :t "
                    "ORDER BY indexname"), {"t": t})).all():
                print(f"  índice {nome}")

        for nome, definicao in (await conn.execute(text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                f"WHERE conrelid = '{TABELA}'::regclass AND contype = 'c'"))).all():
            print(f"  CHECK  {nome} {definicao}")

        linhas = (await conn.execute(text(f"SELECT count(*) FROM {TABELA}"))).scalar()
        print(f"\nOK: {linhas} linha(s) em {TABELA} — 0 é o esperado (sem backfill).")
        print("Nenhum comportamento alterado por esta migração: o job nasce desligado "
              "(FOLLOW_ESTAGIO_ENABLED != true) e o cursor já está no fim do histórico.")
        print("NÃO tocou nat_config: desligar o follow_20h do agente é UPDATE separado.")


if __name__ == "__main__":
    asyncio.run(migrar())
