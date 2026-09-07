"""Fase 1 do RD Station — normalização, enfileiramento e desfecho do drenador.

    cd backend && venv/bin/python test_rd_station.py

NADA sai daqui: banco é dublê (a UNIQUE vive num `set` em memória) e `enviar_conversao` é
mockado. **Nenhuma chamada de rede ao RD Station em nenhum caminho deste arquivo.**

O QUE ESTE TESTE PROVA
  1. e-mail normaliza para a chave, e a peneira recusa o que não é e-mail
  2. telefone decide POR COMPRIMENTO — o DDD 55 sobrevive (o defeito que o RECON nomeou)
  3. a chave de idempotência é a PESSOA, não o agendamento
  4. o mapa é case-insensitive, e arquivo ausente não levanta
  5. o payload leva só o que a decisão 2 da sprint autorizou
  6. o par lead_criado+agendado da mesma pessoa vira UMA linha, não duas
  7. todo caminho de recusa grava `skipped` com motivo — nunca silêncio
  8. o drenador: 2xx envia, 429/5xx/rede retentam, 4xx desiste na hora, gate fechado não
     toca no banco
"""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Aponta o mapa para o arquivo do repo ANTES de importar quem o lê. `rd_station` não cacheia,
# mas o teste do "arquivo ausente" troca a variável no meio — deixar explícito aqui evita que
# a ordem dos blocos passe a importar.
os.environ["RD_CONVERSOES_PATH"] = "rd_conversoes.json"

from sqlalchemy.dialects import postgresql  # noqa: E402

from app import rd_outbox, rd_sender, rd_station  # noqa: E402
from app.models import RD_ENVIADO, RD_FALHOU, RD_PENDENTE, RD_SKIPPED  # noqa: E402

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


# ==========================================================================================
print("\n1) normalizar_email — a caixa importa porque o e-mail é metade da chave")

checa("maiúscula vira minúscula", rd_station.normalizar_email("Maria@Exemplo.COM"),
      "maria@exemplo.com")
checa("espaço nas bordas some", rd_station.normalizar_email("  ana@x.com.br  "),
      "ana@x.com.br")
checa("sem arroba não é e-mail", rd_station.normalizar_email("nao tenho"), None)
checa("sem ponto no domínio não passa", rd_station.normalizar_email("ana@localhost"), None)
checa("None continua None", rd_station.normalizar_email(None), None)
checa("string vazia é None", rd_station.normalizar_email(""), None)
checa("só espaço é None", rd_station.normalizar_email("   "), None)
checa("e-mail comum passa intacto", rd_station.normalizar_email("joao.silva@gmail.com"),
      "joao.silva@gmail.com")


# ==========================================================================================
print("\n2) normalizar_telefone_rd — POR COMPRIMENTO, nunca por prefixo")
#
# O caso do DDD 55 é o motivo de esta função existir separada. Quatro linhas reais da base
# têm 11 dígitos começando em 55 — Santa Maria/RS. Tratar isso como DDI produziria um número
# de 9 dígitos sem DDD, que o RD aceita e ninguém consegue ligar.

checa("11 dígitos (celular com DDD) ganha o DDI",
      rd_station.normalizar_telefone_rd("11999998888"), "+5511999998888")
checa("10 dígitos (fixo com DDD) ganha o DDI",
      rd_station.normalizar_telefone_rd("1133334444"), "+551133334444")
checa("13 dígitos (já com DDI) só ganha o +",
      rd_station.normalizar_telefone_rd("5511999998888"), "+5511999998888")
checa("12 dígitos (fixo com DDI) só ganha o +",
      rd_station.normalizar_telefone_rd("551133334444"), "+551133334444")
checa("DDD 55 com 11 dígitos NÃO é confundido com DDI",
      rd_station.normalizar_telefone_rd("55998581234"), "+5555998581234")
checa("máscara é limpa antes de contar",
      rd_station.normalizar_telefone_rd("(11) 99999-8888"), "+5511999998888")
