"""Follow automático por estágio da Exact — o mapa, a idempotência, a allowlist e o opt-out.

    cd backend && venv/bin/python test_follow_estagio.py

NADA sai daqui: banco é dublê, `bulk_send_template` mockado, nenhuma chamada de rede e
nenhuma escrita. O único acesso a banco é OPCIONAL e SOMENTE LEITURA (seção 1b, que confronta
o JSON com `exact_stage_events` e é pulada se o banco não estiver acessível).

O QUE ESTE TESTE PROVA
  1.  o mapa TRAVA contra os nove estágios — grafia byte a byte, com o espaço à esquerda
  1b. (opcional, lê o banco) os nove nomes do JSON são os nove que os eventos realmente têm
  2.  os parâmetros de cada degrau, e que `mes` NUNCA vira curso
  3.  o mapa recusa JSON torto no CARREGAMENTO, não no envio
  4.  outro funil é ignorado — Intercâmbio tem `Follow 1` e 703 entradas em 30 dias
  5.  gate fechado NÃO TOCA NO BANCO
  6.  allowlist casa pela chave tolerante, e evento de fora NÃO cria linha (nem `skipped`)
  7.  reentrada não duplica: `ON CONFLICT DO NOTHING` na UNIQUE (lead, estágio)
  8.  `sem_sdr` e `sem_telefone` viram `skipped` ANTES de qualquer chamada à Meta
  9.  cursor ausente é falha fechada (não zero), e só avança depois de enfileirar
  10. o payload: `param_mappings` (não `mappings`), `lead_ids` = PK LOCAL, `campanha`
  11. o desfecho do bulk vira status, e `falhou` EXIGE motivo
  12. `131050` pula e `131049` não (a regra nova de `higiene_disparo`)

POR QUE TANTA PROVA DE NOME E DE CHAVE
  Os dois defeitos que esta sprint pode ter são silenciosos e caros:
  um nome de estágio escrito sem o espaço à esquerda (o follow do degrau simplesmente nunca
  sai, e ninguém percebe), e `mappings` no lugar de `param_mappings` (a rota cai no modo
  legado, monta `[nome, curso]` por posição, e o lead lê "neste mês de Autolesão, Suicídio e
  Luto"). Nenhum dos dois levanta exceção. Por isso são asserções, não confiança.
"""
import asyncio
import io
import json
import os
import tempfile
from contextlib import redirect_stdout
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app import follow_estagio as fe
from app import follow_estagio_mapa as fem
from app.follow_estagio_mapa import (MESES, MapaInvalido, estagio_para, estagios_do_mapa,
                                     mes_corrente_sp, montar_mappings, primeiro_nome)
