"""
Motor de IA com RAG para atendimento via WhatsApp.
Usa OpenAI para embeddings + geração de respostas.
"""
import os
import json
import numpy as np
import tiktoken
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import KnowledgeDocument, AIConfig, Message, AIConversationSummary

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_SYSTEM_PROMPT = """Você é um atendente virtual do CENAT (Centro Educacional Novas Abordagens em Saúde Mental).
Seu papel é atender leads interessados em cursos de pós-graduação.
Seja cordial, profissional e objetivo. Use as informações da base de conhecimento para responder.
Se não souber a resposta, diga que vai encaminhar para um atendente humano.
Nunca invente informações sobre preços, datas ou grades curriculares.
Responda de forma natural, como uma conversa no WhatsApp (mensagens curtas, use emojis com moderação)."""


# === Tokenização ===

def count_tokens(text: str, model: str = "gpt-5") -> int:
    """Conta tokens de um texto."""
    try:
        enc = tiktoken.encoding_for_model(model)
        return len(enc.encode(text))
    except Exception:
        return len(text) // 4


def split_into_chunks(text: str, title: str, max_tokens: int = 400) -> list[dict]:
    """Divide texto em chunks menores para embedding."""
    enc = tiktoken.encoding_for_model("gpt-4o")
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    chunks = []
    current_chunk = ""
    chunk_index = 0

    for paragraph in paragraphs:
        test_chunk = f"{current_chunk}\n{paragraph}".strip() if current_chunk else paragraph

        if len(enc.encode(test_chunk)) > max_tokens and current_chunk:
            tokens = len(enc.encode(current_chunk))
            chunks.append({
                "title": title,
                "content": current_chunk,
                "chunk_index": chunk_index,
                "token_count": tokens,
            })
            chunk_index += 1
            current_chunk = paragraph
        else:
            current_chunk = test_chunk

    if current_chunk:
        tokens = len(enc.encode(current_chunk))
        chunks.append({
            "title": title,
            "content": current_chunk,
            "chunk_index": chunk_index,
            "token_count": tokens,
        })

    return chunks


# === Embeddings ===

