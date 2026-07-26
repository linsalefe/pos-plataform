"""Observabilidade de envio: realimentação do welcome_status, alerta de saúde e autenticação.

Rodar: cd backend && venv/bin/python test_observabilidade_envio.py

NADA É ENVIADO, NADA É GRAVADO E NADA SAI PARA A REDE. A sessão é um dublê em memória
(SessaoFalsa / SessaoSaude) e o relay do webhook para a CS Platform é mockado — sem isso o
teste 4 faria um POST de verdade para pedagogico.cenatdata.online, que é exatamente o tipo de
efeito colateral que um suite não pode ter.

DIVISÃO DE TRABALHO, para não fingir cobertura que não existe:

  * O SQL — a janela de 1h, o `count(*) FILTER`, o índice parcial em welcome_wamid — só o
    Postgres responde de verdade, e foi exercido contra o banco real durante as Fases 3 e 4
    (dry-run de 254 leads, replay hora a hora do incidente). Um dublê que "confirmasse" o
    resultado de um GROUP BY estaria confirmando a si mesmo.
  * A LÓGICA — o pareamento por wamid, a recusa a desfazer um `failed`, o savepoint que
    protege o lote, as transições do alerta e a histerese entre os dois limiares — é o que
    este arquivo cobre, e cobre de verdade: `_realimentar_welcome_status`, `receive_webhook`
    e `delivery_health.avaliar` rodam de fato, não são mockados.

  1. failed no webhook -> welcome_status='failed' + erro literal da Meta gravado
  2. delivered -> welcome_status='delivered' (e read também)
  3. status de mensagem que NÃO é boas-vindas -> exact_leads intacta
  4. falha ao atualizar o lead -> o lote de status segue processando
  5. alerta: 10 envios / 6 falhas -> notifica a gestão
  6. alerta: mesma condição no ciclo seguinte -> NÃO notifica de novo
  7. recuperação: taxa cai para 0 -> notifica normalização, uma vez só
  8. volume baixo (3 envios, 3 falhas) -> NÃO alerta
  9. endpoints de disparo sem token -> 401
 10. regressão dos suites existentes
"""
import asyncio
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import delivery_health as dh
from app import main as app_main
from app.models import ExactLead, Notification

falhas = []


