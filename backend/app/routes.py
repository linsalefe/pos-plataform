from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional

from app.database import get_db
from app.models import Channel, Contact, Message, Tag, contact_tags
from app.whatsapp import send_text_message, send_template_message

router = APIRouter(prefix="/api", tags=["api"])


# === Schemas ===

class SendTextRequest(BaseModel):
    to: str
    text: str
    channel_id: int = 1


class SendTemplateRequest(BaseModel):
    to: str
    template_name: str
    language: str = "pt_BR"
    channel_id: int = 1
    parameters: list = []
    contact_name: str = ""


class UpdateContactRequest(BaseModel):
    name: Optional[str] = None
    lead_status: Optional[str] = None
    notes: Optional[str] = None


class TagRequest(BaseModel):
    name: str
    color: str = "blue"


class ChannelRequest(BaseModel):
    name: str
    phone_number: str
    phone_number_id: str
    whatsapp_token: str
    waba_id: Optional[str] = None


# === Channels ===

@router.get("/channels")
async def list_channels(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.is_active == True).order_by(Channel.id))
    channels = result.scalars().all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "phone_number": c.phone_number,
            "phone_number_id": c.phone_number_id,
            "waba_id": c.waba_id,
            "is_active": c.is_active,
        }
        for c in channels
    ]


