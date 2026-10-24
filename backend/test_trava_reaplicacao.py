"""Trava de reaplicação: telefone com reunião Vigente e futura não cria lead nem reunião nova.

Rodar: cd backend && venv/bin/python test_trava_reaplicacao.py

Nenhuma conexão: a Exact, o RD e o agente são mockados, o banco é dublê em memória e as
rotas rodam num app mínimo via ASGITransport. Nada é criado na agenda real.

   1. predicado: chave do telefone, Vigente e slot_inicio > agora, a mais próxima
   2. telefone com e sem 55, com e sem o 9º dígito: a mesma chave
   3. telefone ilegível: não consulta, não trava
   4. /agendar com reunião e nome batendo: 200 com data e consultora, nada escrito fora
   5. /agendar com e-mail batendo e nome não: 200 com data
   6. /agendar sem nada batendo: 200 genérico (inicio/fim/consultora nulos)
   7. /lead com reunião: 200 com o lead_id da reunião, sem LeadsAdd nem RD
   8. linha `recusado/ja_agendado`: sem lead_id, sem box, com meeting_id, origem e extras
   9. sem reunião (Vigente passada, Cancelada, inexistente): fluxo normal
  10. reunião `origem=exact` (marcada pela SDR) trava igual
  11. rotas do token: identidade provada, dados sempre, link NÃO é consumido
  12. fluxo.agendar e cadastrar_lead_sem_agendar não conhecem a trava (agente, remarcação)
  13. _duplo_clique compara por todas as grafias do telefone
"""
import asyncio
import inspect
import io
import re
import os
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app import rd_outbox
from app.agendamento import agendar as fluxo
from app.agendamento import client, rastro, routes, trava
from app.agendamento import token as tokens
from app.agendamento.horarios import agora_sp
from app.database import get_db
from app.models import PASSO_RECUSADO, Agendamento, ReuniaoStatus
from app.telefone import chave_telefone

for _v in ("AGENDAMENTO_CONSULTORAS", "AGENDAMENTO_CONSULTORAS_PATH",
           "AGENDAMENTO_SUBSOURCES", "AGENDAMENTO_SUBSOURCE_PADRAO",
           "AGENDAMENTO_ORIGEM_ALIASES"):
    os.environ.pop(_v, None)
os.environ["AGENDAMENTO_SUBSOURCES"] = "PosMulheridades,Pos Grupos e Oficinas T2"
os.environ["AGENDAMENTO_SUBSOURCE_PADRAO"] = "PosMulheridades"

TELEFONE = "66999050115"
ORIGEM = "Pos Grupos e Oficinas T2"
WA = "https://wa.me/5511952137432"

_ip_seq = 0


def _novo_ip() -> str:
    global _ip_seq
    _ip_seq += 1
    return f"198.51.100.{_ip_seq}"


def checa(rotulo, obtido, esperado):
    assert obtido == esperado, f"{rotulo}: esperado {esperado!r}, obtido {obtido!r}"


def _reuniao(**extra) -> ReuniaoStatus:
    base = dict(meeting_id=4789461, lead_id=53195657, telefone_chave=chave_telefone(TELEFONE),
                telefone_bruto=TELEFONE, nome="José Roberto Lopes",
                slot_inicio=agora_sp().replace(microsecond=0, second=0) + timedelta(days=2),
                slot_fim=agora_sp().replace(microsecond=0, second=0) + timedelta(days=2, minutes=45),
                sales_rep_email="processoseletivo@cenatcursos.com.br", origem="hub",
                agendamento_id=1311, exact_type="Vigente")
    base.update(extra)
    return ReuniaoStatus(**base)


