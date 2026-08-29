"""S5-1 — a reunião que o AGENTE marca entra na Exact com o curso do lead.

    cd backend && venv/bin/python test_agendamento_origem_agente.py

NADA sai daqui: `agendamento.agendar` é mockado, o banco é falso, o LLM nunca é chamado.
Nenhuma linha gravada, nenhum WhatsApp, nenhuma chamada à Exact.

O QUE ESTE TESTE PROVA
  1. o sub_source do lead é lido nas mesmas duas fontes que a abertura já usa
  2. o valor volta na CAIXA DA ALLOWLIST, não na do banco
  3. sub_source fora da allowlist -> origem padrão + LOG (a reunião NÃO morre)
  4. sub_source ausente          -> origem padrão + LOG
  5. `_agendar` repassa `origem` E `extras` a `agendamento.agendar` — o defeito era
     `origem=None, extras=None` fixos, e 4 de 4 reuniões saíram `PosMulheridades`
"""
import asyncio
import io
import os
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["AGENDAMENTO_SUBSOURCES"] = "PosMulheridades,Pos TEA V3,posgenerot2"
os.environ["AGENDAMENTO_SUBSOURCE_PADRAO"] = "PosMulheridades"

from app import qualificacao_fluxo as fluxo
from app.models import ETAPA_Q_ESCOLHENDO_SLOT, NatQualificacaoState, ORIGEM_LP

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def _estado(lead_id=51610927):
    e = NatQualificacaoState(contact_wa_id="5521951019121", exact_lead_id=lead_id,
                             origem=ORIGEM_LP, etapa=ETAPA_Q_ESCOLHENDO_SLOT)
    e.agendamento_id = None
    return e


def _db(*retornos):
    """Um db falso cujo `execute` devolve `retornos` em ordem (scalar_one_or_none)."""
    fila = list(retornos)

    async def execute(*a, **kw):
        valor = fila.pop(0) if fila else None
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=valor)
        return r

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


