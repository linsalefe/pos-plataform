"""A página de Relatórios — os invariantes que não podem quebrar em silêncio.

    cd backend && venv/bin/python test_relatorios.py

LÊ o banco de produção e não escreve nada: nenhum INSERT, nenhum UPDATE, nenhuma migração,
nenhuma mensagem. É um teste de LEITURA sobre dado real, e é de propósito — os defeitos que
esta página pode ter são todos de dado (chave que não casa, denominador trocado, fuso), e
nenhum deles aparece contra um banco dublê.

O QUE ELE PROVA
  1. o `periodo` do JSON é IDÊNTICO ao par que foi para o WHERE (o bug que o recon achou)
  2. `chave_sql` == `app/telefone.chave_telefone` sobre a base inteira
  3. o predicado de teste: 52 excluídos, 1 duvidoso LISTADO, e o Thobias fora dos 45
  4. o `''` não vira conversa: números ilegíveis não se fundem num único thread
  5. os invariantes de saúde continuam onde estavam
  6. reprodução: /jornada devolve 45 / 10 / {ia 3, lp 7} / 28 na coorte congelada
  7. as duas etapas `Reagendamento` e `Reagendamento.` estão as DUAS na guarda
  8. toda query de funil filtra funnel_id explicitamente (INGEST_FUNNEL_IDS está vazio)
  9. seção que estoura devolve erro tratado, sem derrubar as outras
 10. o painel inteiro cabe no orçamento de 2 s
"""
import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import text

from app import relatorios as R
from app.database import async_session
from app.telefone import chave_telefone

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def afirma(rotulo, cond, detalhe=""):
    print(f"  [{'ok' if cond else 'FALHOU'}] {rotulo}")
    if not cond:
        if detalhe:
            print(f"      {detalhe}")
        falhas.append(rotulo)


def m(resposta, id_):
    return next(x for x in resposta["metricas"] if x["id"] == id_)


# A coorte congelada do RECON_JORNADA + EMENDA: `passo='agendado'` entre 24/08 23:16 e
# 01/09 17:00 UTC. Em SP (−3 h) isso é 24/08 20:16 → 01/09 14:00. É este par, e não o
# cabeçalho de 20h do recon, que reproduz os números publicados.
COORTE = "2026-08-24T20:16..2026-09-01T14:00"


