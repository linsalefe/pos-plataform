"""Espelho das reuniões da Exact em `reuniao_status` (Bloco 0, 07/10/2026).

==========================================================================================
POR QUE EXISTE
==========================================================================================
O Hub não sabia o que acontecia com a reunião depois que ela nascia. `agendamentos.passo`
fica `agendado` para sempre, e o sync de leads só lê `/Leads`. MEDIDO em 07/10
(RECON_CONFIRMACAO_NOSHOW_20261007 §2 e §5.3):

  * 4 lembretes T-30 saíram para reunião já remarcada;
  * 2 lembretes estavam pendentes para reunião já `Cancelada` (cancelados à mão em 07/10);
  * 64 de 249 reuniões desde 07/09 foram marcadas direto na Exact, pela SDR ou pela
    consultora, e não existem em `agendamentos`.

Este job lê `GET /Meetings` e mantém uma linha por reunião. O guard do lembrete
(`qualificacao_guard.guard_de_lembrete`) passa a ler daqui, e os blocos 1 e 2 também vão.

==========================================================================================
O CICLO: DUAS LEITURAS, UMA TRANSAÇÃO
==========================================================================================
  1. NOVAS: `registerDate ge <cursor>` (UTC). Pega tudo o que nasceu desde a última passada,
     inclusive a reunião que a SDR marcou na mão.
  2. MUDANÇA DE STATUS: `startTime ge <hoje SP - 2 dias>`. A Exact não tem "data de
     alteração" na reunião, então o único jeito de ver `Vigente -> Cancelada` de uma reunião
     futura, ou `Vigente -> Concluido` da reunião de ontem, é reler a janela inteira.
     Medido: ~20 reuniões futuras por vez (RECON §2), barato.

As duas leituras vêm ANTES de qualquer escrita: falha da Exact não deixa meio ciclo gravado.
Depois, um upsert por reunião e o cursor, tudo no mesmo commit. Exceção = rollback e o cursor
não avança (a próxima passada relê a mesma janela, e o upsert é idempotente).

2 requisições por ciclo, uma página cada, sempre com `$filter` (FINDINGS §5). A cota da Exact
(30 req/20s) é do token inteiro e dividida com o `sync_job` de leads, que roda a cada 600 s
desde o boot. Por isso o primeiro ciclo daqui sai 120 s depois do boot: os dois relógios
ficam deslocados em 2 min e nunca batem no mesmo instante.

==========================================================================================
O QUE ESTE BLOCO NÃO FAZ
==========================================================================================
Não manda mensagem, não escreve na Exact, não cadastra webhook. Não arma lembrete para reunião
marcada na Exact (é o bloco 1). O único efeito fora de `reuniao_status` é CANCELAR o
`lembrete_reuniao` pendente de uma reunião do Hub que a Exact diz `Cancelada`.
"""
import asyncio
import os
from datetime import datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agendamento import client
from app.agendamento.horarios import agora_sp, de_exact
from app.date_parse import parse_datetime
from app.models import (ACAO_CANCELADO, ACAO_PENDENTE, EXACT_TYPE_CANCELADA,
                        EXACT_TYPE_VIGENTE, KIND_LEMBRETE_REUNIAO, ORIGEM_REUNIAO_EXACT,
                        ORIGEM_REUNIAO_HUB, PASSO_AGENDADO, PREFIXO_REUNIAO_HUB, Agendamento,
                        NatScheduledAction, ReuniaoStatus, ReuniaoSyncCursor)
from app.telefone import chave_telefone

INTERVALO_SEGUNDOS = 600
# Deslocamento do primeiro ciclo em relação ao boot. Ver "O CICLO" no cabeçalho.
ATRASO_PRIMEIRO_CICLO_SEGUNDOS = 120

# Quantos dias para trás a releitura de status alcança. 2 cobre o fim de semana curto: o
# feedback de sexta registrado na segunda ainda é visto.
DIAS_RELEITURA = 2

# Folga ao avançar o cursor de `registerDate`. A Exact grava a reunião e o índice de leitura
# atrasa alguns segundos (FINDINGS §13, o mesmo efeito em `description`); recuar 5 min relê um
# pouco a mais e o upsert torna isso inofensivo.
FOLGA_CURSOR = timedelta(minutes=5)

# `registerDate` é UTC de verdade; SP é UTC-3 fixo (sem horário de verão desde 2019). Mesmo
# deslocamento de `qualificacao_gatilho.OFFSET_SP_PARA_UTC`.
OFFSET_SP_PARA_UTC = timedelta(hours=3)


