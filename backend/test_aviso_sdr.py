"""Avisos por WhatsApp ao SDR e às consultoras (07/10/2026).

    cd backend && venv/bin/python test_aviso_sdr.py

NADA sai daqui: o envio é dublê. Escrito e NÃO executado na sprint de 07/10.

O QUE ESTE TESTE PROVA
  1. normalização do telefone ((21) 97007-5652 -> 5521970075652; lixo -> None)
  2. destinatários: corte = consultora da reunião + SDR_AVISO_TELEFONES; ligar agora = as
     duas consultoras + SDR_AVISO_TELEFONES; sem repetição
  3. SDR_AVISO_TELEFONES vazio e consultora sem telefone = nenhum envio
  4. falha num destino (exceção ou recusa da Meta) não impede os outros, e avisar_* nunca levanta
"""
import asyncio
import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app import aviso_sdr as a
from app.agendamento import consultoras as eq

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


EQUIPE = [SimpleNamespace(email="comercial@cenatcursos.com.br", telefone="(21) 97007-5652"),
          SimpleNamespace(email="processoseletivo@cenatcursos.com.br", telefone="(12) 99185-1221")]


def com_equipe():
    return patch.object(eq, "consultoras", lambda: EQUIPE)


def env(v):
    return patch.dict(os.environ, {"SDR_AVISO_TELEFONES": v})


# ==========================================================================================
print("\n1. normalização")
checa("(21) 97007-5652", eq.normalizar_telefone("(21) 97007-5652"), "5521970075652")
checa("com DDI", eq.normalizar_telefone("+55 83 98804-6720"), "5583988046720")
checa("fixo 10 dígitos", eq.normalizar_telefone("1133334444"), "551133334444")
checa("lixo = None", eq.normalizar_telefone("123"), None)
checa("vazio = None", eq.normalizar_telefone(""), None)
checa("telefone legível", a.telefone_legivel("5583988046720"), "(83) 98804-6720")
checa("quando", a.quando(datetime(2026, 10, 9, 10, 0)), "sex 09/10 10:00")

# ==========================================================================================
print("\n2. destinatários")
r = SimpleNamespace(sales_rep_email="processoseletivo@cenatcursos.com.br", meeting_id=1,
                    slot_inicio=datetime(2026, 10, 9, 10, 0), telefone_bruto="5583988046720")
with com_equipe(), env("83 98804-6720, 5583988046720"):
    checa("corte: consultora + SDR, sem repetir", a.destinatarios_corte(r),
          ["5512991851221", "5583988046720"])
    checa("ligar agora: as duas + SDR", a.destinatarios_ligar_agora(),
          ["5521970075652", "5512991851221", "5583988046720"])
with com_equipe(), env(""):
    checa("SDR vazio: corte só a consultora", a.destinatarios_corte(r), ["5512991851221"])
    r_sem = SimpleNamespace(**{**vars(r), "sales_rep_email": "sdr@cenatsaudemental.com"})
    checa("consultora fora do json e SDR vazio: ninguém", a.destinatarios_corte(r_sem), [])


# ==========================================================================================
print("\n3 e 4. envio")
enviados = []


async def _send(to, template_name, **kw):
    enviados.append(to)
    if to.endswith("1221"):
        raise RuntimeError("timeout")
    if to.endswith("5652"):
        return {"error": {"code": 131026}}
    return {"messages": [{"id": "wamid.X"}]}


async def _canal(db):
    return SimpleNamespace(phone_number_id="1", whatsapp_token="t")

with patch("app.whatsapp.send_template_message", _send), patch.object(a, "_canal", _canal):
    n = asyncio.run(a.enviar_aviso("nat_sdr_ligar_agora", ["Ana", "(83)", "Saúde"],
                                   ["5521970075652", "5512991851221", "5583988046720"], None))
    checa("falha em 2 destinos não impede o 3º", (n, enviados),
          (1, ["5521970075652", "5512991851221", "5583988046720"]))
    enviados.clear()
    checa("sem destinos: nenhum envio", (asyncio.run(a.enviar_aviso("x", [], [], None)), enviados),
          (0, []))
    with com_equipe(), env(""):
        r_sem = SimpleNamespace(sales_rep_email="sdr@x", meeting_id=1,
                                slot_inicio=datetime(2026, 10, 9, 10, 0), telefone_bruto="")
        checa("avisar_corte sem destinos devolve 0", asyncio.run(a.avisar_corte(r_sem, "Ana", "x", None)), 0)


async def _quebra(db):
    raise RuntimeError("banco caiu")

with patch.object(a, "_canal", _quebra), com_equipe(), env("83988046720"):
    checa("canal quebrado: avisar_corte não levanta", asyncio.run(a.avisar_corte(r, "Ana", "x", None)), 0)

print()
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ todos os casos passaram")
