import os
import httpx
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import (ExactLead, Contact, Channel, Message, AIConversationSummary,
                        AutoWelcomeConfig, NatConfig, ExactStageEvent)
from app.whatsapp import send_template_message
from app.course_names import resolve_course_name
from app.nomes import primeiro_nome
from app.date_parse import parse_datetime

BASE_URL = "https://api.exactspotter.com/v3"

# Canal, template e idioma da boas-vindas vêm de auto_welcome_config (tela), NÃO de constante.
# As antigas AI_CHANNEL_ID=2 / AUTO_TEMPLATE_NAME="mensagens_de_boas_vindas" foram removidas:
# apontavam para um canal e um template que não existem — causa da falha silenciosa.


def _parse_ids(env_value: str) -> set:
    return {int(x) for x in (env_value or "").split(",") if x.strip().isdigit()}


# Funis que RECEBEM welcome + IA + card (tratados como pós). Funil-Isa (25588) conta como pós.
POS_FUNNEL_IDS = _parse_ids(os.getenv("POS_FUNNEL_IDS", "18535,18537,25588"))
# Funis que entram no banco (ingestão). Vazio = puxa TODOS os funis da Exact.
# Pode-se restringir definindo INGEST_FUNNEL_IDS no ambiente (lista separada por vírgula).
INGEST_FUNNEL_IDS = _parse_ids(os.getenv("INGEST_FUNNEL_IDS", ""))

# ID do usuário para comentários na timeline (Victória Amorim)
EXACT_BOT_USER_ID = 415875


def _funnels_from_config(cfg) -> set:
    """CSV da config -> set de ints. Fallback para POS_FUNNEL_IDS."""
    if cfg and cfg.funnel_ids:
        parsed = {int(x) for x in cfg.funnel_ids.split(",") if x.strip().isdigit()}
        if parsed:
            return parsed
    return POS_FUNNEL_IDS


async def get_auto_welcome_config(db: AsyncSession):
    """Retorna a linha singleton (id=1) de auto_welcome_config, ou None."""
    try:
        res = await db.execute(select(AutoWelcomeConfig).where(AutoWelcomeConfig.id == 1))
        return res.scalar_one_or_none()
    except Exception:
        return None  # sem config = DESLIGADO (na dúvida, não envia)


