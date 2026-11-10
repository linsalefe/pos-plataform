"""Case "participação da IA no faturamento": por quais automações cada venda passou (10/11/2026).

    cd backend && venv/bin/python case_participacao.py --de 2026-10-01 --ate 2026-10-31 \
        --cache /caminho/leadssold.json --csv /caminho/vendas.csv

SOMENTE LEITURA: só SELECT (transação READ ONLY). `LeadsSold` vem do cache do recon 1
(`case_faturamento.leads_sold`, que só relê a Exact se o arquivo não existir). Relatório:
CASE_PARTICIPACAO_IA_20261109.md. Continua CASE_FATURAMENTO_AGENTE_20261109.md.

UNIDADE: a VENDA. Uma por lead: a primeira de `LeadsSold` com saleDate >= dia da primeira
marcação (regra do recon 1), ou a primeira do período se o lead nunca teve marcação nossa.
Entra quem tem essa venda com saleDate no período, em funil de pós, fora dos leads de teste.

RELÓGIOS, todos MEDIDOS (não lidos de comentário) e levados para SP naive aqui:
  SP   messages.timestamp, agendamentos.created_at, reuniao_status.*,
       nat_scheduled_actions.processed_at (230 de 235 confirmações saem no mesmo minuto)
  UTC  LeadsSold.saleDate, nat_qualificacao_state.created_at (322 de 322 a 3 h da
       nat_b_abertura), follow_estagio_envios.enviado_em (1 993 de 1 993 a 3 h da mensagem)
A comparação "toque antes da venda" é por DIA: saleDate às vezes é só a data.

OS FLAGS (um por automação; vale o ÚLTIMO toque daquele tipo com dia <= dia da venda):
  abertura          saída não falhada com nat_etapa em ETAPAS_ABERTURA (aberturas T1/T2/T3,
                    qualif_conversa e o follow_up do Sprint D)
  fluxo_b           estado de nat_qualificacao_state com fluxo='b' criado
  follow_etapa      follow_estagio_envios com status 'enviado' para o lead
  marcou_ia         a PRIMEIRA marcação do lead é agendamento sem origem_ip (coorte ia)
  confirmacao       confirm_a_imediata executada numa reunião do lead E a nat_a_confirmacao
                    daquele minuto não falhou na Meta
  confirmou         reuniao_status.confirmado_em numa reunião do lead
  lembrete_t30      lembrete_reuniao executado para reunião (meeting_id) ou agendamento do lead
  noshow_regua      reunião do lead com noshow_em (o corte sem_confirmacao grava os dois)
  noshow_recuperado depois do noshow_em, a régua encerrou por NS_* ou humano, OU o lead teve
                    marcação nova; e a venda veio nesse dia ou depois
  remarcou_ia       agendamento do agente que NÃO é a primeira marcação, ou reunião com
                    cancelado_motivo / regua_encerrada_motivo = 'remarcar' (botão)
"Reuniões do lead" = as do espelho com registrado_em entre o dia da primeira marcação e o dia
da venda (decisão 1.2). O script conta também quantos flags sobram se só a reunião da
primeira marcação valer.
"""
import argparse
import asyncio
import csv
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import text

from app.database import async_session
from app.relatorios import (ABERTURA_T1, ABERTURA_T2, ABERTURA_T3, N_MINIMO_TAXA,
                            chaves_de_teste, metrica, thread_sql)
from app.telefone import chave_telefone
from case_faturamento import (FUNIS_POS, INICIO_ESPELHO, brl, leads_sold, pct, sp,
                              venda_apos)

UTC_PARA_SP = timedelta(hours=3)
# As réguas de confirmação e de no-show nasceram aqui (Bloco 1 e 2). Antes: "não existia".
INICIO_REGUAS = date(2026, 10, 7)
ETAPAS_ABERTURA = ("qualif_conversa", "follow_up", ABERTURA_T1, ABERTURA_T2, ABERTURA_T3)
# O que conta como "o agente falou" para separar sdr_exact e landing_page: o mesmo critério
# do recon 1 (case_faturamento.ETAPAS_AGENTE + nat_b_*), sem o follow_up, que ele não usava.
ETAPAS_TOQUE_ORIGEM = ("qualif_conversa", ABERTURA_T1, ABERTURA_T2, ABERTURA_T3)

