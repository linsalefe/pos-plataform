"""Migração da máquina de estados do fluxo NAT. Rodar uma vez:

    cd backend && venv/bin/python migrate_nat_flow_state.py

É idempotente: pode rodar de novo com segurança se falhar no meio.

O que faz, TUDO numa única transação (engine.begin):
  1. lock_timeout=3s — mesma razão de migrate_nat_config.py: o sync_exact_leads mantém
     transação longa. Aqui só criamos tabela NOVA (sem ALTER, sem FK para tabela quente),
     então na prática não há disputa de lock; o timeout é rede de segurança.
  2. Cria nat_flow_state — onde cada lead está no fluxo.

NÃO envia mensagem, NÃO altera auto_welcome_config nem nat_config, NÃO toca em exact_leads,
contacts ou messages. Nenhum comportamento de produção muda ao rodar isto.

Notas de schema (decisões, não acidentes):

  * contact_wa_id é UNIQUE: um estado por contato. É a chave real da tabela — todo o
    roteamento entra pelo wa_id que veio no webhook. Sem a UNIQUE, uma reentrega da Meta
    poderia criar dois estados para o mesmo lead e o fluxo passaria a depender de qual linha
    fosse lida primeiro.

  * SEM FK para contacts, exact_leads ou users — mesma razão de nat_button_events: esta
    tabela é escrita de dentro do webhook, e uma FK só acrescentaria um modo de falha capaz
    de derrubar o lote inteiro de mensagens. O estado do fluxo serve ao fluxo; ele não pode
    ser a causa de uma mensagem de lead se perder.

  * CHECK em `etapa` com as 7 etapas válidas. A máquina de estados é fechada e conhecida —
    escrever uma etapa inexistente é bug, e o banco recusar é melhor do que descobrir depois
    com o lead parado num estado que nenhuma transição consome. Acrescentar etapa exige
    migração, que é exatamente o atrito desejado.
    `sem_contato` já entra aqui embora só seja usada no Bloco 6: é barato agora e evitaria
    uma migração de ALTER depois.

  * ultimo_wa_message_id é a trava de idempotência. A Meta reentrega webhook; sem ele, o
    mesmo clique avançaria o estado duas vezes e mandaria a mensagem seguinte em duplicata.
    TEXT e não VARCHAR(255) só por simetria com nat_button_events.

  * tentativas_contato e transferido_em nascem aqui sem consumidor: são do Bloco 5/6 (SLA e
    recuperação). Estão na criação da tabela para não precisar de ALTER numa tabela que a
    essa altura já estará sendo escrita pelo webhook em produção.

  * Índice em `etapa`: a fila da fase 2 do Cenário 2 é exatamente
    `WHERE etapa = 'aguardando_horario'`, varrida periodicamente.
"""
import asyncio
from sqlalchemy import text
from app.database import engine

ETAPAS_VALIDAS = (
    "aguardando_horario",    # chegou fora de 09h-19h; NADA enviado; fila da fase 2
    "aguardando_resposta",   # nat_boasvindas enviado, esperando clique
    "aguardando_motivacao",  # clicou "Sim", nat_sim enviado, esperando texto
    "aguardando_ligacao",    # nat_confirma_transferencia enviado; SDR deve ligar
    "reagendado",            # pediu outro horário
    "sem_contato",           # SDR não conseguiu contato (Bloco 6)
    "encerrado",             # fim de linha
)


async def migrate():
    lista_sql = ", ".join(f"'{e}'" for e in ETAPAS_VALIDAS)

    async with engine.begin() as conn:
        # 1. Não travar a API atrás de uma transação longa do sync.
        await conn.execute(text("SET lock_timeout = '3s'"))

        # 2. Estado do fluxo, um por contato.
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS nat_flow_state (
                id BIGSERIAL PRIMARY KEY,
                contact_wa_id VARCHAR(20) NOT NULL UNIQUE,
                exact_lead_id INTEGER,
                sdr_user_id INTEGER,
                etapa VARCHAR(30) NOT NULL,
                tentativas_contato INTEGER NOT NULL DEFAULT 0,
                horario_preferencial TEXT,
                ultimo_wa_message_id TEXT,
                transferido_em TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT nat_flow_state_etapa_valida CHECK (etapa IN ({lista_sql}))
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_nat_flow_etapa ON nat_flow_state(etapa)"))

        total = (await conn.execute(text("SELECT count(*) FROM nat_flow_state"))).scalar()

    print("OK: tabela nat_flow_state criada/verificada (+1 índice em etapa)")
    print(f"OK: etapas aceitas pelo CHECK: {', '.join(ETAPAS_VALIDAS)}")
    print(f"OK: {total} linha(s) na tabela")
    print("NAT permanece DESLIGADA. Nenhuma mensagem enviada, nenhuma config alterada.")


if __name__ == "__main__":
    asyncio.run(migrate())
