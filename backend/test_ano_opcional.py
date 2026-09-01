"""S6-5 — o ano de conclusão virou opcional, e "não lembro" cumpre a etapa.

    cd backend && venv/bin/python test_ano_opcional.py

NADA sai daqui: LLM e envio mockados, banco dublê.

O DEFEITO (RECON_FOLLOWS_HUMANO_IA_20260901, §4.5)
  É o maior degrau do funil, e sozinho derruba mais gente que todos os outros somados:

      respondeu alguma vez   77
      deu a formação         72     -5
      deu o ANO              45    -27  (-37,5%)   <- aqui
      deu a atuação          40     -5
      deu a motivação        35     -5

  Perder alguém no ano não custa o ano: custa a atuação, a motivação e o agendamento que
  vinham depois. "Em que ano você concluiu?" é a única pergunta de MEMÓRIA do roteiro — quem
  não lembra na hora não escreve "não lembro", some.

O QUE ESTE TESTE PROVA
  1. A missão declara o contrato: opcional, "não lembro" vale, e não insiste
  2. O FLUXO aceita um ano não-numérico e avança — a etapa não exige formato
  3. O que ela disse é gravado LITERALMENTE: "não lembra" ≠ NULL
  4. Uma digressão continua não avançando a etapa (a saída não virou porta dos fundos)
  5. As outras etapas NÃO viraram opcionais — só esta
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app import qualificacao_fluxo as fluxo
from app.models import (ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_AGUARDANDO_ATUACAO,
                        ETAPA_Q_AGUARDANDO_FORMACAO, ETAPA_Q_AGUARDANDO_MOTIVACAO,
                        NatQualificacaoState, ORIGEM_LP)

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


MISSAO = fluxo.MISSOES[ETAPA_Q_AGUARDANDO_ANO]


# ==========================================================================================
print("\n1) A missão declara o contrato")

checa("diz que a pergunta é OPCIONAL", "OPCIONAL" in MISSAO, True)
checa("proíbe insistir", "NUNCA insiste" in MISSAO, True)
checa("proíbe pedir duas vezes", "NUNCA peça o ano duas vezes" in MISSAO, True)
for frase in ("não lembro", "não sei", "faz muito tempo", "ainda estou cursando"):
    checa(f'aceita "{frase}" como resposta', frase in MISSAO, True)
checa("carrega a saída, com as palavras pedidas",
      "se não lembrar de cabeça, sem problema, seguimos" in MISSAO, True)
checa("manda gravar LITERALMENTE o que ela disse", "literalmente" in MISSAO, True)
checa("e ainda termina perguntando a atuação (o roteiro não some)",
      "atua" in MISSAO, True)

print("\n  --- e o que NÃO mudou ---")
checa("a formação continua sendo perguntada de verdade",
      "OPCIONAL" in fluxo.MISSOES[ETAPA_Q_AGUARDANDO_FORMACAO], False)
checa("a atuação também", "OPCIONAL" in fluxo.MISSOES[ETAPA_Q_AGUARDANDO_ATUACAO], False)
checa("a motivação também", "OPCIONAL" in fluxo.MISSOES[ETAPA_Q_AGUARDANDO_MOTIVACAO], False)
checa("toda etapa ativa continua tendo missão",
      sorted(set(fluxo.MISSOES) & {ETAPA_Q_AGUARDANDO_ANO}) != [], True)


# ==========================================================================================
print("\n2, 3 e 4) O fluxo aceita — e grava o que ela disse")


def _db():
    db = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    db.add = MagicMock()
    return db


def _estado(etapa):
    e = NatQualificacaoState(contact_wa_id="5541999888777", exact_lead_id=1,
                             origem=ORIGEM_LP, etapa=etapa)
    e.ultimo_wa_message_id = None
    return e


def _resp(cumprida=True, extraido=None, msg="ok"):
    return {"mensagem": msg, "etapa_cumprida": cumprida, "acao": "continuar",
            "dado_extraido": extraido or {}}


async def roda(estado, resposta):
    envio = AsyncMock(return_value=True)

    async def _via_envio(*a, **k):
        await envio(*a, **k)
        return True, "ok"

    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)), \
         patch.object(fluxo, "_fatos", new=AsyncMock(return_value=("ctx", {}))), \
         patch.object(fluxo, "_historico", new=AsyncMock(return_value=[])), \
         patch.object(fluxo, "_reuniao", new=AsyncMock(return_value=None)), \
         patch.object(fluxo, "_notificar", new=AsyncMock()), \
         patch.object(fluxo, "_agendar_encerramento", new=AsyncMock()), \
         patch.object(fluxo, "_agendar_follow", new=AsyncMock()), \
         patch.object(fluxo, "_armar_vigia", new=AsyncMock()), \
         patch.object(fluxo.llm, "conversar", new=AsyncMock(return_value=resposta)) as ia, \
         patch.object(fluxo, "send_nat_message", new=envio), \
         patch.object(fluxo, "enviar_nat", new=AsyncMock(side_effect=_via_envio)):
        await fluxo.processar_texto(estado.contact_wa_id, "oi", "wamid.1", _db())
    return envio, ia


# Um ano de verdade continua funcionando — o teste não pode provar só o caso novo.
e = _estado(ETAPA_Q_AGUARDANDO_ANO)
asyncio.run(roda(e, _resp(extraido={"ano_conclusao": "2019"})))
checa("um ano numérico avança ano -> atuacao", e.etapa, ETAPA_Q_AGUARDANDO_ATUACAO)
checa("  e é gravado", e.ano_conclusao, "2019")

# O caso desta sprint, em cinco formas reais de dizer a mesma coisa.
for dito in ("não lembro", "não sei, faz muito tempo", "preciso ver o diploma",
             "ainda estou cursando", "por volta de 2010"):
    e = _estado(ETAPA_Q_AGUARDANDO_ANO)
    envio, _ = asyncio.run(roda(e, _resp(extraido={"ano_conclusao": dito})))
    checa(f'"{dito}" cumpre a etapa', e.etapa, ETAPA_Q_AGUARDANDO_ATUACAO)
    checa("  e é gravado LITERALMENTE (≠ NULL)", e.ano_conclusao, dito)
    checa("  e o agente falou (não calou)", envio.await_count, 1)

print()
# A saída não é porta dos fundos: quem desconversa continua sem avançar, e é aí que a
# oferta ("se não lembrar de cabeça, sem problema") aparece na fala do agente.
e = _estado(ETAPA_Q_AGUARDANDO_ANO)
envio, ia = asyncio.run(roda(e, _resp(cumprida=False, msg="Custa quanto?")))
checa("digressão NÃO avança a etapa", e.etapa, ETAPA_Q_AGUARDANDO_ANO)
checa("  mas o agente responde", envio.await_count, 1)
checa("  e a missão que foi ao LLM é a desta etapa (com a saída)",
      "seguimos" in ia.await_args.kwargs["missao"], True)

# `ano_conclusao` NULL continua querendo dizer "ninguém perguntou" — é a distinção que
# torna "não lembra" um dado e não uma lacuna.
e = _estado(ETAPA_Q_AGUARDANDO_ANO)
asyncio.run(roda(e, _resp(cumprida=False)))
checa("sem resposta, a coluna segue NULL (≠ 'não lembra')", e.ano_conclusao, None)


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado.")