FLAGS = ("abertura", "fluxo_b", "follow_etapa", "marcou_ia", "confirmacao", "confirmou",
         "lembrete_t30", "noshow_regua", "noshow_recuperado", "remarcou_ia")
CONVERSA = ("abertura", "fluxo_b", "follow_etapa", "remarcou_ia")
POS_MARCACAO = ("confirmacao", "lembrete_t30", "noshow_regua")
# `confirmou` é resposta da pessoa, não toque da IA: fica fora do "só essa automação".
TOQUES_IA = tuple(f for f in FLAGS if f != "confirmou")
O_QUE_FAZ = {
    "abertura": "o agente abriu ou conduziu a conversa de qualificação",
    "fluxo_b": "a pessoa aplicou na LP sem marcar e o agente entrou em seguida",
    "follow_etapa": "template automático por etapa da Exact, NÃO é conversa do agente",
    "lembrete_antigo": "lembrete antigo (até 06/10), saía para toda reunião, sem confirmação",
    "lembrete_novo": "régua nova (desde 07/10): T-30 só para quem confirmou",
    "marcou_ia": "o agente marcou a primeira reunião na conversa",
    "confirmacao": "régua de confirmação rodou na reunião (1ª mensagem entregue)",
    "confirmou": "a pessoa confirmou presença (botão ou texto)",
    "lembrete_t30": "lembrete automático 30 min antes da reunião (antigo + novo)",
    "noshow_regua": "a reunião foi cortada sem confirmação ou caiu em no-show",
    "noshow_recuperado": "depois do corte, a pessoa respondeu ou remarcou, e a venda veio depois",
    "remarcou_ia": "a reunião foi remarcada pelo agente ou pelo botão",
}
FAIXAS = (("mesmo dia", 0, 0), ("1 a 3 dias", 1, 3), ("4 a 7 dias", 4, 7),
          ("8 a 30 dias", 8, 30), ("mais de 30 dias", 31, 10 ** 6))


def thr(tel) -> str:
    """O espelho em Python de `relatorios.thread_sql`: chave tolerante ou o número cru."""
    return chave_telefone(tel) or "".join(c for c in (tel or "") if c.isdigit())


def ultimo(datas, ate: date):
    """O último instante com dia <= `ate`, ou None."""
    ok = [d for d in datas if d is not None and d.date() <= ate]
    return max(ok) if ok else None


def faixa(dias: int) -> str:
    for nome, a, b in FAIXAS:
        if a <= dias <= b:
            return nome
    return "toque depois da marcação"


async def carregar(db) -> dict:
    async def q(sql, **kw):
        return (await db.execute(text(sql), kw)).all()

    teste = (await chaves_de_teste(db)).excluir
    leads = {r.exact_id: r for r in await q(
        "SELECT exact_id, stage, funnel_id, phone1 FROM exact_leads")}
    ags = await q("""SELECT id, lead_id, telefone, passo, origem_ip IS NULL AS ia, created_at AS em,
                            meeting_id FROM agendamentos WHERE lead_id IS NOT NULL""")
    reunioes = await q("""SELECT meeting_id, lead_id, telefone_bruto, registrado_em, slot_inicio,
                                 origem, agendamento_id, exact_type, confirmado_em, cancelado_motivo,
                                 noshow_em, regua_encerrada_em, regua_encerrada_motivo
                          FROM reuniao_status WHERE lead_id IS NOT NULL""")
    acoes = await q("""SELECT kind, contact_wa_id, processed_at,
                              (payload::json->>'meeting_id')::bigint AS meeting_id,
                              (payload::json->>'agendamento_id')::bigint AS agendamento_id
                       FROM nat_scheduled_actions WHERE status = 'executado'
                         AND kind IN ('confirm_a_imediata','lembrete_reuniao')""")
    msgs = await q(f"""SELECT {thread_sql('m.contact_wa_id')} AS thr, m.timestamp AS ts,
                              m.nat_etapa AS etapa, m.status
                       FROM messages m WHERE m.direction = 'outbound'
                         AND (m.nat_etapa = ANY(:et) OR m.nat_etapa LIKE 'nat_b_%'
                              OR m.nat_etapa = 'nat_a_confirmacao')""",
                   et=list(set(ETAPAS_ABERTURA) | set(ETAPAS_TOQUE_ORIGEM)))
    estados = await q(f"""SELECT {thread_sql('s.contact_wa_id')} AS thr, s.created_at AS criado_utc
                          FROM nat_qualificacao_state s WHERE s.dados_extras->>'fluxo' = 'b'""")
    follows = await q("""SELECT lead_exact_id, telefone, enviado_em AS enviado_utc
                         FROM follow_estagio_envios WHERE status = 'enviado'""")
    return dict(teste=teste, leads=leads, ags=ags, reunioes=reunioes, acoes=acoes, msgs=msgs,
                estados=estados, follows=follows)