from app.models import FE_ENVIADO, FE_FALHOU, FE_PENDENTE, FE_SKIPPED, FE_STATUS

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def mudo(fn, *a, **kw):
    """Roda engolindo o stdout. Devolve `(retorno, log)`."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = asyncio.run(fn(*a, **kw)) if asyncio.iscoroutinefunction(fn) else fn(*a, **kw)
    return r, buf.getvalue()


# Os nove, COPIADOS de `GET /v3/stages` do funil 18535 em 27/09/2026 — não digitados de
# memória. `position` 2 a 10. Reparar no espaço à ESQUERDA do 7 e do 9.
NOVE = (
    (129985, "Follow 1",   "mensagem_flow",     ["nome", "sdr", "curso"]),
    (129984, "Follow 2",   "mensagens_flows2",  ["nome", "curso"]),
    (129983, "Follow 3",   "mensagem_follow3",  ["nome", "curso"]),
    (129955, "Follow 4",   "mensagem_follow4",  ["nome"]),
    (129967, "Follows 5",  "mensagem_follow5",  ["nome", "curso"]),
    (174517, "Follows 6",  "mansagem_follows6", ["nome", "curso"]),
    (174516, " Follows 7", "mensagem_follow7",  ["nome", "mes"]),
    (174515, "Follows 8",  "mensagem_follow8",  ["nome", "curso"]),
    (174514, " Follows 9", "mensagem_follow9",  ["nome"]),
)
FUNIL = 18535
AGORA_SP = datetime(2026, 9, 27, 10, 0, 0)


# ==========================================================================================
print("\n1) O mapa TRAVA contra os nove estágios — grafia byte a byte")

m = fem.recarregar()
checa("funil alvo é o 18535 (pós), e só ele", m["funnel_id"], FUNIL)
checa("nove estágios, nem oito nem dez", len(m["estagios"]), 9)

for eid, nome, template, params in NOVE:
    e = m["estagios"].get(eid)
    checa(f"id {eid} existe no mapa", e is not None, True)
    if e is None:
        continue
    # `==` e não `.strip() ==`: o espaço à esquerda É o nome. Um `strip()` aqui faria o teste
    # passar com o JSON errado, que é a única forma de este teste ser pior que nenhum.
    checa(f"  nome de {eid} é exatamente {nome!r} (len {len(nome)})", e["nome"], nome)
    checa(f"  template de {nome!r}", e["template"], template)
    checa(f"  params de {nome!r}", e["params"], params)

checa("` Follows 7` tem espaço à ESQUERDA", m["estagios"][174516]["nome"][0], " ")
checa("` Follows 9` tem espaço à ESQUERDA", m["estagios"][174514]["nome"][0], " ")
checa("nenhum nome tem espaço à direita",
      [e["nome"] for e in m["estagios"].values() if e["nome"] != e["nome"].rstrip()], [])
# Singular até o 4, plural do 5 em diante. Escrito na ordem da escada porque é assim que a
# armadilha aparece: quem digita a lista de memória escreve "Follow 5".
checa("singular até o 4, plural do 5 em diante",
      [m["estagios"][eid]["nome"].strip().startswith("Follows") for eid, *_ in NOVE],
      [False, False, False, False, True, True, True, True, True])

checa("os nove nomes do mapa, na ordem da escada",
      list(estagios_do_mapa()), [n[1] for n in NOVE])
checa("nenhum nome repetido (a busca em runtime é pelo NOME)",
      len(set(estagios_do_mapa())), 9)
checa("nove templates DISTINTOS", len({n[2] for n in NOVE}), 9)

# Os nomes que a Meta tem de verdade (§3.2 do recon). `mensagem_follow1`, `_follow2` e
# `_follow6` NÃO EXISTEM, e `mansagem_follows6` está escrito errado na própria Meta.
templates = {e["template"] for e in m["estagios"].values()}
for inexistente in ("mensagem_follow1", "mensagem_follow2", "mensagem_follow6"):
    checa(f"{inexistente} NÃO é usado (não existe na Meta)", inexistente in templates, False)
checa("o degrau 6 usa a grafia ERRADA que a Meta tem: 'mansagem_follows6'",
      m["estagios"][174517]["template"], "mansagem_follows6")
checa("o degrau 1 é 'mensagem_flow' (o 'mensagem_follow1' não existe)",
      m["estagios"][129985]["template"], "mensagem_flow")


# ==========================================================================================
print("\n1b) Os nove nomes do JSON são os nove que os eventos REALMENTE têm (lê o banco)")
#
# É o SELECT da Fase 1 da sprint, virado asserção. SOMENTE LEITURA. Se o banco não estiver
# acessível (máquina de desenvolvimento, CI), a seção é PULADA — nunca falha por isso, porque
# o resto do teste não depende de banco e falhar aqui esconderia os outros 11 blocos.


async def _nomes_no_banco():
    from sqlalchemy import text
    from app.database import async_session
    async with async_session() as db:
        return [r[0] for r in (await db.execute(text("""
            SELECT stage_para FROM exact_stage_events
             WHERE funnel_id = :f
               AND observado_em >= now() - interval '30 days'
               AND stage_para ~* 'follow'
             GROUP BY 1 ORDER BY 1"""), {"f": FUNIL})).all()]


try:
    nomes_banco, _ = mudo(_nomes_no_banco)
except Exception as e:
    print(f"  [pulado] banco inacessível ({type(e).__name__}) — o resto do teste não depende")
else:
    checa("o mapa e o banco têm o MESMO conjunto de nomes",
          sorted(nomes_banco), sorted(estagios_do_mapa()))
    # O que mataria a feature em silêncio: um nome no banco que o mapa não conhece.
    checa("nenhum estágio de follow do 18535 ficou fora do mapa",
          sorted(set(nomes_banco) - set(estagios_do_mapa())), [])
    checa("nenhum nome do mapa é fantasma (todos aparecem nos eventos)",
          sorted(set(estagios_do_mapa()) - set(nomes_banco)), [])


# ==========================================================================================
print("\n2) Os parâmetros de cada degrau — e `mes` NUNCA vira curso")


class Lead:
    def __init__(self, **kw):
        self.id = kw.get("id", 9127)
        self.exact_id = kw.get("exact_id", 51438018)
        self.name = kw.get("name", "marina leite Guimaraes serra")
        self.phone1 = kw.get("phone1", "5583988046720")
        self.sdr_name = kw.get("sdr_name", "Victória")
        self.sub_source = kw.get("sub_source", "PosMulheridades")


ESPERADO = {
    "nome": {"type": "lead_name"},
    "curso": {"type": "lead_course"},
    "sdr": {"type": "sdr_name"},
}
for eid, nome, _, params in NOVE:
    mp, motivo = montar_mappings(m["estagios"][eid], Lead(), agora=AGORA_SP)
    esperado = [ESPERADO[p] if p != "mes" else {"type": "fixed_text", "value": "Setembro"}
                for p in params]
    checa(f"{nome!r}: mappings", mp, esperado)
    checa(f"  sem motivo de pulo", motivo, None)

# O ACHADO QUE ESTE MAPA EXISTE PARA NÃO REPETIR: o {{2}} do `mensagem_follow7` é o MÊS.
# Medido em 27/09: 15 dos 40 envios manuais saíram com o nome do CURSO ali.
mp7, _ = montar_mappings(m["estagios"][174516], Lead(), agora=AGORA_SP)
checa("mensagem_follow7: o {{2}} é fixed_text (o MÊS)", mp7[1]["type"], "fixed_text")
checa("  e o valor é um dos doze meses", mp7[1]["value"] in MESES, True)
checa("  e NÃO é lead_course", [x for x in mp7 if x["type"] == "lead_course"], [])
checa("nenhum degrau usa `sdr_logado` (não há humano logado num job)",
      [x for e in m["estagios"].values()
       for x in montar_mappings(e, Lead(), agora=AGORA_SP)[0] or []
       if x["type"] == "sdr_logado"], [])

print()
for mes_num, nome_mes in enumerate(MESES, start=1):
    checa(f"mes_corrente_sp 2026-{mes_num:02d}: {nome_mes}",
          mes_corrente_sp(datetime(2026, mes_num, 15, 12, 0)), nome_mes)
# Naive é assumido JÁ em SP. Um `astimezone` sobre naive (ou um `utcnow`) faria 1º/10 às 00:30
# SP virar "Setembro" — o mês errado na mensagem, nas três primeiras horas de todo dia 1º.
checa("naive 01/10 00:30 é assumido em SP: Outubro",
      mes_corrente_sp(datetime(2026, 10, 1, 0, 30)), "Outubro")
checa("aware 01/10 02:00 UTC = 30/09 23:00 SP: Setembro",
      mes_corrente_sp(datetime(2026, 10, 1, 2, 0, tzinfo=fem.timezone.utc)), "Setembro")
checa("doze meses, em português", len(MESES), 12)
checa("  com o acento de Março", MESES[2], "Março")

# `primeiro_nome` aqui é ESPELHO da regra do bulk, não a melhor regra. Ver a docstring dela:
# um espelho que melhora a regra mente sobre o que o lead vai ler.
checa("primeiro_nome espelha o bulk (split()[0], sem capitalizar)",
      primeiro_nome("marina leite Guimaraes serra"), "marina")
checa("  e nome vazio vira 'Aluno(a)' (nunca em branco: #131008)",
      (primeiro_nome(None), primeiro_nome("")), ("Aluno(a)", "Aluno(a)"))


# ==========================================================================================
print("\n3) O mapa recusa JSON torto no CARREGAMENTO, não no meio de um envio")


def com_json(conteudo):
    """Escreve um JSON temporário e tenta carregá-lo. Devolve a exceção, ou None."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump(conteudo, fh)
        caminho = fh.name
    try:
        fem.carregar(caminho)
        return None
    except Exception as e:
        return e
    finally:
        os.unlink(caminho)


