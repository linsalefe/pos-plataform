"""S6-1 — autoria do outbound: `messages.sent_by` e `messages.template_name`.

    cd backend && venv/bin/python migrate_message_autoria.py

É idempotente (ADD COLUMN IF NOT EXISTS, índices por nome). Pode rodar de novo.

O QUE ESTA MIGRAÇÃO CONSERTA
-------------------------------------------------------------------------------------------
`messages` não guarda QUEM enviou nem QUAL template saiu. As cinco rotas de envio
(`routes.py` send_text/send_template/send_media, `exact_routes.bulk_send_template`,
`nat_sender.enviar`) recebem `current_user` — e o usam, para calar o agente — e o descartam
na hora de gravar a Message. `content` guarda só o texto RENDERIZADO.

Medido no RECON_FOLLOWS_HUMANO_IA_20260901: todo relatório por SDR é hoje inexequível. O
único traço durável é `nat_qualificacao_state.dados_extras->'assumido_por'`, que só existe
quando o agente estava em etapa ativa (45 envios na janela de 8 dias, de 517 templates
humanos). A última alternativa — a assinatura no corpo do template — está ERRADA em 52% dos
casos (`tentativa_contato` recebe o nome do curso no `{{2}}`), então nem para inferir serve.

  sent_by        INTEGER FK users(id)  -> quem apertou enviar. NULL = não foi humano logado
                                         (agente, boas-vindas automática, disparo agendado)
  template_name  VARCHAR(512)          -> nome do template na Meta. NULL = não foi template

SEM BACKFILL, E ISSO NÃO É PREGUIÇA. O passado não volta: o dado nunca existiu em lugar
nenhum do banco. Inventar `sent_by` a partir de `contacts.assigned_to` (dono na Exact) ou da
assinatura no corpo produziria um número que PARECE medição e não é. As colunas nascem NULL
para todo o histórico, e a primeira linha preenchida é o primeiro envio depois do deploy.

VARCHAR(512) espelha `whatsapp_templates.name`, que é 512. Nome de template da Meta é curto,
mas divergir do tipo da tabela irmã cria um truncamento silencioso onde hoje não há nenhum.

POR QUE É SEGURO NUMA TABELA QUENTE (32 846 linhas, 17 MB, escrita pelo webhook)
-------------------------------------------------------------------------------------------
  1. ADD COLUMN nullable e SEM DEFAULT é operação de CATÁLOGO no Postgres — não reescreve a
     tabela, não varre as 32 mil linhas. Confirmado: PostgreSQL 14.24.
  2. `lock_timeout = 3s`. O ALTER precisa de ACCESS EXCLUSIVE por um instante, e o
     `sync_exact_leads` mantém transação longa (pagina a Exact por HTTP e só commita no
     fim). Sem o timeout, o ALTER esperaria o sync SEGURANDO a fila de quem vem atrás — e o
     webhook, que só quer inserir mensagem, ficaria parado atrás dele. Com o timeout, o pior
     caso é a migração falhar e ser rodada de novo, em vez de travar o recebimento.
  3. A FK entra `NOT VALID` e só depois é validada. `ADD CONSTRAINT ... REFERENCES` numa
     tacada valida na hora, segurando ACCESS EXCLUSIVE durante a varredura; `NOT VALID` +
     `VALIDATE CONSTRAINT` faz a varredura sob SHARE UPDATE EXCLUSIVE, que não bloqueia
     INSERT. A coluna nasce toda NULL, então a validação não pode falhar — o cuidado é com
     o LOCK, não com o dado.
  4. Os índices entram CONCURRENTLY, fora de bloco de transação (daí o AUTOCOMMIT).

Os dois índices são PARCIAIS porque a esmagadora maioria das linhas fica NULL para sempre:
todo o histórico, todo inbound e todo envio do agente. Índice cheio guardaria 32 mil NULLs
para responder perguntas que só existem sobre o que NÃO é NULL.

NÃO altera comportamento nenhum. As colunas nascem NULL e ninguém as lê; quem as preenche é
o código do S6-1, que sobe depois. NÃO envia mensagem, NÃO toca em nat_config nem em
auto_welcome_config.
"""
import asyncio

