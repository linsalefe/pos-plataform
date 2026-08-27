"""Sprint 3 item 2 — o `log.info` do projeto sai do processo, e o SQL não. (27/08/2026)

    cd backend && venv/bin/python test_logging_config.py

O QUE ESTE ARQUIVO GUARDA:

  1. com a config do uvicorn SOZINHA (o estado de 26/08), `agente.llm` não emite INFO
  2. depois de `configurar()`, emite — e o `dictConfig` do uvicorn rodando DEPOIS não desfaz
  3. o SQL do SQLAlchemy é descartado NO HANDLER, inclusive com `echo=True` reativando o
     logger — que é o cenário dos 4,0 GB de 25/08
  4. WARNING do SQLAlchemy passa (erro é notícia; SELECT não é)
  5. idempotente: importar duas vezes não duplica linha no journald
  6. SQL_MUDO=0 desliga o filtro (a válvula de depuração)
"""
import io
import logging
import logging.config
import os
import sys
from unittest.mock import patch

from uvicorn.config import LOGGING_CONFIG

from app import logging_config

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def limpa_root():
    """Volta o root ao estado de um processo recém-nascido."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.WARNING)
    for nome in logging_config.PREFIXOS_MUDOS + logging_config.TERCEIROS_EM_WARNING + (
            "agente.llm",):
        logging.getLogger(nome).setLevel(logging.NOTSET)


def captura(fn):
    """Roda `fn` com o stderr do handler do root redirecionado. Devolve o texto emitido."""
    buf = io.StringIO()
    alvos = [h for h in logging.getLogger().handlers if isinstance(h, logging.StreamHandler)]
    originais = [h.stream for h in alvos]
    for h in alvos:
        h.stream = buf
    try:
        fn()
    finally:
        for h, s in zip(alvos, originais):
            h.stream = s
    return buf.getvalue()


print("=" * 78)
print("Sprint 3 item 2 — o logging do P0-E saindo do processo")
print("=" * 78)

print("\n1) O estado de 26/08: só a config do uvicorn -> INFO morre no lastResort")
limpa_root()
logging.config.dictConfig(LOGGING_CONFIG)
llm = logging.getLogger("agente.llm")
checa("LOGGING_CONFIG do uvicorn não declara root", "root" in LOGGING_CONFIG, False)
checa("agente.llm NÃO está habilitado para INFO", llm.isEnabledFor(logging.INFO), False)
checa("  mas ESTÁ para WARNING (por isso 'FORA DO CONTRATO' era mensurável)",
      llm.isEnabledFor(logging.WARNING), True)

print("\n2) Depois de configurar(), o INFO sai — e o uvicorn não desfaz")
limpa_root()
logging.config.dictConfig(LOGGING_CONFIG)
logging_config.configurar()
checa("agente.llm habilitado para INFO", llm.isEnabledFor(logging.INFO), True)
saida = captura(lambda: llm.info("🧠 LLM %s | acao=%s", "5537999965494/aguardando_ano",
                                 "nenhuma"))
checa("  a linha 🧠 LLM aparece", "🧠 LLM" in saida, True)
checa("  com o rótulo do contato", "5537999965494/aguardando_ano" in saida, True)
checa("  e com a ação (a pergunta que a auditoria não pôde responder)",
      "acao=nenhuma" in saida, True)

# A ordem real é a inversa (uvicorn primeiro), mas travar os dois sentidos é barato e
# protege de uma mudança futura no uvicorn.
logging.config.dictConfig(LOGGING_CONFIG)
checa("dictConfig do uvicorn rodando DEPOIS não derruba o INFO",
      llm.isEnabledFor(logging.INFO), True)
saida = captura(lambda: llm.info("🏷️  LLM devolveu 'ofertar_agenda'"))
checa("  e a linha da normalização também sai", "ofertar_agenda" in saida, True)

print("\n3) O SQL fica de fora — inclusive com `echo=True` de volta")
sql = logging.getLogger("sqlalchemy.engine.Engine")
saida = captura(lambda: sql.info("SELECT messages.id FROM messages WHERE ..."))
checa("SELECT em INFO é descartado", "SELECT" in saida, False)

# É isto que um `create_async_engine(echo=True)` faz, e é o que um `setLevel(WARNING)`
# sozinho não sobreviveria: o filtro está no HANDLER, fora do alcance dele.
sql.setLevel(logging.INFO)
checa("  echo=True reabilita o LOGGER", sql.isEnabledFor(logging.INFO), True)
saida = captura(lambda: sql.info("SELECT messages.id FROM messages WHERE ..."))
checa("  e mesmo assim NADA sai (o filtro está no handler)", saida, "")
saida = captura(lambda: llm.info("🧠 LLM ainda funcionando"))
checa("  sem calar o resto do processo junto", "🧠 LLM" in saida, True)

print("\n4) WARNING do SQLAlchemy passa — erro é notícia, SELECT não é")
saida = captura(lambda: sql.warning("connection pool is exhausted"))
checa("WARNING do sqlalchemy.engine aparece", "pool is exhausted" in saida, True)

print("\n5) Idempotente — importar duas vezes não duplica a linha")
antes = len(logging.getLogger().handlers)
segunda = logging_config.configurar()
checa("segunda chamada devolve None", segunda, None)
checa("  e não acrescenta handler", len(logging.getLogger().handlers), antes)
saida = captura(lambda: llm.info("uma vez só"))
checa("  a linha aparece UMA vez", saida.count("uma vez só"), 1)

print("\n6) SQL_MUDO=0 — a válvula, para não voltarem a mexer em echo")
limpa_root()
with patch.dict(os.environ, {"SQL_MUDO": "0"}):
    logging_config.configurar()
sql.setLevel(logging.INFO)
saida = captura(lambda: sql.info("SELECT com SQL_MUDO=0"))
checa("com SQL_MUDO=0 o SQL volta a sair", "SELECT com SQL_MUDO=0" in saida, True)

# Devolve o processo ao estado padrão para não contaminar quem importar isto depois.
limpa_root()
logging_config.configurar()

print("\n" + "=" * 78)
if falhas:
    print(f"{len(falhas)} FALHA(S):")
    for f in falhas:
        print(f"  - {f}")
    raise SystemExit(1)
print("TUDO OK")
