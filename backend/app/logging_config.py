"""O `logging` da aplicação — um handler no root, e o SQL fora dele. (S3-2, 27/08/2026)

Importado na PRIMEIRA linha de `app/main.py`, antes de qualquer outro módulo do projeto.

------------------------------------------------------------------------------------------
O PROBLEMA: A INSTRUMENTAÇÃO DO P0-E NUNCA SAIU DO PROCESSO
------------------------------------------------------------------------------------------
O P0-E (`f19fae9`) pôs o turno do LLM numa linha estruturada por `logging`, com o objetivo
declarado de responder "quantas vezes o modelo devolveu `ofertar_agenda`?" — pergunta que a
auditoria de 26/08 não pôde responder porque o dado nunca existiu.

O dado continuou não existindo. O RECON de 27/08 mediu: **zero linhas `🧠 LLM` no journald**,
com ~10 turnos reais rodados no mesmo período. A causa, reproduzida na mão:

    from uvicorn.config import LOGGING_CONFIG
    logging.config.dictConfig(LOGGING_CONFIG)
    log = logging.getLogger("agente.llm")
    log.isEnabledFor(logging.INFO)     -> False
    log.isEnabledFor(logging.WARNING)  -> True

`LOGGING_CONFIG` do uvicorn **não tem chave `root`** (verificado). Ele configura só
`uvicorn`, `uvicorn.error` e `uvicorn.access`; o root fica sem handler e no default WARNING.
Sem handler no root, o `logging` cai no `lastResort`, que emite a partir de WARNING. Logo:

    log.warning / log.error  -> SAEM (é por isso que "FORA DO CONTRATO" era mensurável)
    log.info                 -> descartado ANTES de virar byte

E as duas linhas que interessavam — o turno bem-sucedido (`🧠 LLM … acao=…`) e a
normalização de `ofertar_agenda` (`🏷️ LLM devolveu …`) — são as duas `log.info`.

Nota histórica: até o P1-A isso ficava **escondido**. O `echo=True` do engine fazia o
SQLAlchemy instalar um handler, e o INFO aparecia por acidente, afogado em SQL. O P1-A
(`dde2fd8`) trocou para `echo=False` — correto, e foi o que resolveu os 4,0 GB de journald e
as 36 750 linhas suprimidas em 25/08 — e com ele foi embora o handler que sustentava o
acidente. Ninguém percebeu porque ninguém tinha ido procurar a linha ainda.

------------------------------------------------------------------------------------------
A CORREÇÃO, E POR QUE ELA NÃO TRAZ OS 4 GB DE VOLTA
------------------------------------------------------------------------------------------
Um handler no root em INFO reabre a porta por onde o SQL entrou. Por isso o handler nasce
com um FILTRO, e não só com um nível:

    nível de logger   -> qualquer um pode desfazer. `echo=True` faz exatamente isso:
                         `create_async_engine(echo=True)` chama
                         `getLogger("sqlalchemy.engine").setLevel(INFO)` no momento em que o
                         engine é criado, DEPOIS deste módulo rodar. Um `setLevel(WARNING)`
                         aqui seria sobrescrito sem aviso.
    filtro no handler -> não tem como ser desfeito de fora. O registro do SQLAlchemy chega ao
                         handler e é descartado ali, independente de nível, de `echo` e de
                         quem mexeu no logger.

Os dois estão aplicados. O filtro é o que segura; o nível é conveniência.

`SQL_MUDO=0` no ambiente desliga o filtro — é a válvula para depurar SQL por alguns minutos
sem editar código, e ela existe justamente para ninguém ser tentado a voltar `echo=True`.

TERCEIROS BARULHENTOS ficam em WARNING por lista explícita (abaixo). `httpx` loga uma linha
INFO por requisição — e o agente faz 1–2 chamadas à OpenAI por turno de lead, mais a Meta,
mais a Exact. Não é 4 GB, mas também não é sinal.

O QUE ESTE MÓDULO NÃO TOCA:
  * os `print()` do projeto (🚀 🔒 🛟 ➡️ ✅). Vão para stdout, o journald pega, e continuam
    exatamente como estavam. Nenhum deles passa a duplicar;
  * os loggers do uvicorn. `uvicorn` tem `propagate=False` com handler próprio, e
    `uvicorn.error`/`uvicorn.access` param nele — nada deles chega ao root, então não há
    linha dobrada.

ORDEM DE EXECUÇÃO (verificada): o uvicorn chama `configure_logging()` no `Config.__init__`,
ANTES de importar a app. Este módulo roda depois, no import de `app.main`. E mesmo que a
ordem se invertesse, `LOGGING_CONFIG` não declara `root` e `disable_existing_loggers` é
`False` — o `dictConfig` do uvicorn não desfaz nada do que está aqui.
"""
import logging
import os
import sys

# Prefixos de logger cujo INFO/DEBUG nunca deve chegar ao journald. `sqlalchemy.engine` é o
# que gerou os 4,0 GB; `sqlalchemy.pool` e `.orm` são da mesma família e igualmente verbosos
# com echo ligado.
PREFIXOS_MUDOS = ("sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.orm", "sqlalchemy.dialects")

# Bibliotecas que falam em INFO a cada chamada de rede. Uma linha por request da OpenAI, da
# Meta e da Exact é ruído com custo, não rastro.
TERCEIROS_EM_WARNING = ("httpx", "httpcore", "openai", "urllib3", "asyncio", "multipart",
                        "python_multipart", "watchfiles", "google", "googleapiclient",
                        "twilio", "aiosqlite")

FORMATO = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
# Sem timezone no formato de propósito: o journald já carimba a hora dele, e um segundo
# carimbo com fuso diferente é exatamente o tipo de coisa que fez o RECON de 27/08 gastar
# meia hora com `created_at`. Este é UTC, igual ao do journald.
DATA = "%Y-%m-%dT%H:%M:%S"

_MARCA = "_cenat_root_handler"


class SemSQL(logging.Filter):
    """Descarta o log do SQLAlchemy no HANDLER, não no logger.

    No handler é o único lugar que `echo=True` não consegue desfazer — ver o cabeçalho.
    WARNING e acima passam: um erro do SQLAlchemy é notícia, o `SELECT` dele não é.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return not record.name.startswith(PREFIXOS_MUDOS)


def configurar() -> logging.Handler | None:
    """Instala o handler do root. Idempotente — devolve o handler, ou None se já havia um.

    Idempotência importa: `app.main` pode ser importado mais de uma vez (reload do uvicorn,
    import indireto num teste), e dois handlers no root significam cada linha duas vezes no
    journald.
    """
    root = logging.getLogger()
    for h in root.handlers:
        if getattr(h, _MARCA, False):
            return None

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(FORMATO, datefmt=DATA))
    handler.setLevel(logging.INFO)
    if os.getenv("SQL_MUDO", "1") != "0":
        handler.addFilter(SemSQL())
    setattr(handler, _MARCA, True)

    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Conveniência, não defesa: o filtro acima é o que segura mesmo com `echo=True`.
    for nome in PREFIXOS_MUDOS:
        logging.getLogger(nome).setLevel(logging.WARNING)
    for nome in TERCEIROS_EM_WARNING:
        logging.getLogger(nome).setLevel(logging.WARNING)

    logging.getLogger("agente.boot").info(
        "logging configurado — root=INFO, handler no stderr, SQL filtrado=%s",
        os.getenv("SQL_MUDO", "1") != "0")
    return handler


configurar()
