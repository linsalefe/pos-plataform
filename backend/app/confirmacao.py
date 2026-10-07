"""Régua de CONFIRMAÇÃO de reunião (Fluxo A da spec da Isa, 28/09; Bloco 1, 07/10/2026).

==========================================================================================
O QUE É
==========================================================================================
Toda reunião `Vigente` de `reuniao_status` (site, agente ou SDR na Exact) ganha a régua da
spec: confirmação imediata com botões, ementa +4h e benefício +8h (só se a reunião está a mais
de 12h), pedido de confirmação, último aviso, corte, e o T-30 só para quem confirmou. O lead
responde por botão ou por texto da lista fechada; o resto vai para humano e pausa a régua.

SEM LLM NO CONTROLE DE FLUXO. Cada transição é um botão com payload ou um texto da lista
fechada (`TEXTOS_CONFIRMACAO`). Tudo é agendamento determinístico em `nat_scheduled_actions`,
um kind por mensagem (`models.KINDS_CONFIRMACAO`), payload `{"meeting_id": ...}`. Todo handler
RELÊ `reuniao_status`: nunca confia no payload.

==========================================================================================
POR QUE EXISTE (RECON_CONFIRMACAO_NOSHOW_20261007)
==========================================================================================
Das reuniões marcadas pelo Hub com horário já passado, só 17% constam `Concluido` na Exact
(26 de 153); 75% `Cancelada` (§2). A única mensagem pós-agendamento era o T-30, que saía para
todo mundo, inclusive para reunião cancelada (§0).

==========================================================================================
GATES
==========================================================================================
`CONFIRMACAO_ENABLED` (desligado = nada muda, o T-30 segue como era) e
`CONFIRMACAO_SOMENTE_TELEFONES` (allowlist pela chave tolerante; vazia = todos). Os dois lidos a
cada chamada, sem cache, padrão de `follow_estagio`.

==========================================================================================
O QUE NÃO FAZ
==========================================================================================
Não cancela reunião na Exact (impossível pela API, RECON §5.1): o corte anota, avisa a
consultora e o SDR, e para a régua. Não mostra horários no "Preciso remarcar" (Bloco 3). Não
faz a régua de no-show D0+1h em diante (Bloco 2): aqui só o D0, que é a mensagem do corte, e o
tratamento dos dois botões dela.
"""
import json
import os
import re
import string
import unicodedata
from datetime import datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import nat_copy
from app.models import (ACAO_EXECUTADO, ACAO_PENDENTE, EXACT_TYPE_VIGENTE,
                        KIND_CONFIRM_A_BENEFICIO, KIND_CONFIRM_A_CORTE, KIND_CONFIRM_A_EMENTA,
                        KIND_CONFIRM_A_IMEDIATA, KIND_CONFIRM_A_PEDIDO,
                        KIND_CONFIRM_A_ULTIMO_AVISO, KIND_LEMBRETE_REUNIAO, KINDS_CONFIRMACAO,
                        TIPO_NOTIF_CONFIRMACAO, TIPO_NOTIF_LIGAR_AGORA, Contact, Message,
                        NatScheduledAction, Notification, ReuniaoStatus)
from app.nat_guard import (GESTOR_USER_ID, _agora_sp, dentro_janela_envio,
                           proxima_janela_envio)
from app.nat_scheduler import AcaoAdiada, AcaoIgnorada, registrar_handler
from app.telefone import chave_telefone, variantes_wa_id

# ==========================================================================================
# GATES
# ==========================================================================================

def flag_ligada() -> bool:
    """`CONFIRMACAO_ENABLED`, sem cache. `true`/`1`/`sim`/`yes`; o resto é DESLIGADO."""
    return (os.getenv("CONFIRMACAO_ENABLED", "") or "").strip().lower() in (
        "true", "1", "sim", "yes")


def allowlist() -> frozenset[str]:
    """`CONFIRMACAO_SOMENTE_TELEFONES` como chaves tolerantes. Vazia = todos entram.

    Mesma regra de `follow_estagio.allowlist`: qualquer grafia do número vira a mesma chave, e
    chave ilegível é descartada (senão `''` casaria com todo telefone ilegível).
    """
    cru = os.getenv("CONFIRMACAO_SOMENTE_TELEFONES", "") or ""
    return frozenset(c for c in (chave_telefone(p) for p in cru.split(",")) if c)


def telefone_permitido(telefone: str | None) -> bool:
    lista = allowlist()
    return not lista or chave_telefone(telefone) in lista


# ==========================================================================================
# O CALENDÁRIO DA RÉGUA — função pura (é o que o checkpoint e o teste conferem)
# ==========================================================================================
# Spec, "Linha do tempo" e "Exceções" (pág. 6). Hora de parede de SP; manhã = antes das 12h.
DIAS_SEMANA = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira",
               "sábado", "domingo")

EMENTA_APOS = timedelta(hours=4)
BENEFICIO_APOS = timedelta(hours=8)
# Ementa e benefício só para reunião "em mais de 12h" (spec). MEDIDO: 84% das reuniões do
# Hub (117 de 140) são marcadas com mais de 12h de antecedência (RECON §2).
MIN_PARA_EMENTA = timedelta(hours=12)
# Menos de 4h até a reunião: só a confirmação imediata, sem corte (spec, "Exceções"). MEDIDO:
# 8 de 140 (5,7%) (RECON §2).
MIN_PARA_CORTE = timedelta(hours=4)
CORTE_TARDE_ANTES = timedelta(hours=4)
ULTIMO_AVISO_TARDE_ANTES_DO_CORTE = timedelta(hours=1)
ANTECEDENCIA_T30 = timedelta(minutes=30)
ATRASO_POR_TETO = timedelta(minutes=10)


def manha(slot: datetime) -> bool:
    return slot.hour < 12


def corte_de(slot: datetime) -> datetime:
    """Manhã: 9h do dia. Tarde: 4h antes."""
    if manha(slot):
        return slot.replace(hour=9, minute=0, second=0, microsecond=0)
    return slot - CORTE_TARDE_ANTES


def _as(dia: datetime, hora: int) -> datetime:
    return dia.replace(hour=hora, minute=0, second=0, microsecond=0)


