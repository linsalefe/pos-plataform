"""Risco 3 — `abrir()` nunca mais consome uma ação sem enviar nada. E o contato que faltava.

Rodar: cd backend && venv/bin/python test_risco3_abertura.py

NADA É ENVIADO E NADA É GRAVADO: sessão em memória, sem banco, sem rede.

------------------------------------------------------------------------------------------
O INCIDENTE QUE ORIGINOU ESTE ARQUIVO — 25/08/2026
------------------------------------------------------------------------------------------
Depois de os dois bugs do FIX_GATILHO_ABERTURA serem corrigidos, a fila do agente enfim
encheu, sobreviveu ao commit e drenou. Quatro ações venceram e viraram `executado`. E
`nat_qualificacao_state` continuou com ZERO linhas.

    id 60  5582998307979  executado   ← porteiro tolerante abriu na linha de OUTRA PESSOA,
                                        estado nasceu, sender estrito não achou, estado
                                        descartado
    id 61  5565996306463  executado   ← contato não existia
    id 63  5591985119613  executado   ← contato não existia
    id 65  5591985119613  executado   ← contato não existia (de novo, mesmo lead)

MEDIDO nos 45 leads do dia: 33 sem linha em `contacts`, 11 com. Três de cada quatro leads
não podiam receber abertura NENHUMA, com o agente ligado e a fila funcionando.

Duas coisas, e este arquivo tranca as duas:

  1. `contacts` só nascia da boas-vindas (passo 7 do `send_welcome_to_new_lead`) ou de um
     inbound. O passo 4.5 cede a abertura ao agente e sai ANTES disso. O agente herdou a
     dependência sem herdar quem a satisfazia. → `abrir()` passa a CRIAR o contato.

  2. As cinco saídas do handler eram `return` mudos, e todas viravam `executado` — o mesmo
     status de quem abriu a conversa. Nada distinguia "abri" de "desisti do lead".
     → AcaoIgnorada (`skipped` + motivo no banco) e AcaoAdiada (volta a `pendente`, run_at
       empurrado, SEM consumir tentativa).

Casos:
  1. contato inexistente -> CRIA e a abertura SAI
  2. contato já existe na grafia exata -> reusa, não duplica
  3. só existe a variante de 12 dígitos, de OUTRA PESSOA -> não usa a linha do estranho
  4. sem canal configurado -> AcaoIgnorada (e nenhum Contact órfão)
  5. já tem estado -> AcaoIgnorada com o motivo
  6. lead anterior ao corte -> AcaoIgnorada com o motivo
  7. teto na ADMISSÃO -> AcaoAdiada
  8. teto no ENVIO (passou na admissão) -> AcaoAdiada
  9. envio recusado por outro motivo -> AcaoIgnorada
 10. fora do horário -> AcaoAdiada para o próximo dia útil
 11. o agendador: AcaoIgnorada -> `skipped` + motivo; sem consumir tentativa
 12. o agendador: AcaoAdiada -> `pendente` + run_at empurrado; sem consumir tentativa
 13. o agendador: executado LIMPA o motivo de um adiamento anterior
 14. passo 4.5: gatilho que NÃO enfileirou não carimba "o agente assumiu"
 15. janela de 24h enxerga o inbound na grafia de 12 dígitos (o 8º ponto de comparação)
 16. contato SEM nome -> nome vem do lead, e o parâmetro em branco é barrado antes da Meta
"""
import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app import exact_spotter
from app import qualificacao_fluxo as fluxo
from app import nat_scheduler as ns
from app.models import (ACAO_EXECUTADO, ACAO_PENDENTE, ACAO_SKIPPED, AutoWelcomeConfig,
                        Contact, NatConfig,
                        ORIGEM_LP, ETAPA_Q_AGUARDANDO_ANO)
from app.nat_scheduler import AcaoAdiada, AcaoIgnorada
from app.qualificacao_guard import MOTIVO_TETO

AGORA = datetime(2026, 8, 25, 10, 0, 0)          # terça, dentro do horário comercial
WA = "5582998307979"                              # o número real do incidente (13 dígitos)
WA_12 = "558298307979"                            # a variante que era de OUTRA pessoa
CANAL = 1

falhas = []


