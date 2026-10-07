"""Espelho das reuniões da Exact — as tabelas `reuniao_status` e `reuniao_sync_cursor`.

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python migrate_reuniao_status.py

É idempotente (`CREATE TABLE IF NOT EXISTS`, índices `IF NOT EXISTS`, CHECK por DROP + ADD,
cursor por `ON CONFLICT DO NOTHING`). Pode rodar de novo sem efeito, inclusive no cursor, que
NÃO é reinicializado numa segunda passada.

==========================================================================================
O QUE ESTA MIGRAÇÃO DESTRAVA
==========================================================================================
O Hub não sabe o que acontece com a reunião depois que ela nasce. `agendamentos.passo` fica
`agendado` para sempre, e o sync de leads só lê `/Leads` (`exact_spotter.py:501`). MEDIDO em
07/10 (`RECON_CONFIRMACAO_NOSHOW_20261007_REPORT.md`):

  * 4 lembretes T-30 saíram para reunião que já tinha sido remarcada (§2);
  * 2 lembretes estavam pendentes para reunião já `Cancelada` (cancelados à mão em 07/10);
  * 64 de 249 reuniões desde 07/09 foram marcadas direto na Exact e não existem em
    `agendamentos` (§5.3).

`reuniao_status` é o espelho de `GET /Meetings`: o lembrete passa a ler daqui, e os blocos 1
(confirmação) e 2 (no-show) também vão ler.

==========================================================================================
POR QUE A CHAVE É `meeting_id`
==========================================================================================
Remarcar na Exact é cancelar a reunião e criar outra com id novo (RECON §5.4: 0 de 158
reuniões do Hub com data diferente da gravada; 22 leads com 2+ reuniões, a antiga sempre
`Cancelada`). Uma reunião nunca muda de data: o que muda é qual reunião é a vigente da pessoa.
Por isso o PK é o id da Exact, e a pessoa é o `telefone_chave` (DDD + 8 últimos), indexado.

==========================================================================================
CHECK EM `exact_type` E EM `origem`, NADA MAIS
==========================================================================================
Os dois CHECKs são construídos de `EXACT_TYPES` e `ORIGENS_REUNIAO` (`app/models.py`), padrão
de `migrate_follow_estagio.py`: as duas definições nascem da mesma lista. Um `type` novo na
Exact faz o upsert daquela reunião falhar alto, em vez de gravar um valor que nenhuma regra
(lembrete, confirmação, no-show) sabe tratar.

`confirmado_por`, `cancelado_motivo` e `regua_encerrada_motivo` ficam SEM CHECK: são dos
blocos 1 e 2, os valores ainda não estão fechados, e um CHECK desatualizado viraria erro no
meio de uma confirmação real.

==========================================================================================
FK PARA `agendamentos`, COM `ON DELETE SET NULL`
==========================================================================================
O repo evita FK em tabela escrita pelo webhook (uma FK a mais é um jeito a mais de derrubar o
lote de mensagens). Aqui quem escreve é um job próprio, sem webhook no caminho, e a FK pega o
erro de vincular a um agendamento que não existe. `BIGINT` porque `agendamentos.id` é
BIGSERIAL. `SET NULL` para o espelho não impedir uma limpeza em `agendamentos`.

==========================================================================================
RELÓGIOS
==========================================================================================
Tudo em `reuniao_status` é SP naive, inclusive `created_at`/`updated_at`, que aqui têm default
`now() AT TIME ZONE 'America/Sao_Paulo'` (e não o `now()` puro, que no banco em Etc/UTC dá
UTC). Uma tabela com dois relógios misturados é o defeito do `dashboard_stats`, que zera das
21h às 24h. `slot_inicio` é o `startTime` da Exact sem conversão (hora de parede, FINDINGS §1).

A exceção é o cursor, `reuniao_sync_cursor.register_date_cursor`, que é UTC naive: ele é
comparado com o `registerDate` da Exact, que é UTC de verdade.

==========================================================================================
O CURSOR NASCE EM 07/09/2026
==========================================================================================
O mesmo recorte do RECON, para o primeiro ciclo devolver um retrato comparável com o §5.2
(249 reuniões, Cancelada 155 · Concluido 73 · Vigente 21 em 07/10 06h). Medido: 218 reuniões
registradas desde 07/09, abaixo do `$top=500` de uma página só.

Backfill aqui é inofensivo, ao contrário do follow por estágio: o Bloco 0 não manda mensagem
nenhuma. Ele grava o espelho e passa a pular lembrete de reunião que não está `Vigente`.

`ON CONFLICT (id) DO NOTHING`: rodar de novo NÃO move o cursor. Mover para trás é UPDATE à mão.

==========================================================================================
NÃO ALTERA COMPORTAMENTO POR SI SÓ
==========================================================================================
Criar as tabelas não liga nada. O job (`app/reuniao_sync.py`) só lê a Exact com
`REUNIAO_SYNC_ENABLED=true`. Sem linha em `reuniao_status`, o guard do lembrete deixa passar
(fail-closed só sobre o que ele sabe). Esta migração não toca `agendamentos`,
`nat_scheduled_actions`, `messages` nem `exact_leads`.

As duas tabelas NÃO EXISTEM ainda: não há lock a disputar nem linha a varrer. Sem
`lock_timeout` e sem `CONCURRENTLY`, pelo mesmo motivo de `migrate_follow_estagio.py`.
"""
import asyncio
from datetime import datetime

