"""Máquina de estados do fluxo NAT — Cenário 1.

Aqui mora "QUANDO a NAT fala e para onde o lead vai depois". O "COMO ela fala" (template vs.
texto livre, credencial, janela de 24h) é do nat_sender.

Transições implementadas:

  gatilho                        origem                 ação                          destino
  ---------------------------------------------------------------------------------------------
  boas-vindas JÁ enviada,        —                      NADA (só adota o lead)        aguardando_resposta
    dentro do horário
  boas-vindas JÁ enviada,        —                      NADA                          (fora do fluxo)
    fora do horário
  lead entra, dentro do horário  —                      envia nat_boasvindas          aguardando_resposta
  lead entra, fora do horário    —                      NADA                          aguardando_horario
  payload NAT_SIM                aguardando_resposta    envia nat_sim                 aguardando_motivacao
  payload NAT_OUTRO_HORARIO      aguardando_resposta    nat_outro_horario + avisa SDR reagendado
  texto qualquer                 aguardando_motivacao   envia confirma_transferencia  aguardando_ligacao
  1º texto                       reagendado             grava período + atualiza      reagendado
                                                        o aviso do SDR
  SDR clica "Assumir ligação"    aguardando_ligacao     (nat_routes.assumir_ligacao)  encerrado
  SDR marca "sem contato"        aguardando_ligacao     envia nat_recuperacao_sdr,    sem_contato
    (1ª vez)                                            arma retry de 10 min            (Bloco 6)
  SDR marca "sem contato"        sem_contato            envia, NÃO arma retry         encerrado
    (2ª vez = teto)
  payload NAT_TENTAR_AGORA       sem_contato, ou        avisa SDR, arma sla_check     aguardando_ligacao
                                 encerrado PELO TETO
  payload NAT_AGENDAR_OUTRO      idem                   avisa SDR (reagendamento)     reagendado
  clique ou texto                encerrado por ASSUMIR  nada — o humano conduz        encerrado
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
                        ETAPA_ENCERRADO, ETAPA_REAGENDADO, ETAPA_SEM_CONTATO, KIND_SLA_CHECK,
                        Contact, ExactLead, Notification, NatFlowState, User)
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

# Tipo separado do de transferência, e não um campo dentro dela: são pedidos OPOSTOS do lead
# ("me ligue agora" x "me ligue depois"), e o tipo é o que permite perguntar ao banco quantos
# leads pediram reagendamento sem parsear título — mesma razão dos dois tipos do nat_sla.
TIPO_NOTIF_REAGENDADO = "nat_reagendado"

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


def montar_notificacao_reagendamento(nome: str, wa_id: str, curso: str, periodo: str,
                                     *, sem_sdr: bool = False) -> tuple[str, str]:
    """(title, body) do aviso de "o lead quer falar, mas depois".

    Mesmo formato da transferência, pela mesma razão (ver montar_notificacao_transferencia):
    telefone no título, que o NotificationBell.tsx mostra inteiro, e telefone no começo do
    corpo, que é `line-clamp-2` — é o dado sem o qual o SDR não liga.

    O QUE MUDA EM RELAÇÃO À TRANSFERÊNCIA é a urgência, e o título tem que dizer isso. Lá é
    "Ligar agora" com SLA de 2 minutos correndo; aqui o lead pediu explicitamente para NÃO
    ser ligado agora. Um título parecido faria o SDR ligar na hora — exatamente o contrário
    do que o lead pediu, e depois de a NAT ter prometido a ele que não ligaríamos.

    `periodo` é o texto livre do lead ("de manhã", "depois das 18h") e chega DEPOIS do clique,
    numa segunda mensagem — quando chega. Sem ele o aviso já vale: o SDR sabe que o lead está
    interessado e quer outro horário, e pode perguntar qual. Com ele, o período entra no
    título, porque é o que decide QUANDO o SDR volta, e o título é o que sobrevive a qualquer
    corte.
    """
    fone = telefone_legivel(wa_id)
    quem = nome or "Lead sem nome"
    resumo = _resumir(periodo, 30) if periodo else ""

    if sem_sdr:
        title = f"Reagendar (SEM SDR): {quem} — {fone}"
    elif resumo:
        title = f"Reagendar — {resumo}: {quem} — {fone}"
    else:
        title = f"Reagendar: {quem} — {fone}"

    partes = [fone]
    if curso:
        partes.append(curso)
    if periodo:
        partes.append(f'prefere: "{_resumir(periodo)}"')
    else:
        partes.append("pediu outro horário — ainda não disse quando")
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


async def _destinatario_do_aviso(state: NatFlowState, db: AsyncSession):
    """(user_id, eh_fallback) de quem recebe a notificação. (None, _) se não há ninguém.

    Vale para os DOIS avisos que o fluxo emite — a transferência (lead quer falar agora) e o
    reagendamento (lead quer falar depois). A regra de destinatário é a mesma nos dois: o SDR
    dono, e a gestão como rede.

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
        print(f"⚠️  NAT: {state.contact_wa_id} precisa de aviso e está sem SDR válido "
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
    destinatario, eh_fallback = await _destinatario_do_aviso(state, db)
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


async def _aviso_de_reagendamento(wa_id: str, db: AsyncSession):
    """O aviso de reagendamento já existente deste contato, se houver."""
    res = await db.execute(
        select(Notification)
        .where(Notification.contact_wa_id == wa_id,
               Notification.type == TIPO_NOTIF_REAGENDADO)
        .order_by(Notification.id.desc())
        .limit(1))
    return res.scalar_one_or_none()


async def notificar_reagendamento(state: NatFlowState, periodo: str | None,
                                  wa_message_id: str, db: AsyncSession) -> bool:
    """Avisa quem deve reagendar o contato. True se o aviso saiu.

    Chamada em DOIS momentos, e o segundo ATUALIZA o aviso do primeiro em vez de criar outro:

      1. no clique em "Prefiro outro horário", sem período — o SDR já pode agir;
      2. no texto que o lead manda depois, com o período.

    POR QUE ATUALIZAR E NÃO CRIAR UM SEGUNDO AVISO. Os dois falam do MESMO pedido, para a
    MESMA pessoa, e o primeiro não tem nenhuma informação que o segundo não tenha — ele diz
    estritamente menos. Dois itens no sino colocariam o SDR diante de um aviso obsoleto e de
    um atual, sem nada que os distinga à primeira vista, e agir pelo obsoleto significa ligar
    sem saber o horário que o lead acabou de informar. (É o oposto do caso do nat_sla, que
    cria um aviso por degrau de propósito: lá cada evento vai para uma PESSOA diferente e
    registra uma falha distinta.)

    `is_read` volta para False na atualização, e é isso que faz o aviso reaparecer: o sino
    marca o não-lido em negrito e com fundo. Sem esse reset, o SDR que já tinha lido o aviso
    do clique nunca ficaria sabendo do período — que é justamente o que esta fase entrega.

    `created_at` NÃO é mexido, e o `ref` continua apontando para o clique. O carimbo de tempo
    responde "desde quando este lead está esperando", que é a pergunta do SDR e não muda
    porque o lead mandou uma segunda mensagem; e o `ref` guarda o evento que originou o
    pedido, que é o que dá idempotência se este caminho for reexecutado.
    """
    wa_id = state.contact_wa_id
    dados = await _dados_do_lead(state, db)

    destinatario, eh_fallback = await _destinatario_do_aviso(state, db)
    if destinatario is None:
        print(f"❌ NAT: {wa_id} pediu outro horário e não há destinatário possível "
              f"(sdr_user_id={state.sdr_user_id}, gestor id={GESTOR_USER_ID} não existe) — "
              "ninguém foi avisado")
        return False

    title, body = montar_notificacao_reagendamento(
        dados["nome"], wa_id, dados["curso"], periodo or "", sem_sdr=eh_fallback)

    try:
        async with db.begin_nested():
            existente = await _aviso_de_reagendamento(wa_id, db)
            if existente is None:
                db.add(Notification(
                    user_id=destinatario,
                    contact_wa_id=wa_id,
                    type=TIPO_NOTIF_REAGENDADO,
                    ref=wa_message_id,
                    title=title,
                    body=body,
                ))
                acao = "criado"
            else:
                existente.user_id = destinatario
                existente.title = title
                existente.body = body
                existente.is_read = False
                acao = "atualizado"
    except Exception as e:
        print(f"❌ NAT: aviso de reagendamento FALHOU para {wa_id} "
              f"({type(e).__name__}: {e})")
        return False

    print(f"🗓️  NAT: reagendamento de {wa_id} {acao} para user {destinatario}"
          f"{' (FALLBACK gestão)' if eh_fallback else ''}: {title}")
    return True

async def iniciar_fluxo_nat(lead, db: AsyncSession, *,
                            boas_vindas_wamid: str | None = None) -> str | None:
    """Cria o estado inicial do lead. Retorna a etapa criada, ou None se a NAT não atuou.

    `lead` é um ExactLead ou o dict lead_data que o sync monta.

    ADOÇÃO x ENVIO — `boas_vindas_wamid` decide qual dos dois modos roda:

      * PREENCHIDO: a nat_boasvindas JÁ SAIU, enviada por quem chamou (o único chamador em
        produção é send_welcome_to_new_lead, exact_spotter.py:322). Esta função NÃO envia
        nada — só ADOTA o lead, criando o estado em aguardando_resposta. Era daqui que vinha
        a duplicata: send_welcome_to_new_lead mandava o template e, uma linha depois, esta
        função mandava O MESMO template de novo via send_nat_message, porque com a janela de
        24h fechada (lead novo, sem inbound) o sender cai no ramo de template. Nada entre os
        dois deduplicava.

      * None: modo antigo, a NAT é quem envia. Não tem chamador em produção hoje — sobrevive
        para os testes e para um eventual disparo que não venha da boas-vindas. O
        comportamento dele NÃO mudou.

    FORA DO HORÁRIO COMERCIAL, no modo adoção, o lead NÃO entra no fluxo (retorna None).
    Medido em 2026-08-11: a sync roda 24/7 e 55% das boas-vindas do funil 18535 saem fora de
    09h-19h — ou seja, o lead já está com os dois botões na mão quando chegamos aqui. As duas
    alternativas eram piores:

      * aguardando_horario seria um beco: não existe handler que drene essa etapa, então o
        clique do lead cairia em "clique fora da etapa" e seria engolido PARA SEMPRE — e a
        premissa que justificava a fila ("o lead não recebe nada, então não há dano") deixou
        de valer no momento em que a boas-vindas passou a sair antes;
      * adotar assim mesmo faria a NAT responder e prometer ligação às 22h de um sábado —
        64% dos cliques históricos vieram fora do horário — para um SDR que não vai ligar.

    Sem estado, o clique noturno segue o caminho que já existe para qualquer mensagem: fica
    em messages e em nat_button_events, e o SDR dono recebe a notificação de "nova mensagem"
    (main.py:452). Atendimento humano, sem a NAT no meio. O custo é cobertura: ~45% dos leads
    elegíveis entram no fluxo, e quem recebeu a boas-vindas à noite fica fora dele em
    definitivo, inclusive se clicar às 09h do dia seguinte.
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

        # ---- MODO ADOÇÃO: a boas-vindas já saiu, ninguém envia nada aqui ----
        if boas_vindas_wamid:
            if not dentro_horario_comercial():
                print(f"🌙 NAT: {wa_id} recebeu a boas-vindas fora de 09h-19h — fluxo NÃO "
                      "adotado. O clique dele segue para atendimento humano.")
                return None

            # O wamid do envio que JÁ aconteceu mora em ultimo_wa_message_id: o campo é
            # "último id de mensagem que este estado contabilizou", e guardá-lo aqui mantém o
            # rastro da mensagem que abriu o fluxo sem exigir coluna nova. Não atrapalha a
            # trava de reentrega de _ja_processado: id de mensagem é único global na Meta, e
            # este é de OUTBOUND — nenhum webhook de inbound vai chegar com ele.
            db.add(NatFlowState(
                contact_wa_id=wa_id, exact_lead_id=exact_lead_id, sdr_user_id=sdr_user_id,
                etapa=ETAPA_AGUARDANDO_RESPOSTA, ultimo_wa_message_id=boas_vindas_wamid,
            ))
            print(f"✅ NAT: {wa_id} adotado em {ETAPA_AGUARDANDO_RESPOSTA} a partir da "
                  f"boas-vindas {boas_vindas_wamid} (nenhum envio novo)")
            return ETAPA_AGUARDANDO_RESPOSTA

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


# Todos os payloads que a NAT fixa nos próprios envios. Derivado de nat_copy em vez de
# listado à mão: um payload novo lá passa a ser reconhecido aqui sem ninguém lembrar.
PAYLOADS_CONHECIDOS = frozenset(
    p for chave in nat_copy.BOTOES_LIVRES
    for p in (nat_copy.payloads_dos_botoes(chave) or []))


def _clique_e_da_recuperacao(state: NatFlowState) -> bool:
    """O último botão que este lead recebeu é o da recuperação, e ele ainda pode ser clicado?

    `sem_contato` é o caso óbvio. O outro é `encerrado` COM tentativa registrada, e ele existe
    porque a 2ª tentativa manda a mensagem E encerra o fluxo no mesmo ato: sem esta linha, o
    lead receberia dois botões vivos apontando para um estado que descarta cliques em
    silêncio — a mesma classe de bug dos cliques perdidos que esta sprint existe para matar.
    Um lead que clica é um lead respondendo; encerrar o fluxo foi decisão NOSSA, não dele.

    `assumido_por` é o corte: se um humano assumiu a ligação, `encerrado` significa "o
    atendimento é dele agora" e a NAT não retoma o lead — é exatamente o que o /assumir
    documenta. Aí o clique volta a ser ignorado, e ignorar é a resposta certa.
    """
    if state.etapa == ETAPA_SEM_CONTATO:
        return True
    return (state.etapa == ETAPA_ENCERRADO
            and (state.tentativas_contato or 0) > 0
            and state.assumido_por is None)


def _chave_dos_botoes(state: NatFlowState) -> str | None:
    """Qual MENSAGEM tem botões esperados no estado atual. None = texto não identifica nada.

    É o que dá sentido ao fallback por texto: o mesmo rótulo "Outro horário" pertence à
    boas-vindas e à recuperação, e só o lugar do lead no fluxo desempata.
    """
    if state.etapa == ETAPA_AGUARDANDO_RESPOSTA:
        return nat_copy.NAT_BOASVINDAS
    if _clique_e_da_recuperacao(state):
        return nat_copy.NAT_MSG_RECUPERACAO
    return None


def _payload_do_evento(evento: dict, state: NatFlowState) -> str | None:
    """Payload do clique. Texto do botão é FALLBACK, nunca o mecanismo principal.

    O payload é o que distingue os botões; o texto não distingue nada — "Prefiro outro
    horário" é idêntico em nat_boasvindas e em nat_reativacao_09h, e "Outro horário" é o
    título livre TANTO da boas-vindas QUANTO da recuperação. O fallback por texto só existe
    para os cliques que chegarem SEM payload (template disparado antes desta sprint, quando
    ainda não fixávamos payload no envio) e só resolve porque a ETAPA em que o lead está já
    elimina a ambiguidade — não porque o texto seja confiável. É por isso que ele é indexado
    pela etapa: o MESMO texto resolve para NAT_OUTRO_HORARIO em aguardando_resposta e para
    NAT_AGENDAR_OUTRO em sem_contato, e não há como acertar isso sem saber onde o lead está.

    A POSIÇÃO é o que casa texto com payload — 1º botão, 2º botão —, e a ordem das listas de
    nat_copy é a ordem aprovada na Meta. Inverter uma delas faria "quero falar agora" virar
    "quero falar depois", em silêncio.
    """
    payload = (evento.get("button_payload") or "").strip()
    if payload in PAYLOADS_CONHECIDOS:
        return payload

    chave = _chave_dos_botoes(state)
    if chave is None:
        return payload or None

    texto = (evento.get("button_text") or "").strip().lower()
    if not texto:
        return payload or None

    aprovados = nat_copy.BOTOES_APROVADOS.get(chave, [])
    livres = [b["titulo"] for b in nat_copy.BOTOES_LIVRES.get(chave, [])]
    payloads = nat_copy.payloads_dos_botoes(chave) or []

    for posicao, esperado in enumerate(payloads[:2]):
        titulos = {t.lower() for t in (aprovados[posicao:posicao + 1]
                                       + livres[posicao:posicao + 1])}
        if texto in titulos:
            print(f"↪️  NAT: clique sem payload conhecido em {state.etapa}, resolvido por "
                  f"texto → {esperado}")
            return esperado

    return payload or None


async def _clique_na_recuperacao(state: NatFlowState, payload: str | None,
                                 wa_message_id: str, db: AsyncSession) -> str | None:
    """Cliques na mensagem de recuperação (Bloco 6). Devolve a etapa nova, ou None.

    NENHUM DOS DOIS CAMINHOS MANDA MENSAGEM AO LEAD. É a diferença em relação ao ramo da
    boas-vindas, e é deliberada: o lead já recebeu a única mensagem deste fluxo, e o que ele
    pede agora — ser chamado agora, ou depois — se resolve com um HUMANO, não com mais texto.
    (O acusar-recebimento ao lead ficou de fora desta sprint; ver o relatório do Bloco 6.)

    "Tentar novamente agora" devolve o lead à FILA DE LIGAÇÃO, e devolver de verdade exige
    três coisas além da etapa:

      * cancelar o retry_contato pendente — a cobrança de 10 min perdeu o objeto no instante
        em que o lead respondeu; deixá-la de pé faria o SDR ser cobrado por um lead que já
        voltou para a fila;
      * ZERAR o escalonamento e recarimbar transferido_em. Sem isso o sla_check novo nasce
        morto: o ciclo anterior quase sempre terminou em nível 2, e a PRIMEIRA coisa que o
        handler faz é sair calado quando o nível já é 2. O relógio que estamos armando aqui
        é de uma promessa NOVA ("um consultor vai te ligar agora"), e uma promessa nova pede
        uma escada nova — o histórico de quem já foi avisado antes não deve calar o aviso
        desta vez;
      * agendar o sla_check, que é o que garante que alguém seja cobrado se o SDR não
        assumir.

    "Agendar outro horário" cai em `reagendado` e reaproveita inteiro o aviso que já existe
    na saída dessa etapa. A extração do período (a IA que lê "de tarde") é Sprint B; até lá o
    SDR recebe o pedido e combina o horário por conta própria.
    """
    from app.models import KIND_RETRY_CONTATO
    from app.nat_recuperacao import (TIPO_NOTIF_TENTAR_AGORA, montar_notificacao_tentar_agora,
                                     notificar_sdr)
    from app.nat_scheduler import agendar, cancelar

    wa_id = state.contact_wa_id
    origem = state.etapa  # sem_contato, ou encerrado pelo teto — ver _clique_e_da_recuperacao

    if payload not in (nat_copy.NAT_TENTAR_AGORA, nat_copy.NAT_AGENDAR_OUTRO):
        print(f"↩️  NAT: payload '{payload}' não é da recuperação (lead está em "
              f"{origem}) — ignorado")
        return None

    # O retry morre nos DOIS caminhos: o lead respondeu, e cobrar o SDR daqui a 10 minutos
    # por falta de resposta seria falso. (O handler também se protege relendo a etapa; isto
    # aqui é o mecanismo, aquilo é a rede.)
    try:
        async with db.begin_nested():
            await cancelar(KIND_RETRY_CONTATO, wa_id, db)
    except Exception as e:
        print(f"⚠️  NAT: retry_contato de {wa_id} não pôde ser cancelado "
              f"({type(e).__name__}: {e}) — o handler ainda relê a etapa e sai calado")

    if payload == nat_copy.NAT_AGENDAR_OUTRO:
        state.etapa = ETAPA_REAGENDADO
        state.ultimo_wa_message_id = wa_message_id
        print(f"➡️  NAT: {wa_id} {origem} → {ETAPA_REAGENDADO} "
              "(lead pediu outro horário depois da tentativa de ligação)")
        if not await notificar_reagendamento(state, None, wa_message_id, db):
            print(f"🚨 NAT: {wa_id} pediu outro horário e NINGUÉM foi avisado. O lead está "
                  "em reagendado sem ninguém encarregado de voltar nele.")
        return ETAPA_REAGENDADO

    # --- NAT_TENTAR_AGORA: de volta para a fila de ligação ---
    dados = await _dados_do_lead(state, db)
    title, body = montar_notificacao_tentar_agora(dados["nome"], wa_id, dados["curso"])

    try:
        async with db.begin_nested():
            avisado = await notificar_sdr(state, db, tipo=TIPO_NOTIF_TENTAR_AGORA,
                                          ref=wa_message_id, title=title, body=body)
            state.etapa = ETAPA_AGUARDANDO_LIGACAO
            state.ultimo_wa_message_id = wa_message_id
            state.transferido_em = _agora_sp()
            state.escalonamento_nivel = 0
    except Exception as e:
        print(f"❌ NAT: clique 'tentar agora' de {wa_id} falhou ao registrar "
              f"({type(e).__name__}: {e}) — estado permanece em {state.etapa}")
        return None

    if not avisado:
        print(f"🚨 NAT: {wa_id} pediu NOVA LIGAÇÃO e ninguém foi avisado diretamente. O "
              f"sla_check de {SLA_LIGACAO_MINUTOS} min é a única rede que sobrou.")

    try:
        async with db.begin_nested():
            await agendar(KIND_SLA_CHECK, wa_id,
                          _agora_sp() + timedelta(minutes=SLA_LIGACAO_MINUTOS),
                          {"origem": "recuperacao_tentar_agora"}, db)
    except Exception as e:
        print(f"⚠️  NAT: sla_check NÃO agendado para {wa_id} ({type(e).__name__}: {e}) — o "
              "aviso ao SDR permanece, mas NÃO haverá escalonamento automático")

    print(f"➡️  NAT: {wa_id} {origem} → {ETAPA_AGUARDANDO_LIGACAO} "
          "(lead pediu nova tentativa agora)")
    return ETAPA_AGUARDANDO_LIGACAO


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

        # RECUPERAÇÃO (Bloco 6). Ramo próprio: os cliques daqui não enviam nada ao lead e não
        # seguem a máquina de estados da boas-vindas. Vem ANTES da checagem de etapa porque
        # inclui um caso de `encerrado` — ver _clique_e_da_recuperacao.
        if _clique_e_da_recuperacao(state):
            return await _clique_na_recuperacao(state, payload, wa_message_id, db)

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

        # SAÍDA DE `reagendado`. Vem DEPOIS do envio do nat_outro_horario e depois da
        # transição, pelo mesmo raciocínio de processar_texto: a mensagem já está com o lead,
        # e o que pode falhar é o efeito colateral, nunca a transição.
        #
        # Sem isto, `reagendado` é beco sem saída: o lead diz que quer falar depois, a NAT
        # responde, e ninguém fica sabendo — o período iria para um campo que nenhum código
        # lê. O reagendamento AUTOMÁTICO do envio é Bloco 6; o que entra aqui é o aviso ao
        # humano, que é o que impede o lead de ser esquecido enquanto o Bloco 6 não existe.
        if destino == ETAPA_REAGENDADO:
            if not await notificar_reagendamento(state, None, wa_message_id, db):
                print(f"🚨 NAT: {wa_id} pediu outro horário e NINGUÉM foi avisado. O lead "
                      "está em reagendado sem ninguém encarregado de voltar nele.")

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
        #
        # Só o PRIMEIRO texto conta, como já era antes desta sprint: o lead que manda cinco
        # mensagens seguidas não reescreve cinco vezes o período nem ressuscita o aviso cinco
        # vezes no sino do SDR. As mensagens seguintes seguem visíveis na conversa e geram a
        # notificação de "nova mensagem" de sempre (main.py) — nada se perde.
        if state.etapa == ETAPA_REAGENDADO:
            if state.horario_preferencial is None and (texto or "").strip():
                state.horario_preferencial = texto.strip()
                state.ultimo_wa_message_id = wa_message_id
                print(f"🗓️  NAT: horário preferencial de {contact_wa_id} registrado: "
                      f"{state.horario_preferencial!r}")
                # ATUALIZA o aviso do clique com o período (não cria um segundo) — ver
                # notificar_reagendamento.
                await notificar_reagendamento(state, state.horario_preferencial,
                                              wa_message_id, db)
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