def check(nome, condicao, detalhe=""):
    print(f"  {'✅' if condicao else '❌'} {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


# ==========================================================================================
# DUBLÊS
# ==========================================================================================

class ResultadoFalso:
    def __init__(self, valor=None):
        self._valor = valor

    def scalar_one_or_none(self):
        return self._valor

    def scalar(self):
        return self._valor

    def first(self):
        return self._valor


class SavepointFalso:
    """Emula begin_nested: na exceção, desfaz o que foi adicionado DENTRO dele e propaga."""
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
        return False


class SessaoFalsa:
    """Sessão em memória. Nenhuma conexão aberta, nada gravado."""
    def __init__(self, resposta_execute=None):
        self.adicionados = []
        self.statements = []
        self.savepoints = 0
        self.rollbacks = 0
        self.commits = 0
        self._resposta = resposta_execute

    def add(self, obj):
        self.adicionados.append(obj)

    async def flush(self):
        pass

    async def execute(self, stmt, *a, **kw):
        self.statements.append(stmt)
        if callable(self._resposta):
            return self._resposta(stmt)
        return ResultadoFalso()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    def begin_nested(self):
        return SavepointFalso(self)

    def notificacoes(self):
        return [o for o in self.adicionados if isinstance(o, Notification)]


def lead_falso(**kw):
    """Um ExactLead solto, sem sessão. Os atributos que o código toca, e só eles."""
    lead = ExactLead()
    lead.exact_id = kw.get("exact_id", 51111310)
    lead.name = kw.get("name", "Joziane de Oliveira")
    lead.welcome_wamid = kw.get("welcome_wamid", "wamid.BOASVINDAS123")
    lead.welcome_status = kw.get("welcome_status", "sent")
    lead.welcome_error = kw.get("welcome_error", None)
    return lead


def sessao_com_lead(lead):
    """Sessão que devolve `lead` para o SELECT de ExactLead e nada para o resto."""
    def responder(stmt):
        return ResultadoFalso(lead if "exact_leads" in str(stmt) else None)
    return SessaoFalsa(responder)


# Erro como `_erro_do_status` o devolve a partir do payload real da Meta.
ERRO_131042 = {
    "error_code": 131042,
    "error_title": "Business eligibility payment issue",
    "error_details": ("Message failed to send because your WhatsApp Business account "
                      "has a payment issue."),
}


# ==========================================================================================
# 1: failed -> welcome_status='failed' com o motivo literal
# ==========================================================================================

async def teste_1_failed_carimba_lead():
    print("\n1) failed no webhook → welcome_status='failed' + erro literal")
    lead = lead_falso()
    db = sessao_com_lead(lead)

    await app_main._realimentar_welcome_status(
        "wamid.BOASVINDAS123", "failed", ERRO_131042, db)

    check("welcome_status virou 'failed'", lead.welcome_status == "failed",
          repr(lead.welcome_status))
    check("welcome_error tem o código da Meta", "131042" in (lead.welcome_error or ""),
          repr(lead.welcome_error))
    check("welcome_error tem o details LITERAL, não o title",
          "payment issue." in (lead.welcome_error or ""), repr(lead.welcome_error))

    # Falha sem nenhum detalhe não pode virar welcome_error vazio: um lead 'failed' sem motivo
    # é a mesma cegueira de antes, só que com outro rótulo.
    lead2 = lead_falso()
    await app_main._realimentar_welcome_status(
        "wamid.BOASVINDAS123", "failed", {}, sessao_com_lead(lead2))
    check("falha sem detalhe ainda grava um motivo legível",
          lead2.welcome_status == "failed" and bool(lead2.welcome_error),
          repr(lead2.welcome_error))


# ==========================================================================================
# 2: delivered / read -> 'delivered'
# ==========================================================================================

async def teste_2_delivered_carimba_entregue():
    print("\n2) delivered → welcome_status='delivered'")
    lead = lead_falso()
    await app_main._realimentar_welcome_status(
        "wamid.BOASVINDAS123", "delivered", {}, sessao_com_lead(lead))
    check("delivered → 'delivered'", lead.welcome_status == "delivered",
          repr(lead.welcome_status))

    lido = lead_falso()
    await app_main._realimentar_welcome_status(
        "wamid.BOASVINDAS123", "read", {}, sessao_com_lead(lido))
    check("read também vira 'delivered'", lido.welcome_status == "delivered",
          repr(lido.welcome_status))

    # A defesa contra webhook fora de ordem: entrega NÃO desfaz falha.
    ja_falhou = lead_falso(welcome_status="failed", welcome_error="131042 — payment issue")
    await app_main._realimentar_welcome_status(
        "wamid.BOASVINDAS123", "delivered", {}, sessao_com_lead(ja_falhou))
    check("delivered NÃO desfaz um 'failed' anterior",
          ja_falhou.welcome_status == "failed" and ja_falhou.welcome_error is not None,
          repr(ja_falhou.welcome_status))

    # 'sent' não é notícia: é o que o envio já carimbou.
    intacto = lead_falso(welcome_status="sent")
    await app_main._realimentar_welcome_status(
        "wamid.BOASVINDAS123", "sent", {}, sessao_com_lead(intacto))
    check("status 'sent' não mexe em nada", intacto.welcome_status == "sent")


# ==========================================================================================
# 3: status que não é de boas-vindas -> exact_leads intacta
# ==========================================================================================

async def teste_3_nao_boas_vindas_nao_toca():
    print("\n3) status de mensagem que NÃO é boas-vindas → exact_leads intacta")

    # Nenhum lead casa com o wamid: é o caso de mensagem de atendente, campanha ou NAT.
    db = SessaoFalsa(lambda stmt: ResultadoFalso(None))
    await app_main._realimentar_welcome_status(
        "wamid.DE_UM_ATENDENTE", "failed", ERRO_131042, db)
    check("wamid sem lead correspondente → nada gravado", db.adicionados == [])

    # A guarda que impede o carimbo em massa: sem wamid, `welcome_wamid == None` viraria
    # IS NULL e casaria com os 8.391 leads que nunca tiveram envio.
    for vazio in (None, ""):
        db_vazio = SessaoFalsa(lambda stmt: ResultadoFalso(lead_falso()))
        await app_main._realimentar_welcome_status(vazio, "failed", ERRO_131042, db_vazio)
        check(f"wamid {vazio!r} sai antes de consultar (sem carimbo em massa)",
              db_vazio.statements == [], f"{len(db_vazio.statements)} query(ies)")


# ==========================================================================================
# 4: falha ao atualizar o lead não derruba o lote de status
# ==========================================================================================

async def teste_4_falha_nao_derruba_lote():
    print("\n4) falha ao atualizar o lead → o lote de status segue processando")

    mensagens = {w: SimpleNamespace(wa_message_id=w, status="sent", error_code=None,
                                    error_title=None, error_details=None)
                 for w in ("wamid.A", "wamid.B", "wamid.C")}

    def responder(stmt):
        texto = str(stmt)
        if "messages" in texto and "exact_leads" not in texto:
            # devolve a Message do wamid que está sendo consultado
            for w, m in mensagens.items():
                if w in str(stmt.compile(compile_kwargs={"literal_binds": True})):
                    return ResultadoFalso(m)
        return ResultadoFalso(None)

    db = SessaoFalsa(responder)

    corpo = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"statuses": [
            {"id": "wamid.A", "status": "delivered"},
            {"id": "wamid.B", "status": "failed",
             "errors": [{"code": 131042, "title": "payment", "error_data":
                         {"details": "payment issue"}}]},
            {"id": "wamid.C", "status": "read"},
        ]}}]}]
    }
    request = SimpleNamespace(json=AsyncMock(return_value=corpo))

    # O do meio explode. Sem o savepoint + except do webhook, a transação do asyncpg ficaria
    # abortada e o wamid.C nem seria tentado.
    async def realimentar_com_bomba(wa_message_id, novo_status, erro, db_):
        if wa_message_id == "wamid.B":
            raise RuntimeError("banco fora do ar no meio do lote")

    # httpx mockado: sem isto o webhook faz um POST REAL para a CS Platform.
    with patch.object(app_main, "_realimentar_welcome_status", realimentar_com_bomba), \
         patch.object(app_main.httpx, "AsyncClient") as relay:
        relay.return_value.__aenter__.return_value.post = AsyncMock()
        await app_main.receive_webhook(request, db)

    check("o status ANTERIOR ao erro foi aplicado",
          mensagens["wamid.A"].status == "delivered", mensagens["wamid.A"].status)
    check("o status POSTERIOR ao erro foi aplicado (o lote não parou)",
          mensagens["wamid.C"].status == "read", mensagens["wamid.C"].status)
    check("a mensagem que falhou ainda teve o próprio status/erro gravados",
          mensagens["wamid.B"].status == "failed"
          and mensagens["wamid.B"].error_code == 131042,
          f"status={mensagens['wamid.B'].status} code={mensagens['wamid.B'].error_code}")
    check("o savepoint foi revertido, não a transação inteira",
          db.rollbacks == 1 and db.savepoints == 3,
          f"savepoints={db.savepoints} rollbacks={db.rollbacks}")


