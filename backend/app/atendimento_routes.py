"""O painel de Atendimento: tempo de resposta, SLA de 2 h, janela de 24 h e quem está sem
retorno (pedido da Isa, 13/10/2026). Somente leitura, só admin.

AS DEFINIÇÕES SÃO AS DE `/relatorios/humano`, NÃO UMA SEGUNDA LEITURA
------------------------------------------------------------------------------------------
Dois números para a mesma coisa é o defeito que a página de relatórios existe para não ter.
Por isso a consulta-base (`SQL_PERGUNTAS`) é o CTE `w` de `relatorios.SQL_MEDIANA`, com
colunas a mais e o mesmo predicado:

  conversa   thread por telefone (`relatorios.CHAVE_MSG`, tolerante ao 9º dígito)
  pergunta   mensagem `inbound` cuja anterior na thread não é `inbound`. Rajada conta uma.
  resposta   a primeira `outbound` com `message_type <> 'template'` depois da pergunta.
             Template depois da pergunta é disparo, não resposta: entra em `so_template`.
  quem       `nat_etapa` da resposta preenchida = automação (agente ou régua); senão, time.

O mesmo período sobre as duas rotas dá a mesma mediana, e `test_atendimento.py` confere.

ONDE CADA CONTA É FEITA
------------------------------------------------------------------------------------------
O SQL faz o que só ele faz barato: as janelas por thread (pergunta, resposta, fim da rajada).
Devolve UMA LINHA POR PERGUNTA, algumas centenas em 30 dias. O resto (SLA corrido e em
expediente, janela de 24 h, série, histograma, tabela por SDR) é Python sobre essas linhas,
em funções puras: o teste prova a regra sem banco, e a regra do expediente (8h a 20h30, a
mesma janela das réguas, `nat_guard.JANELA_REGUA_*`) não vira uma função SQL de 30 linhas
que ninguém revisa.

O RELÓGIO
------------------------------------------------------------------------------------------
Tudo SP naive (`messages.timestamp`). `contacts.created_at` e afins não entram aqui.

DONO DA PERGUNTA: HISTÓRICO É PROXY, LISTA VIVA É ESTADO
------------------------------------------------------------------------------------------
Na série (passado), não há como saber quem era dono do inbound naquele instante: a etapa do
agente é sobrescrita e não tem histórico. A regra usada é a única que o banco permite:
respondida = quem respondeu; sem resposta = automação se a última mensagem nossa antes da
pergunta tinha `nat_etapa`, senão time. Na lista de pendentes (agora) o dono é o estado real:
`nat_qualificacao_state` ativo, régua viva em `reuniao_status`, senão o SDR do contato.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from functools import wraps

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_admin
from app.database import get_db
from app.models import ETAPAS_QUALIFICACAO_ATIVAS
from app.nat_guard import JANELA_REGUA_FIM, JANELA_REGUA_INICIO
from app.relatorios import (CHAVE_MSG, CORTE_SENT_BY, MOVEL, Periodo, agora_sp,
                            chaves_de_teste, envelope, janela, metrica)
from app.telefone import chave_telefone

router = APIRouter(prefix="/api/atendimento", tags=["atendimento"],
                   dependencies=[Depends(get_current_admin)])
log = logging.getLogger(__name__)

SLA = timedelta(hours=2)
JANELA_META = timedelta(hours=24)
LIMIAR_PERTO = timedelta(hours=20)        # = window_20h do window_alerts_job
ANOMALIA_AUTOMACAO = timedelta(minutes=10)
PENDENTES_DIAS = 7                        # lista viva olha a última semana (ver /pendentes)

# Faixas do histograma, em segundos. A última é aberta.
FAIXAS = [("até 15 min", 15 * 60), ("15 min a 1 h", 3600), ("1 h a 2 h", 2 * 3600),
          ("2 h a 6 h", 6 * 3600), ("6 h a 24 h", 24 * 3600), ("mais de 24 h", None)]

QUEM = ("time", "ia", "ambos")
_R_SP = "SP (messages.timestamp)"


# ==========================================================================================
# AS CONSULTAS
# ==========================================================================================
SQL_PERGUNTAS = f"""
-- RELÓGIO: SP (messages.timestamp). Uma linha por PERGUNTA do período.
-- É o CTE `w` de relatorios.SQL_MEDIANA com quatro colunas a mais:
--   rajada      contador de mensagens nossas até aqui: todas as mensagens do lead entre
--               duas nossas têm o mesmo valor, e a nossa que abriu o grupo também
--   ultimo_inb  a última mensagem da rajada: é ELA que abre a janela de 24 h da Meta
--   etapa_antes nat_etapa da nossa mensagem imediatamente anterior (proxy do dono)
--   ts_tpl      primeiro template depois da pergunta (o "recebeu só template")
-- A resposta é procurada até :fim, não até agora: "sem resposta" é no fim do período.
-- CUSTO MEDIDO (13/10/2026): ver SPRINT_DASH_ATENDIMENTO_20261013_REPORT.md §2.
WITH mk AS (
  SELECT m.id, m.contact_wa_id AS wa, m.direction, m.message_type, m.timestamp AS ts,
         m.nat_etapa, m.sent_by, {CHAVE_MSG} AS thr
  FROM messages m WHERE m.timestamp >= :ini AND m.timestamp <= :fim
), g AS (
  SELECT mk.*,
    lag(direction) OVER p AS dir_ant,
    count(*) FILTER (WHERE direction <> 'inbound')
          OVER (PARTITION BY thr ORDER BY ts, id ROWS UNBOUNDED PRECEDING) AS rajada
  FROM mk WINDOW p AS (PARTITION BY thr ORDER BY ts, id)
), w AS (
  SELECT g.*,
    max(ts) FILTER (WHERE direction = 'inbound') OVER r AS ultimo_inb,
    max(nat_etapa) FILTER (WHERE direction <> 'inbound') OVER r AS etapa_antes,
    min(ts) FILTER (WHERE direction = 'outbound' AND message_type <> 'template') OVER f AS ts_resp,
    (array_agg(nat_etapa) FILTER (WHERE direction = 'outbound' AND message_type <> 'template')
            OVER f)[1] AS etapa_resp,
    (array_agg(sent_by) FILTER (WHERE direction = 'outbound' AND message_type <> 'template')
            OVER f)[1] AS sent_by_resp,
    min(ts) FILTER (WHERE direction = 'outbound' AND message_type = 'template') OVER f AS ts_tpl
  FROM g
  WINDOW r AS (PARTITION BY thr, rajada),
         f AS (PARTITION BY thr ORDER BY ts, id ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING)
)
SELECT w.thr, w.wa, w.ts, w.ultimo_inb, w.ts_resp, w.ts_tpl, w.etapa_antes,
       w.etapa_resp, w.sent_by_resp AS sent_by, ur.name AS sent_by_nome,
       c.assigned_to AS dono_id, ud.name AS dono_nome
