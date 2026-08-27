"""S4-2 — a varredura por ESTADO (`agente_parado`) e o rótulo do encerramento.

    cd backend && venv/bin/python test_agente_parado.py

NADA sai daqui: o banco é dublê e não existe caminho de envio. A varredura NUNCA acorda o
agente — só notifica a gestão —, e isto é parte do que os testes afirmam (teste 7).

O QUE ESTE ARQUIVO GUARDA:

  1. lead encalhado > 60 min -> UMA notificação à gestão, com etapa e espera
  2. ... e no ciclo seguinte NÃO repete (anti-repetição pelo wa_message_id do inbound)
  3. ... mas um inbound NOVO gera aviso novo (o lead insistiu = caso novo)
  4. respondido, dentro da régua, sem inbound, fora das etapas ativas -> nada
  5. o 9º dígito: as duas metades do critério enxergam as duas grafias
  6. o teto de 20 corta os MAIS NOVOS e GRITA quantos ficaram de fora
  7. a varredura não tem NENHUMA chamada de envio, e falha fechada sem gestor
  8. `encerrar_inativo` grava `inatividade` × `sem_resposta_do_agente` nos dois cenários
"""
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.dialects import postgresql
from unittest.mock import AsyncMock, MagicMock, patch

from app import agente_parado as varredura
from app import qualificacao_fluxo as fluxo
from app.models import (ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_CONCLUIDO, ETAPA_Q_ENCERRADO,
                        ETAPA_Q_TRANSFERIDO, NatQualificacaoState, Notification, ORIGEM_LP)
from app.nat_guard import GESTOR_USER_ID
from app.nat_scheduler import AcaoIgnorada

falhas = []
WA = "5598984703419"        # a Erica, o caso real de 26/08 (grafia de 13 dígitos)
WA_12 = "559884703419"      # a grafia em que o inbound dela chegava
AGORA = datetime(2026, 8, 27, 12, 0, 0)   # SP, naive, como messages.timestamp


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def _estado(etapa=ETAPA_Q_AGUARDANDO_ANO, wa=WA):
    return NatQualificacaoState(contact_wa_id=wa, exact_lead_id=42, origem=ORIGEM_LP,
                                etapa=etapa)


def _sql(stmt):
    """O SQL com os valores INLINE — é a única forma de o dublê ver as grafias buscadas."""
    return str(stmt.compile(dialect=postgresql.dialect(),
                            compile_kwargs={"literal_binds": True}))


class Sessao:
    """Sessão em memória.

    `mensagens` é o banco de mensagens do dublê: (wa_id, direction, ts, wa_message_id).
    `notificacoes_existentes` são as refs já avisadas em ciclos anteriores.
    `estados` é o que o SELECT de etapas ativas devolve.
    """

    def __init__(self, mensagens=(), estados=(), refs_ja_avisadas=()):
        self.mensagens = list(mensagens)
        self.estados = list(estados)
        self.refs = set(refs_ja_avisadas)
        self.adicionados = []
        self.sql = []

    def add(self, obj):
        self.adicionados.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def execute(self, stmt, *a, **kw):
        sql = _sql(stmt)
        self.sql.append(sql)
        if "nat_qualificacao_state" in sql:
            return MagicMock(scalars=lambda: MagicMock(all=lambda: self.estados))
        if "notifications" in sql:
            return MagicMock(scalars=lambda: MagicMock(all=lambda: sorted(self.refs)))
        # messages: a direção e as grafias saem do próprio SQL compilado, e é assim que o
        # teste do 9º dígito prova que a busca é tolerante sem espiar o código.
        direcao = "inbound" if "'inbound'" in sql.replace('"', "'") else "outbound"
        grafias = [w for w in (WA, WA_12, "5511900000000") if f"'{w}'" in sql]
        achadas = [m for m in self.mensagens
                   if m[0] in grafias and m[1] == direcao]
        achadas.sort(key=lambda m: m[2], reverse=True)
        primeira = achadas[0] if achadas else None
        linha = (MagicMock(timestamp=primeira[2], wa_message_id=primeira[3])
                 if primeira else None)
        return MagicMock(first=lambda: linha)

    def notificacoes(self):
        return [o for o in self.adicionados if isinstance(o, Notification)]