def montar(base: dict, sold: list[dict], de: date, ate: date) -> dict:
    teste, leads = base["teste"], base["leads"]

    def real(tel) -> bool:
        return chave_telefone(tel) not in teste

    # --- índices ----------------------------------------------------------------------------
    marcacoes = defaultdict(list)        # lead -> [(em, origem, agendamento_id, meeting_id)]
    ags_do_lead = defaultdict(list)
    for a in base["ags"]:
        ags_do_lead[a.lead_id].append(a)
        if a.passo == "agendado" and real(a.telefone):
            marcacoes[a.lead_id].append((a.em, "ia" if a.ia else "landing_page", a.id,
                                         a.meeting_id))
    reun_do_lead = defaultdict(list)
    for r in base["reunioes"]:
        reun_do_lead[r.lead_id].append(r)
        if r.origem == "exact" and real(r.telefone_bruto):
            marcacoes[r.lead_id].append((r.registrado_em, "sdr_exact", None, r.meeting_id))
    msgs = defaultdict(list)
    for m in base["msgs"]:
        msgs[m.thr].append(m)
    fluxo_b = defaultdict(list)
    for s in base["estados"]:
        fluxo_b[s.thr].append(s.criado_utc - UTC_PARA_SP)
    follows = defaultdict(list)
    for f in base["follows"]:
        follows[f.lead_exact_id].append(f.enviado_utc - UTC_PARA_SP)
    acoes_meeting, acoes_ag = defaultdict(list), defaultdict(list)
    for a in base["acoes"]:
        if a.meeting_id:
            acoes_meeting[(a.kind, a.meeting_id)].append(a)
        if a.agendamento_id:
            acoes_ag[(a.kind, a.agendamento_id)].append(a)
    vendas_lead = defaultdict(list)
    for x in sold:
        vendas_lead[x["leadId"]].append(x)

    ini, fim = de, ate
    linhas, fora = [], Counter()
    for lid, vs in vendas_lead.items():
        lead = leads.get(lid)
        if lead is None:
            if any(ini <= sp(x["saleDate"]).date() <= fim for x in vs):
                fora["lead não está no espelho exact_leads"] += 1
            continue
        if lead.funnel_id not in FUNIS_POS:
            continue
        if not real(lead.phone1):
            if any(ini <= sp(x["saleDate"]).date() <= fim for x in vs):
                fora["lead de teste"] += 1
            continue
        t = thr(lead.phone1)
        ms = sorted(marcacoes.get(lid, []), key=lambda m: m[0])
        if ms:
            em, origem, ag_id, meeting_id = ms[0]
            v = venda_apos(vs, em)
            if v is None:
                no_per = sorted((x for x in vs if ini <= sp(x["saleDate"]).date() <= fim),
                                key=lambda x: x["saleDate"])
                if not no_per:
                    continue
                v, origem, em, ag_id, meeting_id = no_per[0], "venda_antes_da_marcacao", \
                    None, None, None
        else:
            no_per = sorted((x for x in vs if ini <= sp(x["saleDate"]).date() <= fim),
                            key=lambda x: x["saleDate"])
            if not no_per:
                continue
            v, origem, em, ag_id, meeting_id = no_per[0], "sem_reuniao", None, None, None
        dv = sp(v["saleDate"])
        if not ini <= dv.date() <= fim:
            continue
        dia = dv.date()

        # --- flags de conversa (pelo telefone) -------------------------------------------
        ms_t = msgs.get(t, [])
        ok = [m for m in ms_t if m.status != "failed"]
        f = {}
        f["abertura"] = ultimo([m.ts for m in ok if m.etapa in ETAPAS_ABERTURA], dia)
        f["fluxo_b"] = ultimo(fluxo_b.get(t, []), dia)
        f["follow_etapa"] = ultimo(follows.get(lid, []), dia)
        f["marcou_ia"] = em if origem == "ia" else None

        # Toque do agente ANTES da marcação, com o critério do recon 1, para dividir as origens.
        if em is not None:
            toque_antes = [m.ts for m in ms_t if m.ts <= em and (
                m.etapa in ETAPAS_TOQUE_ORIGEM or (m.etapa or "").startswith("nat_b_"))]
            if origem == "sdr_exact":
                origem = "sdr_com_agente" if toque_antes else "sdr_sem_agente"
            elif origem == "landing_page":
                origem = "lp_com_agente" if toque_antes else "lp_sem_agente"

        # --- reuniões do lead entre a 1ª marcação e a venda ------------------------------
        if em is not None:
            rs = [r for r in reun_do_lead.get(lid, []) if r.registrado_em
                  and em.date() <= r.registrado_em.date() <= dia]
            ag_ids = [a.id for a in ags_do_lead.get(lid, []) if a.passo == "agendado"
                      and em.date() <= a.em.date() <= dia]
        else:
            rs, ag_ids = [], []
        primeira = [r for r in rs if r.meeting_id == meeting_id] if meeting_id else []

        def flags_reuniao(rs_, ags_):
            g = {}
            conf = []
            for r in rs_:
                for a in acoes_meeting.get(("confirm_a_imediata", r.meeting_id), []):
                    ent = any(m.etapa == "nat_a_confirmacao" and m.status != "failed"
                              and abs((m.ts - a.processed_at).total_seconds()) <= 1800
                              for m in ms_t)
                    if ent:
                        conf.append(a.processed_at)
            g["confirmacao"] = ultimo(conf, dia)
            g["confirmou"] = ultimo([r.confirmado_em for r in rs_], dia)
            lem = [a.processed_at for r in rs_
                   for a in acoes_meeting.get(("lembrete_reuniao", r.meeting_id), [])]
            lem += [a.processed_at for i in ags_
                    for a in acoes_ag.get(("lembrete_reuniao", i), [])]
            g["lembrete_t30"] = ultimo(lem, dia)
            g["lembrete_antigo"] = ultimo([x for x in lem if x.date() < INICIO_REGUAS], dia)
            g["lembrete_novo"] = ultimo([x for x in lem if x.date() >= INICIO_REGUAS], dia)
            g["noshow_regua"] = ultimo([r.noshow_em for r in rs_], dia)
            rec = []
            for r in rs_:
                if not r.noshow_em or r.noshow_em.date() > dia:
                    continue
                if r.regua_encerrada_em and r.regua_encerrada_em >= r.noshow_em and (
                        (r.regua_encerrada_motivo or "").startswith("NS_")
                        or r.regua_encerrada_motivo == "humano"):
                    rec.append(r.regua_encerrada_em)
                nova = [m[0] for m in marcacoes.get(lid, []) if m[0] > r.noshow_em]
                if nova:
                    rec.append(min(nova))
            g["noshow_recuperado"] = ultimo(rec, dia)
            return g

        f.update(flags_reuniao(rs, ag_ids))
        f_primeira = flags_reuniao(primeira, [ag_id] if ag_id else [])

        rem = [a.em for a in ags_do_lead.get(lid, []) if a.passo == "agendado" and a.ia
               and em is not None and a.em > em]
        rem += [r.regua_encerrada_em or r.registrado_em for r in rs
                if "remarcar" in (r.cancelado_motivo, r.regua_encerrada_motivo)]
        f["remarcou_ia"] = ultimo(rem, dia)

        conversa_antes = [f[k] for k in ("abertura", "fluxo_b", "follow_etapa")
                          if f[k] is not None and (em is None or f[k] <= em)]
        ref = em or dv
        dist = (ref.date() - max(conversa_antes).date()).days if conversa_antes else None
        linhas.append(dict(lead_id=lid, valor=v["totalDealValue"] or None, venda=dv,
                           origem=origem, marcacao=em, flags=f, flags_primeira=f_primeira,
                           distancia=dist, conversa_depois=bool(
                               [f[k] for k in CONVERSA if f[k] is not None]) and dist is None,
                           stage=lead.stage))
    return dict(linhas=linhas, fora=fora)