from sqlalchemy import text

from app.database import engine
from app.models import EXACT_TYPES, ORIGENS_REUNIAO

TABELA = "reuniao_status"
TABELA_CURSOR = "reuniao_sync_cursor"

# Mesmo recorte do RECON §5.2. UTC naive (ver "RELÓGIOS").
# `datetime` e não string: o asyncpg recusa string em parâmetro de timestamp (DataError).
CURSOR_INICIAL = datetime(2026, 9, 7, 0, 0, 0)

AGORA_SP = "(now() AT TIME ZONE 'America/Sao_Paulo')"

DDL = f"""
CREATE TABLE IF NOT EXISTS reuniao_status (
    meeting_id             BIGINT       PRIMARY KEY,
    lead_id                BIGINT,
    telefone_chave         VARCHAR(10),
    telefone_bruto         VARCHAR(30),
    nome                   VARCHAR(255),
    slot_inicio            TIMESTAMP    NOT NULL,
    slot_fim               TIMESTAMP,
    sales_rep_email        VARCHAR(255),
    origem                 VARCHAR(10)  NOT NULL,
    agendamento_id         BIGINT       REFERENCES agendamentos(id) ON DELETE SET NULL,
    exact_type             VARCHAR(20)  NOT NULL,
    exact_type_visto_em    TIMESTAMP    NOT NULL,
    exact_type_anterior    VARCHAR(20),
    registrado_em          TIMESTAMP,
    confirmado_em          TIMESTAMP,
    confirmado_por         VARCHAR(10),
    cancelado_em           TIMESTAMP,
    cancelado_motivo       VARCHAR(60),
    noshow_em              TIMESTAMP,
    regua_encerrada_em     TIMESTAMP,
    regua_encerrada_motivo VARCHAR(60),
    created_at             TIMESTAMP    NOT NULL DEFAULT {AGORA_SP},
    updated_at             TIMESTAMP    NOT NULL DEFAULT {AGORA_SP}
)
"""

DDL_CURSOR = """
CREATE TABLE IF NOT EXISTS reuniao_sync_cursor (
    id                     INTEGER   PRIMARY KEY,
    register_date_cursor   TIMESTAMP,
    ultimo_ciclo_em        TIMESTAMP,
    ultimo_ciclo_resultado TEXT
)
"""

