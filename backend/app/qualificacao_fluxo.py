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
                        KIND_RESPONDER_PENDENTE,
                        Agendamento, Contact, Message, Notification, NatQualificacaoState,
                        PASSO_AGENDADO)
from app.nat_guard import (GESTOR_USER_ID, _agora_sp, dentro_horario_comercial,
                           proximo_horario_util)
from app.nat_scheduler import (AcaoAdiada, AcaoIgnorada, agendar as nat_agendar,
                               cancelar as nat_cancelar, registrar_handler)
from app.nat_sender import enviar_nat, send_nat_message
from app.telefone import variantes_wa_id
from app.nomes import primeiro_nome

# Quantas mensagens da conversa vão para o modelo. 10 cobre o vaivém das 4 perguntas com
# folga para uma digressão, e mantém o custo previsível.
MAX_HISTORICO = 10

# Quanto antes da reunião o lembrete sai.
ANTECEDENCIA_LEMBRETE = timedelta(minutes=30)

# De quanto em quanto tempo uma abertura barrada pelo TETO por hora volta a tentar.
#
# O teto é uma contagem MÓVEL de 1h (qualificacao_guard.contar_envios_ultima_hora), então ele
# se resolve sozinho conforme os envios antigos saem da janela — não há um instante exato para
# esperar, e mirar "a hora cheia" seria pior: concentraria de novo todo mundo no mesmo minuto.
# 10 min é o passo que espalha a fila sem fazer o lead esperar.
#
# MEDIDO em 24/08: ~7 aberturas caem juntas no pico das 09h, contra teto de 20/h. Isto é uma
# rede, não um caminho quente.
ATRASO_POR_TETO = timedelta(minutes=10)

# Silêncio do lead que encerra a qualificação. Constante nomeada porque é número de produto,
# não de engenharia: mudar a régua é mudar esta linha.
#
# 72h e não 24h: o lead é abordado logo depois de se candidatar, e "não respondeu no mesmo
# dia" é rotina — muita gente aplica de madrugada e volta no fim de semana. Encerrar cedo
# demais joga fora quem só demorou a ver o WhatsApp.
INATIVIDADE_ENCERRA = timedelta(hours=72)
MOTIVO_INATIVIDADE = "inatividade"

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
        'Ofereça NO MÁXIMO 5 horários, escolhidos entre os do contexto e espalhados entre '
        'os dias e entre manhã e tarde. NÃO liste todos. Depois dos 5, TERMINE convidando: '
        'se nenhum servir, que ela diga que dia e período prefere, que você procura. '
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


async def _identidade_do_lead(lead_id: int | None, db: AsyncSession) -> tuple[str, str | None]:
    """`(nome, sdr_name)` do lead, de onde houver. `("", None)` quando não há nada.

    Duas fontes na ordem em que ficam prontas: `exact_leads` é a boa (traz o SDR), mas o lead
    da LP pode ainda não ter sido sincronizado — MEDIDO, o sync leva até 10 min e a abertura
    dispara em 5. `agendamentos` tem o nome desde o instante do formulário, e é o que salva o
    caso comum de quem acabou de se candidatar.
    """
    if not lead_id:
        return "", None
    from app.models import ExactLead
    lead = (await db.execute(
        select(ExactLead).where(ExactLead.exact_id == lead_id))).scalar_one_or_none()
    if lead is not None:
        return (lead.name or ""), lead.sdr_name
    nome = (await db.execute(
        select(Agendamento.nome).where(Agendamento.lead_id == lead_id)
        .order_by(Agendamento.id.desc()).limit(1))).scalar_one_or_none()
    return (nome or ""), None


