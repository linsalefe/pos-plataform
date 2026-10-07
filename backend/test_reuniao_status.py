"""Bloco 0 — espelho das reuniões da Exact (`reuniao_status`) e o guard do lembrete.

    cd backend && venv/bin/python test_reuniao_status.py

NADA sai daqui: Exact mockada (`listar` injetado), banco dublê. Escrito e NÃO executado na
sprint de 07/10 (convenção do bloco).

O BURACO (RECON_CONFIRMACAO_NOSHOW_20261007 §2)
  `agendamentos.passo` nunca sai de `agendado`. 4 lembretes T-30 saíram para reunião já
  remarcada e 2 pendentes eram de reunião `Cancelada` na Exact.

O QUE ESTE TESTE PROVA
  1. `_normalizar`: startTime vai SEM conversão; registerDate (UTC) vira SP
  2. origem: marcador "Agendamento LP" -> hub; nulo/outro -> exact
  3. upsert: o SQL grava `exact_type_anterior` e `visto_em` só quando o tipo muda, e nunca
     toca `created_at`; a segunda passada conta como atualizada e registra a mudança
  4. Vigente -> Cancelada de reunião `hub` cancela o lembrete pendente e loga
  5. guard: Cancelada bloqueia com motivo; reunião mais nova do mesmo telefone bloqueia;
     sem espelho passa
  6. flag desligada: `sincronizar` não é chamado e o banco não é aberto
"""
import asyncio
import io
from contextlib import redirect_stdout
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app import reuniao_sync as rs
from app import qualificacao_guard as guard
from app.models import (EXACT_TYPE_CANCELADA, EXACT_TYPE_VIGENTE, ORIGEM_REUNIAO_EXACT,
                        ORIGEM_REUNIAO_HUB)

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


AGORA = datetime(2026, 10, 7, 10, 0, 0)


def meeting(mid, tipo, *, desc="Agendamento LP — Ana", lead=51705390,
            fone="5583988887777", inicio="2026-10-09T14:30:00.0000000",
            reg="2026-10-07T12:00:00.1234567Z"):
    """Uma reunião no formato EXATO de GET /Meetings (RECON §5.2)."""
    return {"id": mid, "type": tipo, "registerDate": reg, "meetingType": "Online",
            "meetingDate": inicio[:10], "startTime": inicio,
            "finalTime": inicio[:11] + "15:15:00.0000000", "managerDescription": desc,
            "lead": {"id": lead, "name": "Ana Teste", "site": "", "phone": fone},
            "salesRep": {"id": 415967, "email": "comercial@cenatcursos.com.br"},
            "user": {"id": 443275, "email": "sdr@cenatsaudemental.com"}}


# ==========================================================================================
print("\n1. _normalizar: fusos")
l = rs._normalizar(meeting(4745629, "Concluido", inicio="2026-09-08T18:30:00.0000000",
                           reg="2026-09-04T16:06:50.4609863Z"))
checa("startTime 18:30 fica 18:30 (hora de parede, sem conversão)",
      l["slot_inicio"], datetime(2026, 9, 8, 18, 30))
checa("registerDate 16:06:50Z vira 13:06:50 SP", l["registrado_em"],
      datetime(2026, 9, 4, 13, 6, 50, 460986))
checa("register_date_utc fica em UTC (é o que o cursor compara)", l["register_date_utc"],
      datetime(2026, 9, 4, 16, 6, 50, 460986))
checa("telefone_chave = DDD + 8 últimos", l["telefone_chave"], "8388887777")
checa("meeting_id inteiro", l["meeting_id"], 4745629)

# ==========================================================================================
print("\n2. origem")
checa("prefixo 'Agendamento LP' -> hub", rs._origem("Agendamento LP — Fulana"),
      ORIGEM_REUNIAO_HUB)
checa("managerDescription nulo -> exact", rs._origem(None), ORIGEM_REUNIAO_EXACT)
checa("texto da SDR -> exact", rs._origem("Remarcado pela consultora"), ORIGEM_REUNIAO_EXACT)


