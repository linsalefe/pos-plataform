"""Remarcação que espera a Exact, e o aviso que chega a quem atende (SPRINT_REMARCACAO_20261019).

==========================================================================================
POR QUE EXISTE (RECON_REAGENDAMENTO_20261018)
==========================================================================================
O agente NUNCA concluiu uma remarcação: 0 de 3 entre 07 e 18/10. O lead clicava "Preciso
remarcar" ou "Escolher horário", escolhia o horário oferecido, e a Exact recusava o
`scheduleAdd`:

    reunião antiga marcada pelo SDR (lead no 18537)  ->  400 Stage not found
    reunião antiga marcada pela LP (lead no 18535)   ->  400 Lead has already gone through
                                                         this stage in this cycle.

Nos três casos a reunião antiga ainda estava Vigente na Exact. A API não desmarca (FINDINGS §6),
e o SDR contornava desmarcando à mão e criando a nova depois. Daí a regra desta sprint:

    NUNCA chamar `scheduleAdd` com a reunião antiga Vigente na Exact.

==========================================================================================
O FLUXO
==========================================================================================
  1. O clique (ou o texto, `confirmacao.inbound`) reabre o agente em `ofertando_agenda`, como
     antes. A oferta continua imediata: o lead está quente.
  2. O lead escolhe. `qualificacao_fluxo._agendar` pergunta `reuniao_que_bloqueia`; havendo
     uma, chama `estacionar` em vez de `fluxo.agendar`:
        - grava `slot_desejado_*` e `remarcacao_expira_em` (+24h) NA LINHA DA REUNIÃO ANTIGA;
        - responde "Anotei {dia} às {hora}, {nome}. ...";
        - avisa os SDRs (e o dono): "cancele a reunião {id} na Exact para o Hub remarcar";
        - fecha o agente (`concluido`, `encerrado_motivo='remarcacao_pendente'`).
     Enquanto pendente, o horário fica RESERVADO na grade da consultora (`ocupados_pendentes`).
  3. Um humano cancela a antiga na Exact. O `reuniao_sync` vê `Vigente -> Cancelada` e chama
     `ao_cancelar`, que só ENFILEIRA `remarcacao_retry` para agora. Quem chama a Exact é o
     handler, fora da transação do sync (o sync não manda mensagem nem segura transação em
     HTTP — cabeçalho de `reuniao_sync`).
  4. `remarcacao_retry`: o horário ainda está livre? `fluxo.agendar` no slot desejado (lead
     existente, `LeadsAdd` pulado). Sucesso: a régua de confirmação arma sozinha e o lead recebe
     a confirmação imediata. Horário ocupado: o agente oferece de novo. A Exact recusou: nova
     tentativa em 10 min. Segunda falha: humano, com o erro da Exact no motivo.
  5. `remarcacao_expira` (+24h): a antiga continua Vigente, ninguém cancelou. O lead ouve que a
     consultora vai falar com ele, e o caso vai para humano.

⚠️ NÃO ESTÁ PROVADO que o `scheduleAdd` passa depois do cancelamento manual (RECON §3). É por
isso que o passo 4 tem fallback para humano. O primeiro caso real vai para o relatório.

==========================================================================================
AVISO SEM DONO
==========================================================================================
Lead da LP nasce sem `assigned_to`. O aviso caía só na gestão (Isa), e o SDR que atende não via
(RECON §4: 1 respondido 9h depois, 2 nunca). `destinatarios` devolve o dono quando há; sem dono,
todos os `SDR_USER_IDS` mais a gestão. Não há papel SDR em `users` (todos são `admin`, menos um
`atendente`), por isso a lista vem do `.env`.
"""
import os
import re
import unicodedata
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (EXACT_TYPE_CANCELADA, EXACT_TYPE_VIGENTE, KIND_REMARCACAO_EXPIRA,
                        KIND_REMARCACAO_RETRY, TIPO_NOTIF_REMARCACAO, Contact, Message,
                        NatQualificacaoState, Notification, ReuniaoStatus)
from app.nat_guard import GESTOR_USER_ID, _agora_sp
from app.nat_scheduler import AcaoIgnorada, registrar_handler
from app.telefone import chave_telefone, variantes_wa_id

