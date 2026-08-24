"""A máquina de etapas do agente. Só este módulo muda `etapa`.

------------------------------------------------------------------------------------------
O CONTRATO COM O LLM, DO LADO DE CÁ
------------------------------------------------------------------------------------------
`qualificacao_llm.conversar` PROPÕE `etapa_cumprida` e `acao`. Aqui a proposta é lida,
validada contra a etapa em que o lead realmente está, e só então vira escrita. Um
`acao="agendar_slot"` chegando em `aguardando_motivacao` não agenda nada: cai em ação
impossível → humano.

------------------------------------------------------------------------------------------
FLUXO
------------------------------------------------------------------------------------------
    abertura T3 --> aguardando_formacao --+
    abertura T1/T2 --------------------> aguardando_ano
                                             |
                                         aguardando_atuacao
                                             |
                                         aguardando_motivacao
                                             |
                              +--------------+--------------+
                    já tem reunião?                    não tem
                              |                             |
                         concluido                   ofertando_agenda
                      (+ lembrete)                          |
                                                     escolhendo_slot
                                                            |
                                                       concluido
                                                      (+ lembrete)

E de QUALQUER etapa: `transferido_humano`, que é terminal para o agente.

------------------------------------------------------------------------------------------
ONDE ELE CALA
------------------------------------------------------------------------------------------
`concluido`, `transferido_humano` e `encerrado` não estão em ETAPAS_QUALIFICACAO_ATIVAS.
Fora delas o agente não escuta (precedência do webhook) e não fala
(`qualificacao_pode_atuar`) — a mesma constante governa os dois lados, então "o agente fala"
e "o agente escuta" não podem divergir.
"""
import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import qualificacao_llm as llm
from app import qualificacao_guard as guard
from app.models import (ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_AGUARDANDO_ATUACAO,
                        ETAPA_Q_AGUARDANDO_FORMACAO, ETAPA_Q_AGUARDANDO_MOTIVACAO,
                        ETAPA_Q_CONCLUIDO, ETAPA_Q_ESCOLHENDO_SLOT, ETAPA_Q_OFERTANDO_AGENDA,
                        ETAPA_Q_TRANSFERIDO, ETAPAS_QUALIFICACAO_ATIVAS,
                        KIND_LEMBRETE_REUNIAO, Agendamento, Contact, Message, Notification,
                        NatQualificacaoState, PASSO_AGENDADO)
from app.nat_guard import GESTOR_USER_ID, _agora_sp
from app.nat_scheduler import registrar_handler
from app.nat_sender import send_nat_message
from app.nomes import primeiro_nome

# Quantas mensagens da conversa vão para o modelo. 10 cobre o vaivém das 4 perguntas com
# folga para uma digressão, e mantém o custo previsível.
MAX_HISTORICO = 10

# Quanto antes da reunião o lembrete sai.
ANTECEDENCIA_LEMBRETE = timedelta(minutes=30)

TIPO_NOTIF_AGENTE = "agente_transferiu"

# Mensagem determinística do fallback. NÃO passa pelo LLM: é justamente o caminho de quando
# o LLM não é confiável. Texto único, sem variação — a pessoa precisa entender que alguém
# vai assumir, não receber uma desculpa criativa.
TEXTO_FALLBACK = ("Deixa eu te conectar com uma pessoa da nossa equipe para seguir daqui, "
                  "tá? 🙂 Em breve alguém fala com você por aqui.")

