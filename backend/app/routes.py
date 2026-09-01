from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from typing import Optional
import json
import re
from app.auth import get_current_user, get_current_admin
from app.models import Channel, Contact, Message, Tag, contact_tags, CourseAlias, User, WhatsappTemplate

SP_TZ = timezone(timedelta(hours=-3))

from app.database import get_db
from app.whatsapp import send_text_message, send_template_message, upload_media, send_media_message, create_template, GRAPH_VERSION
# Trava unica do template de boas-vindas (a MESMA usada em bulk-send-template).
from app.welcome_guard import bloquear_se_boas_vindas
from app.contatos import canonizar, contato_existente, destinatario
# Quem apertou enviar (ver app/autoria.py — a armadilha do `Depends`).
from app.autoria import quem_enviou

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
    rendered_text: str = ""


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


class TemplateButton(BaseModel):
    type: str                            # "QUICK_REPLY" | "URL" | "PHONE_NUMBER"
    text: str
    url: Optional[str] = None            # type URL
    phone_number: Optional[str] = None   # type PHONE_NUMBER


class CreateTemplateRequest(BaseModel):
    name: str
    category: str                        # MARKETING | UTILITY
    language: str = "pt_BR"
    header_text: Optional[str] = None
    body_text: str
    body_examples: list[str] = []        # 1 valor por variável {{n}}
    footer_text: Optional[str] = None
    buttons: list[TemplateButton] = []


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


# AUTENTICAÇÃO (Fase 5). No decorator e não na assinatura, pelo mesmo motivo documentado em
# exact_routes.bulk-send-template: mantém as funções chamáveis de dentro do processo sem que
# a dependência de request vaze para a assinatura. Aqui não há chamador interno hoje, mas a
# forma é a mesma nos quatro endpoints de disparo — um padrão só, e o que já existia em
# /{exact_id}/resend-welcome.
async def _silenciar_agente_apos_envio_manual(wa_id: str, quem, db: AsyncSession) -> None:
    """SDR digitou num contato que o agente estava conduzindo → o agente cala.

    NUNCA DUAS VOZES NA MESMA THREAD. Sem isto, o SDR responde "oi, sou o Thobias" e a
    próxima mensagem do lead ainda é processada pelo agente, que responde por cima — o lead
    vê duas pessoas conduzindo a mesma conversa, e nenhuma sabe da outra.

    A TRAVA VIVE NAS ROTAS `/send/*`, E ISSO É A DEFINIÇÃO DE "MANUAL"
    -----------------------------------------------------------------
    Distinguir SDR de agente por TEXTO seria adivinhação. Por ROTA é fato:

        app/routes.py  /send/text · /send/template · /send/media   humano, com login
        app/nat_sender.py:191                                      agente e NAT, sempre
                                                                   carimbando `nat_etapa`

    `nat_sender` é o ÚNICO ponto por onde envio do agente passa, e ele não chama isto. Então
    a mensagem do próprio agente jamais dispara a trava — não por uma checagem que possa
    esquecer um caso, mas porque o código nunca é alcançado por aquele caminho. É a diferença
    entre uma regra que pode falhar e uma que não tem como.

    Os outros escritores de outbound do projeto NÃO estão aqui, de propósito:
    `exact_spotter` (boas-vindas automática), `exact_routes.bulk_send_template` (disparo em
    massa) e o job de `scheduled_messages`. Nenhum é um SDR conversando 1:1, que é o gatilho
    que o produto pediu. O disparo em massa é o caso limítrofe — ver o CHECKPOINT.

    NÃO PODE DERRUBAR O ENVIO
    -------------------------
    A mensagem do SDR já foi para a Meta quando chegamos aqui: falhar agora significaria
    devolver erro para um envio que ACONTECEU, e o SDR mandaria de novo. Por isso savepoint
    (um IntegrityError deixaria a transação abortada e o `commit` do envio falharia junto) e
    `except` largo. O pior caso é o agente continuar ativo, que é o estado de hoje.
    """
    try:
        async with db.begin_nested():
            from app.qualificacao_fluxo import MOTIVO_OUTBOUND_MANUAL, silenciar
            await silenciar(wa_id, MOTIVO_OUTBOUND_MANUAL, db,
                            quem_id=getattr(quem, "id", None),
                            quem_nome=getattr(quem, "name", None))
    except Exception as e:
        print(f"⚠️  Falha ao silenciar o agente em {wa_id} depois de envio manual "
              f"({type(e).__name__}: {e}). O agente segue ativo.")