# ==========================================================================================
# DUBLÊ DO ALERTA DE SAÚDE
# ==========================================================================================

class SessaoSaude(SessaoFalsa):
    """Sessão que responde às 3 consultas do delivery_health a partir de números fixos.

    O estado do alerta NÃO é fixo: sai das notificações que os próprios ciclos adicionaram, que
    é como o código lê em produção (`ORDER BY id DESC`). É o que torna os testes 6 e 7 reais —
    com estado chumbado, "não notifica de novo" passaria mesmo num código que notificasse.
    """
    def __init__(self, total, falhas_, erro_top=None):
        super().__init__()
        self.total, self.falhas_, self.erro_top = total, falhas_, erro_top

    def ajustar(self, total, falhas_):
        self.total, self.falhas_ = total, falhas_
        return self

    async def execute(self, stmt, *a, **kw):
        texto = str(stmt)
        self.statements.append(stmt)

        if "FROM notifications" in texto:
            saude = [n for n in self.notificacoes()
                     if n.type in (dh.TIPO_QUEBROU, dh.TIPO_VOLTOU)]
            return ResultadoFalso(
                SimpleNamespace(type=saude[-1].type) if saude else None)

        if "coalesce(error_code" in texto:
            return ResultadoFalso(
                SimpleNamespace(codigo=self.erro_top, n=self.falhas_)
                if self.erro_top else None)

        if "count(*) FILTER" in texto:
            return ResultadoFalso(
                SimpleNamespace(total=self.total, falhas=self.falhas_))

        # select(User.id) — a gestora existe.
        return ResultadoFalso((dh.GESTOR_USER_ID,))