# A missão de cada etapa. É o único lugar onde o roteiro vira texto para o modelo — mudar o
# roteiro é mudar estas linhas, não caçar prompt espalhado pelo módulo.
# A missão de cada etapa diz DUAS coisas, e a segunda é tão importante quanto a primeira:
# o que extrair, e QUAL PERGUNTA FAZER EM SEGUIDA quando a etapa se cumpre.
#
# Sem a segunda, o teste manual de 24/08 mostrou o que acontece: com `etapa_cumprida=true`
# o modelo inventava um fecho ("quer que eu te envie as próximas etapas da inscrição?"),
# `_avancar` mandava essa mensagem E movia a etapa, e o lead respondia uma pergunta que a
# etapa seguinte ia interpretar como outra coisa. A pergunta seguinte não é criatividade do
# modelo — é o roteiro.
MISSOES = {
    ETAPA_Q_AGUARDANDO_FORMACAO: (
        'Descubra QUAL É a formação (graduação) da pessoa. '
        'dado_extraido = {"formacao": "<o que ela disse>"}. '
        'SE ELA RESPONDER: valide em uma frase e TERMINE perguntando em que ano ela '
        'concluiu essa graduação.'),
    ETAPA_Q_AGUARDANDO_ANO: (
        'Descubra em QUE ANO ela concluiu a graduação. Se ela ainda está cursando, isso '
        'também serve como resposta. dado_extraido = {"ano_conclusao": "<o que ela disse>"}. '
        'SE ELA RESPONDER: valide em uma frase e TERMINE perguntando como e onde ela atua '
        'profissionalmente hoje.'),
    ETAPA_Q_AGUARDANDO_ATUACAO: (
        'Descubra COMO E ONDE ela atua profissionalmente hoje. Se estiver fora da área ou '
        'sem atuar, isso também é resposta. dado_extraido = {"atuacao": "<o que ela disse>"}. '
        'SE ELA RESPONDER: valide em uma frase e TERMINE perguntando, de forma aberta, o que '
        'despertou o interesse dela nesta pós-graduação.'),
    ETAPA_Q_AGUARDANDO_MOTIVACAO: (
        'Pergunta ABERTA: o que despertou o interesse dela nesta pós-graduação. '
        'dado_extraido = {"motivacao": "<o que ela disse>"}. '
        'SE ELA RESPONDER: sua mensagem VALIDA o que ela de fato disse — comente o conteúdo '
        'real, com as palavras dela; nada de "que interessante". E NÃO FAÇA NENHUMA '
        'PERGUNTA: esta é a última etapa de qualificação, e quem fala em seguida é o '
        'sistema, com os horários. Termine dizendo que vai ver os horários disponíveis.'),
    ETAPA_Q_OFERTANDO_AGENDA: (
        'Apresente os horários que estão no contexto, de forma curta, e pergunte qual serve. '
        'Use SOMENTE os horários listados. Quando ela escolher um deles, use '
        'acao="agendar_slot" e dado_extraido = {"slot_id": "<o id exato do horário '
        'escolhido, copiado do contexto>"}.'),
    ETAPA_Q_ESCOLHENDO_SLOT: (
        'A pessoa está confirmando qual horário quer. Use SOMENTE os horários do contexto. '
        'Ao ter certeza de qual é, use acao="agendar_slot" e '
        'dado_extraido = {"slot_id": "<o id exato copiado do contexto>"}.'),
}

# Para onde cada etapa vai quando cumprida. `aguardando_motivacao` não está aqui: o destino
# dela depende de o lead já ter reunião, e isso é decidido em código.
PROXIMA = {
    ETAPA_Q_AGUARDANDO_FORMACAO: ETAPA_Q_AGUARDANDO_ANO,
    ETAPA_Q_AGUARDANDO_ANO: ETAPA_Q_AGUARDANDO_ATUACAO,
    ETAPA_Q_AGUARDANDO_ATUACAO: ETAPA_Q_AGUARDANDO_MOTIVACAO,
}

# Onde cada dado do LLM é gravado. Chave fora daqui vai para `dados_extras` (JSONB), que
# existe para não exigir ALTER a cada pergunta nova do roteiro.
CAMPOS = {"formacao", "ano_conclusao", "atuacao", "motivacao"}


# ==========================================================================================
# LEITURA
# ==========================================================================================

async def estado_de(contact_wa_id: str, db: AsyncSession) -> NatQualificacaoState | None:
    res = await db.execute(select(NatQualificacaoState).where(
        NatQualificacaoState.contact_wa_id == contact_wa_id))
    return res.scalar_one_or_none()


async def agente_e_dono(contact_wa_id: str, db: AsyncSession) -> bool:
    """O agente é o dono do inbound deste contato? É a PRECEDÊNCIA do webhook.

    Uma pergunta, um lugar. `main.py` chama isto e, se for True, não roda o
    `processar_clique`/`processar_texto` do fluxo de botões para esta mensagem.
    """
    estado = await estado_de(contact_wa_id, db)
    return estado is not None and estado.etapa in ETAPAS_QUALIFICACAO_ATIVAS