ENV_SDRS = "SDR_USER_IDS"

# Quanto tempo a escolha do lead espera alguém cancelar a antiga na Exact (decisão 3).
VALIDADE_PENDENTE = timedelta(hours=24)
# Tentativas automáticas de `scheduleAdd` por remarcação (decisão 6). Horário ocupado também
# conta: é tentativa gasta, e o lead já ouviu uma oferta nova.
MAX_TENTATIVAS = 2
# Intervalo entre a 1ª recusa da Exact e a 2ª tentativa.
ESPERA_RETRY = timedelta(minutes=10)
# Horário desejado que começa antes disto não é marcado: a consultora não teria como ver.
ANTECEDENCIA_MINIMA = timedelta(minutes=30)
# Reunião Vigente mais velha que isto não bloqueia: o sync relê `startTime >= hoje - 2 dias`
# (`reuniao_sync.DIAS_RELEITURA`) e nunca a veria virar Cancelada. A remarcação esperaria para
# sempre por um evento que não chega.
JANELA_VIGENTE = timedelta(days=2)
# Conversa "pausada" para fins de `new_message` sem dono: régua ou agente passaram para humano
# nesta janela e ninguém marcou Tratado.
JANELA_PAUSA = timedelta(days=7)

ENCERRADO_REMARCACAO_PENDENTE = "remarcacao_pendente"

# Critério 3 do spec. Casado contra o texto SEM ACENTO e minúsculo (`_normalizar`).
PADRAO_REMARCACAO = (r"remarc|reagend|outro horario|outro dia|apos (o )?dia|desmarcar"
                     r"|nao vou conseguir")

# Textos ao lead (convenção: sem travessão e sem emoji).
TEXTO_ANOTADO = "Anotei {dia} às {hora}, {nome}. A consultora confirma por aqui em breve."
TEXTO_REMARCADA = "Pronto, {nome}! Sua conversa com a consultora ficou para {dia} às {hora}."
TEXTO_HUMANO = ("{nome}, não consegui confirmar o novo horário por aqui. A consultora vai falar "
                "com você para combinar.")


# ==========================================================================================
# TEXTO DO LEAD
# ==========================================================================================

def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def pede_remarcacao(texto: str | None) -> bool:
    """Texto livre pedindo para remarcar. Clique (`botao:`) e mídia (`media:`) nunca casam."""
    bruto = (texto or "").strip()
    if not bruto or bruto.startswith(("botao:", "media:")):
        return False
    return re.search(PADRAO_REMARCACAO, _normalizar(bruto)) is not None


async def ultima_mensagem(wa_id: str, db: AsyncSession) -> str | None:
    """Prévia da última mensagem do lead. Mídia vira `[mídia]`, clique vira o rótulo."""
    linha = (await db.execute(select(Message.content).where(
        Message.contact_wa_id.in_(variantes_wa_id(wa_id) or (wa_id,)),
        Message.direction == "inbound").order_by(Message.timestamp.desc()).limit(1))).first()
    if linha is None:
        return None
    conteudo = linha[0] or ""
    if conteudo.startswith("media:"):
        return "[mídia]"
    if conteudo.startswith("botao:"):
        return f"clicou \"{conteudo[len('botao:'):]}\""
    return conteudo[:160]


# ==========================================================================================
# DESTINATÁRIOS
# ==========================================================================================

def sdr_user_ids() -> list[int]:
    """`SDR_USER_IDS` (ex.: "5,4"), lido a cada chamada. Valor ruim é ignorado e grita no log."""
    ids: list[int] = []
    for parte in (os.getenv(ENV_SDRS, "") or "").split(","):
        parte = parte.strip()
        if not parte:
            continue
        try:
            uid = int(parte)
        except ValueError:
            print(f"⚠️ remarcacao: {ENV_SDRS} tem valor inválido {parte!r} — ignorado")
            continue
        if uid not in ids:
            ids.append(uid)
    return ids


async def dono_de(wa_id: str, db: AsyncSession) -> int | None:
    """`assigned_to` em qualquer das grafias do contato (a mesma regra de `main.py`)."""
    linha = (await db.execute(select(Contact.assigned_to).where(
        Contact.wa_id.in_(variantes_wa_id(wa_id) or (wa_id,)),
        Contact.assigned_to.isnot(None)))).first()
    return linha[0] if linha else None


