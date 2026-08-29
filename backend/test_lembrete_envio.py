"""S5-3 — o lembrete só é `executado` quando SAIU.

    cd backend && venv/bin/python test_lembrete_envio.py

NADA sai daqui: `enviar_nat` é mockado, o banco é falso, a Exact nunca é chamada.

O DEFEITO (medido em 27-28/08)
  `lembrete_reuniao` chamava `send_nat_message` e DESCARTAVA o bool. 15 lembretes
  `executado`, 13 enviados. Os 2 fantasmas:
    ação 226, Mikaelle, 27/08 09:15 — `teto de envios/hora estourado (22/20)`
    ação  64, Josiqueila, 28/08 08:30 — `contato não existe no banco`
  As quatro PRÉ-checagens já eram `AcaoIgnorada` desde o S4-1; o envio, não.

O QUE ESTE TESTE PROVA
  1. envio ok               -> a ação passa (nada levantado) = `executado` honesto
  2. recusa qualquer        -> AcaoIgnorada COM o motivo do sender
  3. teto por hora          -> AcaoAdiada (+10 min): ele passa sozinho, e no caso da
                              Mikaelle ainda sobravam 20 min antes da reunião
  4. teto perto da reunião  -> AcaoIgnorada: readiar passaria da hora, e lembrete
                              atrasado é pior que nenhum (mesma regra da pré-checagem)
  5. as pré-checagens do S4-1 continuam de pé (nada regrediu)
  6. `_fallback`: a despedida que não sai vira AVISO NA NOTIFICAÇÃO do SDR
"""
import asyncio
import io
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app import qualificacao_fluxo as fluxo
from app import qualificacao_guard as guard
from app.models import ETAPA_Q_AGUARDANDO_ANO, NatQualificacaoState, ORIGEM_LP
from app.nat_scheduler import AcaoAdiada, AcaoIgnorada

TETO = f"{guard.MOTIVO_TETO} (22/20)"
falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def _reuniao(minutos_ate=30):
    r = MagicMock()
    r.id = 251
    r.passo = "agendado"
    r.slot_inicio = fluxo._agora_sp() + timedelta(minutes=minutos_ate)
    r.sales_rep_email = "comercial@cenatcursos.com.br"
    r.nome = "Mikaelle Santos"
    r.telefone = "5541992680313"
    return r


def _db(reuniao):
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=reuniao)))
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def roda(*, envio, reuniao=None, minutos_ate=30):
    """Executa o handler. Devolve (excecao_ou_None, chamadas_de_envio)."""
    r = reuniao if reuniao is not None else _reuniao(minutos_ate)
    acao = {"contact_wa_id": "5541992680313", "payload": '{"agendamento_id": 251}'}
    mock = AsyncMock(return_value=envio)
    with patch.object(fluxo, "enviar_nat", new=mock), \
         patch.object(fluxo, "_corpo_do_template", new=AsyncMock(return_value="Oi!")), \
         patch("app.agendamento.consultoras.nome_de",
               new=MagicMock(return_value="Victória Rodrigues")):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                asyncio.run(fluxo.lembrete_reuniao(acao, _db(r)))
            return None, mock
        except (AcaoIgnorada, AcaoAdiada) as e:
            return e, mock


# ==========================================================================================
print("\n1) Envio ok — a ação passa, e `executado` volta a significar uma coisa só")

erro, mock = roda(envio=(True, "ok"))
checa("nada levantado", erro, None)
checa("e o envio aconteceu", mock.await_count, 1)


# ==========================================================================================
print("\n2) Recusa do sender — o caso da Josiqueila (contato inexistente)")

erro, _ = roda(envio=(False, "contato não existe no banco"))
checa("vira AcaoIgnorada (era `executado` mudo)", type(erro), AcaoIgnorada)
checa("  com o motivo do sender GRAVADO na ação",
      "contato não existe no banco" in erro.motivo, True)