FROM w
LEFT JOIN users ur ON ur.id = w.sent_by_resp
LEFT JOIN contacts c ON c.wa_id = w.wa
LEFT JOIN users ud ON ud.id = c.assigned_to
WHERE w.direction = 'inbound' AND w.dir_ant IS DISTINCT FROM 'inbound'
  AND NOT (w.thr = ANY(:teste))
"""

SQL_PENDENTES = f"""
-- RELÓGIO: SP. A lista VIVA: threads em que o lead falou e nenhuma mensagem nossa que não
-- seja template veio depois. Sem período: é agora.
-- `desde` delimita QUEM ENTRA (lead escreveu nos últimos N dias); a história da thread é
-- lida inteira e PELA CHAVE, não pelo wa_id: a resposta pode ter saído na outra grafia do
-- telefone, e "esperando há" tem de contar da pergunta, não do corte.
--
-- CUSTO: a chave é uma regex por linha, e calculá-la sobre as 39 mil mensagens custava
-- 190 ms dos 288. O pré-filtro `right(wa, 8)` (os últimos 8 dígitos, que a chave preserva)
-- é comparação de texto barata e corta para as mensagens das pessoas candidatas; o JOIN
-- final continua sendo pela chave, então o resultado é o mesmo.
-- MATERIALIZED nos dois: sem ele o planner empurra o predicado da chave para dentro da
-- varredura de `messages` e volta a calcular a regex nas 39 mil linhas (medido: 227 ms).
WITH cand AS MATERIALIZED (
  SELECT DISTINCT {CHAVE_MSG} AS thr FROM messages m
  WHERE m.direction = 'inbound' AND m.timestamp >= :desde
    AND NOT ({CHAVE_MSG} = ANY(:teste))
), mk AS MATERIALIZED (
  SELECT m.id, m.contact_wa_id AS wa, m.direction, m.message_type, m.timestamp AS ts,
         m.content, {CHAVE_MSG} AS thr
  FROM messages m
  WHERE right(m.contact_wa_id, 8) IN (SELECT right(thr, 8) FROM cand)
), k AS (
  SELECT mk.* FROM mk JOIN cand USING (thr)
), t AS (
  SELECT thr, max(ts) FILTER (WHERE direction = 'outbound' AND message_type <> 'template')
              AS ult_resp
  FROM k GROUP BY 1
), q AS (
  -- o que veio DEPOIS da última resposta de verdade: só mensagens do lead e templates
  SELECT k.* FROM k JOIN t USING (thr) WHERE t.ult_resp IS NULL OR k.ts > t.ult_resp
), o AS (
  SELECT thr, max(ts) FILTER (WHERE direction = 'outbound') AS ult_tpl,
         min(ts) FILTER (WHERE direction = 'inbound') AS primeira_sem_resposta
  FROM q GROUP BY 1
), agg AS (
  -- Só a ÚLTIMA pergunta: as mensagens do lead depois do último template. Se o template é a
  -- última mensagem da thread, o lead não falou por último e a conversa não entra na lista.
  SELECT q.thr, array_agg(q.ts ORDER BY q.ts) AS inbs, max(q.ts) AS ultimo_inb,
         o.ult_tpl, o.primeira_sem_resposta
  FROM q JOIN o USING (thr)
  WHERE q.direction = 'inbound' AND (o.ult_tpl IS NULL OR q.ts > o.ult_tpl)
  GROUP BY q.thr, o.ult_tpl, o.primeira_sem_resposta
), ult AS (
  SELECT DISTINCT ON (thr) thr, wa, content AS ultima_msg
  FROM q WHERE direction = 'inbound' ORDER BY thr, ts DESC, id DESC
)
SELECT agg.thr, ult.wa, agg.inbs, agg.ultimo_inb, ult.ultima_msg,
       agg.primeira_sem_resposta,
       -- recebeu só template: havia mensagem do lead sem resposta ANTES de um template nosso
       coalesce(agg.ult_tpl > agg.primeira_sem_resposta, false) AS so_template,
       c.name AS nome, c.assigned_to AS dono_id, u.name AS dono_nome
