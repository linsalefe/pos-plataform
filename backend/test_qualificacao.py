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
  8. o 9º dígito: os quatro formatos do mesmo telefone casam (2b)
  9. humano assume -> agente silencia; e a mensagem da Nat NÃO dispara isso (2c)
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
                        ETAPAS_QUALIFICACAO_VALIDAS, KIND_RESPONDER_PENDENTE,
                        NatConfig, NatQualificacaoState,
                        ORIGENS_QUALIFICACAO_VALIDAS,
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
checa("JSON válido passa", llm._validar(VALIDO)[0]["dado_extraido"], {"ano_conclusao": "2019"})
checa("cercado em markdown passa",
      llm._validar("```json\n" + VALIDO + "\n```")[0]["mensagem"], "Oi!")
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
    resultado, motivo = llm._validar(bruto)
    checa(f"{rotulo} -> None", resultado, None)
    checa(f"{rotulo} -> tem motivo", bool(motivo), True)

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
print("\n2b) O 9º dígito — o mesmo humano escrito de quatro jeitos")

from app import telefone as tel
from app.models import Contact

# Os QUATRO formatos do mesmo número colapsam no mesmo par. É a igualdade que importa:
# a Exact guarda 5586994169303, o WhatsApp entrega 558694169303, e antes disto o agente
# tratava os dois como pessoas diferentes.
PAR = ("5586994169303", "558694169303")
for formato in ("5586994169303", "558694169303", "86994169303", "8694169303"):
    checa(f"variantes de {formato}", tel.variantes_wa_id(formato), PAR)

checa("a ordem é estável (13 dígitos primeiro)", tel.variantes_wa_id("8694169303")[0],
      "5586994169303")
checa("os quatro formatos dão a MESMA chave de conjunto",
      len({tel.chave_telefone(f) for f in
           ("5586994169303", "558694169303", "86994169303", "8694169303")}), 1)

# Fixo NÃO ganha um 9 — 86 2234-5678 com 9 na frente é o celular de OUTRA pessoa.
checa("fixo não vira celular", tel.variantes_wa_id("8622345678"), ("558622345678",))
# Estrangeiro passa inteiro: não sabemos ler o plano de numeração de lá.
checa("estrangeiro intocado", tel.variantes_wa_id("447834239129"), ("447834239129",))
checa("estrangeiro não gera chave de conjunto", tel.chave_telefone("447834239129"), "")
checa("lixo não casa com nada", (tel.variantes_wa_id(""), tel.variantes_wa_id(None),
                                 tel.chave_telefone("abc")), ((), (), ""))


class _Scalars(list):
    def first(self):
        return self[0] if self else None


class _DbFiltrante:
    """Dublê que executa o `IN` de verdade: lê os binds do statement e filtra.

    Um mock que devolve tudo passaria mesmo se o código tivesse voltado para `==`. Este
    filtra, então o teste falha se a tolerância sumir.
    """

    def __init__(self, linhas):
        self.linhas = linhas

    async def execute(self, stmt):
        # `in_` compila para um bind expansível, cujo valor é a LISTA inteira.
        valores = set()
        for bruto in stmt.compile().params.values():
            valores.update(bruto) if isinstance(bruto, (list, tuple)) else valores.add(bruto)
        casadas = [o for o in self.linhas
                   if getattr(o, "contact_wa_id", None) in valores
                   or getattr(o, "wa_id", None) in valores]
        r = MagicMock()
        r.scalars.return_value = _Scalars(casadas)
        r.all.return_value = casadas
        r.scalar_one_or_none.return_value = casadas[0] if casadas else None
        return r


def _est(wa, id=1):
    e = NatQualificacaoState(contact_wa_id=wa, exact_lead_id=1, origem=ORIGEM_LP,
                             etapa=ETAPA_Q_AGUARDANDO_ANO)
    e.id = id
    return e


# O DEFEITO, nos dois sentidos. O estado nasce da chave montada do telefone do lead
# (13 dígitos, qualificacao_gatilho.wa_id_de) e o inbound chega com 12 — ou o contrário.
achado = asyncio.run(fluxo.estado_de("558694169303", _DbFiltrante([_est("5586994169303")])))
checa("estado gravado com 13 dígitos é achado pelo inbound de 12",
      achado.contact_wa_id if achado else None, "5586994169303")

achado = asyncio.run(fluxo.estado_de("5586994169303", _DbFiltrante([_est("558694169303")])))
checa("e o caminho inverso também", achado.contact_wa_id if achado else None,
      "558694169303")

achado = asyncio.run(fluxo.estado_de("5511918330251", _DbFiltrante([_est("5586994169303")])))
checa("número de OUTRA pessoa continua não casando", achado, None)

# Duas threads do mesmo humano: escolha determinística, e nada de MultipleResultsFound.
duas = _DbFiltrante([_est("558694169303", id=9), _est("5586994169303", id=2)])
achado = asyncio.run(fluxo.estado_de("8694169303", duas))
checa("com as duas threads, escolhe a de 13 dígitos, sem levantar",
      achado.contact_wa_id if achado else None, "5586994169303")