async def destinatarios(wa_id: str, db: AsyncSession, *, dono: int | None = None,
                        consultar_dono: bool = True) -> list[int]:
    """Com dono: só ele. Sem dono: todos os SDRs de `SDR_USER_IDS` + a gestão (decisão 4).

    Só ids que existem em `users`: `notifications.user_id` tem FK e um id errado no `.env`
    derrubaria o savepoint inteiro (`nat_flow.usuario_existe`).
    """
    from app.nat_flow import usuario_existe
    if dono is None and consultar_dono:
        dono = await dono_de(wa_id, db)
    candidatos = [dono] if dono else [*sdr_user_ids(), GESTOR_USER_ID]
    saida: list[int] = []
    for uid in candidatos:
        if uid not in saida and await usuario_existe(uid, db):
            saida.append(uid)
    return saida


async def notificar(wa_id: str, tipo: str, ref: str | None, titulo: str, corpo: str,
                    db: AsyncSession, *, extras: tuple[int, ...] = (),
                    com_ultima_mensagem: bool = True) -> list[int]:
    """Uma Notification por destinatário, com a ÚLTIMA mensagem do lead no corpo. Nunca levanta."""
    try:
        alvos = await destinatarios(wa_id, db)
        for uid in extras:
            if uid and uid not in alvos:
                alvos.append(uid)
        if com_ultima_mensagem:
            ultima = await ultima_mensagem(wa_id, db)
            if ultima:
                corpo = f"{corpo} Última mensagem: {ultima}"
        for uid in alvos:
            db.add(Notification(user_id=uid, contact_wa_id=wa_id, type=tipo, ref=ref,
                                title=titulo[:255], body=corpo))
        return alvos
    except Exception as e:
        print(f"⚠️ remarcacao: notificação '{titulo}' para {wa_id} falhou "
              f"({type(e).__name__}: {e})")
        return []


async def conversa_pausada(wa_id: str, db: AsyncSession, agora: datetime | None = None) -> bool:
    """A conversa está com humano: o agente transferiu, ou a régua parou por resposta fora do
    padrão ou pedido de remarcação, e ninguém marcou Tratado. Usado pelo `new_message` sem dono.
    """
    agora = agora or _agora_sp()
    variantes = variantes_wa_id(wa_id) or (wa_id,)
    transferido = (await db.execute(select(NatQualificacaoState.id).where(
        NatQualificacaoState.contact_wa_id.in_(variantes),
        NatQualificacaoState.etapa == "transferido_humano",
        NatQualificacaoState.transferido_em >= agora - JANELA_PAUSA).limit(1))).first()
    if transferido is not None:
        return True
    chave = chave_telefone(wa_id)
    if not chave:
        return False
    regua = (await db.execute(select(ReuniaoStatus.meeting_id).where(
        ReuniaoStatus.telefone_chave == chave,
        ReuniaoStatus.slot_inicio >= agora - JANELA_PAUSA,
        ReuniaoStatus.sdr_tratado_em.is_(None),
        (ReuniaoStatus.regua_encerrada_motivo == "humano")
        | (ReuniaoStatus.cancelado_motivo == "remarcar")).limit(1))).first()
    return regua is not None


# ==========================================================================================
# A REUNIÃO QUE BLOQUEIA O scheduleAdd
# ==========================================================================================

async def reuniao_que_bloqueia(wa_id: str, db: AsyncSession, *,
                               agora: datetime | None = None) -> ReuniaoStatus | None:
    """A reunião Vigente na Exact desta pessoa, se houver. É a que precisa ser cancelada.

    `exact_type`, e não `cancelado_motivo`: o corte e o "Preciso remarcar" cancelam só no Hub, e
    é a Exact que recusa. A mais recente vence (a pessoa remarca a última que marcou).
    """
    chave = chave_telefone(wa_id)
    if not chave:
        return None
    agora = agora or _agora_sp()
    return (await db.execute(select(ReuniaoStatus).where(
        ReuniaoStatus.telefone_chave == chave,
        ReuniaoStatus.exact_type == EXACT_TYPE_VIGENTE,
        ReuniaoStatus.slot_inicio >= agora - JANELA_VIGENTE)
        .order_by(ReuniaoStatus.registrado_em.desc().nullslast(),
                  ReuniaoStatus.slot_inicio.desc()).limit(1))).scalar_one_or_none()