def check(nome, condicao, detalhe=""):
    print(f"  {'✅' if condicao else '❌'} {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


# ==========================================================================================
# SESSÃO FALSA
# ==========================================================================================
class SessaoFalsa:
    """Sessão em memória que responde aos SELECTs do handler pelo TEXTO do statement.

    `contacts` é uma lista de verdade, e não um mock que devolve sempre a mesma coisa: o
    caso 3 depende de `WHERE wa_id = '5582998307979'` NÃO achar a linha de `558298307979`,
    que é exatamente a distinção que o bug apagava.
    """

    def __init__(self, *, contatos=(), canal_id=CANAL):
        self.contatos = list(contatos)
        self.canal_id = canal_id
        self.adicionados = []
        self.deletados = []
        self.flushes = 0

    async def execute(self, stmt):
        texto = str(stmt)
        res = MagicMock()
        res.rowcount = 0
        alvo = None
        if "FROM contacts" in texto:
            # Igualdade crua, a MESMA regra do nat_sender. Ver _contato_ou_criar.
            for c in self.contatos:
                if f"'{c.wa_id}'" in texto or c.wa_id in _parametros(stmt):
                    alvo = c
                    break
        elif "auto_welcome_config" in texto:
            alvo = SimpleNamespace(id=1, channel_id=self.canal_id)
        res.scalar_one_or_none.return_value = alvo
        scalars = MagicMock()
        scalars.first.return_value = alvo
        scalars.all.return_value = [alvo] if alvo is not None else []
        scalars.__iter__ = lambda self_: iter([alvo] if alvo is not None else [])
        res.scalars.return_value = scalars
        res.scalar.return_value = None
        return res

    def add(self, obj):
        self.adicionados.append(obj)
        if isinstance(obj, Contact):
            self.contatos.append(obj)

    async def delete(self, obj):
        self.deletados.append(obj)

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        pass

    def begin_nested(self):
        sessao = self

        class CM:
            async def __aenter__(self_):
                return sessao

            async def __aexit__(self_, *a):
                return False
        return CM()

    def contatos_criados(self):
        return [o for o in self.adicionados if isinstance(o, Contact)]


def _parametros(stmt):
    """Os valores literais ligados ao statement, para o dublê casar o WHERE."""
    try:
        return [str(v) for v in stmt.compile().params.values()]
    except Exception:
        return []


def _acao(payload=None, agora=AGORA, wa=WA):
    return {"id": 60, "kind": "iniciar_qualificacao", "contact_wa_id": wa, "agora": agora,
            "attempts": 0, "run_at": agora,
            "payload": json.dumps(payload or {"lead_id": 51543718, "origem": ORIGEM_LP,
                                              "referencia_utc": "2026-08-25T13:00:00"})}


def _contato(wa, nome="Alguém"):
    return Contact(wa_id=wa, name=nome, channel_id=CANAL)


async def _abrir(db, *, admissao=(True, "ok"), envio=(True, "ok"), estado=None,
                 agora=AGORA, wa=WA):
    """Roda o handler de verdade, dublando só as fronteiras (admissão, envio, LLM/dados)."""
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)), \
         patch.object(fluxo.guard, "qualificacao_pode_iniciar",
                      new=AsyncMock(return_value=admissao)), \
         patch.object(fluxo, "enviar_nat", new=AsyncMock(return_value=envio)) as spy_envio, \
         patch.object(fluxo, "_corpo_do_template", new=AsyncMock(return_value="oi")), \
         patch.object(fluxo, "_reuniao", new=AsyncMock(return_value=None)), \
         patch.object(fluxo, "_curso", new=AsyncMock(return_value="Pós")), \
         patch.object(fluxo, "_nome", new=AsyncMock(return_value="Ronaldo")), \
         patch.object(fluxo, "_agendar_encerramento", new=AsyncMock()), \
         patch.object(fluxo, "_identidade_do_lead",
                      new=AsyncMock(return_value=("Ronaldo Cesar", None))), \
         patch("app.qualificacao_dados.resolver_dados",
               new=AsyncMock(return_value={"formacao": "Psicologia",
                                           "faixa_investimento": None,
                                           "como_conheceu": None})):
        try:
            await fluxo.iniciar_qualificacao(_acao(agora=agora, wa=wa), db)
            return None, spy_envio
        except (AcaoIgnorada, AcaoAdiada) as e:
            return e, spy_envio


# ==========================================================================================
# 1-4: O CONTATO QUE FALTAVA
# ==========================================================================================