async def add_timeline_comment(lead_id: int, text: str, *, timeout: float = 15):
    """Insere comentário na timeline do lead na Exact Spotter.

    `timeout` é parâmetro para o chamador poder ser mais impaciente que o default. O default
    segue 15s para não mudar o comportamento de quem já chamava (ai_engine, no resumo do
    atendimento, que roda fora de qualquer caminho crítico). O fluxo NAT passa 5s: ele roda
    DENTRO do processamento do webhook da Meta, e a Exact fora do ar não pode segurar o lote
    de mensagens de todos os leads por 15s.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
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


# parse_datetime foi movida para app/date_parse.py — módulo neutro, só stdlib. O backfill
# precisa do MESMO parser sem importar este arquivo, que carrega send_template_message no topo.
# O nome segue exportado aqui: `from app.exact_spotter import parse_datetime` continua válido.


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


async def _agente_assume_a_abertura(db: AsyncSession) -> bool:
    """O agente de pré-qualificação está ligado? Falha fechada: erro = False.

    Lido UMA vez por lead e usado em DOIS pontos de `send_welcome_to_new_lead` (o passo 1 e
    o 4.5). Tem que ser o mesmo valor nos dois: se o passo 1 deixasse passar por causa do
    agente e o 4.5 decidisse o contrário, o lead cairia no envio da boas-vindas com a
    automação desligada — exatamente o que o passo 1 existe para impedir.
    """
    try:
        cfg = (await db.execute(select(NatConfig).where(NatConfig.id == 1))
               ).scalar_one_or_none()
        return bool(cfg is not None and cfg.qualificacao_enabled)
    except Exception as e:
        print(f"⚠️  Agente: não consegui ler nat_config ({type(e).__name__}: {e}) — "
              "boas-vindas segue o caminho normal")
        return False


async def send_welcome_to_new_lead(lead_data: dict, db: AsyncSession, config, *,
                                   force: bool = False) -> dict:
    """Envia boas-vindas + ativa IA + cria card. Retorna a decisão tomada.

    Retorno: {exact_id, name, status: 'sent'|'skipped'|'failed', reason, detail}

    REGRA Nº 1: cada lead tem UMA única chance — o momento em que é ingerido. Todo caminho de
    saída CARIMBA a decisão em welcome_status, inclusive "automação desligada". Assim, um lead
    ingerido com o botão desligado fica permanentemente marcado e NUNCA recebe retroativamente
    quando alguém ligar a automação.

    force=True (reenvio manual individual) é a ÚNICA porta que ignora enabled/funil/idempotência.
    """
    exact_id = lead_data.get("exact_id")
    name = lead_data.get("name", "") or ""

    def result(status, reason, detail=None):
        return {"exact_id": exact_id, "name": name, "status": status,
                "reason": reason, "detail": detail}

    # 0) BUSCAR O LEAD PRIMEIRO — para poder carimbar em QUALQUER saída.
    lead_row = None
    if exact_id is not None:
        lr = await db.execute(select(ExactLead).where(ExactLead.exact_id == exact_id))
        lead_row = lr.scalar_one_or_none()

    def stamp(status: str, error):
        if lead_row is not None:
            lead_row.welcome_status = status
            lead_row.welcome_error = error

    # A boas-vindas e o AGENTE são dois donos possíveis da mesma abertura, e este é o
    # ponto onde se decide qual dos dois atende este lead. Lido antes do passo 1 porque o
    # passo 1 pode sair da função — e sair dali com o agente ligado significaria que os
    # leads do sync não receberiam abertura NENHUMA.
    agente_ligado = False if force else await _agente_assume_a_abertura(db)

    # 1) LIGA/DESLIGA — carimba, para nunca receber retroativamente.
    #
    # `agente_ligado` segura este return: com a boas-vindas desligada E o agente ligado, o
    # lead PRECISA seguir até o passo 4.5. Foi o que faltou quando a automação foi desligada
    # em 24/08 — o checklist de ativação do agente manda desligá-la, e sem esta condição
    # seguir o checklist desativaria a metade do agente que atende os leads do sync.
    if not force and not agente_ligado and (config is None or not config.enabled):
        stamp("skipped", "automação desligada — lead anterior à ativação")
        return result("skipped", "disabled")

    # 2) GUARDRAIL DE FUNIL — carimba.
    funnels = _funnels_from_config(config)
    if not force and lead_data.get("funnel_id") not in funnels:
        stamp("skipped", f"funil {lead_data.get('funnel_id')} fora do escopo")
        return result("skipped", "not_pos_funnel")

    # 3) IDEMPOTÊNCIA — usa welcome_status (NÃO welcome_sent_at): quem foi pulado também
    #    já teve sua decisão registrada. Não re-carimbar: preserva o motivo original.
    if not force and lead_row is not None and lead_row.welcome_status is not None:
        return result("skipped", "already_processed")

    # 4) TELEFONE
    phone = format_phone(lead_data.get("phone1", ""))
    if not phone or len(phone) < 12:
        stamp("skipped", "sem telefone válido")
        return result("skipped", "no_phone")

    # 4.5) UM DONO POR ABERTURA.
    #
    # Com o agente de pré-qualificação ligado, ele SUBSTITUI a boas-vindas para os leads que
    # chegam pelo sync — os da landing page já foram enfileirados no POST, 5 minutos antes.
    # Sem esta troca, o lead receberia DUAS aberturas diferentes do mesmo número: a
    # `nat_boasvindas` ("posso falar agora?") e a do agente. Foi o mesmo problema que o
    # `boas_vindas_wamid` resolveu entre a boas-vindas e a NAT.
    #
    # O CARIMBO É O DE SEMPRE. `welcome_status` continua sendo a trava permanente de
    # idempotência (passo 3 acima testa `is not null`), então um lead que o agente assumiu
    # NUNCA volta a ser candidato à boas-vindas — nem se o agente for desligado depois.
    # Reaproveitar o carimbo em vez de criar outro é o que garante que os dois caminhos
    # compartilham uma única verdade sobre "este lead já teve sua abertura decidida".
    #
    # `force=True` (reenvio manual, lead a lead) continua ignorando tudo isto, como já
    # ignora enabled, funil e idempotência.
    if agente_ligado:
        from app.models import ORIGEM_EXACT
        from app.qualificacao_gatilho import agendar_abertura
        # register_date já é UTC; o gatilho soma 3h a quem vem em SP, então descontamos aqui
        # para o valor chegar certo do outro lado.
        from app.qualificacao_gatilho import MOTIVO_ERRO, MOTIVO_SEM_TELEFONE
        nascido = lead_data.get("register_date")
        enfileirou, motivo = await agendar_abertura(
            db, telefone=phone, lead_id=exact_id, origem=ORIGEM_EXACT,
            nascido_em=(nascido - timedelta(hours=3)) if nascido else None)

        # O CARIMBO TEM QUE DIZER A VERDADE, porque ele é irreversível: `welcome_status`
        # não-nulo é a trava de idempotência do passo 3, e um lead carimbado nunca volta a
        # ser candidato — nem à boas-vindas, nem ao agente. Carimbar "o agente assumiu" em
        # cima de um gatilho que NÃO enfileirou fecha a porta do lead pelos dois lados, e o
        # deixa indistinguível dos leads realmente atendidos.
        #
        # `já tem estado` é o único False benigno: a pessoa está sendo atendida agora, e o
        # carimbo de "assumido" é literalmente verdadeiro.
        if not enfileirou and motivo.startswith((MOTIVO_ERRO, MOTIVO_SEM_TELEFONE)):
            stamp("failed", f"agente ligado, mas a abertura não foi enfileirada: {motivo}")
            print(f"⛔ Agente NÃO assumiu {name} ({phone}) — {motivo}")
            return result("failed", "gatilho_falhou", motivo)

        stamp("skipped", f"agente de pré-qualificação assumiu a abertura ({motivo})")
        print(f"🤝 Boas-vindas cedida ao agente para {name} ({phone}) — {motivo}")
        return result("skipped", "agente_assumiu")

    # 5) CANAL — SEMPRE da config. Sem fallback para constante.
    channel_id = config.channel_id if (config and config.channel_id) else None
    if channel_id is None:
        stamp("failed", "canal não configurado no painel")
        return result("failed", "no_channel", "config.channel_id está NULL")

    ch = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = ch.scalar_one_or_none()
    if not channel:
        detail = f"canal id={channel_id} não existe"
        stamp("failed", detail)
        return result("failed", "no_channel", detail)

    # 6) TEMPLATE — da config, sem fallback para constante.
    template_name = config.template_name
    template_lang = config.template_language or "pt_BR"
    if not template_name:
        stamp("failed", "template não configurado no painel")
        return result("failed", "no_template", "config.template_name vazio")

    course = await resolve_course_name(lead_data.get("sub_source", ""), db)
    # SÓ para as variáveis da mensagem. `name` (cadastro completo) segue indo para o
    # Contact e para o card do Kanban, que é onde o SDR precisa do nome inteiro.
    nome_curto = primeiro_nome(name)

    from app.whatsapp import fetch_template_body, render_template_text
    auto_template_body = await fetch_template_body(
        channel.waba_id, channel.whatsapp_token, template_name, template_lang)
    if auto_template_body is None:
        detail = f"template '{template_name}'/{template_lang} não encontrado no WABA"
        stamp("failed", detail)
        return result("failed", "template_not_found", detail)  # nada de falha silenciosa

    try:
        send_result = await send_template_message(
            to=phone,
            template_name=template_name,
            language=template_lang,
            phone_number_id=channel.phone_number_id,
            token=channel.whatsapp_token,
            parameters=[nome_curto, course],
        )

        if "messages" not in send_result:
            detail = str(send_result)
            stamp("failed", detail[:1000])
            return result("failed", "meta_error", detail)

        # Criar ou atualizar contato + vincular SDR do Exact (comportamento mantido).
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
                channel_id=channel_id,
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

        # Salvar mensagem do template.
        #
        # `timezone` e `timedelta` vêm do TOPO do módulo, e isto não é estilo: um
        # `from datetime import timedelta` AQUI torna `timedelta` local à função INTEIRA, e
        # o passo 4.5 — 80 linhas acima — passa a levantar UnboundLocalError antes de
        # qualquer atribuição. Foi exatamente o que derrubou o laço de boas-vindas do sync
        # em 25/08: `local variable 'timedelta' referenced before assignment`.
        SP_TZ = timezone(timedelta(hours=-3))

        welcome_wamid = send_result["messages"][0]["id"]

        db.add(Message(
            wa_message_id=welcome_wamid,
            contact_wa_id=phone,
            channel_id=channel_id,
            direction="outbound",
            message_type="template",
            content=(render_template_text(auto_template_body, [nome_curto, course])
                     or f"[Template] {nome_curto}, {course}"),
            timestamp=datetime.now(SP_TZ).replace(tzinfo=None),
            status="sent",
        ))

        # Card no Kanban — checar duplicata antes (protege o reenvio manual com force=True).
        ex = await db.execute(
            select(AIConversationSummary).where(AIConversationSummary.contact_wa_id == phone))
        if ex.scalar_one_or_none() is None:
            db.add(AIConversationSummary(
                contact_wa_id=phone,
                channel_id=channel_id,
                status="em_atendimento_ia",
                lead_name=name,
                lead_course=course,
                ai_messages_count=0,
            ))

        # Carimbo de sucesso — welcome_sent_at SÓ aqui (envio real).
        #
        # ATENÇÃO AO QUE 'sent' SIGNIFICA AQUI: a Meta ACEITOU a mensagem, não que o lead a
        # recebeu. A entrega (ou a recusa) chega depois, assíncrona, pelo webhook de status.
        # welcome_wamid é o que permite àquele webhook achar este lead e corrigir o carimbo
        # para 'failed' ou 'delivered' — sem ele o 'sent' era permanente e mentiroso.
        if lead_row is not None:
            lead_row.welcome_sent_at = datetime.now(SP_TZ).replace(tzinfo=None)
            lead_row.welcome_status = "sent"
            lead_row.welcome_error = None
            lead_row.welcome_wamid = welcome_wamid

        # PONTO DE ENTRADA DO FLUXO NAT.
        #
        # Só depois do envio ter dado certo e do contato existir — iniciar_fluxo_nat precisa
        # do Contact para checar assigned_to.
        #
        # Passa lead_row (o ExactLead) e não lead_data: a trava de data lê register_date, que
        # o dict montado pelo sync não carrega. Com o dict, nat_pode_atuar bloquearia sempre
        # por "register_date ausente" — falha fechada correta, mas pelo motivo errado, e a NAT
        # nunca sairia do lugar depois de ligada.
        #
        # Guardado por nat_pode_atuar: com a NAT desligada isto é no-op puro. Dentro de
        # SAVEPOINT porque falha aqui não pode desfazer o carimbo de welcome_status nem o
        # registro da mensagem que JÁ saiu para o lead.
        #
        # boas_vindas_wamid É O QUE IMPEDE O ENVIO DUPLICADO. O template acabou de sair, dez
        # linhas acima; passar o wamid diz a iniciar_fluxo_nat "a nat_boasvindas já está com o
        # lead, só adote o estado". Sem ele, a NAT mandava o MESMO template outra vez — a
        # janela de 24h está fechada para um lead novo, então o sender caía no ramo de
        # template e repetia a mensagem. Ver o docstring de iniciar_fluxo_nat.
        try:
            async with db.begin_nested():
                from app.nat_flow import iniciar_fluxo_nat
                await iniciar_fluxo_nat(lead_row if lead_row is not None else lead_data, db,
                                        boas_vindas_wamid=welcome_wamid)
        except Exception as e:
            print(f"⚠️  NAT: fluxo não iniciado para {phone}: {type(e).__name__}: {e}")

        print(f"🤖 Boas-vindas enviada para {name} ({phone}) - Curso: {course}")
        return result("sent", "ok")

    except Exception as e:
        detail = str(e)
        stamp("failed", detail[:1000])
        print(f"❌ Erro ao enviar welcome para {name}: {detail}")
        return result("failed", "exception", detail)


async def _registrar_transicao(db: AsyncSession, exact_id, de, para, funnel_id) -> None:
    """Grava uma mudança de estágio em `exact_stage_events`. NUNCA levanta.

    SAVEPOINT + except largo, e o motivo é o mesmo dos savepoints do webhook: este INSERT é
    a fundação de uma régua que ainda nem existe, e o `sync_exact_leads` é o que alimenta
    boas-vindas, agente e todo o espelho de leads. Um erro aqui — coluna faltando, tipo
    inesperado, o que for — não pode derrubar o sync inteiro e deixar a base congelada.

    Try/except puro não bastaria: um IntegrityError deixaria a transação do asyncpg em
    estado abortado e TODA operação seguinte da mesma sessão falharia com
    InFailedSQLTransaction — inclusive o `setattr` dos 9.133 leads. O SAVEPOINT é o que
    permite reverter só este INSERT.

    A falha é RUIDOSA de propósito. Perder um evento em silêncio significa uma transição que
    a régua nunca vai ver, e um lead que nunca recebe o follow que deveria.
    """
    try:
        async with db.begin_nested():
            db.add(ExactStageEvent(exact_lead_id=exact_id, stage_de=de, stage_para=para,
                                   funnel_id=funnel_id))
    except Exception as e:
        print(f"⚠️  TRANSIÇÃO NÃO REGISTRADA lead={exact_id} {de!r}→{para!r}: "
              f"{type(e).__name__}: {e}")


async def sync_exact_leads(db: AsyncSession):
    """Sincroniza leads de pós do Exact Spotter com o banco local."""
    skip = 0
    top = 500
    total_synced = 0
    total_new = 0
    total_updated = 0
    new_leads_to_contact = []

    # Config lida UMA vez por sync (canal, template, funis, liga/desliga).
    config = await get_auto_welcome_config(db)
    funnels = _funnels_from_config(config)

    while True:
        data = await fetch_leads_from_exact(skip=skip, top=top)
        leads = data.get("value", [])

        if not leads:
            break

        for lead in leads:
            # Ingestão de TODOS os funis da Exact. Se INGEST_FUNNEL_IDS estiver
            # configurado (não-vazio), restringe; vazio = puxa todos os funis.
            if INGEST_FUNNEL_IDS and lead.get("funnelId") not in INGEST_FUNNEL_IDS:
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
                # TRANSIÇÃO DE ESTÁGIO — tem que ser lida ANTES do setattr, que sobrescreve.
                #
                # É a fundação da cadência de follow-up: sem isto, `exact_leads.stage` é uma
                # coluna só e não há como distinguir "entrou em Follow 1 agora" de "está em
                # Follow 1 há três semanas". Uma régua que dispare sobre ESTADO varreria de
                # uma vez os leads parados nos follows.
                #
                # Custo no caminho quente: o INSERT só acontece na MUDANÇA real (~20/dia
                # medido em 18535), não nas 9.133 linhas que o laço reescreve a cada 600s.
                if existing.stage != lead_data.get("stage"):
                    await _registrar_transicao(
                        db, exact_id, existing.stage, lead_data.get("stage"),
                        lead_data.get("funnel_id"))
                for key, value in lead_data.items():
                    setattr(existing, key, value)
                existing.synced_at = datetime.utcnow()
                total_updated += 1
            else:
                new_lead = ExactLead(exact_id=exact_id, **lead_data)
                db.add(new_lead)
                total_new += 1
                # exact_id entra no dict SÓ DEPOIS de construir o ExactLead (senão viria
                # duplicado no kwargs). É essencial para o carimbo do welcome_status.
                lead_data["exact_id"] = exact_id
                # Primeira aparição: evento com `stage_de = NULL`. O NULL é informação, não
                # ausência — a régua precisa distinguir "nasceu em Follow 1" de "migrou para
                # Follow 1", que são gatilhos diferentes.
                await _registrar_transicao(db, exact_id, None, lead_data.get("stage"),
                                           lead_data.get("funnel_id"))
                # Só lead NOVO é candidato. Lead já existente cai no ramo de update acima e
                # nunca é enfileirado — os antigos jamais entram aqui.
                if lead_data.get("funnel_id") in funnels:
                    new_leads_to_contact.append(lead_data)

            total_synced += 1

        if len(leads) < top:
            break

        skip += top

    await db.commit()

    # Boas-vindas para leads novos. Cada chamada decide e CARIMBA (inclusive quando pula).
    #
    # UM LEAD NÃO DERRUBA O LOTE. Sem este isolamento, a primeira exceção inesperada aqui
    # aborta o `sync_exact_leads` inteiro — e o estrago é PERMANENTE, não passageiro: os
    # leads já foram commitados no `db.commit()` logo acima, então na passada seguinte todos
    # caem no ramo `existing` e nunca mais voltam a ser candidatos. Ficam com
    # `welcome_status` NULL para sempre, invisíveis para a boas-vindas E para o agente.
    #
    # Foi o que aconteceu em 25/08: um UnboundLocalError no passo 4.5 (`timedelta`
    # sombreado por um import local) matou o laço na PRIMEIRA iteração, e 42 leads do dia
    # entraram no banco sem carimbo e sem abertura nenhuma.
    #
    # SAVEPOINT e não try/except puro, mesmo motivo de `_registrar_transicao`: um erro de
    # banco deixaria a transação do asyncpg abortada e TODA operação seguinte da mesma
    # sessão falharia com InFailedSQLTransaction — inclusive os carimbos dos leads restantes.
    welcome_results = []
    for lead_data in new_leads_to_contact:
        try:
            async with db.begin_nested():
                welcome_results.append(await send_welcome_to_new_lead(lead_data, db, config))
        except Exception as e:
            # O lead segue com `welcome_status` NULL e NÃO volta na próxima passada (já é
            # `existing`). Este log é a única trilha que resta — por isso vai o exact_id e o
            # nome, que é o que permite recuperar o lead à mão.
            print(f"❌ Boas-vindas ABORTOU no lead {lead_data.get('exact_id')} "
                  f"({lead_data.get('name')!r}) — sem carimbo e sem abertura, NÃO será "
                  f"retentado. {type(e).__name__}: {e}")
            welcome_results.append({"exact_id": lead_data.get("exact_id"),
                                    "name": lead_data.get("name", ""), "status": "failed",
                                    "reason": "excecao_no_laco", "detail": f"{type(e).__name__}: {e}"})

    await db.commit()

    # Relatório honesto: conta o RESULTADO real, nunca o número de enfileirados.
    sent = sum(1 for r in welcome_results if r["status"] == "sent")
    skipped = sum(1 for r in welcome_results if r["status"] == "skipped")
    failed = sum(1 for r in welcome_results if r["status"] == "failed")
    by_reason = {}
    for r in welcome_results:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1

    return {
        "total_synced": total_synced,
        "new": total_new,
        "updated": total_updated,
        "welcome_sent": sent,  # compat: agora é o número REAL de envios
        "welcome": {
            "queued": len(new_leads_to_contact),
            "sent": sent,
            "skipped": skipped,
            "failed": failed,
            "by_reason": by_reason,
            "errors": [{"name": r["name"], "reason": r["reason"], "detail": r["detail"]}
                       for r in welcome_results if r["status"] == "failed"][:50],
        },
    }