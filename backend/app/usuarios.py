"""Quem é SDR, quem é consultora: `users.papel` (24/10/2026).

`papel` é OPERAÇÃO (`sdr`, `consultora`, `gestao`, `outro`); `role` continua sendo PERMISSÃO
(`admin`/`atendente`) e não muda. Antes disto, "quem é SDR" morava em dois lugares que
discordavam: `SDR_USER_IDS=5` no .env e `SDR_IDS_PERMITIDOS = {4, 5}` em nat_guard.py.
Agora a fonte é o banco (`migrate_papel_usuarios.py`), e os dois viram reserva.

Decisão do Álefe (24/10): o Thobias (5) é o único SDR; a Victória (6) é a consultora; a conta
3 "Vi Amorim" foi desativada. RECON_4_PEDIDOS_COMERCIAL_20261024 §4.

RESERVA. Se a consulta voltar vazia ou falhar (coluna ainda não migrada, banco piscando), cai
no `SDR_USER_IDS` do .env e, sem ele, em `SDR_PADRAO`, sempre com aviso no log: um aviso que
não chega a SDR nenhum é o silêncio que as réguas existem para evitar.
"""
from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

PAPEL_SDR = "sdr"
PAPEL_CONSULTORA = "consultora"
PAPEL_GESTAO = "gestao"
PAPEL_OUTRO = "outro"
PAPEIS = (PAPEL_SDR, PAPEL_CONSULTORA, PAPEL_GESTAO, PAPEL_OUTRO)

ENV_SDRS = "SDR_USER_IDS"
# Último degrau da reserva: o Thobias, único SDR em 24/10.
SDR_PADRAO = (5,)


def _ids_do_env() -> list[int]:
    ids: list[int] = []
    for parte in (os.getenv(ENV_SDRS, "") or "").split(","):
        parte = parte.strip()
        if not parte:
            continue
        try:
            uid = int(parte)
        except ValueError:
            print(f"⚠️ usuarios: {ENV_SDRS} tem valor inválido {parte!r}, ignorado")
            continue
        if uid not in ids:
            ids.append(uid)
    return ids


async def ids_do_papel(db: AsyncSession, papel: str) -> list[int]:
    """Usuários ATIVOS com este papel, por id. Falha vira lista vazia (com log)."""
    from app.models import User
    try:
        res = await db.execute(
            select(User.id).where(User.papel == papel, User.is_active.is_(True))
            .order_by(User.id))
        return list(res.scalars().all())
    except Exception as e:
        # Sem rollback aqui: a sessão é de quem chamou, e desfazer o que ele tem pendente
        # (as Notifications que vai gravar, por exemplo) seria pior que a reserva.
        print(f"⚠️ usuarios: não consegui ler papel={papel} ({type(e).__name__}: {e})")
        return []


async def sdr_ids(db: AsyncSession) -> list[int]:
    """Os SDRs ativos. Banco primeiro; .env e `SDR_PADRAO` só como reserva, com aviso."""
    ids = await ids_do_papel(db, PAPEL_SDR)
    if ids:
        return ids
    reserva = _ids_do_env() or list(SDR_PADRAO)
    print(f"⚠️ usuarios: nenhum usuário ativo com papel=sdr; usando a reserva {reserva}")
    return reserva


async def consultora_ids(db: AsyncSession) -> list[int]:
    return await ids_do_papel(db, PAPEL_CONSULTORA)


async def papel_de(user_id: int | None, db: AsyncSession) -> str | None:
    if user_id is None:
        return None
    from app.models import User
    res = await db.execute(select(User.papel).where(User.id == user_id))
    return res.scalar_one_or_none()
