#!/usr/bin/env python3
"""Backfill de `exact_leads.register_date` e `exact_leads.update_date` a partir da fonte.

    cd /home/ubuntu/pos-plataform/backend
    venv/bin/python backfill_register_date.py            # dry-run (padrão)
    venv/bin/python backfill_register_date.py --apply    # grava

POR QUE ESTE SCRIPT EXISTE
    `parse_datetime` rejeitava fração de segundo de tamanho diferente de 6 dígitos. A Exact
    devolve 4, 5, 6 e 7 — com 7 sendo ~90% dos casos. Resultado: as duas colunas de data
    ficaram NULL em 91% da base. A verificação 2 do `nat_guard` falha fechada quando
    `register_date` é NULL, então ligar a NAT hoje ignoraria 91% dos leads em silêncio.

    O parser já foi corrigido (`app/date_parse.py`), mas isso só vale para o que a Exact
    devolver DAQUI PRA FRENTE. Este script recupera o que já está no banco.

🔴 ISOLAMENTO — ESTE SCRIPT NÃO PODE ENVIAR MENSAGEM
    `sync_exact_leads` dispara boas-vindas para lead que ele considera novo. Reaproveitar
    aquele caminho, ou fazer um lead parecer novo, mandaria milhares de mensagens numa WABA
    que já está com a entrega degradada. As travas, em ordem de importância:

      1. NÃO importa `app.whatsapp` — nem direta, nem transitivamente. Por isso este script
         também NÃO importa `app.exact_spotter` (que carrega `send_template_message` no topo,
         linha 7) nem `app.models`. O único import de `app/` é `app.date_parse`, módulo neutro
         que só depende da stdlib. Sem o módulo importado, não existe função de envio no
         processo.
      2. NÃO chama `sync_exact_leads` nem `send_welcome_to_new_lead`. A paginação da API é
         reimplementada aqui (`_buscar_pagina`), espelhando `fetch_leads_from_exact`, em vez de
         importada — é o preço de manter a trava 1, e são 10 linhas de GET.
      3. Só faz UPDATE, nunca INSERT. Lead que existe na Exact mas não no banco é CONTADO e
         IGNORADO — criar linha aqui é justamente o que faria o sync tratá-lo como novo.
      4. Só escreve nas duas colunas de data. Nunca toca `welcome_status`, `welcome_sent_at`,
         `contacts`, `messages` nem `nat_*`.
      5. Só escreve onde o valor atual é NULL (garantido de novo no WHERE do UPDATE), então
         não sobrescreve dado bom nem corre com o sync que roda de 10 em 10 min.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.date_parse import parse_datetime  # noqa: E402  (único import de app/, só stdlib dentro)

BASE_URL = "https://api.exactspotter.com/v3"
TAMANHO_PAGINA = 500
PAUSA_ENTRE_PAGINAS = 0.5   # segundos, para não martelar a API da Exact
MAX_PAGINAS = 100           # trava de segurança contra paginação infinita

# As ÚNICAS colunas que este script escreve. Mapeia coluna do banco -> campo da API.
COLUNAS_DE_DATA = {
    "register_date": "registerDate",
    "update_date": "updateDate",
}

# Faixa de sanidade: data fora disto não é gravada, é reportada.
DATA_MINIMA = datetime(2020, 1, 1)


def _cabecalhos():
    return {
        "Content-Type": "application/json",
        "token_exact": os.getenv("EXACT_SPOTTER_TOKEN"),
    }


async def _buscar_pagina(cliente, skip, top):
    """Espelha `exact_spotter.fetch_leads_from_exact`. Reimplementado, não importado — ver trava 1."""
    resposta = await cliente.get(
        f"{BASE_URL}/Leads",
        headers=_cabecalhos(),
        params={"$top": top, "$skip": skip, "$orderby": "Id desc"},
    )
    resposta.raise_for_status()
    return resposta.json().get("value", [])


async def carregar_pendentes(engine):
    """exact_id -> conjunto de colunas de data que estão NULL no banco."""
    colunas = ", ".join(COLUNAS_DE_DATA)
    condicao = " OR ".join(f"{c} IS NULL" for c in COLUNAS_DE_DATA)
    async with engine.connect() as conn:
        linhas = await conn.execute(
            text(f"SELECT exact_id, {colunas} FROM exact_leads WHERE {condicao}")
        )
        pendentes = {}
        for linha in linhas.mappings():
            faltando = {c for c in COLUNAS_DE_DATA if linha[c] is None}
            if faltando:
                pendentes[linha["exact_id"]] = faltando
    return pendentes


async def gravar(engine, exact_id, valores):
    """UPDATE restrito: só colunas de data, só onde ainda está NULL.

    O `IS NULL` no WHERE é redundante com a checagem em memória — de propósito. O sync roda de
    10 em 10 min e pode ter preenchido a coluna entre a leitura e a escrita; assim nunca
    sobrescrevemos dado que chegou depois. Retorna quantas linhas foram de fato alteradas.
    """
    atribuicoes = ", ".join(f"{c} = :{c}" for c in valores)
    guarda = " AND ".join(f"{c} IS NULL" for c in valores)
    async with engine.begin() as conn:
        resultado = await conn.execute(
            text(f"UPDATE exact_leads SET {atribuicoes} WHERE exact_id = :exact_id AND {guarda}"),
            {**valores, "exact_id": exact_id},
        )
        return resultado.rowcount


async def executar(aplicar):
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

    url = os.getenv("DATABASE_URL")
    if not url:
        print("❌ DATABASE_URL não definida.")
        return 1
    if not os.getenv("EXACT_SPOTTER_TOKEN"):
        print("❌ EXACT_SPOTTER_TOKEN não definido.")
        return 1

    modo = "APLICANDO (grava no banco)" if aplicar else "DRY-RUN (não grava nada)"
    print(f"{'=' * 72}\nBackfill de datas do Exact — {modo}\n{'=' * 72}")

    engine = create_async_engine(url, echo=False)
    try:
        pendentes = await carregar_pendentes(engine)
        print(f"Leads com alguma data NULL no banco: {len(pendentes)}")
        if not pendentes:
            print("Nada a fazer.")
            return 0

        lidos = casados = atualizados = 0
        sem_data_na_fonte = 0
        fora_de_faixa = []
        amostra = []
        vistos = set()
        agora = datetime.utcnow()

        async with httpx.AsyncClient(timeout=60) as cliente:
            for pagina in range(MAX_PAGINAS):
                skip = pagina * TAMANHO_PAGINA
                leads = await _buscar_pagina(cliente, skip, TAMANHO_PAGINA)
                if not leads:
                    break
                lidos += len(leads)

                for lead in leads:
                    exact_id = lead.get("id")
                    if exact_id is None:
                        continue
                    vistos.add(exact_id)
                    faltando = pendentes.get(exact_id)
                    if not faltando:
                        continue

                    valores = {}
                    for coluna in faltando:
                        bruto = lead.get(COLUNAS_DE_DATA[coluna])
                        convertida = parse_datetime(bruto)
                        if convertida is None:
                            continue
                        if convertida < DATA_MINIMA or convertida > agora:
                            fora_de_faixa.append((exact_id, coluna, bruto, convertida))
                            continue
                        valores[coluna] = convertida

                    if not valores:
                        sem_data_na_fonte += 1
                        continue

                    casados += 1
                    if len(amostra) < 10:
                        amostra.append((exact_id, {
                            c: (lead.get(COLUNAS_DE_DATA[c]), v) for c, v in valores.items()
                        }))
                    if aplicar:
                        atualizados += await gravar(engine, exact_id, valores)
                    else:
                        atualizados += 1

                print(f"  página {pagina + 1:>3} (skip={skip:>5}): "
                      f"{len(leads):>3} lidos | acumulado casados={casados} atualizados={atualizados}")

                if len(leads) < TAMANHO_PAGINA:
                    break
                await asyncio.sleep(PAUSA_ENTRE_PAGINAS)

        nao_encontrados = [i for i in pendentes if i not in vistos]

        print(f"\n{'-' * 72}\nAmostra (id | coluna | valor bruto da API -> valor que seria gravado)")
        for exact_id, campos in amostra:
            for coluna, (bruto, convertida) in campos.items():
                print(f"  {exact_id:>10} | {coluna:<14} | NULL -> {bruto}  ->  {convertida}")

        print(f"\n{'=' * 72}\nRESUMO — {modo}")
        print(f"  lidos da fonte ................. {lidos}")
        print(f"  pendentes no banco ............. {len(pendentes)}")
        print(f"  casados (têm data na fonte) .... {casados}")
        print(f"  {'ATUALIZADOS' if aplicar else 'seriam atualizados'} ................. {atualizados}")
        print(f"  na fonte, mas sem data usável .. {sem_data_na_fonte}")
        print(f"  não encontrados na fonte ....... {len(nao_encontrados)}")
        print(f"  fora da faixa de sanidade ...... {len(fora_de_faixa)}")

        if fora_de_faixa:
            print(f"\n🔴 {len(fora_de_faixa)} data(s) fora da faixa "
                  f"(anterior a {DATA_MINIMA:%Y-%m-%d} ou futura). NENHUMA foi gravada:")
            for exact_id, coluna, bruto, convertida in fora_de_faixa[:20]:
                print(f"     {exact_id} | {coluna} | {bruto} -> {convertida}")
            if aplicar:
                print("   Interrompendo: revisar antes de continuar.")
                return 2

        if nao_encontrados:
            print(f"\n  {len(nao_encontrados)} lead(s) do banco não apareceram na fonte "
                  f"(provável exclusão na Exact). Nada foi feito com eles. "
                  f"Primeiros: {nao_encontrados[:10]}")

        if not aplicar:
            print("\nNada foi gravado. Para aplicar: --apply")
        print("=" * 72)
        return 0
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Recupera register_date/update_date de exact_leads a partir da API do Exact. "
                    "NUNCA envia mensagem, nunca cria lead, nunca toca welcome_status.")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--dry-run", action="store_true",
                       help="conta e mostra o que faria, sem escrever (padrão)")
    grupo.add_argument("--apply", action="store_true",
                       help="grava de fato as datas no banco")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(executar(aplicar=args.apply)))


if __name__ == "__main__":
    main()