async def generate_embedding(text: str) -> list[float]:
    """Gera embedding de um texto usando OpenAI."""
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calcula similaridade de cosseno entre dois vetores."""
    a = np.array(a)
    b = np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# === RAG: Busca por Similaridade ===

async def search_knowledge(query: str, channel_id: int, db: AsyncSession, top_k: int = 3) -> list[dict]:
    """Busca os chunks mais relevantes para a pergunta do lead."""
    query_embedding = await generate_embedding(query)

    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.channel_id == channel_id,
            KnowledgeDocument.embedding.isnot(None),
        )
    )
    documents = result.scalars().all()

    if not documents:
        return []

    scored = []
    for doc in documents:
        try:
            doc_embedding = json.loads(doc.embedding)
            score = cosine_similarity(query_embedding, doc_embedding)
            scored.append({
                "title": doc.title,
                "content": doc.content,
                "score": score,
            })
        except (json.JSONDecodeError, TypeError):
            continue

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


# === Histórico de Conversa ===

async def get_conversation_history(contact_wa_id: str, db: AsyncSession, limit: int = 10) -> list[dict]:
    """Busca as últimas mensagens da conversa para contexto."""
    result = await db.execute(
        select(Message)
        .where(Message.contact_wa_id == contact_wa_id)
        .order_by(Message.timestamp.desc())
        .limit(limit)
    )
    messages = result.scalars().all()
    messages.reverse()

    history = []
    for msg in messages:
        role = "user" if msg.direction == "inbound" else "assistant"
        content = msg.content or ""

        # Ignorar mensagens de mídia no contexto
        if content.startswith("media:"):
            content = "[mídia enviada]"
        if msg.message_type == "template" or content.startswith("template:") or content.startswith("[Template]"):
            content = "[mensagem de template enviada]"

        history.append({"role": role, "content": content})

    return history


# === Geração de Resposta ===

async def generate_ai_response(
    contact_wa_id: str,
    user_message: str,
    channel_id: int,
    db: AsyncSession,
) -> str | None:
    """Gera resposta do agente IA usando RAG + histórico."""

    # 1. Buscar config da IA para o canal
    result = await db.execute(
        select(AIConfig).where(AIConfig.channel_id == channel_id)
    )
    ai_config = result.scalar_one_or_none()

    if not ai_config or not ai_config.is_enabled:
        return None

    system_prompt = ai_config.system_prompt or DEFAULT_SYSTEM_PROMPT
    model = ai_config.model or "gpt-4o"
    temperature = float(ai_config.temperature or "0.7")
    max_tokens = ai_config.max_tokens or 500

    # 1.5 Buscar nome e curso do lead
    from app.models import Contact, AIConversationSummary
    contact_result = await db.execute(
        select(Contact).where(Contact.wa_id == contact_wa_id)
    )
    contact = contact_result.scalar_one_or_none()
    lead_name = contact.name if contact and contact.name else ""
    
    # Buscar curso no card do kanban
    card_result = await db.execute(
        select(AIConversationSummary).where(
            AIConversationSummary.contact_wa_id == contact_wa_id,
            AIConversationSummary.channel_id == channel_id,
        )
    )
    card = card_result.scalar_one_or_none()
    lead_course = card.lead_course if card and card.lead_course else ""
    
    # Injetar dados do lead no prompt
    lead_info = ""
    if lead_name or lead_course:
        lead_info = "\n\nINFORMAÇÕES DO LEAD ATUAL:\n"
        if lead_name:
            lead_info += f"- Nome: {lead_name}\n"
        if lead_course:
            lead_info += f"- Curso de interesse: {lead_course}\n"
    # 1.7 Buscar disponibilidade do calendário
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
    # 2. Buscar contexto do RAG
    relevant_docs = await search_knowledge(user_message, channel_id, db)
    context = ""
    if relevant_docs:
        context = "\n\n---\nINFORMAÇÕES DA BASE DE CONHECIMENTO:\n"
        for doc in relevant_docs:
            context += f"\n[{doc['title']}] (relevância: {doc['score']:.2f})\n{doc['content']}\n"
        context += "---\n"

    # 3. Buscar histórico da conversa
    history = await get_conversation_history(contact_wa_id, db, limit=10)

    # 4. Montar mensagens para o GPT
    messages = [
        {"role": "system", "content": system_prompt + lead_info + calendar_info + context},
    ]
    messages.extend(history)

    # Se a última mensagem do histórico já é a mensagem atual, não duplicar
    if not history or history[-1].get("content") != user_message:
        messages.append({"role": "user", "content": user_message})

    # 5. Chamar OpenAI
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,

            max_completion_tokens=max_tokens,
        )
        ai_response = response.choices[0].message.content
        if not ai_response:
            messages.append({"role": "assistant", "content": ""})
            messages.append({"role": "user", "content": "Por favor, continue o atendimento."})
            retry = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_completion_tokens=max_tokens,
            )
            ai_response = retry.choices[0].message.content or "Desculpe, não consegui processar. Um momento que vou transferir para nossa consultora."
        # Detectar agendamento e criar evento no Google Calendar
        try:
            from app.google_calendar import detect_and_create_event
            await detect_and_create_event(
                ai_response,
                [],
                lead_name or "Lead",
                contact_wa_id,
                lead_course or "Não informado",
            )
        except Exception as e:
            print(f"⚠️ Erro ao criar evento: {e}")
        return ai_response
    except Exception as e:
        print(f"❌ Erro ao gerar resposta IA: {e}")
        return None


# === Resumo da Conversa ===

async def generate_conversation_summary(contact_wa_id: str, db: AsyncSession) -> str | None:
    """Gera um resumo da conversa para o Kanban."""
    history = await get_conversation_history(contact_wa_id, db, limit=30)

    if not history:
        return None

    conversation_text = "\n".join([
        f"{'Lead' if m['role'] == 'user' else 'Atendente'}: {m['content']}"
        for m in history
    ])

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Resuma esta conversa de atendimento em 2-3 frases objetivas. "
                               "Inclua: interesse do lead, dúvidas principais, e status final."
                },
                {"role": "user", "content": conversation_text},
            ],
            temperature=0.3,
            max_tokens=200,
        )
        ai_response = response.choices[0].message.content
        if not ai_response:
            messages.append({"role": "assistant", "content": ""})
            messages.append({"role": "user", "content": "Por favor, continue o atendimento."})
            retry = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_completion_tokens=max_tokens,
            )
            ai_response = retry.choices[0].message.content or "Desculpe, não consegui processar. Um momento que vou transferir para nossa consultora."
        return ai_response
    except Exception as e:
        print(f"❌ Erro ao gerar resumo: {e}")
        return None

# === Anotação na Exact Spotter ===
async def save_annotation_to_exact(contact_wa_id: str, channel_id: int, db: AsyncSession):
    """Gera resumo da conversa e salva na timeline da Exact Spotter."""
    from app.exact_spotter import add_timeline_comment
    
    # 1. Buscar exact_lead_id pelo phone
    result = await db.execute(
        select(ExactLead).where(ExactLead.phone1 == contact_wa_id)
    )
    exact_lead = result.scalar_one_or_none()
    if not exact_lead:
        print(f"⚠️ Lead não encontrado na Exact para wa_id: {contact_wa_id}")
        return False
    
    # 2. Buscar histórico da conversa
    history = await get_conversation_history(contact_wa_id, db, limit=30)
    if not history:
        return False
    
    # 3. Buscar info do card kanban
    card_result = await db.execute(
        select(AIConversationSummary).where(
            AIConversationSummary.contact_wa_id == contact_wa_id,
            AIConversationSummary.channel_id == channel_id,
        )
    )
    card = card_result.scalar_one_or_none()
    lead_course = card.lead_course if card else "Não informado"
    
    # 4. Gerar resumo com GPT
    conversation_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """Gere um resumo objetivo do atendimento via WhatsApp feito pela IA Nat.
Formato:
📋 RESUMO DO ATENDIMENTO (IA Nat)
📅 Data: [data atual]
🎓 Curso de interesse: [curso]
👤 Graduação: [se informou]
💼 Área de atuação: [se informou]
📌 Expectativa: [se informou]
�� Valor aceito: [sim/não/não chegou nessa etapa]
�� Agendamento: [data/hora se marcou]
📊 Status: [Qualificado/Não qualificado/Incompleto/Passou para humano]
📝 Observações: [algo relevante]

Seja breve e direto."""},
                {"role": "user", "content": f"Curso de interesse: {lead_course}\n\nConversa:\n{conversation_text}"}
            ],
            max_completion_tokens=500,
        )
        summary = response.choices[0].message.content
    except Exception as e:
        summary = f"�� Atendimento realizado pela IA Nat em {datetime.now().strftime('%d/%m/%Y %H:%M')}. Erro ao gerar resumo: {e}"
    
    # 5. Enviar para timeline da Exact Spotter
    success = await add_timeline_comment(exact_lead.exact_id, summary)
    
    # 6. Salvar no Hub também (card kanban)
    if card and summary:
        card.summary = summary
        await db.commit()
    
    return success
