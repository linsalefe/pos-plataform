"""O fluxo de agendamento: box -> lead -> schedule, com compensação e estado local.

------------------------------------------------------------------------------------------
POR QUE O BOX VEM PRIMEIRO
------------------------------------------------------------------------------------------
Porque é o único passo desfazível. `BoxesRemove` funciona enquanto o box não tiver reunião
(AGENDAMENTO_FINDINGS.md §8: o box `busy` do experimento saiu com 204 — o que trava a remoção
é a reunião, não o status).

Na ordem inversa, um `BoxesAdd` que falhasse por conflito deixaria lead órfão no CRM, e a
única saída seria `LeadsDelete` — que é exclusão DURA (o `LeadsRecover` responde "Lead not
found") e cascateia para reunião e box. Trocar um horário perdido por um lead destruído é um
mau negócio.

E o `BoxesAdd` sendo primeiro tem um segundo efeito, mais importante: ele É o lock. Quem
consegue criar o box ganhou o horário. Não existe janela de check-then-act.

------------------------------------------------------------------------------------------
A COMPENSAÇÃO, E O QUE ELA DELIBERADAMENTE NÃO FAZ
------------------------------------------------------------------------------------------
    passo 2 falha  ->  BoxesRemove. Não sobra nada.
    passo 3 falha  ->  BoxesRemove, e O LEAD FICA. Em `Entrada`, com telefone e origem.

O lead que fica não é sujeira: é uma pessoa real que preencheu o formulário e quer falar com
a CENAT. Ela aparece no funil e um SDR liga. O que se perdeu foi o horário, não o contato —
e `LeadsDelete` transformaria uma falha de agendamento numa perda de lead.

**Nunca chamar LeadsDelete como compensação.** Está escrito aqui porque é a tentação óbvia
de quem for mexer nisto depois.

------------------------------------------------------------------------------------------
O QUE NÃO TEM DESFAZER
------------------------------------------------------------------------------------------
Depois do passo 3 não há compensação nenhuma: não existe `ScheduleRemove` na API. Remarcação
e cancelamento saem pelo WhatsApp, por decisão de produto. A consequência aceita é que cada
remarcação queima um slot da agenda para sempre.
"""
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agendamento import client, disponibilidade, origens
from app.agendamento.grade import Slot, grade
from app.agendamento.horarios import agora_sp
from app.models import (PASSO_AGENDADO, PASSO_BOX_CRIADO, PASSO_FALHOU, PASSO_INICIADO,
                        PASSO_LEAD_CRIADO, Agendamento)

# `source` segue fixo: é a origem de marketing da CENAT inteira, não varia por curso.
#
# `subSource` NÃO é mais fixo — vem do corpo do POST, conferido contra a allowlist de
# `origens.py`. O que não pode é aceitar texto livre: `LeadsAdd` CRIA o subSource quando o
# valor não existe (medido — ver o cabeçalho de origens.py), e o cadastro é global e usado em
# relatório. A allowlist é o que separa "configurável" de "qualquer um escreve lá dentro".
FUNIL_POS_GRADUACAO = 18535
SOURCE = "Rd Marketing"
STAGE_AGENDADOS = "Agendados"

# Janela em que dois POSTs do mesmo telefone são tratados como duplo clique, não como duas
# intenções. Protege o que o `BoxesAdd` não protege: ele barra o mesmo HORÁRIO, não a mesma
# PESSOA pegando dois horários diferentes em dois cliques.
JANELA_DUPLO_CLIQUE = timedelta(seconds=90)


class SlotInvalido(Exception):
    """O id de slot não pertence à grade, ou já venceu a antecedência mínima. -> 400"""


class SlotIndisponivel(Exception):
    """O horário foi tomado entre a exibição e o clique. -> 409, o front recarrega."""


class AgendamentoFalhou(Exception):
    """Falha nossa ou da Exact depois do lock. -> 502. `lead_id` diz se o lead sobreviveu."""

    def __init__(self, mensagem: str, *, lead_id: int | None = None):
        super().__init__(mensagem)
        self.lead_id = lead_id


@dataclass
class Resultado:
    agendamento_id: int
    lead_id: int
    box_id: int
    slot: Slot
    meeting_id: int | None


