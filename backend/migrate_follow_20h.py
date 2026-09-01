"""S6-4 (Sprint D) — os dois campos do follow do agente, DESLIGADOS.

    cd backend && venv/bin/python migrate_follow_20h.py

Idempotente (ADD COLUMN IF NOT EXISTS). Roda de novo sem efeito.

  follow_enabled   BOOLEAN NOT NULL DEFAULT false  -> o terceiro eixo, e nasce desligado
  follow_template  VARCHAR(512) NULL               -> nome do template na Meta, HOJE NULO

POR QUE OS DOIS, E NÃO SÓ O BOOLEANO
------------------------------------------------------------------------------------------
O texto do follow ainda não existe: está para ser submetido à Meta. Sem `follow_template`, a
alternativa seria escolher um nome no código e torcer — e o candidato óbvio, o
`nat_recuperacao_sdr`, NÃO SERVE: o corpo dele diz "Tentamos falar com você há alguns
minutos", que é falso 20 horas depois. Além disso `nat_copy.py:80` registra que existem DOIS
`nat_recuperacao_sdr` aprovados no WABA, com corpos diferentes (`en` e `pt_BR`).

Com o nome em coluna, aprovar o template é um UPDATE e não um deploy. E enquanto for NULL o
handler recusa com `skipped` e motivo legível, em vez de mandar coisa errada.

`follow_enabled` é o TERCEIRO eixo do nat_config, ao lado de nat_enabled e
qualificacao_enabled, e é independente dos dois pelo mesmo motivo que eles são independentes
entre si: ligar o agente não pode ligar o follow junto. Um lead que hoje fica em silêncio
não recebe nada; passar a receber é decisão de produto, não efeito colateral de um deploy.

NÃO altera comportamento nenhum: as colunas nascem desligada/nula, o handler novo consulta
as duas e recusa nas duas condições. NÃO envia mensagem.
"""
import asyncio

from sqlalchemy import text

from app.database import engine

COLUNAS = (
    ("follow_enabled", "BOOLEAN NOT NULL DEFAULT false"),
    ("follow_template", "VARCHAR(512)"),
)


async def migrar():
    async with engine.begin() as conn:
        await conn.execute(text("SET lock_timeout = '3s'"))
        for nome, tipo in COLUNAS:
            await conn.execute(text(
                f"ALTER TABLE nat_config ADD COLUMN IF NOT EXISTS {nome} {tipo}"))
            print(f"  ADD COLUMN IF NOT EXISTS {nome} {tipo}")

        linhas = (await conn.execute(text(
            "SELECT id, follow_enabled, follow_template FROM nat_config ORDER BY id"))).all()

    print("\nAFTER — nat_config:")
    for id_, enabled, tpl in linhas:
        print(f"  id={id_} follow_enabled={enabled} follow_template={tpl!r}")
    print("\nOK: o follow nasce DESLIGADO e SEM template. O handler recusa nas duas "
          "condições, com motivo gravado.")


if __name__ == "__main__":
    asyncio.run(migrar())
