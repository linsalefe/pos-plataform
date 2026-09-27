"""SPRINT_RELIGAR_AGENTE_20260927 — um grupo por critério (1 a 6). NÃO EXECUTADO na sprint.

    cd backend && venv/bin/python test_religar_agente_20260927.py

NADA sai daqui: o httpx da Exact, `enviar_nat`, `bulk_send_template` e o scheduler são
dublês; o banco é `MagicMock` com `execute` assíncrono. Mesmo padrão de
`test_nat_correcoes_20260918.py`.

O QUE CADA GRUPO PROVA
  1. `registrar_observacao`: POST em /timelineAdd com {leadId, userId, text}, prefixo [NAT],
     e NUNCA levanta — HTTP 500, timeout e lead_id None viram `False` + log `❌ exact_note #`
  2. recusa de ligação grava a observação no lead da Exact, com o texto do critério
  3. `iniciar_qualificacao`: reunião futura em QUALQUER horizonte -> skipped 'ja_agendado';
     reunião passada não bloqueia; a constante das 2h não existe mais
  4. inbound com reunião futura -> `encerrado`/'agendou_no_meio', pendentes da conversa
     cancelados (não o lembrete), nenhuma mensagem, LLM não chamado
  5. `bulk_send_template` não pula mais por `nat_ativa`: silencia ANTES de enviar, em
     campanha e em individual — 'disparo_manual', ou 'follow_estagio' vindo do job de follow;
     `add_timeline_comment` usa o mesmo autor ativo das notas
  6. follow por estágio: `enviado` grava observação; falha da nota não muda o status
"""
import asyncio
import io
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app import exact_notes
from app import nat_scheduler as sched
from app import qualificacao_fluxo as fluxo
from app import qualificacao_guard as guard
from app import qualificacao_llm as llm
from app.models import (ETAPA_Q_ENCERRADO, ETAPA_Q_ESCOLHENDO_SLOT, ETAPA_Q_OFERTANDO_AGENDA,
                        ETAPA_Q_TRANSFERIDO, KIND_ENCERRAR_INATIVO, KIND_FOLLOW_20H,
                        KIND_LEMBRETE_REUNIAO, KIND_RESPONDER_PENDENTE, KIND_VIGIAR_RESPOSTA,
                        PASSO_AGENDADO, Agendamento, Contact, NatQualificacaoState,
                        ORIGEM_EXACT)

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def mudo(coro):
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = asyncio.run(coro)
    return r, buf.getvalue()


def _db(scalar=None):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=scalar),
        scalar=MagicMock(return_value=scalar)))
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


AGORA = datetime(2026, 9, 28, 10, 0)
WA = "5583988046720"
LEAD = 51999999


def estado_em(etapa, **kw):
    e = NatQualificacaoState(contact_wa_id=WA, exact_lead_id=LEAD, origem=ORIGEM_EXACT,
                             etapa=etapa)
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def reuniao(em, id=900):
    return Agendamento(id=id, nome="Teste", telefone="83988046720", lead_id=LEAD,
                       passo=PASSO_AGENDADO, slot_inicio=em,
                       sales_rep_email="consultora@example.com",
                       created_at=AGORA - timedelta(days=1))


# ==========================================================================================
print("\n1) registrar_observacao — best-effort, nunca levanta")


class _Cliente:
    """Dublê de `httpx.AsyncClient` que grava o POST e devolve `resposta` (ou levanta)."""
    chamadas = []

    def __init__(self, resposta=None, excecao=None):
        self.resposta, self.excecao = resposta, excecao

    def __call__(self, *a, **kw):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        _Cliente.chamadas.append((url, json))
        if self.excecao:
            raise self.excecao
        return self.resposta


def nota(resposta=None, excecao=None, lead_id=LEAD, texto="Teste"):
    _Cliente.chamadas = []
    with patch.object(exact_notes.httpx, "AsyncClient", new=_Cliente(resposta, excecao)):
        return mudo(exact_notes.registrar_observacao(lead_id, texto))


