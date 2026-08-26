from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/cenat_whatsapp")

# ==========================================================================================
# O POOL — dimensionado por medição, não por default (P1-A, 26/08/2026)
# ==========================================================================================
# ANTES: `create_async_engine(DATABASE_URL, echo=True)`. Sem `pool_size`, o default do
# SQLAlchemy é 5 + 10 de overflow = 15 conexões, com `pool_timeout=30s`.
#
# QUINZE ESGOTOU COM CARGA REAL. Em 25/08, das 18:18:55 às 18:19:29 UTC, ~70 tracebacks de
# `QueuePool limit of size 5 overflow 10 reached`. Vítimas nomeadas no journald:
# `scheduled_messages_job`, a faxina de agendamento, o NAT scheduler (`TimeoutError`) e —
# o pior — o próprio webhook, que bateu em `main.py:370` (`await db.execute` logo na
# entrada): MENSAGEM DE LEAD RECUSADA NA PORTA, antes de qualquer log de identidade.
# Gatilho da janela: 8× `POST /api/exact-leads/bulk-send-template` (47 outbounds em 60s)
# + rajada de `POST /api/contacts/<n>/read` + o polling de `/api/notifications` que o
# frontend faz a cada ~15s POR ABA ABERTA.
#
# O agente é o consumidor que mais SEGURA conexão: a sessão fica presa durante
# `llm.conversar` (timeout × 2 tentativas), `fetch_template_body` (Meta) e `fluxo.agendar`
# (Exact, vários round-trips). Medido nos prints: 3–5s por turno de lead. Num pool de 15,
# com campanha rodando, isso fecha a porta.
#
# OS NÚMEROS, e por que estes:
#   pool_size=20 + max_overflow=20  -> teto de 40 conexões vindas da app. `max_connections`
#       do Postgres é 100 (3 reservadas para superusuário → 97 utilizáveis) e a app roda em
#       UM processo uvicorn (sem `--workers`), logo UM engine: 40 é o teto real, não 40×N.
#       Sobra folga para psql, migrações e scripts pontuais. 40 cobre a rajada da campanha
#       + polling + scheduler + faxina simultâneos, que é exatamente o cenário de 18:18.
#   pool_timeout=10 (era 30)  -> quando o pool ENCHER mesmo assim, o webhook falha RÁPIDO e
#       a Meta reentrega a mensagem. Segurar 30s é pior que falhar em 10: o handler da Meta
#       tem prazo, e uma espera longa consome worker sem entregar nada.
#   pool_pre_ping=True  -> testa a conexão antes de entregá-la. Conexão morta no pool (idle
#       cortada pelo Postgres ou pela rede) hoje aparece como erro aleatório no primeiro
#       `execute` de um turno — e um erro aleatório no turno do agente é, desde o P0-B,
#       transferência de lead para humano. Um SELECT 1 por checkout é barato demais para
#       comparar com isso.
#
# `echo=False` (era True): o journald acumulou 4,0 GB de SQL cru e chegou a SUPRIMIR 36 750
# linhas em 25/08 — ou seja, o excesso de log estava apagando o log que importa. A troca só
# é aceitável porque o P0-E (f19fae9) já pôs o turno do LLM numa linha estruturada por
# `logging`: perdemos o SQL, não a rastreabilidade do agente.
#
# AVALIADO E DEIXADO DE FORA (item próprio, não deste sprint): soltar a conexão durante
# `llm.conversar`. Cortaria a retenção de 3–5s para <1s, mas exige reabrir sessão e reler o
# estado no meio do turno — mudança de fluxo, não de dimensionamento.
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=20,
    pool_timeout=10,
    pool_pre_ping=True,
)

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session
