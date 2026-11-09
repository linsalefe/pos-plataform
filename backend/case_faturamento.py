"""Case "faturamento atribuível ao agente": vendas por ORIGEM DA REUNIÃO (09/11/2026).

    cd backend && venv/bin/python case_faturamento.py --de 2026-09-07 --ate 2026-11-08 \
        --cache /caminho/leadssold.json
    cd backend && venv/bin/python case_faturamento.py --de 2026-08-27 --ate 2026-11-08 ...

SOMENTE LEITURA: só SELECT (transação READ ONLY) e `GET /v3/LeadsSold` na Exact. Nenhuma
escrita, nenhum envio pela Meta. Relatório: CASE_FATURAMENTO_AGENTE_20261109.md.

PERÍODO em datas de SP, as duas pontas inclusive. Relógios: `agendamentos.created_at`,
`reuniao_status.registrado_em`/`slot_inicio` e `messages.timestamp` são SP naive;
`LeadsSold.saleDate` é UTC de verdade (convertido aqui).

⚠️ `agendamentos.created_at` é SP, NÃO UTC, apesar do comentário de
`relatorios.SQL_JORNADA_COORTE`: medido em 09/11, 322 de 322 agendamentos com `meeting_id`
batem na hora com `registerDate` da Exact convertido para SP (diferença 0 h). Somar 3 h aqui
punha a marcação do agente ANTES da abertura que a originou.

AS DEFINIÇÕES (aprovadas no checkpoint 1.5 do recon):
  marcação     `agendamentos` com passo='agendado' (created_at) e `reuniao_status` com
               origem='exact' (registrado_em). Vale a PRIMEIRA marcação do lead; as demais
               no período são remarcação e só entram na contagem de remarcações.
  ia           primeira marcação é agendamento sem `origem_ip` (feito pelo agente)
  landing_page primeira marcação é agendamento com `origem_ip` (a pessoa no site)
  sdr_exact    primeira marcação é reunião marcada na Exact, em lead SEM `passo='agendado'`
               anterior. Inclui quem aplicou na LP (`lead_criado`/`falhou`) e não marcou.
               Dividida pelo toque do agente: alguma saída de conversa/abertura/Fluxo B para
               o telefone antes da marcação = "assistida pelo agente".
  concluída    alguma reunião `Concluido` no espelho com horário >= dia da marcação
  vendido      `exact_leads.stage='Vendidos'` HOJE e uma venda em `LeadsSold` com
               saleDate >= marcação. Vendido sem venda posterior = "venda antes da marcação".
  faturamento  `LeadsSold.totalDealValue` dessa venda (a primeira com saleDate >= marcação).
               0/nulo ou sem linha em LeadsSold = "sem valor informado", fora da soma.

Leads de teste: fora de tudo, pela regra de /relatorios (`relatorios.chaves_de_teste`).
"""
import argparse
import asyncio
import json
import os
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import text

from app.agendamento.client import _req
from app.database import async_session
from app.relatorios import (ABERTURA_T1, ABERTURA_T2, ABERTURA_T3,
                            N_MINIMO_TAXA, chaves_de_teste, metrica, thread_sql)
from app.telefone import chave_telefone

# Funis de pós. 18285 (Intercâmbio) e 20776 (Congresso) ficam fora.
FUNIS_POS = (18535, 18537, 21007, 25588)
# O espelho `reuniao_status` só tem reunião com horário a partir daqui (carga inicial).
INICIO_ESPELHO = date(2026, 9, 7)
# Pausa do agente (start_at=2099): 17/09 a 27/09 18:27 UTC.
PAUSA = (date(2026, 9, 17), date(2026, 9, 27))
# O que conta como "o agente falou com essa pessoa". Confirmação e no-show ficam de fora: elas
# só saem DEPOIS de uma reunião, não levam ninguém até ela.
ETAPAS_AGENTE = ("qualif_conversa", ABERTURA_T1, ABERTURA_T2, ABERTURA_T3)
PREFIXO_FLUXO_B = "nat_b_%"