def calcular_regua(slot: datetime, agora: datetime) -> tuple[list[tuple[str, datetime]],
                                                             list[tuple[str, str]]]:
    """(ações a criar `[(kind, run_at)]`, descartadas `[(kind, motivo)]`).

    Regras gerais (decisão 5 da sprint): ação com `run_at` já passado não é criada; ação com
    `run_at >= corte` não é criada. Com menos de 4h até a reunião, só a imediata.

    A exceção "agendou depois das 17h para a manhã seguinte: pula o pedido da véspera" sai
    SOZINHA destas regras: o pedido da véspera às 17h já passou.
    """
    criar: list[tuple[str, datetime]] = [(KIND_CONFIRM_A_IMEDIATA, agora)]
    fora: list[tuple[str, str]] = []
    if slot - agora < MIN_PARA_CORTE:
        for k in (KIND_CONFIRM_A_EMENTA, KIND_CONFIRM_A_BENEFICIO, KIND_CONFIRM_A_PEDIDO,
                  KIND_CONFIRM_A_ULTIMO_AVISO, KIND_CONFIRM_A_CORTE):
            fora.append((k, "faltam menos de 4h para a reunião: só a confirmação imediata"))
        return criar, fora

    corte = corte_de(slot)
    candidatas: list[tuple[str, datetime]] = []
    if slot - agora > MIN_PARA_EMENTA:
        candidatas += [(KIND_CONFIRM_A_EMENTA, agora + EMENTA_APOS),
                       (KIND_CONFIRM_A_BENEFICIO, agora + BENEFICIO_APOS)]
    else:
        fora += [(KIND_CONFIRM_A_EMENTA, "reunião em 12h ou menos"),
                 (KIND_CONFIRM_A_BENEFICIO, "reunião em 12h ou menos")]
    if manha(slot):
        pedido = _as(slot - timedelta(days=1), 17)
        ultimo = _as(slot, 8)
    else:
        pedido = _as(slot, 8)
        ultimo = corte - ULTIMO_AVISO_TARDE_ANTES_DO_CORTE
    candidatas += [(KIND_CONFIRM_A_PEDIDO, pedido), (KIND_CONFIRM_A_ULTIMO_AVISO, ultimo)]

    validas: list[tuple[str, datetime]] = []
    for kind, quando in candidatas:
        if quando <= agora:
            fora.append((kind, f"{quando:%d/%m %H:%M} já passou"))
        elif quando >= corte:
            fora.append((kind, f"{quando:%d/%m %H:%M} não é antes do corte {corte:%d/%m %H:%M}"))
        else:
            validas.append((kind, quando))

    # COLISÃO COM O PEDIDO (Álefe, checkpoint de 07/10). Ementa e benefício que, depois da
    # janela de silêncio, sairiam no MESMO horário ou depois da primeira mensagem de
    # confirmação (o pedido, ou o último aviso quando não há pedido) não são criados. Medido
    # no checkpoint: quem agenda às 19h para as 10h do dia seguinte receberia ementa, benefício
    # e último aviso juntos às 08:00, e o corte às 09:00.
    confirmacoes = [q for k, q in validas
                    if k in (KIND_CONFIRM_A_PEDIDO, KIND_CONFIRM_A_ULTIMO_AVISO)]
    primeira = min(confirmacoes) if confirmacoes else corte
    for kind, quando in validas:
        if kind in (KIND_CONFIRM_A_EMENTA, KIND_CONFIRM_A_BENEFICIO):
            sai = proxima_janela_envio(quando)
            if sai >= primeira:
                fora.append((kind, f"sairia {sai:%d/%m %H:%M}, junto ou depois da primeira "
                                   f"mensagem de confirmação ({primeira:%d/%m %H:%M})"))
                continue
        criar.append((kind, quando))
    criar.append((KIND_CONFIRM_A_CORTE, corte))
    return criar, fora


def dia_extenso(slot: datetime) -> str:
    """'quinta-feira, 09/10'."""
    return f"{DIAS_SEMANA[slot.weekday()]}, {slot:%d/%m}"


def hoje_ou_amanha(slot: datetime, agora: datetime) -> str:
    if slot.date() == agora.date():
        return "hoje"
    if slot.date() == (agora + timedelta(days=1)).date():
        return "amanhã"
    return dia_extenso(slot)


# ==========================================================================================
# O QUE CONTA COMO CONFIRMAÇÃO EM TEXTO — lista FECHADA (Álefe, 07/10)
# ==========================================================================================
# A mensagem INTEIRA, normalizada (sem acento, sem pontuação, minúscula). "ok, mas posso
# mudar?" não é confirmação: é dúvida, e vai para humano. Fora da lista, nunca confirma.
TEXTOS_CONFIRMACAO = frozenset({"ok", "👍", "confirmo", "confirmado", "sim", "certo",
                                "combinado", "estarei la", "pode ser", "isso"})
_TONS_DE_PELE = re.compile("[\U0001F3FB-\U0001F3FF️]")


def normalizar(texto: str | None) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").strip().lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _TONS_DE_PELE.sub("", t)
    t = t.translate(str.maketrans({c: " " for c in string.punctuation}))
    return " ".join(t.split())


def e_confirmacao(texto: str | None) -> bool:
    return normalizar(texto) in TEXTOS_CONFIRMACAO


# ==========================================================================================
# LEITURAS
# ==========================================================================================

async def _reuniao(meeting_id, db: AsyncSession) -> ReuniaoStatus | None:
    if not meeting_id:
        return None
    return (await db.execute(select(ReuniaoStatus).where(
        ReuniaoStatus.meeting_id == int(meeting_id)))).scalar_one_or_none()


async def _acoes(meeting_id: int, db: AsyncSession, *, kinds=None, status=None):
    q = select(NatScheduledAction).where(
        text("(nat_scheduled_actions.payload::json->>'meeting_id') = :mid")
        .bindparams(mid=str(meeting_id)))
    if kinds:
        q = q.where(NatScheduledAction.kind.in_(kinds))
    if status:
        q = q.where(NatScheduledAction.status == status)
    return list((await db.execute(q)).scalars())


async def _wa_id(reuniao: ReuniaoStatus, db: AsyncSession) -> str | None:
    """O wa_id para onde a régua vai, criando o contato se não existir.

    Mesmo caminho do T-30 (`qualificacao_fluxo._contato_ou_criar`, 18/09): a reunião marcada na
    Exact pode ser de alguém que nunca falou com o Hub. Se o contato já existe na outra grafia
    do telefone, a régua segue nela (regra S5-2).
    """
    from app.exact_spotter import format_phone
    from app.qualificacao_fluxo import _contato_ou_criar
    wa = format_phone(reuniao.telefone_bruto or "")
    if not wa:
        return None
    contato = await _contato_ou_criar(wa, lead_id=reuniao.lead_id, db=db)
    return contato.wa_id if contato is not None else None


async def _nome(reuniao: ReuniaoStatus, wa_id: str | None, db: AsyncSession) -> str:
    from app.nomes import primeiro_nome
    nome = primeiro_nome(reuniao.nome or "").strip()
    if nome or not wa_id:
        return nome
    c = (await db.execute(select(Contact).where(
        Contact.wa_id.in_(variantes_wa_id(wa_id) or (wa_id,))))).scalars().first()
    return primeiro_nome((c.name if c else "") or "").strip()


async def _sub_source(reuniao: ReuniaoStatus, db: AsyncSession) -> str:
    from app.models import Agendamento, ExactLead
    if reuniao.lead_id:
        sub = (await db.execute(select(ExactLead.sub_source).where(
            ExactLead.exact_id == reuniao.lead_id))).scalar_one_or_none()
        if sub:
            return sub
    if reuniao.agendamento_id:
        sub = (await db.execute(select(Agendamento.sub_source).where(
            Agendamento.id == reuniao.agendamento_id))).scalar_one_or_none()
        if sub:
            return sub
    return ""


async def _pos(reuniao: ReuniaoStatus, db: AsyncSession) -> str:
    from app.course_names import resolve_course_name
    sub = await _sub_source(reuniao, db)
    return (await resolve_course_name(sub, db)) if sub else ""


def _consultora(reuniao: ReuniaoStatus):
    from app.agendamento import consultoras as equipe
    return equipe.por_email(reuniao.sales_rep_email or "")


_EMENTAS: dict | None = None


