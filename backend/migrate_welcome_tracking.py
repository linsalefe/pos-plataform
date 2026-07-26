"""Vínculo entre a mensagem de boas-vindas e o lead — Fase 1 da sprint de observabilidade.

Rodar uma vez:

    cd backend && venv/bin/python migrate_welcome_tracking.py

Idempotente, numa única transação (engine.begin): ou entra tudo, ou não entra nada.

------------------------------------------------------------------------------------------
POR QUE ESTA COLUNA EXISTE
------------------------------------------------------------------------------------------
O incidente 131042 durou 4 dias porque `exact_leads.welcome_status` é carimbado 'sent' quando
a Meta ACEITA o envio (HTTP 200 com messages[0].id), e o `failed` que chega depois pelo webhook
de status nunca realimenta a tabela. O painel mostrou 254 sucessos enquanto 100% falhava.

Para o webhook poder corrigir o carimbo, ele precisa saber A QUAL LEAD aquela falha pertence —
e hoje não existe vínculo nenhum entre `messages` e `exact_leads`. O status chega com o
`wamid`, e o `wamid` não está guardado em lugar nenhum do lado do lead.

`welcome_wamid` é esse vínculo, e é o que a Fase 2 consome.

------------------------------------------------------------------------------------------
NOTAS DE SCHEMA
------------------------------------------------------------------------------------------
  * TEXT, não VARCHAR(n). Os wamids reais desta conta vão de 58 a 82 caracteres
    (`SELECT max(length(wa_message_id)) FROM messages` = 82), o formato é opaco e definido pela
    Meta, e um VARCHAR curto demais viraria StringDataRightTruncation no meio de um envio que
    JÁ saiu — perder o vínculo por causa de um limite que nós inventamos seria o pior desfecho.
    `messages.wa_message_id` é VARCHAR(255); aqui não há motivo para repetir o limite.

  * NULLABLE, sem default. NULL é a resposta certa e vai continuar sendo maioria: os 8.388
    leads `skipped` nunca tiveram envio, e os 254 `sent` de antes desta migração jamais terão o
    wamid (a informação só existia no instante do envio e não foi guardada). A Fase 3 lida com
    esses por telefone + janela de tempo, que é o único caminho possível para o passado.

  * ÍNDICE COMUM, não único. É a busca do webhook de status — `WHERE welcome_wamid = :wamid`,
    que roda por mensagem de status recebida, então precisa de índice.
    NÃO é único de propósito: a coluna é preenchida por um caminho só, mas um UNIQUE
    transformaria qualquer colisão inesperada (reenvio manual com force=True gravando o mesmo
    wamid, bug futuro) num IntegrityError dentro do envio — quebrando o envio para proteger uma
    garantia que não precisamos. Índice parcial `WHERE welcome_wamid IS NOT NULL` porque a
    esmagadora maioria das 8.662 linhas é NULL e não tem por que ser indexada.

  * SEM FK para messages.wa_message_id. Mesma razão do resto do projeto: a escrita acontece
    dentro do fluxo de envio, e uma FK só acrescentaria um jeito de derrubá-lo. Além disso a
    Message e o ExactLead são gravados na mesma transação, e a ordem entre eles não é garantida.

NÃO envia mensagem, NÃO altera auto_welcome_config nem nat_config, NÃO toca em welcome_status.
Nenhum comportamento muda ao rodar isto: a coluna nasce vazia e o único código que a escreve é
o envio, que segue desligado.
"""
import asyncio
from sqlalchemy import text
from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        # exact_leads é reescrita inteira pelo sync a cada 10 min (8.662 linhas, ramo de
        # UPDATE). Sem lock_timeout, o ALTER esperaria a transação do sync e enfileiraria
        # toda leitura da tabela atrás dele.
        await conn.execute(text("SET lock_timeout = '3s'"))

        await conn.execute(text(
            "ALTER TABLE exact_leads ADD COLUMN IF NOT EXISTS welcome_wamid TEXT"))

        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_exact_leads_welcome_wamid
                ON exact_leads (welcome_wamid)
                WHERE welcome_wamid IS NOT NULL
        """))

        # Conferência na mesma transação — se algo acima não pegou, aparece aqui.
        col = (await conn.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'exact_leads' AND column_name = 'welcome_wamid'"))).scalar()
        idx = (await conn.execute(text(
            "SELECT count(*) FROM pg_indexes WHERE tablename = 'exact_leads' "
            "AND indexname = 'idx_exact_leads_welcome_wamid'"))).scalar()
        preenchidos = (await conn.execute(text(
            "SELECT count(*) FROM exact_leads WHERE welcome_wamid IS NOT NULL"))).scalar()
        total = (await conn.execute(text("SELECT count(*) FROM exact_leads"))).scalar()

    print(f"OK: exact_leads.welcome_wamid presente: {col == 1}")
    print(f"OK: índice parcial idx_exact_leads_welcome_wamid presente: {idx == 1}")
    print(f"OK: {preenchidos} de {total} leads com wamid "
          "(0 é o esperado — só envios NOVOS preenchem)")
    print("Nenhuma mensagem enviada. auto_welcome_config e nat_config intactas.")


if __name__ == "__main__":
    asyncio.run(migrate())
