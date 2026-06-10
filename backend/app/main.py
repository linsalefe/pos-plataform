from fastapi import FastAPI, Request, Query, HTTPException, Depends
from app.ai_engine import generate_ai_response
from app.whatsapp import send_text_message
from app.ai_routes import router as ai_router
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from dotenv import load_dotenv
from app.twilio_routes import router as twilio_router
from datetime import datetime, timezone, timedelta
from app.kanban_routes import router as kanban_router
from app.calendar_routes import router as calendar_router
from contextlib import asynccontextmanager
import os
import httpx
import asyncio

SP_TZ = timezone(timedelta(hours=-3))

from app.database import get_db, async_session
from app.models import Channel, Contact, Message
from app.routes import router
from app.auth_routes import router as auth_router
from app.exact_routes import router as exact_router
from app.exact_spotter import sync_exact_leads

load_dotenv()


async def sync_job():
    """Job que sincroniza leads do Exact Spotter a cada 10 minutos."""
    while True:
        await asyncio.sleep(600)  # 10 minutos
        try:
            async with async_session() as db:
                result = await sync_exact_leads(db)
                print(f"🔄 Sync Exact Spotter: {result}")
        except Exception as e:
            print(f"❌ Erro no sync Exact Spotter: {e}")

async def cleanup_recordings_job():
    """Job que exclui gravações com +90 dias a cada 24 horas."""
    while True:
        await asyncio.sleep(86400)  # 24 horas
        try:
            from app.google_drive import delete_old_recordings
            delete_old_recordings(days=90)
            print("🗑️ Limpeza de gravações antigas concluída")
        except Exception as e:
            print(f"❌ Erro na limpeza de gravações: {e}")


async def window_alerts_job():
    """Alerta o SDR dono quando o lead aguarda resposta e cruza 1h/3h/5h/20h (janela de 24h)."""
    from sqlalchemy import text as sa_text
    from app.models import Notification
    thresholds = [(1, "window_1h", "1h"), (3, "window_3h", "3h"), (5, "window_5h", "5h"), (20, "window_20h", "20h")]
    while True:
        await asyncio.sleep(300)
        try:
            async with async_session() as db:
                now = datetime.now(SP_TZ).replace(tzinfo=None)
                cutoff = now - timedelta(hours=24)
                rows = (await db.execute(sa_text("""
                    SELECT c.wa_id, c.name, c.assigned_to,
                           lm.wa_message_id AS ref, lm.timestamp AS ts
                    FROM contacts c
                    JOIN LATERAL (
                        SELECT wa_message_id, timestamp, direction
                        FROM messages WHERE contact_wa_id = c.wa_id
                        ORDER BY timestamp DESC LIMIT 1
                    ) lm ON true
                    WHERE c.assigned_to IS NOT NULL
                      AND lm.direction = 'inbound'
                      AND lm.timestamp >= :cutoff
                """), {"cutoff": cutoff})).fetchall()
                created = 0
                for r in rows:
                    elapsed_h = (now - r.ts).total_seconds() / 3600.0
                    for hours, ntype, label in thresholds:
                        if elapsed_h >= hours:
                            exists = (await db.execute(sa_text(
                                "SELECT 1 FROM notifications WHERE contact_wa_id = :wa AND type = :t AND ref = :ref LIMIT 1"
                            ), {"wa": r.wa_id, "t": ntype, "ref": r.ref})).first()
                            if not exists:
                                db.add(Notification(
                                    user_id=r.assigned_to,
                                    contact_wa_id=r.wa_id,
                                    type=ntype,
                                    ref=r.ref,
                                    title=f"Lead aguardando há {label}",
                                    body=f"{r.name or r.wa_id} sem resposta — janela de 24h correndo.",
                                ))
                                created += 1
                await db.commit()
                if created:
                    print(f"🔔 Alertas de janela criados: {created}")
        except Exception as e:
            print(f"❌ Erro no window_alerts_job: {e}")


