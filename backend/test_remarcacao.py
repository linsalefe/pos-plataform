"""Remarcação pendente e aviso sem dono (SPRINT_REMARCACAO_20261019).

    cd backend && venv/bin/python test_remarcacao.py

Sem banco e sem Exact: dublês de sessão e monkeypatch nas dependências. Escrito e NÃO executado
na sprint de 19/10 (convenção do repo).

O QUE ESTE TESTE PROVA
  1. padrão de texto: casa as frases reais do RECON, não casa clique, mídia, horário nem recusa
  2. escolha de slot com a antiga Vigente NÃO chama `fluxo.agendar` e grava a pendência
  3. o slot desejado bloqueia a grade da consultora (e só dela)
  4. sync vê a antiga Cancelada -> enfileira `remarcacao_retry`; Vigente -> nada
  5. retry com horário livre -> agenda e limpa a pendência
  6. retry com horário ocupado -> reoferta
  7. Exact recusa 2 vezes -> humano com o erro verbatim
  8. expiração em 24h com a antiga ainda Vigente -> humano
  9. texto "podemos remarcar?" com reunião Vigente -> remarcar; sem reunião -> fluxo antigo
 10. sem dono: destinatários = SDR_USER_IDS + gestão; com dono: só ele; corpo com a última mensagem
 11. inbound sem dono com conversa pausada -> `conversa_pausada` True
"""
import asyncio
import os
from datetime import datetime, timedelta
from types import SimpleNamespace

from app import remarcacao as rm
from app.models import EXACT_TYPE_CANCELADA, EXACT_TYPE_VIGENTE

falhas = []
AGORA = datetime(2026, 10, 19, 10, 0)


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def reuniao(**k):
    base = dict(meeting_id=4778560, lead_id=52672016, telefone_chave="1191174062",
                telefone_bruto="5511991174062", nome="Maria", slot_inicio=AGORA + timedelta(hours=8),
                exact_type=EXACT_TYPE_VIGENTE, agendamento_id=1065, registrado_em=AGORA,
                slot_desejado_inicio=None, slot_desejado_consultora=None,
                remarcacao_tentativas=0, remarcacao_expira_em=None, cancelado_motivo=None,
                regua_encerrada_motivo=None, sdr_tratado_em=None)
    base.update(k)
    return SimpleNamespace(**base)


class Res:
    def __init__(self, valor=None, linhas=()):
        self.valor, self.linhas = valor, list(linhas)

    def scalar_one_or_none(self):
        return self.valor

    def first(self):
        return self.linhas[0] if self.linhas else None

    def all(self):
        return self.linhas


class DB:
    """Devolve, em ordem, os resultados enfileirados em `respostas`."""

    def __init__(self, respostas=()):
        self.respostas = list(respostas)
        self.adicionados = []

    async def execute(self, *a, **k):
        return self.respostas.pop(0) if self.respostas else Res()

    def add(self, obj):
        self.adicionados.append(obj)

    async def flush(self):
        pass

    def begin_nested(self):
        db = self

        class Ctx:
            async def __aenter__(self):
                return db

            async def __aexit__(self, *a):
                return False
        return Ctx()


