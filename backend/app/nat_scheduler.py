"""Agendador genérico da NAT — Bloco 7. "Rode isto para este contato a esta hora."

O SLA de 2 minutos do Bloco 5 é o primeiro consumidor, mas este módulo não sabe o que é um
SLA: ele guarda (kind, contato, hora) e despacha por `kind`. Acrescentar uma ação nova é
escrever um handler e registrar o módulo em MODULOS_DE_HANDLERS — nada aqui muda.

------------------------------------------------------------------------------------------
COMO A EXECUÇÃO ÚNICA É GARANTIDA
------------------------------------------------------------------------------------------
Três camadas, e as três importam:

1. `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1` — a linha fica travada pela transação que a
   pegou. Outro processo que rode o mesmo SELECT no mesmo instante SALTA a linha travada em
   vez de esperar por ela. Hoje há 1 worker, então isto é seguro contra o futuro (2º worker,
   restart com sobreposição, alguém rodando o job à mão num shell) e não contra o presente.

2. A ação é executada e marcada `executado` na MESMA TRANSAÇÃO. Não existe janela entre
   "executei" e "registrei que executei": ou as duas coisas entram no commit, ou nenhuma. Se
   o processo morrer no meio, o commit não acontece, a linha volta a `pendente` e a ação roda
   de novo do zero — nunca meio-executada e marcada como pronta.

3. UMA transação por ação, não uma por lote. Um handler lento segura o lock só da própria
   linha, e uma ação que falhe não contamina a sessão das outras.

O reverso disso é o que NÃO é garantido, e é bom dizer: a ação pode rodar mais de uma vez se
ela mesma tiver efeito colateral externo e o commit falhar depois. Para o sla_check isso é
inofensivo (o efeito é uma notificação no banco, que volta atrás junto). Um handler futuro
que mande WhatsApp precisa da própria idempotência — o mesmo padrão de
nat_flow_state.ultimo_wa_message_id.

------------------------------------------------------------------------------------------
RETENTATIVA
------------------------------------------------------------------------------------------
Handler levantou exceção → o SAVEPOINT dele é revertido (nada pela metade), `attempts += 1`,
a linha permanece `pendente` e o `run_at` é EMPURRADO para agora + ATRASO_RETENTATIVA_SEGUNDOS.
Na tentativa MAX_TENTATIVAS_ACAO (3) vira `falhou` e sai de circulação. Sem backoff
exponencial de propósito: 3 tentativas espaçadas de 60s, e depois um humano olha.

Empurrar o run_at não é detalhe — é o que FAZ a retentativa existir. Sem isso, a ação
continuaria vencida (`run_at <= corte`) e o laço interno de processar_pendentes a repescaria
na MESMA passada: as 3 tentativas queimariam em milissegundos, e uma falha transitória
(timeout de rede, indisponibilidade momentânea do banco) mataria a ação na hora — que é
exatamente o que a retentativa deveria evitar. Foi assim que a primeira versão deste módulo
se comportou, e só o smoke contra o Postgres mostrou.

Como o atraso vive no `run_at` (banco) e não em memória, ele também sobrevive a restart: o
processo pode morrer entre tentativas sem que a ação volte a ser tentada em rajada.

`kind` sem handler NÃO consome tentativa: vira `falhou` na hora, com o motivo. Retentar não
faz um kind desconhecido virar conhecido, e ficar 3 ciclos tentando só atrasaria o alarme.

------------------------------------------------------------------------------------------
FUSO
------------------------------------------------------------------------------------------
`run_at` é naive em horário de São Paulo, igual a messages.timestamp. O banco está em
Etc/UTC: um `run_at <= now()` do Postgres compararia SP contra UTC e dispararia tudo 3h
adiantado, em silêncio. O corte SEMPRE vem de `_agora_sp()` (Python) — reaproveitado de
nat_guard, não reimplementado aqui, para não existirem duas definições de "agora".
"""
import asyncio
import json
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import (ACAO_CANCELADO, ACAO_EXECUTADO, ACAO_FALHOU, ACAO_PENDENTE,
                        ACAO_SKIPPED, KIND_INICIAR_QUALIFICACAO, MAX_TENTATIVAS_ACAO,
                        ExactLead, NatScheduledAction)
from app.nat_guard import _agora_sp

# De quanto em quanto tempo o job varre a fila. 60s é o mesmo passo do
# scheduled_messages_job. Para o SLA de 2 min significa disparar entre 2:00 e 3:00 depois da
# transferência — aceitável, e a alternativa (varrer a cada 5s) seria 12x mais consulta para
# ganhar segundos num relógio que já é humano.
INTERVALO_SEGUNDOS = 60

