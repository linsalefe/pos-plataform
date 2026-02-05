from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import ExactLead
from app.exact_spotter import sync_exact_leads

router = APIRouter(prefix="/api/exact-leads", tags=["exact-leads"])


@router.get("")
async def list_exact_leads(
    stage: str = None,
    sub_source: str = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(ExactLead).order_by(ExactLead.register_date.desc())

    if stage:
        query = query.where(ExactLead.stage == stage)
    if sub_source:
        query = query.where(ExactLead.sub_source == sub_source)

    result = await db.execute(query)
    leads = result.scalars().all()

    return [
        {
            "id": l.id,
            "exact_id": l.exact_id,
            "name": l.name,
            "phone1": l.phone1,
            "phone2": l.phone2,
            "source": l.source,
            "sub_source": l.sub_source,
            "stage": l.stage,
            "funnel_id": l.funnel_id,
            "sdr_name": l.sdr_name,
            "register_date": l.register_date.isoformat() if l.register_date else None,
            "update_date": l.update_date.isoformat() if l.update_date else None,
            "synced_at": l.synced_at.isoformat() if l.synced_at else None,
        }
        for l in leads
    ]


@router.post("/sync")
async def trigger_sync(db: AsyncSession = Depends(get_db)):
    result = await sync_exact_leads(db)
    return {"status": "ok", **result}


@router.get("/stats")
async def exact_leads_stats(db: AsyncSession = Depends(get_db)):
    total = await db.execute(select(func.count(ExactLead.id)))
    total = total.scalar()

    stage_result = await db.execute(
        select(ExactLead.stage, func.count(ExactLead.id)).group_by(ExactLead.stage)
    )
    stages = {row[0] or "N/A": row[1] for row in stage_result.all()}

    sub_source_result = await db.execute(
        select(ExactLead.sub_source, func.count(ExactLead.id)).group_by(ExactLead.sub_source)
    )
    sub_sources = {row[0] or "N/A": row[1] for row in sub_source_result.all()}

    return {
        "total": total,
        "by_stage": stages,
        "by_sub_source": sub_sources,
    }
