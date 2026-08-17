from sqlalchemy import Column, String, Text, DateTime, BigInteger, Integer, Boolean, ForeignKey, func, Table, CheckConstraint
from sqlalchemy.orm import relationship
from app.database import Base


contact_tags = Table(
    "contact_tags",
    Base.metadata,
    Column("contact_wa_id", String(20), ForeignKey("contacts.wa_id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    phone_number = Column(String(20), nullable=False)
    phone_number_id = Column(String(50), nullable=False)
    whatsapp_token = Column(Text, nullable=False)
    waba_id = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    contacts = relationship("Contact", back_populates="channel")
    messages = relationship("Message", back_populates="channel")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    wa_id = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    lead_status = Column(String(30), default="novo")
    notes = Column(Text, nullable=True)
    ai_active = Column(Boolean, default=False)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)

    messages = relationship("Message", back_populates="contact")
    tags = relationship("Tag", secondary=contact_tags, back_populates="contacts")
    channel = relationship("Channel", back_populates="contacts")


class Message(Base):
    __tablename__ = "messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    wa_message_id = Column(String(255), unique=True, nullable=False, index=True)
    contact_wa_id = Column(String(20), ForeignKey("contacts.wa_id"), nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    direction = Column(String(10), nullable=False)
    message_type = Column(String(20), nullable=False)
    content = Column(Text, nullable=True)
    timestamp = Column(DateTime, nullable=False)
    status = Column(String(20), default="received")
    sent_by_ai = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

    # Marcador de envio da NAT (ver migrate_nat_sprint3.py). Guarda a ETAPA que originou o
    # envio — nat_boasvindas, nat_sim, nat_confirma_transferencia, nat_outro_horario — e não
    # um booleano: é o que permite ao teto por hora contar SÓ o que a NAT mandou, e ainda
    # dizer de qual passo do fluxo veio. NULL para todo o resto (boas-vindas, resposta manual
    # de SDR, disparo em massa), que é a resposta certa e não uma lacuna.
    # É a coluna que substitui o COLUNA_MARCADOR_ENVIO_NAT = None de nat_guard.
    nat_etapa = Column(Text, nullable=True)

    # Motivo da falha, vindo de statuses[].errors[] no webhook (ver migrate_message_error.py).
    # Só é preenchido quando a Meta reporta erro; NULL é o caso normal.
    # error_details é onde a Meta explica em linguagem natural — vale mais que o title.
    error_code = Column(Integer, nullable=True)
    error_title = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)

    contact = relationship("Contact", back_populates="messages")
    channel = relationship("Channel", back_populates="messages")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    color = Column(String(20), nullable=False, default="blue")
    created_at = Column(DateTime, server_default=func.now())

    contacts = relationship("Contact", secondary=contact_tags, back_populates="tags")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="atendente")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class ExactLead(Base):
    __tablename__ = "exact_leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    exact_id = Column(Integer, unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    phone1 = Column(String(30), nullable=True)
    phone2 = Column(String(30), nullable=True)
    source = Column(String(100), nullable=True)
    sub_source = Column(String(100), nullable=True)
    stage = Column(String(50), nullable=True)
    funnel_id = Column(Integer, nullable=True)
    sdr_name = Column(String(255), nullable=True)
    register_date = Column(DateTime, nullable=True)
    update_date = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, server_default=func.now())

    # Boas-vindas automática.
    # welcome_sent_at: SÓ preenchido em envio REAL.
    # welcome_status: decisão registrada (sent | skipped | failed). É a trava de idempotência —
    #   não usar welcome_sent_at pra isso, senão lead pulado (antigo, ou ingerido com a automação
    #   desligada) voltaria a ser candidato depois.
    welcome_sent_at = Column(DateTime, nullable=True)
    welcome_status = Column(String(30), nullable=True)
    welcome_error = Column(Text, nullable=True)

    # wamid da boas-vindas (ver migrate_welcome_tracking.py). É o ÚNICO vínculo entre
    # `messages` e este lead: o webhook de status recebe o wamid e sem isto não tem como saber
    # a qual lead a falha pertence — foi por isso que o 131042 durou 4 dias com o painel
    # mostrando 254 sucessos enquanto 100% falhava.
    # TEXT porque o formato é opaco e definido pela Meta (58 a 82 chars nesta conta).
    # NULL para todo lead que nunca teve envio, e para os 254 'sent' anteriores à coluna —
    # esses só dá para reconciliar por telefone + janela de tempo (fix_welcome_status_falso).
    welcome_wamid = Column(Text, nullable=True)