def _ja_processado(estado: NatQualificacaoState, wa_message_id: str) -> bool:
    """Trava de reentrega: mesmo wa_message_id que o último processado (padrão nat_flow)."""
    return bool(wa_message_id) and estado.ultimo_wa_message_id == wa_message_id


async def _historico(contact_wa_id: str, db: AsyncSession) -> list:
    """As últimas mensagens da conversa, em ordem cronológica, no formato do chat.

    Template outbound vira um marcador: o corpo renderizado já está em `content`, mas
    reapresentá-lo cru faria o modelo repetir a saudação. Mídia idem — o modelo não a vê.
    """
    res = await db.execute(
        select(Message.direction, Message.content, Message.message_type)
        .where(Message.contact_wa_id == contact_wa_id)
        .order_by(Message.timestamp.desc()).limit(MAX_HISTORICO))
    linhas = list(res.all())[::-1]
    saida = []
    for direcao, conteudo, tipo in linhas:
        texto = (conteudo or "").strip()
        if not texto:
            continue
        if texto.startswith("media:"):
            texto = "[a pessoa enviou um arquivo]"
        saida.append({"role": "assistant" if direcao == "outbound" else "user",
                      "content": texto})
    return saida


async def _reuniao(estado: NatQualificacaoState, db: AsyncSession):
    """O agendamento CONFIRMADO deste lead, ou None. Nunca inventa.

    Procura pelo `agendamento_id` quando o agente mesmo marcou; senão pelo `lead_id`, que é
    o caso do lead que agendou sozinho no obrigado.html.
    """
    if estado.agendamento_id:
        res = await db.execute(select(Agendamento).where(
            Agendamento.id == estado.agendamento_id))
        achado = res.scalar_one_or_none()
        if achado is not None:
            return achado
    if not estado.exact_lead_id:
        return None
    res = await db.execute(
        select(Agendamento)
        .where(Agendamento.lead_id == estado.exact_lead_id,
               Agendamento.passo == PASSO_AGENDADO)
        .order_by(Agendamento.id.desc()).limit(1))
    return res.scalar_one_or_none()


async def _curso(estado: NatQualificacaoState, db: AsyncSession) -> str:
    from app.course_names import resolve_course_name
    from app.models import ExactLead
    if not estado.exact_lead_id:
        return ""
    res = await db.execute(select(ExactLead.sub_source).where(
        ExactLead.exact_id == estado.exact_lead_id))
    sub = res.scalar_one_or_none()
    return await resolve_course_name(sub or "", db) if sub else ""


async def _nome(estado: NatQualificacaoState, db: AsyncSession) -> str:
    res = await db.execute(select(Contact.name).where(
        Contact.wa_id == estado.contact_wa_id))
    return primeiro_nome((res.scalar_one_or_none() or ""))


async def _fatos(estado: NatQualificacaoState, db: AsyncSession, *,
                 com_slots: bool = False) -> tuple[str, dict]:
    """(contexto para o prompt, mapa slot_id → slot oferecido).

    Os slots entram SÓ quando `com_slots` — é o que garante que o modelo não tem horário
    nenhum para oferecer nas etapas de qualificação, mesmo que a pessoa peça.
    """
    from app.agendamento import consultoras as equipe

    reuniao = await _reuniao(estado, db)
    fatos = {
        "Primeiro nome da pessoa": await _nome(estado, db),
        "Curso a que ela se candidatou": await _curso(estado, db),
        "Formação dela": estado.formacao,
        "Ano de conclusão": estado.ano_conclusao,
        "Atuação profissional": estado.atuacao,
        "Motivação declarada": estado.motivacao,
    }
    if reuniao is not None:
        fatos["Reunião já marcada para"] = reuniao.slot_inicio.strftime("%d/%m às %H:%M")
        fatos["Consultora que vai atender"] = equipe.nome_de(reuniao.sales_rep_email or "")

    ofertados = {}
    if com_slots:
        from app.agendamento import disponibilidade
        try:
            por_dia = await disponibilidade.resumo_por_dia(db)
        except Exception as e:
            print(f"⚠️  Agente: grade não carregada ({type(e).__name__}: {e})")
            por_dia = {}
        linhas = []
        for dia in sorted(por_dia)[:3]:          # 3 dias bastam para uma escolha
            for h in por_dia[dia][:6]:           # e 6 horários por dia
                rotulo = f"{dia} {h['hora']} (id: {h['id']})"
                linhas.append(rotulo)
                ofertados[h["id"]] = rotulo
        fatos["Horários disponíveis (use SÓ estes)"] = linhas

    return llm.montar_contexto(fatos), ofertados


