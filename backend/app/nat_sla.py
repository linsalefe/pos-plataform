"""SLA da ligação e escalonamento — Bloco 5, segunda metade.

Este módulo responde a UMA pergunta, 2 minutos depois da transferência: alguém assumiu?
Se não, sobe um degrau. É o handler do `kind` sla_check do agendador (Bloco 7).

------------------------------------------------------------------------------------------
A ESCADA
------------------------------------------------------------------------------------------
Só existem três degraus, e o terceiro é o fim:

  nível 0  o SDR dono foi avisado na transferência e não assumiu
           -> avisa O OUTRO SDR (4 ↔ 5), vira nível 1, REAGENDA +2min
  nível 1  os dois SDRs foram avisados e ninguém assumiu
           -> avisa A GESTÃO (id 2), vira nível 2, NÃO reagenda
  nível 2  fim de linha. Nada a fazer.

Não reagendar no nível 2 é o que impede escalonamento infinito: sem novo sla_check, nenhum
ciclo futuro volta a este lead. O nível 2 no banco existe para o caso de uma ação atrasada
chegar depois — ela encontra o nível 2 e não faz nada.

Só há 2 SDRs, então "o outro" é subtração, não round-robin. Se o dono não for um dos dois
(lead que caiu no fallback da gestão por estar sem SDR), não existe "o outro": o nível 0 PULA
direto para a gestão e marca nível 2. Avisar de novo quem já foi avisado na transferência é
correto — a mensagem agora é "ninguém assumiu", que é informação nova.

------------------------------------------------------------------------------------------
O QUE PARA O RELÓGIO
------------------------------------------------------------------------------------------
`assumido_por` preenchido. Só isso. NÃO é a leitura da notificação — o sino pode ser limpo
sem intenção, e "vi o alerta" não é "vou ligar". Quem preenche é o botão "Assumir ligação"
(POST /api/nat/{wa_id}/assumir), que também cancela o sla_check pendente. O cancelamento é o
caminho normal; esta verificação aqui é a rede para a corrida em que o SDR clica no mesmo
instante em que o job pega a ação.

O estado é RELIDO a cada execução, nunca vem do payload: entre agendar e executar passam
minutos, e nesse intervalo o dono pode mudar, o lead pode responder de novo e sair de
aguardando_ligacao, ou alguém pode assumir. O payload guarda só o que é histórico.

------------------------------------------------------------------------------------------
ATOMICIDADE, E UMA INTERAÇÃO SUTIL COM O ÍNDICE ÚNICO
------------------------------------------------------------------------------------------
O handler roda dentro do SAVEPOINT de _executar_acao, na mesma transação que marca a ação
como `executado`. Notificação + nível novo + reagendamento entram no commit juntos, ou nenhum
entra.

A sutileza: quando este handler chama `agendar()`, a ação que está sendo executada AINDA está
`pendente` (o `executado` só é gravado depois do handler). Inserir um segundo sla_check
`pendente` para o mesmo contato violaria o índice único parcial. Não viola porque `agendar()`
cancela o pendente do mesmo (kind, contato) antes de inserir — ele cancela a própria ação em
curso, e logo depois `_finalizar` a sobrescreve para `executado`. O resultado final é o certo
(ação atual `executado`, nova `pendente`), mas o cancelamento dentro do `agendar()` não é
conveniência aqui: é o que torna o reagendamento possível.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (ETAPA_AGUARDANDO_LIGACAO, KIND_SLA_CHECK, NatFlowState, Notification,
                        User)
from app.nat_flow import (SLA_LIGACAO_MINUTOS, telefone_legivel, usuario_existe,
                          _dados_do_lead)
from app.nat_guard import GESTOR_USER_ID, SDR_IDS_PERMITIDOS
from app.nat_scheduler import agendar, registrar_handler

# Tipos distintos por degrau, como window_alerts_job faz com 1h/3h/5h/20h: o tipo é o que
# permite consultar "quantos leads chegaram à gestão" sem parsear o título.
TIPO_NOTIF_SLA_SDR = "nat_sla_sdr"
TIPO_NOTIF_SLA_GESTAO = "nat_sla_gestao"

NIVEL_SDR_DONO = 0
NIVEL_OUTRO_SDR = 1
NIVEL_GESTAO = 2


def outro_sdr(dono: int | None) -> int | None:
    """O SDR que NÃO é o dono. None se o dono não é um dos SDRs conhecidos.

    Subtração de conjunto e não round-robin: são exatamente dois (Valéria 4, Thobias 5), e uma
    fila circular para dois elementos seria estado a mais para guardar sem nada em troca.
    """
    if dono not in SDR_IDS_PERMITIDOS:
        return None
    restantes = SDR_IDS_PERMITIDOS - {dono}
    return next(iter(restantes)) if len(restantes) == 1 else None


async def _nome_do_usuario(user_id: int | None, db: AsyncSession) -> str:
    if user_id is None:
        return "sem SDR"
    res = await db.execute(select(User.name).where(User.id == user_id))
    row = res.first()
    return (row[0] if row else None) or f"usuário {user_id}"


def montar_notificacao_escalonamento(nivel_destino: int, nome: str, wa_id: str, curso: str,
                                     dono: str, esperando_desde) -> tuple[str, str]:
    """(title, body) de uma notificação de escalonamento.

    O TÍTULO TEM QUE DIZER QUE É ESCALONAMENTO, não lead novo. Quem recebe no nível 1 é um SDR
    que não é o dono do lead: se o título parecesse uma transferência normal, ele assumiria
    achando que o lead é dele, e o dono de verdade nunca saberia que perdeu o SLA.

    Mesmas restrições de formato do Bloco 5 (NotificationBell.tsx): o `title` aparece inteiro
    e o `body` é truncado em ~50 caracteres numa linha só. Por isso o telefone vai nos dois.
    """
    fone = telefone_legivel(wa_id)
    quem = nome or "Lead sem nome"
    desde = f"{esperando_desde:%H:%M}" if esperando_desde else "?"

    if nivel_destino == NIVEL_GESTAO:
        title = f"SLA 2º nível — ninguém assumiu: {quem} — {fone}"
        partes = [fone, f"aguardando desde {desde}",
                  f"{dono} e o outro SDR foram avisados e não assumiram"]
    else:
        title = f"SLA estourado — assuma: {quem} — {fone}"
        partes = [fone, f"aguardando desde {desde}", f"{dono} não assumiu em "
                  f"{SLA_LIGACAO_MINUTOS} min"]

    if curso:
        partes.insert(1, curso)

    return title[:255], " · ".join(partes)


async def _notificar(db: AsyncSession, *, user_id: int, wa_id: str, tipo: str, acao_id: int,
                     title: str, body: str) -> bool:
    """Cria a notificação. False (sem levantar) se o destinatário não existe.

    Não levantar é decisão: um destinatário inexistente é problema de cadastro, e fazer o
    handler falhar transformaria isso em 3 retentativas e uma ação `falhou` — ruído que não
    conserta o cadastro. O nível sobe de todo modo, para o ciclo não ficar preso tentando
    avisar alguém que não existe.
    """
    if not await usuario_existe(user_id, db):
        print(f"⚠️  NAT SLA: destinatário id={user_id} não existe — {wa_id} não escalonado "
              f"para ele (o nível sobe igual, para não travar o ciclo)")
        return False
    db.add(Notification(
        user_id=user_id,
        contact_wa_id=wa_id,
        type=tipo,
        # ref pela AÇÃO, não pelo contato: cada sla_check é um evento distinto, e dois
        # escalonamentos do mesmo lead em ciclos diferentes devem aparecer como dois avisos.
        ref=f"{KIND_SLA_CHECK}:{acao_id}",
        title=title,
        body=body,
    ))
    return True


@registrar_handler(KIND_SLA_CHECK)
async def sla_check(acao: dict, db: AsyncSession) -> None:
    """Handler do sla_check. Roda dentro do savepoint de _executar_acao.

    Todo caminho de saída é silencioso e bem-sucedido (a ação vira `executado`): "não havia
    nada a fazer" é um desfecho legítimo do SLA, não uma falha. O handler só levanta se algo
    de verdade der errado — e aí o agendador retenta.
    """
    wa_id = acao["contact_wa_id"]
    agora = acao["agora"]
    acao_id = acao["id"]

    res = await db.execute(
        select(NatFlowState).where(NatFlowState.contact_wa_id == wa_id))
    state = res.scalar_one_or_none()

    # --- as três saídas de "nada a fazer" ---
    if state is None:
        print(f"↩️  NAT SLA: {wa_id} sem estado de fluxo — nada a fazer")
        return

    if state.etapa != ETAPA_AGUARDANDO_LIGACAO:
        print(f"↩️  NAT SLA: {wa_id} já saiu de {ETAPA_AGUARDANDO_LIGACAO} "
              f"(está em {state.etapa}) — nada a fazer")
        return

    if state.assumido_por is not None:
        print(f"✅ NAT SLA: {wa_id} já assumido por user {state.assumido_por} em "
              f"{state.assumido_em:%H:%M:%S} — relógio parado, nada a fazer")
        return

    nivel = state.escalonamento_nivel or 0
    if nivel >= NIVEL_GESTAO:
        print(f"↩️  NAT SLA: {wa_id} já está no nível {nivel} (gestão avisada) — "
              "fim da escada, nada a fazer")
        return

    dados = await _dados_do_lead(state, db)
    dono = await _nome_do_usuario(state.sdr_user_id, db)

    # --- nível 0 -> avisa o OUTRO SDR e reagenda ---
    if nivel == NIVEL_SDR_DONO:
        alvo = outro_sdr(state.sdr_user_id)

        if alvo is None:
            # Lead sem SDR conhecido: não existe "o outro". Pula para a gestão e encerra —
            # reagendar aqui só gastaria um ciclo para chegar ao mesmo lugar.
            print(f"↪️  NAT SLA: {wa_id} sem SDR dono conhecido "
                  f"(sdr_user_id={state.sdr_user_id}) — pulando direto para a gestão")
            title, body = montar_notificacao_escalonamento(
                NIVEL_GESTAO, dados["nome"], wa_id, dados["curso"], dono,
                state.transferido_em)
            await _notificar(db, user_id=GESTOR_USER_ID, wa_id=wa_id,
                             tipo=TIPO_NOTIF_SLA_GESTAO, acao_id=acao_id,
                             title=title, body=body)
            state.escalonamento_nivel = NIVEL_GESTAO
            print(f"🔺 NAT SLA: {wa_id} nível 0 → {NIVEL_GESTAO} (gestão) — não reagenda")
            return

        title, body = montar_notificacao_escalonamento(
            NIVEL_OUTRO_SDR, dados["nome"], wa_id, dados["curso"], dono,
            state.transferido_em)
        await _notificar(db, user_id=alvo, wa_id=wa_id, tipo=TIPO_NOTIF_SLA_SDR,
                         acao_id=acao_id, title=title, body=body)
        state.escalonamento_nivel = NIVEL_OUTRO_SDR

        # Reagenda ANTES de retornar, na mesma transação. Ver a nota sobre o índice único na
        # docstring do módulo: o agendar() cancela esta própria ação em curso, e o
        # _finalizar do agendador a sobrescreve para `executado` em seguida.
        await agendar(KIND_SLA_CHECK, wa_id,
                      agora + timedelta(minutes=SLA_LIGACAO_MINUTOS),
                      {"nivel_anterior": NIVEL_SDR_DONO, "notificado": alvo}, db)
        print(f"🔺 NAT SLA: {wa_id} nível 0 → {NIVEL_OUTRO_SDR} (SDR {alvo}) — "
              f"reagendado +{SLA_LIGACAO_MINUTOS}min")
        return

    # --- nível 1 -> avisa a GESTÃO e ENCERRA ---
    title, body = montar_notificacao_escalonamento(
        NIVEL_GESTAO, dados["nome"], wa_id, dados["curso"], dono, state.transferido_em)
    await _notificar(db, user_id=GESTOR_USER_ID, wa_id=wa_id, tipo=TIPO_NOTIF_SLA_GESTAO,
                     acao_id=acao_id, title=title, body=body)
    state.escalonamento_nivel = NIVEL_GESTAO
    print(f"🔺 NAT SLA: {wa_id} nível {NIVEL_OUTRO_SDR} → {NIVEL_GESTAO} (gestão id="
          f"{GESTOR_USER_ID}) — fim da escada, NÃO reagenda")
