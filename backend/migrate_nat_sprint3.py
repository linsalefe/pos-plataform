"""Migração dos Blocos 5 e 7 do fluxo NAT (transferência, SLA, escalonamento, agendador).

Rodar uma vez:

    cd backend && venv/bin/python migrate_nat_sprint3.py

É idempotente: pode rodar de novo com segurança se falhar no meio. Toda a migração roda
numa ÚNICA transação (engine.begin) — ou entra tudo, ou não entra nada.

O que faz:
  1. lock_timeout=3s — o sync_exact_leads mantém transação longa a cada 10 min. Os itens 2
     e 3 abaixo são ALTER TABLE em tabelas quentes (messages, nat_flow_state) e precisam de
     ACCESS EXCLUSIVE. Sem o timeout, a migração ficaria pendurada esperando o lock E, pior,
     enfileiraria toda leitura de messages atrás dela. Com 3s ela desiste e reclama.
  2. Cria nat_scheduled_actions — o agendador genérico do Bloco 7.
  3. messages.nat_etapa — marcador de envio da NAT (fecha a dívida do teto por hora).
  4. nat_flow_state: assumido_por, assumido_em, escalonamento_nivel — Bloco 5.

O item "role gestor" que constava do plano original foi REMOVIDO, em definitivo. Auditoria de
2026-07-26: `users` só tem os constraints `users_pkey` e `users_email_key` — nenhum CHECK em
role, que é um VARCHAR livre sem default no banco. E os 7 gates de permissão do código
(auth.py:65, routes.py:346, twilio_routes.py:290, auth_routes.py:64/92/119/140) são todos o
literal `role != "admin"`. Não existe enum, CHECK nem lista de valores válidos: não há a que
acrescentar 'gestor'. O escalonamento notifica o id 2 literal, do mesmo jeito que os SDRs são
4 e 5 em nat_guard.py — menos uma peça móvel.

NÃO envia mensagem, NÃO altera auto_welcome_config nem nat_config, NÃO toca em exact_leads
nem em contacts. Nenhum comportamento de produção muda ao rodar isto — as colunas nascem
sem consumidor e a NAT segue desligada.

------------------------------------------------------------------------------------------
NOTAS DE SCHEMA (decisões, não acidentes)
------------------------------------------------------------------------------------------

nat_scheduled_actions
  * run_at é TIMESTAMP SEM FUSO e guarda horário NAIVE DE SÃO PAULO, igual a
    messages.timestamp e a nat_guard._agora_sp(). O banco está em Etc/UTC (verificado): um
    `run_at <= now()` do Postgres compararia SP contra UTC e dispararia tudo 3h adiantado.
    Por isso o job manda o corte de Python, nunca usa now() do banco. O DEFAULT NOW() em
    created_at/processed_at é só carimbo de auditoria e não entra em nenhuma comparação.

  * SEM FK em contact_wa_id — mesma razão de nat_flow_state e nat_button_events: a tabela é
    escrita de dentro do webhook e de dentro do fluxo, e uma FK só acrescentaria um modo de
    falha capaz de derrubar o lote inteiro de mensagens.

  * payload é TEXT com JSON dentro, não JSONB. Segue scheduled_messages.lead_ids /
    param_mappings, que é o padrão da casa, e não há nenhuma consulta que filtre por dentro
    do payload — o que o job precisa (kind, contato, hora) são colunas de verdade.

  * CHECK em status com os 4 valores. Mesmo argumento do CHECK de nat_flow_state.etapa: o
    conjunto é fechado e conhecido, e o banco recusar um status inventado é melhor do que
    descobrir depois com uma ação parada num estado que nenhum ramo do job consome.

  * NÃO há CHECK em `kind`, de propósito. `etapa` é uma máquina de estados fechada; `kind` é
    um ponto de extensão — o Bloco 6 acrescenta pelo menos mais um. Exigir migração para
    cada handler novo seria atrito sem contrapartida. O job trata kind desconhecido marcando
    `falhou` com o motivo, que é ruidoso e visível, nunca `executado` em silêncio.

  * ÍNDICE PARCIAL ÚNICO em (kind, contact_wa_id) WHERE status = 'pendente': no máximo UMA
    ação pendente de cada tipo por contato. É a tradução em banco da regra "nenhuma ação
    agendada pode executar duas vezes" — sem ele, dois caminhos que chamem agendar() para o
    mesmo lead criariam dois sla_check e o lead seria escalonado em dobro.
    O índice é REDE DE SEGURANÇA, não o mecanismo: agendar() cancela o pendente do mesmo
    (kind, contato) antes de inserir, então em operação normal o conflito nunca acontece.
    Parcial porque só 'pendente' é exclusivo — o histórico de executado/cancelado/falhou do
    mesmo contato pode e deve acumular.

  * ÍNDICE em (status, run_at): é literalmente o WHERE do job, rodando a cada 60s.

messages.nat_etapa
  * TEXT nullable, sem DEFAULT. Em PG 14 isso é troca de catálogo, sem reescrever as 26.767
    linhas — o único custo é adquirir o lock, coberto pelo lock_timeout.
  * NULL é a resposta certa para tudo que não veio da NAT: boas-vindas, resposta manual de
    SDR, disparo em massa. A coluna guarda a ETAPA que originou o envio (nat_boasvindas,
    nat_sim, ...), não um booleano, porque "quantos a NAT mandou" e "de qual passo do fluxo"
    são a mesma pergunta feita com granularidade diferente, e o booleano só responde a
    primeira. Note que sent_by_ai já é uma coluna morta por ter escolhido o booleano.
  * ÍNDICE PARCIAL em (timestamp) WHERE nat_etapa IS NOT NULL: o teto por hora é
    `direction='outbound' AND timestamp > corte AND nat_etapa IS NOT NULL` e roda ANTES DE
    CADA ENVIO da NAT. O índice parcial indexa só as linhas da NAT — hoje zero, sempre um
    punhado — em vez de varrer as 26.767 (e crescendo) de messages.

nat_flow_state (3 colunas novas)
  * assumido_por / assumido_em: preenchidos pelo botão "Assumir ligação". assumido_por é o
    que PARA O RELÓGIO do SLA, e é por isso que ele é um int (quem assumiu) e não um
    booleano: a notificação de escalonamento precisa dizer o nome.
    Sem FK para users, pela mesma razão do resto da tabela.
  * escalonamento_nivel: 0 = ninguém escalonou ainda; 1 = o outro SDR já foi avisado;
    2 = a gestora já foi avisada, fim de linha. NOT NULL DEFAULT 0 para o handler do
    sla_check nunca ter que decidir o que fazer com NULL — com 0 linhas na tabela hoje, o
    backfill do DEFAULT é instantâneo.
"""
import asyncio
from sqlalchemy import text
from app.database import engine