# ==========================================================================================
# ESCRITA
# ==========================================================================================

async def _enviar(estado: NatQualificacaoState, texto: str, db: AsyncSession) -> bool:
    """Fala livre do agente, dentro da janela de 24h."""
    return await send_nat_message(
        estado.contact_wa_id, guard.ETAPA_CONVERSA, db,
        guard=guard.qualificacao_pode_atuar, corpo_livre=texto)


async def _notificar(estado: NatQualificacaoState, titulo: str, corpo: str,
                     db: AsyncSession) -> None:
    """Avisa o SDR dono; sem dono, a gestão. Nunca levanta — aviso não derruba fluxo."""
    from app.nat_flow import telefone_legivel, usuario_existe
    try:
        res = await db.execute(select(Contact.assigned_to).where(
            Contact.wa_id == estado.contact_wa_id))
        dono = res.scalar_one_or_none()
        destinatario = dono if await usuario_existe(dono, db) else GESTOR_USER_ID
        if not await usuario_existe(destinatario, db):
            print(f"❌ Agente: sem destinatário para avisar sobre {estado.contact_wa_id}")
            return
        db.add(Notification(
            user_id=destinatario, contact_wa_id=estado.contact_wa_id,
            type=TIPO_NOTIF_AGENTE, ref=estado.ultimo_wa_message_id,
            title=titulo,
            body=f"{corpo} — {telefone_legivel(estado.contact_wa_id)}"))
        print(f"🔔 Agente notificou user {destinatario}: {titulo}")
    except Exception as e:
        print(f"⚠️  Agente: notificação falhou ({type(e).__name__}: {e})")


async def _fallback(estado: NatQualificacaoState, motivo: str, db: AsyncSession) -> None:
    """LLM caiu, fugiu do contrato, ou pediu o impossível. Encerra o agente para o contato.

    A ORDEM IMPORTA: muda a etapa ANTES de enviar. `transferido_humano` está fora de
    ETAPAS_QUALIFICACAO_ATIVAS, então a partir daqui o agente nem escuta nem fala — e é
    justamente isso que impede um loop de "falhou → tenta de novo → falhou".

    Por isso o envio usa `guard_de_abertura` e não `qualificacao_pode_atuar`: a etapa já não
    é ativa, e o guard de envio recusaria a própria mensagem de despedida.
    """
    print(f"🛟 Agente transferiu {estado.contact_wa_id} para humano: {motivo}")
    estado.etapa = ETAPA_Q_TRANSFERIDO
    estado.transferido_em = _agora_sp()
    estado.transferido_motivo = motivo
    await db.flush()

    await send_nat_message(estado.contact_wa_id, guard.ETAPA_CONVERSA, db,
                           guard=guard.guard_de_abertura, corpo_livre=TEXTO_FALLBACK)
    await _notificar(estado, "Agente passou um lead para você",
                     f"Motivo: {motivo}", db)


def _guardar_dado(estado: NatQualificacaoState, extraido: dict | None) -> None:
    """Grava o que o LLM extraiu. Campo conhecido vira coluna; o resto vira JSONB."""
    if not extraido:
        return
    extras = dict(estado.dados_extras or {})
    for chave, valor in extraido.items():
        if chave in CAMPOS:
            setattr(estado, chave, valor)
        elif chave != "slot_id":     # slot_id é instrução, não dado do lead
            extras[chave] = valor
    if extras:
        estado.dados_extras = extras


# ==========================================================================================
# ENTRADA: A ABERTURA (handler do KIND_INICIAR_QUALIFICACAO)
# ==========================================================================================

