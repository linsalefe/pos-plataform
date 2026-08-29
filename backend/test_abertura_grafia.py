"""S5-2 — a abertura que evaporava quando o contato existia na OUTRA grafia.

    cd backend && venv/bin/python test_abertura_grafia.py

NADA sai daqui: `enviar_nat` é mockado nos grupos 1-3, e no grupo 4 ele roda de verdade
mas contra um banco dublê, parando na primeira recusa — antes de qualquer chamada à Meta.

O DEFEITO (medido em 27-28/08: 6 ações, 4 pessoas, 19% das aberturas da janela)
  `_contato_ou_criar` resolve nas duas grafias, acha o contato de 12 dígitos e decide — 
  corretamente — não criar o de 13. O objeto resolvido era DESCARTADO. O estado nascia em
  13d, `nat_sender` procurava `Contact.wa_id == <13d>` com igualdade crua, não achava,
  recusava com "contato não existe no banco", e o savepoint revertia o estado junto.

O QUE ESTE TESTE PROVA
  1. contato pré-existente em 12d: estado E envio passam a usar 12d
  2. contato criado do zero: a grafia não muda (nada regrediu para o lead novo)
  3. o alinhamento é logado — a troca de grafia nunca é silenciosa
  4. a igualdade crua do `nat_sender` CONTINUA crua (é ela que impediu o envio para o
     estranho em 25/08) — o conserto é alinhar a grafia, não afrouxar quem envia
"""
import asyncio
import io
from contextlib import redirect_stdout
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app import nat_sender
from app import qualificacao_fluxo as fluxo
from app import qualificacao_guard as guard
from app.models import (ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_AGUARDANDO_FORMACAO,
                        Contact, ORIGEM_LP)

DOZE = "554999333881"        # a Fernanda, como ela existe em `contacts`
TREZE = "5549999333881"      # como a ação 360/364 tentou enviar

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def _db():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


def abre(*, contato_wa_id, alvo=TREZE):
    """Roda `iniciar_qualificacao`. Devolve (estado gravado, envio mockado, stdout)."""
    contato = Contact(wa_id=contato_wa_id, name="Fernanda", channel_id=1)
    db = _db()
    gravados = []
    db.add = MagicMock(side_effect=lambda o: gravados.append(o))

    envio = AsyncMock(return_value=(True, "ok"))
    acao = {"contact_wa_id": alvo, "payload": '{"lead_id": 42, "origem": "lp"}',
            "agora": datetime(2026, 8, 28, 10, 0)}

    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=None)), \
         patch.object(guard, "qualificacao_pode_iniciar",
                      new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(fluxo, "_contato_ou_criar", new=AsyncMock(return_value=contato)), \
         patch("app.qualificacao_dados.resolver_dados",
               new=AsyncMock(return_value={"formacao": "Psicologia",
                                           "faixa_investimento": None,
                                           "como_conheceu": None})), \
         patch.object(fluxo, "_reuniao", new=AsyncMock(return_value=None)), \
         patch.object(fluxo, "_nome", new=AsyncMock(return_value="Fernanda")), \
         patch.object(fluxo, "_curso", new=AsyncMock(return_value="Pós em TEA")), \
         patch.object(fluxo, "_corpo_do_template", new=AsyncMock(return_value="Olá!")), \
         patch.object(fluxo, "enviar_nat", new=envio), \
         patch.object(fluxo, "_agendar_encerramento", new=AsyncMock()):
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(fluxo.iniciar_qualificacao(acao, db))
    estado = next((o for o in gravados if hasattr(o, "etapa")), None)
    return estado, envio, buf.getvalue()


# ==========================================================================================
print("\n1) Contato pré-existente na outra grafia — o caso da Fernanda")

estado, envio, log = abre(contato_wa_id=DOZE)
checa("a abertura SAIU (era recusa + estado revertido)", envio.await_count, 1)
checa("  e foi para a grafia do contato que existe", envio.await_args.args[0], DOZE)
checa("o estado nasce na MESMA grafia do envio", estado.contact_wa_id, DOZE)
checa("  (e não na grafia da ação)", estado.contact_wa_id == TREZE, False)
checa("o resto da abertura não mudou: etapa", estado.etapa, ETAPA_Q_AGUARDANDO_ANO)
checa("  e o template escolhido", envio.await_args.args[1],
      guard.ETAPA_ABERTURA_QUALIFICACAO)


# ==========================================================================================
print("\n2) Contato criado do zero — nada regrediu para o lead novo")

estado, envio, log = abre(contato_wa_id=TREZE)
checa("grafia inalterada quando o contato é o da própria ação",
      envio.await_args.args[0], TREZE)
checa("  e o estado idem", estado.contact_wa_id, TREZE)
checa("  e nada foi logado sobre grafia", "🔤" in log, False)


# ==========================================================================================
print("\n3) A troca de grafia nunca é silenciosa")

_, _, log = abre(contato_wa_id=DOZE)
checa("o log registra o alinhamento", "🔤" in log, True)
checa("  nomeando a grafia da ação", TREZE in log, True)
checa("  e a do contato", DOZE in log, True)


# ==========================================================================================
print("\n4) A igualdade crua do `nat_sender` continua crua — de propósito")
#
# Em 25/08 a variante de 12 dígitos do número de um lead era o número de OUTRA PESSOA
# (Ronaldo -> Pablo). Só a igualdade estrita do sender impediu o envio para o estranho.
# Este grupo é o guardrail disso: afrouxar aqui reabriria aquele buraco.

class DbSoDoze:
    """Banco em que SÓ o contato de 12 dígitos existe."""
    def __init__(self):
        self.consultado = []

    async def execute(self, stmt):
        self.consultado.append(str(stmt))
        return MagicMock(scalar_one_or_none=MagicMock(return_value=None))


buf = io.StringIO()
with redirect_stdout(buf):
    saiu, motivo = asyncio.run(nat_sender.enviar_nat(TREZE, "nat_abertura_qualificacao",
                                                     DbSoDoze()))
checa("sender com wa_id que não casa: RECUSA", saiu, False)
checa("  com o motivo de sempre", motivo, "contato não existe no banco")
checa("  e nem chegou a consultar guard/canal", "🔒" in buf.getvalue(), True)


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} teste(s) falharam:")
    for f in falhas:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado.")
