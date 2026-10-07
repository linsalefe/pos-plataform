"""Métricas do case "IA de confirmação": antes (RECON §2, fixo) × depois (período dado).

    cd backend && venv/bin/python case_metrics.py                         # 07/10 até hoje
    cd backend && venv/bin/python case_metrics.py --de 2026-10-07 --ate 2026-11-06

SOMENTE LEITURA: só SELECT, nenhum commit, nenhuma chamada à Meta ou à Exact.

PERÍODO em datas de SP, as duas pontas inclusive. Relógios: `reuniao_status.*`,
`messages.timestamp` e `nat_scheduled_actions.processed_at` são SP naive;
`nat_qualificacao_state.created_at` é `now()` do banco (UTC naive) e é convertido para SP.

LEADS DE TESTE: fora de todas as contas, pela mesma regra da página /relatorios
(`relatorios.chaves_de_teste`, predicado ancorado em `^zz` + bloco de telefones do time). A
comparação é pela chave tolerante do telefone (`telefone.chave_telefone`).

O "ANTES" é o RECON_CONFIRMACAO_NOSHOW_20261007 §2 (30 dias até 06/10, sem teste). Onde o
antes não existe (não havia régua de confirmação nem de no-show), o valor é 0 e a linha diz
"não existia". Comparar períodos de tamanhos diferentes: use as TAXAS, não os absolutos.
"""
import argparse
import asyncio
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import text

from app.database import async_session
from app.nat_guard import _agora_sp
from app.relatorios import chaves_de_teste
from app.telefone import chave_telefone

# ==========================================================================================
# ANTES — RECON_CONFIRMACAO_NOSHOW_20261007_REPORT.md §2 (07/09 a 06/10, sem teste)
# ==========================================================================================
ANTES_PERIODO = "07/09 a 06/10/2026 (30 dias)"
# Reuniões com horário passado, pelo `type` na Exact
ANTES_REUNIOES_TODAS = {"total": 230, "Concluido": 71, "Cancelada": 147, "Vigente": 12}
ANTES_REUNIOES_HUB = {"total": 153, "Concluido": 26, "Cancelada": 115, "Vigente": 12}
# Confirmação de presença: não existia régua (só o T-30, que saía para todo mundo)
ANTES_CONFIRMACOES = {"reguas": 0, "botao": 0, "texto": 0}
# No-show: não existia corte nem régua D0–D8
ANTES_CORTES = 0
ANTES_RECUPERADOS = 0
# Fluxo B: 293 pessoas aplicaram (`lead_criado`), 121 agendaram em até 10 min, 161 nunca
# tiveram reunião; o agente marcou 19 reuniões no período (todas as origens do agente).
ANTES_APLICOU = 293
ANTES_AGENDOU_10MIN = 121
ANTES_APLICOU_SEM_AGENDAR = ANTES_APLICOU - ANTES_AGENDOU_10MIN      # 172
ANTES_NUNCA_TEVE_REUNIAO = 161
ANTES_AGENDADAS_PELO_AGENTE = 19
# Mensagens automáticas pós-agendamento: só o T-30 (122 executados)
ANTES_MENSAGENS = {"T-30 (lembrete antigo)": 122, "confirmação": 0, "no-show": 0, "Fluxo B": 0}
# Reuniões marcadas pela SDR direto na Exact (fora do Hub) que receberam confirmação: nenhuma.
# RECON §5.3: 64 de 249 reuniões (26%) não passavam pelo Hub.
ANTES_SDR_EXACT = {"reunioes": 64, "com_confirmacao": 0}