def ementa_de(sub_source: str) -> str | None:
    """Sufixo do Drive da ementa (`backend/ementas.json`), sem caixa. None = não cadastrada."""
    global _EMENTAS
    if _EMENTAS is None:
        caminho = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ementas.json")
        try:
            with open(caminho, encoding="utf-8") as fh:
                bruto = json.load(fh)
            _EMENTAS = {k.lower(): v for k, v in bruto.items() if not k.startswith("_")}
        except (OSError, ValueError) as e:
            print(f"⚠️ confirmacao: ementas.json ilegível ({e}) — nenhuma ementa será enviada")
            _EMENTAS = {}
    return _EMENTAS.get((sub_source or "").strip().lower())


async def _dono(wa_id: str, db: AsyncSession) -> int | None:
    linha = (await db.execute(select(Contact.assigned_to).where(
        Contact.wa_id.in_(variantes_wa_id(wa_id) or (wa_id,)),
        Contact.assigned_to.isnot(None)))).first()
    return linha[0] if linha else None


# ==========================================================================================
# EFEITOS: nota na Exact e notificação no Hub
# ==========================================================================================

async def _nota(reuniao: ReuniaoStatus, texto: str) -> None:
    """Nota `[NAT]` na timeline do lead. O único status que o Hub consegue gravar na Exact
    (estágio intra-funil não se move pela API, RECON §5.5). Best-effort, nunca levanta."""
    from app.exact_notes import registrar_observacao
    await registrar_observacao(reuniao.lead_id, texto)


async def _notificar(reuniao: ReuniaoStatus, wa_id: str, tipo: str, titulo: str, corpo: str,
                     db: AsyncSession, *, consultora: bool = False, todas: bool = False) -> None:
    """Notifica o dono do contato e, quando pedido, a consultora da reunião (ou as duas).

    Sem dono e sem consultora mapeada, vai para a gestão (`GESTOR_USER_ID`): um aviso que não
    chega a ninguém é o silêncio que esta régua existe para evitar.
    """
    from app.agendamento import consultoras as equipe
    alvos: set[int] = set()
    dono = await _dono(wa_id, db)
    if dono:
        alvos.add(dono)
    if todas:
        alvos |= {c.user_id_hub for c in equipe.consultoras() if c.user_id_hub}
    elif consultora:
        c = _consultora(reuniao)
        if c is not None and c.user_id_hub:
            alvos.add(c.user_id_hub)
    if not alvos:
        alvos.add(GESTOR_USER_ID)
    for uid in alvos:
        db.add(Notification(user_id=uid, contact_wa_id=wa_id, type=tipo,
                            ref=str(reuniao.meeting_id), title=titulo[:255], body=corpo))


# ==========================================================================================
# ARMAR E CANCELAR
# ==========================================================================================

async def armar(reuniao: ReuniaoStatus, db: AsyncSession, *,
                agora: datetime | None = None) -> int:
    """Cria a régua desta reunião. Idempotente. Devolve quantas ações inseriu.

    Chamada de dois lugares, com este único código: `agendar.py:_gatilho_do_agente` (site e
    agente, na hora) e `reuniao_sync` (reunião nova no espelho: a SDR na Exact, e qualquer
    reunião do Hub que o primeiro caminho tenha perdido).
    """
    from app.nat_scheduler import agendar
    agora = agora or _agora_sp()
    mid = reuniao.meeting_id

    def sai(motivo: str) -> int:
        print(f"↩️ confirmacao: régua da reunião {mid} não armada — {motivo}")
        return 0

    if not flag_ligada():
        return 0                                  # silencioso: é o estado normal desligado
    if not telefone_permitido(reuniao.telefone_bruto):
        return 0                                  # idem: fora da allowlist do teste
    if reuniao.exact_type != EXACT_TYPE_VIGENTE:
        return sai(f"está {reuniao.exact_type}")
    if reuniao.slot_inicio <= agora:
        return sai("já começou")
    if not reuniao.telefone_chave:
        return sai("sem telefone legível")
    if _consultora(reuniao) is None:
        # Só reunião de consultora da PÓS (consultoras.json). MEDIDO (RECON §5.3): há reuniões
        # com `sdr@` como rep e 2 da Marina, que é do intercâmbio. Mandar "a consultora sdr" ou
        # uma confirmação de pós a quem marcou intercâmbio é pior que não mandar.
        return sai(f"consultora {reuniao.sales_rep_email!r} fora de consultoras.json")
    if await _acoes(mid, db, kinds=(KIND_CONFIRM_A_IMEDIATA,)):
        return 0                                  # já armada (qualquer status): idempotente

    wa = await _wa_id(reuniao, db)
    if not wa:
        return sai("não foi possível resolver nem criar o contato")

    criar, fora = calcular_regua(reuniao.slot_inicio, agora)
    for kind, quando in criar:
        payload = {"meeting_id": mid}
        if kind == KIND_CONFIRM_A_IMEDIATA:
            payload["regua_armada_em"] = agora.isoformat(timespec="seconds")
        anterior = (await db.execute(select(func.count()).select_from(NatScheduledAction).where(
            NatScheduledAction.kind == kind, NatScheduledAction.contact_wa_id == wa,
            NatScheduledAction.status == ACAO_PENDENTE))).scalar()
        if anterior:
            # Duas reuniões vigentes da mesma pessoa: a mais nova manda (decisão 2). O
            # `agendar` cancela o pendente do par; aqui só fica registrado no log.
            print(f"🔁 confirmacao: {kind} pendente de outra reunião de {wa} substituído "
                  f"pela reunião {mid}")
        await agendar(kind, wa, quando, payload, db)
    for kind, motivo in fora:
        print(f"⏭️ confirmacao: reunião {mid} sem {kind} — {motivo}")
    print(f"📅 confirmacao: régua armada para a reunião {mid} ({wa}, "
          f"{reuniao.slot_inicio:%d/%m %H:%M}): {len(criar)} ação(ões)")
    return len(criar)


async def _cancelar_kinds(wa_id: str, kinds, motivo: str, db: AsyncSession) -> int:
    """Por CONTATO, todas as reuniões. Só para quando um humano assume a pessoa inteira."""
    from app.nat_scheduler import cancelar
    total = 0
    for kind in kinds:
        for v in dict.fromkeys(variantes_wa_id(wa_id) or (wa_id,)):
            total += await cancelar(kind, v, db, motivo=motivo)
    return total


async def _cancelar_da_reuniao(r: ReuniaoStatus, kinds, motivo: str, db: AsyncSession) -> int:
    """Cancela os pendentes DESTA reunião, e só dela. Nunca por contato.

    POR QUE NÃO `nat_scheduler.cancelar(kind, wa_id)`: remarcar na Exact é reunião NOVA e a
    antiga vira Cancelada (RECON §5.4). Se a régua da nova já estiver armada quando o sync ver
    a antiga cancelar, cancelar por contato mataria a régua da reunião que vale. O vínculo é o
    `meeting_id` do payload; o T-30 do Hub carrega `agendamento_id`, e casa por ele.
    """
    from app.models import ACAO_CANCELADO
    cond = "(nat_scheduled_actions.payload::json->>'meeting_id') = :mid"
    params = {"mid": str(r.meeting_id)}
    if r.agendamento_id and KIND_LEMBRETE_REUNIAO in kinds:
        cond = (f"({cond} OR (nat_scheduled_actions.kind = '{KIND_LEMBRETE_REUNIAO}' AND "
                "(nat_scheduled_actions.payload::json->>'agendamento_id') = :ag))")
        params["ag"] = str(r.agendamento_id)
    res = await db.execute(
        update(NatScheduledAction)
        .where(NatScheduledAction.status == ACAO_PENDENTE,
               NatScheduledAction.kind.in_(list(kinds)),
               text(cond).bindparams(**params))
        .values(status=ACAO_CANCELADO, motivo=motivo, processed_at=_agora_sp())
        .execution_options(synchronize_session=False))
    return res.rowcount or 0


