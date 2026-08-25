"""Guardrail do agente de pré-qualificação.

    cd backend && venv/bin/python test_qualificacao.py

NADA sai daqui: `send_nat_message`, o LLM e a Exact são sempre mockados, e o banco é falso.
Nenhuma chamada real à OpenAI, nenhum WhatsApp, nenhuma linha gravada.

O que estes testes provam:
  1. o parser lê o NOSSO formato e ignora o do RD e o texto do SDR
  2. o contrato do LLM é estrito — fora dele, ninguém improvisa
  3. só código muda etapa, e transição inválida vira humano
  4. a ramificação 4a/4b é decidida na EXECUÇÃO, não no agendamento
  5. gatilho e lembrete são idempotentes
  6. um dono por mensagem: com estado ativo, o fluxo velho não roda
  7. o guard falha fechado em todas as travas
"""
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app import qualificacao_dados as dados
from app import qualificacao_fluxo as fluxo
from app import qualificacao_guard as guard
from app import qualificacao_llm as llm
from app.models import (ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_AGUARDANDO_ATUACAO,
                        ETAPA_Q_AGUARDANDO_FORMACAO, ETAPA_Q_AGUARDANDO_MOTIVACAO,
                        ETAPA_Q_CONCLUIDO, ETAPA_Q_ESCOLHENDO_SLOT, ETAPA_Q_OFERTANDO_AGENDA,
                        ETAPA_Q_TRANSFERIDO, ETAPAS_QUALIFICACAO_ATIVAS,
                        ETAPAS_QUALIFICACAO_VALIDAS, NatConfig, NatQualificacaoState,
                        ORIGEM_LP)

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def _db():
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()
    return db


def _estado(etapa=ETAPA_Q_AGUARDANDO_ANO, **kw):
    e = NatQualificacaoState(contact_wa_id="5583999998888", exact_lead_id=42,
                             origem=ORIGEM_LP, etapa=etapa, **kw)
    e.ultimo_wa_message_id = None
    e.dados_extras = None
    e.agendamento_id = kw.get("agendamento_id")
    return e


def _resp(mensagem="ok", cumprida=True, extraido=None, acao="nenhuma"):
    return {"mensagem": mensagem, "etapa_cumprida": cumprida,
            "dado_extraido": extraido, "acao": acao}


def _reuniao(id=7, dias=2):
    r = MagicMock()
    r.id = id
    r.slot_inicio = datetime.now() + timedelta(days=dias)
    r.sales_rep_email = "comercial@cenatcursos.com.br"
    r.telefone = "5583999998888"
    r.nome = "Maria Silva"
    return r


# ==========================================================================================
print("\n1) Parser do description — lê o NOSSO formato, ignora o resto")

NOSSO = ("E-mail: m@x.com | Profissão: Enfermagem | Ensino Superior: Sim | "
         "Como conheceu: Instagram | Faixa de investimento: De R$100,00 a R$200,00")
RD = "Profissão escolha:\nProfessor(a)\n\nNível de escolaridade:\nSim"
SDR = NOSSO + "\n\nVI AMORIM: Psicóloga, trabalha no CRAS. Atende de manhã."

checa("nosso formato -> formação", dados._formacao_de(dados.parse_description(NOSSO)),
      "Enfermagem")
checa("nosso formato -> faixa", dados.parse_description(NOSSO)["faixa de investimento"],
      "De R$100,00 a R$200,00")
checa("texto do SDR colado não contamina",
      dados.parse_description(SDR)["faixa de investimento"], "De R$100,00 a R$200,00")
checa("formato do RD é ignorado", dados.parse_description(RD), {})
checa("vazio", dados.parse_description(""), {})
checa("None", dados.parse_description(None), {})
checa("chave em snake_case ainda é lida",
      dados._formacao_de(dados._de_extras({"profissao": "Psicologia"})), "Psicologia")
checa("'Outra profissão' NÃO é formação",
      dados._formacao_de({"profissao": "Outra profissão"}), None)
checa("formação vazia -> None", dados._formacao_de({"profissao": "   "}), None)


# ==========================================================================================
print("\n2) Contrato do LLM — fora dele, ninguém improvisa")