# Teto de ações por ciclo. Protege contra a fila crescer sem limite e o job passar um ciclo
# inteiro drenando (ex.: banco fora do ar por uma hora, 600 ações vencidas de uma vez). O que
# sobrar é pego no ciclo seguinte, em ordem de run_at — nada é perdido, só adiado.
MAX_ACOES_POR_CICLO = 50

# Espaçamento entre tentativas de uma ação que falhou. Aplicado empurrando o run_at, o que
# tira a ação da passada atual e a devolve à fila só depois desse intervalo. Igual ao passo do
# job para não inventar um segundo relógio: na prática, uma tentativa por ciclo.
ATRASO_RETENTATIVA_SEGUNDOS = 60

# Módulos que registram handlers. Importados sob demanda por _resolver_handler, e não no topo
# deste arquivo, porque o caminho natural é o inverso: quem tem handler importa `agendar`
# daqui. Importar de volta no topo criaria ciclo.
#
# Um `kind` cujo módulo não esteja listado aqui vira `falhou` com motivo explícito — o que é
# ruidoso em vez de silencioso, e é o comportamento certo.
MODULOS_DE_HANDLERS: tuple[str, ...] = ("app.nat_sla", "app.nat_recuperacao",
                                       "app.qualificacao_fluxo")

# Rótulo do desfecho "adiada" no resumo de processar_pendentes. NÃO é status de banco: a
# linha continua `pendente`, com o run_at empurrado. Existe separado de ACAO_PENDENTE para o
# resumo do ciclo distinguir "adiei 3" de "3 continuam na fila sem terem sido tocadas".
ACAO_ADIADO = "adiado"

# kind -> coroutine(acao: dict, db: AsyncSession). Preenchido por registrar_handler.
_HANDLERS: dict = {}


# ------------------------------------------------------------------------------------------
# OS DOIS DESFECHOS QUE NÃO SÃO "EXECUTOU" NEM "FALHOU"  (Risco 3)
# ------------------------------------------------------------------------------------------
# Antes disto um handler tinha três saídas: agir, levantar exceção (retentativa), ou dar
# `return` mudo. O `return` mudo virava `executado` — e "executado" passava a significar duas
# coisas incompatíveis: "a abertura saiu" e "eu desisti deste lead". Foi assim que 4 ações
# executadas produziram ZERO estados em 25/08 sem nada quebrar.
#
# São exceções, e não valores de retorno, por um motivo concreto: o handler roda dentro de
# `db.begin_nested()`, e levantar REVERTE o savepoint. Um handler que já tinha escrito
# metade das coisas (criado o Contact, criado o estado) e então descobre que não pode enviar
# não deixa resíduo — o que um `return` no meio deixaria.
class AcaoIgnorada(Exception):
    """Não havia o que fazer, e não haverá. Vira `skipped` com o motivo GRAVADO.

    Não consome tentativa e não vira `falhou`: nada falhou. É o desfecho de "este lead já
    tem estado", "é anterior ao corte", "não tem telefone".
    """

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


class AcaoAdiada(Exception):
    """Não dá para agir AGORA, mas vai dar. Volta a `pendente` com `run_at` empurrado.

    NÃO CONSOME TENTATIVA — esta é a diferença que importa em relação a levantar uma
    exceção qualquer. Adiar não é falhar: um lead que chega às 22h vai esperar até as 09h e
    isso não pode gastar 1 das 3 tentativas que existem para erro de verdade.

    O motivo fica gravado na linha PENDENTE, que é o que torna visível — sem depender do log
    — a fila que está parada esperando janela.
    """

    def __init__(self, quando: datetime, motivo: str):
        super().__init__(f"{motivo} → {quando:%d/%m %H:%M}")
        self.quando = quando
        self.motivo = motivo


def registrar_handler(kind: str):
    """Decorator: liga um `kind` ao seu handler.

    O handler recebe (acao: dict, db) — dict, não o objeto ORM, de propósito: ele roda dentro
    de um SAVEPOINT que pode ser revertido, e reverter savepoint EXPIRA os objetos ORM
    tocados nele. Um acesso a atributo depois disso dispararia recarga lazy, que em contexto
    async estoura MissingGreenlet. O snapshot em dict elimina a classe de bug inteira, e de
    graça torna o handler testável sem banco.

    Não pode levantar em silêncio: registrar dois handlers para o mesmo kind é erro de
    programação, e o segundo sobrescrever o primeiro seria descoberto em produção.
    """
    def decorator(fn):
        if kind in _HANDLERS and _HANDLERS[kind] is not fn:
            raise RuntimeError(f"handler duplicado para kind={kind!r}")
        _HANDLERS[kind] = fn
        return fn
    return decorator


