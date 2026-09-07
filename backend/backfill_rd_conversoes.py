"""Enfileira no RD as submissões que aconteceram entre 18/08 e o deploy desta integração.

    cd /home/ubuntu/pos-plataform/backend
    venv/bin/python backfill_rd_conversoes.py              # dry-run (padrão): não escreve nada
    venv/bin/python backfill_rd_conversoes.py --executar    # grava as linhas em rd_conversoes

------------------------------------------------------------------------------------------
NÃO ENVIA NADA
------------------------------------------------------------------------------------------
Este script SÓ ENFILEIRA. Nenhuma chamada ao RD Station acontece aqui, nem com `--executar`.
Quem envia é `rd_sender`, e só quando `RD_ENVIO_ENABLED=true` no `.env`.

A separação é o ponto: rodar o backfill com o gate fechado põe algumas centenas de linhas em
`rd_conversoes` para serem OLHADAS — quantas `pendente`, quantas `skipped` e por qual motivo,
e se o `conversion_identifier` de cada curso é mesmo o que o fluxo correspondente escuta lá
dentro. Só depois disso a torneira abre. O caminho inverso não existe: conversão entregue ao
RD com o identifier errado dispara o fluxo errado, e não há como despachar de volta.

------------------------------------------------------------------------------------------
POR QUE 18/08
------------------------------------------------------------------------------------------
É o dia em que o formulário nativo substituiu o do RD na landing page. Antes disso o RD
recebia a conversão pelo próprio formulário, e reenfileirar aquele período criaria evento
duplicado para gente que o RD já conhece. Depois disso, ninguém.

------------------------------------------------------------------------------------------
IDEMPOTENTE POR CONSTRUÇÃO
------------------------------------------------------------------------------------------
`rd_outbox.enfileirar` faz `INSERT ... ON CONFLICT (chave, conversion_identifier) DO NOTHING`.
Rodar de novo devolve `duplicado` para tudo que já entrou e não reescreve linha nenhuma —
inclusive as que o fluxo normal já tiver enfileirado enquanto isto rodava.

É a mesma UNIQUE que resolve o fluxo de duas etapas da landing page: as duas linhas de
`agendamentos` da mesma submissão (`lead_criado` e `agendado`) viram UMA conversão. Por isso o
resumo final tem sempre muito `duplicado` — não é aviso, é o desenho funcionando.

------------------------------------------------------------------------------------------
LEADS DE TESTE FICAM DE FORA
------------------------------------------------------------------------------------------
Mesmo corte de `app/relatorios.py`, e pelo mesmo motivo: `zz`, `smoke`, `teste`, `john doe` e
os telefones do time não podem virar contato no RD nem acordar fluxo de e-mail. O predicado é
importado, não copiado — duas implementações sem teste de igualdade divergem, e o RECON de
01/09 mostrou o que custa (`^zz` sem âncora apaga 48 leads reais).

O corte é por CHAVE DE TELEFONE (`thread_sql`), não por nome, porque `agendamentos` não tem o
nome do lead na Exact — e a chave tolerante é o que junta as duas grafias do mesmo número.

------------------------------------------------------------------------------------------
COMMIT A CADA 50
------------------------------------------------------------------------------------------
Sessão própria, commit em lotes: o script não pode segurar uma transação longa contra a mesma
tabela que o fluxo de agendamento está escrevendo ao vivo. Interrompido no meio, o que já
commitou fica — e como é idempotente, rodar de novo continua de onde parou sem duplicar.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime

from sqlalchemy import select, text

from app.database import async_session
from app.models import Agendamento
from app.relatorios import chaves_de_teste, thread_sql
from app import rd_outbox

# O dia em que o formulário nativo substituiu o do RD Station na landing page.
CORTE = "2026-08-18"

# De quantas em quantas linhas commitar. Ver o cabeçalho.
LOTE = 50


async def _selecionar(db, teste: list[str]) -> list[Agendamento]:
    """Os agendamentos elegíveis, em ordem cronológica.

    ORDEM CRONOLÓGICA IMPORTA por causa do `ON CONFLICT DO NOTHING`: quem chega primeiro fica
    com a linha, e o `agendamento_id` gravado deve ser o do PRIMEIRO contato da pessoa (o
    `lead_criado` do formulário), não o do `agendado` que veio minutos depois. É a mesma
    convenção que o fluxo ao vivo produz naturalmente.
    """
    filtro = text(f"NOT ({thread_sql('agendamentos.telefone')} = ANY(:teste))")
    stmt = (select(Agendamento)
            .where(Agendamento.created_at >= datetime.fromisoformat(CORTE), filtro)
            .order_by(Agendamento.created_at, Agendamento.id))
    res = await db.execute(stmt, {"teste": teste})
    return list(res.scalars().all())


async def backfill(*, executar: bool) -> dict:
    resumo: Counter = Counter()
    motivos: Counter = Counter()

    async with async_session() as db:
        conj = await chaves_de_teste(db)
        print(f"Leads de teste: {len(conj.excluir)} chave(s) excluída(s), "
              f"{len(conj.duvidosos)} duvidoso(s).")
        linhas = await _selecionar(db, conj.array)
        print(f"Agendamentos desde {CORTE}, sem leads de teste: {len(linhas)}\n")

    if not executar:
        # DRY-RUN: reproduz a MESMA árvore de decisão de `rd_outbox.enfileirar`, sem tocar no
        # banco. Não pode divergir dela — se divergir, o dry-run mente sobre o que o
        # `--executar` faria, que é o único defeito capaz de tornar este modo pior que inútil.
        from app import rd_station
        for ag in linhas:
            identifier = rd_station.identifier_para(ag.sub_source)
            if identifier is None:
                resumo["skipped"] += 1
                motivos[rd_outbox.MOTIVO_SEM_MAPA] += 1
                continue
            email = rd_station.normalizar_email(ag.email)
            if email is None:
                resumo["skipped"] += 1
                motivos[rd_outbox.MOTIVO_EMAIL_INVALIDO if (ag.email or "").strip()
                        else rd_outbox.MOTIVO_SEM_EMAIL] += 1
                continue
            resumo["pendente"] += 1
        # O dry-run NÃO consegue prever `duplicado`: a UNIQUE é por (chave, identifier) e duas
        # linhas do mesmo par aparecem aqui como duas `pendente`. Por isso o aviso — o número
        # real de linhas gravadas será MENOR, e é isso que o `--executar` mostra.
        distintas = len({(rd_station.chave_de(rd_station.normalizar_email(a.email), a.telefone),
                          rd_station.identifier_para(a.sub_source)) for a in linhas})
        print(f"⚠️ DRY-RUN: nada foi gravado. As contagens abaixo são por AGENDAMENTO; "
              f"após deduplicar por (chave, identifier) sobram ~{distintas} linha(s).")
    else:
        pendentes_no_lote = 0
        async with async_session() as db:
            for i, ag in enumerate(linhas, 1):
                status = await rd_outbox.enfileirar(db, ag)
                resumo[status] += 1
                pendentes_no_lote += 1
                if pendentes_no_lote >= LOTE:
                    await db.commit()
                    pendentes_no_lote = 0
                    print(f"  … {i}/{len(linhas)} processados, commit do lote")
            await db.commit()

    print("\n" + "=" * 70)
    print("RESUMO" + ("  (DRY-RUN — nada gravado)" if not executar else ""))
    for chave in ("pendente", "skipped", rd_outbox.DUPLICADO, rd_outbox.ERRO):
        print(f"  {chave:<12} {resumo.get(chave, 0)}")
    if motivos:
        print("  motivos dos skipped:")
        for motivo, n in motivos.most_common():
            print(f"    {motivo:<16} {n}")
    print(f"  total lido   {len(linhas)}")
    print("=" * 70)
    print("NADA foi enviado ao RD Station. O envio é do rd_sender, e só com "
          "RD_ENVIO_ENABLED=true.")
    return dict(resumo)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    # `--executar` em vez de `--no-dry-run`: escrever é a exceção, e a flag que escreve tem de
    # ser digitada por inteiro e de propósito. Sem ela, o padrão é o modo que não muda nada.
    p.add_argument("--executar", action="store_true",
                   help="grava de verdade em rd_conversoes (padrão: dry-run)")
    args = p.parse_args()
    asyncio.run(backfill(executar=args.executar))
