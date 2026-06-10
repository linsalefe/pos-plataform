"""Cria a tabela notifications. Rodar uma vez: python migrate_notifications.py"""
import asyncio
from sqlalchemy import text
from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notifications (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                contact_wa_id VARCHAR(20),
                type VARCHAR(30) NOT NULL,
                ref VARCHAR(255),
                title VARCHAR(255) NOT NULL,
                body TEXT,
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_id, is_read)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notifications_dedup ON notifications(contact_wa_id, type, ref)"))
        print("OK: tabela notifications criada/verificada")


if __name__ == "__main__":
    asyncio.run(migrate())
