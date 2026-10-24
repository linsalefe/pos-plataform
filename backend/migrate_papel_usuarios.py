"""`users.papel`, conta 3 desativada e transferida, e a tag `Vagas afirmativas` (24/10/2026).

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python migrate_papel_usuarios.py          # só conta
    cd /home/ubuntu/pos-plataform/backend && venv/bin/python migrate_papel_usuarios.py --aplicar

Idempotente: `ADD COLUMN IF NOT EXISTS`, UPDATEs que convergem e `ON CONFLICT DO NOTHING`.
Sem `--aplicar`, roda tudo numa transação e faz ROLLBACK no fim: mostra as contagens sem
gravar nada.

POR QUE `papel` E NÃO `role`. `role` é permissão (admin/atendente) e continua igual: 7 de 8
usuários são admin e a decisão de 24/10 é esconder, não bloquear. `papel` é operação (quem é
SDR, quem é consultora), e passa a ser a fonte única de "quem é SDR", que hoje mora espalhada
em `SDR_USER_IDS` no .env e `SDR_IDS_PERMITIDOS` em nat_guard.py
(RECON_4_PEDIDOS_COMERCIAL_20261024 §4).

AS DECISÕES DO ÁLEFE (24/10):
  * 5 Thobias = único `sdr`. 6 Victória (`comercialcenat@gmail.com`) = a Victória Amorim,
    `consultora`. 1 Álefe e 2 Isa = `gestao`. 4, 7, 8 = `outro`.
  * 3 "Vi Amorim" é resquício: `outro`, `is_active=false`, contatos e notificações não lidas
    para o Thobias. NÃO é apagada: `messages.sent_by` e históricos ainda a referenciam.

A TAG. Dono não separa os contatos de vagas (o Thobias é dono de 127 dos 159 e é ele quem abre
com `vagasafirmativas_1`). O que separa é a régua: todo contato que recebeu um template
`*vagasafirmativas*` ganha a tag. Backfill desde 01/09 (início de `sent_by`).
"""
import asyncio
import sys

from sqlalchemy import text

from app.database import engine

TAG_VAGAS = "Vagas afirmativas"
COR_VAGAS = "purple"

PAPEIS = {5: "sdr", 6: "consultora", 1: "gestao", 2: "gestao",
          3: "outro", 4: "outro", 7: "outro", 8: "outro"}

DDL = ("ALTER TABLE users ADD COLUMN IF NOT EXISTS papel VARCHAR(20) NOT NULL DEFAULT 'outro'",)


async def _contar(conn, rotulo, sql, **p):
    n = (await conn.execute(text(sql), p)).scalar()
    print(f"  {rotulo}: {n}")
    return n


async def migrar(aplicar: bool):
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            for sql in DDL:
                print(f"  {sql}")
                await conn.execute(text(sql))

            for uid, papel in PAPEIS.items():
                await conn.execute(text("UPDATE users SET papel=:p WHERE id=:i"),
                                   {"p": papel, "i": uid})
            print("  papéis:", (await conn.execute(text(
                "SELECT id, name, role, papel, is_active FROM users ORDER BY id"))).all())

            await conn.execute(text("UPDATE users SET is_active=false WHERE id=3"))

            await _contar(conn, "contatos da conta 3 -> Thobias",
                          "SELECT count(*) FROM contacts WHERE assigned_to=3")
            await conn.execute(text("UPDATE contacts SET assigned_to=5 WHERE assigned_to=3"))

            await _contar(conn, "notificações não lidas da conta 3 -> Thobias",
                          "SELECT count(*) FROM notifications WHERE user_id=3 AND is_read=false")
            await conn.execute(text(
                "UPDATE notifications SET user_id=5 WHERE user_id=3 AND is_read=false"))

            await conn.execute(text(
                "INSERT INTO tags (name, color) VALUES (:n, :c) ON CONFLICT (name) DO NOTHING"),
                {"n": TAG_VAGAS, "c": COR_VAGAS})
            tag_id = (await conn.execute(text("SELECT id FROM tags WHERE name=:n"),
                                         {"n": TAG_VAGAS})).scalar()
            await _contar(conn, "contatos com template de vagas desde 01/09",
                          "SELECT count(DISTINCT contact_wa_id) FROM messages "
                          "WHERE template_name ILIKE '%vagasafirmativas%' "
                          "AND timestamp >= '2026-09-01'")
            res = await conn.execute(text(
                "INSERT INTO contact_tags (contact_wa_id, tag_id) "
                "SELECT DISTINCT m.contact_wa_id, CAST(:t AS INTEGER) FROM messages m "
                "WHERE m.template_name ILIKE '%vagasafirmativas%' AND m.timestamp >= '2026-09-01' "
                "ON CONFLICT DO NOTHING"), {"t": tag_id})
            print(f"  tag '{TAG_VAGAS}' (id {tag_id}) aplicada agora: {res.rowcount}")

            if aplicar:
                await trans.commit()
                print("✅ aplicado")
            else:
                await trans.rollback()
                print("ℹ️ ensaio: ROLLBACK, nada gravado. Rode com --aplicar.")
        except Exception:
            await trans.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(migrar("--aplicar" in sys.argv))