async def _contato_ou_criar(wa_id: str, *, lead_id: int | None,
                            db: AsyncSession) -> Contact | None:
    """O `Contact` para quem a abertura vai sair — CRIANDO-O se ele ainda não existe.

    ------------------------------------------------------------------------------------
    POR QUE CRIAR, E POR QUE ISTO ERA O BUG DE 25/08
    ------------------------------------------------------------------------------------
    `contacts` só nascia de dois jeitos: mensagem inbound do lead, ou efeito colateral do
    envio da BOAS-VINDAS (`send_welcome_to_new_lead` cria o Contact junto com a Message do
    template). O passo 4.5 cede a abertura ao agente e sai ANTES disso, e nada passou a criar
    o contato no lugar.

    Quem se candidata pela landing page e nunca mandou mensagem simplesmente não existe em
    `contacts`. MEDIDO nos 45 leads de 25/08: 33 sem linha, 11 com. Três de cada quatro leads
    não podiam receber abertura nenhuma — com a fila cheia, o agendador drenando e o agente
    ligado. O agente herdou a dependência da boas-vindas sem herdar quem a satisfazia.

    ------------------------------------------------------------------------------------
    POR QUE A BUSCA AQUI É ESTRITA, E NÃO TOLERANTE AO 9º DÍGITO
    ------------------------------------------------------------------------------------
    Este contato existe para UMA coisa: ser encontrado por `nat_sender`, que faz
    `Contact.wa_id == contact_wa_id`, igualdade crua. Um porteiro tolerante aqui não ajuda o
    envio — ele só decide se a função segue adiante — e em 25/08 fez pior que não ajudar:

        wa_id do lead   5582998307979  (Ronaldo Cesar, formulário da LP)
        variante de 12  558298307979   -> já existia em contacts como **Pablo Valente**

    A variante sem o 9º dígito do número de um é o número de OUTRA PESSOA (`app/telefone.py`
    documenta por que a tolerância é ambígua justamente para local de 8 dígitos começando em
    9). O porteiro abriu, o estado nasceu na linha de um estranho, e só não houve envio para
    a pessoa errada porque o sender é estrito e não achou os 13 dígitos. A inconsistência
    entre os dois foi o que impediu o estrago.

    Então a regra passa a ser UMA: o contato da abertura é o da grafia para a qual vamos
    mandar a mensagem. É exatamente o que a boas-vindas sempre fez
    (`select(Contact).where(Contact.wa_id == phone)` e cria se não achar) — o comportamento
    que o agente deveria ter herdado.

    A tolerância continua onde ela é certa e não pode escrever nada: `estado_de` (o mesmo
    humano não pode ganhar dois estados) e o histórico da conversa.

    Devolve None só se não houver canal — sem canal o envio não sairia de qualquer forma, e
    um Contact órfão sem `channel_id` seria lixo.
    """
    achado = (await db.execute(
        select(Contact).where(Contact.wa_id == wa_id))).scalar_one_or_none()
    if achado is not None:
        # Contato que existe SEM nome recebe o nome do lead — exatamente o que a boas-vindas
        # faz no passo 7 (`if not contact.name: contact.name = name`). Sem isto, um contato
        # criado por outro caminho (disparo em massa, inbound de perfil sem nome) mantém o
        # nome vazio para sempre, e o `{{1}}` vazio faz a Meta recusar a abertura inteira.
        if not (achado.name or "").strip():
            nome_do_lead, _ = await _identidade_do_lead(lead_id, db)
            if nome_do_lead:
                achado.name = nome_do_lead
                print(f"👤 Agente: nome de {wa_id} preenchido do lead ({nome_do_lead})")
        return achado

    from app.models import AutoWelcomeConfig
    from app.sdr_mapping import resolve_sdr_user_id

    # Mesmo canal que a boas-vindas usa, pela mesma leitura que `nat_sender._resolver_canal`
    # já faz — uma fonte de verdade para a credencial do WABA, não duas.
    cfg = (await db.execute(
        select(AutoWelcomeConfig).where(AutoWelcomeConfig.id == 1))).scalar_one_or_none()
    channel_id = cfg.channel_id if cfg else None
    if channel_id is None:
        return None

    nome, sdr_name = await _identidade_do_lead(lead_id, db)
    contato = Contact(
        wa_id=wa_id,
        name=nome or None,
        channel_id=channel_id,
        # ai_active=False, e aqui a boas-vindas NÃO é o modelo a seguir. Lá o True entrega a
        # conversa ao `ai_engine`; aqui quem conduz é o agente, e marcar o lead como "a IA
        # genérica responde" seria pedir dois robôs na mesma thread no dia em que aquele
        # trecho do webhook (hoje comentado) voltar.
        ai_active=False,
        lead_status="novo",
        assigned_to=resolve_sdr_user_id(sdr_name),
    )
    db.add(contato)
    await db.flush()
    print(f"👤 Agente: contato {wa_id} criado para a abertura "
          f"({nome or 'sem nome'}, canal {channel_id})")
    return contato


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
    """Primeiro nome do lead. DUAS fontes, porque uma só não cobre.

    `contacts.name` nasce do perfil do WhatsApp e está VAZIO em 4 490 linhas do Hub — quem
    nunca mandou mensagem e quem tem o perfil sem nome público. Este campo era a única fonte,
    e um nome vazio aqui vira `{{1}}` vazio no template, que a Meta recusa inteiro:

        (#131008) Required parameter is missing
        details: 'Parameter of type text is missing text value'

    Não é degradação elegante: a mensagem simplesmente não sai. Em 25/08 derrubou 3 das 18
    aberturas do backfill (Karen, Marlen, Beatriz) — e as três tinham nome em `exact_leads` o
    tempo todo. A Beatriz é a prova do mecanismo: o perfil dela chegou às 20:18 e a recusa
    dela foi às 19:46, com o mesmo número e o mesmo template.

    A segunda fonte é o cadastro do lead, que é onde o nome sempre esteve — o mesmo lugar de
    onde `_contato_ou_criar` tira o nome ao criar o contato.
    """
    contato = await _contato_de(estado.contact_wa_id, db)
    nome = primeiro_nome((contato.name if contato else "") or "")
    if nome:
        return nome
    do_lead, _ = await _identidade_do_lead(estado.exact_lead_id, db)
    return primeiro_nome(do_lead or "")


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

    ISTO NÃO É O QUE A PESSOA VÊ. Este `n` corta o que vai para o CONTEXTO — a lista da qual
    o modelo pode escolher, e a garantia de que ele não inventa horário. Quantos deles são
    APRESENTADOS é regra da missão de `ofertando_agenda`, hoje no máximo 5. Os dois números
    são diferentes de propósito: 3 dias × 6 dão ao modelo margem para atender "prefiro de
    manhã" sem uma segunda consulta à grade; 5 é o que cabe numa mensagem de WhatsApp sem
    virar parede. A Fabiana recebeu 14 numa mensagem só, em 25/08.

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

