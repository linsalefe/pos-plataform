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
    from sqlalchemy import select
    import httpx, os

    form = await request.form()
    print(f"📥 Recording webhook: CallSid={form.get('CallSid')} RecordingSid={form.get('RecordingSid')} Status={form.get('RecordingStatus')}")
    call_sid = form.get("CallSid", "")
    recording_sid = form.get("RecordingSid", "")
    recording_url = form.get("RecordingUrl", "")
    recording_status = form.get("RecordingStatus", "")

    if recording_status == "completed" and recording_url:
        mp3_url = f"{recording_url}.mp3"

        recordings_dir = "/home/ubuntu/pos-plataform/recordings"
        os.makedirs(recordings_dir, exist_ok=True)
        local_path = f"{recordings_dir}/{call_sid}.mp3"

        try:
            account_sid = os.getenv("TWILIO_ACCOUNT_SID")
            auth_token = os.getenv("TWILIO_AUTH_TOKEN")
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    mp3_url,
                    auth=(account_sid, auth_token),
                    follow_redirects=True,
                    timeout=60,
                )
                if resp.status_code == 200:
                    with open(local_path, "wb") as f:
                        f.write(resp.content)
                    print(f"✅ Gravação salva em {local_path}")
                else:
                    print(f"❌ Erro ao baixar gravação: {resp.status_code}")
                    local_path = None
        except Exception as e:
            print(f"❌ Erro ao salvar gravação: {e}")
            local_path = None

        async with async_session() as db:
            result = await db.execute(select(CallLog).where(CallLog.call_sid == call_sid))
            call_log = result.scalar_one_or_none()

            # Fallback: match por tempo
            if not call_log:
                try:
                    import httpx as _httpx
                    from datetime import datetime as _dt
                    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
                    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
                    async with _httpx.AsyncClient() as _client:
                        call_resp = await _client.get(
                            f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls/{call_sid}.json",
                            auth=(account_sid, auth_token),
                        )
                        call_data = call_resp.json()
                        date_created = call_data.get("date_created", "")
                        dt = _dt.strptime(date_created, "%a, %d %b %Y %H:%M:%S +0000")
                        result2 = await db.execute(
                            select(CallLog).where(
                                CallLog.created_at.between(
                                    dt.replace(second=max(0, dt.second - 30)),
                                    dt.replace(second=min(59, dt.second + 60))
                                )
                            ).order_by(CallLog.created_at.desc()).limit(1)
                        )
                        call_log = result2.scalar_one_or_none()
                        if call_log:
                            print(f"🔁 Match por tempo: {call_sid} -> {call_log.call_sid}")
                except Exception as e:
                    print(f"❌ Erro no fallback: {e}")

            if call_log:
                call_log.recording_sid = recording_sid
                call_log.recording_url = mp3_url
                if local_path:
                    call_log.local_recording_path = local_path
                    call_log.transcription_status = "pending"
                await db.commit()
                print(f"✅ CallLog atualizado: {call_log.call_sid}")
            else:
                print(f"⚠️ CallLog não encontrado para SID: {call_sid}")

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
        query = select(CallLog).order_by(CallLog.created_at.desc())
        # SDR só vê suas próprias ligações
        if current_user.role != "admin":
            query = query.where(CallLog.user_id == current_user.id)
        result = await db.execute(query.limit(limit).offset(offset))
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
                "local_recording_path": log.local_recording_path,
                "drive_file_url": log.drive_file_url,
                "user_name": log.user_name,
                "contact_name": log.contact_name,
                "transcription_status": log.transcription_status,
                "transcription": log.transcription,
                "transcription_insights": log.transcription_insights,
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

@router.get("/recording/{call_sid}")
async def stream_recording(call_sid: str):
    """Serve gravação salva localmente."""
    from fastapi.responses import FileResponse
    from app.database import async_session
    from app.models import CallLog
    from sqlalchemy import select
    import os

    async with async_session() as db:
        result = await db.execute(select(CallLog).where(CallLog.call_sid == call_sid))
        call_log = result.scalar_one_or_none()

    local_path = call_log.local_recording_path if call_log else None

    # Fallback: tenta pelo nome direto
    if not local_path:
        direct_path = f"/home/ubuntu/pos-plataform/recordings/{call_sid}.mp3"
        if os.path.exists(direct_path):
            local_path = direct_path

    if not local_path or not os.path.exists(local_path):
        return Response(content="Gravação não encontrada", status_code=404)

    return FileResponse(
        path=local_path,
        media_type="audio/mpeg",
        filename=f"{call_sid}.mp3",
    )

@router.delete("/recording/{call_sid}")
async def delete_recording(call_sid: str, current_user=Depends(get_current_user)):
    """Apaga gravação do disco e limpa o campo no banco."""
    from app.database import async_session
    from app.models import CallLog
    from sqlalchemy import select
    import os

    async with async_session() as db:
        result = await db.execute(select(CallLog).where(CallLog.call_sid == call_sid))
        call_log = result.scalar_one_or_none()

        if not call_log:
            raise HTTPException(status_code=404, detail="Ligação não encontrada")

        local_path = call_log.local_recording_path

        if local_path and os.path.exists(local_path):
            os.remove(local_path)
            print(f"🗑️ Gravação apagada: {local_path}")

        call_log.local_recording_path = None
        call_log.transcription_status = None
        await db.commit()

    return {"success": True}

@router.post("/transcribe/{call_id}")
async def transcribe_call(call_id: int, current_user=Depends(get_current_user)):
    """Aciona transcrição e geração de insights de uma ligação."""
    from app.database import async_session
    from app.models import CallLog
    from app.transcription import transcribe_audio, generate_insights
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(select(CallLog).where(CallLog.id == call_id))
        call_log = result.scalar_one_or_none()

        if not call_log:
            raise HTTPException(status_code=404, detail="Ligação não encontrada")

        if not call_log.local_recording_path:
            raise HTTPException(status_code=400, detail="Gravação não disponível")

        call_log.transcription_status = "processing"
        await db.commit()

    try:
        transcription = await transcribe_audio(call_log.local_recording_path)
        insights = await generate_insights(
            transcription=transcription,
            duration=call_log.duration or 0,
            user_name=call_log.user_name or "N/A",
        )

        async with async_session() as db:
            result = await db.execute(select(CallLog).where(CallLog.id == call_id))
            call_log = result.scalar_one_or_none()
            call_log.transcription = transcription
            call_log.transcription_insights = insights
            call_log.transcription_status = "done"
            await db.commit()

        return {"status": "done", "transcription": transcription, "insights": insights}

    except Exception as e:
        async with async_session() as db:
            result = await db.execute(select(CallLog).where(CallLog.id == call_id))
            call_log = result.scalar_one_or_none()
            if call_log:
                call_log.transcription_status = "error"
                await db.commit()
        raise HTTPException(status_code=500, detail=str(e))