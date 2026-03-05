"""
Adiciona coluna assigned_to na tabela contacts.
Rodar uma vez: python migrate_assigned_to.py
"""
import asyncio
from sqlalchemy import text
from app.database import engine

async def migrate():
    async with engine.begin() as conn:
        # Verificar se coluna já existe
        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='contacts' AND column_name='assigned_to'"
        ))
        if result.scalar():
            print("Coluna assigned_to já existe")
            return

        # Adicionar coluna
        await conn.execute(text(
            "ALTER TABLE contacts ADD COLUMN assigned_to INTEGER REFERENCES users(id)"
        ))
        await conn.execute(text(
            "CREATE INDEX idx_contacts_assigned_to ON contacts(assigned_to)"
        ))
        print("Coluna assigned_to adicionada à tabela contacts")

        # Atribuir contatos existentes à Victória (user_id precisa ser verificado)
        # Buscar ID da Victória
        victoria = await conn.execute(text(
            "SELECT id FROM users WHERE name ILIKE '%vict%' LIMIT 1"
        ))
        victoria_id = victoria.scalar()
        if victoria_id:
            await conn.execute(text(
                f"UPDATE contacts SET assigned_to = {victoria_id}"
            ))
            print(f"Contatos existentes atribuídos à Victória (id={victoria_id})")
        else:
            print("Victória não encontrada - contatos ficam sem atribuição")

    print("Migration completa!")

if __name__ == "__main__":
    asyncio.run(migrate())
