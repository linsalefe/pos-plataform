"""Endpoints do fluxo NAT.

Dois grupos, com públicos diferentes, todos autenticados:

  A TELA DE CONVERSAS (Bloco 5, Fase 7) — qualquer usuário logado:
  GET  /api/nat/{wa_id}/estado       o que a tela precisa para decidir o que mostrar
  POST /api/nat/{wa_id}/assumir      o botão "Assumir ligação"
  POST /api/nat/{wa_id}/sem-contato  o botão "Não consegui contato" (Bloco 6)

  O PAINEL DE CONTROLE (sprint de ativação, Fase 4) — só admin:
  GET   /api/nat/config           lê o kill switch
  PATCH /api/nat/config           liga, desliga e ajusta o teto

`assumido_por` é O QUE PARA O RELÓGIO do SLA. É um clique explícito, e não a leitura da
notificação: o sino pode ser limpo sem intenção, e "vi o alerta" não é "vou ligar".

O mesmo clique é também a ÚNICA SAÍDA do fluxo: leva o lead para `encerrado`. Antes desta
sprint nenhum caminho atribuía essa etapa e o lead morria em `aguardando_ligacao`.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import nat_copy
from app.auth import get_current_admin, get_current_user
from app.database import get_db
from app.models import (ETAPA_AGUARDANDO_LIGACAO, ETAPA_ENCERRADO, ETAPA_SEM_CONTATO,
                        KIND_RETRY_CONTATO, KIND_SLA_CHECK, NatConfig, NatContactAttempt,
                        NatFlowState, User)
from app.nat_flow import _dados_do_lead
from app.nat_guard import SP_TZ, _agora_sp
from app.nat_recuperacao import (JANELA_IDEMPOTENCIA_SEGUNDOS, MAX_TENTATIVAS_CONTATO,
                                 RESULTADO_SEM_CONTATO, RETRY_CONTATO_MINUTOS)
from app.nat_sender import send_nat_message

# Etapas em que "não consegui contato" faz sentido: o lead está esperando ligação, ou já
# levou uma tentativa sem sucesso. Fora daí o botão não aparece e o endpoint recusa.
ETAPAS_PODE_MARCAR_SEM_CONTATO = frozenset({ETAPA_AGUARDANDO_LIGACAO, ETAPA_SEM_CONTATO})

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

    `pode_marcar_sem_contato` segue a mesma disciplina, e por um motivo mais forte: a regra
    dele tem DUAS partes (a etapa e o teto de tentativas), e é o teto que impede a NAT de
    mandar uma terceira mensagem para quem já não respondeu duas vezes. Uma condição de teto
    replicada no TSX é uma condição de teto que um dia diverge — e o lado que diverge é o que
    manda mensagem.

    `tentativas_contato` e `max_tentativas_contato` vão junto porque a tela mostra
    "tentativa N de 2": sem os dois números, o frontend teria que saber o teto, que é
    exatamente o que a linha acima evita.
    """
    tentativas = state.tentativas_contato or 0
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
        "tentativas_contato": tentativas,
        "max_tentativas_contato": MAX_TENTATIVAS_CONTATO,
        "pode_marcar_sem_contato": (state.etapa in ETAPAS_PODE_MARCAR_SEM_CONTATO
                                    and tentativas < MAX_TENTATIVAS_CONTATO),
    }