async def _enviar(estado: NatQualificacaoState, texto: str,
                  db: AsyncSession) -> tuple[bool, str]:
    """Fala livre do agente, dentro da janela de 24h. `(saiu, motivo)`."""
    return await enviar_nat(
        estado.contact_wa_id, guard.ETAPA_CONVERSA, db,
        guard=guard.qualificacao_pode_atuar, corpo_livre=texto)


async def _descartar_fala_adiada(estado: NatQualificacaoState, porque: str,
                                 db: AsyncSession) -> None:
    """Joga fora a fala que o teto adiou. Nunca levanta — higiene não derruba turno.

    ------------------------------------------------------------------------------------
    A ARESTA DAS DUAS FALAS FORA DE ORDEM
    ------------------------------------------------------------------------------------
    O adiamento por teto (P0-B) guarda o texto do turno e tenta de novo em 10 min. Entre
    agendar e disparar, a pessoa pode escrever DE NOVO — e escreve, justamente porque não
    recebeu resposta. O turno novo roda na etapa que já avançou (o `_avancar` move a etapa
    mesmo quando a fala foi só adiada: o dado extraído não pode se perder) e produz a fala
    da etapa seguinte. Dois desfechos:

        o turno novo TAMBÉM é recusado pelo teto -> `nat_agendar` cancela o pendente do
            mesmo (kind, contato) antes de inserir. Só o texto mais novo sobrevive. Já
            estava certo, por construção do agendador.

        o turno novo CONSEGUE falar (o teto é contagem MÓVEL de 1h — ele libera sozinho
            dentro dos 10 min) -> sem este cancelamento, a fala velha dispara depois e a
            pessoa recebe a pergunta do passo ANTERIOR depois da do passo seguinte. Duas
            falas fora de ordem, e a segunda perguntando o que ela já respondeu.

    NADA SE PERDE AO DESCARTAR. A fala adiada era o reconhecimento + a pergunta da etapa em
    que o lead já está; como ela nunca chegou a sair, o turno novo faz a mesma pergunta com
    contexto mais fresco. O que se descarta é uma duplicata velha, não informação.

    Chamado nos dois pontos em que o agente EFETIVAMENTE fala com o lead: quando a fala sai
    (`_falar`) e quando ele se despede (`_fallback`). Depois de qualquer um dos dois, uma
    fala velha na fila só pode piorar a conversa.
    """
    try:
        await nat_cancelar(KIND_RESPONDER_PENDENTE, estado.contact_wa_id, db)
    except Exception as e:
        print(f"⚠️  Agente: fala adiada de {estado.contact_wa_id} não cancelada "
              f"({porque}): {type(e).__name__}: {e}")


