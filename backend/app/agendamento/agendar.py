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
O FLUXO DE DUAS ETAPAS: `lead_id` JÁ PRONTO
------------------------------------------------------------------------------------------
A landing page trocou o formulário do RD Station por um form nativo, e isso partiu o fluxo
em duas requisições:

    index.html   -> POST /lead                  -> lead criado em Entrada
    obrigado.html -> POST /agendar com leadId   -> agenda O MESMO lead

Sem isso, o `/agendar` faria `LeadsAdd` de novo e a pessoa viraria DOIS leads no funil — um
do formulário, outro do agendamento — com o SDR ligando duas vezes para o mesmo telefone.

Com `lead_id`, o passo 2 deixa de ser criação e vira **verificação**: `GET /Leads` com
`$filter=id eq {leadId}`. Lead inexistente para o fluxo antes de qualquer escrita.

E a compensação ganha uma razão a mais para não tocar no lead. No fluxo de uma etapa,
preservar o lead é decisão de produto. Aqui é mais simples que isso: **o lead não é nosso**.
Foi criado por outra requisição, possivelmente minutos antes, e apagá-lo destruiria o
contato de alguém que sequer chegou a escolher horário. A coluna `lead_externo` grava essa
distinção, porque `lead_id` preenchido tem a mesma cara nos dois caminhos.

O caminho SEM `lead_id` continua idêntico ao que sempre foi — a LP de Mulheridades usa ele.

------------------------------------------------------------------------------------------
QUAL CONSULTORA ATENDE, E POR QUE O 409 FICOU MAIS RARO
------------------------------------------------------------------------------------------
Com mais de uma consultora, o mesmo horário pode estar livre para várias. A escolha é por
**menor carga do dia** (`escolher_consultora`), contada na NOSSA tabela — não na Exact, que
não distingue reunião nossa de compromisso pessoal dela.

E o `Boxes are occupied` deixou de ser 409 imediato. Antes ele significava "o horário
morreu"; agora significa "morreu PARA ESTA consultora", e o fluxo tenta a próxima da lista
antes de desistir. Só quando todas recusam é que o visitante vê 409.

Isso importa mais do que parece: `disponibilidade` é cacheada por 60s, então duas pessoas
que abrem a página juntas veem a mesma oferta. Sem o retry, a segunda tomaria 409 mesmo
havendo consultora livre no mesmo horário — e a LP mandaria ela escolher outro horário sem
necessidade.

O `BoxesAdd` continua sendo o lock. O que mudou é que agora existem N locks independentes,
um por agenda, e perder um não é perder o horário.

------------------------------------------------------------------------------------------
O QUE NÃO TEM DESFAZER
------------------------------------------------------------------------------------------
Depois do passo 3 não há compensação nenhuma: não existe `ScheduleRemove` na API. Remarcação
e cancelamento saem pelo WhatsApp, por decisão de produto. A consequência aceita é que cada
remarcação queima um slot da agenda para sempre.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agendamento import client, consultoras as equipe_mod, disponibilidade
from app.agendamento import extras as extras_mod, origens
from app.agendamento.grade import Slot
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


class LeadNaoEncontrado(Exception):
    """O `leadId` do corpo não existe na Exact. -> 404, e NADA foi escrito.

    Acontece de verdade, não é só defesa contra POST forjado: o visitante pode ter deixado
    o obrigado.html aberto até o lead ser excluído do CRM, ou ter chegado com um `?lead=`
    copiado de outra sessão.
    """


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
    consultora_email: str = ""
    consultora_nome: str = ""


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


async def escolher_consultora(db: AsyncSession, candidatas, dia) -> list:
    """Ordena as candidatas por carga do dia, da mais livre para a mais cheia.

    Devolve LISTA, não uma só: quem chama percorre na ordem quando a primeira perde a
    corrida do `BoxesAdd`. Empate mantém a ordem da configuração, que é estável entre
    processos — sortear aqui tornaria o comportamento irreprodutível no log.

    A carga é contada na NOSSA tabela e não na Exact de propósito. A agenda da consultora tem
    compromisso pessoal, bloco de equipe e reunião de outro funil; distribuir por ela faria a
    LP evitar quem tem a agenda cheia por motivos que não têm nada com a landing page. O que
    queremos equilibrar é o que NÓS mandamos.
    """
    if len(candidatas) <= 1:
        return list(candidatas)
    inicio = datetime.combine(dia, time.min)
    fim = inicio + timedelta(days=1)
    res = await db.execute(
        select(Agendamento.sales_rep_email, func.count())
        .where(Agendamento.slot_inicio >= inicio,
               Agendamento.slot_inicio < fim,
               Agendamento.passo.notin_([PASSO_FALHOU, PASSO_INICIADO]))
        .group_by(Agendamento.sales_rep_email)
    )
    carga = {(linha[0] or "").lower(): linha[1] for linha in res.all()}
    ordenadas = sorted(enumerate(candidatas),
                       key=lambda par: (carga.get(par[1].email.lower(), 0), par[0]))
    return [c for _, c in ordenadas]


