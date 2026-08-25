"""Onde o agente NASCE: agenda a abertura para +5 min. Módulo deliberadamente magro.

------------------------------------------------------------------------------------------
POR QUE ELE EXISTE EM VEZ DE UM IMPORT DIRETO
------------------------------------------------------------------------------------------
Quem chama isto é o módulo `agendamento/`, que atende a landing page e é o ÚNICO caminho
público do backend. `horarios.py:26-27` já documenta a regra: não trazer para o caminho da
LP nada que carregue a cadeia de envio do WhatsApp.

E `qualificacao_fluxo` carrega — ele importa `nat_sender`, que importa `whatsapp`. Este
módulo importa só `nat_scheduler` (que puxa apenas database/models/nat_guard, verificado) e
`models`. O fluxo só é carregado lá na frente, quando o agendador executa a ação, fora do
request do visitante.

------------------------------------------------------------------------------------------
POR QUE +5 MINUTOS
------------------------------------------------------------------------------------------
A ramificação do roteiro ("já agendou" × "não agendou") só é definitiva depois que a pessoa
termina — ou abandona — o obrigado.html. MEDIDO em 24/08 nos 54 pares reais:

    mediana 28s · mínimo 6,6s · MÁXIMO 3min14s

Aos 5 minutos, 100% dos casos observados já decidiram. Disparar na hora do POST /lead
mandaria "vamos marcar um horário?" para quem está marcando naquele instante.

O índice único parcial `uq_nat_sched_pendente_por_contato (kind, contact_wa_id) WHERE
status='pendente'` já impede duplicata; `nat_scheduler.agendar` cancela o pendente anterior
antes de inserir, então dois POSTs da mesma pessoa reagendam em vez de acumular.
"""
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KIND_INICIAR_QUALIFICACAO, ORIGEM_EXACT, ORIGEM_LP
from app.nat_guard import _agora_sp

ESPERA = timedelta(minutes=5)

# A referência de data do lead vai para o payload em UTC naive, que é o fuso de
# `qualificacao_start_at`. Ver o cabeçalho de qualificacao_guard: converter no destino
# exigiria adivinhar o fuso da entrada.
OFFSET_SP_PARA_UTC = timedelta(hours=3)


def wa_id_de(telefone: str) -> str:
    """`11999998888` → `5511999998888`. Mesma regra de `exact_spotter.format_phone`.

    Reescrita aqui, em três linhas, em vez de importada: `exact_spotter` carrega
    `send_template_message` no topo, e importá-lo colocaria a cadeia de envio no caminho do
    POST da landing page — exatamente o que este módulo existe para evitar.
    """
    digitos = "".join(c for c in (telefone or "") if c.isdigit())
    if not digitos:
        return ""
    return digitos if digitos.startswith("55") else "55" + digitos


async def agendar_abertura(db: AsyncSession, *, telefone: str, lead_id: int | None,
                           origem: str = ORIGEM_LP, nascido_em=None) -> None:
    """Agenda a abertura do agente. NUNCA levanta — a LP não pode quebrar por causa disto.

    `nascido_em` é naive em SP (é o `agendamentos.created_at`); None usa agora. Vira UTC no
    payload.

    Nada aqui verifica se o agente está ligado: quem decide é a ADMISSÃO, no handler, +5 min
    depois. Enfileirar sempre e admitir na execução é o que torna a ativação instantânea —
    ligar a chave passa a valer para quem já está na fila, sem precisar de backfill.
    """
    try:
        wa_id = wa_id_de(telefone)
        if not wa_id:
            return

        # QUEM JÁ TEM ESTADO NÃO PRECISA DE ABERTURA — e enfileirar assim mesmo tem custo.
        #
        # `abrir()` já barra este caso ("já tem estado — abertura ignorada"), então isto não
        # é correção de bug: é evitar lixo. O caminho que trouxe a necessidade foi o lead
        # ESPONTÂNEO, em que o booking pela página chama `fluxo.agendar` para alguém que está
        # em `esp_link_enviado` — a abertura nasceria condenada.
        #
        # E o lixo não é inofensivo: `monitor_qualificacao.py` §2b procura AÇÃO EXECUTADA SEM
        # ESTADO CORRESPONDENTE, que é a assinatura do descarte silencioso (lead perdido pelo
        # teto ou pelo corte). Uma abertura enfileirada para quem já tem estado produz
        # exatamente essa assinatura como FALSO POSITIVO — o alerta que existe para pegar
        # lead descartado passaria a gritar por lead atendido.
        #
        # A consulta é tolerante ao 9º dígito (ver app/telefone.py) porque a chave montada
        # aqui vem do TELEFONE e o estado pode ter nascido da grafia do inbound.
        from app.models import NatQualificacaoState
        from app.telefone import variantes_wa_id
        from sqlalchemy import select
        vs = variantes_wa_id(wa_id)
        if vs:
            ja = (await db.execute(
                select(NatQualificacaoState.etapa)
                .where(NatQualificacaoState.contact_wa_id.in_(vs)))).scalars().first()
            if ja is not None:
                print(f"↩️  Agente: {wa_id} já tem estado ({ja}) — abertura NÃO enfileirada")
                return

        from app.nat_scheduler import agendar as agendar_acao
        referencia = (nascido_em or _agora_sp()) + OFFSET_SP_PARA_UTC
        await agendar_acao(
            KIND_INICIAR_QUALIFICACAO, wa_id, _agora_sp() + ESPERA,
            {"lead_id": lead_id, "origem": origem,
             "referencia_utc": referencia.isoformat()},
            db)
    except Exception as e:
        # Falhar aqui não pode custar o lead nem o agendamento que acabaram de dar certo.
        print(f"⚠️  Agente: gatilho não agendado para {telefone!r} "
              f"({type(e).__name__}: {e})")