checa("+55 na frente também",
      rd_station.normalizar_telefone_rd("+55 11 99999-8888"), "+5511999998888")
checa("9 dígitos não dá para afirmar nada", rd_station.normalizar_telefone_rd("999998888"),
      None)
checa("14 dígitos idem", rd_station.normalizar_telefone_rd("55119999988881"), None)
checa("None continua None", rd_station.normalizar_telefone_rd(None), None)


# ==========================================================================================
print("\n3) chave_de — a identidade é a PESSOA, não a tentativa")

checa("com e-mail, a chave é o e-mail",
      rd_station.chave_de("ana@x.com", "11999998888"), "email:ana@x.com")
checa("sem e-mail, cai no telefone",
      rd_station.chave_de(None, "5511999998888"), "tel:5511999998888")
checa("o telefone da chave é só dígitos",
      rd_station.chave_de(None, "(11) 99999-8888"), "tel:11999998888")
checa("e-mail inválido já chega como None e vira tel:",
      rd_station.chave_de(rd_station.normalizar_email("nao tem"), "11999998888"),
      "tel:11999998888")


# ==========================================================================================
print("\n4) identifier_para — o mapa não é derivável do nome do curso")

checa("caixa diferente casa",
      rd_station.identifier_para("posmulheridades"), "formulario-pos-mulheridades-2")
checa("espaço nas bordas não atrapalha",
      rd_station.identifier_para("  Pos TEA V3  "), "formulario-pos-tea")
checa("o hash do identifier é preservado byte a byte",
      rd_station.identifier_para("Pos Saude do Trabalhador"),
      "formulario-pos-sm-trabalhador-7c1bffb18b")
checa("curso fora do mapa devolve None (e não um palpite)",
      rd_station.identifier_para("Pos Que Nao Existe"), None)
checa("sub_source vazio devolve None", rd_station.identifier_para(""), None)
checa("None devolve None", rd_station.identifier_para(None), None)
checa("os 14 cursos da allowlist estão no mapa", len(rd_station.carregar_mapa()), 14)

# Arquivo ausente NÃO pode levantar: esta função é chamada de dentro do fluxo de agendamento.
os.environ["RD_CONVERSOES_PATH"] = "/tmp/nao-existe-rd-conversoes.json"
checa("arquivo ausente devolve mapa vazio, sem exceção", rd_station.carregar_mapa(), {})
checa("  e identifier_para devolve None", rd_station.identifier_para("Pos TEA V3"), None)
os.environ["RD_CONVERSOES_PATH"] = "rd_conversoes.json"
checa("voltou a ler o mapa depois (sem cache preso)",
      rd_station.identifier_para("Pos TEA V3"), "formulario-pos-tea")


# ==========================================================================================
print("\n5) montar_payload — só o que a decisão 2 da sprint autorizou")

corpo = rd_station.montar_payload(identifier="formulario-pos-tea", email="ana@x.com",
                                  nome="  Ana Souza  ", telefone="+5511999998888")
checa("envelope do evento", (corpo["event_type"], corpo["event_family"]),
      ("CONVERSION", "CDP"))
checa("as chaves do payload são exatamente estas",
      sorted(corpo["payload"]),
      ["conversion_identifier", "email", "mobile_phone", "name", "tags"])
checa("nome vem sem espaço nas bordas", corpo["payload"]["name"], "Ana Souza")
checa("a tag de origem está lá", corpo["payload"]["tags"], ["cenat-hub"])

sem_tel = rd_station.montar_payload(identifier="x", email="a@b.co", nome="A", telefone=None)
checa("mobile_phone é OMITIDO, não vai vazio", "mobile_phone" in sem_tel["payload"], False)
sem_nome = rd_station.montar_payload(identifier="x", email="a@b.co", nome="  ",
                                     telefone=None)
checa("name em branco também é omitido", "name" in sem_nome["payload"], False)
checa("nenhum cf_* nesta fase",
      [k for k in corpo["payload"] if k.startswith("cf_")], [])