async def teste_1_cria_o_contato():
    print("\n1) contato inexistente -> CRIA o contato e a abertura SAI")
    db = SessaoFalsa()
    desfecho, envio = await _abrir(db)

    criados = db.contatos_criados()
    check("nenhuma exceção — a abertura seguiu", desfecho is None, repr(desfecho))
    check("criou UM Contact", len(criados) == 1, f"criados={len(criados)}")
    if criados:
        c = criados[0]
        check("na grafia EXATA para a qual a mensagem vai", c.wa_id == WA, c.wa_id)
        check("com o canal da config", c.channel_id == CANAL, str(c.channel_id))
        check("com o nome do lead", c.name == "Ronaldo Cesar", str(c.name))
        # A boas-vindas põe ai_active=True porque entrega a thread ao ai_engine. Aqui quem
        # conduz é o agente: dois robôs na mesma conversa é o que isto evita.
        check("ai_active=False (o agente conduz, não o ai_engine)", c.ai_active is False,
              str(c.ai_active))
    check("o envio foi tentado", envio.await_count == 1, str(envio.await_count))
    check("o estado do agente foi criado", any(
        type(o).__name__ == "NatQualificacaoState" for o in db.adicionados))


async def teste_2_reusa_o_contato_existente():
    print("\n2) contato já existe na grafia exata -> reusa, não duplica")
    db = SessaoFalsa(contatos=[_contato(WA, "Ronaldo Cesar")])
    desfecho, _ = await _abrir(db)
    check("não levantou", desfecho is None, repr(desfecho))
    check("NÃO criou Contact novo", db.contatos_criados() == [],
          f"criados={len(db.contatos_criados())}")


async def teste_3_nao_usa_a_linha_do_estranho():
    print("\n3) só existe a variante de 12 dígitos, de OUTRA PESSOA -> não a usa")
    # Este é o caso literal de produção: 558298307979 existia em contacts como
    # 'Pablo Valente', e a tolerância ao 9º dígito fazia o porteiro abrir na linha dele.
    db = SessaoFalsa(contatos=[_contato(WA_12, "Pablo Valente")])
    desfecho, _ = await _abrir(db)

    criados = db.contatos_criados()
    check("criou o contato do Ronaldo", len(criados) == 1, f"criados={len(criados)}")
    if criados:
        check("  com os 13 dígitos DELE", criados[0].wa_id == WA, criados[0].wa_id)
        check("  e o nome DELE, não o do Pablo", criados[0].name == "Ronaldo Cesar",
              str(criados[0].name))
    check("a linha do Pablo continua intacta",
          [c.name for c in db.contatos if c.wa_id == WA_12] == ["Pablo Valente"])


async def teste_4_sem_canal_nao_deixa_contato_orfao():
    print("\n4) sem canal configurado -> AcaoIgnorada, e nenhum Contact órfão")
    db = SessaoFalsa(canal_id=None)
    desfecho, envio = await _abrir(db)
    check("AcaoIgnorada", isinstance(desfecho, AcaoIgnorada), repr(desfecho))
    check("nenhum Contact criado sem canal", db.contatos_criados() == [])
    check("não tentou enviar", envio.await_count == 0)


# ==========================================================================================
# 5-10: OS DESFECHOS DO HANDLER
# ==========================================================================================

async def teste_5_ja_tem_estado():
    print("\n5) já tem estado -> AcaoIgnorada com o motivo (e o §2b do monitor para de mentir)")
    estado = SimpleNamespace(etapa=ETAPA_Q_AGUARDANDO_ANO)
    db = SessaoFalsa(contatos=[_contato(WA)])
    desfecho, envio = await _abrir(db, estado=estado)
    check("AcaoIgnorada", isinstance(desfecho, AcaoIgnorada), repr(desfecho))
    check("o motivo nomeia a etapa", ETAPA_Q_AGUARDANDO_ANO in desfecho.motivo,
          desfecho.motivo)
    check("não enviou nada", envio.await_count == 0)


async def teste_6_anterior_ao_corte():
    print("\n6) lead anterior ao corte -> AcaoIgnorada com o motivo")
    db = SessaoFalsa(contatos=[_contato(WA)])
    desfecho, envio = await _abrir(
        db, admissao=(False, "lead de 2026-08-01 é anterior ao corte 2026-08-24"))
    check("AcaoIgnorada", isinstance(desfecho, AcaoIgnorada), repr(desfecho))
    check("o motivo carrega o corte", "anterior ao corte" in desfecho.motivo, desfecho.motivo)
    check("não enviou nada", envio.await_count == 0)


