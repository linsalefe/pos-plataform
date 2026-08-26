"""P3-A — o vigia "AGENTE MUDO" (kind `vigiar_resposta`).

    cd backend && venv/bin/python test_vigia_agente_mudo.py

NADA sai daqui: o WhatsApp, o banco e o agendador são dublês. O vigia NUNCA fala com o
lead — ele só notifica a gestão —, e isto é parte do que os testes afirmam.

O QUE ESTE ARQUIVO GUARDA:

  1. agente responde -> vigia cancelado, zero notificação (e recusa NÃO cancela)
  2. agente mudo aos 10 min -> notificação à GESTÃO com contato, etapa e inbound
  3. `transferido_humano` / `concluido` / `encerrado` no meio da janela -> não dispara
  4. fala adiada pelo teto (P0-B): suprime abaixo de 30 min de espera...
     ... e NOTIFICA aos 30 min mesmo com a pendência viva (readiada 3×)
  5. restart no meio da janela -> o vigia vive no banco e dispara do snapshot
  6. dois inbounds seguidos -> um vigia só, sem acúmulo
  7. o 9º dígito: o vigia enxerga o inbound nas duas grafias
"""
import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app import nat_sender
from app import qualificacao_fluxo as fluxo
from app import nat_scheduler
from app.models import (ACAO_PENDENTE, ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_CONCLUIDO,
                        ETAPA_Q_ENCERRADO, ETAPA_Q_ESCOLHENDO_SLOT, ETAPA_Q_TRANSFERIDO,
                        KIND_RESPONDER_PENDENTE, KIND_VIGIAR_RESPOSTA, NatQualificacaoState,
                        Notification, ORIGEM_LP)
from app.nat_guard import GESTOR_USER_ID
from app.nat_scheduler import AcaoAdiada, AcaoIgnorada

falhas = []
WA = "5583988046720"        # o número real do caso de 25/08, grafia de 13 dígitos
WA_12 = "558388046720"      # a grafia em que o inbound dele chegava
AGORA = datetime(2026, 8, 26, 14, 0, 0)   # relógio preso: SP, naive, como messages.timestamp


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


class Sessao:
    """Sessão em memória. Junta o que foi adicionado; nada é gravado."""
    def __init__(self):
        self.adicionados = []

    def add(self, obj):
        self.adicionados.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def execute(self, stmt, *a, **kw):
        return MagicMock()

    def notificacoes(self):
        return [o for o in self.adicionados if isinstance(o, Notification)]


def _estado(etapa=ETAPA_Q_AGUARDANDO_ANO, wa=WA):
    e = NatQualificacaoState(contact_wa_id=wa, exact_lead_id=42, origem=ORIGEM_LP, etapa=etapa)
    e.ultimo_wa_message_id = "wamid.ULTIMO"
    return e


def dispara(*, estado, espera_min=11, pendencia=False, payload=None, gestor_existe=True):
    """Roda o handler do vigia com o relógio preso. Devolve (desfecho, sessão, motivo)."""
    db = Sessao()
    ultimo_inbound = AGORA - timedelta(minutes=espera_min)
    acao = {"contact_wa_id": estado.contact_wa_id if estado else WA,
            "payload": json.dumps(payload) if payload else None}
    with patch.object(fluxo, "_agora_sp", return_value=AGORA), \
         patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)), \
         patch.object(fluxo, "_ultimo_inbound", new=AsyncMock(return_value=ultimo_inbound)), \
         patch.object(fluxo, "_fala_adiada_pendente",
                      new=AsyncMock(return_value=pendencia)), \
         patch("app.nat_flow.usuario_existe", new=AsyncMock(return_value=gestor_existe)):
        try:
            asyncio.run(fluxo.vigiar_resposta(acao, db))
            return "notificou", db, None
        except AcaoIgnorada as e:
            return "ignorou", db, str(e)
        except AcaoAdiada as e:
            return "adiou", db, e.motivo
        except Exception as e:
            return f"levantou:{type(e).__name__}", db, str(e)


print("=" * 78)
print("P3-A — o vigia AGENTE MUDO")
print("=" * 78)

