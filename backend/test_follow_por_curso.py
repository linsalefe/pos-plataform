"""Follow 3 e Follow 4 com template por pós, o genérico como fallback (sprint de 28/09).

    cd backend && venv/bin/python test_follow_por_curso.py

NADA sai daqui: banco é dublê, `bulk_send_template` e a nota da Exact são mockados, nenhuma
chamada de rede.

O QUE ESTE TESTE PROVA
  1. o JSON de produção: `por_curso` só no 3 e no 4, e os nomes conferidos na Meta em 28/09
  2. `resolver`: variante encontrada; sub_source fora do mapa -> genérico; caixa e espaço nas
     pontas não importam; sub_source nulo/vazio -> genérico
  3. `montar_mappings`: a variante leva só `nome`; o genérico mantém `nome`+`curso`
  4. os outros sete degraus não mudam, qualquer que seja o sub_source
  5. o carregamento recusa `por_curso` torto
  6. `_enfileirar` e `_enviar_uma` gravam e enviam o template EFETIVO, e a nota o cita
"""
import asyncio
import io
import json
import os
import tempfile
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

from app import follow_estagio as fe
from app import follow_estagio_mapa as fem
from app.follow_estagio_mapa import MapaInvalido, estagio_para, montar_mappings, resolver
from app.models import FE_ENVIADO, FE_PENDENTE

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def mudo(fn, *a, **kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = asyncio.run(fn(*a, **kw)) if asyncio.iscoroutinefunction(fn) else fn(*a, **kw)
    return r, buf.getvalue()


class Lead:
    def __init__(self, **kw):
        self.id = kw.get("id", 9127)
        self.exact_id = kw.get("exact_id", 51438018)
        self.name = kw.get("name", "marina leite")
        self.phone1 = kw.get("phone1", "5583988046720")
        self.sdr_name = kw.get("sdr_name", "Victória")
        self.sub_source = kw.get("sub_source", "Pos TEA V3")


# Conferido ao vivo no WABA 1360246076143727 em 28/09: APPROVED, pt_BR, um `{{1}}`, botão URL
# estático. `f4_audiosmenfermagem` NÃO está: é `pt_PT` e o envio usa `pt_BR` (CONTRADIZ no
# relatório), então Enfermagem cai no genérico no Follow 4.
F3 = {
    "Pos Enfermagem em Saude Mental": "f3_guiaenfermagemsm",
    "Pos Infantojuvenil EAD":         "f3_siteinfantoead",
    "Pos Psicologia Escolar":         "f3_guiaescolar",
    "Pos Psicologia na RAPS T3":      "f3_guiarapst3",
    "PosMulheridades":                "f3_guiamulheridades",
    "Pos Grupos e Oficinas T2":       "f3_guiagrupot2",
    "Pos TEA V3":                     "f3_guiatea",
    "Pos Gestao Psicossocial T5":     "f3_guiagestaot5",
    "Pos Suicidio e Luto T3":         "f3_guiasuicidiot3",
    "Pos Saude do Trabalhador":       "f3_guiatrabalhot3",
}
F4 = {
    "Pos Infantojuvenil EAD":         "f4_audioinfantoead",
    "Pos Psicologia Escolar":         "f4_audiopsiescolar",
    "Pos Psicologia na RAPS T3":      "f4_audioraps",
    "PosMulheridades":                "f4_audiomulheridades",
    "Pos Grupos e Oficinas T2":       "f4_audiogrupot2",
    "Pos TEA V3":                     "f4_audiotea",
    "Pos Gestao Psicossocial T5":     "f4_audiogestaot5",
    "Pos Suicidio e Luto T3":         "f4_audiosuicidiot3",
    "Pos Saude do Trabalhador":       "f4_audiosmtrabalho",
}
OUTROS_SETE = (129985, 129984, 129967, 174517, 174516, 174515, 174514)


# ==========================================================================================
print("\n1) O JSON de produção")

m = fem.recarregar()
e3, e4 = m["estagios"][129983], m["estagios"][129955]
checa("Follow 3: genérico continua mensagem_follow3", e3["template"], "mensagem_follow3")
checa("Follow 3: params do genérico continuam nome+curso", e3["params"], ["nome", "curso"])
checa("Follow 3: as dez variantes",
      e3["por_curso"], {k.lower(): v for k, v in F3.items()})
checa("Follow 3: variantes só com `nome`", e3["params_por_curso"], ["nome"])
checa("Follow 4: genérico continua mensagem_follow4", e4["template"], "mensagem_follow4")
checa("Follow 4: as nove variantes (sem Enfermagem)",
      e4["por_curso"], {k.lower(): v for k, v in F4.items()})
checa("Follow 4: variantes só com `nome`", e4["params_por_curso"], ["nome"])
checa("f4_audiosmenfermagem (pt_PT) NÃO está no mapa",
      "f4_audiosmenfermagem" in e4["por_curso"].values(), False)
for eid in OUTROS_SETE:
    checa(f"estágio {eid} não tem por_curso", m["estagios"][eid]["por_curso"], {})


# ==========================================================================================
print("\n2) resolver: variante, fallback, caixa, nulo")

checa("variante encontrada (F3, TEA)", resolver(e3, "Pos TEA V3"), ("f3_guiatea", ["nome"]))
checa("variante encontrada (F4, Trabalhador)",
      resolver(e4, "Pos Saude do Trabalhador"), ("f4_audiosmtrabalho", ["nome"]))
checa("sub_source fora do mapa -> genérico (F3)",
      resolver(e3, "Pos Psicologia Clinica T2"), ("mensagem_follow3", ["nome", "curso"]))
checa("sub_source fora do mapa -> genérico (F4)",
      resolver(e4, "Pos Alcool e Drogas T4"), ("mensagem_follow4", ["nome"]))
# Grafia legada do MESMO curso não casa: o mapa é por sub_source exato (sem caixa), não por
# curso. 3 leads em Follow 3/4 no dia 28/09 tinham `posinfantoead`.
checa("grafia legada (posinfantoead) -> genérico",
      resolver(e3, "posinfantoead"), ("mensagem_follow3", ["nome", "curso"]))
checa("Enfermagem no F4 -> genérico (variante pt_PT fora do mapa)",
      resolver(e4, "Pos Enfermagem em Saude Mental"), ("mensagem_follow4", ["nome"]))
checa("caixa diferente casa", resolver(e3, "pos tea v3"), ("f3_guiatea", ["nome"]))
checa("CAIXA ALTA casa", resolver(e3, "POSMULHERIDADES"), ("f3_guiamulheridades", ["nome"]))
checa("espaço nas pontas casa", resolver(e4, "  Pos TEA V3 "), ("f4_audiotea", ["nome"]))
checa("sub_source None -> genérico", resolver(e3, None), ("mensagem_follow3", ["nome", "curso"]))
checa("sub_source vazio -> genérico", resolver(e3, "   "), ("mensagem_follow3", ["nome", "curso"]))
checa("sub_source não-string -> genérico", resolver(e4, MagicMock()), ("mensagem_follow4", ["nome"]))
checa("resolver devolve cópia (mutar não estraga o mapa)",
      (resolver(e3, None)[1].append("x"), e3["params"])[1], ["nome", "curso"])


# ==========================================================================================
print("\n3) montar_mappings acompanha o template escolhido")

mp, mot = montar_mappings(e3, Lead(sub_source="Pos TEA V3"))
checa("variante F3: só `nome` (um {{1}})", (mp, mot), ([{"type": "lead_name"}], None))
mp, mot = montar_mappings(e3, Lead(sub_source="Pos Psicologia Clinica T2"))
checa("genérico F3: nome + curso", (mp, mot),
      ([{"type": "lead_name"}, {"type": "lead_course"}], None))
mp, mot = montar_mappings(e3, Lead(sub_source=None))
checa("sub_source nulo F3: nome + curso", len(mp), 2)
mp, mot = montar_mappings(e3, {"sub_source": "pos tea v3", "sdr_name": "X"})
checa("dict (linha do SELECT) também resolve a variante", mp, [{"type": "lead_name"}])


# ==========================================================================================
print("\n4) Os outros sete degraus não mudam")

for eid in OUTROS_SETE:
    e = m["estagios"][eid]
    for ss in ("Pos TEA V3", "PosMulheridades", None, "posinfantoead"):
        checa(f"{e['nome']!r} com {ss!r}", resolver(e, ss), (e["template"], e["params"]))


# ==========================================================================================
print("\n5) O carregamento recusa por_curso torto")


def carrega(estagio: dict):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"funnel_id": 1, "estagios": {"1": estagio}}, fh)
    try:
        fem.carregar(fh.name)
        return "carregou"
    except MapaInvalido as e:
        return f"recusou: {e}"
    finally:
        os.unlink(fh.name)


