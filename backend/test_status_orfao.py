"""Status da Meta que chega antes do commit do envio não se perde mais.

    cd backend && venv/bin/python test_status_orfao.py

NADA sai daqui: o banco é falso, nenhuma sessão real é aberta, o relay para o CS é trocado
por um dublê e nada é enviado.

O DEFEITO (medido em 28/09 — SPRINT_FOLLOW_POR_CURSO_20260928_REPORT.md §7)
  `bulk_send_template` só faz commit no fim do lote, e o follow por estágio segura a transação
  até a nota na Exact. A Meta devolve `failed` em 1–2 s, o webhook procura o wamid, não acha
  e joga o status fora. De 21 a 28/09, 130 de 154 falhas logadas: as 130 linhas existem em
  `messages`, todas `sent`.

O QUE ESTE TESTE PROVA
  1. órfão que aparece na 3ª tentativa recebe o status e o erro, com um commit
  2. status atrasado não rebaixa ('delivered' depois de 'read' não apaga a leitura)
  3. 'failed' passa por cima de 'sent'
  4. mensagem que nunca aparece: desiste sem commit e sem levantar
  5. erro de banco numa tentativa não mata as seguintes
  6. a realimentação da boas-vindas roda na reaplicação
  7. 'sent' e wamid vazio não agendam nada; o teto recusa
  8. o webhook agenda o órfão e continua carimbando quem já está no banco
"""
import asyncio
import io
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import app.main as main
from app.database import get_db
from app.models import Message

falhas = []


