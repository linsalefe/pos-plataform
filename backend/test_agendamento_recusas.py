"""Rastro das tentativas recusadas — toda recusa de /lead e /agendar deixa nome e telefone.

Rodar: cd backend && venv/bin/python test_agendamento_recusas.py

Nenhuma conexão: a Exact é mockada, o banco é dublê em memória e as rotas rodam num app
mínimo via ASGITransport (sem nginx, sem lifespan). Nada é criado na agenda real.

   1. origem_nao_permitida no /lead: 400, linha `recusado` com a origem COMO VEIO, log
   2. origem_nao_permitida no /agendar: idem, com slot e leadId no detalhe
   3. validacao_telefone (422): resposta idêntica à padrão; telefone e nome crus e cortados
   4. validacao_<campo> e validacao_corpo: o motivo sai do primeiro campo com erro
   5. duplo_clique: 200 com o agendamento anterior, e uma linha `recusado` de rastro
   6. slot_invalido: 400 e linha `recusado`
   7. slot_ocupado: 409, motivo marcado na linha `falhou` que já existia — sem duplicar
   8. lead_nao_encontrado: 404 e linha `recusado` SEM lead_id (o leadId vai no detalhe)
   9. rate_limit: 429 só no log, nenhuma linha
  10. falha ao gravar o rastro não muda a resposta (400 e 422 continuam iguais)
  11. teto do rastro do 422 por IP: o 6º continua 422 e no log, mas não grava
  12. 422 fora das rotas da LP: handler padrão, nenhuma linha, nenhum log de recusa
  13. regressão: /lead e /agendar de sucesso não gravam `recusado` nem logam recusa
  14. carga das consultoras exclui `recusado` (linha com slot_inicio = agora)
"""
import asyncio
import io
import json
import os
from contextlib import redirect_stdout
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

from app.agendamento import agendar as fluxo
from app.agendamento import client, consultoras as equipe_mod, rastro, routes
from app.agendamento.grade import recarregar
from app.database import get_db
from app.models import (PASSO_AGENDADO, PASSO_FALHOU, PASSO_LEAD_CRIADO, PASSO_RECUSADO,
                        Agendamento)

# Hermética ao .env do servidor — mesma razão do cabeçalho de test_agendamento.py.
for _v in ("AGENDAMENTO_CONSULTORAS", "AGENDAMENTO_CONSULTORAS_PATH",
           "AGENDAMENTO_GRADE_JSON", "AGENDAMENTO_GRADE_PATH",
           "AGENDAMENTO_FUNIL_DESTINO", "AGENDAMENTO_SUBSOURCES",
           "AGENDAMENTO_SUBSOURCE_PADRAO", "AGENDAMENTO_JANELA_DIAS",
           "AGENDAMENTO_ORIGEM_ALIASES"):
    os.environ.pop(_v, None)
os.environ["AGENDAMENTO_JANELA_DIAS"] = "7"
os.environ["AGENDAMENTO_SUBSOURCES"] = "PosMulheridades,Pos Grupos e Oficinas T2"
os.environ["AGENDAMENTO_SUBSOURCE_PADRAO"] = "PosMulheridades"

TELEFONE = "66999050115"
ORIGEM_OK = "Pos Grupos e Oficinas T2"
ORIGEM_RUIM = "Pos DH T4"

_ip_seq = 0


def _novo_ip() -> str:
    """Um IP por requisição de teste: o rate limit é em memória e duraria a suíte inteira."""
    global _ip_seq
    _ip_seq += 1
    return f"203.0.113.{_ip_seq}"


def checa(rotulo, obtido, esperado):
    assert obtido == esperado, f"{rotulo}: esperado {esperado!r}, obtido {obtido!r}"


class _DbFalso:
    """Dublê de AsyncSession. `falhar_commit` simula o banco recusando a escrita."""

    def __init__(self, *, duplo=None, falhar_commit=False):
        self.adicionados = []
        self.commits = 0
        self.rollbacks = 0
        self.statements = []
        self._duplo = duplo
        self._falhar_commit = falhar_commit
        self._proximo_id = 1

    async def execute(self, stmt, *a, **k):
        self.statements.append(stmt)
        res = MagicMock()
        res.scalar_one_or_none.return_value = self._duplo
        res.all.return_value = []
        res.scalars.return_value.all.return_value = []
        return res

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self._proximo_id
            self._proximo_id += 1
        self.adicionados.append(obj)

    async def commit(self):
        if self._falhar_commit:
            raise RuntimeError("banco fora")
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def flush(self):
        pass

    def agendamentos(self):
        return [o for o in self.adicionados if isinstance(o, Agendamento)]

    def recusados(self):
        return [o for o in self.agendamentos() if o.passo == PASSO_RECUSADO]


