import os
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "..", "google-credentials.json")

# Calendários das consultoras
CALENDARS = {
    "victoria": {
        "name": "Victória Amorim",
        "calendar_id": "comercialcenat@gmail.com",
    },
}


def get_service():
    """Cria serviço autenticado do Google Calendar."""
    credentials = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=credentials)


async def get_busy_slots(calendar_id: str, date_str: str):
    """Retorna horários ocupados de um dia específico."""
    service = get_service()
    date = datetime.strptime(date_str, "%Y-%m-%d")
    time_min = date.replace(hour=8, minute=0).isoformat() + "-03:00"
    time_max = date.replace(hour=18, minute=0).isoformat() + "-03:00"

    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "timeZone": "America/Sao_Paulo",
        "items": [{"id": calendar_id}],
    }
    result = service.freebusy().query(body=body).execute()
    busy = result["calendars"][calendar_id]["busy"]
    return busy


async def get_available_slots(calendar_id: str, date_str: str, duration_min: int = 30):
    """Retorna horários livres de um dia (slots de 30 min, das 8h às 18h)."""
    busy = await get_busy_slots(calendar_id, date_str)
    date = datetime.strptime(date_str, "%Y-%m-%d")

    # Gerar todos os slots possíveis (8h-18h)
    slots = []
    current = date.replace(hour=8, minute=0, second=0)
    end_of_day = date.replace(hour=18, minute=0, second=0)

    while current + timedelta(minutes=duration_min) <= end_of_day:
        slot_end = current + timedelta(minutes=duration_min)
        is_free = True
        for b in busy:
            busy_start = datetime.fromisoformat(b["start"].replace("Z", "+00:00")).replace(tzinfo=None) + timedelta(hours=-3)
            busy_end = datetime.fromisoformat(b["end"].replace("Z", "+00:00")).replace(tzinfo=None) + timedelta(hours=-3)
            if current < busy_end and slot_end > busy_start:
                is_free = False
                break
        if is_free:
            slots.append({
                "start": current.strftime("%H:%M"),
                "end": slot_end.strftime("%H:%M"),
            })
        current += timedelta(minutes=duration_min)

    return slots


async def create_event(calendar_id: str, summary: str, description: str, start_dt: datetime, end_dt: datetime):
    """Cria evento no Google Calendar."""
    service = get_service()
    event = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "America/Sao_Paulo",
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "America/Sao_Paulo",
        },
    }
    result = service.events().insert(calendarId=calendar_id, body=event).execute()
    print(f"✅ Evento criado: {result.get('htmlLink')}")
    return result


async def get_available_dates(calendar_id: str, days_ahead: int = 5):
    """Retorna os próximos dias com horários disponíveis."""
    available = []
    today = datetime.now()
    for i in range(1, days_ahead + 8):
        date = today + timedelta(days=i)
        if date.weekday() >= 5:  # Pula sábado e domingo
            continue
        date_str = date.strftime("%Y-%m-%d")
        slots = await get_available_slots(calendar_id, date_str)
        if slots:
            available.append({
                "date": date_str,
                "weekday": ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"][date.weekday()],
                "slots_count": len(slots),
                "first_slot": slots[0]["start"],
                "last_slot": slots[-1]["start"],
            })
        if len(available) >= days_ahead:
            break
    return available


async def detect_and_create_event(ai_response: str, conversation_history: list, lead_name: str, lead_phone: str, lead_course: str):
    """Detecta se houve agendamento na resposta e cria evento no Google Calendar."""
    from openai import AsyncOpenAI
    import json
    
    client = AsyncOpenAI()
    
    # Pedir ao GPT para extrair data/hora se houver agendamento
    try:
        extraction = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """Analise a resposta do assistente. Se ela confirma um agendamento de reunião/ligação, extraia a data e hora.
O ano atual é 2026. Responda APENAS com JSON, sem markdown:
{"agendado": true, "data": "YYYY-MM-DD", "hora": "HH:MM"} 
ou
{"agendado": false}"""},
                {"role": "user", "content": f"Resposta do assistente: {ai_response}"}
            ],
            max_completion_tokens=100,
        )
        
        result_text = extraction.choices[0].message.content.strip()
        result_text = result_text.replace("```json", "").replace("```", "").strip()
        result = json.loads(result_text)
        
        if result.get("agendado") and result.get("data") and result.get("hora"):
            from datetime import datetime, timedelta
            
            cal_id = CALENDARS["victoria"]["calendar_id"]
            start_dt = datetime.strptime(f"{result['data']} {result['hora']}", "%Y-%m-%d %H:%M")
            end_dt = start_dt + timedelta(minutes=30)
            
            summary = f"📞 Ligação - {lead_name} ({lead_course})"
            description = f"Lead: {lead_name}\nTelefone: {lead_phone}\nCurso: {lead_course}\nAgendado pela IA Nat"
            
            event = await create_event(cal_id, summary, description, start_dt, end_dt)
            print(f"�� Evento criado automaticamente: {result['data']} {result['hora']}")
            return event
    except Exception as e:
        print(f"⚠️ Erro ao detectar/criar evento: {e}")
    
    return None
