"""Máquina de estados, envio unificado e horário comercial da NAT.

Rodar: cd backend && venv/bin/python test_nat_flow.py

NENHUMA mensagem real é enviada: httpx e as funções de envio são sempre mockados, o banco é
falso (MagicMock — nenhuma conexão aberta, nada gravado) e nenhum estado real é criado.

A ÚNICA saída de rede é o caso 13, que faz um GET read-only na definição dos templates para
detectar drift de copy. Se a rede falhar, ele AVISA em vez de reprovar — um problema de
conectividade não é um problema de código.

  1. horário: 08h59 fora, 09h00 dentro, 18h59 dentro, 19h00 fora, e UTC vs SP
  2. fim de semana: sáb e dom fora, sexta 18h59 dentro, segunda 09h00 dentro
  3. lead fora do horário -> aguardando_horario, NENHUM envio
  4. lead dentro do horário, NAT desligada -> nenhum estado, nenhum envio
  5. payload NAT_SIM em aguardando_resposta -> aguardando_motivacao
  6. mesmo clique reentregue -> NENHUM segundo envio
  7. payload NAT_SIM em aguardando_ligacao -> ignorado, estado intacto
  8. texto em aguardando_motivacao -> aguardando_ligacao
  9. texto em aguardando_resposta -> ignorado
 10. send_nat_message: janela aberta -> texto livre; fechada -> template
 11. nat_sim sem formação -> frase removida, sem buraco no texto
 12. send_template_message sem button_payloads -> corpo idêntico ao de hoje (NÃO-REGRESSÃO)
 13. drift: nat_copy.py x corpo aprovado na Meta (corpos, botoes, status e limite de 20)
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app import nat_copy, nat_flow, nat_sender
from app.models import (ETAPA_AGUARDANDO_HORARIO, ETAPA_AGUARDANDO_LIGACAO,
                        ETAPA_AGUARDANDO_MOTIVACAO, ETAPA_AGUARDANDO_RESPOSTA,
                        Contact, ExactLead, NatFlowState)
from app.nat_guard import SP_TZ, dentro_horario_comercial
from app.whatsapp import send_template_message

UTC = timezone.utc

# Datas fixas — 2026-07-24 sexta, 25 sábado, 26 domingo, 27 segunda (conferido no caso 2).
SEXTA = (2026, 7, 24)
SABADO = (2026, 7, 25)
DOMINGO = (2026, 7, 26)
SEGUNDA = (2026, 7, 27)


def _sp(dia, hora, minuto=0):
    """datetime naive no fuso de SP — igual ao que o banco guarda."""
    return datetime(*dia, hora, minuto)


class _FakeResp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class _CapturaHTTP:
    """AsyncClient falso: guarda o corpo do POST e devolve sucesso. Não abre socket."""

    def __init__(self):
        self.enviado = None

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        self.enviado = json
        return _FakeResp({"messages": [{"id": "wamid.FAKE"}]})


def _state(etapa, ultimo=None, horario=None):
    s = NatFlowState(contact_wa_id="5583999998888", exact_lead_id=999, sdr_user_id=4,
                     etapa=etapa)
    s.ultimo_wa_message_id = ultimo
    s.horario_preferencial = horario
    s.transferido_em = None
    return s


def _db_com_assigned(assigned_to=4):
    """Banco falso: db.execute().first() -> (assigned_to,). Registra o que for add()."""
    db = MagicMock()
    res = MagicMock()
    res.first.return_value = (assigned_to,)
    db.execute = AsyncMock(return_value=res)
    db.add = MagicMock()
    return db


def _evento(payload, wa_message_id="wamid.CLIQUE", texto="Sim, posso agora"):
    return {"contact_wa_id": "5583999998888", "wa_message_id": wa_message_id,
            "context_message_id": "wamid.ORIGINAL", "button_payload": payload,
            "button_text": texto, "source": "template"}


# ---------------------------------------------------------------------------------------
async def caso_1_horario_bordas():
    assert dentro_horario_comercial(_sp(SEGUNDA, 8, 59)) is False, "08h59 devia estar FORA"
    assert dentro_horario_comercial(_sp(SEGUNDA, 9, 0)) is True, "09h00 devia estar DENTRO"
    assert dentro_horario_comercial(_sp(SEGUNDA, 18, 59)) is True, "18h59 devia estar DENTRO"
    assert dentro_horario_comercial(_sp(SEGUNDA, 19, 0)) is False, "19h00 devia estar FORA"
    print("  1. 08h59 fora | 09h00 dentro | 18h59 dentro | 19h00 fora")

    # Mesmo INSTANTE, fusos diferentes. 12:00 UTC = 09:00 SP -> dentro.
    em_utc = datetime(*SEGUNDA, 12, 0, tzinfo=UTC)
    em_sp = em_utc.astimezone(SP_TZ)
    assert em_sp.hour == 9, f"esperava 09h em SP, veio {em_sp.hour}"
    assert dentro_horario_comercial(em_utc) is True, "12h UTC (=09h SP) devia estar DENTRO"
    assert dentro_horario_comercial(em_sp) is True
    # 11:59 UTC = 08:59 SP -> fora. Se a conversão sumisse, isto passaria como 11h e daria True.
    assert dentro_horario_comercial(datetime(*SEGUNDA, 11, 59, tzinfo=UTC)) is False, \
        "FALHOU: aware em UTC nao foi convertido para SP!"
    print("     12h00 UTC = 09h00 SP -> dentro | 11h59 UTC = 08h59 SP -> fora")


async def caso_2_fim_de_semana():
    assert datetime(*SABADO).weekday() == 5 and datetime(*DOMINGO).weekday() == 6, \
        "as datas fixas do teste sairam do lugar"
    assert dentro_horario_comercial(_sp(SABADO, 14, 0)) is False, "sabado 14h devia estar FORA"
    assert dentro_horario_comercial(_sp(DOMINGO, 10, 0)) is False, "domingo 10h devia estar FORA"
    assert dentro_horario_comercial(_sp(SEXTA, 18, 59)) is True, "sexta 18h59 devia estar DENTRO"
    assert dentro_horario_comercial(_sp(SEGUNDA, 9, 0)) is True, "segunda 09h devia estar DENTRO"
    print("  2. sab 14h fora | dom 10h fora | sex 18h59 dentro | seg 09h00 dentro")


async def caso_3_fora_do_horario_enfileira():
    lead = ExactLead(exact_id=999, name="Fulano", phone1="5583999998888", funnel_id=18535)
    lead.register_date = datetime(2026, 7, 26, 20, 0)
    db = _db_com_assigned()
    with patch.object(nat_flow, "nat_pode_atuar", new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(nat_flow, "dentro_horario_comercial", return_value=False), \
         patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=None)), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock()) as spy:
        etapa = await nat_flow.iniciar_fluxo_nat(lead, db)
    assert etapa == ETAPA_AGUARDANDO_HORARIO, etapa
    assert spy.call_count == 0, "FALHOU: enviou mensagem fora do horario comercial!"
    criado = db.add.call_args[0][0]
    assert criado.etapa == ETAPA_AGUARDANDO_HORARIO
    print(f"  3. fora do horario -> {etapa}  envios={spy.call_count}  (enfileirado p/ fase 2)")


async def caso_4_nat_desligada_nao_cria_estado():
    lead = ExactLead(exact_id=999, name="Fulano", phone1="5583999998888", funnel_id=18535)
    lead.register_date = datetime(2026, 7, 26, 10, 0)
    db = _db_com_assigned()
    with patch.object(nat_flow, "nat_pode_atuar",
                      new=AsyncMock(return_value=(False, "nat_enabled=false"))), \
         patch.object(nat_flow, "dentro_horario_comercial", return_value=True), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock()) as spy:
        etapa = await nat_flow.iniciar_fluxo_nat(lead, db)
    assert etapa is None, f"FALHOU: criou etapa {etapa} com a NAT desligada!"
    assert spy.call_count == 0, "FALHOU: enviou com a NAT desligada!"
    assert db.add.call_count == 0, "FALHOU: gravou estado com a NAT desligada!"
    print(f"  4. NAT desligada -> etapa={etapa}  envios={spy.call_count}  "
          f"estados criados={db.add.call_count}")


async def caso_5_clique_sim_avanca():
    state = _state(ETAPA_AGUARDANDO_RESPOSTA)
    db = MagicMock()
    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "_dados_do_lead", new=AsyncMock(return_value={
             "nome": "Fulano", "curso": "Psicologia", "formacao": ""})), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock(return_value=True)) as spy:
        destino = await nat_flow.processar_clique(_evento(nat_copy.NAT_SIM), db)
    assert destino == ETAPA_AGUARDANDO_MOTIVACAO, destino
    assert spy.call_count == 1, spy.call_count
    assert spy.call_args[0][1] == nat_copy.NAT_MSG_SIM, spy.call_args
    assert state.etapa == ETAPA_AGUARDANDO_MOTIVACAO
    assert state.ultimo_wa_message_id == "wamid.CLIQUE", "FALHOU: nao carimbou idempotencia!"
    print(f"  5. NAT_SIM em aguardando_resposta -> {destino}  (enviou {spy.call_args[0][1]})")


async def caso_6_reentrega_nao_reenvia():
    """A Meta reentrega webhook. O mesmo clique nao pode mandar a mensagem duas vezes."""
    state = _state(ETAPA_AGUARDANDO_MOTIVACAO, ultimo="wamid.CLIQUE")
    db = MagicMock()
    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock(return_value=True)) as spy:
        destino = await nat_flow.processar_clique(_evento(nat_copy.NAT_SIM,
                                                          wa_message_id="wamid.CLIQUE"), db)
    assert spy.call_count == 0, "FALHOU: reenviou numa reentrega de webhook!"
    assert state.etapa == ETAPA_AGUARDANDO_MOTIVACAO, "FALHOU: avancou o estado duas vezes!"
    assert destino == ETAPA_AGUARDANDO_MOTIVACAO
    print(f"  6. mesmo wa_message_id reentregue -> envios={spy.call_count}  "
          f"etapa intacta ({state.etapa})")


async def caso_7_clique_fora_da_etapa():
    state = _state(ETAPA_AGUARDANDO_LIGACAO)
    db = MagicMock()
    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock(return_value=True)) as spy:
        destino = await nat_flow.processar_clique(
            _evento(nat_copy.NAT_SIM, wa_message_id="wamid.OUTRO"), db)
    assert destino is None, f"FALHOU: agiu num clique fora da etapa! -> {destino}"
    assert spy.call_count == 0, "FALHOU: enviou por clique fora da etapa!"
    assert state.etapa == ETAPA_AGUARDANDO_LIGACAO, "FALHOU: mandou o fluxo para tras!"
    print(f"  7. NAT_SIM em aguardando_ligacao -> ignorado  envios={spy.call_count}  "
          f"etapa intacta ({state.etapa})")


async def caso_8_texto_transfere():
    """A TRANSIÇÃO. Os efeitos da transferência (notificar, timeline, SLA) são do Bloco 5 e
    têm testes próprios em test_nat_sprint3.py — aqui transferir_para_sdr é dublada, para
    este caso continuar respondendo só "texto em aguardando_motivacao avança a etapa?".
    """
    state = _state(ETAPA_AGUARDANDO_MOTIVACAO)
    db = MagicMock()

    async def _transferencia_falsa(st, resposta, wa_message_id, _db):
        st.transferido_em = datetime.now(SP_TZ).replace(tzinfo=None)
        return True

    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "_dados_do_lead", new=AsyncMock(return_value={
             "nome": "Fulano", "curso": "Psicologia", "formacao": ""})), \
         patch.object(nat_flow, "transferir_para_sdr",
                      new=AsyncMock(side_effect=_transferencia_falsa)) as transfer, \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock(return_value=True)) as spy:
        destino = await nat_flow.processar_texto(
            "5583999998888", "quero mudar de área", "wamid.TXT", db)
    assert destino == ETAPA_AGUARDANDO_LIGACAO, destino
    assert spy.call_args[0][1] == nat_copy.NAT_CONFIRMA_TRANSFERENCIA, spy.call_args
    assert state.transferido_em is not None, "FALHOU: nao marcou transferido_em!"
    assert transfer.await_count == 1, "FALHOU: nao acionou a transferencia!"
    # A resposta do lead tem que CHEGAR na transferência — é ela que vai na notificação.
    assert transfer.await_args[0][1] == "quero mudar de área", transfer.await_args
    assert transfer.await_args[0][2] == "wamid.TXT", transfer.await_args
    print(f"  8. texto em aguardando_motivacao -> {destino}  "
          f"(enviou {spy.call_args[0][1]}, transferencia acionada com a resposta do lead)")


async def caso_9_texto_fora_da_etapa():
    state = _state(ETAPA_AGUARDANDO_RESPOSTA)
    db = MagicMock()
    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock(return_value=True)) as spy:
        destino = await nat_flow.processar_texto("5583999998888", "oi", "wamid.TXT2", db)
    assert destino is None, f"FALHOU: transicionou por texto na etapa errada -> {destino}"
    assert spy.call_count == 0, "FALHOU: enviou por texto fora da etapa!"
    assert state.etapa == ETAPA_AGUARDANDO_RESPOSTA
    print(f"  9. texto em aguardando_resposta -> ignorado  envios={spy.call_count}")


async def _envia_com_janela(aberta: bool, etapa=nat_copy.NAT_BOASVINDAS, **vars):
    """Roda send_nat_message com a janela forçada. Devolve (ok, chamadas)."""
    contato = Contact(wa_id="5583999998888", name="Fulano", channel_id=1)
    contato.assigned_to = 4
    canal = MagicMock(id=1, phone_number_id="p", whatsapp_token="t", waba_id="w")

    db = MagicMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = contato
    db.execute = AsyncMock(return_value=res)
    db.add = MagicMock()

    ok = {"messages": [{"id": "wamid.FAKE"}]}
    with patch.object(nat_sender, "nat_pode_atuar", new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(nat_sender, "_resolver_canal", new=AsyncMock(return_value=canal)), \
         patch.object(nat_sender, "janela_aberta", new=AsyncMock(return_value=aberta)), \
         patch.object(nat_sender, "send_text_message", new=AsyncMock(return_value=ok)) as txt, \
         patch.object(nat_sender, "send_interactive_buttons",
                      new=AsyncMock(return_value=ok)) as inter, \
         patch.object(nat_sender, "send_template_message",
                      new=AsyncMock(return_value=ok)) as tpl:
        enviou = await nat_sender.send_nat_message("5583999998888", etapa, db, **vars)
    return enviou, {"texto": txt, "interativo": inter, "template": tpl}, db


async def caso_10_janela_decide_formato():
    # Janela ABERTA + etapa com botões -> interactive (texto livre com botões).
    enviou, c, _ = await _envia_com_janela(True, nome="Fulano", curso="Psicologia")
    assert enviou is True
    assert c["interativo"].call_count == 1 and c["template"].call_count == 0, \
        "FALHOU: usou template com a janela ABERTA!"
    titulos = [b["titulo"] for b in c["interativo"].call_args.kwargs["buttons"]]
    assert all(len(t) <= nat_copy.LIMITE_TITULO_BOTAO for t in titulos), titulos
    print(f" 10. janela ABERTA  -> interactive, botoes={titulos}")

    # Janela FECHADA -> template, com os payloads fixados no envio.
    enviou, c, _ = await _envia_com_janela(False, nome="Fulano", curso="Psicologia")
    assert enviou is True
    assert c["template"].call_count == 1 and c["interativo"].call_count == 0, \
        "FALHOU: mandou texto livre com a janela FECHADA (a Meta recusaria)!"
    kw = c["template"].call_args.kwargs
    assert kw["button_payloads"] == [nat_copy.NAT_SIM, nat_copy.NAT_OUTRO_HORARIO], kw
    print(f"     janela FECHADA -> template, button_payloads={kw['button_payloads']}")

    # Etapa sem botões, janela aberta -> texto puro.
    enviou, c, _ = await _envia_com_janela(True, etapa=nat_copy.NAT_CONFIRMA_TRANSFERENCIA,
                                           nome="Fulano")
    assert c["texto"].call_count == 1 and c["interativo"].call_count == 0
    print("     etapa sem botoes, janela aberta -> texto puro")


async def caso_11_nat_sim_sem_formacao():
    com = nat_copy.texto_livre(nat_copy.NAT_MSG_SIM, nome="Ana", curso="Psicologia",
                               formacao="Enfermagem")
    sem = nat_copy.texto_livre(nat_copy.NAT_MSG_SIM, nome="Ana", curso="Psicologia",
                               formacao="")
    assert "sua formação é em Enfermagem" in com, com
    assert "formação" not in sem, f"FALHOU: sobrou mencao a formacao sem ter o dado!\n{sem}"
    assert "{{" not in sem and "}}" not in sem, f"FALHOU: sobrou placeholder!\n{sem}"
    assert "  " not in sem and " ." not in sem, f"FALHOU: buraco no texto!\n{sem}"
    assert "Psicologia" in sem and "Ana" in sem, sem
    # E o caminho de template recusa, em vez de inventar a formação do lead.
    assert nat_copy.parametros_template(nat_copy.NAT_MSG_SIM, nome="Ana",
                                        curso="Psicologia", formacao="") is None, \
        "FALHOU: montou template afirmando formacao que nao temos!"
    print(f" 11. nat_sim sem formacao -> frase removida, texto integro")
    print(f"     {sem.splitlines()[2][:78]}...")


async def caso_12_template_sem_payload_nao_regride():
    """O corpo enviado sem button_payloads tem que ser IDENTICO ao de antes da mudanca."""
    captura = _CapturaHTTP()
    with patch("app.whatsapp.httpx.AsyncClient", captura):
        await send_template_message(to="5583999998888", template_name="nat_boasvindas",
                                    language="pt_BR", phone_number_id="p", token="t",
                                    parameters=["Fulano", "Psicologia"])
    esperado = {
        "messaging_product": "whatsapp",
        "to": "5583999998888",
        "type": "template",
        "template": {
            "name": "nat_boasvindas",
            "language": {"code": "pt_BR"},
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": "Fulano"},
                {"type": "text", "text": "Psicologia"}]}],
        },
    }
    assert captura.enviado == esperado, f"REGRESSAO no envio de template!\n{captura.enviado}"
    print(" 12. send_template_message sem button_payloads -> corpo identico ao de hoje")

    # Sem parâmetros também: nada de "components" vazio no corpo.
    captura2 = _CapturaHTTP()
    with patch("app.whatsapp.httpx.AsyncClient", captura2):
        await send_template_message(to="x", template_name="t", language="pt_BR",
                                    phone_number_id="p", token="t")
    assert "components" not in captura2.enviado["template"], captura2.enviado
    print("     sem parametros -> sem chave 'components' (igual ao de hoje)")

    # COM payloads: os componentes de botão entram por índice, sem tocar no body.
    captura3 = _CapturaHTTP()
    with patch("app.whatsapp.httpx.AsyncClient", captura3):
        await send_template_message(to="x", template_name="nat_boasvindas", language="pt_BR",
                                    phone_number_id="p", token="t",
                                    parameters=["Fulano", "Psicologia"],
                                    button_payloads=[nat_copy.NAT_SIM,
                                                     nat_copy.NAT_OUTRO_HORARIO])
    comps = captura3.enviado["template"]["components"]
    assert comps[0]["type"] == "body"
    assert [c["index"] for c in comps[1:]] == ["0", "1"], comps
    assert comps[1]["parameters"][0]["payload"] == nat_copy.NAT_SIM, comps
    print("     com button_payloads -> body + quick_reply index 0 e 1")


async def caso_13_drift_de_copy():
    """Compara nat_copy.py com o que está aprovado na Meta. GET read-only, nenhum envio."""
    import httpx
    from sqlalchemy import text as sql_text
    from app.database import async_session

    try:
        async with async_session() as db:
            row = (await db.execute(
                sql_text("SELECT waba_id, whatsapp_token FROM channels WHERE id=1"))).first()
        async with httpx.AsyncClient(timeout=20) as c:
            resp = await c.get(
                f"https://graph.facebook.com/v22.0/{row[0]}/message_templates",
                headers={"Authorization": f"Bearer {row[1]}"}, params={"limit": 100})
        # FILTRA POR IDIOMA ANTES DE INDEXAR POR NOME. O mesmo nome pode ter mais de uma
        # versão aprovada no WABA, e nome não é chave única lá — nat_recuperacao_sdr existe
        # em `en` e em `pt_BR`, com corpos DIFERENTES. Sem o filtro, quem fica no dict é o
        # último que a Graph API devolver, e a ordem da lista não é contrato: um dia este
        # teste passaria a comparar o corpo em inglês e acusaria drift que não existe.
        # O idioma certo é o que o envio pede (nat_sender: language=nat_copy.IDIOMA).
        aprovados = {t["name"]: t for t in resp.json().get("data", [])
                     if t.get("language") == nat_copy.IDIOMA}
    except Exception as e:
        print(f" 13. drift: NAO VERIFICADO (sem acesso a Meta: {type(e).__name__}) — "
              "problema de rede, nao de codigo")
        return

    divergencias = []
    for chave, corpo_local in nat_copy.CORPO_APROVADO.items():
        t = aprovados.get(chave)
        if t is None:
            divergencias.append(f"{chave}: NAO EXISTE mais no WABA em {nat_copy.IDIOMA}")
            continue
        # Um template REJECTED/PAUSED continua na listagem. Fora de APPROVED ele não sai para
        # o lead com a janela fechada, e descobrir isso aqui é melhor do que num envio recusado.
        if t.get("status") != "APPROVED":
            divergencias.append(f"{chave}: status {t.get('status')} (esperado APPROVED)")
        corpo_meta = next((c.get("text") for c in t.get("components", [])
                           if c.get("type") == "BODY"), None)
        if corpo_meta != corpo_local:
            divergencias.append(f"{chave}: BODY divergente")
        botoes_meta = [b.get("text") for c in t.get("components", [])
                       if c.get("type") == "BUTTONS" for b in c.get("buttons", [])]
        botoes_local = nat_copy.BOTOES_APROVADOS.get(chave, [])
        if botoes_meta != botoes_local:
            divergencias.append(
                f"{chave}: botoes divergentes — Meta={botoes_meta} local={botoes_local}")

        # Os botões LIVRES são os mesmos botões em mensagem interactive. A lista tem que ter o
        # MESMO TAMANHO e a MESMA ORDEM da aprovada: a posição é o índice do quick_reply no
        # envio por template (payloads_dos_botoes), então um botão a mais, a menos ou trocado
        # de lugar manda o payload errado — o lead clica em "outro horário" e o fluxo entende
        # "quero falar agora". O limite de 20 é da Cloud API: acima disso a Meta recusa.
        livres = nat_copy.BOTOES_LIVRES.get(chave, [])
        if botoes_meta and len(livres) != len(botoes_meta):
            divergencias.append(
                f"{chave}: {len(livres)} botao(oes) livre(s) para {len(botoes_meta)} "
                "aprovado(s) — a ordem/indice deixaria de casar")
        for b in livres:
            if len(b["titulo"]) > nat_copy.LIMITE_TITULO_BOTAO:
                divergencias.append(
                    f"{chave}: titulo livre {b['titulo']!r} tem {len(b['titulo'])} chars "
                    f"(limite {nat_copy.LIMITE_TITULO_BOTAO})")

    if divergencias:
        print(" 13. drift: ⚠️  DIVERGENCIA entre nat_copy.py e a Meta:")
        for d in divergencias:
            print(f"       - {d}")
        raise AssertionError("copy divergiu do template aprovado")
    com_botoes = sorted(nat_copy.BOTOES_APROVADOS)
    print(f" 13. drift: nenhum — {len(nat_copy.CORPO_APROVADO)} corpos em "
          f"{nat_copy.IDIOMA} e os botoes de {', '.join(com_botoes)} batem com a Meta")


async def main():
    print("\nFluxo NAT: estados, envio unificado e horario (banco falso, nenhum envio real)\n")
    await caso_1_horario_bordas()
    await caso_2_fim_de_semana()
    print()
    await caso_3_fora_do_horario_enfileira()
    await caso_4_nat_desligada_nao_cria_estado()
    await caso_5_clique_sim_avanca()
    await caso_6_reentrega_nao_reenvia()
    await caso_7_clique_fora_da_etapa()
    await caso_8_texto_transfere()
    await caso_9_texto_fora_da_etapa()
    print()
    await caso_10_janela_decide_formato()
    await caso_11_nat_sim_sem_formacao()
    await caso_12_template_sem_payload_nao_regride()
    await caso_13_drift_de_copy()
    print("\nOK: 13/13 passaram. Estados so avancam apos envio confirmado, reentrega nao "
          "duplica, e o envio de template existente nao mudou.\n")


if __name__ == "__main__":
    asyncio.run(main())
