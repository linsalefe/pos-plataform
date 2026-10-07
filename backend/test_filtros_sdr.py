"""Filtros de sinalização ao SDR: Não confirmou, Cancelar na Exact, Devolver ao funil (07/10/2026).

    cd backend && venv/bin/python test_filtros_sdr.py

Sem banco (dublê de sessão). Escrito e NÃO executado na sprint de 07/10.

O QUE ESTE TESTE PROVA
  1. não confirmou: marcada, sem confirmação, régua viva; some quando confirma ou a régua para
  2. cancelar na Exact: corte com a Exact ainda Vigente; some com Cancelada no sync, com
     "Tratado" e quando o lead confirmou depois do corte
  3. devolver ao funil: d8_sem_resposta mesmo com a reunião de mais de 7 dias; some com "Tratado"
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace

from app import reuniao_contato as rc

falhas = []
AGORA = datetime(2026, 10, 7, 12, 0)


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def R(mid, slot, tipo="Vigente", conf=None, canc=None, enc_em=None, enc=None, tratado=None,
      chave="8388046720"):
    return SimpleNamespace(meeting_id=mid, telefone_chave=chave, slot_inicio=slot,
                           exact_type=tipo, confirmado_em=conf, cancelado_motivo=canc,
                           regua_encerrada_em=enc_em, regua_encerrada_motivo=enc,
                           sdr_tratado_em=tratado)


class DB:
    """Devolve as linhas como a consulta devolveria (o filtro de janela é refeito aqui)."""
    def __init__(self, linhas):
        self.linhas = sorted(linhas, key=lambda r: r.slot_inicio)

    async def execute(self, *a, **k):
        linhas = self.linhas

        class Res:
            def all(self):
                return linhas
        return Res()


def mapa(*linhas):
    return asyncio.run(rc.reunioes_por_chave(DB(list(linhas)), AGORA)).get("8388046720")


AMANHA = datetime(2026, 10, 8, 14, 30)
# ==========================================================================================
print("\n1. não confirmou")
checa("marcada sem confirmação, régua viva", mapa(R(1, AMANHA))["nao_confirmou"], True)
checa("confirmou: sai", mapa(R(1, AMANHA, conf=AGORA))["nao_confirmou"], False)
checa("régua parada (humano): sai", mapa(R(1, AMANHA, enc_em=AGORA, enc="humano"))["nao_confirmou"],
      False)
checa("cortada: sai (não é marcada)", mapa(R(1, AMANHA, canc="sem_confirmacao"))["nao_confirmou"],
      False)

# ==========================================================================================
print("\n2. cancelar na Exact")
checa("cortada e Vigente", mapa(R(7, AMANHA, canc="sem_confirmacao"))["cancelar_na_exact"], 7)
checa("sync viu Cancelada: sai",
      mapa(R(7, AMANHA, tipo="Cancelada", canc="sem_confirmacao"))["cancelar_na_exact"], None)
checa("Tratado: sai",
      mapa(R(7, AMANHA, canc="sem_confirmacao", tratado=AGORA))["cancelar_na_exact"], None)
checa("confirmou depois do corte: sai",
      mapa(R(7, AMANHA, canc="sem_confirmacao", conf=AGORA))["cancelar_na_exact"], None)
velha = R(8, datetime(2026, 9, 20, 10, 0), canc="sem_confirmacao")
checa("corte antigo ainda Vigente continua aparecendo", mapa(velha)["cancelar_na_exact"], 8)

# ==========================================================================================
print("\n3. devolver ao funil")
d8 = R(9, datetime(2026, 9, 28, 10, 0), tipo="Cancelada", enc_em=AGORA, enc="d8_sem_resposta")
checa("D8 com reunião de 9 dias atrás", mapa(d8)["devolver_ao_funil"], 9)
d8t = R(9, datetime(2026, 9, 28, 10, 0), tipo="Cancelada", enc="d8_sem_resposta", tratado=AGORA)
checa("Tratado: sai (e a reunião velha não aparece)", mapa(d8t), None)
checa("D8 + reunião nova marcada: os dois sinais", (lambda m: (m["devolver_ao_funil"], m["marcada"]))(
    mapa(d8, R(10, AMANHA))), (9, True))

print()
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ todos os casos passaram")