# ==========================================================================================
# Banco dublê para `sincronizar`. Despacha pelo texto do statement.
class Res:
    def __init__(self, linhas=(), escalar=None, rowcount=0):
        self._linhas, self._escalar, self.rowcount = list(linhas), escalar, rowcount

    def all(self):
        return self._linhas

    def scalar_one_or_none(self):
        return self._escalar

    def first(self):
        return self._linhas[0] if self._linhas else None


class FakeDB:
    def __init__(self, *, antes=None, cursor_em=datetime(2026, 9, 7)):
        self.antes = antes or {}          # meeting_id -> exact_type já gravado
        self.cursor = SimpleNamespace(id=1, register_date_cursor=cursor_em,
                                      ultimo_ciclo_em=None, ultimo_ciclo_resultado=None)
        self.upserts, self.updates = [], []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "INSERT INTO reuniao_status" in sql:
            self.upserts.append(params)
            return Res()
        if "UPDATE nat_scheduled_actions" in sql:
            self.updates.append(stmt)
            return Res(rowcount=1)
        if "FROM reuniao_sync_cursor" in sql:
            return Res(escalar=self.cursor)
        if "FROM reuniao_status" in sql:
            return Res(linhas=list(self.antes.items()))
        if "FROM agendamentos" in sql and "meeting_id" in sql.split("FROM")[0]:
            return Res(linhas=[(m, 900 + i) for i, m in enumerate(self.antes)])
        return Res()

    async def flush(self):
        pass


def roda_sync(db, novas, janela):
    async def listar(*, register_date_ge=None, start_time_ge=None):
        return novas if register_date_ge is not None else janela
    saida = io.StringIO()
    with redirect_stdout(saida):
        r = asyncio.run(rs.sincronizar(db, listar=listar, agora=AGORA))
    return r, saida.getvalue()


# ==========================================================================================
print("\n3. upsert")
sql = str(rs.UPSERT)
checa("anterior só muda quando o tipo muda (IS DISTINCT FROM)",
      "exact_type_anterior = CASE WHEN reuniao_status.exact_type IS DISTINCT FROM" in sql, True)
checa("visto_em só muda quando o tipo muda",
      "exact_type_visto_em = CASE WHEN reuniao_status.exact_type IS DISTINCT FROM" in sql, True)
checa("created_at fora do SET (não muda numa segunda passada)",
      "created_at" not in sql.split("DO UPDATE SET")[1], True)
checa("agendamento_id nunca é apagado (COALESCE)",
      "COALESCE(reuniao_status.agendamento_id, EXCLUDED.agendamento_id)" in sql, True)

db = FakeDB()
r, _ = roda_sync(db, [meeting(1, EXACT_TYPE_VIGENTE)], [])
checa("primeira passada: 1 nova, 0 atualizada", (r["novas"], r["atualizadas"]), (1, 0))
checa("cursor avança para registerDate - 5 min",
      db.cursor.register_date_cursor, datetime(2026, 10, 7, 11, 55, 0, 123456))

db = FakeDB(antes={1: EXACT_TYPE_VIGENTE})
r, _ = roda_sync(db, [], [meeting(1, "Concluido", desc=None)])
checa("segunda passada com tipo diferente: atualizada e mudança registrada",
      (r["novas"], r["atualizadas"], r["mudancas"]), (0, 1, [(1, "Vigente", "Concluido")]))
checa("sem reunião nova, o cursor não anda", db.cursor.register_date_cursor,
      datetime(2026, 9, 7))
db = FakeDB()
roda_sync(db, [meeting(2, "Vigente")], [meeting(2, "Vigente")])
checa("a mesma reunião nas duas leituras vira UM upsert", len(db.upserts), 1)

# ==========================================================================================
pedidos = []


async def _listar_registra(*, register_date_ge=None, start_time_ge=None):
    pedidos.append(start_time_ge)
    return []

db = FakeDB()
asyncio.run(rs.sincronizar(db, listar=_listar_registra, agora=AGORA))
checa("primeiro ciclo relê o status desde o cursor (07/09)", pedidos[-1], datetime(2026, 9, 7))
db.cursor.ultimo_ciclo_em = AGORA
asyncio.run(rs.sincronizar(db, listar=_listar_registra, agora=AGORA))
checa("ciclos seguintes relêem só hoje - 2 dias", pedidos[-1], datetime(2026, 10, 5, 10, 0))