VALIDO = json.dumps({"mensagem": "Oi!", "etapa_cumprida": True,
                     "dado_extraido": {"ano_conclusao": "2019"}, "acao": "nenhuma"})
checa("JSON válido passa", llm._validar(VALIDO)["dado_extraido"], {"ano_conclusao": "2019"})
checa("cercado em markdown passa",
      llm._validar("```json\n" + VALIDO + "\n```")["mensagem"], "Oi!")
for rotulo, bruto in [
    ("acao fora do enum", json.dumps({"mensagem": "x", "etapa_cumprida": True,
                                      "dado_extraido": None, "acao": "inventar"})),
    ("etapa_cumprida ausente", json.dumps({"mensagem": "x", "dado_extraido": None,
                                           "acao": "nenhuma"})),
    ("etapa_cumprida não-booleana", json.dumps({"mensagem": "x", "etapa_cumprida": "sim",
                                                "dado_extraido": None, "acao": "nenhuma"})),
    ("mensagem vazia", json.dumps({"mensagem": "  ", "etapa_cumprida": True,
                                   "dado_extraido": None, "acao": "nenhuma"})),
    ("dado_extraido não-dict", json.dumps({"mensagem": "x", "etapa_cumprida": True,
                                           "dado_extraido": [1], "acao": "nenhuma"})),
    ("texto solto", "desculpe, não entendi"),
    ("lista no lugar do objeto", "[]"),
    ("None", None),
]:
    checa(f"{rotulo} -> None", llm._validar(bruto), None)

ctx = llm.montar_contexto({"Curso": "TEA", "Formação": None, "Vazio": "",
                           "Horários": ["ter 10:30"]})
checa("contexto OMITE campo vazio (não vira 'não informado')", "Formação" in ctx, False)
checa("contexto lista horários", "  - ter 10:30" in ctx, True)

# --- a amostra de horários do dia cobre a tarde ---------------------------------------
# Isto era `[:6]` e virou defeito em 25/08/2026, quando a grade passou de 5 para 12
# horários por dia (09:00–18:30): os seis PRIMEIROS de doze são todos antes das 13:00, e o
# agente deixaria de oferecer tarde — sem erro nenhum, com a tarde inteira livre.
DOZE = [{"hora": h} for h in ["09:00", "09:45", "10:30", "11:15", "12:00", "12:45",
                              "13:30", "14:15", "15:00", "15:45", "16:30", "17:15"]]
amostra = [h["hora"] for h in fluxo._espalhados(DOZE, 6)]
checa("6 de 12 saem espalhados, não os 6 primeiros", amostra,
      ["09:00", "10:30", "12:00", "14:15", "15:45", "17:15"])
checa("o primeiro e o último do dia sempre entram",
      (amostra[0], amostra[-1]), ("09:00", "17:15"))
checa("tem pelo menos um horário depois do almoço",
      any(h >= "13:00" for h in amostra), True)
checa("dia mais curto que a amostra volta inteiro",
      [h["hora"] for h in fluxo._espalhados(DOZE[:4], 6)],
      ["09:00", "09:45", "10:30", "11:15"])
checa("dia vazio não explode", fluxo._espalhados([], 6), [])


# ==========================================================================================
print("\n3) Máquina de etapas — só código muda etapa")

checa("as 9 etapas do CHECK batem com o modelo", len(ETAPAS_QUALIFICACAO_VALIDAS), 9)
checa("etapas ativas não incluem concluido", ETAPA_Q_CONCLUIDO in ETAPAS_QUALIFICACAO_ATIVAS,
      False)
checa("etapas ativas não incluem transferido",
      ETAPA_Q_TRANSFERIDO in ETAPAS_QUALIFICACAO_ATIVAS, False)
checa("toda etapa ativa tem missão",
      sorted(ETAPAS_QUALIFICACAO_ATIVAS - set(fluxo.MISSOES)), [])


