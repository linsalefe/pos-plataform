"""A grade de horários oferecidos na LP. Fonte da verdade NOSSA — não consulta a Exact.

------------------------------------------------------------------------------------------
POR QUE A GRADE É NOSSA
------------------------------------------------------------------------------------------
`scheduleAdd` só aceita box com `status: "available"` (AGENDAMENTO_FINDINGS.md §8, provado em
experimento controlado). Os blocos da agenda dos consultores são `busy` com `leadId: 0` — a
API os recusa. Em toda a base da Exact existem 4 boxes `available`, e os quatro estão no
passado.

Ou seja: **não existem slots da Exact para listar**. Quem define os horários somos nós, e o
módulo cria o próprio box na hora de agendar.

------------------------------------------------------------------------------------------
POR QUE A GRADE PRECISA CABER NAS LACUNAS
------------------------------------------------------------------------------------------
`BoxesAdd` recusa QUALQUER interseção com box existente do mesmo consultor, independente do
status (§2). Os blocos recorrentes de `comercial@cenatcursos.com.br` observados em agosto/2026:

    seg–qui   09:00–10:10 · 13:30–14:30 · 15:00–15:45
    sex       08:00–09:10 · 13:30–14:30 · 15:00–15:45 · 18:00–19:00

A grade padrão abaixo (10:15–13:25 e 16:00–18:00) vive nas lacunas disso. Quando a consultora
mexer na agenda dela, a grade desencosta da realidade e o agendamento começa a falhar com
`Boxes are occupied` — por isso ela é CONFIGURAÇÃO, não constante de código, e por isso
`disponibilidade.py` subtrai o que a Exact reporta antes de oferecer qualquer coisa.

------------------------------------------------------------------------------------------
COMO CONFIGURAR
------------------------------------------------------------------------------------------
Duas formas, nesta ordem de precedência:

    AGENDAMENTO_GRADE_JSON='{"duracao_min": 30, ...}'   # JSON inline
    AGENDAMENTO_GRADE_PATH=/etc/cenat/grade.json        # caminho de arquivo

Sem nenhuma das duas, vale GRADE_PADRAO. Um JSON inválido NÃO derruba o processo: cai no
padrão e grita no log. Derrubar o backend inteiro por causa de uma vírgula num env seria pior
que servir a grade padrão.

O JSON aceita chaves parciais — o que não vier é herdado de GRADE_PADRAO.
"""
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.agendamento.horarios import agora_sp

# Dias da semana no padrão de `date.weekday()`: 0 = segunda ... 6 = domingo.
GRADE_PADRAO = {
    "sales_rep_email": "comercial@cenatcursos.com.br",
    "duracao_min": 45,
    "antecedencia_min_horas": 2,
    "horizonte_dias": 14,
    "type_meeting": "web",
    "janelas": {
        "0": [["10:15", "13:25"], ["16:00", "18:00"]],
        "1": [["10:15", "13:25"], ["16:00", "18:00"]],
        "2": [["10:15", "13:25"], ["16:00", "18:00"]],
        "3": [["10:15", "13:25"], ["16:00", "18:00"]],
        "4": [["10:15", "13:25"], ["16:00", "18:00"]],
    },
}


@dataclass(frozen=True)
class Slot:
    """Um horário oferecível. `inicio`/`fim` são naive em SP."""
    inicio: datetime
    fim: datetime

    @property
    def id(self) -> str:
        """Identificador estável que vai e volta da LP: `2026-08-19T11:00:00`.

        É o `inicio` em ISO sem fuso. Não usa o `Z` de `para_exact` de propósito — este id é
        contrato NOSSO com o front, e misturar o `Z` decorativo da Exact aqui só convidaria
        alguém a passá-lo adiante sem pensar.
        """
        return self.inicio.strftime("%Y-%m-%dT%H:%M:%S")