def _resolver_handler(kind: str):
    """Handler do kind, ou None. Importa MODULOS_DE_HANDLERS na primeira necessidade."""
    if kind not in _HANDLERS:
        for modulo in MODULOS_DE_HANDLERS:
            __import__(modulo)
    return _HANDLERS.get(kind)


def payload_de(acao: dict) -> dict:
    """payload da ação como dict. Nunca levanta.

    JSON quebrado ou payload NULL devolve {} — um payload ilegível é problema do handler
    (que vai achar a chave faltando e falhar com motivo claro), não motivo para derrubar o
    despacho de TODAS as ações do ciclo.
    """
    bruto = acao.get("payload")
    if not bruto:
        return {}
    try:
        dados = json.loads(bruto)
        return dados if isinstance(dados, dict) else {}
    except (ValueError, TypeError):
        print(f"⚠️  NAT scheduler: payload ilegível na ação {acao.get('id')}: {bruto!r}")
        return {}


# ------------------------------------------------------------------------------------------
# API DE AGENDAMENTO
#
# agendar e cancelar NÃO abrem savepoint e NÃO dão commit — são primitivas, e quem chama
# decide a fronteira da transação. Isso não é descuido em relação à regra "toda escrita da
# NAT em begin_nested()": a regra é cumprida no ponto de chamada (nat_flow, o endpoint
# /assumir), e é o único jeito de o handler do sla_check reagendar ATOMICAMENTE junto da
# própria marcação de `executado`. Se agendar abrisse a própria transação, o reagendamento
# poderia sobreviver a um rollback que desfez a execução que o originou.
# ------------------------------------------------------------------------------------------

async def agendar(kind: str, contact_wa_id: str, run_at: datetime, payload: dict,
                  db: AsyncSession) -> int:
    """Agenda uma ação e devolve o id criado.

    CANCELA antes de inserir o pendente do mesmo (kind, contato), se houver. É o que dá a
    semântica de "no máximo um pendente por tipo por contato" — reagendar substitui, não
    acumula. O índice único parcial do banco é a rede de segurança da mesma regra; este
    cancelamento é o mecanismo, e é o que evita que o INSERT esbarre no índice.

    `run_at` deve ser naive em SP (ver docstring do módulo).
    """
    await cancelar(kind, contact_wa_id, db)

    acao = NatScheduledAction(
        kind=kind,
        contact_wa_id=contact_wa_id,
        run_at=run_at,
        payload=json.dumps(payload, ensure_ascii=False) if payload else None,
        status=ACAO_PENDENTE,
        attempts=0,
    )
    db.add(acao)
    await db.flush()  # materializa o id do BIGSERIAL sem commitar
    print(f"⏰ NAT scheduler: {kind} agendado para {contact_wa_id} às "
          f"{run_at:%Y-%m-%d %H:%M:%S} (id={acao.id})")
    return acao.id


async def cancelar(kind: str, contact_wa_id: str, db: AsyncSession) -> int:
    """Cancela os pendentes de (kind, contato). Devolve quantos foram cancelados.

    Só mexe em `pendente`: executado/cancelado/falhou é histórico e não se reescreve. Zero
    cancelados é resultado normal, não erro — é o caso de "o SLA já tinha disparado quando o
    SDR clicou em Assumir", e é justamente o que torna o /assumir idempotente.
    """
    res = await db.execute(
        update(NatScheduledAction)
        .where(NatScheduledAction.kind == kind,
               NatScheduledAction.contact_wa_id == contact_wa_id,
               NatScheduledAction.status == ACAO_PENDENTE)
        .values(status=ACAO_CANCELADO, processed_at=_agora_sp())
    )
    quantos = res.rowcount or 0
    if quantos:
        print(f"🚫 NAT scheduler: {quantos} ação(ões) {kind} cancelada(s) para {contact_wa_id}")
    return quantos


# ------------------------------------------------------------------------------------------
# EXECUÇÃO
# ------------------------------------------------------------------------------------------

