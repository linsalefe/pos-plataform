from sqlalchemy import Column, String, Text, DateTime, BigInteger, Integer, Boolean, ForeignKey, func, Table, CheckConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
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

    # --- AUTORIA DO ENVIO (ver migrate_message_autoria.py, S6-1) ---
    #
    # sent_by responde "quem apertou enviar", e NULL é resposta, não lacuna: quer dizer
    # "não foi humano logado" — o agente (nat_sender), a boas-vindas automática
    # (exact_spotter) e o disparo agendado (roda sem sessão) gravam NULL de propósito.
    # Inventar um usuário "sistema" apagaria justamente o que a coluna informa.
    # Quem resolve o valor é `app/autoria.quem_enviou` — ver lá a armadilha do `Depends`.
    #
    # template_name é o nome do template NA META. Sem ele, a única forma de saber que
    # template saiu é `LIKE` sobre o corpo renderizado em `content` — que foi como o
    # RECON de 01/09 teve que reconstruir 17 famílias, e é o motivo de a medição por
    # template ter sido impossível antes. NULL = não foi template.
    #
    # As duas nascem NULL para TODO o histórico: não houve backfill, porque o dado nunca
    # existiu em lugar nenhum do banco. A primeira linha preenchida é o primeiro envio
    # depois do deploy do S6-1.
    sent_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    template_name = Column(String(512), nullable=True)

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

    # --- Eixos do AGENTE de pré-qualificação, separados dos da NAT de botões ---
    #
    # Dois eixos pelo mesmo motivo dos de cima: ligar só o booleano não faz o agente atuar,
    # porque o corte por data continua bloqueando.
    #
    # E são campos PRÓPRIOS de propósito. Ligar o agente NÃO pode ressuscitar o fluxo de
    # botões — que segue governado por nat_enabled — nem o contrário. Os dois moram na mesma
    # linha por serem a mesma classe de trava, não por serem a mesma trava.
    qualificacao_enabled = Column(Boolean, nullable=False, default=False,
                                  server_default="false")
    qualificacao_start_at = Column(DateTime, nullable=True)

    # Terceiro eixo, independente dos outros dois: ligar o espontâneo não pode depender de
    # ligar o fluxo da LP, nem o contrário. Nasce DESLIGADO.
    espontaneo_enabled = Column(Boolean, nullable=False, default=False,
                                server_default="false")

    # --- S6-4 (Sprint D): o follow do agente, também num eixo próprio ---
    #
    # Nasce DESLIGADO e SEM template, e as duas condições são checadas pelo handler: um lead
    # que hoje fica em silêncio não recebe nada, e passar a receber é decisão de produto,
    # não efeito colateral de deploy.
    #
    # `follow_template` é o nome do template NA META, e está NULO porque o texto ainda vai
    # ser submetido. Com o nome em coluna, aprovar o template é um UPDATE e não um deploy —
    # e enquanto for NULL o handler recusa com `skipped` e motivo legível.
    #
    # NÃO reusar `nat_recuperacao_sdr` aqui: o corpo diz "Tentamos falar com você há alguns
    # minutos", falso 20 horas depois, e há DOIS com esse nome aprovados no WABA com corpos
    # diferentes (ver nat_copy.py:80).
    follow_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    follow_template = Column(String(512), nullable=True)

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

# `executado` passou a significar UMA coisa só: o handler agiu. Quando ele decide NÃO agir —
# o lead já tem estado, é anterior ao corte, não tem telefone — a ação vira `skipped` com o
# motivo gravado em `motivo`, e não `executado` mudo.
#
# A distinção não é cosmética. `monitor_qualificacao.py` §2b cruza ação EXECUTADA contra
# estado existente e chama de lead perdido a que não tem par. Com tudo virando `executado`,
# essa consulta não conseguia separar "descartei o lead em silêncio" de "não havia o que
# fazer" — as duas tinham exatamente a mesma assinatura no banco. Ver o Risco 3 em
# SPRINT_ESPONTANEO_20260825.md §7.
ACAO_SKIPPED = "skipped"

STATUS_ACAO_VALIDOS = frozenset({ACAO_PENDENTE, ACAO_EXECUTADO, ACAO_CANCELADO, ACAO_FALHOU,
                                 ACAO_SKIPPED})

# Tipos de ação agendada. NÃO há CHECK no banco para `kind` (ver migrate_nat_sprint3.py): é
# ponto de extensão, não máquina de estados fechada. O preço disso é que um kind cujo módulo
# não esteja em nat_scheduler.MODULOS_DE_HANDLERS vira `falhou` — ruidoso, mas só depois de a
# ação vencer. Acrescentar constante aqui sem registrar o módulo lá é o erro a evitar.
KIND_SLA_CHECK = "sla_check"

# Bloco 6: 10 min depois de o SDR marcar "não consegui contato", cobra o SDR de novo. O
# destinatário é o SDR, NUNCA o lead — a mensagem ao lead sai uma única vez, no clique.
KIND_RETRY_CONTATO = "retry_contato"

# Agente de pré-qualificação: abre a conversa +5 min depois da aplicação. A espera existe
# porque a ramificação "já agendou × não agendou" só é definitiva depois que a pessoa
# terminou (ou não) o fluxo do obrigado.html — medido: mediana 28s, máximo 3min14s.
KIND_INICIAR_QUALIFICACAO = "iniciar_qualificacao"

# Lembrete T-30min da reunião. Agendado no instante em que a reunião passa a ser conhecida,
# venha ela do agente ou do obrigado.html.
KIND_LEMBRETE_REUNIAO = "lembrete_reuniao"

# Encerra por inatividade um lead que parou de responder no meio da qualificação. Sem ele,
# `ETAPA_Q_ENCERRADO` seria constante morta — o mesmo defeito que o ESTADO_NAT_20260809
# apontou no fluxo velho (`sem_contato` e `encerrado` declaradas e nunca atribuídas).
KIND_ENCERRAR_INATIVO = "encerrar_inativo"

# S6-4 (Sprint D) — o follow do agente. 20h de silêncio do lead sobre a NOSSA pergunta.
#
# O N não é palpite: na janela 24/08-01/09 a taxa de resposta ao follow por faixa de silêncio
# foi 20-24h → 13,7% (N=124), 24-48h → 10,3%, 48-72h → 7,9% (N=127). A operação humana manda
# hoje com 45,7h de mediana, ou seja, no balde de 7,9%. E 20h fica ABAIXO da janela de 24h da
# Meta, então o envio ainda pode sair como texto livre em vez de template pago.
#
# UM só, e não uma régua: a taxa por ORDEM do follow cai 17,4% → 11,7% → 7,8% → 6,8% → 0%.
# O segundo rende menos que o primeiro e o quinto rende zero. Se um dia houver um segundo,
# que seja medido antes de virar padrão, não depois.
KIND_FOLLOW_20H = "follow_20h"

# A fala que o teto por hora adiou. Não precisa de migração: o CHECK de
# `nat_scheduled_actions` é sobre `status`, não sobre `kind`.
KIND_RESPONDER_PENDENTE = "responder_pendente"

