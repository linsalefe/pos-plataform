"""O painel de Atendimento: as regras que não podem mudar em silêncio.

    cd backend && venv/bin/python test_atendimento.py

Duas partes, e nenhuma escreve no banco de produção:

  A. FUNÇÕES PURAS (sem banco): SLA corrido × expediente, janela de 24 h nos limiares
     exatos, dono da pergunta, filtro de pendentes, variação, início da pergunta atual.
  B. SQL contra TABELAS TEMPORÁRIAS dentro de uma transação desfeita no fim. `messages`,
     `contacts` e `users` temporárias SOMBREIAM as reais (o Postgres procura `pg_temp`
     primeiro), então `SQL_PERGUNTAS` roda o texto de produção sobre um cenário montado
     à mão: rajada conta uma, template não é resposta, IA por `nat_etapa`, predicado de
     teste exclui. Ao final, `ROLLBACK`: as temporárias somem e nada tocou as tabelas reais.
  C. LEITURA da base real: a mediana daqui é a mesma do /relatorios/humano.
"""
import asyncio
from datetime import datetime, timedelta

from sqlalchemy import text

from app import atendimento_routes as A
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


def linha(ts, *, resp=None, etapa_resp=None, etapa_antes=None, tpl=None, ultimo=None,
          dono_id=None, sent_by=None):
    """Uma linha como o `SQL_PERGUNTAS` devolve."""
    return {"thr": "11999990000", "wa": "5511999990000", "ts": ts, "ultimo_inb": ultimo or ts,
            "ts_resp": resp, "ts_tpl": tpl, "etapa_antes": etapa_antes,
            "etapa_resp": etapa_resp, "sent_by": sent_by, "sent_by_nome": None,
            "dono_id": dono_id, "dono_nome": None}


D = datetime(2026, 10, 7)          # uma quarta-feira qualquer


