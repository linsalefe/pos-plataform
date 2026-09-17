"""SPRINT_NAT_CORRECOES_20260918 — um teste por critério (1 a 7). NÃO EXECUTADO na sprint.

    cd backend && venv/bin/python test_nat_correcoes_20260918.py

NADA sai daqui: `enviar_nat` é mockado em todo grupo; o banco é dublê (`MagicMock` com
`execute` assíncrono). Mesmo padrão de `test_abertura_grafia.py`.

O QUE CADA GRUPO PROVA (recon: RECON_NAT_FOLLOWUPS_20260917.md)
  1. follow_20h compara o datetime devolvido por `_ultimo_inbound` (Defeito 1: 60 falhou)
  2. `_finalizar` recusa `falhou` sem motivo (Defeito 2)
  3. `reuniao_de` acha por telefone a reunião de OUTRO lead da mesma pessoa (Defeito 3:
     Luciana Zola, Elisangela — lead B nasceu 2 min depois)
  4. `_agendar` relê a reunião antes de `fluxo.agendar` e confirma em vez de marcar outra
  5. abertura recusada com reunião em < 2h (Defeito 4: Elisangela, 09:00 → reunião 10:30)
  6. `guard_de_lembrete` não consulta `qualificacao_enabled`
  7. `motivo="recusa_ligacao"` do LLM vira transferência com texto fixo, sem vídeo
"""
import asyncio
import io
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app import nat_copy
from app import nat_scheduler as sched
from app import qualificacao_fluxo as fluxo
from app import qualificacao_guard as guard
from app import qualificacao_llm as llm
from app.models import (ACAO_FALHOU, ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_CONCLUIDO,
                        ETAPA_Q_ESCOLHENDO_SLOT, ETAPA_Q_TRANSFERIDO, PASSO_AGENDADO,
                        Agendamento, Contact, NatQualificacaoState, ORIGEM_EXACT)
from app.telefone import formas_gravadas

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def _db(scalar=None):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=scalar),
        scalar=MagicMock(return_value=scalar),
        scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=scalar)))))
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


AGORA = datetime(2026, 9, 18, 10, 0)
WA = "5541996390611"          # a Elisangela, grafia com 9º dígito


def estado_em(etapa, **kw):
    e = NatQualificacaoState(contact_wa_id=WA, exact_lead_id=51846975, origem=ORIGEM_EXACT,
                             etapa=etapa)
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def reuniao(id=498, lead_id=51846973, telefone="41996390611", em=None):
    return Agendamento(id=id, nome="Elisangela", telefone=telefone, lead_id=lead_id,
                       passo=PASSO_AGENDADO, slot_inicio=em or AGORA + timedelta(days=1),
                       sales_rep_email="processoseletivo@cenatcursos.com.br",
                       created_at=AGORA - timedelta(days=2))


# ==========================================================================================
print("\n1) follow_20h — a comparação usa o datetime, não `.timestamp`")

def roda_follow(ultimo_inbound):
    """Executa o handler até a checagem do silêncio. Devolve o motivo do skip (ou None)."""
    db = _db()
    acao = {"contact_wa_id": WA, "payload": "{}"}
    envio = AsyncMock(return_value=(True, "ok"))
    with patch.object(fluxo, "_config_follow", new=AsyncMock(return_value=(True, "follow_up"))), \
         patch.object(fluxo, "estado_de",
                      new=AsyncMock(return_value=estado_em(ETAPA_Q_AGUARDANDO_ANO))), \
         patch.object(fluxo, "_ultimo_inbound", new=AsyncMock(return_value=ultimo_inbound)), \
         patch.object(fluxo, "_alguem_falou_depois", new=AsyncMock(return_value=False)), \
         patch.object(fluxo, "_corpo_aprovado", new=AsyncMock(return_value="Olá {{1}}, {{2}}")), \
         patch.object(fluxo, "_nome", new=AsyncMock(return_value="Elisangela")), \
         patch.object(fluxo, "_agora_sp", new=MagicMock(return_value=AGORA)), \
         patch.object(fluxo, "enviar_nat", new=envio):
        try:
            with redirect_stdout(io.StringIO()):
                asyncio.run(fluxo.follow_20h(acao, db))
            return None, envio
        except sched.AcaoIgnorada as e:
            return e.motivo, envio
        except TypeError as e:                      # o defeito, se voltar
            return f"TypeError: {e}", envio