async def cancelar_regua(wa_id: str, reuniao: ReuniaoStatus | None, motivo: str,
                         db: AsyncSession, *, manter_corte: bool = False,
                         manter_t30: bool = False, encerrar: bool = True) -> int:
    """Cancela as ações pendentes da régua desta pessoa, gravando o motivo. Nunca levanta.

    Por CONTATO (o índice único já garante uma régua por pessoa), com `motivo` no
    `nat_scheduler.cancelar`. `encerrar` grava `regua_encerrada_em/motivo` na reunião.
    """
    kinds = [k for k in KINDS_CONFIRMACAO if not (manter_corte and k == KIND_CONFIRM_A_CORTE)]
    if not manter_t30:
        kinds.append(KIND_LEMBRETE_REUNIAO)
    try:
        # Com a reunião: escopo da reunião. Sem ela (SDR assumiu e a pessoa não tem reunião
        # viva no espelho): por contato.
        n = (await _cancelar_da_reuniao(reuniao, kinds, motivo, db) if reuniao is not None
             else await _cancelar_kinds(wa_id, kinds, motivo, db))
        if encerrar and reuniao is not None and reuniao.regua_encerrada_em is None:
            reuniao.regua_encerrada_em = _agora_sp()
            reuniao.regua_encerrada_motivo = motivo[:60]
        if n:
            print(f"🚫 confirmacao: {n} ação(ões) da régua de {wa_id} cancelada(s) — {motivo}")
        return n
    except Exception as e:
        print(f"⚠️ confirmacao: régua de {wa_id} não cancelada ({motivo}): "
              f"{type(e).__name__}: {e}")
        return 0


async def reunioes_vivas_da_pessoa(wa_id: str, db: AsyncSession) -> list[ReuniaoStatus]:
    chave = chave_telefone(wa_id)
    if not chave:
        return []
    return list((await db.execute(select(ReuniaoStatus).where(
        ReuniaoStatus.telefone_chave == chave,
        ReuniaoStatus.exact_type == EXACT_TYPE_VIGENTE,
        ReuniaoStatus.slot_inicio > _agora_sp()))).scalars())


async def cancelar_regua_da_pessoa(wa_id: str, motivo: str, db: AsyncSession) -> int:
    """O SDR assumiu: cancela TUDO (corte incluído, decisão 10) de toda reunião viva da pessoa.

    Roda mesmo com a flag desligada: cancelar é sempre seguro, e ligar/desligar não pode deixar
    régua órfã correndo depois que um humano entrou.
    """
    reunioes = await reunioes_vivas_da_pessoa(wa_id, db)
    n = 0
    for r in reunioes:
        n += await cancelar_regua(wa_id, r, motivo, db)
    # E por contato, por cima: o humano assumiu a PESSOA, e uma ação de reunião que o espelho
    # ainda não vê (ou de outra grafia) não pode sobrar.
    n += await _cancelar_kinds(wa_id, list(KINDS_CONFIRMACAO) + [KIND_LEMBRETE_REUNIAO],
                               motivo, db)
    return n


# ==========================================================================================
# OS GUARDS DE ENVIO (assinatura `(contact, db) -> (pode, motivo)` do `enviar_nat`)
# ==========================================================================================

def _regua_parada(reuniao: ReuniaoStatus, kind: str) -> str | None:
    """Motivo pelo qual a régua não deve mandar `kind`, ou None.

    A PAUSA POR HUMANO NÃO PARA O CORTE NEM O T-30 (spec: "o corte continua valendo").
    """
    if reuniao.regua_encerrada_em is None:
        return None
    if reuniao.regua_encerrada_motivo == "humano" and kind in (KIND_CONFIRM_A_CORTE,
                                                               KIND_LEMBRETE_REUNIAO):
        return None
    return f"régua encerrada: {reuniao.regua_encerrada_motivo}"


def guard_de_regua(meeting_id: int, kind: str, *, exigir_viva: bool = True):
    async def _guard(contact, db: AsyncSession) -> tuple[bool, str]:
        from app import qualificacao_guard as qg
        from app.higiene_disparo import _opt_out_meta

        def bloqueia(motivo: str) -> tuple[bool, str]:
            print(f"🔒 Régua não enviou {kind} ({getattr(contact, 'wa_id', '?')}): {motivo}")
            return False, motivo
        try:
            r = await _reuniao(meeting_id, db)
            if r is None or r.exact_type != EXACT_TYPE_VIGENTE:
                return bloqueia(f"reunião {meeting_id} não está Vigente")
            if r.slot_inicio <= _agora_sp():
                return bloqueia(f"reunião {meeting_id} já começou")
            if exigir_viva:
                parada = _regua_parada(r, kind)
                if parada:
                    return bloqueia(parada)
            if await _opt_out_meta(variantes_wa_id(contact.wa_id) or (contact.wa_id,), db):
                return bloqueia("opt-out registrado pela Meta (131050)")
            if await _acoes(meeting_id, db, kinds=(kind,), status=ACAO_EXECUTADO):
                return bloqueia(f"{kind} já enviado para a reunião {meeting_id}")
            config = await qg._carregar_config(db)
            if config is not None:
                ok, motivo = await qg._teto_ok(config, db)
                if not ok:
                    return bloqueia(motivo)
            return True, "ok"
        except Exception as e:
            return bloqueia(f"erro inesperado no guard da régua: {type(e).__name__}: {e}")
    return _guard


async def _guard_resposta(contact, db: AsyncSession) -> tuple[bool, str]:
    """Resposta fixa a um clique/texto: o lead acabou de escrever. Só o opt-out bloqueia."""
    from app.higiene_disparo import _opt_out_meta
    try:
        if await _opt_out_meta(variantes_wa_id(contact.wa_id) or (contact.wa_id,), db):
            return False, "opt-out registrado pela Meta (131050)"
        return True, "ok"
    except Exception as e:
        return False, f"erro inesperado no guard da resposta: {type(e).__name__}: {e}"


ETAPA_RESPOSTA = "confirm_a_resposta"


async def _responder(wa_id: str, texto: str, db: AsyncSession) -> bool:
    from app.nat_sender import enviar_nat
    ok, motivo = await enviar_nat(wa_id, ETAPA_RESPOSTA, db, guard=_guard_resposta,
                                  corpo_livre=texto)
    if not ok:
        print(f"⚠️ confirmacao: resposta fixa NÃO saiu para {wa_id} ({motivo})")
    return ok


# ==========================================================================================
# HANDLERS DE ENVIO — a mesma espinha para os seis
# ==========================================================================================