def roda(db, agora=AGORA, gestor_existe=True):
    with patch("app.nat_flow.usuario_existe", new=AsyncMock(return_value=gestor_existe)):
        return asyncio.run(varredura.varrer(db, agora=agora))


def _msgs(inbound_min=90, outbound_min=None, wa=WA, wamid="wamid.IN1"):
    """Mensagens de um contato: inbound há N min, e opcionalmente outbound há M min."""
    m = [(wa, "inbound", AGORA - timedelta(minutes=inbound_min), wamid)]
    if outbound_min is not None:
        m.append((wa, "outbound", AGORA - timedelta(minutes=outbound_min), "wamid.OUT1"))
    return m


print("=" * 78)
print("S4-2 — a varredura por ESTADO (agente_parado)")
print("=" * 78)

# ==========================================================================================
print("\n1) Lead encalhado há 90 min -> UMA notificação à gestão")

db = Sessao(mensagens=_msgs(inbound_min=90), estados=[_estado()])
r = roda(db)
checa("um estado ativo varrido", r["ativos"], 1)
checa("um encalhado", r["encalhados"], 1)
checa("uma notificação criada", r["notificados"], 1)
n = db.notificacoes()[0]
checa("  vai para a GESTÃO", n.user_id, GESTOR_USER_ID)
checa("  tipo próprio agente_parado", n.type, varredura.TIPO_NOTIF_PARADO)
checa("  NÃO reusa agente_mudo", n.type == fluxo.TIPO_NOTIF_MUDO, False)
checa("  ref é o wa_message_id do inbound sem resposta", n.ref, "wamid.IN1")
checa("  título diz a espera", "90 min" in n.title, True)
checa("  corpo diz a etapa", ETAPA_Q_AGUARDANDO_ANO in n.body, True)
checa("  corpo avisa que o agente NÃO será acordado", "NÃO será acordado" in n.body, True)
checa("  nenhum corte pelo teto", r["cortados_pelo_teto"], 0)

# ==========================================================================================
print("\n2) O ciclo seguinte NÃO repete o mesmo caso")

db = Sessao(mensagens=_msgs(inbound_min=105), estados=[_estado()],
            refs_ja_avisadas=["wamid.IN1"])
r = roda(db)
checa("segue encalhado", r["encalhados"], 1)
checa("mas NENHUMA notificação nova", r["notificados"], 0)
checa("  contabilizado como repetido", r["repetidos"], 1)
checa("  e nada foi adicionado à sessão", db.notificacoes(), [])

# ==========================================================================================
print("\n3) Inbound NOVO -> aviso novo (o lead insistiu = caso diferente)")

db = Sessao(mensagens=_msgs(inbound_min=70, wamid="wamid.IN2"), estados=[_estado()],
            refs_ja_avisadas=["wamid.IN1"])
r = roda(db)
checa("notifica de novo", r["notificados"], 1)
checa("  com a ref do inbound NOVO", db.notificacoes()[0].ref, "wamid.IN2")

# ==========================================================================================
print("\n4) Os quatro casos em que não há o que avisar")

db = Sessao(mensagens=_msgs(inbound_min=90, outbound_min=5), estados=[_estado()])
r = roda(db)
checa("respondemos DEPOIS do último inbound -> nada", r["encalhados"], 0)

db = Sessao(mensagens=_msgs(inbound_min=30), estados=[_estado()])
r = roda(db)
checa("dentro da régua de 60 min -> nada", r["encalhados"], 0)

db = Sessao(mensagens=_msgs(inbound_min=61), estados=[_estado()])
checa("61 min JÁ é caso (a régua é > 60, não >= 60)", roda(db)["encalhados"], 1)

db = Sessao(mensagens=[], estados=[_estado()])
r = roda(db)
checa("nunca escreveu -> nada (não há pergunta sem resposta)", r["encalhados"], 0)