motivo, envio = roda_follow(AGORA - timedelta(hours=30))
checa("com inbound antigo (30h): não levanta TypeError", str(motivo).startswith("TypeError"), False)
checa("  e o follow SAI", envio.await_count, 1)

motivo, envio = roda_follow(AGORA - timedelta(hours=2))
checa("com inbound recente (2h): skip 'falou dentro da janela'",
      "dentro da janela" in (motivo or ""), True)
checa("  e nada é enviado", envio.await_count, 0)

motivo, envio = roda_follow(None)
checa("sem inbound nenhum: segue e envia (o caso que já funcionava)", envio.await_count, 1)


# ==========================================================================================
print("\n2) `_finalizar` exige motivo em `falhou`")

def finaliza(**kw):
    db = _db()
    try:
        asyncio.run(sched._finalizar(db, 1, ACAO_FALHOU, AGORA, **kw))
        return "gravou", db
    except ValueError as e:
        return f"ValueError: {e}", db

r, _ = finaliza()
checa("falhou SEM motivo levanta ValueError", r.startswith("ValueError"), True)
r, db = finaliza(motivo="TypeError: '>=' not supported")
checa("falhou COM motivo grava", r, "gravou")
checa("  com um UPDATE", db.execute.await_count, 1)
r, _ = finaliza(motivo="")
checa("motivo vazio conta como ausente", r.startswith("ValueError"), True)


# ==========================================================================================
print("\n3) `reuniao_de` acha por telefone a reunião do OUTRO lead (Luciana/Elisangela)")

checa("formas_gravadas cobre as 4 grafias",
      formas_gravadas(WA), ("5541996390611", "41996390611", "554196390611", "4196390611"))
checa("  a partir da grafia SEM DDI e SEM 9 também",
      formas_gravadas("4196390611"), ("5541996390611", "41996390611", "554196390611", "4196390611"))

def busca(reuniao_por_id=None, reuniao_por_telefone=None, reuniao_por_lead=None, **kw):
    """Dublê que responde por ORDEM de consulta: id → telefone → lead."""
    respostas = iter([r for r in (reuniao_por_id, reuniao_por_telefone, reuniao_por_lead)
                      if r is not ...])
    db = MagicMock()
    async def execute(stmt):
        return MagicMock(scalar_one_or_none=MagicMock(return_value=next(respostas, None)))
    db.execute = execute
    return asyncio.run(fluxo.reuniao_de(db=db, **kw))

# lead B (51846975) sem reunião; a reunião 498 é do lead A (51846973), mesmo telefone
achada = busca(reuniao_por_id=..., reuniao_por_telefone=reuniao(), reuniao_por_lead=...,
               telefone=WA, lead_id=51846975, agendamento_id=None)
checa("estado no lead B acha a reunião do lead A pelo telefone", getattr(achada, "id", None), 498)

achada = busca(reuniao_por_id=reuniao(id=7), telefone=WA, lead_id=51846975, agendamento_id=7)
checa("`agendamento_id` do estado vem primeiro", achada.id, 7)

achada = busca(reuniao_por_id=..., reuniao_por_telefone=None, reuniao_por_lead=reuniao(id=9),
               telefone=WA, lead_id=51846975, agendamento_id=None)
checa("`lead_id` é o último recurso", achada.id, 9)

achada = busca(reuniao_por_id=..., reuniao_por_telefone=..., reuniao_por_lead=...,
               telefone="", lead_id=None, agendamento_id=None)
checa("sem telefone legível e sem lead: None, sem consulta", achada, None)


# ==========================================================================================
print("\n4) `_agendar` relê a reunião antes de marcar — e confirma em vez de duplicar")

def agenda(ja_tem):
    estado = estado_em(ETAPA_Q_ESCOLHENDO_SLOT)
    db = _db()
    marcar = AsyncMock()
    concluir = AsyncMock()
    slots = SimpleNamespace(slots_livres=AsyncMock(return_value=[SimpleNamespace(id="s1")]))
    pacote = SimpleNamespace(agendar=SimpleNamespace(agendar=marcar), disponibilidade=slots)
    with patch.dict("sys.modules", {"app.agendamento": pacote,
                                    "app.agendamento.agendar": pacote.agendar,
                                    "app.agendamento.disponibilidade": slots}), \
         patch.object(fluxo, "_reuniao", new=AsyncMock(return_value=ja_tem)), \
         patch.object(fluxo, "_concluir", new=concluir), \
         patch.object(fluxo, "_contato_de", new=AsyncMock(return_value=None)), \
         patch.object(fluxo, "_fallback", new=AsyncMock()):
        with redirect_stdout(io.StringIO()):
            asyncio.run(fluxo._agendar(
                estado, {"mensagem": "Marquei!", "dado_extraido": {"slot_id": "s1"}},
                {"s1": object()}, db))
    return estado, marcar, concluir

