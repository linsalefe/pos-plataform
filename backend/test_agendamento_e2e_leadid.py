"""E2E REAL do fluxo de DUAS ETAPAS: cria o lead, depois agenda ELE — sem duplicar.

    cd backend && venv/bin/python test_agendamento_e2e_leadid.py --sim-eu-quero

------------------------------------------------------------------------------------------
LEIA ANTES DE RODAR
------------------------------------------------------------------------------------------
Vale tudo que está no cabeçalho de `test_agendamento_e2e.py`: escreve na Exact de PRODUÇÃO,
deixa **um box órfão permanente** (o `scheduleAdd` é irreversível, FINDINGS §6), exige
`--sim-eu-quero` e agenda em **2027**, longe de qualquer agenda real.

------------------------------------------------------------------------------------------
O QUE ESTE TESTE PROVA QUE O OUTRO NÃO PROVA
------------------------------------------------------------------------------------------
O E2E original atravessa o fluxo de UMA etapa, onde o `/agendar` cria o lead. Este aqui
atravessa o de DUAS, que é o novo caminho da landing page:

    1. `cadastrar_lead_sem_agendar`  (o que o POST /lead faz)  -> lead em Entrada
    2. `agendar(..., lead_id=...)`   (o que o POST /agendar faz) -> agenda O MESMO lead

A afirmação central é **negativa**, e é a razão de este arquivo existir: ao final tem que
haver **exatamente um** lead com este telefone na Exact. Se o `leadId` for ignorado em
algum ponto do caminho, aparecem dois — a pessoa vira dois cadastros no funil e um SDR liga
duas vezes para o mesmo número. Nenhum teste offline pega isso, porque o que falha é a
integração inteira, não uma função.

O telefone é exclusivo deste teste (11999995555) justamente para a contagem ser conclusiva.
"""
import asyncio
import json
import os
import sys
from datetime import date, datetime

NOME = "TESTE API Alefe E2E LEADID"
TELEFONE = "11999995555"
EMAIL = "teste-e2e-leadid@cenat.invalid"

# Quinta-feira distante, e um dia DIFERENTE do E2E de uma etapa (17/03/2027) para os dois
# poderem rodar na mesma tarde sem disputar o mesmo slot.
ALVO = date(2027, 3, 18)
HORA_INICIO = "14:00"
HORA_FIM = "14:45"


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
    """Grade de um slot só, na quinta distante. Precisa vir ANTES de importar o módulo."""
    assert ALVO.weekday() == 3, f"{ALVO} não é quinta-feira"
    janela = _janela_ate(ALVO)
    os.environ["AGENDAMENTO_GRADE_JSON"] = json.dumps({
        "sales_rep_email": "comercial@cenatcursos.com.br",
        "duracao_min": 45,
        "antecedencia_min_horas": 2,
        "janela_dias": janela,
        "type_meeting": "web",
        "janelas": {"3": [[HORA_INICIO, HORA_FIM]]},
    })
    return janela


