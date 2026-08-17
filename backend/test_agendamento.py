"""Suíte do módulo de agendamento pela LP.

Rodar: cd backend && venv/bin/python test_agendamento.py

Nenhuma conexão: a Exact é mockada e o banco é dublê em memória. Nada é criado na agenda
real, nenhum lead é cadastrado.

   1. grade: 6 slots por dia útil, nada no fim de semana, antecedência respeitada
   2. fuso: para_exact NÃO converte para UTC — é este teste que trava o erro de 3 horas
   3. slot_por_id recusa horário forjado que não está na grade
   4. disponibilidade subtrai bloco sobreposto; encostar não é sobrepor
   5. caminho feliz: as 3 chamadas na ordem box -> lead -> schedule
   6. LeadsAdd falha -> box é removido, nada sobra
   7. scheduleAdd falha -> box é removido e O LEAD FICA (nunca LeadsDelete)
   8. slot ocupado no passo 1 -> SlotIndisponivel, e nem lead nem schedule são chamados
   9. duplo clique do mesmo telefone devolve o agendamento anterior, sem falar com a Exact
  10. faxina: remove o parado, promove o que tem reunião, mantém o que falhou por rede
  11. rate limit por IP corta o 6º POST na janela
"""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.agendamento import agendar as fluxo
from app.agendamento import client, disponibilidade, faxina
from app.agendamento.grade import recarregar
from app.agendamento.horarios import de_exact, para_exact
from app.models import (PASSO_AGENDADO, PASSO_BOX_CRIADO, PASSO_FALHOU, PASSO_LEAD_CRIADO,
                        Agendamento)

TELEFONE = "11999998888"


class _DbFalso:
    """Dublê de AsyncSession. Guarda o que for add() e responde o que for configurado."""

    def __init__(self, *, duplo=None, ocupados=None, pendentes=None):
        self.adicionados = []
        self.commits = 0
        self._duplo = duplo
        self._ocupados = ocupados or []
        self._pendentes = pendentes or []
        self._proximo_id = 1

    async def execute(self, *a, **k):
        res = MagicMock()
        res.scalar_one_or_none.return_value = self._duplo
        res.all.return_value = self._ocupados
        res.scalars.return_value.all.return_value = self._pendentes
        return res

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self._proximo_id
            self._proximo_id += 1
        self.adicionados.append(obj)

    async def commit(self):
        self.commits += 1

    async def flush(self):
        pass

    def agendamentos(self):
        return [o for o in self.adicionados if isinstance(o, Agendamento)]


def _slot_valido():
    """Primeiro slot livre da grade real — o que a LP ofereceria agora."""
    return recarregar().slots_candidatos()[0]


# ==========================================================================================


async def caso_1_grade():
    g = recarregar()
    qua = g.slots_do_dia(datetime(2026, 8, 19).date())
    sab = g.slots_do_dia(datetime(2026, 8, 22).date())

    horas = [(s.inicio.strftime("%H:%M"), s.fim.strftime("%H:%M")) for s in qua]
    assert horas == [("10:15", "11:00"), ("11:00", "11:45"), ("11:45", "12:30"),
                     ("12:30", "13:15"), ("16:00", "16:45"), ("16:45", "17:30")], horas
    assert sab == [], f"fim de semana não devia ter slot: {sab}"

    # Nenhum slot encosta nos blocos reais de comercial@ (09:00-10:10, 13:30-14:30,
    # 15:00-15:45). Se encostasse, o BoxesAdd recusaria com "Boxes are occupied".
    for s in qua:
        for bi, bf in [("09:00", "10:10"), ("13:30", "14:30"), ("15:00", "15:45")]:
            assert not (s.inicio.strftime("%H:%M") < bf and bi < s.fim.strftime("%H:%M")), \
                f"slot {s.id} colide com o bloco {bi}-{bf}"

    agora = datetime(2026, 8, 19, 11, 0)
    cand = g.slots_candidatos(agora=agora)
    assert all(s.inicio >= agora + timedelta(hours=2) for s in cand), "antecedência furada"
    assert cand[0].inicio == datetime(2026, 8, 19, 13, 0) or cand[0].inicio.hour >= 13, cand[0].id
    print(f"  1. 6 slots por dia útil, 0 no sábado, {len(cand)} candidatos com 2h de antecedência")