# O `abrir()` abortava com "não existe em contacts" — mentira: existia, na outra grafia.
c = Contact(wa_id="558694169303", name="Raimundo Nonato")
c.id = 1
achado = asyncio.run(fluxo._contato_de("5586994169303", _DbFiltrante([c])))
checa("contato é achado na grafia gêmea", achado.name if achado else None,
      "Raimundo Nonato")
checa("contato inexistente continua None",
      asyncio.run(fluxo._contato_de("5511918330251", _DbFiltrante([c]))), None)


# ==========================================================================================
print("\n2c) Humano assume, agente silencia")

from app import routes as rotas_hub

MOTIVO_SDR = fluxo.MOTIVO_ASSUMIDO_SDR
MOTIVO_MANUAL = fluxo.MOTIVO_OUTBOUND_MANUAL


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _DbEstado(_DbFiltrante):
    """_DbFiltrante + flush/commit/begin_nested, para exercitar `silenciar` de ponta a ponta.

    `begin_nested` precisa ser um gerenciador de contexto async de verdade: a trava roda
    DENTRO de um SAVEPOINT (um IntegrityError deixaria a transação abortada e o commit do
    envio do SDR falharia junto), e um dublê sem ele mandaria o teste pelo `except` — que é
    exatamente o caminho que NÃO se quer exercitar aqui.
    """

    def begin_nested(self):
        return _Savepoint()

    async def flush(self):
        pass

    async def commit(self):
        pass


def _sdr(id=3, nome="Thobias"):
    u = MagicMock()
    u.id, u.name = id, nome
    return u


# --- caminho 1: o botão "Assumir conversa" ------------------------------------------
e = _est("5583999998888")
anterior = asyncio.run(fluxo.silenciar("5583999998888", MOTIVO_SDR, _DbEstado([e]),
                                       quem_id=3, quem_nome="Thobias"))
checa("botão: devolve a etapa que o agente deixou", anterior, ETAPA_Q_AGUARDANDO_ANO)
checa("botão: etapa vai para transferido_humano", e.etapa, ETAPA_Q_TRANSFERIDO)
checa("botão: motivo é o literal parseável", e.transferido_motivo, MOTIVO_SDR)
checa("botão: quem clicou fica registrado",
      (e.dados_extras or {}).get("assumido_por"), {"id": 3, "nome": "Thobias"})
checa("botão: a etapa saiu das ATIVAS — a Nat cala na hora",
      e.etapa in ETAPAS_QUALIFICACAO_ATIVAS, False)

# Idempotente: clicar de novo não sobrescreve quem assumiu primeiro.
de_novo = asyncio.run(fluxo.silenciar("5583999998888", MOTIVO_SDR, _DbEstado([e]),
                                      quem_id=99, quem_nome="Outro"))
checa("botão: segunda vez não faz nada", de_novo, None)
checa("botão: e não rouba o crédito de quem assumiu primeiro",
      (e.dados_extras or {}).get("assumido_por")["nome"], "Thobias")

checa("sem estado nenhum, silenciar é no-op",
      asyncio.run(fluxo.silenciar("5511918330251", MOTIVO_SDR, _DbEstado([]))), None)

# Tolerante ao 9º dígito: a tela pode mandar uma grafia e o estado estar na outra.
e2 = _est("5586994169303")
checa("silenciar acha o estado na grafia gêmea",
      asyncio.run(fluxo.silenciar("558694169303", MOTIVO_SDR, _DbEstado([e2]))),
      ETAPA_Q_AGUARDANDO_ANO)


# --- caminho 2: a trava automática do envio manual ----------------------------------
e3 = _est("5583999998888")
asyncio.run(rotas_hub._silenciar_agente_apos_envio_manual(
    "5583999998888", _sdr(), _DbEstado([e3])))
checa("trava: SDR digitou -> agente silenciado", e3.etapa, ETAPA_Q_TRANSFERIDO)
checa("trava: motivo distingue do botão", e3.transferido_motivo, MOTIVO_MANUAL)
checa("trava: registra quem digitou",
      (e3.dados_extras or {}).get("assumido_por"), {"id": 3, "nome": "Thobias"})


class _DbQuebrado(_DbEstado):
    async def execute(self, stmt):
        raise RuntimeError("banco caiu")


# A mensagem do SDR JÁ foi para a Meta quando a trava roda: falhar aqui devolveria erro
# para um envio que aconteceu, e o SDR mandaria de novo.
asyncio.run(rotas_hub._silenciar_agente_apos_envio_manual("x", _sdr(), _DbQuebrado([])))
checa("trava: erro no banco NÃO derruba o envio do SDR", True, True)


