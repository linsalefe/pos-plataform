"""Filtros do SDR: a reunião que representa cada contato (07/10/2026).

    cd backend && venv/bin/python test_reuniao_contato.py

Sem banco (dublê de sessão). Escrito e NÃO executado na sprint de 07/10.

O QUE ESTE TESTE PROVA
  1. marcada/confirmada/fora_do_padrao/situacao de cada tipo de reunião
  2. a próxima Vigente futura vence uma passada mais recente; sem futura, a mais recente
  3. o casamento é tolerante ao 9º dígito
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


def R(mid, chave, slot, tipo="Vigente", conf=None, canc=None, enc=None):
    return SimpleNamespace(meeting_id=mid, telefone_chave=chave, slot_inicio=slot,
                           exact_type=tipo, confirmado_em=conf, cancelado_motivo=canc,
                           regua_encerrada_motivo=enc)


class DB:
    def __init__(self, linhas):
        self.linhas = sorted(linhas, key=lambda r: r.slot_inicio)

    async def execute(self, *a, **k):
        linhas = self.linhas

        class Res:
            def all(self):
                return linhas
        return Res()


# ==========================================================================================
print("\n1. resumo")
s = rc._resumo(R(1, "6198525281", datetime(2026, 10, 8, 17, 40), conf=AGORA), AGORA)
checa("Vigente futura confirmada", (s["marcada"], s["confirmada"], s["situacao"]),
      (True, True, "marcada"))
s = rc._resumo(R(2, "x", datetime(2026, 10, 8, 10, 0), canc="sem_confirmacao"), AGORA)
checa("cortada não é marcada", (s["marcada"], s["situacao"]), (False, "sem_confirmacao"))
s = rc._resumo(R(3, "x", datetime(2026, 10, 9, 10, 0), enc="humano"), AGORA)
checa("fora do padrão = humano", (s["marcada"], s["fora_do_padrao"]), (True, True))
s = rc._resumo(R(4, "x", datetime(2026, 10, 9, 10, 0), enc="sem_interesse"), AGORA)
checa("sem_interesse NÃO é fora do padrão", s["fora_do_padrao"], False)
s = rc._resumo(R(7, "x", datetime(2026, 10, 9, 18, 15), enc="telefone_invalido"), AGORA)
checa("telefone inválido marcado", (s["telefone_invalido"], s["fora_do_padrao"]), (True, False))
s = rc._resumo(R(5, "x", datetime(2026, 10, 6, 10, 0), tipo="Concluido"), AGORA)
checa("Concluido passada", (s["marcada"], s["situacao"]), (False, "concluida"))
s = rc._resumo(R(6, "x", datetime(2026, 10, 6, 10, 0), tipo="Cancelada"), AGORA)
checa("Cancelada", s["situacao"], "cancelada")

# ==========================================================================================
print("\n2. qual reunião representa a pessoa")
db = DB([R(10, "k", datetime(2026, 10, 6, 10, 0), tipo="Cancelada"),
         R(11, "k", datetime(2026, 10, 9, 10, 0)),
         R(12, "k", datetime(2026, 10, 10, 10, 0))])
mapa = asyncio.run(rc.reunioes_por_chave(db, AGORA))
checa("a próxima Vigente futura vence", mapa["k"]["meeting_id"], 11)
db = DB([R(20, "j", datetime(2026, 10, 5, 10, 0), tipo="Concluido"),
         R(21, "j", datetime(2026, 10, 6, 10, 0), tipo="Cancelada")])
mapa = asyncio.run(rc.reunioes_por_chave(db, AGORA))
checa("sem futura: a mais recente", mapa["j"]["meeting_id"], 21)

# ==========================================================================================
print("\n3. casamento pela chave")
mapa = {"6198525281": {"meeting_id": 4774914}}
checa("12 dígitos casa", rc.reuniao_do_contato(mapa, ["556198525281"]), {"meeting_id": 4774914})
checa("13 dígitos casa", rc.reuniao_do_contato(mapa, ["5561998525281"]), {"meeting_id": 4774914})
checa("sem reunião = None", rc.reuniao_do_contato(mapa, ["5511999998888"]), None)

print()
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ todos os casos passaram")
