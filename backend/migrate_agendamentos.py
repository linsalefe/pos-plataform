"""Tabela `agendamentos` — módulo de agendamento pela landing page.

Rodar uma vez:

    cd backend && venv/bin/python migrate_agendamentos.py

Idempotente, numa única transação (engine.begin): ou entra tudo, ou não entra nada.

------------------------------------------------------------------------------------------
POR QUE UMA TABELA NOSSA
------------------------------------------------------------------------------------------
O agendamento na Exact são TRÊS chamadas sem transação (BoxesAdd, LeadsAdd, scheduleAdd) e
sem desfazer para a última (não existe `ScheduleRemove` na API — conferido no `$metadata`).
Um fluxo que morra no meio não deixa rastro NENHUM do lado da Exact: o box criado some da
listagem se o lead for excluído, e a tentativa que falhou nunca existiu.

Esta tabela é a única auditoria possível, e é também o que o job de faxina lê para saber
quais boxes `available` são nossos — a Exact não distingue um box criado por nós de um bloco
criado pela consultora na UI.

------------------------------------------------------------------------------------------
NOTAS DE SCHEMA
------------------------------------------------------------------------------------------
  * `slot_inicio`/`slot_fim` são TIMESTAMP SEM FUSO, naive em São Paulo. É o mesmo padrão de
    `messages.timestamp` e `nat_scheduled_actions.run_at`, e é também o que a Exact guarda em
    `Boxes.start` — que é hora de parede apesar do sufixo 'Z' (AGENDAMENTO_FINDINGS.md §1).
    TIMESTAMPTZ aqui obrigaria a converter nos dois sentidos e criaria o erro de 3 horas que
    o módulo inteiro existe para evitar.

  * `created_at`/`updated_at` NOT NULL **sem** server_default. O DEFAULT NOW() do Postgres é
    UTC (o banco está em Etc/UTC), e misturar uma coluna em UTC com duas em SP na mesma linha
    é como se erra um relatório. Quem escreve é o Python, sempre com `agora_sp()`.

  * SEM FK para `exact_leads`. O lead nasce na Exact e só entra em `exact_leads` no sync
    seguinte — até 10 minutos depois. Uma FK recusaria a linha exatamente no instante do
    agendamento, que é quando ela mais importa.

  * `box_id` NÃO é único. Um box removido pela faxina pode, em tese, ter o id reaproveitado
    pela Exact; e mais importante: um UNIQUE transformaria colisão inesperada num 500 na cara
    do visitante da LP, para proteger uma garantia que não precisamos.

  * Índice parcial `(passo) WHERE passo = 'box_criado'` — é EXATAMENTE a consulta da faxina,
    que roda a cada minuto. A esmagadora maioria das linhas estará em `agendado` ou `falhou`,
    e não tem por que ser indexada.

  * Índice `(slot_inicio)` — é a consulta de disponibilidade, que subtrai os slots já tomados
    por nós dentro do horizonte de 14 dias.

  * `origem_ip` VARCHAR(45): comprimento de um IPv6 em texto. Guardado para investigar abuso
    na LP pública, não para rate limit (esse é em memória, ver `agendamento/routes.py`).

NÃO cria endpoint, NÃO sobe job, NÃO fala com a Exact. A tabela nasce vazia e o único código
que a escreve é o módulo de agendamento.
"""
import asyncio

from sqlalchemy import text

from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text("SET lock_timeout = '3s'"))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agendamentos (
                id              BIGSERIAL PRIMARY KEY,
                nome            VARCHAR(200) NOT NULL,
                email           VARCHAR(200),
                telefone        VARCHAR(20)  NOT NULL,
                slot_inicio     TIMESTAMP    NOT NULL,
                slot_fim        TIMESTAMP    NOT NULL,
                sales_rep_email VARCHAR(200) NOT NULL,
                box_id          BIGINT,
                lead_id         BIGINT,
                meeting_id      BIGINT,
                passo           VARCHAR(20)  NOT NULL DEFAULT 'iniciado',
                erro            TEXT,
                origem_ip       VARCHAR(45),
                created_at      TIMESTAMP    NOT NULL,
                updated_at      TIMESTAMP    NOT NULL
            )
        """))

        # A consulta da faxina, que roda a cada minuto.
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agendamentos_faxina
                ON agendamentos (passo, updated_at)
                WHERE passo = 'box_criado'
        """))

        # A consulta de disponibilidade.
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agendamentos_slot
                ON agendamentos (slot_inicio)
        """))

        # Conferência na mesma transação — se algo acima não pegou, aparece aqui.
        cols = (await conn.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'agendamentos'"))).scalar()
        idx_faxina = (await conn.execute(text(
            "SELECT count(*) FROM pg_indexes WHERE tablename = 'agendamentos' "
            "AND indexname = 'idx_agendamentos_faxina'"))).scalar()
        idx_slot = (await conn.execute(text(
            "SELECT count(*) FROM pg_indexes WHERE tablename = 'agendamentos' "
            "AND indexname = 'idx_agendamentos_slot'"))).scalar()
        linhas = (await conn.execute(text("SELECT count(*) FROM agendamentos"))).scalar()

    print(f"OK: agendamentos com {cols} colunas (esperado 15)")
    print(f"OK: idx_agendamentos_faxina presente: {idx_faxina == 1}")
    print(f"OK: idx_agendamentos_slot presente: {idx_slot == 1}")
    print(f"OK: {linhas} linhas (0 é o esperado numa instalação nova)")
    print("Nenhum endpoint exposto, nenhum job iniciado, nada enviado à Exact.")


if __name__ == "__main__":
    asyncio.run(migrate())
