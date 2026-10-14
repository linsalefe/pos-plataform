"""Folga de 30 min em volta de toda ocupação na oferta de horários (14/10/2026).

    cd backend && venv/bin/python test_folga_agenda.py

Escrito e NÃO executado na sprint de 14/10. Offline: a Exact é mockada, o banco é dublê.

O QUE ESTE TESTE PROVA
  1. bloco 12:00–13:30 com folga 30 derruba 11:30–12:15 (já derrubava), 11:15–12:00 e
     13:30–14:15 (os dois novos); 10:45–11:30 e 14:15–15:00 sobrevivem (encostam na folga)
  2. com AGENDAMENTO_FOLGA_MIN=0 volta o comportamento antigo: 11:15 e 13:30 reaparecem
  3. agendamento NOSSO (não só box da Exact) também ganha folga
  4. env inválido ou negativo cai no padrão de 30
  5. consultoras.json de produção: duas janelas por dia (almoço 12:00–13:30) nas duas
"""
import asyncio
import json
import os
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.agendamento import client, consultoras as equipe_mod, disponibilidade
from app.agendamento.horarios import para_exact

# Hermético ao .env do servidor (ver o mesmo bloco em test_agendamento.py).
for _v in ("AGENDAMENTO_CONSULTORAS", "AGENDAMENTO_CONSULTORAS_PATH",
           "AGENDAMENTO_GRADE_JSON", "AGENDAMENTO_GRADE_PATH",
           "AGENDAMENTO_JANELA_DIAS", "AGENDAMENTO_FOLGA_MIN"):
    os.environ.pop(_v, None)

falhas = []

# Quarta 14/10/2026 às 07:00: antecedência de 2h deixa o dia inteiro a partir das 09:00.
AGORA = datetime(2026, 10, 14, 7, 0)
DIA = AGORA.date()

# Duas grades de passo 45 que, juntas, têm os quatro slots do enunciado:
#   Ana 09:00–18:30 -> ... 10:30 11:15 12:00 12:45 13:30 14:15 ...
#   Bia 10:00–19:00 -> ... 10:45 11:30 12:15 13:00 13:45 14:30 ...
EQUIPE = json.dumps([
    {"email": "ana@cenatcursos.com.br", "nome_exibicao": "Ana",
     "grade": {"janelas": {"2": [["09:00", "18:30"]]}}},
    {"email": "bia@cenatcursos.com.br", "nome_exibicao": "Bia",
     "grade": {"janelas": {"2": [["10:00", "19:00"]]}}},
])

BLOCO = [{"start": para_exact(datetime.combine(DIA, datetime.min.time()).replace(hour=12)),
          "end": para_exact(datetime.combine(DIA, datetime.min.time()).replace(hour=13,
                                                                               minute=30))}]


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


class _Db:
    """Dublê de AsyncSession: responde `_ocupados_por_nos` com as linhas dadas."""

    def __init__(self, linhas=()):
        self.linhas = list(linhas)

    async def execute(self, *a, **k):
        res = MagicMock()
        res.all.return_value = self.linhas
        return res


async def _livres(boxes, db=None) -> dict[str, set[str]]:
    """{"HH:MM": {nomes}} do dia DIA."""
    os.environ["AGENDAMENTO_CONSULTORAS"] = EQUIPE
    equipe_mod.recarregar()
    disponibilidade.invalidar_cache()
    with patch("app.agendamento.grade.agora_sp", return_value=AGORA), \
         patch.object(client, "listar_boxes", AsyncMock(return_value=boxes)):
        livres = await disponibilidade.slots_livres(db or _Db(), usar_cache=False)
    saida: dict[str, set[str]] = {}
    for d in livres:
        if d.slot.inicio.date() == DIA:
            saida[d.slot.inicio.strftime("%H:%M")] = {c.nome_exibicao for c in d.consultoras}
    return saida