async def _duplo_clique(db: AsyncSession, telefone: str) -> Agendamento | None:
    corte = agora_sp() - JANELA_DUPLO_CLIQUE
    res = await db.execute(
        select(Agendamento)
        .where(Agendamento.telefone == telefone,
               Agendamento.created_at >= corte,
               Agendamento.passo == PASSO_AGENDADO)
        .order_by(Agendamento.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def _marcar(db: AsyncSession, ag: Agendamento, passo: str, *, erro: str | None = None):
    """Grava o passo ANTES da próxima chamada à Exact e commita.

    O commit por passo é o ponto: sem ele, um processo morto no meio do fluxo perderia toda a
    linha, e a faxina nunca saberia que existe um box nosso para remover. É a mesma razão de
    `nat_scheduler` marcar `executado` na mesma transação da ação — só que aqui o efeito
    colateral é externo e não volta atrás, então o registro tem que vir na frente.
    """
    ag.passo = passo
    ag.erro = erro
    ag.updated_at = agora_sp()
    await db.commit()


async def agendar(db: AsyncSession, *, nome: str, email: str | None, telefone: str,
                  slot_id: str, origem: str | None = None,
                  origem_ip: str | None = None) -> Resultado:
    """Caminho completo da LP.

    Levanta SlotInvalido / SlotIndisponivel / AgendamentoFalhou / origens.OrigemInvalida.
    """
    g = grade()
    slot = g.slot_por_id(slot_id)
    if slot is None:
        raise SlotInvalido(f"slot fora da grade ou vencido: {slot_id!r}")

    # Resolvido ANTES de qualquer escrita: uma origem inválida não pode chegar a criar box e
    # depois falhar, deixando o horário bloqueado até a faxina passar.
    sub_source = origens.resolver(origem)

    anterior = await _duplo_clique(db, telefone)
    if anterior is not None:
        # Devolve o agendamento que já deu certo em vez de criar um segundo. O visitante que
        # clicou duas vezes vê a mesma confirmação, que é o que ele espera.
        print(f"🔁 agendamento: duplo clique de {telefone}, devolvendo #{anterior.id}")
        return Resultado(agendamento_id=anterior.id, lead_id=anterior.lead_id,
                         box_id=anterior.box_id, slot=slot, meeting_id=anterior.meeting_id)

    agora = agora_sp()
    ag = Agendamento(
        nome=nome, email=email, telefone=telefone,
        slot_inicio=slot.inicio, slot_fim=slot.fim,
        sales_rep_email=g.sales_rep_email, sub_source=sub_source,
        passo=PASSO_INICIADO, origem_ip=origem_ip,
        created_at=agora, updated_at=agora,
    )
    db.add(ag)
    await db.commit()

    # ---- passo 1: o lock ------------------------------------------------------------
    try:
        box_id = await client.criar_box(
            inicio=slot.inicio, fim=slot.fim,
            sales_rep_email=g.sales_rep_email,
            type_meeting=g.type_meeting,
            description=f"Agendamento LP — {nome}",
        )
    except client.SlotOcupado as e:
        await _marcar(db, ag, PASSO_FALHOU, erro=str(e))
        disponibilidade.invalidar_cache()
        print(f"⚠️ agendamento #{ag.id}: slot {slot.id} já ocupado — {e}")
        raise SlotIndisponivel(str(e)) from e
    except client.ExactErro as e:
        await _marcar(db, ag, PASSO_FALHOU, erro=str(e))
        print(f"❌ agendamento #{ag.id}: BoxesAdd falhou — {type(e).__name__}: {e}")
        raise AgendamentoFalhou(str(e)) from e

    ag.box_id = box_id
    await _marcar(db, ag, PASSO_BOX_CRIADO)
    print(f"📦 agendamento #{ag.id}: box {box_id} criado para {slot.id}")

    # ---- passo 2: o lead ------------------------------------------------------------
    try:
        lead_id = await client.criar_lead(
            nome=nome, telefone=telefone, email=email,
            source=SOURCE, sub_source=sub_source, funnel_id=FUNIL_POS_GRADUACAO,
        )
    except client.ExactErro as e:
        await _compensar_box(db, ag, motivo="LeadsAdd falhou")
        await _marcar(db, ag, PASSO_FALHOU, erro=str(e))
        print(f"❌ agendamento #{ag.id}: LeadsAdd falhou — {type(e).__name__}: {e}")
        raise AgendamentoFalhou(str(e)) from e

    ag.lead_id = lead_id
    await _marcar(db, ag, PASSO_LEAD_CRIADO)
    print(f"👤 agendamento #{ag.id}: lead {lead_id} criado "
          f"(Entrada, funil {FUNIL_POS_GRADUACAO}, subSource {sub_source})")

    # ---- passo 3: ponto de não retorno ----------------------------------------------
    try:
        await client.agendar_reuniao(
            box_id=box_id, lead_id=lead_id,
            stage_name=STAGE_AGENDADOS, sales_rep_email=g.sales_rep_email,
        )
    except client.ExactErro as e:
        # O box sai; o LEAD FICA em Entrada, com telefone e origem. Ver cabeçalho.
        await _compensar_box(db, ag, motivo="scheduleAdd falhou")
        await _marcar(db, ag, PASSO_FALHOU, erro=str(e))
        print(f"❌ agendamento #{ag.id}: scheduleAdd falhou — {type(e).__name__}: {e}. "
              f"Lead {lead_id} MANTIDO em Entrada de propósito.")
        raise AgendamentoFalhou(str(e), lead_id=lead_id) from e

    await _marcar(db, ag, PASSO_AGENDADO)
    disponibilidade.invalidar_cache()
    print(f"✅ agendamento #{ag.id}: lead {lead_id} agendado em {slot.id} "
          f"(box {box_id}, {g.sales_rep_email})")

    # O id da reunião é best-effort: o scheduleAdd devolve booleano (FINDINGS §4) e falhar
    # aqui não desfaz nada — a reunião existe.
    try:
        reuniao = await client.meeting_por_lead(lead_id)
        if reuniao:
            ag.meeting_id = int(reuniao["id"])
            ag.updated_at = agora_sp()
            await db.commit()
    except (client.ExactErro, KeyError, TypeError, ValueError) as e:
        print(f"⚠️ agendamento #{ag.id}: agendado, mas não consegui o meeting_id — {e}")

    return Resultado(agendamento_id=ag.id, lead_id=lead_id, box_id=box_id,
                     slot=slot, meeting_id=ag.meeting_id)


async def _compensar_box(db: AsyncSession, ag: Agendamento, *, motivo: str) -> None:
    """Devolve o horário à agenda. Nunca levanta — já estamos tratando uma falha.

    Se o `BoxesRemove` também falhar, a linha fica em `box_criado` e a faxina tenta de novo
    daqui a alguns minutos. É por isso que a faxina não olha só a idade do box.
    """
    if ag.box_id is None:
        return
    try:
        await client.remover_box(ag.box_id)
        print(f"↩️ agendamento #{ag.id}: box {ag.box_id} removido ({motivo})")
    except client.ExactErro as e:
        print(f"⚠️ agendamento #{ag.id}: não consegui remover o box {ag.box_id} "
              f"({motivo}) — {type(e).__name__}: {e}. A faxina tentará de novo.")


async def cadastrar_lead_sem_agendar(db: AsyncSession, *, nome: str, email: str | None,
                                     telefone: str, origem: str | None = None,
                                     origem_ip: str | None = None) -> int:
    """Fallback do POST /lead: cadastra e pronto. O lead cai em `Entrada`.

    Existe para o visitante que não quer escolher horário, e para o caso de a grade estar
    vazia (feriado, agenda lotada, grade desencostada da realidade). Perder o contato porque
    não havia horário seria o pior desfecho possível de uma landing page.

    Não cria box e não toca em agenda — por isso não tem compensação nenhuma.
    """
    sub_source = origens.resolver(origem)
    agora = agora_sp()
    ag = Agendamento(
        nome=nome, email=email, telefone=telefone,
        slot_inicio=agora, slot_fim=agora,  # sem slot; as colunas são NOT NULL
        sales_rep_email=grade().sales_rep_email, sub_source=sub_source,
        passo=PASSO_INICIADO, origem_ip=origem_ip,
        created_at=agora, updated_at=agora,
    )
    db.add(ag)
    await db.commit()

    try:
        lead_id = await client.criar_lead(
            nome=nome, telefone=telefone, email=email,
            source=SOURCE, sub_source=sub_source, funnel_id=FUNIL_POS_GRADUACAO,
        )
    except client.ExactErro as e:
        await _marcar(db, ag, PASSO_FALHOU, erro=str(e))
        print(f"❌ agendamento #{ag.id}: LeadsAdd (sem agendar) falhou — {e}")
        raise AgendamentoFalhou(str(e)) from e

    ag.lead_id = lead_id
    await _marcar(db, ag, PASSO_LEAD_CRIADO)
    print(f"👤 agendamento #{ag.id}: lead {lead_id} cadastrado sem agendar "
          f"(Entrada, subSource {sub_source})")
    return lead_id
