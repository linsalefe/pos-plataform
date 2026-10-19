"""`reuniao_status`: remarcação pendente (SPRINT_REMARCACAO_20261019).

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python migrate_remarcacao_pendente.py

Idempotente (`ADD COLUMN IF NOT EXISTS`). Sem índice: a tabela tem algumas centenas de linhas e
o filtro que a lê carrega a tabela em memória (`app/reuniao_contato.py`), como em
`migrate_sdr_tratado.py`.

⚠️ RODAR ANTES DO DEPLOY DA BRANCH. `models.ReuniaoStatus` passa a declarar estas colunas, e todo
`select(ReuniaoStatus)` (régua, sync, filtros) quebra num banco sem elas.

POR QUE (RECON_REAGENDAMENTO_20261018 §3): a Exact recusa o `scheduleAdd` enquanto a reunião
antiga está Vigente. O lead escolhe o horário novo na hora, mas a reunião nova só pode nascer
depois que um humano cancelar a antiga na Exact. A escolha fica na linha da reunião ANTIGA:

    slot_desejado_inicio      SP naive, o `inicio` do slot escolhido. NULL = nada pendente
    slot_desejado_consultora  e-mail da consultora livre no slot quando o lead escolheu
    remarcacao_tentativas     quantas vezes o Hub já tentou o `scheduleAdd` (máx. 2)
    remarcacao_expira_em      SP naive; antiga ainda Vigente depois disto = humano

Sem CHECK: os valores vêm só de `app/remarcacao.py`.
"""
import asyncio

from sqlalchemy import text

from app.database import engine

DDL = (
    "ALTER TABLE reuniao_status ADD COLUMN IF NOT EXISTS slot_desejado_inicio TIMESTAMP",
    "ALTER TABLE reuniao_status ADD COLUMN IF NOT EXISTS slot_desejado_consultora VARCHAR(255)",
    "ALTER TABLE reuniao_status ADD COLUMN IF NOT EXISTS remarcacao_tentativas INTEGER "
    "NOT NULL DEFAULT 0",
    "ALTER TABLE reuniao_status ADD COLUMN IF NOT EXISTS remarcacao_expira_em TIMESTAMP",
)


async def migrar():
    async with engine.begin() as conn:
        for sql in DDL:
            print(f"  {sql}")
            await conn.execute(text(sql))
        cols = (await conn.execute(text(
            "SELECT column_name, data_type, column_default FROM information_schema.columns "
            "WHERE table_name='reuniao_status' AND (column_name LIKE 'slot_desejado%' "
            "OR column_name LIKE 'remarcacao%') ORDER BY column_name"))).all()
        print(f"✅ colunas: {cols}")


if __name__ == "__main__":
    asyncio.run(migrar())
