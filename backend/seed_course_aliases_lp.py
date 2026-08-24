"""Aliases dos 13 subSources da landing page (Sprint Higiene, 24/08/2026).

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python seed_course_aliases_lp.py

------------------------------------------------------------------------------------------
O PROBLEMA
------------------------------------------------------------------------------------------
Os subSources da LP (`AGENDAMENTO_SUBSOURCES`) foram criados na Exact SEM ACENTO e COM
CÓDIGO DE TURMA. Nenhum tinha alias, então `resolve_course_name` caía no fallback de
`course_names.py:29-34`, que só remove o prefixo `Pos` — e o lead recebia isso cru:

    "Recebi sua aplicação para a Pós-Graduação em Alcool e Drogas T4"
    "Recebi sua aplicação para a Pós-Graduação em Grupos e Oficinas T2"

9 dos 13 saíam errados. Mensagens reais, medidas em 24/08.

------------------------------------------------------------------------------------------
DE ONDE VÊM OS NOMES
------------------------------------------------------------------------------------------
`knowledge_documents` (o nome oficial no material de cada curso) e `seed_courses.py`.
Nada foi inventado — ver as 3 ausências no fim do arquivo.

Script separado de `seed_courses.py` de propósito: aquele diz "rodar uma vez" e cria a
tabela; este só acrescenta linhas, é idempotente e pode rodar de novo sem efeito.

`full_name` é NOT NULL (models.py:248), então toda linha traz as duas colunas — embora só
`short_name` chegue à mensagem.
"""
import asyncio

from sqlalchemy import text

from app.database import async_session

# alias = o subSource EXATO da Exact. A comparação em resolve_course_name é
# case-insensitive, mas o espaçamento e a grafia têm que bater.
CURSOS_LP = [
    {"alias": "PosMulheridades",
     "full_name": "Pós-graduação: Saúde Mental e Mulheridades",
     "short_name": "Saúde Mental e Mulheridades"},
    {"alias": "Pos Grupos e Oficinas T2",
     "full_name": "Pós-graduação: Grupos e Oficinas em Saúde Mental — Práticas de Cuidado Psicossocial",
     "short_name": "Grupos e Oficinas em Saúde Mental"},
    {"alias": "Pos Psicologia na RAPS T3",
     "full_name": "Pós-graduação: Psicologia na Atenção Psicossocial — Elementos para o Trabalho na RAPS",
     "short_name": "Psicologia na RAPS"},
    {"alias": "Pos Psicologia Hospitalar",
     "full_name": "Pós-graduação: Psicologia Hospitalar",
     "short_name": "Psicologia Hospitalar"},
    {"alias": "Pos Suicidio e Luto T3",
     "full_name": "Pós-graduação: Novas Abordagens em Saúde Mental — Autolesão, Comportamento Suicida e Luto",
     "short_name": "Autolesão, Suicídio e Luto"},
    {"alias": "Pos Alcool e Drogas T4",
     "full_name": "Pós-graduação: Cuidado a Usuários de Álcool e Outras Drogas no Brasil",
     "short_name": "Álcool e Outras Drogas"},
    {"alias": "Pos Psicologia Clinica T2",
     "full_name": "Pós-graduação: Psicologia Clínica e Saúde Mental",
     "short_name": "Psicologia Clínica e Saúde Mental"},
    {"alias": "Pos Gestao Psicossocial T5",
     "full_name": "Pós-graduação: Gestão, Avaliação e Planejamento no Campo da Atenção Psicossocial",
     "short_name": "Gestão, Avaliação e Planejamento"},
    {"alias": "Pos TEA V3",
     "full_name": ("Pós-graduação: Transtorno do Espectro Autista (TEA) — Subjetividade, "
                   "Atenção Psicossocial e Novas Práticas Profissionais"),
     "short_name": "Transtorno do Espectro Autista (TEA)"},
    {"alias": "Pos Saude do Trabalhador",
     "full_name": "Pós-Graduação em Saúde Mental do Trabalhador",
     "short_name": "Saúde Mental do Trabalhador"},
]

# ------------------------------------------------------------------------------------------
# OS 3 QUE FICARAM DE FORA — DE PROPÓSITO
# ------------------------------------------------------------------------------------------
# Não têm nome comercial em NENHUMA fonte do projeto (course_aliases, seed_courses,
# knowledge_documents, templates da Meta, docs). Inventar um nome de curso é pior que o
# fallback: o fallback erra de um jeito visível ("Infantojuvenil EAD"), o palpite erra de um
# jeito que ninguém percebe.
#
#   Pos Infantojuvenil EAD          existem DOIS cursos infantojuvenis no cadastro
#                                   ("Interlocução no Território (T5)" e "Práticas Clínicas
#                                   em Saúde Mental Infantojuvenil"); "EAD" não decide qual
#   Pos Psicologia Escolar          nome completo não existe em lugar nenhum
#   Pos Enfermagem em Saude Mental  idem
#
# Quando o time confirmar, acrescentar aqui em cima e rodar de novo.
PENDENTES = ["Pos Infantojuvenil EAD", "Pos Psicologia Escolar",
             "Pos Enfermagem em Saude Mental"]


async def seed():
    async with async_session() as session:
        inseridos = 0
        for c in CURSOS_LP:
            existe = await session.execute(
                text("SELECT id FROM course_aliases WHERE lower(alias) = lower(:alias)"),
                {"alias": c["alias"]})
            if existe.scalar():
                print(f"  = {c['alias']} (já existe)")
                continue
            await session.execute(
                text("INSERT INTO course_aliases (alias, full_name, short_name) "
                     "VALUES (:alias, :full_name, :short_name)"), c)
            print(f"  + {c['alias']} → {c['short_name']}")
            inseridos += 1
        await session.commit()

    print(f"\n✅ {inseridos} alias inserido(s), {len(CURSOS_LP) - inseridos} já existia(m).")
    print(f"⏳ {len(PENDENTES)} pendente(s) de confirmação do time: {', '.join(PENDENTES)}")


if __name__ == "__main__":
    asyncio.run(seed())
