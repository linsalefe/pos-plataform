"""Monitor da PRIMEIRA HORA do agente de qualificação. Só leitura, nada é escrito.

    cd backend && venv/bin/python monitor_qualificacao.py            # última 1h
    cd backend && venv/bin/python monitor_qualificacao.py --horas 3

Existe porque a ativação de 25/08/2026 é a primeira em que o agente fala com lead real, e
"deu certo?" precisa de resposta em números, não de olhar o log passar.

O que ele responde, nesta ordem:
  1. a config está como se espera? (kill switch, corte de data, teto)
  2. a fila do agendador, por kind × status
  3. os estados criados, por etapa e origem
  4. qual template cada lead recebeu (agendado / qualificação / sem formação)
  5. quem respondeu — e se o agente RECONHECEU a thread (a correção do 9º dígito)
  6. transferido_motivo e encerrado_motivo, um por linha
  7. ALERTAS: o que merece desligar a automação

LEADS DE TESTE (`ZZ TESTE`, `TESTE API`) saem das métricas e vão para um bloco à parte.
"""
import asyncio
import re
import sys
from datetime import timedelta
from collections import Counter

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text                                            # noqa: E402

from app.database import async_session                                 # noqa: E402
from app.models import (ACAO_FALHOU, ACAO_PENDENTE,                    # noqa: E402
                        ETAPAS_QUALIFICACAO_ATIVAS)
from app.nat_guard import _agora_sp                                    # noqa: E402
from app.telefone import variantes_wa_id                               # noqa: E402

TESTE = re.compile(r"\bZZ\s*TESTE\b|TESTE API|\bteste\b.*\balefe\b", re.I)
ABERTURAS = ("nat_abertura_agendado", "nat_abertura_qualificacao", "nat_abertura_sem_formacao")
ROTULO = {"nat_abertura_agendado": "T1 já agendado",
          "nat_abertura_qualificacao": "T2 qualificação",
          "nat_abertura_sem_formacao": "T3 sem formação"}


def cab(t):
    print(f"\n{'─' * 78}\n{t}\n{'─' * 78}")


