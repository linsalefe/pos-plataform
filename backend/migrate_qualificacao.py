"""Migração do agente de pré-qualificação (Bloco A). Rodar uma vez:

    cd backend && venv/bin/python migrate_qualificacao.py

É idempotente: pode rodar de novo com segurança se falhar no meio.

O que faz, TUDO numa única transação (engine.begin):
  1. lock_timeout=3s — o sync_exact_leads mantém transação longa (pagina a Exact via HTTP
     dentro dela). O ALTER em nat_config abaixo precisa de lock; sem timeout, uma coincidência
     com o sync deixaria a migração pendurada segurando o singleton que o guard lê a cada envio.
  2. Cria nat_qualificacao_state — onde cada lead está no fluxo do AGENTE.
  3. Acrescenta qualificacao_enabled e qualificacao_start_at em nat_config.

NÃO envia mensagem. NÃO altera nat_enabled, nat_start_at, auto_welcome_config, exact_leads,
contacts nem messages. Nenhum comportamento de produção muda ao rodar isto: as colunas novas
nascem desligadas e nenhum código as lê ainda.

------------------------------------------------------------------------------------------
POR QUE UMA TABELA NOVA, E NÃO nat_flow_state
------------------------------------------------------------------------------------------
`nat_flow_state.etapa` tem CHECK com as 7 etapas do fluxo VELHO, e nenhuma serve aqui
(RECON G8). Reusar exigiria alargar o CHECK e passar a guardar dois fluxos distintos numa
tabela cuja chave é `contact_wa_id UNIQUE` — o mesmo lead não poderia estar nos dois, e a
precedência do webhook viraria um `if` sobre o valor de `etapa`, que é exatamente o tipo de
acoplamento que faz um fluxo quebrar o outro.

Tabelas separadas dão a precedência de graça: existe linha em nat_qualificacao_state? o
agente é o dono. Não existe? o fluxo velho segue como sempre.

------------------------------------------------------------------------------------------
NOTAS DE SCHEMA (decisões, não acidentes)
------------------------------------------------------------------------------------------
  * `contact_wa_id` UNIQUE: um estado por contato, mesma razão de nat_flow_state — todo o
    roteamento entra pelo wa_id do webhook, e sem a UNIQUE uma reentrega da Meta criaria dois
    estados e o fluxo dependeria de qual linha fosse lida primeiro.

  * SEM FK para contacts, exact_leads, users ou agendamentos. Mesma regra das outras tabelas
    escritas de dentro do webhook: uma FK só acrescenta um modo de falha capaz de derrubar o
    lote inteiro de mensagens. O estado serve ao fluxo; não pode ser a causa de uma mensagem
    de lead se perder. `agendamento_id` é o id da NOSSA tabela, guardado solto de propósito.

  * CHECK em `etapa`. Máquina fechada e conhecida: escrever etapa inexistente é bug, e o banco
    recusar na hora é melhor que descobrir com o lead parado num estado que ninguém consome.
    Acrescentar etapa exige migração — o atrito é desejado.

  * `ultimo_wa_message_id` é a trava de idempotência, padrão `_ja_processado` do nat_flow: a
    Meta reentrega webhook, e sem ele a mesma resposta avançaria a etapa duas vezes.

  * `origem` ('lp' | 'exact') com CHECK: diz de qual gatilho o lead veio. Muda de onde a
    formação é lida (extras da LP × description da Exact) e serve de auditoria quando os dois
    caminhos divergirem.

  * `faixa_investimento` é COLETADA e nunca lida pelo fluxo. A régua R$100/200/300 é critério
    humano (RECON §1.11, decisão do time). A coluna existe para o relatório e para o dia em que
    houver regra — guardar não custa; deixar o agente decidir com ela custaria.

  * `transferido_motivo` guarda POR QUE o agente desistiu (fallback do LLM, lead pediu
    remarcação, ação impossível). Sem isso, `transferido_humano` vira um balde onde não se
    distingue "o LLM caiu" de "o lead pediu para falar com gente".

  * Índice em `etapa`: a leitura recorrente é por etapa.

  * `dados_extras` JSONB: o que o LLM extrair além dos 4 campos nomeados, sem exigir ALTER a
    cada pergunta nova do roteiro. NÃO é onde mora estado de máquina — etapa é coluna.
"""
import asyncio

from sqlalchemy import text

from app.database import engine