# O VIGIA (P3-A). Lead escreveu, o agente não respondeu em 10 min: avisa a GESTÃO de que o
# agente está mudo. É o alarme do sintoma, não de uma causa — existe para a classe de falha
# que ainda não conhecemos, depois que P0-A..P0-E, P1-A e P1-B fecharam as que conhecemos.
#
# Não é mais um `window_*`: aqueles vão para o SDR dono, dizem "Lead aguardando há 1h" — que
# é indistinguível de um lead esperando um humano — e a auditoria de 26/08 mediu 87 deles
# para os 5 casos mortos, 100% com `is_read=false`. Este vai para o GESTOR_USER_ID e diz
# AGENTE MUDO, porque é falha de sistema e não fila de atendimento.
#
# Sem migração: o CHECK de `nat_scheduled_actions` é sobre `status`, e o índice único parcial
# é sobre (kind, contact_wa_id) — um vigia convive com o `encerrar_inativo` do mesmo contato.
KIND_VIGIAR_RESPOSTA = "vigiar_resposta"

# Régua de CONFIRMAÇÃO de reunião (Fluxo A da spec da Isa, 28/09; Bloco 1, 07/10/2026). UM
# KIND POR MENSAGEM, e não um kind com o degrau no payload: o índice único parcial
# `uq_nat_sched_pendente_por_contato (kind, contact_wa_id) WHERE pendente` e o `agendar()` que
# cancela o pendente do mesmo par fariam o pedido apagar a ementa (RECON_CONFIRMACAO_NOSHOW
# §6.1). O T-30 continua sendo `lembrete_reuniao`. Ver app/confirmacao.py.
KIND_CONFIRM_A_IMEDIATA = "confirm_a_imediata"
KIND_CONFIRM_A_EMENTA = "confirm_a_ementa"
KIND_CONFIRM_A_BENEFICIO = "confirm_a_beneficio"
KIND_CONFIRM_A_PEDIDO = "confirm_a_pedido"
KIND_CONFIRM_A_ULTIMO_AVISO = "confirm_a_ultimo_aviso"
KIND_CONFIRM_A_CORTE = "confirm_a_corte"
KINDS_CONFIRMACAO = (KIND_CONFIRM_A_IMEDIATA, KIND_CONFIRM_A_EMENTA, KIND_CONFIRM_A_BENEFICIO,
                     KIND_CONFIRM_A_PEDIDO, KIND_CONFIRM_A_ULTIMO_AVISO, KIND_CONFIRM_A_CORTE)

# Tipos de `notifications` da régua. Sem migração: `notifications.type` não tem CHECK.
TIPO_NOTIF_CONFIRMACAO = "confirmacao_humano"
TIPO_NOTIF_LIGAR_AGORA = "ligar_agora"

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
    # POR QUE O MOTIVO É COLUNA E NÃO SÓ LOG. O log desta aplicação é afogado pelo
    # `echo=True` do engine (36 750 linhas suprimidas pelo journald em 25/08), então
    # "está no log" não é o mesmo que "dá para responder depois". Um `skipped` sem motivo
    # legível no banco seria a mesma falha silenciosa que ele veio corrigir.
    #
    # Vale também para `pendente`: uma ação ADIADA pelo teto guarda aqui por que ela ainda
    # não rodou, o que torna visível — sem ler log — a fila que está esperando janela.
    # Limpo (NULL) quando a ação enfim executa.
    motivo = Column(Text, nullable=True)


