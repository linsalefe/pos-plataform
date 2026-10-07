"""Trava do 131026 (07/10, liberação geral): o número não recebe WhatsApp.

Chamada pelo webhook de status (`main.py`) e pela reaplicação de status órfão, as duas portas
por onde um `failed` chega. Age só sobre a PRIMEIRA mensagem de cada régua:

    nat_a_confirmacao  -> `confirmacao.encerrar_por_telefone_invalido` (régua da reunião)
    nat_b_abertura     -> `qualificacao_fluxo.encerrar_por_telefone_invalido` (estado do lead)

Só o 131026. O 130472 ("experiment") e qualquer outro erro seguem o fluxo normal. Nunca
levanta para fora: quem chama já está num savepoint, e o status das outras mensagens do lote
não pode depender disto.
"""
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (EXACT_TYPE_VIGENTE, KIND_CONFIRM_A_IMEDIATA, Message, NatScheduledAction,
                        ReuniaoStatus)
from app.telefone import chave_telefone

ETAPA_CONFIRMACAO = "nat_a_confirmacao"
ETAPA_ABERTURA_B = "nat_b_abertura"


async def _reuniao_da_mensagem(msg: Message, db: AsyncSession) -> ReuniaoStatus | None:
    """A reunião cuja confirmação imediata gerou esta mensagem: pelo `wa_message_id` gravado no
    payload da ação; sem ele, a reunião Vigente mais recente do telefone."""
    mid = (await db.execute(
        select(NatScheduledAction.payload)
        .where(NatScheduledAction.kind == KIND_CONFIRM_A_IMEDIATA,
               text("(nat_scheduled_actions.payload::json->>'wa_message_id') = :w")
               .bindparams(w=msg.wa_message_id))
        .limit(1))).scalar_one_or_none()
    if mid:
        import json
        meeting_id = (json.loads(mid) or {}).get("meeting_id")
        if meeting_id:
            r = (await db.execute(select(ReuniaoStatus).where(
                ReuniaoStatus.meeting_id == int(meeting_id)))).scalar_one_or_none()
            if r is not None:
                return r
    chave = chave_telefone(msg.contact_wa_id)
    if not chave:
        return None
    return (await db.execute(
        select(ReuniaoStatus)
        .where(ReuniaoStatus.telefone_chave == chave,
               ReuniaoStatus.exact_type == EXACT_TYPE_VIGENTE)
        .order_by(ReuniaoStatus.registrado_em.desc().nullslast()).limit(1))).scalar_one_or_none()


async def ao_status_falho(wa_message_id: str, erro: dict | None, db: AsyncSession) -> bool:
    """True se encerrou alguma régua/conversa por 131026."""
    from app.confirmacao import CODIGO_TELEFONE_INVALIDO
    if not erro or erro.get("error_code") != CODIGO_TELEFONE_INVALIDO:
        return False
    msg = (await db.execute(select(Message).where(
        Message.wa_message_id == wa_message_id))).scalar_one_or_none()
    if msg is None:
        return False
    if msg.nat_etapa == ETAPA_CONFIRMACAO:
        from app import confirmacao
        r = await _reuniao_da_mensagem(msg, db)
        if r is None:
            print(f"⚠️ 131026 em {wa_message_id} ({msg.contact_wa_id}): reunião não encontrada")
            return False
        return await confirmacao.encerrar_por_telefone_invalido(r, msg.contact_wa_id, db) > 0 \
            or r.regua_encerrada_motivo == confirmacao.MOTIVO_TELEFONE_INVALIDO
    if msg.nat_etapa == ETAPA_ABERTURA_B:
        from app import qualificacao_fluxo
        return await qualificacao_fluxo.encerrar_por_telefone_invalido(msg.contact_wa_id, db)
    return False