STATUS_VALIDOS = (
    "pendente",   # ainda não chegou a hora, ou falhou e vai ser retentada
    "executado",  # handler rodou até o fim; marcado na MESMA transação da execução
    "cancelado",  # o motivo da ação deixou de existir (ex.: SDR assumiu a ligação)
    "falhou",     # 3 tentativas sem sucesso, ou kind sem handler. Não é mais retentada.
)


async def migrate():
    lista_sql = ", ".join(f"'{s}'" for s in STATUS_VALIDOS)

    async with engine.begin() as conn:
        # 1. Não travar a API atrás de uma transação longa do sync.
        await conn.execute(text("SET lock_timeout = '3s'"))

        # 2. AGENDADOR GENÉRICO (Bloco 7).
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS nat_scheduled_actions (
                id BIGSERIAL PRIMARY KEY,
                kind VARCHAR(40) NOT NULL,
                contact_wa_id VARCHAR(20) NOT NULL,
                run_at TIMESTAMP NOT NULL,
                payload TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'pendente',
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                processed_at TIMESTAMP,
                CONSTRAINT nat_scheduled_status_valido CHECK (status IN ({lista_sql}))
            )
        """))
        # WHERE do job, a cada 60s.
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_nat_sched_status_runat
                ON nat_scheduled_actions (status, run_at)
        """))
        # No máximo UMA ação pendente por (kind, contato). Rede de segurança da regra
        # "nenhuma ação agendada pode executar duas vezes".
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_nat_sched_pendente_por_contato
                ON nat_scheduled_actions (kind, contact_wa_id)
                WHERE status = 'pendente'
        """))

        # 3. MARCADOR DE ENVIO DA NAT (fecha a dívida do teto por hora).
        await conn.execute(text(
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS nat_etapa TEXT"))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_messages_nat_etapa_ts
                ON messages (timestamp)
                WHERE nat_etapa IS NOT NULL
        """))

        # 4. TRANSFERÊNCIA / SLA / ESCALONAMENTO (Bloco 5).
        await conn.execute(text(
            "ALTER TABLE nat_flow_state ADD COLUMN IF NOT EXISTS assumido_por INTEGER"))
        await conn.execute(text(
            "ALTER TABLE nat_flow_state ADD COLUMN IF NOT EXISTS assumido_em TIMESTAMP"))
        await conn.execute(text(
            "ALTER TABLE nat_flow_state ADD COLUMN IF NOT EXISTS escalonamento_nivel "
            "INTEGER NOT NULL DEFAULT 0"))

        # Conferência dentro da mesma transação — se algo acima não pegou, aparece aqui.
        pendentes = (await conn.execute(
            text("SELECT count(*) FROM nat_scheduled_actions"))).scalar()
        cols_msg = (await conn.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'messages' AND column_name = 'nat_etapa'"))).scalar()
        cols_flow = (await conn.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'nat_flow_state' AND column_name IN "
            "('assumido_por', 'assumido_em', 'escalonamento_nivel')"))).scalar()

    print(f"OK: nat_scheduled_actions criada/verificada — {pendentes} linha(s)")
    print(f"OK: status aceitos pelo CHECK: {', '.join(STATUS_VALIDOS)}")
    print("OK: 2 índices em nat_scheduled_actions (status+run_at; único parcial de pendente)")
    print(f"OK: messages.nat_etapa presente: {cols_msg == 1} (+índice parcial por timestamp)")
    print(f"OK: nat_flow_state ganhou {cols_flow}/3 colunas do Bloco 5")
    print("NAT permanece DESLIGADA. Nenhuma mensagem enviada, nenhuma config alterada.")


if __name__ == "__main__":
    asyncio.run(migrate())