def soma(ls) -> tuple[int, float | None, int]:
    v = [l["valor"] for l in ls if l["valor"]]
    return len(ls), (sum(v) if v else None), len(ls) - len(v)


def tabelas(d: dict, de: date, ate: date) -> None:
    ls = d["linhas"]
    n_tot, r_tot, _ = soma(ls)
    reguas = "" if de >= INICIO_REGUAS else (
        f" (régua só existe desde {INICIO_REGUAS:%d/%m}; antes disso: não existia)")
    print(f"# Período {de:%d/%m/%Y} a {ate:%d/%m/%Y} (SP, por saleDate)\n")
    print(f"Vendas: {n_tot} · {brl(r_tot)} · fora: {dict(d['fora']) or 'nenhuma'}\n")

    print("## Origem da marcação\n")
    print("| origem | vendas | faturamento | sem valor |")
    print("|---|---|---|---|")
    for o, n in Counter(l["origem"] for l in ls).most_common():
        n_, r_, sv = soma([l for l in ls if l["origem"] == o])
        print(f"| {o} | {n_} | {brl(r_)} | {sv} |")

    def tem(l, ks):
        return any(l["flags"][k] for k in ks)

    print("\n## Escada (os degraus NÃO somam: uma venda pode estar em vários)\n")
    print("| degrau | vendas | faturamento | % do faturamento |")
    print("|---|---|---|---|")
    degraus = [("total do período", lambda l: True),
               ("qualquer toque da IA", lambda l: tem(l, TOQUES_IA)),
               ("qualquer toque, sem confirmação e lembrete",
                lambda l: tem(l, [k for k in TOQUES_IA
                                  if k not in ("confirmacao", "lembrete_t30")])),
               ("toque de conversa (abertura, Fluxo B, follow, remarcação)",
                lambda l: tem(l, CONVERSA)),
               ("conversa do agente (abertura, Fluxo B, remarcação; sem o follow)",
                lambda l: tem(l, ("abertura", "fluxo_b", "remarcou_ia"))),
               ("régua pós-marcação (confirmação, lembrete, no-show)" + reguas,
                lambda l: tem(l, POS_MARCACAO)),
               ("recuperada de no-show" + reguas, lambda l: bool(l["flags"]["noshow_recuperado"])),
               ("marcada pela IA (gerou)", lambda l: bool(l["flags"]["marcou_ia"]))]
    for nome, fn in degraus:
        n_, r_, _ = soma([l for l in ls if fn(l)])
        print(f"| {nome} | {n_} | {brl(r_)} | "
              f"{100 * (r_ or 0) / r_tot:.1f}% |" if r_tot else f"| {nome} | {n_} | — | — |")

    print("\n## Por automação\n")
    print("| automação | o que faz | vendas | faturamento | só essa automação (vendas · R$) | "
          "1ª reunião só |")
    print("|---|---|---|---|---|---|")
    for k in FLAGS + ("lembrete_antigo", "lembrete_novo"):
        com = [l for l in ls if l["flags"][k]]
        base_k = "lembrete_t30" if k.startswith("lembrete_") else k
        so = [l for l in com if base_k in TOQUES_IA
              and all(not l["flags"][j] for j in TOQUES_IA if j != base_k)]
        n_, r_, _ = soma(com)
        ns, rs_, _ = soma(so)
        prim = (sum(1 for l in com if l["flags_primeira"].get(k))
                if k in l_flags_reuniao() else "—")
        so_txt = f"{ns} · {brl(rs_)}" if base_k in TOQUES_IA else "não se aplica (resposta)"
        nota = reguas if k in ("confirmacao", "confirmou", "noshow_regua",
                               "noshow_recuperado") else ""
        print(f"| {k}{nota} | {O_QUE_FAZ[k]} | {n_} | {brl(r_)} | {so_txt} | {prim} |")

    print("\n## Distância: último toque de conversa ANTES da marcação → marcação\n")
    print("Vendas sem reunião nossa: distância até a venda.\n")
    print("| faixa | vendas | faturamento |")
    print("|---|---|---|")
    com_conv = [l for l in ls if tem(l, CONVERSA)]
    grupos = defaultdict(list)
    for l in com_conv:
        grupos[faixa(l["distancia"]) if l["distancia"] is not None
               else "toque de conversa só depois da marcação"].append(l)
    for nome in [f[0] for f in FAIXAS] + ["toque de conversa só depois da marcação"]:
        n_, r_, _ = soma(grupos.get(nome, []))
        print(f"| {nome} | {n_} | {brl(r_)} |")
    plaus = [l for l in com_conv if l["distancia"] is not None and l["distancia"] <= 7]
    n_, r_, _ = soma(plaus)
    print(f"| **influência plausível (até 7 dias)** | {n_} | {brl(r_)} |")

    print("\n## landing_page por toque antes de marcar\n")
    print("| lado | vendas | faturamento |")
    print("|---|---|---|")
    for o in ("lp_sem_agente", "lp_com_agente"):
        n_, r_, _ = soma([l for l in ls if l["origem"] == o])
        print(f"| {o} | {n_} | {brl(r_)} |")

    print("\n## Venda sem reunião nossa, com flags\n")
    for l in [l for l in ls if l["origem"] == "sem_reuniao"]:
        on = [k for k in FLAGS if l["flags"][k]]
        print(f"- lead {l['lead_id']}: {brl(l['valor'])}, flags: {', '.join(on) or 'nenhum'}")

    print("\n## 2.7 Régua de confirmação: confirmou × não confirmou (por reunião)\n")
    print("Unidade: o lead, na 1ª reunião com régua entregue no período e horário já passado. "
          "Venda = qualquer venda até hoje com saleDate >= dia da régua.\n")
    print("| lado | reuniões | concluídas | vendas | faturamento | reunião→venda |")
    print("|---|---|---|---|---|---|")
    for nome, lado in (("confirmou", True), ("não confirmou", False)):
        rs = [x for x in d["regua"].values() if x["confirmou"] is lado]
        vend = [x for x in rs if x["vendeu"]]
        val = [x["valor"] for x in vend if x["valor"]]
        print(f"| {nome} | {len(rs)} | {pct(sum(x['concluido'] for x in rs), len(rs))} | "
              f"{len(vend)} | {brl(sum(val) if val else None)} | {pct(len(vend), len(rs))} |")
    conf = [l for l in ls if l["flags"]["confirmacao"]]
    n1, r1, _ = soma([l for l in conf if l["flags"]["confirmou"]])
    n2, r2, _ = soma([l for l in conf if not l["flags"]["confirmou"]])
    print(f"\nPelo lado da venda: das {len(conf)} vendas do período com régua, {n1} confirmaram "
          f"({brl(r1)}) e {n2} não ({brl(r2)}).\n")

    m = metrica("vendas_tocadas", "Vendas com algum toque da IA",
                soma([l for l in ls if tem(l, TOQUES_IA)])[1], n=n_tot,
                relogio="SP (toques) · UTC→SP (saleDate)", confianca="media",
                definicao="Faturamento das vendas do período com ao menos um flag de IA antes "
                          "do dia da venda.",
                limitacao="Participou não é causou.")
    print(f"\n`{m['id']}`: valor={m['valor']} · N={m['n']} · {m['relogio']} · "
          f"confiança={m['confianca']}")


