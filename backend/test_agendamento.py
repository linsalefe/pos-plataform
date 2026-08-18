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
  12. allowlist de origem: padrão, caixa normalizada, valor fora da lista recusado
  13. origem inválida não cria nada; válida chega ao lead e à nossa tabela
  14. leadId válido: LeadsAdd é PULADO e o schedule usa o lead que veio no corpo
  15. leadId inexistente: 
      LeadNaoEncontrado antes de qualquer escrita — nem box é criado
  16. leadId + falha no scheduleAdd: box removido, lead externo intocado
  17. regressão: sem leadId o fluxo cria o lead como sempre fez
  18. extras: sanitização (pipe, quebra de linha, vazio) e contrato (10 chaves, 200 chars)
  19. description montado na ordem certa, e o orçamento corta com marca visível
  20. extras chegam ao LeadsAdd e à nossa tabela, nos dois fluxos
  21. regressão: sem extras, o description é só o e-mail — e sem e-mail, não existe
  22. consultoras: config, herança de grade, e-mail que sobrescreve, fallback de uma só
  23. /slots é a UNIÃO das grades, com quem está livre em cada horário
  24. escolha pela menor carga do dia, empate mantém a ordem da config
  25. ocupada na primeira -> tenta a segunda; todas ocupadas -> 409 (e só aí)
  26. validação de startup: inválida sai de rotação; Exact fora não tira ninguém
