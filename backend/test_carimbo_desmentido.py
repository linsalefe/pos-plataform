"""O carimbo do lead para de mentir quando a abertura não sai.

    cd backend && venv/bin/python test_carimbo_desmentido.py

NADA sai daqui: o banco é falso, nenhuma sessão real é aberta, nada é enviado.

O DEFEITO (medido em 29/08 — RECON_VAO_ESPONTANEO_20260829 §4.2)
  `exact_spotter.py:266` carimba `welcome_status='skipped'` + "agente de pré-qualificação
  assumiu a abertura" no instante em que a ação é ENFILEIRADA. A ação podia morrer 5 min ou
  2 dias depois e ninguém voltava no carimbo. O lead ficava invisível pelos três lados:
  `existing` no sync, não-NULL para o `reprocessar_leads_perdidos.py`, e com a ação em
  estado final para o agendador.

  7 leads assim na janela de 24-29/08 — 3 pela saída muda de 25/08 (Adriana Palhana,
  Josiqueila, Elidilza) e 4 pela grafia do telefone (Fernanda, Claudia, Sandra, Dyenifer).

O QUE ESTE TESTE PROVA
  1. `skipped` na abertura -> o carimbo é reescrito com o motivo REAL
  2. `welcome_status` NÃO é tocado (é a trava de idempotência, não o que estava errado)
  3. só o carimbo que mente é reescrito (WHERE exige o texto "assumiu a abertura")
  4. `falhou` terminal desmente igual — é tão terminal quanto `skipped`
  5. `executado` e `adiado` NÃO desmentem: ali o carimbo continua verdadeiro
  6. lembrete não mexe em carimbo nenhum (só a abertura nasce daquele texto)
  7. ação sem `lead_id` no payload não faz UPDATE (LP que ainda não virou lead)
  8. erro no UPDATE não derruba o registro do desfecho da ação
"""
import asyncio
import io
from contextlib import redirect_stdout
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app import nat_scheduler as sched
from app.models import (ACAO_EXECUTADO, ACAO_FALHOU, ACAO_SKIPPED,
                        KIND_INICIAR_QUALIFICACAO)
from app.nat_scheduler import ACAO_ADIADO, AcaoAdiada, AcaoIgnorada

AGORA = datetime(2026, 8, 31, 9, 0, 0)
falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _DB:
    """Banco falso que GUARDA os statements. É o que permite ler o UPDATE compilado."""

    def __init__(self, rowcount=1, erro=None):
        self.stmts = []
        self._rowcount = rowcount
        self._erro = erro

    def begin_nested(self):
        return _Savepoint()

    async def execute(self, stmt, *a, **kw):
        if self._erro is not None:
            raise self._erro
        self.stmts.append(stmt)
        return MagicMock(rowcount=self._rowcount)


def _sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def _updates_de_lead(db) -> list:
    return [s for s in db.stmts if "exact_leads" in _sql(s).lower()]


def _acao(kind=KIND_INICIAR_QUALIFICACAO, payload='{"lead_id": 51610928, "origem": "exact"}'):
    return {"id": 360, "kind": kind, "contact_wa_id": "5549999333881", "run_at": AGORA,
            "payload": payload, "attempts": 0, "agora": AGORA}


def desmente(db, dados=None, motivo="abertura não saiu: contato não existe no banco"):
    buf = io.StringIO()
    with redirect_stdout(buf):
        asyncio.run(sched._desmentir_carimbo_do_lead(db, dados or _acao(), motivo))
    return buf.getvalue()


# ==========================================================================================
print("\n1) `skipped` na abertura — o carimbo é reescrito com o motivo REAL")

db = _DB()
saida = desmente(db)
ups = _updates_de_lead(db)
checa("um UPDATE em exact_leads", len(ups), 1)
sql = _sql(ups[0]) if ups else ""
checa("  com o motivo real gravado",
      "agente NÃO abriu: abertura não saiu: contato não existe no banco" in sql, True)
checa("  mirando o lead do payload", "51610928" in sql, True)
checa("  e avisando no log", "carimbo do lead 51610928 corrigido" in saida, True)


# ==========================================================================================
print("\n2) `welcome_status` NÃO é tocado — ele é a trava, não o erro")

checa("o SET tem welcome_error", "welcome_error=" in sql.replace(" ", ""), True)
checa("  e NÃO tem welcome_status",
      "welcome_status=" in sql.split("WHERE")[0].replace(" ", ""), False)
