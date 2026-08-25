"""E2E REAL do agendamento: cria box, lead e reunião DE VERDADE na Exact de produção.

    cd backend && venv/bin/python test_agendamento_e2e.py --sim-eu-quero

------------------------------------------------------------------------------------------
LEIA ANTES DE RODAR
------------------------------------------------------------------------------------------
Este teste **deixa resíduo permanente**. O `scheduleAdd` é irreversível: não existe
`ScheduleRemove` na API, e um box com reunião recusa `BoxesRemove` para sempre
(AGENDAMENTO_FINDINGS.md §6). Ao final, o lead é excluído e o box fica **órfão** — invisível
em todo GET, sem bloquear a agenda, e impossível de remover.

Por isso ele:
  * exige o argumento `--sim-eu-quero`, para não rodar por engano num `for` de CI;
  * agenda em **2027**, longe de qualquer agenda real de consultor;
  * usa uma grade própria, passada por env, que não toca na grade de produção.

O caminho exercitado é o REAL: `fluxo.agendar()`, o mesmo que o POST /agendar chama. Só o
que muda é a grade — nada é mockado, nem a Exact nem o banco.
"""
import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta

NOME = "TESTE API Alefe E2E"
TELEFONE = "11999996666"
EMAIL = "teste-e2e@cenat.invalid"

# Quarta-feira distante, deliberadamente fora de qualquer agenda real.
ALVO = date(2027, 3, 17)
HORA_INICIO = "11:00"
HORA_FIM = "11:45"


def _janela_ate(alvo):
    """Dias de HOJE até o alvo, inclusive, contados NO FUSO DE SÃO PAULO.

    `date.today()` usa a hora do sistema, que aqui é UTC. A grade conta os dias a partir de
    `agora_sp()`. Entre 21:00 e 00:00 de São Paulo os dois JÁ ESTÃO EM DIAS DIFERENTES, e a
    janela sai um dia curta — o alvo simplesmente não aparece em `slots_candidatos()`, e o
    teste morre com "esperava 1 slot, achei 0" sem nada a ver com o que ele testa.

    É a mesma classe de erro que o módulo inteiro existe para evitar (FINDINGS §1), só que
    do lado do teste. Medido de verdade: rodando 00:0x UTC, `date.today()` dava 2026-08-18 e
    `agora_sp().date()` dava 2026-08-17.

    O `+ 1` é a janela contando HOJE como dia 1 (grade.py: `range(janela_dias)`). E
    `janela_dias` vai EXPLÍCITO na config de propósito: assim o `AGENDAMENTO_JANELA_DIAS=3`
    do servidor não encurta a janela deste teste para três dias e some com o alvo.
    """
    from app.agendamento.horarios import agora_sp
    return (alvo - agora_sp().date()).days + 1


def _preparar_grade():
    """Grade de um slot só, na quarta distante. Precisa vir ANTES de importar o módulo."""
    assert ALVO.weekday() == 2, f"{ALVO} não é quarta-feira"
    janela = _janela_ate(ALVO)
    os.environ["AGENDAMENTO_GRADE_JSON"] = json.dumps({
        "sales_rep_email": "comercial@cenatcursos.com.br",
        "duracao_min": 45,
        "antecedencia_min_horas": 2,
        "janela_dias": janela,
        "type_meeting": "web",
        "janelas": {"2": [[HORA_INICIO, HORA_FIM]]},
    })
    return janela