async def ocupados_pendentes(db: AsyncSession, inicio: datetime, fim: datetime,
                             sales_rep_email: str) -> list[tuple[datetime, datetime]]:
    """Horários reservados por remarcação pendente DESTA consultora (decisão 3).

    Só enquanto a antiga está Vigente e a reserva não expirou. Quando a antiga vira Cancelada a
    reserva some, e é de propósito: o `remarcacao_retry` precisa ver o horário livre para
    marcá-lo. A janela entre o sync e o handler é de segundos.
    """
    from app.agendamento.consultoras import consultoras
    duracao = next((c.grade.duracao for c in consultoras()
                    if c.email.lower() == (sales_rep_email or "").lower()),
                   timedelta(minutes=45))
    agora = _agora_sp()
    res = await db.execute(select(ReuniaoStatus.slot_desejado_inicio).where(
        ReuniaoStatus.slot_desejado_inicio >= inicio,
        ReuniaoStatus.slot_desejado_inicio <= fim,
        ReuniaoStatus.slot_desejado_consultora == (sales_rep_email or "").lower(),
        ReuniaoStatus.exact_type == EXACT_TYPE_VIGENTE,
        ReuniaoStatus.remarcacao_expira_em > agora))
    return [(linha[0], linha[0] + duracao) for linha in res.all()]


def _limpar(r: ReuniaoStatus) -> None:
    r.slot_desejado_inicio = None
    r.slot_desejado_consultora = None
    r.remarcacao_expira_em = None


def _quando(slot: datetime) -> tuple[str, str]:
    from app.confirmacao import dia_extenso
    return dia_extenso(slot), f"{slot:%H:%M}"


# ==========================================================================================
# PASSO 2 — ESTACIONAR A ESCOLHA
# ==========================================================================================

async def estacionar(estado, slot, antiga: ReuniaoStatus, db: AsyncSession) -> None:
    """O lead escolheu `slot` (um `SlotDisponivel`), mas `antiga` está Vigente na Exact.

    Nada aqui chama a Exact para escrever: só a nota na timeline, que é best-effort.
    """
    from app import qualificacao_fluxo as qf
    from app import qualificacao_guard as guard
    from app.confirmacao import _nota
    from app.nat_scheduler import agendar as nat_agendar
    from app.nat_sender import enviar_nat
    from app.nat_flow import telefone_legivel

    agora = _agora_sp()
    inicio = slot.slot.inicio
    consultora = (slot.consultoras[0].email if slot.consultoras else "").lower() or None
    antiga.slot_desejado_inicio = inicio
    antiga.slot_desejado_consultora = consultora
    antiga.remarcacao_tentativas = 0
    antiga.remarcacao_expira_em = agora + VALIDADE_PENDENTE

    # O agente sai de cena ANTES de falar, como em `_fallback`: daqui em diante quem resolve é
    # o sync (ou um humano), e a próxima mensagem do lead não pode reabrir a oferta.
    await qf._descartar_fala_adiada(estado, "remarcação pendente", db)
    estado.etapa = qf.ETAPA_Q_CONCLUIDO
    estado.encerrado_em = agora
    estado.encerrado_motivo = ENCERRADO_REMARCACAO_PENDENTE
    await db.flush()
    await qf._cancelar_follow(estado.contact_wa_id, "remarcação pendente", db)
    await nat_agendar(KIND_REMARCACAO_EXPIRA, estado.contact_wa_id,
                      antiga.remarcacao_expira_em, {"meeting_id": antiga.meeting_id}, db)

    dia, hora = _quando(inicio)
    nome = await qf._nome(estado, db)
    saiu, motivo = await enviar_nat(
        estado.contact_wa_id, guard.ETAPA_CONVERSA, db, guard=guard.guard_de_despedida,
        corpo_livre=TEXTO_ANOTADO.format(dia=dia, hora=hora, nome=nome))
    await _nota(antiga, f"Remarcação pendente: {inicio:%d/%m %H:%M}")
    aviso = "" if saiu else f" ⚠️ O \"Anotei\" NÃO saiu para o lead ({motivo})."
    await notificar(
        estado.contact_wa_id, TIPO_NOTIF_REMARCACAO, str(antiga.meeting_id),
        "Remarcação pendente: cancele na Exact",
        f"{antiga.nome or nome} ({telefone_legivel(estado.contact_wa_id)}) escolheu "
        f"{inicio:%d/%m às %H:%M}. Cancele a reunião {antiga.meeting_id} "
        f"({antiga.slot_inicio:%d/%m %H:%M}) na Exact para o Hub remarcar.{aviso}", db)
    print(f"📌 remarcacao: {estado.contact_wa_id} escolheu {inicio:%d/%m %H:%M} "
          f"({consultora}); reunião {antiga.meeting_id} Vigente na Exact — pendente até "
          f"{antiga.remarcacao_expira_em:%d/%m %H:%M}")