async def caso_2_fuso_nao_converte():
    """O teste que existe para alguém não 'consertar' o Z decorativo."""
    d = datetime(2026, 8, 19, 14, 0)          # 14:00 em São Paulo
    assert para_exact(d) == "2026-08-19T14:00:00Z", para_exact(d)
    assert para_exact(d) != "2026-08-19T17:00:00Z", \
        "FALHOU: converteu para UTC — a reunião seria agendada 3h adiantada"

    # Aware entra e sai como a MESMA hora de parede de SP.
    from app.agendamento.horarios import SP_TZ
    assert para_exact(d.replace(tzinfo=SP_TZ)) == "2026-08-19T14:00:00Z"

    # Ida e volta preserva.
    assert de_exact(para_exact(d)) == d
    assert de_exact("2027-03-10T11:00:00.0000000") == datetime(2027, 3, 10, 11, 0)
    print("  2. 14:00 SP -> '2026-08-19T14:00:00Z' (sem conversão), ida e volta preserva")


async def caso_3_slot_forjado():
    g = recarregar()
    assert g.slot_por_id("2026-08-23T03:00:00") is None, "aceitou 03:00 de domingo"
    assert g.slot_por_id("nao-e-data") is None
    assert g.slot_por_id("2020-01-01T10:15:00") is None, "aceitou slot no passado"
    valido = _slot_valido()
    assert g.slot_por_id(valido.id) is not None, "recusou slot da própria grade"
    print(f"  3. forjados recusados; {valido.id} (da grade) aceito")


async def caso_4_disponibilidade_subtrai():
    g = recarregar()
    alvo = _slot_valido()

    # Um bloco que cobre exatamente o slot alvo.
    boxes = [{"start": para_exact(alvo.inicio), "end": para_exact(alvo.fim)}]
    with patch.object(client, "listar_boxes", AsyncMock(return_value=boxes)):
        disponibilidade.invalidar_cache()
        livres = await disponibilidade.slots_livres(_DbFalso(), usar_cache=False)
    assert all(s.id != alvo.id for s in livres), "ofereceu slot já ocupado"

    # Um bloco que só ENCOSTA (termina onde o slot começa) não pode remover nada.
    encosta = [{"start": para_exact(alvo.inicio - timedelta(minutes=45)),
                "end": para_exact(alvo.inicio)}]
    with patch.object(client, "listar_boxes", AsyncMock(return_value=encosta)):
        disponibilidade.invalidar_cache()
        livres = await disponibilidade.slots_livres(_DbFalso(), usar_cache=False)
    assert any(s.id == alvo.id for s in livres), "removeu slot que só encostava no bloco"
    disponibilidade.invalidar_cache()
    print(f"  4. bloco sobreposto remove {alvo.id}; bloco que encosta não remove")


async def caso_5_caminho_feliz():
    db = _DbFalso()
    slot = _slot_valido()
    ordem = []

    async def _box(**k):
        ordem.append("box"); return 777

    async def _lead(**k):
        ordem.append("lead"); return 888

    async def _sched(**k):
        ordem.append("schedule"); return True

    with patch.object(client, "criar_box", _box), \
         patch.object(client, "criar_lead", _lead), \
         patch.object(client, "agendar_reuniao", _sched), \
         patch.object(client, "meeting_por_lead", AsyncMock(return_value={"id": 999})), \
         patch.object(client, "remover_box", AsyncMock()) as rm:
        r = await fluxo.agendar(db, nome="TESTE", email="a@b.com", telefone=TELEFONE,
                                slot_id=slot.id)

    assert ordem == ["box", "lead", "schedule"], f"ordem errada: {ordem}"
    assert (r.box_id, r.lead_id, r.meeting_id) == (777, 888, 999), r
    assert db.agendamentos()[0].passo == PASSO_AGENDADO
    rm.assert_not_awaited()
    print(f"  5. box -> lead -> schedule, passo={PASSO_AGENDADO}, meeting_id capturado")