async def _proxima_acao(db: AsyncSession, corte: datetime):
    """A ação vencida mais antiga, TRAVADA para esta transação. None se não há nenhuma.

    ORDER BY run_at: quem venceu primeiro roda primeiro. Importa no escalonamento, onde a
    ordem das ações é a ordem dos níveis.
    """
    res = await db.execute(
        select(NatScheduledAction)
        .where(NatScheduledAction.status == ACAO_PENDENTE,
               NatScheduledAction.run_at <= corte)
        .order_by(NatScheduledAction.run_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return res.scalar_one_or_none()


def _snapshot(acao: NatScheduledAction, agora: datetime) -> dict:
    """Valores primitivos da ação, para o handler não depender do estado do ORM.

    `agora` entra no snapshot para o handler usar o MESMO relógio do ciclo em vez de chamar
    _agora_sp() por conta própria. É a mesma regra de um-relógio-só que o smoke da Fase 3
    cobrou aqui dentro: um handler que reagenda (o sla_check reagenda) precisa que o "+2 min"
    parta do instante do ciclo, senão o tempo simulado dos testes não fecha.
    """
    return {
        "id": acao.id,
        "kind": acao.kind,
        "contact_wa_id": acao.contact_wa_id,
        "run_at": acao.run_at,
        "payload": acao.payload,
        "attempts": acao.attempts or 0,
        "agora": agora,
    }


async def _finalizar(db: AsyncSession, acao_id: int, status: str, agora: datetime,
                     attempts: int | None = None, run_at: datetime | None = None,
                     motivo: str | None = None):
    """Grava o desfecho por UPDATE explícito, não por atributo do ORM.

    UPDATE e não `acao.status = ...` porque este código roda depois de um savepoint que pode
    ter sido revertido, e um objeto ORM expirado recarregaria de forma lazy. A linha já está
    travada por esta transação desde o SELECT FOR UPDATE, então o UPDATE não disputa nada.

    processed_at só é carimbado em desfecho FINAL. Uma ação que ainda vai ser retentada
    continua `pendente` e sem processed_at — o campo responde "quando isto saiu da fila", e
    não "quando foi tentado pela última vez".
    """
    # `motivo` é escrito SEMPRE, inclusive como NULL: uma ação adiada pelo teto que enfim
    # executa não pode ficar carregando o motivo do adiamento anterior como se ainda valesse.
    valores = {"status": status, "motivo": motivo}
    if attempts is not None:
        valores["attempts"] = attempts
    if run_at is not None:
        valores["run_at"] = run_at
    if status != ACAO_PENDENTE:
        valores["processed_at"] = agora
    await db.execute(
        update(NatScheduledAction).where(NatScheduledAction.id == acao_id).values(**valores))


# O carimbo que o sync põe no lead quando cede a abertura ao agente. É o texto de
# `exact_spotter.py:266` — casado por LIKE porque ele leva o motivo entre parênteses
# ("(enfileirado)", "(já tem estado)") e o motivo não importa aqui.
CARIMBO_AGENTE_ASSUMIU = "%assumiu a abertura%"


async def _desmentir_carimbo_do_lead(db: AsyncSession, dados: dict, motivo: str) -> None:
    """A abertura NÃO saiu — então o lead não pode continuar carimbado como atendido.

    ------------------------------------------------------------------------------------
    O QUE ESTA FUNÇÃO CONSERTA
    ------------------------------------------------------------------------------------
    `exact_spotter.py:266` carimba `welcome_status='skipped'` com "agente de pré-qualificação
    assumiu a abertura" no instante em que a ação é ENFILEIRADA. O comentário lá já trata o
    caso de o gatilho recusar na hora. O que faltava é o outro: a ação pode morrer 5 minutos
    ou 2 dias DEPOIS, e até 29/08 ninguém voltava no carimbo.

    O lead ficava terminal pelos três lados ao mesmo tempo, e é a conjunção que o some:

        `existing` no sync            -> nunca volta a `new_leads_to_contact`
        `welcome_status` não-nulo     -> `reprocessar_leads_perdidos.py` filtra IS NULL
        ação em estado final          -> o agendador não a repesca

    MEDIDO em 29/08 (RECON_VAO_ESPONTANEO_20260829 §4.2): 7 leads carimbados como atendidos
    sem uma única abertura — 3 pela saída muda de 25/08 e 4 pela grafia do telefone. Os dois
    bugs já estavam consertados; o que não existia era o caminho de volta.

    ------------------------------------------------------------------------------------
    O QUE ELA NÃO FAZ, DE PROPÓSITO
    ------------------------------------------------------------------------------------
    **Não mexe em `welcome_status`.** Ele é a trava de idempotência que o passo 3 de
    `send_welcome_to_new_lead` consulta (`is not null`), e devolvê-lo a NULL faria o lead
    voltar a ser candidato à BOAS-VINDAS — que é o fluxo velho, não o agente. O que estava
    errado nunca foi o status; era o texto ao lado dele.

    **Não reenfileira.** Enfileirar de novo é decisão com triagem humana — a mesma que o
    dict EXCLUIDOS de `reprocessar_leads_perdidos.py` registra. Aqui só se grava a verdade,
    para que a varredura de reconciliação consiga ENXERGAR o lead depois.

    **Só reescreve o carimbo que mente.** O `WHERE` exige `welcome_error LIKE
    '%assumiu a abertura%'`: um lead marcado "funil fora do escopo" ou "backfill 25/08" tem
    carimbo verdadeiro, e sobrescrevê-lo apagaria a decisão de quem o pôs lá.

    Savepoint próprio pelo mesmo motivo de `_registrar_transicao`: um erro aqui não pode
    abortar a transação que acabou de registrar o desfecho da ação. O desfecho é o que
    importa; este UPDATE é o acréscimo.
    """
    if dados["kind"] != KIND_INICIAR_QUALIFICACAO:
        return                      # só a abertura nasce daquele carimbo
    lead_id = payload_de(dados).get("lead_id")
    if not lead_id:
        return                      # LP sem lead na Exact ainda — não há o que desmentir

    try:
        async with db.begin_nested():
            resultado = await db.execute(
                update(ExactLead)
                .where(ExactLead.exact_id == lead_id,
                       ExactLead.welcome_status == ACAO_SKIPPED,
                       ExactLead.welcome_error.ilike(CARIMBO_AGENTE_ASSUMIU))
                .values(welcome_error=f"agente NÃO abriu: {motivo}"))
        if resultado.rowcount:
            print(f"🩹 Agente: carimbo do lead {lead_id} corrigido — a abertura não saiu "
                  f"({motivo})")
    except Exception as e:
        # Nunca custar o registro do desfecho por causa do acréscimo.
        print(f"⚠️  Agente: não deu para corrigir o carimbo do lead {lead_id} "
              f"({type(e).__name__}: {e})")


async def _executar_acao(acao: NatScheduledAction, db: AsyncSession, agora: datetime) -> str:
    """Executa uma ação já travada e grava o desfecho. Devolve o status final.

    NÃO dá commit: quem chama commita, e é esse commit que torna "executou" e "está marcado
    como executado" a mesma operação.

    `agora` é o MESMO instante usado como corte no SELECT, propagado de propósito. Usar
    `_agora_sp()` aqui criaria um segundo relógio: com tempo simulado, o run_at empurrado
    cairia antes do corte e a ação seria repescada na mesma passada — a falha que o smoke
    pegou. Um relógio por ciclo, e ele desce por parâmetro.
    """
    dados = _snapshot(acao, agora)
    acao_id, kind = dados["id"], dados["kind"]

    handler = _resolver_handler(kind)
    if handler is None:
        await _finalizar(db, acao_id, ACAO_FALHOU, agora)
        print(f"⛔ NAT scheduler: kind {kind!r} sem handler (ação {acao_id}) → falhou. "
              f"Registre o módulo em MODULOS_DE_HANDLERS.")
        return ACAO_FALHOU

    try:
        # SAVEPOINT: um handler que falhe no meio não deixa escrita parcial, e a transação
        # segue utilizável para registrar a tentativa logo abaixo. try/except puro não
        # bastaria — um IntegrityError deixaria a transação abortada e o próprio UPDATE de
        # attempts falharia com InFailedSQLTransaction.
        #
        # AcaoIgnorada e AcaoAdiada também revertem este savepoint, e isso é o desejado: o
        # handler pode ter criado Contact e estado antes de descobrir que não vai enviar, e
        # nenhum dos dois deve sobreviver a uma abertura que não saiu.
        async with db.begin_nested():
            await handler(dados, db)
    except AcaoIgnorada as e:
        await _finalizar(db, acao_id, ACAO_SKIPPED, agora, motivo=e.motivo)
        # DEPOIS do `_finalizar`, e fora do savepoint do handler: aquele savepoint acabou de
        # ser revertido pela exceção, e escrever antes seria escrever no que some.
        await _desmentir_carimbo_do_lead(db, dados, e.motivo)
        print(f"⏭️  NAT scheduler: {kind} (ação {acao_id}, {dados['contact_wa_id']}) "
              f"SKIPPED — {e.motivo}")
        return ACAO_SKIPPED
    except AcaoAdiada as e:
        # Sem `attempts=`: adiar não consome tentativa. Ver a docstring de AcaoAdiada.
        await _finalizar(db, acao_id, ACAO_PENDENTE, agora, run_at=e.quando,
                         motivo=e.motivo)
        print(f"⏳ NAT scheduler: {kind} (ação {acao_id}, {dados['contact_wa_id']}) adiada "
              f"para {e.quando:%d/%m %H:%M} — {e.motivo}")
        return ACAO_ADIADO
    except Exception as e:
        tentativas = dados["attempts"] + 1
        if tentativas >= MAX_TENTATIVAS_ACAO:
            await _finalizar(db, acao_id, ACAO_FALHOU, agora, attempts=tentativas)
            # `falhou` esgota as 3 tentativas e sai de circulação — é tão terminal quanto o
            # `skipped`, e deixa o lead exatamente na mesma invisibilidade. O carimbo mente
            # igual, então é desmentido igual.
            await _desmentir_carimbo_do_lead(
                db, dados, f"{type(e).__name__}: {e}"[:200])
            print(f"⛔ NAT scheduler: {kind} (ação {acao_id}, {dados['contact_wa_id']}) "
                  f"falhou na tentativa {tentativas}/{MAX_TENTATIVAS_ACAO} — desistindo. "
                  f"{type(e).__name__}: {e}")
            return ACAO_FALHOU
        # run_at empurrado: é o que tira a ação desta passada e dá espaçamento de verdade
        # entre tentativas (ver RETENTATIVA na docstring do módulo).
        proxima = agora + timedelta(seconds=ATRASO_RETENTATIVA_SEGUNDOS)
        await _finalizar(db, acao_id, ACAO_PENDENTE, agora, attempts=tentativas,
                         run_at=proxima)
        print(f"⚠️  NAT scheduler: {kind} (ação {acao_id}, {dados['contact_wa_id']}) falhou "
              f"na tentativa {tentativas}/{MAX_TENTATIVAS_ACAO}, nova tentativa às "
              f"{proxima:%H:%M:%S}. {type(e).__name__}: {e}")
        return ACAO_PENDENTE

    await _finalizar(db, acao_id, ACAO_EXECUTADO, agora)
    return ACAO_EXECUTADO


async def processar_pendentes(*, agora: datetime | None = None,
                              limite: int = MAX_ACOES_POR_CICLO) -> dict:
    """Drena a fila vencida. Devolve {status: quantidade}.

    `agora` explícito é o que permite testar o vencimento sem mock de relógio — mesmo padrão
    de dentro_horario_comercial(quando=...).

    Uma transação (e uma sessão) por ação. O `break` sai no primeiro ciclo sem ação vencida,
    então o custo em fila vazia é UM select por minuto.
    """
    corte = agora if agora is not None else _agora_sp()
    resumo: dict = {}

    for _ in range(limite):
        try:
            async with async_session() as db:
                acao = await _proxima_acao(db, corte)
                if acao is None:
                    break
                status = await _executar_acao(acao, db, corte)
                await db.commit()
        except Exception as e:
            # Falha na infraestrutura (commit, lock, conexão), não no handler — este já tem
            # o próprio savepoint. Sem `break`: a ação continua pendente e o ciclo seguinte
            # tenta de novo. Sem `continue` cego também — contabiliza e segue.
            print(f"❌ NAT scheduler: erro ao processar ação: {type(e).__name__}: {e}")
            resumo["erro"] = resumo.get("erro", 0) + 1
            continue
        resumo[status] = resumo.get(status, 0) + 1

    return resumo


async def nat_scheduler_job():
    """Loop de 60s. Registrado no lifespan de main.py, junto dos outros jobs.

    Dorme ANTES de trabalhar, como todos os outros jobs do main.py: no boot o processo tem
    coisa melhor a fazer, e uma ação vencida esperar 60s a mais é irrelevante.

    O try/except abraça o ciclo inteiro porque este loop não pode morrer: se ele morrer, o
    SLA para de existir sem nada quebrar visivelmente — o pior tipo de falha.
    """
    while True:
        await asyncio.sleep(INTERVALO_SEGUNDOS)
        try:
            resumo = await processar_pendentes()
            if resumo:
                print(f"⏱️  NAT scheduler: {resumo}")
        except Exception as e:
            print(f"❌ Erro no nat_scheduler_job: {type(e).__name__}: {e}")
