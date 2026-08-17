"""Quais slots da grade estão livres. É EXIBIÇÃO, não reserva.

------------------------------------------------------------------------------------------
ESTA LEITURA NÃO GARANTE VAGA
------------------------------------------------------------------------------------------
Entre o visitante ver a grade e clicar em "agendar" passam segundos ou minutos, e outra
pessoa pode ter pego o horário. Quem decide de verdade é o `BoxesAdd`, que recusa qualquer
sobreposição e por isso É o lock (AGENDAMENTO_FINDINGS.md §8).

O papel deste módulo é não OFERECER o que obviamente já está tomado. Se ele errar para menos,
o visitante vê um horário a menos; se errar para mais, o `BoxesAdd` devolve 409 e o front
recarrega. Nenhum dos dois corrompe nada — o que seria grave é confiar nele para reservar.

------------------------------------------------------------------------------------------
DUAS SUBTRAÇÕES, E POR QUE AS DUAS
------------------------------------------------------------------------------------------
1. **Boxes da Exact** (`$filter` por período e consultor) — os blocos da agenda dela, mais os
   boxes que nós já criamos. É a fonte autoritativa.

2. **Nossos agendamentos em voo** (`passo` em box_criado/lead_criado/agendado) — redundante
   com (1) na maior parte do tempo, e não é: o `GET /Boxes` responde a partir de um cache do
   lado da Exact que já vi atrasar alguns segundos, e é exatamente nesses segundos que dois
   visitantes simultâneos brigam pelo mesmo slot. Custa um SELECT indexado.
"""
import time as _time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agendamento import client
from app.agendamento.grade import Slot, grade
from app.agendamento.horarios import agora_sp, de_exact
from app.models import PASSO_FALHOU, PASSO_INICIADO, Agendamento

# Cache do resultado de /slots. 60s é o pedido do produto e casa com o custo: sem ele, cada
# visitante que abre o obrigado.html dispara um GET /Boxes, e o rate limit da Exact
# (30 req/20s) é do TOKEN INTEIRO — dividido com o sync_job que roda a cada 10 min.
CACHE_SEGUNDOS = 60
_cache: tuple[float, list[Slot]] | None = None


def _sobrepoe(a_ini: datetime, a_fim: datetime, b_ini: datetime, b_fim: datetime) -> bool:
    """Interseção de intervalos meio-abertos: encostar não é sobrepor.

    Um slot 11:00–11:45 e um bloco 11:45–12:30 NÃO conflitam. É a mesma regra que o
    `BoxesAdd` aplica — os blocos de produção 09:00–10:10 e 13:30–14:30 convivem sem reclamar.
    """
    return a_ini < b_fim and b_ini < a_fim


async def _ocupados_na_exact(inicio: datetime, fim: datetime,
                             sales_rep_email: str) -> list[tuple[datetime, datetime]]:
    boxes = await client.listar_boxes(inicio, fim, sales_rep_email)
    faixas = []
    for box in boxes:
        try:
            faixas.append((de_exact(box["start"]), de_exact(box["end"])))
        except (KeyError, ValueError):
            continue  # box com data ilegível não deve derrubar a grade inteira
    return faixas


async def _ocupados_por_nos(db: AsyncSession, inicio: datetime,
                            fim: datetime) -> list[tuple[datetime, datetime]]:
    res = await db.execute(
        select(Agendamento.slot_inicio, Agendamento.slot_fim).where(
            Agendamento.slot_inicio >= inicio,
            Agendamento.slot_inicio <= fim,
            Agendamento.passo.notin_([PASSO_FALHOU, PASSO_INICIADO]),
        )
    )
    return [(linha[0], linha[1]) for linha in res.all()]


async def slots_livres(db: AsyncSession, *, usar_cache: bool = True) -> list[Slot]:
    """A grade menos o que já está ocupado. Ordenado por horário.

    `usar_cache=False` no caminho do POST /agendar: ali a resposta vai virar decisão, e servir
    uma leitura de até 60s atrás só aumentaria a chance de oferecer um slot morto.
    """
    global _cache
    agora = _time.monotonic()
    if usar_cache and _cache is not None and (agora - _cache[0]) < CACHE_SEGUNDOS:
        return _cache[1]

    g = grade()
    candidatos = g.slots_candidatos()
    if not candidatos:
        _cache = (agora, [])
        return []

    janela_ini = min(s.inicio for s in candidatos).replace(hour=0, minute=0, second=0)
    janela_fim = max(s.inicio for s in candidatos) + timedelta(days=1)

    ocupados = await _ocupados_na_exact(janela_ini, janela_fim, g.sales_rep_email)
    ocupados += await _ocupados_por_nos(db, janela_ini, janela_fim)

    livres = [
        slot for slot in candidatos
        if not any(_sobrepoe(slot.inicio, slot.fim, oi, of) for oi, of in ocupados)
    ]
    livres.sort(key=lambda s: s.inicio)
    _cache = (agora, livres)
    return livres


def invalidar_cache() -> None:
    """Chamado depois de um agendamento bem-sucedido.

    Sem isto, o slot recém-tomado continuaria sendo oferecido por até 60s — e todo mundo que
    o escolhesse tomaria 409. Não é corretude (o `BoxesAdd` protege), é não fazer o visitante
    passar por um erro evitável.
    """
    global _cache
    _cache = None


async def resumo_por_dia(db: AsyncSession) -> dict[str, list[dict]]:
    """Formato que o front consome: `{"2026-08-19": [{"id": ..., "hora": "11:00"}, ...]}`.

    Agrupado por dia porque o calendário da LP desenha por dia, e fazer esse agrupamento no
    JavaScript significaria repetir a regra de fuso do lado do navegador — que está em outro
    fuso do que São Paulo com frequência maior do que se imagina.
    """
    saida: dict[str, list[dict]] = {}
    for slot in await slots_livres(db):
        dia = slot.inicio.strftime("%Y-%m-%d")
        saida.setdefault(dia, []).append({
            "id": slot.id,
            "hora": slot.inicio.strftime("%H:%M"),
            "fim": slot.fim.strftime("%H:%M"),
        })
    return saida


def agora() -> datetime:
    """Reexportado para os testes não precisarem importar `horarios` só por isto."""
    return agora_sp()
