"""`agendamentos.sub_source` — de qual curso veio o lead da landing page.

Rodar uma vez:

    cd backend && venv/bin/python migrate_agendamentos_subsource.py

Idempotente, numa única transação. Aditiva: coluna nova, NULLABLE, sem default.

------------------------------------------------------------------------------------------
POR QUE A COLUNA EXISTE
------------------------------------------------------------------------------------------
O `subSource` deixou de ser constante no código e passou a vir do corpo do POST, conferido
contra a allowlist de `app/agendamento/origens.py`. Com uma LP por curso, é ele que responde
"quantos agendamentos vieram da página de Mulheridades?".

`exact_leads.sub_source` não serve para isso: o dado só chega ali no sync seguinte (até 10
minutos depois) e desaparece se o lead for excluído. Aqui ele é escrito no mesmo instante da
tentativa — inclusive nas que falharam, que a Exact não guarda de forma alguma.

NULLABLE porque as linhas anteriores a esta migração não têm como saber o valor. Na prática
não há nenhuma: a tabela está vazia (o E2E limpou a única linha que existiu).

VARCHAR(100): o maior subSource cadastrado hoje tem 47 caracteres
(`Posemcuidadoausuariosdealcooleoutrasdrogasturma4`). 100 dá folga sem convidar texto longo.

SEM CHECK e SEM FK. A allowlist vive em env, não no banco: acrescentar um curso não pode
exigir migração, e um CHECK desatualizado viraria erro no meio de um agendamento real.

NÃO cria endpoint, NÃO fala com a Exact, NÃO altera linha existente.
"""
import asyncio

from sqlalchemy import text

from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text("SET lock_timeout = '3s'"))

        await conn.execute(text(
            "ALTER TABLE agendamentos ADD COLUMN IF NOT EXISTS sub_source VARCHAR(100)"))

        col = (await conn.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'agendamentos' AND column_name = 'sub_source'"))).scalar()
        total = (await conn.execute(text("SELECT count(*) FROM agendamentos"))).scalar()
        preenchidos = (await conn.execute(text(
            "SELECT count(*) FROM agendamentos WHERE sub_source IS NOT NULL"))).scalar()

    print(f"OK: agendamentos.sub_source presente: {col == 1}")
    print(f"OK: {preenchidos} de {total} linhas com sub_source "
          "(0 de 0 é o esperado — só agendamentos NOVOS preenchem)")
    print("Nenhuma linha alterada, nada enviado à Exact.")


if __name__ == "__main__":
    asyncio.run(migrate())
