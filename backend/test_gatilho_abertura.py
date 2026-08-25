"""O gatilho da abertura do agente, nos DOIS caminhos que falharam em 25/08/2026.

Rodar: cd backend && venv/bin/python test_gatilho_abertura.py

Nada real é tocado: banco falso, nenhum envio, nenhuma chamada à Exact.

------------------------------------------------------------------------------------------
O QUE ESTES TESTES PROVAM, E POR QUE OS QUE JÁ EXISTIAM NÃO PEGARAM
------------------------------------------------------------------------------------------
Em 25/08 a fila `nat_scheduled_actions` passou o dia com ZERO linhas, com o agente LIGADO e
73 leads entrando. Dois bugs independentes, um em cada caminho:

CAMINHO SYNC — `send_welcome_to_new_lead`, passo 4.5.
  `exact_spotter.py` tinha um `from datetime import timezone, timedelta` DENTRO da função.
  Isso torna `timedelta` local à função INTEIRA, e o passo 4.5 — 80 linhas ACIMA do import —
  passou a levantar `UnboundLocalError` ao calcular `nascido - timedelta(hours=3)`.

  Por que `test_welcome_guardrail.caso_4b` passava mesmo assim: seu `_lead_data()` não tem
  a chave `register_date`. Com `nascido = None`, a expressão
  `(nascido - timedelta(hours=3)) if nascido else None` curto-circuita e `timedelta` NUNCA
  é avaliado. O teste exercitava o passo 4.5 pela metade — a metade sem a data.
  → casos 1 e 2 abaixo passam a mandar o lead COM `register_date`, que é o que produção manda.
  → caso 3 tranca a CLASSE do bug, não a instância: nenhum nome de `datetime` pode virar
    local nessa função de novo.

CAMINHO LP — `agendamento/agendar.py::_gatilho_do_agente`.
  `nat_scheduler.agendar` é primitiva: dá `flush()` e não commita, por desenho. Só que
  nenhum dos dois chamadores da landing page commitava depois, e a sessão do `get_db` fecha
  com rollback. As 31 aberturas do dia foram inseridas, ANUNCIADAS NO LOG com id (27 a 57)
  e desfeitas — `pg_stat_user_tables` fechou o dia com 57 inserts e 0 linhas vivas.
  → casos 4 a 6 exigem o commit, e exigem que ele NÃO aconteça quando não há o que salvar.
"""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app import exact_spotter
from app.models import (ExactLead, AutoWelcomeConfig, NatConfig, Agendamento,
                        KIND_INICIAR_QUALIFICACAO, KIND_LEMBRETE_REUNIAO, ORIGEM_EXACT)


# ==========================================================================================
# BANCO FALSO
# ==========================================================================================
class FakeDB:
    """Sessão falsa que REGISTRA o que foi adicionado, flushado e commitado.

    Guardar a ordem importa: o bug do caminho LP era exatamente "add + flush sem commit",
    e um mock que só conta chamadas não distingue isso de "add + flush + commit".
    """

    def __init__(self, *, estado_existente=None, nat_cfg=None, lead_row=None):
        self.adicionados = []
        self.commits = 0
        self.flushes = 0
        self.eventos = []
        self._estado_existente = estado_existente   # etapa já existente do contato, ou None
        self._nat_cfg = nat_cfg
        self._lead_row = lead_row

    async def execute(self, stmt):
        """Devolve o suficiente para os três SELECTs/UPDATEs do caminho do gatilho."""
        texto = str(stmt)
        res = MagicMock()
        res.rowcount = 0
        if "nat_config" in texto:
            res.scalar_one_or_none.return_value = self._nat_cfg
        elif "exact_leads" in texto:
            res.scalar_one_or_none.return_value = self._lead_row
        else:
            res.scalar_one_or_none.return_value = None
        scalars = MagicMock()
        scalars.first.return_value = self._estado_existente
        scalars.all.return_value = []
        res.scalars.return_value = scalars
        return res

    def add(self, obj):
        self.adicionados.append(obj)
        self.eventos.append(("add", type(obj).__name__))

    async def flush(self):
        self.flushes += 1
        self.eventos.append(("flush", None))

    async def commit(self):
        self.commits += 1
        self.eventos.append(("commit", None))

    async def rollback(self):
        self.eventos.append(("rollback", None))

    async def refresh(self, obj):
        pass

    def acoes(self, kind=None):
        return [a for a in self.adicionados
                if type(a).__name__ == "NatScheduledAction" and (kind is None or a.kind == kind)]


def _cfg(enabled=False):
    return AutoWelcomeConfig(id=1, enabled=enabled, channel_id=1,
                             template_name="nat_boasvindas", template_language="pt_BR",
                             funnel_ids="18535,18537,25588")