ORIGENS = ("ia", "landing_page", "sdr_sem_agente", "sdr_com_agente")
ROTULO = {"ia": "ia (marcada pelo agente)",
          "landing_page": "landing_page (a pessoa no site)",
          "sdr_sem_agente": "sdr_exact sem toque do agente",
          "sdr_com_agente": "sdr_exact assistida pelo agente",
          "sem_reuniao": "venda sem reunião nossa"}
_R = "SP (marcação) · UTC (stage e saleDate, lidos hoje)"


def sp(utc_iso: str) -> datetime:
    """`saleDate` da Exact (UTC, 7 casas) -> SP naive."""
    return datetime.fromisoformat(utc_iso[:19]) - timedelta(hours=3)


def brl(v) -> str:
    if v is None:
        return "não medível"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(n: int, d: int) -> str:
    """Taxa só com denominador >= N_MINIMO_TAXA; abaixo, a contagem e o motivo."""
    if d < N_MINIMO_TAXA:
        return f"{n} de {d} (N < {N_MINIMO_TAXA}, sem taxa)"
    return f"{100 * n / d:.1f}% ({n}/{d})"


async def leads_sold(cache: str | None) -> list[dict]:
    """`GET /LeadsSold` inteiro, paginado por `$skip` até vazio. 4 páginas hoje, e mais
    barato que um GET por lead. Com `--cache`, lê do arquivo se existir e grava se não."""
    if cache and os.path.exists(cache):
        return json.load(open(cache))
    tudo, skip = [], 0
    while True:
        v = (await _req("GET", "/LeadsSold", params={"$top": 500, "$skip": skip},
                        timeout=60)).json().get("value", [])
        if not v:
            break
        tudo += v
        skip += 500
        await asyncio.sleep(1)      # cota 30 req/20 s dividida com os syncs
    if cache:
        json.dump(tudo, open(cache, "w"))
    return tudo


def venda_apos(vendas: list[dict], marcacao: datetime) -> dict | None:
    """A primeira venda com saleDate >= marcação (no DIA: saleDate às vezes é só data)."""
    depois = [x for x in vendas if sp(x["saleDate"]).date() >= marcacao.date()]
    return min(depois, key=lambda x: x["saleDate"]) if depois else None