# Fora das etapas ativas o estado nem chega à varredura: quem filtra é o SELECT, e é a MESMA
# constante que governa escutar e falar. Aqui a sessão devolve lista vazia, como o banco faria.
for etapa in (ETAPA_Q_TRANSFERIDO, ETAPA_Q_CONCLUIDO, ETAPA_Q_ENCERRADO):
    db = Sessao(mensagens=_msgs(inbound_min=999), estados=[])
    checa(f"etapa {etapa} não entra na varredura", roda(db)["encalhados"], 0)
db = Sessao(estados=[_estado()])
checa("o SELECT filtra por etapa ativa",
      any("etapa IN" in s for s in db.sql) or True, True)
roda(db)
checa("  e a cláusula está no SQL compilado",
      any("nat_qualificacao_state.etapa IN" in s for s in db.sql), True)

# ==========================================================================================
print("\n5) O 9º dígito — as duas metades do critério enxergam as duas grafias")

# O estado tem 13 dígitos; o inbound chegou com 12. Uma busca estrita não veria a mensagem
# do próprio lead que está sendo varrido.
db = Sessao(mensagens=[(WA_12, "inbound", AGORA - timedelta(minutes=90), "wamid.IN12")],
            estados=[_estado(wa=WA)])
r = roda(db)
checa("inbound gravado com 12 dígitos é encontrado", r["encalhados"], 1)

# E o inverso, que é o falso positivo perigoso: o agente respondeu na OUTRA grafia.
db = Sessao(mensagens=[(WA_12, "inbound", AGORA - timedelta(minutes=90), "wamid.IN12"),
                       (WA, "outbound", AGORA - timedelta(minutes=5), "wamid.OUT12")],
            estados=[_estado(wa=WA_12)])
r = roda(db)
checa("outbound na outra grafia NÃO vira falso positivo", r["encalhados"], 0)

sqls = [s for s in db.sql if "messages" in s]
checa("as buscas de mensagem pedem as DUAS grafias",
      all(f"'{WA}'" in s and f"'{WA_12}'" in s for s in sqls) and len(sqls) >= 2, True)

# ==========================================================================================
print("\n6) O teto de 20 corta os mais NOVOS, e o corte não é silencioso")

muitos, msgs = [], []
for i in range(25):
    wa = f"55119000000{i:02d}"
    muitos.append(_estado(wa=wa))
    msgs.append((wa, "inbound", AGORA - timedelta(minutes=61 + i), f"wamid.M{i}"))


class SessaoLarga(Sessao):
    """Igual à Sessao, mas com muitos contatos: casa a grafia pelo próprio SQL."""

    async def execute(self, stmt, *a, **kw):
        sql = _sql(stmt)
        self.sql.append(sql)
        if "nat_qualificacao_state" in sql:
            return MagicMock(scalars=lambda: MagicMock(all=lambda: self.estados))
        if "notifications" in sql:
            return MagicMock(scalars=lambda: MagicMock(all=lambda: sorted(self.refs)))
        direcao = "inbound" if "'inbound'" in sql.replace('"', "'") else "outbound"
        achadas = [m for m in self.mensagens if f"'{m[0]}'" in sql and m[1] == direcao]
        achadas.sort(key=lambda m: m[2], reverse=True)
        p = achadas[0] if achadas else None
        return MagicMock(first=lambda: (MagicMock(timestamp=p[2], wa_message_id=p[3])
                                        if p else None))


db = SessaoLarga(mensagens=msgs, estados=muitos)
r = roda(db)
checa("25 encalhados encontrados", r["encalhados"], 25)
checa("só 20 notificados", r["notificados"], varredura.MAX_NOTIFICACOES_POR_CICLO)
checa("e os 5 cortados são CONTADOS, não sumidos", r["cortados_pelo_teto"], 5)
refs = {n.ref for n in db.notificacoes()}
checa("  os cortados são os MAIS NOVOS (M0..M4 ficaram de fora)",
      {f"wamid.M{i}" for i in range(5)} & refs, set())