class _DbFalso:
    """Dublê de AsyncSession. `emails` é o que a consulta de e-mails da reunião devolve."""

    def __init__(self, *, reuniao=None, emails=()):
        self.adicionados = []
        self.statements = []
        self.commits = 0
        self._reuniao = reuniao
        self._emails = list(emails)
        self._proximo_id = 1

    async def execute(self, stmt, *a, **k):
        self.statements.append(stmt)
        res = MagicMock()
        res.scalar_one_or_none.return_value = self._reuniao
        res.scalars.return_value.all.return_value = self._emails
        return res

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self._proximo_id
            self._proximo_id += 1
        self.adicionados.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    def recusados(self):
        return [o for o in self.adicionados
                if isinstance(o, Agendamento) and o.passo == PASSO_RECUSADO]


def _app(db) -> FastAPI:
    app = FastAPI()
    app.include_router(routes.router)
    app.add_exception_handler(RequestValidationError, routes.validacao_recusada)

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    return app


async def _post(db, caminho, corpo):
    saida = io.StringIO()
    transporte = httpx.ASGITransport(app=_app(db))
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as c:
        with redirect_stdout(saida):
            r = await c.post(caminho, json=corpo, headers={"x-forwarded-for": _novo_ip()})
    return r, saida.getvalue()


def _corpo(**extra):
    base = {"nome": "José Roberto Lopes", "email": "jose@example.com",
            "telefone": TELEFONE, "origem": ORIGEM, "extras": {"Profissão": "Psicóloga"}}
    base.update(extra)
    return base


class _Escritas:
    """Tudo que a reaplicação travada NÃO pode chamar, mockado de uma vez."""

    def __enter__(self):
        self.agendar = AsyncMock(side_effect=AssertionError("fluxo.agendar chamado"))
        self.cadastrar = AsyncMock(side_effect=AssertionError("cadastrar chamado"))
        self.criar_lead = AsyncMock(side_effect=AssertionError("LeadsAdd chamado"))
        self.criar_box = AsyncMock(side_effect=AssertionError("BoxesAdd chamado"))
        self.rd = AsyncMock(side_effect=AssertionError("fila do RD chamada"))
        self.consumir = AsyncMock(side_effect=AssertionError("token consumido"))
        self._p = [patch.object(fluxo, "agendar", self.agendar),
                   patch.object(fluxo, "cadastrar_lead_sem_agendar", self.cadastrar),
                   patch.object(client, "criar_lead", self.criar_lead),
                   patch.object(client, "criar_box", self.criar_box),
                   patch.object(rd_outbox, "enfileirar", self.rd),
                   patch.object(tokens, "consumir", self.consumir),
                   patch.object(trava, "whatsapp_url", AsyncMock(return_value=WA))]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._p:
            p.stop()


def _sql(stmt) -> tuple[str, dict]:
    comp = stmt.compile()
    return str(comp), comp.params


# ==========================================================================================

async def caso_1_predicado():
    db = _DbFalso(reuniao=_reuniao())
    r = await trava.reuniao_vigente_futura(db, TELEFONE)
    checa("devolve a reunião", r.meeting_id, 4789461)
    sql, params = _sql(db.statements[0])
    for trecho in ("reuniao_status.telefone_chave =", "reuniao_status.exact_type =",
                   "reuniao_status.slot_inicio >", "ORDER BY reuniao_status.slot_inicio ASC"):
        assert trecho in sql, f"predicado sem {trecho!r}: {sql}"
    checa("chave", params["telefone_chave_1"], chave_telefone(TELEFONE))
    checa("Vigente", params["exact_type_1"], "Vigente")
    print("  1. predicado: chave, Vigente, slot futuro, a mais próxima")


async def caso_2_grafias():
    chaves = {chave_telefone(t) for t in
              ("66999050115", "5566999050115", "6699050115", "556699050115")}
    checa("uma chave só", len(chaves), 1)
    for t in ("5566999050115", "6699050115"):
        db = _DbFalso(reuniao=_reuniao())
        await trava.reuniao_vigente_futura(db, t)
        checa(f"chave de {t}", _sql(db.statements[0])[1]["telefone_chave_1"],
              chave_telefone(TELEFONE))
    print("  2. com e sem 55, com e sem 9º dígito: mesma chave")


