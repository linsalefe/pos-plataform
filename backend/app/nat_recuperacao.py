"""Recuperação do lead sem contato — Bloco 6.

O SDR ligou, ninguém atendeu. Ele marca "Não consegui contato" na tela de conversas
(POST /api/nat/{wa_id}/sem-contato) e este módulo cuida do que vem depois:

  * o LEAD recebe UMA mensagem (nat_recuperacao_sdr, com dois botões) — quem manda é o
    endpoint, no instante do clique;
  * 10 minutos depois, se nada aconteceu, o SDR é COBRADO DE NOVO — é o handler daqui.

------------------------------------------------------------------------------------------
O RETRY COBRA O SDR, NUNCA O LEAD
------------------------------------------------------------------------------------------
Esta é a decisão que define o módulo. O retry de 10 min NÃO manda segunda mensagem ao lead:
ele cria uma notificação para quem tem que ligar. Um lead que não atendeu o telefone e não
respondeu ao WhatsApp não precisa de uma segunda mensagem 10 minutos depois — precisa de uma
segunda ligação. E o caminho oposto (retry que envia) é o que transforma um agendador em
disparador: bastaria um erro de guarda para o lead receber a mesma mensagem em ciclo.

Por isso o handler tem exatamente um efeito colateral, uma notificação, e NÃO REAGENDA nada.
Sem reagendamento não existe ciclo: cada "sem contato" gera no máximo um retry, e o retry
termina em si mesmo.

------------------------------------------------------------------------------------------
O TETO DE 2, E POR QUE ELE NÃO MORA AQUI
------------------------------------------------------------------------------------------
São no máximo 2 tentativas por lead. Quem conta é nat_flow_state.tentativas_contato e quem
aplica o teto é o ENDPOINT, antes de qualquer envio — o histórico em nat_contact_attempts é
auditoria, não controle de fluxo. Ao atingir a 2ª tentativa o lead vai para `encerrado` e
nenhum retry é agendado: o fluxo da NAT acabou para ele, e o que sobra é trabalho humano.

------------------------------------------------------------------------------------------
AS TRÊS SAÍDAS DE "NADA A FAZER"
------------------------------------------------------------------------------------------
Mesmo espírito do nat_sla: todo caminho de saída é silencioso e bem-sucedido (a ação vira
`executado`). O estado é RELIDO, nunca vem do payload — entre agendar e executar passam 10
minutos, e nesse intervalo o lead pode ter clicado, o SDR pode ter assumido, o dono pode ter
mudado.

  sem estado          o fluxo sumiu (não deveria acontecer) — nada a fazer
  etapa != sem_contato o lead JÁ reagiu (clicou em "Tentar agora", pediu outro horário, ou o
                      SDR encerrou) — cobrar de novo seria ruído sobre algo resolvido
  assumido_por        alguém pegou o lead — a cobrança perdeu o objeto
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (ETAPA_SEM_CONTATO, KIND_RETRY_CONTATO, NatFlowState, Notification)
from app.nat_flow import (_dados_do_lead, _destinatario_do_aviso, telefone_legivel,
                          usuario_existe)
from app.nat_guard import GESTOR_USER_ID
from app.nat_scheduler import registrar_handler

# Teto de tentativas de contato por lead. Na segunda o fluxo ENCERRA: nem envio novo, nem
# retry agendado. Dois é o número que o time definiu — mais que isso, com o lead calado nas
# duas, deixa de ser recuperação e vira insistência.
MAX_TENTATIVAS_CONTATO = 2

# Quanto tempo depois do "não consegui contato" o SDR é cobrado de novo.
RETRY_CONTATO_MINUTOS = 10

# Janela de idempotência do endpoint. Dois cliques no mesmo botão dentro deste intervalo são
# o MESMO ato: o segundo devolve o estado atual sem gravar tentativa e sem enviar nada.
# Medida por CONTATO e não por usuário: dois SDRs (ou duas abas) clicando juntos mandariam
# duas mensagens ao lead e queimariam as duas tentativas de uma vez.
JANELA_IDEMPOTENCIA_SEGUNDOS = 30

# O que fica gravado em nat_contact_attempts.resultado. Coluna sem CHECK (ver o modelo): hoje
# só existe este valor, e Sprint B/C podem acrescentar outros desfechos.
RESULTADO_SEM_CONTATO = "sem_contato"

# Tipos distintos por evento, como o nat_sla faz com os degraus: é o tipo que permite
# perguntar ao banco "quantos leads voltaram para a fila de ligação" sem parsear título.
TIPO_NOTIF_RETRY = "nat_retry_contato"
TIPO_NOTIF_TENTAR_AGORA = "nat_tentar_agora"


def montar_notificacao_retry(nome: str, wa_id: str, curso: str, tentativa: int) -> tuple:
    """(title, body) da cobrança de 10 minutos.

    O TÍTULO TEM QUE DIZER QUE É COBRANÇA, não lead novo: quem recebe já sabe deste lead — foi
    ele mesmo que marcou "não consegui contato" — e o que a notificação acrescenta é que o
    tempo passou e nada mudou.

    O corpo NÃO afirma que o lead ignorou a mensagem. Com a NAT desligada, ou com o guard
    bloqueando o envio, o lead pode nunca ter recebido nada — e um aviso que afirma o que não
    sabe ensina o SDR a desconfiar do sino. Diz o que é certo: ninguém respondeu e ninguém
    assumiu.

    Formato ditado pelo NotificationBell.tsx: `title` aparece inteiro, `body` é limitado a
    duas linhas. O telefone vai nos dois — no título é garantido, no corpo é o que sobra.
    """
    fone = telefone_legivel(wa_id)
    quem = nome or "Lead sem nome"
    title = f"Sem retorno há {RETRY_CONTATO_MINUTOS} min — tente ligar de novo: {quem} — {fone}"
    partes = [fone, f"tentativa {tentativa} de {MAX_TENTATIVAS_CONTATO}",
              "ninguém respondeu e ninguém assumiu"]
    if curso:
        partes.insert(1, curso)
    return title[:255], " · ".join(partes)


def montar_notificacao_tentar_agora(nome: str, wa_id: str, curso: str) -> tuple:
    """(title, body) do clique em "Tentar novamente agora".

    É o aviso mais URGENTE do Bloco 6: o lead está com o celular na mão, acabou de dizer que
    quer ser chamado AGORA. Por isso o título é imperativo e traz o telefone — o SDR precisa
    conseguir ligar sem abrir a conversa.
    """
    fone = telefone_legivel(wa_id)
    quem = nome or "Lead sem nome"
    title = f"LIGUE AGORA — o lead pediu nova tentativa: {quem} — {fone}"
    partes = [fone, "clicou em 'Tentar novamente agora'"]
    if curso:
        partes.insert(1, curso)
    return title[:255], " · ".join(partes)


async def notificar_sdr(state: NatFlowState, db: AsyncSession, *, tipo: str, ref: str,
                        title: str, body: str) -> bool:
    """Cria a notificação para o dono do lead (gestão como rede). True se saiu.

    Reusa `_destinatario_do_aviso` do nat_flow — a regra de "quem recebe" é a MESMA dos
    avisos de transferência e de reagendamento, e uma segunda cópia dela aqui seria mais um
    lugar para divergir. A existência do usuário é conferida (notifications.user_id tem FK
    para users) antes do INSERT, pelo mesmo motivo de lá.

    Não levanta em caso de destinatário ausente: um lead sem dono é problema de cadastro, e
    fazer o handler falhar transformaria isso em 3 retentativas e uma ação `falhou` — ruído
    que não conserta cadastro nenhum.
    """
    wa_id = state.contact_wa_id
    destinatario, eh_fallback = await _destinatario_do_aviso(state, db)
    if destinatario is None:
        print(f"❌ NAT recuperação: {wa_id} sem destinatário possível "
              f"(sdr_user_id={state.sdr_user_id}, gestor id={GESTOR_USER_ID} não existe) — "
              "ninguém foi avisado")
        return False

    if not await usuario_existe(destinatario, db):
        print(f"⚠️  NAT recuperação: destinatário id={destinatario} não existe — {wa_id} "
              "não notificado")
        return False

    db.add(Notification(
        user_id=destinatario,
        contact_wa_id=wa_id,
        type=tipo,
        ref=ref,
        title=title,
        body=body,
    ))
    print(f"🔔 NAT recuperação: {wa_id} notificado para user {destinatario}"
          f"{' (FALLBACK gestão)' if eh_fallback else ''}: {title}")
    return True


@registrar_handler(KIND_RETRY_CONTATO)
async def retry_contato(acao: dict, db: AsyncSession) -> None:
    """Handler do retry_contato. Roda dentro do savepoint de _executar_acao.

    Recebe `dict` e não o objeto ORM (ver nat_scheduler.registrar_handler): o savepoint pode
    ser revertido, e reverter savepoint expira o ORM — um acesso a atributo depois disso
    estouraria MissingGreenlet em contexto async.

    NÃO ENVIA NADA AO LEAD e NÃO REAGENDA. É o que impede o ciclo: cada "sem contato" gera no
    máximo um retry, e ele termina aqui.
    """
    wa_id = acao["contact_wa_id"]
    acao_id = acao["id"]

    res = await db.execute(
        select(NatFlowState).where(NatFlowState.contact_wa_id == wa_id))
    state = res.scalar_one_or_none()

    # --- as três saídas de "nada a fazer" ---
    if state is None:
        print(f"↩️  NAT recuperação: {wa_id} sem estado de fluxo — nada a fazer")
        return

    if state.etapa != ETAPA_SEM_CONTATO:
        print(f"↩️  NAT recuperação: {wa_id} já saiu de {ETAPA_SEM_CONTATO} "
              f"(está em {state.etapa}) — o lead reagiu, nada a fazer")
        return

    if state.assumido_por is not None:
        print(f"✅ NAT recuperação: {wa_id} já assumido por user {state.assumido_por} — "
              "cobrança sem objeto, nada a fazer")
        return

    dados = await _dados_do_lead(state, db)
    title, body = montar_notificacao_retry(
        dados["nome"], wa_id, dados["curso"], state.tentativas_contato or 1)

    # ref pela AÇÃO, não pelo contato: cada retry é um evento distinto, e a 1ª e a 2ª
    # tentativa do mesmo lead devem aparecer como dois avisos. Mesma escolha do nat_sla.
    await notificar_sdr(state, db, tipo=TIPO_NOTIF_RETRY,
                        ref=f"{KIND_RETRY_CONTATO}:{acao_id}", title=title, body=body)
