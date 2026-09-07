"""O drenador da fila do RD Station. Cópia reduzida do `nat_scheduler`, com um gate.

Uma linha `pendente` por vez, travada por `FOR UPDATE SKIP LOCKED`, enviada e marcada na MESMA
transação. O desenho inteiro e o porquê de cada camada estão no cabeçalho de
`nat_scheduler.py` — aqui ficam só as diferenças, que são três:

  1. **Gate de operação.** O `nat_scheduler` nasceu ligado; este nasce DESLIGADO. Enquanto
     `RD_ENVIO_ENABLED` não for `true`, o job não faz uma única chamada ao RD e a fila
     acumula. É o que permite subir o código, olhar `rd_conversoes` com calma e só então
     abrir a torneira — sem a alternativa infeliz de descobrir o mapa errado depois de 300
     conversões terem entrado com o identifier de outro curso.

  2. **A retentativa é mais lenta.** `ATRASO_RETENTATIVA_SEGUNDOS = 300`, contra 60s de lá. O
     que se retenta aqui é indisponibilidade de um serviço de terceiro; insistir de minuto em
     minuto não faz o RD voltar mais cedo, e três tentativas em 15 minutos cobrem uma
     manutenção curta sem queimar as três em três minutos.

  3. **Retentar é seguro, e isso é uma propriedade do RD.** `agendamento/client.py:18-22` não
     tem retry porque um `BoxesAdd` repetido cria dois boxes. Aqui é o contrário: o RD casa a
     conversão pelo e-mail, e o mesmo evento duas vezes atualiza o mesmo contato em vez de
     duplicá-lo. Sem essa garantia, uma resposta perdida por timeout obrigaria a desistir.

------------------------------------------------------------------------------------------
SEM LIMITADOR DE TAXA SEPARADO
------------------------------------------------------------------------------------------
O RD aceita 120 requisições por minuto por conta. Este job faz no máximo `MAX_POR_CICLO`
chamadas a cada `INTERVALO_SEGUNDOS` — **50 por minuto**, com folga de mais que o dobro, e as
chamadas são SEQUENCIAIS (uma transação por linha), então o pico instantâneo também não
estoura. O teto sai da aritmética do laço, não de um contador que alguém precisa manter em dia.

O outro limite do RD, 120 eventos por lead por 24h, é irrelevante aqui: a UNIQUE
`(chave, conversion_identifier)` garante no máximo UM evento por pessoa por curso, para sempre.

Vale registrar o que NÃO existe, porque a pergunta volta: não há limitador de saída em lugar
nenhum deste projeto — nem para a Exact, nem para a Meta. O `_limitar` de
`agendamento/routes.py:67` é de ENTRADA, por IP. Se um dia `MAX_POR_CICLO` subir perto de 120,
é aqui que um contador de verdade terá de nascer.

------------------------------------------------------------------------------------------
FUSO: TUDO UTC NESTA TABELA
------------------------------------------------------------------------------------------
`run_at` e `created_at` de `rd_conversoes` têm `server_default (now() AT TIME ZONE 'utc')`, e
o corte deste job vem de `datetime.utcnow()`. É a exceção deliberada ao naive-SP do resto do
projeto, explicada na docstring de `RdConversao`: estes instantes não são hora de parede que
alguém lê, são só o relógio do drenador. O que NÃO pode acontecer é misturar — um
`agora_sp()` aqui adiantaria a fila em 3h, em silêncio, que é o defeito que o cabeçalho do
`nat_scheduler` documenta.
"""
import asyncio
import os
from datetime import datetime, timedelta

from sqlalchemy import select, update

from app.database import async_session
from app.models import (RD_ENVIADO, RD_FALHOU, RD_PENDENTE, RdConversao)
from app import rd_station

# Mesmo passo dos outros jobs do main.py. Uma conversão esperar até 60s é irrelevante para um
# fluxo de e-mail que trabalha em dias.
INTERVALO_SEGUNDOS = 60

# Teto por ciclo. É também o limitador de taxa (ver cabeçalho): 50/min contra os 120/min do RD.
MAX_POR_CICLO = 50

# Três tentativas e um humano olha. Sem backoff exponencial, mesma decisão do nat_scheduler.
MAX_TENTATIVAS = 3

# 5 minutos entre tentativas, empurrando o `run_at` — e não dormindo. O atraso vive no banco,
# então sobrevive a restart: o processo pode morrer entre tentativas sem que a linha volte a
# ser tentada em rajada. Sem empurrar o `run_at`, a linha continuaria vencida e as três
# tentativas queimariam na MESMA passada do laço, em milissegundos.
ATRASO_RETENTATIVA_SEGUNDOS = 300

# O corpo da resposta é guardado para diagnóstico, não para auditoria. 2000 chars cobrem
# qualquer erro estruturado do RD; um HTML de proxy pode vir com muito mais e não acrescenta.
LIMITE_RESPOSTA = 2000