from sqlalchemy import text

from app.database import engine

COLUNAS = (
    ("sent_by", "INTEGER"),
    ("template_name", "VARCHAR(512)"),
)
FK = "messages_sent_by_fkey"
INDICES = {
    "idx_messages_sent_by":
        "CREATE INDEX CONCURRENTLY idx_messages_sent_by ON messages (sent_by) "
        "WHERE sent_by IS NOT NULL",
    "idx_messages_template_name":
        "CREATE INDEX CONCURRENTLY idx_messages_template_name ON messages (template_name) "
        "WHERE template_name IS NOT NULL",
}


async def migrar():
    # ---- Fase A: colunas + FK NOT VALID (transação curta, com lock_timeout) --------------
    async with engine.begin() as conn:
        await conn.execute(text("SET lock_timeout = '3s'"))

        antes = (await conn.execute(text(
            "SELECT count(*) FROM messages"))).scalar()
        print(f"BEFORE — messages: {antes} linhas")

        for nome, tipo in COLUNAS:
            await conn.execute(text(
                f"ALTER TABLE messages ADD COLUMN IF NOT EXISTS {nome} {tipo}"))
            print(f"  ADD COLUMN IF NOT EXISTS {nome} {tipo}")

        ja_tem_fk = (await conn.execute(text(
            "SELECT count(*) FROM pg_constraint WHERE conname = :n"), {"n": FK})).scalar()
        if ja_tem_fk:
            print(f"  {FK} já existe — nada a fazer")
        else:
            await conn.execute(text(
                f"ALTER TABLE messages ADD CONSTRAINT {FK} "
                f"FOREIGN KEY (sent_by) REFERENCES users(id) NOT VALID"))
            print(f"  ADD CONSTRAINT {FK} FOREIGN KEY (sent_by) REFERENCES users(id) NOT VALID")

    # ---- Fase B: VALIDATE + índices CONCURRENTLY (fora de transação) --------------------
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")

        await conn.execute(text(f"ALTER TABLE messages VALIDATE CONSTRAINT {FK}"))
        print(f"  VALIDATE CONSTRAINT {FK}")

        existentes = set((await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='messages'"))).scalars().all())
        for nome, ddl in INDICES.items():
            if nome in existentes:
                print(f"  {nome} já existe — nada a fazer")
                continue
            await conn.execute(text(ddl))
            print(f"  {ddl}")

        print("\nAFTER — messages:")
        for nome, tipo, nulo in (await conn.execute(text("""
                SELECT column_name, data_type, is_nullable FROM information_schema.columns
                WHERE table_name='messages' AND column_name IN ('sent_by','template_name')
                ORDER BY column_name"""))).all():
            print(f"  coluna {nome} {tipo} nullable={nulo}")

        for nome, valido in (await conn.execute(text("""
                SELECT c.relname, i.indisvalid FROM pg_index i
                JOIN pg_class c ON c.oid = i.indexrelid
                WHERE c.relname IN ('idx_messages_sent_by','idx_messages_template_name')
                ORDER BY c.relname"""))).all():
            print(f"  índice {nome} indisvalid={valido}")

        convalidated = (await conn.execute(text(
            "SELECT convalidated FROM pg_constraint WHERE conname = :n"), {"n": FK})).scalar()
        print(f"  FK {FK} convalidated={convalidated}")

        preenchidas = (await conn.execute(text(
            "SELECT count(*) FROM messages WHERE sent_by IS NOT NULL "
            "   OR template_name IS NOT NULL"))).scalar()
        print(f"\nOK: {preenchidas} linha(s) com autoria preenchida "
              "(0 é o esperado — sem backfill, só envios FUTUROS)")
        print("Nenhum comportamento alterado.")


if __name__ == "__main__":
    asyncio.run(migrar())
