"""Fase 1 do sprint de ativação: a nat_boasvindas sai UMA vez, não duas.

Rodar: cd backend && venv/bin/python test_nat_duplicata.py

NENHUMA mensagem real é enviada e NENHUMA conexão é aberta: o banco é um dublê em memória e
as três funções de envio da Cloud API (send_template_message em exact_spotter E em nat_sender,
send_text_message, send_interactive_buttons) são substituídas por contadores.

O caso 1 é a PROVA pedida no checkpoint: roda send_welcome_to_new_lead inteiro, com a NAT
LIGADA e liberada pelo guard, e conta quantas vezes um template foi para a Meta. Antes da
correção esse número era 2 (exact_spotter manda config.template_name, e iniciar_fluxo_nat
mandava nat_boasvindas de novo porque a janela de 24h de um lead novo está fechada).

  1. send_welcome_to_new_lead com a NAT ligada -> 1 envio, estado em aguardando_resposta
  2. adoção guarda o wamid da boas-vindas em ultimo_wa_message_id
  3. adoção fora do horário comercial -> NENHUM estado, NENHUM envio
  4. NÃO-REGRESSÃO: sem boas_vindas_wamid, iniciar_fluxo_nat continua enviando como antes
  5. o wamid outbound guardado no estado não trava o clique do lead (idempotência intacta)
"""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app import exact_spotter, nat_copy, nat_flow, nat_sender
from app.models import (ETAPA_AGUARDANDO_RESPOSTA, AIConversationSummary, Channel, Contact,
                        ExactLead, Message, NatFlowState)

WAMID_BOASVINDAS = "wamid.BOASVINDAS_QUE_JA_SAIU"


class _Resultado:
    """O que db.execute() devolve.

    `escalar` é o que scalar_one_or_none() entrega, `linha` o que first() entrega. São dois
    campos e não um porque Contact é consultado das duas formas: select(Contact) devolve o
    objeto, select(Contact.assigned_to) devolve a tupla.
    """

    def __init__(self, escalar=None, linha=None):
        self._escalar = escalar
        self._linha = linha

    def scalar_one_or_none(self):
        return self._escalar

    def scalar(self):
        return self._escalar

    def first(self):
        return self._linha

    def scalars(self):
        return iter([])


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _DbFalso:
    """Sessão de mentira que responde POR ENTIDADE, não por ordem de chamada.

    Responder por ordem seria armadilha: o caminho com o bug faz MAIS consultas que o
    corrigido, e uma fila ordenada simplesmente se esgotaria — o envio duplicado morreria
    num "contato não existe no banco" e o teste passaria a verde pelo motivo errado.
    Respondendo por entidade, os dois caminhos recebem o mesmo banco e a diferença que
    aparece é só a que estamos medindo: quantas mensagens foram para a Meta.
    """

    def __init__(self, por_entidade):
        self._mapa = por_entidade
        self.adicionados = []
        self.consultas = []

    async def execute(self, stmt, *a, **k):
        entidade = None
        try:
            descricoes = stmt.column_descriptions
            entidade = descricoes[0].get("entity") if descricoes else None
        except Exception:
            pass
        self.consultas.append(getattr(entidade, "__name__", str(entidade)))
        return self._mapa.get(entidade, _Resultado())

    def add(self, obj):
        self.adicionados.append(obj)

    async def flush(self):
        pass

    def begin_nested(self):
        return _Savepoint()

    def gravados(self, tipo):
        return [o for o in self.adicionados if isinstance(o, tipo)]


def _lead_row():
    lead = ExactLead(exact_id=999, name="Fulano de Tal", phone1="5583999998888",
                     funnel_id=18535, sub_source="psicologia")
    lead.register_date = datetime(2026, 8, 11, 10, 0)
    lead.welcome_status = None
    lead.welcome_sent_at = None
    lead.welcome_wamid = None
    lead.welcome_error = None
    return lead


def _config():
    cfg = MagicMock()
    cfg.enabled = True
    cfg.funnel_ids = "18535,18537,25588"
    cfg.channel_id = 1
    cfg.template_name = "nat_boasvindas"
    cfg.template_language = "pt_BR"
    return cfg


def _canal():
    c = Channel(id=1, name="CENAT")
    c.phone_number_id = "p"
    c.whatsapp_token = "t"
    c.waba_id = "w"
    return c


def _contato():
    c = Contact(wa_id="5583999998888", name="Fulano de Tal", channel_id=1)
    c.assigned_to = 4
    c.ai_active = True
    return c