async def roda(estado, resposta, *, reuniao=None, ofertados=None, wa_id="wamid.1"):
    """Uma passada de processar_texto com LLM e envio mockados."""
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)), \
         patch.object(fluxo, "_fatos", new=AsyncMock(return_value=("ctx", ofertados or {}))), \
         patch.object(fluxo, "_historico", new=AsyncMock(return_value=[])), \
         patch.object(fluxo, "_reuniao", new=AsyncMock(return_value=reuniao)), \
         patch.object(fluxo, "_notificar", new=AsyncMock()), \
         patch.object(fluxo, "agendar_lembrete", new=AsyncMock()) as lembrete, \
         patch.object(fluxo.llm, "conversar", new=AsyncMock(return_value=resposta)) as ia, \
         patch.object(fluxo, "send_nat_message",
                      new=AsyncMock(return_value=True)) as envio:
        tratou = await fluxo.processar_texto(estado.contact_wa_id, "oi", wa_id, _db())
    return tratou, envio, ia, lembrete


e = _estado(ETAPA_Q_AGUARDANDO_ANO)
tratou, envio, _, _ = asyncio.run(roda(e, _resp(extraido={"ano_conclusao": "2019"})))
checa("etapa cumprida avança ano -> atuacao", e.etapa, ETAPA_Q_AGUARDANDO_ATUACAO)
checa("  e grava o dado na coluna", e.ano_conclusao, "2019")
checa("  e envia uma mensagem", envio.await_count, 1)

e = _estado(ETAPA_Q_AGUARDANDO_ATUACAO)
asyncio.run(roda(e, _resp(cumprida=False)))
checa("não cumprida NÃO anda a etapa", e.etapa, ETAPA_Q_AGUARDANDO_ATUACAO)

e = _estado(ETAPA_Q_AGUARDANDO_FORMACAO)
asyncio.run(roda(e, _resp(extraido={"formacao": "Psicologia"})))
checa("formacao -> ano", e.etapa, ETAPA_Q_AGUARDANDO_ANO)
checa("  formação gravada", e.formacao, "Psicologia")

e = _estado(ETAPA_Q_AGUARDANDO_ANO)
asyncio.run(roda(e, _resp(extraido={"curiosidade": "mora em Recife"})))
checa("dado desconhecido vai para dados_extras (sem ALTER)",
      e.dados_extras, {"curiosidade": "mora em Recife"})

print("\n   fallback — os quatro caminhos que viram humano")
for rotulo, resposta in [
    ("LLM devolveu None (timeout/contrato)", None),
    ("LLM pediu transferir_humano", _resp(acao="transferir_humano")),
    ("ação impossível na etapa (agendar_slot)", _resp(acao="agendar_slot")),
]:
    e = _estado(ETAPA_Q_AGUARDANDO_ANO)
    _, envio, _, _ = asyncio.run(roda(e, resposta))
    checa(f"{rotulo} -> transferido_humano", e.etapa, ETAPA_Q_TRANSFERIDO)
    checa("  motivo registrado", bool(e.transferido_motivo), True)
    checa("  despedida determinística enviada",
          envio.await_args.kwargs.get("corpo_livre"), fluxo.TEXTO_FALLBACK)

e = _estado(ETAPA_Q_OFERTANDO_AGENDA)
asyncio.run(roda(e, _resp(cumprida=True), ofertados={"x": "y"}))
checa("etapa de agenda 'cumprida' sem slot -> humano", e.etapa, ETAPA_Q_TRANSFERIDO)


print("\n   bifurcação do roteiro (passo 4a x 4b), decidida por CÓDIGO")
e = _estado(ETAPA_Q_AGUARDANDO_MOTIVACAO)
_, _, _, lembrete = asyncio.run(roda(e, _resp(extraido={"motivacao": "quero atuar no CAPS"}),
                                     reuniao=_reuniao()))
checa("motivação + JÁ tem reunião -> concluido", e.etapa, ETAPA_Q_CONCLUIDO)
checa("  lembrete agendado", lembrete.await_count, 1)
checa("  motivação gravada", e.motivacao, "quero atuar no CAPS")

e = _estado(ETAPA_Q_AGUARDANDO_MOTIVACAO)
with patch.object(fluxo, "_ofertar_agenda", new=AsyncMock()) as ofertar:
    asyncio.run(roda(e, _resp(extraido={"motivacao": "x"}), reuniao=None))
checa("motivação + SEM reunião -> ofertando_agenda", e.etapa, ETAPA_Q_OFERTANDO_AGENDA)
checa("  e a grade é oferecida", ofertar.await_count, 1)


