"""Risco 3: `skipped` como status de ação, e o MOTIVO gravado no banco.

Duas mudanças, as duas aditivas e reversíveis:

    1. nat_scheduled_actions.motivo  TEXT NULL
    2. o CHECK de status passa a aceitar 'skipped'

POR QUE O CHECK PRECISA VIR ANTES DO CÓDIGO
-------------------------------------------------------------------------------------------
`nat_scheduled_status_valido` hoje aceita quatro valores. Um deploy do código novo contra o
banco velho não falharia no boot: falharia no primeiro lead que o handler decidisse pular,
com IntegrityError dentro do agendador — ou seja, na produção, em cima de um lead real, e
transformando um `skipped` limpo numa retentativa que vai falhar três vezes e virar `falhou`.

Banco à frente do código é a direção segura da assimetria (é a mesma regra que a migração do
espontâneo seguiu em 25/08): com o CHECK largo e o código velho, nada muda — o processo velho
simplesmente nunca escreve 'skipped'.

IDEMPOTENTE. Roda quantas vezes for preciso.
"""
import asyncio

from sqlalchemy import text

from app.database import engine


async def migrar():
    async with engine.begin() as conn:
        ja = (await conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='nat_scheduled_actions' AND column_name='motivo'"))).first()
        if ja:
            print("• coluna motivo já existe")
        else:
            await conn.execute(text(
                "ALTER TABLE nat_scheduled_actions ADD COLUMN motivo TEXT"))
            print("✅ nat_scheduled_actions.motivo criada")

        # DROP + ADD porque Postgres não tem ALTER CONSTRAINT para CHECK. Dentro da mesma
        # transação de `engine.begin()`: ou o banco fica com o CHECK novo, ou com o velho —
        # nunca sem CHECK nenhum.
        await conn.execute(text(
            "ALTER TABLE nat_scheduled_actions "
            "DROP CONSTRAINT IF EXISTS nat_scheduled_status_valido"))
        await conn.execute(text(
            "ALTER TABLE nat_scheduled_actions ADD CONSTRAINT nat_scheduled_status_valido "
            "CHECK (status IN ('pendente','executado','cancelado','falhou','skipped'))"))
        print("✅ CHECK de status aceita 'skipped'")

        linhas = (await conn.execute(text(
            "SELECT status, count(*) FROM nat_scheduled_actions GROUP BY status ORDER BY 1"
        ))).all()
        print("\nEstado atual da fila:")
        for status, n in linhas:
            print(f"  {status:<10} {n}")


if __name__ == "__main__":
    asyncio.run(migrar())