BOM = {"funnel_id": 18535,
       "estagios": {"1": {"nome": "Follow 1", "template": "t", "params": ["nome"]}}}
checa("JSON bom carrega", com_json(BOM), None)

TORTOS = [
    ("sem funnel_id", {"estagios": BOM["estagios"]}),
    ("funnel_id string", {"funnel_id": "18535", "estagios": BOM["estagios"]}),
    ("estagios vazio", {"funnel_id": 18535, "estagios": {}}),
    ("chave não-numérica", {"funnel_id": 18535,
                            "estagios": {"Follow 1": BOM["estagios"]["1"]}}),
    ("nome vazio", {"funnel_id": 18535,
                    "estagios": {"1": {"nome": "  ", "template": "t", "params": ["nome"]}}}),
    ("template vazio", {"funnel_id": 18535,
                        "estagios": {"1": {"nome": "F", "template": "", "params": ["nome"]}}}),
    ("params vazio", {"funnel_id": 18535,
                      "estagios": {"1": {"nome": "F", "template": "t", "params": []}}}),
    # O que mais importa: um parâmetro que a rota não sabe resolver viraria `{{n}}` em branco,
    # e a Meta recusa a mensagem INTEIRA com #131008.
    ("param desconhecido", {"funnel_id": 18535,
                            "estagios": {"1": {"nome": "F", "template": "t",
                                               "params": ["nome", "telefone"]}}}),
    # Dois ids com o MESMO nome: a busca em runtime é pelo nome e ficaria ambígua.
    ("nome duplicado", {"funnel_id": 18535,
                        "estagios": {"1": {"nome": "F", "template": "a", "params": ["nome"]},
                                     "2": {"nome": "F", "template": "b", "params": ["nome"]}}}),
]
for rotulo, conteudo in TORTOS:
    erro = com_json(conteudo)
    checa(f"recusa: {rotulo}", isinstance(erro, MapaInvalido), True)

# Arquivo ausente levanta OSError, e é um dos três que `processar` captura para devolver
# `{"mapa_invalido": True}` sem tocar no banco.
try:
    fem.carregar("/tmp/nao-existe-follow-estagios-20260927.json")
    erro = None
except Exception as e:
    erro = e
checa("arquivo ausente levanta OSError (capturado por `processar`)",
      isinstance(erro, OSError), True)

fem.recarregar()  # volta ao JSON de produção para as seções seguintes


# ==========================================================================================
print("\n4) Outro funil é IGNORADO — Intercâmbio tem `Follow 1` e 703 entradas em 30 dias")

checa("18535 / 'Follow 1' casa",
      (estagio_para({"funnel_id": 18535, "stage_para": "Follow 1"}) or {}).get("template"),
      "mensagem_flow")
for funil, rotulo in ((18285, "Intercâmbio"), (20647, "Reativação - SQL"),
                      (20776, "CONGRESSO"), (18537, "Vendas"), (21007, "Vagas Afirmativas"),
                      (25588, "Funil - Isa"), (None, "funil nulo")):
    checa(f"{funil} ({rotulo}) / 'Follow 1' NÃO casa",
          estagio_para({"funnel_id": funil, "stage_para": "Follow 1"}), None)

# Nomes parecidos que NÃO podem entrar por semelhança.
for destino, porque in (("Follows 7", "sem o espaço à esquerda"),
                        (" Follows 7 ", "espaço a mais à direita"),
                        ("follow 1", "minúsculas"),
                        ("Follow 1 ", "espaço à direita"),
                        ("Follow 2 - Vi", "estágio do funil 20647"),
                        ("Ultimo follow (Descarte) ", "estágio do Intercâmbio"),
                        ("Descartado", "não é follow"),
                        ("Agendados", "não é follow"),
                        ("Entrada", "não é follow"),
                        ("Reagendamento - IA", "não é follow"),
                        (None, "destino nulo"),
                        (123, "destino não-string")):
    checa(f"18535 / {destino!r} NÃO casa ({porque})",
          estagio_para({"funnel_id": 18535, "stage_para": destino}), None)

