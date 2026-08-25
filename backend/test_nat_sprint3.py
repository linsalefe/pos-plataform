"""Blocos 5 e 7 da NAT: agendador, transferência, SLA, escalonamento e o botão Assumir.

Rodar: cd backend && venv/bin/python test_nat_sprint3.py

NADA É ENVIADO E NADA É GRAVADO. Sem conexão de banco, sem httpx, sem rede: a sessão é um
dublê em memória (SessaoFalsa) e a fila do agendador é uma lista (FilaFalsa). Mesmo padrão dos
outros suites do projeto.

DIVISÃO DE TRABALHO, para não fingir cobertura que não existe:

  * A SEMÂNTICA DE BANCO — SELECT ... FOR UPDATE SKIP LOCKED com duas sessões concorrentes,
    e o índice único parcial recusando o segundo `pendente` — só o Postgres responde, e foi
    provada no smoke da Fase 3 contra o banco real. Um dublê que "confirmasse" SKIP LOCKED
    estaria confirmando a si mesmo.
  * A LÓGICA — transições de status, contagem de tentativas, execução única, ordem dos
    savepoints, degraus do escalonamento, idempotência do /assumir — é o que este arquivo
    cobre, e cobre de verdade: _executar_acao, processar_pendentes, transferir_para_sdr,
    sla_check e assumir_ligacao rodam de fato, não são mockados.

  1. agendar cria pendente; job executa e marca executado
  2. job roda duas vezes -> a ação executa UMA vez
  3. ação que falha 3x -> falhou, sem loop (e uma passada gasta UMA tentativa)
  4. cancelar remove o pendente
  5. entrada em aguardando_ligacao -> notificação criada + sla_check agendado
  6. falha na chamada ao Exact -> notificação ao SDR acontece mesmo assim
  7. sla_check com lead já assumido -> nada
  8. sla_check nível 0 -> notifica o OUTRO SDR e reagenda
  9. sla_check nível 1 -> notifica a gestão e NÃO reagenda
 10. sla_check nível 2 -> nada (não escala infinito)
 11. assumir cancela o sla_check pendente
 12. assumir duas vezes -> idempotente
 12b. assumir encerra o fluxo: etapa vira encerrado, SLA para, NAT não interfere mais
 13. teto por hora conta só nat_etapa IS NOT NULL (envio manual de SDR não conta)
 14. sdr_user_id nulo na transferência -> fallback para a gestão (Bloco 5, ponto 4)
"""
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql

from app import nat_copy, nat_flow, nat_scheduler as ns, nat_sla, nat_routes
from app.models import (ACAO_CANCELADO, ACAO_EXECUTADO, ACAO_FALHOU, ACAO_PENDENTE,
                        ETAPA_AGUARDANDO_LIGACAO, ETAPA_AGUARDANDO_MOTIVACAO,
                        ETAPA_ENCERRADO, KIND_SLA_CHECK, MAX_TENTATIVAS_ACAO, Message,
                        Notification)
from app.nat_guard import GESTOR_USER_ID

AGORA = datetime(2026, 7, 26, 15, 0, 0)
VENCIDA = AGORA - timedelta(minutes=5)

falhas = []


