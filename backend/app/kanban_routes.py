"""
Rotas do Kanban: listar cards, mover entre colunas, atualizar notas.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models import AIConversationSummary, Contact
from app.ai_engine import generate_conversation_summary

router = APIRouter(prefix="/api/kanban", tags=["kanban"])


# === Schemas ===

class MoveCardRequest(BaseModel):
    status: str  # em_atendimento_ia, aguardando_humano, finalizado


class UpdateSummaryRequest(BaseModel):
    summary: Optional[str] = None
    lead_name: Optional[str] = None
    lead_course: Optional[str] = None


# === Listar Cards ===

@router.get("/cards")
async def list_kanban_cards(
    channel_id: Optional[int] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(AIConversationSummary).order_by(AIConversationSummary.updated_at.desc())

    if channel_id:
        query = query.where(AIConversationSummary.channel_id == channel_id)
    if status:
        query = query.where(AIConversationSummary.status == status)

    result = await db.execute(query)
    cards = result.scalars().all()

    return [
        {
            "id": c.id,
            "contact_wa_id": c.contact_wa_id,
            "channel_id": c.channel_id,
            "status": c.status,
            "summary": c.summary,
            "lead_name": c.lead_name,
            "lead_course": c.lead_course,
            "ai_messages_count": c.ai_messages_count,
            "human_took_over": c.human_took_over,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "finished_at": c.finished_at.isoformat() if c.finished_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in cards
    ]


# === Estatísticas do Kanban ===

@router.get("/stats")
async def kanban_stats(channel_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    base_filter = []
    if channel_id:
        base_filter.append(AIConversationSummary.channel_id == channel_id)

    # Total por status
    result = await db.execute(
        select(
            AIConversationSummary.status,
            func.count(AIConversationSummary.id),
        )
        .where(*base_filter)
        .group_by(AIConversationSummary.status)
    )
    status_counts = {row[0]: row[1] for row in result.all()}

    # Total geral
    total = sum(status_counts.values())

    # Humanos que assumiram
    human_result = await db.execute(
        select(func.count(AIConversationSummary.id)).where(
            AIConversationSummary.human_took_over == True,
            *base_filter,
        )
    )
    human_took_over = human_result.scalar()

    return {
        "total": total,
        "em_atendimento_ia": status_counts.get("em_atendimento_ia", 0),
        "aguardando_humano": status_counts.get("aguardando_humano", 0),
        "finalizado": status_counts.get("finalizado", 0),
        "human_took_over": human_took_over,
    }


# === Mover Card ===

@router.patch("/cards/{card_id}/move")
async def move_card(card_id: int, req: MoveCardRequest, db: AsyncSession = Depends(get_db)):
    valid_statuses = ["em_atendimento_ia", "aguardando_humano", "finalizado"]
    if req.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Status inválido. Use: {valid_statuses}")

    result = await db.execute(
        select(AIConversationSummary).where(AIConversationSummary.id == card_id)
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Card não encontrado")

    card.status = req.status

    if req.status == "finalizado":
        card.finished_at = datetime.utcnow()

    if req.status == "aguardando_humano":
        card.human_took_over = True
        # Desativar IA no contato
        contact_result = await db.execute(
            select(Contact).where(Contact.wa_id == card.contact_wa_id)
        )
        contact = contact_result.scalar_one_or_none()
        if contact:
            contact.ai_active = False

    await db.commit()
    return {"status": "moved", "new_status": req.status}


# === Atualizar Summary ===

@router.patch("/cards/{card_id}")
async def update_card(card_id: int, req: UpdateSummaryRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AIConversationSummary).where(AIConversationSummary.id == card_id)
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Card não encontrado")

    if req.summary is not None:
        card.summary = req.summary
    if req.lead_name is not None:
        card.lead_name = req.lead_name
    if req.lead_course is not None:
        card.lead_course = req.lead_course

    await db.commit()
    return {"status": "updated"}


# === Gerar Resumo Automático via IA ===

@router.post("/cards/{card_id}/generate-summary")
async def generate_summary(card_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AIConversationSummary).where(AIConversationSummary.id == card_id)
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Card não encontrado")

    summary = await generate_conversation_summary(card.contact_wa_id, db)

    if summary:
        card.summary = summary
        await db.commit()
        return {"status": "generated", "summary": summary}

    raise HTTPException(status_code=500, detail="Não foi possível gerar o resumo")