async def coletar(db, de: date, ate: date, sold: list[dict]) -> dict:
    ini = datetime.combine(de, datetime.min.time())
    fim = datetime.combine(ate, datetime.max.time())
    teste = (await chaves_de_teste(db)).excluir

    def real(tel) -> bool:
        return chave_telefone(tel) not in teste

    def thr(tel) -> str:
        return chave_telefone(tel) or "".join(c for c in (tel or "") if c.isdigit())

    async def q(sql, **kw):
        return (await db.execute(text(sql), kw)).all()

    ags = await q("""SELECT id, lead_id, telefone, origem_ip IS NULL AS ia,
                            created_at AS em, sales_rep_email, slot_inicio
                     FROM agendamentos WHERE passo = 'agendado' AND lead_id IS NOT NULL""")
    # Qualquer passo: para saber se a pessoa APLICOU na LP antes de o agente marcar.
    aplic = await q("""SELECT lead_id, min(created_at) AS em
                       FROM agendamentos WHERE passo IN ('lead_criado','falhou','recusado')
                         AND lead_id IS NOT NULL GROUP BY 1""")
    reunioes = await q("""SELECT meeting_id, lead_id, telefone_bruto, registrado_em, slot_inicio,
                                 exact_type, origem, sales_rep_email
                          FROM reuniao_status WHERE lead_id IS NOT NULL""")
    leads = {r.exact_id: r for r in await q(
        "SELECT exact_id, stage, funnel_id, phone1 FROM exact_leads")}
    estados = {r.agendamento_id: r for r in await q(
        """SELECT agendamento_id, origem, dados_extras->>'fluxo' AS fluxo
           FROM nat_qualificacao_state WHERE agendamento_id IS NOT NULL""")}
    toques = defaultdict(list)          # thr -> [(quando, etapa)] das falas do agente
    for r in await q(f"""SELECT {thread_sql('m.contact_wa_id')} AS thr, m.timestamp AS quando,
                                m.nat_etapa AS etapa
                         FROM messages m WHERE m.direction = 'outbound'
                           AND (m.nat_etapa = ANY(:et) OR m.nat_etapa LIKE :fb)""",
                     et=list(ETAPAS_AGENTE), fb=PREFIXO_FLUXO_B):
        toques[r.thr].append((r.quando, r.etapa))

    por_lead_sold = defaultdict(list)
    for x in sold:
        por_lead_sold[x["leadId"]].append(x)
    aplicou_em = {r.lead_id: r.em for r in aplic}
    espelho = defaultdict(list)
    for r in reunioes:
        espelho[r.lead_id].append(r)

    marcacoes = defaultdict(list)       # lead -> [(em, origem_bruta, consultora, agendamento)]
    for a in ags:
        if real(a.telefone):
            marcacoes[a.lead_id].append((a.em, "ia" if a.ia else "landing_page",
                                         a.sales_rep_email, a.id))
    for r in reunioes:
        if r.origem == "exact" and real(r.telefone_bruto):
            marcacoes[r.lead_id].append((r.registrado_em, "sdr_exact", r.sales_rep_email, None))

    coorte, fora = {}, Counter()
    for lid, ms in marcacoes.items():
        ms.sort(key=lambda m: m[0])
        em, origem, consultora, ag_id = ms[0]
        no_periodo = [m for m in ms if ini <= m[0] <= fim]
        if not no_periodo:
            continue
        if not ini <= em <= fim:
            fora["primeira marcação antes do período (remarcação de reunião antiga)"] += 1
            continue
        lead = leads.get(lid)
        if lead is None:
            fora["lead não existe mais no espelho exact_leads"] += 1
            continue
        if lead.funnel_id not in FUNIS_POS:
            fora[f"funil fora da pós ({lead.funnel_id})"] += 1
            continue
        fala = sorted(t for t in toques.get(thr(lead.phone1), []) if t[0] <= em)
        if origem == "sdr_exact":
            origem = "sdr_com_agente" if fala else "sdr_sem_agente"
        c = dict(lead_id=lid, origem=origem, em=em, consultora=consultora or "(sem consultora)",
                 remarcacoes=len(no_periodo) - 1, stage=lead.stage, funil=lead.funnel_id,
                 concluida=any(m.exact_type == "Concluido" and m.slot_inicio.date() >= em.date()
                               for m in espelho[lid]),
                 espelho=any(m.slot_inicio.date() >= INICIO_ESPELHO for m in espelho[lid])
                 or em.date() >= INICIO_ESPELHO,
                 aplicou_lp_antes=lid in aplicou_em and aplicou_em[lid] <= em,
                 roteiro=None, fluxo=None, venda=None, motivo_sem_venda=None)
        if origem == "ia":
            etapas = {e for _, e in fala}
            c["roteiro"] = ("fluxo_b" if any(e.startswith("nat_b_") for e in etapas) else
                            "t3" if ABERTURA_T3 in etapas else
                            "t1_t2" if etapas & {ABERTURA_T1, ABERTURA_T2} else "só conversa")
            st = estados.get(ag_id)
            c["fluxo"] = ("b" if st and st.fluxo == "b" else
                          (f"qualificação ({st.origem})" if st else "sem estado"))
        if lead.stage == "Vendidos":
            v = venda_apos(por_lead_sold.get(lid, []), em)
            if not por_lead_sold.get(lid):
                c["motivo_sem_venda"] = "Vendidos sem linha em LeadsSold"
            elif v is None:
                c["motivo_sem_venda"] = "venda antes da marcação"
            else:
                c["venda"] = dict(data=sp(v["saleDate"]), valor=v["totalDealValue"] or None,
                                  closer=(v.get("salesRep") or {}).get("email"),
                                  ciclo=v["cycle"])
        coorte[lid] = c

    # Vendas com saleDate no período, em funil de pós, de lead sem NENHUMA marcação nossa.
    sem_reuniao, marc_fora = [], 0
    for lid, vs in por_lead_sold.items():
        lead = leads.get(lid)
        if not lead or lead.funnel_id not in FUNIS_POS or not real(lead.phone1):
            continue
        no_per = sorted((x for x in vs if ini <= sp(x["saleDate"]) <= fim),
                        key=lambda x: x["saleDate"])
        if not no_per or lid in coorte:
            continue
        if lid in marcacoes:
            marc_fora += 1
            continue
        sem_reuniao.append(dict(lead_id=lid, stage=lead.stage, data=sp(no_per[0]["saleDate"]),
                                valor=no_per[0]["totalDealValue"] or None))

    # 2.5: vendas FECHADAS no período (saleDate), qualquer coorte, funis de pós.
    fechadas = []
    for lid, vs in por_lead_sold.items():
        lead = leads.get(lid)
        if not lead or lead.funnel_id not in FUNIS_POS or not real(lead.phone1):
            continue
        for x in vs:
            if ini <= sp(x["saleDate"]) <= fim:
                o = coorte[lid]["origem"] if lid in coorte else (
                    "marcação fora do período" if lid in marcacoes else "sem_reuniao")
                fechadas.append(dict(lead_id=lid, origem=o, valor=x["totalDealValue"] or None,
                                     mes=sp(x["saleDate"]).strftime("%Y-%m")))

    return dict(coorte=coorte, fora=fora, sem_reuniao=sem_reuniao, marc_fora=marc_fora,
                fechadas=fechadas, n_teste=len(teste), ini=ini, fim=fim)


