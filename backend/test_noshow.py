"""Bloco 2 — régua de no-show D0+1h a D8.

    cd backend && venv/bin/python test_noshow.py

NADA sai daqui: envio, Exact e banco são dublês. Escrito e NÃO executado na sprint de 07/10.

O QUE ESTE TESTE PROVA
  1. relógio: corte ter 9h e sex 15h; D0+8h às 22h adia para 8h e não colide com o D1 9h
  2. armar: sem flag devolve 0; idempotente (noshow_em já gravado); reabre a coluna da régua
  3. handlers: régua encerrada e colisão viram skipped; degrau sem conteúdo pula com motivo
  4. cada clique encerra com o motivo certo; texto livre encerra como humano; "QUERO" só
     depois do D3; recusa encerra sem resposta
  5. arrasto: SDR moveu = sdr_assumiu; a volta automática Agendados -> Entrada não conta
  6. conteúdo do mês: vazio ou vencido = None; linha de horários hoje/amanhã e o fallback
"""
import asyncio
import io
from contextlib import redirect_stdout
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import confirmacao as cf
from app import nat_copy
from app import noshow as ns
from app.models import (KIND_NOSHOW_D0_8H, KIND_NOSHOW_D1, KIND_NOSHOW_D2, KIND_NOSHOW_D3,
                        KIND_NOSHOW_D8, KINDS_NOSHOW)
from app.nat_guard import proxima_janela_envio
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


def roda(coro):
    saida = io.StringIO()
    with redirect_stdout(saida):
        try:
            return asyncio.run(coro), saida.getvalue()
        except (AcaoIgnorada, AcaoAdiada) as e:
            return e, saida.getvalue()


# ==========================================================================================
print("\n1. relógio")
g = dict(ns.calcular_degraus(D(2026, 10, 13, 9, 0)))
checa("corte ter 9h: 8 degraus", list(g), list(KINDS_NOSHOW))
checa("  D0+8h 17h", g[KIND_NOSHOW_D0_8H], D(2026, 10, 13, 17, 0))
checa("  D1 qua 9h", g[KIND_NOSHOW_D1], D(2026, 10, 14, 9, 0))
checa("  D8 qua 21/10 10h", g[KIND_NOSHOW_D8], D(2026, 10, 21, 10, 0))
g = dict(ns.calcular_degraus(D(2026, 10, 16, 15, 0)))
checa("corte sex 15h: D2 domingo 10h", g[KIND_NOSHOW_D2], D(2026, 10, 18, 10, 0))
g = dict(ns.calcular_degraus(D(2026, 10, 14, 14, 0)))
checa("corte 14h: D0+8h 22h", g[KIND_NOSHOW_D0_8H], D(2026, 10, 14, 22, 0))
checa("  adiado para 8h", proxima_janela_envio(g[KIND_NOSHOW_D0_8H]), D(2026, 10, 15, 8, 0))
checa("  e 8h é antes do D1 9h", proxima_janela_envio(g[KIND_NOSHOW_D0_8H]) <
      ns.proximo_degrau(D(2026, 10, 14, 14, 0), KIND_NOSHOW_D0_8H), True)
checa("D8 não tem próximo", ns.proximo_degrau(D(2026, 10, 14, 14, 0), KIND_NOSHOW_D8), None)


# ==========================================================================================
def reuniao(**kw):
    base = dict(meeting_id=4774374, lead_id=52500000, telefone_chave="8388046720",
                telefone_bruto="5583988046720", nome="Álefe Teste", agendamento_id=971,
                slot_inicio=D(2026, 10, 14, 10, 0), noshow_em=None,
                regua_encerrada_em=D(2026, 10, 14, 9, 0), regua_encerrada_motivo="corte",
                sales_rep_email="comercial@cenatcursos.com.br")
    base.update(kw)
    return SimpleNamespace(**base)


ENV = {"NOSHOW_ENABLED": "true", "NOSHOW_SOMENTE_TELEFONES": ""}

print("\n2. armar")
with patch.dict("os.environ", {"NOSHOW_ENABLED": "false"}):
    n, _ = roda(ns.armar(reuniao(), "558388046720", None))
checa("flag desligada: 0", n, 0)
with patch.dict("os.environ", ENV):
    n, _ = roda(ns.armar(reuniao(noshow_em=D(2026, 10, 14, 9)), "558388046720", None))
checa("noshow_em já gravado: 0 (idempotente)", n, 0)
r = reuniao()
agendados = []