# `estagio_para` aceita objeto também (é uma Row do SELECT no job).
ev = MagicMock(funnel_id=18535, stage_para=" Follows 9")
checa("aceita objeto com atributos (a Row do SELECT)",
      (estagio_para(ev) or {}).get("template"), "mensagem_follow9")


# ==========================================================================================
print("\n5) Gate fechado NÃO TOCA NO BANCO")

with patch.dict(os.environ, {"FOLLOW_ESTAGIO_ENABLED": "false"}, clear=False):
    sessao = MagicMock(side_effect=AssertionError("abriu sessão com o gate fechado!"))
    with patch.object(fe, "async_session", sessao):
        r, log = mudo(fe.processar)
    checa("processar() devolve {'desligado': True}", r, {"desligado": True})
    checa("  e NÃO abriu sessão nenhuma", sessao.call_count, 0)
    checa("  e diz no log que é por escolha", "DESLIGADO" in log, True)

print()
for valor, esperado in (("true", True), ("TRUE", True), (" true ", True), ("1", True),
                        ("sim", True), ("yes", True), ("false", False), ("", False),
                        ("0", False), ("nao", False), ("tru", False), ("truee", False)):
    with patch.dict(os.environ, {"FOLLOW_ESTAGIO_ENABLED": valor}, clear=False):
        checa(f"gate {valor!r} -> {esperado}", fe._ligado(), esperado)
os.environ.pop("FOLLOW_ESTAGIO_ENABLED", None)
checa("variável AUSENTE = desligado (falha fechada)", fe._ligado(), False)


# ==========================================================================================
print("\n6) A allowlist: chave tolerante, e evento de fora NÃO cria linha")
#
# O número de teste do Álefe está gravado nas DUAS grafias — `5583988046720` em `exact_leads`
# (a Exact guarda o 9º dígito) e `558388046720` nos inbounds (o WhatsApp entrega sem, para DDD
# fora de 11–28). Igualdade crua faria o teste passar ou falhar por acaso, dependendo de qual
# grafia o operador digitasse no `.env`.

CHAVE_ALEFE = "8388046720"
for grafia in ("83988046720", "5583988046720", "558388046720", "8388046720",
               "+55 83 98804-6720", "(83) 98804-6720"):
    with patch.dict(os.environ, {"FOLLOW_ESTAGIO_SOMENTE_TELEFONES": grafia}, clear=False):
        checa(f"{grafia!r} -> chave {CHAVE_ALEFE}", fe.allowlist(), frozenset({CHAVE_ALEFE}))

with patch.dict(os.environ,
                {"FOLLOW_ESTAGIO_SOMENTE_TELEFONES": "83988046720, 5511999999999"},
                clear=False):
    checa("lista com dois telefones", fe.allowlist(),
          frozenset({CHAVE_ALEFE, "1199999999"}))
for cru, rotulo in (("", "vazia"), ("  ", "só espaço"), (",,", "só vírgulas"),
                    ("abc", "lixo")):
    with patch.dict(os.environ, {"FOLLOW_ESTAGIO_SOMENTE_TELEFONES": cru}, clear=False):
        checa(f"allowlist {rotulo} = vazia = TODOS entram", fe.allowlist(), frozenset())
# `''` casa com `''`: uma entrada ilegível na allowlist ligaria o follow para todo lead de
# telefone ilegível — o oposto de uma allowlist.
with patch.dict(os.environ, {"FOLLOW_ESTAGIO_SOMENTE_TELEFONES": "abc,83988046720"},
                clear=False):
    checa("lixo é descartado, a chave boa fica", fe.allowlist(),
          frozenset({CHAVE_ALEFE}))
    checa("  e a chave vazia NUNCA entra", "" in fe.allowlist(), False)
os.environ.pop("FOLLOW_ESTAGIO_SOMENTE_TELEFONES", None)


def evento(**kw):
    """Uma linha do SELECT de `_eventos_novos`, como `.mappings()` a devolve (um dict)."""
    base = {"evento_id": 7001, "lead_exact_id": 51438018, "stage_de": "Agendados",
            "stage_para": "Follow 1", "funnel_id": 18535,
            "observado_em": datetime(2026, 9, 27, 13, 0),
            "lead_id": 9127, "lead_nome": "Álefe Guimel Lins Barbosa",
            "telefone": "5583988046720", "sdr_name": "Thobias",
            "sub_source": "PosMulheridades"}
    base.update(kw)
    return base


def enfileira(ev, permitidos=frozenset(), conflito=False):
    """Roda `_enfileirar` com um banco dublê. Devolve `(rótulo, params_do_insert, log)`."""
    capturado = {}

    async def execute(stmt, params=None):
        capturado["sql"] = str(stmt)
        capturado["params"] = params
        r = MagicMock()
        r.first = MagicMock(return_value=None if conflito else (4242,))
        return r

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    entrada = estagio_para(ev)
    rotulo, log = mudo(fe._enfileirar, db, ev, entrada, permitidos)
    return rotulo, capturado, log, db


rotulo, cap, _, db = enfileira(evento(), permitidos=frozenset({CHAVE_ALEFE}))
checa("lead DA allowlist entra", rotulo, FE_PENDENTE)
checa("  e o INSERT rodou", db.execute.await_count, 1)