class AutoWelcomeConfig(Base):
    """Singleton (id=1) com a configuração da mensagem automática de boas-vindas.

    Nasce DESLIGADA. Canal e template vêm daqui, não de constante no código.
    """
    __tablename__ = "auto_welcome_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    enabled = Column(Boolean, nullable=False, default=False)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=True)
    template_name = Column(String(255), nullable=True)
    template_language = Column(String(20), default="pt_BR")
    funnel_ids = Column(String(255), nullable=True)  # CSV: "18535,18537,25588"
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_name = Column(String(255), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())

    channel = relationship("Channel", backref="auto_welcome_configs")


class AIConfig(Base):
    __tablename__ = "ai_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), unique=True, nullable=False)
    is_enabled = Column(Boolean, default=False)
    system_prompt = Column(Text, nullable=True)
    model = Column(String(50), default="gpt-5")
    temperature = Column(String(10), default="0.7")
    max_tokens = Column(Integer, default=500)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    channel = relationship("Channel", backref="ai_config")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Text, nullable=True)
    chunk_index = Column(Integer, default=0)
    token_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    channel = relationship("Channel", backref="knowledge_documents")


class AIConversationSummary(Base):
    __tablename__ = "ai_conversation_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_wa_id = Column(String(20), ForeignKey("contacts.wa_id"), nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    status = Column(String(30), default="em_atendimento_ia")
    summary = Column(Text, nullable=True)
    lead_name = Column(String(255), nullable=True)
    lead_course = Column(String(255), nullable=True)
    ai_messages_count = Column(Integer, default=0)
    human_took_over = Column(Boolean, default=False)
    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    contact = relationship("Contact", backref="ai_summaries")
    channel = relationship("Channel", backref="ai_summaries")