# --- o INVERSO: a mensagem da própria Nat não dispara a trava -----------------------
# A garantia é ESTRUTURAL, não uma checagem que possa esquecer um caso: `nat_sender` é o
# único ponto por onde envio do agente passa, e ele não chama a trava. Este teste prova
# comportamento, não leitura de código — manda pela Nat e confere que o estado NÃO mudou.
e4 = _est("5583999998888")
db_nat = _DbEstado([e4])
with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=e4)), \
     patch("app.nat_sender.send_nat_message", new=AsyncMock(return_value=True)):
    from app.nat_sender import send_nat_message as _envio_nat
    asyncio.run(_envio_nat("5583999998888", "nat_boasvindas", db_nat))
checa("INVERSO: envio da Nat não silencia o agente", e4.etapa, ETAPA_Q_AGUARDANDO_ANO)
checa("INVERSO: e não inventa motivo de transferência", e4.transferido_motivo, None)

# E a prova estrutural, que é a que não pode ser esquecida num refactor: o módulo de envio
# da Nat NÃO conhece a trava. Se alguém um dia importar `silenciar` lá dentro, este teste
# cai — e é para cair.
_fonte_nat = open("app/nat_sender.py", encoding="utf-8").read()
checa("INVERSO: nat_sender não importa a trava nem `silenciar`",
      ("_silenciar_agente_apos_envio_manual" in _fonte_nat) or ("silenciar" in _fonte_nat),
      False)

# O disparo em massa REUSA a trava, não uma cópia. Duas implementações da regra "humano
# falou, agente cala" divergiriam, e o lado que divergisse é o que deixa o robô responder
# por cima.
_fonte_bulk = open("app/exact_routes.py", encoding="utf-8").read()
checa("massa: bulk_send_template importa a trava de routes.py",
      "from app.routes import _silenciar_agente_apos_envio_manual" in _fonte_bulk, True)
checa("massa: e a chama por contato dentro do laço",
      "_silenciar_agente_apos_envio_manual(wa_id, current_user, db)" in _fonte_bulk, True)
checa("massa: sem cópia da regra (nenhum def novo)",
      _fonte_bulk.count("async def _silenciar_agente_apos_envio_manual"), 0)


# ==========================================================================================
print("\n3) Máquina de etapas — só código muda etapa")

# Modelo e banco em LOCKSTEP. Era `len(...) == 9`, um número mágico que não dizia contra o
# quê. Agora compara com a tupla que a migração usa para montar o CHECK — se alguém
# acrescentar etapa no modelo sem migrar (ou migrar sem tocar no modelo), o INSERT falharia
# em produção e este teste falha antes.
from migrate_espontaneo import ETAPAS as _ETAPAS_DO_CHECK, ORIGENS as _ORIGENS_DO_CHECK

checa("as etapas do modelo batem com o CHECK da migração",
      ETAPAS_QUALIFICACAO_VALIDAS, frozenset(_ETAPAS_DO_CHECK))
checa("e são 13 depois do espontâneo", len(ETAPAS_QUALIFICACAO_VALIDAS), 13)
checa("as origens também", ORIGENS_QUALIFICACAO_VALIDAS, frozenset(_ORIGENS_DO_CHECK))

# As esp_* existem no banco mas NÃO são ativas ainda, e a ausência é o que impede o webhook
# de entregar a mensagem a um fluxo sem missão — o lead ficaria mudo. Entram junto com as
# missões, no Bloco A. Este teste é o alarme de quem tentar ligar uma coisa sem a outra.
_ESP = {e for e in ETAPAS_QUALIFICACAO_VALIDAS if e.startswith("esp_")}
checa("as 4 etapas do espontâneo estão no CHECK", len(_ESP), 4)
checa("mas NENHUMA é ativa enquanto não houver missão",
      sorted(_ESP & ETAPAS_QUALIFICACAO_ATIVAS), [])
checa("etapas ativas não incluem concluido", ETAPA_Q_CONCLUIDO in ETAPAS_QUALIFICACAO_ATIVAS,
      False)
checa("etapas ativas não incluem transferido",
      ETAPA_Q_TRANSFERIDO in ETAPAS_QUALIFICACAO_ATIVAS, False)
checa("toda etapa ativa tem missão",
      sorted(ETAPAS_QUALIFICACAO_ATIVAS - set(fluxo.MISSOES)), [])


async def roda(estado, resposta, *, reuniao=None, ofertados=None, wa_id="wamid.1"):
    """Uma passada de processar_texto com LLM e envio mockados.

    UM espião para os DOIS caminhos de saída: a fala normal passa por `enviar_nat`
    (que devolve `(saiu, motivo)` desde o P0-B) e a despedida do `_fallback` passa por
    `send_nat_message`. Espionar só um deixaria metade dos envios invisível ao teste.
    """
    envio = AsyncMock(return_value=True)

    async def _via_envio(*a, **k):
        await envio(*a, **k)
        return True, "ok"

    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)), \
         patch.object(fluxo, "_fatos", new=AsyncMock(return_value=("ctx", ofertados or {}))), \
         patch.object(fluxo, "_historico", new=AsyncMock(return_value=[])), \
         patch.object(fluxo, "_reuniao", new=AsyncMock(return_value=reuniao)), \
         patch.object(fluxo, "_notificar", new=AsyncMock()), \
         patch.object(fluxo, "agendar_lembrete", new=AsyncMock()) as lembrete, \
         patch.object(fluxo.llm, "conversar", new=AsyncMock(return_value=resposta)) as ia, \
         patch.object(fluxo, "send_nat_message", new=envio), \
         patch.object(fluxo, "enviar_nat", new=AsyncMock(side_effect=_via_envio)):
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


