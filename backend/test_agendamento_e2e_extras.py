"""E2E REAL dos extras: o `description` chega mesmo à Exact, e do jeito que o SDR lê.

    cd backend && venv/bin/python test_agendamento_e2e_extras.py --sim-eu-quero

------------------------------------------------------------------------------------------
ESTE É O ÚNICO E2E DO MÓDULO QUE NÃO DEIXA RESÍDUO
------------------------------------------------------------------------------------------
Ele exercita só o caminho do `POST /lead`: `LeadsAdd` e nada mais. Sem `BoxesAdd` e sem
`scheduleAdd`, o `LeadsDelete` limpa 100% — o box órfão permanente dos outros E2E vem da
reunião (FINDINGS §6), e aqui não existe reunião.

Ainda assim escreve na Exact de PRODUÇÃO, então mantém o `--sim-eu-quero`.

------------------------------------------------------------------------------------------
O QUE ELE PROVA QUE O TESTE OFFLINE NÃO PROVA
------------------------------------------------------------------------------------------
O offline verifica a string que MONTAMOS. Este verifica a string que a Exact GUARDOU — e são
coisas diferentes, porque o `description` tem teto de 8000 e a API trunca em silêncio, sem
erro e sem log (FINDINGS §13). Só relendo o lead dá para afirmar que nada se perdeu.

Verifica também que acentuação sobrevive à viagem: `Profissão` e `Até R$100,00` passam por
JSON, HTTP e o banco da Exact, e voltam iguais.
"""
import asyncio
import sys

NOME = "TESTE API Alefe E2E EXTRAS"
TELEFONE = "11999993333"
EMAIL = "teste-e2e-extras@cenat.invalid"

EXTRAS = {
    "Profissão": "Psicologia",
    "Ensino Superior": "Sim",
    "Como conheceu": "Instagram",
    "Faixa": "Até R$100,00",
}
ESPERADO = ("E-mail: teste-e2e-extras@cenat.invalid | Profissão: Psicologia | "
            "Ensino Superior: Sim | Como conheceu: Instagram | Faixa: Até R$100,00")


async def _ler_lead(client, lead_id, tentativas=5):
    """Relê insistindo: logo após o LeadsAdd a leitura às vezes volta sem o description.

    Não é o índice de texto de FINDINGS §10 (aqui o filtro é por id, que é consistente) —
    é o campo que demora a aparecer. Medido durante a sonda do limite de tamanho.
    """
    for _ in range(tentativas):
        resp = await client._req("GET", "/Leads", params={"$filter": f"id eq {lead_id}"})
        v = resp.json().get("value", [])
        if v and v[0].get("description") is not None:
            return v[0]
        await asyncio.sleep(2)
    return v[0] if v else None


