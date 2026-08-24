"""E2E REAL do passo 4: agenda no 18535 e transfere para o funil de Vendas.

    cd backend && venv/bin/python test_agendamento_e2e_funil.py --sim-eu-quero

------------------------------------------------------------------------------------------
LEIA ANTES DE RODAR
------------------------------------------------------------------------------------------
Escreve na Exact de PRODUÇÃO e deixa **um box órfão permanente** (`scheduleAdd` é
irreversível, FINDINGS §6). Agenda em 2027 e exige `--sim-eu-quero`.

------------------------------------------------------------------------------------------
O QUE ELE VERIFICA — E O QUE ELE DOCUMENTA
------------------------------------------------------------------------------------------
Verifica que o agendamento SOBREVIVE à transferência: o lead muda de funil, mas o box
continua `busy` e vinculado, e a reunião mantém id, data e consultora.

E documenta, num assert explícito, o efeito colateral que decide se o passo 4 deve ficar
ligado: **a reunião passa de `Vigente` para `Concluido`** (FINDINGS §15). Uma reunião futura
constando como realizada. O teste AFIRMA esse comportamento em vez de ignorá-lo — se um dia a
Exact parar de fazer isso, o teste falha e alguém relê a decisão de produto.
"""
import asyncio
import json
import os
import sys
from datetime import date, datetime

CONSULTORA = "processoseletivo@cenatcursos.com.br"
STAGE_VENDAS = 133413          # "Agendados" do funil 18537
FUNIL_PRE, FUNIL_VENDAS = 18535, 18537

NOME = "TESTE API Alefe E2E FUNIL"
TELEFONE = "11999996161"
ALVO = date(2027, 5, 19)       # quarta distante
HORA_INICIO, HORA_FIM = "10:00", "10:45"


def _horizonte_ate(alvo):
    from app.agendamento.horarios import agora_sp
    return (alvo - agora_sp().date()).days


def _preparar():
    assert ALVO.weekday() == 2, f"{ALVO} não é quarta"
    os.environ["AGENDAMENTO_CONSULTORAS"] = json.dumps([{
        "email": CONSULTORA, "nome_exibicao": "Consultora Teste",
        "grade": {"duracao_min": 45, "antecedencia_min_horas": 2,
                  "horizonte_dias": _horizonte_ate(ALVO), "type_meeting": "web",
                  "janelas": {"2": [[HORA_INICIO, HORA_FIM]]}}}])
    os.environ["AGENDAMENTO_FUNIL_DESTINO"] = str(STAGE_VENDAS)


async def _reuniao(client, lead_id):
    m = (await client._req("GET", "/Meetings",
                           params={"$filter": f"lead/id eq {lead_id}"})).json().get("value", [])
    return m[0] if m else None