async def teste_7_teto_na_admissao():
    print("\n7) teto na ADMISSÃO -> AcaoAdiada (esperar resolve; descartar, não)")
    db = SessaoFalsa(contatos=[_contato(WA)])
    desfecho, envio = await _abrir(db, admissao=(False, f"{MOTIVO_TETO} (20/20)"))
    check("AcaoAdiada, NÃO ignorada", isinstance(desfecho, AcaoAdiada), repr(desfecho))
    check("adiada por ATRASO_POR_TETO",
          desfecho.quando == AGORA + fluxo.ATRASO_POR_TETO, str(desfecho.quando))
    check("não enviou nada", envio.await_count == 0)


async def teste_8_teto_no_envio():
    print("\n8) teto no ENVIO, já tendo passado na admissão -> AcaoAdiada")
    # Acontece de verdade: entre a admissão e o envio há a chamada de _corpo_do_template à
    # Meta, e outras aberturas do mesmo ciclo podem encher a janela nesse intervalo.
    db = SessaoFalsa(contatos=[_contato(WA)])
    desfecho, envio = await _abrir(db, envio=(False, f"{MOTIVO_TETO} (20/20)"))
    check("AcaoAdiada", isinstance(desfecho, AcaoAdiada), repr(desfecho))
    check("o envio chegou a ser tentado", envio.await_count == 1)


async def teste_9_envio_recusado_por_outro_motivo():
    print("\n9) envio recusado por outro motivo -> AcaoIgnorada com o motivo do sender")
    db = SessaoFalsa(contatos=[_contato(WA)])
    desfecho, _ = await _abrir(db, envio=(False, "Meta recusou: {'error': 131047}"))
    check("AcaoIgnorada", isinstance(desfecho, AcaoIgnorada), repr(desfecho))
    check("o motivo do sender chegou inteiro", "131047" in desfecho.motivo, desfecho.motivo)
    # O savepoint do agendador é quem desfaz o estado — o handler não apaga mais à mão.
    check("o handler NÃO apaga o estado à mão (quem desfaz é o savepoint)",
          db.deletados == [], f"deletados={len(db.deletados)}")


async def teste_10_fora_do_horario():
    print("\n10) fora do horário -> AcaoAdiada para o próximo dia útil, sem linha nova")
    db = SessaoFalsa(contatos=[_contato(WA)])
    sexta_19h = datetime(2026, 8, 28, 19, 0, 0)
    desfecho, envio = await _abrir(db, agora=sexta_19h)
    check("AcaoAdiada", isinstance(desfecho, AcaoAdiada), repr(desfecho))
    check("sexta 19h -> segunda 09h", desfecho.quando == datetime(2026, 8, 31, 9, 0),
          str(desfecho.quando))
    check("não enviou nada", envio.await_count == 0)


# ==========================================================================================
# 11-13: O AGENDADOR HONRA OS DOIS DESFECHOS
# ==========================================================================================

class FilaFalsa:
    """A fila em memória. Só _proxima_acao e _finalizar são dublados — o resto roda."""

    def __init__(self):
        self.acoes = []

    def inserir(self, kind="__t__", attempts=0, motivo=None):
        acao = SimpleNamespace(id=len(self.acoes) + 1, kind=kind, contact_wa_id=WA,
                               run_at=AGORA - timedelta(minutes=5), status=ACAO_PENDENTE,
                               attempts=attempts, payload=None, processed_at=None,
                               motivo=motivo)
        self.acoes.append(acao)
        return acao

    async def proxima_acao(self, db, corte):
        v = [a for a in self.acoes if a.status == ACAO_PENDENTE and a.run_at <= corte]
        return sorted(v, key=lambda a: a.run_at)[0] if v else None

    async def finalizar(self, db, acao_id, status, agora, attempts=None, run_at=None,
                        motivo=None):
        a = self.acoes[acao_id - 1]
        a.status, a.motivo = status, motivo
        if attempts is not None:
            a.attempts = attempts
        if run_at is not None:
            a.run_at = run_at
        if status != ACAO_PENDENTE:
            a.processed_at = agora


def _fabrica(sessao):
    class CM:
        async def __aenter__(self):
            return sessao

        async def __aexit__(self, *a):
            return False
    return lambda: CM()