def regua_por_reuniao(base: dict, sold: list[dict], de: date, ate: date) -> dict:
    """2.7: UMA reunião por lead, a primeira com régua de confirmação ENTREGUE no período e
    com horário já passado. Lado = confirmou ou não; desfecho = Concluido e venda posterior.

    Só reunião passada: uma futura ainda não teve chance de acontecer nem de vender, e
    entraria como "não compareceu, não comprou" no lado de quem não confirmou."""
    teste, leads = base["teste"], base["leads"]
    hoje = datetime.now() - UTC_PARA_SP
    reun = {r.meeting_id: r for r in base["reunioes"]}
    msgs = defaultdict(list)
    for m in base["msgs"]:
        if m.etapa == "nat_a_confirmacao":
            msgs[m.thr].append(m)
    vendas = defaultdict(list)
    for x in sold:
        vendas[x["leadId"]].append(x)
    por_lead = {}
    for a in sorted(base["acoes"], key=lambda a: a.processed_at):
        if a.kind != "confirm_a_imediata" or not a.meeting_id:
            continue
        r = reun.get(a.meeting_id)
        if (r is None or not de <= a.processed_at.date() <= ate or r.lead_id in por_lead
                or r.slot_inicio >= hoje or chave_telefone(r.telefone_bruto) in teste):
            continue
        lead = leads.get(r.lead_id)
        if lead is None or lead.funnel_id not in FUNIS_POS:
            continue
        if not any(m.status != "failed" and abs((m.ts - a.processed_at).total_seconds()) <= 1800
                   for m in msgs.get(thr(r.telefone_bruto), [])):
            continue
        v = venda_apos(vendas.get(r.lead_id, []), a.processed_at)
        por_lead[r.lead_id] = dict(confirmou=r.confirmado_em is not None,
                                   concluido=r.exact_type == "Concluido",
                                   valor=(v["totalDealValue"] or None) if v else None,
                                   vendeu=v is not None)
    return por_lead


