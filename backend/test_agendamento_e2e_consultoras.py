"""E2E REAL de múltiplas consultoras: a ocupada é pulada, a livre atende.

    cd backend && venv/bin/python test_agendamento_e2e_consultoras.py --sim-eu-quero

------------------------------------------------------------------------------------------
LEIA ANTES DE RODAR
------------------------------------------------------------------------------------------
Escreve na Exact de PRODUÇÃO e deixa **um box órfão permanente** (o `scheduleAdd` é
irreversível, FINDINGS §6). Agenda em 2027, longe de qualquer agenda real, e exige
`--sim-eu-quero`.

------------------------------------------------------------------------------------------
O QUE ELE PROVA QUE O OFFLINE NÃO PROVA
------------------------------------------------------------------------------------------
O teste offline mocka `Boxes are occupied`. Aqui a recusa vem da Exact DE VERDADE: o teste
cria um box bloqueador na agenda da primeira consultora e deixa o `BoxesAdd` bater nele.

É a diferença entre "meu código trata a exceção que eu inventei" e "a Exact recusa como eu
acho que recusa, e o fluxo se recupera". A mensagem exata (`Boxes are occupied at the desired
time.`) é o que `client._ERROS` casa por prefixo — se a Exact mudar o texto, o erro deixa de
virar `SlotOcupado`, o retry nunca acontece e o visitante toma 502 em vez de ser atendido
pela segunda consultora. Só um teste real pega isso.
"""
import asyncio
import json
import os
import sys
from datetime import date, datetime

# As duas candidatas a consultora. NÃO é o comercial@ (esse é o SDR de pré-venda).
CONSULTORA_A = "processoseletivo@cenatcursos.com.br"
CONSULTORA_B = "executivadecarreiras@cenatcursos.com.br"

NOME = "TESTE API Alefe E2E CONSULTORAS"
TELEFONE = "11999997777"
EMAIL = "teste-e2e-consultoras@cenat.invalid"

ALVO = date(2027, 4, 21)          # quarta distante
HORA_INICIO, HORA_FIM = "10:00", "10:45"


def _janela_ate(alvo):
    """Dias de HOJE até o alvo, inclusive, no fuso de SP. Ver test_agendamento_e2e.py."""
    from app.agendamento.horarios import agora_sp
    return (alvo - agora_sp().date()).days + 1


def _preparar():
    """Duas consultoras, mesma janela de um slot só. Antes de importar o módulo."""
    assert ALVO.weekday() == 2, f"{ALVO} não é quarta"
    g = {"duracao_min": 45, "antecedencia_min_horas": 2,
         "janela_dias": _janela_ate(ALVO), "type_meeting": "web",
         "janelas": {"2": [[HORA_INICIO, HORA_FIM]]}}
    os.environ["AGENDAMENTO_CONSULTORAS"] = json.dumps([
        {"email": CONSULTORA_A, "nome_exibicao": "Consultora A", "grade": g},
        {"email": CONSULTORA_B, "nome_exibicao": "Consultora B", "grade": g},
    ])