# ==========================================================================================
# 5 e 6: quebra e não-repetição
# ==========================================================================================

async def teste_5_alerta_quebrou():
    print("\n5) 10 envios / 6 falhas → notifica a gestão")
    db = SessaoSaude(total=10, falhas_=6, erro_top="131042")
    r = await dh.avaliar(db)

    notifs = db.notificacoes()
    check("uma notificação criada", len(notifs) == 1, f"{len(notifs)}")
    check("foi do tipo de quebra", bool(notifs) and notifs[0].type == dh.TIPO_QUEBROU)
    check("endereçada à gestão (id=2)",
          bool(notifs) and notifs[0].user_id == dh.GESTOR_USER_ID)
    check("transição registrada como normal→alerta",
          r["estado_anterior"] == "normal" and r["estado"] == "alerta")
    corpo = notifs[0].body if notifs else ""
    check("corpo traz total, falhas e taxa",
          "6 de 10" in corpo and "60%" in corpo, corpo)
    check("corpo traz o error_code mais frequente", "131042" in corpo, corpo)


async def teste_6_nao_repete():
    print("\n6) mesma condição no ciclo seguinte → NÃO notifica de novo")
    db = SessaoSaude(total=10, falhas_=6, erro_top="131042")
    await dh.avaliar(db)                      # ciclo 1: quebra
    r2 = await dh.avaliar(db)                 # ciclo 2: mesma condição
    r3 = await dh.avaliar(db)                 # ciclo 3: idem

    check("segue com UMA notificação depois de 3 ciclos",
          len(db.notificacoes()) == 1, f"{len(db.notificacoes())}")
    check("ciclo 2 não registrou transição", r2["transicao"] is None)
    check("ciclo 3 não registrou transição", r3["transicao"] is None)
    check("estado continua 'alerta'", r3["estado"] == "alerta")

    # Histerese: entre 10% e 50% ninguém é avisado de nada.
    r4 = await dh.avaliar(db.ajustar(total=10, falhas_=3))   # 30%
    check("taxa de 30% (entre os limiares) não normaliza nem re-alerta",
          r4["transicao"] is None and r4["estado"] == "alerta")


# ==========================================================================================
# 7: recuperação
# ==========================================================================================

async def teste_7_recuperacao():
    print("\n7) taxa cai para 0 → notifica normalização, uma vez só")
    db = SessaoSaude(total=10, falhas_=6, erro_top="131042")
    await dh.avaliar(db)                                     # quebra

    # ANTES de normalizar: 128 envios com 3 falhas é 2%, abaixo do limiar de 10% — mas com
    # falhas reais. É o cenário de 24/07: uma campanha em massa saudável escondendo a
    # boas-vindas 100% morta. Anunciar "normalizou" aqui seria um falso "está tudo bem".
    r_falso = await dh.avaliar(db.ajustar(total=128, falhas_=3))
    check("taxa de 2% COM falhas não anuncia normalização (anti-diluição)",
          r_falso["transicao"] is None and r_falso["estado"] == "alerta",
          f"transicao={r_falso['transicao']}")

    db.erro_top = None
    r = await dh.avaliar(db.ajustar(total=10, falhas_=0))
    notifs = db.notificacoes()
    check("normalização notificada", len(notifs) == 2 and notifs[1].type == dh.TIPO_VOLTOU,
          f"{[n.type for n in notifs]}")
    check("transição registrada como alerta→normal",
          r["estado_anterior"] == "alerta" and r["estado"] == "normal")

    r2 = await dh.avaliar(db)
    check("ciclo seguinte não notifica de novo",
          len(db.notificacoes()) == 2 and r2["transicao"] is None)