print("\n   P0-B — a recusa de envio nunca mais é silêncio")
# Até 26/08 `_enviar` devolvia bool e ninguém lia: recusa do guard = turno que termina
# normalmente, sem mensagem, sem fallback, sem notificação e sem exceção. Matou 4 mensagens
# do 5583988046720 e 2 do 5582998307979 em 25/08, sem deixar rastro em tabela nenhuma.
#
# A recusa tem DUAS naturezas e o teste guarda a distinção: o teto passa sozinho (adia), o
# resto não passa (transfere).

def _falar_com_recusa(motivo, etapa=ETAPA_Q_AGUARDANDO_ANO):
    e = _estado(etapa)
    agendou = AsyncMock()
    with patch.object(fluxo, "_enviar", new=AsyncMock(return_value=(False, motivo))), \
         patch.object(fluxo, "nat_agendar", new=agendou), \
         patch.object(fluxo, "send_nat_message", new=AsyncMock(return_value=True)):
        seguiu = asyncio.run(fluxo._falar(e, "oi", _db()))
    return e, seguiu, agendou

e, seguiu, agendou = _falar_com_recusa(guard.MOTIVO_TETO + " (20/20)")
checa("teto -> NÃO transfere", e.etapa, ETAPA_Q_AGUARDANDO_ANO)
checa("  reenfileira a fala", agendou.await_count, 1)
checa("  no kind certo", agendou.await_args.args[0], KIND_RESPONDER_PENDENTE)
checa("  com o texto no payload", agendou.await_args.args[3], {"texto": "oi"})
checa("  e avisa quem chamou que não saiu", seguiu, False)

e, seguiu, agendou = _falar_com_recusa("janela de 24h fechada")
checa("recusa definitiva -> transferido_humano", e.etapa, ETAPA_Q_TRANSFERIDO)
checa("  motivo cita o envio", "envio recusado" in (e.transferido_motivo or ""), True)
checa("  NÃO reenfileira", agendou.await_count, 0)

# ------------------------------------------------------------------------------------------
# A ARESTA DAS DUAS FALAS FORA DE ORDEM (26/08)
# ------------------------------------------------------------------------------------------
# Entre agendar a fala adiada e ela disparar passam 10 min, e a pessoa escreve de novo
# justamente porque não recebeu resposta. O turno novo roda na etapa JÁ AVANÇADA e, se o teto
# tiver liberado (contagem móvel de 1h), fala AGORA — e a fala velha dispararia depois,
# perguntando o passo anterior. O cancelamento é o que impede isso.
e = _estado(ETAPA_Q_AGUARDANDO_ANO)
cancelou = AsyncMock()
with patch.object(fluxo, "_enviar", new=AsyncMock(return_value=(True, "ok"))), \
     patch.object(fluxo, "nat_cancelar", new=cancelou):
    seguiu = asyncio.run(fluxo._falar(e, "oi", _db()))
checa("fala que SAI descarta a fala adiada na fila", cancelou.await_count, 1)
checa("  no kind certo", cancelou.await_args.args[0], KIND_RESPONDER_PENDENTE)
checa("  e o turno segue normalmente", seguiu, True)

# Quando o turno novo TAMBÉM é recusado pelo teto, quem resolve é o agendador: `nat_agendar`
# cancela o pendente do mesmo (kind, contato) antes de inserir. Só o texto mais novo fica.
e, seguiu, agendou = _falar_com_recusa(guard.MOTIVO_TETO + " (20/20)")
checa("fala adiada de novo -> reagenda (o agendador substitui, não acumula)",
      agendou.await_count, 1)

# Transferir também limpa a fila: depois da despedida, uma fala velha só pode piorar.
e = _estado(ETAPA_Q_AGUARDANDO_ANO)
cancelou = AsyncMock()
with patch.object(fluxo, "send_nat_message", new=AsyncMock(return_value=True)), \
     patch.object(fluxo, "_notificar", new=AsyncMock()), \
     patch.object(fluxo, "nat_cancelar", new=cancelou):
    asyncio.run(fluxo._fallback(e, "motivo qualquer", _db()))
checa("transferência descarta a fala adiada", cancelou.await_count, 1)

# Higiene não derruba turno: cancelamento que explode vira log, não exceção.
e = _estado(ETAPA_Q_AGUARDANDO_ANO)
with patch.object(fluxo, "_enviar", new=AsyncMock(return_value=(True, "ok"))), \
     patch.object(fluxo, "nat_cancelar", new=AsyncMock(side_effect=RuntimeError("banco"))):
    seguiu = asyncio.run(fluxo._falar(e, "oi", _db()))