BASE = {"nome": "F", "template": "t", "params": ["nome", "curso"]}
checa("por_curso sem params_por_curso",
      carrega({**BASE, "por_curso": {"A": "x"}}).startswith("recusou"), True)
checa("params_por_curso sem por_curso",
      carrega({**BASE, "params_por_curso": ["nome"]}).startswith("recusou"), True)
checa("chave repetida só na caixa",
      carrega({**BASE, "por_curso": {"Pos A": "x", "pos a": "y"},
               "params_por_curso": ["nome"]}).startswith("recusou"), True)
checa("template vazio numa variante",
      carrega({**BASE, "por_curso": {"A": " "}, "params_por_curso": ["nome"]}).startswith("recusou"),
      True)
checa("param inválido em params_por_curso",
      carrega({**BASE, "por_curso": {"A": "x"}, "params_por_curso": ["cpf"]}).startswith("recusou"),
      True)
checa("por_curso vazio",
      carrega({**BASE, "por_curso": {}, "params_por_curso": ["nome"]}).startswith("recusou"), True)
checa("bloco válido carrega",
      carrega({**BASE, "por_curso": {"A": "x"}, "params_por_curso": ["nome"]}), "carregou")
fem.recarregar()


# ==========================================================================================
print("\n6) A linha e a nota gravam o template EFETIVO")


