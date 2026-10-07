"""Bloco 1 — régua de confirmação de reunião (Fluxo A da spec da Isa, 28/09).

    cd backend && venv/bin/python test_confirmacao.py

NADA sai daqui: envio, Exact e banco são dublês. Escrito e NÃO executado na sprint de 07/10
(convenção do bloco).

O QUE ESTE TESTE PROVA
  1. calendário: os 5 casos do checkpoint, inclusive o pedido de domingo 17h para segunda
     de manhã e a regra de colisão (ementa/benefício que cairiam junto com o pedido)
  2. armar: flag desligada devolve 0; idempotente (já tem imediata); consultora fora da pós
  3. handlers pulam com motivo: Cancelada, régua encerrada, já confirmou, fora da janela sem
     tempo até o corte; a pausa por humano NÃO para o corte
  4. lista fechada de confirmação: cada texto confirma; variações com pontuação/acento/tom
     de pele confirmam; frases maiores não
  5. inbound: botão confirma; texto da lista confirma; texto fora pausa (mantém corte); recusa
     encerra; clique sem payload roteia pelo context.id só quando casa; flag desligada = False
  6. cancelamento escopado pela reunião (remarcação não derruba a régua da reunião nova)
  7. janela 8h–20h30 e o contrato da dúvida simples
"""
import asyncio
import io
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import confirmacao as cf
from app import nat_copy
from app import qualificacao_llm as llm
from app.models import (EXACT_TYPE_CANCELADA, EXACT_TYPE_VIGENTE, KIND_CONFIRM_A_BENEFICIO,
                        KIND_CONFIRM_A_CORTE, KIND_CONFIRM_A_EMENTA, KIND_CONFIRM_A_IMEDIATA,
                        KIND_CONFIRM_A_PEDIDO, KIND_CONFIRM_A_ULTIMO_AVISO)
from app.nat_guard import dentro_janela_envio, proxima_janela_envio
from app.nat_scheduler import AcaoAdiada, AcaoIgnorada

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def D(*a):
    return datetime(*a)


def kinds(regua):
    return {k: q for k, q in regua[0]}


# ==========================================================================================
print("\n1. calendário")
k = kinds(cf.calcular_regua(D(2026, 10, 15, 10, 0), D(2026, 10, 13, 15, 0)))
checa("ter 15h -> qui 10h: 6 ações", set(k), {KIND_CONFIRM_A_IMEDIATA, KIND_CONFIRM_A_EMENTA,
      KIND_CONFIRM_A_BENEFICIO, KIND_CONFIRM_A_PEDIDO, KIND_CONFIRM_A_ULTIMO_AVISO,
      KIND_CONFIRM_A_CORTE})
checa("  pedido na véspera 17h", k[KIND_CONFIRM_A_PEDIDO], D(2026, 10, 14, 17, 0))
checa("  último aviso no dia 8h", k[KIND_CONFIRM_A_ULTIMO_AVISO], D(2026, 10, 15, 8, 0))
checa("  corte no dia 9h", k[KIND_CONFIRM_A_CORTE], D(2026, 10, 15, 9, 0))
checa("  benefício 23h (o handler empurra para 8h)", k[KIND_CONFIRM_A_BENEFICIO],
      D(2026, 10, 13, 23, 0))

k = kinds(cf.calcular_regua(D(2026, 10, 15, 10, 0), D(2026, 10, 14, 19, 0)))
checa("qua 19h -> qui 10h: sem pedido (17h passou) e sem ementa/benefício (colisão)", set(k),
      {KIND_CONFIRM_A_IMEDIATA, KIND_CONFIRM_A_ULTIMO_AVISO, KIND_CONFIRM_A_CORTE})

k = kinds(cf.calcular_regua(D(2026, 10, 15, 14, 0), D(2026, 10, 15, 11, 0)))
checa("qui 11h -> qui 14h (< 4h): só a imediata", set(k), {KIND_CONFIRM_A_IMEDIATA})

k = kinds(cf.calcular_regua(D(2026, 10, 19, 10, 0), D(2026, 10, 16, 16, 0)))
checa("sex 16h -> seg 10h: pedido no DOMINGO 17h", k[KIND_CONFIRM_A_PEDIDO],
      D(2026, 10, 18, 17, 0))

k = kinds(cf.calcular_regua(D(2026, 10, 14, 16, 30), D(2026, 10, 13, 15, 0)))
checa("ter 15h -> qua 16h30: corte 4h antes", k[KIND_CONFIRM_A_CORTE], D(2026, 10, 14, 12, 30))
checa("  último aviso 1h antes do corte", k[KIND_CONFIRM_A_ULTIMO_AVISO],
      D(2026, 10, 14, 11, 30))