# ==========================================================================================
# A. FUNÇÕES PURAS
# ==========================================================================================
def parte_a():
    print("\nA1. SLA corrido × expediente: pergunta às 23h respondida às 8h30")
    p = A.montar(linha(D.replace(hour=23), resp=(D + timedelta(days=1)).replace(hour=8, minute=30)),
                 D + timedelta(days=2))
    checa("espera corrida = 9 h 30", p.espera, 9.5 * 3600)
    checa("espera em expediente = 30 min", p.espera_exp, 1800.0)
    checa("fora do SLA no corrido", A.no_sla(p, False), False)
    checa("dentro do SLA no expediente", A.no_sla(p, True), True)

    print("\nA2. expediente: bordas 8h00 e 20h30")
    checa("20h30 às 8h00 do dia seguinte = 0", A.segundos_expediente(
        D.replace(hour=20, minute=30), (D + timedelta(days=1)).replace(hour=8)), 0.0)
    checa("19h às 21h = 1 h 30", A.segundos_expediente(D.replace(hour=19), D.replace(hour=21)),
          5400.0)
    checa("b <= a = 0", A.segundos_expediente(D.replace(hour=10), D.replace(hour=9)), 0.0)

    print("\nA3. janela de 24 h nos limiares exatos (da ÚLTIMA mensagem do lead)")
    ult = D.replace(hour=10)
    checa("19h59m59s = aberta", A.estado_janela(ult, ult + timedelta(hours=20, seconds=-1)), "aberta")
    checa("20h00 = perto", A.estado_janela(ult, ult + timedelta(hours=20)), "perto")
    checa("23h59m59s = perto", A.estado_janela(ult, ult + timedelta(hours=24, seconds=-1)), "perto")
    checa("24h00 = expirada", A.estado_janela(ult, ult + timedelta(hours=24)), "expirada")

    print("\nA4. janela perdida no período")
    fim = D + timedelta(days=3)
    checa("sem resposta, 24 h passadas -> perdida",
          A.janela_perdida(A.montar(linha(D), fim), fim), True)
    checa("resposta em 25 h -> perdida",
          A.janela_perdida(A.montar(linha(D, resp=D + timedelta(hours=25)), fim), fim), True)
    checa("resposta em 23 h -> não perdida",
          A.janela_perdida(A.montar(linha(D, resp=D + timedelta(hours=23)), fim), fim), False)
    checa("janela ainda aberta no fim do período -> não conta",
          A.janela_perdida(A.montar(linha(fim - timedelta(hours=3)), fim), fim), False)

    print("\nA5. quem respondeu e de quem era a pergunta")
    fim = D + timedelta(days=1)
    checa("resposta com nat_etapa = ia",
          A.montar(linha(D, resp=D + timedelta(seconds=5), etapa_resp="qualif_conversa"), fim)
          .respondido_por, "ia")
    checa("resposta sem nat_etapa = time",
          A.montar(linha(D, resp=D + timedelta(minutes=5)), fim).respondido_por, "time")
    checa("sem resposta, última nossa era do agente = dona ia",
          A.montar(linha(D, etapa_antes="nat_b_abertura"), fim).dono, "ia")
    checa("sem resposta, última nossa era humana = dona time",
          A.montar(linha(D), fim).dono, "time")

    print("\nA6. template não é resposta, mas é contado à parte")
    fim = D + timedelta(days=2)
    ps = [A.montar(linha(D, tpl=D + timedelta(hours=1)), fim),
          A.montar(linha(D, resp=D + timedelta(minutes=10)), fim)]
    ag = A.agregar(ps, fim)
    checa("1 respondida de 2", (ag["respondidas"], ag["perguntas"]), (1, 2))
    checa("1 recebeu só template", ag["so_template"], 1)
    checa("% SLA = 50 (a do template conta como falha)", ag["corrido"]["pct_sla"], 50.0)

    print("\nA7. pergunta de agora há pouco não entra no SLA")
    fim = D.replace(hour=12)
    p = A.montar(linha(fim - timedelta(minutes=30)), fim)
    checa("não vencida no corrido", A.vencida(p, fim, False), False)
    checa("sem denominador -> pct None", A.agregar([p], fim)["corrido"]["pct_sla"], None)

    print("\nA8. pendentes: quem=time esconde agente e régua")
    itens = [{"dono_inbound": d, "sdr_id": 5, "horas_esperando": 3.0,
              "esperando_desde": f"2026-10-07T0{i}:00"} for i, d in
             enumerate(("sdr", "agente", "regua", "sdr"))]
    checa("time -> só sdr", [i["dono_inbound"] for i in A.filtrar_pendentes(itens, "time", None, 0)],
          ["sdr", "sdr"])
    checa("ia -> agente e régua",
          sorted(i["dono_inbound"] for i in A.filtrar_pendentes(itens, "ia", None, 0)),
          ["agente", "regua"])
    checa("ambos -> 4", len(A.filtrar_pendentes(itens, "ambos", None, 0)), 4)
    checa("min_horas corta", len(A.filtrar_pendentes(itens, "ambos", None, 4)), 0)
    checa("ordem do mais antigo",
          [i["esperando_desde"] for i in A.filtrar_pendentes(itens, "ambos", None, 0)],
          sorted(i["esperando_desde"] for i in itens))

    print("\nA9. classificar_pendente: dono pelo estado, régua e agente pela chave tolerante")
    agora = D.replace(hour=15)
    base = {"wa": "5582998307979", "inbs": [agora - timedelta(hours=1)],
            "ultimo_inb": agora - timedelta(hours=1), "ultima_msg": "oi", "so_template": False,
            "primeira_sem_resposta": None, "nome": "X", "dono_id": None, "dono_nome": None}
    k = chave_telefone("558298307979")          # a OUTRA grafia: tem de casar igual
    checa("agente ativo -> agente",
          A.classificar_pendente(base, agora, {k: "aguardando_ano"}, {})["dono_inbound"], "agente")
    checa("régua viva -> regua",
          A.classificar_pendente(base, agora, {}, {k: "confirmacao"})["dono_inbound"], "regua")
    c = A.classificar_pendente(base, agora, {}, {})
    checa("nenhum -> sdr, 'sem dono'", (c["dono_inbound"], c["sdr_nome"]), ("sdr", "sem dono"))
    checa("automação há 1 h = anomalia",
          A.classificar_pendente(base, agora, {k: "x"}, {})["anomalia"], True)

    print("\nA10. início da pergunta atual: volta depois de 24 h recomeça")
    t0 = datetime(2026, 3, 27, 10, 41)
    t1 = datetime(2026, 10, 8, 19, 1)
    checa("caso real de 13/10 (27/03 e 08/10) -> 08/10", A.inicio_da_pergunta([t0, t1]), t1)
    checa("rajada de 3 em 2 h -> a primeira",
          A.inicio_da_pergunta([t1, t1 + timedelta(hours=1), t1 + timedelta(hours=2)]), t1)

    print("\nA11. variação contra o período anterior")
    checa("20 contra 10 = +100%", A.variacao(20, 10), {"anterior": 10, "delta": 10, "pct": 100.0})
    checa("anterior 0 -> pct None", A.variacao(5, 0)["pct"], None)
    checa("sem base -> delta None", A.variacao(None, 3)["delta"], None)
    p = R.Periodo(datetime(2026, 9, 13), datetime(2026, 10, 13, 15), 30, "30d")
    ant = A.periodo_anterior(p)
    checa("anterior tem a mesma duração", ant.ate - ant.de, p.ate - p.de)
    checa("anterior termina onde o atual começa", ant.ate, p.de)

    print("\nA12. histograma: faixas fechadas à direita")
    fim = D + timedelta(days=2)
    ps = [A.montar(linha(D, resp=D + timedelta(minutes=m)), fim) for m in (15, 16, 120, 121, 1441)]
    h = {f["faixa"]: f["n"] for f in A.histograma(ps, False)}
    checa("15 min cai em 'até 15 min'", h["até 15 min"], 1)
    checa("2 h cai em '1 h a 2 h'", h["1 h a 2 h"], 1)
    checa("24 h 01 cai em 'mais de 24 h'", h["mais de 24 h"], 1)