# ==========================================================================================
# GRUPOS DE MENSAGEM AUTOMÁTICA (messages.nat_etapa)
# ==========================================================================================
GRUPOS = {
    "confirmação": ("nat_a_confirmacao", "nat_a_ementa", "nat_a_beneficio",
                    "nat_a_pedido_confirmacao", "nat_a_ultimo_aviso", "nat_a_30min",
                    "nat_ns_d0_corte", "confirm_a_resposta", "confirm_a_duvida"),
    "no-show": ("nat_ns_d0_1h", "nat_ns_d0_8h", "nat_ns_d1", "nat_ns_d2_audio",
                "nat_ns_d3_seminario", "nat_ns_d5_conteudo", "nat_ns_d7_condicao",
                "nat_ns_d8_encerramento", "noshow_resposta"),
    "Fluxo B": ("nat_b_abertura", "nat_b_reativ_30m", "nat_b_reativ_2h", "nat_b_reativ_4h",
                "nat_b_reativ_d1"),
    "agente (conversa e aberturas antigas)": ("qualif_conversa", "nat_abertura_qualificacao",
                                              "nat_abertura_agendado",
                                              "nat_abertura_sem_formacao"),
    "T-30 (lembrete antigo)": ("nat_lembrete_reuniao",),
}

# Como a régua de no-show foi encerrada (`reuniao_status.regua_encerrada_motivo`)
CLIQUES_NOSHOW = {"NS_D0_AGORA", "NS_1H_AGORA", "NS_8H_AGORA", "NS_D2_AGORA", "NS_D8_AGORA",
                  "NS_D0_HORARIO", "NS_1H_HORARIO", "NS_8H_HORARIO", "NS_D1_HORARIO",
                  "NS_D2_REAGENDAR", "NS_D7_REAGENDAR", "NS_D8_REAGENDAR", "NS_D3_QUERO"}
TEXTO_NOSHOW = {"humano"}
REAGENDOU_NOSHOW = {"reagendou"}


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "—"


def linha(rotulo: str, antes, depois, largura: int = 58, valor: int = 16) -> None:
    print(f"  {rotulo:<{largura}} {str(antes):>{valor}} {str(depois):>{valor}}")


def cabecalho(titulo: str) -> None:
    print(f"\n{titulo}")
    print(f"  {'':<58} {'ANTES':>16} {'DEPOIS':>16}")


