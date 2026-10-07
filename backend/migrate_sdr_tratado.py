"""`reuniao_status.sdr_tratado_em` (+ `sdr_tratado_por`) para o botão "Tratado" (07/10/2026).

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python migrate_sdr_tratado.py

Idempotente (`ADD COLUMN IF NOT EXISTS`). Duas colunas nullable, sem default e sem índice: a
tabela tem algumas centenas de linhas, e o filtro que as lê já carrega a tabela inteira em
memória (`app/reuniao_contato.py`).

POR QUE COLUNA E NÃO JSONB. `reuniao_status` não tem coluna JSONB livre (`models.ReuniaoStatus`).
Criar uma só para isto seria uma coluna genérica para um campo só.

`sdr_tratado_em` é SP naive, como todo relógio da tabela. `sdr_tratado_por` é o `users.id` de
quem clicou, sem FK (o espelho não pode ser derrubado por limpeza de usuário).
"""
import asyncio

from sqlalchemy import text

from app.database import engine

DDL = (
    "ALTER TABLE reuniao_status ADD COLUMN IF NOT EXISTS sdr_tratado_em TIMESTAMP",
    "ALTER TABLE reuniao_status ADD COLUMN IF NOT EXISTS sdr_tratado_por INTEGER",
)


async def migrar():
    async with engine.begin() as conn:
        for sql in DDL:
            print(f"  {sql}")
            await conn.execute(text(sql))
        cols = (await conn.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name='reuniao_status' AND column_name LIKE 'sdr_tratado%'"))).all()
        print(f"✅ colunas: {cols}")


if __name__ == "__main__":
    asyncio.run(migrar())