def _app(db: _DbFalso) -> FastAPI:
    """O router real + o handler de 422 real, com o banco trocado pelo dublê."""
    app = FastAPI()
    app.include_router(routes.router)
    app.add_exception_handler(RequestValidationError, routes.validacao_recusada)

    class _Outro(BaseModel):
        x: int

    @app.post("/api/outra")
    async def outra(corpo: _Outro):
        return {"ok": True}

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    return app


async def _post(db: _DbFalso, caminho: str, corpo, *, ip: str | None = None,
                cru: bool = False):
    """POST e devolve (resposta, log). `cru=True` manda o texto como veio (JSON inválido)."""
    saida = io.StringIO()
    transporte = httpx.ASGITransport(app=_app(db))
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as c:
        cab = {"x-forwarded-for": ip or _novo_ip()}
        with redirect_stdout(saida):
            if cru:
                cab["content-type"] = "application/json"
                r = await c.post(caminho, content=corpo, headers=cab)
            else:
                r = await c.post(caminho, json=corpo, headers=cab)
    return r, saida.getvalue()


def _linhas_de_recusa(log: str) -> list[str]:
    return [l for l in log.splitlines() if rastro.PREFIXO_LOG in l]


def _slot_valido():
    g = recarregar()
    equipe_mod.recarregar()
    return g.slots_candidatos()[0]


def _corpo(**extra):
    base = {"nome": "José Roberto Lopes", "email": "jose@example.com",
            "telefone": TELEFONE, "origem": ORIGEM_OK}
    base.update(extra)
    return base


# ==========================================================================================

async def caso_1_origem_no_lead():
    db = _DbFalso()
    criar = AsyncMock(return_value=1)
    with patch.object(client, "criar_lead", criar):
        r, log = await _post(db, "/api/agendamento/lead", _corpo(origem=ORIGEM_RUIM))

    checa("status", r.status_code, 400)
    checa("resposta inalterada", r.json(), {"detail": "Origem inválida."})
    checa("LeadsAdd nunca chamado", criar.called, False)
    [ag] = db.recusados()
    checa("motivo", ag.motivo_recusa, rastro.ORIGEM_NAO_PERMITIDA)
    checa("origem COMO VEIO", ag.sub_source, ORIGEM_RUIM)
    checa("telefone", ag.telefone, TELEFONE)
    checa("nome", ag.nome, "José Roberto Lopes")
    checa("sem lead", ag.lead_id, None)
    checa("sem box", ag.box_id, None)
    checa("sem consultora", ag.sales_rep_email, "")
    checa("rota no erro", ag.erro.startswith("/lead · "), True)
    [linha] = _linhas_de_recusa(log)
    for trecho in ("rota=/lead", "motivo=origem_nao_permitida", f"tel='{TELEFONE}'",
                   f"origem='{ORIGEM_RUIM}'"):
        checa(f"log tem {trecho}", trecho in linha, True)
    print("  1. origem no /lead: 400, linha recusado com a origem como veio, log com telefone")


async def caso_2_origem_no_agendar():
    db = _DbFalso()
    slot = _slot_valido()
    with patch.object(client, "criar_box", AsyncMock()) as box:
        r, log = await _post(db, "/api/agendamento/agendar",
                             _corpo(origem=ORIGEM_RUIM, slot=slot.id, leadId=51441824))

    checa("status", r.status_code, 400)
    checa("BoxesAdd nunca chamado", box.called, False)
    [ag] = db.recusados()
    checa("motivo", ag.motivo_recusa, rastro.ORIGEM_NAO_PERMITIDA)
    checa("leadId NÃO vira lead_id", ag.lead_id, None)
    checa("leadId no detalhe", "leadId=51441824" in ag.erro, True)
    checa("slot no detalhe", slot.id in ag.erro, True)
    checa("uma linha só no journal", len(_linhas_de_recusa(log)), 1)
    print("  2. origem no /agendar: 400, linha sem lead_id, slot e leadId no detalhe")