print("\n1) O agente falou -> o vigia não tem mais o que vigiar")
# O cancelamento mora em `enviar_nat`, não em `_falar`: este é o ÚNICO ponto por onde TODO
# envio da NAT passa. Em `_falar` ficariam de fora a despedida do `_fallback`, a confirmação
# do `_concluir`, a oferta de agenda e o lembrete — e vigia sobrevivente depois de o agente
# ter falado é falso positivo, a doença que este detector veio curar.
def envia_nat(*, guard_ok=True, meta_ok=True):
    cancelou = AsyncMock(return_value=1)
    resultado = ({"messages": [{"id": "wamid.X"}]} if meta_ok else {"error": "recusado"})
    with patch.object(nat_sender, "send_text_message",
                      new=AsyncMock(return_value=resultado)), \
         patch.object(nat_sender, "send_template_message",
                      new=AsyncMock(return_value=resultado)), \
         patch.object(nat_sender, "janela_aberta", new=AsyncMock(return_value=True)), \
         patch.object(nat_sender, "_resolver_canal",
                      new=AsyncMock(return_value=SimpleNamespace(
                          id=1, phone_number_id="1", whatsapp_token="t"))), \
         patch.object(nat_scheduler, "cancelar", new=cancelou):
        saiu, motivo = asyncio.run(nat_sender.enviar_nat(
            WA, "qualif_conversa", Sessao(),
            guard=AsyncMock(return_value=(guard_ok, "ok" if guard_ok else "chave desligada")),
            corpo_livre="oi, tudo bem?"))
    return saiu, motivo, cancelou


saiu, _, cancelou = envia_nat()
checa("envio que SAI cancela o vigia", cancelou.await_count, 1)
checa("  no kind certo", cancelou.await_args.args[0], KIND_VIGIAR_RESPOSTA)
checa("  para o contato certo", cancelou.await_args.args[1], WA)
checa("  e o envio segue reportando sucesso", saiu, True)

saiu, _, cancelou = envia_nat(guard_ok=False)
checa("recusa do guard NÃO cancela (o lead continua sem resposta)", cancelou.await_count, 0)
checa("  e o envio reporta recusa", saiu, False)

saiu, _, cancelou = envia_nat(meta_ok=False)
checa("Meta recusando NÃO cancela", cancelou.await_count, 0)
checa("  e o envio reporta recusa", saiu, False)

# Cancelar não pode desfazer uma mensagem já entregue ao lead.
with patch.object(nat_scheduler, "cancelar",
                  new=AsyncMock(side_effect=RuntimeError("banco"))):
    with patch.object(nat_sender, "send_text_message",
                      new=AsyncMock(return_value={"messages": [{"id": "wamid.X"}]})), \
         patch.object(nat_sender, "janela_aberta", new=AsyncMock(return_value=True)), \
         patch.object(nat_sender, "_resolver_canal",
                      new=AsyncMock(return_value=SimpleNamespace(
                          id=1, phone_number_id="1", whatsapp_token="t"))):
        saiu, _ = asyncio.run(nat_sender.enviar_nat(
            WA, "qualif_conversa", Sessao(),
            guard=AsyncMock(return_value=(True, "ok")), corpo_livre="oi"))
checa("cancelamento que falha NÃO desfaz o envio", saiu, True)


print("\n2) Agente mudo aos 10 min -> a GESTÃO é avisada")
e = _estado(ETAPA_Q_AGUARDANDO_ANO)
desfecho, db, _ = dispara(estado=e, espera_min=11)
checa("espera de 11 min -> notifica", desfecho, "notificou")
n = db.notificacoes()
checa("  uma notificação", len(n), 1)
checa("  para a GESTÃO, não para o SDR dono", n[0].user_id, GESTOR_USER_ID)
checa("  título inequívoco de falha de sistema",
      n[0].title, "AGENTE MUDO — lead esperando há 11 min")
checa("  corpo tem a etapa", f"'{ETAPA_Q_AGUARDANDO_ANO}'" in n[0].body, True)
checa("  corpo tem quando o lead escreveu", "26/08 13:49" in n[0].body, True)
checa("  tipo próprio, separado de agente_transferiu", n[0].type, fluxo.TIPO_NOTIF_MUDO)
checa("  e NADA foi enviado ao lead (o vigia só notifica)",
      [o for o in db.adicionados if not isinstance(o, Notification)], [])

# A etapa pode ter andado entre armar e vencer — o corpo diz isso, em vez de mentir.
e = _estado(ETAPA_Q_ESCOLHENDO_SLOT)
_, db, _ = dispara(estado=e, espera_min=15, payload={"etapa": ETAPA_Q_AGUARDANDO_ANO})
checa("etapa mudou desde o armar -> o corpo registra as duas",
      "era 'aguardando_ano'" in db.notificacoes()[0].body, True)