@router.post("/channels")
async def create_channel(req: ChannelRequest, db: AsyncSession = Depends(get_db)):
    channel = Channel(
        name=req.name,
        phone_number=req.phone_number,
        phone_number_id=req.phone_number_id,
        whatsapp_token=req.whatsapp_token,
        waba_id=req.waba_id,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return {"id": channel.id, "name": channel.name}


# === Dashboard ===

@router.get("/dashboard/stats")
async def dashboard_stats(channel_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    # Filtro base por canal
    contact_filter = [] if not channel_id else [Contact.channel_id == channel_id]
    message_filter = [] if not channel_id else [Message.channel_id == channel_id]

    total_contacts = await db.execute(
        select(func.count(Contact.id)).where(*contact_filter)
    )
    total_contacts = total_contacts.scalar()

    new_today = await db.execute(
        select(func.count(Contact.id)).where(Contact.created_at >= today_start, *contact_filter)
    )
    new_today = new_today.scalar()

    messages_today = await db.execute(
        select(func.count(Message.id)).where(Message.timestamp >= today_start, *message_filter)
    )
    messages_today = messages_today.scalar()

    inbound_today = await db.execute(
        select(func.count(Message.id)).where(
            Message.timestamp >= today_start, Message.direction == "inbound", *message_filter
        )
    )
    inbound_today = inbound_today.scalar()

    outbound_today = await db.execute(
        select(func.count(Message.id)).where(
            Message.timestamp >= today_start, Message.direction == "outbound", *message_filter
        )
    )
    outbound_today = outbound_today.scalar()

    messages_week = await db.execute(
        select(func.count(Message.id)).where(Message.timestamp >= week_start, *message_filter)
    )
    messages_week = messages_week.scalar()

    status_result = await db.execute(
        select(Contact.lead_status, func.count(Contact.id)).where(*contact_filter).group_by(Contact.lead_status)
    )
    status_counts = {row[0] or "novo": row[1] for row in status_result.all()}

    daily_messages = []
    for i in range(6, -1, -1):
        day = today_start - timedelta(days=i)
        next_day = day + timedelta(days=1)
        count = await db.execute(
            select(func.count(Message.id)).where(
                Message.timestamp >= day, Message.timestamp < next_day, *message_filter
            )
        )
        daily_messages.append({
            "date": day.strftime("%d/%m"),
            "day": day.strftime("%a"),
            "count": count.scalar()
        })

    return {
        "total_contacts": total_contacts,
        "new_today": new_today,
        "messages_today": messages_today,
        "inbound_today": inbound_today,
        "outbound_today": outbound_today,
        "messages_week": messages_week,
        "status_counts": status_counts,
        "daily_messages": daily_messages,
    }


# === Envio de Mensagens ===

async def get_channel(channel_id: int, db: AsyncSession) -> Channel:
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Canal não encontrado")
    return channel


@router.post("/send/text")
async def send_text(req: SendTextRequest, db: AsyncSession = Depends(get_db)):
    channel = await get_channel(req.channel_id, db)
    result = await send_text_message(req.to, req.text, channel.phone_number_id, channel.whatsapp_token)

    if "messages" in result:
        wa_id = result.get("contacts", [{}])[0].get("wa_id", req.to)

        contact_result = await db.execute(select(Contact).where(Contact.wa_id == wa_id))
        contact = contact_result.scalar_one_or_none()
        if not contact:
            contact = Contact(wa_id=wa_id, name="", channel_id=req.channel_id)
            db.add(contact)
            await db.flush()

        message = Message(
            wa_message_id=result["messages"][0]["id"],
            contact_wa_id=wa_id,
            channel_id=req.channel_id,
            direction="outbound",
            message_type="text",
            content=req.text,
            timestamp=datetime.now(),
            status="sent",
        )
        db.add(message)
        await db.commit()

    return result


@router.post("/send/template")
async def send_template(req: SendTemplateRequest, db: AsyncSession = Depends(get_db)):
    channel = await get_channel(req.channel_id, db)
    result = await send_template_message(req.to, req.template_name, req.language, channel.phone_number_id, channel.whatsapp_token, req.parameters if req.parameters else None)

    if "messages" in result:
        wa_id = result.get("contacts", [{}])[0].get("wa_id", req.to)

        contact_result = await db.execute(select(Contact).where(Contact.wa_id == wa_id))
        contact = contact_result.scalar_one_or_none()
        if not contact:
            db.add(Contact(wa_id=wa_id, name=req.contact_name or "", channel_id=req.channel_id))
            await db.flush()
        elif req.contact_name and not contact.name:
            contact.name = req.contact_name

        # Montar conteúdo legível
        content_text = f"template:{req.template_name}"
        if req.parameters:
            content_text = f"[Template] " + ", ".join(req.parameters)

        message = Message(
            wa_message_id=result["messages"][0]["id"],
            contact_wa_id=wa_id,
            channel_id=req.channel_id,
            direction="outbound",
            message_type="template",
            content=content_text,
            timestamp=datetime.now(),
            status="sent",
        )
        db.add(message)
        await db.commit()

    return result


# === Contatos ===

@router.get("/contacts")
async def list_contacts(channel_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    query = select(Contact).order_by(Contact.updated_at.desc())
    if channel_id:
        query = query.where(Contact.channel_id == channel_id)
    result = await db.execute(query)
    contacts = result.scalars().all()

    contacts_list = []
    for c in contacts:
        msg_result = await db.execute(
            select(Message).where(Message.contact_wa_id == c.wa_id).order_by(Message.timestamp.desc()).limit(1)
        )
        last_msg = msg_result.scalar_one_or_none()

        tag_result = await db.execute(
            select(Tag).join(contact_tags).where(contact_tags.c.contact_wa_id == c.wa_id)
        )
        tags = tag_result.scalars().all()

        unread_result = await db.execute(
            select(func.count(Message.id)).where(
                Message.contact_wa_id == c.wa_id, Message.direction == "inbound", Message.status == "received"
            )
        )
        unread = unread_result.scalar()

        contacts_list.append({
            "wa_id": c.wa_id,
            "name": c.name or c.wa_id,
            "lead_status": c.lead_status or "novo",
            "notes": c.notes,
            "channel_id": c.channel_id,
            "last_message": last_msg.content if last_msg else "",
            "last_message_time": last_msg.timestamp.isoformat() if last_msg else None,
            "direction": last_msg.direction if last_msg else None,
            "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in tags],
            "unread": unread,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })

    return contacts_list


@router.get("/contacts/{wa_id}")
async def get_contact(wa_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Contact).where(Contact.wa_id == wa_id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    tag_result = await db.execute(
        select(Tag).join(contact_tags).where(contact_tags.c.contact_wa_id == wa_id)
    )
    tags = tag_result.scalars().all()

    msg_count = await db.execute(select(func.count(Message.id)).where(Message.contact_wa_id == wa_id))

    return {
        "wa_id": contact.wa_id,
        "name": contact.name,
        "lead_status": contact.lead_status,
        "notes": contact.notes,
        "channel_id": contact.channel_id,
        "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in tags],
        "total_messages": msg_count.scalar(),
        "created_at": contact.created_at.isoformat() if contact.created_at else None,
    }


@router.patch("/contacts/{wa_id}")
async def update_contact(wa_id: str, req: UpdateContactRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Contact).where(Contact.wa_id == wa_id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    if req.name is not None:
        contact.name = req.name
    if req.lead_status is not None:
        contact.lead_status = req.lead_status
    if req.notes is not None:
        contact.notes = req.notes

    await db.commit()
    return {"status": "updated"}


@router.post("/contacts/{wa_id}/tags/{tag_id}")
async def add_tag_to_contact(wa_id: str, tag_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(contact_tags.insert().values(contact_wa_id=wa_id, tag_id=tag_id))
    await db.commit()
    return {"status": "tag added"}


@router.delete("/contacts/{wa_id}/tags/{tag_id}")
async def remove_tag_from_contact(wa_id: str, tag_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(
        contact_tags.delete().where(contact_tags.c.contact_wa_id == wa_id, contact_tags.c.tag_id == tag_id)
    )
    await db.commit()
    return {"status": "tag removed"}


# === Mensagens ===

@router.get("/contacts/{wa_id}/messages")
async def get_messages(wa_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Message).where(Message.contact_wa_id == wa_id).order_by(Message.timestamp.asc())
    )
    messages = result.scalars().all()

    return [
        {
            "id": m.id,
            "wa_message_id": m.wa_message_id,
            "direction": m.direction,
            "type": m.message_type,
            "content": m.content,
            "timestamp": m.timestamp.isoformat(),
            "status": m.status,
            "channel_id": m.channel_id,
        }
        for m in messages
    ]


# === Tags ===

@router.get("/tags")
async def list_tags(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tag).order_by(Tag.name))
    tags = result.scalars().all()
    return [{"id": t.id, "name": t.name, "color": t.color} for t in tags]


@router.post("/tags")
async def create_tag(req: TagRequest, db: AsyncSession = Depends(get_db)):
    tag = Tag(name=req.name, color=req.color)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return {"id": tag.id, "name": tag.name, "color": tag.color}


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tag).where(Tag.id == tag_id))
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag não encontrada")
    await db.delete(tag)
    await db.commit()
    return {"status": "deleted"}


@router.get("/channels/{channel_id}/templates")
async def list_templates(channel_id: int, db: AsyncSession = Depends(get_db)):
    import httpx
    channel = await get_channel(channel_id, db)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://graph.facebook.com/v22.0/{channel.waba_id}/message_templates",
            headers={"Authorization": f"Bearer {channel.whatsapp_token}"},
            params={"status": "APPROVED", "limit": 50},
        )
        data = response.json()

    templates = []
    for t in data.get("data", []):
        params = []
        for comp in t.get("components", []):
            if comp["type"] == "BODY":
                text = comp.get("text", "")
                import re
                matches = re.findall(r'\{\{(\d+)\}\}', text)
                params = [f"Variável {m}" for m in matches]
                body_text = text
        templates.append({
            "name": t["name"],
            "language": t["language"],
            "status": t["status"],
            "body": body_text if 'body_text' in dir() else "",
            "parameters": params,
        })
        if 'body_text' in dir():
            del body_text

    return templates