def l_flags_reuniao() -> tuple:
    return ("confirmacao", "confirmou", "lembrete_t30", "lembrete_antigo", "lembrete_novo",
            "noshow_regua", "noshow_recuperado")


def gravar_csv(d: dict, caminho: str) -> None:
    """Uma linha por venda: só lead_id, valor, datas e flags. Sem nome, telefone ou e-mail."""
    with open(caminho, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["lead_id", "valor", "venda", "origem", "marcacao", "distancia_dias"]
                   + list(FLAGS))
        for l in sorted(d["linhas"], key=lambda l: l["venda"]):
            w.writerow([l["lead_id"], l["valor"] or "", l["venda"].date(), l["origem"],
                        l["marcacao"].date() if l["marcacao"] else "",
                        "" if l["distancia"] is None else l["distancia"]]
                       + [l["flags"][k].date() if l["flags"][k] else "" for k in FLAGS])


async def main(de: date, ate: date, cache: str | None, csv_path: str | None) -> None:
    sold = await leads_sold(cache)
    async with async_session() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        base = await carregar(db)
        await db.rollback()
    d = montar(base, sold, de, ate)
    d["regua"] = regua_por_reuniao(base, sold, de, ate)
    tabelas(d, de, ate)
    if csv_path:
        gravar_csv(d, csv_path)
        print(f"\nCSV: {csv_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--de", type=date.fromisoformat, default=INICIO_ESPELHO)
    ap.add_argument("--ate", type=date.fromisoformat,
                    default=date.today() - timedelta(days=1))
    ap.add_argument("--cache", default=None)
    ap.add_argument("--csv", default=None)
    a = ap.parse_args()
    asyncio.run(main(a.de, a.ate, a.cache, a.csv))