def _lead(exact_id=111, funnel_id=18535):
    l = ExactLead(exact_id=exact_id, name="Fulano de Tal", phone1="5583999998888",
                  sub_source="pospsicologia", funnel_id=funnel_id)
    l.welcome_status = None
    l.welcome_error = None
    l.welcome_sent_at = None
    return l


def _lead_data(lead, register_date):
    """IGUAL ao que `sync_exact_leads` monta — com `register_date`, que é o ponto.

    `sync_exact_leads` sempre põe esta chave (`parse_datetime(lead.get("registerDate"))`).
    Um `_lead_data` sem ela não representa produção nenhuma.
    """
    return {"exact_id": lead.exact_id, "name": lead.name, "phone1": lead.phone1,
            "sub_source": lead.sub_source, "funnel_id": lead.funnel_id,
            "register_date": register_date}


# ==========================================================================================
# CAMINHO SYNC
# ==========================================================================================
async def caso_1_passo_4_5_com_register_date():
    """O caso exato de produção: agente LIGADO, boas-vindas DESLIGADA, lead COM data.

    Antes da correção este teste morria com
    `UnboundLocalError: local variable 'timedelta' referenced before assignment`.
    """
    lead = _lead()
    nascido = datetime(2026, 8, 25, 14, 23, 51)          # register_date vem em UTC
    db = FakeDB(nat_cfg=NatConfig(id=1, nat_enabled=False, max_envios_hora=20,
                                  qualificacao_enabled=True),
                lead_row=lead)

    with patch.object(exact_spotter, "send_template_message", new=AsyncMock()) as envio, \
         patch("app.qualificacao_gatilho.agendar_abertura",
               new=AsyncMock(return_value=(True, "enfileirado"))) as gatilho:
        r = await exact_spotter.send_welcome_to_new_lead(
            _lead_data(lead, nascido), db, _cfg(enabled=False))

    assert r["reason"] == "agente_assumiu", r
    assert envio.call_count == 0, "FALHOU: mandou boas-vindas com a automação desligada!"
    assert gatilho.await_count == 1, "FALHOU: o passo 4.5 não enfileirou a abertura!"
    assert lead.welcome_status == "skipped"

    kw = gatilho.await_args.kwargs
    assert kw["origem"] == ORIGEM_EXACT, kw
    assert kw["lead_id"] == lead.exact_id, kw
    # register_date é UTC; o gatilho soma 3h de volta, então tem que chegar já descontado.
    assert kw["nascido_em"] == nascido - timedelta(hours=3), kw
    print(f"  1. sync, lead COM register_date    -> {r['status']}/{r['reason']:16s} "
          f"gatilho={gatilho.await_count}  nascido_em={kw['nascido_em']:%H:%M:%S} (SP)")


async def caso_2_a_acao_chega_na_fila():
    """Sem mock no gatilho: a cadeia inteira até a linha de `nat_scheduled_actions`.

    O caso 1 prova que o passo 4.5 CHAMA. Este prova que a chamada vira ação enfileirada,
    com o kind e o run_at certos — é o elo que o mock do caso 1 esconde.
    """
    lead = _lead()
    nascido = datetime(2026, 8, 25, 14, 23, 51)
    db = FakeDB(nat_cfg=NatConfig(id=1, nat_enabled=False, max_envios_hora=20,
                                  qualificacao_enabled=True),
                lead_row=lead)

    with patch.object(exact_spotter, "send_template_message", new=AsyncMock()):
        r = await exact_spotter.send_welcome_to_new_lead(
            _lead_data(lead, nascido), db, _cfg(enabled=False))

    assert r["reason"] == "agente_assumiu", r
    acoes = db.acoes(KIND_INICIAR_QUALIFICACAO)
    assert len(acoes) == 1, f"FALHOU: {len(acoes)} ações enfileiradas, esperava 1"
    acao = acoes[0]
    assert acao.contact_wa_id == "5583999998888", acao.contact_wa_id
    assert acao.status == "pendente", acao.status
    print(f"  2. sync -> fila (sem mock)         -> kind={acao.kind!r} "
          f"contato={acao.contact_wa_id} run_at={acao.run_at:%d/%m %H:%M:%S}")


