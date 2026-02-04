import asyncio
from app.database import engine, Base
from app.models import Contact, Message


async def create_all():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Tabelas criadas com sucesso!")


if __name__ == "__main__":
    asyncio.run(create_all())