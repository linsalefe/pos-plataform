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

Só há 2 SDRs, então "o outro" é subtração, não round-robin.

CASO ESPECIAL — LEAD SEM SDR. Se o dono não é um dos dois (lead que caiu no fallback da gestão
no Bloco 5 por estar sem `assigned_to`), não existe "o outro SDR" — mas existem OS DOIS, e são
eles que ligam. O nível 0 então avisa AMBOS (4 e 5) e encerra no nível 2.

Encerrar em vez de reagendar para a gestão porque a gestão JÁ foi avisada na transferência: um
terceiro aviso para ela não acrescenta informação, e quem faltava saber eram os SDRs. A versão
anterior deste módulo notificava a gestão de novo e encerrava — a gestora recebia duas
notificações do mesmo lead e os SDRs nunca ficavam sabendo, que é o oposto do que o
escalonamento existe para fazer.

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
from app.nat_scheduler import AcaoIgnorada, agendar, registrar_handler

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
                                     dono: str, esperando_desde,
                                     *, sem_dono: bool = False) -> tuple[str, str]:
    """(title, body) de uma notificação de escalonamento.

    O TÍTULO TEM QUE DIZER QUE É ESCALONAMENTO, não lead novo. Quem recebe no nível 1 é um SDR
    que não é o dono do lead: se o título parecesse uma transferência normal, ele assumiria
    achando que o lead é dele, e o dono de verdade nunca saberia que perdeu o SLA.

    `sem_dono` é o caso do lead que nem chegou a ter SDR: aí não há "o dono não assumiu", há
    "ninguém é dono". A distinção importa porque muda o que o SDR deve fazer — no escalonamento
    normal ele está cobrindo o colega, aqui ele está adotando um lead órfão.

    Formato ditado pelo NotificationBell.tsx: o `title` aparece inteiro (sem `truncate`) e o
    `body` é limitado a DUAS linhas (`line-clamp-2`). Por isso o telefone vai nos dois — no
    título ele é garantido, e no começo do corpo ele é a primeira coisa a sobrar.
    """
    fone = telefone_legivel(wa_id)
    quem = nome or "Lead sem nome"
    desde = f"{esperando_desde:%H:%M}" if esperando_desde else "?"

    if sem_dono:
        title = f"SLA estourado — lead SEM SDR, assuma: {quem} — {fone}"
        partes = [fone, f"aguardando desde {desde}",
                  "ninguém é dono deste lead — assuma se for ligar"]
    elif nivel_destino == NIVEL_GESTAO:
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

    NENHUMA SAÍDA DAQUI É SILENCIOSA (Risco 3, S4-1). "Não havia nada a fazer" continua sendo
    um desfecho legítimo do SLA — mas ele não pode se parecer com "escalonei". As quatro
    saídas de nada-a-fazer viravam `executado` com motivo NULL, iguais às duas que de fato
    notificam alguém; agora são `AcaoIgnorada`, isto é, `skipped` com o motivo GRAVADO na
    linha. Falha de verdade continua levantando exceção, e aí o agendador retenta.
    """
    wa_id = acao["contact_wa_id"]
    agora = acao["agora"]
    acao_id = acao["id"]

    res = await db.execute(
        select(NatFlowState).where(NatFlowState.contact_wa_id == wa_id))
    state = res.scalar_one_or_none()

    # --- as QUATRO saídas de "nada a fazer" — todas AcaoIgnorada, nenhuma muda (S4-1) ---
    if state is None:
        raise AcaoIgnorada("sem estado de fluxo — nada a escalonar")

    if state.etapa != ETAPA_AGUARDANDO_LIGACAO:
        raise AcaoIgnorada(f"já saiu de {ETAPA_AGUARDANDO_LIGACAO} (está em {state.etapa})")

    if state.assumido_por is not None:
        raise AcaoIgnorada(f"já assumido por user {state.assumido_por} em "
                           f"{state.assumido_em:%d/%m %H:%M} — relógio parado")

    nivel = state.escalonamento_nivel or 0
    if nivel >= NIVEL_GESTAO:
        raise AcaoIgnorada(f"já está no nível {nivel} (gestão avisada) — fim da escada")

    dados = await _dados_do_lead(state, db)
    dono = await _nome_do_usuario(state.sdr_user_id, db)

    # --- nível 0 -> avisa o OUTRO SDR e reagenda ---
    if nivel == NIVEL_SDR_DONO:
        alvo = outro_sdr(state.sdr_user_id)

        if alvo is None:
            # LEAD SEM SDR. Não existe "o outro SDR", mas existem OS DOIS — e são eles que
            # ligam. A versão anterior notificava a gestão de novo e encerrava; o efeito
            # prático era o oposto do que o escalonamento existe para fazer: a gestora recebia
            # duas notificações do mesmo lead (a da transferência e esta) e Valéria e Thobias
            # nunca ficavam sabendo que havia um lead esperando ligação.
            #
            # Agora avisa AMBOS e encerra no nível 2. Encerrar (em vez de reagendar para a
            # gestão) porque a gestão JÁ foi avisada na transferência, pelo fallback do Bloco
            # 5: um terceiro aviso para ela não acrescenta informação, e quem faltava saber
            # eram os SDRs.
            print(f"↪️  NAT SLA: {wa_id} sem SDR dono (sdr_user_id={state.sdr_user_id}) — "
                  f"avisando AMBOS os SDRs {sorted(SDR_IDS_PERMITIDOS)}")
            title, body = montar_notificacao_escalonamento(
                NIVEL_OUTRO_SDR, dados["nome"], wa_id, dados["curso"], dono,
                state.transferido_em, sem_dono=True)
            avisados = []
            for sdr in sorted(SDR_IDS_PERMITIDOS):
                if await _notificar(db, user_id=sdr, wa_id=wa_id,
                                    tipo=TIPO_NOTIF_SLA_SDR, acao_id=acao_id,
                                    title=title, body=body):
                    avisados.append(sdr)
            state.escalonamento_nivel = NIVEL_GESTAO
            print(f"🔺 NAT SLA: {wa_id} nível 0 → {NIVEL_GESTAO} — SDRs avisados: "
                  f"{avisados or 'nenhum'}. Fim da escada, NÃO reagenda "
                  "(a gestão já foi avisada na transferência)")
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
