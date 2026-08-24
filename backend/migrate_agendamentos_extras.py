"""`agendamentos.extras` — respostas livres do formulário da landing page.

Rodar uma vez:

    cd backend && venv/bin/python migrate_agendamentos_extras.py

Idempotente, numa única transação. Aditiva: coluna nova, NULLABLE, sem default.

------------------------------------------------------------------------------------------
POR QUE A COLUNA EXISTE
------------------------------------------------------------------------------------------
Cada LP pergunta coisas diferentes além de nome/e-mail/telefone — profissão, se tem ensino
superior, como conheceu a CENAT, faixa de investimento. Transformar cada pergunta em coluna
significaria uma migração por campanha, e a equipe de marketing muda o formulário sem falar
com ninguém. JSON absorve isso.

O mesmo dado também é concatenado no `description` do lead na Exact, para o SDR ler antes de
ligar. Os dois destinos são intencionais e servem a públicos diferentes: o `description` é
texto para humano, esta coluna é dado para consulta.

------------------------------------------------------------------------------------------
POR QUE JSONB, DIVERGINDO DO RESTO DO PROJETO
------------------------------------------------------------------------------------------
`templates.components` e `nat_scheduled_actions.payload` são `Text` com `json.dumps`. Não
segui esses dois de propósito: ambos guardam payload OPACO, escrito para auditoria e nunca
lido por dentro. Aqui é o contrário — a pergunta que o marketing vai fazer é exatamente
"quantos leads vieram do Instagram?", e com JSONB isso é

    SELECT extras->>'Como conheceu', count(*)
      FROM agendamentos GROUP BY 1;

sem parse na aplicação. JSONB ainda recusa JSON inválido na escrita, o que `Text` não faz.
Postgres 14.23 em produção — suporte nativo, sem extensão.

NULLABLE porque a maioria das submissões não terá extras: as LPs antigas não mandam o campo,
e ele é opcional por definição. NULL aqui significa "não perguntaram nada", que é diferente
de `{}` ("perguntaram e a pessoa não respondeu") — a distinção é de graça e pode importar
num relatório.

SEM índice GIN. A tabela é pequena (uma linha por tentativa de agendamento da LP) e um
`GROUP BY` sobre ela varre tudo em milissegundos. Índice GIN custa escrita no caminho do
agendamento, que é o caminho que não pode ficar lento. Se um dia a tabela crescer para
centenas de milhares de linhas, aí sim:

    CREATE INDEX CONCURRENTLY ix_agendamentos_extras ON agendamentos USING GIN (extras);

NÃO cria endpoint, NÃO fala com a Exact, NÃO altera linha existente.
"""
import asyncio

from sqlalchemy import text

from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text("SET lock_timeout = '3s'"))

        await conn.execute(text(
            "ALTER TABLE agendamentos ADD COLUMN IF NOT EXISTS extras JSONB"))

        col = (await conn.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'agendamentos' AND column_name = 'extras'"))).scalar()
        total = (await conn.execute(text("SELECT count(*) FROM agendamentos"))).scalar()
        com_extras = (await conn.execute(text(
            "SELECT count(*) FROM agendamentos WHERE extras IS NOT NULL"))).scalar()

    print(f"OK: agendamentos.extras presente, tipo={col}")
    print(f"OK: {com_extras} de {total} linhas com extras "
          "(0 é o esperado — só submissões NOVAS com o campo preenchem)")
    print("Nenhuma linha alterada, nada enviado à Exact.")


if __name__ == "__main__":
    asyncio.run(migrate())
