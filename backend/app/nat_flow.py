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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import nat_copy
from app.models import (ETAPA_AGUARDANDO_HORARIO, ETAPA_AGUARDANDO_LIGACAO,
                        ETAPA_AGUARDANDO_MOTIVACAO, ETAPA_AGUARDANDO_RESPOSTA,
                        ETAPA_REAGENDADO, Contact, ExactLead, NatFlowState)
from app.nat_guard import _agora_sp, dentro_horario_comercial, nat_pode_atuar
from app.nat_sender import send_nat_message


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

        state.etapa = ETAPA_AGUARDANDO_LIGACAO
        state.ultimo_wa_message_id = wa_message_id
        state.transferido_em = _agora_sp()
        print(f"➡️  NAT: {contact_wa_id} {ETAPA_AGUARDANDO_MOTIVACAO} → "
              f"{ETAPA_AGUARDANDO_LIGACAO}")
        return ETAPA_AGUARDANDO_LIGACAO

    except Exception as e:
        print(f"⚠️  NAT: erro ao processar texto: {type(e).__name__}: {e}")
        return None