class CallLog(Base):
    __tablename__ = "call_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    call_sid = Column(String(100), unique=True, nullable=False, index=True)
    from_number = Column(String(30), nullable=False)
    to_number = Column(String(30), nullable=False)
    direction = Column(String(20), nullable=False)
    status = Column(String(30), default="initiated")
    duration = Column(Integer, default=0)
    recording_url = Column(Text, nullable=True)
    recording_sid = Column(String(100), nullable=True)
    drive_file_url = Column(Text, nullable=True)
    local_recording_path = Column(String(500), nullable=True)
    transcription = Column(Text, nullable=True)
    transcription_insights = Column(Text, nullable=True)
    transcription_status = Column(String(30), nullable=True)  # pending, processing, done, error
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_name = Column(String(255), nullable=True)
    contact_wa_id = Column(String(20), nullable=True)
    contact_name = Column(String(255), nullable=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", backref="call_logs")
    channel = relationship("Channel", backref="call_logs")

class CourseAlias(Base):
    __tablename__ = "course_aliases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alias = Column(String(150), unique=True, nullable=False, index=True)
    full_name = Column(String(500), nullable=False)
    short_name = Column(String(150), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    contact_wa_id = Column(String(20), nullable=True, index=True)
    type = Column(String(30), nullable=False)
    ref = Column(String(255), nullable=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, server_default=func.now())


class ScheduledMessage(Base):
    __tablename__ = "scheduled_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_name = Column(String(255), nullable=False)
    language = Column(String(20), default="pt_BR")
    channel_id = Column(Integer, nullable=False)
    param_mappings = Column(Text, nullable=True)
    lead_ids = Column(Text, nullable=False)
    scheduled_at = Column(DateTime, nullable=False, index=True)
    status = Column(String(20), default="pending", index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_name = Column(String(255), nullable=True)
    lead_count = Column(Integer, default=0)
    result = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    sent_at = Column(DateTime, nullable=True)


class WhatsappTemplate(Base):
    __tablename__ = "whatsapp_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    name = Column(String(512), nullable=False)
    language = Column(String(20), nullable=False, default="pt_BR")
    category = Column(String(30), nullable=False)
    components = Column(Text, nullable=True)        # JSON dos components submetidos
    meta_template_id = Column(String(64), nullable=True)
    status = Column(String(30), default="PENDING")  # último status conhecido
    rejected_reason = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class NatConfig(Base):
    """Singleton (id=1) com as travas do fluxo NAT.

    Nasce DESLIGADA em dois eixos independentes: nat_enabled=False e nat_start_at=None.
    Ligar só o nat_enabled não faz a NAT atuar — o corte por data continua bloqueando.

    nat_start_at é comparado com exact_leads.register_date, NÃO com "é novo no banco":
    assim a trava é imune a backfill e a falha de sync.

    O CHECK (id = 1) faz o singleton valer no banco, não por convenção: duas linhas aqui
    deixariam o kill switch com comportamento indefinido.
    """
    __tablename__ = "nat_config"
    __table_args__ = (CheckConstraint("id = 1", name="nat_config_singleton"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    nat_enabled = Column(Boolean, nullable=False, default=False)
    nat_start_at = Column(DateTime, nullable=True)
    max_envios_hora = Column(Integer, nullable=False, default=20)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class NatButtonEvent(Base):
    """Captura crua do clique de botão (quick reply de template ou botão interativo).

    Sem FK em contact_wa_id de propósito (ver migrate_nat_config.py): a tabela existe para
    nunca perder um clique, e uma FK derrubaria a transação inteira do webhook.

    Pela mesma razão, quem escreve aqui (webhook, main.py) tem que fazê-lo dentro de SAVEPOINT
    com try/except: nem a UNIQUE de wa_message_id nem qualquer outro erro desta tabela podem
    abortar o recebimento da mensagem. Observabilidade serve ao fluxo, não o contrário.

    context_message_id é o wamid da mensagem que o botão respondeu — é o que distingue
    "Prefiro outro horário" vindo de nat_boasvindas do mesmo texto vindo de nat_reativacao_09h.
    """
    __tablename__ = "nat_button_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    contact_wa_id = Column(String(20), nullable=False, index=True)
    wa_message_id = Column(String(255), unique=True, nullable=False)
    context_message_id = Column(String(255), nullable=True, index=True)
    button_payload = Column(Text, nullable=True)
    button_text = Column(Text, nullable=True)
    source = Column(String(20), nullable=False)  # "template" | "interactive"
    created_at = Column(DateTime, server_default=func.now())


# Etapas da máquina de estados do fluxo NAT. Espelha o CHECK de migrate_nat_flow_state.py —
# mudar aqui sem mudar lá (ou o contrário) faz o INSERT falhar no banco, que é o
# comportamento desejado: a divergência aparece na hora, não semanas depois.
ETAPA_AGUARDANDO_HORARIO = "aguardando_horario"
ETAPA_AGUARDANDO_RESPOSTA = "aguardando_resposta"
ETAPA_AGUARDANDO_MOTIVACAO = "aguardando_motivacao"
ETAPA_AGUARDANDO_LIGACAO = "aguardando_ligacao"
ETAPA_REAGENDADO = "reagendado"
ETAPA_SEM_CONTATO = "sem_contato"
ETAPA_ENCERRADO = "encerrado"

ETAPAS_VALIDAS = frozenset({
    ETAPA_AGUARDANDO_HORARIO, ETAPA_AGUARDANDO_RESPOSTA, ETAPA_AGUARDANDO_MOTIVACAO,
    ETAPA_AGUARDANDO_LIGACAO, ETAPA_REAGENDADO, ETAPA_SEM_CONTATO, ETAPA_ENCERRADO,
})


class NatFlowState(Base):
    """Onde cada lead está no fluxo da NAT. UM estado por contato.

    Sem FK para contacts/exact_leads/users de propósito (ver migrate_nat_flow_state.py): a
    tabela é escrita de dentro do webhook e não pode ser a causa de um lote de mensagens se
    perder. Vale a mesma regra de nat_button_events — toda escrita dentro de begin_nested().

    ultimo_wa_message_id é a trava de idempotência: a Meta reentrega webhook, e sem ele o
    mesmo clique avançaria o estado duas vezes e mandaria a mensagem seguinte em duplicata.

    tentativas_contato ainda não tem consumidor — é do Bloco 6 (recuperação). Está aqui para
    não exigir ALTER numa tabela que a essa altura já estará sendo escrita em produção.
    """
    __tablename__ = "nat_flow_state"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    contact_wa_id = Column(String(20), unique=True, nullable=False)
    exact_lead_id = Column(Integer, nullable=True)
    sdr_user_id = Column(Integer, nullable=True)
    etapa = Column(String(30), nullable=False, index=True)
    tentativas_contato = Column(Integer, nullable=False, default=0)
    horario_preferencial = Column(Text, nullable=True)
    ultimo_wa_message_id = Column(Text, nullable=True)
    transferido_em = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # --- Bloco 5: quem assumiu a ligação, e até onde o escalonamento chegou ---
    #
    # assumido_por é o que PARA O RELÓGIO do SLA. É int (quem assumiu) e não booleano de
    # propósito: a tela precisa mostrar o nome, e a notificação de escalonamento precisa
    # dizer quem já estava com o lead. Sem FK para users, como o resto da tabela.
    #
    # escalonamento_nivel: 0 = só o SDR dono foi avisado; 1 = o outro SDR também;
    # 2 = a gestora também, e o ciclo acabou (nível 2 não agenda mais nada).
    assumido_por = Column(Integer, nullable=True)
    assumido_em = Column(DateTime, nullable=True)
    escalonamento_nivel = Column(Integer, nullable=False, default=0)


# Status de uma ação agendada. Espelha o CHECK de migrate_nat_sprint3.py — mesma regra do
# ETAPAS_VALIDAS acima: divergir daqui faz o INSERT falhar na hora, que é o desejado.
ACAO_PENDENTE = "pendente"
ACAO_EXECUTADO = "executado"
ACAO_CANCELADO = "cancelado"
ACAO_FALHOU = "falhou"

STATUS_ACAO_VALIDOS = frozenset({ACAO_PENDENTE, ACAO_EXECUTADO, ACAO_CANCELADO, ACAO_FALHOU})

# Tipos de ação agendada. Nesta sprint só existe o sla_check. NÃO há CHECK no banco para
# `kind` (ver migrate_nat_sprint3.py): é ponto de extensão, não máquina de estados fechada.
KIND_SLA_CHECK = "sla_check"

# Quantas vezes uma ação é tentada antes de virar `falhou` e sair do loop de retry.
MAX_TENTATIVAS_ACAO = 3


class NatScheduledAction(Base):
    """Agendador genérico da NAT: "rode isto para este contato a esta hora".

    O SLA de 2 minutos do Bloco 5 é o primeiro consumidor, mas a tabela não sabe disso —
    ela guarda (kind, contato, hora) e o job despacha por `kind`.

    run_at é NAIVE EM HORÁRIO DE SÃO PAULO, igual a messages.timestamp e a
    nat_guard._agora_sp(). O banco está em Etc/UTC: comparar contra now() do Postgres
    dispararia tudo 3h adiantado, silenciosamente. O job sempre manda o corte de Python.

    Sem FK em contact_wa_id — mesma razão de NatFlowState e NatButtonEvent: escrita de dentro
    do webhook, e uma FK só acrescentaria um jeito de derrubar o lote de mensagens.

    Execução única é garantida pelo job, não por esta classe: SELECT ... FOR UPDATE SKIP
    LOCKED + marcação de `executado` na MESMA transação que executa a ação.
    """
    __tablename__ = "nat_scheduled_actions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    kind = Column(String(40), nullable=False)
    contact_wa_id = Column(String(20), nullable=False)
    run_at = Column(DateTime, nullable=False)
    payload = Column(Text, nullable=True)  # JSON serializado; ver migrate_nat_sprint3.py
    status = Column(String(20), nullable=False, default=ACAO_PENDENTE)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    processed_at = Column(DateTime, nullable=True)


# ==========================================================================================
# AGENDAMENTO PELA LANDING PAGE
# ==========================================================================================

# Passos do fluxo, na ordem em que acontecem. O valor é gravado ANTES de cada chamada à
# Exact, nunca depois: se o processo morrer no meio, a linha mostra até onde chegou.
PASSO_INICIADO = "iniciado"          # nada foi para a Exact ainda
PASSO_BOX_CRIADO = "box_criado"      # BoxesAdd passou. Reversível — a faxina limpa.
PASSO_LEAD_CRIADO = "lead_criado"    # LeadsAdd passou. O lead está em Entrada.
PASSO_AGENDADO = "agendado"          # scheduleAdd passou. DEFINITIVO.
PASSO_FALHOU = "falhou"              # desistimos; `erro` diz por quê


class Agendamento(Base):
    """Uma tentativa de agendamento vinda da LP — inclusive as que falharam.

    A ESCRITA É NOSSA ANTES DE SER DA EXACT. A Exact não guarda tentativa que não deu certo:
    um fluxo que morre entre o BoxesAdd e o scheduleAdd não deixa rastro nenhum lá. Sem esta
    tabela não há como responder "quantos agendamentos ficaram pela metade ontem?", e o job
    de faxina não teria como saber quais boxes são nossos para remover.

    slot_inicio/slot_fim são NAIVE EM SÃO PAULO, igual a messages.timestamp e a
    nat_scheduled_actions.run_at — e igual ao que a Exact grava em Boxes.start, que é hora de
    parede apesar do sufixo 'Z' (AGENDAMENTO_FINDINGS.md §1). Guardar UTC aqui obrigaria a
    converter nos dois sentidos e criaria exatamente o erro de 3h que o módulo evita.

    Sem FK para exact_leads: o lead nasce na Exact e só entra em exact_leads no sync seguinte
    (até 10 min depois). Uma FK recusaria a linha justamente no instante do agendamento.

    `meeting_id` é preenchido best-effort depois do scheduleAdd, que devolve booleano e não o
    id da reunião (FINDINGS §4). NULL aqui não significa que a reunião não existe.
    """
    __tablename__ = "agendamentos"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    nome = Column(String(200), nullable=False)
    email = Column(String(200), nullable=True)   # a Exact não tem campo de e-mail no lead
    telefone = Column(String(20), nullable=False)
    slot_inicio = Column(DateTime, nullable=False)
    slot_fim = Column(DateTime, nullable=False)
    sales_rep_email = Column(String(200), nullable=False)
    box_id = Column(BigInteger, nullable=True)
    lead_id = Column(BigInteger, nullable=True)
    meeting_id = Column(BigInteger, nullable=True)
    passo = Column(String(20), nullable=False, default=PASSO_INICIADO)
    erro = Column(Text, nullable=True)           # mensagem crua da Exact, sem tradução
    origem_ip = Column(String(45), nullable=True)  # 45 = IPv6 textual
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