checa("  (o status segue como condição no WHERE)",
      "welcome_status" in sql.split("WHERE")[1], True)


# ==========================================================================================
print("\n3) Só o carimbo que MENTE é reescrito")

checa("o WHERE exige o texto do sync", "assumiu a abertura" in sql, True)
checa("  e exige que o status já seja skipped", ACAO_SKIPPED in sql.split("WHERE")[1], True)

db = _DB(rowcount=0)                       # carimbo verdadeiro: o WHERE não casa
saida = desmente(db)
checa("o UPDATE sai, mas não acerta linha nenhuma", len(_updates_de_lead(db)), 1)
checa("  e por isso NÃO vira aviso no log", "corrigido" in saida, False)


# ==========================================================================================
print("\n4) Lembrete não mexe em carimbo nenhum")

db = _DB()
desmente(db, _acao(kind="lembrete_reuniao", payload='{"agendamento_id": 187}'))
checa("nenhum UPDATE de lead", len(_updates_de_lead(db)), 0)


# ==========================================================================================
print("\n5) Ação sem lead_id — a LP que ainda não virou lead na Exact")

db = _DB()
desmente(db, _acao(payload='{"origem": "lp"}'))
checa("nenhum UPDATE de lead", len(_updates_de_lead(db)), 0)

db = _DB()
desmente(db, _acao(payload=None))
checa("payload NULL também não quebra", len(_updates_de_lead(db)), 0)

db = _DB()
desmente(db, _acao(payload="{isto não é json"))
checa("payload ilegível também não quebra", len(_updates_de_lead(db)), 0)


# ==========================================================================================
print("\n6) Erro no UPDATE não derruba nada — falha fechada, e avisa")

db = _DB(erro=RuntimeError("conexão caiu"))
saida = desmente(db)                                 # não levanta: chegar aqui já é metade
checa("engoliu o erro e seguiu", "conexão caiu" in saida, True)
checa("  dizendo que não deu para corrigir", "não deu para corrigir o carimbo" in saida, True)


# ==========================================================================================
# A FIAÇÃO — `_executar_acao` chama isto nos desfechos certos, e só neles.
# ==========================================================================================
def roda_acao(resultado):
    """Roda `_executar_acao` com um handler que produz `resultado`. Devolve (status, mock)."""
    async def handler(dados, db):
        if isinstance(resultado, Exception):
            raise resultado

    acao = MagicMock(id=360, kind=KIND_INICIAR_QUALIFICACAO,
                     contact_wa_id="5549999333881", run_at=AGORA,
                     payload='{"lead_id": 51610928}', attempts=2)
    mock = AsyncMock()
    db = _DB()
    with patch.object(sched, "_resolver_handler", new=MagicMock(return_value=handler)), \
         patch.object(sched, "_finalizar", new=AsyncMock()), \
         patch.object(sched, "_desmentir_carimbo_do_lead", new=mock):
        buf = io.StringIO()
        with redirect_stdout(buf):
            status = asyncio.run(sched._executar_acao(acao, db, AGORA))
    return status, mock


print("\n7) `skipped` desmente; `executado` e `adiado` não")

status, mock = roda_acao(AcaoIgnorada("já tem estado (concluido)"))
checa("AcaoIgnorada -> skipped", status, ACAO_SKIPPED)
checa("  e desmentiu o carimbo", mock.await_count, 1)
checa("  com o motivo da ação", mock.await_args.args[2], "já tem estado (concluido)")

status, mock = roda_acao(None)
checa("handler ok -> executado", status, ACAO_EXECUTADO)
checa("  e NÃO desmentiu (o carimbo está certo)", mock.await_count, 0)

status, mock = roda_acao(AcaoAdiada(AGORA, "fora do horário comercial (20:39)"))
checa("AcaoAdiada -> volta a pendente", status, ACAO_ADIADO)
checa("  e NÃO desmentiu: a abertura ainda vai sair", mock.await_count, 0)


# ==========================================================================================
print("\n8) `falhou` terminal desmente — some o lead do mesmo jeito")

status, mock = roda_acao(RuntimeError("Meta fora do ar"))
checa("3ª tentativa -> falhou", status, ACAO_FALHOU)
checa("  e desmentiu o carimbo", mock.await_count, 1)
checa("  com o erro real", "Meta fora do ar" in mock.await_args.args[2], True)


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} teste(s) falharam:")
    for f in falhas:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado.")
