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
                        ETAPA_Q_ENCERRADO, KIND_ENCERRAR_INATIVO, KIND_LEMBRETE_REUNIAO,
                        Agendamento, Contact, Message, Notification, NatQualificacaoState,
                        PASSO_AGENDADO)
from app.nat_guard import (GESTOR_USER_ID, _agora_sp, dentro_horario_comercial,
                           proximo_horario_util)
from app.nat_scheduler import registrar_handler
from app.nat_sender import send_nat_message
from app.telefone import variantes_wa_id
from app.nomes import primeiro_nome

# Quantas mensagens da conversa vão para o modelo. 10 cobre o vaivém das 4 perguntas com
# folga para uma digressão, e mantém o custo previsível.
MAX_HISTORICO = 10

# Quanto antes da reunião o lembrete sai.
ANTECEDENCIA_LEMBRETE = timedelta(minutes=30)

# Silêncio do lead que encerra a qualificação. Constante nomeada porque é número de produto,
# não de engenharia: mudar a régua é mudar esta linha.
#
# 72h e não 24h: o lead é abordado logo depois de se candidatar, e "não respondeu no mesmo
# dia" é rotina — muita gente aplica de madrugada e volta no fim de semana. Encerrar cedo
# demais joga fora quem só demorou a ver o WhatsApp.
INATIVIDADE_ENCERRA = timedelta(hours=72)
MOTIVO_INATIVIDADE = "inatividade"

# O mesmo valor do decorator abaixo. Nomeado porque o handler reagenda a si mesmo quando
# acorda fora do horário comercial, e uma string solta em dois lugares diverge.
KIND_INICIAR_QUALIFICACAO_STR = "iniciar_qualificacao"

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

def _mais_relevante(linhas, variantes: tuple[str, ...], de):
    """Escolhe UMA linha quando o mesmo humano tem duas. Determinístico.

    A ordem de `variantes_wa_id` manda (a forma de 13 dígitos primeiro) e o `id` desempata.
    Sem isto, `scalar_one_or_none()` levantaria `MultipleResultsFound` no dia em que as duas
    threads existirem — e elas já existem para 340 pessoas.
    """
    if not linhas:
        return None
    ordem = {v: i for i, v in enumerate(variantes)}
    return sorted(linhas, key=lambda o: (ordem.get(de(o), 99), o.id))[0]


async def _contato_de(wa_id: str, db: AsyncSession) -> Contact | None:
    """O contato, achando também a thread gêmea sem o 9º dígito. Ver `app/telefone.py`."""
    vs = variantes_wa_id(wa_id)
    if not vs:
        return None
    res = await db.execute(select(Contact).where(Contact.wa_id.in_(vs)))
    return _mais_relevante(list(res.scalars()), vs, lambda c: c.wa_id)