async def _agendar(kind, wa, quando, payload, db):
    agendados.append((kind, quando, payload))

with patch.dict("os.environ", ENV), patch("app.nat_scheduler.agendar", _agendar):
    n, _ = roda(ns.armar(r, "558388046720", None, agora=D(2026, 10, 14, 9, 0)))
checa("arma 8 degraus", (n, len(agendados)), (8, 8))
checa("grava noshow_em", r.noshow_em, D(2026, 10, 14, 9, 0))
checa("reabre a régua (o corte tinha encerrado a de confirmação)",
      (r.regua_encerrada_em, r.regua_encerrada_motivo), (None, None))
checa("payload = meeting_id", agendados[0][2], {"meeting_id": 4774374})


# ==========================================================================================
print("\n3. handlers")


def espinha(r, kind, agora):
    acao = {"id": 1, "contact_wa_id": "558388046720", "agora": agora,
            "payload": f'{{"meeting_id": {r.meeting_id}}}'}
    with patch.dict("os.environ", ENV), patch.object(cf, "_reuniao", AsyncMock(return_value=r)):
        return roda(ns._espinha(acao, None, kind))[0]


viva = reuniao(noshow_em=D(2026, 10, 14, 14, 0), regua_encerrada_em=None,
               regua_encerrada_motivo=None)
e = espinha(reuniao(noshow_em=D(2026, 10, 14, 14), regua_encerrada_motivo="humano"),
            KIND_NOSHOW_D1, D(2026, 10, 15, 9))
checa("régua encerrada -> skipped", (type(e), "humano" in e.motivo), (AcaoIgnorada, True))
e = espinha(viva, KIND_NOSHOW_D0_8H, D(2026, 10, 14, 22, 0))
checa("D0+8h às 22h -> adiada para 8h", (type(e), getattr(e, "quando", None)),
      (AcaoAdiada, D(2026, 10, 15, 8, 0)))
e = espinha(viva, KIND_NOSHOW_D0_8H, D(2026, 10, 15, 9, 0))
checa("D0+8h executado depois do D1 -> colidiu", (type(e), "colidiu" in e.motivo),
      (AcaoIgnorada, True))

with patch.dict("os.environ", ENV), \
        patch.object(ns, "_espinha", AsyncMock(return_value=(viva, "558388046720",
                                                             D(2026, 10, 17, 10), None))), \
        patch.object(ns, "conteudos", return_value={"seminario": {"nome": "", "data": "",
                                                                   "hora": "", "valido_ate": ""}}):
    e, _ = roda(ns.noshow_d3({"id": 1, "contact_wa_id": "558388046720"}, None))
checa("D3 sem seminário cadastrado -> 'conteúdo do mês não cadastrado'",
      (type(e), e.motivo.startswith(ns.SEM_CONTEUDO)), (AcaoIgnorada, True))
with patch.dict("os.environ", ENV), \
        patch.object(ns, "_espinha", AsyncMock(return_value=(viva, "558388046720",
                                                             D(2026, 10, 16, 10), None))), \
        patch.object(cf, "_sub_source", AsyncMock(return_value="Curso Sem Audio")), \
        patch.object(ns, "conteudos", return_value={"audio_por_curso": {}}):
    e, _ = roda(ns.noshow_d2({"id": 1, "contact_wa_id": "558388046720"}, None))
checa("D2 sem áudio do curso -> pula com motivo", e.motivo.startswith(ns.SEM_CONTEUDO), True)
checa("pular um degrau não toca nos outros (cada kind é uma ação)", len(set(KINDS_NOSHOW)), 8)


# ==========================================================================================
print("\n4. inbound")


def inbound(r, *, evento=None, content="", d3=False, contexto=None):
    chamadas = {}

    def grava(nome):
        async def f(*a, **k):
            chamadas.setdefault(nome, []).append((a, k))
        return f
    with patch.object(ns, "encerrar", grava("encerrar")), \
            patch.object(ns, "_payload_pelo_contexto", AsyncMock(return_value=contexto)), \
            patch.object(ns, "_d3_ja_saiu", AsyncMock(return_value=d3)), \
            patch.object(ns, "conteudos", return_value={"seminario": {"nome": "Território"}}), \
            patch.object(cf, "ligar_agora", grava("ligar")), \
            patch.object(cf, "remarcar", grava("remarcar")), \
            patch.object(cf, "_notificar", grava("notificar")), \
            patch.object(cf, "_responder", grava("responder")), \
            patch.object(cf, "_nome", AsyncMock(return_value="Álefe")):
        dono, _ = roda(ns.inbound(r, "558388046720", evento, content, None))
    motivo = chamadas["encerrar"][0][0][1] if "encerrar" in chamadas else None
    return dono, motivo, set(chamadas)