# Sem destinatário, o detector de silêncio não pode virar silêncio.
desfecho, db, motivo = dispara(estado=_estado(), gestor_existe=False)
checa("GESTOR_USER_ID inexistente -> levanta ALTO, não engole",
      desfecho, "levantou:RuntimeError")
checa("  e nomeia o problema", "não existe" in motivo, True)


print("\n3) Etapa terminal no meio da janela -> o vigia não dispara")
# Mesma constante que governa escutar e falar (ETAPAS_QUALIFICACAO_ATIVAS). Nenhum caso
# especial novo: se o agente não é mais dono da conversa, não existe agente mudo.
for etapa in (ETAPA_Q_TRANSFERIDO, ETAPA_Q_CONCLUIDO, ETAPA_Q_ENCERRADO):
    desfecho, db, motivo = dispara(estado=_estado(etapa), espera_min=30)
    checa(f"'{etapa}' -> ignora", desfecho, "ignorou")
    checa("  sem notificar", len(db.notificacoes()), 0)
    checa("  com motivo na linha (skipped não é mudo)", "etapa não é mais ativa" in motivo,
          True)

desfecho, db, motivo = dispara(estado=None, espera_min=30)
checa("sem estado -> ignora, com motivo", desfecho, "ignorou")

with patch.object(fluxo, "_ultimo_inbound", new=AsyncMock(return_value=None)), \
     patch.object(fluxo, "estado_de", new=AsyncMock(return_value=_estado())):
    try:
        asyncio.run(fluxo.vigiar_resposta({"contact_wa_id": WA}, Sessao()))
        d = "notificou"
    except AcaoIgnorada as ex:
        d = "ignorou"
checa("sem inbound nenhum -> ignora (nada a vigiar)", d, "ignorou")

desfecho, db, motivo = dispara(estado=_estado(), espera_min=3)
checa("lead escreveu há 3 min -> ADIA, não notifica cedo", desfecho, "adiou")
checa("  sem notificar", len(db.notificacoes()), 0)


print("\n4) A fala adiada pelo teto (P0-B) — a régua é a ESPERA, não o run_at")
# MEDIDO: ATRASO_POR_TETO = 10 min e o vigia vence em inbound+10 min — os dois relógios
# coincidem. E `AcaoAdiada` não consome tentativa: cada readiamento é +10 min, então o
# `run_at` da pendência fica PARA SEMPRE a menos de 10 min de distância. Uma supressão medida
# no run_at nunca deixaria o vigia disparar.
for espera in (10, 20, 29):
    desfecho, db, motivo = dispara(estado=_estado(), espera_min=espera, pendencia=True)
    checa(f"pendência viva + espera de {espera} min -> ADIA", desfecho, "adiou")
    checa("  sem notificar", len(db.notificacoes()), 0)
    checa("  com o motivo gravado na linha (nunca skip mudo)",
          "fala adiada pelo teto" in motivo, True)

# O caso que o teto na ESPERA existe para cobrir: a pendência readiou 3× (30 min), continua
# viva, e o "esperar resolve" já falhou três vezes seguidas. A partir daqui o vigia fala.
desfecho, db, motivo = dispara(estado=_estado(), espera_min=30, pendencia=True)
checa("pendência readiada 3× (30 min de espera) -> NOTIFICA mesmo com pendência viva",
      desfecho, "notificou")
checa("  e o título mostra a espera real", db.notificacoes()[0].title,
      "AGENTE MUDO — lead esperando há 30 min")

desfecho, db, _ = dispara(estado=_estado(), espera_min=45, pendencia=True)
checa("espera de 45 min com pendência -> notifica", desfecho, "notificou")

desfecho, db, _ = dispara(estado=_estado(), espera_min=11, pendencia=False)
checa("SEM pendência, 11 min -> notifica na hora", desfecho, "notificou")


print("\n5) Restart no meio da janela -> o vigia sobrevive")
# Ele vive em `nat_scheduled_actions` com status `pendente`, não em memória do processo. E o
# handler recebe um DICT (snapshot), não objeto ORM — é o que permite ao scheduler executá-lo
# depois de um restart sem nada do processo anterior.
armou = AsyncMock()
with patch("app.nat_scheduler.agendar", new=armou), \
     patch.object(fluxo, "_agora_sp", return_value=AGORA):
    asyncio.run(fluxo._armar_vigia(_estado(), Sessao()))
