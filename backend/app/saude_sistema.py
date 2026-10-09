"""Saúde do sistema: pool, transação ociosa e espelho de reuniões (09/10/2026).

POR QUE EXISTE. Em 07/10 18:29 UTC uma transação do webhook ficou `idle in transaction`
segurando o lock de um contato (INCIDENTE_LOGIN_POOL_20261009.md). Por 47h as conexões foram
se acumulando atrás dela até as 40 do pool acabarem, e só se soube quando o login caiu. O
`reuniao_sync` ficou parado o tempo todo, e 4 reuniões perderam a régua. Nada disso alertava.

O QUE MEDE (`verificar`), e o que derruba para 503:
  * pool: `checkedout` / capacidade (20 + 20). Acima de 80% -> 503.
  * pool utilizável: tira UMA conexão do pool e roda `SELECT 1`. Não conseguiu em 10 s
    (`pool_timeout`) -> 503. É a pergunta que o login faz.
  * transação ociosa: a mais antiga `idle in transaction` do role da app em pg_stat_activity.
    Ociosa (now() - state_change) há mais de 5 min -> 503.
  * reuniao_sync: `reuniao_sync_cursor.ultimo_ciclo_em` há mais de 30 min (o ciclo é de 10)
    -> 503. Só vale com `REUNIAO_SYNC_ENABLED` ligado: desligado ele não deveria rodar.

CONEXÃO FORA DO POOL. O diagnóstico (pg_stat_activity, cursor) e a Notification do vigia vão
por um engine `NullPool` próprio: quando o pool está esgotado é justamente quando mais
precisamos ler o banco e registrar o alerta, e pedir uma conexão ao pool cheio só devolveria
o mesmo timeout. Cada uso abre e fecha UMA conexão; o Postgres tem folga (100 - 40 da app).

O VIGIA (`vigia_saude_job`, a cada 5 min) chama o MESMO `verificar`. No 503: Notification para
a gestão (`GESTOR_USER_ID`) e o template `alerta_cenat_hub` para `ALERTA_TELEFONE`. Alerta na
transição e repete a cada hora enquanto continuar fora; avisa também quando volta. O estado
fica em memória: um restart com o problema ainda presente alerta de novo, que é o lado certo
de errar.

O WhatsApp vai por `aviso_sdr.enviar_aviso` (número interno, sem contato, sem guard), o mesmo
caminho dos avisos ao SDR. Não depende do pool: o canal é lido pela conexão fora do pool.
"""
import asyncio
import os
import time
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import DATABASE_URL, engine
from app.nat_guard import GESTOR_USER_ID, _agora_sp

INTERVALO_SEGUNDOS = 300            # vigia: 5 min
LIMITE_POOL = 0.80                  # fração de checkedout sobre a capacidade
LIMITE_OCIOSA_S = 5 * 60            # transação idle in transaction
LIMITE_REUNIAO_SYNC_S = 30 * 60     # ultimo_ciclo_em (ciclo de 10 min)
REALERTA_S = 60 * 60                # repete o alerta enquanto continuar fora
CACHE_S = 10                        # /health é público: no máximo 1 diagnóstico a cada 10 s

TEMPLATE_ALERTA = "alerta_cenat_hub"
# {{1}} = o motivo, numa linha. A Meta recusa variável no fim do corpo (subcode 2388299,
# 07/10), por isso a frase fixa depois dela.
CORPO_ALERTA = "Alerta do Cenat Hub: {{1}}. Confira o servidor assim que puder."
EXEMPLO_ALERTA = ["pool de conexões 38/40 (95%)"]

TIPO_CAIU = "saude_sistema_down"    # notifications.type é VARCHAR(30)
TIPO_VOLTOU = "saude_sistema_up"

# Diagnóstico fora do pool. statement_timeout curto: um health não pode pendurar.
_engine_direto = create_async_engine(
    DATABASE_URL, poolclass=NullPool,
    connect_args={"timeout": 5, "server_settings": {
        "lock_timeout": "5s", "statement_timeout": "5s", "application_name": "saude_sistema"}},
)

_cache: tuple[float, dict] | None = None
_lock = asyncio.Lock()


def _capacidade() -> int:
    return engine.pool.size() + engine.pool._max_overflow


async def _checar_pool() -> dict:
    """Tira uma conexão do pool e roda SELECT 1. Devolve também o lock_timeout da sessão."""
    inicio = time.monotonic()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            lock_timeout = (await conn.execute(text("SHOW lock_timeout"))).scalar()
        return {"ok": True, "ms": round((time.monotonic() - inicio) * 1000),
                "lock_timeout": lock_timeout}
    except Exception as e:
        return {"ok": False, "ms": round((time.monotonic() - inicio) * 1000),
                "erro": f"{type(e).__name__}: {e}"[:200]}


async def _diagnostico_direto() -> dict:
    from app.reuniao_sync import flag_ligada
    out: dict = {}
    async with _engine_direto.connect() as conn:
        r = (await conn.execute(text("""
            SELECT count(*) AS n,
                   extract(epoch FROM max(now() - state_change))::int AS ociosa_s,
                   extract(epoch FROM max(now() - xact_start))::int AS transacao_s
            FROM pg_stat_activity
            WHERE usename = current_user AND datname = current_database()
              AND state IN ('idle in transaction', 'idle in transaction (aborted)')
        """))).first()
        out["ociosas"] = {"quantidade": r.n, "mais_antiga_ociosa_s": r.ociosa_s,
                          "mais_antiga_transacao_s": r.transacao_s}
        if flag_ligada():
            ultimo = (await conn.execute(text(
                "SELECT ultimo_ciclo_em FROM reuniao_sync_cursor WHERE id = 1"))).scalar()
            idade = int((_agora_sp() - ultimo).total_seconds()) if ultimo else None
            out["reuniao_sync"] = {"ligado": True,
                                   "ultimo_ciclo_em": ultimo.isoformat() if ultimo else None,
                                   "idade_s": idade}
        else:
            out["reuniao_sync"] = {"ligado": False}
    return out