def flag_ligada() -> bool:
    """`REUNIAO_SYNC_ENABLED` lido a cada ciclo, sem cache (padrão de `follow_estagio._ligado`).

    Aceita `true`, `1`, `sim`, `yes`. Qualquer outra coisa, inclusive vazio, é DESLIGADO.
    """
    return (os.getenv("REUNIAO_SYNC_ENABLED", "") or "").strip().lower() in (
        "true", "1", "sim", "yes")


# ==========================================================================================
# NORMALIZAÇÃO — função pura, sem banco
# ==========================================================================================

def _origem(manager_description: str | None) -> str:
    """`hub` se o `managerDescription` tem o marcador que o Hub grava no `BoxesAdd`.

    O campo `user` da reunião não serve: é o dono do token em 249 de 249 (RECON §5.3).
    """
    texto = (manager_description or "").strip()
    return ORIGEM_REUNIAO_HUB if texto.startswith(PREFIXO_REUNIAO_HUB) else ORIGEM_REUNIAO_EXACT


def _registrado_sp(register_date: str | None) -> datetime | None:
    """`registerDate` (UTC de verdade, 7 casas de fração) -> SP naive."""
    utc = parse_datetime(register_date)
    return utc - OFFSET_SP_PARA_UTC if utc else None


def _normalizar(meeting: dict) -> dict:
    """Uma reunião de `/Meetings` -> os campos de `reuniao_status`. Sem `agendamento_id`, que
    depende do banco (`_vincular`).

    `startTime`/`finalTime` vão SEM conversão: são hora de parede de SP, apesar do formato
    (FINDINGS §1). `registerDate` é o único campo UTC, e é convertido.
    """
    lead = meeting.get("lead") or {}
    rep = meeting.get("salesRep") or {}
    telefone = (lead.get("phone") or "").strip()
    fim = meeting.get("finalTime")
    return {
        "meeting_id": int(meeting["id"]),
        "lead_id": int(lead["id"]) if lead.get("id") else None,
        "telefone_chave": chave_telefone(telefone) or None,
        "telefone_bruto": telefone[:30] or None,
        "nome": ((lead.get("name") or "").strip()[:255]) or None,
        "slot_inicio": de_exact(meeting["startTime"]),
        "slot_fim": de_exact(fim) if fim else None,
        "sales_rep_email": ((rep.get("email") or "").strip().lower()[:255]) or None,
        "origem": _origem(meeting.get("managerDescription")),
        "exact_type": meeting["type"],
        "registrado_em": _registrado_sp(meeting.get("registerDate")),
        "register_date_utc": parse_datetime(meeting.get("registerDate")),
    }


# ==========================================================================================
# VÍNCULO COM `agendamentos`
# ==========================================================================================

async def _vincular(db: AsyncSession, linhas: list[dict]) -> None:
    """Preenche `agendamento_id` em cada linha. Duas regras, nesta ordem:

    1. `agendamentos.meeting_id` igual (gravado best-effort depois do `scheduleAdd`,
       `agendar.py:485`). É o vínculo exato: 158 das 249 reuniões do RECON casaram assim.
    2. Só para reunião `hub` ainda sem vínculo: mesmo `lead_id` E mesmo horário de início, com
       `passo='agendado'`.

    POR QUE A REGRA 2 EXIGE O HORÁRIO, e não só o `lead_id` como no plano. RECON §5.3: 25
    reuniões caem em lead que tem agendamento do Hub, mas SEM o marcador LP. São a remarcação
    que a consultora fez na Exact. Vincular por `lead_id` puro penduraria a reunião NOVA no
    agendamento ANTIGO, e o guard do lembrete leria o status errado. Mesmo lead + mesmo
    horário + marcador LP é a mesma reunião.
    """
    ids = [l["meeting_id"] for l in linhas]
    por_meeting: dict[int, int] = {}
    if ids:
        res = await db.execute(select(Agendamento.meeting_id, Agendamento.id).where(
            Agendamento.meeting_id.in_(ids)))
        for meeting_id, ag_id in res.all():
            por_meeting.setdefault(int(meeting_id), int(ag_id))

    sem = [l for l in linhas
           if l["meeting_id"] not in por_meeting and l["origem"] == ORIGEM_REUNIAO_HUB
           and l["lead_id"]]
    por_lead_slot: dict[tuple[int, datetime], int] = {}
    if sem:
        res = await db.execute(
            select(Agendamento.lead_id, Agendamento.slot_inicio, Agendamento.id)
            .where(Agendamento.lead_id.in_({l["lead_id"] for l in sem}),
                   Agendamento.passo == PASSO_AGENDADO)
            .order_by(Agendamento.id.desc()))
        for lead_id, slot, ag_id in res.all():
            por_lead_slot.setdefault((int(lead_id), slot), int(ag_id))

    for l in linhas:
        l["agendamento_id"] = (por_meeting.get(l["meeting_id"])
                               or por_lead_slot.get((l["lead_id"], l["slot_inicio"])))