def evento(**kw):
    base = {"evento_id": 7001, "lead_exact_id": 51438018, "stage_de": "Follow 2",
            "stage_para": "Follow 3", "funnel_id": 18535, "lead_id": 9127,
            "lead_nome": "Marina", "telefone": "5583988046720", "sdr_name": "Victória",
            "sub_source": "Pos TEA V3"}
    base.update(kw)
    return base


def enfileira(ev):
    cap = {}

    async def execute(stmt, params=None):
        cap["params"] = params
        r = MagicMock()
        r.first = MagicMock(return_value=(4242,))
        return r

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    rotulo, _ = mudo(fe._enfileirar, db, ev, estagio_para(ev), frozenset())
    return rotulo, cap["params"]


rot, p = enfileira(evento())
checa("F3 + TEA: enfileira", rot, FE_PENDENTE)
checa("  e a linha nasce com f3_guiatea", p["template"], "f3_guiatea")
_, p = enfileira(evento(sub_source="Pos Psicologia Clinica T2"))
checa("F3 + pós sem variante: linha com o genérico", p["template"], "mensagem_follow3")
_, p = enfileira(evento(sub_source=None))
checa("F3 + sub_source nulo: linha com o genérico", p["template"], "mensagem_follow3")
_, p = enfileira(evento(stage_para="Follow 4", sub_source="pos saude do trabalhador"))
checa("F4 + Trabalhador em minúsculas: f4_audiosmtrabalho", p["template"], "f4_audiosmtrabalho")
_, p = enfileira(evento(stage_para="Follows 5"))
checa("Follows 5 + TEA: continua o genérico", p["template"], "mensagem_follow5")

OK = {"sent": 1, "failed": 0, "errors": [], "skipped_nat": 0, "skipped_total": 0,
      "skipped_por_regra": {}, "skipped": []}


def envia(estagio_id, estagio_nome, lead):
    updates = []

    async def execute(stmt, params=None):
        if str(stmt).strip().upper().startswith("UPDATE"):
            updates.append(stmt.compile().params)
            return MagicMock()
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=lead)
        return r

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    linha = MagicMock()
    linha.id, linha.lead_exact_id = 4242, 51438018
    linha.estagio_id, linha.estagio_nome = estagio_id, estagio_nome
    bulk = AsyncMock(return_value=OK)
    nota = AsyncMock(return_value=True)
    with patch("app.exact_routes.bulk_send_template", new=bulk), \
         patch("app.exact_notes.registrar_observacao", new=nota):
        status, _ = mudo(fe._enviar_uma, db, linha)
    payload = bulk.await_args.args[0]
    texto_nota = nota.await_args.args[1]
    return status, payload, updates[-1], texto_nota


st, pl, upd, nota = envia(129983, "Follow 3", Lead(sub_source="PosMulheridades"))
checa("F3 + Mulheridades: enviado", st, FE_ENVIADO)
checa("  payload com f3_guiamulheridades", pl["template_name"], "f3_guiamulheridades")
checa("  param_mappings só com nome", pl["param_mappings"], [{"type": "lead_name"}])
checa("  a linha é regravada com o template efetivo", upd.get("template"), "f3_guiamulheridades")
checa("  a nota da Exact cita a variante", "(template f3_guiamulheridades)" in nota, True)

st, pl, upd, nota = envia(129955, "Follow 4", Lead(sub_source="Pos Alcool e Drogas T4"))
checa("F4 + pós sem variante: payload com o genérico", pl["template_name"], "mensagem_follow4")
checa("  a linha grava o genérico", upd.get("template"), "mensagem_follow4")
checa("  a nota cita o genérico", "(template mensagem_follow4)" in nota, True)

st, pl, upd, _ = envia(129983, "Follow 3", Lead(sub_source=None))
checa("F3 + sub_source nulo: genérico com nome+curso",
      (pl["template_name"], len(pl["param_mappings"])), ("mensagem_follow3", 2))

st, pl, upd, _ = envia(174516, " Follows 7", Lead(sub_source="Pos TEA V3"))
checa("Follows 7 + TEA: continua mensagem_follow7", pl["template_name"], "mensagem_follow7")


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado.")
