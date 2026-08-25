"""Trava central do AGENTE de pré-qualificação. Nada do agente atua sem passar por aqui.

Mesmo princípio do `nat_guard`: FALHA FECHADA. Qualquer dúvida, qualquer ausência de dado,
qualquer exceção inesperada → (False, motivo). Nunca (True) por omissão.

------------------------------------------------------------------------------------------
POR QUE NÃO REUSAR nat_pode_atuar
------------------------------------------------------------------------------------------
Aquela função checa cinco coisas, e TRÊS são específicas do fluxo de botões:

    nat_enabled ......... ligar o agente exigiria ligar o fluxo velho junto
    funil == 18535 ...... 21 dos 80 leads da LP medidos já tinham migrado para 18537/21007
    assigned_to em {4,5}  5 dos 80 estavam com Vi, Isa ou Victória

As duas que valem para os dois fluxos — corte por data e teto por hora — estão reproduzidas
aqui sobre os campos PRÓPRIOS do agente. Um guard por fluxo, e nenhum envio sem guard.

------------------------------------------------------------------------------------------
DUAS PORTAS, NÃO UMA
------------------------------------------------------------------------------------------
`qualificacao_pode_iniciar` é a ADMISSÃO: roda uma vez, quando o lead entraria no fluxo. É
onde mora o corte por data.

`qualificacao_pode_atuar` é o ENVIO: roda a cada mensagem, e é o que `send_nat_message`
recebe em `guard=`. NÃO repete o corte por data — de propósito. A data decide quem ENTRA;
uma vez dentro, o lead está numa conversa, e recusar a terceira mensagem dela porque o corte
mudou deixaria a pessoa falando sozinha. O que ele checa é o que pode mudar no meio da
conversa: a chave geral e o teto por hora.

------------------------------------------------------------------------------------------
A DATA DE REFERÊNCIA NÃO É SEMPRE register_date
------------------------------------------------------------------------------------------
O gatilho da LP dispara +5 min depois do formulário, e o sync roda a cada 600s: MEDIDO, a
boas-vindas sai em mediana 4min24s e no pior caso 11min19s depois do form — ou seja, aos 5
minutos o lead da LP pode ainda NÃO existir em `exact_leads`, e `register_date` seria NULL.

Por isso a admissão recebe a data JÁ RESOLVIDA por quem chama:
    origem 'lp'    -> agendamentos.created_at, que é naive em SP e existe na hora
    origem 'exact' -> exact_leads.register_date, que é UTC

`qualificacao_start_at` é gravado em UTC (mesma rota de config, mesmo `_para_utc_naive`), e
por isso a admissão exige receber a referência já em UTC naive. Converter aqui dentro
exigiria adivinhar o fuso da entrada — e adivinhar errado põe o corte 3h fora, em silêncio.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.telefone import variantes_wa_id
from app.models import (ETAPAS_QUALIFICACAO_ATIVAS, Contact, Message, NatConfig,
                        NatQualificacaoState)
from app.nat_guard import _agora_sp

# Valores de `messages.nat_etapa` que pertencem ao AGENTE. É o que separa o teto por hora
# dele do teto do fluxo velho SEM coluna nova: os dois gravam no mesmo marcador, e cada um
# conta só os seus nomes.
#
# Os quatro primeiros são nomes de template aprovado (whatsapp_templates ids 2-5); o último é
# marcador de fala livre gerada pelo LLM dentro da janela de 24h, que não tem template.
ETAPA_ABERTURA_AGENDADO = "nat_abertura_agendado"
ETAPA_ABERTURA_QUALIFICACAO = "nat_abertura_qualificacao"
ETAPA_ABERTURA_SEM_FORMACAO = "nat_abertura_sem_formacao"
ETAPA_LEMBRETE_REUNIAO = "nat_lembrete_reuniao"
ETAPA_CONVERSA = "qualif_conversa"

ETAPAS_DE_ENVIO_DO_AGENTE = (
    ETAPA_ABERTURA_AGENDADO, ETAPA_ABERTURA_QUALIFICACAO, ETAPA_ABERTURA_SEM_FORMACAO,
    ETAPA_LEMBRETE_REUNIAO, ETAPA_CONVERSA,
)

ABERTURAS = frozenset({ETAPA_ABERTURA_AGENDADO, ETAPA_ABERTURA_QUALIFICACAO,
                       ETAPA_ABERTURA_SEM_FORMACAO})


async def _carregar_config(db: AsyncSession):
    """Singleton id=1 de nat_config. Ausência = desligado."""
    res = await db.execute(select(NatConfig).where(NatConfig.id == 1))
    return res.scalar_one_or_none()


async def contar_envios_ultima_hora(db: AsyncSession) -> int:
    """Envios DO AGENTE na última hora, pelo marcador nat_etapa.

    Recorte em `_agora_sp()` e não em `now()` do Postgres: o banco está em Etc/UTC e
    messages.timestamp é naive em SP. Um `now() - interval '1 hour'` ficaria 3h adiantado e
    NUNCA casaria com nada — o teto passaria sempre, em silêncio.
    """
    corte = _agora_sp() - timedelta(hours=1)
    res = await db.execute(
        select(func.count()).select_from(Message).where(
            Message.direction == "outbound",
            Message.timestamp >= corte,
            Message.nat_etapa.in_(ETAPAS_DE_ENVIO_DO_AGENTE),
        )
    )
    return int(res.scalar() or 0)


# O teto é o ÚNICO bloqueio deste módulo que passa sozinho com o tempo, e por isso é o único
# que merece adiamento em vez de descarte (Risco 3). Quem recebe o motivo precisa reconhecê-lo
# sem casar string à mão em três arquivos — daí a constante e o `e_teto`.
MOTIVO_TETO = "teto de envios/hora estourado"


def e_teto(motivo: str | None) -> bool:
    """Este motivo de recusa é o teto por hora? Então esperar resolve — não descartar.

    Serve tanto para o motivo devolvido pela ADMISSÃO quanto para o do ENVIO (`enviar_nat`
    repassa o motivo do guard tal e qual), que é justamente o que permite ao handler da
    abertura tratar os dois pontos com a mesma regra.
    """
    return bool(motivo) and motivo.startswith(MOTIVO_TETO)


async def _teto_ok(config, db: AsyncSession) -> tuple[bool, str]:
    teto = config.max_envios_hora
    if teto is None:
        return False, "max_envios_hora não definido"
    enviados = await contar_envios_ultima_hora(db)
    if enviados >= teto:
        return False, f"{MOTIVO_TETO} ({enviados}/{teto})"
    return True, "ok"


async def qualificacao_pode_iniciar(referencia_utc: datetime | None,
                                    db: AsyncSession) -> tuple[bool, str]:
    """ADMISSÃO: este lead pode entrar no fluxo do agente? (pode, motivo).

    `referencia_utc` é a data de nascimento do lead, JÁ em UTC naive — ver o cabeçalho.
    None significa "não sei quando este lead nasceu", e falha fechada: sem data não há como
    garantir que ele é posterior ao corte, e admitir seria abrir a porta para a base inteira.
    """
    def bloqueia(motivo: str) -> tuple[bool, str]:
        print(f"🔒 Agente bloqueado: {motivo}")
        return False, motivo

    try:
        config = await _carregar_config(db)
        if config is None:
            return bloqueia("nat_config inexistente (id=1) — sem config, agente não atua")
        if not config.qualificacao_enabled:
            return bloqueia("qualificacao_enabled=false")
        if config.qualificacao_start_at is None:
            return bloqueia("qualificacao_start_at não definido — corte de data ausente")
        if referencia_utc is None:
            return bloqueia("data de referência ausente no lead")
        if referencia_utc < config.qualificacao_start_at:
            return bloqueia(f"lead de {referencia_utc} é anterior ao corte "
                            f"{config.qualificacao_start_at}")
        ok, motivo = await _teto_ok(config, db)
        if not ok:
            return bloqueia(motivo)
        return True, "ok"
    except Exception as e:
        # FALHA FECHADA — exceção inesperada nunca libera.
        return bloqueia(f"erro inesperado na admissão: {type(e).__name__}: {e}")


async def qualificacao_pode_atuar(contact: Contact, db: AsyncSession) -> tuple[bool, str]:
    """ENVIO: é o que vai em `send_nat_message(guard=...)`. (pode, motivo).

    Assinatura idêntica a `nat_pode_atuar` porque é isso que a injeção exige.

    Exige estado ATIVO: o agente só fala com quem ele já admitiu e que ainda está numa etapa
    de conversa. Depois de `concluido`, `transferido_humano` ou `encerrado` ele cala — e essa
    é a MESMA condição que o webhook usa para decidir a precedência, então "o agente fala" e
    "o agente escuta" nunca divergem.
    """
    def bloqueia(motivo: str) -> tuple[bool, str]:
        print(f"🔒 Agente não enviou: {motivo}")
        return False, motivo

    try:
        config = await _carregar_config(db)
        if config is None:
            return bloqueia("nat_config inexistente (id=1)")
        if not config.qualificacao_enabled:
            return bloqueia("qualificacao_enabled=false")

        wa_id = getattr(contact, "wa_id", None)
        if not wa_id:
            return bloqueia("contato sem wa_id")

        # Mesma tolerância ao 9º dígito de `qualificacao_fluxo.estado_de` — a REGRA mora em
        # `app/telefone.py`, e a consulta é repetida aqui em vez de importada porque
        # `qualificacao_fluxo` já importa este módulo (importar de volta seria ciclo).
        # Ordenado: o mesmo humano pode ter duas linhas, e `scalar_one_or_none` levantaria.
        vs = variantes_wa_id(wa_id)
        estado = (await db.execute(
            select(NatQualificacaoState)
            .where(NatQualificacaoState.contact_wa_id.in_(vs or ("",)))
            .order_by(NatQualificacaoState.id))).scalars().first()
        if estado is None:
            return bloqueia(f"{wa_id} não tem estado do agente")
        if estado.etapa not in ETAPAS_QUALIFICACAO_ATIVAS:
            return bloqueia(f"{wa_id} está em '{estado.etapa}', etapa em que o agente cala")

        ok, motivo = await _teto_ok(config, db)
        if not ok:
            return bloqueia(motivo)
        return True, "ok"
    except Exception as e:
        return bloqueia(f"erro inesperado na verificação: {type(e).__name__}: {e}")


async def guard_de_abertura(contact: Contact, db: AsyncSession) -> tuple[bool, str]:
    """Guard das ABERTURAS e do LEMBRETE, quando não há (ou não se exige) estado ativo.

    A abertura é o envio que CRIA a conversa: exigir estado ativo nela seria exigir que ela
    já tivesse acontecido. O lembrete é o oposto — sai quando a etapa já é `concluido`, em que
    `qualificacao_pode_atuar` cala de propósito.

    Checa chave geral e teto. A admissão (corte por data) já rodou no handler, antes.
    """
    def bloqueia(motivo: str) -> tuple[bool, str]:
        print(f"🔒 Agente não abriu: {motivo}")
        return False, motivo

    try:
        config = await _carregar_config(db)
        if config is None or not config.qualificacao_enabled:
            return bloqueia("qualificacao_enabled=false ou config ausente")
        ok, motivo = await _teto_ok(config, db)
        if not ok:
            return bloqueia(motivo)
        return True, "ok"
    except Exception as e:
        return bloqueia(f"erro inesperado na abertura: {type(e).__name__}: {e}")