checa("cancelamento que falha NÃO derruba o turno", seguiu, True)


# O handler da fala adiada relê o estado: em 10 min um humano pode ter assumido.
for etapa_terminal in (ETAPA_Q_TRANSFERIDO, ETAPA_Q_CONCLUIDO):
    e = _estado(etapa_terminal)
    envio_h = AsyncMock(return_value=(True, "ok"))
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=e)), \
         patch.object(fluxo, "_enviar", new=envio_h):
        try:
            asyncio.run(fluxo.responder_pendente(
                {"contact_wa_id": "5583999998888",
                 "payload": json.dumps({"texto": "oi"})}, _db()))
            ignorou = False
        except fluxo.AcaoIgnorada:
            ignorou = True
    checa(f"fala adiada NÃO ressuscita conversa em '{etapa_terminal}'", ignorou, True)
    checa("  e nada foi enviado", envio_h.await_count, 0)


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


class _SessaoDoAgendamento:
    """A `async_session()` que o P0-A abre só para o `fluxo.agendar`. Conta abre/fecha."""
    abertas = 0
    fechadas = 0

    async def __aenter__(self):
        _SessaoDoAgendamento.abertas += 1
        return self

    async def __aexit__(self, *a):
        _SessaoDoAgendamento.fechadas += 1
        return False


async def tenta_agendar(slot_id, livres, ofertados=OFERTADOS, reuniao_explode=False):
    e = _estado(ETAPA_Q_ESCOLHENDO_SLOT)
    disp = MagicMock()
    disp.slots_livres = AsyncMock(return_value=[MagicMock(id=s) for s in livres])
    fluxo_ag = MagicMock()
    fluxo_ag.agendar = AsyncMock(return_value=MagicMock(agendamento_id=99))
    modulo = MagicMock(agendar=fluxo_ag, disponibilidade=disp)
    _SessaoDoAgendamento.abertas = _SessaoDoAgendamento.fechadas = 0
    db_webhook = _db()
    reuniao_mock = (AsyncMock(side_effect=RuntimeError("banco caiu depois do commit"))
                    if reuniao_explode else AsyncMock(return_value=_reuniao()))
    with patch.dict("sys.modules", {"app.agendamento": modulo}), \
         patch("app.database.async_session", new=lambda: _SessaoDoAgendamento()), \
         patch.object(fluxo, "_fallback", new=AsyncMock()) as fb, \
         patch.object(fluxo, "_ofertar_agenda", new=AsyncMock()) as reoferta, \
         patch.object(fluxo, "_enviar", new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(fluxo, "_concluir", new=AsyncMock()) as concluir, \
         patch.object(fluxo, "_reuniao", new=reuniao_mock):
        await fluxo._agendar(e, _resp(acao="agendar_slot",
                                      extraido={"slot_id": slot_id}), ofertados, db_webhook)
    return e, fb, reoferta, concluir, fluxo_ag, db_webhook


_, fb, _, concluir, escrita, db_webhook = asyncio.run(
    tenta_agendar("2026-09-01T10:30:00", ["2026-09-01T10:30:00"]))
checa("slot oferecido E livre -> agenda", escrita.agendar.await_count, 1)
checa("  e conclui", concluir.await_count, 1)
checa("  sem fallback", fb.await_count, 0)
checa("  SEMPRE com lead_id (impede lead duplicado)",
      escrita.agendar.await_args.kwargs.get("lead_id"), 42)

# ------------------------------------------------------------------------------------------
# P0-A — `agendar` roda em SESSÃO PRÓPRIA (26/08/2026)
# ------------------------------------------------------------------------------------------
# `agendar._marcar` commita a cada passo, de propósito: é o que deixa a faxina enxergar um
# box nosso pendurado. Recebendo a sessão do WEBHOOK, esse commit fechava o savepoint e a
# instrução seguinte levantava InvalidRequestError — 3× com a Fabiana em 25/08, e seria em
# 100% dos agendamentos do agente. A sessão própria devolve ao `agendar` a transação que ele
# espera SEM tocar no `_marcar`, e portanto sem mexer no caminho da LP.
checa("agendar recebe sessão PRÓPRIA, não a do webhook",
      escrita.agendar.await_args.args[0] is db_webhook, False)
checa("  e ela é uma sessão de verdade, aberta pelo async_session",
      isinstance(escrita.agendar.await_args.args[0], _SessaoDoAgendamento), True)
checa("  aberta uma vez", _SessaoDoAgendamento.abertas, 1)
checa("  e FECHADA antes do resto do turno (não fica presa no pool)",
      _SessaoDoAgendamento.fechadas, 1)

_, fb, _, _, escrita, _ = asyncio.run(tenta_agendar("2026-09-09T03:00:00", ["2026-09-01T10:30:00"]))
checa("slot que o LLM INVENTOU -> fallback, sem escrita", escrita.agendar.await_count, 0)
checa("  e transfere", fb.await_count, 1)
# A conexão extra só nasce no instante do agendamento. Abri-la no começo do turno dobraria a
# retenção — o turno já segura a do webhook durante `llm.conversar` (3-5s medidos) — e o pool
# acabou de ser dimensionado para a retenção de UMA (P1-A).
checa("  e NENHUMA sessão foi aberta (o turno não chegou a agendar)",
      _SessaoDoAgendamento.abertas, 0)

_, fb, reoferta, _, escrita, _ = asyncio.run(tenta_agendar("2026-09-01T10:30:00", []))
checa("slot que saiu da grade -> nenhuma sessão aberta", _SessaoDoAgendamento.abertas, 0)

# ------------------------------------------------------------------------------------------
# O MODO DE FALHA RESIDUAL DO P0-A — exceção DEPOIS do agendamento commitado
# ------------------------------------------------------------------------------------------
# A sessão própria commita; a reunião existe na Exact e em `agendamentos`. Se o turno
# estourar DEPOIS disso, o savepoint do webhook reverte `estado.agendamento_id` enquanto a
# reunião continua marcada de verdade. Este é o resíduo assumido da opção (iii), e a regra
# é: o resíduo é aceitável, o SILÊNCIO sobre ele não é.
#
# Por isso a exceção tem de ESCAPAR — é o que entrega o caso à rede de última instância do
# P0-C (`main.py`), que notifica a gestão em sessão nova e manda a despedida ao lead. Um
# `try/except` local aqui engoliria o caso e a gestão nunca saberia da reunião órfã.
# O outro lado deste teste vive em test_rede_ultima_instancia.py.
try:
    _, fb, _, _, escrita, _ = asyncio.run(
        tenta_agendar("2026-09-01T10:30:00", ["2026-09-01T10:30:00"], reuniao_explode=True))
    escapou = False
except RuntimeError:
    escapou = True
checa("exceção APÓS o agendamento commitado ESCAPA (vai para a rede do P0-C)", escapou, True)
checa("  e a sessão do agendamento fechou assim mesmo (async with)",
      _SessaoDoAgendamento.fechadas, 1)
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
         patch.object(fluxo, "enviar_nat", new=AsyncMock(return_value=(True, "ok"))), \
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


from app.nat_scheduler import AcaoIgnorada  # noqa: E402


async def executa_lembrete(reuniao, agendamento_id=7):
    """Devolve (spy_do_envio, motivo_da_AcaoIgnorada_ou_None).

    S4-1: as saídas de "nada a fazer" deixaram de ser `return` mudo. Não basta mais checar
    que nada foi enviado — o motivo TEM de existir, senão a ação sai `executado` com motivo
    NULL e fica indistinguível de um lembrete que saiu.
    """
    db = _db()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=reuniao)))
    motivo = None
    with patch.object(fluxo, "send_nat_message", new=AsyncMock(return_value=True)) as spy, \
         patch.object(fluxo, "_corpo_do_template", new=AsyncMock(return_value="corpo")):
        try:
            await fluxo.lembrete_reuniao(
                {"contact_wa_id": "5583999998888",
                 "payload": json.dumps({"agendamento_id": agendamento_id})}, db)
        except AcaoIgnorada as e:
            motivo = e.motivo
    return spy, motivo