print("\n4. Vigente -> Cancelada de reunião hub")
db = FakeDB(antes={7: EXACT_TYPE_VIGENTE})
r, log = roda_sync(db, [], [meeting(7, EXACT_TYPE_CANCELADA)])
checa("lembrete pendente cancelado", r["lembretes_cancelados"], 1)
checa("um UPDATE em nat_scheduled_actions", len(db.updates), 1)
checa("log claro da mudança", "⚠️ reunião 7 do Hub (agendamento 900) virou Cancelada" in log,
      True)
db = FakeDB(antes={8: EXACT_TYPE_VIGENTE})
r, log = roda_sync(db, [], [meeting(8, EXACT_TYPE_CANCELADA, desc=None)])
checa("reunião marcada na Exact (origem exact) não mexe em lembrete", len(db.updates), 0)
db = FakeDB(antes={9: EXACT_TYPE_CANCELADA})
r, _ = roda_sync(db, [], [meeting(9, EXACT_TYPE_CANCELADA)])
checa("já estava Cancelada: nada a fazer de novo", len(db.updates), 0)


# ==========================================================================================
print("\n5. guard do lembrete")


class GuardDB:
    """Responde às duas consultas de `_espelho_bloqueia`, na ordem."""
    def __init__(self, propria, nova):
        self.respostas = [Res(escalar=propria), Res(linhas=[nova] if nova else [])]

    async def execute(self, stmt, params=None):
        return self.respostas.pop(0) if self.respostas else Res()


reuniao = SimpleNamespace(id=959, telefone="62999386070", created_at=datetime(2026, 10, 6, 10),
                          meeting_id=4773923)


def espelho(propria, nova=None):
    saida = io.StringIO()
    with redirect_stdout(saida):
        motivo = asyncio.run(guard._espelho_bloqueia(reuniao, AGORA, GuardDB(propria, nova)))
    return motivo, saida.getvalue()


cancelada = SimpleNamespace(meeting_id=4773923, exact_type=EXACT_TYPE_CANCELADA,
                            telefone_chave="6299386070", registrado_em=datetime(2026, 10, 6, 10))
m, _ = espelho(cancelada)
checa("Cancelada bloqueia com motivo", m, "reunião 4773923 está Cancelada na Exact")

vigente = SimpleNamespace(meeting_id=4773923, exact_type=EXACT_TYPE_VIGENTE,
                          telefone_chave="6299386070", registrado_em=datetime(2026, 10, 6, 10))
m, _ = espelho(vigente, (4779999, datetime(2026, 10, 10, 11, 0)))
checa("reunião mais nova do mesmo telefone bloqueia", m,
      "existe reunião mais nova para esta pessoa (remarcação): 4779999 em 10/10 11:00")

m, _ = espelho(vigente, None)
checa("Vigente e sem reunião mais nova: passa", m, None)

m, log = espelho(None, None)
checa("sem espelho: passa (fail-closed só sobre o que se sabe)", m, None)
checa("  e loga que seguiu sem espelho", "↩️ lembrete sem espelho" in log, True)

# ==========================================================================================
print("\n6. flag desligada")
chamado = []


async def _nao_chame(*a, **k):
    chamado.append(1)

with patch.dict("os.environ", {"REUNIAO_SYNC_ENABLED": "false"}), \
        patch.object(rs, "sincronizar", _nao_chame), \
        patch("app.database.async_session", side_effect=AssertionError("abriu o banco")):
    saida = io.StringIO()
    with redirect_stdout(saida):
        r = asyncio.run(rs.ciclo())
checa("devolve desligado", r, {"desligado": True})
checa("sincronizar não chamado", chamado, [])
checa("loga uma linha DESLIGADO", "reuniao_sync DESLIGADO" in saida.getvalue(), True)
for valor, esperado in (("true", True), (" TRUE ", True), ("1", True), ("", False),
                        ("tru", False), ("nao", False)):
    with patch.dict("os.environ", {"REUNIAO_SYNC_ENABLED": valor}):
        checa(f"flag {valor!r} -> {esperado}", rs.flag_ligada(), esperado)

# ==========================================================================================
print()
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ todos os casos passaram")