async def principal():
    async with async_session() as db:

        # ==================================================================================
        print("\n1) O período do JSON é o MESMO par que foi para o WHERE")
        #
        # O bug que este teste existe para impedir: os "46 agendamentos" do recon não
        # reproduziam com o corte que o cabeçalho declarava (01/09 20h SP) — reproduziam com
        # corte em ~17h UTC. O período era CARIMBADO DEPOIS, não usado como corte da query.
        # Se alguém voltar a formatar o período separado do bind, isto quebra.

        vistos = {}
        real = db.execute

        async def espiao(stmt, params=None, *a, **k):
            if isinstance(params, dict) and "ini" in params:
                vistos.setdefault("ini", params["ini"])
                vistos.setdefault("fim", params["fim"])
            return await real(stmt, params, *a, **k)

        db.execute = espiao
        r = await R.resumo(COORTE, db)
        db.execute = real

        p = R.janela(COORTE)
        checa("o `de` do JSON é o `:ini` do WHERE", r["periodo"]["de"], p.de.isoformat())
        checa("o `ate` do JSON é o `:fim` do WHERE", r["periodo"]["ate"], p.ate.isoformat())
        checa("  e o `:ini` que a query recebeu é esse mesmo", vistos["ini"], p.de)
        checa("  e o `:fim` também", vistos["fim"], p.ate)
        afirma("o período com hora é aceito (as coortes dos recons têm corte no minuto)",
               p.de == datetime(2026, 8, 24, 20, 16) and p.ate == datetime(2026, 9, 1, 14, 0))

        # o bind UTC é o SP + 3 h, e essa soma acontece UMA vez, no helper
        checa("para_utc soma 3 h e só", R.para_utc(p.de), p.de + timedelta(hours=3))

        # ==================================================================================
        print("\n2) `chave_sql` é o espelho EXATO de `chave_telefone`, sobre a base inteira")
        #
        # Duas implementações da mesma regra em idiomas diferentes divergem se ninguém
        # comparar. 379 pessoas têm as duas grafias do telefone; um desencontro aqui é uma
        # pessoa contada duas vezes em metade do painel e uma vez na outra.

        divergentes = []
        for tabela, col in (("exact_leads", "phone1"), ("agendamentos", "telefone"),
                            ("nat_qualificacao_state", "contact_wa_id")):
            linhas = (await db.execute(text(
                f"SELECT {col} AS bruto, {R.chave_sql(col)} AS sql_ FROM {tabela}"))).all()
            for bruto, sql_ in linhas:
                if sql_ != chave_telefone(bruto):
                    divergentes.append((tabela, bruto, sql_, chave_telefone(bruto)))
        afirma(f"nenhuma divergência em exact_leads + agendamentos + estados",
               not divergentes, f"{len(divergentes)} divergem: {divergentes[:5]}")

        # ==================================================================================
        print("\n3) O predicado de teste: duas cestas, e a Ana Cristina fica")

        conj = await R.chaves_de_teste(db)
        checa("53 nomes casam o predicado", conj.nomes_que_casaram, 53)
        checa("18 chaves de telefone entram na cesta EXCLUIR", len(conj.excluir), 18)
        checa("1 duvidoso, e ele é LISTADO — não excluído", len(conj.duvidosos), 1)
        checa("  e é a Ana Cristina", conj.duvidosos[0]["nome"],
              "ANA CRISTINA JEFFRES PEREIRA - TESTE")
        # Ela é Landing Page, sub_source PosMulheridades, SDR Thobias, Follow 4, telefone de
        # Manaus único na base, 4 mensagens dela. O sufixo " - TESTE" está no nome dela na
        # Exact. O predicado a apagaria de todo relatório, em silêncio.
        afirma("a chave dela NÃO está na cesta EXCLUIR",
               conj.duvidosos[0]["chave"] not in conj.excluir)

        # ⚠️ o `zz` ancorado. Sem a âncora, 48 leads REAIS casam.
        # O predicado roda no Postgres, não no `re` do Python — `\m` (início de palavra) é
        # sintaxe do Postgres e o `re` nem compila. Testar num motor e usar no outro é o
        # jeito de o teste aprovar um predicado que o banco lê de outro jeito.
        async def casa(nome):
            return (await db.execute(text(
                "SELECT lower(translate(:n, :de, :para)) ~ :pred"),
                {"n": nome, "de": R.ACENTOS_DE, "para": R.ACENTOS_PARA,
                 "pred": R.PREDICADO_TESTE})).scalar()

        for real_ in ("Pozzebon", "Rizzato", "Azzi", "Mazzeo", "Lanzzarin", "andrezza",
                      "Garbazza", "Pezzi"):
            afirma(f"  `{real_}` NÃO casa (era o bug do zz sem âncora: 48 pessoas reais)",
                   not await casa(real_))
        for teste_ in ("zzz teste", "ZZ TESTE ChangeFunnel - ignorar", "John Doe",
                       "Álefe Guimel Lins Barbosa"):
            afirma(f"  `{teste_}` casa", bool(await casa(teste_)))

        j = await R.jornada(COORTE, db)
        nomes = {l["nome"] for l in j["tabela"]}
        afirma("o Thobias Justino França NÃO está entre os 45",
               not any("Thobias Justino" in (n or "") for n in nomes),
               f"encontrado em {[n for n in nomes if 'Thobias' in (n or '')]}")

        # ==================================================================================
        print("\n4) O `''` não funde conversas — `chave_telefone` diz que ele nunca casa")
        #
        # Números estrangeiros (`447834239129`, `245956444415`) e lixo de digitação reduzem
        # a `''`. Num GROUP BY, `''` casa com `''`: todos viram UMA conversa. Foi assim que
        # o invariante de silêncio acusou 1 conversa parada que era a soma de vários
        # números, e o funil contou 334 pessoas onde havia 127.

        colidem = (await db.execute(text(
            f"SELECT count(*) FROM messages m WHERE {R.chave_sql('m.contact_wa_id')} = ''"
        ))).scalar()
        threads = (await db.execute(text(
            f"SELECT count(DISTINCT {R.CHAVE_MSG}) FROM messages m "
            f"WHERE {R.chave_sql('m.contact_wa_id')} = ''"))).scalar()
        afirma(f"as {colidem} mensagens de chave ilegível viram {threads} threads, não 1",
               threads > 1 or colidem <= 1, f"colidem={colidem} threads={threads}")

        # ==================================================================================
        print("\n5) Os invariantes de saúde")

        r_ia = await R.ia("30d", db)
        checa("silêncio em etapa ativa = 0 (margem de 15 min)",
              m(r_ia, "saude_silencio")["valor"], 0)
        checa("  a margem é 15 min, não 10 — p99 do agente é 14,3 min",
              R.MARGEM_SILENCIO, timedelta(minutes=15))
        # `sem_resposta_do_agente` NÃO é 0 e isso NÃO é regressão: há um único caso,
        # 5598984703419 em 29/08 09:37, que o RECON_28/08 §1.10 previu ("o primeiro vence
        # amanhã"). O teste trava o número em 1 — um SEGUNDO caso é que seria notícia.
        checa("`sem_resposta_do_agente` continua no único caso conhecido (29/08)",
              m(r_ia, "saude_sem_resposta_agente")["valor"], 1)

        # ==================================================================================
        print("\n6) Reprodução: a coorte congelada da jornada")

        checa("agendaram = 45", m(j, "agendaram")["n"], 45)
        checa("  IA 9 · landing page 36", m(j, "agendaram")["valor"],
              {"ia": 9, "landing_page": 36})
        checa("  processoseletivo@ 25", m(j, "agendaram")["por_consultora"]
              ["processoseletivo@cenatcursos.com.br"]["agendou"], 25)
        checa("  comercial@ 20", m(j, "agendaram")["por_consultora"]
              ["comercial@cenatcursos.com.br"]["agendou"], 20)
        checa("atravessaram para vendas = 10", m(j, "chegou_em_vendas")["n"], 10)
        checa("  e são {ia: 3, landing_page: 7} — a emenda corrigiu os dois campos",
              m(j, "chegou_em_vendas")["valor"], {"ia": 3, "landing_page": 7})
        da_ia = sorted(x["nome"].split()[0] for x in m(j, "chegou_em_vendas")["lista"]
                       if x["origem"] == "ia")
        checa("  os três da IA são Luigi, Alexandra e Kaylla", da_ia,
              ["Alexandra", "Kaylla", "Luigi"])
        checa("vendas rastreáveis = 28", m(j, "vendidos_rastreaveis")["valor"], 28)
        checa("  sobre 1176 vendidos", m(j, "vendidos_rastreaveis")["n"], 1176)
        afirma("  e a limitação PROÍBE o percentual sobre 1176",
               "NÃO calcule percentual" in m(j, "vendidos_rastreaveis")["limitacao"])
        checa("compareceu é não medível — nunca 0",
              (m(j, "compareceu")["valor"], m(j, "compareceu")["confianca"]),
              (None, "nao_medivel"))

        # ==================================================================================
        print("\n7) As duas etapas homônimas entram as DUAS na guarda")
        #
        # `Reagendamento` e `Reagendamento.` (com ponto) são etapas distintas do funil 18535.
        # Já inflaram uma conversão de 6 para 18. A guarda é uma constante nomeada.

        existem = {r[0] for r in (await db.execute(text(
            "SELECT DISTINCT stage_de FROM exact_stage_events "
            "WHERE stage_de ILIKE '%eagendament%'"))).all()}
        checa("as duas grafias existem no banco", sorted(existem),
              ["Reagendamento", "Reagendamento."])
        for etapa in R.ETAPAS_REAGENDAMENTO:
            barra = (await db.execute(text(
                f"SELECT {R._GUARDA_REAGENDAMENTO.replace('e.stage_de', ':s')}"),
                {"s": etapa})).scalar()
            afirma(f"  a guarda barra `{etapa}`", barra is False)
        passa = (await db.execute(text(
            f"SELECT {R._GUARDA_REAGENDAMENTO.replace('e.stage_de', ':s')}"),
            {"s": "Follow 1"})).scalar()
        afirma("  e deixa passar `Follow 1`", passa is True)

        # ==================================================================================
        print("\n8) Toda query de funil filtra funnel_id explicitamente")
        #
        # `INGEST_FUNNEL_IDS` está VAZIO: `exact_leads` tem os 9 299 leads de TODOS os funis,
        # incluindo Intercâmbio (2 493) e Congresso (97). Uma query que esquecer o filtro
        # conta 9 300 onde deveria contar 3 800, sem erro visível.

        total = (await db.execute(text("SELECT count(*) FROM exact_leads"))).scalar()
        pos = (await db.execute(text(
            "SELECT count(*) FROM exact_leads WHERE funnel_id = :f"), {"f": R.FUNIL_POS})).scalar()
        afirma(f"a base tem {total} leads e só {pos} no funil de pós — o filtro importa",
               total > pos * 1.5)
        for nome, sql in (("SQL_REUNIOES", R.SQL_REUNIOES),
                          ("SQL_VENDIDOS_RASTREAVEIS", R.SQL_VENDIDOS_RASTREAVEIS)):
            afirma(f"  {nome} filtra funnel_id", "funnel_id = :" in sql)

        # ==================================================================================
        print("\n9) Seção que estoura devolve erro tratado")

        quebrado = MagicMock()
        quebrado.execute = AsyncMock(side_effect=RuntimeError("banco caiu"))
        R._TESTE_CACHE = None
        ruim = await R.resumo("30d", quebrado)
        checa("a rota não propaga a exceção", ruim["secao"], "resumo")
        checa("  e diz o motivo", ruim["erro"]["tipo"], "RuntimeError")
        checa("  com métricas vazias, não zeradas", ruim["metricas"], [])
        ok = await R.jornada("30d", db)          # a vizinha continua de pé
        afirma("a seção vizinha continua respondendo", "erro" not in ok)

        # ==================================================================================
        print("\n10) O orçamento de 2 s")

        R._TESTE_CACHE = None
        t = time.monotonic()
        primeira = [await f("30d", db) for f in (R.resumo, R.ia, R.humano, R.atritos, R.jornada)]
        ms1 = (time.monotonic() - t) * 1000
        t = time.monotonic()
        for f in (R.resumo, R.ia, R.humano, R.atritos, R.jornada):
            await f("30d", db)
        ms2 = (time.monotonic() - t) * 1000
        print(f"      primeira abertura (sem cache de chaves): {ms1:.0f} ms")
        print(f"      seguintes (cache quente, TTL {R.TTL_TESTE} s): {ms2:.0f} ms")
        afirma("painel completo abaixo de 2 s, em série", ms1 < 2000, f"{ms1:.0f} ms")
        afirma("  e o cache das chaves de teste corta a segunda", ms2 < ms1)
        afirma("nenhuma seção veio com erro", not any("erro" in x for x in primeira))


asyncio.run(principal())
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ Todos passaram. Somente leitura — nada foi gravado.")
