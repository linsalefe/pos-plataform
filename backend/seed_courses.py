"""
Script para criar tabela course_aliases e popular com os mapeamentos.
Rodar uma vez no servidor: python seed_courses.py
"""
import asyncio
from sqlalchemy import text
from app.database import engine, async_session

COURSES = [
    {
        "alias": "pospics2025",
        "full_name": "Pós-Graduação Online: Práticas Integrativas e Complementares em Saúde no Contexto da Saúde Mental",
        "short_name": "Práticas Integrativas em Saúde Mental",
    },
    {
        "alias": "poscuidaremliberdadeturma5",
        "full_name": "Pós-Graduação Online em Acompanhamento Terapêutico em Diferentes Contextos na Saúde Mental: Cuidado em Liberdade",
        "short_name": "Acompanhamento Terapêutico - Cuidado em Liberdade",
    },
    {
        "alias": "possupervisao",
        "full_name": "Pós-Graduação Online em Supervisão Clínico Institucional",
        "short_name": "Supervisão Clínico Institucional",
    },
    {
        "alias": "posat",
        "full_name": "Pós-Graduação Online em Acompanhamento Terapêutico em Diferentes Contextos na Saúde Mental: Cuidado em Liberdade",
        "short_name": "Acompanhamento Terapêutico",
    },
    {
        "alias": "pospsihospitalar",
        "full_name": "Pós-Graduação Online: Psicologia Hospitalar",
        "short_name": "Psicologia Hospitalar",
    },
    {
        "alias": "possminfantoterritoriot5",
        "full_name": "Pós-Graduação Online: Novas Abordagens em Saúde Mental Infantojuvenil: Interlocução no Território (Turma 5)",
        "short_name": "Saúde Mental Infantojuvenil",
    },
    {
        "alias": "posgenerot2",
        "full_name": "Pós-Graduação Online: Gêneros e Sexualidades — Cuidados interseccionais em Saúde Mental coletiva (Turma 2)",
        "short_name": "Gêneros e Sexualidades em Saúde Mental",
    },
    {
        "alias": "PosPsicologiaClinicaeSaudeMentalturma2",
        "full_name": "Pós-Graduação Online: Boas Práticas em Psicologia Clínica e Saúde Mental",
        "short_name": "Psicologia Clínica e Saúde Mental",
    },
    {
        "alias": "Posemcuidadoausuariosdealcooleoutrasdrogasturma4",
        "full_name": "Pós-Graduação Online: Cuidado a Usuários de Álcool e Outras Drogas (Turma 4)",
        "short_name": "Cuidado a Usuários de Álcool e Drogas",
    },
    {
        "alias": "possmedh",
        "full_name": "Pós-Graduação em Saúde Mental e Direitos Humanos",
        "short_name": "Saúde Mental e Direitos Humanos",
    },
    {
        "alias": "posautolesao",
        "full_name": "Pós-Graduação em Autolesão e Prevenção do Suicídio",
        "short_name": "Autolesão e Prevenção do Suicídio",
    },
    {
        "alias": "possmdotrabalhador",
        "full_name": "Pós-Graduação em Saúde Mental do Trabalhador",
        "short_name": "Saúde Mental do Trabalhador",
    },
    {
        "alias": "pospsiclinicasminfantojuvenil",
        "full_name": "Pós-Graduação em Práticas Clínicas em Saúde Mental Infantojuvenil",
        "short_name": "Práticas Clínicas Infantojuvenil",
    },
]


async def seed():
    async with engine.begin() as conn:
        # Criar tabela
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS course_aliases (
                id SERIAL PRIMARY KEY,
                alias VARCHAR(150) UNIQUE NOT NULL,
                full_name VARCHAR(500) NOT NULL,
                short_name VARCHAR(150),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_course_alias ON course_aliases(alias)"))
        print("✅ Tabela course_aliases criada")

    async with async_session() as session:
        for c in COURSES:
            # Upsert: insere se não existir
            exists = await session.execute(
                text("SELECT id FROM course_aliases WHERE alias = :alias"),
                {"alias": c["alias"]}
            )
            if not exists.scalar():
                await session.execute(
                    text("INSERT INTO course_aliases (alias, full_name, short_name) VALUES (:alias, :full_name, :short_name)"),
                    c
                )
                print(f"  + {c['alias']} → {c['short_name']}")
            else:
                print(f"  = {c['alias']} (já existe)")
        await session.commit()

    print("\n✅ Seed completo!")


if __name__ == "__main__":
    asyncio.run(seed())
