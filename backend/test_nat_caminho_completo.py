"""O Cenário 1 inteiro, de ponta a ponta, num fluxo só.

Rodar: cd backend && venv/bin/python test_nat_caminho_completo.py

As outras suítes cobrem cada peça isoladamente, com as vizinhas dubladas. Esta cobre a
EMENDA entre elas: o mesmo lead, o mesmo banco e o mesmo estado atravessando os cinco passos
na ordem em que acontecem em produção. É o tipo de erro que teste de unidade não pega —
cada peça passa e a costura entre duas delas está trocada.

Nenhuma mensagem real e nenhuma conexão: só as chamadas à Cloud API e à Exact são
substituídas por contadores. A máquina de estados, o guard, o sender, a transferência e o
endpoint /assumir rodam de verdade.

  passo 1  lead entra pela boas-vindas  -> 1 envio, aguardando_resposta
  passo 2  clique "Sim"                 -> nat_sim,                    aguardando_motivacao
  passo 3  texto do lead                -> confirma_transferencia,     aguardando_ligacao
                                           + notificação ao SDR + sla_check em +2min
  passo 4  SDR clica "Assumir ligação"  -> encerrado, sla_check cancelado
  passo 5  lead clica de novo           -> ignorado, nada enviado
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import exact_spotter, nat_copy, nat_flow, nat_routes, nat_sender
from app.nat_guard import _agora_sp
from app.models import (ETAPA_AGUARDANDO_LIGACAO, ETAPA_AGUARDANDO_MOTIVACAO,
                        ETAPA_AGUARDANDO_RESPOSTA, ETAPA_ENCERRADO, AIConversationSummary,
                        Channel, Contact, ExactLead, KIND_VIGIAR_RESPOSTA, Message,
                        NatFlowState, Notification, User)

WA_ID = "5583999998888"
SDR_ID = 4

falhas = []


def check(nome, condicao, detalhe=""):
    print(f"  {'✅' if condicao else '❌'} {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


class _Resultado:
    def __init__(self, escalar=None, linha=None):
        self._e, self._l = escalar, linha

    def scalar_one_or_none(self):
        return self._e

    def scalar(self):
        return self._e

    def first(self):
        return self._l

    def scalars(self):
        return iter([])


class _Savepoint:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        self.db.savepoints += 1
        return self

    async def __aexit__(self, *a):
        return False


# Entidades que o teste lê de volta VIVAS, isto é: o que foi gravado num passo tem que
# aparecer na consulta do passo seguinte. É o que dá sentido a este arquivo — sem isso o
# passo 2 não acharia o estado que o passo 1 criou, e a costura entre eles, que é o objeto do
# teste, passaria despercebida.
#
# A lista é EXPLÍCITA e não "tudo que foi adicionado" de propósito: `messages` é gravada como
# objeto mas CONSULTADA por coluna (select(Message.timestamp), em janela_aberta), e devolver
# o objeto ali estoura num TypeError obscuro dentro do sender.
VIVOS = (NatFlowState, Notification)


class _Db:
    """Banco em memória que responde por ENTIDADE. Ver VIVOS acima."""

    def __init__(self, fixos):
        self.fixos = fixos
        self.adicionados = []
        self.savepoints = 0
        self.commits = 0

    async def execute(self, stmt, *a, **k):
        entidade = None
        try:
            d = stmt.column_descriptions
            entidade = d[0].get("entity") if d else None
        except Exception:
            pass
        if entidade in VIVOS:
            gravados = [o for o in self.adicionados if isinstance(o, entidade)]
            if gravados:
                return _Resultado(escalar=gravados[-1], linha=(gravados[-1],))
        return self.fixos.get(entidade, _Resultado())

    def add(self, obj):
        self.adicionados.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass

    def begin_nested(self):
        return _Savepoint(self)

    def de(self, tipo):
        return [o for o in self.adicionados if isinstance(o, tipo)]


def _monta_banco():
    lead = ExactLead(exact_id=999, name="Ana Prado", phone1=WA_ID, funnel_id=18535,
                     sub_source="psicologia")
    lead.register_date = datetime(2026, 8, 11, 10, 0)
    lead.welcome_status = None
    lead.welcome_sent_at = None
    lead.welcome_wamid = None
    lead.welcome_error = None

    canal = Channel(id=1, name="CENAT")
    canal.phone_number_id, canal.whatsapp_token, canal.waba_id = "p", "t", "w"

    contato = Contact(wa_id=WA_ID, name="Ana Prado", channel_id=1)
    contato.assigned_to = SDR_ID

    return lead, _Db({
        ExactLead: _Resultado(escalar=lead),
        Channel: _Resultado(escalar=canal),
        Contact: _Resultado(escalar=contato, linha=(SDR_ID,)),
        AIConversationSummary: _Resultado(escalar=AIConversationSummary()),
        NatFlowState: _Resultado(escalar=None),
        User: _Resultado(escalar=SDR_ID, linha=("Valéria",)),
        # Um inbound recente = janela de 24h ABERTA. É a verdade depois do clique do lead,
        # e é o que permite à NAT responder em texto livre — nat_sim por template seria
        # recusado por falta da formação (nat_copy.parametros_template).
        Message: _Resultado(escalar=_agora_sp()),
    })


def _config_welcome():
    return SimpleNamespace(enabled=True, funnel_ids="18535,18537,25588", channel_id=1,
                           template_name="nat_boasvindas", template_language="pt_BR")


async def main():
    print("\nCenário 1 ponta a ponta — mesmo lead, mesmo banco, cinco passos\n")

    lead, db = _monta_banco()
    ok_meta = {"messages": [{"id": "wamid.SAIU"}]}
    agendados, cancelados = [], []

    async def _agendar(kind, wa, quando, payload, _db):
        agendados.append((kind, wa, quando, payload))

    async def _cancelar(kind, wa, _db):
        cancelados.append((kind, wa))
        return 1

    envios = {}

    def _conta(nome, mock):
        envios[nome] = mock
        return mock

    with patch.object(exact_spotter, "send_template_message",
                      new=_conta("welcome", AsyncMock(return_value=ok_meta))), \
         patch.object(nat_sender, "send_template_message",
                      new=_conta("nat_template", AsyncMock(return_value=ok_meta))), \
         patch.object(nat_sender, "send_text_message",
                      new=_conta("nat_texto", AsyncMock(return_value=ok_meta))), \
         patch.object(nat_sender, "send_interactive_buttons",
                      new=_conta("nat_botoes", AsyncMock(return_value=ok_meta))), \
         patch("app.whatsapp.fetch_template_body",
               new=AsyncMock(return_value="Olá {{1}}, sobre {{2}}")), \
         patch.object(exact_spotter, "resolve_course_name",
                      new=AsyncMock(return_value="Psicologia")), \
         patch.object(nat_flow, "nat_pode_atuar", new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(nat_sender, "nat_pode_atuar", new=AsyncMock(return_value=(True, "ok"))), \
         patch.object(nat_flow, "dentro_horario_comercial", return_value=True), \
         patch("app.nat_scheduler.agendar", new=_agendar), \
         patch("app.nat_scheduler.cancelar", new=_cancelar), \
         patch("app.exact_spotter.add_timeline_comment", new=AsyncMock(return_value=True)):

        # ---------- passo 1: o lead entra ----------
        print("1) lead entra pela boas-vindas")
        r = await exact_spotter.send_welcome_to_new_lead(
            {"exact_id": 999, "name": "Ana Prado", "phone1": WA_ID, "funnel_id": 18535,
             "sub_source": "psicologia", "sdr_name": "Valéria"}, db, _config_welcome())

        total = sum(m.await_count for m in envios.values())
        estado = db.de(NatFlowState)[0] if db.de(NatFlowState) else None
        check("boas-vindas enviada", r["status"] == "sent", f"{r['status']}/{r['reason']}")
        check("UM único envio à Meta", total == 1, f"{total} envios")
        check("estado criado em aguardando_resposta",
              estado is not None and estado.etapa == ETAPA_AGUARDANDO_RESPOSTA,
              estado.etapa if estado else "nenhum estado")
        check("wamid da boas-vindas guardado no estado",
              estado.ultimo_wa_message_id == "wamid.SAIU", f"{estado.ultimo_wa_message_id}")

        # ---------- passo 2: clique "Sim" ----------
        print('2) lead clica "Sim, posso conversar agora"')
        destino = await nat_flow.processar_clique(
            {"contact_wa_id": WA_ID, "wa_message_id": "wamid.CLIQUE_SIM",
             "button_payload": nat_copy.NAT_SIM, "button_text": "Sim, posso agora",
             "source": "template"}, db)

        check("etapa avançou para aguardando_motivacao",
              destino == ETAPA_AGUARDANDO_MOTIVACAO and estado.etapa == destino, f"{destino}")
        check("a NAT respondeu (2º envio)", sum(m.await_count for m in envios.values()) == 2,
              f"{sum(m.await_count for m in envios.values())} envios acumulados")
        msgs_nat = [m for m in db.de(Message) if m.nat_etapa]
        check("o envio da NAT foi marcado com nat_etapa (é o que o teto conta)",
              msgs_nat and msgs_nat[-1].nat_etapa == nat_copy.NAT_MSG_SIM,
              f"{msgs_nat[-1].nat_etapa if msgs_nat else 'nenhum'}")

        # ---------- passo 3: o lead responde e é transferido ----------
        print("3) lead responde e é transferido")
        destino = await nat_flow.processar_texto(
            WA_ID, "quero mudar de área", "wamid.TEXTO", db)

        notifs = db.de(Notification)
        check("etapa avançou para aguardando_ligacao",
              destino == ETAPA_AGUARDANDO_LIGACAO and estado.etapa == destino, f"{destino}")
        check("confirmação de transferência enviada (3º envio)",
              sum(m.await_count for m in envios.values()) == 3,
              f"{sum(m.await_count for m in envios.values())} envios acumulados")
        check("SDR dono notificado", len(notifs) == 1 and notifs[0].user_id == SDR_ID,
              f"{len(notifs)} notificação(ões)")
        check("a notificação leva telefone, curso e a fala do lead",
              "quero mudar de área" in notifs[0].body and "Psicologia" in notifs[0].body,
              notifs[0].body)
        check("transferido_em carimbado", estado.transferido_em is not None,
              f"{estado.transferido_em}")
        check("sla_check agendado para +2min",
              len(agendados) == 1 and agendados[0][1] == WA_ID,
              f"{agendados}")

        # ---------- passo 4: o SDR assume ----------
        print('4) SDR clica "Assumir ligação"')
        resp = await nat_routes.assumir_ligacao(
            WA_ID, db, SimpleNamespace(id=SDR_ID, name="Valéria"))

        check("etapa virou encerrado", estado.etapa == ETAPA_ENCERRADO, f"{estado.etapa}")
        check("quem assumiu registrado", estado.assumido_por == SDR_ID,
              f"{estado.assumido_por}")
        # `in` e não igualdade: desde o P3-A (26/08) TODO envio da NAT cancela também o
        # `vigiar_resposta` do contato — o vigia do "AGENTE MUDO" não tem o que vigiar depois
        # que uma mensagem chegou ao lead. A travessia manda 3 mensagens, então a lista traz
        # 3 cancelamentos de vigia além deste. O que este passo afirma continua sendo o
        # mesmo: assumir a ligação MATA o SLA.
        check("sla_check cancelado", ("sla_check", WA_ID) in cancelados, f"{cancelados}")
        check("  e os demais cancelamentos são só do vigia (P3-A)",
              {k for k, _ in cancelados} == {"sla_check", KIND_VIGIAR_RESPOSTA},
              f"{sorted({k for k, _ in cancelados})}")
        check("botão some e selo aparece",
              resp["pode_assumir"] is False and resp["assumido_por"] == SDR_ID, f"{resp}")

        # ---------- passo 5: o lead clica de novo ----------
        print("5) lead clica de novo depois de encerrado")
        antes = sum(m.await_count for m in envios.values())
        d_clique = await nat_flow.processar_clique(
            {"contact_wa_id": WA_ID, "wa_message_id": "wamid.DEPOIS",
             "button_payload": nat_copy.NAT_SIM, "button_text": "Sim",
             "source": "template"}, db)
        d_texto = await nat_flow.processar_texto(WA_ID, "oi?", "wamid.DEPOIS2", db)

        check("clique ignorado sem erro", d_clique is None, f"{d_clique}")
        check("texto ignorado sem erro", d_texto is None, f"{d_texto}")
        check("NADA foi enviado depois de encerrado",
              sum(m.await_count for m in envios.values()) == antes,
              f"{sum(m.await_count for m in envios.values()) - antes} envios a mais")
        check("etapa continua encerrado", estado.etapa == ETAPA_ENCERRADO, f"{estado.etapa}")

    print(f"\nTotal na travessia: {sum(m.await_count for m in envios.values())} mensagens à "
          f"Meta (1 boas-vindas + 2 da NAT), {len(db.de(Notification))} notificação, "
          f"{len(agendados)} SLA agendado, {len(cancelados)} cancelado.")

    if falhas:
        print(f"\n❌ {len(falhas)} falha(s): {falhas}\n")
        raise SystemExit(1)
    print("\nOK: o Cenário 1 atravessa inteiro, sem duplicata e sem beco sem saída.\n")


if __name__ == "__main__":
    asyncio.run(main())