# ==========================================================================================
# ESCRITA
# ==========================================================================================

# Só o que a Exact pode mudar numa reunião existente entra no UPDATE. Identidade (telefone,
# lead, origem, registro) é fixada no INSERT.
#
# `exact_type_visto_em` é QUANDO O STATUS ATUAL FOI VISTO PELA PRIMEIRA VEZ: só muda junto com
# o `exact_type`. É o que dá ao bloco 1 o "cancelada desde quando", que a Exact não tem.
#
# `agendamento_id` por COALESCE: a reunião do Hub pode ser vista antes de o `meeting_id`
# chegar em `agendamentos` (é best-effort); o vínculo entra na passada seguinte e nunca é
# apagado por uma passada que não o achou.
#
# No ON CONFLICT, `reuniao_status.<col>` é o valor ANTIGO em todas as expressões do SET,
# independentemente da ordem.
UPSERT = text("""
INSERT INTO reuniao_status (
    meeting_id, lead_id, telefone_chave, telefone_bruto, nome, slot_inicio, slot_fim,
    sales_rep_email, origem, agendamento_id, exact_type, exact_type_visto_em, registrado_em,
    updated_at)
VALUES (
    :meeting_id, :lead_id, :telefone_chave, :telefone_bruto, :nome, :slot_inicio, :slot_fim,
    :sales_rep_email, :origem, :agendamento_id, :exact_type, :agora, :registrado_em, :agora)
ON CONFLICT (meeting_id) DO UPDATE SET
    exact_type_anterior = CASE WHEN reuniao_status.exact_type IS DISTINCT FROM EXCLUDED.exact_type
                               THEN reuniao_status.exact_type
                               ELSE reuniao_status.exact_type_anterior END,
    exact_type_visto_em = CASE WHEN reuniao_status.exact_type IS DISTINCT FROM EXCLUDED.exact_type
                               THEN EXCLUDED.exact_type_visto_em
                               ELSE reuniao_status.exact_type_visto_em END,
    exact_type     = EXCLUDED.exact_type,
    slot_inicio    = EXCLUDED.slot_inicio,
    slot_fim       = EXCLUDED.slot_fim,
    agendamento_id = COALESCE(reuniao_status.agendamento_id, EXCLUDED.agendamento_id),
    updated_at     = EXCLUDED.updated_at
""")

_CAMPOS_UPSERT = ("meeting_id", "lead_id", "telefone_chave", "telefone_bruto", "nome",
                  "slot_inicio", "slot_fim", "sales_rep_email", "origem", "agendamento_id",
                  "exact_type", "registrado_em")


async def _cancelar_lembrete(db: AsyncSession, agendamento_id: int, motivo: str) -> int:
    """Cancela o `lembrete_reuniao` PENDENTE do agendamento, gravando o motivo.

    Por `agendamento_id` do payload, e não por `nat_scheduler.cancelar(kind, wa_id)` como dizia
    o plano: aquele não grava motivo e cancela por CONTATO, o que levaria junto o lembrete de
    outra reunião da mesma pessoa. É o mesmo UPDATE que cancelou as ações 3964 e 4002 à mão em
    07/10. `payload` é TEXT (JSON serializado), daí o `::json`.
    """
    res = await db.execute(
        update(NatScheduledAction)
        .where(NatScheduledAction.kind == KIND_LEMBRETE_REUNIAO,
               NatScheduledAction.status == ACAO_PENDENTE,
               text("(nat_scheduled_actions.payload::json->>'agendamento_id') = :ag")
               .bindparams(ag=str(agendamento_id)))
        .values(status=ACAO_CANCELADO, motivo=motivo, processed_at=agora_sp())
        .execution_options(synchronize_session=False))
    return res.rowcount or 0


