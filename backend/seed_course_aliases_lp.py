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

    # --- Os 3 que faltavam, confirmados pelo coordenador em 24/08 -----------------------
    #
    # São o nome comercial próprio, com acento e sem o prefixo `Pos`. `full_name` segue o
    # padrão da linha acima ("Pós-Graduação em X"), porque o coordenador confirmou o nome
    # curto e o campo é NOT NULL.
    #
    # MEDIDO antes de inserir: para os dois primeiros o valor é IDÊNTICO ao que o fallback
    # de course_names.py já produzia — a linha não muda a mensagem, torna o valor explícito
    # e imune a uma mudança futura na string do subSource. Só a Enfermagem muda de fato, e
    # o que ela ganha é o acento: "Saude" -> "Saúde".
    {"alias": "Pos Infantojuvenil EAD",
     "full_name": "Pós-Graduação em Infantojuvenil EAD",
     "short_name": "Infantojuvenil EAD"},
    {"alias": "Pos Psicologia Escolar",
     "full_name": "Pós-Graduação em Psicologia Escolar",
     "short_name": "Psicologia Escolar"},
    {"alias": "Pos Enfermagem em Saude Mental",
     "full_name": "Pós-Graduação em Enfermagem em Saúde Mental",
     "short_name": "Enfermagem em Saúde Mental"},
]

# ------------------------------------------------------------------------------------------
# NÃO HÁ MAIS PENDENTES
# ------------------------------------------------------------------------------------------
# Os 3 que faltavam não tinham nome comercial em NENHUMA fonte do projeto (course_aliases,
# seed_courses, knowledge_documents, templates da Meta, docs) — e inventar um nome de curso
# seria pior que o fallback, que ao menos erra de um jeito visível. Ficaram de fora até o
# coordenador confirmar, o que aconteceu em 24/08. Os 13 subSources da LP estão cobertos.
PENDENTES = []


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