checa("  benefício cairia às 8h junto com o pedido: fora", KIND_CONFIRM_A_BENEFICIO in k, False)
checa("  ementa às 19h fica", k[KIND_CONFIRM_A_EMENTA], D(2026, 10, 13, 19, 0))

checa("dia por extenso", cf.dia_extenso(D(2026, 10, 15, 10)), "quinta-feira, 15/10")
checa("hoje/amanhã", (cf.hoje_ou_amanha(D(2026, 10, 15, 10), D(2026, 10, 15, 8)),
                      cf.hoje_ou_amanha(D(2026, 10, 15, 10), D(2026, 10, 14, 17))),
      ("hoje", "amanhã"))


# ==========================================================================================
def reuniao(**kw):
    base = dict(meeting_id=4774374, lead_id=52500000, telefone_chave="8388046720",
                telefone_bruto="5583988046720", nome="Álefe Teste",
                slot_inicio=D(2026, 10, 15, 10, 0), sales_rep_email="comercial@cenatcursos.com.br",
                origem="hub", agendamento_id=971, exact_type=EXACT_TYPE_VIGENTE,
                registrado_em=D(2026, 10, 13, 15, 0), confirmado_em=None, confirmado_por=None,
                cancelado_em=None, cancelado_motivo=None, regua_encerrada_em=None,
                regua_encerrada_motivo=None)
    base.update(kw)
    return SimpleNamespace(**base)


ENV_LIGADO = {"CONFIRMACAO_ENABLED": "true", "CONFIRMACAO_SOMENTE_TELEFONES": ""}
CONSULTORA = SimpleNamespace(nome_exibicao="Victória Amorim", telefone="", user_id_hub=None,
                             email="comercial@cenatcursos.com.br")


def roda(coro):
    saida = io.StringIO()
    with redirect_stdout(saida):
        try:
            return asyncio.run(coro), saida.getvalue()
        except (AcaoIgnorada, AcaoAdiada) as e:
            return e, saida.getvalue()


print("\n2. armar")
with patch.dict("os.environ", {"CONFIRMACAO_ENABLED": "false"}):
    n, _ = roda(cf.armar(reuniao(), None, agora=D(2026, 10, 13, 15)))
checa("flag desligada: 0, sem tocar no banco (db=None)", n, 0)

with patch.dict("os.environ", ENV_LIGADO), \
        patch.object(cf, "_consultora", return_value=CONSULTORA), \
        patch.object(cf, "_acoes", AsyncMock(return_value=[object()])):
    n, _ = roda(cf.armar(reuniao(), None, agora=D(2026, 10, 13, 15)))
checa("já tem imediata (qualquer status): idempotente, 0", n, 0)

with patch.dict("os.environ", ENV_LIGADO), patch.object(cf, "_consultora", return_value=None):
    n, log = roda(cf.armar(reuniao(sales_rep_email="executivadecarreiras@cenatcursos.com.br"),
                           None, agora=D(2026, 10, 13, 15)))
checa("consultora fora da pós (intercâmbio): 0 e log", (n, "fora de consultoras.json" in log),
      (0, True))

with patch.dict("os.environ", {**ENV_LIGADO, "CONFIRMACAO_SOMENTE_TELEFONES": "11999998888"}):
    n, _ = roda(cf.armar(reuniao(), None, agora=D(2026, 10, 13, 15)))
checa("fora da allowlist: 0", n, 0)


# ==========================================================================================
print("\n3. handlers pulam com motivo")


def espinha(r, kind, agora):
    acao = {"id": 1, "contact_wa_id": "558388046720", "agora": agora,
            "payload": f'{{"meeting_id": {r.meeting_id}}}'}
    with patch.dict("os.environ", ENV_LIGADO), patch.object(cf, "_reuniao", AsyncMock(return_value=r)):
        return roda(cf._espinha(acao, None, kind))[0]


e = espinha(reuniao(exact_type=EXACT_TYPE_CANCELADA), KIND_CONFIRM_A_PEDIDO, D(2026, 10, 14, 17))
checa("Cancelada na Exact -> skipped", (type(e), "Cancelada" in e.motivo), (AcaoIgnorada, True))
e = espinha(reuniao(regua_encerrada_em=D(2026, 10, 14, 10), regua_encerrada_motivo="remarcar"),
            KIND_CONFIRM_A_PEDIDO, D(2026, 10, 14, 17))