async def _espinha(acao: dict, db: AsyncSession, kind: str):
    """Relê tudo e decide se esta ação pode rodar AGORA. Devolve (reuniao, wa_id, agora)."""
    from app.nat_scheduler import payload_de
    agora = acao.get("agora") or _agora_sp()
    wa = acao["contact_wa_id"]
    mid = payload_de(acao).get("meeting_id")
    r = await _reuniao(mid, db)
    if r is None:
        raise AcaoIgnorada(f"reunião {mid!r} não existe em reuniao_status")
    if not flag_ligada():
        raise AcaoIgnorada("CONFIRMACAO_ENABLED desligado")
    if not telefone_permitido(r.telefone_bruto):
        raise AcaoIgnorada("telefone fora de CONFIRMACAO_SOMENTE_TELEFONES")
    if r.exact_type != EXACT_TYPE_VIGENTE:
        raise AcaoIgnorada(f"reunião {r.meeting_id} está {r.exact_type} na Exact")
    if r.slot_inicio <= agora:
        raise AcaoIgnorada(f"reunião {r.meeting_id} já começou ({r.slot_inicio:%d/%m %H:%M})")
    parada = _regua_parada(r, kind)
    if parada:
        raise AcaoIgnorada(parada)
    if kind in (KIND_CONFIRM_A_PEDIDO, KIND_CONFIRM_A_ULTIMO_AVISO, KIND_CONFIRM_A_CORTE) \
            and r.confirmado_em is not None:
        raise AcaoIgnorada(f"já confirmou em {r.confirmado_em:%d/%m %H:%M}")

    corte = corte_de(r.slot_inicio)
    limite = r.slot_inicio if kind in (KIND_CONFIRM_A_CORTE, KIND_CONFIRM_A_IMEDIATA) else corte
    if kind not in (KIND_CONFIRM_A_IMEDIATA, KIND_CONFIRM_A_CORTE) and agora >= corte:
        raise AcaoIgnorada(f"passou do corte ({corte:%d/%m %H:%M})")
    # A janela de silêncio vale para todos, menos a confirmação imediata (spec).
    if kind != KIND_CONFIRM_A_IMEDIATA and not dentro_janela_envio(agora):
        prox = proxima_janela_envio(agora)
        if prox >= limite:
            raise AcaoIgnorada(f"fora da janela 8h–20h30 e a próxima janela "
                               f"({prox:%d/%m %H:%M}) não é antes de {limite:%d/%m %H:%M}")
        raise AcaoAdiada(prox, f"fora da janela 8h–20h30 ({agora:%H:%M})")
    return r, wa, agora, limite


async def _enviar(acao: dict, db: AsyncSession, r: ReuniaoStatus, kind: str, template: str,
                  parametros: list, corpo: str, agora: datetime, limite: datetime, *,
                  url_suffixes: list | None = None, exigir_viva: bool = True) -> str | None:
    """Envia e vincula o wamid à ação. Devolve None se saiu, ou o motivo se não saiu.

    Teto por hora vira `AcaoAdiada(+10 min)` com o mesmo prazo da janela; qualquer outra
    recusa é devolvida para o handler decidir (todos menos o corte levantam AcaoIgnorada).
    """
    from app import qualificacao_guard as qg
    from app.nat_sender import enviar_nat
    wa = acao["contact_wa_id"]
    ok, motivo = await enviar_nat(wa, template, db,
                                  guard=guard_de_regua(r.meeting_id, kind,
                                                       exigir_viva=exigir_viva),
                                  parametros=parametros, corpo_livre=corpo,
                                  url_suffixes=url_suffixes)
    if not ok:
        if qg.e_teto(motivo):
            prox = agora + ATRASO_POR_TETO
            if prox < limite:
                raise AcaoAdiada(prox, motivo)
            raise AcaoIgnorada(f"{motivo} — e readiar passaria de {limite:%d/%m %H:%M}")
        return motivo
    # O VÍNCULO wamid → reunião. É o que deixa um clique SEM payload (o rótulo cru) ser
    # roteado pelo `context.id` da mensagem que ele respondeu (decisão 11).
    wamid = (await db.execute(
        select(Message.wa_message_id).where(Message.contact_wa_id == wa,
                                            Message.nat_etapa == template)
        .order_by(Message.id.desc()).limit(1))).scalar_one_or_none()
    from app.nat_scheduler import payload_de
    novo = {**payload_de(acao), "wa_message_id": wamid}
    await db.execute(update(NatScheduledAction).where(NatScheduledAction.id == acao["id"])
                     .values(payload=json.dumps(novo, ensure_ascii=False)))
    return None


def _render(corpo: str, parametros: list) -> str:
    from app.whatsapp import render_template_text
    return render_template_text(corpo, parametros) or corpo


C = nat_copy.CORPO_SUBMETIDO_FLUXO_A


@registrar_handler(KIND_CONFIRM_A_IMEDIATA)
async def confirm_a_imediata(acao: dict, db: AsyncSession):
    r, wa, agora, limite = await _espinha(acao, db, KIND_CONFIRM_A_IMEDIATA)
    c = _consultora(r)
    params = [await _nome(r, wa, db), await _pos(r, db), dia_extenso(r.slot_inicio),
              f"{r.slot_inicio:%H:%M}", c.nome_exibicao if c else ""]
    falhou = await _enviar(acao, db, r, KIND_CONFIRM_A_IMEDIATA, nat_copy.NAT_A_CONFIRMACAO,
                           params, _render(C[nat_copy.NAT_A_CONFIRMACAO], params), agora, limite)
    if falhou:
        raise AcaoIgnorada(f"confirmação imediata não saiu: {falhou}")
    await _nota(r, "Aguardando confirmação")


@registrar_handler(KIND_CONFIRM_A_EMENTA)
async def confirm_a_ementa(acao: dict, db: AsyncSession):
    r, wa, agora, limite = await _espinha(acao, db, KIND_CONFIRM_A_EMENTA)
    sub = await _sub_source(r, db)
    sufixo = ementa_de(sub)
    if not sufixo:
        raise AcaoIgnorada(f"sem ementa cadastrada para {sub!r} (backend/ementas.json)")
    nome, pos = await _nome(r, wa, db), await _pos(r, db)
    dia, hora = DIAS_SEMANA[r.slot_inicio.weekday()], f"{r.slot_inicio:%H:%M}"
    params = [nome, pos, dia, hora]
    livre = nat_copy.TEXTO_A_EMENTA_LIVRE.format(
        nome=nome, pos=pos, dia=dia, hora=hora,
        link=f"https://drive.google.com/file/d/{sufixo}")
    falhou = await _enviar(acao, db, r, KIND_CONFIRM_A_EMENTA, nat_copy.NAT_A_EMENTA, params,
                           livre, agora, limite, url_suffixes=[sufixo])
    if falhou:
        raise AcaoIgnorada(f"ementa não saiu: {falhou}")


@registrar_handler(KIND_CONFIRM_A_BENEFICIO)
async def confirm_a_beneficio(acao: dict, db: AsyncSession):
    r, wa, agora, limite = await _espinha(acao, db, KIND_CONFIRM_A_BENEFICIO)
    params = [await _nome(r, wa, db)]
    falhou = await _enviar(acao, db, r, KIND_CONFIRM_A_BENEFICIO, nat_copy.NAT_A_BENEFICIO,
                           params, _render(C[nat_copy.NAT_A_BENEFICIO], params), agora, limite)
    if falhou:
        raise AcaoIgnorada(f"benefício não saiu: {falhou}")


