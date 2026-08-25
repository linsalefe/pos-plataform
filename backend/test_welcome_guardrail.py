"""Guardrail da mensagem automática de boas-vindas.

Rodar: cd backend && venv/bin/python test_welcome_guardrail.py

NENHUM envio real acontece: send_template_message e fetch_template_body são sempre
mockados, e o banco é falso (nada é gravado). O que estes testes provam:

  1. funil fora do escopo, automação LIGADA     -> skipped/not_pos_funnel,  0 envios
  2. funil pós, automação DESLIGADA             -> skipped/disabled,        0 envios
                                                   + LEAD CARIMBADO  <-- a regra do Álefe
  3. lead já processado (force=False)           -> skipped/already_processed, 0 envios
  4. funil pós, automação LIGADA, lead limpo    -> sent,                    1 envio
 4b. automação DESLIGADA + AGENTE ligado      -> skipped/agente_assumiu,  0 envios
                                                  + gatilho enfileirado
 4c. automação DESLIGADA + agente desligado   -> skipped/disabled,        0 envios
  5. canal em branco na config                  -> failed/no_channel,       0 envios
  6. bulk_send_template com nat_boasvindas      -> HTTP 400 (trava do envio em massa)

Trava única (app/welcome_guard.py) — todas as PORTAS de envio:
  7. POST /api/send/template  com nat_boasvindas  -> HTTP 400
  8. POST /api/send/template  com outro template  -> NÃO bloqueia
  9. POST /api/scheduled-messages nat_boasvindas  -> HTTP 400 (recusa na CRIAÇÃO)
 10. POST /api/scheduled-messages outro template  -> NÃO bloqueia
 11. variação de caixa/espaço em TODAS as portas  -> HTTP 400
 12. ⭐ a automação CONTINUA enviando (trava foi na porta, não no corredor)

Fechaduras de login (FASE 10) — o resend-welcome fura os guardas com force=True, então a
porta precisa estar trancada por fora; e o botão liga/desliga também, senão um estranho
liga a automação e a trava do enabled vira uma tranca com a chave na porta:
 13. POST /api/exact-leads/{id}/resend-welcome SEM token -> HTTP 401, 0 envios
 14. idem, LOGADO mas automação DESLIGADA                -> HTTP 400, 0 envios
 15. PUT /api/auto-welcome/config SEM token              -> HTTP 401, config intacta

Os testes 13-15 usam usuário FALSO (dependency_overrides) e banco FALSO: nenhum usuário
real é tocado, nenhum token real é gerado, nenhuma conexão com o banco é aberta.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import exact_spotter, whatsapp
from app.models import ExactLead, AutoWelcomeConfig, NatConfig


def _res(value):
    """Resultado falso de db.execute(): .scalar_one_or_none() -> value."""
    m = MagicMock()
    m.scalar_one_or_none.return_value = value
    return m


def _fake_db(*returns):
    """Banco falso. Cada db.execute() devolve, em ordem, um dos valores passados."""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_res(v) for v in returns])
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _lead(exact_id=111, funnel_id=18535, status=None):
    l = ExactLead(exact_id=exact_id, name="Fulano", phone1="5583999998888",
                  sub_source="pospsicologia", funnel_id=funnel_id)
    l.welcome_status = status
    l.welcome_error = None
    l.welcome_sent_at = None
    return l


def _nat_cfg(qualificacao_enabled=False):
    """`nat_config` falso, para o passo 4.5 de send_welcome_to_new_lead.

    DESLIGADO por padrão: é o estado de produção, e é o que faz a boas-vindas seguir o
    caminho de sempre. Precisa ser um objeto REAL e não um MagicMock — em MagicMock qualquer
    atributo é truthy, e `cfg.qualificacao_enabled` daria True sozinho, fazendo o agente
    "assumir" em todo teste.
    """
    return NatConfig(id=1, nat_enabled=False, max_envios_hora=20,
                     qualificacao_enabled=qualificacao_enabled)


def _cfg(enabled=True, channel_id=1):
    return AutoWelcomeConfig(id=1, enabled=enabled, channel_id=channel_id,
                             template_name="nat_boasvindas", template_language="pt_BR",
                             funnel_ids="18535,18537,25588")


def _lead_data(lead):
    return {"exact_id": lead.exact_id, "name": lead.name, "phone1": lead.phone1,
            "sub_source": lead.sub_source, "funnel_id": lead.funnel_id}


CHANNEL = MagicMock(id=1, waba_id="w", whatsapp_token="t", phone_number_id="p")
OK_SEND = {"messages": [{"id": "wamid.TESTE"}]}


async def caso_1_funil_fora_do_escopo():
    lead = _lead(funnel_id=18285, status=None)          # Intercambio, fora dos funis-alvo
    db = _fake_db(lead)
    with patch.object(exact_spotter, "send_template_message", new=AsyncMock()) as spy:
        r = await exact_spotter.send_welcome_to_new_lead(_lead_data(lead), db, _cfg(enabled=True))
    assert r["status"] == "skipped" and r["reason"] == "not_pos_funnel", r
    assert spy.call_count == 0, "FALHOU: enviou para funil fora do escopo!"
    assert lead.welcome_status == "skipped"
    print(f"  1. funil fora do escopo (18285)     -> {r['status']}/{r['reason']:18s} "
          f"envios={spy.call_count}  carimbo={lead.welcome_status!r}")


async def caso_2_automacao_desligada():
    """O TESTE MAIS IMPORTANTE: lead ingerido com o botão desligado tem que ficar
    CARIMBADO, senão receberia a boas-vindas retroativamente ao ligar a automação."""
    lead = _lead(status=None)
    db = _fake_db(lead)
    with patch.object(exact_spotter, "send_template_message", new=AsyncMock()) as spy:
        r = await exact_spotter.send_welcome_to_new_lead(_lead_data(lead), db, _cfg(enabled=False))
    assert r["status"] == "skipped" and r["reason"] == "disabled", r
    assert spy.call_count == 0, "FALHOU: enviou com a automacao desligada!"
    assert lead.welcome_status == "skipped", "FALHOU: NAO CARIMBOU -> receberia retroativamente!"
    assert lead.welcome_sent_at is None, "FALHOU: marcou envio sem ter enviado!"
    print(f"  2. automacao DESLIGADA             -> {r['status']}/{r['reason']:18s} "
          f"envios={spy.call_count}  carimbo={lead.welcome_status!r}")
    print(f"     motivo gravado: {lead.welcome_error!r}")


async def caso_3_lead_ja_processado():
    lead = _lead(status="skipped")                      # ja tem decisao registrada
    lead.welcome_error = "motivo original"
    db = _fake_db(lead)
    with patch.object(exact_spotter, "send_template_message", new=AsyncMock()) as spy:
        r = await exact_spotter.send_welcome_to_new_lead(_lead_data(lead), db, _cfg(enabled=True))
    assert r["status"] == "skipped" and r["reason"] == "already_processed", r
    assert spy.call_count == 0, "FALHOU: reenviou para lead ja processado!"
    assert lead.welcome_error == "motivo original", "FALHOU: re-carimbou e perdeu o motivo!"
    print(f"  3. lead ja processado              -> {r['status']}/{r['reason']:18s} "
          f"envios={spy.call_count}  motivo preservado={lead.welcome_error!r}")


async def caso_4_envio_normal():
    lead = _lead(status=None)
    # ordem dos db.execute(): lead -> canal -> curso(alias) -> contato -> card
    db = _fake_db(lead, _nat_cfg(), CHANNEL, None, None, None)
    with patch.object(exact_spotter, "send_template_message",
                      new=AsyncMock(return_value=OK_SEND)) as spy, \
         patch.object(whatsapp, "fetch_template_body",
                      new=AsyncMock(return_value="Olá, {{1}}! Curso: {{2}}")):
        r = await exact_spotter.send_welcome_to_new_lead(_lead_data(lead), db, _cfg(enabled=True))
    assert r["status"] == "sent", r
    assert spy.call_count == 1, "FALHOU: nao enviou para lead valido!"
    assert lead.welcome_status == "sent"
    assert lead.welcome_sent_at is not None, "FALHOU: enviou mas nao registrou a hora!"
    enviado = spy.call_args.kwargs
    print(f"  4. lead novo, automacao LIGADA     -> {r['status']}/{r['reason']:18s} "
          f"envios={spy.call_count}  carimbo={lead.welcome_status!r}")
    print(f"     template={enviado['template_name']!r} lang={enviado['language']!r} "
          f"params={enviado['parameters']}")


async def caso_4b_agente_assume_com_a_automacao_DESLIGADA():
    """O caso que o desligamento de 24/08 revelou.

    O checklist de ativação do agente manda desligar `auto_welcome_config`. Se o passo 1
    saísse da função por causa disso, o passo 4.5 nunca rodaria e os leads do sync ficariam
    SEM abertura nenhuma — a metade do agente que não vem da landing page morreria em
    silêncio, com o lead carimbado como "automação desligada".
    """
    lead = _lead(status=None)
    db = _fake_db(lead, _nat_cfg(qualificacao_enabled=True))
    with patch.object(exact_spotter, "send_template_message", new=AsyncMock()) as spy, \
         patch("app.qualificacao_gatilho.agendar_abertura",
               new=AsyncMock(return_value=(True, "enfileirado"))) as gatilho:
        r = await exact_spotter.send_welcome_to_new_lead(
            _lead_data(lead), db, _cfg(enabled=False))     # <-- automação DESLIGADA
    assert r["reason"] == "agente_assumiu", r
    assert spy.call_count == 0, "FALHOU: mandou boas-vindas com a automação desligada!"
    assert gatilho.await_count == 1, "FALHOU: o agente não foi enfileirado!"
    assert lead.welcome_status == "skipped"
    print(f"  4b. automação OFF + agente ON      -> {r['status']}/{r['reason']:18s} "
          f"envios={spy.call_count}  gatilho={gatilho.await_count}  "
          f"carimbo={lead.welcome_status!r}")


async def caso_4c_automacao_e_agente_desligados():
    """Não-regressão: com os dois desligados, o comportamento é o de sempre."""
    lead = _lead(status=None)
    db = _fake_db(lead, _nat_cfg(qualificacao_enabled=False))
    with patch.object(exact_spotter, "send_template_message", new=AsyncMock()) as spy:
        r = await exact_spotter.send_welcome_to_new_lead(
            _lead_data(lead), db, _cfg(enabled=False))
    assert r["reason"] == "disabled", r
    assert spy.call_count == 0
    assert lead.welcome_status == "skipped"
    print(f"  4c. automação OFF + agente OFF     -> {r['status']}/{r['reason']:18s} "
          f"envios={spy.call_count}  carimbo={lead.welcome_status!r}")


async def caso_5_canal_em_branco():
    lead = _lead(status=None)
    db = _fake_db(lead, _nat_cfg())
    with patch.object(exact_spotter, "send_template_message", new=AsyncMock()) as spy:
        r = await exact_spotter.send_welcome_to_new_lead(
            _lead_data(lead), db, _cfg(enabled=True, channel_id=None))
    assert r["status"] == "failed" and r["reason"] == "no_channel", r
    assert spy.call_count == 0, "FALHOU: tentou enviar sem canal!"
    assert lead.welcome_status == "failed", "FALHOU: falha silenciosa, nao gravou estado!"
    print(f"  5. canal em branco na config       -> {r['status']}/{r['reason']:18s} "
          f"envios={spy.call_count}  carimbo={lead.welcome_status!r}")
    print(f"     motivo gravado: {lead.welcome_error!r}")


async def caso_6_trava_do_envio_em_massa():
    from app.exact_routes import bulk_send_template
    db = _fake_db(_cfg(enabled=False))                  # get_auto_welcome_config
    payload = {"template_name": "nat_boasvindas", "language": "pt_BR",
               "channel_id": 1, "lead_ids": [1, 2, 3]}
    try:
        await bulk_send_template(payload, db)
        raise AssertionError("FALHOU: o envio em massa do nat_boasvindas NAO foi bloqueado!")
    except HTTPException as e:
        assert e.status_code == 400, e
        print(f"  6. bulk-send nat_boasvindas        -> HTTP {e.status_code} BLOQUEADO")
        print(f"     {e.detail}")


async def caso_7_send_template_bloqueado():
    from app import routes
    from app.routes import send_template, SendTemplateRequest
    req = SendTemplateRequest(to="5583999999999", template_name="nat_boasvindas", channel_id=1)
    db = _fake_db(_cfg(enabled=False))
    status = None
    with patch.object(routes, "send_template_message", new=AsyncMock()) as spy:
        try:
            await send_template(req, db)
            raise AssertionError("FALHOU: /send/template NAO bloqueou o nat_boasvindas!")
        except HTTPException as e:
            status = e.status_code
    assert status == 400, status
    assert spy.call_count == 0, "FALHOU: chegou a chamar a Meta!"
    print(f"  7. /send/template nat_boasvindas   -> HTTP {status} BLOQUEADO   envios={spy.call_count}")


async def caso_8_send_template_outro_passa():
    from app import routes
    from app.routes import send_template, SendTemplateRequest
    req = SendTemplateRequest(to="5583999999999", template_name="sdr_primeiro_contato", channel_id=1)
    db = _fake_db(_cfg(enabled=False))
    with patch.object(routes, "send_template_message", new=AsyncMock(return_value={})) as spy, \
         patch.object(routes, "get_channel", new=AsyncMock(return_value=CHANNEL)):
        await send_template(req, db)   # nao pode levantar HTTPException
    assert spy.call_count == 1, "FALHOU: bloqueou um template legitimo!"
    print(f"  8. /send/template outro template   -> passou (nao bloqueado)  envios={spy.call_count}")


async def caso_9_agendamento_bloqueado_na_criacao():
    from app.routes import create_scheduled_message, ScheduleMessageRequest
    req = ScheduleMessageRequest(template_name="nat_boasvindas", channel_id=1,
                                 lead_ids=[1, 2], scheduled_at="2030-01-01T10:00:00")
    db = _fake_db(_cfg(enabled=False))
    status = None
    try:
        await create_scheduled_message(req, db, MagicMock(id=1, name="Teste"))
        raise AssertionError("FALHOU: agendou o nat_boasvindas!")
    except HTTPException as e:
        status = e.status_code
    assert status == 400, status
    assert db.add.call_count == 0, "FALHOU: criou a linha de agendamento!"
    print(f"  9. /scheduled-messages nat_boas..  -> HTTP {status} BLOQUEADO na CRIACAO")


async def caso_10_agendamento_outro_passa():
    from app.routes import create_scheduled_message, ScheduleMessageRequest
    req = ScheduleMessageRequest(template_name="sdr_primeiro_contato", channel_id=1,
                                 lead_ids=[1], scheduled_at="2030-01-01T10:00:00")
    db = _fake_db(_cfg(enabled=False))
    await create_scheduled_message(req, db, MagicMock(id=1, name="Teste"))  # nao pode levantar
    assert db.add.call_count == 1, "FALHOU: bloqueou um agendamento legitimo!"
    print(f" 10. /scheduled-messages outro tpl   -> passou (agendamento criado)")


async def caso_11_variacao_de_caixa():
    from app.welcome_guard import bloquear_se_boas_vindas
    for variacao in ["  NAT_BoasVindas  ", "NAT_BOASVINDAS", "nat_BoasVindas"]:
        db = _fake_db(_cfg(enabled=False))
        try:
            await bloquear_se_boas_vindas(variacao, db)
            raise AssertionError(f"FALHOU: {variacao!r} passou pela trava!")
        except HTTPException as e:
            assert e.status_code == 400
    print(f" 11. variacoes de caixa/espaco       -> HTTP 400 nas 3 (trava normaliza)")


async def caso_12_automacao_continua_funcionando():
    """⭐ Prova de que a trava foi na PORTA e nao no CORREDOR: se estivesse dentro de
    send_template_message, a propria automacao teria sido bloqueada."""
    lead = _lead(status=None)
    db = _fake_db(lead, _nat_cfg(), CHANNEL, None, None, None)
    with patch.object(exact_spotter, "send_template_message",
                      new=AsyncMock(return_value=OK_SEND)) as spy, \
         patch.object(whatsapp, "fetch_template_body",
                      new=AsyncMock(return_value="Olá, {{1}}! Curso: {{2}}")):
        r = await exact_spotter.send_welcome_to_new_lead(_lead_data(lead), db, _cfg(enabled=True))
    assert r["status"] == "sent", f"FALHOU: a trava quebrou a automacao! {r}"
    assert spy.call_count == 1, "FALHOU: a automacao nao enviou!"
    assert lead.welcome_status == "sent" and lead.welcome_sent_at is not None
    print(f" 12. AUTOMACAO (nat_boasvindas)      -> {r['status']}/{r['reason']} envios={spy.call_count}"
          f"  <-- a trava NAO quebrou o fluxo automatico")


def _client(db_falso=None):
    """App real, mas com o banco trocado por um falso. Sem lifespan: os jobs de
    background NAO sobem (TestClient fora do `with` nao dispara startup)."""
    from app.main import app
    from app.database import get_db

    async def _db_override():
        yield db_falso if db_falso is not None else _fake_db()

    app.dependency_overrides[get_db] = _db_override
    return app, TestClient(app)


def _logar_usuario_falso(app):
    """Simula 'SDR logado' SEM usuario real e SEM token real: troca a propria
    dependencia de login por uma que devolve um usuario de mentira."""
    from app.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: MagicMock(
        id=999, name="Usuario Falso do Teste", role="admin", is_active=True)


def _limpar(app):
    app.dependency_overrides.clear()


async def caso_13_resend_welcome_sem_token():
    """A porta lateral (force=True fura TODOS os guardas) tem que exigir login."""
    app, client = _client()                        # anonimo: nenhum login injetado
    with patch.object(exact_spotter, "send_template_message", new=AsyncMock()) as spy:
        r = client.post("/api/exact-leads/999999999/resend-welcome")
    _limpar(app)
    assert r.status_code == 401, f"FALHOU: porta lateral ABERTA! HTTP {r.status_code}"
    assert spy.call_count == 0, "FALHOU: chegou a enviar sem login!"
    print(f" 13. /resend-welcome SEM token       -> HTTP {r.status_code} BLOQUEADO   envios={spy.call_count}")


async def caso_14_resend_welcome_logado_mas_desligado():
    """Defesa em profundidade: nem quem esta logado reenvia com o botao desligado."""
    lead = _lead(status="skipped")
    db = _fake_db(lead, _cfg(enabled=False))       # 1o execute: lead | 2o: a config
    app, client = _client(db)
    _logar_usuario_falso(app)
    with patch.object(exact_spotter, "send_template_message", new=AsyncMock()) as spy:
        r = client.post(f"/api/exact-leads/{lead.exact_id}/resend-welcome")
    _limpar(app)
    assert r.status_code == 400, f"FALHOU: reenviou com a automacao desligada! HTTP {r.status_code}"
    assert spy.call_count == 0, "FALHOU: chegou a chamar a Meta com o botao desligado!"
    print(f" 14. /resend-welcome LOGADO+desligado-> HTTP {r.status_code} BLOQUEADO   envios={spy.call_count}")
    print(f"     {r.json()['detail']}")


async def caso_15_botao_sem_token():
    """Sem esta fechadura, um estranho liga a automacao e a trava do caso 14 nao vale nada."""
    cfg = _cfg(enabled=False)
    db = _fake_db(cfg)
    app, client = _client(db)                      # anonimo: nenhum login injetado
    r = client.put("/api/auto-welcome/config", json={"enabled": True})
    _limpar(app)
    assert r.status_code == 401, f"FALHOU: ESTRANHO PODE LIGAR A AUTOMACAO! HTTP {r.status_code}"
    assert cfg.enabled is False, "FALHOU: a config foi alterada sem login!"
    assert db.commit.call_count == 0, "FALHOU: gravou no banco sem login!"
    print(f" 15. PUT /auto-welcome/config s/token-> HTTP {r.status_code} BLOQUEADO   "
          f"enabled continua {cfg.enabled}  commits={db.commit.call_count}")


async def main():
    print("\nGuardrail da boas-vindas (nenhum envio real — tudo mockado)\n")
    await caso_1_funil_fora_do_escopo()
    await caso_2_automacao_desligada()
    await caso_3_lead_ja_processado()
    await caso_4_envio_normal()
    await caso_4b_agente_assume_com_a_automacao_DESLIGADA()
    await caso_4c_automacao_e_agente_desligados()
    await caso_5_canal_em_branco()
    await caso_6_trava_do_envio_em_massa()
    print()
    await caso_7_send_template_bloqueado()
    await caso_8_send_template_outro_passa()
    await caso_9_agendamento_bloqueado_na_criacao()
    await caso_10_agendamento_outro_passa()
    await caso_11_variacao_de_caixa()
    await caso_12_automacao_continua_funcionando()
    print()
    await caso_13_resend_welcome_sem_token()
    await caso_14_resend_welcome_logado_mas_desligado()
    await caso_15_botao_sem_token()
    print("\nOK: 17/17 passaram. Todas as PORTAS de envio travadas; a porta lateral e o botao "
          "agora exigem login; a automacao continua funcionando.\n")


if __name__ == "__main__":
    asyncio.run(main())