async def _contar_leads(client, telefone: str) -> list[dict]:
    """Leads com este telefone. É a medida de "duplicou ou não".

    O `55` na frente NÃO é decoração: o `GET /Leads` devolve `phone1` com o DDI grudado
    (`5511999995555`), e consultar sem ele devolve zero em silêncio — foi assim que a
    primeira execução deste teste "provou" que o lead sumiu quando ele estava lá.
    Ver `client.buscar_lead_por_telefone`, que tinha exatamente o mesmo erro.
    """
    resp = await client._req("GET", "/Leads",
                             params={"$filter": f"phone1 eq '55{telefone}'", "$top": 50})
    return resp.json().get("value", [])


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
    print(f"\nE2E do fluxo de DUAS ETAPAS — janela {janela} dias, alvo {slot.id}\n")

    criados = []   # ids de lead para limpar no final, aconteça o que acontecer
    ags = []       # ids das nossas linhas em `agendamentos`
    r = None       # resultado do agendar(); fica None se o fluxo morrer antes

    try:
        # ---- 1. ponto de partida limpo ----------------------------------------------
        antes = await _contar_leads(client, TELEFONE)
        assert not antes, f"o telefone de teste já tem lead: {[l['id'] for l in antes]}"
        boxes = await client.listar_boxes(datetime.combine(ALVO, datetime.min.time()),
                                          datetime.combine(ALVO, datetime.max.time()),
                                          g.sales_rep_email)
        assert not boxes, f"a data de teste não está vazia: {boxes}"
        print(f"  1. {TELEFONE} sem lead nenhum, {ALVO} sem box nenhum")

        # ---- 2. ETAPA 1: o form nativo do index.html --------------------------------
        async with async_session() as db:
            lead_id = await fluxo.cadastrar_lead_sem_agendar(
                db, nome=NOME, email=EMAIL, telefone=TELEFONE,
                origem="PosMulheridades", origem_ip="127.0.0.1")
            # O /lead grava a própria linha em `agendamentos`; recolho o id para a limpeza.
            linha = (await db.execute(select(Agendamento)
                                      .where(Agendamento.lead_id == lead_id))).scalars().first()
            if linha:
                ags.append(linha.id)
        criados.append(lead_id)
        print(f"  2. ETAPA 1 (POST /lead): lead {lead_id} criado")

        resp = await client._req("GET", "/Leads", params={"$filter": f"id eq {lead_id}"})
        lead = resp.json()["value"][0]
        assert lead["stage"] == "Entrada", f"deveria nascer em Entrada: {lead['stage']}"
        assert lead["subSource"]["value"] == "PosMulheridades", lead["subSource"]
        print(f"     etapa={lead['stage']}, subSource={lead['subSource']['value']} "
              f"(a origem veio do index, não do obrigado)")

        # ---- 3. ETAPA 2: o obrigado.html agenda ESTE lead ---------------------------
        async with async_session() as db:
            r = await fluxo.agendar(db, nome=NOME, email=EMAIL, telefone=TELEFONE,
                                    slot_id=slot.id, lead_id=lead_id,
                                    origem_ip="127.0.0.1")
        ags.append(r.agendamento_id)
        assert r.lead_id == lead_id, \
            f"FALHOU: agendou o lead {r.lead_id}, mas o pedido era {lead_id}"
        print(f"  3. ETAPA 2 (POST /agendar com leadId): agendamento #{r.agendamento_id}, "
              f"box {r.box_id}, reunião {r.meeting_id}")

        # ---- 4. A AFIRMAÇÃO CENTRAL: um lead, não dois ------------------------------
        depois = await _contar_leads(client, TELEFONE)
        assert len(depois) == 1, (
            f"FALHOU — LEAD DUPLICADO: {len(depois)} leads com {TELEFONE}: "
            f"{[l['id'] for l in depois]}. O leadId foi ignorado em algum ponto.")
        assert depois[0]["id"] == lead_id, depois[0]["id"]
        print(f"  4. EXATAMENTE 1 lead com {TELEFONE} — o {lead_id}, o mesmo da etapa 1. "
              "Nenhum LeadsAdd extra.")

        # ---- 5. o lead andou de etapa, sem trocar de identidade ---------------------
        resp = await client._req("GET", "/Leads", params={"$filter": f"id eq {lead_id}"})
        lead = resp.json()["value"][0]
        assert lead["stage"] == "Agendados", f"etapa errada: {lead['stage']}"
        assert lead["salesRep"]["email"] == g.sales_rep_email, lead["salesRep"]
        assert lead["subSource"]["value"] == "PosMulheridades", \
            f"a origem mudou no caminho: {lead['subSource']}"
        print(f"  5. lead {lead_id}: Entrada -> {lead['stage']}, "
              f"salesRep={lead['salesRep']['email']}, subSource intacto")

        # ---- 6. o box e o fuso ------------------------------------------------------
        resp = await client._req("GET", "/Boxes", params={"$filter": f"id eq {r.box_id}"})
        box = resp.json()["value"][0]
        assert box["status"] == "busy" and box["leadId"] == lead_id, box
        assert box["start"] == f"{ALVO}T{HORA_INICIO}:00Z", \
            f"FUSO ERRADO: pedi {HORA_INICIO} e a Exact gravou {box['start']}"
        print(f"  6. box {r.box_id}: status={box['status']}, leadId={box['leadId']}, "
              f"start={box['start']} (hora de parede preservada)")

        # ---- 7. o estado local registrou a procedência ------------------------------
        async with async_session() as db:
            ag = (await db.execute(
                select(Agendamento).where(Agendamento.id == r.agendamento_id))).scalar_one()
            assert ag.passo == PASSO_AGENDADO, ag.passo
            assert ag.lead_externo is True, \
                f"FALHOU: lead veio pronto mas lead_externo={ag.lead_externo}"
            assert ag.lead_id == lead_id, ag.lead_id
            print(f"  7. agendamentos#{ag.id}: passo={ag.passo}, lead_externo={ag.lead_externo} "
                  "(dá para separar do fluxo de uma etapa no relatório)")

    finally:
        # ---- 8. limpeza — roda mesmo se algo acima falhar ---------------------------
        print("\n  8. limpeza:")
        orfao = None
        box_id = r.box_id if r else None
        for lid in criados:
            try:
                await client._req("DELETE", f"/LeadsDelete/{lid}")
                print(f"     lead {lid} excluído (204)")
            except client.ExactErro as e:
                print(f"     ⚠️ lead {lid} não excluído: {e}")
        if box_id:
            try:
                await client.remover_box(box_id)
                print(f"     box {box_id} removido — inesperado, mas ótimo")
            except client.BoxComReuniao:
                orfao = box_id
                print(f"     box {box_id} NÃO removível (tem reunião) — órfão previsto")
            except client.ExactErro as e:
                print(f"     ⚠️ box {box_id}: {e}")
        if ags:
            async with async_session() as db:
                await db.execute(delete(Agendamento).where(Agendamento.id.in_(ags)))
                await db.commit()
            print(f"     linhas agendamentos {ags} removidas")

    # ---- 9. confirmação final ------------------------------------------------------
    # O índice de texto da Exact atrasa alguns segundos depois do DELETE (FINDINGS §10).
    # A busca por telefone usa `phone1 eq`, que é igualdade e não texto — mas insiste do
    # mesmo jeito, porque não custa e o modo de falha seria um falso alarme.
    restantes = None
    for tentativa in range(6):
        restantes = await _contar_leads(client, TELEFONE)
        if not restantes:
            break
        await asyncio.sleep(5)
        print(f"     (índice ainda mostra o lead; tentativa {tentativa + 1}/6)")
    assert not restantes, f"sobrou lead: {[l['id'] for l in restantes]}"
    boxes = await client.listar_boxes(datetime.combine(ALVO, datetime.min.time()),
                                      datetime.combine(ALVO, datetime.max.time()),
                                      g.sales_rep_email)
    assert not boxes, f"box ainda visível em {ALVO}: {boxes}"
    print(f"  9. 0 leads com {TELEFONE}, 0 boxes visíveis em {ALVO}")

    print(f"\nOK: 9/9. Resíduo permanente: box {orfao} (órfão, invisível, não bloqueia).\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
