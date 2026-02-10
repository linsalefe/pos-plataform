from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from app.database import get_db
from app.google_calendar import get_available_slots, get_available_dates, create_event, CALENDARS

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("/consultants")
async def list_consultants():
    """Lista consultoras disponíveis."""
    return [{"key": k, "name": v["name"], "calendar_id": v["calendar_id"]} for k, v in CALENDARS.items()]


@router.get("/available-dates/{consultant_key}")
async def available_dates(consultant_key: str):
    """Retorna próximos dias com horários livres."""
    if consultant_key not in CALENDARS:
        raise HTTPException(status_code=404, detail="Consultora não encontrada")
    cal_id = CALENDARS[consultant_key]["calendar_id"]
    dates = await get_available_dates(cal_id)
    return dates


@router.get("/available-slots/{consultant_key}/{date}")
async def available_slots(consultant_key: str, date: str):
    """Retorna horários livres de um dia."""
    if consultant_key not in CALENDARS:
        raise HTTPException(status_code=404, detail="Consultora não encontrada")
    cal_id = CALENDARS[consultant_key]["calendar_id"]
    slots = await get_available_slots(cal_id, date)
    return slots


@router.post("/book")
async def book_appointment(
    consultant_key: str,
    lead_name: str,
    lead_phone: str,
    course: str,
    date: str,
    time: str,
    duration: int = 30,
):
    """Agenda reunião no Google Calendar."""
    if consultant_key not in CALENDARS:
        raise HTTPException(status_code=404, detail="Consultora não encontrada")
    
    cal_id = CALENDARS[consultant_key]["calendar_id"]
    consultant_name = CALENDARS[consultant_key]["name"]
    
    # Verificar se o horário está livre
    slots = await get_available_slots(cal_id, date, duration)
    if not any(s["start"] == time for s in slots):
        raise HTTPException(status_code=409, detail="Horário não disponível")
    
    # Criar evento
    start_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=duration)
    
    summary = f"📞 Ligação - {lead_name} ({course})"
    description = f"Lead: {lead_name}\nTelefone: {lead_phone}\nCurso: {course}\nAgendado pela IA Nat"
    
    event = await create_event(cal_id, summary, description, start_dt, end_dt)
    
    return {
        "success": True,
        "consultant": consultant_name,
        "date": date,
        "time": time,
        "event_link": event.get("htmlLink"),
    }