checa("armar grava no agendador (banco), não em memória", armou.await_count, 1)
checa("  no kind certo", armou.await_args.args[0], KIND_VIGIAR_RESPOSTA)
checa("  para vencer em 10 min", armou.await_args.args[2], AGORA + fluxo.PRAZO_VIGIA)
checa("  com a etapa no payload", armou.await_args.args[3], {"etapa": ETAPA_Q_AGUARDANDO_ANO})

# O "restart": nada do processo anterior existe; só a linha do banco, virada em dict.
linha_do_banco = {"contact_wa_id": WA,
                  "payload": json.dumps({"etapa": ETAPA_Q_AGUARDANDO_ANO})}
db = Sessao()
with patch.object(fluxo, "_agora_sp", return_value=AGORA), \
     patch.object(fluxo, "estado_de", new=AsyncMock(return_value=_estado())), \
     patch.object(fluxo, "_ultimo_inbound",
                  new=AsyncMock(return_value=AGORA - timedelta(minutes=12))), \
     patch.object(fluxo, "_fala_adiada_pendente", new=AsyncMock(return_value=False)), \
     patch("app.nat_flow.usuario_existe", new=AsyncMock(return_value=True)):
    asyncio.run(fluxo.vigiar_resposta(linha_do_banco, db))
checa("handler roda só com a linha do banco (dict), sem estado de processo",
      len(db.notificacoes()), 1)

# Armar nunca derruba o turno — é vigia, não fluxo.
with patch("app.nat_scheduler.agendar", new=AsyncMock(side_effect=RuntimeError("banco"))):
    asyncio.run(fluxo._armar_vigia(_estado(), Sessao()))
checa("armar que falha NÃO levanta", True, True)


print("\n6) Dois inbounds seguidos -> um vigia só")
# `nat_scheduler.agendar` CANCELA o pendente do mesmo (kind, contato) antes de inserir. É o
# mecanismo; o índice único parcial `uq_nat_sched_pendente_por_contato (kind, contact_wa_id)
# WHERE status='pendente'` é a rede da mesma regra — e por ser sobre (kind, contato), o vigia
# convive com o `encerrar_inativo` do MESMO contato, sem ALTER nenhum.
cancelou = AsyncMock(return_value=0)
db = Sessao()
with patch.object(nat_scheduler, "cancelar", new=cancelou):
    asyncio.run(nat_scheduler.agendar(KIND_VIGIAR_RESPOSTA, WA, AGORA, {}, db))
    asyncio.run(nat_scheduler.agendar(KIND_VIGIAR_RESPOSTA, WA, AGORA, {}, db))
checa("cada armada cancela a anterior antes de inserir", cancelou.await_count, 2)
checa("  sempre do mesmo par (kind, contato)",
      (cancelou.await_args.args[0], cancelou.await_args.args[1]), (KIND_VIGIAR_RESPOSTA, WA))


print("\n7) O 9º dígito — o vigia enxerga o inbound nas duas grafias")
# Um vigia estrito não veria a mensagem do próprio lead que ele vigia, e calaria: seria o bug
# do silêncio reproduzido DENTRO do detector de silêncio.
from sqlalchemy.dialects import postgresql  # noqa: E402


class DBSql:
    def __init__(self, valor=None):
        self.sql = None
        self.valor = valor

    async def execute(self, stmt):
        self.sql = str(stmt.compile(dialect=postgresql.dialect(),
                                    compile_kwargs={"literal_binds": True}))
        r = MagicMock()
        r.scalar_one_or_none.return_value = self.valor
        r.scalar.return_value = self.valor
        return r


for numero in (WA, WA_12):
    db = DBSql(AGORA - timedelta(minutes=5))
    asyncio.run(fluxo._ultimo_inbound(numero, db))
    checa(f"{numero}: busca as duas grafias", WA in db.sql and WA_12 in db.sql, True)
    checa("  e só inbound", "direction" in db.sql and "'inbound'" in db.sql, True)

db = DBSql(0)
asyncio.run(fluxo._fala_adiada_pendente(WA, db))
checa("a pendência também é procurada nas duas grafias", WA in db.sql and WA_12 in db.sql,
      True)
checa("  e só o que está pendente", f"'{ACAO_PENDENTE}'" in db.sql, True)
checa("  do kind responder_pendente", f"'{KIND_RESPONDER_PENDENTE}'" in db.sql, True)


print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} teste(s) falharam:")
    for f in falhas:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ Todos os testes passaram. Nada enviado, nada gravado, nenhuma conexão aberta.")