def check(nome, condicao, detalhe=""):
    print(f"  {'✅' if condicao else '❌'} {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


# ==========================================================================================
# DUBLÊS
# ==========================================================================================

class ResultadoFalso:
    def __init__(self, valor=None, rowcount=0):
        self._valor = valor
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._valor

    def scalar(self):
        return self._valor

    def first(self):
        return self._valor


class SavepointFalso:
    """Emula begin_nested: na exceção, desfaz o que foi adicionado DENTRO dele.

    Desfazer de verdade (e não só contar) é o que dá sentido ao teste 6: sem isso, "a
    notificação sobreviveu" passaria mesmo num código que a perdesse.
    """
    def __init__(self, sessao):
        self.sessao = sessao

    async def __aenter__(self):
        self.marca = len(self.sessao.adicionados)
        self.sessao.savepoints += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            del self.sessao.adicionados[self.marca:]
            self.sessao.rollbacks += 1
        return False  # propaga, como o savepoint real


class SessaoFalsa:
    """Sessão em memória. Nenhuma conexão aberta, nada gravado."""
    def __init__(self, resposta_execute=None):
        self.adicionados = []
        self.statements = []
        self.savepoints = 0
        self.rollbacks = 0
        self.commits = 0
        self._proximo_id = 1
        self._resposta = resposta_execute

    def add(self, obj):
        self.adicionados.append(obj)

    async def flush(self):
        for o in self.adicionados:
            if getattr(o, "id", None) is None:
                o.id = self._proximo_id
                self._proximo_id += 1

    async def execute(self, stmt, *a, **kw):
        self.statements.append(stmt)
        if callable(self._resposta):
            return self._resposta(stmt)
        return ResultadoFalso()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def refresh(self, obj):
        pass

    def begin_nested(self):
        return SavepointFalso(self)

    def notificacoes(self):
        return [o for o in self.adicionados if isinstance(o, Notification)]


def fabrica_de_sessao(sessao):
    """Substituto de app.database.async_session, que é usado como `async with ...()`."""
    class CM:
        async def __aenter__(self):
            return sessao

        async def __aexit__(self, *a):
            return False
    return lambda: CM()


class FilaFalsa:
    """A fila do agendador em memória, com o comportamento de _proxima_acao e _finalizar.

    Só estes DOIS pontos são substituídos. _executar_acao, processar_pendentes, _snapshot, o
    despacho por kind e o savepoint de falha rodam de verdade.
    """
    def __init__(self):
        self.acoes = []
        self._id = 1

    def inserir(self, kind=KIND_SLA_CHECK, wa="5511900000001", run_at=VENCIDA,
                status=ACAO_PENDENTE, attempts=0, payload=None):
        acao = SimpleNamespace(
            id=self._id, kind=kind, contact_wa_id=wa, run_at=run_at, status=status,
            attempts=attempts, payload=json.dumps(payload) if payload else None,
            processed_at=None, motivo=None)
        self.acoes.append(acao)
        self._id += 1
        return acao

    def por_id(self, acao_id):
        return next(a for a in self.acoes if a.id == acao_id)

    async def proxima_acao(self, db, corte):
        vencidas = [a for a in self.acoes
                    if a.status == ACAO_PENDENTE and a.run_at <= corte]
        vencidas.sort(key=lambda a: a.run_at)
        return vencidas[0] if vencidas else None

    async def finalizar(self, db, acao_id, status, agora, attempts=None, run_at=None,
                        motivo=None):
        acao = self.por_id(acao_id)
        acao.status = status
        acao.motivo = motivo
        if attempts is not None:
            acao.attempts = attempts
        if run_at is not None:
            acao.run_at = run_at
        if status != ACAO_PENDENTE:
            acao.processed_at = agora

    def patches(self):
        return (patch.object(ns, "_proxima_acao", new=self.proxima_acao),
                patch.object(ns, "_finalizar", new=self.finalizar))


def _estado(etapa=ETAPA_AGUARDANDO_LIGACAO, sdr=4, assumido_por=None, nivel=0,
            wa="5511900000001", exact_lead_id=51000001, tentativas=0):
    # `tentativas_contato` espelha a coluna que o Bloco 6 passou a consumir (o payload do
    # /estado e o roteamento de clique leem esse campo). Um dublê sem ele deixaria de
    # exercitar o código real e estouraria AttributeError dentro do try/except do fluxo —
    # que é o pior desfecho num teste: verde por engano.
    return SimpleNamespace(
        contact_wa_id=wa, etapa=etapa, sdr_user_id=sdr, exact_lead_id=exact_lead_id,
        tentativas_contato=tentativas, assumido_por=assumido_por,
        assumido_em=(AGORA if assumido_por else None),
        escalonamento_nivel=nivel, transferido_em=AGORA - timedelta(minutes=2),
        ultimo_wa_message_id=None, horario_preferencial=None)


DADOS_LEAD = {"nome": "Maria Lidia", "curso": "Saúde Mental", "formacao": ""}


# ==========================================================================================
# 1-4: AGENDADOR
# ==========================================================================================

async def teste_1_agendar_e_executar():
    print("1) agendar cria pendente; job executa e marca executado")
    sessao = SessaoFalsa()

    # agendar() de verdade, com cancelar dublado (o cancelamento real é o teste 4).
    with patch.object(ns, "cancelar", new=AsyncMock(return_value=0)):
        acao_id = await ns.agendar("__t__", "5511900000001", VENCIDA, {"a": 1}, sessao)
    criada = sessao.adicionados[0]
    check("agendar devolveu id e criou a ação", acao_id == 1 and criada.status == ACAO_PENDENTE,
          f"id={acao_id} status={criada.status} attempts={criada.attempts}")
    check("payload serializado como JSON", json.loads(criada.payload) == {"a": 1},
          criada.payload)

    fila = FilaFalsa()
    fila.inserir(kind="__t__")
    chamadas = []

    async def handler(acao, db):
        chamadas.append(acao["id"])

    p1, p2 = fila.patches()
    with p1, p2, patch.dict(ns._HANDLERS, {"__t__": handler}), \
         patch.object(ns, "async_session", new=fabrica_de_sessao(SessaoFalsa())):
        resumo = await ns.processar_pendentes(agora=AGORA)

    check("handler executado 1x", chamadas == [1], f"chamadas={chamadas}")
    check("status=executado + processed_at", fila.por_id(1).status == ACAO_EXECUTADO
          and fila.por_id(1).processed_at == AGORA, f"{fila.por_id(1)}")
    check("resumo do ciclo", resumo == {ACAO_EXECUTADO: 1}, f"{resumo}")


async def teste_2_nao_executa_duas_vezes():
    print("2) job roda duas vezes -> a ação executa UMA vez")
    fila = FilaFalsa()
    fila.inserir(kind="__t__")
    chamadas = []

    async def handler(acao, db):
        chamadas.append(acao["id"])

    p1, p2 = fila.patches()
    with p1, p2, patch.dict(ns._HANDLERS, {"__t__": handler}), \
         patch.object(ns, "async_session", new=fabrica_de_sessao(SessaoFalsa())):
        await ns.processar_pendentes(agora=AGORA)
        segundo = await ns.processar_pendentes(agora=AGORA)

    check("handler chamado UMA vez nas duas passadas", chamadas == [1], f"chamadas={chamadas}")
    check("segunda passada não achou nada", segundo == {}, f"{segundo}")


async def teste_3_falha_tres_vezes():
    print("3) ação que falha 3x -> falhou, sem loop")
    fila = FilaFalsa()
    fila.inserir(kind="__t__")
    chamadas = []

    async def handler_ruim(acao, db):
        chamadas.append(acao["attempts"])
        raise RuntimeError("falha proposital")

    p1, p2 = fila.patches()
    with p1, p2, patch.dict(ns._HANDLERS, {"__t__": handler_ruim}), \
         patch.object(ns, "async_session", new=fabrica_de_sessao(SessaoFalsa())):
        # UMA passada gasta UMA tentativa: o run_at empurrado tira a ação da passada atual.
        # Foi exatamente aqui que o smoke da Fase 3 pegou o bug das 3 tentativas em rajada.
        await ns.processar_pendentes(agora=AGORA)
        depois_de_1 = (fila.por_id(1).status, fila.por_id(1).attempts, fila.por_id(1).run_at)

        await ns.processar_pendentes(agora=AGORA + timedelta(seconds=61))
        depois_de_2 = (fila.por_id(1).status, fila.por_id(1).attempts)

        await ns.processar_pendentes(agora=AGORA + timedelta(seconds=122))
        depois_de_3 = (fila.por_id(1).status, fila.por_id(1).attempts)

        await ns.processar_pendentes(agora=AGORA + timedelta(seconds=183))

    check("1ª passada: 1 tentativa, segue pendente",
          depois_de_1[:2] == (ACAO_PENDENTE, 1), f"{depois_de_1[:2]}")
    check("run_at empurrado para o futuro", depois_de_1[2] > AGORA,
          f"run_at={depois_de_1[2]:%H:%M:%S} (era {VENCIDA:%H:%M:%S})")
    check("2ª passada: 2 tentativas, ainda pendente",
          depois_de_2 == (ACAO_PENDENTE, 2), f"{depois_de_2}")
    check(f"3ª passada: falhou com attempts={MAX_TENTATIVAS_ACAO}",
          depois_de_3 == (ACAO_FALHOU, MAX_TENTATIVAS_ACAO), f"{depois_de_3}")
    check("handler chamado exatamente 3x — sem loop", len(chamadas) == 3, f"{chamadas}")


async def teste_4_cancelar():
    print("4) cancelar remove o pendente")
    capturado = {}

    def resposta(stmt):
        capturado["sql"] = str(stmt.compile(dialect=postgresql.dialect(),
                                            compile_kwargs={"literal_binds": True}))
        return ResultadoFalso(rowcount=1)

    sessao = SessaoFalsa(resposta_execute=resposta)
    n = await ns.cancelar(KIND_SLA_CHECK, "5511900000001", sessao)
    sql = " ".join(capturado["sql"].split())

    check("devolveu a quantidade cancelada", n == 1, f"n={n}")
    check("é UPDATE ... SET status='cancelado'",
          "UPDATE nat_scheduled_actions" in sql and "status='cancelado'" in sql, sql[:110])
    check("só mexe em quem está pendente", "status = 'pendente'" in sql, sql[-120:])
    check("filtra por kind E contato",
          "kind = 'sla_check'" in sql and "contact_wa_id = '5511900000001'" in sql)

    vazia = SessaoFalsa(resposta_execute=lambda s: ResultadoFalso(rowcount=0))
    check("nada pendente devolve 0 (não é erro)",
          await ns.cancelar(KIND_SLA_CHECK, "x", vazia) == 0)


# ==========================================================================================
# 5-6, 14: TRANSFERÊNCIA
# ==========================================================================================

async def _roda_transferencia(state, *, exact_falha=False, agendar_falha=False,
                              sdr_existe=True):
    sessao = SessaoFalsa()
    agendados = []

    async def agendar_falso(kind, wa, run_at, payload, db):
        if agendar_falha:
            raise RuntimeError("índice único: já existe pendente")
        agendados.append((kind, wa, run_at, payload))
        return 99

    async def timeline_falsa(lead_id, texto, *, timeout=15):
        if exact_falha:
            raise RuntimeError("Exact fora do ar")
        timeline.append((lead_id, texto, timeout))
        return True

    timeline = []

    async def usuario_existe_falso(uid, db):
        if uid == GESTOR_USER_ID:
            return True
        return sdr_existe and uid is not None

    with patch.object(nat_flow, "_dados_do_lead", new=AsyncMock(return_value=DADOS_LEAD)), \
         patch.object(nat_flow, "usuario_existe", new=usuario_existe_falso), \
         patch.object(nat_flow, "_agora_sp", return_value=AGORA), \
         patch("app.nat_scheduler.agendar", new=agendar_falso), \
         patch("app.exact_spotter.add_timeline_comment", new=timeline_falsa):
        ok = await nat_flow.transferir_para_sdr(state, "quero atender melhor", "wamid.T1",
                                               sessao)
    return ok, sessao, agendados, timeline


async def teste_5_transferencia():
    print("5) entrada em aguardando_ligacao -> notificação criada + sla_check agendado")
    state = _estado()
    ok, sessao, agendados, timeline = await _roda_transferencia(state)

    notifs = sessao.notificacoes()
    check("transferir_para_sdr devolveu True", ok is True)
    check("UMA notificação criada", len(notifs) == 1, f"{len(notifs)}")
    if notifs:
        n = notifs[0]
        check("destinatário é o SDR dono", n.user_id == 4, f"user_id={n.user_id}")
        check("tipo é nat_transferencia", n.type == nat_flow.TIPO_NOTIF_TRANSFERENCIA, n.type)
        check("ref é a mensagem do lead", n.ref == "wamid.T1", n.ref)
        check("telefone no TÍTULO (não truncado no sino)", "+55 11 90000-0001" in n.title,
              n.title)
        check("telefone no COMEÇO do corpo (o sino trunca em ~50 ch)",
              n.body.startswith("+55 11 90000-0001"), n.body[:60])
        check("corpo tem curso e o que o lead respondeu",
              "Saúde Mental" in n.body and "quero atender melhor" in n.body, n.body)
    check("transferido_em carimbado", state.transferido_em == AGORA, f"{state.transferido_em}")
    check("timeline anotada com timeout de 5s",
          len(timeline) == 1 and timeline[0][2] == nat_flow.TIMEOUT_TIMELINE_SEGUNDOS,
          f"{timeline[0][2] if timeline else 'nada'}s")
    check("timeline diz que a NAT transferiu, com horário",
          bool(timeline) and "NAT transferiu" in timeline[0][1] and "15:00" in timeline[0][1],
          timeline[0][1][:70] if timeline else "")
    check("sla_check agendado para +2min",
          len(agendados) == 1 and agendados[0][0] == KIND_SLA_CHECK
          and agendados[0][2] == AGORA + timedelta(minutes=nat_flow.SLA_LIGACAO_MINUTOS),
          f"{agendados}")
    check("3 savepoints, nenhum rollback", sessao.savepoints == 3 and sessao.rollbacks == 0,
          f"savepoints={sessao.savepoints} rollbacks={sessao.rollbacks}")


async def teste_6_exact_falha():
    print("6) falha na chamada ao Exact -> notificação ao SDR acontece mesmo assim")
    state = _estado()
    ok, sessao, agendados, timeline = await _roda_transferencia(state, exact_falha=True)

    check("transferência ainda é válida", ok is True)
    check("notificação ao SDR SOBREVIVEU ao rollback do savepoint da Exact",
          len(sessao.notificacoes()) == 1, f"{len(sessao.notificacoes())}")
    check("transferido_em permanece", state.transferido_em == AGORA)
    check("nada foi anotado na timeline", timeline == [])
    check("o savepoint da Exact foi revertido (1 rollback)", sessao.rollbacks == 1,
          f"rollbacks={sessao.rollbacks}")
    check("sla_check agendado apesar da falha da Exact", len(agendados) == 1, f"{agendados}")

    # E o inverso: falha no AGENDAMENTO não pode custar a notificação.
    state2 = _estado()
    ok2, sessao2, agendados2, _ = await _roda_transferencia(state2, agendar_falha=True)
    check("falha no sla_check NÃO derruba a notificação",
          ok2 is True and len(sessao2.notificacoes()) == 1, f"{len(sessao2.notificacoes())}")
    check("nenhum sla_check ficou agendado", agendados2 == [])


async def teste_14_sem_sdr():
    print("14) sdr_user_id nulo -> fallback para a gestão")
    state = _estado(sdr=None)
    ok, sessao, agendados, _ = await _roda_transferencia(state, sdr_existe=False)
    notifs = sessao.notificacoes()

    check("notificou alguém", ok is True and len(notifs) == 1, f"{len(notifs)}")
    if notifs:
        check(f"destinatário é a gestão (id={GESTOR_USER_ID})",
              notifs[0].user_id == GESTOR_USER_ID, f"user_id={notifs[0].user_id}")
        check("título deixa claro que é lead SEM SDR", "SEM SDR" in notifs[0].title,
              notifs[0].title)
        check("corpo explica o fallback", "sem SDR atribuído" in notifs[0].body,
              notifs[0].body)
    check("SLA armado igual", len(agendados) == 1)


# ==========================================================================================
# 7-10: SLA E ESCALONAMENTO
# ==========================================================================================

async def _roda_sla(state, nivel_dono="Valéria"):
    sessao = SessaoFalsa(resposta_execute=lambda s: ResultadoFalso(state))
    agendados = []

    async def agendar_falso(kind, wa, run_at, payload, db):
        agendados.append((kind, wa, run_at, payload))
        return 99

    async def usuario_existe_falso(uid, db):
        return uid is not None

    with patch.object(nat_sla, "_dados_do_lead", new=AsyncMock(return_value=DADOS_LEAD)), \
         patch.object(nat_sla, "_nome_do_usuario", new=AsyncMock(return_value=nivel_dono)), \
         patch.object(nat_sla, "usuario_existe", new=usuario_existe_falso), \
         patch.object(nat_sla, "agendar", new=agendar_falso):
        acao = {"id": 7, "kind": KIND_SLA_CHECK, "contact_wa_id": "5511900000001",
                "run_at": VENCIDA, "payload": None, "attempts": 0, "agora": AGORA}
        await nat_sla.sla_check(acao, sessao)
    return sessao, agendados


async def teste_7_ja_assumido():
    print("7) sla_check com lead já assumido -> nada")
    state = _estado(assumido_por=4)
    sessao, agendados = await _roda_sla(state)
    check("nenhuma notificação", sessao.notificacoes() == [])
    check("não reagendou", agendados == [])
    check("nível intacto", state.escalonamento_nivel == 0, f"{state.escalonamento_nivel}")

    # As outras duas saídas de "nada a fazer".
    fora = _estado(etapa=ETAPA_AGUARDANDO_MOTIVACAO)
    s2, a2 = await _roda_sla(fora)
    check("etapa diferente de aguardando_ligacao -> nada",
          s2.notificacoes() == [] and a2 == [])

    sem_estado = SessaoFalsa(resposta_execute=lambda s: ResultadoFalso(None))
    await nat_sla.sla_check({"id": 1, "contact_wa_id": "x", "agora": AGORA, "kind": "k",
                             "run_at": VENCIDA, "payload": None, "attempts": 0}, sem_estado)
    check("sem estado de fluxo -> nada", sem_estado.notificacoes() == [])


async def teste_8_nivel_zero():
    print("8) sla_check nível 0 -> notifica o OUTRO SDR e reagenda")
    state = _estado(sdr=4, nivel=0)
    sessao, agendados = await _roda_sla(state)
    notifs = sessao.notificacoes()

    check("UMA notificação", len(notifs) == 1, f"{len(notifs)}")
    if notifs:
        check("foi para o OUTRO SDR (dono=4 -> 5)", notifs[0].user_id == 5,
              f"user_id={notifs[0].user_id}")
        check("tipo nat_sla_sdr", notifs[0].type == nat_sla.TIPO_NOTIF_SLA_SDR)
        check("título diz que é ESCALONAMENTO, não lead novo",
              "SLA estourado" in notifs[0].title, notifs[0].title)
        check("corpo diz quem não assumiu", "Valéria não assumiu" in notifs[0].body,
              notifs[0].body)
    check("nível subiu 0 -> 1", state.escalonamento_nivel == nat_sla.NIVEL_OUTRO_SDR,
          f"{state.escalonamento_nivel}")
    check("REAGENDOU +2min",
          len(agendados) == 1
          and agendados[0][2] == AGORA + timedelta(minutes=nat_flow.SLA_LIGACAO_MINUTOS),
          f"{agendados}")
    check("dono=5 escalona para 4 (simétrico)", nat_sla.outro_sdr(5) == 4)

    # LEAD SEM SDR: não existe "o outro", mas existem OS DOIS — e são eles que ligam.
    sem_dono = _estado(sdr=None, nivel=0)
    s2, a2 = await _roda_sla(sem_dono, nivel_dono="sem SDR")
    destinos = sorted(n.user_id for n in s2.notificacoes())

    check("sem SDR dono -> avisa AMBOS os SDRs (4 e 5)", destinos == [4, 5], f"{destinos}")
    check("NÃO notifica a gestão de novo (já avisada na transferência)",
          GESTOR_USER_ID not in destinos, f"{destinos}")
    check("as duas são do tipo nat_sla_sdr",
          all(n.type == nat_sla.TIPO_NOTIF_SLA_SDR for n in s2.notificacoes()))
    if s2.notificacoes():
        n = s2.notificacoes()[0]
        check("título diz que é lead SEM SDR", "SEM SDR" in n.title, n.title)
        check("corpo diz que ninguém é dono", "ninguém é dono" in n.body, n.body)
        check("corpo NÃO afirma que alguém deixou de assumir",
              "não assumiu" not in n.body, n.body)
    check("vai para o nível 2 e encerra, sem reagendar",
          sem_dono.escalonamento_nivel == nat_sla.NIVEL_GESTAO and a2 == [],
          f"nivel={sem_dono.escalonamento_nivel} agendados={a2}")

    # E uma ação atrasada que chegue depois não pode reabrir nada.
    s3, a3 = await _roda_sla(sem_dono, nivel_dono="sem SDR")
    check("ação atrasada no nível 2 não notifica nem reagenda",
          s3.notificacoes() == [] and a3 == [])


async def teste_9_nivel_um():
    print("9) sla_check nível 1 -> notifica a gestão e NÃO reagenda")
    state = _estado(sdr=4, nivel=1)
    sessao, agendados = await _roda_sla(state)
    notifs = sessao.notificacoes()

    check("UMA notificação", len(notifs) == 1, f"{len(notifs)}")
    if notifs:
        check(f"foi para a gestão (id={GESTOR_USER_ID})",
              notifs[0].user_id == GESTOR_USER_ID, f"user_id={notifs[0].user_id}")
        check("tipo nat_sla_gestao", notifs[0].type == nat_sla.TIPO_NOTIF_SLA_GESTAO)
        check("título diz que ninguém assumiu", "ninguém assumiu" in notifs[0].title,
              notifs[0].title)
    check("nível subiu 1 -> 2", state.escalonamento_nivel == nat_sla.NIVEL_GESTAO,
          f"{state.escalonamento_nivel}")
    check("NÃO reagendou — é o que encerra o ciclo", agendados == [], f"{agendados}")


async def teste_10_nivel_dois():
    print("10) sla_check nível 2 -> nada (não escala infinito)")
    state = _estado(sdr=4, nivel=2)
    sessao, agendados = await _roda_sla(state)
    check("nenhuma notificação", sessao.notificacoes() == [])
    check("não reagendou", agendados == [])
    check("nível permanece 2", state.escalonamento_nivel == 2)


# ==========================================================================================
# 11-12: BOTÃO ASSUMIR
# ==========================================================================================

async def _roda_assumir(state, user_id=5, nome="Thobias", cancelados=1):
    sessao = SessaoFalsa()
    canceladas = []

    async def cancelar_falso(kind, wa, db):
        canceladas.append((kind, wa))
        return cancelados

    with patch.object(nat_routes, "_estado", new=AsyncMock(return_value=state)), \
         patch.object(nat_routes, "_nome", new=AsyncMock(return_value=nome)), \
         patch.object(nat_routes, "_agora_sp", return_value=AGORA), \
         patch("app.nat_scheduler.cancelar", new=cancelar_falso):
        resp = await nat_routes.assumir_ligacao(
            state.contact_wa_id, sessao, SimpleNamespace(id=user_id, name=nome))
    return resp, sessao, canceladas


async def teste_11_assumir_cancela_sla():
    print("11) assumir cancela o sla_check pendente")
    state = _estado()
    resp, sessao, canceladas = await _roda_assumir(state)

    check("assumido_por = usuário logado", state.assumido_por == 5, f"{state.assumido_por}")
    check("assumido_em carimbado", state.assumido_em == AGORA, f"{state.assumido_em}")
    check("cancelou o sla_check DESTE contato",
          canceladas == [(KIND_SLA_CHECK, "5511900000001")], f"{canceladas}")
    check("resposta informa quantos foram cancelados", resp["cancelados"] == 1, f"{resp}")
    check("pode_assumir virou False", resp["pode_assumir"] is False)
    check("commit uma vez", sessao.commits == 1, f"{sessao.commits}")

    # Cancelamento falhando não pode custar o carimbo — é ele que para o relógio.
    state2 = _estado()
    sessao2 = SessaoFalsa()

    async def cancelar_ruim(kind, wa, db):
        raise RuntimeError("banco recusou")

    with patch.object(nat_routes, "_estado", new=AsyncMock(return_value=state2)), \
         patch.object(nat_routes, "_nome", new=AsyncMock(return_value="Thobias")), \
         patch.object(nat_routes, "_agora_sp", return_value=AGORA), \
         patch("app.nat_scheduler.cancelar", new=cancelar_ruim):
        await nat_routes.assumir_ligacao(state2.contact_wa_id, sessao2,
                                         SimpleNamespace(id=5, name="Thobias"))
    check("falha no cancelamento preserva assumido_por (o handler é a rede)",
          state2.assumido_por == 5, f"{state2.assumido_por}")


async def teste_12_assumir_idempotente():
    print("12) assumir duas vezes -> idempotente")
    state = _estado()
    await _roda_assumir(state, user_id=5, nome="Thobias")
    primeiro_por, primeiro_em = state.assumido_por, state.assumido_em

    # Segunda chamada, por OUTRA pessoa: não pode tomar o lead de quem assumiu primeiro.
    resp2, sessao2, canceladas2 = await _roda_assumir(state, user_id=4, nome="Valéria")

    check("devolveu ja_assumido=True, sem erro", resp2["ja_assumido"] is True, f"{resp2}")
    check("NÃO sobrescreveu quem assumiu primeiro",
          state.assumido_por == primeiro_por and state.assumido_em == primeiro_em,
          f"assumido_por={state.assumido_por}")
    check("não tentou cancelar de novo", canceladas2 == [], f"{canceladas2}")
    check("não reabriu nada (pode_assumir segue False)", resp2["pode_assumir"] is False)
    check("nenhum savepoint na segunda chamada", sessao2.savepoints == 0,
          f"{sessao2.savepoints}")


async def teste_12b_assumir_encerra_o_fluxo():
    """Fase 3 do sprint de ativação: assumir é a ÚNICA saída do fluxo.

    Antes, `assumir` gravava assumido_por e deixava a etapa em aguardando_ligacao — o lead
    ficava preso ali para sempre e todo clique posterior dele era descartado em silêncio,
    com um humano já conduzindo a conversa.
    """
    print("12b) assumir encerra o fluxo e devolve o lead ao humano")
    state = _estado()
    resp, _, _ = await _roda_assumir(state, user_id=5, nome="Thobias")

    check("etapa virou encerrado", state.etapa == ETAPA_ENCERRADO, f"{state.etapa}")
    check("quem assumiu segue registrado", state.assumido_por == 5, f"{state.assumido_por}")
    check("a resposta ao frontend já traz a etapa nova",
          resp["etapa"] == ETAPA_ENCERRADO, f"{resp['etapa']}")
    check("botão some (pode_assumir False)", resp["pode_assumir"] is False)
    check("selo de quem assumiu aparece (assumido_por preenchido)",
          resp["assumido_por"] == 5 and resp["assumido_por_nome"], f"{resp}")

    # A segunda rede: mesmo que o cancelamento do sla_check tenha falhado, o handler agora
    # para na PRIMEIRA das suas três saídas de "nada a fazer" — a etapa mudou.
    sessao = SessaoFalsa()
    sessao._resposta = lambda s: ResultadoFalso(state)
    await nat_sla.sla_check({"contact_wa_id": state.contact_wa_id, "agora": AGORA, "id": 1},
                            sessao)
    check("sla_check não escalona lead encerrado",
          [o for o in sessao.adicionados if isinstance(o, Notification)] == [],
          "notificou alguém")

    # E a NAT sai do caminho: clique e texto do lead não disparam mais nada.
    db = MagicMock()
    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock(return_value=True)) as spy:
        destino_clique = await nat_flow.processar_clique(
            {"contact_wa_id": state.contact_wa_id, "wa_message_id": "wamid.DEPOIS",
             "button_payload": nat_copy.NAT_SIM, "button_text": "Sim",
             "source": "template"}, db)
        destino_texto = await nat_flow.processar_texto(
            state.contact_wa_id, "obrigada!", "wamid.DEPOIS2", db)

    check("clique após encerrado -> ignorado sem erro", destino_clique is None,
          f"{destino_clique}")
    check("texto após encerrado -> ignorado sem erro", destino_texto is None,
          f"{destino_texto}")
    check("NADA foi enviado ao lead depois de encerrado", spy.await_count == 0,
          f"{spy.await_count} envios")
    check("etapa continua encerrado", state.etapa == ETAPA_ENCERRADO, f"{state.etapa}")