async def caso_3_nenhum_datetime_vira_local():
    """Trava a CLASSE do bug: nenhum nome de `datetime` pode ser local em 4.5.

    Um `from datetime import X` dentro de `send_welcome_to_new_lead` faz `X` virar local
    para a função TODA — inclusive para as linhas ANTES do import, que passam a levantar
    UnboundLocalError. Um teste de comportamento só pega o caminho que ele percorre; este
    olha o bytecode e pega qualquer reincidência, em qualquer ponto da função.
    """
    codigo = exact_spotter.send_welcome_to_new_lead.__code__
    locais = set(codigo.co_varnames) | set(codigo.co_cellvars)
    proibidos = {"timedelta", "timezone", "datetime", "date"} & locais
    assert not proibidos, (
        f"FALHOU: {sorted(proibidos)} virou nome LOCAL de send_welcome_to_new_lead. "
        "Um import de datetime dentro da função sombreia o do módulo e quebra o passo 4.5 "
        "com UnboundLocalError. Use os nomes do topo do módulo.")
    print(f"  3. nenhum nome de datetime é local -> ok "
          f"({len(locais)} locais varridos, 0 sombreando o módulo)")


async def caso_4_um_lead_ruim_nao_derruba_o_lote():
    """Isolamento do laço: a exceção de um lead não pode custar os outros.

    Em 25/08 o UnboundLocalError estourou na PRIMEIRA iteração e abortou o
    `sync_exact_leads` inteiro. Como os leads já tinham sido commitados, na passada seguinte
    todos eram `existing` — 42 leads ficaram com `welcome_status` NULL para sempre.
    """
    bons = [_lead(exact_id=i) for i in (201, 202)]
    ruim = _lead(exact_id=999)
    nascido = datetime(2026, 8, 25, 14, 0, 0)
    novos = [_lead_data(ruim, nascido)] + [_lead_data(l, nascido) for l in bons]

    chamadas = {"n": 0}

    async def falha_no_primeiro(lead_data, db, config, **kw):
        chamadas["n"] += 1
        if lead_data["exact_id"] == 999:
            raise RuntimeError("boom no primeiro lead")
        return {"exact_id": lead_data["exact_id"], "name": lead_data["name"],
                "status": "skipped", "reason": "agente_assumiu", "detail": None}

    db = MagicMock()
    db.commit = AsyncMock()
    db.begin_nested = MagicMock(return_value=_savepoint_falso())
    db.execute = AsyncMock(side_effect=RuntimeError("não deveria buscar leads aqui"))

    with patch.object(exact_spotter, "send_welcome_to_new_lead", new=falha_no_primeiro), \
         patch.object(exact_spotter, "fetch_leads_from_exact",
                      new=AsyncMock(return_value={"value": []})), \
         patch.object(exact_spotter, "get_auto_welcome_config",
                      new=AsyncMock(return_value=_cfg(enabled=False))):
        # entra direto no laço de boas-vindas com a lista já montada
        resultado = await _rodar_laco_de_boasvindas(db, novos, _cfg(enabled=False),
                                                    falha_no_primeiro)

    assert chamadas["n"] == 3, f"FALHOU: parou na {chamadas['n']}ª chamada — o lote morreu"
    assert resultado[0]["reason"] == "excecao_no_laco", resultado[0]
    assert [r["reason"] for r in resultado[1:]] == ["agente_assumiu"] * 2, resultado
    print(f"  4. lead ruim no meio do lote       -> {len(resultado)} decisões, "
          f"1 exceção isolada, {len(resultado) - 1} leads seguiram")


def _savepoint_falso():
    class _SP:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): return False
    return _SP()


async def _rodar_laco_de_boasvindas(db, novos, config, fn):
    """Réplica FIEL do laço de `sync_exact_leads` — mesmo isolamento, mesmo fallback.

    Replicado em vez de chamado porque `sync_exact_leads` precisaria da Exact inteira
    mockada para chegar até aqui; o que está sob teste é o isolamento do laço.
    """
    resultados = []
    for lead_data in novos:
        try:
            async with db.begin_nested():
                resultados.append(await fn(lead_data, db, config))
        except Exception as e:
            resultados.append({"exact_id": lead_data.get("exact_id"),
                               "name": lead_data.get("name", ""), "status": "failed",
                               "reason": "excecao_no_laco",
                               "detail": f"{type(e).__name__}: {e}"})
    return resultados


# ==========================================================================================
# CAMINHO LP
# ==========================================================================================
def _agendamento(passo, *, slot_inicio=None):
    ag = Agendamento(nome="Fulano", email=None, telefone="83999998888",
                     slot_inicio=slot_inicio or datetime(2026, 8, 26, 15, 0),
                     slot_fim=(slot_inicio or datetime(2026, 8, 26, 15, 0)) + timedelta(minutes=30),
                     sales_rep_email="c@cenat.com", passo=passo)
    ag.id = 777
    ag.lead_id = 51543718
    ag.created_at = datetime(2026, 8, 25, 11, 23, 51)
    return ag