async def sincronizar(db: AsyncSession, *, listar=None, agora: datetime | None = None) -> dict:
    """Um ciclo completo. NÃO commita: quem chama decide (`ciclo`). Devolve o resumo.

    `listar` e `agora` existem para o teste injetar a Exact e o relógio.
    """
    listar = listar or client.listar_meetings
    agora = agora or agora_sp()

    # Sem FOR UPDATE: há um worker só, e travar a linha seguraria a transação aberta durante
    # as duas chamadas HTTP à Exact (até 2 x 15 s de timeout).
    cursor = (await db.execute(select(ReuniaoSyncCursor).where(
        ReuniaoSyncCursor.id == 1))).scalar_one_or_none()
    if cursor is None:
        raise RuntimeError("reuniao_sync_cursor id=1 não existe — rode migrate_reuniao_status.py")
    desde_utc = cursor.register_date_cursor or datetime(2026, 9, 7)

    # As duas leituras ANTES de qualquer escrita.
    novas = await listar(register_date_ge=desde_utc)
    # PRIMEIRO CICLO: a releitura de status começa no mesmo dia do cursor, e não em hoje - 2.
    # Sem isto o backfill deixa de fora a reunião registrada ANTES de 07/09 que acontece
    # DEPOIS. Medido no ensaio com rollback de 07/10: 226 linhas contra as 249 do RECON §5.2,
    # que somou as duas janelas desde 07/09. Do segundo ciclo em diante é hoje - 2 dias.
    if cursor.ultimo_ciclo_em is None:
        inicio_janela = min(agora - timedelta(days=DIAS_RELEITURA), desde_utc)
    else:
        inicio_janela = agora - timedelta(days=DIAS_RELEITURA)
    janela = await listar(start_time_ge=inicio_janela)

    por_id: dict[int, dict] = {}
    for m in list(novas) + list(janela):
        try:
            linha = _normalizar(m)
        except (KeyError, TypeError, ValueError) as e:
            print(f"⚠️ reuniao_sync: reunião ilegível ({m.get('id')!r}): "
                  f"{type(e).__name__}: {e}")
            continue
        por_id[linha["meeting_id"]] = linha
    linhas = list(por_id.values())
    await _vincular(db, linhas)

    antes = {}
    if linhas:
        res = await db.execute(select(ReuniaoStatus.meeting_id, ReuniaoStatus.exact_type).where(
            ReuniaoStatus.meeting_id.in_(list(por_id))))
        antes = {int(mid): tipo for mid, tipo in res.all()}

    novas_n = atualizadas = 0
    mudancas: list[tuple[dict, str | None]] = []
    for l in linhas:
        await db.execute(UPSERT, {**{c: l[c] for c in _CAMPOS_UPSERT}, "agora": agora})
        if l["meeting_id"] in antes:
            atualizadas += 1
            if antes[l["meeting_id"]] != l["exact_type"]:
                mudancas.append((l, antes[l["meeting_id"]]))
        else:
            novas_n += 1

    # Reunião do Hub que a Exact diz Cancelada: o lembrete T-30 dela não pode sair. Dois casos:
    # mudou de Vigente para Cancelada nesta passada, ou já NASCEU Cancelada no espelho (o
    # backfill de 07/09; e a reunião cancelada entre dois ciclos).
    lembretes_cancelados = 0
    canceladas_hub = []
    for l in linhas:
        if l["origem"] != ORIGEM_REUNIAO_HUB or l["exact_type"] != EXACT_TYPE_CANCELADA:
            continue
        anterior = antes.get(l["meeting_id"], "nova")
        if anterior == EXACT_TYPE_CANCELADA:
            continue
        if anterior == EXACT_TYPE_VIGENTE:
            print(f"⚠️ reunião {l['meeting_id']} do Hub (agendamento {l['agendamento_id']}) "
                  f"virou Cancelada na Exact")
        canceladas_hub.append(l["meeting_id"])
        if l["agendamento_id"]:
            n = await _cancelar_lembrete(
                db, l["agendamento_id"],
                f"reunião {l['meeting_id']} Cancelada na Exact (reuniao_sync)")
            if n:
                lembretes_cancelados += n
                print(f"🚫 reuniao_sync: lembrete do agendamento {l['agendamento_id']} "
                      f"cancelado — reunião {l['meeting_id']} está Cancelada na Exact")

    # Bloco 1 (07/10): reunião que SAIU de Vigente (Cancelada ou Concluido na Exact) encerra a
    # régua de confirmação inteira da pessoa, corte e T-30 incluídos. Spec: "reunião cancelada
    # ou remarcada pela equipe no CRM: para todas as mensagens pendentes". Roda com a flag
    # desligada também: cancelar é sempre seguro.
    reguas_canceladas = 0
    for l, de in mudancas:
        if de != EXACT_TYPE_VIGENTE or l["exact_type"] == EXACT_TYPE_VIGENTE:
            continue
        reguas_canceladas += await _encerrar_regua(db, l)

    # Bloco 2: reunião NOVA e Vigente da mesma pessoa = ela remarcou com a consultora. A régua
    # de no-show dela para ('reagendou'). Vigente -> Cancelada NÃO mexe no no-show: a reunião
    # do corte já está cancelada para nós.
    for l in linhas:
        if l["meeting_id"] not in antes and l["exact_type"] == EXACT_TYPE_VIGENTE:
            await _encerrar_noshow_por_reuniao_nova(db, l["telefone_chave"], l["meeting_id"])

    # E a reunião Vigente futura SEM régua ganha a dela: a SDR na Exact, e a do Hub que o
    # `_gatilho_do_agente` não armou (sem meeting_id na hora). `armar` é idempotente e devolve
    # 0 com a flag desligada ou fora da allowlist; a consulta só roda com a flag ligada.
    reguas_armadas = await _armar_vigentes(db, agora)

    # Cursor: maior registerDate visto entre as NOVAS, menos a folga. Nunca anda para trás.
    vistos = [l["register_date_utc"] for l in map(_normalizar_seguro, novas) if l]
    vistos = [v for v in vistos if v]
    if vistos:
        proximo = max(vistos) - FOLGA_CURSOR
        if proximo > desde_utc:
            cursor.register_date_cursor = proximo

    resumo = (f"novas={novas_n} atualizadas={atualizadas} mudancas_status={len(mudancas)} "
              f"canceladas_hub={len(canceladas_hub)} lembretes_cancelados={lembretes_cancelados} "
              f"reguas_armadas={reguas_armadas} reguas_canceladas={reguas_canceladas} "
              f"lidas={len(novas)}+{len(janela)}")
    cursor.ultimo_ciclo_em = agora
    cursor.ultimo_ciclo_resultado = resumo
    await db.flush()
    return {"novas": novas_n, "atualizadas": atualizadas, "mudancas_status": len(mudancas),
            "canceladas_hub": canceladas_hub, "lembretes_cancelados": lembretes_cancelados,
            "requisicoes": 2, "resumo": resumo,
            "mudancas": [(l["meeting_id"], de, l["exact_type"]) for l, de in mudancas]}


