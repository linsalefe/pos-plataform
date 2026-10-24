"""A grade subtrai o livre/ocupado do Google Agenda das consultoras (24/10/2026).

    cd backend && venv/bin/python test_google_ocupado.py

Escrito e NÃO executado na sprint de 24/10. Offline: o Google e a Exact são mockados, o banco
é dublê. Nenhuma consulta real.

O QUE ESTE TESTE PROVA
  1. bloco 13:30–14:30 derruba 13:30 e, pela folga de 15, 14:15; 15:00 sobrevive
  2. bloco 09:00–10:40 derruba 10:00 e 10:45
  3. bloco de dia inteiro derruba o dia
  4. Google 403 numa consultora: ela some da rodada e a outra segue
  5. GOOGLE_GRADE_ENABLED=false: grade idêntica à de antes e o Google nem é consultado
  6. GOOGLE_GRADE_LOG_ONLY=true: serve a grade antiga e loga o que sairia
     (com o Google ativo, o caso 1 confere o log `tirados=`)
  7. cache: duas chamadas em 60 s fazem UMA consulta ao Google, com as duas consultoras
  8. fuso: `-03:00` e `Z` viram a mesma hora de parede de SP
  9. resposta com `errors` num calendário vira GoogleIndisponivel só dele
 10. timeout do Google: todos indisponíveis, nada levanta
 11. agendar: filtrar_pelo_google tira quem está ocupada no Google (e não age desligado)
"""
import asyncio
import io
import json
import os
import time
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.agendamento import client, consultoras as equipe_mod, disponibilidade
from app.agendamento import google_ocupado

for _v in ("AGENDAMENTO_CONSULTORAS", "AGENDAMENTO_CONSULTORAS_PATH",
           "AGENDAMENTO_GRADE_JSON", "AGENDAMENTO_GRADE_PATH",
           "AGENDAMENTO_JANELA_DIAS", "GOOGLE_GRADE_ENABLED", "GOOGLE_GRADE_LOG_ONLY"):
    os.environ.pop(_v, None)
os.environ["AGENDAMENTO_FOLGA_MIN"] = "15"

falhas = []

# Quarta 14/10/2026 às 07:00: com antecedência de 2h o dia inteiro está aberto.
AGORA = datetime(2026, 10, 14, 7, 0)
DIA = AGORA.date()
JANELAS = {"2": [["10:00", "12:00"], ["13:30", "19:00"]]}
ANA, BIA = "ana@cenatcursos.com.br", "bia@cenatcursos.com.br"
EQUIPE = json.dumps([
    {"email": ANA, "nome_exibicao": "Ana", "google_calendar_id": ANA,
     "grade": {"janelas": JANELAS}},
    {"email": BIA, "nome_exibicao": "Bia", "google_calendar_id": BIA,
     "grade": {"janelas": JANELAS}},
])
TODOS = ["10:00", "10:45", "13:30", "14:15", "15:00", "15:45", "16:30", "17:15", "18:00"]


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


class _Db:
    async def execute(self, *a, **k):
        res = MagicMock()
        res.all.return_value = []
        return res


def _h(hh_mm: str, dia=DIA) -> datetime:
    h, m = map(int, hh_mm.split(":"))
    return datetime.combine(dia, datetime.min.time()).replace(hour=h, minute=m)


def _flags(enabled: bool, log_only: bool):
    os.environ["GOOGLE_GRADE_ENABLED"] = "true" if enabled else "false"
    os.environ["GOOGLE_GRADE_LOG_ONLY"] = "true" if log_only else "false"


async def _livres(google: dict | None, *, usar_cache=False, consulta=None):
    """({email: [HH:MM do DIA]}, mock do Google, log)."""
    os.environ["AGENDAMENTO_CONSULTORAS"] = EQUIPE
    equipe_mod.recarregar()
    if not usar_cache:
        disponibilidade.invalidar_cache()
    disponibilidade._ultima_comparacao = None
    consulta = consulta or AsyncMock(return_value=google or {})
    saida = io.StringIO()
    with patch("app.agendamento.grade.agora_sp", return_value=AGORA), \
         patch.object(client, "listar_boxes", AsyncMock(return_value=[])), \
         patch("app.remarcacao.ocupados_pendentes", AsyncMock(return_value=[])), \
         patch.object(google_ocupado, "ocupados_google", consulta), \
         redirect_stdout(saida):
        livres = await disponibilidade.slots_livres(_Db(), usar_cache=usar_cache)
    por: dict[str, list[str]] = {ANA: [], BIA: []}
    for d in livres:
        if d.slot.inicio.date() != DIA:
            continue
        for c in d.consultoras:
            por[c.email].append(d.slot.inicio.strftime("%H:%M"))
    return por, consulta, saida.getvalue()


# ==========================================================================================

async def caso_1_almoco_da_amorim():
    _flags(True, False)
    por, _, log = await _livres({ANA: [(_h("13:30"), _h("14:30"))], BIA: []})
    checa("ativo: log dos tirados", f"consultora={ANA} tirados=['13:30', '14:15']" in log, True)
    checa("Ana perde 13:30 e 14:15 (folga)", por[ANA],
          [h for h in TODOS if h not in ("13:30", "14:15")])
    checa("Bia intacta", por[BIA], TODOS)


async def caso_2_manha():
    _flags(True, False)
    por, _, _ = await _livres({ANA: [(_h("09:00"), _h("10:40"))], BIA: []})
    checa("Ana perde 10:00 e 10:45", por[ANA], [h for h in TODOS if h not in ("10:00", "10:45")])


