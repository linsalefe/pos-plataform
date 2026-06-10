"""Cria a tabela scheduled_messages. Rodar uma vez: python migrate_scheduled_messages.py"""
import asyncio
from sqlalchemy import text
from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS scheduled_messages (
                id SERIAL PRIMARY KEY,
                template_name VARCHAR(255) NOT NULL,
                language VARCHAR(20) DEFAULT 'pt_BR',
                channel_id INTEGER NOT NULL,
                param_mappings TEXT,
                lead_ids TEXT NOT NULL,
                scheduled_at TIMESTAMP NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                created_by INTEGER REFERENCES users(id),
                created_by_name VARCHAR(255),
                lead_count INTEGER DEFAULT 0,
                result TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                sent_at TIMESTAMP
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sched_status_time ON scheduled_messages(status, scheduled_at)"))
        print("OK: tabela scheduled_messages criada/verificada")


if __name__ == "__main__":
    asyncio.run(migrate())