rotulo, cap, _, db = enfileira(evento(telefone="5511988887777"),
                               permitidos=frozenset({CHAVE_ALEFE}))
checa("lead FORA da allowlist: rótulo 'fora_da_allowlist'", rotulo, "fora_da_allowlist")
# O PONTO CRÍTICO. A UNIQUE não é parcial: uma linha `skipped` bloquearia aquele par PARA
# SEMPRE, e o dia em que a allowlist saísse do `.env` todo lead que tivesse passado por um
# estágio durante o teste ficaria invisível ao follow real.
checa("  e NÃO tocou no banco (nem para gravar `skipped`)", db.execute.await_count, 0)
checa("  e o rótulo NÃO é 'skipped'", rotulo != FE_SKIPPED, True)

rotulo, _, _, db = enfileira(evento(telefone=None), permitidos=frozenset({CHAVE_ALEFE}))
checa("telefone NULO com allowlist ligada: fora (chave vazia nunca casa)",
      rotulo, "fora_da_allowlist")
checa("  e nada foi gravado", db.execute.await_count, 0)

rotulo, _, _, db = enfileira(evento(telefone="558388046720"),
                             permitidos=frozenset({CHAVE_ALEFE}))
checa("a OUTRA grafia do mesmo humano também entra", rotulo, FE_PENDENTE)

rotulo, _, _, db = enfileira(evento(), permitidos=frozenset())
checa("allowlist vazia: todos entram", rotulo, FE_PENDENTE)

rotulo, _, log, db = enfileira(evento(lead_id=None))
checa("lead que saiu do espelho: evento consumido, nada gravado", rotulo, "lead_ausente")
checa("  e nada foi gravado", db.execute.await_count, 0)
checa("  e o log explica", "não está em exact_leads" in log, True)


# ==========================================================================================
print("\n7) Reentrada NÃO duplica — `ON CONFLICT DO NOTHING` na UNIQUE (lead, estágio)")
#
# §4.3 do recon: 28 pares (lead, estágio) repetem em 30 dias, em 20 leads, e o padrão é
# `Follows 9 -> Follows 8 -> Follows 9` (17-18/09, num lote). `mensagem_follow9` é a
# despedida — "encerro aqui meu contato". Duas vezes em 32 h é a Michele de 26/08 outra vez.

rotulo, cap, log, db = enfileira(evento(stage_para=" Follows 9", evento_id=7050),
                                 conflito=True)
checa("segundo evento do mesmo (lead, estágio): 'reentrada'", rotulo, "reentrada")
checa("  e o INSERT foi TENTADO (o banco é quem decide, não um SELECT antes)",
      db.execute.await_count, 1)
checa("  e o log diz que é reentrada", "reentrada" in log, True)

rotulo, cap, _, _ = enfileira(evento(stage_para=" Follows 9"))
checa("o SQL tem ON CONFLICT DO NOTHING", "ON CONFLICT" in cap["sql"], True)
checa("  na UNIQUE (lead_exact_id, estagio_id)",
      "(lead_exact_id, estagio_id) DO NOTHING" in " ".join(cap["sql"].split()), True)
checa("  e RETURNING id, que é como sabemos qual dos dois aconteceu",
      "RETURNING id" in cap["sql"], True)
checa("grava o estagio_id do MAPA (estável), não o nome", cap["params"]["estagio_id"], 174514)
checa("  e o nome viaja ao lado, como histórico",
      cap["params"]["estagio_nome"], " Follows 9")
checa("grava lead_exact_id (id NA EXACT)", cap["params"]["lead_exact_id"], 51438018)
checa("grava o template do mapa", cap["params"]["template"], "mensagem_follow9")
checa("grava o evento_id como referência", cap["params"]["evento_id"], 7001)
checa("nasce `pendente`", cap["params"]["status"], FE_PENDENTE)
checa("  sem motivo", cap["params"]["motivo"], None)


# ==========================================================================================
print("\n8) `sem_sdr` e `sem_telefone` viram `skipped` ANTES de qualquer chamada à Meta")
#
# Diferente da allowlist, estes SÃO gravados — e a diferença é de fato: ali o lead está fora
# do TESTE (condição nossa, temporária); aqui falta dado DELE. Bloquear o par é a resposta
# certa: reenviar em loop um follow que não pode ser montado seria pior.

rotulo, cap, log, _ = enfileira(evento(stage_para="Follow 1", sdr_name=None))
checa("Follow 1 sem sdr_name: `skipped`", rotulo, FE_SKIPPED)
checa("  gravado com status skipped", cap["params"]["status"], FE_SKIPPED)
checa("  e com motivo (nunca vazio)", bool(cap["params"]["motivo"]), True)
checa("  e o motivo fala do SDR", "sdr_name" in cap["params"]["motivo"], True)

rotulo, cap, _, _ = enfileira(evento(stage_para="Follow 1", sdr_name="   "))
checa("sdr_name só com espaço também é ausente", rotulo, FE_SKIPPED)

# O degrau 4 não pede SDR: sem sdr_name, ele SAI.
rotulo, cap, _, _ = enfileira(evento(stage_para="Follow 4", sdr_name=None))
checa("Follow 4 (só `nome`) sem sdr_name: ENVIA", rotulo, FE_PENDENTE)
checa("  e o status é pendente", cap["params"]["status"], FE_PENDENTE)

