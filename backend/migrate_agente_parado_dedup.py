"""S4-2: idempotência POR CONSTRAINT na anti-repetição do `agente_parado`.

    cd backend && venv/bin/python migrate_agente_parado_dedup.py

O QUE FAZ, E SÓ ISSO
-------------------------------------------------------------------------------------------
Um índice ÚNICO PARCIAL sobre `notifications`:

    CREATE UNIQUE INDEX CONCURRENTLY uq_notif_agente_parado
        ON notifications (contact_wa_id, ref) WHERE type = 'agente_parado';

Não altera coluna, não altera CHECK, não reescreve tabela. É construção de índice.

POR QUE, SE O JOB NÃO TEM CORRIDA
-------------------------------------------------------------------------------------------
`agente_parado.varrer` faz SELECT-antes-de-INSERT sobre `idx_notifications_dedup`
(contact_wa_id, type, ref), que NÃO é único — a mesma mecânica do `window_alerts_job`. Hoje
não há corrida: o job é uma única task asyncio, sequencial, uma varredura por vez.

"Hoje não há corrida" é uma propriedade do agendamento, não do dado. Um segundo processo
(um worker, um restart sobreposto, um comando manual) reintroduz a corrida sem que ninguém
perceba, e o sintoma seria a sineta da gestão duplicando avisos do MESMO caso — exatamente o
ruído que o teto de 20 existe para evitar. A regra do projeto é idempotência por constraint,
e ela vale mesmo quando a corrida ainda não existe.

PARCIAL, e não sobre a tabela inteira
-------------------------------------------------------------------------------------------
`(contact_wa_id, type, ref)` global NÃO pode virar único: `nat_sla` e `nat_recuperacao`
gravam `ref = '<kind>:<acao_id>'` de propósito para que dois escalonamentos do mesmo lead
apareçam como dois avisos, e os `window_*` já convivem com o padrão atual. Restringir a
`type = 'agente_parado'` toca só o tipo criado nesta sprint, que tinha ZERO linhas quando o
índice foi criado — não há risco de a criação falhar por duplicata preexistente.

`ref` é NULL-able na tabela, e no Postgres NULLs são distintos num índice único. Não abre
buraco aqui: `ref` recebe `Message.wa_message_id`, que é `nullable=False` na origem.

CONCURRENTLY: não trava escrita na `notifications` enquanto constrói. Por isso NÃO pode
rodar dentro de bloco de transação — daí `AUTOCOMMIT` abaixo, e não `engine.begin()`.

IDEMPOTENTE. Roda quantas vezes for preciso.
"""
import asyncio

from sqlalchemy import text

from app.database import engine

INDICE = "uq_notif_agente_parado"


async def migrar():
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")

        antes = (await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='notifications' "
            "ORDER BY indexname"))).scalars().all()
        print("BEFORE — índices de notifications:")
        for i in antes:
            print(f"  {i}")

        dups = (await conn.execute(text(
            "SELECT contact_wa_id, ref, count(*) FROM notifications "
            "WHERE type='agente_parado' GROUP BY 1,2 HAVING count(*) > 1"))).all()
        if dups:
            raise SystemExit(f"❌ {len(dups)} duplicata(s) em agente_parado — o índice "
                             f"falharia. Resolva os dados antes: {dups[:5]}")
        print("\n• nenhuma duplicata preexistente — o índice pode ser criado")

        if INDICE in antes:
            print(f"• {INDICE} já existe — nada a fazer")
        else:
            await conn.execute(text(
                f"CREATE UNIQUE INDEX CONCURRENTLY {INDICE} "
                f"ON notifications (contact_wa_id, ref) WHERE type = 'agente_parado'"))
            print(f"✅ {INDICE} criado")

        depois = (await conn.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='notifications' "
            "ORDER BY indexname"))).all()
        print("\nAFTER — índices de notifications:")
        for nome, definicao in depois:
            marca = "  <-- NOVO" if nome == INDICE and INDICE not in antes else ""
            print(f"  {nome}{marca}")
            if nome == INDICE:
                print(f"      {definicao}")

        valido = (await conn.execute(text(
            "SELECT i.indisvalid, i.indisunique FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :n"),
            {"n": INDICE})).first()
        print(f"\nindisvalid={valido[0]} indisunique={valido[1]}"
              if valido else "\n⚠️  índice não encontrado após a criação")


if __name__ == "__main__":
    asyncio.run(migrar())