async def caso_3_ilegivel():
    db = _DbFalso(reuniao=_reuniao())
    checa("ilegível não trava", await trava.reuniao_vigente_futura(db, "123"), None)
    checa("nem consulta", db.statements, [])
    print("  3. telefone ilegível: não consulta, não trava")


async def caso_4_agendar_nome_bate():
    db = _DbFalso(reuniao=_reuniao())
    with _Escritas() as e:
        r, log = await _post(db, "/api/agendamento/agendar",
                             _corpo(nome="  JOSE da silva", email="outro@x.com",
                                    slot="2026-10-28T10:00"))
    checa("status", r.status_code, 200)
    d = r.json()
    checa("ja_agendado", d["ja_agendado"], True)
    checa("lead da reunião", d["lead_id"], 53195657)
    checa("inicio", d["inicio"], _reuniao().slot_inicio.strftime("%Y-%m-%dT%H:%M:%S"))
    assert d["consultora_nome"], "consultora deveria vir"
    checa("whatsapp", d["whatsapp_url"], WA)
    for m in (e.agendar, e.criar_lead, e.criar_box, e.rd):
        m.assert_not_called()
    assert "🔁 reaplicação travada:" in log, log
    print("  4. /agendar, nome bate (sem acento, caixa): 200 com data, nada escrito fora")


async def caso_5_email_bate():
    db = _DbFalso(reuniao=_reuniao(), emails=["Jose@Example.com "])
    with _Escritas():
        r, _ = await _post(db, "/api/agendamento/agendar",
                           _corpo(nome="Maria Souza", slot="2026-10-28T10:00"))
    checa("status", r.status_code, 200)
    assert r.json()["inicio"], "e-mail bateu: data deveria vir"
    print("  5. e-mail bate e nome não: 200 com data")


async def caso_6_nada_bate():
    db = _DbFalso(reuniao=_reuniao(), emails=["jose@example.com"])
    with _Escritas():
        r, _ = await _post(db, "/api/agendamento/agendar",
                           _corpo(nome="Maria Souza", email="maria@x.com",
                                  slot="2026-10-28T10:00"))
    d = r.json()
    checa("status", r.status_code, 200)
    checa("ja_agendado", d["ja_agendado"], True)
    for k in ("inicio", "fim", "consultora_nome"):
        checa(k, d[k], None)
    checa("mensagem", d["mensagem"], trava.MENSAGEM_GENERICA)
    print("  6. nada bate: 200 genérico")


async def caso_7_lead():
    db = _DbFalso(reuniao=_reuniao())
    with _Escritas() as e:
        r, _ = await _post(db, "/api/agendamento/lead", _corpo())
    checa("status", r.status_code, 200)
    checa("lead_id da reunião", r.json()["lead_id"], 53195657)
    for m in (e.cadastrar, e.criar_lead, e.rd):
        m.assert_not_called()
    print("  7. /lead com reunião: lead existente, sem LeadsAdd nem RD")


async def caso_8_linha_recusada():
    db = _DbFalso(reuniao=_reuniao())
    with _Escritas():
        await _post(db, "/api/agendamento/lead", _corpo())
    linhas = db.recusados()
    checa("uma linha", len(linhas), 1)
    ln = linhas[0]
    checa("motivo", ln.motivo_recusa, rastro.JA_AGENDADO)
    checa("sem lead_id", ln.lead_id, None)
    checa("sem box", ln.box_id, None)
    checa("sem consultora", ln.sales_rep_email, "")
    checa("origem como veio", ln.sub_source, ORIGEM)
    checa("extras", ln.extras, {"Profissão": "Psicóloga"})
    assert "meeting_id=4789461" in ln.erro, ln.erro
    print("  8. linha recusado/ja_agendado com as invariantes do rastro")


