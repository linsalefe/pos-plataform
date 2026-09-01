"""S5-5 — o disparo em massa não atropela conversa viva do agente.

    cd backend && venv/bin/python test_bulk_pula_conversa_ativa.py

NADA sai daqui: `send_template_message` e todo o resto da cadeia da Meta são mockados,
o banco é dublê. Nenhuma chamada de rede, nenhuma linha gravada.

O DEFEITO (medido em 27-28/08)
  20 conversas ativas cortadas em 2 dias — 14 só em 28/08, em 7 rajadas de 10:16 a 15:21.
  Entre elas 3 leads em `escolhendo_slot`, e gente que tinha respondido MINUTOS antes.
  O template afirma "não tive sucesso em falar com você" para quem acabou de falar.

O QUE ESTE TESTE PROVA
  1. lote: lead em etapa ATIVA é PULADO — nem chega à Meta
  2. e o pulo acha o estado nas DUAS grafias do telefone
  3. etapa NÃO ativa (transferido/concluído/encerrado) NÃO é pulada
  4. `origem_envio='individual'` não é filtrado — o SDR decidiu, e a trava de
     transferência continua valendo ali
  4b. DEFAULT FAIL-SAFE: flag ausente, vazia ou desconhecida = campanha = FILTRA
  5. o retorno da rota conta os pulados, com a lista
  6. `sent`/`failed`/`errors` continuam existindo iguais (o front não quebra)
"""
import asyncio
import io
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

from app import exact_routes
from app.models import (ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_CONCLUIDO,
                        ETAPA_Q_ESCOLHENDO_SLOT, ETAPA_Q_TRANSFERIDO,
                        NatQualificacaoState, ORIGEM_LP)

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def _lead(id, nome, telefone):
    l = MagicMock()
    l.id = id
    l.name = nome
    l.phone1 = telefone
    l.sub_source = "Pos TEA V3"
    l.sdr_name = "Thobias"
    l.funnel_id = 18535
    return l


def _estado(wa_id, etapa):
    e = NatQualificacaoState(contact_wa_id=wa_id, exact_lead_id=1,
                             origem=ORIGEM_LP, etapa=etapa)
    return e


CANAL = MagicMock(id=1, waba_id="w", whatsapp_token="t", phone_number_id="p")


def dispara(leads, estados, origem_envio="campanha"):
    """Roda `bulk_send_template`. `estados` = {wa_id consultado: NatQualificacaoState}."""
    passo = {"n": 0}

    async def execute(stmt):
        passo["n"] += 1
        r = MagicMock()
        if passo["n"] == 1:                       # select(ExactLead).where(id.in_(...))
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=leads)))
        else:                                     # select(Channel)
            r.scalar_one_or_none = MagicMock(return_value=CANAL)
        return r

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()

    async def estado_de(wa_id, _db):
        return estados.get(wa_id)

    envio = AsyncMock(return_value={"messages": [{"id": "wamid.X"}],
                                    "contacts": [{"wa_id": "IGNORADO"}]})
    silenciar = AsyncMock()
    pedido = {"template_name": "sdr_primeiro_contato", "channel_id": 1,
              "lead_ids": [l.id for l in leads],
              "param_mappings": [{"type": "lead_name"}]}
    if origem_envio is not None:
        pedido["origem_envio"] = origem_envio

    # S6-2: a higiene do disparo (recusa/teto) tem teste proprio —
    # test_higiene_disparo.py. Aqui ela sai da frente, senao o db-duble responde
    # qualquer SELECT com um MagicMock truthy e TODO lead vira "recusou".
    with patch("app.qualificacao_fluxo.estado_de", new=AsyncMock(side_effect=estado_de)), \
         patch("app.higiene_disparo.por_que_pular", new=AsyncMock(return_value=None)), \
         patch("app.whatsapp.send_template_message", new=envio), \
         patch("app.whatsapp.fetch_template_body", new=AsyncMock(return_value="Olá {{1}}")), \
         patch("app.whatsapp.render_template_text", new=MagicMock(return_value="Olá X")), \
         patch("app.contatos.contato_existente", new=AsyncMock(return_value=None)), \
         patch("app.welcome_guard.bloquear_se_boas_vindas", new=AsyncMock()), \
         patch.object(exact_routes, "bloquear_se_boas_vindas", new=AsyncMock()), \
         patch("app.sdr_mapping.resolve_sdr_user_id", new=MagicMock(return_value=5)), \
         patch("asyncio.sleep", new=AsyncMock()), \
         patch.object(exact_routes, "_silenciar_agente_apos_envio_manual", new=silenciar):
        buf = io.StringIO()
        with redirect_stdout(buf):
            r = asyncio.run(exact_routes.bulk_send_template(pedido, db, MagicMock()))
    return r, envio, silenciar, buf.getvalue()


# ==========================================================================================
print("\n1) Lote: quem está conversando com a Nat AGORA fica de fora")

