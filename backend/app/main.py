from fastapi import FastAPI, Request, Query, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
import os
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: inicia o job de sync
    task = asyncio.create_task(sync_job())
    print("✅ Sync Exact Spotter agendado (a cada 10 min)")
    yield
    # Shutdown: cancela o job
    task.cancel()


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

VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN")


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

            # Atualizar status de mensagens enviadas
            for status_update in value.get("statuses", []):
                wa_message_id = status_update["id"]
                new_status = status_update["status"]

                result = await db.execute(select(Message).where(Message.wa_message_id == wa_message_id))
                existing = result.scalar_one_or_none()
                if existing:
                    existing.status = new_status

            await db.commit()
            print(f"💾 Dados salvos no banco!")

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "online"}
