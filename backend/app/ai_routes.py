"""
Rotas da IA: config do agente, upload de documentos RAG, toggle por contato.
"""
import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models import AIConfig, KnowledgeDocument, Contact, AIConversationSummary
from app.ai_engine import generate_embedding, split_into_chunks, count_tokens

router = APIRouter(prefix="/api/ai", tags=["ai"])


# === Schemas ===

class AIConfigUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[str] = None
    max_tokens: Optional[int] = None


class ToggleAIRequest(BaseModel):
    ai_active: bool


# === Config da IA por Canal ===

@router.get("/config/{channel_id}")
async def get_ai_config(channel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AIConfig).where(AIConfig.channel_id == channel_id)
    )
    config = result.scalar_one_or_none()

    if not config:
        # Detectar agendamento e criar evento no Google Calendar
        try:
            from app.google_calendar import detect_and_create_event
            await detect_and_create_event(
                ai_response,
                req.conversation_history,
                req.lead_name or "Lead",
                "teste",
                req.lead_course or "Não informado",
            )
        except Exception as e:
            print(f"⚠️ Erro ao criar evento: {e}")
        return {
            "channel_id": channel_id,
            "is_enabled": False,
            "system_prompt": "",
            "model": "gpt-5",
            "temperature": "0.7",
            "max_tokens": 500,
        }

    return {
        "id": config.id,
        "channel_id": config.channel_id,
        "is_enabled": config.is_enabled,
        "system_prompt": config.system_prompt or "",
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }


@router.put("/config/{channel_id}")
async def update_ai_config(channel_id: int, req: AIConfigUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AIConfig).where(AIConfig.channel_id == channel_id)
    )
    config = result.scalar_one_or_none()

    if not config:
        config = AIConfig(channel_id=channel_id)
        db.add(config)

    if req.is_enabled is not None:
        config.is_enabled = req.is_enabled
    if req.system_prompt is not None:
        config.system_prompt = req.system_prompt
    if req.model is not None:
        config.model = req.model
    if req.temperature is not None:
        config.temperature = req.temperature
    if req.max_tokens is not None:
        config.max_tokens = req.max_tokens

    await db.commit()
    return {"status": "updated"}


# === Toggle IA por Contato ===

