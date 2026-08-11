"""Fase 2 do sprint de ativação: quem pede outro horário não vira beco sem saída.

Rodar: cd backend && venv/bin/python test_nat_reagendado.py

Nenhuma mensagem real, nenhuma conexão: envio mockado, banco dublê em memória.

  1. clique "Prefiro outro horário" -> nat_outro_horario sai E o SDR dono é avisado
  2. o texto do lead ATUALIZA o aviso do clique (um item no sino, não dois) e reabre o não-lido
  3. lead sem SDR -> o aviso vai para a gestão (id=2), igual à transferência
  4. o aviso não sai antes da mensagem, e o envio que falha não avisa ninguém
  5. formato: telefone no título e no começo do corpo; título NÃO diz "ligar agora"
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app import nat_copy, nat_flow
from app.models import ETAPA_AGUARDANDO_RESPOSTA, ETAPA_REAGENDADO, Notification, NatFlowState
from app.nat_guard import GESTOR_USER_ID

WA_ID = "5583999998888"
DADOS = {"nome": "Ana Prado", "curso": "Psicologia", "formacao": ""}


class _DbFalso:
    """Guarda o que for add() e devolve o aviso já existente quando perguntado."""

    def __init__(self, aviso_existente=None):
        self.adicionados = []
        self._aviso = aviso_existente

    async def execute(self, *a, **k):
        res = MagicMock()
        res.scalar_one_or_none.return_value = self._aviso
        return res

    def add(self, obj):
        self.adicionados.append(obj)
        if isinstance(obj, Notification):
            self._aviso = obj          # o próximo lookup encontra este

    async def flush(self):
        pass

    def begin_nested(self):
        return _Savepoint()

    def notificacoes(self):
        return [o for o in self.adicionados if isinstance(o, Notification)]


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _state(etapa=ETAPA_AGUARDANDO_RESPOSTA, sdr=4, horario=None):
    s = NatFlowState(contact_wa_id=WA_ID, exact_lead_id=999, sdr_user_id=sdr, etapa=etapa)
    s.ultimo_wa_message_id = None
    s.horario_preferencial = horario
    return s


def _evento(wa_message_id="wamid.CLIQUE"):
    return {"contact_wa_id": WA_ID, "wa_message_id": wa_message_id,
            "button_payload": nat_copy.NAT_OUTRO_HORARIO,
            "button_text": "Prefiro outro horário", "source": "template"}


# ---------------------------------------------------------------------------------------
async def caso_1_clique_avisa_o_sdr():
    state = _state()
    db = _DbFalso()
    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "_dados_do_lead", new=AsyncMock(return_value=DADOS)), \
         patch.object(nat_flow, "usuario_existe", new=AsyncMock(return_value=True)), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock(return_value=True)) as spy:
        destino = await nat_flow.processar_clique(_evento(), db)

    assert destino == ETAPA_REAGENDADO, destino
    assert spy.await_args[0][1] == nat_copy.NAT_MSG_OUTRO_HORARIO, spy.await_args
    notifs = db.notificacoes()
    assert len(notifs) == 1, f"esperava 1 aviso, veio {len(notifs)}"
    n = notifs[0]
    assert n.user_id == 4, f"o aviso tem que ir para o SDR dono, foi para {n.user_id}"
    assert n.type == nat_flow.TIPO_NOTIF_REAGENDADO, n.type
    assert n.ref == "wamid.CLIQUE", n.ref
    assert "ainda não disse quando" in n.body, n.body
    print(f"  1. clique -> enviou {spy.await_args[0][1]} e avisou user {n.user_id}")
    print(f"     título: {n.title}")
    print(f"     corpo : {n.body}")


async def caso_2_texto_atualiza_o_aviso():
    """O período chega depois. UM item no sino, atualizado — não dois."""
    state = _state(etapa=ETAPA_REAGENDADO)
    db = _DbFalso()

    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "_dados_do_lead", new=AsyncMock(return_value=DADOS)), \
         patch.object(nat_flow, "usuario_existe", new=AsyncMock(return_value=True)), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock(return_value=True)):
        # 1) o clique cria o aviso
        state.etapa = ETAPA_AGUARDANDO_RESPOSTA
        await nat_flow.processar_clique(_evento(), db)
        aviso = db.notificacoes()[0]
        titulo_antes, corpo_antes = aviso.title, aviso.body
        aviso.is_read = True                     # o SDR leu o aviso do clique

        # 2) o lead diz quando
        await nat_flow.processar_texto(WA_ID, "pode ser de manhã, antes das 10h",
                                       "wamid.TXT", db)

    assert state.horario_preferencial == "pode ser de manhã, antes das 10h", \
        state.horario_preferencial
    notifs = db.notificacoes()
    assert len(notifs) == 1, \
        f"FALHOU: {len(notifs)} avisos no sino para o mesmo pedido — esperava 1 atualizado"
    n = notifs[0]
    assert n.title != titulo_antes and n.body != corpo_antes, "o aviso não foi atualizado"
    assert "de manhã" in n.title, f"o período tem que subir para o título: {n.title}"
    assert "antes das 10h" in n.body, n.body
    assert n.is_read is False, \
        "FALHOU: o aviso continuou lido — o SDR nunca veria o período que o lead informou"
    assert n.ref == "wamid.CLIQUE", f"o ref deve seguir apontando para o clique: {n.ref}"
    print(f"  2. texto do lead ATUALIZOU o mesmo aviso (1 item no sino), is_read={n.is_read}")
    print(f"     título: {n.title}")
    print(f"     corpo : {n.body}")

    # Segundo texto não mexe em mais nada.
    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "_dados_do_lead", new=AsyncMock(return_value=DADOS)), \
         patch.object(nat_flow, "usuario_existe", new=AsyncMock(return_value=True)):
        await nat_flow.processar_texto(WA_ID, "ou à tarde também dá", "wamid.TXT2", db)
    assert state.horario_preferencial == "pode ser de manhã, antes das 10h", \
        "o segundo texto sobrescreveu o período"
    assert len(db.notificacoes()) == 1
    print("     2º texto do lead -> período e aviso intactos (só o 1º conta)")


async def caso_3_sem_sdr_cai_na_gestao():
    state = _state(sdr=None)
    db = _DbFalso()

    async def _existe(uid, _db):
        return uid == GESTOR_USER_ID          # só a gestora existe

    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "_dados_do_lead", new=AsyncMock(return_value=DADOS)), \
         patch.object(nat_flow, "usuario_existe", new=AsyncMock(side_effect=_existe)), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock(return_value=True)):
        await nat_flow.processar_clique(_evento(), db)

    n = db.notificacoes()[0]
    assert n.user_id == GESTOR_USER_ID, n.user_id
    assert "SEM SDR" in n.title, n.title
    assert "avisando a gestão" in n.body, n.body
    print(f"  3. lead sem SDR -> aviso para a gestão (id={n.user_id}): {n.title}")


async def caso_4_envio_falhou_nao_avisa():
    """Se o nat_outro_horario não saiu, o lead não sabe de nada — ninguém é avisado."""
    state = _state()
    db = _DbFalso()
    with patch.object(nat_flow, "_estado_do_contato", new=AsyncMock(return_value=state)), \
         patch.object(nat_flow, "_dados_do_lead", new=AsyncMock(return_value=DADOS)), \
         patch.object(nat_flow, "usuario_existe", new=AsyncMock(return_value=True)), \
         patch.object(nat_flow, "send_nat_message", new=AsyncMock(return_value=False)):
        destino = await nat_flow.processar_clique(_evento(), db)
    assert destino is None, destino
    assert state.etapa == ETAPA_AGUARDANDO_RESPOSTA, "não podia ter avançado"
    assert db.notificacoes() == [], \
        "FALHOU: avisou o SDR de um reagendamento que a NAT nunca confirmou ao lead"
    print("  4. envio falhou -> etapa intacta, 0 avisos")


async def caso_5_formato_nao_confunde_com_transferencia():
    sem, corpo_sem = nat_flow.montar_notificacao_reagendamento(
        "Ana Prado", WA_ID, "Psicologia", "")
    com, corpo_com = nat_flow.montar_notificacao_reagendamento(
        "Ana Prado", WA_ID, "Psicologia", "depois das 18h")
    fone = nat_flow.telefone_legivel(WA_ID)

    for titulo, corpo in ((sem, corpo_sem), (com, corpo_com)):
        assert fone in titulo, f"telefone fora do título: {titulo}"
        assert corpo.startswith(fone), f"telefone não abre o corpo: {corpo}"
        assert "Psicologia" in corpo, corpo
        assert len(titulo) <= 255
        assert "ligar agora" not in titulo.lower(), \
            f"FALHOU: título parece transferência — o SDR ligaria na hora: {titulo}"
    assert "depois das 18h" in com, com
    print(f"  5. sem período: {sem}")
    print(f"     com período: {com}")
    print(f"     corpo      : {corpo_com}")


async def main():
    print("\nFase 2 — saída de `reagendado` (banco falso, nenhum envio real)\n")
    await caso_1_clique_avisa_o_sdr()
    await caso_2_texto_atualiza_o_aviso()
    await caso_3_sem_sdr_cai_na_gestao()
    await caso_4_envio_falhou_nao_avisa()
    await caso_5_formato_nao_confunde_com_transferencia()
    print("\nOK: 5/5 passaram. Quem pede outro horário sempre tem um humano encarregado.\n")


if __name__ == "__main__":
    asyncio.run(main())