# ==========================================================================================
print("\n4) Agendamento — o slot é validado DUAS vezes antes de escrever")

OFERTADOS = {"2026-09-01T10:30:00": "2026-09-01 10:30"}


async def tenta_agendar(slot_id, livres, ofertados=OFERTADOS):
    e = _estado(ETAPA_Q_ESCOLHENDO_SLOT)
    disp = MagicMock()
    disp.slots_livres = AsyncMock(return_value=[MagicMock(id=s) for s in livres])
    fluxo_ag = MagicMock()
    fluxo_ag.agendar = AsyncMock(return_value=MagicMock(agendamento_id=99))
    modulo = MagicMock(agendar=fluxo_ag, disponibilidade=disp)
    with patch.dict("sys.modules", {"app.agendamento": modulo}), \
         patch.object(fluxo, "_fallback", new=AsyncMock()) as fb, \
         patch.object(fluxo, "_ofertar_agenda", new=AsyncMock()) as reoferta, \
         patch.object(fluxo, "_enviar", new=AsyncMock()), \
         patch.object(fluxo, "_concluir", new=AsyncMock()) as concluir, \
         patch.object(fluxo, "_reuniao", new=AsyncMock(return_value=_reuniao())):
        await fluxo._agendar(e, _resp(acao="agendar_slot",
                                      extraido={"slot_id": slot_id}), ofertados, _db())
    return e, fb, reoferta, concluir, fluxo_ag


_, fb, _, concluir, escrita = asyncio.run(
    tenta_agendar("2026-09-01T10:30:00", ["2026-09-01T10:30:00"]))
checa("slot oferecido E livre -> agenda", escrita.agendar.await_count, 1)
checa("  e conclui", concluir.await_count, 1)
checa("  sem fallback", fb.await_count, 0)
checa("  SEMPRE com lead_id (impede lead duplicado)",
      escrita.agendar.await_args.kwargs.get("lead_id"), 42)

_, fb, _, _, escrita = asyncio.run(tenta_agendar("2026-09-09T03:00:00", ["2026-09-01T10:30:00"]))
checa("slot que o LLM INVENTOU -> fallback, sem escrita", escrita.agendar.await_count, 0)
checa("  e transfere", fb.await_count, 1)

_, fb, reoferta, _, escrita = asyncio.run(tenta_agendar("2026-09-01T10:30:00", []))
checa("slot oferecido mas TOMADO (corrida) -> não escreve", escrita.agendar.await_count, 0)
checa("  reoferta a grade em vez de transferir", reoferta.await_count, 1)
checa("  e NÃO chama fallback", fb.await_count, 0)


# ==========================================================================================
print("\n5) Precedência no webhook — um dono por mensagem")


async def dono(etapa_ou_none):
    estado = _estado(etapa_ou_none) if etapa_ou_none else None
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)):
        return await fluxo.agente_e_dono("5583999998888", _db())


checa("estado ATIVO -> agente é dono", asyncio.run(dono(ETAPA_Q_AGUARDANDO_ANO)), True)
checa("estado concluido -> NÃO é dono", asyncio.run(dono(ETAPA_Q_CONCLUIDO)), False)
checa("estado transferido -> NÃO é dono", asyncio.run(dono(ETAPA_Q_TRANSFERIDO)), False)
checa("sem estado -> NÃO é dono", asyncio.run(dono(None)), False)


async def trata(etapa_ou_none):
    estado = _estado(etapa_ou_none) if etapa_ou_none else None
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)), \
         patch.object(fluxo, "_fatos", new=AsyncMock(return_value=("c", {}))), \
         patch.object(fluxo, "_historico", new=AsyncMock(return_value=[])), \
         patch.object(fluxo, "_reuniao", new=AsyncMock(return_value=None)), \
         patch.object(fluxo, "send_nat_message", new=AsyncMock(return_value=True)), \
         patch.object(fluxo.llm, "conversar", new=AsyncMock(return_value=_resp(cumprida=False))):
        return await fluxo.processar_texto("5583999998888", "oi", "wamid.X", _db())


checa("com estado ativo, processar_texto devolve True (fluxo velho não roda)",
      asyncio.run(trata(ETAPA_Q_AGUARDANDO_ANO)), True)
