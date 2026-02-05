import os
import httpx
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import ExactLead

BASE_URL = "https://api.exactspotter.com/v3"


def get_headers():
    return {
        "Content-Type": "application/json",
        "token_exact": os.getenv("EXACT_SPOTTER_TOKEN")
    }


async def fetch_leads_from_exact(skip: int = 0, top: int = 500):
    """Busca leads do Exact Spotter com paginação."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{BASE_URL}/Leads",
            headers=get_headers(),
            params={
                "$top": top,
                "$skip": skip,
                "$orderby": "Id desc"
            }
        )
        response.raise_for_status()
        return response.json()


def is_pos_lead(lead: dict) -> bool:
    """Verifica se o lead é de pós (subSource começa com 'pos')."""
    sub_source = lead.get("subSource")
    if sub_source and sub_source.get("value"):
        return sub_source["value"].lower().startswith("pos")
    return False


def parse_datetime(value: str):
    """Converte datetime string da API para objeto datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


async def sync_exact_leads(db: AsyncSession):
    """Sincroniza leads de pós do Exact Spotter com o banco local."""
    skip = 0
    top = 500
    total_synced = 0
    total_new = 0
    total_updated = 0

    while True:
        data = await fetch_leads_from_exact(skip=skip, top=top)
        leads = data.get("value", [])

        if not leads:
            break

        for lead in leads:
            if not is_pos_lead(lead):
                continue

            exact_id = lead["id"]
            result = await db.execute(
                select(ExactLead).where(ExactLead.exact_id == exact_id)
            )
            existing = result.scalar_one_or_none()

            lead_data = {
                "name": lead.get("lead", ""),
                "phone1": lead.get("phone1"),
                "phone2": lead.get("phone2"),
                "source": lead.get("source", {}).get("value") if lead.get("source") else None,
                "sub_source": lead.get("subSource", {}).get("value") if lead.get("subSource") else None,
                "stage": lead.get("stage"),
                "funnel_id": lead.get("funnelId"),
                "sdr_name": lead.get("sdr", {}).get("name") if lead.get("sdr") else None,
                "register_date": parse_datetime(lead.get("registerDate")),
                "update_date": parse_datetime(lead.get("updateDate")),
            }

            if existing:
                for key, value in lead_data.items():
                    setattr(existing, key, value)
                existing.synced_at = datetime.utcnow()
                total_updated += 1
            else:
                new_lead = ExactLead(exact_id=exact_id, **lead_data)
                db.add(new_lead)
                total_new += 1

            total_synced += 1

        # Se retornou menos que o top, acabaram os leads
        if len(leads) < top:
            break

        skip += top

    await db.commit()
    return {
        "total_synced": total_synced,
        "new": total_new,
        "updated": total_updated
    }
