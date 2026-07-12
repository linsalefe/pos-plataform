"""Migração da mensagem automática de boas-vindas. Rodar uma vez:

    cd backend && venv/bin/python migrate_auto_welcome.py

É idempotente: pode rodar de novo com segurança se falhar no meio.

O que faz, TUDO numa única transação (engine.begin):
  1. lock_timeout=3s — o sync_exact_leads mantém transação longa (pagina a Exact via HTTP e só
     commita no fim). O ALTER TABLE pega ACCESS EXCLUSIVE; sem timeout ele enfileira todos os
     leitores atrás e trava a API. Com timeout, se pegar um sync no meio, falha rápido — é só
     rodar de novo. Janela ideal: logo após um restart do backend (o sync_job dorme 600s antes
     do primeiro sync, então há ~10 min de pista livre).
  2. Cria auto_welcome_config (singleton).
  3. Adiciona welcome_sent_at / welcome_status / welcome_error em exact_leads.
  4. BACKFILL DE PROTEÇÃO: carimba TODOS os leads já existentes como 'skipped'. Eles nunca
     poderão receber boas-vindas. Este UPDATE toca APENAS exact_leads — não cria Contact,
     Message nem AIConversationSummary, e não envia mensagem nenhuma.
  5. Seed do singleton DESLIGADO (enabled=FALSE), com channel_id NULL de propósito (o operador
     escolhe o canal no painel).
"""
import asyncio
from sqlalchemy import text
from app.database import engine

BACKFILL_MOTIVO = "backfill: lead anterior à automação — não deve receber boas-vindas"


async def migrate():
    async with engine.begin() as conn:
        # 1. Não travar a API atrás de uma transação longa do sync.
        await conn.execute(text("SET lock_timeout = '3s'"))

        # 2. Tabela de configuração (singleton).
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS auto_welcome_config (
                id SERIAL PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                channel_id INTEGER REFERENCES channels(id),
                template_name VARCHAR(255),
                template_language VARCHAR(20) DEFAULT 'pt_BR',
                funnel_ids VARCHAR(255),
                updated_by INTEGER REFERENCES users(id),
                updated_by_name VARCHAR(255),
                updated_at TIMESTAMP DEFAULT NOW(),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))

        # 3. Colunas de welcome (nullable => operação de metadados, instantânea no PG 14).
        await conn.execute(text(
            "ALTER TABLE exact_leads ADD COLUMN IF NOT EXISTS welcome_sent_at TIMESTAMP"))
        await conn.execute(text(
            "ALTER TABLE exact_leads ADD COLUMN IF NOT EXISTS welcome_status VARCHAR(30)"))
        await conn.execute(text(
            "ALTER TABLE exact_leads ADD COLUMN IF NOT EXISTS welcome_error TEXT"))

        # 4. BACKFILL DE PROTEÇÃO — o coração da regra "antigo nunca recebe".
        #    welcome_sent_at fica NULL de propósito: nada foi enviado a eles. O que trava é o status.
        res = await conn.execute(text("""
            UPDATE exact_leads
               SET welcome_status = 'skipped',
                   welcome_error  = :motivo
             WHERE welcome_status IS NULL
        """), {"motivo": BACKFILL_MOTIVO})
        carimbados = res.rowcount

        # 5. Seed do singleton, DESLIGADO. channel_id NULL: o operador escolhe no painel.
        await conn.execute(text("""
            INSERT INTO auto_welcome_config
                (id, enabled, channel_id, template_name, template_language, funnel_ids)
            VALUES
                (1, FALSE, NULL, 'nat_boasvindas', 'pt_BR', '18535,18537,25588')
            ON CONFLICT (id) DO NOTHING
        """))

    print(f"OK: auto_welcome_config criada (enabled=FALSE) + 3 colunas em exact_leads")
    print(f"OK: backfill carimbou {carimbados} leads como 'skipped' (nunca receberão boas-vindas)")


if __name__ == "__main__":
    asyncio.run(migrate())