# Construídos, não digitados — ver "CHECK EM ..." no cabeçalho.
CHECKS = {
    "reuniao_status_exact_type_valido":
        "CHECK (exact_type IN (" + ", ".join(f"'{t}'" for t in EXACT_TYPES) + "))",
    "reuniao_status_exact_type_anterior_valido":
        "CHECK (exact_type_anterior IS NULL OR exact_type_anterior IN ("
        + ", ".join(f"'{t}'" for t in EXACT_TYPES) + "))",
    "reuniao_status_origem_valida":
        "CHECK (origem IN (" + ", ".join(f"'{o}'" for o in ORIGENS_REUNIAO) + "))",
}

INDICES = {
    # A pergunta do guard do lembrete e dos blocos seguintes: "qual é a reunião vigente desta
    # PESSOA?". Composto com slot_inicio porque a busca é sempre "desta pessoa, daqui para
    # frente".
    "ix_reuniao_status_telefone_slot":
        "CREATE INDEX IF NOT EXISTS ix_reuniao_status_telefone_slot "
        "ON reuniao_status (telefone_chave, slot_inicio)",
    # O vínculo com a nossa tabela: o guard parte de `agendamentos.id`.
    "ix_reuniao_status_agendamento":
        "CREATE INDEX IF NOT EXISTS ix_reuniao_status_agendamento "
        "ON reuniao_status (agendamento_id)",
    "ix_reuniao_status_lead":
        "CREATE INDEX IF NOT EXISTS ix_reuniao_status_lead "
        "ON reuniao_status (lead_id)",
    # O que o bloco 1 vai varrer: reuniões futuras por horário.
    "ix_reuniao_status_slot":
        "CREATE INDEX IF NOT EXISTS ix_reuniao_status_slot "
        "ON reuniao_status (slot_inicio)",
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
        # transação: ou fica o CHECK novo, ou o velho, nunca nenhum.
        for nome, sql in CHECKS.items():
            await conn.execute(text(f"ALTER TABLE {TABELA} DROP CONSTRAINT IF EXISTS {nome}"))
            await conn.execute(text(f"ALTER TABLE {TABELA} ADD CONSTRAINT {nome} {sql}"))
            print(f"  {nome} {sql}")

        for ddl in INDICES.values():
            await conn.execute(text(ddl))
            print(f"  {ddl}")

        # ON CONFLICT DO NOTHING: uma segunda execução NÃO move o cursor.
        await conn.execute(text(
            "INSERT INTO reuniao_sync_cursor (id, register_date_cursor) "
            "VALUES (1, :c) ON CONFLICT (id) DO NOTHING"),
            {"c": CURSOR_INICIAL})
        atual = (await conn.execute(text(
            "SELECT register_date_cursor, ultimo_ciclo_em FROM reuniao_sync_cursor "
            "WHERE id = 1"))).first()
        print(f"\n  cursor id=1 -> register_date_cursor = {atual[0]} (UTC), "
              f"ultimo_ciclo_em = {atual[1]}")

        print(f"\nAFTER — {TABELA}:")
        for nome, tipo, nulo, padrao in (await conn.execute(text("""
                SELECT column_name, data_type, is_nullable, coalesce(column_default,'')
                FROM information_schema.columns
                WHERE table_name = :t ORDER BY ordinal_position"""), {"t": TABELA})).all():
            print(f"  coluna {nome:<22} {tipo:<28} nullable={nulo:<3} default={padrao}")

        for t in (TABELA, TABELA_CURSOR):
            for (nome,) in (await conn.execute(text(
                    "SELECT indexname FROM pg_indexes WHERE tablename = :t "
                    "ORDER BY indexname"), {"t": t})).all():
                print(f"  índice {nome}")

        for nome, definicao in (await conn.execute(text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                f"WHERE conrelid = '{TABELA}'::regclass AND contype IN ('c', 'f')"))).all():
            print(f"  CONSTRAINT {nome} {definicao}")

        linhas = (await conn.execute(text(f"SELECT count(*) FROM {TABELA}"))).scalar()
        print(f"\nOK: {linhas} linha(s) em {TABELA}. 0 é o esperado: o backfill é do job.")
        print("Nenhum comportamento alterado por esta migração: o job só lê a Exact com "
              "REUNIAO_SYNC_ENABLED=true.")


if __name__ == "__main__":
    asyncio.run(migrar())