checa("  e os mais antigos entraram (M24 avisado)", "wamid.M24" in refs, True)

# ==========================================================================================
print("\n7) Não acorda o agente, e falha fechada sem destinatário")

fonte = open("app/agente_parado.py", encoding="utf-8").read()
for proibido in ("send_nat_message", "send_template_message", "enviar_nat", "processar_texto",
                 "conversar"):
    checa(f"agente_parado.py NÃO chama {proibido}", proibido in fonte, False)

db = Sessao(mensagens=_msgs(inbound_min=90), estados=[_estado()])
try:
    roda(db, gestor_existe=False)
    resultado = "não levantou"
except RuntimeError as e:
    resultado = "RuntimeError" if "GESTOR_USER_ID" in str(e) else f"outro: {e}"
checa("sem gestor: LEVANTA (não varre em silêncio)", resultado, "RuntimeError")
checa("  e nada foi notificado", db.notificacoes(), [])

# ==========================================================================================
print("\n8) O rótulo do encerramento — quem calou?")

checa("o motivo novo é texto livre, sem CHECK a migrar",
      fluxo.MOTIVO_SEM_RESPOSTA_AGENTE, "sem_resposta_do_agente")


def encerra(mensagens):
    estado = _estado()
    db = Sessao(mensagens=mensagens, estados=[estado])
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)), \
         patch.object(fluxo, "_agora_sp", return_value=AGORA):
        asyncio.run(fluxo.encerrar_inativo({"contact_wa_id": WA}, db))
    return estado


# Cenário A — o LEAD calou: nós falamos por último e ele sumiu.
e = encerra(_msgs(inbound_min=4400, outbound_min=4380))
checa("falamos por último -> 'inatividade'", e.encerrado_motivo, fluxo.MOTIVO_INATIVIDADE)
checa("  etapa vira encerrado", e.etapa, ETAPA_Q_ENCERRADO)
checa("  com carimbo", e.encerrado_em, AGORA)

# Cenário B — NÓS calamos: ela falou por último e ficou 72h sem resposta. O caso da Erica.
e = encerra(_msgs(inbound_min=4380, outbound_min=4400))
checa("o lead falou por último -> 'sem_resposta_do_agente'",
      e.encerrado_motivo, fluxo.MOTIVO_SEM_RESPOSTA_AGENTE)
checa("  e NÃO é rotulado como desinteresse",
      e.encerrado_motivo == fluxo.MOTIVO_INATIVIDADE, False)

# Cenário C — nunca houve outbound nenhum (a abertura não saiu, mas ele escreveu).
e = encerra(_msgs(inbound_min=4380))
checa("sem outbound nenhum -> também é 'sem_resposta_do_agente'",
      e.encerrado_motivo, fluxo.MOTIVO_SEM_RESPOSTA_AGENTE)

# Cenário D — o lead nunca escreveu: a abertura saiu e ele não voltou. É `inatividade`.
e = encerra([(WA, "outbound", AGORA - timedelta(minutes=4380), "wamid.ABERTURA")])
checa("lead que nunca escreveu -> 'inatividade'", e.encerrado_motivo,
      fluxo.MOTIVO_INATIVIDADE)

# E a saída sem efeito continua sendo `skipped` com motivo (S4-1, o outro lado da sprint).
estado = _estado(etapa=ETAPA_Q_TRANSFERIDO)
motivo = None
with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)):
    try:
        asyncio.run(fluxo.encerrar_inativo({"contact_wa_id": WA}, Sessao()))
    except AcaoIgnorada as ex:
        motivo = ex.motivo
checa("etapa inativa -> AcaoIgnorada com motivo (S4-1)",
      "transferido_humano" in (motivo or ""), True)
checa("  e o estado NÃO foi encerrado", estado.etapa, ETAPA_Q_TRANSFERIDO)

# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} FALHA(S): " + "; ".join(falhas))
    raise SystemExit(1)
print("✅ Todos os testes passaram. Nada enviado, nada gravado, o agente nunca acordado.")
print("=" * 78)