async def _cicla(handler, fila):
    with patch.object(ns, "_proxima_acao", new=fila.proxima_acao), \
         patch.object(ns, "_finalizar", new=fila.finalizar), \
         patch.dict(ns._HANDLERS, {"__t__": handler}), \
         patch.object(ns, "async_session", new=_fabrica(SessaoFalsa())):
        return await ns.processar_pendentes(agora=AGORA)


async def teste_11_scheduler_skipped():
    print("\n11) agendador: AcaoIgnorada -> `skipped` + motivo, sem consumir tentativa")
    fila = FilaFalsa()
    fila.inserir()

    async def handler(acao, db):
        raise AcaoIgnorada("já tem estado (aguardando_ano)")

    resumo = await _cicla(handler, fila)
    a = fila.acoes[0]
    check("status = skipped, NÃO executado", a.status == ACAO_SKIPPED, a.status)
    check("motivo GRAVADO na linha", a.motivo == "já tem estado (aguardando_ano)", str(a.motivo))
    check("attempts intacto (nada falhou)", a.attempts == 0, str(a.attempts))
    check("processed_at carimbado (saiu da fila)", a.processed_at == AGORA)
    check("aparece no resumo do ciclo", resumo.get(ACAO_SKIPPED) == 1, str(resumo))


async def teste_12_scheduler_adiada():
    print("\n12) agendador: AcaoAdiada -> `pendente` + run_at empurrado, sem consumir tentativa")
    fila = FilaFalsa()
    fila.inserir()
    quando = AGORA + timedelta(minutes=10)

    async def handler(acao, db):
        raise AcaoAdiada(quando, f"{MOTIVO_TETO} (20/20)")

    resumo = await _cicla(handler, fila)
    a = fila.acoes[0]
    check("continua pendente", a.status == ACAO_PENDENTE, a.status)
    check("run_at empurrado", a.run_at == quando, str(a.run_at))
    check("motivo visível na linha PENDENTE", MOTIVO_TETO in (a.motivo or ""), str(a.motivo))
    check("attempts NÃO consumido — adiar não é falhar", a.attempts == 0, str(a.attempts))
    check("sem processed_at (não saiu da fila)", a.processed_at is None, str(a.processed_at))
    check("resumo distingue adiado de pendente", resumo.get(ns.ACAO_ADIADO) == 1, str(resumo))


async def teste_13_executado_limpa_o_motivo():
    print("\n13) agendador: executar LIMPA o motivo do adiamento anterior")
    fila = FilaFalsa()
    fila.inserir(motivo=f"{MOTIVO_TETO} (20/20)")

    async def handler(acao, db):
        return None

    await _cicla(handler, fila)
    a = fila.acoes[0]
    check("status = executado", a.status == ACAO_EXECUTADO, a.status)
    check("motivo zerado (não fica mentindo)", a.motivo is None, str(a.motivo))


# ==========================================================================================
# 14: O CARIMBO DO PASSO 4.5 TEM QUE DIZER A VERDADE
# ==========================================================================================

async def teste_14_carimbo_nao_mente():
    print("\n14) passo 4.5: gatilho que NÃO enfileirou não carimba 'o agente assumiu'")
    from app.qualificacao_gatilho import (MOTIVO_ERRO, MOTIVO_ENFILEIRADO,
                                          MOTIVO_JA_TEM_ESTADO)

    async def roda(retorno):
        lead = SimpleNamespace(exact_id=51543718, welcome_status=None, welcome_error=None)
        db = SessaoFalsa()
        db._lead = lead

        async def execute(stmt):
            res = MagicMock()
            res.rowcount = 0
            texto = str(stmt)
            if "exact_leads" in texto:
                res.scalar_one_or_none.return_value = lead
            elif "nat_config" in texto:
                res.scalar_one_or_none.return_value = NatConfig(
                    id=1, nat_enabled=False, max_envios_hora=20, qualificacao_enabled=True)
            else:
                res.scalar_one_or_none.return_value = None
            return res
        db.execute = execute

        with patch.object(exact_spotter, "send_template_message", new=AsyncMock()) as envio, \
             patch("app.qualificacao_gatilho.agendar_abertura",
                   new=AsyncMock(return_value=retorno)):
            r = await exact_spotter.send_welcome_to_new_lead(
                {"exact_id": 51543718, "name": "Ronaldo Cesar", "phone1": "82998307979",
                 "funnel_id": 18535, "sub_source": "Pos", "register_date": AGORA},
                db, AutoWelcomeConfig(id=1, enabled=False, channel_id=CANAL,
                                      template_name="nat_boasvindas",
                                      template_language="pt_BR", funnel_ids="18535"))
        return r, lead, envio

    r, lead, envio = await roda((True, MOTIVO_ENFILEIRADO))
    check("enfileirou -> skipped/agente_assumiu", r["reason"] == "agente_assumiu", str(r))
    check("  carimbo 'skipped'", lead.welcome_status == "skipped", str(lead.welcome_status))
    check("  e nenhuma boas-vindas saiu", envio.call_count == 0)

    r, lead, _ = await roda((False, f"{MOTIVO_JA_TEM_ESTADO} (aguardando_ano)"))
    check("já tem estado -> ainda é 'assumido' (é verdade: está sendo atendido)",
          r["reason"] == "agente_assumiu" and lead.welcome_status == "skipped",
          f"{r['reason']}/{lead.welcome_status}")

    r, lead, _ = await roda((False, f"{MOTIVO_ERRO}: RuntimeError: banco caiu"))
    check("gatilho FALHOU -> NÃO carimba 'assumiu'", r["reason"] == "gatilho_falhou", str(r))
    check("  carimbo 'failed' (o lead fica achável para reprocessar)",
          lead.welcome_status == "failed", str(lead.welcome_status))
    check("  com o motivo real no welcome_error",
          "banco caiu" in (lead.welcome_error or ""), str(lead.welcome_error))


