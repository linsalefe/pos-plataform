"""API admin da mensagem automática de boas-vindas.

GET  /api/auto-welcome/config   -> lê o singleton
PUT  /api/auto-welcome/config   -> grava; no false->true executa o CORTE DE ATIVAÇÃO
GET  /api/auto-welcome/preview  -> dry-run: quantos leads ainda não foram decididos
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.database import get_db
from app.models import AutoWelcomeConfig, Channel, ExactLead
from app.exact_spotter import get_auto_welcome_config, _funnels_from_config

router = APIRouter(prefix="/api/auto-welcome", tags=["auto-welcome"])


def _serialize(cfg: AutoWelcomeConfig) -> dict:
    return {
        "enabled": cfg.enabled,
        "channel_id": cfg.channel_id,
        "template_name": cfg.template_name,
        "template_language": cfg.template_language,
        "funnel_ids": [int(x) for x in (cfg.funnel_ids or "").split(",") if x.strip().isdigit()],
        "updated_by_name": cfg.updated_by_name,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)):
    cfg = await get_auto_welcome_config(db)
    if cfg is None:
        raise HTTPException(404, "Config não inicializada.")
    return _serialize(cfg)


@router.get("/preview")
async def preview(db: AsyncSession = Depends(get_db)):
    """Dry-run: quantos leads nos funis-alvo ainda NÃO tiveram decisão registrada.

    Critério = welcome_status IS NULL — o MESMO da trava de idempotência do envio.
    Usar welcome_sent_at aqui faria a tela mentir (leads pulados apareceriam como pendentes).
    """
    cfg = await get_auto_welcome_config(db)
    funnels = _funnels_from_config(cfg)
    res = await db.execute(
        select(ExactLead).where(
            ExactLead.funnel_id.in_(list(funnels)),
            ExactLead.welcome_status.is_(None),
        )
    )
    leads = res.scalars().all()
    return {
        "target_funnels": list(funnels),
        "pending_count": len(leads),
        "sample": [{"exact_id": l.exact_id, "name": l.name, "funnel_id": l.funnel_id}
                   for l in leads[:20]],
    }


@router.put("/config")
async def update_config(req: dict, db: AsyncSession = Depends(get_db)):
    cfg = await get_auto_welcome_config(db)
    if cfg is None:
        raise HTTPException(404, "Config não inicializada.")

    # Para LIGAR: canal e template são obrigatórios e o canal tem que existir.
    if req.get("enabled"):
        if not req.get("channel_id") and not cfg.channel_id:
            raise HTTPException(400, "Para ligar é preciso escolher um canal.")
        ch_id = req.get("channel_id") or cfg.channel_id
        ch = await db.execute(select(Channel).where(Channel.id == ch_id))
        if ch.scalar_one_or_none() is None:
            raise HTTPException(400, f"Canal id={ch_id} não existe.")
        if not (req.get("template_name") or cfg.template_name):
            raise HTTPException(400, "Para ligar é preciso um template.")

    estava_desligada = not cfg.enabled
    vai_ligar = bool(req.get("enabled")) and estava_desligada
    cortados = 0

    # ⭐ CORTE DE ATIVAÇÃO — na MESMA transação, ANTES de gravar enabled=True.
    # Ninguém que já existe recebe boas-vindas. A automação começa do zero, deste instante em
    # diante. Implementa a regra: "só recebe quem chegar DEPOIS de ligar". Cobre inclusive os
    # leads ingeridos enquanto o botão estava desligado — nenhuma fila represada estoura.
    if vai_ligar:
        r = await db.execute(
            update(ExactLead)
            .where(ExactLead.welcome_status.is_(None))
            .values(welcome_status="skipped",
                    welcome_error="corte de ativação: lead anterior ao ligamento da automação")
        )
        cortados = r.rowcount or 0

    if "enabled" in req:
        cfg.enabled = bool(req["enabled"])
    if "channel_id" in req:
        cfg.channel_id = req["channel_id"]
    if "template_name" in req:
        cfg.template_name = req["template_name"]
    if "template_language" in req:
        cfg.template_language = req["template_language"] or "pt_BR"
    if "funnel_ids" in req:
        ids = req["funnel_ids"]
        if isinstance(ids, list):
            cfg.funnel_ids = ",".join(str(int(x)) for x in ids)
        elif isinstance(ids, str):
            cfg.funnel_ids = ids
    if "updated_by_name" in req:
        cfg.updated_by_name = req.get("updated_by_name")

    await db.commit()
    await db.refresh(cfg)

    out = _serialize(cfg)
    out["leads_cortados_na_ativacao"] = cortados
    return out