checa("régua encerrada -> skipped", (type(e), "remarcar" in e.motivo), (AcaoIgnorada, True))
e = espinha(reuniao(confirmado_em=D(2026, 10, 13, 16)), KIND_CONFIRM_A_ULTIMO_AVISO,
            D(2026, 10, 15, 8))
checa("já confirmou -> skipped", (type(e), "já confirmou" in e.motivo), (AcaoIgnorada, True))
e = espinha(reuniao(), KIND_CONFIRM_A_ULTIMO_AVISO, D(2026, 10, 15, 7, 0))
checa("último aviso às 7h: próxima janela (8h) é antes do corte (9h) -> adiada",
      (type(e), getattr(e, "quando", None)), (AcaoAdiada, D(2026, 10, 15, 8, 0)))
e = espinha(reuniao(slot_inicio=D(2026, 10, 15, 12, 15)), KIND_CONFIRM_A_ULTIMO_AVISO,
            D(2026, 10, 15, 7, 15))
checa("último aviso 7h15 com corte 8h15: 8h é antes -> adiada", type(e), AcaoAdiada)
e = espinha(reuniao(slot_inicio=D(2026, 10, 15, 11, 30)), KIND_CONFIRM_A_EMENTA,
            D(2026, 10, 15, 6, 0))
checa("ementa 6h com corte 9h... a janela abre 8h: adiada",
      type(e), AcaoAdiada)
e = espinha(reuniao(slot_inicio=D(2026, 10, 15, 12, 0)), KIND_CONFIRM_A_ULTIMO_AVISO,
            D(2026, 10, 15, 7, 0))
checa("corte 8h e janela abre 8h: sem tempo -> skipped", type(e), AcaoIgnorada)
r, wa, agora, limite = espinha(reuniao(regua_encerrada_em=D(2026, 10, 14, 10),
                                       regua_encerrada_motivo="humano"),
                               KIND_CONFIRM_A_CORTE, D(2026, 10, 15, 9, 0))
checa("pausa por humano NÃO para o corte", limite, D(2026, 10, 15, 10, 0))
e = espinha(reuniao(regua_encerrada_em=D(2026, 10, 14, 10), regua_encerrada_motivo="humano"),
            KIND_CONFIRM_A_PEDIDO, D(2026, 10, 14, 17))
checa("pausa por humano para o pedido", type(e), AcaoIgnorada)
e = espinha(reuniao(), KIND_CONFIRM_A_IMEDIATA, D(2026, 10, 13, 23, 0))
checa("imediata às 23h NÃO respeita a janela (spec)", type(e), tuple)

# ==========================================================================================
print("\n4. lista fechada de confirmação")
for t in ("ok", "OK!", "👍", "👍🏽", "Confirmo.", "confirmado", "Sim", "certo", "combinado",
          "Estarei lá", "estarei la!", "pode ser", "isso"):
    checa(f"{t!r} confirma", cf.e_confirmacao(t), True)
for t in ("ok, mas posso mudar?", "sim, quanto custa?", "não", "talvez", "", "confirmo amanhã"):
    checa(f"{t!r} não confirma", cf.e_confirmacao(t), False)
checa("recusa casa 'não tenho interesse'", cf._recusa("Não tenho interesse"), True)
checa("recusa NÃO casa 'não há mais interesse' (memória)", cf._recusa("não há mais interesse"),
      False)


# ==========================================================================================
print("\n5. inbound")


def inbound(r, *, evento=None, content="", cortada=False, contexto=None):
    chamadas = {}

    def grava(nome):
        async def f(*a, **k):
            chamadas[nome] = a
        return f
    with patch.dict("os.environ", ENV_LIGADO), \
            patch.object(cf, "_reuniao_dona", AsyncMock(return_value=(r, cortada))), \
            patch.object(cf, "_payload_pelo_contexto", AsyncMock(return_value=contexto)), \
            patch.object(cf, "_duvida_simples", AsyncMock(return_value=False)), \
            patch.object(cf, "confirmar", grava("confirmar")), \
            patch.object(cf, "remarcar", grava("remarcar")), \
            patch.object(cf, "cancelado_pelo_lead", grava("cancelado")), \
            patch.object(cf, "ligar_agora", grava("ligar")), \
            patch.object(cf, "sem_interesse", grava("sem_interesse")), \
            patch.object(cf, "pausar", grava("pausar")):
        dono, _ = roda(cf.inbound("558388046720", evento, content, None))
    return dono, set(chamadas), chamadas