# ==========================================================================================
# 13: TETO POR HORA
# ==========================================================================================

async def teste_13_teto_conta_so_nat():
    print("13) teto por hora conta só nat_etapa IS NOT NULL")
    from app.nat_guard import contar_envios_nat_ultima_hora, COLUNA_MARCADOR_ENVIO_NAT

    capturado = {}

    def resposta(stmt):
        capturado["sql"] = " ".join(str(stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).split())
        return ResultadoFalso(0)

    sessao = SessaoFalsa(resposta_execute=resposta)
    total = await contar_envios_nat_ultima_hora(sessao)
    sql = capturado["sql"]

    check("marcador é a coluna nat_etapa", COLUNA_MARCADOR_ENVIO_NAT == "nat_etapa",
          repr(COLUNA_MARCADOR_ENVIO_NAT))
    check("query filtra nat_etapa IS NOT NULL", "nat_etapa IS NOT NULL" in sql, sql[-90:])
    check("query filtra outbound", "direction = 'outbound'" in sql)
    check("query tem o corte de 1 hora", "timestamp >" in sql)
    check("NÃO usa sent_by_ai (a coluna morta)", "sent_by_ai" not in sql)
    check("devolve inteiro", total == 0 and isinstance(total, int))

    # O que a NAT grava x o que os outros caminhos gravam.
    da_nat = Message(contact_wa_id="x", direction="outbound", message_type="text",
                     content="oi", nat_etapa="nat_confirma_transferencia")
    manual = Message(contact_wa_id="x", direction="outbound", message_type="text",
                     content="resposta do SDR")           # como routes.py cria
    massa = Message(contact_wa_id="x", direction="outbound", message_type="template",
                    content="campanha")                    # como exact_routes.py cria

    check("envio da NAT carrega a etapa -> É contado",
          da_nat.nat_etapa == "nat_confirma_transferencia", f"{da_nat.nat_etapa!r}")
    check("resposta manual do SDR fica NULL -> NÃO é contada", manual.nat_etapa is None)
    check("disparo em massa fica NULL -> NÃO é contado", massa.nat_etapa is None)