from app.models import PASSO_AGENDADO  # noqa: E402

ok = _reuniao(dias=1)
ok.passo = PASSO_AGENDADO
spy, motivo = asyncio.run(executa_lembrete(ok))
checa("reunião viva -> lembrete enviado", spy.await_count, 1)
checa("  e SEM AcaoIgnorada (executado de verdade)", motivo, None)

spy, motivo = asyncio.run(executa_lembrete(None))
checa("reunião SUMIU -> não envia", spy.await_count, 0)
checa("  e vira skipped COM motivo (S4-1)", "não está mais agendada" in (motivo or ""), True)

morta = _reuniao(dias=1)
morta.passo = "falhou"
spy, motivo = asyncio.run(executa_lembrete(morta))
checa("reunião não está mais agendada -> não envia", spy.await_count, 0)
checa("  e vira skipped COM motivo (S4-1)", "passo=" in (motivo or ""), True)

passada = _reuniao(dias=-1)
passada.passo = PASSO_AGENDADO
spy, motivo = asyncio.run(executa_lembrete(passada))
checa("reunião já começou -> não envia atrasado", spy.await_count, 0)
checa("  e vira skipped COM motivo (S4-1)", "já começou" in (motivo or ""), True)

spy, motivo = asyncio.run(executa_lembrete(ok, agendamento_id=None))
checa("payload sem agendamento_id -> não envia", spy.await_count, 0)
checa("  e vira skipped COM motivo (S4-1)", "sem agendamento_id" in (motivo or ""), True)


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
    # O guard passou a buscar o estado com `IN (variantes)` + `.scalars().first()` para
    # tolerar o 9º dígito (ver 2b). O dublê precisa responder as DUAS APIs, senão ele
    # devolve None calado e o teste "libera" vira "bloqueia" por defeito do teste.
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=estado)
    res.scalars = MagicMock(return_value=_Scalars([estado] if estado is not None else []))
    db.execute = AsyncMock(return_value=res)
    with patch.object(guard, "_carregar_config", new=AsyncMock(return_value=cfg)), \
         patch.object(guard, "contar_envios_ultima_hora", new=AsyncMock(return_value=envios)):
        return await guard.qualificacao_pode_atuar(MagicMock(wa_id="5583999998888"), db)