ok_resp = MagicMock(status_code=201, text="")
(r, log) = nota(ok_resp, texto="Follow 3 enviado")
checa("201 -> True", r, True)
url, corpo = _Cliente.chamadas[0]
checa("  POST em /timelineAdd", url.endswith("/timelineAdd"), True)
checa("  corpo {leadId, userId, text}", sorted(corpo), ["leadId", "text", "userId"])
checa("  leadId é o id da Exact", corpo["leadId"], LEAD)
checa("  userId é o autor ATIVO (415875 dava 400 'User not found')", corpo["userId"], 415967)
checa("  texto ganha o prefixo [NAT]", corpo["text"], "[NAT] Follow 3 enviado")
(r, _) = nota(ok_resp, texto="[NAT] já prefixado")
checa("  prefixo não duplica", _Cliente.chamadas[0][1]["text"], "[NAT] já prefixado")

(r, log) = nota(MagicMock(status_code=500, text="erro interno"))
checa("HTTP 500 -> False", r, False)
checa("  com log '❌ exact_note #<lead_id>'", f"❌ exact_note #{LEAD}" in log, True)
(r, log) = nota(excecao=httpx.ReadTimeout("lento"))
checa("timeout -> False, sem levantar", r, False)
checa("  com log", f"❌ exact_note #{LEAD}" in log, True)
(r, log) = nota(ok_resp, lead_id=None)
checa("lead_id None -> False", r, False)
checa("  e NENHUM POST", _Cliente.chamadas, [])


# ==========================================================================================
print("\n2) recusa de ligação grava observação na Exact")

checa("texto da nota", fluxo.texto_nota_recusa(datetime(2026, 9, 28, 14, 5)),
      "[NAT] Lead recusou ligação pelo WhatsApp em 28/09 14:05. Prefere mensagem.")


def turno(resposta_llm, reuniao_da_pessoa=None, agora=AGORA):
    estado = estado_em(ETAPA_Q_OFERTANDO_AGENDA)
    db = _db()
    envio = AsyncMock(return_value=(True, "ok"))
    conversar = AsyncMock(return_value=resposta_llm)
    registrar = AsyncMock(return_value=True)
    cancelar = AsyncMock(return_value=1)
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)), \
         patch.object(fluxo, "_reuniao", new=AsyncMock(return_value=reuniao_da_pessoa)), \
         patch.object(fluxo, "_agora_sp", new=MagicMock(return_value=agora)), \
         patch.object(fluxo, "_agendar_encerramento", new=AsyncMock()), \
         patch.object(fluxo, "_agendar_follow", new=AsyncMock()), \
         patch.object(fluxo, "_armar_vigia", new=AsyncMock()), \
         patch.object(fluxo, "_fatos", new=AsyncMock(return_value=("ctx", {"s1": 1}))), \
         patch.object(fluxo, "_historico", new=AsyncMock(return_value=[])), \
         patch.object(fluxo, "_descartar_fala_adiada", new=AsyncMock()), \
         patch.object(fluxo, "_cancelar_follow", new=AsyncMock()), \
         patch.object(fluxo, "_notificar", new=AsyncMock()), \
         patch.object(fluxo, "nat_cancelar", new=cancelar), \
         patch.object(fluxo, "enviar_nat", new=envio), \
         patch.object(llm, "conversar", new=conversar), \
         patch("app.exact_notes.registrar_observacao", new=registrar):
        mudo(fluxo.processar_texto(WA, "texto", "wamid.1", db))
    return estado, envio, conversar, registrar, cancelar


estado, _, _, registrar, _ = turno({"mensagem": "ok", "etapa_cumprida": False,
                                    "dado_extraido": None, "acao": "transferir_humano",
                                    "motivo": "recusa_ligacao"})
checa("transferência continua (transferido_humano / recusa_ligacao)",
      (estado.etapa, estado.transferido_motivo), (ETAPA_Q_TRANSFERIDO, "recusa_ligacao"))