class Grade:
    """Grade carregada. Imutável depois de construída."""

    def __init__(self, cfg: dict):
        self.sales_rep_email: str = cfg["sales_rep_email"]
        self.duracao = timedelta(minutes=int(cfg["duracao_min"]))
        self.antecedencia = timedelta(hours=float(cfg["antecedencia_min_horas"]))
        self.horizonte_dias = int(cfg["horizonte_dias"])
        self.type_meeting: str = cfg.get("type_meeting", "web")
        self.janelas: dict[int, list[tuple[time, time]]] = {}
        for dia, faixas in cfg["janelas"].items():
            self.janelas[int(dia)] = [
                (time.fromisoformat(ini), time.fromisoformat(fim)) for ini, fim in faixas
            ]

    def slots_do_dia(self, dia: date) -> list[Slot]:
        """Todos os slots teóricos do dia, sem olhar ocupação nem antecedência."""
        saida: list[Slot] = []
        for faixa_ini, faixa_fim in self.janelas.get(dia.weekday(), []):
            cursor = datetime.combine(dia, faixa_ini)
            limite = datetime.combine(dia, faixa_fim)
            # `<=` no limite: um slot que TERMINA exatamente no fim da faixa cabe. Com 45 min
            # em 10:15–13:25 isso dá 4 slots (o último 12:30–13:15); 13:15–14:00 estouraria.
            while cursor + self.duracao <= limite:
                saida.append(Slot(inicio=cursor, fim=cursor + self.duracao))
                cursor += self.duracao
        return saida

    def slots_candidatos(self, *, agora: datetime | None = None) -> list[Slot]:
        """Slots do horizonte que respeitam a antecedência mínima. Ainda SEM subtrair ocupação.

        É o insumo de `disponibilidade.slots_livres`, que faz a subtração. Separado porque a
        regra de tempo (antecedência, horizonte) é da grade, e a de ocupação é da Exact.
        """
        agora = agora or agora_sp()
        corte = agora + self.antecedencia
        saida: list[Slot] = []
        # `range(horizonte_dias + 1)`: hoje conta como dia 0, senão o horizonte de 14 dias
        # ofereceria 13 dias cheios mais o resto de hoje.
        for offset in range(self.horizonte_dias + 1):
            for slot in self.slots_do_dia(agora.date() + timedelta(days=offset)):
                if slot.inicio >= corte:
                    saida.append(slot)
        return saida

    def slot_por_id(self, slot_id: str) -> Slot | None:
        """Resolve o id vindo da LP contra a grade. `None` se não for um slot que oferecemos.

        Isto é VALIDAÇÃO DE ENTRADA, não conveniência: sem passar pela grade, um POST forjado
        agendaria 03:00 de domingo, ou um slot de 8 horas, e o `BoxesAdd` aceitaria numa boa
        (a Exact não conhece a nossa grade). A checagem de antecedência entra junto — um id
        válido mas vencido também é recusado.
        """
        try:
            inicio = datetime.fromisoformat(slot_id)
        except ValueError:
            return None
        for slot in self.slots_candidatos():
            if slot.inicio == inicio:
                return slot
        return None


def _carregar_cfg() -> dict:
    cfg = dict(GRADE_PADRAO)
    bruto = os.getenv("AGENDAMENTO_GRADE_JSON")
    origem = "AGENDAMENTO_GRADE_JSON"
    if not bruto:
        caminho = os.getenv("AGENDAMENTO_GRADE_PATH")
        origem = f"AGENDAMENTO_GRADE_PATH={caminho}"
        if caminho:
            try:
                with open(caminho, encoding="utf-8") as fh:
                    bruto = fh.read()
            except OSError as e:
                print(f"⚠️ agendamento: não consegui ler {caminho} ({e}). Usando grade padrão.")
                return cfg
    if not bruto:
        return cfg
    try:
        cfg.update(json.loads(bruto))
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        # Não propaga: grade inválida num env não pode derrubar o backend inteiro, que serve
        # o Hub e o webhook da Meta. Cai no padrão e deixa rastro.
        print(f"⚠️ agendamento: {origem} inválido ({e}). Usando grade padrão.")
    return cfg


_grade: Grade | None = None


def grade() -> Grade:
    """Singleton preguiçoso. Recarregar exige restart — é config de infra, não de tela."""
    global _grade
    if _grade is None:
        _grade = Grade(_carregar_cfg())
    return _grade


def recarregar() -> Grade:
    """Só para os testes, que precisam trocar a grade sem reiniciar o processo."""
    global _grade
    _grade = None
    return grade()
