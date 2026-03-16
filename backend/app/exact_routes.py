from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import ExactLead, CourseAlias
from app.exact_spotter import sync_exact_leads

router = APIRouter(prefix="/api/exact-leads", tags=["exact-leads"])


async def resolve_course_name(sub_source: str, db: AsyncSession) -> str:
    """Resolve alias do curso para nome legivel via tabela course_aliases."""
    if not sub_source:
        return "Pós-Graduação"
    result = await db.execute(
        select(CourseAlias).where(
            func.lower(CourseAlias.alias) == func.lower(sub_source),
            CourseAlias.is_active == True,
        )
    )
    course = result.scalar_one_or_none()
    if course:
        return course.short_name
    # Fallback: remove prefixo pos e formata
    name = sub_source
    if name.lower().startswith("pos"):
        name = name[3:]
    name = name.replace("_", " ").replace("-", " ").strip()
    return name if name else "Pós-Graduação"


@router.get("")
async def list_exact_leads(
    stage: str = None,
    sub_source: str = None,
    search: str = None,
    limit: int = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(ExactLead).order_by(ExactLead.register_date.desc())

    if stage:
        query = query.where(ExactLead.stage == stage)
    if sub_source:
        query = query.where(ExactLead.sub_source == sub_source)
    if search:
        query = query.where(
            ExactLead.name.ilike(f"%{search}%") | ExactLead.phone1.ilike(f"%{search}%")
        )
    if limit:
        query = query.limit(limit)

    result = await db.execute(query)
    leads = result.scalars().all()

    return [
        {
            "id": l.id,
            "exact_id": l.exact_id,
            "name": l.name,
            "phone1": l.phone1,
            "phone2": l.phone2,
            "source": l.source,
            "sub_source": l.sub_source,
            "stage": l.stage,
            "funnel_id": l.funnel_id,
            "sdr_name": l.sdr_name,
            "register_date": l.register_date.isoformat() if l.register_date else None,
            "update_date": l.update_date.isoformat() if l.update_date else None,
            "synced_at": l.synced_at.isoformat() if l.synced_at else None,
        }
        for l in leads
    ]


@router.post("/sync")
async def trigger_sync(db: AsyncSession = Depends(get_db)):
    result = await sync_exact_leads(db)
    return {"status": "ok", **result}


@router.get("/stats")
async def exact_leads_stats(db: AsyncSession = Depends(get_db)):
    total = await db.execute(select(func.count(ExactLead.id)))
    total = total.scalar()

    stage_result = await db.execute(
        select(ExactLead.stage, func.count(ExactLead.id)).group_by(ExactLead.stage)
    )
    stages = {row[0] or "N/A": row[1] for row in stage_result.all()}

    sub_source_result = await db.execute(
        select(ExactLead.sub_source, func.count(ExactLead.id)).group_by(ExactLead.sub_source)
    )
    sub_sources = {row[0] or "N/A": row[1] for row in sub_source_result.all()}

    return {
        "total": total,
        "by_stage": stages,
        "by_sub_source": sub_sources,
    }


@router.get("/{exact_id}/details")
async def get_lead_details(exact_id: int):
    import httpx
    import os

    headers = {
        "Content-Type": "application/json",
        "token_exact": os.getenv("EXACT_SPOTTER_TOKEN")
    }
    base = "https://api.exactspotter.com/v3"

    async with httpx.AsyncClient(timeout=30) as client:
        # Lead
        lead_res = await client.get(f"{base}/Leads", headers=headers, params={"$filter": f"id eq {exact_id}"})
        lead_data = lead_res.json().get("value", [])
        lead = lead_data[0] if lead_data else None

        # Persons
        person_res = await client.get(f"{base}/Persons", headers=headers, params={"$filter": f"leadId eq {exact_id}"})
        persons = person_res.json().get("value", [])

        # QualificationHistories
        qual_res = await client.get(f"{base}/QualificationHistories", headers=headers, params={"$filter": f"leadId eq {exact_id}"})
        qualifications = qual_res.json().get("value", [])

    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado no Exact Spotter")

    return {
        "lead": {
            "id": lead["id"],
            "name": lead["lead"],
            "phone1": lead.get("phone1"),
            "phone2": lead.get("phone2"),
            "stage": lead.get("stage"),
            "source": lead.get("source", {}).get("value") if lead.get("source") else None,
            "sub_source": lead.get("subSource", {}).get("value") if lead.get("subSource") else None,
            "sdr": lead.get("sdr", {}).get("name") if lead.get("sdr") else None,
            "register_date": lead.get("registerDate"),
            "update_date": lead.get("updateDate"),
            "description": lead.get("description"),
            "city": lead.get("city"),
            "state": lead.get("state"),
            "public_link": lead.get("publicLink"),
        },
        "persons": [
            {
                "name": p.get("name"),
                "email": p.get("email"),
                "job_title": p.get("jobTitle"),
                "phone1": p.get("phone1"),
            }
            for p in persons
        ],
        "qualifications": [
            {
                "origin_stage": q.get("originStage"),
                "stage": q.get("stage"),
                "score": q.get("score"),
                "qualification_date": q.get("qualificationDate"),
                "meeting_date": q.get("meetingDate"),
                "user_action": q.get("userAction"),
            }
            for q in qualifications
        ],
    }


@router.post("/bulk-send-template")
async def bulk_send_template(
    request: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    Envio em massa com mapeamento dinâmico de variáveis.

    param_mappings: lista de objetos com type e value (opcional).
    Tipos suportados:
      - lead_name: primeiro nome do lead
      - lead_full_name: nome completo do lead
      - lead_course: nome do curso (resolvido via aliases)
      - sdr_name: nome do SDR do lead
      - fixed_text: texto fixo (usa o campo "value")

    Exemplo:
    {
      "template_name": "sdr_primeiro_contato",
      "channel_id": 1,
      "lead_ids": [1, 2, 3],
      "param_mappings": [
        {"type": "lead_name"},
        {"type": "sdr_name"},
        {"type": "lead_course"}
      ]
    }

    Compatibilidade: se param_mappings não for enviado, usa o campo
    "parameters" antigo (nome + curso).
    """
    from app.models import Channel, Contact, Message
    from app.whatsapp import send_template_message
    from datetime import datetime, timedelta, timezone
    import asyncio

    SP_TZ = timezone(timedelta(hours=-3))

    template_name = request.get("template_name")
    language = request.get("language", "pt_BR")
    channel_id = request.get("channel_id", 1)
    lead_ids = request.get("lead_ids", [])
    param_mappings = request.get("param_mappings", None)
    parameters = request.get("parameters", [])

    if not template_name or not lead_ids:
        raise HTTPException(status_code=400, detail="template_name e lead_ids são obrigatórios")

    # Buscar leads
    result = await db.execute(select(ExactLead).where(ExactLead.id.in_(lead_ids)))
    leads = result.scalars().all()

    # Buscar channel
    from sqlalchemy import select as sa_select
    ch_result = await db.execute(sa_select(Channel).where(Channel.id == channel_id))
    channel = ch_result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Canal não encontrado")

    sent = 0
    failed = 0
    errors = []

    for lead in leads:
        phone = lead.phone1
        if not phone:
            failed += 1
            errors.append({"name": lead.name, "error": "Sem telefone"})
            continue

        phone = phone.replace("+", "").replace(" ", "").replace("-", "")

        # Resolver valores das variáveis
        if param_mappings and len(param_mappings) > 0:
            # Modo novo: mapeamento dinâmico
            lead_params = []
            for mapping in param_mappings:
                m_type = mapping.get("type", "fixed_text")
                m_value = mapping.get("value", "")

                if m_type == "lead_name":
                    lead_params.append(lead.name.split()[0] if lead.name else "Aluno(a)")
                elif m_type == "lead_full_name":
                    lead_params.append(lead.name if lead.name else "Aluno(a)")
                elif m_type == "lead_course":
                    course = await resolve_course_name(lead.sub_source, db)
                    lead_params.append(course)
                elif m_type == "sdr_name":
                    lead_params.append(lead.sdr_name if lead.sdr_name else "Equipe CENAT")
                elif m_type == "fixed_text":
                    lead_params.append(m_value if m_value else "")
                else:
                    lead_params.append(m_value if m_value else "")
        else:
            # Modo legado: compatibilidade com frontend antigo
            lead_name = lead.name.split()[0] if lead.name else "Aluno(a)"
            lead_course = await resolve_course_name(lead.sub_source, db)
            param_count = len(parameters) if parameters else 0

            if param_count == 0:
                lead_params = None
            elif param_count == 1:
                lead_params = [lead_name]
            else:
                lead_params = [lead_name, lead_course]

        try:
            result = await send_template_message(
                phone, template_name, language,
                channel.phone_number_id, channel.whatsapp_token,
                lead_params
            )

            if "messages" in result:
                wa_id = result.get("contacts", [{}])[0].get("wa_id", phone)

                # Criar contato se não existir
                contact_result = await db.execute(
                    select(Contact).where(Contact.wa_id == wa_id)
                )
                contact = contact_result.scalar_one_or_none()
                if not contact:
                    db.add(Contact(wa_id=wa_id, name=lead.name, channel_id=channel_id))
                    await db.flush()

                # Salvar mensagem
                content_text = f"[Template] {', '.join(lead_params)}" if lead_params else f"[Template] {template_name}"

                msg = Message(
                    wa_message_id=result["messages"][0]["id"],
                    contact_wa_id=wa_id,
                    channel_id=channel_id,
                    direction="outbound",
                    message_type="template",
                    content=content_text,
                    timestamp=datetime.now(SP_TZ).replace(tzinfo=None),
                    status="sent",
                )
                db.add(msg)
                sent += 1
            else:
                failed += 1
                errors.append({"name": lead.name, "error": str(result)})

        except Exception as e:
            failed += 1
            errors.append({"name": lead.name, "error": str(e)})

        # Delay para evitar rate limit do WhatsApp
        await asyncio.sleep(1)

    await db.commit()
    return {"sent": sent, "failed": failed, "errors": errors}