# ==========================================================================================
# 8: volume baixo
# ==========================================================================================

async def teste_8_volume_baixo():
    print("\n8) 3 envios / 3 falhas → NÃO alerta (abaixo do mínimo)")
    db = SessaoSaude(total=3, falhas_=3, erro_top="131042")
    r = await dh.avaliar(db)
    check("nenhuma notificação com 3 envios", db.notificacoes() == [],
          f"{len(db.notificacoes())}")
    check("estado continua normal apesar de 100% de falha",
          r["estado"] == "normal" and r["transicao"] is None)

    # E o outro lado do mesmo piso: hora vazia não pode anunciar "voltou ao normal".
    db2 = SessaoSaude(total=10, falhas_=6)
    await dh.avaliar(db2)                                    # entra em alerta
    r2 = await dh.avaliar(db2.ajustar(total=0, falhas_=0))
    check("janela sem nenhum envio NÃO anuncia normalização",
          r2["transicao"] is None and r2["estado"] == "alerta",
          f"transicao={r2['transicao']}")


# ==========================================================================================
# 9: autenticação
# ==========================================================================================

def teste_9_endpoints_sem_token():
    print("\n9) endpoints de disparo sem token → 401")
    from fastapi.testclient import TestClient
    # Sem context manager: o lifespan NÃO roda, nenhum job sobe, nenhuma conexão é aberta.
    c = TestClient(app_main.app)

    casos = [
        ("/api/send/text", {"json": {"channel_id": 1, "to": "5511999999999", "text": "x"}}),
        ("/api/send/template", {"json": {"channel_id": 1, "to": "5511999999999",
                                         "template_name": "x", "language": "pt_BR"}}),
        ("/api/send/media", {"data": {"to": "5511999999999", "channel_id": "1",
                                      "type": "image"},
                             "files": {"file": ("a.png", b"x", "image/png")}}),
        ("/api/exact-leads/bulk-send-template",
         {"json": {"template_name": "x", "channel_id": 1, "lead_ids": [1]}}),
    ]
    for url, kw in casos:
        r = c.post(url, **kw)
        check(f"POST {url} sem token → 401", r.status_code == 401, f"{r.status_code}")

    r = c.post("/api/send/text", json={"channel_id": 1, "to": "5511999999999", "text": "x"},
               headers={"Authorization": "Bearer token-invalido"})
    check("POST /api/send/text com token inválido → 401", r.status_code == 401,
          f"{r.status_code}")


# ==========================================================================================
# 10: regressão
# ==========================================================================================

def regressao():
    print("\n10) Regressão dos suites existentes")
    for nome in ("test_nat_sprint3", "test_nat_flow", "test_nat_guard",
                 "test_welcome_guardrail", "test_parse_datetime"):
        r = subprocess.run([sys.executable, f"{nome}.py"], capture_output=True, text=True)
        linha = next((l for l in reversed(r.stdout.splitlines())
                      if l.startswith("OK:") or "TODOS OS TESTES" in l
                      or "Todos os testes" in l), "(sem resumo)")
        check(f"{nome}", r.returncode == 0, linha.strip()[:90])


async def main():
    print("\n" + "=" * 90)
    print("OBSERVABILIDADE DE ENVIO — realimentação, alerta de saúde e autenticação")
    print("Nada enviado. Nada gravado. Nenhuma conexão de banco. Nenhuma chamada de rede.")
    print("=" * 90)

    await teste_1_failed_carimba_lead()
    await teste_2_delivered_carimba_entregue()
    await teste_3_nao_boas_vindas_nao_toca()
    await teste_4_falha_nao_derruba_lote()
    await teste_5_alerta_quebrou()
    await teste_6_nao_repete()
    await teste_7_recuperacao()
    await teste_8_volume_baixo()
    teste_9_endpoints_sem_token()
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
