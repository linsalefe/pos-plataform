"""Migração do lead ESPONTÂNEO (Bloco A + B). Rodar uma vez:

    cd backend && venv/bin/python migrate_espontaneo.py

É idempotente: pode rodar de novo com segurança se falhar no meio.

O que faz, TUDO numa única transação (engine.begin):
  1. lock_timeout=3s — mesma razão de migrate_qualificacao.py: o sync_exact_leads mantém
     transação longa (pagina a Exact via HTTP dentro dela), e os ALTER abaixo precisam de
     lock. Sem timeout, uma coincidência com o sync deixaria a migração pendurada segurando
     nat_config, que o guard lê a cada envio.
  2. Alarga o CHECK de `etapa` com as 4 etapas do fluxo espontâneo.
  3. Alarga o CHECK de `origem` com 'espontaneo'.
  4. Cria nat_agendamento_token — o link personalizado que a Nat manda no chat.
  5. Acrescenta espontaneo_enabled em nat_config, DESLIGADO.

NÃO envia mensagem. NÃO liga nada. NÃO altera qualificacao_enabled, nat_enabled,
auto_welcome_config, exact_leads, contacts nem messages. Nenhum comportamento de produção
muda ao rodar isto: a coluna nova nasce desligada e nenhum código lê as etapas novas ainda.

------------------------------------------------------------------------------------------
POR QUE O ESPONTÂNEO MORA NA MESMA TABELA DO AGENTE
------------------------------------------------------------------------------------------
O oposto da decisão de `migrate_qualificacao.py`, e pelo mesmo critério.

Lá, `nat_flow_state` foi recusada porque o fluxo de botões e o agente disputariam a mesma
linha e a precedência do webhook viraria um `if` sobre `etapa`. Aqui não há disputa: o
espontâneo **é** o agente, com outra porta de entrada. As duas origens nunca coexistem no
mesmo contato — quem tem lead na Exact não é admitido como espontâneo, é a regra 2 da
admissão — e o webhook faz a mesma pergunta para os dois: existe linha em
`nat_qualificacao_state`? o agente é o dono.

Tabela separada obrigaria `agente_e_dono`, `estado_de` e a precedência a consultarem duas
tabelas e a decidirem qual vence quando as duas responderem. Isso é criar a disputa que a
separação de lá existe para evitar.

`origem = 'espontaneo'` é o que distingue, e é a mesma coluna que já distingue 'lp' de
'exact'.

------------------------------------------------------------------------------------------
POR QUE O CHECK É RECRIADO, E POR QUE ISSO É BARATO AGORA
------------------------------------------------------------------------------------------
Postgres não alarga um CHECK: é DROP + ADD, e o ADD valida a tabela inteira sob ACCESS
EXCLUSIVE. Com `nat_qualificacao_state` **vazia** (medido em 24/08: 0 linhas), a validação é
instantânea e o lock não encosta em ninguém.

Se um dia esta migração for reaproveitada com a tabela cheia, o padrão correto é
`ADD CONSTRAINT ... NOT VALID` seguido de `VALIDATE CONSTRAINT` numa transação separada —
que não bloqueia leitura. Não uso aqui porque `NOT VALID` deixaria a janela em que uma etapa
inválida entra sem ninguém ver, e hoje o custo de validar é zero.

O DROP usa `IF EXISTS` e o ADD é precedido de DROP: é o que torna a migração repetível.

------------------------------------------------------------------------------------------
AS ETAPAS NOVAS, E POR QUE SÃO 4 E NÃO 6
------------------------------------------------------------------------------------------
    esp_confirmando_interesse  a Nat se apresenta e pergunta em que pode ajudar. É AQUI que
                               aluno, fornecedor, engano e congresso saem para o humano —
                               e é aqui que a resposta com cara de robô comercial ENCERRA.
    esp_coletando_curso        qual pós. A lista real dos 13 subSources entra no contexto;
                               o modelo escolhe dentro dela ou segue sem curso.
    esp_coletando_formacao     formação E atuação numa etapa só. O espontâneo é mais curto
                               que o roteiro da LP de propósito: quem escreveu primeiro já
                               demonstrou interesse, e cada pergunta a mais é uma chance de
                               abandono antes do link.
    esp_link_enviado           link mandado. A Nat responde dúvidas (a janela de 24h está
                               aberta) mas não repete o link mais de 1x.

Os desfechos são os que já existem: `concluido`, `transferido_humano`, `encerrado`. Não
nascem etapas terminais novas — o encerramento por inatividade de 72h já as consome, e criar
gêmeas obrigaria toda régua futura a conhecer as duas famílias.

------------------------------------------------------------------------------------------
NOTAS DE SCHEMA DO TOKEN (decisões, não acidentes)
------------------------------------------------------------------------------------------
  * `token` UNIQUE, gerado com `secrets.token_urlsafe(32)` (~43 chars, 256 bits). A URL é
    pública e não autenticada: adivinhar um token é agendar no nome de outra pessoa. Id
    sequencial na URL seria enumerável em minutos.

  * `contact_wa_id` guarda o wa_id do INBOUND, verbatim. É a única fonte do telefone que vai
    para o `LeadsAdd` — a pessoa nunca digita telefone na página. E é o que torna o fluxo
    espontâneo imune ao 9º dígito: tudo aqui nasce da grafia que chegou, não de uma montada
    a partir de um cadastro (ver `app/telefone.py`).

  * SEM FK para contacts nem agendamentos. Mesma regra das outras tabelas escritas de dentro
    do webhook: uma FK só acrescenta um modo de falha capaz de derrubar o lote de mensagens.

  * `expira_em` e `usado_em` são NAIVE EM SÃO PAULO, como `nat_scheduled_actions.run_at`;
    `criado_em` é UTC, porque vem de `DEFAULT NOW()`. Os dois fusos na mesma tabela é o que
    já existe no projeto — e é exatamente a fronteira que custou caro em 25/08 (o 9º dígito
    do outro lado). Aqui fica ESCRITO: quem compara `expira_em` compara com
    `nat_guard._agora_sp()`, NUNCA com `NOW()` do Postgres, que está 3h à frente e faria
    todo token nascer com 3h a menos de vida.

  * `usado_em` é o single-use, e é NULO até o booking. A trava real é o índice único parcial
    `uq_token_vivo`: dois cliques simultâneos no mesmo link não podem virar dois leads na
    Exact, e `LeadsAdd` não tem idempotência nenhuma para desfazer isso.

  * `revogado_em` existe por causa de um furo do primeiro desenho: com o índice olhando só
    `usado_em IS NULL`, um token que VENCESSE sem clique trancaria o contato para sempre —
    `usado_em` seguiria NULL e a emissão seguinte bateria no índice. Aposentar marcando
    `usado_em` resolveria o índice e mentiria no relatório, misturando link abandonado com
    link usado. Duas colunas, dois fatos.

  * `curso` guarda o subSource JÁ RESOLVIDO contra a allowlist, não o texto que a pessoa
    escreveu. `LeadsAdd` CRIA subSource que não existe e não há endpoint para remover
    (FINDINGS §11) — deixar texto livre chegar lá é como o cadastro ganhou `DialogicasTurma`
    permanentemente.

  * `agendamento_id` fecha o círculo: o gatilho 4.5 acha a reunião pelo id da NOSSA tabela.
"""
import asyncio