async def _verificar_agora() -> dict:
    cap = _capacidade()
    checkedout = engine.pool.checkedout()
    pool = {"checkedout": checkedout, "overflow": max(engine.pool.overflow(), 0),
            "capacidade": cap, "uso": round(checkedout / cap, 2)}
    pool["teste"] = await _checar_pool()
    try:
        diag = await _diagnostico_direto()
    except Exception as e:
        diag = {"erro": f"{type(e).__name__}: {e}"[:200]}

    problemas = []
    if pool["uso"] > LIMITE_POOL:
        problemas.append(f"pool de conexões {checkedout}/{cap} ({pool['uso']:.0%})")
    if not pool["teste"]["ok"]:
        problemas.append("pool não entregou conexão em 10s")
    if "erro" in diag:
        problemas.append("banco não respondeu ao diagnóstico")
    else:
        o = diag["ociosas"]
        if (o["mais_antiga_ociosa_s"] or 0) > LIMITE_OCIOSA_S:
            problemas.append(f"transação ociosa há {o['mais_antiga_ociosa_s'] // 60} min")
        rs = diag["reuniao_sync"]
        if rs["ligado"] and (rs["idade_s"] is None or rs["idade_s"] > LIMITE_REUNIAO_SYNC_S):
            problemas.append("espelho de reuniões parado há "
                             + (f"{rs['idade_s'] // 60} min" if rs["idade_s"] is not None
                                else "tempo indeterminado"))
    return {"status": "degradado" if problemas else "online", "problemas": problemas,
            "pool": pool, **diag, "medido_em": datetime.utcnow().isoformat() + "Z"}


async def verificar(*, usar_cache: bool = True) -> dict:
    """O check de /health e do vigia. Nunca levanta; `status` é `online` ou `degradado`."""
    global _cache
    async with _lock:
        if usar_cache and _cache and time.monotonic() - _cache[0] < CACHE_S:
            return _cache[1]
        try:
            r = await asyncio.wait_for(_verificar_agora(), timeout=20)
        except Exception as e:
            r = {"status": "degradado", "problemas": [f"check não terminou ({type(e).__name__})"],
                 "medido_em": datetime.utcnow().isoformat() + "Z"}
        _cache = (time.monotonic(), r)
        return r


# ==========================================================================================
# O VIGIA
# ==========================================================================================

_estado = {"fora": False, "ultimo_alerta": 0.0}


def telefone_alerta() -> str | None:
    from app.agendamento.consultoras import normalizar_telefone
    return normalizar_telefone(os.getenv("ALERTA_TELEFONE", "") or "") or None


async def _alertar(tipo: str, titulo: str, motivo: str) -> None:
    """Notification + WhatsApp, os dois pela conexão fora do pool. Nunca levanta."""
    from app import aviso_sdr
    from app.models import Notification
    try:
        async with AsyncSession(_engine_direto, expire_on_commit=False) as db:
            db.add(Notification(user_id=GESTOR_USER_ID, contact_wa_id=None, type=tipo,
                                ref=None, title=titulo, body=motivo))
            await db.commit()
        print(f"🔔 Saúde do sistema: {tipo} registrado para a gestão (id={GESTOR_USER_ID})")
    except Exception as e:
        print(f"⚠️  Saúde do sistema: Notification {tipo} NÃO gravada "
              f"({type(e).__name__}: {e}) — motivo: {motivo}")
    destino = telefone_alerta()
    if not destino:
        print("⚠️  Saúde do sistema: ALERTA_TELEFONE vazio — WhatsApp não enviado")
        return
    try:
        async with AsyncSession(_engine_direto, expire_on_commit=False) as db:
            await aviso_sdr.enviar_aviso(TEMPLATE_ALERTA, [motivo], [destino], db)
    except Exception as e:
        print(f"⚠️  Saúde do sistema: WhatsApp de alerta falhou ({type(e).__name__}: {e})")


async def avaliar() -> dict:
    """Um ciclo do vigia. Alerta na transição, repete a cada hora fora, avisa a volta."""
    r = await verificar(usar_cache=False)
    agora = time.monotonic()
    motivo = "; ".join(r["problemas"])
    if r["status"] != "online":
        if not _estado["fora"] or agora - _estado["ultimo_alerta"] >= REALERTA_S:
            await _alertar(TIPO_CAIU, "Sistema degradado", motivo)
            _estado["ultimo_alerta"] = agora
        _estado["fora"] = True
    elif _estado["fora"]:
        p = r["pool"]
        await _alertar(TIPO_VOLTOU, "Sistema normalizado",
                       f"normalizou, pool {p['checkedout']}/{p['capacidade']}")
        _estado["fora"] = False
    return r


async def vigia_saude_job():
    """Laço de 5 min. Dorme antes de trabalhar, como os outros jobs. Batimento sempre no log."""
    while True:
        await asyncio.sleep(INTERVALO_SEGUNDOS)
        try:
            r = await avaliar()
            p = r.get("pool", {})
            o = r.get("ociosas", {})
            print(f"⏱️  Saúde do sistema: {r['status']} — pool {p.get('checkedout')}/"
                  f"{p.get('capacidade')}, ociosa mais antiga {o.get('mais_antiga_ociosa_s')}s"
                  + (f" — {'; '.join(r['problemas'])}" if r["problemas"] else ""))
        except Exception as e:
            print(f"❌ Erro no vigia_saude_job: {type(e).__name__}: {e}")