@registrar_handler(KIND_CONFIRM_A_PEDIDO)
async def confirm_a_pedido(acao: dict, db: AsyncSession):
    r, wa, agora, limite = await _espinha(acao, db, KIND_CONFIRM_A_PEDIDO)
    c = _consultora(r)
    params = [await _nome(r, wa, db), c.nome_exibicao if c else "",
              hoje_ou_amanha(r.slot_inicio, agora), f"{r.slot_inicio:%H:%M}"]
    falhou = await _enviar(acao, db, r, KIND_CONFIRM_A_PEDIDO,
                           nat_copy.NAT_A_PEDIDO_CONFIRMACAO, params,
                           _render(C[nat_copy.NAT_A_PEDIDO_CONFIRMACAO], params), agora, limite)
    if falhou:
        raise AcaoIgnorada(f"pedido de confirmação não saiu: {falhou}")


@registrar_handler(KIND_CONFIRM_A_ULTIMO_AVISO)
async def confirm_a_ultimo_aviso(acao: dict, db: AsyncSession):
    r, wa, agora, limite = await _espinha(acao, db, KIND_CONFIRM_A_ULTIMO_AVISO)
    params = [await _nome(r, wa, db), f"{r.slot_inicio:%H:%M}",
              f"{corte_de(r.slot_inicio):%H:%M}"]
    falhou = await _enviar(acao, db, r, KIND_CONFIRM_A_ULTIMO_AVISO,
                           nat_copy.NAT_A_ULTIMO_AVISO, params,
                           _render(C[nat_copy.NAT_A_ULTIMO_AVISO], params), agora, limite)
    if falhou:
        raise AcaoIgnorada(f"último aviso não saiu: {falhou}")


@registrar_handler(KIND_CONFIRM_A_CORTE)
async def confirm_a_corte(acao: dict, db: AsyncSession):
    """Sem confirmação até o corte. Decisão 7: marcar, cancelar o T-30, mandar o D0, anotar,
    avisar a consultora e o SDR para cancelarem NA EXACT (a API não cancela).

    Se a mensagem ao lead falhar (fora o teto), a marcação e os avisos FICAM: a reunião precisa
    ser cancelada na Exact de qualquer jeito. O handler devolve a ressalva, que o scheduler grava
    como motivo do `executado`.
    """
    r, wa, agora, limite = await _espinha(acao, db, KIND_CONFIRM_A_CORTE)
    r.cancelado_em = agora
    r.cancelado_motivo = "sem_confirmacao"
    await cancelar_regua(wa, r, "corte", db)        # T-30 e o que restar; encerra a régua
    params = [await _nome(r, wa, db)]
    falhou = await _enviar(acao, db, r, KIND_CONFIRM_A_CORTE, nat_copy.NAT_NS_D0_CORTE, params,
                           _render(C[nat_copy.NAT_NS_D0_CORTE], params), agora, limite,
                           exigir_viva=False)
    await _nota(r, "Cancelado sem confirmação")
    await _notificar(r, wa, TIPO_NOTIF_CONFIRMACAO, "Reunião sem confirmação: cancelar na Exact",
                     f"O lead não confirmou a reunião de {r.slot_inicio:%d/%m às %H:%M} até o "
                     f"corte. Cancele a reunião e exclua o box na Exact (a API não cancela).",
                     db, consultora=True)
    print(f"✂️ confirmacao: corte da reunião {r.meeting_id} ({wa})"
          f"{'' if not falhou else f' — D0 NÃO saiu: {falhou}'}")
    if falhou:
        return f"corte marcado e consultora avisada, mas a mensagem D0 não saiu: {falhou}"


# ==========================================================================================
# T-30 PELO ESPELHO (chamado por `qualificacao_fluxo.lembrete_reuniao`)
# ==========================================================================================

async def lembrete_por_espelho(acao: dict, db: AsyncSession) -> bool:
    """Com a flag ligada: o T-30 só vai para quem confirmou, com `nat_a_30min`.

    Devolve False quando NÃO é caso dele (flag desligada, fora da allowlist, reunião sem
    espelho): o `lembrete_reuniao` segue o caminho de sempre. Devolve True quando enviou;
    levanta AcaoIgnorada/AcaoAdiada nos outros casos.
    """
    from app.models import Agendamento
    from app.nat_scheduler import payload_de
    if not flag_ligada():
        return False
    payload = payload_de(acao)
    r = None
    if payload.get("meeting_id"):
        r = await _reuniao(payload["meeting_id"], db)
        if r is None:
            raise AcaoIgnorada(f"reunião {payload['meeting_id']} não existe em reuniao_status")
    elif payload.get("agendamento_id"):
        r = (await db.execute(select(ReuniaoStatus).where(
            ReuniaoStatus.agendamento_id == int(payload["agendamento_id"]))
            .order_by(ReuniaoStatus.registrado_em.desc().nullslast()).limit(1)
        )).scalar_one_or_none()
    if r is None or not telefone_permitido(r.telefone_bruto):
        return False

    agora = acao.get("agora") or _agora_sp()
    wa = acao["contact_wa_id"]
    if r.exact_type != EXACT_TYPE_VIGENTE:
        raise AcaoIgnorada(f"reunião {r.meeting_id} está {r.exact_type} na Exact")
    if r.slot_inicio <= agora:
        raise AcaoIgnorada(f"reunião {r.meeting_id} já começou — sem lembrete atrasado")
    parada = _regua_parada(r, KIND_LEMBRETE_REUNIAO)
    if parada:
        raise AcaoIgnorada(parada)
    if r.confirmado_em is None:
        raise AcaoIgnorada("não confirmou — o aviso de 30 min é só para confirmados (spec)")
    if not dentro_janela_envio(agora):
        prox = proxima_janela_envio(agora)
        if prox >= r.slot_inicio:
            raise AcaoIgnorada("fora da janela 8h–20h30 até o início da reunião")
        raise AcaoAdiada(prox, f"fora da janela 8h–20h30 ({agora:%H:%M})")

    from app.qualificacao_fluxo import _contato_ou_criar
    contato = await _contato_ou_criar(wa, lead_id=r.lead_id, db=db)
    if contato is None:
        raise AcaoIgnorada("não foi possível resolver nem criar o contato")
    wa = contato.wa_id

    c = _consultora(r)
    nome = await _nome(r, wa, db)
    if c is not None and c.telefone:
        template, params = nat_copy.NAT_A_30MIN, [nome, c.nome_exibicao, c.telefone]
        corpo = _render(C[nat_copy.NAT_A_30MIN], params)
    else:
        # Sem o telefone da consultora em consultoras.json, o `nat_a_30min` não tem o {{3}}
        # verdadeiro. Cai no template antigo, que diz "por este mesmo número" sem citar qual.
        from app import qualificacao_guard as qg
        print(f"↩️ confirmacao: consultora de {r.meeting_id} sem telefone em consultoras.json — "
              f"T-30 vai com {qg.ETAPA_LEMBRETE_REUNIAO}")
        from app.qualificacao_fluxo import _corpo_do_template
        template = qg.ETAPA_LEMBRETE_REUNIAO
        params = [nome, f"{r.slot_inicio:%H:%M}", c.nome_exibicao if c else ""]
        corpo = await _corpo_do_template(template, params, db)

    from app.nat_sender import enviar_nat
    ok, motivo = await enviar_nat(wa, template, db,
                                  guard=guard_de_regua(r.meeting_id, KIND_LEMBRETE_REUNIAO),
                                  parametros=params, corpo_livre=corpo)
    if not ok:
        raise AcaoIgnorada(f"lembrete não saiu: {motivo}")
    return True


