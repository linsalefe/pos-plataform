"""Tag automática `Vagas afirmativas` pelo template enviado (24/10/2026).

Dono não separa os contatos de vagas afirmativas: o Thobias é dono de 127 dos 159 e é ele
quem abre a conversa com `vagasafirmativas_1`; a Victória só dispara os follows em lote
(RECON_4_PEDIDOS_COMERCIAL_20261024 §4). O que separa é a régua. Todo envio de template
`*vagasafirmativas*` marca o contato, e a tela de conversas filtra por essa tag.

Nunca derruba o envio: roda num savepoint próprio e só loga se falhar. O envio já aconteceu na
Meta, e perder a tag é muito menos grave que perder o registro da mensagem.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TAG_VAGAS = "Vagas afirmativas"
COR_VAGAS = "purple"
PADRAO_VAGAS = "vagasafirmativas"


def e_template_de_vagas(template_name: str | None) -> bool:
    return bool(template_name) and PADRAO_VAGAS in template_name.lower()


async def marcar_vagas(db: AsyncSession, wa_id: str, template_name: str | None) -> bool:
    """Aplica a tag se o template é de vagas. True = aplicou (ou já tinha). Nunca levanta."""
    if not e_template_de_vagas(template_name) or not wa_id:
        return False
    try:
        async with db.begin_nested():
            await db.execute(text(
                "INSERT INTO tags (name, color) VALUES (:n, :c) ON CONFLICT (name) DO NOTHING"),
                {"n": TAG_VAGAS, "c": COR_VAGAS})
            await db.execute(text(
                "INSERT INTO contact_tags (contact_wa_id, tag_id) "
                "SELECT :w, id FROM tags WHERE name = :n ON CONFLICT DO NOTHING"),
                {"w": wa_id, "n": TAG_VAGAS})
        return True
    except Exception as e:
        print(f"⚠️ tag vagas: não aplicada em {wa_id} ({type(e).__name__}: {e})")
        return False