# ---------------------------------------------------------------------------------------
async def caso_1_um_unico_envio():
    """A PROVA. Caminho real de produção, NAT ligada, contando o que foi para a Meta."""
    lead = _lead_row()
    lead_data = {"exact_id": 999, "name": "Fulano de Tal", "phone1": "5583999998888",
                 "funnel_id": 18535, "sub_source": "psicologia", "sdr_name": "Valéria"}

    # Banco completo: TUDO o que qualquer um dos dois caminhos possa consultar está aqui.
    # Message sem timestamp = nenhum inbound = janela de 24h FECHADA, que é a condição real
    # de um lead novo e exatamente a que fazia o sender repetir o template.
    db = _DbFalso({
        ExactLead: _Resultado(escalar=lead),
        Channel: _Resultado(escalar=_canal()),
        Contact: _Resultado(escalar=_contato(), linha=(4,)),
        AIConversationSummary: _Resultado(escalar=AIConversationSummary()),
        NatFlowState: _Resultado(escalar=None),
        Message: _Resultado(escalar=None),
    })

    ok = {"messages": [{"id": WAMID_BOASVINDAS}]}
    with patch.object(exact_spotter, "send_template_message",
                      new=AsyncMock(return_value=ok)) as tpl_welcome, \
         patch.object(nat_sender, "send_template_message",
                      new=AsyncMock(return_value=ok)) as tpl_nat, \
         patch.object(nat_sender, "send_text_message", new=AsyncMock(return_value=ok)) as txt, \
         patch.object(nat_sender, "send_interactive_buttons",
                      new=AsyncMock(return_value=ok)) as inter, \
         patch("app.whatsapp.fetch_template_body",
               new=AsyncMock(return_value="Olá {{1}}, sobre {{2}}")), \
         patch.object(exact_spotter, "resolve_course_name",
                      new=AsyncMock(return_value="Psicologia")), \
         patch.object(nat_flow, "nat_pode_atuar",
                      new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(nat_sender, "nat_pode_atuar",
                      new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(nat_flow, "dentro_horario_comercial", return_value=True):
        res = await exact_spotter.send_welcome_to_new_lead(lead_data, db, _config())

    assert res["status"] == "sent", res

    envios = (tpl_welcome.await_count + tpl_nat.await_count
              + txt.await_count + inter.await_count)
    assert envios == 1, (
        f"FALHOU: {envios} mensagens foram para a Meta, esperava 1. "
        f"boas-vindas={tpl_welcome.await_count} nat_template={tpl_nat.await_count} "
        f"texto={txt.await_count} interativo={inter.await_count}")
    assert tpl_welcome.await_count == 1, "quem envia a boas-vindas é send_welcome_to_new_lead"
    assert tpl_nat.await_count == 0, "FALHOU: a NAT reenviou o template por cima!"

    # E o lead ENTROU no fluxo — a correção não pode ter matado a adoção junto com a duplicata.
    estados = db.gravados(NatFlowState)
    assert len(estados) == 1, f"esperava 1 estado criado, veio {len(estados)}"
    assert estados[0].etapa == ETAPA_AGUARDANDO_RESPOSTA, estados[0].etapa

    # E só UMA linha de messages para essa boas-vindas.
    msgs = db.gravados(Message)
    assert len(msgs) == 1, f"FALHOU: {len(msgs)} linhas em messages para um envio só"
    assert msgs[0].wa_message_id == WAMID_BOASVINDAS

    print(f"  1. send_welcome_to_new_lead com a NAT LIGADA -> envios à Meta={envios} "
          f"(boas-vindas={tpl_welcome.await_count}, NAT={tpl_nat.await_count}), "
          f"1 linha em messages, estado={estados[0].etapa}")


async def caso_2_wamid_preservado():
    lead = _lead_row()
    db = _DbFalso({NatFlowState: _Resultado(escalar=None),
                   Contact: _Resultado(escalar=_contato(), linha=(4,))})
    with patch.object(nat_flow, "nat_pode_atuar", new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(nat_flow, "dentro_horario_comercial", return_value=True), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock()) as spy:
        etapa = await nat_flow.iniciar_fluxo_nat(lead, db,
                                                 boas_vindas_wamid=WAMID_BOASVINDAS)
    assert etapa == ETAPA_AGUARDANDO_RESPOSTA, etapa
    assert spy.await_count == 0, "FALHOU: enviou mesmo com a boas-vindas já entregue!"
    estado = db.gravados(NatFlowState)[0]
    assert estado.ultimo_wa_message_id == WAMID_BOASVINDAS, \
        f"FALHOU: rastro da boas-vindas perdido -> {estado.ultimo_wa_message_id!r}"
    assert estado.exact_lead_id == 999 and estado.sdr_user_id == 4
    print(f"  2. adoção guarda o wamid: ultimo_wa_message_id={estado.ultimo_wa_message_id!r} "
          f"(exact_lead_id={estado.exact_lead_id}, sdr={estado.sdr_user_id})")


async def caso_3_fora_do_horario_nao_adota():
    """A boas-vindas já saiu (a sync roda 24/7). Fora do horário a NAT NÃO adota o lead."""
    lead = _lead_row()
    db = _DbFalso({NatFlowState: _Resultado(escalar=None),
                   Contact: _Resultado(escalar=_contato(), linha=(4,))})
    with patch.object(nat_flow, "nat_pode_atuar", new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(nat_flow, "dentro_horario_comercial", return_value=False), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock()) as spy:
        etapa = await nat_flow.iniciar_fluxo_nat(lead, db,
                                                 boas_vindas_wamid=WAMID_BOASVINDAS)
    assert etapa is None, f"FALHOU: adotou lead fora do horário -> {etapa}"
    assert spy.await_count == 0, "FALHOU: enviou fora do horário comercial!"
    assert db.gravados(NatFlowState) == [], \
        "FALHOU: criou estado fora do horário — o clique do lead ficaria preso nele"
    print("  3. boas-vindas fora de 09h-19h -> etapa=None, 0 estados, 0 envios "
          "(clique segue p/ atendimento humano)")


async def caso_4_modo_antigo_nao_regride():
    """Sem boas_vindas_wamid, quem envia continua sendo a NAT. Comportamento intocado."""
    lead = _lead_row()
    db = _DbFalso({NatFlowState: _Resultado(escalar=None),
                   Contact: _Resultado(escalar=_contato(), linha=(4,))})
    with patch.object(nat_flow, "nat_pode_atuar", new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(nat_flow, "dentro_horario_comercial", return_value=True), \
         patch.object(nat_flow, "send_nat_message",
                      new=AsyncMock(return_value=True)) as spy, \
         patch.object(exact_spotter, "resolve_course_name",
                      new=AsyncMock(return_value="Psicologia")):
        etapa = await nat_flow.iniciar_fluxo_nat(lead, db)
    assert etapa == ETAPA_AGUARDANDO_RESPOSTA, etapa
    assert spy.await_count == 1, f"REGRESSÃO: o modo antigo parou de enviar ({spy.await_count})"
    assert spy.await_args[0][1] == nat_copy.NAT_BOASVINDAS, spy.await_args
    estado = db.gravados(NatFlowState)[0]
    assert estado.ultimo_wa_message_id is None, \
        "no modo antigo não há wamid conhecido para guardar"
    print(f"  4. NÃO-REGRESSÃO: sem wamid, iniciar_fluxo_nat ainda envia "
          f"{spy.await_args[0][1]} (1 envio) -> {etapa}")


async def caso_5_wamid_outbound_nao_trava_clique():
    """O wamid guardado é de OUTBOUND. Nenhum webhook de inbound chega com ele, então a
    trava de reentrega (_ja_processado) continua valendo só para o que o lead mandou."""
    state = NatFlowState(contact_wa_id="5583999998888", exact_lead_id=999, sdr_user_id=4,
                         etapa=ETAPA_AGUARDANDO_RESPOSTA)
    state.ultimo_wa_message_id = WAMID_BOASVINDAS
    assert nat_flow._ja_processado(state, "wamid.CLIQUE_DO_LEAD") is False, \
        "FALHOU: o wamid da boas-vindas engoliu o clique do lead!"
    assert nat_flow._ja_processado(state, WAMID_BOASVINDAS) is True

    db = MagicMock()
    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "_dados_do_lead", new=AsyncMock(return_value={
             "nome": "Fulano", "curso": "Psicologia", "formacao": ""})), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock(return_value=True)) as spy:
        destino = await nat_flow.processar_clique(
            {"contact_wa_id": "5583999998888", "wa_message_id": "wamid.CLIQUE_DO_LEAD",
             "button_payload": nat_copy.NAT_SIM, "button_text": "Sim, posso agora",
             "source": "template"}, db)
    assert spy.await_count == 1, "FALHOU: o clique do lead foi engolido pela idempotência!"
    print(f"  5. clique do lead sobre o estado adotado -> {destino} "
          f"(enviou {spy.await_args[0][1]}), wamid outbound não colide")


async def main():
    print("\nFase 1 — envio duplicado da nat_boasvindas (banco falso, nenhum envio real)\n")
    await caso_1_um_unico_envio()
    await caso_2_wamid_preservado()
    await caso_3_fora_do_horario_nao_adota()
    await caso_4_modo_antigo_nao_regride()
    await caso_5_wamid_outbound_nao_trava_clique()
    print("\nOK: 5/5 passaram. A boas-vindas sai UMA vez, o rastro dela fica no estado, "
          "e fora do horário a NAT não adota ninguém.\n")


if __name__ == "__main__":
    asyncio.run(main())