# ==========================================================================================
# PASSO 3 — O SYNC VIU A ANTIGA CANCELADA
# ==========================================================================================

async def ao_cancelar(db: AsyncSession, meeting_id: int) -> bool:
    """Chamado pelo `reuniao_sync` em `Vigente -> Cancelada`. Só enfileira. Nunca levanta."""
    from app.nat_scheduler import agendar as nat_agendar
    try:
        # Savepoint: um erro de banco aqui não pode envenenar a transação do ciclo inteiro.
        async with db.begin_nested():
            r = (await db.execute(select(ReuniaoStatus).where(
                ReuniaoStatus.meeting_id == meeting_id))).scalar_one_or_none()
            if r is None or r.slot_desejado_inicio is None:
                return False
            wa = await _contato_da_remarcacao(r, db)
            if not wa:
                print(f"⚠️ remarcacao: reunião {meeting_id} pendente sem telefone legível")
                return False
            await nat_agendar(KIND_REMARCACAO_RETRY, wa, _agora_sp(),
                              {"meeting_id": meeting_id}, db)
            return True
    except Exception as e:
        print(f"⚠️ remarcacao: retry da reunião {meeting_id} não enfileirado "
              f"({type(e).__name__}: {e})")
        return False


async def _contato_da_remarcacao(r: ReuniaoStatus, db: AsyncSession) -> str | None:
    """O wa_id na grafia do contato que existe (o mesmo `canonizar` do webhook)."""
    from app.contatos import canonizar
    from app.exact_spotter import format_phone
    bruto = format_phone(r.telefone_bruto or "")
    return await canonizar(bruto, db) if bruto else None


async def _outra_vigente(r: ReuniaoStatus, db: AsyncSession, agora: datetime):
    """Reunião Vigente futura da mesma pessoa que NÃO é a antiga: alguém já remarcou à mão."""
    if not r.telefone_chave:
        return None
    return (await db.execute(select(ReuniaoStatus).where(
        ReuniaoStatus.telefone_chave == r.telefone_chave,
        ReuniaoStatus.meeting_id != r.meeting_id,
        ReuniaoStatus.exact_type == EXACT_TYPE_VIGENTE,
        ReuniaoStatus.slot_inicio > agora).limit(1))).scalar_one_or_none()


# ==========================================================================================
# PASSO 4 — CRIAR A NOVA
# ==========================================================================================