async def main(horas: float) -> int:
    agora = _agora_sp()
    alertas = []
    # DOIS cortes, e a diferença não é preciosismo: `messages.timestamp` e
    # `nat_scheduled_actions.run_at` são NAIVE EM SÃO PAULO (ver o cabeçalho do modelo),
    # enquanto `created_at` nasce de `server_default=func.now()` e é UTC. Usar um só
    # deslocaria uma das duas famílias em 3h — em silêncio, e sempre para menos.
    desde_sp = agora - timedelta(hours=horas)
    desde_utc = desde_sp + timedelta(hours=3)
    vencido_sp = agora - timedelta(minutes=10)
    async with async_session() as db:
        async def q(sql, **p):
            return (await db.execute(text(sql), p)).all()

        print(f"\n{'=' * 78}\nAGENTE DE QUALIFICAÇÃO — janela de {horas:g}h até "
              f"{agora:%d/%m %H:%M} (SP)\n{'=' * 78}")

        # ---------------------------------------------------------------- 1. config
        cab("1. CONFIG")
        cfg = await q("""SELECT qualificacao_enabled, qualificacao_start_at, nat_enabled,
                                max_envios_hora FROM nat_config WHERE id = 1""")
        if not cfg:
            print("  🚨 nat_config id=1 NÃO EXISTE — o agente não roda.")
            alertas.append("nat_config ausente")
        else:
            e, corte, nat, teto = cfg[0]
            print(f"  qualificacao_enabled = {e}   (é o kill switch)")
            print(f"  qualificacao_start_at = {corte}   (leads anteriores não entram)")
            print(f"  nat_enabled = {nat}   ·   max_envios_hora = {teto}")
            if not e:
                alertas.append("qualificacao_enabled=false — o agente está DESLIGADO")

        # ---------------------------------------------------- 2. fila do agendador
        cab("2. FILA DO AGENDADOR (nat_scheduled_actions)")
        fila = await q("""SELECT kind, status, COUNT(*), MIN(run_at), MAX(run_at)
                          FROM nat_scheduled_actions
                          WHERE created_at >= :desde_utc OR run_at >= :desde_dia
                          GROUP BY kind, status ORDER BY kind, status""",
                       desde_utc=desde_utc - timedelta(hours=24),
                       desde_dia=agora.replace(hour=0, minute=0, second=0, microsecond=0))
        if not fila:
            print("  (vazia)")
        for kind, st, n, r0, r1 in fila:
            marca = "  ⚠️" if st == ACAO_FALHOU else ""
            print(f"  {kind:<24} {st:<10} {n:>4}   run_at {r0:%d/%m %H:%M} → {r1:%d/%m %H:%M}{marca}")
            if st == ACAO_FALHOU and n:
                alertas.append(f"{n} ação(ões) '{kind}' com status falhou")
        atrasadas = await q("""SELECT COUNT(*) FROM nat_scheduled_actions
                               WHERE status = :p AND run_at < :vencido""",
                            p=ACAO_PENDENTE, vencido=vencido_sp)
        if atrasadas and atrasadas[0][0]:
            print(f"  ⚠️ {atrasadas[0][0]} pendente(s) com run_at vencido há mais de 10 min")
            alertas.append(f"{atrasadas[0][0]} ação(ões) pendentes atrasadas — job parado?")

        # ---------------------------------- 2b. ações consumidas SEM virar estado
        # A assinatura do descarte silencioso — e depois do Risco 3 ela ficou AFIADA.
        #
        # Antes, `abrir()` saía com `return` mudo em cinco situações e todas viravam
        # `executado`: esta consulta não conseguia separar "descartei o lead" de "não havia
        # o que fazer", e o segundo caso (booking espontâneo de quem já tem estado) entrava
        # aqui como falso positivo. Agora quem decide não agir vira `skipped` COM MOTIVO, e
        # quem não pode agir agora volta a `pendente` com o motivo na linha.
        #
        # Sobrando `executado` sem estado, é bug de verdade: a ação diz que a abertura saiu
        # e não há conversa nenhuma do outro lado. Por isso o alerta ficou mais severo, não
        # menos — ele agora acusa uma coisa só.
        consumidas = await q("""SELECT a.contact_wa_id, a.run_at, a.attempts
                                FROM nat_scheduled_actions a
                                WHERE a.kind = 'iniciar_qualificacao'
                                  AND a.status = 'executado' AND a.run_at >= :desde
                                ORDER BY a.run_at""", desde=desde_sp)
        if consumidas:
            com_estado = {v for r in await q(
                "SELECT contact_wa_id FROM nat_qualificacao_state")
                for v in variantes_wa_id(r[0])}
            perdidas = [r for r in consumidas if r[0] not in com_estado]
            cab("2b. AÇÕES CONSUMIDAS SEM VIRAR ESTADO")
            print(f"  {len(consumidas)} executada(s) · {len(perdidas)} sem estado correspondente")
            for wa, ra, att in perdidas:
                print(f"    ⚠️ {ra:%H:%M} {wa} (tentativas={att}) — 'executado' significa que "
                      f"a abertura SAIU; sem estado, isto é bug, não descarte")
            if perdidas:
                alertas.append(f"{len(perdidas)} abertura(s) EXECUTADA(s) sem criar estado — "
                               f"desde o Risco 3 isto não tem mais causa benigna")

        # -------------------------------- 2b'. as decisões que agora ficam gravadas
        # O outro lado da mesma moeda: com motivo no banco, "quem o agente deixou de fora e
        # por quê" virou uma consulta em vez de uma caçada no log — que é justamente o que
        # não dava para fazer em 25/08, com o journald suprimindo 36 750 linhas por causa do
        # `echo=True` do engine.
        decisoes = await q("""SELECT status, motivo, COUNT(*), MAX(run_at)
                              FROM nat_scheduled_actions
                              WHERE kind = 'iniciar_qualificacao' AND motivo IS NOT NULL
                                AND run_at >= :desde
                              GROUP BY status, motivo ORDER BY 3 DESC""", desde=desde_sp)
        if decisoes:
            cab("2b'. DECISÕES REGISTRADAS (skipped / adiadas)")
            for st, motivo, n, ultimo in decisoes:
                print(f"  {st:<9} {n:>3}x  {motivo[:70]:<70} último {ultimo:%d/%m %H:%M}")
                # Pendente com motivo = fila parada esperando janela. Vale alerta se durar.
                if st == ACAO_PENDENTE and ultimo < vencido_sp:
                    alertas.append(f"{n} abertura(s) adiada(s) há mais de 10 min: {motivo}")

        # ------------------------------------------------- 2c. distância do teto
        if cfg:
            usados = await q("""SELECT COUNT(*) FROM messages
                                WHERE nat_etapa IS NOT NULL AND timestamp >= :h1""",
                             h1=agora - timedelta(hours=1))
            n_env, limite = (usados[0][0] if usados else 0), cfg[0][3]
            print(f"\n  teto por hora: {n_env}/{limite} usados na última hora")
            if limite and n_env >= limite * 0.8:
                alertas.append(f"teto por hora em {n_env}/{limite} — o próximo lead pode "
                               f"ser descartado em silêncio")

        # ------------------------------------------------------------- 3. estados
        cab("3. ESTADOS CRIADOS (nat_qualificacao_state)")
        est = await q("""SELECT s.contact_wa_id, s.etapa, s.origem, s.exact_lead_id,
                                s.created_at, s.transferido_motivo, s.encerrado_motivo,
                                c.name
                         FROM nat_qualificacao_state s
                         LEFT JOIN contacts c ON c.wa_id = s.contact_wa_id
                         WHERE s.created_at >= :desde
                         ORDER BY s.created_at""", desde=desde_utc)
        reais = [r for r in est if not TESTE.search(r[7] or "")]
        testes = [r for r in est if TESTE.search(r[7] or "")]
        print(f"  {len(est)} estado(s) — {len(reais)} reais, {len(testes)} de teste\n")
        if reais:
            for k, n in Counter(r[1] for r in reais).most_common():
                ativa = "ativa" if k in ETAPAS_QUALIFICACAO_ATIVAS else "TERMINAL"
                print(f"    {n:>3}  {k:<28} ({ativa})")
            print()
            for k, n in Counter(r[2] for r in reais).most_common():
                print(f"    {n:>3}  origem={k}")
        if testes:
            print(f"\n  [teste, fora das métricas] "
                  + ", ".join(f"{r[7]} ({r[1]})" for r in testes))

        # ------------------------------------------------------------ 4. templates
        cab("4. TEMPLATE ESCOLHIDO POR LEAD")
        env = await q("""SELECT m.nat_etapa, m.contact_wa_id, m.status, c.name, m.timestamp
                         FROM messages m LEFT JOIN contacts c ON c.wa_id = m.contact_wa_id
                         WHERE m.direction = 'outbound' AND m.nat_etapa = ANY(:ab)
                           AND m.timestamp >= :desde
                         ORDER BY m.timestamp""",
                      ab=list(ABERTURAS), desde=desde_sp)
        env_reais = [r for r in env if not TESTE.search(r[3] or "")]
        if not env_reais:
            print("  nenhuma abertura enviada na janela")
        for k, n in Counter(r[0] for r in env_reais).most_common():
            print(f"    {n:>3}  {ROTULO.get(k, k)}")
        ruins = [r for r in env_reais if r[2] in ("failed", "undelivered")]
        if ruins:
            print(f"\n  ⚠️ {len(ruins)} abertura(s) com status de FALHA na Meta:")
            for r in ruins[:8]:
                print(f"      {r[4]:%H:%M} {r[1]} {r[3]} — {r[2]}")
            alertas.append(f"{len(ruins)} abertura(s) recusada(s) pela Meta")
        entregues = Counter(r[2] for r in env_reais)
        if env_reais:
            print(f"\n  status na Meta: {dict(entregues)}")

        # ------------------------- 5. respostas e reconhecimento (correção do 9º dígito)
        cab("5. RESPOSTAS — E SE O AGENTE RECONHECEU A THREAD")
        est_map = {}
        for r in est:
            for v in variantes_wa_id(r[0]):
                est_map[v] = r
        resp = await q("""SELECT m.contact_wa_id, m.content, m.timestamp, m.message_type,
                                 c.name
                          FROM messages m LEFT JOIN contacts c ON c.wa_id = m.contact_wa_id
                          WHERE m.direction = 'inbound' AND m.timestamp >= :desde
                          ORDER BY m.timestamp""",
                       desde=desde_sp)
        do_agente = [r for r in resp if r[0] in est_map]
        print(f"  {len(resp)} inbound na janela · {len(do_agente)} de contato com estado do agente")
        gemeo = 0
        for wa, cont, ts, tipo, nome in do_agente:
            e = est_map[wa]
            via = ""
            if e[0] != wa:
                gemeo += 1
                via = f"  ⟵ RECONHECIDO PELO GÊMEO (estado em {e[0]})"
            marca = " [TESTE]" if TESTE.search(nome or "") else ""
            print(f"    {ts:%H:%M} {wa} {(nome or '?')[:22]:<22} [{e[1]}]{marca}")
            print(f"           {(cont or '')[:90]}{via}")
        if gemeo:
            print(f"\n  ✅ {gemeo} thread(s) só foram reconhecidas por causa da correção "
                  f"do 9º dígito — com `==` teriam sido ignoradas.")
        orfas = [r for r in resp if r[0] not in est_map
                 and any(v in est_map for v in variantes_wa_id(r[0]))]
        if orfas:
            print(f"  🚨 {len(orfas)} resposta(s) que o mapa tolerante NÃO cobriu")
            alertas.append("resposta não reconhecida apesar da tolerância")

        # -------------------------------------------------------- 6. desfechos
        cab("6. TRANSFERÊNCIAS E ENCERRAMENTOS")
        desf = [r for r in est if r[5] or r[6]]
        if not desf:
            print("  nenhum")
        for r in desf:
            tipo = "transferido" if r[5] else "encerrado"
            print(f"  {r[4]:%H:%M} {r[0]} {(r[7] or '?')[:24]:<24} {tipo}: {r[5] or r[6]}")

        # ---------------------------------------------------------- 7. alertas
        cab("7. VEREDITO")
        if alertas:
            print("  🚨 DESLIGAR E INVESTIGAR:")
            for a in alertas:
                print(f"     · {a}")
            print("\n     venv/bin/python desligar_qualificacao.py --sim-desliga")
            return 1
        print("  ✅ nada anômalo na janela.")
        return 0


if __name__ == "__main__":
    h = 1.0
    if "--horas" in sys.argv:
        h = float(sys.argv[sys.argv.index("--horas") + 1])
    sys.exit(asyncio.run(main(h)))