@registrar_handler("iniciar_qualificacao")
async def iniciar_qualificacao(acao: dict, db: AsyncSession) -> None:
    """+5 min depois da aplicação: escolhe a abertura e cria o estado.

    O ESTADO É RELIDO AQUI, nunca vem do payload — entre agendar e executar passam 5 minutos,
    e é exatamente nesse intervalo que a pessoa termina (ou não) o agendamento no
    obrigado.html. Medido: mediana 28s, máximo 3min14s entre o formulário e o agendamento;
    aos 5 minutos a ramificação é definitiva.

    Sai silencioso e bem-sucedido quando não há o que fazer — mesmo espírito de `nat_sla` e
    `nat_recuperacao`: a ação vira `executado` e ninguém é acordado à toa.
    """
    from app.qualificacao_dados import resolver_dados
    from app.models import ORIGEM_LP

    payload = json.loads(acao.get("payload") or "{}")
    wa_id = acao["contact_wa_id"]
    lead_id = payload.get("lead_id")
    origem = payload.get("origem") or ORIGEM_LP

    if await estado_de(wa_id, db) is not None:
        print(f"↩️  Agente: {wa_id} já tem estado — abertura ignorada")
        return

    # ADMISSÃO. A data de referência vem de quem agendou a ação: para a LP é
    # agendamentos.created_at (o lead pode nem estar em exact_leads ainda), para o sync é
    # register_date. Já em UTC naive — ver o cabeçalho de qualificacao_guard.
    referencia = payload.get("referencia_utc")
    if isinstance(referencia, str):
        from datetime import datetime as _dt
        try:
            referencia = _dt.fromisoformat(referencia)
        except ValueError:
            referencia = None
    pode, motivo = await guard.qualificacao_pode_iniciar(referencia, db)
    if not pode:
        print(f"↩️  Agente: abertura de {wa_id} não admitida ({motivo})")
        return

    contato = (await db.execute(select(Contact).where(Contact.wa_id == wa_id))).scalar_one_or_none()
    if contato is None:
        print(f"↩️  Agente: {wa_id} não existe em contacts — abertura ignorada")
        return

    dados = await resolver_dados(lead_id=lead_id, origem=origem, db=db)
    formacao = dados["formacao"]

    estado = NatQualificacaoState(
        contact_wa_id=wa_id, exact_lead_id=lead_id, origem=origem,
        etapa=ETAPA_Q_AGUARDANDO_ANO if formacao else ETAPA_Q_AGUARDANDO_FORMACAO,
        formacao=formacao,
        faixa_investimento=dados["faixa_investimento"],
        dados_extras={"como_conheceu": dados["como_conheceu"]} if dados["como_conheceu"] else None,
    )
    db.add(estado)
    await db.flush()

    reuniao = await _reuniao(estado, db)
    nome, curso = await _nome(estado, db), await _curso(estado, db)

    # T1 / T2 / T3 — a escolha é código, não modelo.
    if reuniao is not None and formacao:
        from app.agendamento import consultoras as equipe
        etapa_msg = guard.ETAPA_ABERTURA_AGENDADO
        parametros = [nome, curso, equipe.nome_de(reuniao.sales_rep_email or ""),
                      reuniao.slot_inicio.strftime("%d/%m"),
                      reuniao.slot_inicio.strftime("%H:%M"), formacao]
        estado.agendamento_id = reuniao.id
    elif formacao:
        etapa_msg = guard.ETAPA_ABERTURA_QUALIFICACAO
        parametros = [nome, curso, formacao]
    else:
        etapa_msg = guard.ETAPA_ABERTURA_SEM_FORMACAO
        parametros = [nome, curso]

    corpo = await _corpo_do_template(etapa_msg, parametros, db)
    enviado = await send_nat_message(wa_id, etapa_msg, db, guard=guard.guard_de_abertura,
                                     parametros=parametros, corpo_livre=corpo)
    if not enviado:
        # Sem abertura não há conversa. Some o estado para o lead poder ser reaberto depois,
        # em vez de ficar preso numa etapa que ninguém vai alimentar.
        print(f"↩️  Agente: abertura de {wa_id} não saiu — estado descartado")
        await db.delete(estado)
        return

    print(f"🚀 Agente abriu com {wa_id}: {etapa_msg} → {estado.etapa}")


