"""Fundações da cadência (Item 1) + encerramento por inatividade (Item 3). Rodar uma vez:

    cd backend && venv/bin/python migrate_cadencia_fundacoes.py

Idempotente. TUDO numa transação (engine.begin), com lock_timeout=3s — o `sync_exact_leads`
mantém transação longa (pagina a Exact por HTTP dentro dela) e o ALTER abaixo precisa de
lock em `nat_qualificacao_state`.

NÃO envia mensagem, NÃO altera nat_enabled/qualificacao_enabled, NÃO toca em exact_leads,
contacts ou messages. Nenhum comportamento muda ao rodar isto.

------------------------------------------------------------------------------------------
POR QUE exact_stage_events EXISTE
------------------------------------------------------------------------------------------
`sync_exact_leads` faz `setattr(existing, key, value)` para os 10 campos a cada passada
(`exact_spotter.py:455-457`) — sobrescreve sem comparar, e `exact_leads.stage` é uma coluna
só. Hoje é IMPOSSÍVEL distinguir "o lead entrou em Follow 1 agora" de "está em Follow 1 há
três semanas".

Sem essa distinção, uma régua de follow-up dispararia sobre ESTADO e, na primeira execução,
varreria de uma vez os 54 leads parados nos follows do 18535. Esta tabela é o que transforma
"onde o lead está" em "quando ele chegou aqui" — é o gatilho da cadência, não observabilidade.

------------------------------------------------------------------------------------------
NOTAS DE SCHEMA
------------------------------------------------------------------------------------------
  * SEM FK para exact_leads — padrão do projeto para tabelas escritas dentro de caminho
    quente. Uma FK aqui só acrescentaria um modo de falha capaz de derrubar o sync inteiro.

  * `stage_de` é NULLABLE, e o NULL é informação: significa PRIMEIRA APARIÇÃO do lead. A
    régua precisa distinguir "nasceu em Follow 1" de "migrou para Follow 1" — são gatilhos
    diferentes.

  * `observado_em` é UTC (`now()` do Postgres, que está em Etc/UTC), e não naive-SP como
    `messages.timestamp`. Escolha deliberada: este carimbo é comparado com
    `exact_leads.register_date` e com `qualificacao_start_at`, que são UTC. Misturar os dois
    fusos numa comparação é o erro que `nat_guard._agora_sp` documenta.

  * NÃO há UNIQUE. A mesma transição pode acontecer de novo (Follow 4 -> Follow 5 -> Follow 4
    é possível se um SDR voltar o card), e o histórico tem que registrar as duas. O UNIQUE
    que o desenho pede — um envio por (lead, estágio) — pertence à tabela de LOG DA RÉGUA,
    que não nasce nesta sprint.

  * Índice em `(exact_lead_id, observado_em DESC)`: a pergunta é sempre "qual a última
    transição deste lead?".
"""
import asyncio

from sqlalchemy import text

from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        await conn.execute(text("SET lock_timeout = '3s'"))

        # 1. HISTÓRICO DE TRANSIÇÃO DE ESTÁGIO.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS exact_stage_events (
                id BIGSERIAL PRIMARY KEY,
                exact_lead_id INTEGER NOT NULL,
                -- NULL = primeira vez que vemos este lead. Ver o cabeçalho.
                stage_de VARCHAR(50),
                stage_para VARCHAR(50),
                funnel_id INTEGER,
                observado_em TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_stage_events_lead "
            "ON exact_stage_events (exact_lead_id, observado_em DESC)"))
        # A régua pergunta "quem entrou NESTE estágio depois de X?" — daí o par invertido.
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_stage_events_para "
            "ON exact_stage_events (stage_para, observado_em DESC)"))

        # 2. ENCERRAMENTO POR INATIVIDADE (Item 3).
        #
        # Coluna própria, e não reuso de `transferido_motivo`: os dois desfechos são
        # diferentes — transferido é "um humano assume", encerrado é "ninguém assume, o
        # lead calou". Misturá-los num campo só apagaria a distinção que a régua futura
        # precisa para escolher quem entra nela.
        await conn.execute(text(
            "ALTER TABLE nat_qualificacao_state ADD COLUMN IF NOT EXISTS "
            "encerrado_motivo TEXT"))
        await conn.execute(text(
            "ALTER TABLE nat_qualificacao_state ADD COLUMN IF NOT EXISTS "
            "encerrado_em TIMESTAMP"))

        # Conferência na mesma transação.
        n = (await conn.execute(text("SELECT count(*) FROM exact_stage_events"))).scalar()
        cols = (await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='nat_qualificacao_state' AND column_name LIKE 'encerrado%' "
            "ORDER BY column_name"))).scalars().all()
        idx = (await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='exact_stage_events' "
            "ORDER BY indexname"))).scalars().all()

    print(f"OK: exact_stage_events criada/verificada — {n} linha(s)")
    print(f"OK: índices — {', '.join(idx)}")
    print(f"OK: colunas novas em nat_qualificacao_state — {', '.join(cols)}")
    print("NADA foi ligado. nat_enabled e qualificacao_enabled intocados; nenhuma mensagem.")


if __name__ == "__main__":
    asyncio.run(migrate())