async def main():
    if "--sim-eu-quero" not in sys.argv:
        print(__doc__)
        print("Recusado: falta --sim-eu-quero. Este teste escreve na Exact de PRODUÇÃO.")
        return 1

    from sqlalchemy import delete, select

    from app.agendamento import agendar as fluxo
    from app.agendamento import client, consultoras as equipe_mod
    from app.database import async_session
    from app.models import PASSO_AGENDADO, Agendamento

    _preparar()
    equipe_mod.recarregar()
    print(f"\nE2E do passo 4 — alvo {ALVO} {HORA_INICIO}, destino etapa {STAGE_VENDAS}\n")

    r = None
    ags = []
    try:
        # ---- 1. o destino é uma etapa real e ativa? --------------------------------
        v = await fluxo.validar_funil_destino()
        assert v.get("ativo") and not v.get("invalida"), v
        assert v["funnel_id"] == FUNIL_VENDAS, v
        print(f"  1. destino validado: {v['etapa']!r} no funil {v['funnel_id']}")

        # ---- 2. dia limpo ----------------------------------------------------------
        dia_i = datetime.combine(ALVO, datetime.min.time())
        dia_f = datetime.combine(ALVO, datetime.max.time())
        assert not await client.listar_boxes(dia_i, dia_f, CONSULTORA), "dia não está vazio"
        print(f"  2. {ALVO} sem box para {CONSULTORA}")

        # ---- 3. fluxo real, com o passo 4 ligado ------------------------------------
        slot = [s for s in equipe_mod.consultoras()[0].grade.slots_candidatos()
                if s.inicio.date() == ALVO]
        assert len(slot) == 1, slot
        async with async_session() as db:
            r = await fluxo.agendar(db, nome=NOME, email=None, telefone=TELEFONE,
                                    slot_id=slot[0].id, origem="PosMulheridades",
                                    origem_ip="127.0.0.1")
        ags.append(r.agendamento_id)
        print(f"  3. agendado: lead {r.lead_id}, box {r.box_id}, reunião {r.meeting_id}")

        # ---- 4. o lead FOI para o funil de vendas? ----------------------------------
        lead = (await client._req("GET", "/Leads",
                                  params={"$filter": f"id eq {r.lead_id}"})).json()["value"][0]
        assert lead["funnelId"] == FUNIL_VENDAS, (
            f"FALHOU: lead ficou no funil {lead['funnelId']}, esperava {FUNIL_VENDAS}")
        assert lead["stage"] == "Agendados", lead["stage"]
        assert lead["salesRep"]["email"] == CONSULTORA, lead["salesRep"]
        print(f"  4. lead no funil {lead['funnelId']} ({lead['stage']}), "
              f"salesRep preservado")

        # ---- 5. O AGENDAMENTO SOBREVIVEU? ------------------------------------------
        box = (await client._req("GET", "/Boxes",
                                 params={"$filter": f"id eq {r.box_id}"})).json()["value"][0]
        assert box["status"] == "busy", f"FALHOU: box virou {box['status']!r}"
        assert box["leadId"] == r.lead_id, f"FALHOU: box desvinculou ({box['leadId']})"
        assert box["salesRepEmail"] == CONSULTORA, box
        assert box["start"] == f"{ALVO}T{HORA_INICIO}:00Z", box["start"]
        print(f"  5. box INTACTO: busy, leadId={box['leadId']}, start={box['start']}")

        reuniao = await _reuniao(client, r.lead_id)
        assert reuniao is not None, "FALHOU: a reunião SUMIU depois da transferência"
        assert reuniao["id"] == r.meeting_id, (
            f"FALHOU: a reunião trocou de id ({r.meeting_id} -> {reuniao['id']})")
        assert reuniao["meetingDate"] == str(ALVO), reuniao["meetingDate"]
        print(f"  6. reunião INTACTA: id={reuniao['id']}, data={reuniao['meetingDate']}, "
              f"rep={(reuniao.get('salesRep') or {}).get('email')}")

        # ---- 7. o efeito colateral, afirmado de propósito ---------------------------
        assert reuniao["type"] == "Concluido", (
            f"A reunião veio como {reuniao['type']!r}. Se a Exact parou de marcar "
            "'Concluido' na transferência, ÓTIMO — mas releia FINDINGS §15 e a decisão de "
            "manter o passo 4 desligado, porque ela foi tomada por causa disso.")
        print(f"  7. ⚠️ type={reuniao['type']!r} — reunião FUTURA ({ALVO}) consta como "
              "realizada. É o custo do passo 4, medido e documentado.")

        # ---- 8. estado local --------------------------------------------------------
        async with async_session() as db:
            ag = (await db.execute(select(Agendamento)
                                   .where(Agendamento.id == r.agendamento_id))).scalar_one()
            assert ag.passo == PASSO_AGENDADO and ag.erro is None, (ag.passo, ag.erro)
            print(f"  8. agendamentos#{ag.id}: passo={ag.passo}, erro=None")

    finally:
        print("\n  9. limpeza:")
        if r and r.lead_id:
            try:
                await client._req("DELETE", f"/LeadsDelete/{r.lead_id}")
                print(f"     lead {r.lead_id} excluído (204)")
            except client.ExactErro as e:
                print(f"     ⚠️ lead: {e}")
        orfao = None
        if r and r.box_id:
            try:
                await client.remover_box(r.box_id)
                print(f"     box {r.box_id} removido — inesperado, mas ótimo")
            except client.BoxComReuniao:
                orfao = r.box_id
                print(f"     box {r.box_id} NÃO removível (tem reunião) — órfão previsto")
            except client.ExactErro as e:
                print(f"     ⚠️ box: {e}")
        if ags:
            async with async_session() as db:
                await db.execute(delete(Agendamento).where(Agendamento.id.in_(ags)))
                await db.commit()
            print(f"     linhas agendamentos {ags} removidas")
        os.environ.pop("AGENDAMENTO_FUNIL_DESTINO", None)

    b = await client.listar_boxes(datetime.combine(ALVO, datetime.min.time()),
                                  datetime.combine(ALVO, datetime.max.time()), CONSULTORA)
    assert not b, f"box ainda visível: {b}"
    print(f"  10. 0 boxes visíveis em {ALVO}")
    print(f"\nOK: 10/10. Resíduo permanente: box {orfao} (órfão, invisível, não bloqueia).\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