async def estado_de(contact_wa_id: str, db: AsyncSession) -> NatQualificacaoState | None:
    """O estado do agente para este humano — nas DUAS grafias do telefone dele.

    Era `== contact_wa_id`. Com igualdade, o estado nascido da chave montada a partir do
    telefone do lead (13 dígitos, via `qualificacao_gatilho.wa_id_de`) nunca era encontrado
    pelo inbound, que chega com 12 para todo DDD fora de 11–28 — 59% das threads do Hub.
    O agente calava sem erro nenhum. Ver `app/telefone.py`.
    """
    vs = variantes_wa_id(contact_wa_id)
    if not vs:
        return None
    res = await db.execute(select(NatQualificacaoState).where(
        NatQualificacaoState.contact_wa_id.in_(vs)))
    return _mais_relevante(list(res.scalars()), vs, lambda e: e.contact_wa_id)


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
    # `in_` e não `==`: as duas grafias do telefone são a MESMA conversa, e ler só uma
    # delas daria ao modelo metade do diálogo — inclusive sem o template que ele mesmo
    # mandou, que sai para a grafia de 13 dígitos.
    res = await db.execute(
        select(Message.direction, Message.content, Message.message_type)
        .where(Message.contact_wa_id.in_(variantes_wa_id(contact_wa_id) or ("",)))
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
    contato = await _contato_de(estado.contact_wa_id, db)
    return primeiro_nome((contato.name if contato else "") or "")


def _espalhados(horarios: list[dict], n: int) -> list[dict]:
    """Até `n` horários do dia, ESPALHADOS da manhã à tarde, em ordem.

    Isto era um `[:6]` — os seis primeiros — e funcionava enquanto a grade tinha 5 horários
    por dia: cortar os seis primeiros de cinco não corta nada. Em 25/08/2026 a grade virou o
    comercial inteiro (09:00–18:30, 12 horários/dia) e o corte passou a devolver
    `09:00 09:45 10:30 11:15 12:00 12:45` — **o agente nunca mais ofereceria uma tarde**,
    em silêncio, e quem só pode à tarde ouviria "não tenho horário" com a tarde inteira
    livre.

    Espalhar em vez de aumentar o `n`: o limite existe porque a lista vai inteira para o
    prompt e uma parede de 12 horários por dia empurra o modelo a despejar tudo no
    WhatsApp. Seis pontos cobrindo 09:00–17:15 dizem mais sobre o dia do que doze.

    Extremos sempre entram — o primeiro e o último horário do dia são justamente os que
    resolvem quem só pode cedo ou só pode tarde.
    """
    if len(horarios) <= n or n < 2:
        return horarios[:n] if n < 2 else horarios
    passo = (len(horarios) - 1) / (n - 1)
    indices = sorted({round(i * passo) for i in range(n)})
    return [horarios[i] for i in indices]


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
            for h in _espalhados(por_dia[dia], 6):
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
        contato = await _contato_de(estado.contact_wa_id, db)
        dono = contato.assigned_to if contato else None
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


# ==========================================================================================
# HUMANO ASSUME, AGENTE SILENCIA
# ==========================================================================================

MOTIVO_ASSUMIDO_SDR = "assumido_sdr"
MOTIVO_OUTBOUND_MANUAL = "outbound_manual_sdr"


async def silenciar(contact_wa_id: str, motivo: str, db: AsyncSession, *,
                    quem_id: int | None = None, quem_nome: str | None = None) -> str | None:
    """Tira o agente da conversa AGORA. Devolve a etapa que ele deixou, ou None.

    Duas portas chamam isto:
      * o botão "Assumir conversa" (`nat_routes.assumir_conversa`), quando o SDR decide;
      * a trava automática (`routes._silenciar_agente_apos_envio_manual`), quando o SDR
        simplesmente digita — que é como a maioria vai acontecer, porque ninguém lembra de
        clicar num botão antes de responder.

    É PARENTE DE `_fallback`, MAS NÃO É ELE, e a diferença é o ponto da sprint:

        _fallback   o agente desistiu -> manda uma despedida ao lead e avisa o SDR
        silenciar   o humano chegou   -> NÃO manda NADA e NÃO avisa NINGUÉM

    Mandar a despedida aqui seria o defeito que esta sprint existe para impedir: o SDR digita
    "oi, sou o Thobias" e o lead recebe, logo depois, "vou te passar para um humano". Duas
    vozes na mesma thread, uma delas dizendo que vai fazer o que a outra acabou de fazer.
    E notificar tampouco: quem seria notificado é justamente quem acabou de agir.

    IDEMPOTENTE e SILENCIOSA no caso comum: sem estado, ou em etapa que já não é ativa,
    devolve None sem tocar em nada. É o que permite chamá-la de dentro de todo envio manual
    sem transformar cada mensagem de SDR numa escrita no banco.

    Tolerante ao 9º dígito por vir de `estado_de` — o wa_id da tela e o do estado podem estar
    em grafias diferentes (ver `app/telefone.py`).

    QUEM assumiu vai para `dados_extras`, não para coluna nova. `transferido_motivo` guarda o
    motivo literal e parseável que o produto pediu (`assumido_sdr`), e enfiar o nome junto
    ("assumido_sdr por Fulano") tornaria a coluna impossível de agrupar em relatório. Coluna
    nova exigiria migração numa tabela que ESTÁ EM PRODUÇÃO com o agente no ar — atrito
    desproporcional para um campo de auditoria. Se virar consulta frequente, promove-se a
    coluna depois.
    """
    estado = await estado_de(contact_wa_id, db)
    if estado is None or estado.etapa not in ETAPAS_QUALIFICACAO_ATIVAS:
        return None

    anterior = estado.etapa
    estado.etapa = ETAPA_Q_TRANSFERIDO
    estado.transferido_em = _agora_sp()
    estado.transferido_motivo = motivo
    if quem_id is not None or quem_nome:
        extras = dict(estado.dados_extras or {})
        extras["assumido_por"] = {"id": quem_id, "nome": quem_nome}
        estado.dados_extras = extras
    await db.flush()

    print(f"🤝 Agente silenciado em {estado.contact_wa_id}: {anterior} → "
          f"{ETAPA_Q_TRANSFERIDO} (motivo={motivo}"
          + (f", por {quem_nome}" if quem_nome else "") + ")")
    return anterior


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

    # HORÁRIO COMERCIAL (09h00–18h30, seg-sex). Só a ABERTURA respeita — ela é
    # business-initiated, e é a única mensagem que a pessoa não pediu.
    #
    # Fora da janela EMPURRA, não recusa: recusar deixaria sem abertura para sempre o lead
    # que se candidatou às 22h — e 22h é uma das horas de maior movimento da LP (8 dos 81
    # formulários medidos). Reagendar não consome tentativa: a ação atual termina
    # `executado` e uma nova nasce pendente, pelo mesmo `agendar` que o sla_check usa.
    agora = acao.get("agora") or _agora_sp()
    if not dentro_horario_comercial(agora):
        from app.nat_scheduler import agendar as agendar_acao
        quando = proximo_horario_util(agora)
        await agendar_acao(KIND_INICIAR_QUALIFICACAO_STR, wa_id, quando, payload, db)
        print(f"🌙 Agente: abertura de {wa_id} fora do horário ({agora:%H:%M}) — "
              f"empurrada para {quando:%d/%m %H:%M}")
        return

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

    # Tolerante ao 9º dígito: `wa_id` aqui vem de `qualificacao_gatilho.wa_id_de`, montado
    # do telefone do LEAD (13 dígitos), e a linha de `contacts` costuma existir na grafia do
    # INBOUND (12). Com igualdade, a abertura era abortada com "não existe em contacts" para
    # a maior parte dos leads — e o log dizia que o contato não existia, o que era mentira.
    contato = await _contato_de(wa_id, db)
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

    # Arma o relógio da inatividade já na abertura. Sem isto, quem NUNCA responde nunca
    # encerraria — e é justamente esse lead que a régua de follow-up quer receber.
    await _agendar_encerramento(estado, db)
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

    # O relógio da inatividade reinicia a cada mensagem DELA. `agendar` cancela o pendente
    # anterior antes de inserir, então isto reagenda em vez de acumular — e o índice único
    # parcial do banco é a rede da mesma regra.
    await _agendar_encerramento(estado, db)

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

    contato = await _contato_de(estado.contact_wa_id, db)
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


async def concluir_por_agendamento_externo(contact_wa_id: str, reuniao,
                                           db: AsyncSession) -> bool:
    """A pessoa agendou pela PÁGINA do token. Fecha o estado e confirma no chat.

    Devolve True se o agente falou. Nunca levanta: o agendamento já existe na Exact quando
    chegamos aqui, e falhar em confirmar não pode desfazer uma reunião real.

    ------------------------------------------------------------------------------------
    POR QUE NÃO DEU PARA REUSAR `_concluir`
    ------------------------------------------------------------------------------------
    `_concluir` fecha o estado e agenda o lembrete, mas NÃO manda mensagem — no fluxo dele a
    confirmação é a própria resposta do LLM naquele turno da conversa. Aqui não existe turno:
    o booking aconteceu numa aba do navegador, e do lado do WhatsApp o silêncio seria a
    última coisa que a pessoa veria depois de clicar no link que a Nat mandou.

    O lembrete T-30 NÃO é agendado aqui: `agendamento/agendar.py::_gatilho_do_agente` já o
    enfileira para todo agendamento que chega a `PASSO_AGENDADO`, venha de onde vier. Chamar
    de novo seria inofensivo (`nat_scheduler.agendar` cancela o pendente antes de inserir),
    mas duas fontes para a mesma ação é o tipo de coisa que diverge quando uma delas muda.

    ------------------------------------------------------------------------------------
    O TEXTO SAI DO BANCO, NUNCA DO MODELO
    ------------------------------------------------------------------------------------
    Data, hora e consultora vêm da linha de `agendamentos` que acabou de ser gravada. Um LLM
    escrevendo "sua reunião é quinta às 15h" a partir do contexto erraria em silêncio, e o
    erro só apareceria quando ninguém aparecesse na reunião.

    O guard é `guard_de_abertura`, não `qualificacao_pode_atuar`: a etapa já é `concluido`,
    que está fora das ativas, e o guard de envio recusaria a própria confirmação. Mesmo
    motivo e mesma solução de `_fallback`.
    """
    try:
        estado = await estado_de(contact_wa_id, db)
        if estado is None:
            return False
        if estado.etapa == ETAPA_Q_CONCLUIDO and estado.agendamento_id == reuniao.id:
            return False                      # reentrega: já fechamos este mesmo booking

        estado.etapa = ETAPA_Q_CONCLUIDO
        estado.agendamento_id = reuniao.id
        await db.flush()

        from app.agendamento import consultoras as equipe
        consultora = equipe.nome_de(reuniao.sales_rep_email or "")
        quando = reuniao.slot_inicio
        texto = (f"Prontinho! ✅ Sua conversa está marcada para "
                 f"{quando:%d/%m} às {quando:%H:%M} (horário de Brasília)"
                 + (f", com {consultora}" if consultora else "") + ".\n\n"
                 "Vou te lembrar 30 minutos antes. Se precisar remarcar, é só me falar "
                 "por aqui.")
        enviado = await send_nat_message(estado.contact_wa_id, guard.ETAPA_CONVERSA, db,
                                         guard=guard.guard_de_abertura, corpo_livre=texto)
        print(f"✅ Agente: {estado.contact_wa_id} agendou pela página "
              f"(reunião {reuniao.id}, {quando:%d/%m %H:%M})"
              f"{'' if enviado else ' — confirmação NÃO saiu'}")
        return enviado
    except Exception as e:
        print(f"⚠️  Agente: falha ao confirmar no chat o agendamento externo de "
              f"{contact_wa_id} ({type(e).__name__}: {e}). A reunião está de pé.")
        return False


# ==========================================================================================
# BLOCO F — LEMBRETE T-30MIN
# ==========================================================================================

async def agendar_lembrete(reuniao, db: AsyncSession) -> bool:
    """Agenda o lembrete para `slot_inicio - 30min`. Idempotente por (kind, contato).

    Devolve True só quando insere. Mesmo motivo de `agendar_abertura`: as saídas silenciosas
    (sem reunião, reunião no passado, sem telefone) não deixam nada para o chamador commitar.

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
        return False
    quando = reuniao.slot_inicio - ANTECEDENCIA_LEMBRETE
    if quando <= _agora_sp():
        print(f"↩️  Agente: reunião {reuniao.id} é cedo demais para lembrete "
              f"({reuniao.slot_inicio:%d/%m %H:%M})")
        return False
    wa_id = format_phone(reuniao.telefone or "")
    if not wa_id:
        return False
    await agendar_acao(KIND_LEMBRETE_REUNIAO, wa_id, quando,
                       {"agendamento_id": reuniao.id}, db)
    return True


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


# ==========================================================================================
# ITEM 3 — ENCERRAMENTO POR INATIVIDADE
# ==========================================================================================
#
# `ETAPA_Q_ENCERRADO` existia no CHECK e nas constantes e NENHUM código a atribuía — o mesmo
# defeito que o ESTADO_NAT_20260809 apontou no fluxo velho, onde `sem_contato` e `encerrado`
# eram constantes mortas. Aqui ela ganha um caminho.
#
# O QUE MUDA QUANDO UM LEAD É ENCERRADO
#   * `encerrado` está FORA de ETAPAS_QUALIFICACAO_ATIVAS: o agente deixa de ser dono do
#     inbound (precedência do webhook) e deixa de poder enviar (qualificacao_pode_atuar);
#   * se o lead responder DEPOIS, `processar_texto` devolve False e a mensagem segue para o
#     caminho de sempre — o fluxo humano. O agente NÃO reabre a conversa sozinho: ele já
#     desistiu uma vez, e reabrir com base numa resposta tardia faria a pessoa receber uma
#     pergunta de três dias atrás como se nada tivesse acontecido;
#   * o lead vira candidato limpo à régua de follow-up, quando ela existir.


async def _agendar_encerramento(estado: NatQualificacaoState, db: AsyncSession) -> None:
    """(Re)agenda o encerramento por inatividade. Nunca levanta — é higiene, não fluxo."""
    try:
        from app.nat_scheduler import agendar as agendar_acao
        await agendar_acao(KIND_ENCERRAR_INATIVO, estado.contact_wa_id,
                           _agora_sp() + INATIVIDADE_ENCERRA, {}, db)
    except Exception as e:
        print(f"⚠️  Agente: encerramento não agendado para {estado.contact_wa_id} "
              f"({type(e).__name__}: {e})")


@registrar_handler("encerrar_inativo")
async def encerrar_inativo(acao: dict, db: AsyncSession) -> None:
    """72h de silêncio numa etapa ativa → `encerrado`.

    RELÊ o estado, nunca confia no payload: entre agendar e executar passam três dias, e
    nesse intervalo o lead pode ter respondido (o que reagenda esta ação), sido transferido,
    ou concluído com reunião marcada.

    Saída silenciosa e bem-sucedida quando não há o que fazer — mesmo espírito das três
    saídas de `nat_recuperacao`. NÃO envia mensagem nenhuma ao lead: quem parou de responder
    não precisa de um aviso de que parou.
    """
    wa_id = acao["contact_wa_id"]
    estado = await estado_de(wa_id, db)
    if estado is None:
        print(f"↩️  Encerramento: {wa_id} não tem estado — nada a fazer")
        return
    if estado.etapa not in ETAPAS_QUALIFICACAO_ATIVAS:
        print(f"↩️  Encerramento: {wa_id} já está em '{estado.etapa}' — nada a fazer")
        return

    estado.etapa = ETAPA_Q_ENCERRADO
    estado.encerrado_em = _agora_sp()
    estado.encerrado_motivo = MOTIVO_INATIVIDADE
    await db.flush()
    print(f"🌑 Agente encerrou {wa_id} por inatividade "
          f"({INATIVIDADE_ENCERRA.total_seconds() / 3600:.0f}h sem resposta)")