async def caso_3_validacao_telefone():
    db = _DbFalso()
    comprido = "+55 (66) 9 9905-0115 ramal 1234 casa"      # 36 chars
    nome_longo = "J" * 150
    r, log = await _post(db, "/api/agendamento/lead",
                         _corpo(telefone=comprido, nome=nome_longo))

    checa("status", r.status_code, 422)
    # A resposta é a do handler padrão do FastAPI, com `loc` começando em "body".
    corpo = r.json()
    checa("formato padrão", isinstance(corpo.get("detail"), list), True)
    checa("loc padrão", corpo["detail"][0]["loc"], ["body", "telefone"])
    [ag] = db.recusados()
    checa("motivo", ag.motivo_recusa, "validacao_telefone")
    checa("telefone cru cortado a 30", ag.telefone, comprido[:30])
    checa("nome cortado a 120", ag.nome, nome_longo[:120])
    checa("origem", ag.sub_source, ORIGEM_OK)
    [linha] = _linhas_de_recusa(log)
    checa("log com motivo", "motivo=validacao_telefone" in linha, True)
    checa("log com o telefone COMPLETO", repr(comprido[:30]) in linha, True)
    print("  3. 422 de telefone: resposta padrão, telefone e nome crus e cortados, log")


async def caso_4_motivo_por_campo():
    casos = [
        (_corpo(nome=" "), "validacao_nome"),
        (_corpo(extras={f"k{i}": "v" for i in range(11)}), "validacao_extras"),
        ({"nome": "Fulana", "origem": ORIGEM_OK}, "validacao_telefone"),   # ausente
    ]
    for corpo, esperado in casos:
        db = _DbFalso()
        r, _ = await _post(db, "/api/agendamento/lead", corpo)
        checa(f"{esperado}: status", r.status_code, 422)
        checa(f"{esperado}: motivo", db.recusados()[0].motivo_recusa, esperado)

    db = _DbFalso()
    slot = _slot_valido()
    r, _ = await _post(db, "/api/agendamento/agendar", _corpo(slot=slot.id, leadId=0))
    checa("leadId=0: status", r.status_code, 422)
    checa("leadId=0: motivo", db.recusados()[0].motivo_recusa, "validacao_leadid")
    checa("leadId=0: sem lead_id", db.recusados()[0].lead_id, None)

    db = _DbFalso()
    r, log = await _post(db, "/api/agendamento/lead", b'{"nome": "Ful', cru=True)
    checa("JSON quebrado: status", r.status_code, 422)
    [ag] = db.recusados()
    checa("JSON quebrado: motivo", ag.motivo_recusa, rastro.VALIDACAO_CORPO)
    checa("JSON quebrado: telefone vazio, não NULL", ag.telefone, "")
    checa("JSON quebrado: log", len(_linhas_de_recusa(log)), 1)
    print("  4. validacao_<campo> sai do primeiro campo; JSON quebrado é validacao_corpo")


async def caso_5_duplo_clique():
    anterior = Agendamento(nome="José", telefone=TELEFONE, slot_inicio=datetime(2026, 9, 29),
                           slot_fim=datetime(2026, 9, 29), sales_rep_email="x@y.com",
                           passo=PASSO_AGENDADO, lead_id=888, box_id=777, meeting_id=999,
                           created_at=datetime.now(), updated_at=datetime.now())
    anterior.id = 42
    db = _DbFalso(duplo=anterior)
    slot = _slot_valido()
    with patch.object(client, "criar_box", AsyncMock()) as box:
        r, log = await _post(db, "/api/agendamento/agendar", _corpo(slot=slot.id))

    checa("status", r.status_code, 200)
    checa("devolve o anterior", (r.json()["agendamento_id"], r.json()["lead_id"]), (42, 888))
    checa("nada na Exact", box.called, False)
    [ag] = db.recusados()
    checa("motivo", ag.motivo_recusa, rastro.DUPLO_CLIQUE)
    checa("sem lead_id", ag.lead_id, None)
    checa("aponta o anterior", "devolveu #42 (lead 888)" in ag.erro, True)
    checa("log", len(_linhas_de_recusa(log)), 1)
    print("  5. duplo clique: 200 com #42, e uma linha recusado apontando para ele")


async def caso_6_slot_invalido():
    db = _DbFalso()
    r, _ = await _post(db, "/api/agendamento/agendar",
                       _corpo(slot="2026-01-04T03:00:00"))     # domingo, 03:00
    checa("status", r.status_code, 400)
    [ag] = db.recusados()
    checa("motivo", ag.motivo_recusa, rastro.SLOT_INVALIDO)
    checa("slot pedido no detalhe", "2026-01-04T03:00:00" in ag.erro, True)
    checa("slot_inicio NÃO é o slot pedido", ag.slot_inicio != datetime(2026, 1, 4, 3), True)
    checa("slot_inicio = slot_fim (linha sem slot)", ag.slot_inicio, ag.slot_fim)
    print("  6. slot inválido: 400, linha recusado, slot pedido só no detalhe")