rotulo, cap, _, _ = enfileira(evento(stage_para="Follow 4", telefone=None))
checa("sem telefone: `skipped` com motivo", (rotulo, bool(cap["params"]["motivo"])),
      (FE_SKIPPED, True))
rotulo, cap, _, _ = enfileira(evento(stage_para="Follow 4", telefone="  "))
checa("telefone só com espaço também é ausente", rotulo, FE_SKIPPED)

# Por que não deixar o fallback da rota agir: `sdr_name` cai em "Equipe CENAT", e o corpo do
# `mensagem_flow` é "Ola {{1}}, é o {{2}} do CENAT" — o lead leria "é o Equipe CENAT do CENAT".
checa("o motivo do sem_sdr diz o CAMINHO (consertar na Exact)",
      "Exact" in fem.MOTIVO_SEM_SDR, True)


# ==========================================================================================
print("\n9) O cursor: ausente é FALHA FECHADA, e só avança depois de enfileirar")


def le_eventos(cursor, eventos):
    """Roda `ler_eventos` com um banco dublê. Devolve `(resumo, sqls, log)`."""
    sqls = []

    async def execute(stmt, params=None):
        sql = " ".join(str(stmt).split())
        sqls.append((sql, params))
        r = MagicMock()
        if "FROM follow_estagio_cursor" in sql:
            r.first = MagicMock(return_value=None if cursor is None else (cursor,))
        elif "FROM exact_stage_events" in sql:
            r.mappings = MagicMock(return_value=MagicMock(
                all=MagicMock(return_value=eventos)))
        else:                                    # o INSERT e o UPDATE do cursor
            r.first = MagicMock(return_value=(1,))
        return r

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    db.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    with patch.object(fe, "async_session", MagicMock(return_value=ctx)):
        resumo, log = mudo(fe.ler_eventos)
    return resumo, sqls, log, db


resumo, sqls, log, db = le_eventos(cursor=None, eventos=[])
checa("cursor AUSENTE: não processa nada", resumo, {"sem_cursor": True})
checa("  e NÃO leu eventos (tratar como 0 varreria 1255 de histórico)",
      [s for s, _ in sqls if "exact_stage_events" in s], [])
checa("  e o log manda rodar a migração", "migrate_follow_estagio" in log, True)
checa("  e não commitou", db.commit.await_count, 0)

resumo, sqls, _, db = le_eventos(cursor=90000, eventos=[])
checa("nenhum evento novo: resumo vazio", resumo, {})
checa("  e o cursor NÃO foi movido", [s for s, _ in sqls if "UPDATE" in s], [])
checa("  e não commitou", db.commit.await_count, 0)

resumo, sqls, _, db = le_eventos(cursor=90000,
                                 eventos=[evento(evento_id=90001),
                                          evento(evento_id=90007, lead_exact_id=51438436,
                                                 stage_para="Follows 5")])
checa("dois eventos: dois enfileirados", resumo.get(FE_PENDENTE), 2)
checa("  e o cursor foi para o ÚLTIMO id lido", resumo.get("cursor"), 90007)
updates = [(s, p) for s, p in sqls if "UPDATE follow_estagio_cursor" in s]
checa("  com UM UPDATE do cursor", len(updates), 1)
checa("  para o id 90007", updates[0][1], {"id": 90007})
checa("  e commitou UMA vez (lote inteiro numa transação)", db.commit.await_count, 1)

# A ORDEM: o UPDATE do cursor é a ÚLTIMA escrita. Avançar antes de enfileirar perderia
# eventos em silêncio se o INSERT falhasse.
ordem = [s for s, _ in sqls if "INSERT INTO follow_estagio_envios" in s
         or "UPDATE follow_estagio_cursor" in s]
checa("  e o UPDATE do cursor vem DEPOIS dos INSERTs",
      ordem[-1].startswith("UPDATE follow_estagio_cursor"), True)

# O cursor é lido com FOR UPDATE: ele é lido, usado para filtrar e reescrito na mesma
# transação, e sem o lock dois processos leriam o mesmo valor.
leitura = [s for s, _ in sqls if "FROM follow_estagio_cursor" in s][0]
checa("o cursor é lido com FOR UPDATE", "FOR UPDATE" in leitura, True)

# O FILTRO INTEIRO NA QUERY (critério 2), não num `if` depois.
sel = [(s, p) for s, p in sqls if "FROM exact_stage_events" in s][0]
checa("a query filtra por funnel_id", "e.funnel_id = :funil" in sel[0], True)
checa("  com o funil do mapa", sel[1]["funil"], FUNIL)
checa("a query filtra por stage_para = ANY(...)", "stage_para = ANY(:estagios)" in sel[0], True)
checa("  com os nove nomes, byte a byte", sel[1]["estagios"], list(estagios_do_mapa()))
checa("  e NÃO usa ILIKE nem trim (semelhança traria `Follow 2 - Vi`)",
      ("ILIKE" in sel[0].upper() or "TRIM(" in sel[0].upper()), False)
checa("a query usa a marca d'água", "e.id > :cursor" in sel[0], True)
checa("  com o valor lido", sel[1]["cursor"], 90000)
checa("a query ordena por id (a marca d'água exige ordem)", "ORDER BY e.id" in sel[0], True)
checa("a query tem LIMIT (cursor zerado à mão não vira uma leitura só)",
      sel[1]["limite"], fe.MAX_EVENTOS_POR_CICLO)