async def _encerrar_regua(db: AsyncSession, linha: dict) -> int:
    """Cancela a régua de confirmação da pessoa desta reunião. Nunca derruba o ciclo."""
    from app import confirmacao
    from app.exact_spotter import format_phone
    wa = format_phone(linha.get("telefone_bruto") or "")
    if not wa:
        return 0
    try:
        async with db.begin_nested():
            r = (await db.execute(select(ReuniaoStatus).where(
                ReuniaoStatus.meeting_id == linha["meeting_id"]))).scalar_one_or_none()
            motivo = ("reuniao_cancelada_exact" if linha["exact_type"] == EXACT_TYPE_CANCELADA
                      else "reuniao_concluida_exact")
            # Escopada pela reunião (ver `confirmacao._cancelar_da_reuniao`): numa remarcação, a
            # régua da reunião NOVA da mesma pessoa não pode cair junto com a antiga.
            return await confirmacao.cancelar_regua(wa, r, motivo, db)
    except Exception as e:
        print(f"⚠️ reuniao_sync: régua da reunião {linha['meeting_id']} não encerrada "
              f"({type(e).__name__}: {e})")
        return 0


async def _armar_vigentes(db: AsyncSession, agora: datetime) -> int:
    """Arma a régua das reuniões Vigentes futuras que ainda não têm. Uma falha não derruba as
    outras nem o ciclo (savepoint por reunião)."""
    from app import confirmacao
    if not confirmacao.flag_ligada():
        return 0
    vigentes = (await db.execute(select(ReuniaoStatus).where(
        ReuniaoStatus.exact_type == EXACT_TYPE_VIGENTE,
        ReuniaoStatus.slot_inicio > agora,
        ReuniaoStatus.regua_encerrada_em.is_(None)))).scalars().all()
    armadas = 0
    for r in vigentes:
        try:
            async with db.begin_nested():
                if await confirmacao.armar(r, db, agora=agora):
                    armadas += 1
        except Exception as e:
            print(f"⚠️ reuniao_sync: régua da reunião {r.meeting_id} não armada "
                  f"({type(e).__name__}: {e})")
    return armadas