async def caso_7_slot_ocupado():
    db = _DbFalso()
    slot = _slot_valido()
    with patch.object(client, "criar_box",
                      AsyncMock(side_effect=client.SlotOcupado("Boxes are occupied"))), \
         patch("app.agendamento.agendar.rd_outbox.enfileirar", AsyncMock()):
        r, log = await _post(db, "/api/agendamento/agendar", _corpo(slot=slot.id))

    checa("status", r.status_code, 409)
    checa("nenhuma linha recusado", db.recusados(), [])
    [ag] = db.agendamentos()
    checa("a linha que já existia", ag.passo, PASSO_FALHOU)
    checa("ganhou o motivo", ag.motivo_recusa, rastro.SLOT_OCUPADO)
    checa("log", len(_linhas_de_recusa(log)), 1)
    print("  7. slot ocupado: 409, motivo na linha falhou que já existia, sem duplicar")


async def caso_8_lead_nao_encontrado():
    db = _DbFalso()
    slot = _slot_valido()
    with patch.object(client, "buscar_lead_por_id", AsyncMock(return_value=None)), \
         patch.object(client, "criar_box", AsyncMock()) as box:
        r, _ = await _post(db, "/api/agendamento/agendar",
                           _corpo(slot=slot.id, leadId=12345))
    checa("status", r.status_code, 404)
    checa("nada na Exact", box.called, False)
    [ag] = db.recusados()
    checa("motivo", ag.motivo_recusa, rastro.LEAD_NAO_ENCONTRADO)
    checa("SEM lead_id — é um id que não existe", ag.lead_id, None)
    checa("leadId no detalhe", "leadId=12345" in ag.erro, True)
    print("  8. lead não encontrado: 404, linha recusado sem lead_id, leadId no detalhe")


async def caso_9_rate_limit():
    routes._baldes.clear()
    ip = _novo_ip()
    with patch.object(client, "criar_lead", AsyncMock(return_value=1)), \
         patch.object(fluxo, "_gatilho_do_agente", AsyncMock()), \
         patch("app.agendamento.agendar.rd_outbox.enfileirar", AsyncMock()):
        for _ in range(routes.LIMITE_ESCRITA[0]):
            await _post(_DbFalso(), "/api/agendamento/lead", _corpo(), ip=ip)
        db = _DbFalso()
        r, log = await _post(db, "/api/agendamento/lead", _corpo(), ip=ip)
    checa("status", r.status_code, 429)
    checa("nenhuma linha", db.agendamentos(), [])
    [linha] = _linhas_de_recusa(log)
    checa("log com motivo", "motivo=rate_limit" in linha, True)
    routes._baldes.clear()
    print("  9. rate limit: 429 no log com telefone, nenhuma linha gravada")


async def caso_10_falha_do_rastro_nao_muda_resposta():
    db = _DbFalso(falhar_commit=True)
    r, log = await _post(db, "/api/agendamento/lead", _corpo(origem=ORIGEM_RUIM))
    checa("400 igual", (r.status_code, r.json()), (400, {"detail": "Origem inválida."}))
    checa("rollback", db.rollbacks, 1)
    checa("aviso no journal", "rastro da recusa NÃO gravado" in log, True)
    checa("linha de recusa continua no journal", len(_linhas_de_recusa(log)), 1)

    db = _DbFalso(falhar_commit=True)
    r, _ = await _post(db, "/api/agendamento/lead", _corpo(telefone="123"))
    checa("422 igual", r.status_code, 422)
    checa("formato padrão", r.json()["detail"][0]["loc"], ["body", "telefone"])
    print("  10. banco recusando o rastro: 400 e 422 idênticos, aviso no journal")


async def caso_11_teto_do_422():
    routes._baldes.clear()
    ip = _novo_ip()
    gravadas = 0
    for _ in range(routes.LIMITE_RASTRO_422[0]):
        db = _DbFalso()
        await _post(db, "/api/agendamento/lead", _corpo(telefone="123"), ip=ip)
        gravadas += len(db.recusados())
    checa("dentro do teto grava", gravadas, routes.LIMITE_RASTRO_422[0])

    db = _DbFalso()
    r, log = await _post(db, "/api/agendamento/lead", _corpo(telefone="123"), ip=ip)
    checa("continua 422", r.status_code, 422)
    checa("não grava", db.recusados(), [])
    checa("mas loga", len(_linhas_de_recusa(log)), 1)
    routes._baldes.clear()
    print("  11. teto do 422 por IP: o 6º continua 422 e no journal, sem INSERT")