checa("  a nota vai para o lead da Exact do estado", registrar.await_args.args[0], LEAD)
checa("  com o texto do critério", registrar.await_args.args[1],
      fluxo.texto_nota_recusa(AGORA))

estado, _, _, registrar, _ = turno({"mensagem": "Vou te passar.", "etapa_cumprida": False,
                                    "dado_extraido": None, "acao": "transferir_humano",
                                    "motivo": None})
checa("transferência comum NÃO grava nota de recusa", registrar.await_count, 0)


# ==========================================================================================
print("\n3) abertura: reunião marcada em QUALQUER horizonte -> 'ja_agendado'")

checa("a constante das 2h não existe mais",
      hasattr(guard, "MIN_HORAS_ATE_REUNIAO_PARA_ABERTURA"), False)
checa("  nem `reuniao_perto_demais`", hasattr(guard, "reuniao_perto_demais"), False)
checa("motivo padronizado", guard.MOTIVO_JA_AGENDADO, "ja_agendado")
for rotulo, delta, esperado in [("em 30 min", timedelta(minutes=30), True),
                                ("em 3 dias", timedelta(days=3), True),
                                ("em 40 dias", timedelta(days=40), True),
                                ("começou há 10 min", -timedelta(minutes=10), False)]:
    checa(f"reuniao_futura: {rotulo}", guard.reuniao_futura(AGORA + delta, AGORA), esperado)
checa("reuniao_futura: sem reunião", guard.reuniao_futura(None, AGORA), False)