class NatContactAttempt(Base):
    """Histórico das tentativas de ligação sem sucesso — Bloco 6 (recuperação).

    Uma linha por clique do SDR em "Não consegui contato". O CONTADOR VIVO não é esta tabela:
    é nat_flow_state.tentativas_contato, e é ele que o endpoint lê para aplicar o teto de 2.
    Aqui fica o histórico — quem marcou, quando, com que desfecho —, que é o que permite
    auditar um lead que encerrou cedo. Contador e histórico devem bater; divergirem é bug, e
    guardar `tentativa_num` em cada linha é o que torna isso conferível.

    Tabela nova em vez de call_logs: `call_logs.call_sid` é UNIQUE NOT NULL e uma tentativa
    marcada à mão não tem sid nenhum — reusar exigiria inventar um sid falso numa tabela que
    hoje é fiel ao que o Twilio reportou. Ver migrate_nat_contact_attempts.py.

    SEM FK em lugar nenhum — nem contact_wa_id para contacts, nem registrado_por para users.
    Mesma razão de NatFlowState, NatButtonEvent e NatScheduledAction: a escrita acontece
    dentro do fluxo da NAT e não pode ser a causa de uma falha em cascata. `registrado_por`
    aponta para users.id sem que o banco cobre isso, igual a NatFlowState.assumido_por.

    `resultado` é VARCHAR livre, sem CHECK: hoje o único valor gravado é "sem_contato", mas o
    conjunto ainda não está fechado (Sprint B/C podem acrescentar outros desfechos). Mesmo
    critério do `kind` acima — máquina de estados fechada leva CHECK, ponto de extensão não.
    """
    __tablename__ = "nat_contact_attempts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    contact_wa_id = Column(String(20), nullable=False)
    tentativa_num = Column(Integer, nullable=False)
    registrado_por = Column(Integer, nullable=True)
    resultado = Column(String(20), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


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
# Recusado por NÓS antes de qualquer chamada à Exact (origem fora da allowlist, 422, slot
# inválido, duplo clique...). Existe só como rastro para achar a pessoa depois: nunca tem
# `lead_id`, `box_id` nem consultora. `motivo_recusa` diz qual foi. Ver agendamento/rastro.py.
PASSO_RECUSADO = "recusado"


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
    # 30 e não 20: a linha `recusado` guarda o telefone COMO VEIO, inclusive o que o 422
    # recusou por ser comprido demais ("+55 (66) 9 9905-0115" já tem 20). O valor do rastro é
    # achar a pessoa, e cortar o número que ela digitou errado é justamente perder isso.
    telefone = Column(String(30), nullable=False)
    slot_inicio = Column(DateTime, nullable=False)
    slot_fim = Column(DateTime, nullable=False)
    sales_rep_email = Column(String(200), nullable=False)
    # De qual curso veio o lead. Conferido contra a allowlist de agendamento/origens.py antes
    # de ir para a Exact — `LeadsAdd` CRIA o subSource quando o valor não existe, e o cadastro
    # é global. Guardado aqui porque é a única forma de saber depois de qual LP veio cada
    # agendamento: em `exact_leads` o dado só aparece no sync seguinte, e some se o lead for
    # excluído. NULL nas linhas anteriores a esta coluna.
    sub_source = Column(String(100), nullable=True)
    box_id = Column(BigInteger, nullable=True)
    lead_id = Column(BigInteger, nullable=True)
    # True quando o `lead_id` veio PRONTO no corpo do POST (fluxo de duas etapas da LP:
    # o form nativo cria o lead em /lead e o obrigado.html só agenda). Nesse caso o módulo
    # NÃO chamou LeadsAdd — o lead é de outra requisição, e a compensação não pode presumir
    # que ele é nosso. É a única forma de responder depois "este lead foi criado aqui ou já
    # existia?", porque `lead_id` preenchido tem a mesma cara nos dois caminhos.
    lead_externo = Column(Boolean, nullable=False, default=False, server_default="false")
    # Respostas livres do formulário da LP: profissão, como conheceu, faixa de investimento.
    # Variam por página e por campanha — viram JSON e não coluna, senão cada pergunta nova
    # da equipe de marketing viraria uma migração.
    #
    # JSONB, e não Text com json.dumps como `templates.components` e
    # `nat_scheduled_actions.payload`. Aqueles dois são payloads OPACOS, guardados para
    # auditoria e nunca consultados por dentro. Este aqui existe justamente para ser
    # consultado — `extras->>'Como conheceu'` é a pergunta que o marketing vai fazer — e
    # JSONB dá isso sem parse na aplicação, além de recusar JSON inválido na escrita.
    extras = Column(JSONB, nullable=True)
    meeting_id = Column(BigInteger, nullable=True)
    passo = Column(String(20), nullable=False, default=PASSO_INICIADO)
    # Por que recusamos, em texto curto e padronizado (`origem_nao_permitida`,
    # `validacao_telefone`, `slot_ocupado`...). NULL = não foi recusa. Preenchido nas linhas
    # `recusado` e também na `falhou` do 409, que já existia e não ganha linha duplicada —
    # por isso a pergunta "quem foi recusado?" é `motivo_recusa IS NOT NULL`, não `passo`.
    motivo_recusa = Column(String(40), nullable=True)
    erro = Column(Text, nullable=True)           # mensagem crua da Exact, sem tradução
    origem_ip = Column(String(45), nullable=True)  # 45 = IPv6 textual
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


# ==========================================================================================
# ESPELHO DAS REUNIÕES DA EXACT (Bloco 0, 07/10/2026)
# ==========================================================================================
#
# Os três valores que `GET /Meetings` devolve em `type`. MEDIDO em 07/10 sobre 249 reuniões
# desde 07/09 (RECON_CONFIRMACAO_NOSHOW_20261007 §5.2): Cancelada 155, Concluido 73, Vigente 21,
# e nenhum outro. NÃO existe valor de no-show: `Cancelada` junta cancelamento prévio,
# remarcação e falta. `Concluido` sem acento é a grafia da Exact.
#
# O CHECK de `migrate_reuniao_status.py` é construído desta tupla. Um `type` novo na Exact faz
# o upsert daquela reunião falhar alto, em vez de gravar um valor que nenhuma regra conhece.
EXACT_TYPE_VIGENTE = "Vigente"
EXACT_TYPE_CONCLUIDO = "Concluido"
EXACT_TYPE_CANCELADA = "Cancelada"
EXACT_TYPES = (EXACT_TYPE_VIGENTE, EXACT_TYPE_CONCLUIDO, EXACT_TYPE_CANCELADA)

# Quem marcou. O campo `user` de /Meetings é SEMPRE o dono do token (Thobias, 249 de 249), e
# não diz nada. O único marcador é o `description` que o Hub grava no `BoxesAdd`
# (`agendamento/agendar.py:389`), que a Exact devolve como `managerDescription`.
ORIGEM_REUNIAO_HUB = "hub"      # managerDescription começa com "Agendamento LP —"
ORIGEM_REUNIAO_EXACT = "exact"  # marcada na Exact, pela SDR ou pela consultora
ORIGENS_REUNIAO = (ORIGEM_REUNIAO_HUB, ORIGEM_REUNIAO_EXACT)
PREFIXO_REUNIAO_HUB = "Agendamento LP"


class ReuniaoStatus(Base):
    """Uma reunião da Exact, venha de onde vier. Chave: o `meeting_id` DELA.

    POR QUE EXISTE. `agendamentos.passo` vira `agendado` e nunca mais muda: nada traz de volta o
    que a consultora faz na Exact. MEDIDO em 07/10 (RECON §2): 4 lembretes T-30 saíram para
    reunião já remarcada, e 2 pendentes eram de reunião `Cancelada` (cancelados à mão). E 64 de
    249 reuniões nem passam pelo Hub: foram marcadas direto na Exact (RECON §5.3).

    POR QUE A CHAVE É `meeting_id` E NÃO O LEAD. Remarcar na Exact NÃO muda a data da reunião:
    cancela a antiga e cria outra, com id novo (RECON §5.4: 0 de 158 reuniões do Hub com data
    diferente da gravada; 22 leads com 2+ reuniões, sempre a antiga `Cancelada`). Logo não há
    "atualizar a data": há reunião nova, e a pessoa é achada pelo TELEFONE (`telefone_chave`).

    POR QUE NÃO `agendamentos` NEM `exact_leads`. A primeira não enxerga a reunião da SDR; a
    segunda é sobrescrita pelo sync a cada 10 min.

    RELÓGIOS: tudo aqui é SP naive, inclusive `created_at`/`updated_at` (default no banco em
    `America/Sao_Paulo`, ver a migração). `slot_inicio` é o `startTime` da Exact SEM conversão
    (é hora de parede, FINDINGS §1); `registrado_em` é o `registerDate`, que é UTC de verdade,
    convertido para SP ao gravar.

    As colunas `confirmado_*`, `cancelado_*`, `noshow_em` e `regua_*` são dos blocos 1 e 2.
    Nascem aqui para não pedir segunda DDL; o Bloco 0 não as escreve.
    """
    __tablename__ = "reuniao_status"
    # Índices e CHECKs moram SÓ em `migrate_reuniao_status.py`, que é quem cria a tabela.

    meeting_id = Column(BigInteger, primary_key=True)
    lead_id = Column(BigInteger)
    telefone_chave = Column(String(10))   # telefone.chave_telefone()
    telefone_bruto = Column(String(30))
    nome = Column(String(255))
    slot_inicio = Column(DateTime, nullable=False)  # SP naive
    slot_fim = Column(DateTime)
    sales_rep_email = Column(String(255))
    origem = Column(String(10), nullable=False)
    # BIGINT porque `agendamentos.id` é BIGSERIAL. ON DELETE SET NULL: o espelho não pode
    # impedir uma limpeza em `agendamentos`, nem morrer junto com ela.
    agendamento_id = Column(BigInteger, ForeignKey("agendamentos.id", ondelete="SET NULL"),
                            nullable=True)
    exact_type = Column(String(20), nullable=False)
    exact_type_visto_em = Column(DateTime, nullable=False)
    exact_type_anterior = Column(String(20))
    registrado_em = Column(DateTime)                 # registerDate em SP naive

    confirmado_em = Column(DateTime)
    confirmado_por = Column(String(10))
    cancelado_em = Column(DateTime)
    cancelado_motivo = Column(String(60))
    noshow_em = Column(DateTime)
    regua_encerrada_em = Column(DateTime)
    regua_encerrada_motivo = Column(String(60))

    created_at = Column(DateTime, server_default=text("(now() AT TIME ZONE 'America/Sao_Paulo')"))
    updated_at = Column(DateTime, server_default=text("(now() AT TIME ZONE 'America/Sao_Paulo')"))


class ReuniaoSyncCursor(Base):
    """Marca d'água do sync de reuniões. Uma linha só (id=1).

    `register_date_cursor` é UTC naive porque é comparado com o `registerDate` da Exact, que é
    UTC de verdade. Fica numa tabela, não no `.env`: avança a cada ciclo, e um restart não pode
    devolvê-lo ao valor de quando o processo subiu.
    """
    __tablename__ = "reuniao_sync_cursor"

    id = Column(Integer, primary_key=True)        # sempre 1
    register_date_cursor = Column(DateTime)       # UTC naive
    ultimo_ciclo_em = Column(DateTime)            # SP naive
    ultimo_ciclo_resultado = Column(Text)


# ==========================================================================================
# AGENTE DE PRÉ-QUALIFICAÇÃO
# ==========================================================================================
#
# Etapas do fluxo do AGENTE. Espelha o CHECK de migrate_qualificacao.py — mesma regra do
# ETAPAS_VALIDAS do fluxo velho: divergir daqui faz o INSERT falhar na hora, que é o desejado.
#
# São DUAS entradas possíveis, e é por isso que existe `aguardando_formacao`: a abertura T3
# (`nat_abertura_sem_formacao`) pergunta QUAL É a formação, então a primeira resposta do lead
# é a formação, não o ano. T1 e T2 já afirmam a formação e perguntam o ano direto.
ETAPA_Q_AGUARDANDO_FORMACAO = "aguardando_formacao"
ETAPA_Q_AGUARDANDO_ANO = "aguardando_ano"
ETAPA_Q_AGUARDANDO_ATUACAO = "aguardando_atuacao"
ETAPA_Q_AGUARDANDO_MOTIVACAO = "aguardando_motivacao"
ETAPA_Q_OFERTANDO_AGENDA = "ofertando_agenda"
ETAPA_Q_ESCOLHENDO_SLOT = "escolhendo_slot"
ETAPA_Q_CONCLUIDO = "concluido"
ETAPA_Q_TRANSFERIDO = "transferido_humano"
ETAPA_Q_ENCERRADO = "encerrado"

# ------------------------------------------------------------------------------------------
# FLUXO ESPONTÂNEO (migrate_espontaneo.py, 25/08/2026)
# ------------------------------------------------------------------------------------------
# Quem escreveu no WhatsApp sem ter preenchido formulário nenhum. Mora nas MESMAS tabela e
# coluna do fluxo da LP porque é o mesmo agente com outra porta de entrada — `origem` é o que
# distingue, e as duas origens nunca coexistem no mesmo contato (a regra de admissão exige
# ausência de lead na Exact). Ver o cabeçalho de migrate_espontaneo.py.
#
# São 4 e não 6: o espontâneo é mais curto de propósito. Quem escreveu primeiro já demonstrou
# interesse, e cada pergunta a mais é uma chance de abandono antes do link.
ETAPA_ESP_CONFIRMANDO_INTERESSE = "esp_confirmando_interesse"
ETAPA_ESP_COLETANDO_CURSO = "esp_coletando_curso"
ETAPA_ESP_COLETANDO_FORMACAO = "esp_coletando_formacao"
ETAPA_ESP_LINK_ENVIADO = "esp_link_enviado"

ETAPAS_QUALIFICACAO_VALIDAS = frozenset({
    ETAPA_Q_AGUARDANDO_FORMACAO, ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_AGUARDANDO_ATUACAO,
    ETAPA_Q_AGUARDANDO_MOTIVACAO, ETAPA_Q_OFERTANDO_AGENDA, ETAPA_Q_ESCOLHENDO_SLOT,
    ETAPA_ESP_CONFIRMANDO_INTERESSE, ETAPA_ESP_COLETANDO_CURSO,
    ETAPA_ESP_COLETANDO_FORMACAO, ETAPA_ESP_LINK_ENVIADO,
    ETAPA_Q_CONCLUIDO, ETAPA_Q_TRANSFERIDO, ETAPA_Q_ENCERRADO,
})

# Etapas em que o agente É DONO do inbound daquele contato (Bloco D, precedência). Fora
# delas o estado existe mas o agente calou-se — e o fluxo velho, se um dia rodar, volta a
# ver a mensagem.
ETAPAS_QUALIFICACAO_ATIVAS = frozenset({
    ETAPA_Q_AGUARDANDO_FORMACAO, ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_AGUARDANDO_ATUACAO,
    ETAPA_Q_AGUARDANDO_MOTIVACAO, ETAPA_Q_OFERTANDO_AGENDA, ETAPA_Q_ESCOLHENDO_SLOT,
    # As `esp_*` NÃO estão aqui ainda, e a ausência é deliberada: esta constante significa
    # "o agente é DONO do inbound e vai responder". O fluxo espontâneo tem etapa no banco
    # (o CHECK já as aceita) mas ainda não tem missão nem handler — declará-las ativas faria
    # o webhook entregar a mensagem a um fluxo que não sabe responder, e o lead ficaria mudo.
    # Entram junto com as missões, na implementação do Bloco A.
})

# Nome que a TELA mostra para cada etapa do agente (rótulo "Agente: …" na conversa, 18/09).
# Mora aqui, ao lado das constantes, para que uma etapa nova sem rótulo seja visível no
# mesmo diff — e para o TSX não carregar uma segunda lista que divergiria.
ETAPAS_QUALIFICACAO_LEGIVEIS = {
    ETAPA_Q_AGUARDANDO_FORMACAO: "perguntando a formação",
    ETAPA_Q_AGUARDANDO_ANO: "perguntando o ano de conclusão",
    ETAPA_Q_AGUARDANDO_ATUACAO: "perguntando a atuação",
    ETAPA_Q_AGUARDANDO_MOTIVACAO: "perguntando a motivação",
    ETAPA_Q_OFERTANDO_AGENDA: "oferecendo horários",
    ETAPA_Q_ESCOLHENDO_SLOT: "lead escolhendo horário",
    ETAPA_Q_CONCLUIDO: "concluído (reunião marcada)",
    ETAPA_Q_TRANSFERIDO: "transferido para humano",
    ETAPA_Q_ENCERRADO: "encerrado",
    ETAPA_ESP_CONFIRMANDO_INTERESSE: "espontâneo: confirmando interesse",
    ETAPA_ESP_COLETANDO_CURSO: "espontâneo: perguntando o curso",
    ETAPA_ESP_COLETANDO_FORMACAO: "espontâneo: perguntando a formação",
    ETAPA_ESP_LINK_ENVIADO: "espontâneo: link enviado",
}

# De qual gatilho o lead veio. Decide de onde a formação é lida: `lp` tem os extras do
# formulário no nosso banco; `exact` só tem o `description`, que é texto livre.
ORIGEM_LP = "lp"
ORIGEM_EXACT = "exact"
# Inbound de número desconhecido, sem formulário e sem lead na Exact. A coluna `origem` foi
# alargada para VARCHAR(20) na migração: 'espontaneo' tem exatamente 10 chars e o limite
# antigo não deixava margem para a próxima.
ORIGEM_ESPONTANEO = "espontaneo"
ORIGENS_QUALIFICACAO_VALIDAS = frozenset({ORIGEM_LP, ORIGEM_EXACT, ORIGEM_ESPONTANEO})


class NatQualificacaoState(Base):
    """Onde cada lead está no fluxo do AGENTE. UM estado por contato.

    NÃO é nat_flow_state com etapas novas — ver o cabeçalho de migrate_qualificacao.py. Em
    resumo: aquela tabela tem `contact_wa_id UNIQUE` e um CHECK com as 7 etapas do fluxo de
    botões; juntar os dois obrigaria a precedência do webhook a virar um `if` sobre o valor
    de `etapa`. Tabelas separadas dão a precedência de graça — existe linha aqui? o agente é
    o dono do inbound.

    Sem FK para contacts, exact_leads, users ou agendamentos: escrita de dentro do webhook,
    e uma FK só acrescentaria um modo de falha capaz de derrubar o lote de mensagens.

    `ultimo_wa_message_id` é a trava de idempotência (padrão nat_flow._ja_processado): a Meta
    reentrega webhook, e sem ele a mesma resposta avançaria a etapa duas vezes.
    """
    __tablename__ = "nat_qualificacao_state"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    contact_wa_id = Column(String(20), unique=True, nullable=False)
    exact_lead_id = Column(Integer, nullable=True)
    origem = Column(String(10), nullable=False)
    etapa = Column(String(30), nullable=False, index=True)

    formacao = Column(Text, nullable=True)
    ano_conclusao = Column(Text, nullable=True)
    atuacao = Column(Text, nullable=True)
    motivacao = Column(Text, nullable=True)

    # COLETADA E NUNCA LIDA PELO FLUXO. A régua R$100/200/300 é critério humano (RECON §1.11).
    # Guardar não custa; deixar o LLM decidir com ela custaria.
    faixa_investimento = Column(Text, nullable=True)

    # O que o LLM extrair além dos campos nomeados, sem exigir ALTER a cada pergunta nova do
    # roteiro. NÃO é onde mora estado de máquina — `etapa` é coluna, e só código a muda.
    dados_extras = Column(JSONB, nullable=True)

    # Id da NOSSA tabela agendamentos, solto de propósito (sem FK).
    agendamento_id = Column(BigInteger, nullable=True)

    ultimo_wa_message_id = Column(Text, nullable=True)

    # ENCERRAMENTO por inatividade. Colunas próprias, e não reuso de `transferido_*`: os
    # dois desfechos são diferentes — transferido é "um humano assume", encerrado é
    # "ninguém assume, o lead calou". A régua de follow-up futura escolhe quem entra nela
    # justamente por essa distinção.
    encerrado_em = Column(DateTime, nullable=True)
    encerrado_motivo = Column(Text, nullable=True)

    transferido_em = Column(DateTime, nullable=True)
    # POR QUE o agente desistiu. Sem isto, `transferido_humano` é um balde onde não se
    # distingue "o LLM caiu" de "o lead pediu para falar com uma pessoa".
    transferido_motivo = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class NatAgendamentoToken(Base):
    """O link personalizado que a Nat manda no chat do lead espontâneo.

    `hub.cenatdata.online/agendar/<token>` — página pública, sem autenticação. Toda a
    identificação da pessoa está DESTE lado: o browser não manda telefone nenhum.

    ------------------------------------------------------------------------------------
    POR QUE UM TOKEN OPACO, E NÃO O wa_id NA URL
    ------------------------------------------------------------------------------------
    A URL é pública. Com o telefone (ou um id sequencial) nela, qualquer um agenda no nome
    de outra pessoa — e um id sequencial é enumerável em minutos. `secrets.token_urlsafe(32)`
    dá 256 bits, que não se adivinha.

    ------------------------------------------------------------------------------------
    UM TOKEN VIVO POR CONTATO, E DUAS COLUNAS PARA DIZER POR QUE MORREU
    ------------------------------------------------------------------------------------
    `uq_token_vivo` é um índice único parcial sobre `contact_wa_id` onde
    `usado_em IS NULL AND revogado_em IS NULL`. Ele faz duas coisas:

      * dá sentido à regra "a Nat não repete o link mais de 1x" — pedir de novo devolve O
        MESMO token, não um novo;
      * é a trava contra a corrida real: dois cliques simultâneos no mesmo link não podem
        virar dois leads na Exact, e `LeadsAdd` não tem idempotência nenhuma para desfazer.

    `revogado_em` existe por causa de um furo do primeiro desenho: com o índice olhando só
    `usado_em`, um token que VENCESSE sem clique trancaria o contato para sempre. Aposentar
    marcando `usado_em` resolveria o índice e mentiria no relatório — link abandonado viraria
    link usado. Duas colunas, dois fatos.

    ------------------------------------------------------------------------------------
    DOIS FUSOS NESTA TABELA, E ESTÁ ESCRITO DE PROPÓSITO
    ------------------------------------------------------------------------------------
    `expira_em` e `usado_em` são NAIVE EM SÃO PAULO, como `nat_scheduled_actions.run_at`.
    `criado_em` vem de `DEFAULT NOW()` e é UTC — auditoria, nunca comparado com os outros.

    Quem compara `expira_em` compara com `nat_guard._agora_sp()`, NUNCA com o `NOW()` do
    Postgres: ele está 3h à frente, e todo token nasceria com 3h a menos de vida.

    Sem FK para contacts nem agendamentos: mesma regra das outras tabelas escritas de dentro
    do webhook — uma FK só acrescenta um modo de falha capaz de derrubar o lote de mensagens.
    """
    __tablename__ = "nat_agendamento_token"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    token = Column(Text, unique=True, nullable=False)

    # wa_id do INBOUND, verbatim. Única fonte do telefone que vai para o LeadsAdd — e o que
    # torna o fluxo espontâneo imune ao 9º dígito: tudo nasce da grafia que chegou, não de
    # uma montada a partir de cadastro. Ver app/telefone.py.
    contact_wa_id = Column(String(20), nullable=False, index=True)

    # O que a Nat já coletou no chat. Tudo opcional: a página pede o que faltar.
    nome = Column(Text, nullable=True)
    curso = Column(Text, nullable=True)       # subSource JÁ RESOLVIDO contra a allowlist
    formacao = Column(Text, nullable=True)
    atuacao = Column(Text, nullable=True)

    expira_em = Column(DateTime, nullable=False)
    usado_em = Column(DateTime, nullable=True)
    revogado_em = Column(DateTime, nullable=True)

    # Id da NOSSA tabela agendamentos, solto de propósito (sem FK).
    agendamento_id = Column(BigInteger, nullable=True)

    criado_em = Column(DateTime, server_default=func.now())


class ExactStageEvent(Base):
    """Uma mudança de estágio observada pelo sync. É o GATILHO da cadência de follow-up.

    Ver o cabeçalho de `migrate_cadencia_fundacoes.py` para o porquê. Em resumo: o sync
    sobrescreve `exact_leads.stage` sem comparar, então sem esta tabela é impossível saber
    QUANDO um lead chegou ao estágio em que está — e uma régua que dispare sobre estado
    varre a base parada na primeira execução.

    `stage_de = NULL` significa PRIMEIRA APARIÇÃO do lead, e o NULL é informação: "nasceu em
    Follow 1" e "migrou para Follow 1" são gatilhos diferentes.

    `observado_em` é UTC (não naive-SP como messages.timestamp): este carimbo é comparado
    com register_date e com os cortes de data, que são UTC.

    Sem FK e sem UNIQUE — os dois de propósito, ver a migração.
    """
    __tablename__ = "exact_stage_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    exact_lead_id = Column(Integer, nullable=False, index=True)
    stage_de = Column(String(50), nullable=True)
    stage_para = Column(String(50), nullable=True)
    funnel_id = Column(Integer, nullable=True)
    observado_em = Column(DateTime, nullable=False,
                          server_default=text("(now() AT TIME ZONE 'utc')"))


class DisparoSkip(Base):
    """Uma linha por lead PULADO num disparo de template. O log que a métrica 6 não tinha.

    O QUE ISTO FECHA (RECON_RELATORIOS_20260901 §4.1)
    ------------------------------------------------------------------------------------------
    `bulk_send_template` devolve `skipped_total` / `skipped_por_regra` / `skipped` **só no
    corpo da resposta HTTP**. O único ponto que persistia era `main.py:240`
    (`sm.result = json.dumps(result)`), no caminho AGENDADO — e o caminho agendado não é
    usado: `scheduled_messages` tem 4 linhas, todas de junho/2026, zero desde agosto.

    Ou seja, 100% dos disparos dos últimos dias saíram pela porta HTTP, cujo retorno ninguém
    guarda. O `skipped_por_regra` que o S6-2 construiu existia só na tela de quem apertou o
    botão, e sumia quando ele fechava a aba. Cada dia sem esta tabela era um dia que nunca
    vai poder ser relatado — e não havia como PROVAR que o filtro de recusa funciona, só que
    ele rodou.

    UM PONTO DE ESCRITA COBRE OS DOIS CAMINHOS. `main.py` chama `bulk_send_template` como
    função Python, não por HTTP; os dois passam pelo mesmo laço. `origem_envio` é o que os
    separa: 'campanha' (massa e agendado) ou 'individual' (o `handleSingleSend` da tela).

    SEM FK EM `telefone`. O pulo acontece ANTES da criação do contato — `contato_existente`
    só roda no ramo de envio, ~100 linhas depois. Um lead nunca contatado não tem linha em
    `contacts`, e uma FK faria o log falhar exatamente nos casos mais interessantes.

    `chave` É GRAVADA, NÃO DERIVADA. Todo agrupamento e todo join do relatório usa a chave
    tolerante (DDD + últimos 8): 379 pessoas têm as duas grafias do telefone. Derivar em SQL
    custa `translate()` sobre a tabela inteira; gravar custa uma chamada a
    `app/telefone.chave_telefone`, que já existe.

    `lead_id` É O `exact_id`, não o `exact_leads.id` — mesma convenção de
    `agendamentos.lead_id`, para que as duas tabelas cruzem sem tradutor.

    NULL em `sent_by` quer dizer "não houve humano logado" (disparo agendado), pela mesma
    regra de `messages.sent_by`. Ver app/autoria.py.
    """
    __tablename__ = "disparo_skip"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    quando = Column(DateTime, nullable=False)        # naive-SP, o relógio de messages.timestamp
    telefone = Column(String(20), nullable=False)    # como foi para a Meta
    chave = Column(String(10), nullable=False)       # DDD + últimos 8
    lead_id = Column(Integer, nullable=True)         # exact_leads.exact_id
    nome = Column(String(255), nullable=True)
    template_name = Column(String(512), nullable=False)
    regra = Column(String(40), nullable=False)       # 'recusa' | 'teto' | 'nat_ativa'
    motivo = Column(Text, nullable=True)
    etapa = Column(String(30), nullable=True)        # só quando regra='nat_ativa'
    origem_envio = Column(String(20), nullable=False)
    sent_by = Column(Integer, ForeignKey("users.id"), nullable=True)


# ==========================================================================================
# RD STATION — a fila de conversões (Fase 1, 07/09/2026)
# ==========================================================================================
#
# Vocabulário espelhado no CHECK de `migrate_rd_conversoes.py`, mesma regra do ETAPAS_VALIDAS
# e do status de `nat_scheduled_actions`: divergir daqui faz o INSERT falhar na hora, que é o
# desfecho desejado — melhor um erro visível que uma linha com status que ninguém drena.
RD_PENDENTE = "pendente"    # esperando o drenador. É o único estado que o job procura.
RD_ENVIADO = "enviado"      # o RD respondeu 2xx. `enviado_em` diz quando.
RD_SKIPPED = "skipped"      # decidimos NÃO enviar, e `motivo` diz por quê. Terminal.
RD_FALHOU = "falhou"        # o RD recusou, ou 3 tentativas queimaram. Terminal.
RD_STATUS = (RD_PENDENTE, RD_ENVIADO, RD_SKIPPED, RD_FALHOU)


class RdConversao(Base):
    """Uma conversão a entregar ao RD Station. Outbox: a decisão e o envio são separados.

    ------------------------------------------------------------------------------------------
    POR QUE OUTBOX, E NÃO UM POST DENTRO DO FLUXO
    ------------------------------------------------------------------------------------------
    O ponto de escrita é o meio do agendamento — entre o `db.commit()` que materializa o
    `Agendamento` e o `BoxesAdd` que reserva o horário na agenda real de uma consultora. Uma
    chamada HTTP ali dentro somaria a latência do RD ao tempo em que o visitante olha para um
    botão desabilitado, e um timeout do RD apareceria para ele como falha de agendamento.

    Com a fila, o fluxo só grava uma linha na MESMA transação do agendamento, e a rede é
    problema de outro processo. É a mesma escolha de `nat_scheduled_actions`, pelo mesmo
    motivo, e o drenador (`rd_sender.py`) é uma cópia reduzida do `nat_scheduler`.

    ------------------------------------------------------------------------------------------
    A CHAVE É A PESSOA, NÃO O AGENDAMENTO
    ------------------------------------------------------------------------------------------
    `UNIQUE (chave, conversion_identifier)`, e `chave` é `email:<normalizado>` ou
    `tel:<dígitos>` — nunca `agendamento_id`.

    O fluxo de duas etapas da landing page grava DUAS linhas em `agendamentos` para UMA
    submissão: `POST /lead` cria a primeira (`lead_criado`) e `POST /agendar` cria a segunda
    (`agendado`), com ids diferentes. Medido em 07/09: 101 dos 124 e-mails repetidos desde
    18/08 são exatamente esse par, 107 deles em menos de 30 minutos. Uma UNIQUE por
    `agendamento_id` aceitaria as duas, e a mesma pessoa viraria duas conversões no RD.

    `agendamento_id` fica na linha, mas como REFERÊNCIA do primeiro que enfileirou — serve
    para investigar, não para deduplicar. O segundo passo da mesma submissão bate no
    `ON CONFLICT DO NOTHING` e não reescreve nada, então o id guardado é o do `lead_criado`.

    ------------------------------------------------------------------------------------------
    SEM FK PARA `agendamentos`
    ------------------------------------------------------------------------------------------
    Mesma política das tabelas `nat_*` e de `disparo_skip`: a fila tem de sobreviver ao
    desaparecimento da linha de origem, e um backfill que enfileire por telefone pode não ter
    `agendamento_id` nenhum. Uma FK transformaria limpeza de histórico em erro de escrita
    numa fila que não deveria nem saber que a outra tabela existe.

    ------------------------------------------------------------------------------------------
    `run_at` E `created_at` SÃO UTC — E AQUI ISSO É EXCEÇÃO
    ------------------------------------------------------------------------------------------
    O resto do projeto usa naive-SP (`messages.timestamp`, `agendamentos.slot_inicio`,
    `nat_scheduled_actions.run_at`), porque aqueles instantes são hora de parede que uma
    pessoa lê. Este não é: `run_at` só existe para o drenador comparar com "agora", e o
    `server_default` é `now() AT TIME ZONE 'utc'`, o mesmo de `exact_stage_events.observado_em`.

    Misturar os dois relógios é o defeito que o cabeçalho de `nat_scheduler.py` documenta (SP
    contra UTC dispara tudo 3h adiantado, em silêncio). Aqui a regra é: **tudo nesta tabela é
    UTC**, e quem escrever `run_at` em Python escreve `datetime.utcnow()`, nunca `agora_sp()`.

    `payload` é NULL nos `skipped`: não há corpo a enviar, e gravar um payload que ninguém vai
    postar convidaria alguém a repescar a linha e mandá-la sem e-mail — que é justo o que o
    `skipped` está dizendo para não fazer.
    """

    __tablename__ = "rd_conversoes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # `email:<normalizado>` ou `tel:<dígitos>`. Ver rd_station.chave_de.
    chave = Column(Text, nullable=False)
    # A string literal do gatilho no RD. Não é derivada do nome do curso — ver rd_station.py.
    conversion_identifier = Column(Text, nullable=False)
    agendamento_id = Column(BigInteger, nullable=True)   # referência, não chave. Sem FK.
    sub_source = Column(String(100), nullable=True)      # como veio, para investigar um skip
    payload = Column(JSONB, nullable=True)               # o corpo do POST. NULL nos skipped.
    status = Column(String(20), nullable=False, default=RD_PENDENTE)
    # 'sem_email' | 'sem_mapa' | 'email_invalido' nos skipped; texto do erro nos falhou.
    motivo = Column(Text, nullable=True)
    tentativas = Column(Integer, nullable=False, default=0)
    run_at = Column(DateTime, nullable=False,
                    server_default=text("(now() AT TIME ZONE 'utc')"))
    # Corpo cru da última resposta do RD, truncado. É o que responde "por que falhou".
    resposta = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False,
                        server_default=text("(now() AT TIME ZONE 'utc')"))
    enviado_em = Column(DateTime, nullable=True)