async def caso_9_sem_reuniao_segue():
    # O banco dublê devolve None, que é o que o predicado dá para Vigente passada,
    # Cancelada ou inexistente (caso 1 prova que as três ficam fora do WHERE).
    db = _DbFalso(reuniao=None)
    cadastrar = AsyncMock(return_value=999)
    with patch.object(fluxo, "cadastrar_lead_sem_agendar", cadastrar):
        r, log = await _post(db, "/api/agendamento/lead", _corpo())
    checa("status", r.status_code, 200)
    checa("lead novo", r.json()["lead_id"], 999)
    assert "ja_agendado" not in r.json()
    cadastrar.assert_awaited_once()
    checa("nenhuma recusa", db.recusados(), [])
    print("  9. sem reunião Vigente futura: fluxo normal")


async def caso_10_origem_exact():
    db = _DbFalso(reuniao=_reuniao(origem="exact", agendamento_id=None))
    with _Escritas():
        r, _ = await _post(db, "/api/agendamento/agendar",
                           _corpo(slot="2026-10-28T10:00"))
    checa("trava", r.json().get("ja_agendado"), True)
    checa("agendamento_id nulo", r.json()["agendamento_id"], None)
    print(" 10. reunião marcada pela SDR na Exact trava igual")


async def caso_11_token():
    token = SimpleNamespace(contact_wa_id="5566999050115")
    resolvido = SimpleNamespace(ok=True, status="ativo", token=token)
    for rota, corpo in (("agendar", {"nome": "Outra Pessoa", "slot": "2026-10-28T10:00"}),
                        ("lead", {"nome": "Outra Pessoa"})):
        db = _DbFalso(reuniao=_reuniao())
        with _Escritas() as e, patch.object(tokens, "resolver",
                                            AsyncMock(return_value=resolvido)):
            r, _ = await _post(db, f"/api/agendamento/espontaneo/segredo123/{rota}", corpo)
        checa(f"{rota} status", r.status_code, 200)
        assert r.json()["inicio"], f"{rota}: token prova identidade, data deveria vir"
        e.consumir.assert_not_called()
        checa(f"{rota} rastro", [x.motivo_recusa for x in db.recusados()], ["ja_agendado"])
        checa(f"{rota} telefone do token", db.recusados()[0].telefone, "5566999050115")
    print(" 11. token: dados sempre, link não consumido, rastro com o telefone do token")


async def caso_12_fluxo_intocado():
    # Por uso e por import, não pela palavra: os comentários de agendar.py já dizem "trava"
    # (do duplo clique) e "travado" (da agenda).
    uso = re.compile(r"\btrava\.|reuniao_vigente_futura")
    for f in (fluxo.agendar, fluxo.cadastrar_lead_sem_agendar):
        assert not uso.search(inspect.getsource(f)), f"{f.__name__} conhece a trava"
    assert not re.search(r"^\s*(from|import)\b.*\btrava\b", inspect.getsource(fluxo),
                         re.M), "agendar.py importa a trava"
    print(" 12. fluxo.agendar e cadastrar_lead_sem_agendar não conhecem a trava")


async def caso_13_duplo_clique_por_chave():
    db = _DbFalso(reuniao=None)
    await fluxo._duplo_clique(db, "66999050115")
    sql, params = _sql(db.statements[0])
    assert "agendamentos.telefone IN" in sql, sql
    formas = set(next(v for v in params.values() if isinstance(v, (list, tuple))))
    checa("todas as grafias", formas,
          {"5566999050115", "66999050115", "556699050115", "6699050115"})
    print(" 13. _duplo_clique por todas as grafias do telefone")


async def main():
    print("\nTrava de reaplicação: Exact, RD e agente mockados, banco dublê, nada real\n")
    await caso_1_predicado()
    await caso_2_grafias()
    await caso_3_ilegivel()
    await caso_4_agendar_nome_bate()
    await caso_5_email_bate()
    await caso_6_nada_bate()
    await caso_7_lead()
    await caso_8_linha_recusada()
    await caso_9_sem_reuniao_segue()
    await caso_10_origem_exact()
    await caso_11_token()
    await caso_12_fluxo_intocado()
    await caso_13_duplo_clique_por_chave()
    print("\nOK: 13/13 passaram. Nenhum lead, box ou fila do RD.\n")


if __name__ == "__main__":
    asyncio.run(main())
