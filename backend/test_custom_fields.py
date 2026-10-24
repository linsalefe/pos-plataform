"""Graduação e faixa de investimento vão para os campos personalizados da Exact (24/10/2026).

    cd backend && venv/bin/python test_custom_fields.py

Escrito e NÃO executado na sprint de 24/10. Offline: o HTTP da Exact é mockado.

O QUE ESTE TESTE PROVA
  1. `Ensino Superior` Sim/Não casa com `_possuigraduacao` pelo id da opção
  2. `Faixa de investimento` casa pelo texto normalizado (caixa, acento, espaço)
  3. valor desconhecido é descartado com log, o resto segue
  4. chave ausente (ou extras vazios) -> lista vazia, e o `LeadsAdd` não leva `customFields`
  5. 4xx com `customFields` -> repete sem eles e loga `❌ custom_fields`
  6. rede/5xx com `customFields` NÃO repete (pode ter gravado)
  7. `description` não muda com os campos
  8. custom_fields.json de produção tem os 2 campos com os ids medidos
"""
import asyncio
import io
import json
import os
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

from app.agendamento import client, extras

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def _resp(valor=53204414):
    r = MagicMock()
    r.json.return_value = {"value": valor}
    return r


GRAD_SIM = {"id": "_possuigraduacao", "options": [{"id": 136999}]}
GRAD_NAO = {"id": "_possuigraduacao", "options": [{"id": 137000}]}
FAIXA_2 = {"id": "_investimentoposgraduacaoonline", "options": [{"id": 137003}]}


def caso_1_graduacao():
    extras.recarregar_custom_fields()
    checa("Sim", extras.montar_custom_fields({"Ensino Superior": "Sim"}), [GRAD_SIM])
    checa("Não", extras.montar_custom_fields({"Ensino Superior": "Não"}), [GRAD_NAO])
    checa("nao sem acento", extras.montar_custom_fields({"ensino superior": " nao "}), [GRAD_NAO])


def caso_2_faixa():
    checa("faixa normalizada",
          extras.montar_custom_fields({"Faixa de investimento": "de r$100,00  a R$200,00"}),
          [FAIXA_2])
    checa("os dois juntos, na ordem do formulário",
          extras.montar_custom_fields({"Ensino Superior": "Sim",
                                       "Faixa de investimento": "De R$100,00 a R$200,00",
                                       "Profissão": "Psicóloga"}),
          [GRAD_SIM, FAIXA_2])


def caso_3_desconhecido():
    saida = io.StringIO()
    with redirect_stdout(saida):
        r = extras.montar_custom_fields({"Ensino Superior": "Talvez", "Faixa de investimento":
                                         "De R$100,00 a R$200,00"})
    checa("desconhecido sai, o resto fica", r, [FAIXA_2])
    checa("log do descarte", "não casa com nenhuma opção" in saida.getvalue(), True)


async def caso_4_sem_campos():
    checa("sem chave", extras.montar_custom_fields({"Profissão": "x"}), [])
    checa("extras None", extras.montar_custom_fields(None), [])
    req = AsyncMock(return_value=_resp())
    with patch.object(client, "_req", req):
        await client.criar_lead(nome="zz", telefone="11999998888", source="Landing Page",
                                sub_source="PosMulheridades", funnel_id=18535,
                                description="d", custom_fields=[])
    corpo = req.await_args.kwargs["json"]
    checa("uma chamada", req.await_count, 1)
    checa("sem customFields no payload", "customFields" in corpo["lead"], False)


async def caso_5_4xx_repete():
    chamadas = []

    async def falso(metodo, caminho, **kw):
        chamadas.append(kw["json"])
        if "customFields" in kw["json"]["lead"]:
            raise client.ExactErro("Custom field '_possuigraduacao': Option(s) 1 not found")
        return _resp(777)

    saida = io.StringIO()
    with patch.object(client, "_req", falso), redirect_stdout(saida):
        lid = await client.criar_lead(nome="zz", telefone="11999998888", source="Landing Page",
                                      sub_source="PosMulheridades", funnel_id=18535,
                                      description="d", custom_fields=[GRAD_SIM])
    checa("lead criado na 2ª", lid, 777)
    checa("duas chamadas", len(chamadas), 2)
    checa("1ª com campos", chamadas[0]["lead"]["customFields"], [GRAD_SIM])
    checa("2ª sem campos", "customFields" in chamadas[1]["lead"], False)
    checa("log ❌ custom_fields", "❌ custom_fields" in saida.getvalue(), True)


async def caso_6_rede_nao_repete():
    req = AsyncMock(side_effect=client.ExactIndisponivel("timeout"))
    with patch.object(client, "_req", req):
        try:
            await client.criar_lead(nome="zz", telefone="11999998888", source="Landing Page",
                                    sub_source="PosMulheridades", funnel_id=18535,
                                    custom_fields=[GRAD_SIM])
            levantou = False
        except client.ExactIndisponivel:
            levantou = True
    checa("rede levanta", levantou, True)
    checa("sem repetição", req.await_count, 1)


async def caso_7_description_igual():
    ex = {"Ensino Superior": "Sim", "Faixa de investimento": "De R$100,00 a R$200,00"}
    desc = extras.montar_descricao("a@b.com", ex)
    checa("description de sempre", desc,
          "E-mail: a@b.com | Ensino Superior: Sim | Faixa de investimento: De R$100,00 a R$200,00")
    req = AsyncMock(return_value=_resp())
    with patch.object(client, "_req", req):
        await client.criar_lead(nome="zz", telefone="11999998888", source="Landing Page",
                                sub_source="PosMulheridades", funnel_id=18535, description=desc,
                                custom_fields=extras.montar_custom_fields(ex))
    lead = req.await_args.kwargs["json"]["lead"]
    checa("description no payload", lead["description"], desc)
    checa("campos no payload", lead["customFields"], [GRAD_SIM, FAIXA_2])


def caso_8_config_producao():
    caminho = os.path.join(os.path.dirname(__file__), "custom_fields.json")
    with open(caminho, encoding="utf-8") as fh:
        cfg = json.load(fh)
    checa("dois campos", sorted(cfg), ["Ensino Superior", "Faixa de investimento"])
    checa("ids de graduação", cfg["Ensino Superior"]["opcoes"], {"Sim": 136999, "Não": 137000})
    checa("ids das faixas", sorted(cfg["Faixa de investimento"]["opcoes"].values()),
          [137002, 137003, 137004, 137005])


async def main():
    print("\nCampos personalizados da Exact: HTTP mockado\n")
    os.environ.pop("AGENDAMENTO_CUSTOM_FIELDS_PATH", None)
    caso_1_graduacao()
    caso_2_faixa()
    caso_3_desconhecido()
    await caso_4_sem_campos()
    await caso_5_4xx_repete()
    await caso_6_rede_nao_repete()
    await caso_7_description_igual()
    caso_8_config_producao()
    if falhas:
        print(f"\nFALHOU: {falhas}\n")
        raise SystemExit(1)
    print("\nOK: todos os casos passaram.\n")


if __name__ == "__main__":
    asyncio.run(main())