# LEFT e não INNER: evento de lead ausente tem de ser CONSUMIDO, não ficar preso bloqueando
# os seguintes para sempre.
checa("o JOIN com exact_leads é LEFT", "LEFT JOIN exact_leads" in sel[0], True)
checa("  e traz el.id (PK local) E e.exact_lead_id (id na Exact)",
      ("el.id" in sel[0], "e.exact_lead_id" in sel[0]), (True, True))


# ==========================================================================================
print("\n10) O payload: `param_mappings`, `lead_ids` = PK LOCAL, `campanha`")


def envia(linha, lead, retorno=None, excecao=None):
    """Roda `_enviar_uma` com `bulk_send_template` mockado. Devolve `(status, payload, upd)`."""
    updates = []

    async def execute(stmt, params=None):
        texto = str(stmt)
        if texto.strip().upper().startswith("UPDATE"):
            updates.append(stmt.compile().params)
            return MagicMock()
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=lead)
        return r

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    bulk = AsyncMock(return_value=retorno, side_effect=excecao)
    with patch("app.exact_routes.bulk_send_template", new=bulk):
        status, log = mudo(fe._enviar_uma, db, linha)
    payload = bulk.await_args.args[0] if bulk.await_count else None
    envia.args = bulk.await_args.args if bulk.await_count else ()
    envia.kwargs = bulk.await_args.kwargs if bulk.await_count else {}
    return status, payload, (updates[-1] if updates else {}), log


def linha(**kw):
    l = MagicMock()
    l.id = kw.get("id", 4242)
    l.lead_exact_id = kw.get("lead_exact_id", 51438018)
    l.estagio_id = kw.get("estagio_id", 174516)     # " Follows 7", o do MÊS
    l.estagio_nome = kw.get("estagio_nome", " Follows 7")
    l.template = kw.get("template", "mensagem_follow7")
    return l


OK = {"sent": 1, "failed": 0, "errors": [], "skipped_nat": 0, "skipped_total": 0,
      "skipped_por_regra": {}, "skipped": []}

status, payload, upd, _ = envia(linha(), Lead(), retorno=OK)
checa("enviou -> status `enviado`", status, FE_ENVIADO)
checa("a chave é `param_mappings`, NÃO `mappings`",
      ("param_mappings" in payload, "mappings" in payload), (True, False))
checa("  e os mappings são os do degrau (nome + MÊS)",
      [x["type"] for x in payload["param_mappings"]], ["lead_name", "fixed_text"])
checa("  com o mês, não o curso", payload["param_mappings"][1]["value"] in MESES, True)
checa("`lead_ids` é o PK LOCAL de exact_leads", payload["lead_ids"], [9127])
checa("  e NÃO o exact_id", payload["lead_ids"] != [51438018], True)
checa("`origem_envio` é 'campanha' (é o que faz o nat_ativa valer)",
      payload["origem_envio"], "campanha")
checa("`template_name` vem do MAPA", payload["template_name"], "mensagem_follow7")
checa("`channel_id` = 1 (o único canal)", payload["channel_id"], fe.CANAL_ID)
checa("`language` = pt_BR", payload["language"], "pt_BR")
checa("o payload tem só as seis chaves que a rota lê", sorted(payload), sorted(
      ["template_name", "language", "channel_id", "lead_ids", "param_mappings",
       "origem_envio"]))
# A chamada é `bulk_send_template(payload, db)` — DOIS argumentos, como em main.py:238.
# `current_user` fica sem valor e recebe o próprio objeto `Depends`; `autoria.quem_enviou`
# devolve None, e "não houve humano logado" É a informação (sent_by NULL).
checa("a chamada é (payload, db): dois posicionais, sem current_user", len(envia.args), 2)
checa("  e nada por keyword", envia.kwargs, {})
checa("marcou `enviado_em`", "enviado_em" in upd, True)


# ==========================================================================================
print("\n11) O desfecho do bulk vira status — e `falhou` EXIGE motivo")

CASOS = [
    ("sent=1", OK, FE_ENVIADO, None),
    ("recusa", {**OK, "sent": 0, "skipped_total": 1, "skipped_por_regra": {"recusa": 1},
                "skipped": [{"regra": "recusa", "motivo": "pediu para parar"}]},
     FE_SKIPPED, "recusa"),
    ("opt_out_meta", {**OK, "sent": 0, "skipped_total": 1,
                      "skipped_por_regra": {"opt_out_meta": 1},
                      "skipped": [{"regra": "opt_out_meta", "motivo": "131050"}]},
     FE_SKIPPED, "opt_out_meta"),
    ("nat_ativa", {**OK, "sent": 0, "skipped_nat": 1, "skipped_total": 1,
                   "skipped_por_regra": {"nat_ativa": 1},
                   "skipped": [{"regra": "nat_ativa", "motivo": "conversa viva"}]},
     FE_SKIPPED, "nat_ativa"),
    ("a Meta recusou", {**OK, "sent": 0, "failed": 1,
                        "errors": [{"name": "X", "error": "131047 re-engagement"}]},
     FE_FALHOU, "131047"),
    # O caso que a chave errada produziria: lote vazio porque `lead_ids` não achou ninguém.
    ("lote vazio (lead_ids errado)", {**OK, "sent": 0}, FE_FALHOU, "sem `sent`"),
]
for rotulo, retorno, esperado, trecho in CASOS:
    st, mot = fe._desfecho_do_bulk(retorno)
    checa(f"{rotulo} -> {esperado}", st, esperado)
    if trecho:
        checa(f"  e o motivo cita {trecho!r}", trecho in (mot or ""), True)
    else:
        checa("  sem motivo (enviado não precisa)", mot, None)

