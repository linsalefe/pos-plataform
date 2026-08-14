"""Bloco 6 da NAT: recuperação do lead sem contato.

Rodar: cd backend && venv/bin/python test_nat_recuperacao.py

NADA É ENVIADO E NADA É GRAVADO. A sessão é um dublê em memória (SessaoFalsa), o envio ao lead
é um espião (AsyncMock) e a fila do agendador é uma lista. Mesmo padrão de test_nat_sprint3.

A ÚNICA saída de rede é o caso 9, que faz um GET read-only na definição do template para
detectar drift de copy. Se a rede falhar, ele AVISA em vez de reprovar.

O QUE ESTE ARQUIVO PROTEGE. Um endpoint que manda mensagem para o lead, com teto de 2 e uma
janela de idempotência de 30s. As três perguntas que ele responde são "o lead recebeu quantas
mensagens?", "o SDR foi cobrado?" e "o clique do lead chegou em alguém?" — e cada teste abaixo
é uma forma de errar uma delas.

  1. sem-contato: registra tentativa, envia UMA mensagem e agenda o retry de 10 min
  2. clique duplo em menos de 30s -> UMA tentativa, UMA mensagem (janela por CONTATO)
  3. 2ª tentativa -> envia, NÃO agenda retry, etapa vira encerrado (o teto se fechando)
  3b. 3º clique (aba velha) -> não envia nada, mantém encerrado
  4. retry com lead assumido -> no-op · retry fora de sem_contato -> no-op
  5. NAT_TENTAR_AGORA em sem_contato -> aguardando_ligacao + sla_check novo (escada zerada)
  5b. clique de recuperação fora da etapa -> ignorado sem erro
  6. sem-contato cancela o sla_check pendente
  7. o template sai com os button_payloads da recuperação, por índice
  8. clique na 2ª mensagem (etapa encerrado PELO TETO) -> atendido, não descartado
  9. drift: nat_recuperacao_sdr x Meta (corpo, botoes e ordem)
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import nat_copy, nat_flow, nat_recuperacao, nat_routes
from app.models import (ETAPA_AGUARDANDO_LIGACAO, ETAPA_AGUARDANDO_RESPOSTA, ETAPA_ENCERRADO,
                        ETAPA_REAGENDADO, ETAPA_SEM_CONTATO, KIND_RETRY_CONTATO,
                        KIND_SLA_CHECK, NatContactAttempt, Notification)
from app.whatsapp import send_template_message

AGORA = datetime(2026, 8, 14, 15, 0, 0)
WA = "5511900000001"
USUARIO = SimpleNamespace(id=4, name="Valéria")
DADOS_LEAD = {"nome": "Maria Lidia", "curso": "Saúde Mental", "formacao": ""}

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
    """Emula begin_nested: na exceção, desfaz o que foi adicionado DENTRO dele."""
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
    """Sessão em memória. Nenhuma conexão aberta, nada gravado.

    O `execute` responde de verdade à consulta de nat_contact_attempts — devolve a última
    tentativa que ESTE teste adicionou. É o que permite exercitar a janela de idempotência
    sem dublar `_tentativa_recente`: dublá-la seria testar o dublê.
    """
    def __init__(self, state=None):
        self.adicionados = []
        self.savepoints = 0
        self.rollbacks = 0
        self.commits = 0
        self.state = state

    def add(self, obj):
        self.adicionados.append(obj)

    async def flush(self):
        pass

    async def execute(self, stmt, *a, **kw):
        sql = str(stmt).lower()
        if "nat_contact_attempts" in sql:
            return ResultadoFalso(self.tentativas()[-1] if self.tentativas() else None)
        if "nat_flow_state" in sql:
            return ResultadoFalso(self.state)
        return ResultadoFalso()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def refresh(self, obj):
        pass

    def begin_nested(self):
        return SavepointFalso(self)

    def tentativas(self):
        return [o for o in self.adicionados if isinstance(o, NatContactAttempt)]

    def notificacoes(self):
        return [o for o in self.adicionados if isinstance(o, Notification)]


def estado(etapa=ETAPA_AGUARDANDO_LIGACAO, tentativas=0, assumido_por=None, nivel=2,
           sdr=4):
    """Estado do fluxo. `nivel=2` de propósito: é onde o SLA termina na vida real, e é o
    valor que denuncia um sla_check novo que nasce morto (ver o teste 5)."""
    return SimpleNamespace(
        contact_wa_id=WA, etapa=etapa, sdr_user_id=sdr, exact_lead_id=51000001,
        tentativas_contato=tentativas, assumido_por=assumido_por,
        assumido_em=(AGORA if assumido_por else None), escalonamento_nivel=nivel,
        transferido_em=AGORA - timedelta(minutes=20), ultimo_wa_message_id=None,
        horario_preferencial=None)


class Agenda:
    """Registra o que foi agendado e cancelado, sem banco."""
    def __init__(self):
        self.agendados = []
        self.cancelados = []

    async def agendar(self, kind, wa, run_at, payload, db):
        self.agendados.append((kind, wa, run_at, payload))
        return len(self.agendados)

    async def cancelar(self, kind, wa, db):
        self.cancelados.append((kind, wa))
        return 1

    def patches(self):
        return (patch("app.nat_scheduler.agendar", new=self.agendar),
                patch("app.nat_scheduler.cancelar", new=self.cancelar))


async def roda_sem_contato(state, sessao=None, envio=None, agenda=None, usuario=USUARIO,
                           agora=AGORA):
    """Chama o endpoint de verdade. Só o que é rede ou banco fica dublado.

    `agora` é injetado (e não lido do relógio) porque é ele que define a janela de
    idempotência: sem controlar o instante, o teste 2 não conseguiria distinguir "clique
    duplo" de "segunda tentativa legítima meia hora depois".
    """
    sessao = sessao if sessao is not None else SessaoFalsa(state)
    agenda = agenda if agenda is not None else Agenda()
    envio = envio if envio is not None else AsyncMock(return_value=True)
    p1, p2 = agenda.patches()
    with patch.object(nat_routes, "_estado_travado", new=AsyncMock(return_value=state)), \
         patch.object(nat_routes, "_nome", new=AsyncMock(return_value="Valéria")), \
         patch.object(nat_routes, "_agora_sp", return_value=agora), \
         patch.object(nat_routes, "_dados_do_lead", new=AsyncMock(return_value=DADOS_LEAD)), \
         patch.object(nat_routes, "send_nat_message", new=envio), p1, p2:
        resp = await nat_routes.marcar_sem_contato(WA, sessao, usuario)
    return resp, sessao, envio, agenda


async def roda_retry(state, sessao=None):
    """Chama o handler do retry_contato de verdade."""
    sessao = sessao if sessao is not None else SessaoFalsa(state)
    with patch.object(nat_recuperacao, "_dados_do_lead",
                      new=AsyncMock(return_value=DADOS_LEAD)), \
         patch.object(nat_recuperacao, "_destinatario_do_aviso",
                      new=AsyncMock(return_value=(4, False))), \
         patch.object(nat_recuperacao, "usuario_existe", new=AsyncMock(return_value=True)):
        await nat_recuperacao.retry_contato(
            {"contact_wa_id": WA, "agora": AGORA, "id": 77}, sessao)
    return sessao


async def roda_clique(state, payload, texto="", wa_message_id="wamid.CLIQUE", agenda=None):
    """Chama processar_clique de verdade, com o roteamento real do payload."""
    sessao = SessaoFalsa(state)
    agenda = agenda if agenda is not None else Agenda()
    envio = AsyncMock(return_value=True)
    p1, p2 = agenda.patches()
    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "_dados_do_lead", new=AsyncMock(return_value=DADOS_LEAD)), \
         patch.object(nat_flow, "send_nat_message", new=envio), \
         patch.object(nat_flow, "_agora_sp", return_value=AGORA), \
         patch.object(nat_flow, "notificar_reagendamento",
                      new=AsyncMock(return_value=True)) as aviso_reag, \
         patch.object(nat_recuperacao, "_destinatario_do_aviso",
                      new=AsyncMock(return_value=(4, False))), \
         patch.object(nat_recuperacao, "usuario_existe", new=AsyncMock(return_value=True)), \
         p1, p2:
        destino = await nat_flow.processar_clique(
            {"contact_wa_id": WA, "wa_message_id": wa_message_id,
             "button_payload": payload, "button_text": texto, "source": "template"}, sessao)
    return destino, sessao, envio, agenda, aviso_reag


# ==========================================================================================
# 1-3: O ENDPOINT
# ==========================================================================================

async def teste_1_registra_envia_agenda():
    print("1) sem-contato: registra tentativa, envia UMA mensagem e agenda o retry")
    state = estado()
    resp, sessao, envio, agenda = await roda_sem_contato(state)

    tentativas = sessao.tentativas()
    check("UMA tentativa registrada", len(tentativas) == 1, f"{len(tentativas)}")
    if tentativas:
        t = tentativas[0]
        check("tentativa_num = 1", t.tentativa_num == 1, f"{t.tentativa_num}")
        check("guarda quem marcou", t.registrado_por == USUARIO.id, f"{t.registrado_por}")
        check("resultado = sem_contato",
              t.resultado == nat_recuperacao.RESULTADO_SEM_CONTATO, f"{t.resultado}")
        check("created_at em horário de SP, escrito por nós (não o NOW() do banco)",
              t.created_at == AGORA, f"{t.created_at}")
    check("contador do estado incrementado", state.tentativas_contato == 1,
          f"{state.tentativas_contato}")
    check("etapa virou sem_contato", state.etapa == ETAPA_SEM_CONTATO, f"{state.etapa}")

    check("UMA mensagem ao lead", envio.await_count == 1, f"{envio.await_count}")
    if envio.await_count:
        args = envio.await_args
        check("mensagem é o nat_recuperacao_sdr",
              args.args[1] == nat_copy.NAT_MSG_RECUPERACAO, f"{args.args[1]}")
        check("com nome e curso do lead",
              args.kwargs.get("nome") == DADOS_LEAD["nome"]
              and args.kwargs.get("curso") == DADOS_LEAD["curso"], f"{args.kwargs}")

    retries = [a for a in agenda.agendados if a[0] == KIND_RETRY_CONTATO]
    check("UM retry_contato agendado", len(retries) == 1, f"{agenda.agendados}")
    if retries:
        check(f"para +{nat_recuperacao.RETRY_CONTATO_MINUTOS} min",
              retries[0][2] == AGORA + timedelta(
                  minutes=nat_recuperacao.RETRY_CONTATO_MINUTOS), f"{retries[0][2]}")
    check("resposta diz o que aconteceu",
          resp["registrado"] and resp["tentativa_num"] == 1 and resp["mensagem_enviada"]
          and resp["retry_agendado"], f"{resp}")
    check("botão continua visível (ainda resta 1 tentativa)",
          resp["pode_marcar_sem_contato"] is True, f"{resp['pode_marcar_sem_contato']}")
    check("commit uma vez", sessao.commits == 1, f"{sessao.commits}")


async def teste_2_clique_duplo():
    print("2) clique duplo em menos de 30s -> UMA tentativa, UMA mensagem")
    state = estado()
    sessao = SessaoFalsa(state)
    envio = AsyncMock(return_value=True)
    agenda = Agenda()

    await roda_sem_contato(state, sessao, envio, agenda)
    # Segundo clique, DE OUTRA PESSOA: a janela é por contato, e é o lead que ela protege.
    resp2, _, _, _ = await roda_sem_contato(state, sessao, envio, agenda,
                                            usuario=SimpleNamespace(id=5, name="Thobias"))

    check("continua UMA tentativa", len(sessao.tentativas()) == 1,
          f"{len(sessao.tentativas())}")
    check("continua UMA mensagem ao lead", envio.await_count == 1, f"{envio.await_count}")
    check("contador não avançou", state.tentativas_contato == 1,
          f"{state.tentativas_contato}")
    check("resposta marca como duplicado", resp2["registrado"] is False
          and resp2["motivo"] == "duplicado", f"{resp2}")
    check("não agendou um segundo retry",
          len([a for a in agenda.agendados if a[0] == KIND_RETRY_CONTATO]) == 1,
          f"{agenda.agendados}")

    # Passada a janela, o MESMO lead pode ser marcado de novo — senão o teto de 2 nunca
    # seria alcançado e a recuperação teria uma tentativa só.
    depois = AGORA + timedelta(seconds=nat_recuperacao.JANELA_IDEMPOTENCIA_SEGUNDOS + 1)
    resp3, _, _, _ = await roda_sem_contato(state, sessao, envio, agenda, agora=depois)
    check("depois da janela, nova tentativa é aceita",
          resp3["registrado"] and len(sessao.tentativas()) == 2,
          f"registrado={resp3['registrado']} tentativas={len(sessao.tentativas())}")
    check("e ela é a 2ª, que encerra o fluxo",
          state.tentativas_contato == 2 and state.etapa == ETAPA_ENCERRADO,
          f"{state.tentativas_contato} / {state.etapa}")


async def teste_3_segunda_tentativa_encerra():
    print("3) 2ª tentativa -> envia, NÃO agenda retry, etapa vira encerrado")
    state = estado(etapa=ETAPA_SEM_CONTATO, tentativas=1)
    resp, sessao, envio, agenda = await roda_sem_contato(state)

    check("tentativa_num = 2", sessao.tentativas()[0].tentativa_num == 2,
          f"{sessao.tentativas()[0].tentativa_num}")
    check("mensagem ainda sai (última chance do lead)", envio.await_count == 1,
          f"{envio.await_count}")
    check("NENHUM retry agendado — é o teto se fechando",
          [a for a in agenda.agendados if a[0] == KIND_RETRY_CONTATO] == [],
          f"{agenda.agendados}")
    check("etapa virou encerrado", state.etapa == ETAPA_ENCERRADO, f"{state.etapa}")
    check("resposta diz que não agendou", resp["retry_agendado"] is False, f"{resp}")
    check("botão some (teto atingido)", resp["pode_marcar_sem_contato"] is False,
          f"{resp['pode_marcar_sem_contato']}")
    check("tela mostra 2 de 2", resp["tentativas_contato"] == 2
          and resp["max_tentativas_contato"] == nat_recuperacao.MAX_TENTATIVAS_CONTATO,
          f"{resp['tentativas_contato']}/{resp['max_tentativas_contato']}")


async def teste_3b_terceiro_clique():
    print("3b) 3º clique (aba velha / API direta) -> não envia nada")
    state = estado(etapa=ETAPA_SEM_CONTATO, tentativas=2)
    resp, sessao, envio, agenda = await roda_sem_contato(state)

    check("NADA enviado ao lead", envio.await_count == 0, f"{envio.await_count}")
    check("nenhuma tentativa nova", sessao.tentativas() == [], f"{sessao.tentativas()}")
    check("nada agendado", agenda.agendados == [], f"{agenda.agendados}")
    check("motivo explícito", resp["motivo"] == "teto_de_tentativas", f"{resp}")
    check("lead fica em encerrado", state.etapa == ETAPA_ENCERRADO, f"{state.etapa}")


# ==========================================================================================
# 4: O HANDLER DO RETRY
# ==========================================================================================

async def teste_4_retry():
    print("4) retry: cobra o SDR, e sai calado quando não há o que cobrar")
    state = estado(etapa=ETAPA_SEM_CONTATO, tentativas=1)
    sessao = await roda_retry(state)
    notifs = sessao.notificacoes()

    check("UMA notificação criada", len(notifs) == 1, f"{len(notifs)}")
    if notifs:
        n = notifs[0]
        check("foi para o SDR dono", n.user_id == 4, f"{n.user_id}")
        check("tipo nat_retry_contato", n.type == nat_recuperacao.TIPO_NOTIF_RETRY, n.type)
        check("ref pela AÇÃO (dois retries = dois avisos)",
              n.ref == f"{KIND_RETRY_CONTATO}:77", n.ref)
        check("título cobra nova ligação", "tente ligar de novo" in n.title, n.title)
        check("corpo diz a tentativa", "tentativa 1 de 2" in n.body, n.body)
        check("corpo NÃO afirma que o lead ignorou a mensagem",
              "ignorou" not in n.body.lower(), n.body)

    # Lead já assumido: a cobrança perdeu o objeto.
    assumido = estado(etapa=ETAPA_SEM_CONTATO, tentativas=1, assumido_por=5)
    s2 = await roda_retry(assumido)
    check("lead assumido -> no-op", s2.notificacoes() == [], f"{s2.notificacoes()}")

    # Fora de sem_contato: o lead já reagiu.
    for etapa in (ETAPA_AGUARDANDO_LIGACAO, ETAPA_REAGENDADO, ETAPA_ENCERRADO):
        s3 = await roda_retry(estado(etapa=etapa, tentativas=1))
        check(f"etapa {etapa} -> no-op", s3.notificacoes() == [], f"{s3.notificacoes()}")

    # Sem estado nenhum: não levanta (levantar viraria 3 retentativas e uma ação `falhou`).
    s4 = SessaoFalsa(None)
    await roda_retry(None, s4)
    check("sem estado -> no-op silencioso", s4.notificacoes() == [])

    # E o retry NUNCA manda mensagem: nenhum caminho do módulo chama o sender.
    fonte = open("app/nat_recuperacao.py", encoding="utf-8").read()
    check("nat_recuperacao.py não tem NENHUMA chamada de envio",
          "send_nat_message" not in fonte and "send_template_message" not in fonte)


# ==========================================================================================
# 5: OS CLIQUES DO LEAD
# ==========================================================================================

async def teste_5_tentar_agora():
    print("5) NAT_TENTAR_AGORA em sem_contato -> volta para a fila de ligação")
    state = estado(etapa=ETAPA_SEM_CONTATO, tentativas=1, nivel=2)
    destino, sessao, envio, agenda, _ = await roda_clique(state, nat_copy.NAT_TENTAR_AGORA)

    check("etapa virou aguardando_ligacao", destino == ETAPA_AGUARDANDO_LIGACAO
          and state.etapa == ETAPA_AGUARDANDO_LIGACAO, f"{state.etapa}")
    check("NENHUMA mensagem ao lead", envio.await_count == 0, f"{envio.await_count}")
    notifs = sessao.notificacoes()
    check("SDR avisado na hora", len(notifs) == 1, f"{len(notifs)}")
    if notifs:
        check("aviso é o de LIGUE AGORA", "LIGUE AGORA" in notifs[0].title, notifs[0].title)
        check("tipo nat_tentar_agora",
              notifs[0].type == nat_recuperacao.TIPO_NOTIF_TENTAR_AGORA, notifs[0].type)
    check("retry_contato cancelado",
          (KIND_RETRY_CONTATO, WA) in agenda.cancelados, f"{agenda.cancelados}")
    slas = [a for a in agenda.agendados if a[0] == KIND_SLA_CHECK]
    check("sla_check novo agendado", len(slas) == 1, f"{agenda.agendados}")
    check("escada ZERADA — senão o sla_check novo nasce morto no nível 2",
          state.escalonamento_nivel == 0, f"nivel={state.escalonamento_nivel}")
    check("transferido_em recarimbado", state.transferido_em == AGORA,
          f"{state.transferido_em}")
    check("idempotência armada (ultimo_wa_message_id)",
          state.ultimo_wa_message_id == "wamid.CLIQUE", f"{state.ultimo_wa_message_id}")

    # Reentrega do MESMO clique não pode refazer nada.
    destino2, sessao2, _, agenda2, _ = await roda_clique(
        state, nat_copy.NAT_TENTAR_AGORA, wa_message_id="wamid.CLIQUE")
    check("clique reentregue -> nada refeito",
          sessao2.notificacoes() == [] and agenda2.agendados == [],
          f"notifs={len(sessao2.notificacoes())} agendados={agenda2.agendados}")

    # E o outro botão: cai em reagendado e reaproveita o aviso que já existia.
    outro = estado(etapa=ETAPA_SEM_CONTATO, tentativas=1)
    d2, _, envio2, agenda3, aviso = await roda_clique(outro, nat_copy.NAT_AGENDAR_OUTRO)
    check("NAT_AGENDAR_OUTRO -> reagendado", d2 == ETAPA_REAGENDADO
          and outro.etapa == ETAPA_REAGENDADO, f"{outro.etapa}")
    check("sem mensagem ao lead", envio2.await_count == 0, f"{envio2.await_count}")
    check("aviso de reagendamento disparado", aviso.await_count == 1, f"{aviso.await_count}")
    check("retry cancelado também aqui",
          (KIND_RETRY_CONTATO, WA) in agenda3.cancelados, f"{agenda3.cancelados}")


async def teste_5b_clique_fora_da_etapa():
    print("5b) clique de recuperação fora da etapa -> ignorado sem erro")
    for etapa in (ETAPA_AGUARDANDO_RESPOSTA, ETAPA_AGUARDANDO_LIGACAO, ETAPA_REAGENDADO):
        st = estado(etapa=etapa, tentativas=0)
        destino, sessao, envio, agenda, _ = await roda_clique(st, nat_copy.NAT_TENTAR_AGORA)
        check(f"em {etapa} -> ignorado, estado intacto",
              destino is None and st.etapa == etapa and envio.await_count == 0
              and sessao.notificacoes() == [] and agenda.agendados == [],
              f"destino={destino} etapa={st.etapa}")

    # E o inverso: um payload da boas-vindas chegando em sem_contato não avança nada.
    st = estado(etapa=ETAPA_SEM_CONTATO, tentativas=1)
    destino, sessao, envio, _, _ = await roda_clique(st, nat_copy.NAT_SIM)
    check("NAT_SIM em sem_contato -> ignorado",
          destino is None and st.etapa == ETAPA_SEM_CONTATO and envio.await_count == 0,
          f"destino={destino} etapa={st.etapa}")

    # Clique SEM payload (template antigo): resolvido por texto, e pela etapa certa.
    st2 = estado(etapa=ETAPA_SEM_CONTATO, tentativas=1)
    destino2, _, _, _, _ = await roda_clique(st2, "", texto="Tentar novamente agora")
    check("sem payload, resolvido por texto -> aguardando_ligacao",
          destino2 == ETAPA_AGUARDANDO_LIGACAO, f"{destino2}")
    # "Outro horário" é o rótulo livre das DUAS mensagens: só a etapa desempata.
    st3 = estado(etapa=ETAPA_SEM_CONTATO, tentativas=1)
    p_recup = nat_flow._payload_do_evento({"button_text": "Outro horário"}, st3)
    p_boas = nat_flow._payload_do_evento(
        {"button_text": "Outro horário"}, estado(etapa=ETAPA_AGUARDANDO_RESPOSTA))
    check("mesmo texto, payloads diferentes conforme a etapa",
          p_recup == nat_copy.NAT_AGENDAR_OUTRO and p_boas == nat_copy.NAT_OUTRO_HORARIO,
          f"sem_contato={p_recup} aguardando_resposta={p_boas}")


# ==========================================================================================
# 6-9: SLA, ENVIO E DRIFT
# ==========================================================================================

async def teste_6_cancela_sla():
    print("6) sem-contato cancela o sla_check pendente")
    state = estado()
    resp, _, _, agenda = await roda_sem_contato(state)

    check("cancelou o sla_check DESTE contato",
          (KIND_SLA_CHECK, WA) in agenda.cancelados, f"{agenda.cancelados}")
    check("resposta informa quantos", resp["cancelados"] == 1, f"{resp['cancelados']}")

    # Falha no cancelamento não pode custar o registro — o handler do SLA é a rede: ele relê
    # a etapa, que já não é aguardando_ligacao.
    state2 = estado()
    sessao2 = SessaoFalsa(state2)

    async def cancelar_ruim(kind, wa, db):
        raise RuntimeError("banco recusou")

    with patch.object(nat_routes, "_estado_travado", new=AsyncMock(return_value=state2)), \
         patch.object(nat_routes, "_nome", new=AsyncMock(return_value="Valéria")), \
         patch.object(nat_routes, "_agora_sp", return_value=AGORA), \
         patch.object(nat_routes, "_dados_do_lead", new=AsyncMock(return_value=DADOS_LEAD)), \
         patch.object(nat_routes, "send_nat_message", new=AsyncMock(return_value=True)), \
         patch("app.nat_scheduler.cancelar", new=cancelar_ruim), \
         patch("app.nat_scheduler.agendar", new=AsyncMock(return_value=1)):
        await nat_routes.marcar_sem_contato(WA, sessao2, USUARIO)
    check("falha no cancelamento preserva a tentativa registrada",
          len(sessao2.tentativas()) == 1 and state2.etapa == ETAPA_SEM_CONTATO,
          f"tentativas={len(sessao2.tentativas())} etapa={state2.etapa}")


async def teste_7_template_com_payloads():
    print("7) o template da recuperação sai com os payloads por índice")
    captura = _CapturaHTTP()
    with patch("app.whatsapp.httpx.AsyncClient", captura):
        await send_template_message(
            to=WA, template_name=nat_copy.NAT_MSG_RECUPERACAO, language=nat_copy.IDIOMA,
            phone_number_id="p", token="t",
            parameters=nat_copy.parametros_template(
                nat_copy.NAT_MSG_RECUPERACAO, nome="Maria", curso="Saúde Mental"),
            button_payloads=nat_copy.payloads_dos_botoes(nat_copy.NAT_MSG_RECUPERACAO))

    comps = captura.enviado["template"]["components"]
    check("nome e idioma do template",
          captura.enviado["template"]["name"] == "nat_recuperacao_sdr"
          and captura.enviado["template"]["language"]["code"] == "pt_BR",
          f"{captura.enviado['template']['name']}")
    check("body com nome e curso, nessa ordem",
          [p["text"] for p in comps[0]["parameters"]] == ["Maria", "Saúde Mental"],
          f"{comps[0]['parameters']}")
    check("dois quick_reply, índices 0 e 1",
          [c["index"] for c in comps[1:]] == ["0", "1"], f"{comps[1:]}")
    check("índice 0 = tentar agora, índice 1 = outro horário",
          comps[1]["parameters"][0]["payload"] == nat_copy.NAT_TENTAR_AGORA
          and comps[2]["parameters"][0]["payload"] == nat_copy.NAT_AGENDAR_OUTRO,
          f"{[c['parameters'][0]['payload'] for c in comps[1:]]}")


async def teste_8_clique_na_segunda_mensagem():
    print("8) clique na 2ª mensagem (encerrado PELO TETO) -> atendido, não descartado")
    # É o bug que a 2ª tentativa criaria se `encerrado` calasse tudo: o lead recebe dois
    # botões vivos e o clique dele seria descartado em silêncio.
    state = estado(etapa=ETAPA_ENCERRADO, tentativas=2, assumido_por=None)
    destino, sessao, envio, agenda, _ = await roda_clique(state, nat_copy.NAT_TENTAR_AGORA)

    check("clique atendido -> aguardando_ligacao", destino == ETAPA_AGUARDANDO_LIGACAO,
          f"{destino}")
    check("alguém foi avisado", len(sessao.notificacoes()) == 1,
          f"{len(sessao.notificacoes())}")
    check("sem mensagem ao lead", envio.await_count == 0, f"{envio.await_count}")

    # Mas encerrado por ASSUMIR continua calado: ali um humano está conduzindo.
    assumido = estado(etapa=ETAPA_ENCERRADO, tentativas=1, assumido_por=5)
    d2, s2, envio2, _, _ = await roda_clique(assumido, nat_copy.NAT_TENTAR_AGORA)
    check("encerrado por assumir -> clique ignorado (o humano conduz)",
          d2 is None and s2.notificacoes() == [] and envio2.await_count == 0,
          f"destino={d2}")

    # E encerrado sem nenhuma tentativa (fluxo normal) também segue calado.
    normal = estado(etapa=ETAPA_ENCERRADO, tentativas=0)
    d3, s3, _, _, _ = await roda_clique(normal, nat_copy.NAT_TENTAR_AGORA)
    check("encerrado sem tentativa -> clique ignorado", d3 is None and s3.notificacoes() == [],
          f"destino={d3}")


async def teste_9_drift():
    """Compara o template novo com o que está aprovado na Meta. GET read-only, nenhum envio."""
    print("9) drift: nat_recuperacao_sdr x Meta")
    import httpx
    from sqlalchemy import text as sql_text
    from app.database import async_session

    try:
        async with async_session() as db:
            row = (await db.execute(
                sql_text("SELECT waba_id, whatsapp_token FROM channels WHERE id=1"))).first()
        async with httpx.AsyncClient(timeout=20) as c:
            resp = await c.get(
                f"https://graph.facebook.com/v22.0/{row[0]}/message_templates",
                headers={"Authorization": f"Bearer {row[1]}"}, params={"limit": 100})
        # Filtra por IDIOMA: nat_recuperacao_sdr existe em `en` e em `pt_BR`, com corpos
        # DIFERENTES, e nome não é chave única no WABA. Ver o caso 13 de test_nat_flow.
        candidatos = [t for t in resp.json().get("data", [])
                      if t.get("name") == nat_copy.NAT_MSG_RECUPERACAO
                      and t.get("language") == nat_copy.IDIOMA]
    except Exception as e:
        print(f"  ⚠️  NAO VERIFICADO (sem acesso a Meta: {type(e).__name__}) — "
              "problema de rede, nao de codigo")
        return

    check(f"existe exatamente 1 versão em {nat_copy.IDIOMA}", len(candidatos) == 1,
          f"{len(candidatos)} encontradas")
    if not candidatos:
        return
    t = candidatos[0]
    corpo = next((c.get("text") for c in t.get("components", [])
                  if c.get("type") == "BODY"), None)
    botoes = [b.get("text") for c in t.get("components", [])
              if c.get("type") == "BUTTONS" for b in c.get("buttons", [])]

    check("status APPROVED", t.get("status") == "APPROVED", f"{t.get('status')}")
    check("BODY idêntico ao de nat_copy (verbatim)",
          corpo == nat_copy.CORPO_APROVADO[nat_copy.NAT_MSG_RECUPERACAO],
          f"{len(corpo or '')} chars na Meta (se divergiu, traga a mudança de lá para cá)")
    check("botões idênticos e NA ORDEM da Meta",
          botoes == nat_copy.BOTOES_APROVADOS[nat_copy.NAT_MSG_RECUPERACAO],
          f"Meta={botoes} local={nat_copy.BOTOES_APROVADOS[nat_copy.NAT_MSG_RECUPERACAO]}")
    livres = nat_copy.BOTOES_LIVRES[nat_copy.NAT_MSG_RECUPERACAO]
    check("títulos livres cabem no limite de 20 e são 2, na mesma ordem",
          len(livres) == len(botoes)
          and all(len(b["titulo"]) <= nat_copy.LIMITE_TITULO_BOTAO for b in livres),
          f"{[(b['titulo'], len(b['titulo'])) for b in livres]}")


class _CapturaHTTP:
    """AsyncClient falso: guarda o corpo do POST e devolve sucesso. Não abre socket."""
    def __init__(self):
        self.enviado = None

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        self.enviado = json
        return SimpleNamespace(json=lambda: {"messages": [{"id": "wamid.FAKE"}]},
                               status_code=200)


async def main():
    print("\nBloco 6 da NAT: recuperação sem contato (nada enviado, nada gravado)\n")
    await teste_1_registra_envia_agenda()
    await teste_2_clique_duplo()
    await teste_3_segunda_tentativa_encerra()
    await teste_3b_terceiro_clique()
    await teste_4_retry()
    await teste_5_tentar_agora()
    await teste_5b_clique_fora_da_etapa()
    await teste_6_cancela_sla()
    await teste_7_template_com_payloads()
    await teste_8_clique_na_segunda_mensagem()
    await teste_9_drift()

    print()
    if falhas:
        print(f"❌ {len(falhas)} verificação(ões) falharam:")
        for f in falhas:
            print(f"   - {f}")
        raise SystemExit(1)
    print("OK: o lead recebe no máximo 2 mensagens, sempre por ato humano; o retry cobra o "
          "SDR e nunca o lead; e nenhum clique cai no vazio.")


if __name__ == "__main__":
    asyncio.run(main())