def botao(payload, texto="", ctx=None):
    return {"button_payload": payload, "button_text": texto, "context_message_id": ctx}


checa("botão Confirmo (A_CONF_SIM) confirma", inbound(reuniao(), evento=botao("A_CONF_SIM"))[:2],
      (True, {"confirmar"}))
checa("A_PED_NAO cancela pelo lead", inbound(reuniao(), evento=botao("A_PED_NAO"))[1],
      {"cancelado"})
checa("A_ULT_REMARCAR remarca", inbound(reuniao(), evento=botao("A_ULT_REMARCAR"))[1],
      {"remarcar"})
d, c, args = inbound(reuniao(), content="Estarei lá!")
checa("texto da lista confirma por 'texto'", (c, args["confirmar"][2]), ({"confirmar"}, "texto"))
checa("texto fora da lista pausa", inbound(reuniao(), content="vai ser por vídeo?")[1],
      {"pausar"})
checa("áudio pausa", inbound(reuniao(), content="media:123|audio/ogg|")[1], {"pausar"})
checa("recusa encerra sem resposta", inbound(reuniao(), content="não tenho interesse")[1],
      {"sem_interesse"})
checa("clique sem payload COM context casando -> roteia",
      inbound(reuniao(), evento=botao("", "Confirmo", "wamid.X"), contexto="A_PED_SIM")[1],
      {"confirmar"})
checa("clique sem payload SEM context casando -> pausa",
      inbound(reuniao(), evento=botao("", "Confirmo", "wamid.Y"), contexto=None)[1], {"pausar"})
checa("depois do corte: NS_D0_AGORA liga", inbound(reuniao(), evento=botao("NS_D0_AGORA"),
                                                   cortada=True)[1], {"ligar"})
checa("depois do corte: texto livre não é da régua",
      inbound(reuniao(), content="oi", cortada=True)[:2], (False, set()))
with patch.dict("os.environ", {"CONFIRMACAO_ENABLED": "false"}):
    dono, _ = roda(cf.inbound("558388046720", None, "ok", None))
checa("flag desligada: False sem tocar no banco", dono, False)


# ==========================================================================================
print("\n6. cancelamento escopado pela reunião")


class DB:
    def __init__(self):
        self.sql = []

    async def execute(self, stmt, params=None):
        self.sql.append(str(stmt.compile(compile_kwargs={"literal_binds": False})))
        return SimpleNamespace(rowcount=2)


db = DB()
n, _ = roda(cf._cancelar_da_reuniao(reuniao(), (KIND_CONFIRM_A_PEDIDO, "lembrete_reuniao"),
                                     "reuniao_cancelada_exact", db))
checa("UPDATE filtra pelo meeting_id do payload (não por contato)",
      "payload::json->>'meeting_id'" in db.sql[0] and "contact_wa_id" not in db.sql[0], True)
checa("o T-30 do Hub casa pelo agendamento_id", "agendamento_id" in db.sql[0], True)


# ==========================================================================================
print("\n7. janela e dúvida simples")
checa("7h59 fora, 8h dentro, 20h29 dentro, 20h30 fora",
      [dentro_janela_envio(D(2026, 10, 7, h, m)) for h, m in ((7, 59), (8, 0), (20, 29), (20, 30))],
      [False, True, True, False])
checa("sábado 10h dentro (todos os dias)", dentro_janela_envio(D(2026, 10, 10, 10, 0)), True)
checa("20h30 -> amanhã 8h", proxima_janela_envio(D(2026, 10, 7, 20, 30)), D(2026, 10, 8, 8, 0))
checa("contrato: duvida_simples válida",
      llm._validar_duvida('{"tipo":"duvida_simples","resposta":"Dura cerca de 15 minutos."}'),
      {"tipo": "duvida_simples", "resposta": "Dura cerca de 15 minutos."})
checa("contrato: resposta com pergunta é recusada",
      llm._validar_duvida('{"tipo":"duvida_simples","resposta":"Quer confirmar?"}'), None)
checa("contrato: tipo desconhecido é recusado", llm._validar_duvida('{"tipo":"preco"}'), None)
checa("contrato: JSON torto é recusado", llm._validar_duvida("{tipo"), None)
checa("botões da dúvida = Confirmo/Preciso remarcar do pedido",
      [b["payload"] for b in nat_copy.BOTOES_LIVRES["confirm_a_duvida"]],
      ["A_PED_SIM", "A_PED_REMARCAR"])

print()
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ todos os casos passaram")
