from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.auth import get_current_user
from app.database import get_db
# A trava vive em `routes.py` porque foi lá que nasceu, com as rotas /send/*.
# Importada e não duplicada: duas cópias da regra "humano falou, agente cala"
# divergiriam, e o lado que divergisse é o que deixa o robô respondendo por cima.
from app.routes import _silenciar_agente_apos_envio_manual
from app.models import ExactLead, CourseAlias, User
from app.exact_spotter import sync_exact_leads, get_auto_welcome_config
# Movida para modulo neutro (quebra o import circular com exact_spotter).
# Re-export: quem ja importava daqui continua funcionando, comportamento identico.
from app.course_names import resolve_course_name
# Trava unica do template de boas-vindas — a MESMA usada em /send/template e /scheduled-messages.
from app.welcome_guard import bloquear_se_boas_vindas

router = APIRouter(prefix="/api/exact-leads", tags=["exact-leads"])


@router.get("")
async def list_exact_leads(
    stage: str = None,
    sub_source: str = None,
    funnel_id: int = None,
    search: str = None,
    limit: int = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(ExactLead).order_by(ExactLead.register_date.desc())

    if stage:
        query = query.where(ExactLead.stage == stage)
    if sub_source:
        query = query.where(ExactLead.sub_source == sub_source)
    if funnel_id:
        query = query.where(ExactLead.funnel_id == funnel_id)
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

    funnel_result = await db.execute(
        select(ExactLead.funnel_id, func.count(ExactLead.id)).group_by(ExactLead.funnel_id)
    )
    by_funnel = {str(row[0]) if row[0] is not None else "N/A": row[1] for row in funnel_result.all()}

    return {
        "total": total,
        "by_stage": stages,
        "by_sub_source": sub_sources,
        "by_funnel": by_funnel,
    }


@router.get("/funnels")
async def list_funnels():
    """Proxy read-only do Exact /Funnels. Retorna [{id, name}] pro front montar o filtro."""
    import httpx
    import os

    headers = {
        "Content-Type": "application/json",
        "token_exact": os.getenv("EXACT_SPOTTER_TOKEN"),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get("https://api.exactspotter.com/v3/Funnels", headers=headers)
        data = res.json()

    return [
        {"id": f.get("id"), "name": f.get("value")}
        for f in data.get("value", [])
    ]


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


@router.post("/{exact_id}/resend-welcome", dependencies=[Depends(get_current_user)])
async def resend_welcome(exact_id: int, db: AsyncSession = Depends(get_db)):
    """Reenvia boas-vindas para UM lead específico. force=True ignora enabled/funil/idempotência.

    É a ÚNICA porta que fura o carimbo — e exige ação humana explícita, um lead por vez.
    NUNCA aceitar lista: o exact_id vem na URL, um por chamada.

    DUAS fechaduras, porque o force=True fura os guardas de send_welcome_to_new_lead:
      1. login (no decorator, para nao mexer na assinatura) — 401 antes de o corpo rodar;
      2. o liga/desliga — com a automacao desligada, nem quem esta logado reenvia.
    """
    from app.exact_spotter import send_welcome_to_new_lead

    lr = await db.execute(select(ExactLead).where(ExactLead.exact_id == exact_id))
    lead = lr.scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead não encontrado")

    cfg = await get_auto_welcome_config(db)
    if cfg is None or not cfg.enabled:
        raise HTTPException(
            400,
            "A automação de boas-vindas está desligada. Não é possível reenviar agora."
        )

    lead_data = {
        "exact_id": lead.exact_id,
        "name": lead.name,
        "phone1": lead.phone1,
        "sub_source": lead.sub_source,
        "funnel_id": lead.funnel_id,
        "sdr_name": lead.sdr_name,
    }
    r = await send_welcome_to_new_lead(lead_data, db, cfg, force=True)
    await db.commit()
    return r


# AUTENTICAÇÃO NO DECORATOR, NÃO NA ASSINATURA — e a diferença aqui é de correção, não de
# estilo. Esta função é chamada DIRETAMENTE como função Python pelo scheduled_messages_job
# (main.py:223: `await bulk_send_template(payload, db)`), sem passar por HTTP. Um parâmetro
# `usuario: User = Depends(get_current_user)` na assinatura receberia, nessa chamada, o
# próprio objeto `Depends` em vez de um User — silenciosamente, até alguém usar o valor.
# `dependencies=[...]` só é avaliado pelo pipeline de request do FastAPI, então a porta HTTP
# fica fechada e a chamada interna segue idêntica.
#
# Disparo em massa sem login é risco de suspensão da conta WhatsApp, não de conveniência: um
# POST anônimo daqui manda template para a lista de leads que quiser.
@router.post("/bulk-send-template")
async def bulk_send_template(
    request: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
    from app.sdr_mapping import resolve_sdr_user_id
    from app.whatsapp import send_template_message, fetch_template_body, render_template_text
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

    # ⛔ TRAVA ÚNICA (app/welcome_guard.py). Sem isto, alguém poderia filtrar o funil 18535,
    # selecionar milhares de leads antigos e disparar o nat_boasvindas para todos.
    await bloquear_se_boas_vindas(template_name, db)

    # Buscar leads
    result = await db.execute(select(ExactLead).where(ExactLead.id.in_(lead_ids)))
    leads = result.scalars().all()

    # GUARDRAIL: não cruzar funil — todos os leads selecionados devem ser do mesmo funnel_id.
    funnels = {l.funnel_id for l in leads}
    if len(funnels) > 1:
        raise HTTPException(status_code=400,
            detail="Os leads selecionados são de funis diferentes. Filtre por um único funil antes de enviar.")

    # Buscar channel
    from sqlalchemy import select as sa_select
    ch_result = await db.execute(sa_select(Channel).where(Channel.id == channel_id))
    channel = ch_result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Canal não encontrado")

    # Buscar o corpo do template uma única vez (para gravar o texto completo)
    template_body = await fetch_template_body(channel.waba_id, channel.whatsapp_token, template_name, language)

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
                # CANONIZAÇÃO (b) — ver `app/contatos.py`. O eco da Meta traz a grafia
                # canônica DELA, que pode ser a de 12 dígitos enquanto o contato daqui
                # nasceu com 13 (o agente cria a partir do telefone da Exact). Sem alinhar
                # as duas ANTES, `contato_existente` acha o contato pela outra grafia, o
                # `if not contact` decide não criar — corretamente — e o `Message` lá
                # embaixo aponta `contact_wa_id` para uma linha que não existe:
                # ForeignKeyViolation, e o lote inteiro morre em 500.
                #
                # Foi o que aconteceu em 28/08 (5 × 500 em ~35 min): o commit 05cea3f
                # trocou a busca exata por `contato_existente` aqui, mas não trouxe o
                # `canonizar` que `routes.py:261` recebeu no mesmo commit. Metade da
                # correção causa um bug que a busca exata não tinha.
                #
                # `contato_existente` + a grafia dele é, literalmente, o corpo de
                # `canonizar` — resolvido assim numa consulta só, em vez de chamar
                # `canonizar` e repetir a mesma busca na linha seguinte.
                from app.contatos import contato_existente

                eco_meta = result.get("contacts", [{}])[0].get("wa_id", phone)

                # Criar contato se não existir + vincular SDR do Exact
                sdr_user_id = resolve_sdr_user_id(lead.sdr_name)
                contact = await contato_existente(eco_meta, db)
                wa_id = contact.wa_id if contact is not None else eco_meta
                if not contact:
                    db.add(Contact(wa_id=wa_id, name=lead.name, channel_id=channel_id, assigned_to=sdr_user_id))
                    await db.flush()
                elif contact.assigned_to is None and sdr_user_id is not None:
                    contact.assigned_to = sdr_user_id

                # Texto COMPLETO renderizado (fallback ao formato antigo)
                rendered = render_template_text(template_body, lead_params)
                if rendered and rendered.strip():
                    content_text = rendered
                elif lead_params:
                    content_text = f"[Template] {', '.join(lead_params)}"
                else:
                    content_text = f"[Template] {template_name}"

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
                # FLUSH AQUI, DENTRO DO `try` DESTE LEAD. Sem ele o `msg` fica pendente e
                # quem estoura é o PRÓXIMO ponto que flusha — na prática o `begin_nested`
                # do `_silenciar` logo abaixo, cujo `except` largo engole o erro e devolve
                # a sessão em `PendingRollbackError`. O laço então morre no `lead.phone1`
                # da volta seguinte (atributo expirado → reload → sessão suja) e o lote
                # inteiro vira 500. O savepoint do `_silenciar` não isola isto: o objeto
                # que viola é da transação de FORA, não da dele.
                #
                # Com o flush aqui, uma falha deste lead é contabilizada como falha DESTE
                # lead (`failed`/`errors`) e os demais seguem — que é o contrato do laço.
                await db.flush()
                # NUNCA DUAS VOZES NA MESMA THREAD — a mesma regra de routes.py /send/*.
                # O disparo em massa não é um SDR conversando 1:1, mas o efeito no lead é
                # idêntico: um template cai na conversa que o agente está conduzindo, e a
                # resposta a ele volta para o agente, que não sabe do template. Quem dispara
                # é humano e está logado, então o motivo é o mesmo `outbound_manual_sdr`.
                #
                # Por contato, dentro do laço: um disparo para 300 leads pode ter 2 em
                # qualificação, e silenciar em bloco no fim exigiria carregar a lista inteira
                # só para descobrir isso. `silenciar` é no-op barato para quem não tem estado.
                await _silenciar_agente_apos_envio_manual(wa_id, current_user, db)
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