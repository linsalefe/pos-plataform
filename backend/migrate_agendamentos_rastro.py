"""`agendamentos.motivo_recusa` + `telefone` VARCHAR(30) — o rastro das tentativas recusadas.

Rodar uma vez, ANTES de reiniciar o backend com o código novo:

    cd backend && venv/bin/python migrate_agendamentos_rastro.py

Idempotente, numa única transação. Aditiva.

------------------------------------------------------------------------------------------
POR QUE EXISTE
------------------------------------------------------------------------------------------
Em 16–29/09/2026, 11 pessoas preencheram a LP de Direitos Humanos T4 e sumiram sem deixar
nome nem telefone em lugar nenhum: o `POST /lead` tomava 400 de origem ANTES de gravar a
linha em `agendamentos`, e o 422 de validação nem chega ao handler
(INVESTIGACAO_LEADS_LP_SPOTTER_20260930.md). Agora toda recusa grava uma linha com
`passo='recusado'`, e esta coluna diz o porquê.

  * `motivo_recusa VARCHAR(40) NULL`: NULL em toda linha antiga, e NULL em toda tentativa
    que não foi recusa. O código antigo não conhece a coluna e segue funcionando.
  * `telefone` de 20 para 30: a linha recusada guarda o telefone COMO VEIO. Aumentar o
    limite de um VARCHAR no Postgres é só catálogo, sem reescrever a tabela.

⚠️ A ORDEM IMPORTA: o model já declara `motivo_recusa`, e o SQLAlchemy põe toda coluna no
INSERT. Reiniciar com o código novo antes desta migração faz TODO agendamento falhar.

NÃO cria endpoint, NÃO fala com a Exact, NÃO altera valor de linha existente.
"""
import asyncio

from sqlalchemy import text

from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text("SET lock_timeout = '3s'"))

        await conn.execute(text(
            "ALTER TABLE agendamentos ADD COLUMN IF NOT EXISTS motivo_recusa VARCHAR(40)"))

        atual = (await conn.execute(text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'agendamentos' AND column_name = 'telefone'"))).scalar()
        if atual is not None and atual < 30:
            await conn.execute(text(
                "ALTER TABLE agendamentos ALTER COLUMN telefone TYPE VARCHAR(30)"))

        col = (await conn.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'agendamentos' AND column_name = 'motivo_recusa'"))).scalar()
        tel = (await conn.execute(text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'agendamentos' AND column_name = 'telefone'"))).scalar()
        total = (await conn.execute(text("SELECT count(*) FROM agendamentos"))).scalar()
        com_motivo = (await conn.execute(text(
            "SELECT count(*) FROM agendamentos WHERE motivo_recusa IS NOT NULL"))).scalar()

    print(f"OK: agendamentos.motivo_recusa presente: {col == 1}")
    print(f"OK: agendamentos.telefone VARCHAR({tel}) (era {atual})")
    print(f"OK: {com_motivo} de {total} linhas com motivo_recusa "
          "(0 é o esperado logo depois da migração)")
    print("Nenhuma linha alterada, nada enviado à Exact.")


if __name__ == "__main__":
    asyncio.run(migrate())