async def main(de: date, ate: date) -> None:
    ini = datetime.combine(de, datetime.min.time())
    fim = datetime.combine(ate + timedelta(days=1), datetime.min.time())
    agora = _agora_sp()
    p = {"ini": ini, "fim": fim, "agora": agora}

    async with async_session() as db:
        teste = (await chaves_de_teste(db)).excluir

        def real(tel) -> bool:
            return chave_telefone(tel) not in teste

        async def q(sql: str, **extra):
            return (await db.execute(text(sql), {**p, **extra})).all()

        # --------------------------------------------------------------------------------
        # Réguas de confirmação armadas no período (a confirmação imediata saiu)
        imediatas = await q("""
            SELECT DISTINCT (a.payload::json->>'meeting_id')::bigint
            FROM nat_scheduled_actions a
            WHERE a.kind = 'confirm_a_imediata' AND a.status = 'executado'
              AND a.processed_at >= :ini AND a.processed_at < :fim""")
        ids_regua = {r[0] for r in imediatas if r[0]}
        reunioes = {r.meeting_id: r for r in await q("""
            SELECT meeting_id, telefone_bruto, origem, slot_inicio, exact_type, confirmado_em,
                   confirmado_por, cancelado_em, cancelado_motivo, noshow_em,
                   regua_encerrada_motivo
            FROM reuniao_status""") if real(r.telefone_bruto)}
        com_regua = [reunioes[m] for m in ids_regua if m in reunioes]
        # A 1ª mensagem falhou na Meta (131026, 130472...): a pessoa nunca viu o pedido, então
        # não entra no denominador da taxa de confirmação.
        falhou_1a = {chave_telefone(r[0]) for r in await q("""
            SELECT contact_wa_id FROM messages
            WHERE nat_etapa = 'nat_a_confirmacao' AND status = 'failed'
              AND timestamp >= :ini AND timestamp < :fim""")}
        entregues = [r for r in com_regua
                     if r.confirmado_em or chave_telefone(r.telefone_bruto) not in falhou_1a]

        # --------------------------------------------------------------------------------
        cabecalho(f"1. CONFIRMAÇÃO DE PRESENÇA (período {de:%d/%m}–{ate:%d/%m}; antes: "
                  f"{ANTES_PERIODO})")
        botao = sum(1 for r in entregues if r.confirmado_por == "botao")
        texto_ = sum(1 for r in entregues if r.confirmado_por == "texto")
        linha("réguas armadas (confirmação imediata enviada)", "não existia", len(com_regua))
        linha("  descontadas: 1ª mensagem falhou na Meta (131026, 130472)", "—",
              len(com_regua) - len(entregues))
        linha("confirmou por botão", 0, f"{botao} ({pct(botao, len(entregues))})")
        linha("confirmou por texto", 0, f"{texto_} ({pct(texto_, len(entregues))})")
        linha("taxa de confirmação total", "—", pct(botao + texto_, len(entregues)))

        # --------------------------------------------------------------------------------
        cabecalho("2. COMPARECIMENTO: reuniões com horário no período e já passadas, pelo "
                  "type na Exact")
        passadas = [r for r in reunioes.values() if ini <= r.slot_inicio < min(fim, agora)]

        def dist(rs) -> str:
            c = Counter(r.exact_type for r in rs)
            return (f"{len(rs)}: C {c['Concluido']} ({pct(c['Concluido'], len(rs))}) · "
                    f"X {c['Cancelada']} · V {c['Vigente']}")

        a = ANTES_REUNIOES_TODAS
        linha("todas", f"{a['total']}: C {a['Concluido']} ({pct(a['Concluido'], a['total'])})",
              dist(passadas), 26, 30)
        h = ANTES_REUNIOES_HUB
        linha("marcadas pelo Hub",
              f"{h['total']}: C {h['Concluido']} ({pct(h['Concluido'], h['total'])})",
              dist([r for r in passadas if r.origem == "hub"]), 26, 30)
        regua_passadas = [r for r in passadas if r.meeting_id in ids_regua]
        linha("com régua, CONFIRMOU", "não existia",
              dist([r for r in regua_passadas if r.confirmado_em]), 26, 30)
        linha("com régua, NÃO confirmou", "não existia",
              dist([r for r in regua_passadas if not r.confirmado_em]), 26, 30)
        print("  (C = Concluido, X = Cancelada, V = Vigente sem feedback da consultora; "
              "'Concluido' é o único sinal de que a reunião aconteceu)")

        # --------------------------------------------------------------------------------
        cabecalho("3. CORTES (sem confirmação) E RECUPERADOS PELA RÉGUA DE NO-SHOW")
        cortes = [r for r in reunioes.values() if r.cancelado_motivo == "sem_confirmacao"
                  and r.cancelado_em and ini <= r.cancelado_em < fim]
        linha("cortes no período", ANTES_CORTES, len(cortes))
        por_dia = Counter(r.cancelado_em.date() for r in cortes)
        for d in sorted(por_dia):
            linha(f"  {d:%d/%m}", "", por_dia[d])
        ns = [r for r in cortes if r.noshow_em]
        clique = sum(1 for r in ns if r.regua_encerrada_motivo in CLIQUES_NOSHOW)
        txt = sum(1 for r in ns if r.regua_encerrada_motivo in TEXTO_NOSHOW)
        reag = sum(1 for r in ns if r.regua_encerrada_motivo in REAGENDOU_NOSHOW)
        linha("régua de no-show armada", "não existia", len(ns))
        linha("  recuperados por clique", ANTES_RECUPERADOS, f"{clique} ({pct(clique, len(ns))})")
        linha("  recuperados por texto (foi para humano)", 0, f"{txt} ({pct(txt, len(ns))})")
        linha("  reagendou (reunião nova no espelho)", 0, f"{reag} ({pct(reag, len(ns))})")
        linha("  ainda viva / esgotou / outro", "—", len(ns) - clique - txt - reag)

        # --------------------------------------------------------------------------------
        cabecalho("4. FLUXO B: aplicou sem agendar → agendou pelo agente")
        estados = [e for e in await q("""
            SELECT contact_wa_id, etapa, origem, agendamento_id, encerrado_motivo,
                   transferido_motivo, dados_extras
            FROM nat_qualificacao_state
            WHERE (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') >= :ini
              AND (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') < :fim
              AND dados_extras->>'fluxo' = 'b'""") if real(e.contact_wa_id)]

        def extras(e) -> dict:
            v = e.dados_extras
            return v if isinstance(v, dict) else json.loads(v or "{}")

        abertos = [e for e in estados if not extras(e).get("reaberturas") and e.origem == "lp"]
        agendou = [e for e in abertos if e.etapa == "concluido" and e.agendamento_id]
        linha("aplicou sem agendar (abertura do agente saiu)", ANTES_APLICOU_SEM_AGENDAR,
              len(abertos))
        linha("  agendou pelo agente", ANTES_AGENDADAS_PELO_AGENTE,
              f"{len(agendou)} ({pct(len(agendou), len(abertos))})")
        motivos = Counter(e.encerrado_motivo or e.transferido_motivo or e.etapa
                          for e in abertos if e not in agendou)
        for m, n in motivos.most_common(8):
            linha(f"  {m[:52]}", "", n)
        reab = [e for e in estados if extras(e).get("reaberturas") or e.origem == "exact"]
        reab_ag = [e for e in reab if e.etapa == "concluido" and e.agendamento_id]
        linha("remarcação pelo botão: agente reabriu", "não existia", len(reab))
        linha("  remarcou pelo agente", "não existia", len(reab_ag))
        print(f"  (antes: {ANTES_APLICOU} aplicaram, {ANTES_AGENDOU_10MIN} agendaram em 10 min, "
              f"{ANTES_NUNCA_TEVE_REUNIAO} nunca tiveram reunião; as {ANTES_AGENDADAS_PELO_AGENTE}"
              f" do agente são de todas as origens)")

        # --------------------------------------------------------------------------------
        cabecalho("5. MENSAGENS AUTOMÁTICAS POR RÉGUA (enviadas · falharam na Meta)")
        msgs = await q("""
            SELECT contact_wa_id, nat_etapa, status FROM messages
            WHERE direction = 'outbound' AND nat_etapa IS NOT NULL
              AND timestamp >= :ini AND timestamp < :fim""")
        por_grupo, falhas = Counter(), Counter()
        grupo_de = {e: g for g, es in GRUPOS.items() for e in es}
        for m in msgs:
            g = grupo_de.get(m.nat_etapa)
            if g and real(m.contact_wa_id):
                por_grupo[g] += 1
                falhas[g] += m.status == "failed"
        for g in GRUPOS:
            linha(g, ANTES_MENSAGENS.get(g, "—"), f"{por_grupo[g]} · {falhas[g]} falha(s)")
        dias = (ate - de).days + 1
        linha("total por dia (régua nova: confirmação + no-show + Fluxo B)",
              f"{122 / 30:.1f}",
              f"{(por_grupo['confirmação'] + por_grupo['no-show'] + por_grupo['Fluxo B']) / dias:.1f}")

        # --------------------------------------------------------------------------------
        cabecalho("6. REUNIÕES MARCADAS PELA SDR NA EXACT (fora do Hub)")
        sdr = [r for r in reunioes.values() if r.origem == "exact"
               and ini <= r.slot_inicio < fim]
        sdr_conf = [r for r in sdr if r.meeting_id in ids_regua]
        linha("reuniões da SDR com horário no período", f"{ANTES_SDR_EXACT['reunioes']} (de 249)",
              len(sdr))
        linha("  receberam a confirmação imediata", ANTES_SDR_EXACT["com_confirmacao"],
              f"{len(sdr_conf)} ({pct(len(sdr_conf), len(sdr))})")
        linha("  confirmaram", 0, sum(1 for r in sdr_conf if r.confirmado_em))

        print(f"\nLeads de teste excluídos: {len(teste)} chave(s) de telefone. "
              f"Gerado em {agora:%d/%m %H:%M} (SP). Somente leitura.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--de", type=date.fromisoformat, default=date(2026, 10, 7))
    ap.add_argument("--ate", type=date.fromisoformat, default=None)
    a = ap.parse_args()
    asyncio.run(main(a.de, a.ate or _agora_sp().date()))
