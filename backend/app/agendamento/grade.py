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
A GRADE OFERECE O COMERCIAL INTEIRO — QUEM RECORTA OS BLOCOS É A SUBTRAÇÃO AO VIVO
------------------------------------------------------------------------------------------
Até 25/08/2026 a grade era desenhada **à mão para caber nas lacunas** dos blocos recorrentes
das consultoras (`10:30–12:00` + `15:45–18:00`, cinco horários/dia). O motivo era real:
`BoxesAdd` recusa QUALQUER interseção com box existente do mesmo consultor, independente do
status (§2), e bloco recorrente não é agendável (§8).

Isso continua verdade — mudou quem resolve. A grade passou a ser o **horário comercial
inteiro** (seg–sex 09:00–18:30, 45 min), e a colisão com bloco é removida por consultora, ao
vivo, em `disponibilidade.slots_livres`. Duas razões:

  * **Uma janela desenhada à mão é uma foto.** Ela envelhece na primeira vez que a consultora
    mexe na agenda, e envelhece **em silêncio** — começa a colidir e o agendamento falha com
    `Boxes are occupied`. A subtração ao vivo não tem esse problema.
  * **Com duas agendas diferentes, a interseção das lacunas é pequena.** Recortar à mão o que
    serve para as duas custava capacidade: 25 horários/semana na união contra 59 do comercial
    inteiro, medido contra os blocos reais em 25/08/2026.

O preço está medido e é conhecido: **a colisão deixa de custar erro e passa a custar
retry**. Um horário em que só uma das duas está livre continua sendo oferecido (a união), mas
se o `BoxesAdd` dela recusar não há segunda tentativa. A cobertura de retry caiu de 88% para
49%. Ver `AGENDAMENTO_JANELA_GRADE_20260825.md`.

Só um slot da semana some da união inteira por colisão dupla: **segunda 15:00** (Amorim
15:00–15:45 e Rodrigues 15:00–16:00).

------------------------------------------------------------------------------------------
A JANELA É CURTA DE PROPÓSITO: HOJE + D+1 + D+2
------------------------------------------------------------------------------------------
`janela_dias` conta **dias corridos de calendário**, hoje incluído — 3 significa hoje, amanhã
e depois. Substituiu o horizonte de 14 dias em 25/08/2026.

Fim de semana não tem grade (as janelas só existem em seg–sex), então a janela **não se
estica** para compensar: cadastro no sábado enxerga só a segunda (D+2); cadastro na sexta
depois das 15:15 não enxerga dia útil nenhum e o `/slots` volta vazio com `fallback:true` — a
LP cai no "deixe seu contato", que é o degrade correto e já existia.

Contar dias corridos em vez de dias úteis é decisão, não descuido: a promessa ao lead é "a
gente fala com você nos próximos dias", e uma janela que anda para trás no fim de semana faz
a oferta de sexta ser mais longa que a de segunda, sem que ninguém tenha pedido.

------------------------------------------------------------------------------------------
COMO CONFIGURAR
------------------------------------------------------------------------------------------
    AGENDAMENTO_JANELA_DIAS=3                          # dias corridos, hoje incluído
    AGENDAMENTO_GRADE_JSON='{"duracao_min": 30, ...}'  # JSON inline
    AGENDAMENTO_GRADE_PATH=/etc/cenat/grade.json       # caminho de arquivo

Sem nenhuma das duas últimas, vale GRADE_PADRAO. Um JSON inválido NÃO derruba o processo: cai
no padrão e grita no log. Derrubar o backend inteiro por causa de uma vírgula num env seria
pior que servir a grade padrão.

O JSON aceita chaves parciais — o que não vier é herdado de GRADE_PADRAO.

