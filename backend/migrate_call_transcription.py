import asyncio
from sqlalchemy import text
from app.database import async_session

async def migrate():
    async with async_session() as db:
        await db.execute(text("""
            ALTER TABLE call_logs 
            ADD COLUMN IF NOT EXISTS local_recording_path VARCHAR(500),
            ADD COLUMN IF NOT EXISTS transcription TEXT,
            ADD COLUMN IF NOT EXISTS transcription_insights TEXT,
            ADD COLUMN IF NOT EXISTS transcription_status VARCHAR(30)
        """))
        await db.commit()
        print("✅ Migration concluída")

asyncio.run(migrate())