def _origem(*retornos):
    """(origem devolvida, stdout) — o stdout é onde a divergência tem de aparecer."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = asyncio.run(fluxo._origem_do_agendamento(_estado(), _db(*retornos)))
    return r, buf.getvalue()


# ==========================================================================================
print("\n1) O sub_source cru — as duas fontes de `_curso`, sem resolver nome de curso")

sub = asyncio.run(fluxo._sub_source_do_lead(_estado(), _db("Pos TEA V3")))
checa("1ª fonte: exact_leads.sub_source", sub, "Pos TEA V3")

sub = asyncio.run(fluxo._sub_source_do_lead(_estado(), _db(None, "Pos TEA V3")))
checa("2ª fonte: agendamentos.sub_source quando exact_leads não tem", sub, "Pos TEA V3")

sub = asyncio.run(fluxo._sub_source_do_lead(_estado(), _db(None, None)))
checa("nenhuma das duas -> string vazia (nunca None)", sub, "")

e = _estado(lead_id=None)
sub = asyncio.run(fluxo._sub_source_do_lead(e, _db("Pos TEA V3")))
checa("sem exact_lead_id não consulta nada", sub, "")


# ==========================================================================================
print("\n2) A allowlist — o caso da Kaylla, que virou PosMulheridades em produção")

r, log = _origem("Pos TEA V3")
checa("sub_source na allowlist -> ele mesmo", r, "Pos TEA V3")
checa("  e nada de aviso no log", "⚠️" in log, False)

r, log = _origem("pos tea v3")
checa("caixa diferente casa (case-insensitive)", r, "Pos TEA V3")
checa("  e volta na CAIXA DA ALLOWLIST, não na do banco", r == "pos tea v3", False)

r, log = _origem("  Pos TEA V3  ")
checa("espaço em volta não atrapalha", r, "Pos TEA V3")


# ==========================================================================================
print("\n3) Fora da allowlist — padrão + LOG, e a reunião NÃO morre")

r, log = _origem("PosBoasPraticasEAD")
checa("sub_source fora da allowlist -> None (= origem padrão)", r, None)
checa("  e o valor recusado aparece no log", "PosBoasPraticasEAD" in log, True)
checa("  e o log diz qual padrão vai no lugar", "PosMulheridades" in log, True)
checa("  e é aviso, não exceção", "⚠️" in log, True)

r, log = _origem(None, None)
checa("sem sub_source nenhum -> None (= origem padrão)", r, None)
checa("  com log dizendo que o lead não tem origem", "sem sub_source" in log, True)


# ==========================================================================================
print("\n4) `_agendar` repassa origem E extras — o defeito, no ponto exato")

FORM = {"Profissão": "Psicologia", "Faixa de investimento": "De R$100,00 a R$200,00"}


def roda_agendar(*, sub_source, extras):
    """Executa `_agendar` com tudo mockado. Devolve os kwargs vistos por `agendar`."""
    estado = _estado()
    resposta = {"mensagem": "Marcado!", "etapa_cumprida": True,
                "dado_extraido": {"slot_id": "s1"}, "acao": "agendar_slot"}
    ofertados = {"s1": "2026-08-28 13:30 (id: s1)"}

    slot = MagicMock()
    slot.id = "s1"
    resultado = MagicMock()
    resultado.agendamento_id = 251

    sessao = MagicMock()
    sessao.__aenter__ = AsyncMock(return_value=MagicMock())
    sessao.__aexit__ = AsyncMock(return_value=False)

    agendar_mock = AsyncMock(return_value=resultado)

    with patch("app.agendamento.disponibilidade.slots_livres",
               new=AsyncMock(return_value=[slot])), \
         patch("app.agendamento.agendar.agendar", new=agendar_mock), \
         patch("app.database.async_session", new=MagicMock(return_value=sessao)), \
         patch.object(fluxo, "_contato_de", new=AsyncMock(return_value=None)), \
         patch.object(fluxo, "_sub_source_do_lead",
                      new=AsyncMock(return_value=sub_source)), \
         patch("app.qualificacao_dados.extras_brutos_da_lp",
               new=AsyncMock(return_value=extras)), \
         patch.object(fluxo, "_reuniao", new=AsyncMock(return_value=None)), \
         patch.object(fluxo, "_falar", new=AsyncMock(return_value=True)), \
         patch.object(fluxo, "_concluir", new=AsyncMock()), \
         patch.object(fluxo, "_fallback", new=AsyncMock()) as caiu:
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(fluxo._agendar(estado, resposta, ofertados, _db()))
    return agendar_mock, caiu, buf.getvalue()


chamada, caiu, log = roda_agendar(sub_source="Pos TEA V3", extras=FORM)
checa("agendou (não caiu no fallback)", caiu.await_count, 0)
checa("`agendar` foi chamado uma vez", chamada.await_count, 1)
kw = chamada.await_args.kwargs
checa("origem = o sub_source REAL do lead (era None)", kw["origem"], "Pos TEA V3")
checa("extras = o formulário da LP (era None)", kw["extras"], FORM)
checa("lead_id continua indo (nada regrediu)", kw["lead_id"], 51610927)
checa("slot_id continua indo", kw["slot_id"], "s1")

chamada, caiu, log = roda_agendar(sub_source="CursoQueNinguemCadastrou", extras={})
kw = chamada.await_args.kwargs
checa("fora da allowlist: origem=None (padrão) e a reunião SAI", kw["origem"], None)
checa("  a chamada aconteceu mesmo assim", chamada.await_count, 1)
checa("  e o log nomeia o valor recusado", "CursoQueNinguemCadastrou" in log, True)
checa("formulário vazio -> extras=None (grava NULL, como sempre)", kw["extras"], None)


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} teste(s) falharam:")
    for f in falhas:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado, nenhuma chamada à Exact.")