ativa = _lead(1, "Daniela", "5541999888777")
livre = _lead(2, "Roberto", "5511988887777")
r, envio, sil, log = dispara([ativa, livre],
                             {"5541999888777": _estado("5541999888777",
                                                       ETAPA_Q_ESCOLHENDO_SLOT)})
checa("só o lead LIVRE recebeu", envio.await_count, 1)
checa("  e foi o Roberto", envio.await_args.args[0], "5511988887777")
checa("a Daniela foi pulada", r["skipped_nat"], 1)
checa("  com nome, telefone e etapa no retorno",
      (r["skipped"][0]["name"], r["skipped"][0]["etapa"]), ("Daniela", ETAPA_Q_ESCOLHENDO_SLOT))
checa("  e o pulo está no log, por contato", "⏭️" in log and "Daniela" in log, True)
checa("`sent` conta só o que saiu", r["sent"], 1)
checa("pular NÃO é falhar", r["failed"], 0)
checa("  nem vira erro na lista", r["errors"], [])
checa("o silenciar rodou só para quem recebeu", sil.await_count, 1)


# ==========================================================================================
print("\n2) O pulo acha o estado nas DUAS grafias — 59% das threads chegam sem o 9º dígito")
#
# `estado_de` é tolerante por construção (`app/telefone.py`). Aqui o estado vive em 12
# dígitos e o disparo mira os 13: com igualdade crua, o filtro passaria batido.

doze = _estado("554199888777", ETAPA_Q_AGUARDANDO_ANO)


def estado_tolerante(wa_id):
    from app.telefone import variantes_wa_id
    return doze if doze.contact_wa_id in (variantes_wa_id(wa_id) or ()) else None


r, envio, _, _ = dispara(
    [ativa, livre],
    {v: doze for v in __import__("app.telefone", fromlist=["x"]).variantes_wa_id(
        "5541999888777")})
checa("estado na outra grafia também barra", r["skipped_nat"], 1)
checa("  e nada foi para ele", envio.await_count, 1)


# ==========================================================================================
print("\n3) Etapa que NÃO é ativa não é pulada — o agente já saiu dessa conversa")

for etapa in (ETAPA_Q_TRANSFERIDO, ETAPA_Q_CONCLUIDO):
    r, envio, _, _ = dispara([ativa, livre],
                             {"5541999888777": _estado("5541999888777", etapa)})
    checa(f"'{etapa}' não barra o disparo", r["skipped_nat"], 0)
    checa(f"  e os 2 leads receberam", envio.await_count, 2)

r, envio, _, _ = dispara([ativa, livre], {})
checa("lead sem estado nenhum recebe normalmente", r["skipped_nat"], 0)
checa("  os 2 receberam", envio.await_count, 2)


# ==========================================================================================
print("\n4) `origem_envio='individual'` não é filtrado — o SDR decidiu responder")
#
# `handleSingleSend` (automacoes/page.tsx) usa ESTA rota com `lead_ids: [id]`. Um SDR que
# escolhe uma pessoa e aperta enviar está agindo de propósito; a trava de transferência
# continua valendo ali, e é ela que evita duas vozes.

EM_SLOT = {"5541999888777": _estado("5541999888777", ETAPA_Q_ESCOLHENDO_SLOT)}

r, envio, sil, log = dispara([ativa], EM_SLOT, origem_envio="individual")
checa("individual: NÃO pula", r["skipped_nat"], 0)
checa("  a mensagem saiu", envio.await_count, 1)
checa("  e o agente foi silenciado (a trava de sempre)", sil.await_count, 1)

r, envio, _, _ = dispara([ativa], EM_SLOT, origem_envio="INDIVIDUAL")
checa("a flag é case-insensitive", r["skipped_nat"], 0)


print("\n4b) DEFAULT FAIL-SAFE — sem a flag, é campanha, e campanha filtra")
#
# Um chamador de fora que esqueça a flag tem como pior caso um envio individual PULADO,
# com o caminho certo no retorno — nunca uma conversa ativa cortada.

for rotulo, valor in [("flag ausente", None), ("flag vazia", ""),
                      ("valor desconhecido", "sei_la"), ("explícito", "campanha")]:
    r, envio, _, _ = dispara([ativa], EM_SLOT, origem_envio=valor)
    checa(f"{rotulo} -> filtra", r["skipped_nat"], 1)
    checa(f"  e nada foi enviado", envio.await_count, 0)

r, _, _, _ = dispara([ativa], EM_SLOT, origem_envio=None)
checa("o motivo diz o CAMINHO, não só o impedimento",
      "tela de Conversas" in r["skipped"][0]["motivo"], True)
checa("  e explica o que acontece lá",
      "transfere o agente" in r["skipped"][0]["motivo"], True)


# ==========================================================================================
print("\n5) O contrato do retorno não mudou para quem já lia")

r, _, _, _ = dispara([livre], {})
checa("`sent` continua lá", "sent" in r, True)
checa("`failed` continua lá", "failed" in r, True)
checa("`errors` continua lá", "errors" in r, True)
checa("sem pulados, a lista vem vazia (não some)", r["skipped"], [])


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} teste(s) falharam:")
    for f in falhas:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado.")