# ==========================================================================================
# FOLLOW POR ESTÁGIO DA EXACT (27/09/2026)
# ==========================================================================================
#
# Vocabulário espelhado no CHECK de `migrate_follow_estagio.py`, mesma regra do `RD_STATUS`
# acima: as duas definições nascem desta lista, e divergir faz o INSERT falhar na hora em vez
# de gravar um status que ninguém drena.
FE_PENDENTE = "pendente"   # esperando o drenador. É o único estado que o job procura.
FE_ENVIADO = "enviado"     # `bulk_send_template` devolveu `sent >= 1`. `enviado_em` diz quando.
FE_SKIPPED = "skipped"     # o bulk PULOU (recusa, nat_ativa, opt_out_meta) ou faltou dado
                           # nosso (sem_sdr, sem_telefone). `motivo` diz qual. Terminal.
FE_FALHOU = "falhou"       # exceção, ou a Meta recusou. `motivo` é OBRIGATÓRIO. Terminal.
FE_STATUS = (FE_PENDENTE, FE_ENVIADO, FE_SKIPPED, FE_FALHOU)


class FollowEstagioEnvio(Base):
    """Um follow a mandar (ou já mandado) porque o lead entrou num estágio na Exact.

    ==========================================================================================
    POR QUE TABELA PRÓPRIA E NÃO `nat_scheduled_actions`
    ==========================================================================================
    `nat_scheduler.agendar()` (`nat_scheduler.py:205`) **CANCELA o pendente anterior do mesmo
    `(kind, contact_wa_id)`** antes de inserir, e o índice
    `uq_nat_sched_pendente_por_contato` reforça isso no banco. Essa semântica ("no máximo um
    pendente por tipo por contato") está certa para o que ela serve — reagendar um lembrete
    substitui, não acumula.

    Aqui ela seria um defeito silencioso: um lead que entra em `Follow 3` e, antes do job
    rodar, é movido para `Follow 4` teria o `Follow 3` **cancelado**, e receberia só o último.
    Medido: 45 leads entraram em `" Follows 9"` numa única passada de 18/09, e movimentos
    encadeados no mesmo minuto são a norma (§1.3 e §1.4 do recon).

    Daria para contornar embutindo o estágio no `kind` (`follow_estagio_3`), mas aí `kind`
    deixaria de ser um tipo e passaria a ser uma chave composta, e a UNIQUE que importa —
    "uma vez por estágio por lead, PARA SEMPRE" — continuaria impossível, porque a de lá é
    parcial em `status='pendente'`: a linha sai do índice ao ser executada, e a reentrada
    passaria.

    ==========================================================================================
    A UNIQUE É `(lead_exact_id, estagio_id)` — UMA VEZ POR ESTÁGIO, NÃO POR ENTRADA
    ==========================================================================================
    Não é parcial e não tem `evento_id`: é a regra de negócio inteira num índice.

    §4.3 do recon: **28 pares (lead, estágio) se repetem em 30 dias**, em 20 leads, e o padrão
    observado é o vaivém do fim da escada —

        14/09  Follows 8  ->  Follows 9
        17/09   Follows 9 -> Follows 8      (voltou)
        18/09  Follows 8  ->  Follows 9     (entrou DE NOVO)

    `mensagem_follow9` é a despedida: "entendo que não há mais interesse … e encerro aqui meu
    contato". "Uma vez por entrada" a mandaria DUAS VEZES em 32 horas. É a Michele de 26/08
    outra vez (`higiene_disparo.py`), com a nossa assinatura em cima. Custo de "por estágio":
    28 envios a menos em 30 dias (2,2 %), e são exatamente os que não se quer mandar.

    `evento_id` fica na linha como REFERÊNCIA do primeiro evento que a criou — serve para
    investigar, não para deduplicar. O segundo evento bate no `ON CONFLICT DO NOTHING` e não
    reescreve nada, então o id guardado é o da primeira entrada.

    ==========================================================================================
    `estagio_id` É A COLUNA DA UNIQUE, E O NOME VIAJA AO LADO
    ==========================================================================================
    `estagio_id` vem do `follow_estagios.json` (o id em `GET /v3/stages`), não do evento — o
    evento só tem o nome (`exact_stage_events.stage_para`, `varchar(50)`). O id é estável;
    renomear a etapa na Exact não reabre um estágio já enviado.

    `estagio_nome` é o nome **como estava no mapa no momento do envio**. É histórico, como o
    `Reagendamento.` que `exact_stage_events` guarda e que o `/v3/LeadStages` já reescreveu
    para `Reagendamento - IA` (§1.2 do recon). Sem ele, um rename apaga a leitura do passado.

    ==========================================================================================
    SEM FK PARA `exact_leads` NEM PARA `exact_stage_events`
    ==========================================================================================
    Mesma política de `RdConversao`, das tabelas `nat_*` e de `disparo_skip`. `lead_exact_id`
    é o `exact_leads.exact_id` (o id na Exact), não o PK local — é o que `exact_stage_events`
    usa, e é o que sobrevive a um espelho recriado. Há 10 leads no nosso espelho que a Exact
    já não tem (9 901 contra 9 891, medido em 27/09): uma FK transformaria faxina de
    histórico em erro de escrita.

    ATENÇÃO ao chamar `bulk_send_template`: o `lead_ids` dele é **`exact_leads.id` (PK
    local)**, não este `lead_exact_id`. Confundir os dois é um lote vazio silencioso — a rota
    faz `WHERE ExactLead.id.in_(lead_ids)`, não encontra nada e devolve `sent=0` sem erro.

    ==========================================================================================
    `telefone` É CÓPIA, E ISSO É DE PROPÓSITO
    ==========================================================================================
    É o `exact_leads.phone1` no instante em que a linha nasceu. Serve para a allowlist do modo
    de teste e para o log. Não é a chave de nada: a canonização das duas grafias (12/13
    dígitos) é feita pela rota, contra o eco da Meta (`exact_routes.py:531`). Guardar aqui
    evita reler o lead só para decidir se ele está na allowlist.

    ==========================================================================================
    FUSO: TUDO UTC NESTA TABELA
    ==========================================================================================
    Mesma exceção deliberada de `RdConversao`, e pela mesma razão: `created_at` e `enviado_em`
    só existem para o drenador e para auditoria, não são hora de parede que alguém lê. O
    `server_default` é `now() AT TIME ZONE 'utc'`, igual ao de
    `exact_stage_events.observado_em` — que é justamente a coluna com que estas linhas serão
    cruzadas. Misturar SP e UTC aqui daria 3h de deslocamento em silêncio.

    O `messages.timestamp` que a rota grava continua em SP, porque aquele é lido na tela de
    Conversas. As duas regras convivem porque cada tabela declara a sua.
    """
    __tablename__ = "follow_estagio_envios"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # `exact_leads.exact_id`, o id do lead NA EXACT. Ver a seção "SEM FK" acima.
    lead_exact_id = Column(BigInteger, nullable=False)
    telefone = Column(String(30), nullable=True)
    # A chave estável do degrau, vinda do JSON. Junto com `lead_exact_id`, é a UNIQUE.
    estagio_id = Column(Integer, nullable=False)
    estagio_nome = Column(String(50), nullable=True)
    template = Column(String(512), nullable=False)
    # Referência para investigar, nunca para deduplicar. Sem FK (a tabela de eventos pode ser
    # podada, e a linha de follow tem de sobreviver a isso).
    evento_id = Column(BigInteger, nullable=True)
    status = Column(String(20), nullable=False, default=FE_PENDENTE)
    # Obrigatório em `falhou` e em `skipped` — padrão da sprint de 18/09 (`falhou` sem motivo
    # foi o que fez os 60 `follow_20h` quebrados serem indiagnosticáveis por um mês).
    motivo = Column(Text, nullable=True)
    # O retorno de `bulk_send_template` em JSON, truncado. É o que responde "por que pulou".
    resposta = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False,
                        server_default=text("(now() AT TIME ZONE 'utc')"))
    enviado_em = Column(DateTime, nullable=True)


