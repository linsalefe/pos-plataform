"""Migração do Bloco 6 do fluxo NAT (recuperação — "não consegui contato").

Rodar uma vez:

    cd backend && venv/bin/python migrate_nat_contact_attempts.py

É idempotente: pode rodar de novo com segurança se falhar no meio. Toda a migração roda numa
ÚNICA transação (engine.begin) — ou entra tudo, ou não entra nada.

O que faz:
  1. lock_timeout=3s — regra fixa das migrações desta base. Aqui é conformidade, não
     necessidade: só cria tabela NOVA, não há ALTER em tabela quente para disputar lock com a
     transação longa do sync_exact_leads. O timeout fica porque uma migração que possa
     pendurar a API é sempre a próxima a ser escrita, e o hábito é a defesa.
  2. Cria nat_contact_attempts — o histórico de tentativas de ligação sem sucesso.

NÃO envia mensagem, NÃO altera nat_config nem auto_welcome_config, NÃO toca em exact_leads,
contacts ou users, NÃO altera nat_flow_state (a coluna tentativas_contato que o Bloco 6
consome já existe desde migrate_nat_flow_state.py, sem consumidor). Nenhum comportamento de
produção muda ao rodar isto — a tabela nasce vazia e a NAT segue DESLIGADA.

------------------------------------------------------------------------------------------
NOTAS DE SCHEMA (decisões, não acidentes)
------------------------------------------------------------------------------------------

POR QUE UMA TABELA NOVA, E NÃO call_logs
  call_logs é o registro de ligações do Twilio: `call_sid` é UNIQUE NOT NULL, e uma tentativa
  marcada à mão pelo SDR não tem call_sid nenhum. Enfiá-la lá exigiria inventar um sid falso
  para satisfazer o NOT NULL — dado fabricado numa tabela que hoje é fiel ao que o Twilio
  reportou. A semântica também é outra: call_logs responde "o que aconteceu na telefonia",
  esta tabela responde "quantas vezes o humano já tentou e desistiu neste lead do fluxo NAT".

  A pergunta que esta tabela existe para responder é o TETO: no máximo 2 tentativas por lead,
  e na 2ª o fluxo encerra. O contador vivo é nat_flow_state.tentativas_contato (é ele que o
  endpoint lê para decidir); esta tabela é o HISTÓRICO — quem marcou, quando, e com que
  desfecho. Um contador sem histórico não permite auditar um lead que encerrou cedo.

contact_wa_id
  * SEM FK para contacts — mesma razão de nat_flow_state, nat_button_events e
    nat_scheduled_actions: a escrita acontece dentro do fluxo da NAT (endpoint chamado da
    tela de conversas), e uma FK só acrescentaria um modo de falha. VARCHAR(20) para casar
    com contacts.wa_id e com as outras tabelas da NAT.

tentativa_num
  * O número da tentativa (1 ou 2), copiado de nat_flow_state.tentativas_contato no momento
    do registro. Redundante com "contar as linhas do contato" só na aparência: o contador
    vivo é o que o endpoint consulta para aplicar o teto, e guardar o número em cada linha
    torna as duas fontes conferíveis uma contra a outra. Divergirem é sinal de bug, e é bom
    que seja visível.
  * NÃO há UNIQUE em (contact_wa_id, tentativa_num), de propósito. Seria uma rede de
    segurança contra duplo registro, mas a rede erraria o alvo: quem defende contra dois
    cliques simultâneos é o SELECT ... FOR UPDATE no nat_flow_state dentro do endpoint (que
    serializa as chamadas do mesmo contato) mais a janela de idempotência de 30s. Um UNIQUE
    aqui transformaria a corrida remanescente num IntegrityError, e o SDR veria um 500 ao
    clicar num botão — pior desfecho do que a linha extra que ele evitaria.

registrado_por
  * users.id de quem clicou. INTEGER sem FK, igual a nat_flow_state.assumido_por. Nullable
    porque um registro futuro de origem automática (varredura, integração) não teria autor
    humano — e porque uma coluna NOT NULL sem default é a que trava a migração seguinte.

resultado
  * VARCHAR(20) nullable e SEM CHECK. Hoje o endpoint grava sempre "sem_contato"; o conjunto
    de valores ainda não está fechado (Sprint B/C podem acrescentar "caixa_postal",
    "numero_invalido"). Mesmo argumento do `kind` de nat_scheduled_actions em
    migrate_nat_sprint3.py: máquina de estados fechada leva CHECK (etapa, status), ponto de
    extensão não leva. A etapa do lead, essa sim, continua protegida pelo CHECK de
    nat_flow_state, que já aceita 'sem_contato' desde migrate_nat_flow_state.py — conferido
    em pg_constraint, nenhum ALTER é necessário aqui.

created_at
  * TIMESTAMP DEFAULT NOW(), e NOW() é UTC neste banco (Etc/UTC), enquanto o resto do fluxo
    NAT trabalha em naive de São Paulo (_agora_sp). Isso é intencional e inofensivo porque
    created_at NÃO entra em nenhuma comparação de negócio: quem decide a janela de
    idempotência de 30s é o endpoint, que grava e compara o SEU próprio carimbo em SP. O
    DEFAULT é rede para linha inserida à mão em psql, não a fonte do valor.
    (É a mesma escolha de nat_scheduled_actions: run_at é SP e vem de Python; created_at é
    carimbo de auditoria e pode ser do banco.)

ÍNDICE (contact_wa_id, created_at)
  * É exatamente a consulta do endpoint — "a última tentativa deste contato" — que roda a
    cada clique, e o ORDER BY created_at DESC LIMIT 1 sai do índice sem ordenar. A tabela vai
    ser minúscula por muito tempo; o índice é barato e evita que "minúscula" vire premissa.
"""
import asyncio

