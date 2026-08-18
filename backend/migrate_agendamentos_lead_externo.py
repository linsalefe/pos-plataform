"""`agendamentos.lead_externo` — o lead veio pronto no POST, ou fomos nós que criamos?

Rodar uma vez:

    cd backend && venv/bin/python migrate_agendamentos_lead_externo.py

Idempotente, numa única transação. Aditiva: coluna nova, NOT NULL com default `false`.

------------------------------------------------------------------------------------------
POR QUE A COLUNA EXISTE
------------------------------------------------------------------------------------------
O `POST /agendamento/agendar` passou a aceitar `leadId` opcional. Com ele, o fluxo pula o
`LeadsAdd` e agenda um lead que JÁ existe — é o fluxo de duas etapas da landing page:

    index.html (form nativo) -> POST /lead  -> lead criado em Entrada
    obrigado.html            -> POST /agendar com leadId -> agenda o MESMO lead

Sem `leadId`, o /agendar continua criando o lead ele mesmo (a LP de Mulheridades usa esse
caminho). Os dois desfechos gravam `lead_id` preenchido e ficam **indistinguíveis** na
tabela. Esta coluna é o que separa um do outro.

Serve a duas perguntas concretas:

  * **Operação:** "este lead é nosso para mexer?" A compensação de falha no `scheduleAdd`
    remove o box e PRESERVA o lead nos dois casos — mas por razões diferentes. No lead nosso
    é decisão de produto (o contato vale mais que o horário); no lead externo é que ele
    simplesmente não nos pertence, foi criado por outra requisição. Quem for mexer na
    compensação depois precisa enxergar a diferença antes de escrever `LeadsDelete`.

  * **Produto:** "quantos agendamentos vieram do formulário nativo em duas etapas contra o
    formulário de uma etapa?" É a medida de conversão entre o index e o obrigado — o dado
    que diz se trocar o form do RD Station valeu a pena.

NOT NULL com `server_default 'false'`: as linhas antigas são todas do fluxo de uma etapa,
onde o lead foi criado por nós. `false` é o valor historicamente correto, não um placeholder.
Difere de `sub_source`, que foi NULLABLE porque ali o valor antigo era genuinamente
desconhecido — aqui ele é conhecido e é `false`.

SEM índice: a tabela é pequena (uma linha por tentativa de agendamento da LP) e a coluna é
booleana, de baixa cardinalidade. Índice aqui só custaria escrita.

NÃO cria endpoint, NÃO fala com a Exact, NÃO altera o valor de linha existente além do
default de preenchimento.
"""
import asyncio

from sqlalchemy import text

from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text("SET lock_timeout = '3s'"))

        await conn.execute(text(
            "ALTER TABLE agendamentos ADD COLUMN IF NOT EXISTS lead_externo "
            "BOOLEAN NOT NULL DEFAULT false"))

        col = (await conn.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'agendamentos' AND column_name = 'lead_externo'"))).scalar()
        total = (await conn.execute(text("SELECT count(*) FROM agendamentos"))).scalar()
        externos = (await conn.execute(text(
            "SELECT count(*) FROM agendamentos WHERE lead_externo"))).scalar()

    print(f"OK: agendamentos.lead_externo presente: {col == 1}")
    print(f"OK: {externos} de {total} linhas com lead_externo=true "
          "(0 é o esperado — só agendamentos NOVOS com leadId marcam true)")
    print("Nenhuma linha alterada, nada enviado à Exact.")


if __name__ == "__main__":
    asyncio.run(migrate())