async def _corpo_do_template(nome_template: str, parametros: list,
                             db: AsyncSession) -> str | None:
    """O texto renderizado do template, para a Message local não ficar vazia na tela do SDR.

    Vem da Meta, que é a única fonte da verdade do corpo aprovado — copiá-lo para cá criaria
    a mesma cópia que apodrece que o `nat_copy` já precisa vigiar com teste de drift.
    Falhar aqui é inofensivo: o envio usa template + parâmetros e independe disto.
    """
    try:
        from app.models import Channel
        from app.whatsapp import fetch_template_body, render_template_text
        canal = (await db.execute(select(Channel).where(Channel.id == 1))).scalar_one_or_none()
        if canal is None:
            return None
        corpo = await fetch_template_body(canal.waba_id, canal.whatsapp_token,
                                          nome_template, "pt_BR")
        return render_template_text(corpo, parametros) if corpo else None
    except Exception as e:
        print(f"⚠️  Agente: corpo de '{nome_template}' não renderizado ({type(e).__name__})")
        return None


# ==========================================================================================
# O NÚCLEO: UMA MENSAGEM DO LEAD
# ==========================================================================================

async def processar_texto(contact_wa_id: str, texto: str, wa_message_id: str,
                          db: AsyncSession) -> bool:
    """Uma mensagem recebida. True se o agente tratou; False se não é dele.

    False significa "não sou o dono desta mensagem" — o webhook então segue para o fluxo
    velho, como sempre fez.
    """
    estado = await estado_de(contact_wa_id, db)
    if estado is None or estado.etapa not in ETAPAS_QUALIFICACAO_ATIVAS:
        return False
    if _ja_processado(estado, wa_message_id):
        print(f"↩️  Agente: {wa_message_id} já processado para {contact_wa_id}")
        return True

    estado.ultimo_wa_message_id = wa_message_id
    await db.flush()

    etapa = estado.etapa
    com_slots = etapa in (ETAPA_Q_OFERTANDO_AGENDA, ETAPA_Q_ESCOLHENDO_SLOT)
    contexto, ofertados = await _fatos(estado, db, com_slots=com_slots)

    resposta = await llm.conversar(missao=MISSOES[etapa], contexto=contexto,
                                   historico=await _historico(contact_wa_id, db))
    if resposta is None:
        await _fallback(estado, "LLM indisponível ou fora do contrato", db)
        return True

    if resposta["acao"] == "transferir_humano":
        await _fallback(estado, "o LLM pediu transferência (lead quer falar com uma pessoa, "
                                "remarcar, ou saiu do roteiro)", db)
        return True

    _guardar_dado(estado, resposta["dado_extraido"])

    # AÇÃO IMPOSSÍVEL NA ETAPA. O modelo propôs agendar numa etapa de qualificação: não
    # improvisa, não ignora — transfere. Ignorar seria seguir conversando como se nada
    # tivesse acontecido, e o lead acabou de ouvir uma promessa que não vai ser cumprida.
    if resposta["acao"] == "agendar_slot" and not com_slots:
        await _fallback(estado, f"ação 'agendar_slot' pedida em '{etapa}', onde não há "
                                "agenda oferecida", db)
        return True

    if resposta["acao"] == "agendar_slot":
        await _agendar(estado, resposta, ofertados, db)
        return True

    if not resposta["etapa_cumprida"]:
        # A pessoa desconversou ou perguntou outra coisa. O LLM acolhe e retoma; a etapa NÃO
        # anda. É o caminho normal de uma digressão, não uma falha.
        await _enviar(estado, resposta["mensagem"], db)
        return True

    await _avancar(estado, resposta["mensagem"], db)
    return True