FROM agg JOIN ult USING (thr)
LEFT JOIN contacts c ON c.wa_id = ult.wa
LEFT JOIN users u ON u.id = c.assigned_to
"""

SQL_AGENTE_ATIVO = """
-- Estados do agente que o tornam DONO do inbound (qualificacao_fluxo.agente_e_dono).
SELECT contact_wa_id, etapa FROM nat_qualificacao_state WHERE etapa = ANY(:etapas)
"""

SQL_REGUA_VIVA = """
-- RELÓGIO: SP (slot_inicio). Régua viva: no-show em andamento, ou confirmação de reunião
-- Vigente e futura. Aproxima confirmacao._reuniao_dona sem a checagem da mensagem imediata
-- (aqui só se ROTULA a pendência; quem decide o roteamento é o webhook).
SELECT telefone_chave,
       CASE WHEN noshow_em IS NOT NULL THEN 'noshow' ELSE 'confirmacao' END AS regua
FROM reuniao_status
WHERE telefone_chave <> '' AND regua_encerrada_em IS NULL
  AND (noshow_em IS NOT NULL OR (exact_type = 'Vigente' AND slot_inicio > :agora))
"""


# ==========================================================================================
# AS REGRAS, EM FUNÇÕES PURAS
# ==========================================================================================
def segundos_expediente(a: datetime, b: datetime) -> float:
    """Segundos de [a, b] que caem dentro de 08h00 a 20h30, qualquer dia (feriado não é
    tratado, igual às réguas). Pergunta às 23h respondida às 8h30 vale 30 min."""
    if b <= a:
        return 0.0
    total = 0.0
    dia = a.date()
    while dia <= b.date():
        abre = datetime.combine(dia, JANELA_REGUA_INICIO)
        fecha = datetime.combine(dia, JANELA_REGUA_FIM)
        ini, fim = max(a, abre), min(b, fecha)
        if fim > ini:
            total += (fim - ini).total_seconds()
        dia += timedelta(days=1)
    return total


def estado_janela(ultimo_inb: datetime, agora: datetime) -> str:
    """`aberta` < 20 h <= `perto` < 24 h <= `expirada`, contados da ÚLTIMA mensagem do lead:
    é ela que abre a janela de 24 h na Meta, não a primeira da rajada."""
    idade = agora - ultimo_inb
    if idade >= JANELA_META:
        return "expirada"
    if idade >= LIMIAR_PERTO:
        return "perto"
    return "aberta"


@dataclass
class Pergunta:
    """Uma pergunta e o que aconteceu com ela, já com as regras aplicadas."""
    thr: str
    wa: str
    ts: datetime
    ultimo_inb: datetime
    ts_resp: datetime | None
    ts_tpl: datetime | None
    respondido_por: str | None        # 'ia' | 'time' | None
    dono: str                         # 'ia' | 'time'
    sent_by: int | None
    sent_by_nome: str | None
    dono_id: int | None
    dono_nome: str | None
    espera: float | None = None       # segundos, relógio corrido
    espera_exp: float | None = None   # segundos, só expediente
    extra: dict = field(default_factory=dict)


def montar(linha, fim: datetime) -> Pergunta:
    """Linha do `SQL_PERGUNTAS` -> `Pergunta`. `fim` só entra nas contas de vencimento."""
    respondido = None
    if linha["ts_resp"] is not None:
        respondido = "ia" if linha["etapa_resp"] else "time"
    dono = respondido or ("ia" if linha["etapa_antes"] else "time")
    p = Pergunta(thr=linha["thr"], wa=linha["wa"], ts=linha["ts"],
                 ultimo_inb=linha["ultimo_inb"] or linha["ts"], ts_resp=linha["ts_resp"],
                 ts_tpl=linha["ts_tpl"], respondido_por=respondido, dono=dono,
                 sent_by=linha["sent_by"], sent_by_nome=linha["sent_by_nome"],
                 dono_id=linha["dono_id"], dono_nome=linha["dono_nome"])
    if p.ts_resp is not None:
        p.espera = (p.ts_resp - p.ts).total_seconds()
        p.espera_exp = segundos_expediente(p.ts, p.ts_resp)
    return p


def filtrar(ps: list[Pergunta], quem: str, sdr: int | None) -> list[Pergunta]:
    if quem in ("time", "ia"):
        ps = [p for p in ps if p.dono == quem]
    if sdr is not None:
        ps = [p for p in ps if p.dono_id == sdr]
    return ps


def vencida(p: Pergunta, fim: datetime, expediente: bool) -> bool:
    """O prazo de 2 h desta pergunta já venceu em `fim`? Pergunta sem resposta há 10 min
    não é falha ainda: não entra no denominador do SLA."""
    if p.ts_resp is not None:
        return True
    corrido = segundos_expediente(p.ts, fim) if expediente else (fim - p.ts).total_seconds()
    return corrido > SLA.total_seconds()


def no_sla(p: Pergunta, expediente: bool) -> bool:
    e = p.espera_exp if expediente else p.espera
    return e is not None and e <= SLA.total_seconds()


def janela_perdida(p: Pergunta, fim: datetime) -> bool:
    """A janela de 24 h da Meta fechou sem resposta nossa (dentro do período)."""
    fecha = p.ultimo_inb + JANELA_META
    if fecha > fim:
        return False
    return p.ts_resp is None or p.ts_resp > fecha


def mediana(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def agregar(ps: list[Pergunta], fim: datetime) -> dict:
    """Os números de um conjunto de perguntas. Corrido e expediente lado a lado."""
    resp = [p for p in ps if p.ts_resp is not None]
    out: dict = {"perguntas": len(ps), "respondidas": len(resp),
                 "sem_resposta": len(ps) - len(resp),
                 "so_template": sum(1 for p in ps if p.ts_resp is None and p.ts_tpl),
                 "janelas_perdidas": sum(1 for p in ps if janela_perdida(p, fim)),
                 "por_ia": sum(1 for p in resp if p.respondido_por == "ia"),
                 "por_time": sum(1 for p in resp if p.respondido_por == "time")}
    for nome, exp in (("corrido", False), ("expediente", True)):
        venc = [p for p in ps if vencida(p, fim, exp)]
        dentro = sum(1 for p in venc if no_sla(p, exp))
        esperas = [p.espera_exp if exp else p.espera for p in resp]
        out[nome] = {"mediana": mediana(esperas), "no_sla": dentro,
                     "fora_sla": sum(1 for p in venc if p.ts_resp is not None and not no_sla(p, exp)),
                     "vencidas": len(venc),
                     "pct_sla": round(100 * dentro / len(venc), 1) if venc else None}
    return out


def histograma(ps: list[Pergunta], expediente: bool) -> list[dict]:
    contas = [0] * len(FAIXAS)
    for p in ps:
        e = p.espera_exp if expediente else p.espera
        if e is None:
            continue
        for i, (_, teto) in enumerate(FAIXAS):
            if teto is None or e <= teto:
                contas[i] += 1
                break
    return [{"faixa": f, "n": n} for (f, _), n in zip(FAIXAS, contas)]


def serie(ps: list[Pergunta], p: Periodo, granularidade: str) -> list[dict]:
    """Por dia do período (todos os dias, vazios inclusos) ou por hora do dia (0 a 23)."""
    if granularidade == "hora":
        chaves = list(range(24))
        chave = lambda x: x.ts.hour                                    # noqa: E731
    else:
        chaves, d = [], p.de.date()
        while d <= p.ate.date():
            chaves.append(d)
            d += timedelta(days=1)
        chave = lambda x: x.ts.date()                                  # noqa: E731
    grupos: dict = {k: [] for k in chaves}
    for x in ps:
        grupos.setdefault(chave(x), []).append(x)
    linhas = []
    for k in chaves:
        a = agregar(grupos[k], p.ate)
        linhas.append({"chave": k.isoformat() if isinstance(k, date) else k,
                       "perguntas": a["perguntas"], "sem_resposta": a["sem_resposta"],
                       "so_template": a["so_template"],
                       "corrido": a["corrido"], "expediente": a["expediente"]})
    return linhas


def variacao(atual, anterior) -> dict:
    """Seta e percentual prontos para o cartão. `None` quando não há base de comparação."""
    if atual is None or anterior is None:
        return {"anterior": anterior, "delta": None, "pct": None}
    delta = atual - anterior
    pct = round(100 * delta / anterior, 1) if anterior else None
    return {"anterior": anterior, "delta": round(delta, 1), "pct": pct}


def periodo_anterior(p: Periodo) -> Periodo:
    dur = p.ate - p.de
    return Periodo(p.de - dur, p.de, p.dias, f"anterior a {p.rotulo}")


# ==========================================================================================
# O PERÍODO
# ==========================================================================================
FIXOS_EXTRA = {"14d": 14, "90d": 90}


def janela_atendimento(periodo: str | None, de: str | None, ate: str | None) -> Periodo:
    """`relatorios.janela` com 14d e 90d a mais e `de`/`ate` livres. Mesmo relógio, mesmos
    rótulos: 7d e 30d passam direto por `janela`."""
    if de and ate:
        return janela(f"{de}:{ate}")
    periodo = (periodo or "30d").strip()
    if periodo in FIXOS_EXTRA:
        agora, dias = agora_sp(), FIXOS_EXTRA[periodo]
        ini = (agora - timedelta(days=dias)).replace(hour=0, minute=0, second=0, microsecond=0)
        return Periodo(ini, agora, dias, periodo)
    return janela(periodo)


def cobertura_sent_by(p: Periodo) -> dict:
    """O aviso de `/humano`, na mesma redação. Afeta só QUEM DO TIME respondeu."""
    if p.ate < CORTE_SENT_BY:
        conf, aviso = "nao_medivel", (
            "O período escolhido é inteiro anterior a 01/09/2026 16h, quando o sistema "
            "começou a gravar quem enviou cada mensagem. Respostas do time aparecem como "
            "'time, sem autor': o dado não existe, e não é zero.")
    elif p.de < CORTE_SENT_BY:
        conf, aviso = "indisponivel", (
            "Só dá para atribuir resposta a uma pessoa a partir de 01/09/2026, 16h. Antes "
            "disso as respostas do time aparecem como 'time, sem autor'.")
    else:
        conf, aviso = "alta", None
    return {"desde": CORTE_SENT_BY.isoformat(), "confianca": conf, "aviso": aviso}


# ==========================================================================================
# A LEITURA
# ==========================================================================================
async def perguntas(db: AsyncSession, p: Periodo, teste: list[str]) -> list[Pergunta]:
    linhas = (await db.execute(text(SQL_PERGUNTAS),
                               {"ini": p.de, "fim": p.ate, "teste": teste})).mappings().all()
    return [montar(l, p.ate) for l in linhas]


async def donos_automacao(db: AsyncSession, agora: datetime) -> tuple[dict, dict]:
    """`({chave: etapa}, {chave: régua})`. A chave tolerante casa as duas grafias."""
    agente = {}
    for r in (await db.execute(text(SQL_AGENTE_ATIVO),
                               {"etapas": list(ETAPAS_QUALIFICACAO_ATIVAS)})).all():
        k = chave_telefone(r.contact_wa_id)
        if k:
            agente[k] = r.etapa
    regua = {}
    for r in (await db.execute(text(SQL_REGUA_VIVA), {"agora": agora})).all():
        regua.setdefault(r.telefone_chave, r.regua)
    return agente, regua


def inicio_da_pergunta(inbs: list[datetime]) -> datetime:
    """De quando conta o "esperando há" da lista viva: a primeira mensagem da pergunta ATUAL.

    Pela definição, mensagens do lead sem nada nosso entre elas são uma pergunta só, mesmo
    com meses de distância. MEDIDO em 13/10: uma lead escreveu em 27/03, ninguém respondeu,
    e ela voltou em 08/10; a lista dizia "esperando há 4 804 h". Para quem vai responder,
    a pergunta é a de 08/10: quando o lead volta depois de mais de 24 h, a janela anterior
    já morreu e a conversa recomeça. A primeira sem resposta segue no JSON à parte."""
    inicio = inbs[-1]
    for anterior in reversed(inbs[:-1]):
        if inicio - anterior > JANELA_META:
            break
        inicio = anterior
    return inicio


def classificar_pendente(linha, agora: datetime, agente: dict, regua: dict) -> dict:
    """Uma pendência com dono, janela e anomalia. Pura: o teste não precisa de banco."""
    k = chave_telefone(linha["wa"])
    if k and k in agente:
        dono, detalhe = "agente", agente[k]
    elif k and k in regua:
        dono, detalhe = "regua", regua[k]
    else:
        dono, detalhe = "sdr", None
    desde = inicio_da_pergunta(linha["inbs"] or [linha["ultimo_inb"]])
    horas = (agora - desde).total_seconds() / 3600
    return {
        "wa_id": linha["wa"], "nome": linha["nome"],
        "dono_inbound": dono, "dono_detalhe": detalhe,
        "sdr_id": linha["dono_id"], "sdr_nome": linha["dono_nome"] or "sem dono",
        "esperando_desde": desde.isoformat(), "ultimo_inb": linha["ultimo_inb"].isoformat(),
        "horas_esperando": round(horas, 2),
        "janela": estado_janela(linha["ultimo_inb"], agora),
        "janela_fecha_em": (linha["ultimo_inb"] + JANELA_META).isoformat(),
        "ultima_msg": (linha["ultima_msg"] or "")[:200],
        "so_template": bool(linha["so_template"]),
        # A primeira mensagem do lead sem resposta de verdade (pode ser bem anterior: entre
        # ela e a pergunta atual só saiu template).
        "primeira_sem_resposta": (linha["primeira_sem_resposta"] or desde).isoformat(),
        # Dono automação há mais de 10 min sem resposta: o vigia do agente cobre; aqui só rotula.
        "anomalia": dono != "sdr" and (agora - linha["ultimo_inb"]) > ANOMALIA_AUTOMACAO,
    }


def filtrar_pendentes(itens: list[dict], quem: str, sdr: int | None,
                      min_horas: float) -> list[dict]:
    if quem == "time":
        itens = [i for i in itens if i["dono_inbound"] == "sdr"]
    elif quem == "ia":
        itens = [i for i in itens if i["dono_inbound"] != "sdr"]
    if sdr is not None:
        itens = [i for i in itens if i["sdr_id"] == sdr]
    itens = [i for i in itens if i["horas_esperando"] >= min_horas]
    return sorted(itens, key=lambda i: i["esperando_desde"])


async def pendentes_agora(db: AsyncSession, teste: list[str], dias: int) -> list[dict]:
    agora = agora_sp()
    linhas = (await db.execute(text(SQL_PENDENTES), {
        "desde": agora - timedelta(days=dias), "teste": teste})).mappings().all()
    agente, regua = await donos_automacao(db, agora)
    return [classificar_pendente(l, agora, agente, regua) for l in linhas]


# ==========================================================================================
# AS ROTAS
# ==========================================================================================
def tolerante(secao: str):
    """Mesmo contrato de `relatorios.tolerante`: 200 com `erro`, nunca um card vazio mudo."""
    def deco(fn):
        @wraps(fn)
        async def wrapper(*a, **kw):
            try:
                return await fn(*a, **kw)
            except HTTPException:
                raise
            except Exception as e:
                log.exception("atendimento/%s falhou", secao)
                return {"secao": secao, "periodo": None, "apurado_em": agora_sp().isoformat(),
                        "metricas": [],
                        "erro": {"tipo": type(e).__name__, "mensagem": str(e)[:300]}}
        return wrapper
    return deco


def _quem(quem: str) -> str:
    if quem not in QUEM:
        raise HTTPException(400, "quem deve ser time, ia ou ambos.")
    return quem


DEF_PERGUNTA = ("Pergunta é a mensagem do lead que vem depois de uma nossa (ou abre a "
                "conversa); várias mensagens seguidas do lead contam uma vez. Resposta é a "
                "primeira mensagem nossa depois dela que NÃO é template.")
LIM_TEMPLATE = ("Template depois da pergunta (disparo em massa, follow) não conta como "
                "resposta. Ligação também não: só mensagem de WhatsApp entra.")
LIM_DONO = ("Quem era responsável por responder é inferido: respondida, vale quem "
            "respondeu; sem resposta, é da automação se a última mensagem nossa antes dela "
            "era do agente ou da régua, senão é do time. O SDR é o dono ATUAL do contato.")


@router.get("/resumo")
@tolerante("resumo")
async def resumo(periodo: str = Query("30d"), de: str | None = None, ate: str | None = None,
                 sdr: int | None = None, quem: str = "time",
                 db: AsyncSession = Depends(get_db)):
    """Os 5 cartões, cada um com o valor do período anterior de mesma duração."""
    quem = _quem(quem)
    p = janela_atendimento(periodo, de, ate)
    teste = await chaves_de_teste(db)
    ant = periodo_anterior(p)
    atual = filtrar(await perguntas(db, p, teste.array), quem, sdr)
    antes = filtrar(await perguntas(db, ant, teste.array), quem, sdr)
    a, b = agregar(atual, p.ate), agregar(antes, ant.ate)
    pend = filtrar_pendentes(await pendentes_agora(db, teste.array, PENDENTES_DIAS),
                             quem, sdr, 0)
    cob = cobertura_sent_by(p)

    def sla_val(x: dict) -> dict:
        return {k: x[k]["pct_sla"] for k in ("corrido", "expediente")}

    taxa = round(100 * a["respondidas"] / a["perguntas"], 1) if a["perguntas"] else None
    taxa_ant = round(100 * b["respondidas"] / b["perguntas"], 1) if b["perguntas"] else None
    return envelope("atendimento_resumo", p, [
        metrica("sem_resposta_agora", "Sem resposta agora", len(pend), n=None,
                relogio=_R_SP, confianca="alta", unidade="conversas",
                definicao="Conversas em que o lead falou por último nos últimos "
                          f"{PENDENTES_DIAS} dias e nenhuma mensagem nossa que não seja "
                          "template veio depois. Não depende do período: é agora.",
                limitacao=MOVEL,
                por_janela={j: sum(1 for i in pend if i["janela"] == j)
                            for j in ("aberta", "perto", "expirada")},
                ignora_periodo=True),
        metrica("mediana", "Tempo de resposta (mediana)",
                {k: a[k]["mediana"] for k in ("corrido", "expediente")}, n=a["respondidas"],
                relogio=_R_SP, confianca="media", unidade="segundos",
                definicao=DEF_PERGUNTA + " Mediana do tempo entre as duas. 'Expediente' só "
                          "conta o relógio entre 8h e 20h30.",
                limitacao=LIM_TEMPLATE,
                variacao={k: variacao(a[k]["mediana"], b[k]["mediana"])
                          for k in ("corrido", "expediente")}),
        metrica("pct_sla", "Respondidas em até 2 h", sla_val(a),
                n={k: a[k]["vencidas"] for k in ("corrido", "expediente")},
                relogio=_R_SP, confianca="media", unidade="%",
                definicao="Das perguntas cujo prazo de 2 h já venceu (ou que já foram "
                          "respondidas), quantas tiveram resposta em até 2 h. Pergunta de "
                          "agora há pouco ainda não entra na conta.",
                limitacao="No relógio corrido, pergunta às 23h respondida às 8h30 é falha. "
                          "No de expediente (8h a 20h30, todo dia, feriado não tratado) "
                          "ela levou 30 min. " + LIM_TEMPLATE,
                detalhe={k: a[k] for k in ("corrido", "expediente")},
                variacao={k: variacao(a[k]["pct_sla"], b[k]["pct_sla"])
                          for k in ("corrido", "expediente")}),
        metrica("janelas_perdidas", "Janelas de 24 h perdidas", a["janelas_perdidas"],
                n=a["perguntas"], relogio=_R_SP, confianca="alta", unidade="perguntas",
                definicao="Perguntas do período em que passaram 24 h desde a última "
                          "mensagem do lead sem resposta nossa. Depois disso só dá para "
                          "falar com ele por template pago.",
                limitacao="Conta cada pergunta, não cada pessoa: quem perdeu a janela duas "
                          "vezes no período conta duas. " + LIM_TEMPLATE,
                variacao=variacao(a["janelas_perdidas"], b["janelas_perdidas"])),
        metrica("taxa_resposta", "Taxa de resposta", taxa, n=a["perguntas"],
                relogio=_R_SP, confianca="media", unidade="%",
                definicao="Perguntas do período que receberam resposta até o fim do "
                          "período, em qualquer tempo.",
                limitacao=(f"{a['so_template']} pergunta(s) receberam só template e contam "
                           "como sem resposta. " + MOVEL),
                variacao=variacao(taxa, taxa_ant)),
    ], teste, filtros={"quem": quem, "sdr": sdr}, periodo_anterior=ant.json(),
        cobertura_sent_by=cob, nota_dono=LIM_DONO,
        respondidas_por={"ia": a["por_ia"], "time": a["por_time"]},
        histograma={"corrido": histograma(atual, False),
                    "expediente": histograma(atual, True)})


@router.get("/serie")
@tolerante("serie")
async def serie_rota(periodo: str = Query("30d"), de: str | None = None,
                     ate: str | None = None, granularidade: str = "dia",
                     sdr: int | None = None, quem: str = "time",
                     db: AsyncSession = Depends(get_db)):
    if granularidade not in ("dia", "hora"):
        raise HTTPException(400, "granularidade deve ser dia ou hora.")
    quem = _quem(quem)
    p = janela_atendimento(periodo, de, ate)
    teste = await chaves_de_teste(db)
    ps = filtrar(await perguntas(db, p, teste.array), quem, sdr)
    return envelope("atendimento_serie", p, [], teste, granularidade=granularidade,
                    filtros={"quem": quem, "sdr": sdr}, linhas=serie(ps, p, granularidade),
                    definicao=DEF_PERGUNTA,
                    nota=("Por hora do dia: hora em que o lead perguntou, somando todos os "
                          "dias do período." if granularidade == "hora" else
                          "Dia em que o lead perguntou. Resposta procurada até o fim do "
                          "período."))


@router.get("/sdr")
@tolerante("sdr")
async def por_sdr(periodo: str = Query("30d"), de: str | None = None, ate: str | None = None,
                  db: AsyncSession = Depends(get_db)):
    """Uma linha por dono do contato. Só perguntas do time: a automação não é de SDR."""
    p = janela_atendimento(periodo, de, ate)
    teste = await chaves_de_teste(db)
    ps = filtrar(await perguntas(db, p, teste.array), "time", None)
    pend = filtrar_pendentes(await pendentes_agora(db, teste.array, PENDENTES_DIAS),
                             "time", None, 0)
    grupos: dict = {}
    for x in ps:
        grupos.setdefault((x.dono_id, x.dono_nome or "sem dono"), []).append(x)
    agora_por: dict = {}
    for i in pend:
        agora_por[i["sdr_id"]] = agora_por.get(i["sdr_id"], 0) + 1
    linhas = []
    for (sid, nome), xs in grupos.items():
        a = agregar(xs, p.ate)
        linhas.append({"sdr_id": sid, "sdr": nome, "perguntas": a["perguntas"],
                       "respondidas": a["respondidas"],
                       "respondeu_pessoalmente": sum(1 for x in xs if x.sent_by == sid
                                                     and sid is not None),
                       "janelas_perdidas": a["janelas_perdidas"],
                       "corrido": a["corrido"], "expediente": a["expediente"],
                       "sem_resposta_agora": agora_por.get(sid, 0)})
    for sid in set(agora_por) - {l["sdr_id"] for l in linhas}:
        nome = next(i["sdr_nome"] for i in pend if i["sdr_id"] == sid)
        linhas.append({"sdr_id": sid, "sdr": nome, "perguntas": 0, "respondidas": 0,
                       "respondeu_pessoalmente": 0, "janelas_perdidas": 0,
                       "corrido": agregar([], p.ate)["corrido"],
                       "expediente": agregar([], p.ate)["expediente"],
                       "sem_resposta_agora": agora_por[sid]})
    linhas.sort(key=lambda l: -l["perguntas"])
    return envelope("atendimento_sdr", p, [], teste, linhas=linhas,
                    cobertura_sent_by=cobertura_sent_by(p), nota_dono=LIM_DONO,
                    definicao=("Perguntas atribuídas = perguntas do time em contatos de "
                               "que a pessoa é dona hoje. 'Respondeu pessoalmente' só "
                               "existe a partir de 01/09/2026 16h."))


@router.get("/pendentes")
@tolerante("pendentes")
async def pendentes(quem: str = "time", sdr: int | None = None, min_horas: float = 0,
                    dias: int = Query(PENDENTES_DIAS, ge=1, le=30),
                    db: AsyncSession = Depends(get_db)):
    quem = _quem(quem)
    teste = await chaves_de_teste(db)
    todos = await pendentes_agora(db, teste.array, dias)
    itens = filtrar_pendentes(todos, quem, sdr, min_horas)
    return {"secao": "atendimento_pendentes", "apurado_em": agora_sp().isoformat(),
            "periodo": None, "filtros": {"quem": quem, "sdr": sdr, "min_horas": min_horas,
                                         "dias": dias},
            "total": len(itens),
            "por_janela": {j: sum(1 for i in itens if i["janela"] == j)
                           for j in ("aberta", "perto", "expirada")},
            "ocultos_automacao": sum(1 for i in todos if i["dono_inbound"] != "sdr")
            if quem == "time" else 0,
            "itens": itens,
            "leads_de_teste": {"excluidos": len(teste.excluir)},
            "definicao": (f"Conversas em que o lead escreveu nos últimos {dias} dias e "
                          "nenhuma mensagem nossa que não seja template veio depois. "
                          "Janela: aberta até 20 h desde a última mensagem dele, perto "
                          "de 20 h a 24 h, expirada depois de 24 h.")}