async def caso_6_lead_falha_remove_box():
    db = _DbFalso()
    slot = _slot_valido()
    with patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", AsyncMock(side_effect=client.ExactErro("boom"))), \
         patch.object(client, "agendar_reuniao", AsyncMock()) as sched, \
         patch.object(client, "remover_box", AsyncMock()) as rm:
        try:
            await fluxo.agendar(db, nome="TESTE", email=None, telefone=TELEFONE,
                                slot_id=slot.id)
            assert False, "deveria ter levantado AgendamentoFalhou"
        except fluxo.AgendamentoFalhou as e:
            assert e.lead_id is None, "não havia lead para preservar"

    rm.assert_awaited_once_with(777)
    sched.assert_not_awaited()
    assert db.agendamentos()[0].passo == PASSO_FALHOU
    print("  6. LeadsAdd falhou -> BoxesRemove(777), schedule não chamado")


async def caso_7_schedule_falha_mantem_lead():
    db = _DbFalso()
    slot = _slot_valido()
    with patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", AsyncMock(return_value=888)), \
         patch.object(client, "agendar_reuniao",
                      AsyncMock(side_effect=client.BoxIndisponivel("ocupado"))), \
         patch.object(client, "remover_box", AsyncMock()) as rm:
        try:
            await fluxo.agendar(db, nome="TESTE", email=None, telefone=TELEFONE,
                                slot_id=slot.id)
            assert False, "deveria ter levantado AgendamentoFalhou"
        except fluxo.AgendamentoFalhou as e:
            assert e.lead_id == 888, f"o lead tem que sobreviver e ser reportado: {e.lead_id}"

    rm.assert_awaited_once_with(777)
    ag = db.agendamentos()[0]
    assert ag.passo == PASSO_FALHOU and ag.lead_id == 888
    # A prova de que ninguém inventou uma compensação destrutiva.
    assert not hasattr(client, "excluir_lead"), \
        "FALHOU: apareceu um excluir_lead no client — LeadsDelete é exclusão dura"
    print("  7. scheduleAdd falhou -> box removido, lead 888 MANTIDO em Entrada")


async def caso_8_slot_ocupado():
    db = _DbFalso()
    slot = _slot_valido()
    with patch.object(client, "criar_box",
                      AsyncMock(side_effect=client.SlotOcupado("Boxes are occupied"))), \
         patch.object(client, "criar_lead", AsyncMock()) as lead, \
         patch.object(client, "agendar_reuniao", AsyncMock()) as sched, \
         patch.object(client, "remover_box", AsyncMock()) as rm:
        try:
            await fluxo.agendar(db, nome="TESTE", email=None, telefone=TELEFONE,
                                slot_id=slot.id)
            assert False, "deveria ter levantado SlotIndisponivel"
        except fluxo.SlotIndisponivel:
            pass

    lead.assert_not_awaited()
    sched.assert_not_awaited()
    rm.assert_not_awaited()          # não há box para remover
    assert db.agendamentos()[0].passo == PASSO_FALHOU
    print("  8. slot ocupado -> SlotIndisponivel; lead e schedule nunca chamados")


async def caso_9_duplo_clique():
    anterior = Agendamento(nome="TESTE", telefone=TELEFONE, slot_inicio=datetime(2026, 8, 19),
                           slot_fim=datetime(2026, 8, 19), sales_rep_email="x@y.com",
                           passo=PASSO_AGENDADO, lead_id=888, box_id=777, meeting_id=999,
                           created_at=datetime.now(), updated_at=datetime.now())
    anterior.id = 42
    db = _DbFalso(duplo=anterior)
    slot = _slot_valido()

    with patch.object(client, "criar_box", AsyncMock()) as box, \
         patch.object(client, "criar_lead", AsyncMock()) as lead:
        r = await fluxo.agendar(db, nome="TESTE", email=None, telefone=TELEFONE,
                                slot_id=slot.id)

    assert r.agendamento_id == 42 and r.lead_id == 888, r
    box.assert_not_awaited()
    lead.assert_not_awaited()
    print("  9. duplo clique devolve o agendamento #42 sem tocar na Exact")


