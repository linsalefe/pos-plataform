"""Fronteira de fuso do módulo de agendamento. É o ÚNICO lugar que formata data para a Exact.

------------------------------------------------------------------------------------------
POR QUE ESTE ARQUIVO EXISTE SOZINHO
------------------------------------------------------------------------------------------
A Exact grava `start`/`end` de box como HORA DE PAREDE e devolve o valor verbatim, com um
sufixo `Z` que é decorativo. Medido em 17/08/2026 (AGENDAMENTO_FINDINGS.md §1): enviei
`2026-08-19T11:00:00Z`, o `GET /Boxes` devolveu `2026-08-19T11:00:00Z`, e o `GET /Meetings`
devolveu o MESMO horário sem `Z` (`2026-08-19T11:00:00.0000000`).

Converter para UTC de verdade (`astimezone(timezone.utc)`) agenda a reunião 3 horas adiantada
DENTRO do CRM, sem erro nenhum em lugar nenhum. É o tipo de bug que só aparece quando o lead
não atende a ligação — três semanas depois, sem rastro.

Por isso a formatação vive num arquivo só, e nada mais no módulo chama `strftime`.

------------------------------------------------------------------------------------------
O QUE NÃO PASSA POR AQUI
------------------------------------------------------------------------------------------
`registerDate` e `updateDate` de lead são UTC DE VERDADE (o lead criado 15:34 SP voltou como
`18:34:22Z`). Não são o mesmo padrão. `para_exact` serve para `start`/`end` de box e para o
`$filter` de período — nada além disso.
"""
from datetime import datetime, timedelta, timezone

# Mesmo valor de nat_guard.SP_TZ e main.SP_TZ. Repetido aqui de propósito: importar
# nat_guard traria junto o guard da NAT (e o send_template_message da cadeia dele) para
# dentro de um módulo que não tem nada com WhatsApp.
SP_TZ = timezone(timedelta(hours=-3))


def agora_sp() -> datetime:
    """Naive em horário de São Paulo — igual a `nat_guard._agora_sp` e a `messages.timestamp`.

    O banco está em Etc/UTC. Comparar contra `now()` do Postgres deixaria toda janela 3h
    adiantada, em silêncio.
    """
    return datetime.now(SP_TZ).replace(tzinfo=None)


def para_exact(dt: datetime) -> str:
    """Hora de parede de SP com `Z` decorativo. NÃO converte para UTC.

    O `Z` é mentira e é proposital — ver o cabeçalho deste arquivo. Se algum dia um teste
    aqui falhar afirmando que "deveria ser UTC", a resposta é: não deveria. Leia
    AGENDAMENTO_FINDINGS.md §1 antes de "corrigir".

    Aceita naive (assumido JÁ em SP, que é como o resto do projeto grava) ou aware
    (convertido para SP antes de formatar).
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(SP_TZ)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def de_exact(valor: str) -> datetime:
    """`2027-03-10T11:00:00Z` -> datetime NAIVE 11:00. Descarta o `Z` sem converter nada.

    Simétrica de `para_exact`. Tolera o formato de `/Meetings`, que vem sem `Z` e com 7 casas
    de fração (`2027-03-10T11:00:00.0000000`).
    """
    texto = valor.strip()
    if texto.endswith("Z"):
        texto = texto[:-1]
    if "." in texto:
        texto = texto.split(".", 1)[0]
    return datetime.fromisoformat(texto)