async def _encerrar_noshow_por_reuniao_nova(db: AsyncSession, chave: str | None,
                                           meeting_id: int) -> None:
    from app import noshow
    if not chave:
        return
    try:
        async with db.begin_nested():
            r = (await db.execute(select(ReuniaoStatus).where(
                ReuniaoStatus.telefone_chave == chave, ReuniaoStatus.noshow_em.isnot(None),
                ReuniaoStatus.regua_encerrada_em.is_(None),
                ReuniaoStatus.meeting_id != meeting_id))).scalars().first()
            if r is not None:
                await noshow.encerrar(r, "reagendou", db,
                                      nota=f"Régua de no-show encerrada: nova reunião {meeting_id}")
    except Exception as e:
        print(f"⚠️ reuniao_sync: no-show não encerrado pela reunião nova {meeting_id} "
              f"({type(e).__name__}: {e})")


async def espelhar_agendamento(ag, db: AsyncSession) -> ReuniaoStatus | None:
    """Cria (ou atualiza) a linha de `reuniao_status` de um agendamento do Hub NA HORA.

    Para o `_gatilho_do_agente` armar a régua sem esperar o sync (até 10 min). Usa o MESMO
    UPSERT do ciclo, então a passada seguinte só confirma ou corrige o status. Sem `meeting_id`
    (o `scheduleAdd` devolve booleano e o id é lido best-effort), devolve None.
    """
    if not getattr(ag, "meeting_id", None):
        return None
    linha = {
        "meeting_id": int(ag.meeting_id), "lead_id": ag.lead_id,
        "telefone_chave": chave_telefone(ag.telefone) or None,
        "telefone_bruto": (ag.telefone or "")[:30] or None,
        "nome": (ag.nome or "")[:255] or None,
        "slot_inicio": ag.slot_inicio, "slot_fim": ag.slot_fim,
        "sales_rep_email": (ag.sales_rep_email or "").lower()[:255] or None,
        "origem": ORIGEM_REUNIAO_HUB, "agendamento_id": ag.id,
        "exact_type": EXACT_TYPE_VIGENTE, "registrado_em": ag.created_at,
    }
    await db.execute(UPSERT, {**{c: linha[c] for c in _CAMPOS_UPSERT}, "agora": agora_sp()})
    # Reagendou pela LP: a régua de no-show da reunião anterior para.
    await _encerrar_noshow_por_reuniao_nova(db, linha["telefone_chave"], linha["meeting_id"])
    return (await db.execute(select(ReuniaoStatus).where(
        ReuniaoStatus.meeting_id == linha["meeting_id"]))).scalar_one_or_none()


def _normalizar_seguro(m: dict) -> dict | None:
    try:
        return _normalizar(m)
    except (KeyError, TypeError, ValueError):
        return None


# ==========================================================================================
# O JOB
# ==========================================================================================

async def ciclo() -> dict:
    """Uma passada com gate e transação própria. Nunca levanta."""
    if not flag_ligada():
        # Toda passada, de propósito: é a prova no journald de que o gate está fechado por
        # escolha e não porque o job morreu (mesma decisão de `follow_estagio.processar`).
        print("ℹ️  reuniao_sync DESLIGADO (REUNIAO_SYNC_ENABLED != true) — /Meetings não é lido.")
        return {"desligado": True}

    from app.database import async_session
    inicio = datetime.now()
    try:
        async with async_session() as db:
            try:
                resultado = await sincronizar(db)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        segundos = (datetime.now() - inicio).total_seconds()
        print(f"🔄 reuniao_sync: {resultado['resumo']} ({segundos:.1f}s)")
        return resultado
    except Exception as e:
        print(f"❌ reuniao_sync: ciclo abortado, cursor NÃO avançou — {type(e).__name__}: {e}")
        return {"erro": f"{type(e).__name__}: {e}"}


async def reuniao_sync_job():
    """Laço de 10 min. Primeiro ciclo 120 s depois do boot (ver "O CICLO" no cabeçalho)."""
    await asyncio.sleep(ATRASO_PRIMEIRO_CICLO_SEGUNDOS)
    while True:
        try:
            await ciclo()
        except Exception as e:      # `ciclo` não levanta; isto é a rede do laço
            print(f"❌ reuniao_sync: erro fora do ciclo: {type(e).__name__}: {e}")
        await asyncio.sleep(INTERVALO_SEGUNDOS)