async def main():
    try:
        # ==================================================================================
        print("\n1. bloco 12:00–13:30, folga padrão (30)")
        os.environ.pop("AGENDAMENTO_FOLGA_MIN", None)
        h = await _livres(BLOCO)
        checa("11:30–12:15 cai (já caía)", "11:30" in h, False)
        checa("11:15–12:00 cai (novo)", "11:15" in h, False)
        checa("13:30–14:15 cai (novo)", "13:30" in h, False)
        checa("12:15, 12:45, 13:00 caem", {"12:15", "12:45", "13:00"} & set(h), set())
        checa("13:45–14:30 cai (termina dentro da folga)", "13:45" in h, False)
        checa("10:45–11:30 sobrevive (encosta em 11:30)", h.get("10:45"), {"Bia"})
        checa("14:15–15:00 sobrevive (começa depois de 14:00)", h.get("14:15"), {"Ana"})
        checa("10:30 e 14:30 sobrevivem", ("10:30" in h, "14:30" in h), (True, True))

        # ==================================================================================
        print("\n2. AGENDAMENTO_FOLGA_MIN=0 volta ao comportamento antigo")
        os.environ["AGENDAMENTO_FOLGA_MIN"] = "0"
        h = await _livres(BLOCO)
        checa("11:15 reaparece (termina 12:00, encosta)", h.get("11:15"), {"Ana"})
        checa("13:30 reaparece (começa 13:30, encosta)", h.get("13:30"), {"Ana"})
        checa("11:30 continua caindo (sobrepõe de verdade)", "11:30" in h, False)

        # ==================================================================================
        print("\n3. agendamento nosso também ganha folga")
        os.environ.pop("AGENDAMENTO_FOLGA_MIN", None)
        nosso = [(datetime.combine(DIA, datetime.min.time()).replace(hour=15),
                  datetime.combine(DIA, datetime.min.time()).replace(hour=15, minute=45))]
        h = await _livres([], db=_Db(nosso))
        # 15:00–15:45 + folga = 14:30–16:15. Ana: 14:15–15:00 e 15:45–16:30 caem; 16:30 fica.
        checa("14:15 cai", "14:15" in h, False)
        checa("15:45 cai", "15:45" in h, False)
        checa("13:30–14:15 fica (termina antes de 14:30)", "13:30" in h, True)
        checa("16:30 fica", "16:30" in h, True)

        # ==================================================================================
        print("\n4. env inválido cai no padrão")
        for bruto in ("abc", "-5", ""):
            os.environ["AGENDAMENTO_FOLGA_MIN"] = bruto
            checa(f"AGENDAMENTO_FOLGA_MIN={bruto!r} -> 30 min",
                  disponibilidade.folga(), timedelta(minutes=30))
        os.environ["AGENDAMENTO_FOLGA_MIN"] = "15"
        checa("AGENDAMENTO_FOLGA_MIN='15' -> 15 min", disponibilidade.folga(),
              timedelta(minutes=15))
        os.environ.pop("AGENDAMENTO_FOLGA_MIN", None)
        checa("sem env -> 30 min", disponibilidade.folga(), timedelta(minutes=30))
    finally:
        os.environ.pop("AGENDAMENTO_CONSULTORAS", None)
        os.environ.pop("AGENDAMENTO_FOLGA_MIN", None)
        equipe_mod.recarregar()
        disponibilidade.invalidar_cache()

    # ======================================================================================
    print("\n5. consultoras.json de produção: almoço 12:00–13:30 nas duas")
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "consultoras.json")
    os.environ["AGENDAMENTO_CONSULTORAS_PATH"] = caminho
    try:
        equipe = equipe_mod.recarregar()
        checa("duas consultoras", len(equipe), 2)
        for c in equipe:
            horas = [s.inicio.strftime("%H:%M") for s in c.grade.slots_do_dia(date(2026, 10, 15))]
            checa(f"{c.nome_exibicao}: grade de quinta", horas,
                  ["10:00", "10:45", "13:30", "14:15", "15:00", "15:45", "16:30", "17:15",
                   "18:00"])
            checa(f"{c.nome_exibicao}: nada no sábado",
                  c.grade.slots_do_dia(date(2026, 10, 17)), [])
    finally:
        os.environ.pop("AGENDAMENTO_CONSULTORAS_PATH", None)
        equipe_mod.recarregar()

    print(f"\n{'TUDO OK' if not falhas else f'{len(falhas)} FALHA(S): {falhas}'}")
    raise SystemExit(1 if falhas else 0)


if __name__ == "__main__":
    asyncio.run(main())