# ==========================================================================================
# B. SQL SOBRE TABELAS TEMPORÁRIAS (transação desfeita)
# ==========================================================================================
async def parte_b():
    print("\nB. SQL_PERGUNTAS sobre um cenário montado (temporárias, ROLLBACK no fim)")
    async with async_session() as db:
        try:
            for ddl in (
                "CREATE TEMP TABLE messages (id bigint, contact_wa_id varchar(20), "
                "direction varchar(10), message_type varchar(20), content text, "
                "timestamp timestamp, nat_etapa text, sent_by int) ON COMMIT DROP",
                "CREATE TEMP TABLE contacts (wa_id varchar(20), name text, assigned_to int) "
                "ON COMMIT DROP",
                "CREATE TEMP TABLE users (id int, name text) ON COMMIT DROP",
            ):
                await db.execute(text(ddl))
            await db.execute(text("INSERT INTO users VALUES (5, 'SDR Teste')"))

            n = 0

            async def msg(wa, minutos, direcao, tipo="text", etapa=None, autor=None):
                nonlocal n
                n += 1
                await db.execute(text(
                    "INSERT INTO messages VALUES (:id, :wa, :d, :t, 'x', :ts, :e, :a)"),
                    {"id": n, "wa": wa, "d": direcao, "t": tipo,
                     "ts": D + timedelta(minutes=minutos), "e": etapa, "a": autor})

            # 1) rajada de 3 do lead, resposta do time em 30 min
            await db.execute(text("INSERT INTO contacts VALUES ('5511911110001', 'R', 5)"))
            for m in (0, 1, 2):
                await msg("5511911110001", m, "inbound")
            await msg("5511911110001", 30, "outbound", autor=5)
            # 2) pergunta, template de disparo, e nada mais
            await db.execute(text("INSERT INTO contacts VALUES ('5511911110002', 'T', 5)"))
            await msg("5511911110002", 0, "inbound")
            await msg("5511911110002", 60, "outbound", tipo="template", autor=5)
            # 3) pergunta respondida pelo agente
            await db.execute(text("INSERT INTO contacts VALUES ('5511911110003', 'I', NULL)"))
            await msg("5511911110003", 0, "inbound")
            await msg("5511911110003", 0.1, "outbound", etapa="qualif_conversa")
            # 4) lead de teste: tem de sumir
            await db.execute(text("INSERT INTO contacts VALUES ('5511911110004', 'zz', 5)"))
            await msg("5511911110004", 0, "inbound")

            p = R.Periodo(D - timedelta(hours=1), D + timedelta(days=2), 2, "teste")
            teste = [chave_telefone("5511911110004")]   # o array que chaves_de_teste daria
            ps = await A.perguntas(db, p, teste)
            por = {x.wa: x for x in ps}

            checa("4 contatos, teste excluído -> 3 perguntas", len(ps), 3)
            checa("rajada de 3 conta UMA pergunta",
                  sum(1 for x in ps if x.wa == "5511911110001"), 1)
            r = por["5511911110001"]
            checa("rajada: resposta em 30 min, pelo time, autor 5",
                  (r.espera, r.respondido_por, r.sent_by), (1800.0, "time", 5))
            checa("rajada: ultimo_inb é a 3ª mensagem", r.ultimo_inb, D + timedelta(minutes=2))
            t = por["5511911110002"]
            checa("template depois da pergunta NÃO é resposta", t.ts_resp, None)
            checa("... mas fica em ts_tpl", t.ts_tpl, D + timedelta(minutes=60))
            i = por["5511911110003"]
            checa("resposta com nat_etapa = ia", i.respondido_por, "ia")
            checa("dono do contato vem de contacts.assigned_to", r.dono_id, 5)
        finally:
            await db.rollback()


# ==========================================================================================
# C. A MESMA MEDIANA QUE /relatorios/humano (leitura da base real)
# ==========================================================================================
async def parte_c():
    print("\nC. mediana do /atendimento == mediana do /relatorios/humano (30 dias)")
    async with async_session() as db:
        teste = await R.chaves_de_teste(db)
        p = A.janela_atendimento("30d", None, None)
        med = {r.quem: (r.n, r.mediana) for r in (await db.execute(
            text(R.SQL_MEDIANA), {"ini": p.de, "fim": p.ate, "teste": teste.array})).all()}
        ps = await A.perguntas(db, p, teste.array)
        for nosso, deles in (("ia", "ia"), ("time", "humano")):
            xs = [x.espera for x in ps if x.respondido_por == nosso]
            n, m = med.get(deles, (0, None))
            checa(f"{nosso}: mesmo N", len(xs), n)
            checa(f"{nosso}: mesma mediana", A.mediana(xs) is None and m is None
                  or abs(A.mediana(xs) - m) < 1e-6, True)
        checa("nenhuma pergunta de lead de teste",
              any(x.thr in teste.excluir for x in ps), False)


async def main():
    parte_a()
    await parte_b()
    await parte_c()
    print(f"\n{'TUDO OK' if not falhas else f'{len(falhas)} FALHA(S): {falhas}'}")


if __name__ == "__main__":
    asyncio.run(main())