async def main():
    if "--sim-eu-quero" not in sys.argv:
        print(__doc__)
        print("Recusado: falta --sim-eu-quero. Este teste escreve na Exact de PRODUÇÃO.")
        return 1

    janela = _preparar_grade()

    from sqlalchemy import delete, select

    from app.agendamento import agendar as fluxo
    from app.agendamento import client
    from app.agendamento.grade import recarregar
    from app.database import async_session
    from app.models import PASSO_AGENDADO, Agendamento

    g = recarregar()
    alvo = [s for s in g.slots_candidatos() if s.inicio.date() == ALVO]
    assert len(alvo) == 1, f"esperava 1 slot em {ALVO}, achei {len(alvo)}"
    slot = alvo[0]
    print(f"\nE2E do agendamento — janela {janela} dias, alvo {slot.id}\n")

    # ---- 1. o slot está livre na Exact? --------------------------------------------
    boxes = await client.listar_boxes(datetime.combine(ALVO, datetime.min.time()),
                                      datetime.combine(ALVO, datetime.max.time()),
                                      g.sales_rep_email)
    assert not boxes, f"a data de teste não está vazia: {boxes}"
    print(f"  1. {ALVO} sem nenhum box para {g.sales_rep_email}")

    # ---- 2. o fluxo real -------------------------------------------------------------
    async with async_session() as db:
        r = await fluxo.agendar(db, nome=NOME, email=EMAIL, telefone=TELEFONE,
                                slot_id=slot.id, origem_ip="127.0.0.1")
    print(f"  2. agendado: agendamento #{r.agendamento_id}, lead {r.lead_id}, "
          f"box {r.box_id}, reunião {r.meeting_id}")

    # ---- 3. o lead está em Agendados? ------------------------------------------------
    resp = await client._req("GET", "/Leads", params={"$filter": f"id eq {r.lead_id}"})
    lead = resp.json()["value"][0]
    assert lead["stage"] == "Agendados", f"etapa errada: {lead['stage']}"
    assert lead["funnelId"] == fluxo.FUNIL_POS_GRADUACAO, lead["funnelId"]
    assert lead["salesRep"]["email"] == g.sales_rep_email, lead["salesRep"]
    print(f"  3. lead {r.lead_id}: etapa={lead['stage']}, funil={lead['funnelId']}, "
          f"salesRep={lead['salesRep']['email']}, source={lead['source']['value']}, "
          f"subSource={lead['subSource']['value']}")

    # ---- 4. o box virou busy com o leadId? -------------------------------------------
    resp = await client._req("GET", "/Boxes", params={"$filter": f"id eq {r.box_id}"})
    box = resp.json()["value"][0]
    assert box["status"] == "busy", box
    assert box["leadId"] == r.lead_id, box
    assert box["start"] == f"{ALVO}T{HORA_INICIO}:00Z", \
        f"FUSO ERRADO: pedi {HORA_INICIO} e a Exact gravou {box['start']}"
    print(f"  4. box {r.box_id}: status={box['status']}, leadId={box['leadId']}, "
          f"start={box['start']} (hora de parede preservada)")

    # ---- 5. o estado local bate? -----------------------------------------------------
    async with async_session() as db:
        ag = (await db.execute(
            select(Agendamento).where(Agendamento.id == r.agendamento_id))).scalar_one()
        assert ag.passo == PASSO_AGENDADO, ag.passo
        assert (ag.lead_id, ag.box_id) == (r.lead_id, r.box_id)
        assert ag.slot_inicio == slot.inicio, (ag.slot_inicio, slot.inicio)
        assert ag.email == EMAIL, ag.email
        print(f"  5. agendamentos#{ag.id}: passo={ag.passo}, slot={ag.slot_inicio}, "
              f"email guardado (a Exact não tem campo para ele)")

    # ---- 6. limpeza possível ---------------------------------------------------------
    await client._req("DELETE", f"/LeadsDelete/{r.lead_id}")
    print(f"  6. lead {r.lead_id} excluído (204)")

    try:
        await client.remover_box(r.box_id)
        print(f"     box {r.box_id} removido — inesperado, mas ótimo")
        orfao = None
    except client.BoxComReuniao:
        orfao = r.box_id
        print(f"     box {r.box_id} NÃO removível (tem reunião) — órfão previsto e aceito")

    async with async_session() as db:
        await db.execute(delete(Agendamento).where(Agendamento.id == r.agendamento_id))
        await db.commit()
    print(f"     linha agendamentos#{r.agendamento_id} removida (tabela volta a vazia)")

    # ---- 7. confirmação final --------------------------------------------------------
    # O `contains(lead, ...)` responde de um índice que atrasa alguns segundos em relação ao
    # DELETE — medido na primeira execução deste teste: a busca por texto ainda devolvia o
    # lead que a busca por `id eq` já não encontrava. Não é o DELETE que falhou; é a leitura
    # que está velha. Por isso aqui insiste em vez de afirmar de primeira.
    restantes = None
    for tentativa in range(6):
        resp = await client._req("GET", "/Leads",
                                 params={"$filter": "contains(lead,'TESTE API')"})
        restantes = resp.json()["value"]
        if not restantes:
            break
        await asyncio.sleep(5)
        print(f"     (índice de texto ainda mostra o lead; tentativa {tentativa + 1}/6)")
    assert not restantes, f"sobrou lead de teste: {[l['id'] for l in restantes]}"
    boxes = await client.listar_boxes(datetime.combine(ALVO, datetime.min.time()),
                                      datetime.combine(ALVO, datetime.max.time()),
                                      g.sales_rep_email)
    assert not boxes, f"box ainda visível em {ALVO}: {boxes}"
    print(f"  7. 0 leads 'TESTE API', 0 boxes visíveis em {ALVO}")

    print(f"\nOK: 7/7. Resíduo permanente: box {orfao} (órfão, invisível, não bloqueia).\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