checa("envio sem estado -> bloqueia", asyncio.run(envia(_cfg(), None))[0], False)
checa("envio em etapa terminal -> bloqueia",
      asyncio.run(envia(_cfg(), _estado(ETAPA_Q_CONCLUIDO)))[0], False)
checa("envio em etapa ativa -> libera",
      asyncio.run(envia(_cfg(), _estado(ETAPA_Q_AGUARDANDO_ANO)))[0], True)


# ------------------------------------------------------------------------------------------
# P1-B — o teto por hora não cala quem já está conversando (26/08/2026)
# ------------------------------------------------------------------------------------------
# Este teste dizia o contrário até hoje: "o teto vale também no envio" -> False. Ele estava
# fiel ao código e o código estava errado. O teto foi dimensionado para ABERTURA, que é
# business-initiated; responder a quem acabou de escrever é user-initiated e não ameaça a
# qualidade do número. MEDIDO em 25/08: duas mensagens do 5583988046720 (20:32:00 e 20:32:12)
# morreram em "teto de envios/hora estourado (20/20)", e morreram em silêncio.
#
# O cenário do teste é o pedido pela auditoria: TETO ARTIFICIAL EM 1, já estourado.
checa("teto ESTOURADO + lead ativo -> RESPONDE assim mesmo (era o silêncio de 25/08)",
      asyncio.run(envia(_cfg(teto=1), _estado(ETAPA_Q_AGUARDANDO_ANO), envios=1))[0], True)
checa("  e nem chega a contar os envios da hora",
      asyncio.run(envia(_cfg(teto=1), _estado(ETAPA_Q_AGUARDANDO_ANO), envios=999))[0], True)

# O outro lado da mesma regra: a ABERTURA continua limitada. Sem isto, P1-B viraria "o agente
# pode abrir conversa com quantas pessoas quiser por hora", que é exatamente o risco de
# qualidade que o teto existe para conter.
checa("teto ESTOURADO + ABERTURA -> continua bloqueando",
      asyncio.run(admite(_cfg(teto=1), DEPOIS, envios=1))[0], False)


async def abre_guard(cfg, envios=0):
    with patch.object(guard, "_carregar_config", new=AsyncMock(return_value=cfg)), \
         patch.object(guard, "contar_envios_ultima_hora", new=AsyncMock(return_value=envios)):
        return await guard.guard_de_abertura(MagicMock(wa_id="5583999998888"), _db())


checa("teto ESTOURADO + guard_de_abertura -> bloqueia (abertura e lembrete)",
      asyncio.run(abre_guard(_cfg(teto=1), envios=1))[0], False)


# A DESPEDIDA é a resposta a um inbound, é o último recurso de um turno que já falhou, e é o
# que o P0-B e o P0-C usam para que falha nunca vire silêncio. Herdava o teto do
# `guard_de_abertura`; agora tem guard próprio. O único que ela ainda respeita é a chave
# geral — desligar o agente desliga tudo, inclusive a despedida.
async def despede(cfg, envios=0):
    with patch.object(guard, "_carregar_config", new=AsyncMock(return_value=cfg)), \
         patch.object(guard, "contar_envios_ultima_hora", new=AsyncMock(return_value=envios)):
        return await guard.guard_de_despedida(MagicMock(wa_id="5583999998888"), _db())


checa("teto ESTOURADO + despedida -> ENVIA (senão o fail-closed vira silêncio)",
      asyncio.run(despede(_cfg(teto=1), envios=999))[0], True)
checa("despedida NÃO exige etapa ativa (a etapa já é transferido_humano quando ela sai)",
      asyncio.run(despede(_cfg()))[0], True)
checa("chave geral desligada -> nem despedida", asyncio.run(despede(_cfg(enabled=False)))[0],
      False)
checa("config ausente -> nem despedida", asyncio.run(despede(None))[0], False)
with patch.object(guard, "_carregar_config", new=AsyncMock(side_effect=RuntimeError("x"))):
    checa("despedida também falha FECHADA",
          asyncio.run(guard.guard_de_despedida(MagicMock(wa_id="x"), _db()))[0], False)

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


from app.nat_scheduler import AcaoAdiada, AcaoIgnorada  # noqa: E402