async def _falar(estado: NatQualificacaoState, texto: str, db: AsyncSession) -> bool:
    """Fala — e trata a RECUSA, que até 26/08 era jogada fora. Devolve se o turno segue.

    ------------------------------------------------------------------------------------
    O BURACO MAIS LARGO DOS SEIS (P0-B)
    ------------------------------------------------------------------------------------
    `_enviar` sempre soube dizer se a mensagem saiu. Ninguém lia. `processar_texto`,
    `_avancar` e `_ofertar_agenda` chamavam `await _enviar(...)` e descartavam o retorno,
    devolviam True ("tratei") e o turno terminava normalmente — sem mensagem, sem fallback,
    sem notificação e SEM EXCEÇÃO. Silêncio perfeito, invisível em qualquer tabela.

    MEDIDO em 25/08: matou 4 mensagens do 5583988046720 e 2 do 5582998307979. As duas
    conversas morreram sem deixar um único rastro ligado ao lead — só uma linha de `print`
    no journald que nem sempre chegava a sair do buffer.

    A RECUSA TEM DUAS NATUREZAS, E TRATÁ-LAS IGUAL É O ERRO:

        teto por hora   -> passa sozinho. REENFILEIRA a fala e tenta de novo em 10 min.
                           É a mesma lógica que `iniciar_qualificacao` já usa com AcaoAdiada:
                           o teto é contagem MÓVEL, esperar resolve. Transferir o lead para
                           humano por causa de uma janela cheia seria queimar lead por
                           congestionamento.
        qualquer outra  -> não passa sozinha (janela fechada, chave desligada, template não
                           montável, Meta recusou). `_fallback`: despedida + notificação.

    A fala reenfileirada é a MESMA que o LLM gerou agora. Ela pode chegar até 10 min depois
    do inbound e soar um pouco atrasada — e isso é aceitável de propósito: a alternativa
    medida é o lead nunca receber nada. Se o lead escrever nesse intervalo, o cancelamento
    de `_descartar_fala_adiada` impede que as duas falas cheguem fora de ordem.

    DORMENTE DESDE O P1-B (26/08). O teto por hora saiu de `qualificacao_pode_atuar`, então
    a CONVERSA não é mais recusada por ele e este ramo não deve disparar em produção. Fica
    inteiro de propósito: ele é a rede se o teto voltar a valer para a conversa (a auditoria
    previu essa hipótese como "opção B"), e `enviar_nat` repassa o motivo do guard tal e
    qual — qualquer trava futura que se chame teto cai aqui e é ADIADA, não descartada.
    """
    saiu, motivo = await _enviar(estado, texto, db)
    if saiu:
        await _descartar_fala_adiada(estado, "o agente acabou de falar", db)
        return True

    if guard.e_teto(motivo):
        await nat_agendar(KIND_RESPONDER_PENDENTE, estado.contact_wa_id,
                          _agora_sp() + ATRASO_POR_TETO, {"texto": texto}, db)
        print(f"⏳ Agente: fala para {estado.contact_wa_id} adiada ({motivo}) — "
              f"reenfileirada para daqui a {int(ATRASO_POR_TETO.total_seconds() // 60)} min")
        return False

    await _fallback(estado, f"envio recusado: {motivo}", db)
    return False


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

    Por isso o envio usa `guard_de_despedida` e não `qualificacao_pode_atuar`: a etapa já não
    é ativa, e o guard de envio recusaria a própria mensagem de despedida. Era
    `guard_de_abertura` até 26/08 (P1-B) — e com ele vinha o teto por hora, que podia calar
    exatamente a mensagem cuja razão de existir é não deixar o lead no silêncio.
    """
    print(f"🛟 Agente transferiu {estado.contact_wa_id} para humano: {motivo}")
    await _descartar_fala_adiada(estado, "o lead foi transferido", db)
    estado.etapa = ETAPA_Q_TRANSFERIDO
    estado.transferido_em = _agora_sp()
    estado.transferido_motivo = motivo
    await db.flush()

    await send_nat_message(estado.contact_wa_id, guard.ETAPA_CONVERSA, db,
                           guard=guard.guard_de_despedida, corpo_livre=TEXTO_FALLBACK)
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

    NENHUMA SAÍDA DAQUI É SILENCIOSA (Risco 3). Até 25/08 este handler tinha cinco `return`
    mudos, e os cinco viravam `executado` — a mesma marca de quem abriu a conversa. Foi assim
    que 4 ações executadas produziram ZERO estados sem nada quebrar. Agora:

        não dá para agir AGORA  -> AcaoAdiada  (fora do horário, teto por hora) — volta a
                                   `pendente` com run_at empurrado, SEM consumir tentativa
        não há o que fazer      -> AcaoIgnorada (já tem estado, anterior ao corte, sem
                                   contato possível) — vira `skipped` com o motivo no banco
        abriu                   -> `executado`, e agora isso significa uma coisa só

    Levantar em vez de `return` também reverte o savepoint do handler, o que apaga de graça
    o Contact e o estado criados antes de se descobrir que a abertura não sairia — a limpeza
    que o `db.delete(estado)` fazia à mão, e que não cobria o contato.
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
    # formulários medidos).
    #
    # É a MESMA linha que continua pendente, com o run_at empurrado — e não uma linha nova
    # como antes. A versão anterior chamava `agendar`, que começa cancelando o pendente do
    # par (kind, contato): ou seja, cancelava a própria ação em execução e só não estragava
    # nada porque o `_finalizar` logo depois a reescrevia para `executado`. Adiar a linha no
    # lugar tira esse cruzamento, não gasta id, e mantém o histórico da espera num lugar só.
    agora = acao.get("agora") or _agora_sp()
    if not dentro_horario_comercial(agora):
        raise AcaoAdiada(proximo_horario_util(agora),
                         f"fora do horário comercial ({agora:%H:%M})")

    ja = await estado_de(wa_id, db)
    if ja is not None:
        # NÃO é lead perdido: é lead já atendido. Vira `skipped` justamente para o §2b do
        # monitor parar de confundir os dois — ele procura ação EXECUTADA sem estado, e um
        # booking espontâneo caía aqui e produzia essa assinatura como falso positivo.
        raise AcaoIgnorada(f"já tem estado ({ja.etapa}) — abertura desnecessária")

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
        # O TETO É O ÚNICO "NÃO" QUE VIRA "SIM" SOZINHO. Corte de data e chave desligada não
        # mudam de ideia em dez minutos; o teto por hora muda, porque a contagem é móvel.
        # Tratar os dois igual era descartar lead por causa de uma janela cheia.
        if guard.e_teto(motivo):
            raise AcaoAdiada(agora + ATRASO_POR_TETO, motivo)
        raise AcaoIgnorada(f"não admitido: {motivo}")

    contato = await _contato_ou_criar(wa_id, lead_id=lead_id, db=db)
    if contato is None:
        raise AcaoIgnorada("não foi possível resolver nem criar o contato "
                           "(sem canal configurado?)")

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
    enviado, motivo_envio = await enviar_nat(wa_id, etapa_msg, db,
                                             guard=guard.guard_de_abertura,
                                             parametros=parametros, corpo_livre=corpo)
    if not enviado:
        # Sem abertura não há conversa — e o savepoint do handler leva embora o estado E o
        # contato recém-criados, sem `db.delete` à mão (que só cobria o estado).
        #
        # O teto pode estourar AQUI mesmo tendo passado na admissão: entre uma coisa e outra
        # o `_corpo_do_template` faz uma chamada à Meta, e outras aberturas do mesmo ciclo
        # podem ter enchido a janela nesse intervalo. Adiar em vez de descartar é o que faz a
        # segunda linha de defesa não custar o lead.
        if guard.e_teto(motivo_envio):
            raise AcaoAdiada(agora + ATRASO_POR_TETO, motivo_envio)
        raise AcaoIgnorada(f"abertura não saiu: {motivo_envio}")

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
                                   historico=await _historico(contact_wa_id, db),
                                   rotulo=f"{contact_wa_id}/{etapa}")
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
        await _falar(estado, resposta["mensagem"], db)
        return True

    await _avancar(estado, resposta["mensagem"], db)
    return True


async def _avancar(estado: NatQualificacaoState, mensagem: str, db: AsyncSession) -> None:
    """Etapa cumprida: envia a fala e move o estado. ÚNICO lugar que faz as duas coisas."""
    etapa = estado.etapa

    if etapa in PROXIMA:
        # A etapa anda mesmo se a fala foi só ADIADA pelo teto: o dado do lead já foi
        # extraído e regravar a etapa depois exigiria guardar o turno inteiro. O que não
        # pode acontecer — e não acontece — é a etapa andar depois de um `_fallback`, que
        # já move o estado para `transferido_humano` antes de voltar.
        if not await _falar(estado, mensagem, db) and estado.etapa == ETAPA_Q_TRANSFERIDO:
            return
        estado.etapa = PROXIMA[etapa]
        print(f"➡️  Agente: {estado.contact_wa_id} {etapa} → {estado.etapa}")
        return

    if etapa == ETAPA_Q_AGUARDANDO_MOTIVACAO:
        # A bifurcação do roteiro. Releitura, não memória: a reunião pode ter nascido no
        # obrigado.html DEPOIS da abertura.
        reuniao = await _reuniao(estado, db)
        if not await _falar(estado, mensagem, db) and estado.etapa == ETAPA_Q_TRANSFERIDO:
            return
        if reuniao is not None:
            estado.agendamento_id = reuniao.id
            await _concluir(estado, reuniao, db, confirmar=True)
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
                                   historico=await _historico(estado.contact_wa_id, db),
                                   rotulo=f"{estado.contact_wa_id}/ofertar_agenda"
                                          f"[{len(ofertados)} slots]")
    if resposta is None:
        await _fallback(estado, "LLM indisponível ao oferecer a agenda", db)
        return
    if not await _falar(estado, resposta["mensagem"], db) \
            and estado.etapa == ETAPA_Q_TRANSFERIDO:
        return
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
    nome = (contato.name if contato else "") or "Lead"
    try:
        # ----------------------------------------------------------------------------------
        # P0-A — `agendar` PRECISA DE UMA TRANSAÇÃO QUE ELE POSSUA (26/08/2026)
        # ----------------------------------------------------------------------------------
        # Era `fluxo.agendar(db, ...)`, com a sessão DO WEBHOOK, de dentro do
        # `async with db.begin_nested()` de `main.py`. E `agendar._marcar` faz `db.commit()`
        # a cada passo — de propósito, e a razão está no docstring dele: sem o commit por
        # passo, um processo morto no meio do fluxo perderia a linha inteira, e a FAXINA
        # nunca saberia que existe um box nosso pendurado na agenda real da consultora.
        #
        # O commit é certo. O que estava errado era a transação que ele recebia: commitar
        # fecha o savepoint do webhook, e a instrução seguinte levanta
        # `InvalidRequestError: Can't operate on closed transaction inside context manager`.
        # Aí o `_fallback` morre no MESMO erro e o savepoint reverte até a etapa
        # `transferido_humano` que ele acabou de escrever.
        #
        # MEDIDO em 25/08 com a Fabiana (5517997379129): 3 mensagens, 3 exceções, 3
        # rollbacks, ZERO notificações, ZERO mensagens. E não era bug raro — era bug de
        # 100% dos agendamentos feitos pelo agente; teve uma vítima só porque só uma pessoa
        # chegou até aqui.
        #
        # A SESSÃO PRÓPRIA é a opção que NÃO TOCA no `_marcar`: o caminho da LP — que é o de
        # maior volume e o que traz dinheiro — continua byte por byte o que era, e o agente
        # passa a rodar o mesmo fluxo com a mesma durabilidade por passo. As alternativas
        # custavam mais: tornar o commit condicional apagaria a durabilidade justo no
        # caminho do agente (box órfão INVISÍVEL para a faxina), e enfileirar no scheduler
        # poria o lead esperando até 60s logo depois de escolher o horário.
        #
        # ABERTA SÓ AQUI, e não no começo do turno: o turno já segura uma conexão do webhook
        # durante `llm.conversar` (3–5s), e abrir a segunda cedo dobraria a retenção num
        # pool que acabou de ser dimensionado (P1-A). Ela vive o tempo do agendamento e
        # fecha antes de qualquer outra coisa acontecer no turno.
        #
        # `read committed` é o que faz isto funcionar: o `_reuniao()` logo abaixo roda na
        # sessão do webhook — cuja transação começou ANTES — e ainda assim enxerga a linha
        # que esta sessão commitou. Conferido em produção
        # (`default_transaction_isolation = read committed`).
        from app.database import async_session
        async with async_session() as db_agendamento:
            r = await fluxo.agendar(
                db_agendamento, nome=nome, email=None,
                telefone=estado.contact_wa_id, slot_id=slot_id,
                origem=None,
                # SEMPRE com lead_id: é o que impede a pessoa de virar um segundo lead no
                # funil.
                lead_id=estado.exact_lead_id,
                extras=None, origem_ip=None)
    except Exception as e:
        await _fallback(estado, f"agendamento falhou ({type(e).__name__}: {e})", db)
        return

    estado.agendamento_id = r.agendamento_id
    reuniao = await _reuniao(estado, db)
    # A reunião JÁ EXISTE na Exact neste ponto. Se a confirmação não sai, o estado ainda
    # tem de fechar — senão o agente continua "escutando" um lead cuja reunião está marcada.
    await _falar(estado, resposta["mensagem"], db)
    if estado.etapa != ETAPA_Q_TRANSFERIDO:
        await _concluir(estado, reuniao, db)


async def _concluir(estado: NatQualificacaoState, reuniao, db: AsyncSession, *,
                    confirmar: bool = False) -> None:
    """Missão cumprida: etapa `concluido` e lembrete agendado.

    ------------------------------------------------------------------------------------
    `confirmar` — A PROMESSA QUE O AGENTE FAZIA E NÃO CUMPRIA
    ------------------------------------------------------------------------------------
    A MISSAO de `aguardando_motivacao` manda, sem condição: "Termine dizendo que vai ver os
    horários disponíveis". Ela não pode ser condicional — o modelo não sabe se a pessoa já
    tem reunião, e essa é justamente a informação que só o código tem.

    A bifurcação em `_avancar` tem dois ramos e, até 26/08, só um falava depois:

        sem reunião -> _ofertar_agenda -> manda os horários          ✅
        com reunião -> _concluir       -> CALAVA                     ❌

    MEDIDO em 26/08 09h02 com a Evelyn (`nat_abertura_agendado`, reunião 205 já marcada):

        09:02:01 agente: "...Vou ver os horários disponíveis para a sua reunião com a
                          Victória Amorim e te retorno em seguida."
        09:02:14 ela:    "Obrigada 😃"
        (nada, nunca)

    E o silêncio era definitivo: `concluido` está fora de ETAPAS_QUALIFICACAO_ATIVAS, então
    o "Obrigada" seguinte já nem foi escutado. Não é um caso de borda — é TODO lead que
    chega com reunião marcada, a faixa inteira da abertura T1.

    O fecho é determinístico e não passa pelo LLM: ele afirma data, hora e consultora, que
    são fatos do banco. Uma promessa quebrada não se conserta com criatividade.

    Só `_avancar` pede `confirmar=True`. Vindo de `_agendar`, a fala do modelo ACABOU de
    confirmar o horário escolhido — um segundo texto aqui seria a mesma notícia duas vezes.
    """
    estado.etapa = ETAPA_Q_CONCLUIDO
    await db.flush()

    if confirmar and reuniao is not None:
        from app.agendamento import consultoras as equipe
        quem = equipe.nome_de(reuniao.sales_rep_email or "")
        await _falar(estado, (
            f"Na verdade você já tem horário reservado: "
            f"{reuniao.slot_inicio.strftime('%d/%m às %H:%M')}"
            f"{f' com {quem}' if quem else ''}. "
            f"Te espero lá! Se precisar remarcar, é só me dizer. 🙂"), db)

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


@registrar_handler("responder_pendente")
async def responder_pendente(acao: dict, db: AsyncSession) -> None:
    """A fala que o TETO por hora adiou. Tenta de novo; adia outra vez se ainda não couber.

    Existe pelo mesmo motivo que `AcaoAdiada` existe na abertura: o teto é contagem MÓVEL de
    1h, então ele passa sozinho — e recusar por causa dele é perder o lead por
    congestionamento, não por regra de negócio.

    O ESTADO É RELIDO, nunca vem do payload: entre agendar e executar passam 10 minutos, e
    nesse intervalo a pessoa pode ter escrito de novo (a etapa andou), um humano pode ter
    assumido, ou o encerramento por inatividade pode ter corrido. Só o texto vem do payload,
    porque é a única coisa que o banco não sabe reconstruir.
    """
    wa_id = acao["contact_wa_id"]
    texto = (json.loads(acao.get("payload") or "{}")).get("texto") or ""
    if not texto.strip():
        raise AcaoIgnorada("sem texto para reenviar")

    estado = await estado_de(wa_id, db)
    if estado is None or estado.etapa not in ETAPAS_QUALIFICACAO_ATIVAS:
        # Não é falha: humano assumiu, lead concluiu ou o silêncio encerrou. Falar agora
        # seria o agente reaparecendo numa conversa que já não é dele.
        raise AcaoIgnorada(f"etapa não é mais ativa "
                           f"({estado.etapa if estado else 'sem estado'})")

    saiu, motivo = await _enviar(estado, texto, db)
    if saiu:
        print(f"⏳→✅ Agente: fala adiada entregue a {wa_id}")
        return
    if guard.e_teto(motivo):
        raise AcaoAdiada(_agora_sp() + ATRASO_POR_TETO, motivo)
    # Não é mais o teto: virou recusa definitiva enquanto esperávamos. Fecha com humano em
    # vez de tentar para sempre.
    await _fallback(estado, f"envio recusado ao reenviar fala adiada: {motivo}", db)


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
