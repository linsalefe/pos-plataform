"""Migração das travas da NAT + captura de clique de botão. Rodar uma vez:

    cd backend && venv/bin/python migrate_nat_config.py

É idempotente: pode rodar de novo com segurança se falhar no meio.

O que faz, TUDO numa única transação (engine.begin):
  1. lock_timeout=3s — mesma razão de migrate_auto_welcome.py: o sync_exact_leads mantém
     transação longa (pagina a Exact via HTTP e só commita no fim). Aqui só criamos tabelas
     NOVAS (sem ALTER e sem FK para tabela quente), então na prática não há disputa de lock —
     o timeout fica como rede de segurança, não como necessidade.
  2. Cria nat_config (singleton) — kill switch, corte por data e teto por hora.
  3. Cria nat_button_events — captura crua do clique de botão.
  4. Seed do singleton DESLIGADO (nat_enabled=FALSE, nat_start_at=NULL).

NÃO envia mensagem, NÃO altera auto_welcome_config, NÃO toca em exact_leads, contacts nem
messages. Nenhum comportamento de produção muda ao rodar isto.

Notas de schema (decisões, não acidentes):

  * nat_start_at nasce NULL de propósito. O nat_guard exige nat_start_at definido E
    register_date >= nat_start_at. Com NULL, a trava bloqueia mesmo que alguém ligue o
    nat_enabled por engano — a NAT nasce desligada em DOIS eixos independentes.

  * nat_button_events.contact_wa_id NÃO tem FK para contacts(wa_id), diferente de messages.
    A tabela é captura crua: o objetivo é nunca perder um clique. Uma FK só acrescentaria um
    modo de falha (replay de payload, backfill, contato ainda não criado) que derrubaria a
    transação inteira do webhook e faria perder o lote todo de mensagens. O índice dá o mesmo
    desempenho de busca sem esse risco.

  * wa_message_id é UNIQUE — idempotência contra reentrega de webhook, que a Meta faz. O
    webhook já dedupe antes disso (main.py checa Message.wa_message_id e dá `continue`), então
    na prática a constraint nunca deve disparar; ela é a segunda camada.
    IMPORTANTE: pela mesma razão que dispensa a FK, o INSERT nesta tabela (Fase 3) tem que ser
    defensivo — SAVEPOINT + try/except, logando e seguindo. Se a UNIQUE disparar, o erro NÃO
    pode abortar o processamento do webhook e levar o lote de mensagens junto. Esta tabela é
    de observabilidade: ela serve ao fluxo, não o contrário.

  * nat_config tem CHECK (id = 1): o singleton é garantido pelo banco, não pela convenção.
    O guard lê essa linha como kill switch — duas linhas ali seria comportamento indefinido
    no pior lugar possível.

  * context_message_id é o campo que dá sentido ao evento: é o wamid da mensagem que o botão
    respondeu. "Prefiro outro horário" é o MESMO texto em nat_boasvindas e nat_reativacao_09h —
    sem este campo os dois cliques são indistinguíveis. Indexado porque o roteamento do Bloco 2
    vai buscar por ele.
"""
import asyncio
from sqlalchemy import text
from app.database import engine

TETO_PADRAO_ENVIOS_HORA = 20


async def migrate():
    async with engine.begin() as conn:
        # 1. Não travar a API atrás de uma transação longa do sync.
        await conn.execute(text("SET lock_timeout = '3s'"))

        # 2. Configuração da NAT (singleton id=1).
        #    O CHECK (id = 1) é o que torna o singleton real e não uma convenção. Sem ele,
        #    rodar a migração duas vezes ou um INSERT na mão cria uma segunda linha, e o guard
        #    (que lê com LIMIT 1) passa a ter comportamento indefinido — no kill switch, que é
        #    o pior lugar possível pra ambiguidade. Com o CHECK, a segunda linha falha alto:
        #    o SERIAL tentaria id=2 e a constraint recusa.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS nat_config (
                id SERIAL PRIMARY KEY,
                nat_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                nat_start_at TIMESTAMP,
                max_envios_hora INTEGER NOT NULL DEFAULT 20,
                updated_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT nat_config_singleton CHECK (id = 1)
            )
        """))

        # 3. Captura crua do clique de botão.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS nat_button_events (
                id BIGSERIAL PRIMARY KEY,
                contact_wa_id VARCHAR(20) NOT NULL,
                wa_message_id VARCHAR(255) NOT NULL UNIQUE,
                context_message_id VARCHAR(255),
                button_payload TEXT,
                button_text TEXT,
                source VARCHAR(20) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_nat_btn_contact ON nat_button_events(contact_wa_id)"))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_nat_btn_context ON nat_button_events(context_message_id)"))

        # 4. Seed do singleton, DESLIGADO nos dois eixos (enabled=FALSE e start_at=NULL).
        await conn.execute(text("""
            INSERT INTO nat_config (id, nat_enabled, nat_start_at, max_envios_hora)
            VALUES (1, FALSE, NULL, :teto)
            ON CONFLICT (id) DO NOTHING
        """), {"teto": TETO_PADRAO_ENVIOS_HORA})

        estado = (await conn.execute(text(
            "SELECT nat_enabled, nat_start_at, max_envios_hora FROM nat_config WHERE id = 1"
        ))).first()

    print("OK: tabela nat_config criada/verificada")
    print("OK: tabela nat_button_events criada/verificada (+2 índices)")
    print(f"OK: singleton id=1 → nat_enabled={estado[0]}, nat_start_at={estado[1]}, "
          f"max_envios_hora={estado[2]}")
    print("NAT permanece DESLIGADA. Nenhuma mensagem foi enviada, nenhuma config existente alterada.")


if __name__ == "__main__":
    asyncio.run(migrate())