VAZIO = {
    "em_fluxo": False, "etapa": None, "transferido_em": None, "assumido_por": None,
    "assumido_por_nome": None, "assumido_em": None, "escalonamento_nivel": 0,
    "pode_assumir": False, "tentativas_contato": 0,
    "max_tentativas_contato": MAX_TENTATIVAS_CONTATO, "pode_marcar_sem_contato": False,
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
    """Para o relógio do SLA, ENCERRA o fluxo e cancela o sla_check pendente.

    ENCERRAR É O QUE TIRA O LEAD DAS MÃOS DA NAT. Antes desta sprint, `assumir` gravava
    `assumido_por` e parava por aí: o lead ficava em `aguardando_ligacao` para sempre, porque
    nenhum caminho do código atribuía `encerrado` — a constante existia em models.py e nunca
    era usada. O efeito prático era o pior possível: depois de assumido, QUALQUER clique do
    lead caía em "clique fora da etapa esperada" e era descartado em silêncio
    (nat_flow.processar_clique), enquanto um SDR humano já estava conduzindo a conversa.

    Com `encerrado`, a NAT sai do caminho e não volta:
      * processar_clique  — a etapa não é aguardando_resposta, o clique é ignorado;
      * processar_texto   — a etapa não é aguardando_motivacao nem reagendado, sem transição.
    Nos dois casos a mensagem do lead segue o percurso normal (grava em `messages`, notifica o
    SDR dono), que é o atendimento humano que já assumiu. Ignorar aqui é a resposta CERTA, e
    não uma lacuna — o que estava errado era o lead nunca chegar a este estado.

    IDEMPOTENTE. Assumir duas vezes não é erro e não reabre nada: a segunda chamada devolve
    200 com quem já havia assumido e NÃO sobrescreve assumido_por/assumido_em. Sobrescrever
    seria pior que um erro — apagaria o registro de quem realmente pegou o lead primeiro, que
    é justamente o que a escada de escalonamento usa para saber quem responde por ele. Essa
    checagem vem ANTES da checagem de etapa, e tem que continuar vindo: depois desta mudança
    a própria etapa já não é mais `aguardando_ligacao` na segunda chamada, e inverter a ordem
    trocaria o 200 idempotente por um 409.

    Dois savepoints, na ordem da importância — mesmo raciocínio do Bloco 5:
      1. o carimbo + o encerramento, que é o que para o relógio e devolve o lead ao humano;
      2. o cancelamento do sla_check.
    Se o cancelamento falhar, o carimbo permanece e o SLA ainda não escalona: o handler relê
    o estado e encontra `assumido_por` preenchido — e agora também uma etapa que não é
    `aguardando_ligacao`, que é a PRIMEIRA das três saídas de "nada a fazer" do sla_check.
    Duas redes onde antes havia uma.

    O FRONTEND não lê `etapa` (conferido em conversations/page.tsx: usa só `pode_assumir`,
    `assumido_por`, `assumido_por_nome` e `assumido_em`). O botão "Assumir ligação" some, que
    é o desejado — já foi assumido —, e some pelo mesmo motivo de antes: `pode_assumir` exige
    `assumido_por is None`. No lugar dele aparece o selo verde com quem assumiu e a hora,
    ditado por `assumido_por`. Nada na tela muda por causa da etapa.
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
        # Mesma escrita lógica ("este lead é do humano agora"), mesmo savepoint: um estado
        # com assumido_por preenchido e etapa ainda em aguardando_ligacao seria exatamente o
        # meio-termo que esta fase existe para eliminar.
        state.etapa = ETAPA_ENCERRADO

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
    print(f"✋ NAT: {wa_id} assumido por {current_user.name} (id={current_user.id}) → "
          f"{ETAPA_ENCERRADO} — {cancelados} sla_check cancelado(s)")

    await db.refresh(state)
    return {"ja_assumido": False, "cancelados": cancelados, **await _payload(state, db)}


async def _estado_travado(wa_id: str, db: AsyncSession) -> NatFlowState | None:
    """O estado do fluxo, com a LINHA TRAVADA até o fim desta transação.

    `with_for_update()` e não o SELECT comum de `_estado`, porque este é o único endpoint da
    NAT que ENVIA MENSAGEM AO LEAD. Sem o lock, dois cliques simultâneos (dois SDRs, ou a
    mesma pessoa em duas abas) leriam `tentativas_contato = 0` ao mesmo tempo, os dois
    passariam pela janela de idempotência, e o lead receberia DUAS mensagens — queimando as
    duas tentativas de uma vez. Com o lock, o segundo espera o primeiro commitar e então
    enxerga a tentativa já registrada, que é o que faz a janela de 30s funcionar de fato.

    O /assumir não precisa disto: ele não manda nada ao lead, e o pior desfecho da corrida lá
    é um segundo carimbo que a checagem de `assumido_por` já rejeita.
    """
    res = await db.execute(
        select(NatFlowState).where(NatFlowState.contact_wa_id == wa_id).with_for_update())
    return res.scalar_one_or_none()


async def _tentativa_recente(wa_id: str, agora: datetime,
                             db: AsyncSession) -> NatContactAttempt | None:
    """A última tentativa deste contato, se ela for recente demais para ser um ato novo.

    Por CONTATO, não por usuário: o que a janela protege é o lead (uma mensagem só), e um
    segundo clique de outra pessoa entrega o mesmo dano que um segundo clique da mesma.

    Compara contra `created_at` gravado por nós em horário de SP — ver a nota do modelo sobre
    o DEFAULT NOW() ser UTC e não servir para comparação de negócio.
    """
    res = await db.execute(
        select(NatContactAttempt)
        .where(NatContactAttempt.contact_wa_id == wa_id)
        .order_by(NatContactAttempt.created_at.desc())
        .limit(1))
    ultima = res.scalar_one_or_none()
    if ultima is None or ultima.created_at is None:
        return None
    idade = (agora - ultima.created_at).total_seconds()
    return ultima if 0 <= idade < JANELA_IDEMPOTENCIA_SEGUNDOS else None


@router.post("/{wa_id}/sem-contato")
async def marcar_sem_contato(wa_id: str, db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    """O botão "Não consegui contato". Registra a tentativa, avisa o lead e cobra o SDR depois.

    O SDR ligou e ninguém atendeu. Sem este botão o lead ficava parado em
    `aguardando_ligacao` até alguém lembrar dele — e o SLA já tinha escalonado e se esgotado,
    então não havia mais nenhum mecanismo olhando para aquele lead.

    A SEQUÊNCIA, e por que ela é esta:

      1. TRAVA a linha do estado (ver _estado_travado) — é o que serializa cliques
         simultâneos, e é a única defesa contra mandar duas mensagens ao mesmo lead;
      2. IDEMPOTÊNCIA por contato, 30s — clique duplo é um ato só;
      3. TETO — se o lead já esgotou as tentativas, nada é enviado e o fluxo encerra;
      4. REGISTRA a tentativa (histórico + contador + etapa), tudo num savepoint só, porque é
         uma escrita lógica única: "houve uma tentativa";
      5. CANCELA o sla_check pendente — o relógio da transferência perdeu o objeto: o SDR
         ligou, e o que falta agora não é alguém assumir, é o lead responder;
      6. ENVIA a mensagem ao lead (a ÚNICA deste fluxo);
      7. AGENDA o retry de 10 min, que cobra o SDR — nunca o lead.

    NA 2ª TENTATIVA O FLUXO ENCERRA: a mensagem ainda sai (é a segunda e última chance de o
    lead reagir), mas nenhum retry é agendado e a etapa vai para `encerrado`. É o teto se
    fechando — sem ele, "recuperação" viraria insistência automática.

    O QUE NÃO ABORTA O REGISTRO. O envio ao lead e o agendamento do retry são efeitos
    colaterais: se a Meta recusar, ou se a NAT estiver desligada (que é o caso hoje), a
    tentativa continua registrada e a etapa continua mudando. O SDR ligou de fato — esse é um
    acontecimento do mundo, não uma consequência do envio. A resposta diz o que aconteceu com
    cada passo (`mensagem_enviada`, `retry_agendado`) em vez de fingir sucesso.
    """
    agora = _agora_sp()

    state = await _estado_travado(wa_id, db)
    if state is None:
        raise HTTPException(404, "Este contato não está no fluxo da NAT.")

    if state.etapa not in ETAPAS_PODE_MARCAR_SEM_CONTATO:
        raise HTTPException(
            409,
            f"O lead não está aguardando ligação (etapa atual: {state.etapa}). "
            "Não há tentativa de contato a registrar.")

    # --- 2. IDEMPOTÊNCIA (por contato, 30s) ---
    recente = await _tentativa_recente(wa_id, agora, db)
    if recente is not None:
        print(f"↩️  NAT: 'sem contato' de {wa_id} repetido em menos de "
              f"{JANELA_IDEMPOTENCIA_SEGUNDOS}s (tentativa {recente.tentativa_num} já "
              f"registrada por user {recente.registrado_por}) — nada gravado, nada enviado")
        return {"registrado": False, "motivo": "duplicado",
                "tentativa_num": recente.tentativa_num, "mensagem_enviada": False,
                "retry_agendado": False, "cancelados": 0, **await _payload(state, db)}

    tentativas_antes = state.tentativas_contato or 0

    # --- 3. TETO já estourado ANTES desta tentativa ---
    # Caminho de aba velha ou chamada direta à API: a tela esconde o botão quando
    # pode_marcar_sem_contato é falso. Não envia, não agenda, e deixa o lead em `encerrado` —
    # que é onde ele já deveria estar.
    if tentativas_antes >= MAX_TENTATIVAS_CONTATO:
        async with db.begin_nested():
            state.etapa = ETAPA_ENCERRADO
        await db.commit()
        await db.refresh(state)
        print(f"🛑 NAT: 'sem contato' de {wa_id} recusado — teto de "
              f"{MAX_TENTATIVAS_CONTATO} tentativas já atingido ({tentativas_antes}). "
              f"Nada enviado; lead em {ETAPA_ENCERRADO}.")
        return {"registrado": False, "motivo": "teto_de_tentativas",
                "tentativa_num": tentativas_antes, "mensagem_enviada": False,
                "retry_agendado": False, "cancelados": 0, **await _payload(state, db)}

    tentativa_num = tentativas_antes + 1
    ultima = tentativa_num >= MAX_TENTATIVAS_CONTATO

    # --- 4. REGISTRO: histórico + contador + etapa, um savepoint só ---
    async with db.begin_nested():
        db.add(NatContactAttempt(
            contact_wa_id=wa_id,
            tentativa_num=tentativa_num,
            registrado_por=current_user.id,
            resultado=RESULTADO_SEM_CONTATO,
            # Carimbo em SP, escrito por nós: é ele que a janela de idempotência compara. O
            # DEFAULT NOW() da coluna é UTC e serviria só de auditoria.
            created_at=agora,
        ))
        state.tentativas_contato = tentativa_num
        state.etapa = ETAPA_ENCERRADO if ultima else ETAPA_SEM_CONTATO

    # --- 5. CANCELA o sla_check pendente ---
    cancelados = 0
    try:
        async with db.begin_nested():
            from app.nat_scheduler import cancelar
            cancelados = await cancelar(KIND_SLA_CHECK, wa_id, db)
    except Exception as e:
        print(f"⚠️  NAT: {wa_id} marcado sem contato, mas o cancelamento do sla_check "
              f"falhou ({type(e).__name__}: {e}). O SLA não escalona: o handler relê o "
              f"estado e a etapa já não é {ETAPA_AGUARDANDO_LIGACAO}.")

    # --- 6. A ÚNICA MENSAGEM AO LEAD ---
    # Fora de savepoint, como em nat_flow.processar_clique: send_nat_message engole as
    # próprias exceções e devolve False, e o Message que ela grava tem que entrar no MESMO
    # commit do registro — um savepoint revertido aqui apagaria da conversa uma mensagem que
    # o lead já recebeu.
    dados = await _dados_do_lead(state, db)
    enviada = await send_nat_message(wa_id, nat_copy.NAT_MSG_RECUPERACAO, db,
                                     nome=dados["nome"], curso=dados["curso"])

    # --- 7. RETRY que cobra o SDR (nunca o lead). Não existe na última tentativa. ---
    retry_agendado = False
    if not ultima:
        try:
            async with db.begin_nested():
                from app.nat_scheduler import agendar
                await agendar(
                    KIND_RETRY_CONTATO, wa_id,
                    agora + timedelta(minutes=RETRY_CONTATO_MINUTOS),
                    {"tentativa": tentativa_num, "registrado_por": current_user.id}, db)
                retry_agendado = True
        except Exception as e:
            print(f"⚠️  NAT: retry_contato NÃO agendado para {wa_id} "
                  f"({type(e).__name__}: {e}) — a tentativa está registrada, mas ninguém "
                  "será cobrado automaticamente daqui a "
                  f"{RETRY_CONTATO_MINUTOS} min")

    await db.commit()
    await db.refresh(state)
    print(f"📵 NAT: {wa_id} sem contato (tentativa {tentativa_num}/"
          f"{MAX_TENTATIVAS_CONTATO}) por {current_user.name} (id={current_user.id}) → "
          f"{state.etapa} — mensagem {'enviada' if enviada else 'NÃO enviada'}, "
          f"{cancelados} sla_check cancelado(s), retry "
          f"{'agendado' if retry_agendado else 'não agendado'}")

    return {"registrado": True, "motivo": None, "tentativa_num": tentativa_num,
            "mensagem_enviada": enviada, "retry_agendado": retry_agendado,
            "cancelados": cancelados, **await _payload(state, db)}


# ==========================================================================================
# PAINEL DE CONTROLE DO nat_config — o kill switch
# ==========================================================================================
#
# Antes desta sprint, ligar e desligar a NAT era UPDATE manual no Postgres. Um kill switch
# que exige acesso ao banco não é kill switch: na hora em que ele é necessário, quem está
# olhando o problema pode não ser quem tem a credencial.
#
# ---------------------------------------------------------------------------------------
# ⚠️  nat_start_at É UTC. Esta é a única armadilha real deste endpoint.
#
# A trava de data compara nat_start_at com exact_leads.register_date (nat_guard, verificação
# 2), e register_date é gravado NAIVE EM UTC — está no docstring de date_parse.parse_datetime
# e confere no banco: em 11/08/2026 o register_date mais recente era 14:53 com o UTC em 15:18
# e o horário de São Paulo em 12:18.
#
# Ou seja, o resto do fluxo NAT trabalha em horário de São Paulo (nat_guard._agora_sp, o
# horário comercial, messages.timestamp), mas ESTE campo não. Gravar aqui o relógio de SP na
# hora da ativação poria o corte 3 HORAS NO PASSADO, e todo lead registrado nas 3 horas
# anteriores entraria no fluxo retroativamente — exatamente o que a decisão nº 2 do sprint
# proíbe. O erro seria silencioso: nenhuma exceção, só leads a mais.
#
# Por isso o endpoint NÃO aceita data sem fuso. As três formas de escrever o campo são:
#   "agora"                      -> o servidor resolve, e é o caminho da ativação
#   ISO com fuso ("...Z", "-03:00") -> convertido para UTC aqui
#   null                         -> apaga o corte, o que BLOQUEIA tudo (desligamento duro)
# Uma string ISO sem fuso é recusada com 400, porque não há resposta certa para ela.
# ---------------------------------------------------------------------------------------

CAMPOS_CONFIG = {"nat_enabled", "nat_start_at", "max_envios_hora"}


async def _config_singleton(db: AsyncSession) -> NatConfig:
    res = await db.execute(select(NatConfig).where(NatConfig.id == 1))
    cfg = res.scalar_one_or_none()
    if cfg is None:
        # Falha fechada, como o guard: sem config a NAT não atua, e inventar uma linha aqui
        # criaria o singleton com defaults sem ninguém ter decidido nada.
        raise HTTPException(404, "nat_config (id=1) não existe. Rode migrate_nat_config.py.")
    return cfg


def _para_utc_naive(valor, campo: str) -> datetime | None:
    """Normaliza o que veio no JSON para datetime naive em UTC. Ver o aviso acima."""
    if valor is None:
        return None
    if isinstance(valor, str) and valor.strip().lower() in {"agora", "now"}:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if not isinstance(valor, str):
        raise HTTPException(422, f"{campo} deve ser 'agora', uma data ISO com fuso, ou null.")

    texto = valor.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(texto)
    except ValueError:
        raise HTTPException(422, f"{campo}: '{valor}' não é uma data ISO válida.")

    if dt.tzinfo is None:
        raise HTTPException(
            422,
            f"{campo}: '{valor}' está sem fuso horário e seria ambíguo. Este campo é "
            "comparado com register_date, que é UTC — uma data sem fuso interpretada como "
            "horário de São Paulo poria o corte 3h no passado e deixaria leads retroativos "
            "entrarem no fluxo. Use \"agora\", ou informe o fuso ('2026-08-11T15:00:00Z' "
            "para UTC, '2026-08-11T12:00:00-03:00' para horário de São Paulo).")
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _serializar_config(cfg: NatConfig) -> dict:
    """O estado do kill switch, com o corte mostrado nos DOIS fusos.

    `nat_start_at_sp` não é redundância: o campo é UTC e todo o resto do sistema (e a cabeça
    de quem opera) é São Paulo. Sem a tradução ao lado, ninguém consegue conferir de relance
    se o corte que acabou de gravar é o que queria — e conferir o corte é a única defesa
    contra uma ativação retroativa.
    """
    corte = cfg.nat_start_at
    corte_sp = (corte.replace(tzinfo=timezone.utc).astimezone(SP_TZ).replace(tzinfo=None)
                if corte else None)
    return {
        "nat_enabled": cfg.nat_enabled,
        "nat_start_at": corte.isoformat() if corte else None,
        "nat_start_at_sp": corte_sp.isoformat() if corte_sp else None,
        "max_envios_hora": cfg.max_envios_hora,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        # A NAT só atua com os DOIS eixos ligados. Um `nat_enabled=true` com corte nulo
        # parece ligado na tela e não envia nada — a resposta diz o que vale de fato.
        "atuando": bool(cfg.nat_enabled and cfg.nat_start_at is not None),
    }


@router.get("/config")
async def get_nat_config(db: AsyncSession = Depends(get_db),
                         current_admin: User = Depends(get_current_admin)):
    """Estado atual do kill switch da NAT. Só admin."""
    return _serializar_config(await _config_singleton(db))


@router.patch("/config")
async def patch_nat_config(req: dict, db: AsyncSession = Depends(get_db),
                           current_admin: User = Depends(get_current_admin)):
    """Liga, desliga e ajusta o teto da NAT. Só admin. PATCH: o que não vier não muda.

    DESLIGAR NUNCA É BARRADO. Nenhuma validação roda no caminho de `nat_enabled: false` —
    é o caminho de emergência, e um kill switch que pode recusar o desligamento por causa de
    um campo inválido no mesmo corpo não serve para nada.

    LIGAR EXIGE O CORTE DE DATA, e essa é a validação que existe aqui. `nat_enabled=true` com
    `nat_start_at` nulo é o pior desfecho possível: o painel diz LIGADA, o guard bloqueia
    100% dos leads em "nat_start_at não definido", e quem ligou vai procurar o defeito em
    outro lugar. Os dois campos podem vir no mesmo PATCH.

    Chave desconhecida é 422, não é ignorada. Num endpoint cujo objetivo é desligar coisas
    às pressas, `{"nat_enable": false}` aceito em silêncio devolveria 200 com a NAT ligada.
    """
    if not isinstance(req, dict) or not req:
        raise HTTPException(422, f"Informe ao menos um campo: {sorted(CAMPOS_CONFIG)}.")

    desconhecidos = set(req) - CAMPOS_CONFIG
    if desconhecidos:
        raise HTTPException(
            422, f"Campo(s) desconhecido(s): {sorted(desconhecidos)}. "
                 f"Aceitos: {sorted(CAMPOS_CONFIG)}.")

    cfg = await _config_singleton(db)
    antes = _serializar_config(cfg)

    # --- validação dos valores, antes de escrever qualquer coisa ---
    if "nat_enabled" in req and not isinstance(req["nat_enabled"], bool):
        raise HTTPException(422, "nat_enabled deve ser true ou false.")

    if "max_envios_hora" in req:
        teto = req["max_envios_hora"]
        if isinstance(teto, bool) or not isinstance(teto, int) or teto < 0:
            raise HTTPException(422, "max_envios_hora deve ser um inteiro >= 0.")

    novo_corte = (_para_utc_naive(req["nat_start_at"], "nat_start_at")
                  if "nat_start_at" in req else cfg.nat_start_at)

    vai_ligar = req.get("nat_enabled", cfg.nat_enabled)
    if vai_ligar and novo_corte is None:
        raise HTTPException(
            422,
            "Para LIGAR a NAT é preciso um nat_start_at. Sem corte de data o guard bloqueia "
            "todos os leads e a NAT fica ligada sem atuar. Mande os dois juntos: "
            '{"nat_enabled": true, "nat_start_at": "agora"}.')

    # --- escrita ---
    if "nat_enabled" in req:
        cfg.nat_enabled = req["nat_enabled"]
    if "nat_start_at" in req:
        cfg.nat_start_at = novo_corte
    if "max_envios_hora" in req:
        cfg.max_envios_hora = req["max_envios_hora"]

    await db.commit()
    await db.refresh(cfg)
    depois = _serializar_config(cfg)

    # QUEM E QUANDO. `updated_at` é a coluna (o "quando", e ela já existia); o "quem" vai
    # para o journal, porque nat_config não tem coluna de autor e criar uma exigiria migração
    # — que esta sprint não roda sem aprovação. Prefixo fixo e gritante para o grep valer:
    #   journalctl -u <servico> | grep 'NAT CONFIG'
    mudancas = {k: (antes[k], depois[k]) for k in CAMPOS_CONFIG if antes[k] != depois[k]}
    print(f"🎛️  NAT CONFIG alterado por {current_admin.name} (id={current_admin.id}) em "
          f"{_agora_sp():%d/%m/%Y %H:%M:%S} (SP): "
          + (", ".join(f"{k}: {v[0]!r} → {v[1]!r}" for k, v in mudancas.items())
             or "nenhum valor mudou")
          + f" | atuando={depois['atuando']}")

    return depois