def resumo(cs: list[dict]) -> dict:
    # Vendido = Vendidos hoje, tirando a venda anterior à marcação. Sem linha em LeadsSold
    # continua vendido: entra como "sem valor informado" (decisão 3).
    vend = [c for c in cs if c["venda"]
            or c["motivo_sem_venda"] == "Vendidos sem linha em LeadsSold"]
    com_valor = [c["venda"]["valor"] for c in vend if c["venda"] and c["venda"]["valor"]]
    conc = [c for c in cs if c["concluida"]]
    dias = [(c["venda"]["data"] - c["em"]).total_seconds() / 86400 for c in vend if c["venda"]]
    return dict(n=len(cs), concluidas=len(conc), vendidos=len(vend),
                com_valor=len(com_valor), sem_valor=len(vend) - len(com_valor),
                faturamento=sum(com_valor) if com_valor else None,
                ticket=(sum(com_valor) / len(com_valor)) if com_valor else None,
                vend_conc=sum(1 for c in conc if c in vend),
                vend_sem_conc=sum(1 for c in vend if not c["concluida"]),
                remarcaram=sum(1 for c in cs if c["remarcacoes"]),
                antes=sum(1 for c in cs if c["motivo_sem_venda"] == "venda antes da marcação"),
                sem_sold=sum(1 for c in cs
                             if c["motivo_sem_venda"] == "Vendidos sem linha em LeadsSold"),
                ate_1_dia=sum(1 for d in dias if d <= 1),
                mediana_dias=statistics.median(dias) if dias else None,
                sem_espelho=sum(1 for c in cs if not c["espelho"]))