async def teste_13b_sender_grava_marcador():
    """O marcador só vale se o sender realmente o gravar — sem enviar nada de verdade."""
    from app import nat_sender

    sessao = SessaoFalsa()
    contato = SimpleNamespace(wa_id="5511900000001", name="Maria", channel_id=1)
    canal = SimpleNamespace(id=1, phone_number_id="pn", whatsapp_token="tok")

    with patch.object(nat_sender, "nat_pode_atuar", new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(nat_sender, "_resolver_canal", new=AsyncMock(return_value=canal)), \
         patch.object(nat_sender, "janela_aberta", new=AsyncMock(return_value=True)), \
         patch.object(nat_sender, "send_text_message",
                      new=AsyncMock(return_value={"messages": [{"id": "wamid.OUT"}]})), \
         patch.object(nat_sender, "send_interactive_buttons",
                      new=AsyncMock(return_value={"messages": [{"id": "wamid.OUT"}]})):
        sessao._resposta = lambda s: ResultadoFalso(contato)
        ok = await nat_sender.send_nat_message("5511900000001",
                                               "nat_confirma_transferencia", sessao,
                                               nome="Maria", curso="Saúde Mental")

    msgs = [o for o in sessao.adicionados if isinstance(o, Message)]
    check("send_nat_message devolveu True", ok is True)
    check("gravou a Message com nat_etapa preenchido",
          len(msgs) == 1 and msgs[0].nat_etapa == "nat_confirma_transferencia",
          f"{msgs[0].nat_etapa!r}" if msgs else "nenhuma Message")


# ==========================================================================================
# 15: REGRESSÃO DOS SUITES EXISTENTES
# ==========================================================================================

def regressao():
    print("Regressão dos suites existentes")
    for nome in ("test_nat_flow", "test_nat_guard", "test_welcome_guardrail",
                 "test_parse_datetime"):
        r = subprocess.run([sys.executable, f"{nome}.py"], capture_output=True, text=True)
        linha = next((l for l in reversed(r.stdout.splitlines())
                      if l.startswith("OK:") or "Todos os testes" in l), "(sem resumo)")
        check(f"{nome}", r.returncode == 0, linha.strip()[:90])


async def main():
    print("\n" + "=" * 90)
    print("BLOCOS 5 e 7 — agendador, transferência, SLA, escalonamento, botão Assumir")
    print("Nada enviado. Nada gravado. Nenhuma conexão de banco.")
    print("=" * 90 + "\n")

    await teste_1_agendar_e_executar()
    await teste_2_nao_executa_duas_vezes()
    await teste_3_falha_tres_vezes()
    await teste_4_cancelar()
    await teste_5_transferencia()
    await teste_6_exact_falha()
    await teste_7_ja_assumido()
    await teste_8_nivel_zero()
    await teste_9_nivel_um()
    await teste_10_nivel_dois()
    await teste_11_assumir_cancela_sla()
    await teste_12_assumir_idempotente()
    await teste_12b_assumir_encerra_o_fluxo()
    await teste_13_teto_conta_so_nat()
    await teste_13b_sender_grava_marcador()
    await teste_14_sem_sdr()
    print()
    regressao()

    print("\n" + "=" * 90)
    if falhas:
        print(f"❌ {len(falhas)} verificação(ões) falharam:")
        for f in falhas:
            print(f"   - {f}")
        sys.exit(1)
    print("✅ TODOS OS TESTES PASSARAM — nada enviado, nada gravado.")
    print("=" * 90)


if __name__ == "__main__":
    asyncio.run(main())
