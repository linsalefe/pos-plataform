"""P0-C — a rede de última instância do roteamento do webhook.

    cd backend && venv/bin/python test_rede_ultima_instancia.py

NADA sai daqui: a sessão é um dublê em memória, `async_session` é substituída, o envio ao
WhatsApp e a leitura do estado são mockados. Nenhuma conexão, nenhuma linha gravada.

O QUE ESTE ARQUIVO GUARDA — o caso da Fabiana (5517997379129, 25/08), em que 3 mensagens
produziram 3 exceções, 3 rollbacks, ZERO notificações e ZERO mensagens ao lead:

  1. sessão do webhook SADIA -> nenhum rollback (o inbound do lead não pode sumir da tela)
  2. sessão do webhook QUEBRADA -> rollback, para o lote de mensagens seguir vivo
  3. estado ATIVO do agente -> gestão notificada + transferido_humano + despedida
  4. a notificação carrega contato, wa_message_id e traceback
  5. SEM estado ativo -> notifica a gestão, mas NÃO manda despedida (não era conversa dele)
  6. a rede falhando por dentro NÃO levanta (uma rede que derruba o webhook não é rede)
  7. despedida recusada pelo guard não levanta nem desfaz a transferência
"""
import asyncio
import io
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

from app import main
from app import nat_sender
from app import qualificacao_fluxo as fluxo
from app.models import (ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_CONCLUIDO, ETAPA_Q_TRANSFERIDO,
                        NatQualificacaoState, Notification, ORIGEM_LP)
from app.nat_guard import GESTOR_USER_ID

falhas = []
WA_ID = "5517997379129"
WAMID = "wamid.HBgNNTUxNzk5NzM3OTEyOQ=="


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


class SessaoWebhook:
    """A sessão do lote. `sadia=False` imita transação fechada/abortada (o caso real)."""
    def __init__(self, sadia=True):
        self.sadia = sadia
        self.rollbacks = 0

    async def execute(self, stmt, *a, **kw):
        if not self.sadia:
            raise RuntimeError("Can't operate on closed transaction inside context manager")
        return MagicMock()

    async def rollback(self):
        self.rollbacks += 1


class SessaoNova:
    """A `async_session()` da rede: junta o que foi adicionado e conta os commits."""
    def __init__(self):
        self.adicionados = []
        self.commits = 0

    def add(self, obj):
        self.adicionados.append(obj)

    async def commit(self):
        self.commits += 1

    async def flush(self):
        pass

    async def execute(self, stmt, *a, **kw):
        return MagicMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def notificacoes(self):
        return [o for o in self.adicionados if isinstance(o, Notification)]


def _estado(etapa=ETAPA_Q_AGUARDANDO_ANO):
    return NatQualificacaoState(contact_wa_id=WA_ID, exact_lead_id=42, origem=ORIGEM_LP,
                                etapa=etapa)


def _estourado():
    """A exceção com traceback DE VERDADE — é o teste do P0-C, não decoração.

    Uma exceção construída (`RuntimeError("x")`) e nunca levantada tem `__traceback__` None,
    e a rede então só teria o `tipo: msg` que já existia antes dela. É exatamente o cenário
    da injeção de `raise RuntimeError` em `_fatos` que a auditoria pediu como teste.
    """
    try:
        raise RuntimeError("boom no _fatos")
    except RuntimeError as e:
        return e


def roda(*, sadia=True, estado=None, envio=True, erro=None, quebra_sessao_nova=False):
    """Executa a rede uma vez e devolve (sessão do webhook, sessão nova, envio, log)."""
    webhook = SessaoWebhook(sadia=sadia)
    nova = SessaoNova()
    mandar = AsyncMock(return_value=envio)

    def abrir():
        if quebra_sessao_nova:
            raise RuntimeError("pool esgotado")
        return nova

    saida = io.StringIO()
    with patch.object(main, "async_session", abrir), \
         patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)), \
         patch.object(nat_sender, "send_nat_message", new=mandar), \
         redirect_stdout(saida):
        asyncio.run(main._rede_de_ultima_instancia(
            webhook, WA_ID, WAMID, erro or _estourado()))
    return webhook, nova, mandar, saida.getvalue()


print("=" * 78)
print("P0-C — a rede de última instância")
print("=" * 78)