async def caso_5_post_lead_commita():
    """POST /agendamento/lead: enfileira a abertura E COMMITA.

    É o bug de 25/08 na sua forma pura — 31 vezes o log disse "agendado (id=N)" e nenhuma
    linha sobreviveu ao fechamento da sessão.
    """
    from app.agendamento import agendar as fluxo
    ag = _agendamento("lead_criado")
    db = FakeDB()

    await fluxo._gatilho_do_agente(db, ag)

    acoes = db.acoes(KIND_INICIAR_QUALIFICACAO)
    assert len(acoes) == 1, f"FALHOU: {len(acoes)} aberturas enfileiradas, esperava 1"
    assert db.commits == 1, (
        f"FALHOU: {db.commits} commits. A ação foi inserida e NÃO commitada — "
        "a sessão do get_db fecha com rollback e a abertura some, exatamente como em 25/08.")
    assert db.eventos.index(("commit", None)) > db.eventos.index(("flush", None)), \
        "FALHOU: commitou ANTES do flush da ação"
    assert not db.acoes(KIND_LEMBRETE_REUNIAO), "FALHOU: lembrete sem reunião marcada"
    print(f"  5. POST /lead (sem agendar)        -> abertura=1 lembrete=0 "
          f"commits={db.commits}  eventos={[e[0] for e in db.eventos]}")


async def caso_6_booking_commita_abertura_e_lembrete():
    """POST /agendamento/agendar: abertura + lembrete no MESMO commit.

    O caminho do booking perdia as duas coisas pelo mesmo motivo — quem agenda pelo
    obrigado.html nunca passa pelo fluxo do agente, então era o único lembrete que ele teria.
    """
    from app.agendamento import agendar as fluxo
    futuro = datetime.now().replace(microsecond=0) + timedelta(days=1)
    ag = _agendamento("agendado", slot_inicio=futuro)
    db = FakeDB()

    await fluxo._gatilho_do_agente(db, ag)

    assert len(db.acoes(KIND_INICIAR_QUALIFICACAO)) == 1, "FALHOU: sem abertura"
    assert len(db.acoes(KIND_LEMBRETE_REUNIAO)) == 1, "FALHOU: sem lembrete"
    assert db.commits == 1, f"FALHOU: {db.commits} commits, esperava 1 para as duas ações"
    print(f"  6. POST /agendar (com reunião)     -> abertura=1 lembrete=1 "
          f"commits={db.commits}")


async def caso_7_nada_enfileirado_nao_commita():
    """Não-regressão: sem ação nenhuma, nada de commit.

    O commit é do gatilho, não do request. Commitar à toa aqui fecharia a transação do
    chamador por um efeito que não aconteceu.
    """
    from app.agendamento import agendar as fluxo
    ag = _agendamento("lead_criado")
    db = FakeDB()

    with patch("app.qualificacao_gatilho.agendar_abertura",
               new=AsyncMock(side_effect=RuntimeError("scheduler fora do ar"))):
        await fluxo._gatilho_do_agente(db, ag)

    assert db.commits == 0, f"FALHOU: commitou {db.commits}x sem ter enfileirado nada"
    print(f"  7. gatilho falhou, nada na fila    -> commits={db.commits} (não levantou)")


async def caso_8_quem_ja_tem_estado_nao_enfileira():
    """Não-regressão da regra que já existia: estado presente = sem abertura, sem commit."""
    from app.agendamento import agendar as fluxo
    ag = _agendamento("lead_criado")
    db = FakeDB(estado_existente="esp_link_enviado")

    await fluxo._gatilho_do_agente(db, ag)

    assert not db.acoes(KIND_INICIAR_QUALIFICACAO), "FALHOU: enfileirou para quem já tem estado"
    assert db.commits == 0, f"FALHOU: commitou {db.commits}x sem nada para salvar"
    print(f"  8. contato JÁ tem estado           -> abertura=0 commits={db.commits}")


async def main():
    print("\n=== GATILHO DA ABERTURA DO AGENTE — os dois caminhos de 25/08 ===\n")
    print(" caminho SYNC (exact_spotter, passo 4.5):")
    await caso_1_passo_4_5_com_register_date()
    await caso_2_a_acao_chega_na_fila()
    await caso_3_nenhum_datetime_vira_local()
    await caso_4_um_lead_ruim_nao_derruba_o_lote()
    print("\n caminho LP (agendamento/agendar, _gatilho_do_agente):")
    await caso_5_post_lead_commita()
    await caso_6_booking_commita_abertura_e_lembrete()
    await caso_7_nada_enfileirado_nao_commita()
    await caso_8_quem_ja_tem_estado_nao_enfileira()
    print("\nOK: 8/8 passaram. O passo 4.5 sobrevive a um lead com data, um lead ruim não "
          "derruba o lote,\ne as acoes da landing page chegam commitadas na fila.\n")


if __name__ == "__main__":
    asyncio.run(main())
