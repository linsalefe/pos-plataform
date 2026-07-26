"""Instrumentação do erro de entrega da Meta. Rodar uma vez:

    cd backend && venv/bin/python migrate_message_error.py

É idempotente (ADD COLUMN IF NOT EXISTS): pode rodar de novo com segurança.

Acrescenta 3 colunas NULLABLE em `messages` para guardar o que o webhook de status hoje
descarta — `statuses[].errors[]`. Sem isso não há como saber POR QUE 100% dos envios de
nat_boasvindas falham desde 23/07: o motivo só existe no payload daquele instante.

  error_code    INTEGER  -> errors[0].code
  error_title   TEXT     -> errors[0].title
  error_details TEXT     -> errors[0].error_data.details

`error_data.details` é onde a Meta escreve a explicação em linguagem natural, e costuma valer
mais que o title (que é genérico). Por isso os três, e não só o código.

DIFERENÇA IMPORTANTE PARA AS MIGRAÇÕES ANTERIORES DESTA SÉRIE: as outras criaram tabelas
novas; esta faz ALTER numa tabela QUENTE (26.766 linhas, escrita pelo webhook a cada mensagem
recebida). Duas coisas tornam isso seguro:

  1. ADD COLUMN nullable e SEM DEFAULT é operação de catálogo no Postgres — não reescreve a
     tabela, não varre as 26 mil linhas. Confirmado: PostgreSQL 14.23.
  2. lock_timeout de 3s. O ALTER precisa de ACCESS EXCLUSIVE, ainda que por um instante, e o
     sync_exact_leads mantém transação longa (pagina a Exact via HTTP e só commita no fim).
     Sem o timeout, o ALTER esperaria o sync terminar SEGURANDO a fila de quem vem depois — e
     o webhook, que só quer inserir mensagem, ficaria atrás dele. Com o timeout, o pior caso é
     a migração falhar e ser rodada de novo, em vez de travar o recebimento de mensagens.

NÃO altera comportamento nenhum: as colunas nascem NULL e ninguém as lê até o código da Fase 2
subir. NÃO envia mensagem, NÃO toca em nat_config nem em auto_welcome_config.
"""
import asyncio
from sqlalchemy import text
from app.database import engine

COLUNAS = (
    ("error_code", "INTEGER"),
    ("error_title", "TEXT"),
    ("error_details", "TEXT"),
)


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text("SET lock_timeout = '3s'"))

        for nome, tipo in COLUNAS:
            await conn.execute(text(
                f"ALTER TABLE messages ADD COLUMN IF NOT EXISTS {nome} {tipo}"))

        existentes = (await conn.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'messages' AND column_name IN ('error_code','error_title','error_details')
            ORDER BY column_name
        """))).fetchall()

        com_erro = (await conn.execute(text(
            "SELECT count(*) FROM messages WHERE error_code IS NOT NULL"))).scalar()

    for nome, tipo, nulo in existentes:
        print(f"OK: messages.{nome} {tipo} nullable={nulo}")
    print(f"OK: {com_erro} mensagem(ns) com error_code preenchido "
          "(0 é o esperado — só o código da Fase 2 preenche, e só nos envios FUTUROS)")
    print("Nenhum comportamento alterado. NAT segue desligada.")


if __name__ == "__main__":
    asyncio.run(migrate())