print("\n1) A sessão do webhook — rolar para trás só quando precisa")
# Um `db.rollback()` incondicional descartaria a Message do inbound que o lote acabou de
# gravar: o lead sumiria da tela do SDR por causa de um erro que não tinha nada com ele.
webhook, _, _, _ = roda(sadia=True, estado=_estado())
checa("sessão sadia -> NÃO faz rollback", webhook.rollbacks, 0)

webhook, _, _, log = roda(sadia=False, estado=_estado())
checa("sessão quebrada -> rollback, para o lote seguir", webhook.rollbacks, 1)
checa("  e diz isso no log", "revertida" in log, True)

print("\n2) A gestão é avisada — sempre, e com o que dá para agir")
_, nova, _, log = roda(estado=_estado())
notifs = nova.notificacoes()
checa("uma notificação", len(notifs), 1)
checa("  para a GESTÃO, não para o SDR dono", notifs[0].user_id, GESTOR_USER_ID)
checa("  título nomeia a falha", "FALHA NO ROTEAMENTO" in notifs[0].title, True)
checa("  corpo tem o contato", WA_ID in notifs[0].body, True)
checa("  corpo tem o wa_message_id", WAMID in notifs[0].body, True)
checa("  corpo tem o traceback", "Traceback" in notifs[0].body, True)
checa("  ref é a mensagem que estourou", notifs[0].ref, WAMID)
checa("traceback COMPLETO no log (antes só saía 'tipo: msg')", "Traceback" in log, True)

print("\n3) O lead recebe despedida — e o agente para de escutá-lo")
e = _estado()
_, nova, mandar, _ = roda(estado=e)
checa("etapa vira transferido_humano", e.etapa, ETAPA_Q_TRANSFERIDO)
checa("  com motivo legível", "falha no roteamento" in (e.transferido_motivo or ""), True)
checa("  e carimbo de quando", e.transferido_em is not None, True)
checa("despedida enviada UMA vez", mandar.await_count, 1)
checa("  com o texto determinístico", mandar.await_args.kwargs.get("corpo_livre"),
      fluxo.TEXTO_FALLBACK)
# Mesmo motivo do `_fallback`: a etapa já não é ativa, e `qualificacao_pode_atuar`
# recusaria a própria mensagem de despedida. E o guard é o de DESPEDIDA, não o de abertura:
# o de abertura traz o teto por hora junto, que calaria justamente a mensagem que existe
# para o lead não ficar no silêncio (P1-B).
checa("  pelo guard de DESPEDIDA (sem teto por hora)",
      mandar.await_args.kwargs.get("guard").__name__, "guard_de_despedida")
checa("  e a sessão nova commitou", nova.commits >= 2, True)

print("\n4) Quem não era conversa do agente não recebe despedida do agente")
for etapa in (ETAPA_Q_TRANSFERIDO, ETAPA_Q_CONCLUIDO):
    e = _estado(etapa)
    _, nova, mandar, _ = roda(estado=e)
    checa(f"estado em '{etapa}' -> nenhuma despedida", mandar.await_count, 0)
    checa("  mas a gestão é avisada assim mesmo", len(nova.notificacoes()), 1)
    checa("  e a etapa fica como estava", e.etapa, etapa)

_, nova, mandar, log = roda(estado=None)
checa("sem estado (fluxo velho) -> nenhuma despedida", mandar.await_count, 0)
checa("  gestão avisada", len(nova.notificacoes()), 1)
checa("  e o log explica o porquê", "sem estado" in log, True)

print("\n5) A rede não derruba o webhook — nem quando ela mesma falha")
webhook, _, mandar, log = roda(estado=_estado(), quebra_sessao_nova=True)
checa("sessão nova indisponível (pool esgotado) -> não levanta", True, True)
checa("  falha ALTO no log", "Rede de última instância falhou" in log, True)
checa("  e nada foi enviado", mandar.await_count, 0)

e = _estado()
_, _, mandar, log = roda(estado=e, envio=False)
checa("despedida recusada pelo guard -> não levanta", mandar.await_count, 1)
checa("  a transferência PERMANECE (o agente não volta a falar)", e.etapa,
      ETAPA_Q_TRANSFERIDO)
checa("  e a recusa aparece no log", "RECUSADA" in log, True)

print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} teste(s) falharam:")
    for f in falhas:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ Todos os testes passaram. Nada enviado, nada gravado, nenhuma conexão aberta.")