async def armar_t30(reuniao: ReuniaoStatus, wa_id: str, db: AsyncSession) -> bool:
    """O T-30 da reunião confirmada. Payload pelo agendamento (Hub) ou pelo meeting_id (SDR)."""
    from app.nat_scheduler import agendar
    quando = reuniao.slot_inicio - ANTECEDENCIA_T30
    if quando <= _agora_sp():
        return False
    payload = ({"agendamento_id": reuniao.agendamento_id} if reuniao.agendamento_id
               else {"meeting_id": reuniao.meeting_id})
    await agendar(KIND_LEMBRETE_REUNIAO, wa_id, quando, payload, db)
    return True


# ==========================================================================================
# INBOUND: botões e texto
# ==========================================================================================
PAYLOADS_SIM = frozenset({nat_copy.A_CONF_SIM, nat_copy.A_PED_SIM, nat_copy.A_ULT_SIM})
PAYLOADS_REMARCAR = frozenset({nat_copy.A_CONF_REMARCAR, nat_copy.A_PED_REMARCAR,
                               nat_copy.A_ULT_REMARCAR})
PAYLOADS_D0 = frozenset({nat_copy.NS_D0_AGORA, nat_copy.NS_D0_HORARIO})
PAYLOADS_REGUA = PAYLOADS_SIM | PAYLOADS_REMARCAR | PAYLOADS_D0 | {nat_copy.A_PED_NAO}
# Kind → template, para casar o rótulo de um clique sem payload.
TEMPLATE_DO_KIND = {
    KIND_CONFIRM_A_IMEDIATA: nat_copy.NAT_A_CONFIRMACAO,
    KIND_CONFIRM_A_PEDIDO: nat_copy.NAT_A_PEDIDO_CONFIRMACAO,
    KIND_CONFIRM_A_ULTIMO_AVISO: nat_copy.NAT_A_ULTIMO_AVISO,
    KIND_CONFIRM_A_CORTE: nat_copy.NAT_NS_D0_CORTE,
}
# Depois do corte, por quanto tempo os cliques do D0 ainda são desta régua (decisão 8).
JANELA_CLIQUE_D0 = timedelta(hours=24)


async def _reuniao_dona(wa_id: str, db: AsyncSession) -> tuple[ReuniaoStatus | None, bool]:
    """(reunião, cortada?). Viva = Vigente, futura, régua não encerrada e imediata já enviada.
    Cortada = corte executado há menos de 24h (só para os cliques do D0)."""
    chave = chave_telefone(wa_id)
    if not chave:
        return None, False
    agora = _agora_sp()
    vivas = (await db.execute(select(ReuniaoStatus).where(
        ReuniaoStatus.telefone_chave == chave, ReuniaoStatus.exact_type == EXACT_TYPE_VIGENTE,
        ReuniaoStatus.slot_inicio > agora, ReuniaoStatus.regua_encerrada_em.is_(None))
        .order_by(ReuniaoStatus.registrado_em.desc().nullslast()))).scalars().all()
    for r in vivas:
        if await _acoes(r.meeting_id, db, kinds=(KIND_CONFIRM_A_IMEDIATA,),
                        status=ACAO_EXECUTADO):
            return r, False
    cortada = (await db.execute(select(ReuniaoStatus).where(
        ReuniaoStatus.telefone_chave == chave,
        ReuniaoStatus.cancelado_motivo == "sem_confirmacao",
        ReuniaoStatus.cancelado_em > agora - JANELA_CLIQUE_D0)
        .order_by(ReuniaoStatus.cancelado_em.desc()).limit(1))).scalar_one_or_none()
    return (cortada, True) if cortada is not None else (None, False)


async def _payload_pelo_contexto(r: ReuniaoStatus, evento: dict, db: AsyncSession) -> str | None:
    """Clique SEM payload: só roteia pelo rótulo se o `context.id` é uma mensagem que ESTA
    régua mandou para ESTA reunião (decisão 11). Senão, None (vira texto livre)."""
    ctx = evento.get("context_message_id")
    rotulo = (evento.get("button_text") or "").strip().lower()
    if not ctx or not rotulo:
        return None
    from app.nat_scheduler import payload_de
    for a in await _acoes(r.meeting_id, db, kinds=tuple(TEMPLATE_DO_KIND),
                          status=ACAO_EXECUTADO):
        if payload_de({"payload": a.payload}).get("wa_message_id") != ctx:
            continue
        for b in nat_copy.BOTOES_FLUXO_A.get(TEMPLATE_DO_KIND[a.kind], []):
            if b["titulo"].strip().lower() == rotulo:
                return b["payload"]
    return None


async def inbound(wa_id: str, evento_botao: dict | None, content: str,
                  db: AsyncSession) -> bool:
    """A régua é dona deste inbound? Se sim, trata e devolve True. Chamado ANTES do agente.

    Com a flag desligada devolve False sem tocar no banco. False = o webhook segue como sempre.
    """
    if not flag_ligada() or not telefone_permitido(wa_id):
        return False
    r, cortada = await _reuniao_dona(wa_id, db)
    if r is None:
        return False

    payload = None
    if evento_botao:
        payload = (evento_botao.get("button_payload") or "").strip() or None
        if payload not in PAYLOADS_REGUA:
            payload = await _payload_pelo_contexto(r, evento_botao, db)

    if cortada:
        # Depois do corte, a régua só responde aos dois botões do D0. Texto livre segue o
        # caminho de sempre (dono notificado pelo webhook); a régua D0+1h em diante é Bloco 2.
        if payload == nat_copy.NS_D0_AGORA:
            await ligar_agora(r, wa_id, db)
            return True
        if payload == nat_copy.NS_D0_HORARIO:
            await remarcar(r, wa_id, db, ja_cortada=True)
            return True
        return False

    if payload in PAYLOADS_SIM:
        await confirmar(r, wa_id, "botao", db)
    elif payload in PAYLOADS_REMARCAR:
        await remarcar(r, wa_id, db)
    elif payload == nat_copy.A_PED_NAO:
        await cancelado_pelo_lead(r, wa_id, db)
    elif payload is None and not evento_botao and e_confirmacao(content):
        await confirmar(r, wa_id, "texto", db)
    elif payload is None and not evento_botao and _recusa(content):
        await sem_interesse(r, wa_id, db)
    elif payload is None and not evento_botao and await _duvida_simples(r, wa_id, content, db):
        pass                                     # respondeu e pediu a confirmação de novo
    else:
        # Texto fora da lista, áudio/figurinha (`media:`), botão do D0 antes do corte, clique
        # sem payload que não casou: humano.
        await pausar(r, wa_id, db, content)
    return True


# ------------------------------------------------------------------------------------------
# DÚVIDA SIMPLES (Fase 6): LLM com contrato fechado, fail-closed para humano
# ------------------------------------------------------------------------------------------
ETAPA_DUVIDA = "confirm_a_duvida"
TEXTO_PEDE_CONFIRMACAO = "Você confirma sua presença?"
# Uma resposta automática de dúvida por reunião; a segunda dúvida já é conversa, e é humano.
MAX_DUVIDAS_POR_REUNIAO = 1


