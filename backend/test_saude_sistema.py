"""Saúde do sistema: GET /health e vigia (09/10/2026, incidente do pool).

    cd backend && venv/bin/python test_saude_sistema.py

Roda contra o banco real, só LENDO: a transação ociosa de teste é um `SELECT 1` em rollback, e
o envio/Notification do vigia é dublê. NADA sai daqui.

O QUE ESTE TESTE PROVA
  1. sistema saudável -> `online`, e a conexão do pool tem lock_timeout=30s
  2. transação `idle in transaction` além do limite -> `degradado`
  3. pool acima do limite -> `degradado`
  4. pool ESGOTADO de verdade (engine de 1 conexão, presa) -> `degradado`, e o diagnóstico
     fora do pool continua respondendo (é o cenário de 09/10)
  5. reuniao_sync parado além do limite -> `degradado`
  6. vigia: alerta na transição, NÃO repete no ciclo seguinte, avisa a volta
"""
import asyncio
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app import saude_sistema as s
from app.database import DATABASE_URL

falhas = []


def checa(rotulo, ok, detalhe=None):
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        falhas.append(rotulo)
        print(f"      {detalhe!r}")


async def main():
    print("1. saudável")
    r = await s.verificar(usar_cache=False)
    checa("status online", r["status"] == "online", r)
    checa("lock_timeout da sessão do pool = 30s", r["pool"]["teste"].get("lock_timeout") == "30s", r)

    print("2. transação ociosa")
    outro = create_async_engine(DATABASE_URL)
    async with outro.connect() as conn:
        await conn.execute(text("SELECT 1"))          # abre a transação e fica ocioso
        await asyncio.sleep(3)
        with patch.object(s, "LIMITE_OCIOSA_S", 1):
            r = await s.verificar(usar_cache=False)
        await conn.rollback()
    checa("degradado com transação ociosa", r["status"] == "degradado"
          and any("ociosa" in p for p in r["problemas"]), r.get("problemas"))
    checa("idade medida >= 3s", (r["ociosas"]["mais_antiga_ociosa_s"] or 0) >= 3, r["ociosas"])

    print("3. pool acima do limite")
    with patch.object(s, "LIMITE_POOL", -1):
        r = await s.verificar(usar_cache=False)
    checa("degradado com pool cheio", any("pool de conexões" in p for p in r["problemas"]), r)

    print("4. pool esgotado de verdade")
    mini = create_async_engine(DATABASE_URL, pool_size=1, max_overflow=0, pool_timeout=1)
    async with mini.connect():
        with patch.object(s, "engine", mini):
            r = await s.verificar(usar_cache=False)
    checa("degradado, pool não entregou conexão", r["status"] == "degradado"
          and not r["pool"]["teste"]["ok"], r)
    checa("uso 100%", r["pool"]["uso"] == 1.0, r["pool"])
    checa("diagnóstico fora do pool respondeu", "ociosas" in r, r)
    await mini.dispose()

    print("5. reuniao_sync parado")
    with patch("app.reuniao_sync.flag_ligada", return_value=True), \
            patch.object(s, "LIMITE_REUNIAO_SYNC_S", -1):
        r = await s.verificar(usar_cache=False)
    checa("degradado com espelho parado", any("espelho" in p for p in r["problemas"]), r)

    print("6. vigia: transição")
    chamadas = []

    async def dublê(tipo, titulo, motivo):
        chamadas.append(tipo)
    with patch.object(s, "_alertar", dublê):
        with patch.object(s, "LIMITE_POOL", -1):
            await s.avaliar()
            await s.avaliar()
        await s.avaliar()
    checa("down, (nada), up", chamadas == [s.TIPO_CAIU, s.TIPO_VOLTOU], chamadas)
    await outro.dispose()


asyncio.run(main())
print(f"\n{'✅ tudo ok' if not falhas else f'❌ {len(falhas)} falha(s)'}")
raise SystemExit(1 if falhas else 0)