"""
import asyncio
import json
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.agendamento import agendar as fluxo
from app.agendamento import client, consultoras as equipe_mod, disponibilidade, faxina
from app.agendamento.grade import grade, recarregar
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
    """Primeiro slot livre da grade real — o que a LP ofereceria agora.

    Recarrega os DOIS caches. `consultoras()` monta a consultora única a partir de `grade()`
    e guarda o objeto; recarregar só a grade deixaria os dois apontando para grades
    diferentes, e o `slot_por_id` do fluxo passaria a não achar o slot que este helper
    devolveu — falha confusa e sem relação com o que o teste queria verificar.
    """
    g = recarregar()
    equipe_mod.recarregar()
    return g.slots_candidatos()[0]


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


# ==========================================================================================
# leadId opcional — o fluxo de duas etapas da LP
# ==========================================================================================

async def caso_14_lead_id_pula_leadsadd():
    """Com `leadId`, o passo 2 vira verificação. Criar outro lead aqui é O bug a evitar."""
    recarregar()
    slot = _slot_valido()
    db = _DbFalso()
    buscar = AsyncMock(return_value={"id": 51434608, "stage": "Entrada"})
    criar = AsyncMock(return_value=999999)
    schedule = AsyncMock(return_value=True)
    with patch.object(client, "buscar_lead_por_id", buscar), \
         patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", criar), \
         patch.object(client, "agendar_reuniao", schedule), \
         patch.object(client, "meeting_por_lead", AsyncMock(return_value=None)):
        r = await fluxo.agendar(db, nome="TESTE", email=None, telefone=TELEFONE,
                                slot_id=slot.id, lead_id=51434608)

    assert not criar.called, "FALHOU: LeadsAdd foi chamado com leadId presente — lead DUPLICADO"
    assert buscar.await_args.args[0] == 51434608, buscar.await_args
    assert r.lead_id == 51434608, r.lead_id
    # O schedule tem que apontar para o lead que veio, não para outro qualquer.
    assert schedule.await_args.kwargs["lead_id"] == 51434608, schedule.await_args
    linha = db.agendamentos()[0]
    assert linha.lead_id == 51434608 and linha.lead_externo is True, \
        f"FALHOU: procedência não gravada — lead_id={linha.lead_id} externo={linha.lead_externo}"
    assert linha.passo == PASSO_AGENDADO, linha.passo
    print("  14. leadId válido: LeadsAdd pulado, schedule usa o lead do corpo, "
          "lead_externo=True")


async def caso_15_lead_id_inexistente():
    """Lead que não existe para o fluxo ANTES do BoxesAdd — senão trava a agenda à toa."""
    recarregar()
    slot = _slot_valido()
    db = _DbFalso()
    box = AsyncMock(return_value=777)
    criar = AsyncMock(return_value=888)
    with patch.object(client, "buscar_lead_por_id", AsyncMock(return_value=None)), \
         patch.object(client, "criar_box", box), \
         patch.object(client, "criar_lead", criar), \
         patch.object(client, "agendar_reuniao", AsyncMock(return_value=True)):
        try:
            await fluxo.agendar(db, nome="TESTE", email=None, telefone=TELEFONE,
                                slot_id=slot.id, lead_id=42)
        except fluxo.LeadNaoEncontrado:
            pass
        else:
            raise AssertionError("FALHOU: leadId inexistente deveria levantar LeadNaoEncontrado")

    assert not box.called, \
        "FALHOU: box criado antes de validar o lead — o horário fica travado até a faxina"
    assert not criar.called, "FALHOU: LeadsAdd chamado num fluxo que deveria ter parado"
    assert not db.agendamentos(), \
        f"FALHOU: linha gravada sem necessidade — {db.agendamentos()}"
    print("  15. leadId inexistente: para antes do BoxesAdd, nenhuma escrita em lugar nenhum")


async def caso_16_lead_externo_sobrevive_a_falha():
    """Falha no passo 3 remove o box e NÃO toca no lead — que nem é nosso."""
    recarregar()
    slot = _slot_valido()
    db = _DbFalso()
    remover = AsyncMock()
    with patch.object(client, "buscar_lead_por_id",
                      AsyncMock(return_value={"id": 51434608})), \
         patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", AsyncMock(return_value=888)), \
         patch.object(client, "remover_box", remover), \
         patch.object(client, "agendar_reuniao",
                      AsyncMock(side_effect=client.BoxIndisponivel("ocupado"))):
        try:
            await fluxo.agendar(db, nome="TESTE", email=None, telefone=TELEFONE,
                                slot_id=slot.id, lead_id=51434608)
        except fluxo.AgendamentoFalhou as e:
            assert e.lead_id == 51434608, e.lead_id
        else:
            raise AssertionError("FALHOU: deveria levantar AgendamentoFalhou")

    remover.assert_awaited_once_with(777)
    # A garantia central: nada no módulo pode apagar um lead que não criamos.
    assert not hasattr(client, "excluir_lead"), \
        "FALHOU: apareceu um excluir_lead no client — LeadsDelete é exclusão DURA"
    linha = db.agendamentos()[0]
    assert linha.passo == PASSO_FALHOU and linha.lead_id == 51434608, linha.passo
    assert linha.lead_externo is True, linha.lead_externo
    print("  16. leadId + scheduleAdd falho: box 777 removido, lead externo 51434608 intocado")


async def caso_17_sem_lead_id_nao_regrediu():
    """Retrocompatibilidade: a LP de Mulheridades não manda leadId e não pode mudar."""
    recarregar()
    slot = _slot_valido()
    db = _DbFalso()
    buscar = AsyncMock(return_value=None)
    criar = AsyncMock(return_value=888)
    schedule = AsyncMock(return_value=True)
    with patch.object(client, "buscar_lead_por_id", buscar), \
         patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", criar), \
         patch.object(client, "agendar_reuniao", schedule), \
         patch.object(client, "meeting_por_lead", AsyncMock(return_value=None)):
        r = await fluxo.agendar(db, nome="TESTE", email=None, telefone=TELEFONE,
                                slot_id=slot.id)

    assert not buscar.called, \
        "FALHOU: sem leadId não pode haver consulta de lead — é requisição à toa na Exact"
    criar.assert_awaited_once()
    assert r.lead_id == 888, r.lead_id
    assert schedule.await_args.kwargs["lead_id"] == 888, schedule.await_args
    linha = db.agendamentos()[0]
    assert linha.lead_externo is False, \
        f"FALHOU: lead criado por nós marcado como externo — {linha.lead_externo}"
    assert linha.passo == PASSO_AGENDADO, linha.passo
    print("  17. sem leadId: LeadsAdd chamado, lead 888 criado, lead_externo=False")


# ==========================================================================================
# extras — campos livres do formulário da LP
# ==========================================================================================

async def caso_18_extras_sanitiza_e_recusa():
    """Sujeira é limpa em silêncio; violação de contrato é recusada."""
    from app.agendamento import extras as ex

    # O separador do formato não pode vir do conteúdo, senão o SDR lê pares falsos.
    assert ex.sanitizar({"A|B": "Insta|gram"}) == {"A/B": "Insta/gram"}
    # Quebra de linha e tabulação desmontam o layout do CRM.
    assert ex.sanitizar({"k": "linha1\nlinha2\tfim"}) == {"k": "linha1 linha2 fim"}
    # Caractere de controle invisível some.
    assert ex.sanitizar({"k": "a\x00b"}) == {"k": "a b"}
    # Par que virou vazio não vai para lugar nenhum.
    assert ex.sanitizar({"k": "   ", "  ": "v", "ok": "sim"}) == {"ok": "sim"}
    # None no valor é omissão, não erro — formulário com campo não preenchido.
    assert ex.sanitizar({"k": None, "ok": "sim"}) == {"ok": "sim"}
    assert ex.sanitizar(None) == {} and ex.sanitizar({}) == {}
    # A ordem é a das perguntas do formulário, e o SDR lê nessa ordem.
    assert list(ex.sanitizar({"z": "1", "a": "2", "m": "3"})) == ["z", "a", "m"]

    for ruim, porque in (
        ({str(i): "v" for i in range(11)}, "11 chaves"),
        ({"k": "x" * 201}, "valor 201 chars"),
        ({"x" * 61: "v"}, "chave 61 chars"),
        ({"k": 123}, "valor não-texto"),
        ("nem é dict", "tipo errado"),
    ):
        try:
            ex.sanitizar(ruim)
        except ex.ExtrasInvalidos:
            pass
        else:
            raise AssertionError(f"FALHOU: {porque} deveria ser recusado")

    # Exatamente no limite passa — 10 chaves não é 11.
    assert len(ex.sanitizar({str(i): "v" for i in range(10)})) == 10
    assert ex.sanitizar({"k": "x" * 200}) == {"k": "x" * 200}
    print("  18. extras: pipe/quebra/controle limpos, vazios somem, 5 violações recusadas")


async def caso_19_descricao_formato_e_orcamento():
    """O texto que o SDR lê, e o corte que a Exact NÃO faria com aviso."""
    from app.agendamento import extras as ex

    d = ex.montar_descricao("x@y.com", {"Profissão": "Psicologia",
                                        "Ensino Superior": "Sim",
                                        "Como conheceu": "Instagram",
                                        "Faixa": "Até R$100,00"})
    assert d == ("E-mail: x@y.com | Profissão: Psicologia | Ensino Superior: Sim | "
                 "Como conheceu: Instagram | Faixa: Até R$100,00"), d
    # O e-mail vem primeiro: é o dado que o SDR mais usa.
    assert d.startswith("E-mail: "), d

    # Sem nada a dizer, NÃO existe description — o LeadsAdd sai sem a chave, como antes.
    assert ex.montar_descricao(None, None) is None
    assert ex.montar_descricao(None, {}) is None
    assert ex.montar_descricao("", {}) is None
    assert ex.montar_descricao("x@y.com", None) == "E-mail: x@y.com"
    assert ex.montar_descricao(None, {"k": "v"}) == "k: v"

    # O pior caso REAL cabe folgado: 10 chaves cheias mais e-mail.
    pior = ex.montar_descricao("x" * 200, {("c" * 60) + str(i): "v" * 200 for i in range(10)})
    assert len(pior) < ex.ORCAMENTO_DESCRICAO, len(pior)
    assert len(pior) < ex.LIMITE_EXACT, len(pior)

    # E se alguém afrouxar um limite, o corte é NOSSO e deixa marca visível. A Exact
    # cortaria em 8000 sem avisar ninguém (FINDINGS §13).
    #
    # `montar_descricao` não aplica o contrato de propósito — quem aplica é `sanitizar`. Dá
    # para chamá-la com um valor gigante justamente para exercitar o orçamento, que pelo
    # caminho normal é inalcançável.
    cortado = ex.montar_descricao(None, {"k": "v" * 9000})
    assert len(cortado) == ex.ORCAMENTO_DESCRICAO, len(cortado)
    assert cortado.endswith("…"), cortado[-20:]
    assert len(cortado) < ex.LIMITE_EXACT, "o corte tem que ficar abaixo do teto da Exact"
    assert ex.ORCAMENTO_DESCRICAO < ex.LIMITE_EXACT, "o orçamento tem que ficar ABAIXO do teto"

    # Exatamente no orçamento não é cortado — o `>` da comparação não pode virar `>=`.
    no_limite = ex.montar_descricao(None, {"k": "v" * (ex.ORCAMENTO_DESCRICAO - 3)})
    assert len(no_limite) == ex.ORCAMENTO_DESCRICAO and not no_limite.endswith("…"), \
        (len(no_limite), no_limite[-5:])
    print(f"  19. description no formato pedido; pior caso real {len(pior)} chars "
          f"(orçamento {ex.ORCAMENTO_DESCRICAO}, teto da Exact {ex.LIMITE_EXACT})")


async def caso_20_extras_chegam_ao_lead_e_a_tabela():
    """Os dois destinos: o description da Exact e a coluna JSONB nossa."""
    recarregar()
    slot = _slot_valido()
    extras = {"Profissão": "Psicologia", "Como conheceu": "Instagram"}

    # --- fluxo com agendamento ---
    db = _DbFalso()
    criar = AsyncMock(return_value=888)
    with patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", criar), \
         patch.object(client, "agendar_reuniao", AsyncMock(return_value=True)), \
         patch.object(client, "meeting_por_lead", AsyncMock(return_value=None)):
        await fluxo.agendar(db, nome="TESTE", email="a@b.com", telefone=TELEFONE,
                            slot_id=slot.id, extras=extras)
    desc = criar.await_args.kwargs["description"]
    assert desc == "E-mail: a@b.com | Profissão: Psicologia | Como conheceu: Instagram", desc
    assert db.agendamentos()[0].extras == extras, db.agendamentos()[0].extras
    # O e-mail NÃO vai mais como kwarg solto: ele vive dentro do description.
    assert "email" not in criar.await_args.kwargs, criar.await_args.kwargs

    # --- fluxo /lead, sem agendar ---
    db2 = _DbFalso()
    criar2 = AsyncMock(return_value=999)
    with patch.object(client, "criar_lead", criar2):
        await fluxo.cadastrar_lead_sem_agendar(db2, nome="TESTE", email="a@b.com",
                                               telefone=TELEFONE, extras=extras)
    assert criar2.await_args.kwargs["description"] == desc, criar2.await_args.kwargs
    assert db2.agendamentos()[0].extras == extras

    # --- lead externo: extras ficam na tabela, LeadsAdd nem é chamado ---
    db3 = _DbFalso()
    criar3 = AsyncMock(return_value=111)
    with patch.object(client, "buscar_lead_por_id", AsyncMock(return_value={"id": 42})), \
         patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", criar3), \
         patch.object(client, "agendar_reuniao", AsyncMock(return_value=True)), \
         patch.object(client, "meeting_por_lead", AsyncMock(return_value=None)):
        await fluxo.agendar(db3, nome="TESTE", email="a@b.com", telefone=TELEFONE,
                            slot_id=slot.id, lead_id=42, extras=extras)
    assert not criar3.called, "FALHOU: LeadsAdd chamado com lead externo"
    assert db3.agendamentos()[0].extras == extras, "extras têm que ficar na tabela mesmo assim"
    print("  20. extras -> description da Exact + coluna JSONB, nos 3 caminhos")


async def caso_21_sem_extras_nada_muda():
    """Retrocompatibilidade: as LPs que não mandam o campo não podem sentir diferença."""
    recarregar()
    slot = _slot_valido()

    db = _DbFalso()
    criar = AsyncMock(return_value=888)
    with patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", criar), \
         patch.object(client, "agendar_reuniao", AsyncMock(return_value=True)), \
         patch.object(client, "meeting_por_lead", AsyncMock(return_value=None)):
        await fluxo.agendar(db, nome="TESTE", email="a@b.com", telefone=TELEFONE,
                            slot_id=slot.id)
    assert criar.await_args.kwargs["description"] == "E-mail: a@b.com", \
        criar.await_args.kwargs["description"]
    assert db.agendamentos()[0].extras is None, db.agendamentos()[0].extras

    # Sem e-mail e sem extras não existe description nenhum — o payload sai sem a chave,
    # exatamente como saía antes destes campos existirem.
    db2 = _DbFalso()
    criar2 = AsyncMock(return_value=888)
    with patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", criar2), \
         patch.object(client, "agendar_reuniao", AsyncMock(return_value=True)), \
         patch.object(client, "meeting_por_lead", AsyncMock(return_value=None)):
        await fluxo.agendar(db2, nome="TESTE", email=None, telefone=TELEFONE,
                            slot_id=slot.id)
    assert criar2.await_args.kwargs["description"] is None, criar2.await_args.kwargs
    assert db2.agendamentos()[0].extras is None
    print("  21. sem extras: description = só o e-mail; sem e-mail = sem description")


# ==========================================================================================
# múltiplas consultoras
# ==========================================================================================

DUAS = json.dumps([
    {"email": "ana@cenatcursos.com.br", "nome_exibicao": "Ana",
     "grade": {"janelas": {"0": [["10:00", "11:30"]], "1": [["10:00", "11:30"]],
                           "2": [["10:00", "11:30"]], "3": [["10:00", "11:30"]],
                           "4": [["10:00", "11:30"]]}}},
    {"email": "bia@cenatcursos.com.br", "nome_exibicao": "Bia",
     "grade": {"janelas": {"0": [["10:45", "12:15"]], "1": [["10:45", "12:15"]],
                           "2": [["10:45", "12:15"]], "3": [["10:45", "12:15"]],
                           "4": [["10:45", "12:15"]]}}},
])


def _com_duas():
    """Ativa as duas consultoras e devolve a lista recarregada."""
    os.environ["AGENDAMENTO_CONSULTORAS"] = DUAS
    return equipe_mod.recarregar()


def _sem_consultoras():
    os.environ.pop("AGENDAMENTO_CONSULTORAS", None)
    equipe_mod.recarregar()


async def caso_22_config_consultoras():
    try:
        equipe = _com_duas()
        assert [c.nome_exibicao for c in equipe] == ["Ana", "Bia"], equipe
        # A grade herda o que não veio: duração e antecedência são política do produto.
        assert equipe[0].grade.duracao == equipe[1].grade.duracao
        assert int(equipe[0].grade.duracao.total_seconds() // 60) == 45
        # O e-mail da consultora sobrescreve o sales_rep_email de dentro da grade.
        assert equipe[0].grade.sales_rep_email == "ana@cenatcursos.com.br"
        assert equipe_mod.nome_de("BIA@cenatcursos.com.br") == "Bia", "busca é case-insensitive"
        assert equipe_mod.nome_de("sumiu@x.com") == "sumiu", "e-mail desconhecido vira rótulo"

        # JSON inválido NÃO derruba: cai na consultora única, como a grade faz.
        os.environ["AGENDAMENTO_CONSULTORAS"] = "{isto não é json"
        assert len(equipe_mod.recarregar()) == 1
        os.environ["AGENDAMENTO_CONSULTORAS"] = "[]"
        assert len(equipe_mod.recarregar()) == 1, "lista vazia = fallback"
        # Item sem e-mail é ignorado, os outros sobrevivem.
        os.environ["AGENDAMENTO_CONSULTORAS"] = json.dumps(
            [{"nome_exibicao": "Sem email"}, {"email": "ok@x.com", "nome_exibicao": "Ok"}])
        assert [c.email for c in equipe_mod.recarregar()] == ["ok@x.com"]

        # Sem env nenhum: exatamente o comportamento de antes desta sprint.
        _sem_consultoras()
        uma = equipe_mod.consultoras()
        assert len(uma) == 1 and uma[0].email == grade().sales_rep_email
    finally:
        _sem_consultoras()
    print("  22. consultoras: herança, e-mail soberano, 3 configs ruins caem no fallback")


async def caso_23_slots_uniao():
    """A LP vê a união. Ana 10:00–11:30 e Bia 10:45–12:15 dão 10:00, 10:45, 11:30."""
    try:
        _com_duas()
        disponibilidade.invalidar_cache()
        db = _DbFalso()
        with patch.object(client, "listar_boxes", AsyncMock(return_value=[])):
            livres = await disponibilidade.slots_livres(db, usar_cache=False)
        horas = sorted({d.slot.inicio.strftime("%H:%M") for d in livres})
        assert horas == ["10:00", "10:45", "11:30"], horas

        porhora = {}
        for d in livres:
            porhora.setdefault(d.slot.inicio.strftime("%H:%M"), set()).update(
                c.nome_exibicao for c in d.consultoras)
        # 10:45 é o único que as duas oferecem; os outros são de uma só.
        assert porhora["10:00"] == {"Ana"}, porhora["10:00"]
        assert porhora["10:45"] == {"Ana", "Bia"}, porhora["10:45"]
        assert porhora["11:30"] == {"Bia"}, porhora["11:30"]

        # Uma agenda ilegível não pode apagar a grade da outra.
        disponibilidade.invalidar_cache()
        async def so_ana_falha(inicio, fim, email):
            if email.startswith("ana"):
                raise client.ExactIndisponivel("timeout")
            return []
        with patch.object(client, "listar_boxes", AsyncMock(side_effect=so_ana_falha)):
            livres2 = await disponibilidade.slots_livres(db, usar_cache=False)
        nomes = {c.nome_exibicao for d in livres2 for c in d.consultoras}
        assert nomes == {"Bia"}, nomes
        assert livres2, "a Bia tinha que sobrar"
    finally:
        _sem_consultoras()
        disponibilidade.invalidar_cache()
    print("  23. união: 10:00(Ana) 10:45(Ana+Bia) 11:30(Bia); Ana ilegível não apaga a Bia")


async def caso_24_escolha_por_carga():
    try:
        equipe = _com_duas()
        hoje = fluxo.agora_sp().date()

        # Empate (ninguém agendado): mantém a ordem da config.
        db = _DbFalso(ocupados=[])
        ordem = await fluxo.escolher_consultora(db, equipe, hoje)
        assert [c.nome_exibicao for c in ordem] == ["Ana", "Bia"], ordem

        # Ana com 3 no dia, Bia com 1 -> Bia primeiro.
        db = _DbFalso(ocupados=[("ana@cenatcursos.com.br", 3), ("bia@cenatcursos.com.br", 1)])
        ordem = await fluxo.escolher_consultora(db, equipe, hoje)
        assert [c.nome_exibicao for c in ordem] == ["Bia", "Ana"], ordem

        # Consultora sem nenhuma linha conta como zero, não some da lista.
        db = _DbFalso(ocupados=[("ana@cenatcursos.com.br", 5)])
        ordem = await fluxo.escolher_consultora(db, equipe, hoje)
        assert [c.nome_exibicao for c in ordem] == ["Bia", "Ana"], ordem

        # Uma só candidata nem consulta o banco.
        db = _DbFalso(ocupados=[("x", 99)])
        assert await fluxo.escolher_consultora(db, equipe[:1], hoje) == equipe[:1]
    finally:
        _sem_consultoras()
    print("  24. carga: empate mantém config, 3x1 inverte, ausente conta zero")


async def caso_25_ocupada_tenta_a_proxima():
    """O achado que motiva isto: ocupado numa consultora não é o horário morrer."""
    try:
        equipe = _com_duas()
        # 10:45 é o horário que as DUAS oferecem.
        slot = None
        for c in equipe:
            for s_ in c.grade.slots_candidatos():
                if s_.inicio.strftime("%H:%M") == "10:45":
                    slot = s_
                    break
            if slot:
                break
        assert slot is not None

        # --- Ana ocupada, Bia livre: tem que agendar com a Bia, sem 409 ---
        db = _DbFalso()
        chamadas = []
        async def box(**kw):
            chamadas.append(kw["sales_rep_email"])
            if kw["sales_rep_email"].startswith("ana"):
                raise client.SlotOcupado("Boxes are occupied at the desired time.")
            return 777
        sched = AsyncMock(return_value=True)
        with patch.object(client, "criar_box", AsyncMock(side_effect=box)), \
             patch.object(client, "criar_lead", AsyncMock(return_value=888)), \
             patch.object(client, "agendar_reuniao", sched), \
             patch.object(client, "meeting_por_lead", AsyncMock(return_value=None)):
            r = await fluxo.agendar(db, nome="TESTE", email=None, telefone=TELEFONE,
                                    slot_id=slot.id)
        assert chamadas == ["ana@cenatcursos.com.br", "bia@cenatcursos.com.br"], chamadas
        assert r.consultora_nome == "Bia", r.consultora_nome
        # O scheduleAdd tem que ir com a MESMA consultora do box, senão a reunião nasce órfã.
        assert sched.await_args.kwargs["sales_rep_email"] == "bia@cenatcursos.com.br"
        linha = db.agendamentos()[0]
        assert linha.sales_rep_email == "bia@cenatcursos.com.br", linha.sales_rep_email

        # --- as duas ocupadas: aí sim 409, e só aí ---
        db2 = _DbFalso()
        tentou = []
        async def box2(**kw):
            tentou.append(kw["sales_rep_email"])
            raise client.SlotOcupado("Boxes are occupied at the desired time.")
        lead = AsyncMock()
        with patch.object(client, "criar_box", AsyncMock(side_effect=box2)), \
             patch.object(client, "criar_lead", lead):
            try:
                await fluxo.agendar(db2, nome="TESTE", email=None, telefone=TELEFONE,
                                    slot_id=slot.id)
            except fluxo.SlotIndisponivel:
                pass
            else:
                raise AssertionError("FALHOU: as duas ocupadas tinham que dar SlotIndisponivel")
        assert len(tentou) == 2, tentou
        assert not lead.called, "FALHOU: criou lead com o horário perdido"
        assert db2.agendamentos()[0].passo == PASSO_FALHOU

        # --- erro que NÃO é disputa não passa para a próxima ---
        db3 = _DbFalso()
        tentou3 = []
        async def box3(**kw):
            tentou3.append(kw["sales_rep_email"])
            raise client.SdrNaoEncontrado("SDR not found.")
        with patch.object(client, "criar_box", AsyncMock(side_effect=box3)):
            try:
                await fluxo.agendar(db3, nome="TESTE", email=None, telefone=TELEFONE,
                                    slot_id=slot.id)
            except fluxo.AgendamentoFalhou:
                pass
            else:
                raise AssertionError("FALHOU: SDR not found deveria parar o fluxo")
        assert len(tentou3) == 1, \
            f"FALHOU: erro de configuração tentou {len(tentou3)} consultoras — insistir " \
            "só transformaria um env errado em vários boxes"
    finally:
        _sem_consultoras()
    print("  25. Ana ocupada -> agenda com a Bia; as duas -> 409; SDR not found para na 1ª")


async def caso_26_validacao_startup():
    try:
        _com_duas()
        # Bia inativa na Exact -> sai de rotação. Ana ativa fica.
        sellers = [{"email": "ana@cenatcursos.com.br", "active": True},
                   {"email": "bia@cenatcursos.com.br", "active": False}]
        with patch.object(client, "listar_sellers", AsyncMock(return_value=sellers)):
            r = await equipe_mod.validar_contra_exact()
        assert r["verificadas"] == ["ana@cenatcursos.com.br"], r
        assert r["invalidas"][0]["motivo"] == "inativa na Exact", r
        assert [c.nome_exibicao for c in equipe_mod.consultoras()] == ["Ana"]

        # E-mail que não existe em /Sellers -> motivo diferente, e também sai.
        _com_duas()
        with patch.object(client, "listar_sellers",
                          AsyncMock(return_value=[{"email": "ana@cenatcursos.com.br",
                                                   "active": True}])):
            r = await equipe_mod.validar_contra_exact()
        assert r["invalidas"][0]["motivo"] == "não existe em /Sellers", r

        # Exact inacessível -> NINGUÉM sai. Não dá para distinguir inválida de não-verificada.
        _com_duas()
        with patch.object(client, "listar_sellers",
                          AsyncMock(side_effect=client.ExactIndisponivel("timeout"))):
            r = await equipe_mod.validar_contra_exact()
        assert r["checagem_falhou"] is True and not r["invalidas"], r
        assert len(equipe_mod.consultoras()) == 2, "a checagem falhou; ninguém pode sair"
    finally:
        _sem_consultoras()
    print("  26. startup: inativa e inexistente saem com motivos distintos; "
          "Exact fora não tira ninguém")


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
    await caso_14_lead_id_pula_leadsadd()
    await caso_15_lead_id_inexistente()
    await caso_16_lead_externo_sobrevive_a_falha()
    await caso_17_sem_lead_id_nao_regrediu()
    await caso_18_extras_sanitiza_e_recusa()
    await caso_19_descricao_formato_e_orcamento()
    await caso_20_extras_chegam_ao_lead_e_a_tabela()
    await caso_21_sem_extras_nada_muda()
    await caso_22_config_consultoras()
    await caso_23_slots_uniao()
    await caso_24_escolha_por_carga()
    await caso_25_ocupada_tenta_a_proxima()
    await caso_26_validacao_startup()
    print("\nOK: 26/26 passaram. Nenhum box criado, nenhum lead cadastrado.\n")


if __name__ == "__main__":
    asyncio.run(main())