def abre(reuniao_da_pessoa):
    db = _db()
    criar = AsyncMock(return_value=Contact(wa_id=WA, name="Teste", channel_id=1))
    rdd = AsyncMock(return_value=reuniao_da_pessoa)
    acao = {"contact_wa_id": WA, "payload": f'{{"lead_id": {LEAD}, "origem": "exact"}}',
            "agora": AGORA}
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=None)), \
         patch.object(guard, "qualificacao_pode_iniciar",
                      new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(fluxo, "reuniao_de", new=rdd), \
         patch.object(fluxo, "_contato_ou_criar", new=criar):
        try:
            mudo(fluxo.iniciar_qualificacao(acao, db))
            return None, criar, rdd
        except sched.AcaoIgnorada as e:
            return e.motivo, criar, rdd
        except Exception as e:     # depois do ponto testado o handler precisa de mais dublês
            return f"seguiu: {type(e).__name__}", criar, rdd


motivo, criar, rdd = abre(reuniao(AGORA + timedelta(days=12)))
checa("reunião daqui a 12 dias -> skipped 'ja_agendado'", motivo, "ja_agendado")
checa("  antes de criar contato", criar.await_count, 0)
checa("  consulta pelo TELEFONE (reuniao_de, a da sprint de 18/09)",
      rdd.await_args.kwargs.get("telefone"), WA)
motivo, criar, _ = abre(reuniao(AGORA + timedelta(minutes=45)))
checa("reunião em 45 min -> 'ja_agendado' (o caso das 2h está contido)", motivo, "ja_agendado")
motivo, criar, _ = abre(reuniao(AGORA - timedelta(days=2)))
checa("reunião que JÁ passou não bloqueia", motivo == "ja_agendado", False)
checa("  e o contato é resolvido", criar.await_count, 1)
motivo, criar, _ = abre(None)
checa("sem reunião não bloqueia", motivo == "ja_agendado", False)


# ==========================================================================================
print("\n4) marcou pelo site no meio da conversa -> encerrado 'agendou_no_meio', calado")

estado, envio, conversar, _, cancelar = turno(
    {"mensagem": "x", "etapa_cumprida": True, "dado_extraido": None, "acao": "nenhuma",
     "motivo": None},
    reuniao_da_pessoa=reuniao(AGORA + timedelta(days=2)))
checa("etapa vira 'encerrado'", estado.etapa, ETAPA_Q_ENCERRADO)
checa("  encerrado_motivo='agendou_no_meio'", estado.encerrado_motivo, "agendou_no_meio")
checa("  encerrado_em preenchido", estado.encerrado_em, AGORA)
checa("  NENHUMA mensagem ao lead", envio.await_count, 0)
checa("  o LLM nem é chamado", conversar.await_count, 0)
kinds = sorted(c.args[0] for c in cancelar.await_args_list)
checa("  cancela encerrar_inativo, follow_20h, vigiar_resposta, responder_pendente", kinds,
      sorted([KIND_ENCERRAR_INATIVO, KIND_FOLLOW_20H, KIND_VIGIAR_RESPOSTA,
              KIND_RESPONDER_PENDENTE]))
checa("  e NÃO cancela o lembrete T-30", KIND_LEMBRETE_REUNIAO in kinds, False)

estado, envio, conversar, _, _ = turno(
    {"mensagem": "Qual sua formação?", "etapa_cumprida": False, "dado_extraido": None,
     "acao": "nenhuma", "motivo": None},
    reuniao_da_pessoa=reuniao(AGORA - timedelta(days=1)))
checa("reunião PASSADA não encerra: o turno segue para o LLM", conversar.await_count, 1)
checa("  e a etapa continua ativa", estado.etapa, ETAPA_Q_OFERTANDO_AGENDA)


# ==========================================================================================
print("\n5) bulk_send_template: não pula por nat_ativa; encerra o agente ANTES do envio")

from app import exact_routes  # noqa: E402

src = open(exact_routes.__file__, encoding="utf-8").read()
corpo_bulk = src[src.index("async def bulk_send_template"):]
checa("não consulta mais ETAPAS_QUALIFICACAO_ATIVAS",
      "ETAPAS_QUALIFICACAO_ATIVAS" in corpo_bulk, False)
checa("não cria mais pulo com regra 'nat_ativa'", '"regra": "nat_ativa"' in corpo_bulk, False)
checa("MOTIVO_PULO_NAT removido", hasattr(exact_routes, "MOTIVO_PULO_NAT"), False)
checa("motivo novo", fluxo.MOTIVO_DISPARO_MANUAL, "disparo_manual")
i_silencia = corpo_bulk.index("motivo=motivo_agente)")
i_envio = corpo_bulk.index("send_template_message(")
i_higiene = corpo_bulk.index("por_que_pular(")
checa("silenciar vem ANTES do envio à Meta", i_silencia < i_envio, True)
checa("  e DEPOIS da higiene (quem é pulado por recusa não perde o agente)",
      i_higiene < i_silencia, True)
checa("  fora de qualquer `if not individual` (vale nos dois modos)",
      "if not individual" in corpo_bulk[:i_silencia], False)
checa("motivo do follow", fluxo.MOTIVO_FOLLOW_ESTAGIO, "follow_estagio")
checa("bulk só aceita motivo_agente conhecido (senão disparo_manual)",
      "if motivo_agente not in (MOTIVO_DISPARO_MANUAL, MOTIVO_FOLLOW_ESTAGIO)" in corpo_bulk, True)

# add_timeline_comment (NAT, ai_engine) usa o MESMO autor das notas.
from app import exact_spotter  # noqa: E402

checa("exact_spotter não tem mais o 415875 fixo", hasattr(exact_spotter, "EXACT_BOT_USER_ID"),
      False)
_Cliente.chamadas = []
with patch.object(exact_spotter.httpx, "AsyncClient", new=_Cliente(ok_resp)):
    mudo(exact_spotter.add_timeline_comment(LEAD, "resumo"))
checa("add_timeline_comment manda userId=415967", _Cliente.chamadas[0][1]["userId"], 415967)
with patch.dict("os.environ", {"EXACT_NOTE_USER_ID": "443275"}):
    checa("EXACT_NOTE_USER_ID troca o autor sem deploy", exact_spotter.autor_das_notas(), 443275)

# Comportamento do helper: repassa o motivo para `silenciar`.
from app import routes  # noqa: E402

silenciar = AsyncMock(return_value="ofertando_agenda")
db = _db()
db.begin_nested = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(),
                                                   __aexit__=AsyncMock(return_value=False)))