async def _avancar(estado: NatQualificacaoState, mensagem: str, db: AsyncSession) -> None:
    """Etapa cumprida: envia a fala e move o estado. ÚNICO lugar que faz as duas coisas."""
    etapa = estado.etapa

    if etapa in PROXIMA:
        await _enviar(estado, mensagem, db)
        estado.etapa = PROXIMA[etapa]
        print(f"➡️  Agente: {estado.contact_wa_id} {etapa} → {estado.etapa}")
        return

    if etapa == ETAPA_Q_AGUARDANDO_MOTIVACAO:
        # A bifurcação do roteiro. Releitura, não memória: a reunião pode ter nascido no
        # obrigado.html DEPOIS da abertura.
        reuniao = await _reuniao(estado, db)
        await _enviar(estado, mensagem, db)
        if reuniao is not None:
            estado.agendamento_id = reuniao.id
            await _concluir(estado, reuniao, db)
        else:
            estado.etapa = ETAPA_Q_OFERTANDO_AGENDA
            await _ofertar_agenda(estado, db)
        return

    # ofertando_agenda / escolhendo_slot com etapa_cumprida e sem acao=agendar_slot é
    # contradição do modelo: disse que cumpriu sem escolher horário nenhum.
    await _fallback(estado, f"etapa '{etapa}' dada como cumprida sem slot escolhido", db)


async def _ofertar_agenda(estado: NatQualificacaoState, db: AsyncSession) -> None:
    """Apresenta a grade. Os horários vêm de `disponibilidade`; o LLM só os veste."""
    contexto, ofertados = await _fatos(estado, db, com_slots=True)
    if not ofertados:
        await _fallback(estado, "não há horário livre na grade para oferecer", db)
        return
    resposta = await llm.conversar(missao=MISSOES[ETAPA_Q_OFERTANDO_AGENDA],
                                   contexto=contexto,
                                   historico=await _historico(estado.contact_wa_id, db))
    if resposta is None:
        await _fallback(estado, "LLM indisponível ao oferecer a agenda", db)
        return
    await _enviar(estado, resposta["mensagem"], db)
    estado.etapa = ETAPA_Q_ESCOLHENDO_SLOT
    print(f"📅 Agente ofereceu {len(ofertados)} horário(s) a {estado.contact_wa_id}")


async def _agendar(estado: NatQualificacaoState, resposta: dict, ofertados: dict,
                   db: AsyncSession) -> None:
    """Escreve a reunião. O slot é VALIDADO duas vezes antes de qualquer escrita.

    Primeiro contra o que foi realmente oferecido nesta rodada (o modelo não pode inventar
    um id), depois contra `slots_livres(usar_cache=False)` — porque entre oferecer e escolher
    passaram minutos e a grade é cacheada por 60s.
    """
    from app.agendamento import agendar as fluxo, disponibilidade

    slot_id = (resposta.get("dado_extraido") or {}).get("slot_id")
    if not slot_id or slot_id not in ofertados:
        await _fallback(estado, f"o LLM escolheu um horário que não foi oferecido "
                                f"({slot_id!r})", db)
        return

    livres = {d.id for d in await disponibilidade.slots_livres(db, usar_cache=False)}
    if slot_id not in livres:
        # Corrida: alguém pegou o horário. Não é falha — reapresenta a grade.
        print(f"↩️  Agente: slot {slot_id} não está mais livre; reofertando")
        estado.etapa = ETAPA_Q_OFERTANDO_AGENDA
        await _ofertar_agenda(estado, db)
        return

    contato = (await db.execute(select(Contact).where(
        Contact.wa_id == estado.contact_wa_id))).scalar_one_or_none()
    try:
        r = await fluxo.agendar(
            db, nome=(contato.name if contato else "") or "Lead", email=None,
            telefone=estado.contact_wa_id, slot_id=slot_id,
            origem=None,
            # SEMPRE com lead_id: é o que impede a pessoa de virar um segundo lead no funil.
            lead_id=estado.exact_lead_id,
            extras=None, origem_ip=None)
    except Exception as e:
        await _fallback(estado, f"agendamento falhou ({type(e).__name__}: {e})", db)
        return

    estado.agendamento_id = r.agendamento_id
    reuniao = await _reuniao(estado, db)
    await _enviar(estado, resposta["mensagem"], db)
    await _concluir(estado, reuniao, db)