def check(nome, condicao, detalhe=""):
    print(f"  {'✅' if condicao else '❌'} {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


ERRO = {"error_code": 131026, "error_title": "Message undeliverable",
        "error_details": "Message Undeliverable."}
SEM_ESPERA = (0, 0, 0, 0)


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Resultado:
    def __init__(self, valor):
        self.valor = valor

    def scalar_one_or_none(self):
        return self.valor


class _DB:
    """Sessão falsa. `respostas` é o que cada `execute` devolve, em ordem; uma Exception na
    lista é levantada no lugar."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.commits = 0

    async def execute(self, *_a, **_k):
        r = self.respostas.pop(0) if self.respostas else None
        if isinstance(r, Exception):
            raise r
        return _Resultado(r)

    def begin_nested(self):
        return _Savepoint()

    async def commit(self):
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _fabrica(db):
    """`async_session()` falso: toda tentativa abre a MESMA sessão falsa."""
    return lambda: db


def _msg(status):
    return Message(wa_message_id="wamid.X", contact_wa_id="5511999999999",
                   direction="outbound", message_type="template", status=status)


def _reaplicar(db, status, erro=None, esperas=SEM_ESPERA):
    saida = io.StringIO()
    with patch.object(main, "async_session", _fabrica(db)), \
            patch.object(main, "_realimentar_welcome_status", AsyncMock()) as welcome, \
            redirect_stdout(saida):
        ok = asyncio.run(main._reaplicar_status_orfao("wamid.X", status, erro or {}, esperas))
    return ok, welcome, saida.getvalue()


print("1. órfão que aparece na 3ª tentativa")
m = _msg("sent")
db = _DB([None, None, m])
ok, welcome, log = _reaplicar(db, "failed", ERRO)
check("aplicou", ok is True)
check("status virou failed", m.status == "failed", m.status)
check("erro carimbado", (m.error_code, m.error_details) == (131026, "Message Undeliverable."))
check("um commit", db.commits == 1, str(db.commits))
check("log diz a tentativa", "tentativa 3" in log, log.strip())

print("2. status atrasado não rebaixa")
m = _msg("read")
db = _DB([m])
ok, _, _ = _reaplicar(db, "delivered")
check("devolve True (achou)", ok is True)
check("continua read", m.status == "read", m.status)

print("3. failed passa por cima de sent; delivered também")
m = _msg("sent")
_reaplicar(_DB([m]), "delivered")
check("sent → delivered", m.status == "delivered", m.status)

print("4. mensagem que nunca aparece")
db = _DB([])
ok, welcome, log = _reaplicar(db, "failed", ERRO)
check("desiste com False", ok is False)
check("sem commit", db.commits == 0)
check("welcome não chamada", welcome.await_count == 0)
check("log de desistência", "desistido" in log, log.strip())

print("5. erro de banco numa tentativa não mata as seguintes")
m = _msg("sent")
db = _DB([RuntimeError("conexão caiu"), m])
ok, _, log = _reaplicar(db, "failed", ERRO)
check("aplicou na 2ª", ok is True and m.status == "failed", m.status)
check("a falha foi logada", "tentativa 1 falhou" in log, log.strip())

print("6. realimentação da boas-vindas na reaplicação")
m = _msg("sent")
ok, welcome, _ = _reaplicar(_DB([m]), "failed", ERRO)
check("chamada uma vez", welcome.await_count == 1)
check("com wamid, status e erro",
      welcome.await_args.args[:3] == ("wamid.X", "failed", ERRO), str(welcome.await_args))

print("7. o que não agenda")


async def _agendar_varios():
    with patch.object(main, "_reaplicar_status_orfao", AsyncMock(return_value=True)):
        r = {
            "sent": main.agendar_status_orfao("wamid.A", "sent", {}),
            "vazio": main.agendar_status_orfao("", "failed", ERRO),
            "failed": main.agendar_status_orfao("wamid.B", "failed", ERRO),
        }
        await asyncio.sleep(0)
        with patch.object(main, "_MAX_STATUS_ORFAOS", 0), redirect_stdout(io.StringIO()):
            r["teto"] = main.agendar_status_orfao("wamid.C", "failed", ERRO)
        return r


r = asyncio.run(_agendar_varios())
check("'sent' não agenda", r["sent"] is False)
check("wamid vazio não agenda", r["vazio"] is False)
check("'failed' agenda", r["failed"] is True)
check("teto recusa", r["teto"] is False)
check("tarefas concluídas saem do conjunto", len(main._status_orfaos) == 0,
      str(len(main._status_orfaos)))

print("8. o webhook agenda o órfão e carimba quem já está no banco")
presente = _msg("sent")
presente.wa_message_id = "wamid.PRESENTE"


class _DBWebhook(_DB):
    async def execute(self, stmt, *_a, **_k):
        texto = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "wamid.PRESENTE" in texto and "FROM messages" in texto:
            return _Resultado(presente)
        return _Resultado(None)


dbw = _DBWebhook([])


async def _dep():
    yield dbw


payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
    "statuses": [
        {"id": "wamid.ORFAO", "status": "failed", "errors": [
            {"code": 131026, "title": "Message undeliverable",
             "error_data": {"details": "Message Undeliverable."}}]},
        {"id": "wamid.PRESENTE", "status": "delivered"},
    ]}}]}]}

main.app.dependency_overrides[get_db] = _dep
cliente_http = MagicMock()
cliente_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock()))
cliente_http.return_value.__aexit__ = AsyncMock(return_value=False)
saida = io.StringIO()
try:
    with patch.object(main.httpx, "AsyncClient", cliente_http), \
            patch.object(main, "agendar_status_orfao", MagicMock(return_value=True)) as ag, \
            redirect_stdout(saida):
        resp = TestClient(main.app).post("/webhook", json=payload)
finally:
    main.app.dependency_overrides.pop(get_db, None)
check("200", resp.status_code == 200, str(resp.status_code))
check("agendou só o órfão", [c.args[:2] for c in ag.call_args_list] == [("wamid.ORFAO", "failed")],
      str(ag.call_args_list))
check("erro repassado ao agendamento",
      ag.call_args_list and ag.call_args_list[0].args[2]["error_code"] == 131026)
check("o presente foi carimbado", presente.status == "delivered", presente.status)
check("log avisa a reaplicação", "reaplicação agendada" in saida.getvalue(), saida.getvalue())

print()
print("FALHAS:" if falhas else "TUDO OK", *falhas, sep="\n  - " if falhas else "")
raise SystemExit(1 if falhas else 0)