from sqlalchemy import text

from app.database import engine


async def migrate():
    async with engine.begin() as conn:
        # 1. Não travar a API atrás de uma transação longa do sync.
        await conn.execute(text("SET lock_timeout = '3s'"))

        # 2. HISTÓRICO DE TENTATIVAS DE CONTATO (Bloco 6).
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS nat_contact_attempts (
                id BIGSERIAL PRIMARY KEY,
                contact_wa_id VARCHAR(20) NOT NULL,
                tentativa_num INTEGER NOT NULL,
                registrado_por INTEGER,
                resultado VARCHAR(20),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        # "A última tentativa deste contato" — a consulta da janela de idempotência.
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_nat_attempts_contato_ts
                ON nat_contact_attempts (contact_wa_id, created_at)
        """))

        # Conferência dentro da mesma transação — se algo acima não pegou, aparece aqui.
        linhas = (await conn.execute(
            text("SELECT count(*) FROM nat_contact_attempts"))).scalar()
        colunas = (await conn.execute(text("""
            SELECT count(*) FROM information_schema.columns
             WHERE table_name = 'nat_contact_attempts'
               AND column_name IN ('id', 'contact_wa_id', 'tentativa_num',
                                   'registrado_por', 'resultado', 'created_at')
        """))).scalar()
        indices = (await conn.execute(text("""
            SELECT count(*) FROM pg_indexes
             WHERE tablename = 'nat_contact_attempts'
               AND indexname = 'idx_nat_attempts_contato_ts'
        """))).scalar()
        etapa_ok = (await conn.execute(text("""
            SELECT pg_get_constraintdef(oid) LIKE '%sem_contato%'
              FROM pg_constraint WHERE conname = 'nat_flow_state_etapa_valida'
        """))).scalar()

    print(f"OK: nat_contact_attempts criada/verificada — {linhas} linha(s)")
    print(f"OK: {colunas}/6 colunas presentes")
    print(f"OK: índice (contact_wa_id, created_at) presente: {indices == 1}")
    print(f"OK: CHECK de nat_flow_state.etapa já aceita 'sem_contato': {etapa_ok} "
          "(nenhum ALTER necessário)")
    print("NAT permanece DESLIGADA. Nenhuma mensagem enviada, nenhuma config alterada.")


if __name__ == "__main__":
    asyncio.run(migrate())