@registrar_handler(KIND_REMARCACAO_RETRY)
async def remarcacao_retry(acao: dict, db: AsyncSession) -> None:
    from app.agendamento import agendar as fluxo, disponibilidade
    from app.confirmacao import _nota
    from app.nat_scheduler import agendar as nat_agendar, payload_de

    agora = acao.get("agora") or _agora_sp()
    wa = acao["contact_wa_id"]
    mid = payload_de(acao).get("meeting_id")
    r = (await db.execute(select(ReuniaoStatus).where(
        ReuniaoStatus.meeting_id == mid))).scalar_one_or_none()
    if r is None or r.slot_desejado_inicio is None:
        raise AcaoIgnorada(f"reunião {mid!r} sem remarcação pendente")
    if r.exact_type != EXACT_TYPE_CANCELADA:
        raise AcaoIgnorada(f"reunião {mid} está {r.exact_type} na Exact — ainda não dá")

    outra = await _outra_vigente(r, db, agora)
    if outra is not None:
        # Um humano marcou a nova direto na Exact. Marcar a desejada criaria a segunda.
        _limpar(r)
        await _nota(r, f"Remarcação resolvida fora do Hub (reunião {outra.meeting_id})")
        print(f"↩️ remarcacao: {wa} já tem a reunião {outra.meeting_id} "
              f"({outra.slot_inicio:%d/%m %H:%M}) — não marca a desejada")
        return

    slot = r.slot_desejado_inicio
    slot_id = slot.isoformat(timespec="seconds")
    r.remarcacao_tentativas = (r.remarcacao_tentativas or 0) + 1
    livres = {d.id for d in await disponibilidade.slots_livres(db, usar_cache=False)}
    if slot - agora < ANTECEDENCIA_MINIMA or slot_id not in livres:
        await _reofertar(r, wa, db, f"o horário {slot:%d/%m %H:%M} não está mais livre")
        return

    estado = await _estado(wa, db)
    try:
        resultado = await _agendar_na_exact(fluxo, r, wa, slot_id, estado, db)
    except fluxo.SlotIndisponivel:
        await _reofertar(r, wa, db, f"o horário {slot:%d/%m %H:%M} foi ocupado na hora")
        return
    except Exception as e:
        erro = f"{type(e).__name__}: {e}"
        if r.remarcacao_tentativas < MAX_TENTATIVAS:
            await nat_agendar(KIND_REMARCACAO_RETRY, wa, agora + ESPERA_RETRY,
                              {"meeting_id": mid}, db)
            print(f"🔁 remarcacao: scheduleAdd de {wa} recusado ({erro}) — "
                  f"tentativa {r.remarcacao_tentativas + 1} em {ESPERA_RETRY}")
            return
        await _humano(r, wa, estado, db, f"a Exact recusou o agendamento 2 vezes ({erro})")
        return

    _limpar(r)
    if estado is not None:
        from app import qualificacao_fluxo as qf
        estado.agendamento_id = resultado.agendamento_id
        estado.etapa = qf.ETAPA_Q_CONCLUIDO
        estado.encerrado_motivo = "remarcada"
        estado.encerrado_em = agora
    await _nota(r, f"Remarcada para {slot:%d/%m %H:%M}")
    from app import confirmacao
    if not (confirmacao.flag_ligada() and confirmacao.telefone_permitido(wa)):
        # Com a régua ligada, a confirmação imediata dela já diz dia e hora (e pede o clique).
        dia, hora = _quando(slot)
        await confirmacao._responder(wa, TEXTO_REMARCADA.format(
            dia=dia, hora=hora, nome=await _primeiro_nome(r, wa, db)), db)
    await notificar(wa, TIPO_NOTIF_REMARCACAO, str(mid), "Remarcação feita pelo Hub",
                    f"{r.nome or wa}: reunião nova em {slot:%d/%m às %H:%M} "
                    f"(agendamento {resultado.agendamento_id}), no lugar da {mid}.", db,
                    com_ultima_mensagem=False)
    print(f"✅ remarcacao: {wa} remarcado para {slot:%d/%m %H:%M} "
          f"(agendamento {resultado.agendamento_id}, tentativa {r.remarcacao_tentativas})")


async def _agendar_na_exact(fluxo, r: ReuniaoStatus, wa: str, slot_id: str, estado,
                            db: AsyncSession):
    """`fluxo.agendar` numa sessão PRÓPRIA, pela mesma razão de `qualificacao_fluxo._agendar`
    (P0-A): ele commita a cada passo, e commitar a sessão do scheduler fecharia o savepoint do
    handler. Lead existente: `lead_id` presente pula o `LeadsAdd` (`lead_externo`)."""
    from app.database import async_session
    origem = extras = None
    if estado is not None:
        from app import qualificacao_fluxo as qf
        from app.qualificacao_dados import extras_brutos_da_lp
        origem = await qf._origem_do_agendamento(estado, db)
        extras = await extras_brutos_da_lp(estado.exact_lead_id, db)
    async with async_session() as db_agendamento:
        return await fluxo.agendar(
            db_agendamento, nome=r.nome or "Lead", email=None, telefone=wa, slot_id=slot_id,
            origem=origem, lead_id=r.lead_id, extras=extras or None, origem_ip=None)


