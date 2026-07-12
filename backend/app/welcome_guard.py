"""Trava única do template de boas-vindas.

O template de boas-vindas SÓ pode sair por dois caminhos:
  1. o fluxo automático (respeita enabled + carimbo de idempotência);
  2. o reenvio manual individual (POST /api/exact-leads/{exact_id}/resend-welcome).

Qualquer outro caminho de envio DEVE chamar `bloquear_se_boas_vindas()` no início do handler.

A trava vai nas PORTAS (endpoints), nunca no corredor: NÃO colocar isto dentro de
`send_template_message` (whatsapp.py) — a automação usa essa mesma função e seria bloqueada.

NUNCA importar routes / exact_routes / exact_spotter aqui — este módulo precisa ser neutro
para não recriar o import circular.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AutoWelcomeConfig

TEMPLATE_BOAS_VINDAS_FIXO = "nat_boasvindas"

MSG_BLOQUEIO = (
    "Este template é o de boas-vindas automáticas e não pode ser enviado manualmente, "
    "em massa, nem agendado. Ele é disparado apenas pela automação, para leads novos."
)


async def templates_bloqueados(db: AsyncSession) -> set:
    """Nomes normalizados (lower/strip) que não podem ser enviados fora da automação.

    Inclui a trava fixa (nat_boasvindas) e o template configurado no painel — assim a trava
    continua valendo mesmo se alguém trocar o template na tela.
    """
    nomes = {TEMPLATE_BOAS_VINDAS_FIXO}
    try:
        res = await db.execute(select(AutoWelcomeConfig).where(AutoWelcomeConfig.id == 1))
        cfg = res.scalar_one_or_none()
        if cfg and cfg.template_name:
            nomes.add(cfg.template_name.strip().lower())
    except Exception:
        pass  # sem config = mantém ao menos a trava fixa
    return nomes


async def bloquear_se_boas_vindas(template_name, db: AsyncSession) -> None:
    """Levanta HTTP 400 se for o template de boas-vindas. Chamar no INÍCIO do handler."""
    if (template_name or "").strip().lower() in await templates_bloqueados(db):
        raise HTTPException(status_code=400, detail=MSG_BLOQUEIO)