@router.post("/send/text")
async def send_text(req: SendTextRequest, db: AsyncSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    channel = await get_channel(req.channel_id, db)
    # QUEM DECIDE A GRAFIA DO DESTINATÁRIO É O SERVIDOR, NÃO A TELA. O front manda o `wa_id`
    # da conversa que está aberta — que, depois do agrupamento, pode ser qualquer uma das
    # duas. `destinatario` devolve a que a pessoa JÁ usou para nos escrever. Ver contatos.py.
    destino = await destinatario(req.to, db)
    result = await send_text_message(destino, req.text, channel.phone_number_id, channel.whatsapp_token)

    if "messages" in result:
        # O eco da Meta é a grafia canônica DELA; `canonizar` a alinha com o contato que
        # este humano já tem aqui, se tiver. Ver `app/contatos.py`.
        wa_id = await canonizar(result.get("contacts", [{}])[0].get("wa_id", req.to), db)

        contact = await contato_existente(wa_id, db)
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
            timestamp=datetime.now(SP_TZ).replace(tzinfo=None),
            status="sent",
            # S6-1: a MESMA `current_user` que ja calava o agente agora tambem fica gravada.
            # `template_name` segue NULL aqui — texto livre nao tem template.
            sent_by=quem_enviou(current_user),
        )
        db.add(message)
        # Depois do add e ANTES do commit: a mesma transação que registra a fala do humano
        # registra o silêncio do agente. Separar em dois commits abriria a janela em que a
        # mensagem existe e o agente ainda é dono — que é exatamente a janela em que o lead
        # responde e leva resposta dobrada.
        await _silenciar_agente_apos_envio_manual(wa_id, current_user, db)
        await db.commit()

    return result


