"""BLOCO 1 da sprint de Relatórios — a tabela `disparo_skip`.

    cd backend && venv/bin/python migrate_disparo_skip.py

É idempotente (CREATE TABLE IF NOT EXISTS, índices por nome). Pode rodar de novo.

O QUE ESTA MIGRAÇÃO DESTRAVA
-------------------------------------------------------------------------------------------
A métrica 6 do painel ("humano/bulk atrapalhando a IA") tem metade NÃO MEDÍVEL, e o recon
mediu por quê: `bulk_send_template` devolve `skipped_total`, `skipped_por_regra` e `skipped`
apenas no corpo da resposta HTTP (`exact_routes.py:589-591`). O único ponto que persistia
era `main.py:240`, no caminho AGENDADO — e o agendado não é usado:

    scheduled_messages:  4 linhas no total, todas de junho/2026,  0 desde agosto

100% dos disparos recentes saíram pela porta HTTP. O `skipped_por_regra` do S6-2 existia só
na tela de quem apertou o botão. Consequências: (a) nenhum relatório pode falar de quem foi
pulado; (b) não há como PROVAR que o filtro de recusa está funcionando, só que ele rodou.

UM PONTO DE ESCRITA, DOIS CAMINHOS. `main.py` chama `bulk_send_template` como função
Python. Imediato e agendado atravessam o mesmo laço; `origem_envio` os separa.

POR QUE NÃO COPIEI O RITUAL DO `migrate_message_autoria`
-------------------------------------------------------------------------------------------
Lá havia `lock_timeout`, FK `NOT VALID` + `VALIDATE`, e índices `CONCURRENTLY`. Aquilo
protege uma tabela QUENTE de 32 mil linhas, escrita pelo webhook, de um ACCESS EXCLUSIVE
atrás do sync. Aqui a tabela NÃO EXISTE: não há lock a disputar, não há linha a varrer, não
há escritor a bloquear. A FK para `users(id)` valida instantaneamente sobre zero linhas.
Repetir a cerimônia seria imitação, não cuidado.

SEM BACKFILL. O dado nunca existiu em lugar nenhum — nem na resposta HTTP, que morreu com a
aba. A primeira linha é o primeiro pulo depois do deploy.

Nesta sprint a tabela só ACUMULA. O card que a consome entra quando houver dias suficientes.

NÃO altera comportamento nenhum por si só. NÃO envia mensagem, NÃO toca nat_config nem
auto_welcome_config.
"""
import asyncio

from sqlalchemy import text

from app.database import engine

DDL = """
CREATE TABLE IF NOT EXISTS disparo_skip (
    id            BIGSERIAL    PRIMARY KEY,
    quando        TIMESTAMP    NOT NULL,
    telefone      VARCHAR(20)  NOT NULL,
    chave         VARCHAR(10)  NOT NULL,
    lead_id       INTEGER,
    nome          VARCHAR(255),
    template_name VARCHAR(512) NOT NULL,
    regra         VARCHAR(40)  NOT NULL,
    motivo        TEXT,
    etapa         VARCHAR(30),
    origem_envio  VARCHAR(20)  NOT NULL,
    sent_by       INTEGER      REFERENCES users(id)
)
"""

INDICES = {
    # A consulta do painel é sempre por janela; `regra` é a quebra que a métrica 6 mostra.
    "idx_disparo_skip_quando": "CREATE INDEX idx_disparo_skip_quando ON disparo_skip (quando)",
    "idx_disparo_skip_regra": "CREATE INDEX idx_disparo_skip_regra ON disparo_skip (regra, quando)",
}


async def migrar():
    async with engine.begin() as conn:
        ja_existia = (await conn.execute(text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'disparo_skip'"))).scalar()
        print(f"BEFORE — disparo_skip existe: {bool(ja_existia)}")

        await conn.execute(text(DDL))
        print("  CREATE TABLE IF NOT EXISTS disparo_skip")

        existentes = set((await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='disparo_skip'"))).scalars().all())
        for nome, ddl in INDICES.items():
            if nome in existentes:
                print(f"  {nome} já existe — nada a fazer")
                continue
            await conn.execute(text(ddl))
            print(f"  {ddl}")

        print("\nAFTER — disparo_skip:")
        for nome, tipo, nulo in (await conn.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name='disparo_skip' ORDER BY ordinal_position"""))).all():
            print(f"  coluna {nome:<14} {tipo:<28} nullable={nulo}")

        for (nome,) in (await conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename='disparo_skip' "
                "ORDER BY indexname"))).all():
            print(f"  índice {nome}")

        fks = (await conn.execute(text(
            "SELECT conname, convalidated FROM pg_constraint "
            "WHERE conrelid = 'disparo_skip'::regclass AND contype = 'f'"))).all()
        for nome, valido in fks:
            print(f"  FK {nome} convalidated={valido}")

        linhas = (await conn.execute(text("SELECT count(*) FROM disparo_skip"))).scalar()
        print(f"\nOK: {linhas} linha(s) — 0 é o esperado (sem backfill; o dado nunca existiu).")
        print("Nenhum comportamento alterado por esta migração.")


if __name__ == "__main__":
    asyncio.run(migrar())
