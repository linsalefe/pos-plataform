"""Máquina de estados do fluxo NAT — Cenário 1.

Aqui mora "QUANDO a NAT fala e para onde o lead vai depois". O "COMO ela fala" (template vs.
texto livre, credencial, janela de 24h) é do nat_sender.

Transições implementadas:

  gatilho                        origem                 ação                          destino
  ---------------------------------------------------------------------------------------------
  lead entra, dentro do horário  —                      envia nat_boasvindas          aguardando_resposta
  lead entra, fora do horário    —                      NADA                          aguardando_horario
  payload NAT_SIM                aguardando_resposta    envia nat_sim                 aguardando_motivacao
  payload NAT_OUTRO_HORARIO      aguardando_resposta    envia nat_outro_horario       reagendado
  texto qualquer                 aguardando_motivacao   envia confirma_transferencia  aguardando_ligacao
  texto qualquer                 reagendado             grava horário preferencial    reagendado
  qualquer outro                 qualquer               nada, só loga                 inalterado

Duas regras que valem para tudo neste módulo:

  * IDEMPOTÊNCIA. A Meta reentrega webhook. Antes de agir, comparamos o wa_message_id que
    chegou com nat_flow_state.ultimo_wa_message_id; se for o mesmo, já foi processado e a
    função retorna sem enviar nada e sem mexer no estado. O estado só avança DEPOIS do envio
    dar certo — assim uma falha de rede não deixa o lead num estado que afirma uma mensagem
    que ele nunca recebeu.

  * CLIQUE FORA DA ETAPA NÃO FAZ NADA. Um "Sim" clicado quando o lead já está em
    aguardando_ligacao é ruído (lead rolou a conversa e clicou no botão antigo) — reprocessar
    mandaria o fluxo para trás e o lead receberia de novo uma mensagem que já recebeu.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import nat_copy
from app.models import (ETAPA_AGUARDANDO_HORARIO, ETAPA_AGUARDANDO_LIGACAO,
                        ETAPA_AGUARDANDO_MOTIVACAO, ETAPA_AGUARDANDO_RESPOSTA,
                        ETAPA_REAGENDADO, KIND_SLA_CHECK, Contact, ExactLead, Notification,
                        NatFlowState, User)
from app.nat_guard import (GESTOR_USER_ID, _agora_sp, dentro_horario_comercial,
                           nat_pode_atuar)
from app.nat_sender import send_nat_message

# ------------------------------------------------------------------------------------------
# TRANSFERÊNCIA PARA O SDR (Bloco 5)
# ------------------------------------------------------------------------------------------
# Quanto tempo o SDR dono tem para clicar em "Assumir ligação" antes de o SLA escalonar.
# Usado aqui (agendamento) e em nat_sla (reagendamento do nível 1) — uma definição só.
SLA_LIGACAO_MINUTOS = 2

TIPO_NOTIF_TRANSFERENCIA = "nat_transferencia"

# A Exact roda dentro do processamento do webhook. 5s em vez do default de 15s: com a Exact
# fora do ar, 15s segurariam o lote de mensagens de TODOS os leads daquele webhook.
TIMEOUT_TIMELINE_SEGUNDOS = 5

# Teto do trecho da resposta do lead que entra na notificação e na timeline. O corpo do sino
# já é truncado em ~50 caracteres pelo CSS; o resto é para o popup do navegador e a timeline.
MAX_CHARS_RESPOSTA = 140


async def _estado_do_contato(contact_wa_id: str, db: AsyncSession):
    res = await db.execute(
        select(NatFlowState).where(NatFlowState.contact_wa_id == contact_wa_id))
    return res.scalar_one_or_none()


async def _dados_do_lead(state: NatFlowState, db: AsyncSession) -> dict:
    """nome/curso/formacao para preencher a mensagem.

    O exact_lead_id foi gravado em iniciar_fluxo_nat justamente para não precisar varrer
    exact_leads por telefone a cada passo do fluxo.

    `formacao` volta sempre vazia por enquanto: no Exact ela não é campo estruturado, só texto
    livre dentro de `description`, e extrair isso é Bloco 8. nat_copy já trata a ausência
    removendo a frase — não é buraco, é decisão.
    """
    from app.exact_spotter import resolve_course_name

    nome, curso = "", ""

    if state.exact_lead_id is not None:
        res = await db.execute(
            select(ExactLead).where(ExactLead.exact_id == state.exact_lead_id))
        lead = res.scalar_one_or_none()
        if lead is not None:
            nome = lead.name or ""
            curso = await resolve_course_name(lead.sub_source or "", db)

    if not nome:
        res = await db.execute(
            select(Contact.name).where(Contact.wa_id == state.contact_wa_id))
        row = res.first()
        nome = (row[0] if row else "") or ""

    return {"nome": nome, "curso": curso, "formacao": ""}


def _ja_processado(state: NatFlowState, wa_message_id: str) -> bool:
    """Trava de reentrega: mesmo wa_message_id que o último processado."""
    return bool(wa_message_id) and state.ultimo_wa_message_id == wa_message_id


def telefone_legivel(wa_id: str) -> str:
    """5511999998888 -> '+55 11 99999-8888'. Devolve o original se não reconhecer o formato.

    O SDR tem 2 minutos para ligar. Ler o número na notificação e digitar no telefone é parte
    desses 2 minutos, e '5511999998888' é mais lento de ler e mais fácil de errar.
    """
    digitos = "".join(c for c in (wa_id or "") if c.isdigit())
    if len(digitos) == 13 and digitos.startswith("55"):      # 55 + DDD + 9 dígitos
        return f"+55 {digitos[2:4]} {digitos[4:9]}-{digitos[9:]}"
    if len(digitos) == 12 and digitos.startswith("55"):      # 55 + DDD + 8 dígitos
        return f"+55 {digitos[2:4]} {digitos[4:8]}-{digitos[8:]}"
    return wa_id or ""


def _resumir(texto: str, limite: int = MAX_CHARS_RESPOSTA) -> str:
    """Uma linha, sem quebras, cortada com reticências. Nunca None."""
    limpo = " ".join((texto or "").split())
    return limpo if len(limpo) <= limite else limpo[:limite - 1] + "…"


def montar_notificacao_transferencia(nome: str, wa_id: str, curso: str, resposta: str,
                                     *, sem_sdr: bool = False) -> tuple[str, str]:
    """(title, body) da notificação de transferência.

    O FORMATO É DITADO PELO FRONTEND, não por gosto. Em NotificationBell.tsx:
      * o `title` (linha 211) NÃO é limitado — quebra linha e aparece INTEIRO;
      * o `body` (linha 214) é `line-clamp-2`: DUAS linhas num painel de 330px, o que cobre
        o corpo inteiro nos casos reais. Antes era `truncate` (uma linha, ~50 caracteres), e
        aí só o telefone e o começo do nome sobreviviam — o curso e a fala do lead ficavam
        fora, e o SDR precisava abrir a conversa dentro dos 2 minutos do SLA.

    Daí as duas decisões, que seguem valendo com duas linhas:
      1. TELEFONE NO TÍTULO, junto do nome. É o lugar garantidamente visível, e é o dado sem
         o qual o SDR não liga.
      2. TELEFONE NO COMEÇO DO CORPO, para ser a primeira coisa a sobrar em qualquer corte —
         inclusive no popup do navegador, cujo truncamento varia por sistema operacional e
         não está sob nosso controle.
    """
    fone = telefone_legivel(wa_id)
    quem = nome or "Lead sem nome"

    if sem_sdr:
        title = f"Ligar agora (SEM SDR): {quem} — {fone}"
    else:
        title = f"Ligar agora: {quem} — {fone}"

    partes = [fone]
    if curso:
        partes.append(curso)
    if resposta:
        partes.append(f'disse: "{_resumir(resposta)}"')
    if sem_sdr:
        partes.append("lead sem SDR atribuído — avisando a gestão")

    return title[:255], " · ".join(partes)


async def usuario_existe(user_id: int | None, db: AsyncSession) -> bool:
    """O id existe em `users`? None devolve False.

    Conferir antes de criar Notification não é zelo excessivo: notifications.user_id tem FK
    para users, e apontar para um id inexistente estoura IntegrityError — dentro de um
    savepoint cuja falha, por decisão do Bloco 5, cancela os passos seguintes. Melhor
    descobrir com um SELECT do que com um rollback.
    """
    if user_id is None:
        return False
    res = await db.execute(select(User.id).where(User.id == user_id))
    return res.first() is not None


async def _destinatario_da_transferencia(state: NatFlowState, db: AsyncSession):
    """(user_id, eh_fallback) de quem recebe a notificação. (None, _) se não há ninguém.

    O guard bloqueia lead sem SDR na ENTRADA do fluxo, mas `assigned_to` pode ser limpo entre
    a entrada e a transferência (troca de dono, correção manual na tela). Sem fallback, a
    notificação ficaria sem destinatário e o lead chegaria em aguardando_ligacao MUDO — que é
    o pior desfecho possível para um lead que acabou de dizer que quer ser ligado.

    A existência do usuário é CONFERIDA, não presumida: notifications.user_id tem FK para
    users, e apontar para um id que não existe estouraria IntegrityError no passo 1 —
    justamente o passo que, se falhar, cancela todos os outros.
    """
    if await usuario_existe(state.sdr_user_id, db):
        return state.sdr_user_id, False

    if await usuario_existe(GESTOR_USER_ID, db):
        print(f"⚠️  NAT: {state.contact_wa_id} chegou na transferência sem SDR válido "
              f"(sdr_user_id={state.sdr_user_id}) — notificando a gestão "
              f"(id={GESTOR_USER_ID})")
        return GESTOR_USER_ID, True

    return None, False


async def transferir_para_sdr(state: NatFlowState, resposta_do_lead: str,
                              wa_message_id: str, db: AsyncSession) -> bool:
    """Avisa quem tem que ligar, registra e arma o SLA. True se a notificação saiu.

    TRÊS passos, cada um no SEU savepoint (o quarto, estágio no Exact, caiu: a etapa
    "Aguardando Ligação" não existe em nenhum funil e a API não permite criá-la — ver
    RECON_NAT_FASE1_EXACT_20260726.md):

      1. NOTIFICAÇÃO ao SDR    — é ela que faz alguém ligar. Falhou, nada mais é tentado.
      2. transferido_em        — carimbo local, junto do passo 1 no mesmo savepoint por ser
                                 a mesma escrita lógica ("está transferido") e não custar rede.
      3. TIMELINE no Exact     — única chamada de rede. Falha é registrada e ignorada.
      4. sla_check em +2min    — o MAIS DESCARTÁVEL. Vai por último, sozinho no savepoint.

    A ordem é a ordem da importância, e os savepoints são separados justamente para que a
    falha de um passo não desfaça os anteriores — comprovado contra o Postgres no smoke da
    Fase 3, onde um IntegrityError no agendamento deixou o passo anterior intacto e commitado.

    NÃO altera `etapa`: quem avança a máquina de estados é processar_texto, e só depois de o
    envio ao lead ter dado certo. Esta função é o efeito colateral da transição, não a
    transição.
    """
    wa_id = state.contact_wa_id
    dados = await _dados_do_lead(state, db)

    # ---- PASSO 1: notificação (+ carimbo) — se falhar, aborta o resto ----
    destinatario, eh_fallback = await _destinatario_da_transferencia(state, db)
    if destinatario is None:
        print(f"❌ NAT: transferência de {wa_id} sem destinatário possível "
              f"(sdr_user_id={state.sdr_user_id}, gestor id={GESTOR_USER_ID} não existe) — "
              "nada notificado, timeline e SLA não tentados")
        return False

    title, body = montar_notificacao_transferencia(
        dados["nome"], wa_id, dados["curso"], resposta_do_lead, sem_sdr=eh_fallback)

    try:
        async with db.begin_nested():
            db.add(Notification(
                user_id=destinatario,
                contact_wa_id=wa_id,
                type=TIPO_NOTIF_TRANSFERENCIA,
                # ref = a mensagem do lead que disparou a transferência. Dá idempotência se
                # este caminho for reexecutado, no mesmo espírito do ref de window_alerts_job.
                ref=wa_message_id,
                title=title,
                body=body,
            ))
            state.transferido_em = _agora_sp()
        print(f"🔔 NAT: transferência de {wa_id} notificada para user {destinatario}"
              f"{' (FALLBACK gestão)' if eh_fallback else ''}: {title}")
    except Exception as e:
        print(f"❌ NAT: notificação de transferência FALHOU para {wa_id} "
              f"({type(e).__name__}: {e}) — timeline e SLA não serão tentados")
        return False

    # ---- PASSO 2: anotação na timeline do Exact ----
    if state.exact_lead_id is None:
        print(f"↩️  NAT: {wa_id} sem exact_lead_id — timeline não anotada")
    else:
        try:
            async with db.begin_nested():
                from app.exact_spotter import add_timeline_comment
                quando = state.transferido_em
                texto = (
                    f"NAT transferiu o lead para ligação do SDR em "
                    f"{quando:%d/%m/%Y às %H:%M} (horário de Brasília). "
                    f"Lead confirmou interesse e disse: \"{_resumir(resposta_do_lead)}\". "
                    f"SLA de {SLA_LIGACAO_MINUTOS} minutos para o primeiro contato."
                )
                await add_timeline_comment(state.exact_lead_id, texto,
                                           timeout=TIMEOUT_TIMELINE_SEGUNDOS)
        except Exception as e:
            # add_timeline_comment já engole a própria exceção e devolve False; isto aqui é a
            # rede para o que ela não prevê. Falha na Exact não pode custar a transferência,
            # que já está notificada e carimbada.
            print(f"⚠️  NAT: timeline do Exact não anotada para {wa_id} "
                  f"({type(e).__name__}: {e}) — transferência segue válida")

    # ---- PASSO 3: SLA. O mais descartável, sozinho no savepoint. ----
    try:
        async with db.begin_nested():
            from app.nat_scheduler import agendar
            await agendar(
                KIND_SLA_CHECK, wa_id,
                _agora_sp() + timedelta(minutes=SLA_LIGACAO_MINUTOS),
                {"notificado": destinatario, "fallback_gestao": eh_fallback},
                db,
            )
    except Exception as e:
        print(f"⚠️  NAT: sla_check NÃO agendado para {wa_id} ({type(e).__name__}: {e}) — "
              "a notificação ao SDR permanece, mas NÃO haverá escalonamento automático")

    return True


async def iniciar_fluxo_nat(lead, db: AsyncSession) -> str | None:
    """Cria o estado inicial do lead. Retorna a etapa criada, ou None se a NAT não atuou.

    `lead` é um ExactLead ou o dict lead_data que o sync monta.

    Fora do horário comercial NÃO envia nada — o lead fica em aguardando_horario, que é a fila
    que a fase 2 do Cenário 2 (fora de escopo) vai varrer às 09h.
    """
    from app.exact_spotter import format_phone

    try:
        pode, motivo = await nat_pode_atuar(lead, db)
        if not pode:
            print(f"🔒 NAT não iniciou fluxo: {motivo}")
            return None

        if isinstance(lead, ExactLead):
            wa_id = format_phone(lead.phone1 or "")
            exact_lead_id, nome, sub_source = lead.exact_id, lead.name or "", lead.sub_source
        else:
            wa_id = format_phone(lead.get("phone1", "") or "")
            exact_lead_id = lead.get("exact_id")
            nome = lead.get("name", "") or ""
            sub_source = lead.get("sub_source")

        if not wa_id:
            print("🔒 NAT não iniciou fluxo: lead sem telefone resolvível")
            return None

        # Já está no fluxo: não reiniciar. Um lead re-ingerido não volta para o começo.
        existente = await _estado_do_contato(wa_id, db)
        if existente is not None:
            print(f"↩️  NAT: {wa_id} já está no fluxo (etapa {existente.etapa}) — nada a fazer")
            return existente.etapa

        res = await db.execute(select(Contact.assigned_to).where(Contact.wa_id == wa_id))
        row = res.first()
        sdr_user_id = row[0] if row else None

        # FORA DO HORÁRIO: enfileira, não envia.
        if not dentro_horario_comercial():
            db.add(NatFlowState(
                contact_wa_id=wa_id, exact_lead_id=exact_lead_id, sdr_user_id=sdr_user_id,
                etapa=ETAPA_AGUARDANDO_HORARIO,
            ))
            print(f"🌙 NAT: {wa_id} chegou fora de 09h-19h → {ETAPA_AGUARDANDO_HORARIO} "
                  "(nada enviado)")
            return ETAPA_AGUARDANDO_HORARIO

        from app.exact_spotter import resolve_course_name
        curso = await resolve_course_name(sub_source or "", db)

        enviou = await send_nat_message(wa_id, nat_copy.NAT_BOASVINDAS, db,
                                        nome=nome, curso=curso)
        if not enviou:
            # Sem estado: nada pode afirmar que o lead está esperando uma resposta que ele
            # nunca recebeu. O motivo já foi logado pelo sender.
            print(f"🔒 NAT: boas-vindas não saiu para {wa_id} — fluxo não iniciado")
            return None

        db.add(NatFlowState(
            contact_wa_id=wa_id, exact_lead_id=exact_lead_id, sdr_user_id=sdr_user_id,
            etapa=ETAPA_AGUARDANDO_RESPOSTA,
        ))
        print(f"✅ NAT: fluxo iniciado para {wa_id} → {ETAPA_AGUARDANDO_RESPOSTA}")
        return ETAPA_AGUARDANDO_RESPOSTA

    except Exception as e:
        print(f"⚠️  NAT: erro ao iniciar fluxo: {type(e).__name__}: {e}")
        return None


def _payload_do_evento(evento: dict, state: NatFlowState) -> str | None:
    """Payload do clique. Texto do botão é FALLBACK, nunca o mecanismo principal.

    O payload é o que distingue os botões; o texto não distingue nada — "Prefiro outro
    horário" é idêntico em nat_boasvindas e em nat_reativacao_09h. O fallback por texto só
    existe para os cliques que chegarem SEM payload (template disparado antes desta sprint,
    quando ainda não fixávamos payload no envio) e só resolve porque a ETAPA em que o lead
    está já elimina a ambiguidade — não porque o texto seja confiável.
    """
    payload = (evento.get("button_payload") or "").strip()
    if payload in (nat_copy.NAT_SIM, nat_copy.NAT_OUTRO_HORARIO):
        return payload

    if state.etapa != ETAPA_AGUARDANDO_RESPOSTA:
        return payload or None

    texto = (evento.get("button_text") or "").strip().lower()
    if not texto:
        return payload or None

    aprovados = nat_copy.BOTOES_APROVADOS.get(nat_copy.NAT_BOASVINDAS, [])
    livres = [b["titulo"] for b in nat_copy.BOTOES_LIVRES.get(nat_copy.NAT_BOASVINDAS, [])]
    if texto in {t.lower() for t in (aprovados[:1] + livres[:1])}:
        print(f"↪️  NAT: clique sem payload conhecido, resolvido por texto → {nat_copy.NAT_SIM}")
        return nat_copy.NAT_SIM
    if texto in {t.lower() for t in (aprovados[1:2] + livres[1:2])}:
        print("↪️  NAT: clique sem payload conhecido, resolvido por texto → "
              f"{nat_copy.NAT_OUTRO_HORARIO}")
        return nat_copy.NAT_OUTRO_HORARIO

    return payload or None


async def processar_clique(evento: dict, db: AsyncSession) -> str | None:
    """Roteia um clique de botão. Retorna a etapa resultante, ou None se não agiu.

    `evento` é o dict que nat_buttons.extrair_evento_botao devolve.
    """
    try:
        wa_id = evento.get("contact_wa_id")
        wa_message_id = evento.get("wa_message_id")
        if not wa_id:
            return None

        state = await _estado_do_contato(wa_id, db)
        if state is None:
            print(f"↩️  NAT: clique de {wa_id} sem fluxo ativo — ignorado")
            return None

        if _ja_processado(state, wa_message_id):
            print(f"↩️  NAT: clique {wa_message_id} já processado — nada refeito")
            return state.etapa

        payload = _payload_do_evento(evento, state)

        if state.etapa != ETAPA_AGUARDANDO_RESPOSTA:
            print(f"↩️  NAT: clique '{payload}' fora da etapa esperada "
                  f"(lead está em {state.etapa}) — ignorado")
            return None

        if payload == nat_copy.NAT_SIM:
            destino, mensagem = ETAPA_AGUARDANDO_MOTIVACAO, nat_copy.NAT_MSG_SIM
        elif payload == nat_copy.NAT_OUTRO_HORARIO:
            destino, mensagem = ETAPA_REAGENDADO, nat_copy.NAT_MSG_OUTRO_HORARIO
        else:
            print(f"↩️  NAT: payload '{payload}' desconhecido — ignorado")
            return None

        dados = await _dados_do_lead(state, db)
        if not await send_nat_message(wa_id, mensagem, db, **dados):
            print(f"🔒 NAT: '{mensagem}' não saiu — estado permanece em {state.etapa}")
            return None

        state.etapa = destino
        state.ultimo_wa_message_id = wa_message_id
        print(f"➡️  NAT: {wa_id} {ETAPA_AGUARDANDO_RESPOSTA} → {destino}")
        return destino

    except Exception as e:
        print(f"⚠️  NAT: erro ao processar clique: {type(e).__name__}: {e}")
        return None


async def processar_texto(contact_wa_id: str, texto: str, wa_message_id: str,
                          db: AsyncSession) -> str | None:
    """Roteia uma mensagem de texto do lead. Retorna a etapa resultante, ou None.

    Sem IA nesta sprint: QUALQUER texto em aguardando_motivacao avança o fluxo. O refino
    (entender se o lead de fato respondeu à pergunta) é Bloco 8.
    """
    try:
        state = await _estado_do_contato(contact_wa_id, db)
        if state is None:
            return None

        if _ja_processado(state, wa_message_id):
            print(f"↩️  NAT: texto {wa_message_id} já processado — nada refeito")
            return state.etapa

        # Em reagendado, o período só chega por texto — o clique sozinho não traz período.
        if state.etapa == ETAPA_REAGENDADO:
            if state.horario_preferencial is None and (texto or "").strip():
                state.horario_preferencial = texto.strip()
                state.ultimo_wa_message_id = wa_message_id
                print(f"🗓️  NAT: horário preferencial de {contact_wa_id} registrado: "
                      f"{state.horario_preferencial!r}")
            return state.etapa

        if state.etapa != ETAPA_AGUARDANDO_MOTIVACAO:
            print(f"↩️  NAT: texto de {contact_wa_id} em {state.etapa} — nenhuma transição")
            return None

        dados = await _dados_do_lead(state, db)
        if not await send_nat_message(
                contact_wa_id, nat_copy.NAT_CONFIRMA_TRANSFERENCIA, db, **dados):
            print(f"🔒 NAT: confirmação não saiu — {contact_wa_id} segue em {state.etapa}")
            return None

        # A máquina de estados avança AQUI, e sempre: a mensagem já saiu para o lead, e não
        # avançar deixaria a reentrega do webhook mandá-la de novo. O que pode falhar é o
        # efeito colateral (avisar, registrar, armar o SLA), nunca a transição.
        state.etapa = ETAPA_AGUARDANDO_LIGACAO
        state.ultimo_wa_message_id = wa_message_id
        print(f"➡️  NAT: {contact_wa_id} {ETAPA_AGUARDANDO_MOTIVACAO} → "
              f"{ETAPA_AGUARDANDO_LIGACAO}")

        # transferido_em é carimbado lá dentro, junto da notificação (ver transferir_para_sdr).
        if not await transferir_para_sdr(state, texto, wa_message_id, db):
            print(f"🚨 NAT: {contact_wa_id} está em {ETAPA_AGUARDANDO_LIGACAO} e NINGUÉM foi "
                  "avisado. O lead pediu para ser ligado e não há notificação nem SLA.")

        return ETAPA_AGUARDANDO_LIGACAO

    except Exception as e:
        print(f"⚠️  NAT: erro ao processar texto: {type(e).__name__}: {e}")
        return None
