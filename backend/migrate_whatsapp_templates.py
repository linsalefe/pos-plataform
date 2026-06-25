"""Cria a tabela whatsapp_templates. Rodar uma vez: python migrate_whatsapp_templates.py"""
import asyncio
from sqlalchemy import text
from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS whatsapp_templates (
                id SERIAL PRIMARY KEY,
                channel_id INTEGER NOT NULL REFERENCES channels(id),
                name VARCHAR(512) NOT NULL,
                language VARCHAR(20) NOT NULL DEFAULT 'pt_BR',
                category VARCHAR(30) NOT NULL,
                components TEXT,
                meta_template_id VARCHAR(64),
                status VARCHAR(30) DEFAULT 'PENDING',
                rejected_reason TEXT,
                created_by INTEGER REFERENCES users(id),
                created_by_name VARCHAR(255),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_wpp_tpl_channel ON whatsapp_templates(channel_id)"))
        print("OK: tabela whatsapp_templates criada/verificada")


if __name__ == "__main__":
    asyncio.run(migrate())