async def teste_15_janela_tolerante_ao_9o_digito():
    print("\n15) janela de 24h enxerga o inbound na grafia de 12 dígitos")
    # 25/08, o caso real: o agente abriu, a pessoa respondeu, e ele CALOU. `janela_aberta`
    # comparava com `==`; o envio vai para 13 dígitos e o WhatsApp entrega o inbound com 12
    # para todo DDD fora de 11-28 (59% das threads). Sem inbound visível a função concluía
    # "janela fechada", o sender ia para o ramo de TEMPLATE, e `qualif_conversa` — fala livre
    # do LLM — não tem template aprovado. O agente não ficava sem achar: ia para o caminho
    # errado.
    from app import nat_sender
    from sqlalchemy.dialects import postgresql

    class DB:
        def __init__(self):
            self.sql = None

        async def execute(self, stmt):
            self.sql = str(stmt.compile(dialect=postgresql.dialect(),
                                        compile_kwargs={"literal_binds": True}))
            r = MagicMock()
            r.scalar_one_or_none.return_value = AGORA - timedelta(minutes=2)
            return r

    # O RELÓGIO PRECISA SER O DO TESTE, NÃO O DE HOJE. `janela_aberta` compara o inbound
    # com `_agora_sp()`; sem prender esse relógio, o teste nasceu passando (25/08) e virou
    # vermelho sozinho 24h depois — a janela de 24h fechou sobre o próprio dublê. Um suite
    # que fica vermelho pelo calendário deixa de ser lido, e foi o que aconteceu: chegou
    # ao sprint de 26/08 já falhando, escondendo qualquer regressão real neste arquivo.
    for numero in (WA, WA_12):
        db = DB()
        with patch.object(nat_sender, "_agora_sp", return_value=AGORA):
            aberta = await nat_sender.janela_aberta(numero, db)
        check(f"{numero}: janela ABERTA", aberta is True, str(aberta))
        check(f"  busca as duas grafias", WA in db.sql and WA_12 in db.sql,
              [l for l in db.sql.split("\n") if "IN (" in l][:1])

    # A escrita NÃO muda: a Message continua nascendo na grafia do envio. É a regra do
    # app/telefone.py — tolerância é de leitura, nunca de gravação.
    fonte = open("app/nat_sender.py", encoding="utf-8").read()
    check("a Message ainda é gravada em contact_wa_id (grafia do envio)",
          "contact_wa_id=contact_wa_id" in fonte)