@router.patch("/contacts/{wa_id}/toggle")
async def toggle_contact_ai(wa_id: str, req: ToggleAIRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Contact).where(Contact.wa_id == wa_id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    contact.ai_active = req.ai_active

    # Se desligou a IA, atualizar o summary do kanban
    if not req.ai_active:
        summary_result = await db.execute(
            select(AIConversationSummary).where(
                AIConversationSummary.contact_wa_id == wa_id,
                AIConversationSummary.status == "em_atendimento_ia",
            )
        )
        summary = summary_result.scalar_one_or_none()
        if summary:
            summary.status = "aguardando_humano"
            # Salvar anotação na Exact Spotter
            from app.ai_engine import save_annotation_to_exact
            await save_annotation_to_exact(wa_id, summary.channel_id, db)
            summary.human_took_over = True

    await db.commit()
    return {"wa_id": wa_id, "ai_active": req.ai_active}


# === Documentos do RAG ===

@router.get("/documents/{channel_id}")
async def list_documents(channel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            KnowledgeDocument.title,
            func.count(KnowledgeDocument.id).label("chunks"),
            func.sum(KnowledgeDocument.token_count).label("total_tokens"),
            func.min(KnowledgeDocument.created_at).label("created_at"),
        )
        .where(KnowledgeDocument.channel_id == channel_id)
        .group_by(KnowledgeDocument.title)
        .order_by(func.min(KnowledgeDocument.created_at).desc())
    )
    docs = result.all()

    return [
        {
            "title": d.title,
            "chunks": d.chunks,
            "total_tokens": d.total_tokens or 0,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


@router.post("/documents/{channel_id}")
async def upload_document(
    channel_id: int,
    title: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    # Ler conteúdo do arquivo
    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Arquivo deve ser texto (.txt, .md, .csv)")

    if not content.strip():
        raise HTTPException(status_code=400, detail="Arquivo vazio")

    # Dividir em chunks
    chunks = split_into_chunks(content, title)

    if not chunks:
        raise HTTPException(status_code=400, detail="Não foi possível processar o documento")

    # Gerar embeddings e salvar cada chunk
    saved = 0
    for chunk in chunks:
        try:
            embedding = await generate_embedding(chunk["content"])
            doc = KnowledgeDocument(
                channel_id=channel_id,
                title=chunk["title"],
                content=chunk["content"],
                embedding=json.dumps(embedding),
                chunk_index=chunk["chunk_index"],
                token_count=chunk["token_count"],
            )
            db.add(doc)
            saved += 1
        except Exception as e:
            print(f"❌ Erro ao processar chunk {chunk['chunk_index']}: {e}")
            continue

    await db.commit()

    return {
        "title": title,
        "chunks_saved": saved,
        "total_tokens": sum(c["token_count"] for c in chunks),
    }


@router.delete("/documents/{channel_id}/{title}")
async def delete_document(channel_id: int, title: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.channel_id == channel_id,
            KnowledgeDocument.title == title,
        )
    )
    docs = result.scalars().all()

    if not docs:
        raise HTTPException(status_code=404, detail="Documento não encontrado")

    for doc in docs:
        await db.delete(doc)

    await db.commit()
    return {"status": "deleted", "chunks_removed": len(docs)}
class TestChatRequest(BaseModel):
    message: str
    channel_id: int = 2
    conversation_history: list = []
    lead_name: str = ""
    lead_course: str = ""

@router.post("/test-chat")
async def test_chat(req: TestChatRequest, db: AsyncSession = Depends(get_db)):
    """Endpoint de teste: simula conversa com a IA sem enviar WhatsApp."""
    from app.ai_engine import search_knowledge, DEFAULT_SYSTEM_PROMPT
    from openai import AsyncOpenAI
    import os

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Buscar config do canal
    result = await db.execute(
        select(AIConfig).where(AIConfig.channel_id == req.channel_id)
    )
    ai_config = result.scalar_one_or_none()

    system_prompt = ai_config.system_prompt if ai_config and ai_config.system_prompt else DEFAULT_SYSTEM_PROMPT
    model = ai_config.model if ai_config else "gpt-5"
    temperature = float(ai_config.temperature) if ai_config else 0.7
    max_tokens = ai_config.max_tokens if ai_config else 1000

    # RAG
    relevant_docs = await search_knowledge(req.message, req.channel_id, db)
    context = ""
    if relevant_docs:
        context = "\n\n---\nINFORMAÇÕES DA BASE DE CONHECIMENTO:\n"
        for doc in relevant_docs:
            context += f"\n[{doc['title']}] (relevância: {doc['score']:.2f})\n{doc['content']}\n"
        context += "---\n"

    # Montar mensagens
    lead_info = ""
    if req.lead_name or req.lead_course:
        lead_info = "\n\nINFORMAÇÕES DO LEAD ATUAL:\n"
        if req.lead_name:
            lead_info += f"- Nome: {req.lead_name}\n"
        if req.lead_course:
            lead_info += f"- Curso de interesse: {req.lead_course}\n"
    # Buscar disponibilidade do calendário
    calendar_info = ""
    try:
        from app.google_calendar import get_available_dates, get_available_slots, CALENDARS
        cal_id = CALENDARS["victoria"]["calendar_id"]
        dates = await get_available_dates(cal_id, days_ahead=3)
        if dates:
            calendar_info = "\n\nAGENDA DISPONÍVEL PARA LIGAÇÃO:\n"
            for d in dates:
                slots = await get_available_slots(cal_id, d["date"])
                horarios = ", ".join([s["start"] for s in slots[:6]])
                calendar_info += f"- {d['weekday']} {d['date']}: {horarios}\n"
            calendar_info += "\nIMPORTANTE: Só ofereça horários que estão nesta lista. Se o lead pedir um horário que não está disponível, informe que não há vaga e sugira os horários livres.\n"
    except Exception as e:
        print(f"⚠️ Erro ao buscar calendário: {e}")
    print(f"📅 CALENDAR_INFO: {calendar_info[:200] if calendar_info else VAZIO}")
    messages = [{"role": "system", "content": system_prompt + lead_info + calendar_info + context}]
    messages.extend(req.conversation_history)
    messages.append({"role": "user", "content": req.message})

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,

            max_completion_tokens=max_tokens,
        )
        
        ai_response = response.choices[0].message.content
        if not ai_response:
            messages.append({"role": "assistant", "content": ""})
            messages.append({"role": "user", "content": "Por favor, confirme o agendamento com a data e horário que informei."})
            retry = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_completion_tokens=max_tokens,
            )
            ai_response = retry.choices[0].message.content or "Perfeito! Sua reunião está agendada. Lembrando que ao atender no horário agendado você estará elegível para isenção da taxa da matrícula. Abraço! 🌻"
        # Detectar agendamento e criar evento no Google Calendar
        try:
            from app.google_calendar import detect_and_create_event
            await detect_and_create_event(
                ai_response,
                req.conversation_history,
                req.lead_name or "Lead",
                "teste",
                req.lead_course or "Não informado",
            )
        except Exception as e:
            print(f"⚠️ Erro ao criar evento: {e}")
        return {
            "response": ai_response,
            "model": model,
            "rag_docs": len(relevant_docs),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))