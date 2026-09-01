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
    erro = Column(Text, nullable=True)           # mensagem crua da Exact, sem tradução
    origem_ip = Column(String(45), nullable=True)  # 45 = IPv6 textual
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


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