# A lista de pulos chama-se `skipped`, não `pulados`. Ler a chave errada não daria erro:
# daria `[]`, e todo pulo cairia em `falhou` com motivo genérico — "falhou" para um lead que
# foi CORRETAMENTE poupado.
so_pulados = {**OK, "sent": 0, "pulados": [{"regra": "recusa", "motivo": "x"}]}
checa("um retorno com `pulados` e SEM `skipped` não é lido como pulo",
      fe._desfecho_do_bulk(so_pulados)[0], FE_FALHOU)
checa("  mas `skipped_total` é o cinto de segurança",
      fe._desfecho_do_bulk({**so_pulados, "skipped_total": 1})[0], FE_SKIPPED)

print()
status, _, upd, log = envia(linha(), Lead(), excecao=RuntimeError("Meta fora do ar"))
checa("exceção no bulk -> `falhou`", status, FE_FALHOU)
checa("  com motivo OBRIGATÓRIO e nomeando o erro",
      "RuntimeError" in (upd.get("motivo") or ""), True)
checa("  e o log é ruidoso", "❌" in log, True)

# O assert de `_finalizar` é a trava: os 60 `follow_20h` quebrados ficaram um mês
# indiagnosticáveis porque `falhou` não exigia motivo.
db = MagicMock(execute=AsyncMock())
try:
    asyncio.run(fe._finalizar(db, 1, status=FE_FALHOU, motivo=None))
    aceitou = True
except AssertionError:
    aceitou = False
checa("`falhou` SEM motivo é recusado (assert)", aceitou, False)
for mot in ("", "   "):
    try:
        asyncio.run(fe._finalizar(db, 1, status=FE_FALHOU, motivo=mot))
        aceitou = True
    except AssertionError:
        aceitou = False
    checa(f"`falhou` com motivo {mot!r} também é recusado", aceitou, False)
try:
    asyncio.run(fe._finalizar(db, 1, status=FE_ENVIADO))
    aceitou = True
except AssertionError:
    aceitou = False
checa("`enviado` sem motivo é normal", aceitou, True)

# O lead pode ter saído do espelho entre enfileirar e enviar.
status, payload, upd, _ = envia(linha(), None, retorno=OK)
checa("lead ausente na hora do envio: `skipped`, sem chamar a Meta",
      (status, payload), (FE_SKIPPED, None))
# O estágio pode ter saído do JSON.
status, payload, upd, _ = envia(linha(estagio_id=999999), Lead(), retorno=OK)
checa("estágio fora do mapa na hora do envio: `falhou` com motivo, sem enviar",
      (status, payload), (FE_FALHOU, None))
checa("  e o motivo cita o JSON", "follow_estagios.json" in (upd.get("motivo") or ""), True)

checa("os quatro status, e só eles", FE_STATUS,
      ("pendente", "enviado", "skipped", "falhou"))
checa("a espera entre envios é a da sprint (2s)", fe.ESPERA_ENTRE_ENVIOS_SEGUNDOS, 2)
# A decisão do Álefe (27/09) é "sem janela de horário", e ela tem de ser verificável, não só
# comentada: o módulo NÃO CHAMA `dentro_horario_comercial` nem `proximo_horario_util`. Procura
# a chamada (com parêntese), não a palavra — a docstring cita as duas para explicar por que
# não são usadas, e proibir a palavra proibiria a explicação.
_FONTE = open("app/follow_estagio.py", encoding="utf-8").read()
for fn in ("dentro_horario_comercial(", "proximo_horario_util("):
    checa(f"o módulo NÃO chama {fn[:-1]} (sem janela, decisão do Álefe)",
          fn in _FONTE, False)
checa("  e a docstring EXPLICA por que não",
      "SEM JANELA DE HORÁRIO" in _FONTE, True)
checa("  e o teto de rajada também não existe",
      "SEM TETO DE RAJADA" in _FONTE, True)


# ==========================================================================================
print("\n12) `131050` pula e `131049` não — a regra nova de higiene_disparo")
#
# O follow herda a higiene de graça, porque chama a rota. Aqui só se prova que a constante é
# a certa; o comportamento está em test_higiene_disparo.py §8.
from app.higiene_disparo import CODIGOS_OPT_OUT_META

checa("131050 (a pessoa apertou 'parar promoções') está na lista",
      131050 in CODIGOS_OPT_OUT_META, True)
checa("131049 (a META limitando frequência) NÃO está",
      131049 in CODIGOS_OPT_OUT_META, False)
checa("131026 (número indisponível) NÃO está", 131026 in CODIGOS_OPT_OUT_META, False)
checa("131047 (reengajamento) NÃO está", 131047 in CODIGOS_OPT_OUT_META, False)
checa("a lista tem UM código só", len(CODIGOS_OPT_OUT_META), 1)

# E o pulo por opt-out chega ao follow como `skipped` com a regra nomeada.
st, mot = fe._desfecho_do_bulk(
    {**OK, "sent": 0, "skipped_total": 1, "skipped_por_regra": {"opt_out_meta": 1},
     "skipped": [{"regra": "opt_out_meta", "motivo": "a Meta registrou… 131050"}]})
checa("o follow grava o opt-out como `skipped` nomeando a regra",
      (st, mot.startswith("opt_out_meta")), (FE_SKIPPED, True))


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado.")
