"""Sprint 3 item 1 — quem termina a qualificação com reunião marcada é CONFIRMADO.

    cd backend && venv/bin/python test_concluir_confirma.py

NADA sai daqui: o WhatsApp é dublê e o banco é uma sessão em memória. O que NÃO é dublê são
os dois guards (`qualificacao_pode_atuar` e `guard_de_despedida`) nem `enviar_nat` — o bug
de 26/08 morava exatamente na conversa entre eles, e um teste que os mockasse não provaria
nada.

O QUE ESTE ARQUIVO GUARDA:

  1. o caso da regressão: lead com reunião existente completa o roteiro -> recebe a
     CONFIRMAÇÃO (data, hora e consultora), etapa `concluido`, ZERO notificação à gestão
  2. a prova negativa: com o guard errado (`qualificacao_pode_atuar`, que era o que `_falar`
     usava) o mesmo cenário devolve despedida + transferido + notificação — é o que o item 1
     removeu, e o teste falha se ele voltar
  3. a invariante: a etapa NUNCA anda depois de um `_fallback`
  4. confirmação recusada não desfaz a conclusão nem acorda a gestão
  5. `_agendar` (confirmar=False) continua sem falar duas vezes
  6. sem reunião, o ramo é `_ofertar_agenda` — `_concluir` não é chamado
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app import nat_sender
from app import qualificacao_fluxo as fluxo
from app import qualificacao_guard as guard
from app.models import (ETAPA_Q_AGUARDANDO_ATUACAO, ETAPA_Q_AGUARDANDO_MOTIVACAO,
                        ETAPA_Q_CONCLUIDO, ETAPA_Q_OFERTANDO_AGENDA, ETAPA_Q_TRANSFERIDO,
                        Contact, NatConfig, NatQualificacaoState, Notification, ORIGEM_EXACT)

falhas = []
WA = "5537999965494"          # a Amanda, uma das 4 vítimas reais de 26/08
REUNIAO_ID = 220


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


class Sessao:
    """Sessão em memória que responde às consultas REAIS dos guards.

    Despacha pela entidade do `select` em vez de devolver MagicMock para tudo: é isso que
    permite `qualificacao_pode_atuar` enxergar de fato a etapa que `_concluir` acabou de
    gravar — que é o mecanismo do bug.
    """
    def __init__(self, estado, *, chave_ligada=True):
        self.estado = estado
        self.config = NatConfig(id=1, qualificacao_enabled=chave_ligada, max_envios_hora=20)
        self.contact = Contact(wa_id=WA, name="Amanda", channel_id=1)
        self.adicionados = []

    def add(self, obj):
        self.adicionados.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def execute(self, stmt, *a, **kw):
        alvo = str(getattr(stmt, "column_descriptions", [{}])[0].get("entity", "")) \
            if getattr(stmt, "column_descriptions", None) else ""
        texto = str(stmt)
        r = MagicMock()
        if "nat_config" in texto:
            r.scalar_one_or_none.return_value = self.config
            r.scalars.return_value.first.return_value = self.config
        elif "nat_qualificacao_state" in texto:
            r.scalar_one_or_none.return_value = self.estado
            r.scalars.return_value.first.return_value = self.estado
            r.scalars.return_value.__iter__ = lambda s: iter([self.estado])
        elif "contacts" in texto:
            r.scalar_one_or_none.return_value = self.contact
            r.scalars.return_value.first.return_value = self.contact
            r.scalars.return_value.__iter__ = lambda s: iter([self.contact])
        else:
            r.scalar_one_or_none.return_value = None
            r.scalar.return_value = 0
            r.scalars.return_value.first.return_value = None
            r.scalars.return_value.__iter__ = lambda s: iter([])
        return r

    def notificacoes(self):
        return [o for o in self.adicionados if isinstance(o, Notification)]


def _estado(etapa=ETAPA_Q_AGUARDANDO_MOTIVACAO):
    e = NatQualificacaoState(contact_wa_id=WA, exact_lead_id=51574518, origem=ORIGEM_EXACT,
                             etapa=etapa)
    e.ultimo_wa_message_id = "wamid.ULTIMO"
    return e


def _reuniao():
    return SimpleNamespace(id=REUNIAO_ID,
                           slot_inicio=datetime(2026, 8, 28, 14, 15),
                           sales_rep_email="processoseletivo@cenatcursos.com.br",
                           telefone=WA, passo="agendado")


def roda_avancar(estado, db, *, reuniao=None, meta_ok=True):
    """`_avancar` na bifurcação de `aguardando_motivacao`, com o WhatsApp dublê.

    Só o transporte é falso. `_falar`, `enviar_nat`, `qualificacao_pode_atuar` e
    `guard_de_despedida` são os de produção.
    """
    resultado = ({"messages": [{"id": "wamid.X"}]} if meta_ok else {"error": "recusado"})
    enviadas = []

    async def envia_texto(*, to, text, **kw):
        enviadas.append(text)
        return resultado

    with patch.object(nat_sender, "send_text_message", new=AsyncMock(side_effect=envia_texto)), \
         patch.object(nat_sender, "janela_aberta", new=AsyncMock(return_value=True)), \
         patch.object(nat_sender, "_resolver_canal",
                      new=AsyncMock(return_value=SimpleNamespace(
                          id=1, phone_number_id="1", whatsapp_token="t"))), \
         patch.object(fluxo, "_reuniao", new=AsyncMock(return_value=reuniao)), \
         patch.object(fluxo, "agendar_lembrete", new=AsyncMock(return_value=True)), \
         patch.object(fluxo, "_ofertar_agenda", new=AsyncMock(return_value=None)), \
         patch.object(fluxo, "_descartar_fala_adiada", new=AsyncMock(return_value=None)), \
         patch("app.nat_scheduler.cancelar", new=AsyncMock(return_value=0)), \
         patch("app.nat_flow.usuario_existe", new=AsyncMock(return_value=True)), \
         patch("app.agendamento.consultoras.nome_de", return_value="Victória Rodrigues"):
        asyncio.run(fluxo._avancar(estado, "Perfeito — entendi sua motivação. "
                                           "Vou ver os horários.", db))
    return enviadas


print("=" * 78)
print("Sprint 3 item 1 — _concluir confirma, e não se despede")
print("=" * 78)

print("\n1) O caso da regressão: reunião existente + roteiro completo -> CONFIRMAÇÃO")
e = _estado()
db = Sessao(e)
enviadas = roda_avancar(e, db, reuniao=_reuniao())

checa("etapa final é 'concluido'", e.etapa, ETAPA_Q_CONCLUIDO)
checa("  NÃO é 'transferido_humano'", e.etapa == ETAPA_Q_TRANSFERIDO, False)
checa("  sem transferido_em", e.transferido_em, None)
checa("  sem transferido_motivo", e.transferido_motivo, None)
checa("ZERO notificação à gestão", len(db.notificacoes()), 0)
checa("duas falas: a do LLM e a confirmação", len(enviadas), 2)
checa("  a última é a confirmação, não a despedida",
      enviadas[-1].startswith("Na verdade você já tem horário reservado:"), True)
checa("  com a data e a hora do banco", "28/08 às 14:15" in enviadas[-1], True)
checa("  com a consultora", "com Victória Rodrigues" in enviadas[-1], True)
checa("  e o TEXTO_FALLBACK não aparece em lugar nenhum",
      any(fluxo.TEXTO_FALLBACK in t for t in enviadas), False)

print("\n2) Prova negativa: com o guard que `_falar` usava, o bug volta")
# `qualificacao_pode_atuar` EXIGE etapa ativa. Depois de `_concluir` gravar 'concluido', ele
# recusa a própria confirmação — e era isso que empurrava o lead para `_fallback`.
e2 = _estado()
db2 = Sessao(e2)
e2.etapa = ETAPA_Q_CONCLUIDO
pode, motivo = asyncio.run(guard.qualificacao_pode_atuar(db2.contact, db2))
checa("qualificacao_pode_atuar RECUSA com etapa 'concluido'", pode, False)
checa("  e é a recusa exata que aparecia no log de 26/08",
      "está em 'concluido', etapa em que o agente cala" in motivo, True)
pode2, _ = asyncio.run(guard.guard_de_despedida(db2.contact, db2))
checa("guard_de_despedida ACEITA a mesma etapa", pode2, True)

print("\n3) A invariante: a etapa não anda depois de um _fallback")
# `_avancar` no ramo PROXIMA (aguardando_atuacao -> aguardando_motivacao) com o envio
# recusado por motivo que não é o teto: `_falar` transfere e a etapa NÃO pode seguir.
e3 = _estado(ETAPA_Q_AGUARDANDO_ATUACAO)
db3 = Sessao(e3, chave_ligada=False)     # chave geral desligada = recusa definitiva
roda_avancar(e3, db3)
checa("etapa parou em 'transferido_humano'", e3.etapa, ETAPA_Q_TRANSFERIDO)
checa("  não virou 'aguardando_motivacao'", e3.etapa == ETAPA_Q_AGUARDANDO_MOTIVACAO, False)

print("\n4) Confirmação recusada NÃO desfaz a conclusão nem acorda a gestão")
# ISOLADO em `_concluir`, de propósito: por `_avancar` este caso nem existe, porque a recusa
# apanharia primeiro a fala do LLM e o `if ... estado.etapa == ETAPA_Q_TRANSFERIDO: return`
# devolveria antes. O caso real é estreito — a chave cair ENTRE as duas falas, ou a Meta
# recusar só a segunda — e é justamente por ser estreito que ele precisa estar travado: a
# reunião existe na Exact, e falhar em anunciá-la não pode desfazer a conclusão.
e4 = _estado()
db4 = Sessao(e4, chave_ligada=False)
enviadas4 = []
with patch.object(nat_sender, "send_text_message",
                  new=AsyncMock(side_effect=lambda **kw: enviadas4.append(kw.get("text"))
                                or {"messages": [{"id": "wamid.X"}]})), \
     patch.object(nat_sender, "janela_aberta", new=AsyncMock(return_value=True)), \
     patch.object(nat_sender, "_resolver_canal",
                  new=AsyncMock(return_value=SimpleNamespace(
                      id=1, phone_number_id="1", whatsapp_token="t"))), \
     patch.object(fluxo, "agendar_lembrete", new=AsyncMock(return_value=True)), \
     patch("app.nat_scheduler.cancelar", new=AsyncMock(return_value=0)), \
     patch("app.agendamento.consultoras.nome_de", return_value="Victória Rodrigues"):
    asyncio.run(fluxo._concluir(e4, _reuniao(), db4, confirmar=True))
checa("etapa é 'concluido' mesmo com a confirmação recusada", e4.etapa, ETAPA_Q_CONCLUIDO)
checa("  não foi transferido", e4.transferido_em, None)
checa("  e a gestão NÃO foi notificada", len(db4.notificacoes()), 0)
checa("  nenhuma confirmação saiu", enviadas4, [])

print("\n5) `_agendar` (confirmar=False) não dá a mesma notícia duas vezes")
e5 = _estado(ETAPA_Q_ESCOLHENDO_SLOT := "escolhendo_slot")
db5 = Sessao(e5)
enviadas5 = []
with patch.object(nat_sender, "send_text_message",
                  new=AsyncMock(side_effect=lambda **kw: enviadas5.append(kw.get("text"))
                                or {"messages": [{"id": "wamid.X"}]})), \
     patch.object(nat_sender, "janela_aberta", new=AsyncMock(return_value=True)), \
     patch.object(nat_sender, "_resolver_canal",
                  new=AsyncMock(return_value=SimpleNamespace(
                      id=1, phone_number_id="1", whatsapp_token="t"))), \
     patch.object(fluxo, "agendar_lembrete", new=AsyncMock(return_value=True)), \
     patch("app.nat_scheduler.cancelar", new=AsyncMock(return_value=0)):
    asyncio.run(fluxo._concluir(e5, _reuniao(), db5))     # sem confirmar=True
checa("etapa 'concluido'", e5.etapa, ETAPA_Q_CONCLUIDO)
checa("  e NENHUMA fala — quem falou foi o modelo, em `_agendar`", enviadas5, [])

print("\n6) Sem reunião, o ramo é _ofertar_agenda — `_concluir` nem entra")
e6 = _estado()
db6 = Sessao(e6)
with patch.object(fluxo, "_concluir", new=AsyncMock()) as concluir_espiao:
    roda_avancar(e6, db6, reuniao=None)
checa("_concluir não foi chamado", concluir_espiao.await_count, 0)
checa("etapa foi para 'ofertando_agenda'", e6.etapa, ETAPA_Q_OFERTANDO_AGENDA)

print("\n" + "=" * 78)
if falhas:
    print(f"{len(falhas)} FALHA(S):")
    for f in falhas:
        print(f"  - {f}")
    raise SystemExit(1)
print("TUDO OK")