# ==========================================================================================
print("\n6) enfileirar — uma linha por pessoa, e nunca silêncio")
#
# Banco de mentira: a UNIQUE (chave, conversion_identifier) é um `set`. É o suficiente porque
# é exatamente o que o índice do Postgres faz, e o que se quer provar aqui é a ÁRVORE DE
# DECISÃO do rd_outbox — não o Postgres.


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Resultado:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class FakeSessao:
    """`db.begin_nested()` e `db.execute(insert)` com a UNIQUE em memória."""

    def __init__(self):
        self.gravadas = []
        self._unicos = set()

    def begin_nested(self):
        return _Savepoint()

    async def execute(self, stmt, params=None):
        valores = stmt.compile(dialect=postgresql.dialect()).params
        par = (valores["chave"], valores["conversion_identifier"])
        if par in self._unicos:
            return _Resultado(0)
        self._unicos.add(par)
        self.gravadas.append(valores)
        return _Resultado(1)


def _ag(id_, *, email, sub_source="Pos TEA V3", telefone="11999998888", nome="Ana"):
    """Um `Agendamento` só com o que `enfileirar` lê."""
    return SimpleNamespace(id=id_, email=email, sub_source=sub_source,
                           telefone=telefone, nome=nome)


async def bloco_enfileirar():
    # --- o par lead_criado + agendado da MESMA submissão -------------------------------
    db = FakeSessao()
    r1 = await rd_outbox.enfileirar(db, _ag(101, email="Ana@X.com"))
    r2 = await rd_outbox.enfileirar(db, _ag(102, email="ana@x.com"))
    checa("o primeiro passo da LP enfileira", r1, RD_PENDENTE)
    checa("o segundo passo NÃO cria uma segunda conversão", r2, rd_outbox.DUPLICADO)
    checa("  e o banco tem UMA linha", len(db.gravadas), 1)
    checa("  com o agendamento_id do PRIMEIRO", db.gravadas[0]["agendamento_id"], 101)
    checa("  e a chave normalizada", db.gravadas[0]["chave"], "email:ana@x.com")
    checa("  e o identifier do curso", db.gravadas[0]["conversion_identifier"],
          "formulario-pos-tea")
    checa("  com payload pronto", db.gravadas[0]["payload"]["payload"]["email"],
          "ana@x.com")

    # --- caminho do agente: sem e-mail --------------------------------------------------
    db = FakeSessao()
    r = await rd_outbox.enfileirar(db, _ag(201, email=None, telefone="5511988887777"))
    checa("sem e-mail vira skipped", r, RD_SKIPPED)
    checa("  com motivo nomeado", db.gravadas[0]["motivo"], rd_outbox.MOTIVO_SEM_EMAIL)
    checa("  e chave por telefone", db.gravadas[0]["chave"], "tel:5511988887777")
    checa("  sem payload", db.gravadas[0]["payload"], None)
    r = await rd_outbox.enfileirar(db, _ag(202, email=None, telefone="5511988887777"))
    checa("a segunda tentativa do agente não vira linha nova", r, rd_outbox.DUPLICADO)

    # --- e-mail que existe mas não é e-mail ----------------------------------------------
    db = FakeSessao()
    r = await rd_outbox.enfileirar(db, _ag(301, email="nao tenho"))
    checa("e-mail sujo é distinguido de e-mail ausente", r, RD_SKIPPED)
    checa("  com motivo próprio", db.gravadas[0]["motivo"],
          rd_outbox.MOTIVO_EMAIL_INVALIDO)

    # --- curso fora do mapa ---------------------------------------------------------------
    db = FakeSessao()
    r = await rd_outbox.enfileirar(db, _ag(401, email="ana@x.com",
                                           sub_source="Pos Congresso Qualquer"))
    checa("curso fora do mapa vira skipped", r, RD_SKIPPED)
    checa("  com motivo sem_mapa", db.gravadas[0]["motivo"], rd_outbox.MOTIVO_SEM_MAPA)
    checa("  e um identifier órfão que nunca colide com um real",
          db.gravadas[0]["conversion_identifier"], "sem-mapa:pos congresso qualquer")
    # Precedência: sem mapa E sem e-mail ao mesmo tempo reporta `sem_mapa`. O mapa é o
    # problema de verdade; reportar `sem_email` mandaria quem investiga para o lado errado.
    db = FakeSessao()
    await rd_outbox.enfileirar(db, _ag(402, email=None, sub_source="Pos Nada"))
    checa("  sem_mapa tem precedência sobre sem_email", db.gravadas[0]["motivo"],
          rd_outbox.MOTIVO_SEM_MAPA)

    # --- dois cursos fora do mapa não colapsam numa linha só ------------------------------
    db = FakeSessao()
    await rd_outbox.enfileirar(db, _ag(501, email="a@x.com", sub_source="Pos Um"))
    await rd_outbox.enfileirar(db, _ag(502, email="a@x.com", sub_source="Pos Dois"))
    checa("dois cursos sem mapa, duas linhas", len(db.gravadas), 2)

    # --- a mesma pessoa em DOIS cursos é DUAS conversões ----------------------------------
    db = FakeSessao()
    await rd_outbox.enfileirar(db, _ag(601, email="a@x.com", sub_source="Pos TEA V3"))
    await rd_outbox.enfileirar(db, _ag(602, email="a@x.com",
                                       sub_source="Pos Psicologia Escolar"))
    checa("mesma pessoa, dois cursos, duas conversões", len(db.gravadas), 2)

    # --- nunca levanta --------------------------------------------------------------------
    class SessaoQuebrada(FakeSessao):
        async def execute(self, stmt, params=None):
            raise RuntimeError("banco caiu")

    r = await rd_outbox.enfileirar(SessaoQuebrada(), _ag(701, email="a@x.com"))
    checa("banco quebrado devolve 'erro' em vez de levantar", r, rd_outbox.ERRO)


