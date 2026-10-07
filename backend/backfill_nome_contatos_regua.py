"""Backfill de 07/10/2026: nome nos contatos sem nome que têm reunião no espelho.

    cd backend && venv/bin/python backfill_nome_contatos_regua.py           # dry-run
    cd backend && venv/bin/python backfill_nome_contatos_regua.py --apply   # grava

Só toca contato com `name` vazio (NULL ou só espaço). O nome vem da reunião mais recente da
pessoa em `reuniao_status` (pela chave tolerante do telefone, `relatorios.chave_sql`) e, se ela
não tiver nome, do lead dela em `exact_leads`. Daqui para a frente, o contato que a régua cria já
nasce com esse nome (`qualificacao_fluxo._contato_ou_criar(nome=...)`).
"""
import asyncio
import sys

from sqlalchemy import text

from app.database import async_session
from app.relatorios import chave_sql

SQL = f"""
SELECT c.wa_id,
       coalesce(nullif(trim(rs.nome), ''), nullif(trim(el.name), '')) AS nome
FROM contacts c
JOIN LATERAL (
    SELECT r.nome, r.lead_id FROM reuniao_status r
    WHERE r.telefone_chave = {chave_sql('c.wa_id')} AND {chave_sql('c.wa_id')} <> ''
    ORDER BY (coalesce(trim(r.nome), '') <> '') DESC, r.slot_inicio DESC LIMIT 1
) rs ON true
LEFT JOIN exact_leads el ON el.exact_id = rs.lead_id
WHERE coalesce(trim(c.name), '') = ''
"""


async def main(aplicar: bool) -> None:
    async with async_session() as db:
        linhas = [r for r in (await db.execute(text(SQL))).all() if r.nome]
        print(f"contatos sem nome com reunião no espelho e nome disponível: {len(linhas)}")
        for r in linhas[:5]:
            print(f"  …{r.wa_id[-4:]} -> {r.nome.split()[0]} …")
        if not aplicar:
            print("DRY-RUN: nada gravado. Use --apply.")
            return
        n = 0
        for r in linhas:
            res = await db.execute(text(
                "UPDATE contacts SET name = :nome WHERE wa_id = :w "
                "AND coalesce(trim(name), '') = ''"), {"nome": r.nome, "w": r.wa_id})
            n += res.rowcount or 0
        await db.commit()
        print(f"atualizados: {n}")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