async def agendar(db: AsyncSession, *, nome: str, email: str | None, telefone: str,
                  slot_id: str, origem: str | None = None, lead_id: int | None = None,
                  extras: dict[str, str] | None = None,
                  origem_ip: str | None = None) -> Resultado:
    """Caminho completo da LP.

    Com `lead_id`, agenda um lead que JÁ existe e pula o `LeadsAdd` — é o fluxo de duas
    etapas descrito no cabeçalho. Sem ele, cria o lead como sempre fez.

    Levanta SlotInvalido / SlotIndisponivel / LeadNaoEncontrado / AgendamentoFalhou /
    origens.OrigemInvalida.
    """
    # O slot é resolvido contra a UNIÃO das grades: com várias consultoras, um horário é
    # válido se ao menos uma o oferece. Continua sendo validação de entrada — um id que não
    # esteja em grade nenhuma é recusado antes de qualquer escrita.
    slot = None
    candidatas = []
    for c in equipe_mod.consultoras():
        achado = c.grade.slot_por_id(slot_id)
        if achado is not None:
            slot = achado
            candidatas.append(c)
    if slot is None or not candidatas:
        raise SlotInvalido(f"slot fora da grade ou vencido: {slot_id!r}")

    # Resolvido ANTES de qualquer escrita: uma origem inválida não pode chegar a criar box e
    # depois falhar, deixando o horário bloqueado até a faxina passar.
    sub_source = origens.resolver(origem)

    # Mesma razão para validar o lead externo AQUI e não no passo 2: um `leadId` inválido
    # depois do BoxesAdd deixaria o horário travado na agenda da consultora até a faxina
    # passar, e o visitante veria um erro que não tem nada a ver com disponibilidade.
    #
    # A falha de REDE nesta consulta é tratada como indisponibilidade, não como "não
    # existe". Confundir as duas agendaria por cima de um lead inexistente — ou, pior,
    # recusaria um lead válido porque a Exact piscou.
    lead_externo = lead_id is not None
    if lead_externo:
        try:
            achado = await client.buscar_lead_por_id(lead_id)
        except client.ExactErro as e:
            print(f"❌ agendamento: não consegui verificar o lead {lead_id} — "
                  f"{type(e).__name__}: {e}")
            raise AgendamentoFalhou(f"verificação do lead {lead_id} falhou: {e}") from e
        if achado is None:
            print(f"⚠️ agendamento: leadId {lead_id} não existe na Exact (ip {origem_ip})")
            raise LeadNaoEncontrado(f"lead {lead_id} não encontrado")

    anterior = await _duplo_clique(db, telefone)
    if anterior is not None:
        # Devolve o agendamento que já deu certo em vez de criar um segundo. O visitante que
        # clicou duas vezes vê a mesma confirmação, que é o que ele espera.
        print(f"🔁 agendamento: duplo clique de {telefone}, devolvendo #{anterior.id}")
        return Resultado(agendamento_id=anterior.id, lead_id=anterior.lead_id,
                         box_id=anterior.box_id, slot=slot, meeting_id=anterior.meeting_id,
                         consultora_email=anterior.sales_rep_email or "",
                         consultora_nome=equipe_mod.nome_de(anterior.sales_rep_email or ""))

    agora = agora_sp()
    ag = Agendamento(
        nome=nome, email=email, telefone=telefone,
        slot_inicio=slot.inicio, slot_fim=slot.fim,
        # Fica com a primeira candidata e é REESCRITO quando o BoxesAdd define a
        # vencedora. A coluna nunca é NULL, então uma tentativa que morra no passo 1 ainda
        # diz a quem ela era destinada.
        sales_rep_email=candidatas[0].email, sub_source=sub_source,
        lead_id=lead_id, lead_externo=lead_externo,
        # Guardado mesmo quando o lead é externo e o LeadsAdd não vai rodar: o que a pessoa
        # respondeu NESTA submissão é dado nosso, e some se depender só do CRM.
        extras=extras or None,
        passo=PASSO_INICIADO, origem_ip=origem_ip,
        created_at=agora, updated_at=agora,
    )
    db.add(ag)
    await db.commit()

    # ---- passo 1: o lock, tentando cada consultora ----------------------------------
    # `Boxes are occupied` numa consultora NÃO significa que o horário morreu — significa
    # que morreu para ela. Só depois que todas recusarem é que o visitante vê 409.
    ordem = await escolher_consultora(db, candidatas, slot.inicio.date())
    box_id = None
    consultora = None
    ultimo_ocupado = None
    for tentativa in ordem:
        try:
            box_id = await client.criar_box(
                inicio=slot.inicio, fim=slot.fim,
                sales_rep_email=tentativa.email,
                type_meeting=tentativa.grade.type_meeting,
                description=f"Agendamento LP — {nome}",
            )
            consultora = tentativa
            break
        except client.SlotOcupado as e:
            ultimo_ocupado = e
            print(f"↪️ agendamento #{ag.id}: {tentativa.nome_exibicao} ocupada em "
                  f"{slot.id} — tentando a próxima")
            continue
        except client.ExactErro as e:
            # Erro que não é disputa de horário (SDR not found, rede, 5xx) para o fluxo:
            # insistir na próxima consultora só transformaria um erro de configuração em
            # vários boxes criados por engano.
            await _marcar(db, ag, PASSO_FALHOU, erro=str(e))
            print(f"❌ agendamento #{ag.id}: BoxesAdd falhou em {tentativa.email} — "
                  f"{type(e).__name__}: {e}")
            raise AgendamentoFalhou(str(e)) from e

    if consultora is None:
        msg = str(ultimo_ocupado) if ultimo_ocupado else "nenhuma consultora disponível"
        await _marcar(db, ag, PASSO_FALHOU, erro=msg)
        disponibilidade.invalidar_cache()
        print(f"⚠️ agendamento #{ag.id}: slot {slot.id} ocupado nas "
              f"{len(ordem)} consultora(s) — {msg}")
        raise SlotIndisponivel(msg) from ultimo_ocupado

    ag.box_id = box_id
    ag.sales_rep_email = consultora.email
    await _marcar(db, ag, PASSO_BOX_CRIADO)
    print(f"📦 agendamento #{ag.id}: box {box_id} criado para {slot.id} "
          f"com {consultora.nome_exibicao} <{consultora.email}>")

    # ---- passo 2: o lead ------------------------------------------------------------
    # Com lead externo não há chamada nenhuma aqui: o lead já foi verificado lá em cima, e
    # criar outro é exatamente o bug que o `leadId` existe para evitar. O passo é marcado
    # do mesmo jeito para a faxina enxergar o mesmo desenho de estado nos dois fluxos.
    if lead_externo:
        await _marcar(db, ag, PASSO_LEAD_CRIADO)
        # Os extras desta submissão ficam só na NOSSA tabela. O `description` do lead foi
        # escrito no POST /lead e não há LeadsUpdate neste fluxo — reescrevê-lo exigiria
        # outra chamada, e sobrescrever o que o formulário do index já gravou seria pior
        # que não escrever. Na prática o index é quem pergunta, então o dado já está lá.
        aviso = " (extras só na tabela local)" if extras else ""
        print(f"👤 agendamento #{ag.id}: lead {lead_id} JÁ EXISTIA (veio no corpo) — "
              f"LeadsAdd pulado, subSource {sub_source} não reaplicado{aviso}")
    else:
        try:
            lead_id = await client.criar_lead(
                nome=nome, telefone=telefone,
                source=SOURCE, sub_source=sub_source, funnel_id=FUNIL_POS_GRADUACAO,
                description=extras_mod.montar_descricao(email, extras),
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
            stage_name=STAGE_AGENDADOS, sales_rep_email=consultora.email,
        )
    except client.ExactErro as e:
        # O box sai; o LEAD FICA em Entrada, com telefone e origem. Ver cabeçalho.
        #
        # Vale nos DOIS fluxos, por razões diferentes: no lead nosso é decisão de produto
        # (o contato vale mais que o horário perdido); no lead externo é que ele não nos
        # pertence — foi criado por outra requisição e não é nosso para desfazer. Em
        # nenhum dos dois se chama LeadsDelete.
        await _compensar_box(db, ag, motivo="scheduleAdd falhou")
        await _marcar(db, ag, PASSO_FALHOU, erro=str(e))
        posse = "externo, não é nosso" if lead_externo else "nosso, mantido de propósito"
        print(f"❌ agendamento #{ag.id}: scheduleAdd falhou — {type(e).__name__}: {e}. "
              f"Lead {lead_id} PRESERVADO ({posse}).")
        raise AgendamentoFalhou(str(e), lead_id=lead_id) from e

    await _marcar(db, ag, PASSO_AGENDADO)
    disponibilidade.invalidar_cache()
    print(f"✅ agendamento #{ag.id}: lead {lead_id} agendado em {slot.id} "
          f"(box {box_id}, {consultora.nome_exibicao} <{consultora.email}>)")

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
                     slot=slot, meeting_id=ag.meeting_id,
                     consultora_email=consultora.email,
                     consultora_nome=consultora.nome_exibicao)


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
                                     extras: dict[str, str] | None = None,
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
        # Não há consultora escolhida: este caminho não cria box nem reunião. A coluna é
        # NOT NULL, então fica a primeira em rotação, e `passo` nunca chega a `agendado` —
        # é o que distingue esta linha de um agendamento de verdade num relatório.
        sales_rep_email=equipe_mod.consultoras()[0].email, sub_source=sub_source,
        extras=extras or None,
        passo=PASSO_INICIADO, origem_ip=origem_ip,
        created_at=agora, updated_at=agora,
    )
    db.add(ag)
    await db.commit()

    try:
        lead_id = await client.criar_lead(
            nome=nome, telefone=telefone,
            source=SOURCE, sub_source=sub_source, funnel_id=FUNIL_POS_GRADUACAO,
            description=extras_mod.montar_descricao(email, extras),
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
