import os
import httpx
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import ExactLead, Contact, Channel, Message, AIConversationSummary
from app.whatsapp import send_template_message

BASE_URL = "https://api.exactspotter.com/v3"

# Template que será enviado automaticamente para leads novos
AUTO_TEMPLATE_NAME = "mensagens_de_boas_vindas"
AUTO_TEMPLATE_LANG = "pt_BR"
# ID do canal da IA (segundo número)
AI_CHANNEL_ID = 2


def _parse_ids(env_value: str) -> set:
    return {int(x) for x in (env_value or "").split(",") if x.strip().isdigit()}


# Funis que RECEBEM welcome + IA + card (tratados como pós). Funil-Isa (25588) conta como pós.
POS_FUNNEL_IDS = _parse_ids(os.getenv("POS_FUNNEL_IDS", "18535,18537,25588"))
# Funis que entram no banco (ingestão). Intercambio (18285) entra só como dado, sem welcome.
INGEST_FUNNEL_IDS = _parse_ids(os.getenv("INGEST_FUNNEL_IDS", "18535,18537,25588,18285"))

# ID do usuário para comentários na timeline (Victória Amorim)
EXACT_BOT_USER_ID = 415875


async def add_timeline_comment(lead_id: int, text: str):
    """Insere comentário na timeline do lead na Exact Spotter."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{BASE_URL}/timelineAdd",
                headers=get_headers(),
                json={
                    "leadId": lead_id,
                    "text": text,
                    "userId": EXACT_BOT_USER_ID,
                },
            )
            if response.status_code in (200, 201):
                print(f"✅ Timeline atualizada para lead {lead_id}")
                return True
            else:
                print(f"❌ Erro timeline: {response.status_code} - {response.text}")
                return False
    except Exception as e:
        print(f"❌ Erro ao inserir timeline: {e}")
        return False


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


def format_phone(phone: str) -> str:
    """Formata telefone para padrão WhatsApp (55XXXXXXXXXXX)."""
    if not phone:
        return ""
    digits = "".join(c for c in phone if c.isdigit())
    if not digits.startswith("55"):
        digits = "55" + digits
    return digits


def extract_course_name(sub_source: str) -> str:
    """Extrai nome legível do curso a partir do subSource."""
    if not sub_source:
        return "Pós-Graduação"
    # Remove prefixo "pos" e formata
    name = sub_source
    if name.lower().startswith("pos"):
        name = name[3:]
    # Capitaliza
    name = name.replace("_", " ").replace("-", " ").strip()
    if name:
        return name
    return "Pós-Graduação"


async def send_welcome_to_new_lead(lead_data: dict, db: AsyncSession):
    """Envia template de boas-vindas e ativa a IA para um lead novo."""
    # GUARDRAIL: boas-vindas/IA/card só para funis de pós. Não-pós entra só como dado.
    if lead_data.get("funnel_id") not in POS_FUNNEL_IDS:
        return

    phone = format_phone(lead_data.get("phone1", ""))
    if not phone or len(phone) < 12:
        print(f"⚠️ Lead {lead_data.get('name')} sem telefone válido")
        return

    name = lead_data.get("name", "")
    course = extract_course_name(lead_data.get("sub_source", ""))

    # Buscar canal da IA
    result = await db.execute(select(Channel).where(Channel.id == AI_CHANNEL_ID))
    channel = result.scalar_one_or_none()
    if not channel:
        print("❌ Canal da IA não encontrado")
        return

    from app.whatsapp import fetch_template_body, render_template_text
    auto_template_body = await fetch_template_body(channel.waba_id, channel.whatsapp_token, AUTO_TEMPLATE_NAME, AUTO_TEMPLATE_LANG)

    # Enviar template
    try:
        send_result = await send_template_message(
            to=phone,
            template_name=AUTO_TEMPLATE_NAME,
            language=AUTO_TEMPLATE_LANG,
            phone_number_id=channel.phone_number_id,
            token=channel.whatsapp_token,
            parameters=[name, course],
        )

        if "messages" not in send_result:
            print(f"❌ Falha ao enviar para {name} ({phone}): {send_result}")
            return

        # Criar ou atualizar contato + vincular SDR do Exact
        from app.sdr_mapping import resolve_sdr_user_id
        _sdr = lead_data.get("sdr_name") or lead_data.get("sdr")
        if isinstance(_sdr, dict):
            _sdr = _sdr.get("name")
        sdr_user_id = resolve_sdr_user_id(_sdr)
        contact_result = await db.execute(select(Contact).where(Contact.wa_id == phone))
        contact = contact_result.scalar_one_or_none()
        if not contact:
            contact = Contact(
                wa_id=phone,
                name=name,
                channel_id=AI_CHANNEL_ID,
                ai_active=True,
                lead_status="novo",
                assigned_to=sdr_user_id,
            )
            db.add(contact)
            await db.flush()
        else:
            contact.ai_active = True
            if not contact.name:
                contact.name = name
            if contact.assigned_to is None and sdr_user_id is not None:
                contact.assigned_to = sdr_user_id

        # Salvar mensagem do template
        from datetime import timezone, timedelta
        SP_TZ = timezone(timedelta(hours=-3))

        message = Message(
            wa_message_id=send_result["messages"][0]["id"],
            contact_wa_id=phone,
            channel_id=AI_CHANNEL_ID,
            direction="outbound",
            message_type="template",
            content=(render_template_text(auto_template_body, [name, course]) or f"[Template] {name}, {course}"),
            timestamp=datetime.now(SP_TZ).replace(tzinfo=None),
            status="sent",
        )
        db.add(message)

        # Criar card no Kanban
        summary = AIConversationSummary(
            contact_wa_id=phone,
            channel_id=AI_CHANNEL_ID,
            status="em_atendimento_ia",
            lead_name=name,
            lead_course=course,
            ai_messages_count=0,
        )
        db.add(summary)

        print(f"🤖 Template enviado para {name} ({phone}) - Curso: {course}")

    except Exception as e:
        print(f"❌ Erro ao enviar welcome para {name}: {e}")


async def sync_exact_leads(db: AsyncSession):
    """Sincroniza leads de pós do Exact Spotter com o banco local."""
    skip = 0
    top = 500
    total_synced = 0
    total_new = 0
    total_updated = 0
    new_leads_to_contact = []

    while True:
        data = await fetch_leads_from_exact(skip=skip, top=top)
        leads = data.get("value", [])

        if not leads:
            break

        for lead in leads:
            if lead.get("funnelId") not in INGEST_FUNNEL_IDS:
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
                # Marcar para envio de boas-vindas — só funis de pós (blindagem em profundidade).
                if lead_data.get("funnel_id") in POS_FUNNEL_IDS:
                    new_leads_to_contact.append(lead_data)

            total_synced += 1

        if len(leads) < top:
            break

        skip += top

    await db.commit()

    # Enviar template para leads novos
    for lead_data in new_leads_to_contact:
        await send_welcome_to_new_lead(lead_data, db)

    await db.commit()

    return {
        "total_synced": total_synced,
        "new": total_new,
        "updated": total_updated,
        "welcome_sent": len(new_leads_to_contact),
    }