async def caso_12_422_fora_da_lp():
    db = _DbFalso()
    r, log = await _post(db, "/api/outra", {"x": "não é número"})
    checa("status", r.status_code, 422)
    checa("formato padrão", r.json()["detail"][0]["loc"], ["body", "x"])
    checa("nenhuma linha", db.agendamentos(), [])
    checa("nenhum log de recusa", _linhas_de_recusa(log), [])
    print("  12. 422 de outra rota: handler padrão, nada gravado, nada logado")


async def caso_13_sucesso_intacto():
    db = _DbFalso()
    with patch.object(client, "criar_lead", AsyncMock(return_value=888)), \
         patch.object(fluxo, "_gatilho_do_agente", AsyncMock()), \
         patch("app.agendamento.agendar.rd_outbox.enfileirar", AsyncMock()):
        r, log = await _post(db, "/api/agendamento/lead", _corpo())
    checa("/lead 200", r.status_code, 200)
    checa("/lead corpo", r.json()["lead_id"], 888)
    [ag] = db.agendamentos()
    checa("/lead passo", ag.passo, PASSO_LEAD_CRIADO)
    checa("/lead sem motivo", ag.motivo_recusa, None)
    checa("/lead sem log de recusa", _linhas_de_recusa(log), [])

    db = _DbFalso()
    slot = _slot_valido()
    with patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", AsyncMock(return_value=888)), \
         patch.object(client, "agendar_reuniao", AsyncMock(return_value=True)), \
         patch.object(client, "meeting_por_lead", AsyncMock(return_value=None)), \
         patch.object(fluxo, "_gatilho_do_agente", AsyncMock()), \
         patch("app.agendamento.agendar.rd_outbox.enfileirar", AsyncMock()):
        r, log = await _post(db, "/api/agendamento/agendar", _corpo(slot=slot.id))
    checa("/agendar 200", r.status_code, 200)
    [ag] = db.agendamentos()
    checa("/agendar passo", ag.passo, PASSO_AGENDADO)
    checa("/agendar sem motivo", ag.motivo_recusa, None)
    checa("/agendar sem log de recusa", _linhas_de_recusa(log), [])
    print("  13. sucesso: /lead e /agendar sem linha recusado, sem motivo, sem log de recusa")


async def caso_14_carga_exclui_recusado():
    os.environ["AGENDAMENTO_CONSULTORAS"] = json.dumps([
        {"email": "a@cenat.com", "nome_exibicao": "A"},
        {"email": "b@cenat.com", "nome_exibicao": "B"}])
    try:
        equipe_mod.recarregar()
        db = _DbFalso()
        await fluxo.escolher_consultora(db, equipe_mod.consultoras(), datetime.now().date())
        # Pelos parâmetros, e não por `literal_binds`: o dialeto genérico não sabe renderizar
        # datetime como literal, e o teste quebraria por um motivo que não é o que ele testa.
        params = db.statements[-1].compile().params.values()
        excluidos = [v for v in params if isinstance(v, (list, tuple))]
        checa("NOT IN presente", len(excluidos), 1)
        checa("recusado fora da carga", PASSO_RECUSADO in excluidos[0], True)
    finally:
        os.environ.pop("AGENDAMENTO_CONSULTORAS", None)
        equipe_mod.recarregar()
    print("  14. carga das consultoras exclui recusado")


async def main():
    print("\nRastro das recusas — Exact mockada, banco dublê, nada real\n")
    await caso_1_origem_no_lead()
    await caso_2_origem_no_agendar()
    await caso_3_validacao_telefone()
    await caso_4_motivo_por_campo()
    await caso_5_duplo_clique()
    await caso_6_slot_invalido()
    await caso_7_slot_ocupado()
    await caso_8_lead_nao_encontrado()
    await caso_9_rate_limit()
    await caso_10_falha_do_rastro_nao_muda_resposta()
    await caso_11_teto_do_422()
    await caso_12_422_fora_da_lp()
    await caso_13_sucesso_intacto()
    await caso_14_carga_exclui_recusado()
    print("\nOK: 14/14 passaram. Nenhum box criado, nenhum lead cadastrado.\n")


if __name__ == "__main__":
    asyncio.run(main())