# Espelha models.ETAPAS_QUALIFICACAO_VALIDAS. Divergir daqui faz o INSERT falhar na hora,
# que é o comportamento desejado.
ETAPAS = (
    "aguardando_formacao",   # T3: lead sem formação conhecida; a abertura perguntou qual é
    "aguardando_ano",        # T1/T2: abertura afirmou a formação e perguntou o ano
    "aguardando_atuacao",    # passo 2 do roteiro: onde atua hoje
    "aguardando_motivacao",  # passo 3: pergunta aberta; a validação é gerada pelo LLM
    "ofertando_agenda",      # passo 4b: grade apresentada, esperando escolha
    "escolhendo_slot",       # lead indicou preferência; confirmando o slot exato
    "concluido",             # reunião marcada (ou confirmada) + lembrete agendado
    "transferido_humano",    # fallback, remarcação, ou pedido do lead. Agente silencia
    "encerrado",             # fim sem reunião, sem humano pendente
)

ORIGENS = ("lp", "exact")


async def migrate():
    lista_etapas = ", ".join(f"'{e}'" for e in ETAPAS)
    lista_origens = ", ".join(f"'{o}'" for o in ORIGENS)

    async with engine.begin() as conn:
        await conn.execute(text("SET lock_timeout = '3s'"))

        # 1. ESTADO DO AGENTE.
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS nat_qualificacao_state (
                id BIGSERIAL PRIMARY KEY,
                contact_wa_id VARCHAR(20) UNIQUE NOT NULL,
                exact_lead_id INTEGER,
                origem VARCHAR(10) NOT NULL,
                etapa VARCHAR(30) NOT NULL,

                -- Coletados pelo agente ao longo da conversa.
                formacao TEXT,
                ano_conclusao TEXT,
                atuacao TEXT,
                motivacao TEXT,
                faixa_investimento TEXT,
                dados_extras JSONB,

                -- A reunião, quando existir. Id da NOSSA tabela agendamentos, sem FK.
                agendamento_id BIGINT,

                -- Idempotência de webhook (padrão nat_flow._ja_processado).
                ultimo_wa_message_id TEXT,

                transferido_em TIMESTAMP,
                transferido_motivo TEXT,

                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),

                CONSTRAINT nat_qualif_etapa_valida CHECK (etapa IN ({lista_etapas})),
                CONSTRAINT nat_qualif_origem_valida CHECK (origem IN ({lista_origens}))
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_nat_qualif_etapa "
            "ON nat_qualificacao_state(etapa)"))
        # Fila do lembrete e relatório: quem tem reunião marcada.
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_nat_qualif_agendamento "
            "ON nat_qualificacao_state(agendamento_id) WHERE agendamento_id IS NOT NULL"))

        # 2. EIXOS DE LIGA/DESLIGA DO AGENTE — separados dos da NAT velha.
        #
        # DOIS eixos, como nat_enabled/nat_start_at: ligar só o booleano não faz o agente
        # atuar, porque o corte por data continua bloqueando. E são campos PRÓPRIOS: ligar o
        # agente não pode ressuscitar o fluxo de botões, que segue governado por nat_enabled.
        await conn.execute(text(
            "ALTER TABLE nat_config ADD COLUMN IF NOT EXISTS "
            "qualificacao_enabled BOOLEAN NOT NULL DEFAULT FALSE"))
        await conn.execute(text(
            "ALTER TABLE nat_config ADD COLUMN IF NOT EXISTS "
            "qualificacao_start_at TIMESTAMP"))

        # Conferência dentro da mesma transação — se algo acima não pegou, aparece aqui.
        linhas = (await conn.execute(
            text("SELECT count(*) FROM nat_qualificacao_state"))).scalar()
        cols = (await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='nat_config' AND column_name LIKE 'qualificacao%' "
            "ORDER BY column_name"))).scalars().all()
        estado = (await conn.execute(text(
            "SELECT nat_enabled, nat_start_at, qualificacao_enabled, qualificacao_start_at "
            "FROM nat_config WHERE id = 1"))).first()

    print("OK: tabela nat_qualificacao_state criada/verificada (+2 índices)")
    print(f"OK: etapas aceitas pelo CHECK: {', '.join(ETAPAS)}")
    print(f"OK: origens aceitas pelo CHECK: {', '.join(ORIGENS)}")
    print(f"OK: {linhas} linha(s) na tabela")
    print(f"OK: colunas novas em nat_config: {', '.join(cols)}")
    if estado:
        print(f"OK: nat_enabled={estado[0]} nat_start_at={estado[1]} | "
              f"qualificacao_enabled={estado[2]} qualificacao_start_at={estado[3]}")
    print("NAT e AGENTE permanecem DESLIGADOS. Nenhuma mensagem enviada, nenhuma config "
          "existente alterada.")


if __name__ == "__main__":
    asyncio.run(migrate())