checa("sem estado, devolve False (fluxo velho segue como sempre)",
      asyncio.run(trata(None)), False)
checa("em etapa terminal, devolve False", asyncio.run(trata(ETAPA_Q_CONCLUIDO)), False)


# ==========================================================================================
print("\n6) Idempotência — reentrega da Meta não avança nada duas vezes")

e = _estado(ETAPA_Q_AGUARDANDO_ANO)
asyncio.run(roda(e, _resp(extraido={"ano_conclusao": "2019"}), wa_id="wamid.DUP"))
etapa_apos_primeira = e.etapa
_, envio2, ia2, _ = asyncio.run(roda(e, _resp(extraido={"ano_conclusao": "OUTRO"}),
                                     wa_id="wamid.DUP"))
checa("mesma wa_message_id: etapa não anda de novo", e.etapa, etapa_apos_primeira)
checa("  e o LLM NÃO é chamado", ia2.await_count, 0)
checa("  e nada é enviado", envio2.await_count, 0)


# ==========================================================================================
print("\n7) Gatilho e lembrete")

from app.qualificacao_gatilho import ESPERA, wa_id_de  # noqa: E402

checa("espera de 5 min", ESPERA, timedelta(minutes=5))
checa("wa_id com DDI", wa_id_de("11999998888"), "5511999998888")
checa("wa_id já com DDI não duplica", wa_id_de("5511999998888"), "5511999998888")
checa("telefone vazio -> vazio", wa_id_de(""), "")


async def agenda_lembrete(dias):
    r = _reuniao(dias=dias)
    with patch("app.nat_scheduler.agendar", new=AsyncMock()) as spy:
        await fluxo.agendar_lembrete(r, _db())
    return r, spy


r, spy = asyncio.run(agenda_lembrete(2))
checa("reunião futura -> lembrete agendado", spy.await_count, 1)
checa("  exatamente 30 min antes",
      spy.await_args.args[2], r.slot_inicio - timedelta(minutes=30))
checa("  com o kind do lembrete", spy.await_args.args[0], "lembrete_reuniao")

_, spy = asyncio.run(agenda_lembrete(-1))
checa("reunião NO PASSADO -> não agenda (não manda lembrete atrasado)", spy.await_count, 0)


async def executa_lembrete(reuniao):
    db = _db()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=reuniao)))
    with patch.object(fluxo, "send_nat_message", new=AsyncMock(return_value=True)) as spy, \
         patch.object(fluxo, "_corpo_do_template", new=AsyncMock(return_value="corpo")):
        await fluxo.lembrete_reuniao(
            {"contact_wa_id": "5583999998888",
             "payload": json.dumps({"agendamento_id": 7})}, db)
    return spy


from app.models import PASSO_AGENDADO  # noqa: E402

ok = _reuniao(dias=1)
ok.passo = PASSO_AGENDADO
checa("reunião viva -> lembrete enviado", asyncio.run(executa_lembrete(ok)).await_count, 1)

checa("reunião SUMIU -> não envia", asyncio.run(executa_lembrete(None)).await_count, 0)

morta = _reuniao(dias=1)
morta.passo = "falhou"
checa("reunião não está mais agendada -> não envia",
      asyncio.run(executa_lembrete(morta)).await_count, 0)

passada = _reuniao(dias=-1)
passada.passo = PASSO_AGENDADO
checa("reunião já começou -> não envia atrasado",
      asyncio.run(executa_lembrete(passada)).await_count, 0)


# ==========================================================================================
print("\n8) Guard — falha fechada em todas as travas")

CORTE = datetime(2026, 8, 1)
DEPOIS = datetime(2026, 8, 20)
ANTES = datetime(2026, 7, 1)


async def admite(cfg, referencia, envios=0):
    db = _db()
    with patch.object(guard, "_carregar_config", new=AsyncMock(return_value=cfg)), \
         patch.object(guard, "contar_envios_ultima_hora", new=AsyncMock(return_value=envios)):
        return await guard.qualificacao_pode_iniciar(referencia, db)


def _cfg(enabled=True, corte=CORTE, teto=20):
    return NatConfig(id=1, nat_enabled=False, max_envios_hora=teto,
                     qualificacao_enabled=enabled, qualificacao_start_at=corte)


