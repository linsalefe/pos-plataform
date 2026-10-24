"""Blocos ocupados do Google Agenda das consultoras (livre/ocupado), para a grade de horários.

------------------------------------------------------------------------------------------
POR QUE EXISTE
------------------------------------------------------------------------------------------
MEDIDO em 24/10/2026 (RECON_4_PEDIDOS_COMERCIAL_20261024_REPORT.md §1): de 26 a 28/10 o Hub
oferecia 27 pares horário/consultora e 6 deles (22%) estavam ocupados no Google. A Exact só
tinha bloqueios do PRÓXIMO dia útil, copiados à mão na véspera (os de 26/10 nasceram na sexta
23/10 entre 10:49 e 15:56); D+2 e D+3 ficavam sem bloqueio nenhum. As 15 reuniões Vigentes
desses dias, inclusive as 2 marcadas pela SDR direto na Exact, aparecem ocupadas no Google:
ler o Google cobre as duas origens.

------------------------------------------------------------------------------------------
SÓ LIVRE/OCUPADO, DE PROPÓSITO
------------------------------------------------------------------------------------------
A conta de serviço `nat-ia-calendar@...` tem `accessRole = freeBusyReader` nos dois
calendários: o Workspace do CENAT não deixa conta externa ver título. `freebusy.query` basta:
a grade é o expediente de `consultoras.json` menos tudo que o Google diz ocupado. Nada de
regra de título, nada de `events.list`.

------------------------------------------------------------------------------------------
UMA CONSULTA, FORA DO EVENT LOOP, E FALHA FECHADA
------------------------------------------------------------------------------------------
  * Uma `freebusy.query` com todos os calendários em `items`. O cache de 60 s é o de
    `disponibilidade.slots_livres`: uma chamada não cacheada de lá = uma consulta aqui.
  * O cliente do Google é síncrono (httplib2): roda em `asyncio.to_thread`, com timeout de
    5 s no socket e um `wait_for` de cinto e suspensório. Sem isso, um Google lento
    congelaria a LP inteira.
  * Erro geral (rede, 403, timeout) ou erro de um calendário (`notFound`, sem permissão)
    vira `GoogleIndisponivel` para aquela consultora, e ela sai da rodada (decisão do Álefe,
    24/10): nunca oferecer horário no escuro.

------------------------------------------------------------------------------------------
AS DUAS CHAVES, LIDAS A CADA CHAMADA
------------------------------------------------------------------------------------------
  GOOGLE_GRADE_ENABLED   false (padrão) = o Google nem é consultado; grade idêntica à antiga.
  GOOGLE_GRADE_LOG_ONLY  true (padrão) = consulta e loga o que sairia, mas serve a antiga.

A grade só passa a obedecer o Google com ENABLED=true e LOG_ONLY=false (`ativo()`).
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

FUSO_SP = ZoneInfo("America/Sao_Paulo")
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "..", "..",
                                "google-credentials.json")
TIMEOUT_SEGUNDOS = 5


class GoogleIndisponivel(Exception):
    """Não deu para ler o livre/ocupado de uma consultora. Ela sai da rodada."""


def _flag(nome: str, padrao: bool) -> bool:
    bruto = os.getenv(nome)
    if bruto is None or not bruto.strip():
        return padrao
    return bruto.strip().lower() in ("1", "true", "sim", "yes", "on")


def habilitado() -> bool:
    return _flag("GOOGLE_GRADE_ENABLED", False)


def so_log() -> bool:
    return _flag("GOOGLE_GRADE_LOG_ONLY", True)


def ativo() -> bool:
    """O Google decide a grade de verdade (e não só aparece no log de comparação)."""
    return habilitado() and not so_log()


_service = None


def _servico():
    """Cliente do Calendar, criado uma vez. Credencial em `backend/google-credentials.json`."""
    global _service
    if _service is None:
        import httplib2
        from google.oauth2 import service_account
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build
        cred = service_account.Credentials.from_service_account_file(
            CREDENTIALS_PATH, scopes=SCOPES)
        http = AuthorizedHttp(cred, http=httplib2.Http(timeout=TIMEOUT_SEGUNDOS))
        _service = build("calendar", "v3", http=http, cache_discovery=False)
    return _service


def _rfc3339(dt: datetime) -> str:
    """Naive SP -> `2026-10-27T13:30:00-03:00`."""
    return dt.replace(tzinfo=FUSO_SP).isoformat()


def para_sp(bruto: str) -> datetime:
    """`2026-10-27T16:30:00Z` ou `...-03:00` -> naive SP.

    Python 3.10 não lê o `Z` em `fromisoformat`, e o Google devolve `Z` no freebusy mesmo com
    `timeZone` no corpo. Sem offset nenhum, a hora é tratada como SP.
    """
    texto = bruto.strip()
    if texto.endswith("Z"):
        texto = texto[:-1] + "+00:00"
    dt = datetime.fromisoformat(texto)
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(FUSO_SP).replace(tzinfo=None)


def _consultar(ids: list[str], inicio: datetime, fim: datetime) -> dict:
    corpo = {"timeMin": _rfc3339(inicio), "timeMax": _rfc3339(fim),
             "timeZone": "America/Sao_Paulo", "items": [{"id": i} for i in ids]}
    return _servico().freebusy().query(body=corpo).execute()


def _interpretar(resposta: dict, ids: list[str]) -> dict:
    """{id: [(ini, fim)]} ou {id: GoogleIndisponivel} para cada id pedido."""
    calendarios = resposta.get("calendars") or {}
    saida: dict = {}
    for cid in ids:
        cal = calendarios.get(cid)
        if cal is None:
            saida[cid] = GoogleIndisponivel(f"{cid}: ausente na resposta")
            continue
        if cal.get("errors"):
            motivos = ",".join(str(e.get("reason")) for e in cal["errors"])
            saida[cid] = GoogleIndisponivel(f"{cid}: {motivos}")
            continue
        blocos = []
        try:
            for b in cal.get("busy") or []:
                blocos.append((para_sp(b["start"]), para_sp(b["end"])))
        except (KeyError, TypeError, ValueError) as e:
            # Um bloco ilegível não é "livre": a consultora sai, em vez de ganhar um horário
            # que pode estar ocupado.
            saida[cid] = GoogleIndisponivel(f"{cid}: bloco ilegível ({e})")
            continue
        saida[cid] = blocos
    return saida


async def ocupados_google(ids: list[str], inicio: datetime,
                          fim: datetime) -> dict:
    """Blocos ocupados por calendário, em naive SP, entre `inicio` e `fim` (naive SP).

    Devolve `{id: [(ini, fim), ...]}`, e `{id: GoogleIndisponivel(...)}` para o calendário que
    não deu para ler. NUNCA levanta: falha geral marca todos os ids como indisponíveis.
    """
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    t0 = asyncio.get_running_loop().time()
    try:
        resposta = await asyncio.wait_for(
            asyncio.to_thread(_consultar, ids, inicio, fim), timeout=TIMEOUT_SEGUNDOS + 1)
    except Exception as e:
        motivo = f"{type(e).__name__}: {e}"[:300]
        print(f"❌ google_ocupado: freebusy falhou para {', '.join(ids)} ({motivo})")
        return {cid: GoogleIndisponivel(motivo) for cid in ids}
    ms = int((asyncio.get_running_loop().time() - t0) * 1000)
    saida = _interpretar(resposta, ids)
    for cid, v in saida.items():
        if isinstance(v, GoogleIndisponivel):
            print(f"❌ google_ocupado: {v}")
    print(f"🗓️ google_ocupado: freebusy {len(ids)} calendário(s) "
          f"{inicio:%d/%m %H:%M}–{fim:%d/%m %H:%M} em {ms} ms")
    return saida