# Status HTTP que merecem nova tentativa. 429 é excesso de chamadas (o RD pedindo calma) e
# 5xx é problema do lado deles — os dois passam. Qualquer outro 4xx é o RD dizendo que o
# PEDIDO está errado, e repetir um pedido errado só gasta cota.
_RETENTAVEIS = {429}


def _agora_utc() -> datetime:
    return datetime.utcnow()


def _envio_ligado() -> bool:
    """`RD_ENVIO_ENABLED` lido a cada ciclo, sem cache.

    Sem cache de propósito, mesma regra de `exact_spotter.get_headers` com o token: o
    operador tem de conseguir desligar o envio editando o `.env` e reiniciando, sem depender
    de o processo ter sido reiniciado no momento certo. Um ciclo de 60s é barato demais para
    justificar guardar um booleano.

    Aceita `true`, `1`, `sim` e `yes` — qualquer outra coisa, inclusive vazio, é DESLIGADO. A
    falha é fechada por escolha: se a variável estiver escrita errada, o que acontece é a fila
    acumular, não trezentas conversões saírem sem ninguém ter conferido o mapa.
    """
    return (os.getenv("RD_ENVIO_ENABLED", "") or "").strip().lower() in ("true", "1", "sim", "yes")


async def _proxima(db):
    """A conversão vencida mais antiga, TRAVADA para esta transação. None se não há.

    `FOR UPDATE SKIP LOCKED` com `LIMIT 1`: outro processo que rode o mesmo SELECT salta a
    linha travada em vez de esperar. Hoje há um worker só, então isto protege contra o futuro
    (segundo worker, restart com sobreposição, alguém rodando o drenador à mão num shell) e
    não contra o presente.
    """
    res = await db.execute(
        select(RdConversao)
        .where(RdConversao.status == RD_PENDENTE,
               RdConversao.run_at <= _agora_utc())
        .order_by(RdConversao.run_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return res.scalar_one_or_none()


async def _finalizar(db, linha_id: int, *, status: str | None = None,
                     motivo: str | None = None, resposta: str | None = None,
                     tentativas: int | None = None, run_at: datetime | None = None,
                     enviado_em: datetime | None = None) -> None:
    """Grava o desfecho por UPDATE explícito, não por atributo do ORM.

    Mesma razão de `nat_scheduler._finalizar`: este código roda depois de uma chamada externa
    que pode ter levantado, e um objeto ORM expirado recarregaria de forma lazy no meio do
    tratamento de erro. A linha já está travada por esta transação desde o SELECT, então o
    UPDATE não disputa nada.
    """
    valores: dict = {}
    if status is not None:
        valores["status"] = status
    if motivo is not None:
        valores["motivo"] = motivo
    if resposta is not None:
        valores["resposta"] = resposta[:LIMITE_RESPOSTA]
    if tentativas is not None:
        valores["tentativas"] = tentativas
    if run_at is not None:
        valores["run_at"] = run_at
    if enviado_em is not None:
        valores["enviado_em"] = enviado_em
    if not valores:
        return
    await db.execute(update(RdConversao).where(RdConversao.id == linha_id).values(**valores))


async def _adiar_ou_desistir(db, linha, *, motivo: str, resposta: str | None) -> str:
    """A retentativa. Empurra o `run_at` até a terceira falha; depois marca `falhou`."""
    tentativas = (linha.tentativas or 0) + 1
    if tentativas >= MAX_TENTATIVAS:
        await _finalizar(db, linha.id, status=RD_FALHOU, motivo=motivo,
                         resposta=resposta, tentativas=tentativas)
        print(f"❌ rd fila #{linha.id}: {motivo} na tentativa "
              f"{tentativas}/{MAX_TENTATIVAS} — desistindo.")
        return RD_FALHOU

    proxima = _agora_utc() + timedelta(seconds=ATRASO_RETENTATIVA_SEGUNDOS)
    await _finalizar(db, linha.id, motivo=motivo, resposta=resposta,
                     tentativas=tentativas, run_at=proxima)
    print(f"⚠️ rd fila #{linha.id}: {motivo} na tentativa {tentativas}/{MAX_TENTATIVAS}, "
          f"nova tentativa às {proxima:%H:%M:%S} UTC")
    return "adiado"


async def _enviar_uma(db, linha) -> str:
    """Envia UMA linha e grava o desfecho. Devolve um rótulo para o resumo do ciclo.

    A REGRA DE DESFECHO, e o porquê de cada ramo:

        2xx                    -> `enviado`, com `enviado_em`. Fim.
        429 e 5xx              -> retry. O pedido está certo; quem não pôde atender foi eles.
        erro de rede/timeout   -> retry. Não sabemos se chegou — e como o RD deduplica por
                                  e-mail, reenviar é seguro (ver cabeçalho).
        demais 4xx             -> `falhou` NA HORA, sem gastar tentativa. Um 400 por payload
                                  malformado ou um 401 por chave errada não melhoram na
                                  segunda vez; repetir só atrasaria a fila inteira e gastaria
                                  cota. O corpo da resposta fica em `resposta`, que é onde
                                  quem for consertar vai olhar.
    """
    try:
        status_http, corpo = await rd_station.enviar_conversao(linha.payload)
    except Exception as e:
        # `httpx.HTTPError` e qualquer outra falha de transporte. Não sabemos o status.
        return await _adiar_ou_desistir(
            db, linha, motivo=f"{type(e).__name__}: {e}", resposta=None)

    if 200 <= status_http < 300:
        await _finalizar(db, linha.id, status=RD_ENVIADO, resposta=corpo,
                         tentativas=(linha.tentativas or 0) + 1, enviado_em=_agora_utc())
        print(f"✅ rd fila #{linha.id}: conversão {linha.conversion_identifier} "
              f"aceita pelo RD ({status_http})")
        return RD_ENVIADO

    if status_http in _RETENTAVEIS or status_http >= 500:
        return await _adiar_ou_desistir(
            db, linha, motivo=f"HTTP {status_http}", resposta=corpo)

    await _finalizar(db, linha.id, status=RD_FALHOU, motivo=f"HTTP {status_http}",
                     resposta=corpo, tentativas=(linha.tentativas or 0) + 1)
    print(f"❌ rd fila #{linha.id}: RD recusou com {status_http} — sem retentativa. "
          f"Resposta: {corpo[:300]}")
    return RD_FALHOU


async def processar_pendentes(*, limite: int = MAX_POR_CICLO) -> dict:
    """Drena a fila vencida. Devolve `{rótulo: quantidade}`.

    Uma sessão e uma transação POR LINHA, não uma por lote: uma conversão lenta segura só o
    próprio lock, e uma que falhe não contamina a sessão das outras. O `break` sai no primeiro
    ciclo sem linha vencida, então o custo em fila vazia é um SELECT por minuto.

    O gate é conferido ANTES de abrir qualquer sessão: com o envio desligado, este job não
    toca no banco.
    """
    if not _envio_ligado():
        print("ℹ️ rd fila: envio DESLIGADO (RD_ENVIO_ENABLED != true) — "
              "as conversões continuam acumulando como pendente.")
        return {"desligado": True}

    if not (os.getenv("RD_API_KEY", "") or "").strip():
        # Ruidoso e sem tocar no banco: ligar o envio sem a chave é erro de operação, e
        # marcar as linhas como `falhou` por causa dele queimaria a fila inteira em três
        # ciclos por um problema que se conserta editando uma linha do `.env`.
        print("❌ rd fila: RD_ENVIO_ENABLED está ligado mas RD_API_KEY está vazia. "
              "Nada será enviado até a chave ser configurada.")
        return {"sem_chave": True}

    resumo: dict = {}
    for _ in range(limite):
        try:
            async with async_session() as db:
                linha = await _proxima(db)
                if linha is None:
                    break
                rotulo = await _enviar_uma(db, linha)
                await db.commit()
        except Exception as e:
            # Falha de infraestrutura (commit, lock, conexão), não do envio — aquele já tem o
            # próprio tratamento. Sem `break`: a linha continua pendente e o ciclo seguinte
            # tenta de novo. Sem `continue` cego também — contabiliza e segue.
            print(f"❌ rd fila: erro ao processar linha: {type(e).__name__}: {e}")
            resumo["erro"] = resumo.get("erro", 0) + 1
            continue
        resumo[rotulo] = resumo.get(rotulo, 0) + 1

    return resumo


async def rd_sender_job():
    """Loop de 60s. Registrado no lifespan de main.py, junto dos outros jobs.

    Dorme ANTES de trabalhar, como todos os outros jobs: no boot o processo tem coisa melhor a
    fazer, e uma conversão esperar 60s a mais é irrelevante.

    O try/except abraça o ciclo inteiro porque este loop não pode morrer: se ele morrer, a
    fila para de drenar sem nada quebrar visivelmente — e o modo de falha que esta integração
    inteira existe para corrigir foi exatamente esse, um canal de marketing que parou em
    silêncio.
    """
    while True:
        await asyncio.sleep(INTERVALO_SEGUNDOS)
        try:
            resumo = await processar_pendentes()
            # `desligado` sai em toda passada de propósito: é a única prova, no journald, de
            # que o gate está fechado por escolha e não porque o job morreu.
            if resumo:
                print(f"⏱️  rd fila: {resumo}")
        except Exception as e:
            print(f"❌ Erro no rd_sender_job: {type(e).__name__}: {e}")