def botao(p, texto="", ctx=None):
    return {"button_payload": p, "button_text": texto, "context_message_id": ctx}


for p, acao in ((nat_copy.NS_1H_AGORA, "ligar"), (nat_copy.NS_8H_HORARIO, "remarcar"),
                (nat_copy.NS_D1_HORARIO, "remarcar"), (nat_copy.NS_D2_AGORA, "ligar"),
                (nat_copy.NS_D7_REAGENDAR, "remarcar"), (nat_copy.NS_D8_AGORA, "ligar"),
                (nat_copy.NS_D0_HORARIO, "remarcar")):
    d, motivo, c = inbound(viva, evento=botao(p))
    checa(f"{p}: encerra com motivo {p} e {acao}", (d, motivo, acao in c), (True, p, True))
d, motivo, c = inbound(viva, evento=botao(nat_copy.NS_D3_QUERO))
checa("Quero participar: encerra, avisa e responde", (motivo, {"notificar", "responder"} <= c),
      (nat_copy.NS_D3_QUERO, True))
checa("texto QUERO depois do D3 = Quero participar",
      inbound(viva, content="Quero!", d3=True)[1], nat_copy.NS_D3_QUERO)
checa("texto QUERO antes do D3 = humano", inbound(viva, content="quero", d3=False)[1], "humano")
d, motivo, c = inbound(viva, content="não tenho interesse")
checa("recusa: sem_interesse e sem resposta", (motivo, "responder" in c), ("sem_interesse", False))
d, motivo, c = inbound(viva, content="media:9|audio/ogg|")
checa("áudio: humano, sem resposta", (motivo, "responder" in c), ("humano", False))
checa("clique sem payload casando pelo contexto",
      inbound(viva, evento=botao("", "Reagendar", "wamid.X"), contexto=nat_copy.NS_D2_REAGENDAR)[1],
      nat_copy.NS_D2_REAGENDAR)


# ==========================================================================================
print("\n5. arrasto")


class DB:
    def __init__(self, vivas):
        self.vivas = vivas

    async def execute(self, stmt, params=None):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.vivas))


encerrados = []


async def _enc(r, motivo, db, **k):
    encerrados.append(motivo)

with patch.object(ns, "encerrar", _enc):
    roda(ns.encerrar_por_arrasto([(1, "5583988046720", "Agendados", "Entrada")], DB([viva])))
    checa("Agendados -> Entrada (cancelamento) NÃO encerra", encerrados, [])
    roda(ns.encerrar_por_arrasto([(1, "5583988046720", "Entrada", "Follow 1")], DB([viva])))
    checa("Entrada -> Follow 1 encerra com sdr_assumiu", encerrados, ["sdr_assumiu"])

# ==========================================================================================
print("\n6. conteúdo e horários")
hoje = date(2026, 10, 15)
checa("seminário vazio = None", ns._vigente({"nome": ""}, hoje, ("nome",)), None)
checa("valido_ate vencido = None", ns._vigente({"texto": "x", "valido_ate": "2026-10-14"}, hoje,
                                               ("texto", "valido_ate")), None)
checa("valido_ate hoje vale", bool(ns._vigente({"texto": "x", "valido_ate": "2026-10-15"}, hoje,
                                               ("texto", "valido_ate"))), True)
checa("curso sem caixa", ns._por_curso({"Pos TEA V3": "abc"}, "pos tea v3"), "abc")
agora = D(2026, 10, 15, 9, 0)
slots = [D(2026, 10, 15, 14, 15), D(2026, 10, 15, 16, 30), D(2026, 10, 15, 17, 15),
         D(2026, 10, 16, 10, 0)]
checa("hoje e amanhã, 2 por dia", ns.linha_de_horarios(slots, agora),
      "hoje 14h15, 16h30 ou amanhã 10h00")
checa("sem hoje/amanhã: próximos dias", ns.linha_de_horarios([D(2026, 10, 19, 10, 0)],
                                                             D(2026, 10, 16, 21, 0)),
      "segunda-feira, 19/10 10h00")
checa("nada livre = None", ns.linha_de_horarios([], agora), None)

print()
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ todos os casos passaram")