estado, marcar, concluir = agenda(ja_tem=reuniao())
checa("com reunião existente: `fluxo.agendar` NÃO é chamado", marcar.await_count, 0)
checa("  o estado aponta para a reunião existente", estado.agendamento_id, 498)
checa("  e conclui CONFIRMANDO (mesmo caminho de `_avancar`)",
      concluir.await_args.kwargs.get("confirmar"), True)


# ==========================================================================================
print("\n5) abertura recusada com reunião em menos de 2h (Elisangela)")

checa("reunião em 1h30: perto demais", guard.reuniao_perto_demais(AGORA + timedelta(minutes=90), AGORA), True)
checa("reunião em 3h: não", guard.reuniao_perto_demais(AGORA + timedelta(hours=3), AGORA), False)
checa("reunião que já começou: não (não é 'nas próximas 2h')",
      guard.reuniao_perto_demais(AGORA - timedelta(minutes=10), AGORA), False)
checa("sem reunião: não", guard.reuniao_perto_demais(None, AGORA), False)

def abre(reuniao_da_pessoa):
    db = _db()
    criar = AsyncMock(return_value=Contact(wa_id=WA, name="Elisangela", channel_id=1))
    acao = {"contact_wa_id": WA, "payload": '{"lead_id": 51846975, "origem": "exact"}',
            "agora": AGORA}
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=None)), \
         patch.object(guard, "qualificacao_pode_iniciar", new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(fluxo, "reuniao_de", new=AsyncMock(return_value=reuniao_da_pessoa)), \
         patch.object(fluxo, "_contato_ou_criar", new=criar):
        try:
            with redirect_stdout(io.StringIO()):
                asyncio.run(fluxo.iniciar_qualificacao(acao, db))
            return None, criar
        except sched.AcaoIgnorada as e:
            return e.motivo, criar
        except Exception as e:          # depois do ponto testado o handler precisa de mais dublês
            return f"seguiu: {type(e).__name__}", criar

motivo, criar = abre(reuniao(em=AGORA + timedelta(minutes=90)))
checa("reunião em 1h30 → skipped com o motivo padronizado", motivo, guard.MOTIVO_REUNIAO_PERTO)
checa("  ANTES de criar contato (nada para o savepoint reverter)", criar.await_count, 0)
motivo, criar = abre(reuniao(em=AGORA + timedelta(days=1)))
checa("reunião amanhã → a abertura segue (T1)", motivo == guard.MOTIVO_REUNIAO_PERTO, False)
checa("  e o contato é resolvido", criar.await_count, 1)


# ==========================================================================================
print("\n6) `guard_de_lembrete` não olha `qualificacao_enabled`")

def lembrete(reuniao_no_banco, ja_enviados=0, config_lida=None):
    contato = Contact(wa_id=WA, name="Elisangela", channel_id=1)
    db = MagicMock()
    consultas = []
    async def execute(stmt):
        consultas.append(str(stmt))
        if "agendamentos" in str(stmt):
            return MagicMock(scalar_one_or_none=MagicMock(return_value=reuniao_no_banco))
        return MagicMock(scalar=MagicMock(return_value=ja_enviados))
    db.execute = execute
    with patch.object(guard, "_carregar_config", new=AsyncMock(return_value=config_lida)) as cfg, \
         patch.object(guard, "_agora_sp", new=MagicMock(return_value=AGORA)):
        with redirect_stdout(io.StringIO()):
            pode, motivo = asyncio.run(guard.guard_de_lembrete(498)(contato, db))
        return pode, motivo, cfg.await_count

pode, motivo, leu_config = lembrete(reuniao(em=AGORA + timedelta(minutes=30)))
checa("reunião daqui a 30min, nada enviado: PODE", pode, True)
checa("  sem ler nat_config (o flag do agente não manda aqui)", leu_config, 0)
pode, motivo, _ = lembrete(reuniao(em=AGORA - timedelta(minutes=5)))
checa("reunião que já começou: não", pode, False)
pode, motivo, _ = lembrete(None)
checa("reunião inexistente/desmarcada: não", pode, False)
pode, motivo, _ = lembrete(reuniao(em=AGORA + timedelta(minutes=30)), ja_enviados=1)
checa("lembrete já enviado nas últimas 24h: não", pode, False)


# ==========================================================================================
print("\n7) recusa de ligação → transferência determinística, texto fixo, sem vídeo")

validado, motivo = llm._validar('{"mensagem": "ok", "etapa_cumprida": false, '
                                '"dado_extraido": null, "acao": "transferir_humano", '
                                '"motivo": "recusa_ligacao"}')
checa("o contrato aceita motivo=recusa_ligacao com transferir_humano",
      validado and validado["motivo"], llm.MOTIVO_RECUSA_LIGACAO)
validado, _ = llm._validar('{"mensagem": "ok", "etapa_cumprida": false, '
                           '"dado_extraido": null, "acao": "nenhuma", "motivo": "recusa_ligacao"}')
checa("motivo sem transferência é ignorado (None), não recusado", validado["motivo"], None)
validado, _ = llm._validar('{"mensagem": "ok", "etapa_cumprida": false, '
                           '"dado_extraido": null, "acao": "transferir_humano", "motivo": "video"}')
checa("motivo fora do enum vira None", validado["motivo"], None)
validado, _ = llm._validar('{"mensagem": "ok", "etapa_cumprida": false, '
                           '"dado_extraido": null, "acao": "nenhuma"}')
checa("JSON antigo, sem a chave: continua válido", validado is not None, True)
checa("'vídeo' não aparece no texto fixo", "vídeo" in nat_copy.TEXTO_RECUSA_LIGACAO.lower()
      or "video" in nat_copy.TEXTO_RECUSA_LIGACAO.lower(), False)
checa("  nem pergunta", "?" in nat_copy.TEXTO_RECUSA_LIGACAO, False)

def turno(resposta_llm):
    estado = estado_em(fluxo.ETAPA_Q_OFERTANDO_AGENDA)
    db = _db()
    envio = AsyncMock(return_value=(True, "ok"))
    notif = AsyncMock()
    with patch.object(fluxo, "estado_de", new=AsyncMock(return_value=estado)), \
         patch.object(fluxo, "_agendar_encerramento", new=AsyncMock()), \
         patch.object(fluxo, "_agendar_follow", new=AsyncMock()), \
         patch.object(fluxo, "_armar_vigia", new=AsyncMock()), \
         patch.object(fluxo, "_fatos", new=AsyncMock(return_value=("ctx", {"s1": 1}))), \
         patch.object(fluxo, "_historico", new=AsyncMock(return_value=[])), \
         patch.object(fluxo, "_descartar_fala_adiada", new=AsyncMock()), \
         patch.object(fluxo, "_cancelar_follow", new=AsyncMock()), \
         patch.object(fluxo, "_notificar", new=notif), \
         patch.object(fluxo, "enviar_nat", new=envio), \
         patch.object(llm, "conversar", new=AsyncMock(return_value=resposta_llm)):
        with redirect_stdout(io.StringIO()):
            asyncio.run(fluxo.processar_texto(WA, "Não quero ligação", "wamid.1", db))
    return estado, envio, notif

estado, envio, notif = turno({"mensagem": "ok", "etapa_cumprida": False, "dado_extraido": None,
                              "acao": "transferir_humano", "motivo": "recusa_ligacao"})
checa("etapa vira transferido_humano", estado.etapa, ETAPA_Q_TRANSFERIDO)
checa("  com transferido_motivo='recusa_ligacao'", estado.transferido_motivo, "recusa_ligacao")
checa("  o texto ao lead é o FIXO de nat_copy, não o 'ok' do modelo",
      envio.await_args.kwargs.get("corpo_livre"), nat_copy.TEXTO_RECUSA_LIGACAO)
checa("  e o SDR é avisado com o pedido do lead (mensagem)",
      "mensagem" in notif.await_args.args[2].lower(), True)

estado, envio, notif = turno({"mensagem": "Vou te passar para alguém.", "etapa_cumprida": False,
                              "dado_extraido": None, "acao": "transferir_humano", "motivo": None})
checa("transferência comum continua com TEXTO_FALLBACK",
      envio.await_args.kwargs.get("corpo_livre"), fluxo.TEXTO_FALLBACK)
checa("  e motivo genérico", estado.transferido_motivo.startswith("o LLM pediu"), True)


# ==========================================================================================
print()
if falhas:
    print(f"❌ {len(falhas)} falha(s):")
    for f in falhas:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ tudo passou")