# ==========================================================================================
print("\n7) rd_sender — a regra de desfecho")


class FakeSessaoEnvio:
    """Registra os UPDATE de `_finalizar` sem banco."""

    def __init__(self):
        self.updates = []

    async def execute(self, stmt, params=None):
        self.updates.append(stmt.compile(dialect=postgresql.dialect()).params)
        return _Resultado(1)

    async def commit(self):
        pass


def _linha(id_=1, tentativas=0):
    return SimpleNamespace(id=id_, tentativas=tentativas,
                           conversion_identifier="formulario-pos-tea",
                           payload={"event_type": "CONVERSION"})


async def bloco_sender():
    # --- 201: enviado ---------------------------------------------------------------------
    db = FakeSessaoEnvio()
    with patch.object(rd_station, "enviar_conversao",
                      AsyncMock(return_value=(201, '{"event_uuid":"abc"}'))):
        r = await rd_sender._enviar_uma(db, _linha())
    checa("201 marca enviado", r, RD_ENVIADO)
    checa("  com status na linha", db.updates[0]["status"], RD_ENVIADO)
    checa("  e enviado_em preenchido", db.updates[0]["enviado_em"] is not None, True)
    checa("  guardando a resposta", db.updates[0]["resposta"], '{"event_uuid":"abc"}')

    # --- 429: retenta ---------------------------------------------------------------------
    db = FakeSessaoEnvio()
    with patch.object(rd_station, "enviar_conversao",
                      AsyncMock(return_value=(429, "rate limited"))):
        r = await rd_sender._enviar_uma(db, _linha(tentativas=0))
    checa("429 adia em vez de desistir", r, "adiado")
    checa("  sem mexer no status", "status" in db.updates[0], False)
    checa("  contando a tentativa", db.updates[0]["tentativas"], 1)
    checa("  e empurrando o run_at", db.updates[0]["run_at"] is not None, True)

    # --- 503: retenta ---------------------------------------------------------------------
    db = FakeSessaoEnvio()
    with patch.object(rd_station, "enviar_conversao",
                      AsyncMock(return_value=(503, "unavailable"))):
        r = await rd_sender._enviar_uma(db, _linha(tentativas=0))
    checa("5xx adia", r, "adiado")

    # --- 400: desiste na hora --------------------------------------------------------------
    db = FakeSessaoEnvio()
    with patch.object(rd_station, "enviar_conversao",
                      AsyncMock(return_value=(400, '{"errors":"invalid"}'))):
        r = await rd_sender._enviar_uma(db, _linha(tentativas=0))
    checa("400 falha na hora, sem retentativa", r, RD_FALHOU)
    checa("  com o corpo guardado", db.updates[0]["resposta"], '{"errors":"invalid"}')
    checa("  e o motivo nomeando o status", db.updates[0]["motivo"], "HTTP 400")

    # --- 401 (chave errada) também desiste --------------------------------------------------
    db = FakeSessaoEnvio()
    with patch.object(rd_station, "enviar_conversao",
                      AsyncMock(return_value=(401, "unauthorized"))):
        checa("401 falha na hora", await rd_sender._enviar_uma(db, _linha()), RD_FALHOU)

    # --- erro de rede: retenta ---------------------------------------------------------------
    import httpx
    db = FakeSessaoEnvio()
    with patch.object(rd_station, "enviar_conversao",
                      AsyncMock(side_effect=httpx.ConnectError("sem rota"))):
        r = await rd_sender._enviar_uma(db, _linha(tentativas=0))
    checa("erro de rede adia", r, "adiado")
    checa("  com o tipo do erro no motivo", "ConnectError" in db.updates[0]["motivo"], True)

    # --- a terceira falha desiste -------------------------------------------------------------
    db = FakeSessaoEnvio()
    with patch.object(rd_station, "enviar_conversao",
                      AsyncMock(side_effect=httpx.ConnectError("sem rota"))):
        r = await rd_sender._enviar_uma(db, _linha(tentativas=rd_sender.MAX_TENTATIVAS - 1))
    checa("na 3ª tentativa vira falhou", r, RD_FALHOU)
    checa("  com o contador final", db.updates[0]["tentativas"], rd_sender.MAX_TENTATIVAS)

    # --- o gate ---------------------------------------------------------------------------
    def _explode():
        raise AssertionError("processar_pendentes abriu sessão com o envio desligado")

    os.environ.pop("RD_ENVIO_ENABLED", None)
    with patch.object(rd_sender, "async_session", _explode):
        r = await rd_sender.processar_pendentes()
    checa("gate fechado: não toca no banco", r, {"desligado": True})

    os.environ["RD_ENVIO_ENABLED"] = "true"
    os.environ.pop("RD_API_KEY", None)
    with patch.object(rd_sender, "async_session", _explode):
        r = await rd_sender.processar_pendentes()
    checa("ligado sem RD_API_KEY: também não toca no banco", r, {"sem_chave": True})
    os.environ.pop("RD_ENVIO_ENABLED", None)

    for valor in ("true", "TRUE", "1", "sim", "yes", " true "):
        os.environ["RD_ENVIO_ENABLED"] = valor
        checa(f"  {valor!r} liga o envio", rd_sender._envio_ligado(), True)
    for valor in ("", "nao", "false", "0", "talvez"):
        os.environ["RD_ENVIO_ENABLED"] = valor
        checa(f"  {valor!r} NÃO liga (falha fechada)", rd_sender._envio_ligado(), False)
    os.environ.pop("RD_ENVIO_ENABLED", None)
    checa("  variável ausente é desligado", rd_sender._envio_ligado(), False)

    # --- o teto por ciclo fica abaixo dos 120/min do RD ---------------------------------------
    checa("50 por ciclo de 60s cabe nos 120/min do RD",
          rd_sender.MAX_POR_CICLO <= 120 and rd_sender.INTERVALO_SEGUNDOS >= 60, True)


async def main():
    await bloco_enfileirar()
    await bloco_sender()


asyncio.run(main())


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado ao RD, nada gravado no banco.")