async def caso_10_faxina():
    def _pendente(box_id):
        a = Agendamento(nome="T", telefone=TELEFONE, slot_inicio=datetime(2026, 8, 19),
                        slot_fim=datetime(2026, 8, 19), sales_rep_email="x@y.com",
                        passo=PASSO_BOX_CRIADO, box_id=box_id,
                        created_at=datetime.now(), updated_at=datetime.now())
        a.id = box_id
        return a

    # a) box parado -> removido
    db = _DbFalso(pendentes=[_pendente(1)])
    with patch.object(client, "remover_box", AsyncMock()) as rm:
        r = await faxina.limpar(db)
    rm.assert_awaited_once_with(1)
    assert r["removidos"] == 1 and db._pendentes[0].passo == PASSO_FALHOU, r

    # b) box com reunião -> promovido, NÃO removido do nosso lado como falha
    db = _DbFalso(pendentes=[_pendente(2)])
    with patch.object(client, "remover_box",
                      AsyncMock(side_effect=client.BoxComReuniao("tem reunião"))):
        r = await faxina.limpar(db)
    assert r["promovidos"] == 1 and db._pendentes[0].passo == PASSO_AGENDADO, r

    # c) Exact fora do ar -> a linha CONTINUA pendente para o próximo ciclo
    db = _DbFalso(pendentes=[_pendente(3)])
    with patch.object(client, "remover_box",
                      AsyncMock(side_effect=client.ExactIndisponivel("timeout"))):
        r = await faxina.limpar(db)
    assert r["falhas"] == 1 and db._pendentes[0].passo == PASSO_BOX_CRIADO, r
    print("  10. faxina: remove o parado, promove o que tem reunião, retém o que deu timeout")


async def caso_11_rate_limit():
    from app.agendamento import routes

    routes._baldes.clear()
    req = MagicMock()
    req.headers.get.return_value = "203.0.113.7"
    req.client.host = "127.0.0.1"

    for i in range(5):
        routes._limitar(req, routes.LIMITE_ESCRITA, "agendar")
    try:
        routes._limitar(req, routes.LIMITE_ESCRITA, "agendar")
        assert False, "o 6º POST deveria ter tomado 429"
    except Exception as e:
        assert getattr(e, "status_code", None) == 429, e

    # Outro IP não é afetado pelo balde do primeiro.
    outro = MagicMock()
    outro.headers.get.return_value = "203.0.113.8"
    routes._limitar(outro, routes.LIMITE_ESCRITA, "agendar")

    # E o IP vem do X-Forwarded-For, não do 127.0.0.1 do nginx.
    assert routes._ip(req) == "203.0.113.7", routes._ip(req)
    routes._baldes.clear()
    print("  11. 6º POST do mesmo IP -> 429; outro IP passa; IP lido do X-Forwarded-For")