from sqlalchemy import text

from app.database import engine

# Espelha models.ETAPAS_QUALIFICACAO_VALIDAS depois desta sprint. Divergir daqui faz o
# INSERT falhar na hora, que é o comportamento desejado.
ETAPAS = (
    # --- fluxo da LP / Exact (já existiam) ---
    "aguardando_formacao",
    "aguardando_ano",
    "aguardando_atuacao",
    "aguardando_motivacao",
    "ofertando_agenda",
    "escolhendo_slot",
    # --- fluxo ESPONTÂNEO (novas) ---
    "esp_confirmando_interesse",
    "esp_coletando_curso",
    "esp_coletando_formacao",
    "esp_link_enviado",
    # --- desfechos, comuns aos dois ---
    "concluido",
    "transferido_humano",
    "encerrado",
)

ORIGENS = ("lp", "exact", "espontaneo")

DIAS_DE_VIDA_DO_TOKEN = 7


async def migrate():
    lista_etapas = ", ".join(f"'{e}'" for e in ETAPAS)
    lista_origens = ", ".join(f"'{o}'" for o in ORIGENS)

    async with engine.begin() as conn:
        await conn.execute(text("SET lock_timeout = '3s'"))

        # ------------------------------------------------------------------ 1. CHECKs
        antes = (await conn.execute(text(
            "SELECT count(*) FROM nat_qualificacao_state"))).scalar()
        if antes:
            # Não aborta: só avisa. Com linhas, o ADD CONSTRAINT valida a tabela sob ACCESS
            # EXCLUSIVE — ainda rápido para milhares de linhas, mas deixa de ser gratuito.
            print(f"⚠️  nat_qualificacao_state tem {antes} linha(s): o ADD CONSTRAINT vai "
                  f"validar todas sob lock. Esperado 0 nesta sprint.")

        await conn.execute(text(
            "ALTER TABLE nat_qualificacao_state "
            "DROP CONSTRAINT IF EXISTS nat_qualif_etapa_valida"))
        await conn.execute(text(
            f"ALTER TABLE nat_qualificacao_state ADD CONSTRAINT nat_qualif_etapa_valida "
            f"CHECK (etapa IN ({lista_etapas}))"))

        await conn.execute(text(
            "ALTER TABLE nat_qualificacao_state "
            "DROP CONSTRAINT IF EXISTS nat_qualif_origem_valida"))
        await conn.execute(text(
            f"ALTER TABLE nat_qualificacao_state ADD CONSTRAINT nat_qualif_origem_valida "
            f"CHECK (origem IN ({lista_origens}))"))

        # `origem VARCHAR(10)` não cabe 'espontaneo' com folga — são exatamente 10 chars.
        # Alargar agora evita que a próxima origem exija outra migração, e VARCHAR maior não
        # custa nada em Postgres (o storage é o mesmo; o limite é só um CHECK implícito).
        await conn.execute(text(
            "ALTER TABLE nat_qualificacao_state ALTER COLUMN origem TYPE VARCHAR(20)"))

        # ------------------------------------------------------------------- 2. token
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS nat_agendamento_token (
                id BIGSERIAL PRIMARY KEY,

                -- secrets.token_urlsafe(32). A URL é pública: id sequencial seria enumerável.
                token TEXT UNIQUE NOT NULL,

                -- wa_id do INBOUND, verbatim. Única fonte do telefone do LeadsAdd.
                contact_wa_id VARCHAR(20) NOT NULL,

                -- O que a Nat já coletou no chat. Tudo opcional: a página pede o que faltar.
                nome TEXT,
                curso TEXT,          -- subSource JÁ RESOLVIDO contra a allowlist
                formacao TEXT,
                atuacao TEXT,

                -- NAIVE EM SÃO PAULO. Comparar com nat_guard._agora_sp(), nunca com NOW().
                expira_em TIMESTAMP NOT NULL,
                usado_em TIMESTAMP,

                -- Aposentadoria SEM uso: o token venceu e um novo foi emitido no lugar.
                -- Existe para o índice parcial abaixo poder distinguir "vivo" de "morto sem
                -- ter sido usado" — sem ela, um token que expirasse sem clique trancaria o
                -- contato para sempre, porque `usado_em` continuaria NULL e o índice único
                -- recusaria qualquer emissão nova. Marcar como `usado` resolveria o índice
                -- e mentiria no relatório: "quantos links foram usados?" passaria a contar
                -- os abandonados.
                revogado_em TIMESTAMP,

                -- Id da NOSSA tabela agendamentos, solto de propósito (sem FK).
                agendamento_id BIGINT,

                -- UTC, vem do DEFAULT. Auditoria; nunca comparado com as duas de cima.
                criado_em TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_token_contato "
            "ON nat_agendamento_token(contact_wa_id)"))
        # UM token VIVO por contato — vivo = não usado e não revogado.
        #
        # É o que impede a Nat de espalhar links a cada mensagem e o que dá sentido à regra
        # "não repete o link mais de 1x": pedir de novo devolve O MESMO token, não um novo.
        # E é a trava contra a corrida real: dois cliques simultâneos no link não podem virar
        # dois leads na Exact, porque `LeadsAdd` não tem idempotência nenhuma para desfazer.
        #
        # A emissão, no código, é: procura token vivo -> se venceu, `revogado_em = agora` ->
        # insere o novo. Nunca `usado_em` para aposentar o que não foi usado (ver a coluna).
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_token_vivo "
            "ON nat_agendamento_token(contact_wa_id) "
            "WHERE usado_em IS NULL AND revogado_em IS NULL"))

        # ------------------------------------------------------------------- 3. flag
        # Eixo PRÓPRIO, separado de qualificacao_enabled: ligar o espontâneo não pode
        # depender de ligar o fluxo da LP, nem o contrário. Mesmo padrão de
        # nat_enabled × qualificacao_enabled.
        await conn.execute(text(
            "ALTER TABLE nat_config ADD COLUMN IF NOT EXISTS "
            "espontaneo_enabled BOOLEAN NOT NULL DEFAULT FALSE"))

        # -------------------------------------------- conferência na mesma transação
        etapas_ok = (await conn.execute(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'nat_qualif_etapa_valida'"))).scalar()
        origens_ok = (await conn.execute(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'nat_qualif_origem_valida'"))).scalar()
        cols = (await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='nat_agendamento_token' ORDER BY ordinal_position"))).scalars().all()
        flag = (await conn.execute(text(
            "SELECT espontaneo_enabled, qualificacao_enabled, nat_enabled "
            "FROM nat_config WHERE id = 1"))).first()

    print(f"OK: CHECK de etapa  -> {etapas_ok}")
    print(f"OK: CHECK de origem -> {origens_ok}")
    print(f"OK: nat_agendamento_token ({len(cols)} colunas): {', '.join(cols)}")
    print("OK: índices idx_token_contato e uq_token_vivo (único parcial: 1 token VIVO por "
          "contato, onde vivo = não usado e não revogado)")
    if flag:
        print(f"OK: espontaneo_enabled={flag[0]} | qualificacao_enabled={flag[1]} | "
              f"nat_enabled={flag[2]}")
    print(f"OK: token vive {DIAS_DE_VIDA_DO_TOKEN} dias (aplicado no código, não no schema)")
    print("ESPONTÂNEO permanece DESLIGADO. Nenhuma mensagem enviada, nenhuma config "
          "existente alterada.")


if __name__ == "__main__":
    asyncio.run(migrate())