checa("config ausente -> bloqueia", asyncio.run(admite(None, DEPOIS))[0], False)
checa("qualificacao_enabled=false -> bloqueia",
      asyncio.run(admite(_cfg(enabled=False), DEPOIS))[0], False)
checa("sem corte de data -> bloqueia (ligado mas sem atuar é o pior desfecho)",
      asyncio.run(admite(_cfg(corte=None), DEPOIS))[0], False)
checa("sem data de referência -> bloqueia", asyncio.run(admite(_cfg(), None))[0], False)
checa("lead ANTERIOR ao corte -> bloqueia (base de 3.680 leads não entra)",
      asyncio.run(admite(_cfg(), ANTES))[0], False)
checa("teto por hora estourado -> bloqueia",
      asyncio.run(admite(_cfg(teto=5), DEPOIS, envios=5))[0], False)
checa("tudo em ordem -> libera", asyncio.run(admite(_cfg(), DEPOIS))[0], True)

boom = AsyncMock(side_effect=RuntimeError("banco caiu"))
with patch.object(guard, "_carregar_config", new=boom):
    checa("exceção inesperada -> bloqueia (falha FECHADA)",
          asyncio.run(guard.qualificacao_pode_iniciar(DEPOIS, _db()))[0], False)


async def envia(cfg, estado, envios=0):
    db = _db()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=estado)))
    with patch.object(guard, "_carregar_config", new=AsyncMock(return_value=cfg)), \
         patch.object(guard, "contar_envios_ultima_hora", new=AsyncMock(return_value=envios)):
        return await guard.qualificacao_pode_atuar(MagicMock(wa_id="5583999998888"), db)


checa("envio sem estado -> bloqueia", asyncio.run(envia(_cfg(), None))[0], False)
checa("envio em etapa terminal -> bloqueia",
      asyncio.run(envia(_cfg(), _estado(ETAPA_Q_CONCLUIDO)))[0], False)
checa("envio em etapa ativa -> libera",
      asyncio.run(envia(_cfg(), _estado(ETAPA_Q_AGUARDANDO_ANO)))[0], True)
checa("o teto vale também no envio",
      asyncio.run(envia(_cfg(teto=1), _estado(ETAPA_Q_AGUARDANDO_ANO), envios=1))[0], False)

checa("guard do agente NÃO olha nat_enabled (fluxos independentes)",
      asyncio.run(envia(NatConfig(id=1, nat_enabled=False, max_envios_hora=20,
                                  qualificacao_enabled=True, qualificacao_start_at=CORTE),
                        _estado(ETAPA_Q_AGUARDANDO_ANO)))[0], True)


# ==========================================================================================
print("\n9) Horário comercial (09h00–18h30) — só a ABERTURA respeita")

from datetime import datetime as _dt  # noqa: E402
from app.nat_guard import dentro_horario_comercial, proximo_horario_util  # noqa: E402

SEG, SEX, SAB = (2026, 8, 24), (2026, 8, 28), (2026, 8, 29)
for rot, quando, esperado in [
    ("seg 08:59 fora", _dt(*SEG, 8, 59), False),
    ("seg 09:00 dentro", _dt(*SEG, 9, 0), True),
    ("seg 18:29 dentro", _dt(*SEG, 18, 29), True),
    ("seg 18:30 FORA (exclusive)", _dt(*SEG, 18, 30), False),
    ("seg 22:00 fora — hora de pico da LP", _dt(*SEG, 22, 0), False),
    ("sáb 14:00 fora", _dt(*SAB, 14, 0), False),
]:
    checa(rot, dentro_horario_comercial(quando), esperado)

for rot, quando, esperado in [
    ("madrugada de terça -> 09h do MESMO dia", _dt(2026, 8, 25, 2, 0), _dt(2026, 8, 25, 9, 0)),
    ("seg 22h -> terça 09h", _dt(*SEG, 22, 0), _dt(2026, 8, 25, 9, 0)),
    ("sexta 19h -> SEGUNDA 09h", _dt(*SEX, 19, 0), _dt(2026, 8, 31, 9, 0)),
    ("sábado -> segunda 09h", _dt(*SAB, 14, 0), _dt(2026, 8, 31, 9, 0)),
    ("dentro da janela devolve o próprio instante", _dt(*SEG, 10, 0), _dt(*SEG, 10, 0)),
]:
    checa(rot, proximo_horario_util(quando), esperado)