async def _duvida_simples(r: ReuniaoStatus, wa_id: str, content: str, db: AsyncSession) -> bool:
    """True se respondeu a uma dúvida simples (e a régua segue). False = vai para humano."""
    from app import qualificacao_llm as llm
    from app.nat_sender import enviar_nat
    texto = (content or "").strip()
    if not texto or texto.startswith("media:") or texto.startswith("botao:"):
        return False
    desde = r.registrado_em or (r.slot_inicio - timedelta(days=30))
    ja = (await db.execute(select(func.count()).select_from(Message).where(
        Message.contact_wa_id.in_(variantes_wa_id(wa_id) or (wa_id,)),
        Message.direction == "outbound", Message.nat_etapa == ETAPA_DUVIDA,
        Message.timestamp >= desde))).scalar() or 0
    if ja >= MAX_DUVIDAS_POR_REUNIAO:
        return False
    c = _consultora(r)
    resultado = await llm.classificar_duvida(
        texto, quando=f"{dia_extenso(r.slot_inicio)}, às {r.slot_inicio:%H:%M}",
        consultora=c.nome_exibicao if c else "", rotulo=f"{wa_id}/{r.meeting_id}")
    if not resultado or resultado["tipo"] != "duvida_simples":
        return False
    ok, motivo = await enviar_nat(wa_id, ETAPA_DUVIDA, db, guard=_guard_resposta,
                                  corpo_livre=f"{resultado['resposta']}\n\n"
                                              f"{TEXTO_PEDE_CONFIRMACAO}")
    if not ok:
        print(f"⚠️ confirmacao: resposta à dúvida NÃO saiu para {wa_id} ({motivo}) — humano")
        return False
    print(f"💬 confirmacao: dúvida simples respondida na reunião {r.meeting_id} ({wa_id})")
    return True


def _recusa(texto: str | None) -> bool:
    """O mesmo padrão da higiene do disparo. NÃO casa "não há mais interesse" (memória
    `higiene-disparo-recusa-e-teto`): é frase do nosso `sdr_encerramento`, não do lead."""
    from app.higiene_disparo import PADRAO_RECUSA
    return bool(re.search(PADRAO_RECUSA, texto or "", re.IGNORECASE))


async def confirmar(r: ReuniaoStatus, wa_id: str, por: str, db: AsyncSession) -> None:
    """Idempotente: um segundo "Confirmo" não reenvia nada."""
    if r.confirmado_em is not None:
        print(f"↩️ confirmacao: reunião {r.meeting_id} já confirmada — nada a fazer")
        return
    agora = _agora_sp()
    r.confirmado_em = agora
    r.confirmado_por = por
    # Para só as MENSAGENS DE CONFIRMAÇÃO. Ementa e benefício seguem (não pedem confirmação).
    await _cancelar_da_reuniao(r, (KIND_CONFIRM_A_PEDIDO, KIND_CONFIRM_A_ULTIMO_AVISO,
                                   KIND_CONFIRM_A_CORTE), "confirmou", db)
    await armar_t30(r, wa_id, db)
    await _nota(r, f"Confirmado em {agora:%d/%m %H:%M}")
    nome = await _nome(r, wa_id, db)
    await _responder(wa_id, nat_copy.TEXTO_A_CONFIRMADO.format(
        nome=nome, dia=dia_extenso(r.slot_inicio), hora=f"{r.slot_inicio:%H:%M}"), db)
    print(f"✅ confirmacao: reunião {r.meeting_id} confirmada por {por} ({wa_id})")


async def remarcar(r: ReuniaoStatus, wa_id: str, db: AsyncSession, *,
                   ja_cortada: bool = False) -> None:
    if not ja_cortada:
        r.cancelado_em = _agora_sp()
        r.cancelado_motivo = "remarcar"
        await cancelar_regua(wa_id, r, "remarcar", db)
    await _nota(r, "Pediu remarcação")
    await _notificar(r, wa_id, TIPO_NOTIF_CONFIRMACAO, "Lead pediu para remarcar",
                     f"Reunião de {r.slot_inicio:%d/%m às %H:%M}. Mande os horários "
                     f"disponíveis por aqui e cancele a reunião antiga na Exact.",
                     db, consultora=True)
    await _responder(wa_id, nat_copy.TEXTO_A_REMARCAR.format(nome=await _nome(r, wa_id, db)),
                     db)


async def cancelado_pelo_lead(r: ReuniaoStatus, wa_id: str, db: AsyncSession) -> None:
    r.cancelado_em = _agora_sp()
    r.cancelado_motivo = "lead_avisou"
    await cancelar_regua(wa_id, r, "lead_avisou", db)
    await _nota(r, "Cancelado pelo lead")
    await _notificar(r, wa_id, TIPO_NOTIF_CONFIRMACAO, "Lead avisou que não vai conseguir",
                     f"Reunião de {r.slot_inicio:%d/%m às %H:%M}. Cancele a reunião e exclua o "
                     f"box na Exact. Não conta como no-show.", db, consultora=True)
    await _responder(wa_id, nat_copy.TEXTO_A_CANCELADO_LEAD.format(
        nome=await _nome(r, wa_id, db)), db)


async def ligar_agora(r: ReuniaoStatus, wa_id: str, db: AsyncSession) -> None:
    """"Posso falar agora": não há como saber quem está livre neste minuto (a agenda só mostra
    reunião marcada), então avisa as duas consultoras e o SDR dono: quem pegar, assume."""
    await _nota(r, "Pediu ligação agora")
    await _notificar(r, wa_id, TIPO_NOTIF_LIGAR_AGORA, "Lead pediu ligação AGORA",
                     "Clicou \"Posso falar agora\" depois do corte. Quem estiver livre, ligue.",
                     db, todas=True)
    await _responder(wa_id, nat_copy.TEXTO_NS_LIGAR_AGORA.format(
        nome=await _nome(r, wa_id, db)), db)


async def sem_interesse(r: ReuniaoStatus, wa_id: str, db: AsyncSession) -> None:
    r.cancelado_em = _agora_sp()
    r.cancelado_motivo = "sem_interesse"
    await cancelar_regua(wa_id, r, "sem_interesse", db)
    await _nota(r, "Sem interesse agora")
    await _notificar(r, wa_id, TIPO_NOTIF_CONFIRMACAO, "Lead disse que não tem interesse",
                     f"Reunião de {r.slot_inicio:%d/%m às %H:%M}. Cancele na Exact.", db,
                     consultora=True)


async def pausar(r: ReuniaoStatus, wa_id: str, db: AsyncSession, content: str) -> None:
    """Resposta fora do padrão: para as mensagens de confirmação e chama um humano. O CORTE E O
    T-30 CONTINUAM (spec: "o corte continua valendo")."""
    await _cancelar_da_reuniao(r, (KIND_CONFIRM_A_PEDIDO, KIND_CONFIRM_A_ULTIMO_AVISO,
                                   KIND_CONFIRM_A_EMENTA, KIND_CONFIRM_A_BENEFICIO),
                               "humano", db)
    r.regua_encerrada_em = _agora_sp()
    r.regua_encerrada_motivo = "humano"
    await _nota(r, "Aguardando humano")
    previa = "[mídia]" if (content or "").startswith("media:") else (content or "")[:120]
    await _notificar(r, wa_id, TIPO_NOTIF_CONFIRMACAO, "Lead respondeu a confirmação: assuma",
                     f"Reunião de {r.slot_inicio:%d/%m às %H:%M}. Mensagem: {previa}. O corte "
                     f"automático continua valendo se não houver confirmação.", db)
    print(f"🤝 confirmacao: reunião {r.meeting_id} pausada para humano ({wa_id})")