@router.post("/send/template")
async def send_template(req: SendTemplateRequest, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    # ⛔ TRAVA ÚNICA: o template de boas-vindas não sai por envio manual. Sem isto, um SDR
    # poderia abrir "Nova conversa", colar o telefone de um lead antigo e mandar a boas-vindas.
    await bloquear_se_boas_vindas(req.template_name, db)

    channel = await get_channel(req.channel_id, db)
    destino = await destinatario(req.to, db)          # ver send_text
    result = await send_template_message(destino, req.template_name, req.language, channel.phone_number_id, channel.whatsapp_token, req.parameters if req.parameters else None)

    if "messages" in result:
        wa_id = await canonizar(result.get("contacts", [{}])[0].get("wa_id", req.to), db)

        contact = await contato_existente(wa_id, db)
        if not contact:
            db.add(Contact(wa_id=wa_id, name=req.contact_name or "", channel_id=req.channel_id))
            await db.flush()
        elif req.contact_name and not contact.name:
            contact.name = req.contact_name

        # Conteúdo legível: usa o texto renderizado (corpo com variáveis preenchidas).
        # Fallback ao comportamento antigo se rendered_text não vier.
        if req.rendered_text and req.rendered_text.strip():
            content_text = req.rendered_text
        elif req.parameters:
            content_text = "[Template] " + ", ".join(req.parameters)
        else:
            content_text = f"template:{req.template_name}"

        message = Message(
            wa_message_id=result["messages"][0]["id"],
            contact_wa_id=wa_id,
            channel_id=req.channel_id,
            direction="outbound",
            message_type="template",
            content=content_text,
            timestamp=datetime.now(SP_TZ).replace(tzinfo=None),
            status="sent",
            # S6-1: `req.template_name` e o nome APROVADO na Meta, nao o texto renderizado.
            # E' o que `content` nunca soube dizer.
            sent_by=quem_enviou(current_user),
            template_name=req.template_name,
        )
        db.add(message)
        await _silenciar_agente_apos_envio_manual(wa_id, current_user, db)
        await db.commit()

    return result


@router.post("/send/media")
async def send_media(
    file: UploadFile = File(...),
    to: str = Form(...),
    channel_id: int = Form(...),
    type: str = Form(...),  # image, document, audio
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = await get_channel(channel_id, db)
    file_bytes = await file.read()
    mime_type = file.content_type or "application/octet-stream"
    filename = file.filename or "file"

    # Mapear tipo para media_type da Meta
    media_type_map = {
        "image": "image",
        "document": "document",
        "audio": "audio",
        "video": "video",
    }
    media_type = media_type_map.get(type, "document")

    # 1. Upload da mídia para Meta
    media_id = await upload_media(file_bytes, mime_type, filename, channel.phone_number_id, channel.whatsapp_token)

    # 2. Enviar mensagem com mídia
    caption = filename if media_type == "document" else None
    destino = await destinatario(to, db)              # ver send_text
    result = await send_media_message(destino, media_id, media_type, channel.phone_number_id, channel.whatsapp_token, caption)

    if "messages" in result:
        wa_id = await canonizar(result.get("contacts", [{}])[0].get("wa_id", to), db)

        contact = await contato_existente(wa_id, db)
        if not contact:
            contact = Contact(wa_id=wa_id, name="", channel_id=channel_id)
            db.add(contact)
            await db.flush()

        # Salvar referência da mídia: media:{media_id}|{mime_type}|{filename}
        content = f"media:{media_id}|{mime_type}|{filename}"

        message = Message(
            wa_message_id=result["messages"][0]["id"],
            contact_wa_id=wa_id,
            channel_id=channel_id,
            direction="outbound",
            message_type=media_type,
            content=content,
            timestamp=datetime.now(SP_TZ).replace(tzinfo=None),
            status="sent",
            sent_by=quem_enviou(current_user),
        )
        db.add(message)
        await _silenciar_agente_apos_envio_manual(wa_id, current_user, db)
        await db.commit()

    return result


# === Contatos ===

@router.get("/contacts")
async def list_contacts(channel_id: Optional[int] = None, assigned_to: Optional[int] = None, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy import text

    filters = []
    params = {}

    if channel_id:
        filters.append("c.channel_id = :channel_id")
        params["channel_id"] = channel_id

    if current_user.role != "admin":
        filters.append("c.assigned_to = :user_id")
        params["user_id"] = current_user.id
    elif assigned_to:
        filters.append("c.assigned_to = :assigned_to")
        params["assigned_to"] = assigned_to

    where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""

    sql = text(f"""
        SELECT
            c.wa_id, c.name, c.lead_status, c.notes, c.channel_id,
            c.ai_active, c.created_at, c.assigned_to,
            lm.content AS last_message,
            lm.timestamp AS last_message_time,
            lm.direction,
            COALESCE(ur.unread, 0) AS unread,
            COALESCE(ur.inbound_total, 0) AS inbound_total
        FROM contacts c
        LEFT JOIN LATERAL (
            SELECT content, timestamp, direction
            FROM messages WHERE contact_wa_id = c.wa_id
            ORDER BY timestamp DESC LIMIT 1
        ) lm ON true
        LEFT JOIN LATERAL (
            -- `inbound_total` alimenta a escolha do representante do par em
            -- `contatos.principal_do_par`: vence a grafia de que a pessoa NOS escreveu.
            SELECT COUNT(*) FILTER (WHERE status = 'received') AS unread,
                   COUNT(*) AS inbound_total
            FROM messages
            WHERE contact_wa_id = c.wa_id AND direction = 'inbound'
        ) ur ON true
        {where_clause}
        ORDER BY lm.timestamp DESC NULLS LAST
    """)

    result = await db.execute(sql, params)
    rows = result.fetchall()

    # Buscar tags de todos os contatos de uma vez
    wa_ids = [r.wa_id for r in rows]

    if wa_ids:
        tag_sql = text("""
            SELECT ct.contact_wa_id, t.id, t.name, t.color
            FROM contact_tags ct JOIN tags t ON t.id = ct.tag_id
            WHERE ct.contact_wa_id = ANY(:wa_ids)
        """)
        tag_result = await db.execute(tag_sql, {"wa_ids": wa_ids})
        tag_rows = tag_result.fetchall()
    else:
        tag_rows = []

    # Agrupar tags por wa_id
    tags_map: dict = {}
    for tr in tag_rows:
        if tr.contact_wa_id not in tags_map:
            tags_map[tr.contact_wa_id] = []
        tags_map[tr.contact_wa_id].append({"id": tr.id, "name": tr.name, "color": tr.color})

    # ------------------------------------------------------------------------------------
    # UMA CONVERSA POR HUMANO. As duas grafias do mesmo telefone viram UMA linha.
    #
    # 406 pares (10% do Hub) estavam aparecendo como duas conversas, cada uma com metade das
    # mensagens — ver `app/contatos.py` e RECON_THREADS_DIVIDIDAS_20260827.md. Aqui a fusão
    # é só de APRESENTAÇÃO: nada é escrito, nenhum contato é apagado, e desligar este trecho
    # devolve a tela ao estado anterior.
    #
    # Os campos NÃO são fundidos por COALESCE cego — cada um tem uma regra e um motivo:
    #   name        o não-vazio (338 dos 406 pares têm nome só de um lado)
    #   unread      SOMA — o badge tem que zerar junto com o `POST /read`, que agora
    #               marca as duas grafias
    #   last_*      da mensagem mais recente ENTRE as duas, que é o ponto do conserto
    #   tags        união
    #   ai_active   OR — divergente em 366 dos 406 pares; mostrar "ligado" quando qualquer
    #               lado está ligado é o lado seguro do erro: esconder um robô ativo é pior
    #               que mostrar um que não vai falar
    #   assigned_to o dono existente; se os dois lados têm dono DIFERENTE, o do lado que
    #               recebe inbound, e `assigned_to_conflito` avisa a tela (103 pares hoje)
    # ------------------------------------------------------------------------------------
    from app.contatos import chave_par, principal_do_par

    grupos: dict = {}
    for r in rows:
        grupos.setdefault(chave_par(r.wa_id), []).append(r)

    def _ts(r):
        return r.last_message_time

    saida = []
    for membros in grupos.values():
        por_wa = {m.wa_id: m for m in membros}
        principal = principal_do_par(
            list(por_wa),
            tem_inbound=lambda w: (por_wa[w].inbound_total or 0) > 0,
            ultimo_ts=lambda w: por_wa[w].last_message_time,
        )
        r = por_wa[principal]
        outros = [m for m in membros if m.wa_id != principal]

        recente = max((m for m in membros if m.last_message_time is not None),
                      key=_ts, default=None)
        nome = next((m.name for m in [r, *outros] if (m.name or "").strip()), None)
        donos = [m.assigned_to for m in [r, *outros] if m.assigned_to is not None]
        tags = {t["id"]: t for m in membros for t in tags_map.get(m.wa_id, [])}
        nascimento = min((m.created_at for m in membros if m.created_at), default=None)

        saida.append({
            "wa_id": principal,
            "name": nome or principal,
            "lead_status": next((m.lead_status for m in [r, *outros] if m.lead_status), "novo"),
            "notes": next((m.notes for m in [r, *outros] if (m.notes or "").strip()), None),
            "channel_id": next((m.channel_id for m in [r, *outros] if m.channel_id), None),
            "last_message": (recente.last_message or "") if recente else "",
            "last_message_time": recente.last_message_time.isoformat() if recente else None,
            "direction": recente.direction if recente else None,
            "tags": list(tags.values()),
            "unread": sum(m.unread or 0 for m in membros),
            "ai_active": any(m.ai_active for m in membros),
            # O mais antigo dos dois: a conversa começou quando o PRIMEIRO contato nasceu.
            "created_at": nascimento.isoformat() if nascimento else None,
            "assigned_to": donos[0] if donos else None,
            # Só aparece quando há de fato duas grafias — a tela pode ignorar sem quebrar.
            "wa_ids": [m.wa_id for m in membros] if len(membros) > 1 else None,
            "assigned_to_conflito": len(set(donos)) > 1 or None,
        })

    # `last_message_time` já é ISO 8601 — ordena lexicograficamente na ordem certa, e a
    # string vazia (conversa sem mensagem) cai para o fim, como fazia o `NULLS LAST` do SQL.
    saida.sort(key=lambda d: d["last_message_time"] or "", reverse=True)
    return saida


@router.get("/contacts/{wa_id}")
async def get_contact(wa_id: str, db: AsyncSession = Depends(get_db)):
    """O cabeçalho da conversa. Lê as duas grafias, pelas mesmas regras de `GET /contacts`."""
    from app.telefone import variantes_wa_id

    vs = variantes_wa_id(wa_id) or (wa_id,)
    achados = list((await db.execute(
        select(Contact).where(Contact.wa_id.in_(vs)))).scalars())
    if not achados:
        raise HTTPException(status_code=404, detail="Contato não encontrado")
    # O pedido manda: se o wa_id da URL existe, ele é o principal; senão, o que existir.
    # Reordenar (e não só escolher) mantém este endpoint concordando com `GET /contacts`
    # em name/notes/lead_status — dois lugares mostrando nomes diferentes do mesmo humano
    # é exatamente o tipo de divergência que este sprint existe para acabar.
    contact = next((c for c in achados if c.wa_id == wa_id), achados[0])
    achados = [contact] + [c for c in achados if c is not contact]
    todos = [c.wa_id for c in achados]

    tag_result = await db.execute(
        select(Tag).join(contact_tags).where(contact_tags.c.contact_wa_id.in_(todos))
    )
    tags = {t.id: t for t in tag_result.scalars().all()}

    msg_count = await db.execute(
        select(func.count(Message.id)).where(Message.contact_wa_id.in_(vs)))

    return {
        "wa_id": contact.wa_id,
        "name": next((c.name for c in achados if (c.name or "").strip()), contact.name),
        "lead_status": next((c.lead_status for c in achados if c.lead_status), None),
        "notes": next((c.notes for c in achados if (c.notes or "").strip()), None),
        "channel_id": next((c.channel_id for c in achados if c.channel_id), None),
        "ai_active": any(c.ai_active for c in achados),
        "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in tags.values()],
        "total_messages": msg_count.scalar(),
        "created_at": min((c.created_at for c in achados if c.created_at),
                          default=None).isoformat()
                      if any(c.created_at for c in achados) else None,
        "wa_ids": todos if len(todos) > 1 else None,
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


class AssignContactRequest(BaseModel):
    assigned_to: Optional[int] = None


@router.patch("/contacts/{wa_id}/assign")
async def assign_contact(wa_id: str, req: AssignContactRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Contact).where(Contact.wa_id == wa_id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")
    if req.assigned_to is not None:
        user_result = await db.execute(select(User).where(User.id == req.assigned_to, User.is_active == True))
        if not user_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Usuário (SDR) não encontrado")
    contact.assigned_to = req.assigned_to
    await db.commit()
    return {"status": "assigned", "assigned_to": req.assigned_to}


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

@router.post("/contacts/{wa_id}/read")
async def mark_as_read(wa_id: str, db: AsyncSession = Depends(get_db)):
    """Marca como lidas as mensagens inbound do contato — NAS DUAS GRAFIAS.

    Tem que casar com o `unread` de `GET /contacts`, que agora soma as duas metades. Marcar
    só uma deixaria o badge preso num número que o SDR não consegue zerar por mais que abra
    a conversa.
    """
    from sqlalchemy import update
    from app.telefone import variantes_wa_id

    vs = variantes_wa_id(wa_id) or (wa_id,)
    await db.execute(
        update(Message).where(
            Message.contact_wa_id.in_(vs),
            Message.direction == "inbound",
            Message.status == "received"
        ).values(status="read")
    )
    await db.commit()
    return {"status": "ok"}


@router.get("/contacts/{wa_id}/messages")
async def get_messages(wa_id: str, db: AsyncSession = Depends(get_db)):
    """A conversa INTEIRA deste humano — as duas grafias do telefone, mescladas por timestamp.

    Era `== wa_id`, e é por isso que o SDR via meia conversa: a pessoa escreve na grafia de 12
    dígitos e o agente responde na de 13. Lidas juntas na ordem do relógio, os turnos alternam
    perfeitamente (o caso Mikaelle, em RECON_THREADS_DIVIDIDAS_20260827.md).

    Mesma troca `== → IN (variantes)` que os sprints do agente já fizeram em
    `nat_sender.janela_aberta` e `qualificacao_fluxo.estado_de`. Nada é escrito aqui.
    """
    from app.telefone import variantes_wa_id

    vs = variantes_wa_id(wa_id) or (wa_id,)
    result = await db.execute(
        select(Message).where(Message.contact_wa_id.in_(vs)).order_by(Message.timestamp.asc())
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
            "sent_by_ai": m.sent_by_ai or False,
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
async def list_templates(channel_id: int, status: Optional[str] = "APPROVED", db: AsyncSession = Depends(get_db)):
    """Lista templates do WABA (status ao vivo do Meta).

    Default status=APPROVED (não quebra conversas/automações, que enviam só aprovados).
    Passar status=all (ou vazio) lista todos os status e inclui category/rejected_reason.
    """
    import httpx
    channel = await get_channel(channel_id, db)
    params = {
        "limit": 100,
        "fields": "name,language,status,category,components,rejected_reason",
    }
    # Filtra por status só quando não for "all"/vazio.
    if status and status.lower() != "all":
        params["status"] = status

    # O Meta pagina: sem seguir paging.next o Hub some com os templates além da
    # primeira página (o WABA já passou de 50). Teto de páginas só pra não girar à toa.
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{channel.waba_id}/message_templates"
    raw = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for page in range(20):
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {channel.whatsapp_token}"},
                params=params if page == 0 else None,
            )
            data = response.json()
            if data.get("error"):
                raise HTTPException(status_code=502, detail=data["error"].get("message", "Erro do Meta ao listar templates"))
            raw.extend(data.get("data", []))
            url = (data.get("paging") or {}).get("next")
            if not url:
                break

    templates = []
    for t in raw:
        body = ""
        parameters = []
        for comp in t.get("components", []):
            if comp.get("type") == "BODY":
                body = comp.get("text", "")
                matches = re.findall(r'\{\{(\d+)\}\}', body)
                parameters = [f"Variável {m}" for m in matches]
        templates.append({
            "name": t.get("name"),
            "language": t.get("language"),
            "status": t.get("status"),
            "category": t.get("category"),
            "rejected_reason": t.get("rejected_reason"),
            "body": body,
            "parameters": parameters,
        })

    return templates


@router.post("/channels/{channel_id}/templates")
async def create_channel_template(
    channel_id: int,
    req: CreateTemplateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Cria (submete pra aprovação) um template no WABA do canal. Somente admin.

    Pré-valida só o barato (campos obrigatórios/formato); a combinação de botões fica
    a cargo do Meta, cujo erro é repassado verbatim pra tela.
    """
    # --- Validação barata (back) ---
    if not re.fullmatch(r'[a-z0-9_]+', req.name or ""):
        raise HTTPException(status_code=422, detail="Nome inválido: use apenas minúsculas, números e _ (snake_case), sem espaços.")
    if req.category not in {"MARKETING", "UTILITY"}:
        raise HTTPException(status_code=422, detail="Categoria inválida: use MARKETING ou UTILITY.")
    if req.language != "pt_BR":
        raise HTTPException(status_code=422, detail="Idioma inválido: somente pt_BR no v1.")
    if not req.body_text or not req.body_text.strip():
        raise HTTPException(status_code=422, detail="O corpo (body) é obrigatório.")

    # Variáveis {{n}} devem ser sequenciais (1..n) sem buraco.
    var_nums = [int(m) for m in re.findall(r'\{\{(\d+)\}\}', req.body_text)]
    unique_sorted = sorted(set(var_nums))
    expected = list(range(1, len(unique_sorted) + 1))
    if unique_sorted != expected:
        raise HTTPException(status_code=422, detail="Variáveis do corpo devem ser sequenciais começando em {{1}} sem pular números.")
    n_vars = len(unique_sorted)
    examples = [e for e in (req.body_examples or []) if e is not None and str(e).strip() != ""]
    if len(examples) != n_vars:
        raise HTTPException(status_code=422, detail=f"Forneça exatamente 1 valor de exemplo para cada variável ({n_vars} esperado(s), {len(examples)} recebido(s)).")

    # --- Monta components pro Meta ---
    components = []
    if req.header_text and req.header_text.strip():
        components.append({"type": "HEADER", "format": "TEXT", "text": req.header_text})

    body_component = {"type": "BODY", "text": req.body_text}
    if n_vars > 0:
        body_component["example"] = {"body_text": [examples]}
    components.append(body_component)

    if req.footer_text and req.footer_text.strip():
        components.append({"type": "FOOTER", "text": req.footer_text})

    if req.buttons:
        mapped_buttons = []
        for b in req.buttons:
            if b.type == "QUICK_REPLY":
                mapped_buttons.append({"type": "QUICK_REPLY", "text": b.text})
            elif b.type == "URL":
                mapped_buttons.append({"type": "URL", "text": b.text, "url": b.url})
            elif b.type == "PHONE_NUMBER":
                mapped_buttons.append({"type": "PHONE_NUMBER", "text": b.text, "phone_number": b.phone_number})
            else:
                raise HTTPException(status_code=422, detail=f"Tipo de botão inválido: {b.type}.")
        components.append({"type": "BUTTONS", "buttons": mapped_buttons})

    # --- Chama o Meta ---
    channel = await get_channel(channel_id, db)
    result = await create_template(
        channel.waba_id, channel.whatsapp_token,
        req.name, req.language, req.category, components,
    )

    # Erro do Meta: não grava nada, repassa a mensagem verbatim.
    if not result.get("id") or result.get("error"):
        err = result.get("error") or {}
        detail = err.get("error_user_msg") or err.get("message") or json.dumps(result, ensure_ascii=False)
        raise HTTPException(status_code=400, detail=detail)

    # Sucesso: registra auditoria local.
    tpl = WhatsappTemplate(
        channel_id=channel_id,
        name=req.name,
        language=req.language,
        category=req.category,
        components=json.dumps(components, ensure_ascii=False),
        meta_template_id=str(result["id"]),
        status=result.get("status", "PENDING"),
        created_by=current_admin.id,
        created_by_name=current_admin.name,
    )
    db.add(tpl)
    await db.commit()

    return {
        "id": result["id"],
        "name": req.name,
        "status": result.get("status", "PENDING"),
        "category": req.category,
    }


@router.get("/media/{media_id}")
async def get_media(media_id: str, channel_id: int = 1, db: AsyncSession = Depends(get_db)):
    import httpx
    channel = await get_channel(channel_id, db)

    # Passo 1: pegar URL da mídia
    async with httpx.AsyncClient() as client:
        url_response = await client.get(
            f"https://graph.facebook.com/v22.0/{media_id}",
            headers={"Authorization": f"Bearer {channel.whatsapp_token}"},
        )
        url_data = url_response.json()
        media_url = url_data.get("url")

        if not media_url:
            raise HTTPException(status_code=404, detail="Mídia não encontrada")

        # Passo 2: baixar mídia
        media_response = await client.get(
            media_url,
            headers={"Authorization": f"Bearer {channel.whatsapp_token}"},
        )

    from fastapi.responses import Response
    return Response(
        content=media_response.content,
        media_type=url_data.get("mime_type", "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


# === Course Aliases (Mapeamento de cursos) ===

@router.get("/course-aliases")
async def list_course_aliases(db: AsyncSession = Depends(get_db)):
    """Lista todos os mapeamentos de cursos."""
    result = await db.execute(select(CourseAlias).where(CourseAlias.is_active == True).order_by(CourseAlias.short_name))
    aliases = result.scalars().all()
    return [
        {
            "id": a.id,
            "alias": a.alias,
            "full_name": a.full_name,
            "short_name": a.short_name,
            "is_active": a.is_active,
        }
        for a in aliases
    ]


@router.get("/course-aliases/resolve/{alias}")
async def resolve_course_alias(alias: str, db: AsyncSession = Depends(get_db)):
    """Resolve um alias para o nome completo do curso."""
    result = await db.execute(
        select(CourseAlias).where(
            func.lower(CourseAlias.alias) == func.lower(alias),
            CourseAlias.is_active == True,
        )
    )
    course = result.scalar_one_or_none()
    if not course:
        return {"alias": alias, "full_name": alias, "short_name": alias, "found": False}
    return {
        "alias": course.alias,
        "full_name": course.full_name,
        "short_name": course.short_name,
        "found": True,
    }


async def resolve_course_name(alias: str, db: AsyncSession) -> str:
    """Helper interno: retorna short_name se existir, senão retorna o alias original."""
    result = await db.execute(
        select(CourseAlias).where(
            func.lower(CourseAlias.alias) == func.lower(alias),
            CourseAlias.is_active == True,
        )
    )
    course = result.scalar_one_or_none()
    return course.short_name if course else alias


@router.get("/notifications")
async def list_notifications(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models import Notification
    result = await db.execute(
        select(Notification).where(Notification.user_id == current_user.id).order_by(Notification.created_at.desc()).limit(50)
    )
    items = result.scalars().all()
    unread = await db.execute(
        select(func.count(Notification.id)).where(Notification.user_id == current_user.id, Notification.is_read == False)
    )
    return {
        "unread_count": unread.scalar() or 0,
        "items": [
            {
                "id": n.id,
                "contact_wa_id": n.contact_wa_id,
                "type": n.type,
                "title": n.title,
                "body": n.body,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in items
        ],
    }


@router.post("/notifications/{notif_id}/read")
async def read_notification(notif_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models import Notification
    from sqlalchemy import update
    await db.execute(
        update(Notification).where(Notification.id == notif_id, Notification.user_id == current_user.id).values(is_read=True)
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/notifications/read-all")
async def read_all_notifications(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models import Notification
    from sqlalchemy import update
    await db.execute(
        update(Notification).where(Notification.user_id == current_user.id, Notification.is_read == False).values(is_read=True)
    )
    await db.commit()
    return {"status": "ok"}


class ScheduleMessageRequest(BaseModel):
    template_name: str
    language: str = "pt_BR"
    channel_id: int = 1
    param_mappings: Optional[list] = None
    lead_ids: list = []
    scheduled_at: str


@router.post("/scheduled-messages")
async def create_scheduled_message(req: ScheduleMessageRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    import json
    from app.models import ScheduledMessage
    if not req.template_name or not req.lead_ids:
        raise HTTPException(status_code=400, detail="template_name e lead_ids são obrigatórios")

    # ⛔ TRAVA ÚNICA: recusa na CRIAÇÃO do agendamento, não 60s depois na execução.
    await bloquear_se_boas_vindas(req.template_name, db)

    try:
        dt = datetime.fromisoformat(req.scheduled_at)
        if dt.tzinfo is not None:
            dt = dt.astimezone(SP_TZ).replace(tzinfo=None)
    except Exception:
        raise HTTPException(status_code=400, detail="Data/hora inválida")
    now = datetime.now(SP_TZ).replace(tzinfo=None)
    if dt <= now:
        raise HTTPException(status_code=400, detail="O horário precisa ser no futuro")
    sm = ScheduledMessage(
        template_name=req.template_name,
        language=req.language,
        channel_id=req.channel_id,
        param_mappings=json.dumps(req.param_mappings) if req.param_mappings else None,
        lead_ids=json.dumps(req.lead_ids),
        scheduled_at=dt,
        status="pending",
        created_by=current_user.id,
        created_by_name=current_user.name,
        lead_count=len(req.lead_ids),
    )
    db.add(sm)
    await db.commit()
    await db.refresh(sm)
    return {"id": sm.id, "scheduled_at": sm.scheduled_at.isoformat(), "status": sm.status}


@router.get("/scheduled-messages")
async def list_scheduled_messages(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models import ScheduledMessage
    result = await db.execute(
        select(ScheduledMessage).order_by(ScheduledMessage.scheduled_at.desc()).limit(100)
    )
    items = result.scalars().all()
    return [
        {
            "id": s.id,
            "template_name": s.template_name,
            "channel_id": s.channel_id,
            "scheduled_at": s.scheduled_at.isoformat() if s.scheduled_at else None,
            "status": s.status,
            "created_by_name": s.created_by_name,
            "lead_count": s.lead_count,
            "sent_at": s.sent_at.isoformat() if s.sent_at else None,
        }
        for s in items
    ]


@router.post("/scheduled-messages/{sched_id}/cancel")
async def cancel_scheduled_message(sched_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models import ScheduledMessage
    result = await db.execute(select(ScheduledMessage).where(ScheduledMessage.id == sched_id))
    sm = result.scalar_one_or_none()
    if not sm:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    if sm.status != "pending":
        raise HTTPException(status_code=400, detail="Só dá pra cancelar agendamentos pendentes")
    sm.status = "cancelled"
    await db.commit()
    return {"status": "cancelled"}