checa("  e dizendo que foi o lembrete", erro.motivo.startswith("lembrete não saiu"), True)


# ==========================================================================================
print("\n3) Teto por hora — o caso da Mikaelle: ADIA, não descarta")

erro, _ = roda(envio=(False, TETO), minutos_ate=30)
checa("teto vira AcaoAdiada, não AcaoIgnorada", type(erro), AcaoAdiada)
checa("  com o motivo do teto", TETO in erro.motivo, True)
checa("  e readiado em +10 min (ATRASO_POR_TETO)",
      round((erro.quando - fluxo._agora_sp()).total_seconds() / 60), 10)
checa("  que ainda cabe antes da reunião", erro.quando < _reuniao(30).slot_inicio, True)


# ==========================================================================================
print("\n4) Teto perto demais da reunião — aí não adia mesmo")

erro, _ = roda(envio=(False, TETO), minutos_ate=5)
checa("readiar passaria da hora -> AcaoIgnorada", type(erro), AcaoIgnorada)
checa("  e o motivo explica por quê", "início da reunião" in erro.motivo, True)
checa("  sem perder o motivo original", TETO in erro.motivo, True)


# ==========================================================================================
print("\n5) As pré-checagens do S4-1 continuam de pé")

erro, mock = roda(envio=(True, "ok"), reuniao=None, minutos_ate=-10)
checa("reunião já começou -> AcaoIgnorada", type(erro), AcaoIgnorada)
checa("  e não tentou enviar", mock.await_count, 0)

desmarcada = _reuniao(30)
desmarcada.passo = "cancelado"
erro, mock = roda(envio=(True, "ok"), reuniao=desmarcada)
checa("reunião não está mais agendada -> AcaoIgnorada", type(erro), AcaoIgnorada)
checa("  e não tentou enviar", mock.await_count, 0)

erro, mock = roda(envio=(True, "ok"), reuniao=_reuniao(30))
sem_payload = {"contact_wa_id": "5541992680313", "payload": "{}"}
try:
    asyncio.run(fluxo.lembrete_reuniao(sem_payload, _db(None)))
    tipo = None
except AcaoIgnorada as e:
    tipo = type(e)
checa("sem agendamento_id -> AcaoIgnorada", tipo, AcaoIgnorada)


# ==========================================================================================
print("\n6) `_fallback` — a despedida que não sai vira aviso PARA O SDR")

def fallback(envio):
    estado = NatQualificacaoState(contact_wa_id="5541992680313", exact_lead_id=42,
                                  origem=ORIGEM_LP, etapa=ETAPA_Q_AGUARDANDO_ANO)
    estado.ultimo_wa_message_id = None
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    db.flush = AsyncMock()
    db.add = MagicMock()
    notif = AsyncMock()
    with patch.object(fluxo, "enviar_nat", new=AsyncMock(return_value=envio)), \
         patch.object(fluxo, "_descartar_fala_adiada", new=AsyncMock()), \
         patch.object(fluxo, "_notificar", new=notif):
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(fluxo._fallback(estado, "LLM indisponível", db))
    return estado, notif.await_args.args[2]


estado, corpo = fallback((True, "ok"))
checa("despedida saiu: corpo da notificação sem alarme", "⚠️" in corpo, False)
checa("  e o motivo continua lá", "LLM indisponível" in corpo, True)
checa("  e a transferência aconteceu", estado.etapa, fluxo.ETAPA_Q_TRANSFERIDO)

estado, corpo = fallback((False, "contato não existe no banco"))
checa("despedida NÃO saiu: o SDR é avisado na notificação", "⚠️" in corpo, True)
checa("  com o motivo do sender", "contato não existe no banco" in corpo, True)
checa("  e a transferência acontece do mesmo jeito (não desfaz nada)",
      estado.etapa, fluxo.ETAPA_Q_TRANSFERIDO)


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} teste(s) falharam:")
    for f in falhas:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado.")
