"""Parse de data da API do Exact Spotter.

Módulo NEUTRO de propósito: importa só a stdlib. Não importa `whatsapp.py`, `exact_spotter.py`
nem models — assim o backfill (`backfill_register_date.py`) consegue reaproveitar exatamente o
mesmo parser sem arrastar junto nenhum caminho de envio de mensagem.

O parser vivia em `exact_spotter.py` e foi movido para cá sem mudança de assinatura;
`exact_spotter.parse_datetime` continua existindo e apontando para esta função.

O BUG que originou este módulo:
    `datetime.fromisoformat` no Python 3.10 aceita fração de segundo de EXATAMENTE 3 ou 6
    dígitos. A Exact devolve fração de tamanho variável — 4, 5, 6 e 7 dígitos observados em
    amostra de 3.000 leads, sendo 7 o caso dominante (90%). Tudo que não fosse 6 caía no
    `except` e virava None, deixando `register_date` e `update_date` NULL em 91% da base.
"""
import re
from datetime import datetime, timezone

# Reconhece o formato que a Exact devolve, com fração de QUALQUER tamanho e timezone opcional.
# O que não casar aqui cai no caminho de fallback, que preserva o comportamento antigo.
_ISO = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


def parse_datetime(value):
    """Converte string de datetime da API para `datetime` naive em UTC.

    Devolve None para entrada vazia, nula ou realmente inválida — NUNCA inventa data.

    A fração de segundo é normalizada para 6 dígitos antes do parse: truncada quando maior
    (microssegundo é a maior precisão que `datetime` guarda) e completada com zero à direita
    quando menor. `.9519` são 951900µs, não 9519µs — por isso `ljust`, não `zfill`.

    Datas com timezone são convertidas para UTC antes de virar naive. As colunas de
    `exact_leads` são `TIMESTAMP WITHOUT TIME ZONE` e o resto do sistema grava `utcnow()`,
    então UTC é a única leitura consistente. Na prática a Exact só devolve `Z`, para o qual
    isto é idêntico ao comportamento antigo.
    """
    if not value:
        return None
    if not isinstance(value, str):
        return None

    texto = value.strip()
    if not texto:
        return None

    m = _ISO.match(texto)
    if m:
        frac = (m.group("frac") or "0")[:6].ljust(6, "0")
        tz = m.group("tz") or ""
        if tz == "Z":
            tz = "+00:00"
        elif len(tz) == 5:  # +HHMM -> +HH:MM
            tz = f"{tz[:3]}:{tz[3:]}"
        texto = f"{m.group('base')}.{frac}{tz}"
    else:
        # Fallback: tudo que o parser antigo aceitava (ex.: data sem hora) segue aceito.
        texto = texto.replace("Z", "+00:00")

    try:
        dt = datetime.fromisoformat(texto)
    except (ValueError, TypeError):
        return None

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
