"""Kill switch do agente de pré-qualificação. UMA coluna, nada mais.

    cd backend && venv/bin/python desligar_qualificacao.py            # mostra o estado
    cd backend && venv/bin/python desligar_qualificacao.py --sim-desliga
    cd backend && venv/bin/python desligar_qualificacao.py --religa

`nat_config.qualificacao_enabled = false` e pronto. Não cancela ação pendente, não apaga
estado, não toca em mensagem: **preservar tudo é o ponto**. Quem desliga às pressas quer
parar a hemorragia e depois entender o que houve — apagar o rastro no mesmo gesto tornaria
a investigação impossível.

Existe apesar de `PATCH /api/nat/config` porque a rota exige login de admin e um navegador.
Às 09h07 de um dia ruim, `venv/bin/python desligar_qualificacao.py --sim-desliga` é uma
linha e não depende do frontend estar de pé.

O efeito é IMEDIATO e não precisa de restart: `qualificacao_guard._carregar_config` lê a
linha a cada verificação, e as duas portas (`qualificacao_pode_iniciar` para abrir e
`qualificacao_pode_atuar` para responder) passam por ela. Aberturas pendentes continuam
sendo consumidas pelo agendador, mas caem em "não admitida" e nada sai.

O `--religa` existe para o caminho de volta ser tão curto quanto o de ida.
"""
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text                       # noqa: E402

from app.database import async_session            # noqa: E402


async def main() -> int:
    religa = "--religa" in sys.argv
    desliga = "--sim-desliga" in sys.argv
    async with async_session() as db:
        antes = (await db.execute(text(
            "SELECT qualificacao_enabled, nat_enabled FROM nat_config WHERE id = 1"))).first()
        if antes is None:
            print("🚨 nat_config id=1 não existe. Nada a fazer.")
            return 1
        print(f"agora: qualificacao_enabled={antes[0]}  ·  nat_enabled={antes[1]}")

        if not (religa or desliga):
            print(__doc__.split("\n\n")[0])
            print("\nNada mudou. Use --sim-desliga ou --religa.")
            return 0

        alvo = True if religa else False
        if antes[0] == alvo:
            print(f"já está em {alvo}. Nada mudou.")
            return 0

        await db.execute(text(
            "UPDATE nat_config SET qualificacao_enabled = :v WHERE id = 1"), {"v": alvo})
        await db.commit()
        depois = (await db.execute(text(
            "SELECT qualificacao_enabled FROM nat_config WHERE id = 1"))).scalar()
        print(f"✅ qualificacao_enabled: {antes[0]} → {depois}")
        pend = (await db.execute(text(
            "SELECT COUNT(*) FROM nat_scheduled_actions WHERE kind = 'iniciar_qualificacao' "
            "AND status = 'pendente'"))).scalar()
        est = (await db.execute(text(
            "SELECT COUNT(*) FROM nat_qualificacao_state"))).scalar()
        print(f"   preservados: {pend} ação(ões) pendente(s), {est} estado(s). "
              f"Nada foi cancelado nem apagado.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