async def scheduled_messages_job():
    """Dispara agendamentos de template cuja hora chegou (a cada 60s)."""
    from sqlalchemy import select as sa_select
    from app.models import ScheduledMessage
    import json
    while True:
        await asyncio.sleep(60)
        try:
            async with async_session() as db:
                now = datetime.now(SP_TZ).replace(tzinfo=None)
                due = (await db.execute(
                    sa_select(ScheduledMessage).where(
                        ScheduledMessage.status == "pending",
                        ScheduledMessage.scheduled_at <= now,
                    )
                )).scalars().all()
                for sm in due:
                    sm.status = "sending"
                    await db.commit()
                    try:
                        from app.exact_routes import bulk_send_template
                        payload = {
                            "template_name": sm.template_name,
                            "language": sm.language,
                            "channel_id": sm.channel_id,
                            "lead_ids": json.loads(sm.lead_ids) if sm.lead_ids else [],
                            "param_mappings": json.loads(sm.param_mappings) if sm.param_mappings else None,
                        }
                        result = await bulk_send_template(payload, db)
                        sm.status = "sent"
                        sm.sent_at = datetime.now(SP_TZ).replace(tzinfo=None)
                        sm.result = json.dumps(result)
                    except Exception as e:
                        sm.status = "error"
                        sm.result = json.dumps({"error": str(e)})
                    await db.commit()
                if due:
                    print(f"📨 Agendamentos processados: {len(due)}")
        except Exception as e:
            print(f"❌ Erro no scheduled_messages_job: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: inicia o job de sync
    task = asyncio.create_task(sync_job())
    cleanup_task = asyncio.create_task(cleanup_recordings_job())
    window_task = asyncio.create_task(window_alerts_job())
    scheduled_task = asyncio.create_task(scheduled_messages_job())
    print("✅ Sync Exact Spotter agendado (a cada 10 min)")
    print("✅ Alertas de janela 24h agendados (a cada 5 min)")
    print("✅ Agendamento de templates ativo (checa a cada 60s)")
    yield
    # Shutdown: cancela o job
    task.cancel()
    cleanup_task.cancel()
    window_task.cancel()
    scheduled_task.cancel()


app = FastAPI(title="Cenat WhatsApp API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "https://hub.cenatdata.online"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(auth_router)
app.include_router(exact_router)
app.include_router(ai_router)
app.include_router(kanban_router)
app.include_router(calendar_router)
VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN")
app.include_router(twilio_router)


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_token == VERIFY_TOKEN:
        print("✅ Webhook verificado com sucesso!")
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Token inválido")


@app.post("/webhook")
async def receive_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()

    # Relay para CS Platform
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post("https://pedagogico.cenatdata.online/api/webhook/whatsapp", json=body)
    except Exception as e:
        print(f"❌ Relay CS falhou: {e}")

    if body.get("object") != "whatsapp_business_account":
        return {"status": "ignored"}

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id")

            # Identificar canal
            channel_id = None
            if phone_number_id:
                result = await db.execute(
                    select(Channel).where(Channel.phone_number_id == phone_number_id)
                )
                channel = result.scalar_one_or_none()
                if channel:
                    channel_id = channel.id

            # Salvar contato
            for contact_data in value.get("contacts", []):
                wa_id = contact_data["wa_id"]
                name = contact_data.get("profile", {}).get("name", "")

                result = await db.execute(select(Contact).where(Contact.wa_id == wa_id))
                contact = result.scalar_one_or_none()

                if not contact:
                    contact = Contact(wa_id=wa_id, name=name, channel_id=channel_id)
                    db.add(contact)
                else:
                    contact.name = name
                    if not contact.channel_id and channel_id:
                        contact.channel_id = channel_id

            # Salvar mensagens
            for msg in value.get("messages", []):
                wa_message_id = msg["id"]

                result = await db.execute(select(Message).where(Message.wa_message_id == wa_message_id))
                if result.scalar_one_or_none():
                    continue

                msg_type = msg["type"]
                content = ""

                if msg_type == "text":
                    content = msg["text"]["body"]
                elif msg_type == "image":
                    media = msg.get("image", {})
                    content = f'media:{media.get("id", "")}|{media.get("mime_type", "image/jpeg")}|{media.get("caption", "")}'
                elif msg_type == "audio":
                    media = msg.get("audio", {})
                    content = f'media:{media.get("id", "")}|{media.get("mime_type", "audio/ogg")}|'
                elif msg_type == "video":
                    media = msg.get("video", {})
                    content = f'media:{media.get("id", "")}|{media.get("mime_type", "video/mp4")}|{media.get("caption", "")}'
                elif msg_type == "document":
                    media = msg.get("document", {})
                    content = f'media:{media.get("id", "")}|{media.get("mime_type", "")}|{media.get("filename", "documento")}'
                elif msg_type == "sticker":
                    media = msg.get("sticker", {})
                    content = f'media:{media.get("id", "")}|{media.get("mime_type", "image/webp")}|'

                message = Message(
                    wa_message_id=wa_message_id,
                    contact_wa_id=msg["from"],
                    channel_id=channel_id,
                    direction="inbound",
                    message_type=msg_type,
                    content=content,
                    timestamp=datetime.fromtimestamp(int(msg["timestamp"]), tz=SP_TZ).replace(tzinfo=None),
                    status="received",
                )
                db.add(message)

                # Notificação de nova mensagem para o SDR dono (se houver)
                owner_result = await db.execute(select(Contact.assigned_to, Contact.name).where(Contact.wa_id == msg["from"]))
                owner_row = owner_result.first()
                if owner_row and owner_row[0] is not None:
                    from app.models import Notification
                    preview = "[mídia]" if (content or "").startswith("media:") else (content or "")[:80]
                    db.add(Notification(
                        user_id=owner_row[0],
                        contact_wa_id=msg["from"],
                        type="new_message",
                        ref=wa_message_id,
                        title=f"Nova mensagem de {owner_row[1] or msg['from']}",
                        body=preview,
                    ))

            # Atualizar status de mensagens enviadas
            for status_update in value.get("statuses", []):
                wa_message_id = status_update["id"]
                new_status = status_update["status"]

                result = await db.execute(select(Message).where(Message.wa_message_id == wa_message_id))
                existing = result.scalar_one_or_none()
                if existing:
                    existing.status = new_status

            # === AGENTE IA: DESATIVADO TEMPORARIAMENTE ===
            # for msg in value.get("messages", []):
            #     sender_wa_id = msg["from"]
            #     msg_type = msg["type"]
            #
            #     # Só responde mensagens de texto
            #     if msg_type != "text":
            #         continue
            #
            #     # Buscar contato para verificar se IA está ativa
            #     contact_result = await db.execute(
            #         select(Contact).where(Contact.wa_id == sender_wa_id)
            #     )
            #     ai_contact = contact_result.scalar_one_or_none()
            #
            #     if not ai_contact or not ai_contact.ai_active or not channel_id:
            #         continue
            #
            #     # Buscar canal para enviar resposta
            #     channel_result = await db.execute(
            #         select(Channel).where(Channel.id == channel_id)
            #     )
            #     ai_channel = channel_result.scalar_one_or_none()
            #     if not ai_channel:
            #         continue
            #
            #     # Gerar resposta da IA
            #     user_text = msg.get("text", {}).get("body", "")
            #     ai_response = await generate_ai_response(
            #         contact_wa_id=sender_wa_id,
            #         user_message=user_text,
            #         channel_id=channel_id,
            #         db=db,
            #     )
            #
            #     if ai_response:
            #         # Enviar via WhatsApp
            #         send_result = await send_text_message(
            #             to=sender_wa_id,
            #             text=ai_response,
            #             phone_number_id=ai_channel.phone_number_id,
            #             token=ai_channel.whatsapp_token,
            #         )
            #
            #         # Salvar mensagem da IA no banco
            #         if "messages" in send_result:
            #             ai_msg = Message(
            #                 wa_message_id=send_result["messages"][0]["id"],
            #                 contact_wa_id=sender_wa_id,
            #                 channel_id=channel_id,
            #                 direction="outbound",
            #                 message_type="text",
            #                 content=ai_response,
            #                 timestamp=datetime.now(SP_TZ).replace(tzinfo=None),
            #                 status="sent",
            #             )
            #             db.add(ai_msg)
            #
            #             # Atualizar contador no summary do kanban
            #             from app.models import AIConversationSummary
            #             summary_result = await db.execute(
            #                 select(AIConversationSummary).where(
            #                     AIConversationSummary.contact_wa_id == sender_wa_id,
            #                     AIConversationSummary.status == "em_atendimento_ia",
            #                 )
            #             )
            #             summary = summary_result.scalar_one_or_none()
            #             if summary:
            #                 summary.ai_messages_count = (summary.ai_messages_count or 0) + 1
            #
            #         print(f"🤖 IA respondeu para {sender_wa_id}")

            await db.commit()
            print(f"💾 Dados salvos no banco!")

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "online"}