async def caso_12_allowlist_de_origem():
    import os

    from app.agendamento import origens

    anterior = os.environ.get("AGENDAMENTO_SUBSOURCES")
    anterior_padrao = os.environ.get("AGENDAMENTO_SUBSOURCE_PADRAO")
    os.environ["AGENDAMENTO_SUBSOURCES"] = "PosMulheridades,posgenerot2,PosPraticasDialogicasTurma1"
    os.environ["AGENDAMENTO_SUBSOURCE_PADRAO"] = "PosPraticasDialogicasTurma1"
    try:
        assert origens.resolver(None) == "PosPraticasDialogicasTurma1"
        assert origens.resolver("") == "PosPraticasDialogicasTurma1"
        assert origens.resolver("PosMulheridades") == "PosMulheridades"

        # Caixa diferente resolve, mas volta com a caixa da allowlist — senão a Exact criaria
        # um SEGUNDO cadastro com o mesmo nome em caixa diferente.
        assert origens.resolver("posmulheridades") == "PosMulheridades"
        assert origens.resolver("  POSGENEROT2  ") == "posgenerot2"

        for proibida in ("posgenero", "DialogicasTurma", "curso-inventado", "'; DROP TABLE"):
            try:
                origens.resolver(proibida)
                assert False, f"aceitou origem fora da allowlist: {proibida}"
            except origens.OrigemInvalida:
                pass

        # Padrão fora da lista é acrescentado em vez de derrubar todo agendamento.
        os.environ["AGENDAMENTO_SUBSOURCES"] = "PosMulheridades"
        os.environ["AGENDAMENTO_SUBSOURCE_PADRAO"] = "posgenerot2"
        assert origens.resolver(None) == "posgenerot2", origens.permitidas()
        assert set(origens.permitidas()) == {"PosMulheridades", "posgenerot2"}
    finally:
        for chave, valor in (("AGENDAMENTO_SUBSOURCES", anterior),
                             ("AGENDAMENTO_SUBSOURCE_PADRAO", anterior_padrao)):
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor
    print("  12. allowlist: padrão, caixa normalizada, 4 origens recusadas, padrão órfão salvo")


async def caso_13_origem_invalida_nao_cria_nada():
    """A validação vem ANTES do BoxesAdd — senão o horário ficaria travado até a faxina."""
    from app.agendamento import origens

    db = _DbFalso()
    slot = _slot_valido()
    with patch.object(client, "criar_box", AsyncMock()) as box, \
         patch.object(client, "criar_lead", AsyncMock()) as lead:
        try:
            await fluxo.agendar(db, nome="TESTE", email=None, telefone=TELEFONE,
                                slot_id=slot.id, origem="curso-que-nao-existe")
            assert False, "deveria ter levantado OrigemInvalida"
        except origens.OrigemInvalida:
            pass

    box.assert_not_awaited()
    lead.assert_not_awaited()
    assert db.agendamentos() == [], "gravou linha para uma origem que nem chegou à Exact"

    # E o subSource resolvido é o que vai para o lead, não a constante antiga.
    db = _DbFalso()
    with patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", AsyncMock(return_value=888)) as lead, \
         patch.object(client, "agendar_reuniao", AsyncMock(return_value=True)), \
         patch.object(client, "meeting_por_lead", AsyncMock(return_value=None)):
        await fluxo.agendar(db, nome="TESTE", email=None, telefone=TELEFONE,
                            slot_id=slot.id, origem="PosMulheridades")
    assert lead.await_args.kwargs["sub_source"] == "PosMulheridades", lead.await_args
    assert db.agendamentos()[0].sub_source == "PosMulheridades"
    assert not hasattr(fluxo, "SUB_SOURCE"), \
        "FALHOU: a constante SUB_SOURCE voltou — o valor tem que vir da allowlist"
    print("  13. origem inválida não cria box nem lead; válida chega ao lead e à nossa tabela")


async def main():
    print("\nMódulo de agendamento — Exact mockada, banco dublê, nada real\n")
    await caso_1_grade()
    await caso_2_fuso_nao_converte()
    await caso_3_slot_forjado()
    await caso_4_disponibilidade_subtrai()
    await caso_5_caminho_feliz()
    await caso_6_lead_falha_remove_box()
    await caso_7_schedule_falha_mantem_lead()
    await caso_8_slot_ocupado()
    await caso_9_duplo_clique()
    await caso_10_faxina()
    await caso_11_rate_limit()
    await caso_12_allowlist_de_origem()
    await caso_13_origem_invalida_nao_cria_nada()
    print("\nOK: 13/13 passaram. Nenhum box criado, nenhum lead cadastrado.\n")


if __name__ == "__main__":
    asyncio.run(main())