with patch.object(fluxo, "silenciar", new=silenciar):
    mudo(routes._silenciar_agente_apos_envio_manual(WA, None, db, motivo="disparo_manual"))
checa("helper repassa motivo='disparo_manual' a `silenciar`",
      silenciar.await_args.args[1], "disparo_manual")
with patch.object(fluxo, "silenciar", new=silenciar):
    mudo(routes._silenciar_agente_apos_envio_manual(WA, None, db))
checa("  sem motivo continua 'outbound_manual_sdr' (rotas /send/*)",
      silenciar.await_args.args[1], fluxo.MOTIVO_OUTBOUND_MANUAL)


# ==========================================================================================
print("\n6) follow por estágio: `enviado` grava observação; a nota não muda o status")

from app import follow_estagio as fe  # noqa: E402
from app.models import FE_ENVIADO, FE_SKIPPED  # noqa: E402

checa("texto da nota (sem 'Follow Follow', sem o espaço da Exact)",
      fe.texto_nota_follow(" Follows 7", "mensagem_follow7", datetime(2026, 9, 28, 9, 30)),
      "[NAT] Follows 7 enviado pela IA em 28/09 09:30 (template mensagem_follow7).")


def envia(retorno, nota_ok=True):
    lead = MagicMock(id=9324, exact_id=LEAD, phone1="83988046720")
    lead.name = "Teste"

    async def execute(stmt, params=None):
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=lead)
        return r

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    linha = MagicMock(id=1, lead_exact_id=LEAD, estagio_id=129983, estagio_nome="Follow 3")
    nota = AsyncMock(return_value=nota_ok)
    fin = AsyncMock()
    bulk = AsyncMock(return_value=retorno)
    envia.bulk = bulk
    with patch("app.exact_routes.bulk_send_template", new=bulk), \
         patch("app.exact_notes.registrar_observacao", new=nota), \
         patch.object(fe, "montar_mappings", new=MagicMock(return_value=([], None))), \
         patch.object(fe, "_finalizar", new=fin):
        status, _ = mudo(fe._enviar_uma(db, linha))
    return status, nota, fin


ENVIADO = {"sent": 1, "failed": 0, "errors": [], "skipped": [], "skipped_total": 0,
           "skipped_por_regra": {}, "skipped_nat": 0}
status, nota, fin = envia(ENVIADO)
checa("payload do follow leva motivo_agente='follow_estagio'",
      envia.bulk.await_args.args[0].get("motivo_agente"), "follow_estagio")
checa("enviado -> nota gravada", nota.await_count, 1)
checa("  no lead da Exact da linha", nota.await_args.args[0], LEAD)
checa("  com o nome do estágio", nota.await_args.args[1].startswith("[NAT] Follow 3 enviado"),
      True)
checa("  _finalizar ANTES da nota, com 'enviado'", fin.await_args.kwargs["status"], FE_ENVIADO)
status, nota, fin = envia(ENVIADO, nota_ok=False)
checa("nota falhou -> status continua 'enviado'", status, FE_ENVIADO)
checa("  e _finalizar só uma vez (nada reescreve a linha)", fin.await_count, 1)
PULADO = {**ENVIADO, "sent": 0, "skipped_total": 1, "skipped_por_regra": {"recusa": 1},
          "skipped": [{"regra": "recusa", "motivo": "disse não"}]}
status, nota, _ = envia(PULADO)
checa("skipped -> NENHUMA nota", (status, nota.await_count), (FE_SKIPPED, 0))


# ==========================================================================================
print()
if falhas:
    print(f"❌ {len(falhas)} falha(s):")
    for f in falhas:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ tudo passou")
