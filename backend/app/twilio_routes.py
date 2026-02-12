from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from app.auth import get_current_user
import os
import httpx

router = APIRouter(prefix="/api/twilio", tags=["twilio"])

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_API_KEY_SID = os.getenv("TWILIO_API_KEY_SID")
TWILIO_API_KEY_SECRET = os.getenv("TWILIO_API_KEY_SECRET")
TWILIO_TWIML_APP_SID = os.getenv("TWILIO_TWIML_APP_SID")


@router.get("/token")
async def get_voice_token(current_user=Depends(get_current_user)):
    """Gera token de acesso para o Twilio Client (WebRTC)."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET]):
        raise HTTPException(status_code=500, detail="Credenciais Twilio não configuradas")

    import unicodedata
    clean_name = unicodedata.normalize('NFKD', current_user.name).encode('ascii', 'ignore').decode('ascii')
    identity = f"user_{current_user.id}_{clean_name.replace(' ', '_')}"

    token = AccessToken(
        TWILIO_ACCOUNT_SID,
        TWILIO_API_KEY_SID,
        TWILIO_API_KEY_SECRET,
        identity=identity,
        ttl=3600,
    )

    voice_grant = VoiceGrant(
        outgoing_application_sid=TWILIO_TWIML_APP_SID,
        incoming_allow=True,
    )
    token.add_grant(voice_grant)

    jwt_token = token.to_jwt()
    if isinstance(jwt_token, bytes):
        jwt_token = jwt_token.decode("utf-8")

    return {
        "token": jwt_token,
        "identity": identity,
    }


TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")


class CallRequest(BaseModel):
    to: str  # Número destino: +5511999999999


@router.post("/call")
async def make_call(data: CallRequest, current_user=Depends(get_current_user)):
    """Inicia uma ligação de saída via Twilio."""
    from twilio.rest import Client

    if not TWILIO_PHONE_NUMBER:
        raise HTTPException(status_code=500, detail="Número Twilio não configurado")

    client = Client(TWILIO_ACCOUNT_SID, os.getenv("TWILIO_AUTH_TOKEN"))

    # Formatar número
    to_number = data.to.strip()
    if not to_number.startswith("+"):
        to_number = f"+{to_number}"

    import unicodedata
    clean_name = unicodedata.normalize('NFKD', current_user.name).encode('ascii', 'ignore').decode('ascii')
    identity = f"user_{current_user.id}_{clean_name.replace(' ', '_')}"

    call = client.calls.create(
        to=to_number,
        from_=TWILIO_PHONE_NUMBER,
        url=f"https://hub.cenatdata.online/api/twilio/voice-outbound?identity={identity}",
        record=True,
        recording_status_callback="https://hub.cenatdata.online/api/twilio/recording-status",
        status_callback="https://hub.cenatdata.online/api/twilio/call-status",
        status_callback_event=["initiated", "ringing", "answered", "completed"],
    )

    return {"call_sid": call.sid, "status": call.status}


@router.post("/voice")
async def voice_twiml(request: "Request"):
    """TwiML para chamadas do browser (WebRTC). Chamado pelo TwiML App."""
    from starlette.requests import Request as StarletteRequest
    from twilio.twiml.voice_response import VoiceResponse, Dial

    form = await request.form()
    to = form.get("To", "")

    response = VoiceResponse()

    if to and to.startswith("+"):
        # Chamada de saída: browser -> telefone
        dial = Dial(
            caller_id=TWILIO_PHONE_NUMBER,
            record="record-from-answer",
            recording_status_callback="https://hub.cenatdata.online/api/twilio/recording-status",
        )
        dial.number(
            to,
            status_callback="https://hub.cenatdata.online/api/twilio/call-status",
            status_callback_event="initiated ringing answered completed",
        )
        response.append(dial)
    elif to:
        # Chamada para um client (browser)
        dial = Dial()
        dial.client(to)
        response.append(dial)
    else:
        response.say("Nenhum destino informado.", language="pt-BR")

    return Response(content=str(response), media_type="application/xml")


@router.post("/voice-outbound")
async def voice_outbound_twiml(request: "Request"):
    """TwiML para chamadas de saída via API (conecta o atendente ao destino)."""
    from twilio.twiml.voice_response import VoiceResponse, Dial

    form = await request.form()
    identity = request.query_params.get("identity", "")

    response = VoiceResponse()
    dial = Dial()
    dial.client(identity)
    response.append(dial)

    return Response(content=str(response), media_type="application/xml")


@router.post("/call-status")
async def call_status_webhook(request: Request):
    """Webhook que recebe atualizações de status das ligações."""
    from app.database import async_session
    from app.models import CallLog
    from sqlalchemy import select

    form = await request.form()
    call_sid = form.get("CallSid", "")
    status = form.get("CallStatus", "")
    duration = form.get("CallDuration", "0")
    from_number = form.get("From", "")
    to_number = form.get("To", "")
    direction = form.get("Direction", "")

    async with async_session() as db:
        result = await db.execute(select(CallLog).where(CallLog.call_sid == call_sid))
        call_log = result.scalar_one_or_none()

        if call_log:
            call_log.status = status
            call_log.duration = int(duration) if duration else 0
        else:
            call_log = CallLog(
                call_sid=call_sid,
                from_number=from_number,
                to_number=to_number,
                direction="inbound" if "inbound" in direction.lower() else "outbound",
                status=status,
                duration=int(duration) if duration else 0,
            )
            db.add(call_log)

        await db.commit()

    # Quando ligação finaliza, posta no Exact Spotter
        if status == "completed" and call_log:
            try:
                await post_call_to_exact_spotter(call_log)
            except Exception as e:
                print(f"❌ Erro ao postar no Exact: {e}")

    print(f"📞 Call {call_sid}: {status} ({duration}s)")
    return Response(content="", media_type="application/xml")

@router.post("/recording-status")
async def recording_status_webhook(request: Request):
    """Webhook que recebe URL da gravação quando finalizada."""
    from app.database import async_session
    from app.models import CallLog
    from app.google_drive import upload_recording_to_drive
    from sqlalchemy import select

    form = await request.form()
    call_sid = form.get("CallSid", "")
    recording_sid = form.get("RecordingSid", "")
    recording_url = form.get("RecordingUrl", "")
    recording_status = form.get("RecordingStatus", "")

    if recording_status == "completed" and recording_url:
        mp3_url = f"{recording_url}.mp3"

        async with async_session() as db:
            result = await db.execute(select(CallLog).where(CallLog.call_sid == call_sid))
            call_log = result.scalar_one_or_none()

            if call_log:
                call_log.recording_sid = recording_sid
                call_log.recording_url = mp3_url

                # Upload ao Google Drive
                try:
                    drive_link = await upload_recording_to_drive(
                        recording_url=mp3_url,
                        call_sid=call_sid,
                        from_number=call_log.from_number,
                        to_number=call_log.to_number,
                        user_name=call_log.user_name or "Geral",
                        duration=call_log.duration or 0,
                    )
                    if drive_link:
                        call_log.drive_file_url = drive_link
                except Exception as e:
                    print(f"❌ Erro upload Drive: {e}")

                await db.commit()

        print(f"🎙️ Gravação salva: {call_sid} -> {mp3_url}")

    return Response(content="", media_type="application/xml")


@router.get("/call-logs")
async def list_call_logs(
    limit: int = 50,
    offset: int = 0,
    current_user=Depends(get_current_user),
):
    """Lista histórico de ligações."""
    from app.database import async_session
    from app.models import CallLog
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(
            select(CallLog)
            .order_by(CallLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        logs = result.scalars().all()

        return [
            {
                "id": log.id,
                "call_sid": log.call_sid,
                "from_number": log.from_number,
                "to_number": log.to_number,
                "direction": log.direction,
                "status": log.status,
                "duration": log.duration,
                "recording_url": log.recording_url,
                "drive_file_url": log.drive_file_url,
                "user_name": log.user_name,
                "contact_name": log.contact_name,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ]


async def post_call_to_exact_spotter(call_log):
    """Posta resumo da ligação na timeline do Exact Spotter."""
    from app.database import async_session
    from app.models import Contact, ExactLead
    from sqlalchemy import select

    exact_token = os.getenv("EXACT_SPOTTER_TOKEN", "")
    if not exact_token:
        return

    # Buscar lead no Exact Spotter pelo telefone
    phone = call_log.to_number if call_log.direction == "outbound" else call_log.from_number
    phone_clean = phone.replace("+", "").replace(" ", "")

    async with async_session() as db:
        result = await db.execute(
            select(ExactLead).where(
                (ExactLead.phone1.contains(phone_clean[-8:])) |
                (ExactLead.phone2.contains(phone_clean[-8:]))
            )
        )
        lead = result.scalar_one_or_none()

    if not lead:
        print(f"⚠️ Lead não encontrado no Exact para telefone {phone}")
        return

    duration_min = f"{call_log.duration // 60}m{call_log.duration % 60:02d}s"
    drive_info = f"\n🔗 Gravação: {call_log.drive_file_url}" if call_log.drive_file_url else ""

    text = (
        f"📞 LIGAÇÃO VIA CENAT HUB\n"
        f"📅 Data: {call_log.created_at.strftime('%d/%m/%Y %H:%M') if call_log.created_at else 'N/A'}\n"
        f"📱 Direção: {'Saída' if call_log.direction == 'outbound' else 'Entrada'}\n"
        f"👤 Atendente: {call_log.user_name or 'N/A'}\n"
        f"⏱️ Duração: {duration_min}\n"
        f"📊 Status: {call_log.status}"
        f"{drive_info}"
    )

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                "https://api.exactspotter.com/v3/timelineAdd",
                headers={
                    "Content-Type": "application/json",
                    "token_exact": exact_token,
                },
                json={
                    "leadId": lead.exact_id,
                    "text": text,
                    "userId": 415875,
                },
            )
            print(f"📝 Exact Spotter timeline: {resp.status_code}")
        except Exception as e:
            print(f"❌ Erro ao postar no Exact: {e}")

@router.post("/voice-incoming")
async def voice_incoming_twiml(request: "Request"):
    """TwiML para chamadas recebidas no número Twilio. Toca no browser."""
    from twilio.twiml.voice_response import VoiceResponse, Dial
    
    response = VoiceResponse()
    response.say("Aguarde enquanto conectamos sua ligação.", language="pt-BR")
    
    dial = Dial(
        record="record-from-answer",
        recording_status_callback="https://hub.cenatdata.online/api/twilio/recording-status",
        timeout=30,
    )
    # Toca em todos os clients conectados (usuários logados)
    dial.client("user_1_Alefe_Lins")
    response.append(dial)
    
    # Se ninguém atender
    response.say("Desculpe, ninguém está disponível no momento. Tente novamente mais tarde.", language="pt-BR")
    
    return Response(content=str(response), media_type="application/xml")

@router.get("/recording/{recording_sid}")
async def stream_recording(recording_sid: str):
    """Proxy para servir gravações sem expor credenciais Twilio."""
    import httpx
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Recordings/{recording_sid}.mp3"
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, auth=(account_sid, auth_token), follow_redirects=True)
        if resp.status_code != 200:
            return Response(content="Gravação não encontrada", status_code=404)
        return Response(
            content=resp.content,
            media_type="audio/mpeg",
            headers={"Content-Disposition": f"inline; filename={recording_sid}.mp3"}
        )
