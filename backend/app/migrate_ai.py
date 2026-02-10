"""
Migração: cria tabelas do agente IA + Kanban
Executar: cd backend && source venv/bin/activate && python -m app.migrate_ai
"""
import asyncio
from sqlalchemy import text
from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        # 1. Coluna ai_active na tabela contacts
        await conn.execute(text("""
            ALTER TABLE contacts ADD COLUMN IF NOT EXISTS ai_active BOOLEAN DEFAULT FALSE;
        """))
        print("✅ Coluna ai_active adicionada em contacts")

        # 2. Tabela ai_configs
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_configs (
                id SERIAL PRIMARY KEY,
                channel_id INTEGER UNIQUE NOT NULL REFERENCES channels(id),
                is_enabled BOOLEAN DEFAULT FALSE,
                system_prompt TEXT,
                model VARCHAR(50) DEFAULT 'gpt-4o',
                temperature VARCHAR(10) DEFAULT '0.7',
                max_tokens INTEGER DEFAULT 500,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
        """))
        print("✅ Tabela ai_configs criada")

        # 3. Tabela knowledge_documents
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                id SERIAL PRIMARY KEY,
                channel_id INTEGER NOT NULL REFERENCES channels(id),
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT,
                chunk_index INTEGER DEFAULT 0,
                token_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT now()
            );
        """))
        print("✅ Tabela knowledge_documents criada")

        # 4. Tabela ai_conversation_summaries
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_conversation_summaries (
                id SERIAL PRIMARY KEY,
                contact_wa_id VARCHAR(20) NOT NULL REFERENCES contacts(wa_id),
                channel_id INTEGER NOT NULL REFERENCES channels(id),
                status VARCHAR(30) DEFAULT 'em_atendimento_ia',
                summary TEXT,
                lead_name VARCHAR(255),
                lead_course VARCHAR(255),
                ai_messages_count INTEGER DEFAULT 0,
                human_took_over BOOLEAN DEFAULT FALSE,
                started_at TIMESTAMP DEFAULT now(),
                finished_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT now()
            );
        """))
        print("✅ Tabela ai_conversation_summaries criada")

        # 5. Índice para buscas rápidas no kanban
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ai_summaries_status ON ai_conversation_summaries(status);
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ai_summaries_channel ON ai_conversation_summaries(channel_id);
        """))
        print("✅ Índices criados")

    print("\n🎉 Migração concluída com sucesso!")


if __name__ == "__main__":
    asyncio.run(migrate())