def tabelas(d: dict, de: date, ate: date) -> None:
    co = list(d["coorte"].values())
    por = {o: [c for c in co if c["origem"] == o] for o in ORIGENS}
    R = {o: resumo(por[o]) for o in ORIGENS}
    sr = d["sem_reuniao"]
    sr_val = [x["valor"] for x in sr if x["valor"]]
    so_agente = de < INICIO_ESPELHO

    print(f"# Período {de:%d/%m/%Y} a {ate:%d/%m/%Y} (SP, as duas pontas)")
    print(f"\nPausa do agente {PAUSA[0]:%d/%m} a {PAUSA[1]:%d/%m}: zero marcações `ia` nela.")
    if so_agente:
        print(f"\n⚠️ Começa antes de {INICIO_ESPELHO:%d/%m}: o espelho de reuniões não cobre o "
              "início, então `sdr_exact` NÃO é comparável e `concluídas` é parcial.")
    print(f"\nLeads de teste: {d['n_teste']} chave(s) fora. Fora da coorte: "
          f"{dict(d['fora']) or 'nenhum'}. Venda no período de lead cuja marcação foi antes "
          f"do período: {d['marc_fora']} (fora de todas as linhas).")

    print("\n## 2.2 Tabela principal (coorte = primeira marcação no período; venda até hoje)\n")
    print("| origem | reuniões (leads) | concluídas | vendidos | com valor | faturamento | "
          "ticket médio | reunião→venda | concluída→venda |")
    print("|---|---|---|---|---|---|---|---|---|")
    tot = Counter()
    for o in ORIGENS:
        r = R[o]
        sdr = o.startswith("sdr_")
        conc = ("não comparável (espelho só desde 07/09)" if so_agente and sdr else
                f"{r['concluidas']}" + (f" ({r['sem_espelho']} sem espelho)"
                                        if r["sem_espelho"] else ""))
        taxa_r = pct(r["vendidos"], r["n"]) if o in ("ia", "landing_page") else "contagem só"
        taxa_c = pct(r["vend_conc"], r["concluidas"]) if o in ("ia", "landing_page") \
            else "contagem só"
        print(f"| {ROTULO[o]} | {r['n']} | {conc} | {r['vendidos']} | {r['com_valor']} | "
              f"{brl(r['faturamento'])} | {brl(r['ticket'])} | {taxa_r} | {taxa_c} |")
        for k in ("n", "concluidas", "vendidos", "com_valor"):
            tot[k] += r[k]
        tot["fat"] += r["faturamento"] or 0
    print(f"| {ROTULO['sem_reuniao']} | não se aplica | não se aplica | {len(sr)} | "
          f"{len(sr_val)} | {brl(sum(sr_val) if sr_val else None)} | "
          f"{brl(sum(sr_val) / len(sr_val) if sr_val else None)} | não se aplica | "
          f"não se aplica |")
    fat_tot = tot["fat"] + sum(sr_val)
    print(f"| **total** | {tot['n']} | {tot['concluidas']} | {tot['vendidos'] + len(sr)} | "
          f"{tot['com_valor'] + len(sr_val)} | {brl(fat_tot)} | "
          f"{brl(fat_tot / (tot['com_valor'] + len(sr_val)))} | | |")

    print("\nDetalhe por linha:\n")
    for o in ORIGENS:
        r = R[o]
        print(f"- {ROTULO[o]}: {r['remarcaram']} remarcaram (fora da atribuição); "
              f"{r['sem_valor']} vendido(s) sem valor informado; {r['sem_sold']} em Vendidos "
              f"sem linha em LeadsSold; {r['antes']} venda(s) antes da marcação (fora); "
              f"{r['vend_sem_conc']} vendido(s) sem reunião Concluido no espelho; "
              f"{r['ate_1_dia']} venda(s) em até 1 dia da marcação; mediana marcação→venda "
              + (f"{r['mediana_dias']:.1f} dias" if r["mediana_dias"] is not None
                 else "não medível"))
    print(f"- venda sem reunião nossa: {sum(1 for x in sr if x['stage'] != 'Vendidos')} "
          f"com stage diferente de Vendidos hoje; {len(sr) - len(sr_val)} sem valor.")

    print("\n## Três leituras do faturamento (nunca somar a e b como \"do agente\")\n")
    print(f"- (a) direto do agente (ia): {brl(R['ia']['faturamento'])} em "
          f"{R['ia']['com_valor']} venda(s)")
    print(f"- (b) assistido pelo agente (SDR marcou depois de o agente falar): "
          f"{brl(R['sdr_com_agente']['faturamento'])} em {R['sdr_com_agente']['com_valor']}")
    print(f"- (c) total do período, todas as origens: {brl(fat_tot)} em "
          f"{tot['com_valor'] + len(sr_val)}")

    ia = por["ia"]
    print("\n## Natureza da coorte ia\n")
    print(f"- aplicaram na LP (lead_criado/falhou/recusado) ANTES de o agente marcar: "
          f"{sum(c['aplicou_lp_antes'] for c in ia)} de {len(ia)}")
    print(f"- estado do agente: {dict(Counter(c['fluxo'] for c in ia))}")
    lp_perdeu = resumo([c for c in ia if c["aplicou_lp_antes"]])
    abordados = resumo([c for c in ia if not c["aplicou_lp_antes"]])
    print(f"- a LP perdeu e o agente recuperou: {lp_perdeu['n']} leads, "
          f"{lp_perdeu['vendidos']} vendidos, {brl(lp_perdeu['faturamento'])}")
    print(f"- lead da Exact abordado pelo agente (não aplicou na LP antes): {abordados['n']} "
          f"leads, {abordados['vendidos']} vendidos, {brl(abordados['faturamento'])}")
    print(f"- vendidos entre os que aplicaram na LP antes: "
          f"{sum(1 for c in ia if c['aplicou_lp_antes'] and c['venda'])}")

    print("\n## 2.3 Consultora da primeira marcação × origem\n")
    print("| consultora | origem | leads | concluídas | vendidos | faturamento | "
          "reunião→venda |")
    print("|---|---|---|---|---|---|---|")
    grupos = defaultdict(list)
    for c in co:
        grupos[(c["consultora"], c["origem"])].append(c)
    for (cons, o), cs in sorted(grupos.items()):
        r = resumo(cs)
        print(f"| {cons} | {ROTULO[o]} | {r['n']} | {r['concluidas']} | {r['vendidos']} | "
              f"{brl(r['faturamento'])} | {pct(r['vendidos'], r['n'])} |")
    dif = sum(1 for c in co if c["venda"] and c["venda"]["closer"]
              and c["venda"]["closer"].lower() != c["consultora"].lower())
    print(f"\nVendas em que quem fechou (LeadsSold.salesRep) não é a consultora da marcação: "
          f"{dif}.")

    print("\n## 2.4 Agente por mês da marcação (contagem; taxa só com N >= 30)\n")
    print("| mês | marcações ia | concluídas | vendidos | faturamento | reunião→venda |")
    print("|---|---|---|---|---|---|")
    meses = defaultdict(list)
    for c in ia:
        meses[c["em"].strftime("%Y-%m")].append(c)
    for m in sorted(meses):
        r = resumo(meses[m])
        nota = " (pausa 17 a 27/09)" if m == "2026-09" else ""
        conc = f"{r['concluidas']}" + (f" ({r['sem_espelho']} sem espelho)"
                                       if r["sem_espelho"] else "")
        print(f"| {m}{nota} | {r['n']} | {conc} | {r['vendidos']} | {brl(r['faturamento'])} | "
              f"{pct(r['vendidos'], r['n'])} |")

    print("\n## 2.5 Vendas FECHADAS no período (LeadsSold.saleDate), por origem e mês\n")
    print("| origem | vendas | com valor | faturamento |")
    print("|---|---|---|---|")
    fo = defaultdict(list)
    for x in d["fechadas"]:
        fo[x["origem"]].append(x)
    for o in list(ORIGENS) + ["sem_reuniao", "marcação fora do período"]:
        xs = fo.get(o, [])
        v = [x["valor"] for x in xs if x["valor"]]
        print(f"| {ROTULO.get(o, o)} | {len(xs)} | {len(v)} | "
              f"{brl(sum(v) if v else None)} |")
    tv = [x["valor"] for x in d["fechadas"] if x["valor"]]
    print(f"| **total** | {len(d['fechadas'])} | {len(tv)} | {brl(sum(tv) if tv else None)} |")
    pm = defaultdict(list)
    for x in d["fechadas"]:
        pm[x["mes"]].append(x)
    print("\nPor mês da venda: " + "; ".join(
        f"{m}: {len(xs)} vendas, {brl(sum(x['valor'] for x in xs if x['valor']))}"
        for m, xs in sorted(pm.items())))

    print("\n## 2.6 Coorte ia por roteiro de abertura do agente\n")
    print("| roteiro | leads | vendidos | faturamento |")
    print("|---|---|---|---|")
    rot = defaultdict(list)
    for c in ia:
        rot[c["roteiro"]].append(c)
    for k, cs in sorted(rot.items()):
        r = resumo(cs)
        print(f"| {k} | {r['n']} | {r['vendidos']} | {brl(r['faturamento'])} |")

    # O contrato de /relatorios: valor, N, relógio, confiança, definição.
    print("\n## Métricas no contrato `relatorios.metrica`\n")
    ms = [
        metrica("fat_ia", "Faturamento direto do agente", R["ia"]["faturamento"],
                n=R["ia"]["com_valor"], relogio=_R, confianca="media",
                definicao="Soma de LeadsSold.totalDealValue dos leads cuja primeira reunião "
                          "no período foi marcada pelo agente e que estão em Vendidos hoje, "
                          "com venda na data da marcação ou depois.",
                limitacao="O agente marca; quem fecha é a consultora."),
        metrica("fat_assistido", "Faturamento assistido pelo agente",
                R["sdr_com_agente"]["faturamento"], n=R["sdr_com_agente"]["com_valor"],
                relogio=_R, confianca="baixa",
                definicao="Mesma soma, para leads em que a SDR marcou na Exact depois de o "
                          "agente ter falado com a pessoa.",
                limitacao="Não diz quanto o agente pesou; nunca somar com o direto."),
        metrica("taxa_ia", "Reunião→venda, agente", R["ia"]["vendidos"], n=R["ia"]["n"],
                relogio=_R, confianca="media" if R["ia"]["n"] >= N_MINIMO_TAXA else "baixa",
                definicao="Vendidos com venda posterior / leads com primeira marcação ia."),
        metrica("taxa_lp", "Reunião→venda, landing page", R["landing_page"]["vendidos"],
                n=R["landing_page"]["n"], relogio=_R, confianca="media",
                definicao="Vendidos com venda posterior / leads com primeira marcação LP."),
        metrica("concluida_venda_ia", "Concluída→venda, agente",
                R["ia"]["vend_conc"] if R["ia"]["concluidas"] >= N_MINIMO_TAXA else None,
                n=R["ia"]["concluidas"], relogio=_R,
                confianca="media" if R["ia"]["concluidas"] >= N_MINIMO_TAXA else "nao_medivel",
                definicao="Vendidos entre os leads ia com reunião Concluido.",
                limitacao=None if R["ia"]["concluidas"] >= N_MINIMO_TAXA else
                f"não medível como taxa: N={R['ia']['concluidas']} < {N_MINIMO_TAXA}"),
    ]
    for m in ms:
        print(f"- `{m['id']}` {m['rotulo']}: valor={m['valor']} · N={m['n']} · "
              f"relógio={m['relogio']} · confiança={m['confianca']} · {m['definicao']}"
              + (f" Limitação: {m['limitacao']}" if m["limitacao"] else ""))
    print(f"\nGerado em {datetime.now():%d/%m %H:%M} (servidor). Somente leitura.")


async def main(de: date, ate: date, cache: str | None) -> None:
    sold = await leads_sold(cache)
    async with async_session() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        d = await coletar(db, de, ate, sold)
        await db.rollback()
    tabelas(d, de, ate)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--de", type=date.fromisoformat, default=INICIO_ESPELHO)
    ap.add_argument("--ate", type=date.fromisoformat,
                    default=date.today() - timedelta(days=1))
    ap.add_argument("--cache", default=None, help="JSON de LeadsSold (lê se existir)")
    a = ap.parse_args()
    asyncio.run(main(a.de, a.ate, a.cache))