async def abre_em(agora):
    """iniciar_qualificacao com o relógio do ciclo controlado."""
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=None)), \
         patch("app.nat_scheduler.agendar", new=AsyncMock()) as reagenda, \
         patch.object(fluxo.guard, "qualificacao_pode_iniciar",
                      new=AsyncMock(return_value=(True, "ok"))) as admissao:
        await fluxo.iniciar_qualificacao(
            {"contact_wa_id": "5583999998888", "agora": agora,
             "payload": json.dumps({"lead_id": 1, "origem": ORIGEM_LP})}, _db())
    return reagenda, admissao


r, adm = asyncio.run(abre_em(_dt(*SEG, 2, 0)))
checa("abertura às 02h NÃO chega à admissão", adm.await_count, 0)
checa("  e é empurrada para as 09h", r.await_args.args[2], _dt(*SEG, 9, 0))
checa("  pelo mesmo kind", r.await_args.args[0], "iniciar_qualificacao")

r, adm = asyncio.run(abre_em(_dt(*SEX, 19, 0)))
checa("sexta 19h -> segunda 09h", r.await_args.args[2], _dt(2026, 8, 31, 9, 0))

r, adm = asyncio.run(abre_em(_dt(*SEG, 10, 0)))
checa("dentro da janela NÃO reagenda", r.await_count, 0)
checa("  e segue para a admissão", adm.await_count, 1)


# ==========================================================================================
print("\n10) Encerramento por inatividade — ETAPA_Q_ENCERRADO deixa de ser constante morta")

from app.models import ETAPA_Q_ENCERRADO  # noqa: E402

checa("72h é a régua", fluxo.INATIVIDADE_ENCERRA, timedelta(hours=72))
checa("encerrado NÃO é etapa ativa", ETAPA_Q_ENCERRADO in ETAPAS_QUALIFICACAO_ATIVAS, False)


async def encerra(estado):
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)):
        await fluxo.encerrar_inativo({"contact_wa_id": "5583999998888"}, _db())
    return estado


e = asyncio.run(encerra(_estado(ETAPA_Q_AGUARDANDO_ANO)))
checa("etapa ativa + 72h -> encerrado", e.etapa, ETAPA_Q_ENCERRADO)
checa("  com motivo", e.encerrado_motivo, fluxo.MOTIVO_INATIVIDADE)
checa("  e carimbo de quando", e.encerrado_em is not None, True)

e = asyncio.run(encerra(_estado(ETAPA_Q_CONCLUIDO)))
checa("já concluído NÃO é encerrado", e.etapa, ETAPA_Q_CONCLUIDO)

e = asyncio.run(encerra(_estado(ETAPA_Q_TRANSFERIDO)))
checa("já transferido NÃO é encerrado", e.etapa, ETAPA_Q_TRANSFERIDO)

with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=None)):
    asyncio.run(fluxo.encerrar_inativo({"contact_wa_id": "5583999998888"}, _db()))
checa("sem estado: sai em silêncio, sem levantar", True, True)

# resposta do lead REAGENDA o encerramento
e = asyncio.run(encerra(_estado(ETAPA_Q_AGUARDANDO_ANO)))  # já encerrado
_, envio, ia, _ = asyncio.run(roda(e, _resp(), wa_id="wamid.POS"))
checa("resposta DEPOIS de encerrado não reabre (LLM não é chamado)", ia.await_count, 0)
checa("  e nada é enviado", envio.await_count, 0)

e2 = _estado(ETAPA_Q_AGUARDANDO_ANO)
with patch.object(fluxo, "_agendar_encerramento", new=AsyncMock()) as rearma:
    asyncio.run(roda(e2, _resp(extraido={"ano_conclusao": "2019"}), wa_id="wamid.VIVO"))
checa("resposta em etapa ativa REARMA o relógio", rearma.await_count, 1)


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} teste(s) falharam:")
    for f in falhas:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ Todos os testes passaram. Nada enviado, nada gravado, nenhuma chamada ao LLM.")
