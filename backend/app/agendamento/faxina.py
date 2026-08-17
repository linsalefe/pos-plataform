"""Job que devolve à agenda os boxes que ficaram pendurados.

------------------------------------------------------------------------------------------
O QUE FICA PENDURADO
------------------------------------------------------------------------------------------
Um fluxo que morra entre o `BoxesAdd` e o `scheduleAdd` deixa box `available` na agenda da
consultora. E `available` é justamente o status que a Exact trata como vago — o box aparece
na UI dela como horário disponível, e ninguém sabe de onde veio.

Isso acontece por caminhos reais: o processo reinicia no meio do fluxo, a Exact devolve
timeout no `LeadsAdd`, ou a própria compensação (`_compensar_box`) falha por rede.

------------------------------------------------------------------------------------------
POR QUE 15 MINUTOS
------------------------------------------------------------------------------------------
O fluxo inteiro leva segundos. Uma linha parada em `box_criado` por 15 minutos não está
lenta, está morta. O prazo é folgado de propósito: remover cedo demais tiraria o box de baixo
de um fluxo que ainda vai chamar o `scheduleAdd`, e aí o passo 3 falharia com
"The informed box does not exist" — trocando uma falha rara por uma constante.

------------------------------------------------------------------------------------------
POR QUE NÃO É PERIGOSO
------------------------------------------------------------------------------------------
A faxina só toca em box cujo id está na NOSSA tabela, em linha que não chegou a `agendado`.
Ela não varre a agenda da Exact procurando o que remover — não teria como distinguir um box
nosso de um bloco criado pela consultora na UI, e remover o bloco dela seria destruir agenda
real por engano.

E se o box já tiver reunião (corrida com um `scheduleAdd` que passou), o `BoxesRemove` recusa
com `BoxComReuniao` e a linha é promovida a `agendado` em vez de removida — o que é a
verdade: a reunião existe.
"""
import asyncio
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agendamento import client
from app.agendamento.horarios import agora_sp
from app.database import async_session
from app.models import PASSO_AGENDADO, PASSO_BOX_CRIADO, PASSO_FALHOU, Agendamento

INTERVALO_SEGUNDOS = 60
IDADE_MINIMA = timedelta(minutes=15)
# Teto por ciclo. A faxina divide o rate limit da Exact (30 req/20s) com o sync_job e com a
# própria LP; um acúmulo de 200 linhas não pode virar 200 DELETEs de uma vez.
MAX_POR_CICLO = 20


async def limpar(db: AsyncSession) -> dict:
    """Uma passada. Devolve o que fez, para o job logar e os testes afirmarem."""
    corte = agora_sp() - IDADE_MINIMA
    res = await db.execute(
        select(Agendamento)
        .where(Agendamento.passo == PASSO_BOX_CRIADO,
               Agendamento.updated_at <= corte,
               Agendamento.box_id.isnot(None))
        .order_by(Agendamento.updated_at)
        .limit(MAX_POR_CICLO)
    )
    pendentes = list(res.scalars().all())

    removidos = promovidos = falhas = 0
    for ag in pendentes:
        try:
            await client.remover_box(ag.box_id)
            ag.passo = PASSO_FALHOU
            ag.erro = "box removido pela faxina: fluxo não chegou ao scheduleAdd"
            removidos += 1
            print(f"🧹 faxina: box {ag.box_id} removido (agendamento #{ag.id})")
        except client.BoxComReuniao:
            # O scheduleAdd passou e nós não registramos — corrida, ou queda entre a chamada
            # e o commit. A reunião existe: a linha estava mentindo, não o box.
            ag.passo = PASSO_AGENDADO
            ag.erro = "reunião existe na Exact; passo corrigido pela faxina"
            promovidos += 1
            print(f"🧹 faxina: box {ag.box_id} TEM reunião — agendamento #{ag.id} promovido")
        except client.BoxInexistente:
            # Alguém removeu pela UI, ou a compensação passou e o commit não. Nada a fazer.
            ag.passo = PASSO_FALHOU
            ag.erro = "box não existe mais na Exact"
            removidos += 1
            print(f"🧹 faxina: box {ag.box_id} já não existia (agendamento #{ag.id})")
        except client.ExactErro as e:
            # Deixa em `box_criado` de propósito: o próximo ciclo tenta de novo. É o caso de
            # Exact fora do ar, que não deve consumir a linha.
            falhas += 1
            print(f"⚠️ faxina: falha ao remover box {ag.box_id} "
                  f"(agendamento #{ag.id}) — {type(e).__name__}: {e}")
            continue
        ag.updated_at = agora_sp()

    if removidos or promovidos:
        await db.commit()

    return {"candidatos": len(pendentes), "removidos": removidos,
            "promovidos": promovidos, "falhas": falhas}


async def faxina_job():
    """Laço do lifespan. Mesmo formato dos outros jobs do `main.py`."""
    while True:
        await asyncio.sleep(INTERVALO_SEGUNDOS)
        try:
            async with async_session() as db:
                resultado = await limpar(db)
            if resultado["candidatos"]:
                print(f"🧹 Faxina de agendamento: {resultado}")
        except Exception as e:
            print(f"❌ Erro na faxina de agendamento: {e}")
