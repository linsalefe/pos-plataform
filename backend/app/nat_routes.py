"""Endpoints do fluxo NAT usados pela tela de conversas — Bloco 5, Fase 7.

Duas rotas, as duas autenticadas:

  GET  /api/nat/{wa_id}/estado    o que a tela precisa para decidir o que mostrar
  POST /api/nat/{wa_id}/assumir   o botão "Assumir ligação"

`assumido_por` é O QUE PARA O RELÓGIO do SLA. É um clique explícito, e não a leitura da
notificação: o sino pode ser limpo sem intenção, e "vi o alerta" não é "vou ligar".
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import ETAPA_AGUARDANDO_LIGACAO, KIND_SLA_CHECK, NatFlowState, User
from app.nat_guard import _agora_sp

router = APIRouter(prefix="/api/nat", tags=["nat"])


async def _estado(wa_id: str, db: AsyncSession) -> NatFlowState | None:
    res = await db.execute(select(NatFlowState).where(NatFlowState.contact_wa_id == wa_id))
    return res.scalar_one_or_none()


async def _nome(user_id: int | None, db: AsyncSession) -> str | None:
    if user_id is None:
        return None
    res = await db.execute(select(User.name).where(User.id == user_id))
    row = res.first()
    return (row[0] if row else None) or f"usuário {user_id}"


async def _payload(state: NatFlowState, db: AsyncSession) -> dict:
    """A resposta que a tela consome.

    `pode_assumir` é calculado AQUI, não no TSX. A regra é "está em aguardando_ligacao e
    ninguém assumiu" — a mesma que o handler do sla_check aplica. Duplicá-la no frontend
    criaria dois lugares para ela divergir, e o frontend perderia primeiro.
    """
    return {
        "em_fluxo": True,
        "etapa": state.etapa,
        "transferido_em": state.transferido_em.isoformat() if state.transferido_em else None,
        "assumido_por": state.assumido_por,
        "assumido_por_nome": await _nome(state.assumido_por, db),
        "assumido_em": state.assumido_em.isoformat() if state.assumido_em else None,
        "escalonamento_nivel": state.escalonamento_nivel or 0,
        "pode_assumir": (state.etapa == ETAPA_AGUARDANDO_LIGACAO
                         and state.assumido_por is None),
    }


VAZIO = {
    "em_fluxo": False, "etapa": None, "transferido_em": None, "assumido_por": None,
    "assumido_por_nome": None, "assumido_em": None, "escalonamento_nivel": 0,
    "pode_assumir": False,
}


@router.get("/{wa_id}/estado")
async def estado_do_fluxo(wa_id: str, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    """Estado do fluxo NAT do contato. Contato fora do fluxo devolve em_fluxo=false, não 404.

    Não é 404 porque a tela pergunta isto para TODO contato que o atendente abre, e a
    esmagadora maioria não está no fluxo da NAT. 404 nesse caso encheria o console do
    navegador de erro para o comportamento mais normal que existe.
    """
    state = await _estado(wa_id, db)
    if state is None:
        return VAZIO
    return await _payload(state, db)


@router.post("/{wa_id}/assumir")
async def assumir_ligacao(wa_id: str, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    """Para o relógio do SLA: grava quem assumiu e cancela o sla_check pendente.

    IDEMPOTENTE. Assumir duas vezes não é erro e não reabre nada: a segunda chamada devolve
    200 com quem já havia assumido e NÃO sobrescreve assumido_por/assumido_em. Sobrescrever
    seria pior que um erro — apagaria o registro de quem realmente pegou o lead primeiro, que
    é justamente o que a escada de escalonamento usa para saber quem responde por ele.

    Dois savepoints, na ordem da importância — mesmo raciocínio do Bloco 5:
      1. o carimbo, que é o que para o relógio;
      2. o cancelamento do sla_check.
    Se o cancelamento falhar, o carimbo permanece e o SLA ainda não escalona: o handler relê
    o estado e encontra `assumido_por` preenchido. O cancelamento é a via limpa; a
    verificação no handler é a rede.
    """
    state = await _estado(wa_id, db)
    if state is None:
        raise HTTPException(404, "Este contato não está no fluxo da NAT.")

    if state.assumido_por is not None:
        # Idempotência. Inclui o caso de dois SDRs clicando quase juntos: o segundo vê quem
        # ficou com o lead em vez de tomá-lo.
        return {"ja_assumido": True, "cancelados": 0, **await _payload(state, db)}

    if state.etapa != ETAPA_AGUARDANDO_LIGACAO:
        raise HTTPException(
            409,
            f"O lead não está aguardando ligação (etapa atual: {state.etapa}). "
            "Não há SLA correndo para assumir.")

    async with db.begin_nested():
        state.assumido_por = current_user.id
        state.assumido_em = _agora_sp()

    cancelados = 0
    try:
        async with db.begin_nested():
            from app.nat_scheduler import cancelar
            cancelados = await cancelar(KIND_SLA_CHECK, wa_id, db)
    except Exception as e:
        print(f"⚠️  NAT: {wa_id} assumido por {current_user.id}, mas o cancelamento do "
              f"sla_check falhou ({type(e).__name__}: {e}). O SLA não escalona: o handler "
              "relê o estado e vê assumido_por preenchido.")

    await db.commit()
    print(f"✋ NAT: {wa_id} assumido por {current_user.name} (id={current_user.id}) — "
          f"{cancelados} sla_check cancelado(s)")

    await db.refresh(state)
    return {"ja_assumido": False, "cancelados": cancelados, **await _payload(state, db)}