**Precedência de `janela_dias`**: chave explícita na config > `AGENDAMENTO_JANELA_DIAS` >
`JANELA_DIAS_PADRAO`. O env mexe no **padrão**, não atropela quem pediu um valor — é o que
deixa o env ser uma linha só para o produto inteiro e ao mesmo tempo permite que um teste E2E
alcance uma data distante sem mexer no ambiente.
"""
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.agendamento.horarios import agora_sp

# Dias corridos de calendário ofertados, HOJE INCLUÍDO. 3 = hoje + D+1 + D+2.
# Não está em GRADE_PADRAO de propósito: é política do produto, igual para todo mundo, e
# nada tem a ver com a agenda de uma pessoa. Quem manda aqui é o env.
JANELA_DIAS_PADRAO = 3

# Dias da semana no padrão de `date.weekday()`: 0 = segunda ... 6 = domingo.
# 09:00–18:30 com passo de 45 min dá 12 horários (o último 17:15–18:00): 18:00–18:30 sobra
# curto e não vira slot. Ver a seção "GRADE OFERECE O COMERCIAL INTEIRO" no cabeçalho.
GRADE_PADRAO = {
    "sales_rep_email": "comercial@cenatcursos.com.br",
    "duracao_min": 45,
    "antecedencia_min_horas": 2,
    "type_meeting": "web",
    "janelas": {
        "0": [["09:00", "18:30"]],
        "1": [["09:00", "18:30"]],
        "2": [["09:00", "18:30"]],
        "3": [["09:00", "18:30"]],
        "4": [["09:00", "18:30"]],
    },
}


def _janela_dias(cfg: dict) -> int:
    """Resolve `janela_dias`: config explícita > env > padrão. Valor ruim cai no padrão.

    Nunca levanta e nunca devolve < 1: uma janela de 0 dias apagaria o `/slots` inteiro em
    silêncio, e a causa (um typo num env) seria invisível no comportamento.
    """
    if "janela_dias" in cfg:
        bruto, origem = cfg["janela_dias"], "janela_dias da config"
    else:
        bruto, origem = os.getenv("AGENDAMENTO_JANELA_DIAS"), "AGENDAMENTO_JANELA_DIAS"
        if bruto is None:
            return JANELA_DIAS_PADRAO
    try:
        dias = int(bruto)
    except (TypeError, ValueError):
        print(f"⚠️ agendamento: {origem}={bruto!r} não é inteiro. "
              f"Usando {JANELA_DIAS_PADRAO}.")
        return JANELA_DIAS_PADRAO
    if dias < 1:
        print(f"⚠️ agendamento: {origem}={dias} é menor que 1 e apagaria a grade. "
              f"Usando {JANELA_DIAS_PADRAO}.")
        return JANELA_DIAS_PADRAO
    return dias


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
        self.janela_dias = _janela_dias(cfg)
        if "horizonte_dias" in cfg:
            # Chave morta desde 25/08/2026. Avisa em vez de ignorar calado: quem a deixou na
            # config acredita estar ofertando 14 dias, e vai ver 3.
            print(f"⚠️ agendamento: 'horizonte_dias' não existe mais e foi IGNORADO "
                  f"(era {cfg['horizonte_dias']}). A janela agora é 'janela_dias' "
                  f"= {self.janela_dias} dias corridos.")
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
            # em 09:00–18:30 isso dá 12 slots (o último 17:15–18:00); 18:00–18:45 estouraria.
            while cursor + self.duracao <= limite:
                saida.append(Slot(inicio=cursor, fim=cursor + self.duracao))
                cursor += self.duracao
        return saida

    def slots_candidatos(self, *, agora: datetime | None = None) -> list[Slot]:
        """Slots da janela que respeitam a antecedência mínima. Ainda SEM subtrair ocupação.

        É o insumo de `disponibilidade.slots_livres`, que faz a subtração. Separado porque a
        regra de tempo (antecedência, janela) é da grade, e a de ocupação é da Exact.

        **Pode voltar vazia, e isso é comportamento, não falha** — sexta à tarde e sábado com
        `janela_dias=3` não alcançam dia útil nenhum. Quem chama trata: o `/slots` responde
        `fallback:true` e a LP oferece o "deixe seu contato".
        """
        agora = agora or agora_sp()
        corte = agora + self.antecedencia
        saida: list[Slot] = []
        # `range(janela_dias)`, sem `+1`: a contagem é de DIAS DE CALENDÁRIO com hoje dentro,
        # então 3 é hoje (offset 0), amanhã e depois. O antigo `horizonte_dias` contava
        # offsets a partir de hoje e por isso precisava do `+1`.
        for offset in range(self.janela_dias):
            for slot in self.slots_do_dia(agora.date() + timedelta(days=offset)):
                if slot.inicio >= corte:
                    saida.append(slot)
        return saida

    def slot_por_id(self, slot_id: str) -> Slot | None:
        """Resolve o id vindo da LP contra a grade. `None` se não for um slot que oferecemos.

        Isto é VALIDAÇÃO DE ENTRADA, não conveniência: sem passar pela grade, um POST forjado
        agendaria 03:00 de domingo, ou um slot de 8 horas, e o `BoxesAdd` aceitaria numa boa
        (a Exact não conhece a nossa grade). A checagem de antecedência entra junto — um id
        válido mas vencido também é recusado, e com a janela curta um id de D+3 também.
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