class FollowEstagioCursor(Base):
    """A marca d'água: o último `exact_stage_events.id` que o job já olhou. UMA linha (id=1).

    ==========================================================================================
    POR QUE MARCA D'ÁGUA E NÃO "EVENTOS DAS ÚLTIMAS N HORAS"
    ==========================================================================================
    Uma janela de tempo tem os dois modos de falha ao mesmo tempo: se o processo ficar 20 min
    fora do ar, a janela de 10 min perde os eventos do buraco para sempre; e se a janela for
    generosa, cada passada relê os mesmos eventos e depende da UNIQUE para não duplicar —
    transformando o índice, que é a rede de segurança, no mecanismo.

    Com o cursor, "já vi" é um fato gravado. Restart não reprocessa, e uma queda longa é
    recuperada sozinha na primeira passada depois de voltar.

    ==========================================================================================
    INICIALIZADO COM `MAX(id)` NA MIGRAÇÃO — E ISTO É ESSENCIAL
    ==========================================================================================
    `ultimo_evento_id` nasce com o `MAX(id)` de `exact_stage_events` no momento da migração,
    **não com 0**. Com 0, a primeira passada varreria o histórico inteiro e enfileiraria um
    follow para cada entrada em estágio já ocorrida: 1 255 templates em 30 dias de histórico,
    de uma vez, para leads que já foram descartados, já compraram ou já receberam a despedida.
    É o defeito que "gatilho por EVENTO e não por ESTADO" existe para evitar, e ele voltaria
    pela porta do cursor.

    O gate `FOLLOW_ESTAGIO_ENABLED=false` não protege disso sozinho: ele impede o envio
    enquanto estiver fechado, mas o dia em que abrir o cursor ainda estaria em 0.

    ==========================================================================================
    UMA LINHA, `id = 1`
    ==========================================================================================
    Mesmo padrão de `nat_config` e `auto_welcome_config`: singleton por convenção, não por
    constraint. O job faz `UPDATE ... WHERE id = 1` e só avança o cursor DEPOIS de ter
    inserido (ou conflitado) as linhas daquele lote, na mesma transação — se o commit falhar,
    o cursor não anda e o lote volta na passada seguinte.

    Avançar o cursor ANTES de enfileirar perderia eventos em silêncio. Avançar depois do
    ENVIO (e não do enfileiramento) seria pior: um envio lento seguraria o cursor e a passada
    seguinte releria os mesmos eventos.
    """
    __tablename__ = "follow_estagio_cursor"

    id = Column(Integer, primary_key=True, default=1)
    ultimo_evento_id = Column(BigInteger, nullable=False, default=0)
    atualizado_em = Column(DateTime, nullable=False,
                           server_default=text("(now() AT TIME ZONE 'utc')"))