async def _reofertar(r: ReuniaoStatus, wa: str, db: AsyncSession, porque: str) -> None:
    """Horário perdido: o agente oferece de novo. Sem tentativa sobrando (ou sem oferta), humano.

    A antiga já está Cancelada, então a próxima escolha do lead vai direto ao `scheduleAdd`
    (`reuniao_que_bloqueia` não acha mais nada).
    """
    if r.remarcacao_tentativas > MAX_TENTATIVAS:
        await _humano(r, wa, await _estado(wa, db), db, porque)
        return
    from app.qualificacao_fluxo import reabrir_para_oferta
    _limpar(r)
    if await reabrir_para_oferta(wa, r.lead_id, db, agendamento_antigo=r.agendamento_id,
                                 nome=r.nome):
        print(f"↩️ remarcacao: {wa}: {porque} — agente ofereceu de novo")
        return
    await _humano(r, wa, await _estado(wa, db), db, f"{porque}; e não houve oferta nova")


async def _humano(r: ReuniaoStatus, wa: str, estado, db: AsyncSession, motivo: str) -> None:
    """Desiste da remarcação automática: lead avisado, humano com o motivo verbatim."""
    from app.confirmacao import _nota, _responder
    _limpar(r)
    await _nota(r, f"Remarcação automática falhou: {motivo}")
    nome = await _primeiro_nome(r, wa, db)
    if estado is not None:
        from app import qualificacao_fluxo as qf
        await qf._fallback(estado, f"remarcação: {motivo}", db,
                           texto=TEXTO_HUMANO.format(nome=nome),
                           titulo="Remarcação não foi feita: assuma",
                           aviso_sdr=f"Reunião {r.meeting_id}: {motivo}.")
        return
    saiu = await _responder(wa, TEXTO_HUMANO.format(nome=nome), db)
    await notificar(wa, TIPO_NOTIF_REMARCACAO, str(r.meeting_id),
                    "Remarcação não foi feita: assuma",
                    f"Reunião {r.meeting_id}: {motivo}."
                    f"{'' if saiu else ' ⚠️ O aviso ao lead NÃO saiu.'}", db)


# ==========================================================================================
# PASSO 5 — EXPIRAÇÃO
# ==========================================================================================

@registrar_handler(KIND_REMARCACAO_EXPIRA)
async def remarcacao_expira(acao: dict, db: AsyncSession) -> None:
    """24h depois de estacionar. Agendado no `nat_scheduler`, e não dentro do `reuniao_sync`:
    o sync não manda mensagem ao lead (cabeçalho dele), e a fila já tem horário e retentativa."""
    from app.nat_scheduler import payload_de
    agora = acao.get("agora") or _agora_sp()
    wa = acao["contact_wa_id"]
    mid = payload_de(acao).get("meeting_id")
    r = (await db.execute(select(ReuniaoStatus).where(
        ReuniaoStatus.meeting_id == mid))).scalar_one_or_none()
    if r is None or r.slot_desejado_inicio is None:
        raise AcaoIgnorada(f"reunião {mid!r} sem remarcação pendente (já resolvida)")
    if r.exact_type != EXACT_TYPE_VIGENTE:
        raise AcaoIgnorada(f"reunião {mid} já está {r.exact_type}: o retry é quem resolve")
    if r.remarcacao_expira_em and r.remarcacao_expira_em > agora:
        raise AcaoIgnorada(f"reserva vale até {r.remarcacao_expira_em:%d/%m %H:%M}")
    await _humano(r, wa, await _estado(wa, db), db,
                  f"ninguém cancelou a reunião {mid} na Exact em 24h")


# ==========================================================================================
# AUXILIARES
# ==========================================================================================

async def _estado(wa: str, db: AsyncSession):
    from app.qualificacao_fluxo import estado_de      # já procura nas duas grafias
    return await estado_de(wa, db)


async def _primeiro_nome(r: ReuniaoStatus, wa: str, db: AsyncSession) -> str:
    from app.confirmacao import _nome
    return await _nome(r, wa, db)