def rodar(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ==========================================================================================
print("\n1. padrão de texto")
for texto in ("Podemos remarcar?", "Remarcar a conversa para após dia 26",
              "Posso reagendar para segunda de manhã?", "Outro dia",
              "Não vou conseguir. Estou presa no trânsito", "Apenas quero desmarcar",
              "outro horário seria melhor"):
    checa(f"casa: {texto}", rm.pede_remarcacao(texto), True)
for texto in ("13h45", "Confirmo", "botao:Preciso remarcar", "media:audio/ogg",
              "Não tenho mais interesse", "", None):
    checa(f"não casa: {texto!r}", rm.pede_remarcacao(texto), False)


# ==========================================================================================
print("\n2. escolha com a antiga Vigente não chama a Exact")
from app import qualificacao_fluxo as qf  # noqa: E402

chamou_exact = []
estacionou = []
antiga = reuniao()
slot_id = "2026-10-20T18:00:00"
slot = SimpleNamespace(id=slot_id, slot=SimpleNamespace(inicio=datetime(2026, 10, 20, 18, 0)),
                       consultoras=(SimpleNamespace(email="processoseletivo@cenatcursos.com.br"),))


async def _slots(db, usar_cache=True):
    return [slot]


async def _nada(*a, **k):
    return None


async def _bloqueia(wa, db, agora=None):
    return antiga


async def _estacionar(estado, s, a, db):
    estacionou.append((s.id, a.meeting_id))


async def _agendar_exact(*a, **k):
    chamou_exact.append(k)
    raise AssertionError("não podia chamar fluxo.agendar")

from app.agendamento import agendar as fluxo_agendar, disponibilidade  # noqa: E402
disponibilidade.slots_livres = _slots
fluxo_agendar.agendar = _agendar_exact
qf._reuniao = _nada
rm.reuniao_que_bloqueia = _bloqueia
rm.estacionar = _estacionar
estado = SimpleNamespace(contact_wa_id="5511991174062", exact_lead_id=52672016,
                         dados_extras={"fluxo": "b", "reunioes_remarcadas": [1065]},
                         etapa="escolhendo_slot")
rodar(qf._agendar(estado, {"dado_extraido": {"slot_id": slot_id}, "mensagem": "x"},
                  {slot_id: "20/10 18:00"}, DB()))
checa("estacionou com o slot e a antiga", estacionou, [(slot_id, 4778560)])
checa("fluxo.agendar NÃO foi chamado", chamou_exact, [])

estacionou.clear()
estado.dados_extras = {"fluxo": "b"}          # primeira conversa, não é remarcação
try:
    rodar(qf._agendar(estado, {"dado_extraido": {"slot_id": slot_id}, "mensagem": "x"},
                      {slot_id: "20/10 18:00"}, DB()))
except Exception:
    pass                                       # o dublê de fluxo.agendar levanta de propósito
checa("sem `reunioes_remarcadas` não estaciona", estacionou, [])


# ==========================================================================================
print("\n3. slot desejado bloqueia só a consultora dele")
from app.agendamento import consultoras as equipe  # noqa: E402
equipe.consultoras = lambda: [SimpleNamespace(email="processoseletivo@cenatcursos.com.br",
                                              grade=SimpleNamespace(duracao=timedelta(minutes=45)))]
inicio = datetime(2026, 10, 20, 18, 0)
db = DB([Res(linhas=[(inicio,)])])
ocupado = rodar(rm.ocupados_pendentes(db, AGORA, AGORA + timedelta(days=3),
                                      "processoseletivo@cenatcursos.com.br"))
checa("reserva de 45 min", ocupado, [(inicio, inicio + timedelta(minutes=45))])
# A outra consultora: a consulta filtra por e-mail, e o dublê devolve vazio.
checa("outra consultora livre",
      rodar(rm.ocupados_pendentes(DB([Res(linhas=[])]), AGORA, AGORA + timedelta(days=3),
                                  "comercial@cenatcursos.com.br")), [])


# ==========================================================================================
print("\n4. sync: Cancelada enfileira, sem pendência não")
enfileirados = []


async def _nat_agendar(kind, wa, run_at, payload, db):
    enfileirados.append((kind, wa, payload))
    return 1


async def _contato(r, db):
    return "5511991174062"

import app.nat_scheduler as ns  # noqa: E402
ns.agendar = _nat_agendar
rm._contato_da_remarcacao = _contato
pend = reuniao(exact_type=EXACT_TYPE_CANCELADA, slot_desejado_inicio=inicio)
checa("com pendência", rodar(rm.ao_cancelar(DB([Res(pend)]), pend.meeting_id)), True)
checa("kind e payload", enfileirados,
      [("remarcacao_retry", "5511991174062", {"meeting_id": pend.meeting_id})])
enfileirados.clear()
checa("sem pendência", rodar(rm.ao_cancelar(DB([Res(reuniao())]), 1)), False)
checa("nada enfileirado", enfileirados, [])


# ==========================================================================================
print("\n5-7. remarcacao_retry")
notas, humanos, reofertas, agendados = [], [], [], []


async def _nota(r, texto):
    notas.append(texto)


async def _humano(r, wa, estado, db, motivo):
    humanos.append(motivo)
    rm._limpar(r)


async def _reofertar(r, wa, db, porque):
    reofertas.append(porque)
    rm._limpar(r)


async def _sem_outra(r, db, agora):
    return None


async def _sem_estado(wa, db):
    return None


async def _notificar(*a, **k):
    return [5, 2]

import app.confirmacao as cf  # noqa: E402
cf._nota = _nota
cf.flag_ligada = lambda: True
cf.telefone_permitido = lambda t: True
rm._humano = _humano
rm._reofertar = _reofertar
rm._outra_vigente = _sem_outra
rm._estado = _sem_estado
rm.notificar = _notificar


def acao(r):
    return {"contact_wa_id": "5511991174062", "payload": f'{{"meeting_id": {r.meeting_id}}}',
            "agora": AGORA}


# 5. livre -> agenda
r = reuniao(exact_type=EXACT_TYPE_CANCELADA, slot_desejado_inicio=inicio,
            slot_desejado_consultora="processoseletivo@cenatcursos.com.br",
            remarcacao_expira_em=AGORA + timedelta(hours=20))


async def _agendou(fluxo, r_, wa, sid, est, db):
    agendados.append(sid)
    return SimpleNamespace(agendamento_id=1300)

rm._agendar_na_exact = _agendou
disponibilidade.slots_livres = _slots
rodar(rm.remarcacao_retry(acao(r), DB([Res(r)])))
checa("agendou o slot desejado", agendados, [slot_id])
checa("pendência limpa", r.slot_desejado_inicio, None)
checa("nota Remarcada", notas[-1:], ["Remarcada para 20/10 18:00"])

# 6. ocupado -> reoferta
r = reuniao(exact_type=EXACT_TYPE_CANCELADA, slot_desejado_inicio=inicio)


async def _grade_vazia(db, usar_cache=True):
    return []

disponibilidade.slots_livres = _grade_vazia
rodar(rm.remarcacao_retry(acao(r), DB([Res(r)])))
checa("reofertou", len(reofertas), 1)
checa("tentativa contada", r.remarcacao_tentativas, 1)

# 7. Exact recusa 2 vezes -> humano com o erro
disponibilidade.slots_livres = _slots
erro = "AgendamentoFalhou: HTTP 400: Lead has already gone through this stage in this cycle."


async def _recusou(*a, **k):
    raise RuntimeError(erro)

rm._agendar_na_exact = _recusou
r = reuniao(exact_type=EXACT_TYPE_CANCELADA, slot_desejado_inicio=inicio)
enfileirados.clear()
rodar(rm.remarcacao_retry(acao(r), DB([Res(r)])))
checa("1ª recusa reagenda em 10 min",
      [(k, p) for k, _, p in enfileirados], [("remarcacao_retry", {"meeting_id": r.meeting_id})])
checa("ainda pendente", r.slot_desejado_inicio, inicio)
rodar(rm.remarcacao_retry(acao(r), DB([Res(r)])))
checa("2ª recusa vai para humano", len(humanos), 1)
checa("motivo traz o erro verbatim", erro in humanos[-1], True)


# ==========================================================================================
print("\n8. expiração")
humanos.clear()
r = reuniao(slot_desejado_inicio=inicio, remarcacao_expira_em=AGORA - timedelta(minutes=1))
rodar(rm.remarcacao_expira(acao(r), DB([Res(r)])))
checa("expirou -> humano", len(humanos), 1)
r = reuniao(slot_desejado_inicio=inicio, exact_type=EXACT_TYPE_CANCELADA,
            remarcacao_expira_em=AGORA - timedelta(minutes=1))
try:
    rodar(rm.remarcacao_expira(acao(r), DB([Res(r)])))
    checa("antiga já Cancelada é ignorada", "não levantou", "AcaoIgnorada")
except ns.AcaoIgnorada:
    checa("antiga já Cancelada é ignorada", True, True)


# ==========================================================================================
print("\n9. texto livre na régua")
remarcou = []


async def _remarcar(r, wa, db, ja_cortada=False):
    remarcou.append((r.meeting_id, ja_cortada))


async def _pausada(wa, db):
    return reuniao(regua_encerrada_motivo="humano")


async def _sem_dona(wa, db):
    return None, False


async def _canon(wa, db):
    return wa

cf.remarcar = _remarcar
cf._reuniao_pausada = _pausada
cf._reuniao_dona = _sem_dona
import app.contatos as contatos  # noqa: E402
contatos.canonizar = _canon
import app.noshow as noshow  # noqa: E402
noshow.flag_ligada = lambda: False
dono = rodar(cf.inbound("5511941351304", None, "Podemos remarcar?", DB()))
checa("após a pausa, remarcação vira oferta", (dono, remarcou), (True, [(4778560, False)]))


async def _nenhuma(wa, db):
    return None

remarcou.clear()
cf._reuniao_pausada = _nenhuma
dono = rodar(cf.inbound("5511941351304", None, "Podemos remarcar?", DB()))
checa("sem reunião: fluxo antigo (False)", (dono, remarcou), (False, []))


# ==========================================================================================
print("\n10. destinatários")
from app import nat_flow  # noqa: E402


async def _existe(uid, db):
    return uid in (2, 4, 5)

nat_flow.usuario_existe = _existe
os.environ["SDR_USER_IDS"] = "5, 4, x, 99"
checa("sem dono: SDRs válidos + gestão",
      rodar(rm.destinatarios("5511941351304", DB(), consultar_dono=False)), [5, 4, 2])
checa("com dono: só ele",
      rodar(rm.destinatarios("5511941351304", DB(), dono=4, consultar_dono=False)), [4])
os.environ["SDR_USER_IDS"] = ""
checa("sem SDR configurado: só a gestão",
      rodar(rm.destinatarios("5511941351304", DB(), consultar_dono=False)), [2])
checa("última mensagem: clique vira rótulo",
      rodar(rm.ultima_mensagem("x", DB([Res(linhas=[("botao:Preciso remarcar",)])]))),
      'clicou "Preciso remarcar"')


# ==========================================================================================
print("\n11. conversa pausada")
checa("agente transferiu", rodar(rm.conversa_pausada("5511941351304", DB([Res(linhas=[(1,)])]),
                                                     AGORA)), True)
checa("régua parou para humano",
      rodar(rm.conversa_pausada("5511941351304", DB([Res(linhas=[]), Res(linhas=[(4779798,)])]),
                                AGORA)), True)
checa("nada pausado",
      rodar(rm.conversa_pausada("5511941351304", DB([Res(linhas=[]), Res(linhas=[])]), AGORA)),
      False)


print(f"\n{'TODOS OK' if not falhas else f'{len(falhas)} FALHA(S)'}")
raise SystemExit(1 if falhas else 0)