async def teste_16_parametro_vazio_nunca_chega_na_meta():
    print("\n16) contato SEM nome -> nome vem do lead; parâmetro em branco é barrado aqui")
    # 25/08: 3 das 18 aberturas do backfill morreram com (#131008) "Parameter of type text is
    # missing text value". `contacts.name` está vazio em 4 490 linhas do Hub, era a ÚNICA
    # fonte do `{{1}}`, e um parâmetro em branco faz a Meta recusar a mensagem INTEIRA.
    from app import nat_sender

    estado = SimpleNamespace(contact_wa_id=WA, exact_lead_id=51529947)

    # (a) contato sem nome -> cai para o nome do lead
    with patch.object(fluxo, "_contato_de",
                      new=AsyncMock(return_value=_contato(WA, name := ""))), \
         patch.object(fluxo, "_identidade_do_lead",
                      new=AsyncMock(return_value=("Karen Rossi Faris", None))):
        nome = await fluxo._nome(estado, SessaoFalsa())
    check("contato sem nome -> primeiro nome do LEAD", nome == "Karen", repr(nome))

    # (b) o contato manda quando tem nome — a segunda fonte não atropela a primeira
    with patch.object(fluxo, "_contato_de",
                      new=AsyncMock(return_value=_contato(WA, "Beatriz Cristina"))), \
         patch.object(fluxo, "_identidade_do_lead",
                      new=AsyncMock(return_value=("Outro Nome", None))) as lead:
        nome = await fluxo._nome(estado, SessaoFalsa())
    check("contato COM nome continua mandando", nome == "Beatriz", repr(nome))
    check("  e nem consulta o lead", lead.await_count == 0, str(lead.await_count))

    # (c) parâmetro em branco não chega na Meta
    envio = AsyncMock()
    db = SessaoFalsa(contatos=[_contato(WA, "Karen")])
    with patch.object(nat_sender, "send_template_message", new=envio), \
         patch.object(nat_sender, "janela_aberta", new=AsyncMock(return_value=False)), \
         patch.object(nat_sender, "_resolver_canal",
                      new=AsyncMock(return_value=SimpleNamespace(
                          id=1, phone_number_id="1", whatsapp_token="t"))):
        saiu, motivo = await nat_sender.enviar_nat(
            WA, "nat_abertura_qualificacao", db,
            guard=AsyncMock(return_value=(True, "ok")),
            parametros=["", "Saúde Mental do Trabalhador", "Pedagogia"])
    check("recusa antes de chamar a Meta", saiu is False and envio.await_count == 0,
          f"saiu={saiu} chamadas={envio.await_count}")
    check("  e o motivo aponta o parâmetro", "[1]" in motivo and "131008" in motivo, motivo)

    # (d) com todos preenchidos, passa
    envio = AsyncMock(return_value={"messages": [{"id": "wamid.X"}]})
    db = SessaoFalsa(contatos=[_contato(WA, "Karen")])
    with patch.object(nat_sender, "send_template_message", new=envio), \
         patch.object(nat_sender, "janela_aberta", new=AsyncMock(return_value=False)), \
         patch.object(nat_sender, "_resolver_canal",
                      new=AsyncMock(return_value=SimpleNamespace(
                          id=1, phone_number_id="1", whatsapp_token="t"))):
        saiu, _ = await nat_sender.enviar_nat(
            WA, "nat_abertura_qualificacao", db,
            guard=AsyncMock(return_value=(True, "ok")),
            parametros=["Karen", "Saúde Mental do Trabalhador", "Pedagogia"])
    check("todos preenchidos -> envia normalmente", saiu is True and envio.await_count == 1,
          f"saiu={saiu} chamadas={envio.await_count}")


async def main():
    print("=" * 90)
    print("RISCO 3 — nenhuma ação `executado` sem envio, e o contato que o agente não criava")
    print("=" * 90)
    for t in (teste_1_cria_o_contato, teste_2_reusa_o_contato_existente,
              teste_3_nao_usa_a_linha_do_estranho, teste_4_sem_canal_nao_deixa_contato_orfao,
              teste_5_ja_tem_estado, teste_6_anterior_ao_corte, teste_7_teto_na_admissao,
              teste_8_teto_no_envio, teste_9_envio_recusado_por_outro_motivo,
              teste_10_fora_do_horario, teste_11_scheduler_skipped,
              teste_12_scheduler_adiada, teste_13_executado_limpa_o_motivo,
              teste_14_carimbo_nao_mente, teste_15_janela_tolerante_ao_9o_digito,
              teste_16_parametro_vazio_nunca_chega_na_meta):
        await t()

    print("\n" + "=" * 90)
    if falhas:
        print(f"❌ {len(falhas)} FALHA(S): " + " · ".join(falhas))
        raise SystemExit(1)
    print("✅ Todos passaram. Nenhuma ação vira `executado` sem envio, e a abertura "
          "cria o contato que a boas-vindas criava.")
    print("=" * 90)


if __name__ == "__main__":
    asyncio.run(main())