async def abre_em(agora):
    """iniciar_qualificacao com o relógio do ciclo controlado.

    Devolve `(adiada|None, admissao)`. Fora do horário o handler não reagenda uma linha nova:
    ele levanta AcaoAdiada, e é o agendador que empurra o run_at da MESMA ação sem consumir
    tentativa (ver nat_scheduler.AcaoAdiada).
    """
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=None)), \
         patch.object(fluxo, "_contato_ou_criar", new=AsyncMock(return_value=None)), \
         patch.object(fluxo.guard, "qualificacao_pode_iniciar",
                      new=AsyncMock(return_value=(True, "ok"))) as admissao:
        try:
            await fluxo.iniciar_qualificacao(
                {"contact_wa_id": "5583999998888", "agora": agora,
                 "payload": json.dumps({"lead_id": 1, "origem": ORIGEM_LP})}, _db())
            return None, admissao
        except AcaoAdiada as e:
            return e, admissao
        except AcaoIgnorada:
            return None, admissao


adiada, adm = asyncio.run(abre_em(_dt(*SEG, 2, 0)))
checa("abertura às 02h NÃO chega à admissão", adm.await_count, 0)
checa("  é ADIADA (não executada em silêncio)", isinstance(adiada, AcaoAdiada), True)
checa("  para as 09h", adiada.quando, _dt(*SEG, 9, 0))
checa("  com o motivo gravável", "fora do horário" in adiada.motivo, True)

adiada, adm = asyncio.run(abre_em(_dt(*SEX, 19, 0)))
checa("sexta 19h -> segunda 09h", adiada.quando, _dt(2026, 8, 31, 9, 0))

adiada, adm = asyncio.run(abre_em(_dt(*SEG, 10, 0)))
checa("dentro da janela NÃO adia", adiada, None)
checa("  e segue para a admissão", adm.await_count, 1)


# ==========================================================================================
print("\n10) Encerramento por inatividade — ETAPA_Q_ENCERRADO deixa de ser constante morta")

from app.models import ETAPA_Q_ENCERRADO  # noqa: E402

checa("72h é a régua", fluxo.INATIVIDADE_ENCERRA, timedelta(hours=72))
checa("encerrado NÃO é etapa ativa", ETAPA_Q_ENCERRADO in ETAPAS_QUALIFICACAO_ATIVAS, False)


async def encerra(estado, nos_calamos=False):
    """Devolve (estado, motivo_da_AcaoIgnorada_ou_None) — ver S4-1 em executa_lembrete.

    `encalhada` é dublada porque aqui o assunto é a MÁQUINA DE ETAPAS: quem escolhe entre
    `inatividade` e `sem_resposta_do_agente` é a varredura do S4-2, e é lá — em
    test_agente_parado.py §8, contra mensagens de verdade — que a escolha é testada.
    """
    motivo = None
    achado = ("ts", "wamid", "espera") if nos_calamos else None
    with patch("app.agente_parado.encalhada", new=AsyncMock(return_value=achado)), \
         patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)):
        try:
            await fluxo.encerrar_inativo({"contact_wa_id": "5583999998888"}, _db())
        except AcaoIgnorada as e:
            motivo = e.motivo
    return estado, motivo


e, motivo = asyncio.run(encerra(_estado(ETAPA_Q_AGUARDANDO_ANO)))
checa("etapa ativa + 72h -> encerrado", e.etapa, ETAPA_Q_ENCERRADO)
checa("  com motivo", e.encerrado_motivo, fluxo.MOTIVO_INATIVIDADE)
checa("  e carimbo de quando", e.encerrado_em is not None, True)
checa("  e SEM AcaoIgnorada (encerrou de verdade)", motivo, None)

e, _ = asyncio.run(encerra(_estado(ETAPA_Q_AGUARDANDO_ANO), nos_calamos=True))
checa("mas se NÓS calamos, o motivo é outro (S4-2)",
      e.encerrado_motivo, fluxo.MOTIVO_SEM_RESPOSTA_AGENTE)

e, motivo = asyncio.run(encerra(_estado(ETAPA_Q_CONCLUIDO)))
checa("já concluído NÃO é encerrado", e.etapa, ETAPA_Q_CONCLUIDO)
checa("  e vira skipped COM motivo, não executado mudo (S4-1)",
      "concluido" in (motivo or ""), True)

e, motivo = asyncio.run(encerra(_estado(ETAPA_Q_TRANSFERIDO)))
checa("já transferido NÃO é encerrado", e.etapa, ETAPA_Q_TRANSFERIDO)
checa("  e vira skipped COM motivo (S4-1)", "transferido_humano" in (motivo or ""), True)

motivo = None
with patch("app.agente_parado.encalhada", new=AsyncMock(return_value=None)), \
     patch.object(fluxo, "estado_de", new=AsyncMock(return_value=None)):
    try:
        asyncio.run(fluxo.encerrar_inativo({"contact_wa_id": "5583999998888"}, _db()))
    except AcaoIgnorada as ex:
        motivo = ex.motivo
checa("sem estado: skipped COM motivo (S4-1, era `return` mudo)",
      "não tem estado" in (motivo or ""), True)

# resposta do lead REAGENDA o encerramento
e, _ = asyncio.run(encerra(_estado(ETAPA_Q_AGUARDANDO_ANO)))  # já encerrado
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