async def main():
    if "--sim-eu-quero" not in sys.argv:
        print(__doc__)
        print("Recusado: falta --sim-eu-quero. Este teste escreve na Exact de PRODUÇÃO.")
        return 1

    from sqlalchemy import delete, select

    from app.agendamento import agendar as fluxo
    from app.agendamento import client, extras as ex
    from app.database import async_session
    from app.models import Agendamento

    print("\nE2E dos extras — só LeadsAdd, sem box e sem reunião (resíduo zero)\n")
    criados, ags = [], []

    try:
        # ---- 1. o texto que vamos mandar ------------------------------------------
        montado = ex.montar_descricao(EMAIL, ex.sanitizar(EXTRAS))
        assert montado == ESPERADO, f"formato mudou:\n  {montado}"
        print(f"  1. description montado ({len(montado)} chars):\n     {montado}")

        # ---- 2. o caminho real do POST /lead --------------------------------------
        async with async_session() as db:
            lead_id = await fluxo.cadastrar_lead_sem_agendar(
                db, nome=NOME, email=EMAIL, telefone=TELEFONE,
                origem="PosMulheridades", extras=ex.sanitizar(EXTRAS),
                origem_ip="127.0.0.1")
            linha = (await db.execute(select(Agendamento)
                                      .where(Agendamento.lead_id == lead_id))).scalars().first()
            if linha:
                ags.append(linha.id)
        criados.append(lead_id)
        print(f"  2. lead {lead_id} criado pelo fluxo real")

        # ---- 3. A PROVA: o que a Exact GUARDOU -------------------------------------
        lead = await _ler_lead(client, lead_id)
        assert lead is not None, "não consegui reler o lead"
        guardado = lead.get("description")
        assert guardado == ESPERADO, (
            f"FALHOU — a Exact guardou diferente do que mandamos:\n"
            f"  enviado ({len(montado)}): {montado!r}\n"
            f"  guardado ({len(guardado or '')}): {guardado!r}")
        print(f"  3. a Exact guardou os {len(guardado)} chars IDÊNTICOS — nada truncado")

        # ---- 4. acentuação sobreviveu à viagem -------------------------------------
        for pedaco in ("Profissão: Psicologia", "Até R$100,00", "Ensino Superior: Sim"):
            assert pedaco in guardado, f"perdeu no caminho: {pedaco!r}"
        print("  4. acentos intactos: 'Profissão', 'Até R$100,00'")

        # ---- 5. a coluna JSONB nossa ----------------------------------------------
        async with async_session() as db:
            ag = (await db.execute(select(Agendamento)
                                   .where(Agendamento.id == ags[0]))).scalar_one()
            assert ag.extras == EXTRAS, f"JSONB diferente: {ag.extras}"
            # JSONB devolve dict de verdade, não string — é o ponto de não ter usado Text.
            assert isinstance(ag.extras, dict), type(ag.extras)
            print(f"  5. agendamentos#{ag.id}.extras é dict Python com "
                  f"{len(ag.extras)} chaves, sem parse na aplicação")

        # ---- 6. consulta por dentro do JSONB ---------------------------------------
        async with async_session() as db:
            from sqlalchemy import text as sqltext
            r = (await db.execute(sqltext(
                "SELECT extras->>'Como conheceu' FROM agendamentos WHERE id = :i"),
                {"i": ags[0]})).scalar()
            assert r == "Instagram", r
            print(f"  6. SELECT extras->>'Como conheceu' -> {r!r} "
                  "(a consulta que o marketing vai querer)")

    finally:
        print("\n  7. limpeza:")
        for lid in criados:
            try:
                await client._req("DELETE", f"/LeadsDelete/{lid}")
                print(f"     lead {lid} excluído (204)")
            except client.ExactErro as e:
                print(f"     ⚠️ lead {lid}: {e}")
        if ags:
            async with async_session() as db:
                await db.execute(delete(Agendamento).where(Agendamento.id.in_(ags)))
                await db.commit()
            print(f"     linhas agendamentos {ags} removidas")

    # ---- 8. nada sobrou ------------------------------------------------------------
    # INSISTE, e a razão é um achado desta rodada: o atraso de índice da Exact
    # (FINDINGS §10) NÃO se limita à busca textual `contains()`. O filtro `phone1 eq`, que é
    # igualdade e não texto, também continuou devolvendo o lead alguns segundos depois de o
    # DELETE responder 204. Só `id eq` é consistente na hora.
    sobrou = None
    for tentativa in range(6):
        resp = await client._req("GET", "/Leads",
                                 params={"$filter": f"phone1 eq \'55{TELEFONE}\'", "$top": 10})
        sobrou = resp.json().get("value", [])
        if not sobrou:
            break
        await asyncio.sleep(5)
        print(f"     (índice ainda mostra o lead; tentativa {tentativa + 1}/6)")
    assert not sobrou, f"sobrou lead: {[l['id'] for l in sobrou]}"
    print(f"  8. 0 leads com {TELEFONE}")

    print("\nOK: 8/8. RESÍDUO ZERO — nenhum box, nenhuma reunião, nenhum órfão.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
