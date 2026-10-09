"""Reentrega da Meta depois do pool esgotado de 09/10/2026 (INCIDENTE_LOGIN_POOL_20261009.md).

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python consulta_reentrega_webhook_20261009.py

Mensagens RECEBIDAS cuja hora da Meta (`messages.timestamp`, naive SP) cai em 09/10 12h–14h SP e
que entraram no banco (`messages.created_at`, UTC naive = hora do INSERT) com atraso. Atraso
> 2 min = reentrega (o normal medido é ~1 s). Rodar de novo até 10/10 14h SP para fechar a
janela de 24h; a Meta tenta por até 7 dias, e o que chegar depois também aparece
(`dentro_de_24h` separa). Só lê.
"""
import asyncio

from sqlalchemy import text

from app.database import async_session

RESUMO = """
WITH janela AS (
    SELECT m.id, m.contact_wa_id, m.timestamp AS hora_meta_sp,
           (m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') AS chegou_sp,
           m.message_type
    FROM messages m
    WHERE m.direction = 'inbound'
      AND m.timestamp >= '2026-10-09 12:00' AND m.timestamp < '2026-10-09 14:00'
)
SELECT count(*)                                                       AS recebidas_na_janela,
       count(*) FILTER (WHERE chegou_sp - hora_meta_sp > interval '2 min') AS chegaram_atrasadas,
       count(*) FILTER (WHERE chegou_sp - hora_meta_sp > interval '2 min'
                          AND chegou_sp - hora_meta_sp <= interval '24 hours') AS dentro_de_24h,
       max(chegou_sp - hora_meta_sp)                                   AS maior_atraso
FROM janela"""

DETALHE = """
SELECT contact_wa_id, hora_meta_sp, chegou_sp, chegou_sp - hora_meta_sp AS atraso, message_type
FROM (
    SELECT m.contact_wa_id, m.timestamp AS hora_meta_sp,
           (m.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') AS chegou_sp,
           m.message_type
    FROM messages m
    WHERE m.direction = 'inbound'
      AND m.timestamp >= '2026-10-09 12:00' AND m.timestamp < '2026-10-09 14:00'
) x
WHERE chegou_sp - hora_meta_sp > interval '2 min'
ORDER BY hora_meta_sp"""


async def main():
    async with async_session() as db:
        r = (await db.execute(text(RESUMO))).first()
        print(f"recebidas na janela: {r.recebidas_na_janela} | atrasadas: {r.chegaram_atrasadas} "
              f"| dentro de 24h: {r.dentro_de_24h} | maior atraso: {r.maior_atraso}")
        for d in (await db.execute(text(DETALHE))).all():
            print(f"  {d.contact_wa_id}  meta {d.hora_meta_sp:%d/%m %H:%M:%S}  "
                  f"chegou {d.chegou_sp:%d/%m %H:%M:%S}  atraso {d.atraso}  {d.message_type}")


asyncio.run(main())