async def _concluir(estado: NatQualificacaoState, reuniao, db: AsyncSession) -> None:
    """Missão cumprida: etapa `concluido` e lembrete agendado."""
    estado.etapa = ETAPA_Q_CONCLUIDO
    await db.flush()
    if reuniao is not None:
        await agendar_lembrete(reuniao, db)
    print(f"✅ Agente concluiu {estado.contact_wa_id}"
          f"{f' (reunião {reuniao.id})' if reuniao is not None else ''}")


# ==========================================================================================
# BLOCO F — LEMBRETE T-30MIN
# ==========================================================================================

async def agendar_lembrete(reuniao, db: AsyncSession) -> None:
    """Agenda o lembrete para `slot_inicio - 30min`. Idempotente por (kind, contato).

    Chamada dos DOIS nascimentos possíveis de uma reunião: o agente marcando (`_concluir`) e
    o obrigado.html marcando sozinho (`agendamento/agendar.py`). `nat_scheduler.agendar`
    cancela o pendente anterior antes de inserir, então chamar duas vezes reagenda em vez de
    duplicar — e o índice único parcial do banco é a rede da mesma regra.

    Reunião no passado não agenda nada: um `run_at` vencido dispararia no ciclo seguinte e
    mandaria "sua reunião é hoje às X" depois de X.
    """
    from app.exact_spotter import format_phone
    from app.nat_scheduler import agendar as agendar_acao

    if reuniao is None or not reuniao.slot_inicio:
        return
    quando = reuniao.slot_inicio - ANTECEDENCIA_LEMBRETE
    if quando <= _agora_sp():
        print(f"↩️  Agente: reunião {reuniao.id} é cedo demais para lembrete "
              f"({reuniao.slot_inicio:%d/%m %H:%M})")
        return
    wa_id = format_phone(reuniao.telefone or "")
    if not wa_id:
        return
    await agendar_acao(KIND_LEMBRETE_REUNIAO, wa_id, quando,
                       {"agendamento_id": reuniao.id}, db)


@registrar_handler("lembrete_reuniao")
async def lembrete_reuniao(acao: dict, db: AsyncSession) -> None:
    """T-30min. RELÊ tudo: entre agendar e executar passaram horas ou dias.

    Não envia e sai silencioso quando a reunião sumiu, mudou de horário para o passado, ou
    perdeu a consultora. Mesmo espírito das três saídas de `nat_recuperacao`: silencioso e
    bem-sucedido, porque "nada a fazer" não é erro.
    """
    from app.agendamento import consultoras as equipe

    payload = json.loads(acao.get("payload") or "{}")
    wa_id = acao["contact_wa_id"]
    reuniao_id = payload.get("agendamento_id")
    if not reuniao_id:
        print(f"↩️  Lembrete: sem agendamento_id para {wa_id}")
        return

    reuniao = (await db.execute(select(Agendamento).where(
        Agendamento.id == reuniao_id))).scalar_one_or_none()
    if reuniao is None or reuniao.passo != PASSO_AGENDADO:
        print(f"↩️  Lembrete: reunião {reuniao_id} não está mais agendada")
        return
    if reuniao.slot_inicio <= _agora_sp():
        print(f"↩️  Lembrete: reunião {reuniao_id} já começou "
              f"({reuniao.slot_inicio:%d/%m %H:%M}) — não envia atrasado")
        return

    consultora = equipe.nome_de(reuniao.sales_rep_email or "")
    if not consultora:
        print(f"↩️  Lembrete: reunião {reuniao_id} sem consultora resolvível")
        return

    nome = primeiro_nome(reuniao.nome or "")
    hora = reuniao.slot_inicio.strftime("%H:%M")
    parametros = [nome, hora, consultora]
    corpo = await _corpo_do_template(guard.ETAPA_LEMBRETE_REUNIAO, parametros, db)

    # `guard_de_abertura` e não `qualificacao_pode_atuar`: nesta altura a etapa é `concluido`,
    # em que o agente cala de propósito. O lembrete é a exceção combinada — e continua
    # sujeito à chave geral e ao teto por hora.
    await send_nat_message(wa_id, guard.ETAPA_LEMBRETE_REUNIAO, db,
                           guard=guard.guard_de_abertura,
                           parametros=parametros, corpo_livre=corpo)