async def caso_3_dia_inteiro():
    _flags(True, False)
    por, _, _ = await _livres({ANA: [(_h("00:00"), _h("00:00") + timedelta(days=1))], BIA: []})
    checa("Ana sem nada no dia", por[ANA], [])
    checa("Bia intacta", por[BIA], TODOS)


async def caso_4_403():
    _flags(True, False)
    por, _, log = await _livres({ANA: google_ocupado.GoogleIndisponivel(f"{ANA}: forbidden"),
                                 BIA: []})
    checa("Ana fora da rodada", por[ANA], [])
    checa("Bia segue", por[BIA], TODOS)
    checa("log diz quem saiu", "Google de ana@cenatcursos.com.br ilegível" in log, True)


async def caso_5_desligado():
    _flags(False, True)
    por, consulta, _ = await _livres({ANA: [(_h("13:30"), _h("14:30"))]})
    checa("desligado: Ana com tudo", por[ANA], TODOS)
    checa("desligado: Google não consultado", consulta.await_count, 0)


async def caso_6_so_log():
    _flags(True, True)
    por, consulta, log = await _livres({ANA: [(_h("13:30"), _h("14:30"))], BIA: []})
    checa("log only: serve a antiga", por[ANA], TODOS)
    checa("log only: consultou", consulta.await_count, 1)
    linha = f"📊 google_grade dia={DIA:%Y-%m-%d} consultora={ANA} sairiam=['13:30', '14:15']"
    checa("log only: diferença no log", linha in log, True)


async def caso_7_cache():
    _flags(True, False)
    consulta = AsyncMock(return_value={ANA: [], BIA: []})
    disponibilidade.invalidar_cache()
    await _livres(None, usar_cache=True, consulta=consulta)
    await _livres(None, usar_cache=True, consulta=consulta)
    checa("uma consulta em 60 s", consulta.await_count, 1)
    ids = consulta.await_args.args[0]
    checa("as duas consultoras numa consulta", sorted(ids), sorted([ANA, BIA]))
    disponibilidade.invalidar_cache()
    await _livres(None, usar_cache=True, consulta=consulta)
    checa("invalidar_cache força nova consulta", consulta.await_count, 2)


async def caso_8_fuso():
    checa("-03:00", google_ocupado.para_sp("2026-10-27T13:30:00-03:00"),
          datetime(2026, 10, 27, 13, 30))
    checa("Z", google_ocupado.para_sp("2026-10-27T16:30:00Z"),
          datetime(2026, 10, 27, 13, 30))
    checa("naive fica", google_ocupado.para_sp("2026-10-27T13:30:00"),
          datetime(2026, 10, 27, 13, 30))


async def caso_9_errors():
    resp = {"calendars": {ANA: {"errors": [{"domain": "global", "reason": "notFound"}]},
                          BIA: {"busy": [{"start": "2026-10-14T16:30:00Z",
                                          "end": "2026-10-14T17:30:00Z"}]}}}
    r = google_ocupado._interpretar(resp, [ANA, BIA])
    checa("Ana indisponível", isinstance(r[ANA], google_ocupado.GoogleIndisponivel), True)
    checa("Bia lida em SP", r[BIA], [(_h("13:30"), _h("14:30"))])


async def caso_10_timeout():
    def lento(*a, **k):
        time.sleep(0.5)
        return {}
    with patch.object(google_ocupado, "_consultar", lento), \
         patch.object(google_ocupado, "TIMEOUT_SEGUNDOS", -0.9), \
         redirect_stdout(io.StringIO()):
        r = await google_ocupado.ocupados_google([ANA, BIA], _h("10:00"), _h("19:00"))
    checa("timeout: todos indisponíveis",
          all(isinstance(v, google_ocupado.GoogleIndisponivel) for v in r.values()), True)
    checa("timeout: os dois ids", sorted(r), sorted([ANA, BIA]))


async def caso_11_filtro_do_agendar():
    os.environ["AGENDAMENTO_CONSULTORAS"] = EQUIPE
    equipe_mod.recarregar()
    equipe = equipe_mod.consultoras()
    with patch("app.agendamento.grade.agora_sp", return_value=AGORA):
        slot = equipe[0].grade.slot_por_id(f"{DIA:%Y-%m-%d}T13:30:00")
    google = AsyncMock(return_value={ANA: [(_h("13:30"), _h("14:30"))], BIA: []})
    _flags(True, False)
    with patch.object(google_ocupado, "ocupados_google", google), redirect_stdout(io.StringIO()):
        ficam = await disponibilidade.filtrar_pelo_google(slot, list(equipe))
    checa("só a Bia disputa 13:30", [c.email for c in ficam], [BIA])
    _flags(True, True)
    with patch.object(google_ocupado, "ocupados_google", google):
        ficam = await disponibilidade.filtrar_pelo_google(slot, list(equipe))
    checa("log only: filtro não age", [c.email for c in ficam], [ANA, BIA])


async def main():
    print("\nGrade com o Google Agenda: Google e Exact mockados, banco dublê\n")
    for caso in (caso_1_almoco_da_amorim, caso_2_manha, caso_3_dia_inteiro, caso_4_403,
                 caso_5_desligado, caso_6_so_log, caso_7_cache, caso_8_fuso, caso_9_errors,
                 caso_10_timeout, caso_11_filtro_do_agendar):
        print(caso.__name__)
        await caso()
    os.environ.pop("AGENDAMENTO_CONSULTORAS", None)
    equipe_mod.recarregar()
    if falhas:
        print(f"\nFALHOU: {len(falhas)} verificação(ões): {falhas}\n")
        raise SystemExit(1)
    print("\nOK: todos os casos passaram. Nenhuma consulta real ao Google.\n")


if __name__ == "__main__":
    asyncio.run(main())