async def main():
    if "--sim-eu-quero" not in sys.argv:
        print(__doc__)
        print("Recusado: falta --sim-eu-quero. Este teste escreve na Exact de PRODUÇÃO.")
        return 1

    from sqlalchemy import delete, select

    from app.agendamento import agendar as fluxo
    from app.agendamento import client, consultoras as equipe_mod, disponibilidade
    from app.database import async_session
    from app.models import PASSO_AGENDADO, Agendamento

    _preparar()
    equipe = equipe_mod.recarregar()
    assert len(equipe) == 2, equipe
    print(f"\nE2E multi-consultora — alvo {ALVO} {HORA_INICIO}, "
          f"A={CONSULTORA_A.split('@')[0]} B={CONSULTORA_B.split('@')[0]}\n")

    bloqueador = None
    r = None
    ags = []
    leads = []

    try:
        # ---- 1. as duas validam contra /Sellers? -----------------------------------
        resumo = await equipe_mod.validar_contra_exact()
        assert not resumo["checagem_falhou"], "não consegui falar com /Sellers"
        assert not resumo["invalidas"], f"consultora inválida: {resumo['invalidas']}"
        print(f"  1. /Sellers valida as duas: {resumo['verificadas']}")

        # ---- 2. o dia está limpo para ambas? ---------------------------------------
        dia_ini = datetime.combine(ALVO, datetime.min.time())
        dia_fim = datetime.combine(ALVO, datetime.max.time())
        for c in equipe:
            b = await client.listar_boxes(dia_ini, dia_fim, c.email)
            assert not b, f"{c.email} não está livre em {ALVO}: {b}"
        print(f"  2. {ALVO} sem box para nenhuma das duas")

        # ---- 3. a união oferece o slot, com AS DUAS livres -------------------------
        disponibilidade.invalidar_cache()
        async with async_session() as db:
            livres = await disponibilidade.slots_livres(db, usar_cache=False)
        alvo = [d for d in livres if d.slot.inicio.date() == ALVO]
        assert len(alvo) == 1, f"esperava 1 slot em {ALVO}, achei {len(alvo)}"
        disp = alvo[0]
        assert len(disp.consultoras) == 2, [c.email for c in disp.consultoras]
        print(f"  3. /slots oferece {disp.id} com as 2 consultoras livres")

        # ---- 4. BLOQUEIO REAL na agenda da A ---------------------------------------
        # Box `busy` sem reunião: é removível depois (FINDINGS §8, bônus) e faz o
        # BoxesAdd da A recusar de verdade, sem mock nenhum.
        bloqueador = await client.criar_box(
            inicio=disp.slot.inicio, fim=disp.slot.fim, sales_rep_email=CONSULTORA_A,
            type_meeting="web", description="TESTE API BLOQUEADOR - pode excluir")
        print(f"  4. box bloqueador {bloqueador} criado na agenda da A")

        # ---- 5. o fluxo real: tem que pular a A e agendar com a B ------------------
        async with async_session() as db:
            r = await fluxo.agendar(db, nome=NOME, email=EMAIL, telefone=TELEFONE,
                                    slot_id=disp.id, origem="PosMulheridades",
                                    origem_ip="127.0.0.1")
        ags.append(r.agendamento_id)
        leads.append(r.lead_id)
        assert r.consultora_email == CONSULTORA_B, (
            f"FALHOU: agendou com {r.consultora_email}, mas a A estava bloqueada — "
            "o retry não aconteceu")
        print(f"  5. agendou com a B ({r.consultora_nome}): lead {r.lead_id}, "
              f"box {r.box_id}, reunião {r.meeting_id}")

        # ---- 6. a Exact concorda: o lead é da B ------------------------------------
        resp = await client._req("GET", "/Leads", params={"$filter": f"id eq {r.lead_id}"})
        lead = resp.json()["value"][0]
        assert lead["salesRep"]["email"] == CONSULTORA_B, lead["salesRep"]
        assert lead["stage"] == "Agendados", lead["stage"]
        print(f"  6. lead na Exact: etapa={lead['stage']}, "
              f"salesRep={lead['salesRep']['email']}")

        resp = await client._req("GET", "/Boxes", params={"$filter": f"id eq {r.box_id}"})
        box = resp.json()["value"][0]
        assert box["salesRepEmail"] == CONSULTORA_B, box
        assert box["start"] == f"{ALVO}T{HORA_INICIO}:00Z", \
            f"FUSO ERRADO: pedi {HORA_INICIO}, a Exact gravou {box['start']}"
        print(f"  7. box {r.box_id} é da B, start={box['start']} (hora de parede)")

        # ---- 8. a tabela registrou quem atendeu ------------------------------------
        async with async_session() as db:
            ag = (await db.execute(select(Agendamento)
                                   .where(Agendamento.id == r.agendamento_id))).scalar_one()
            assert ag.passo == PASSO_AGENDADO, ag.passo
            assert ag.sales_rep_email == CONSULTORA_B, ag.sales_rep_email
            print(f"  8. agendamentos#{ag.id}.sales_rep_email = {ag.sales_rep_email}")

    finally:
        print("\n  9. limpeza:")
        for lid in leads:
            try:
                await client._req("DELETE", f"/LeadsDelete/{lid}")
                print(f"     lead {lid} excluído (204)")
            except client.ExactErro as e:
                print(f"     ⚠️ lead {lid}: {e}")
        if bloqueador:
            try:
                await client.remover_box(bloqueador)
                print(f"     bloqueador {bloqueador} removido (sem reunião, sai limpo)")
            except client.ExactErro as e:
                print(f"     ⚠️ bloqueador {bloqueador}: {e}")
        orfao = None
        if r and r.box_id:
            try:
                await client.remover_box(r.box_id)
                print(f"     box {r.box_id} removido — inesperado, mas ótimo")
            except client.BoxComReuniao:
                orfao = r.box_id
                print(f"     box {r.box_id} NÃO removível (tem reunião) — órfão previsto")
        if ags:
            async with async_session() as db:
                await db.execute(delete(Agendamento).where(Agendamento.id.in_(ags)))
                await db.commit()
            print(f"     linhas agendamentos {ags} removidas")

    # ---- 10. nada visível sobrou ---------------------------------------------------
    for c in (CONSULTORA_A, CONSULTORA_B):
        b = await client.listar_boxes(datetime.combine(ALVO, datetime.min.time()),
                                      datetime.combine(ALVO, datetime.max.time()), c)
        assert not b, f"box ainda visível para {c}: {b}"
    print(f"  10. 0 boxes visíveis em {ALVO} para as duas")

    print(f"\nOK: 10/10. Resíduo permanente: box {orfao} (órfão, invisível, não bloqueia).\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
