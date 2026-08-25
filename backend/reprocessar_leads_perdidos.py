"""Os leads que o agente perdeu entre a ativação e o conserto — de volta para a fila.

    venv/bin/python reprocessar_leads_perdidos.py              # LISTA (não escreve nada)
    venv/bin/python reprocessar_leads_perdidos.py --executar   # enfileira de verdade

------------------------------------------------------------------------------------------
QUEM SÃO ESTES LEADS
------------------------------------------------------------------------------------------
`welcome_status IS NULL` + `register_date >= qualificacao_start_at`. Os dois pedaços
importam:

  * `welcome_status IS NULL` é a marca de quem NUNCA teve a abertura decidida. Todo caminho
    de saída de `send_welcome_to_new_lead` carimba — inclusive as recusas. NULL só sobra para
    quem foi interrompido no meio, e em 25/08 isso aconteceu de duas formas:
      - caminho LP: a ação era inserida, ANUNCIADA no log com id e desfeita no rollback
        (`_gatilho_do_agente` não commitava);
      - caminho sync: `UnboundLocalError` no passo 4.5 abortava o laço inteiro no PRIMEIRO
        lead, e todos os outros já entram como `existing` na passada seguinte.
    Os dois estão corrigidos. O que estes leads têm de especial é que eles NÃO VOLTAM
    sozinhos: já são `existing` no sync, e nunca mais entram em `new_leads_to_contact`.

  * `>= qualificacao_start_at` porque a admissão (`qualificacao_pode_iniciar`) recusa quem é
    anterior ao corte. Enfileirar lead de antes da ativação seria produzir `skipped` em
    massa — barulho, e nenhum atendimento.

------------------------------------------------------------------------------------------
POR QUE ESPAÇADO NO TEMPO, E NÃO TUDO PARA AGORA
------------------------------------------------------------------------------------------
O teto do agente é `nat_config.max_envios_hora` (20/h). Jogar 40 aberturas com o mesmo
`run_at` faria as 20 primeiras saírem e as outras baterem no teto — hoje isso não perde mais
o lead (elas voltam a `pendente` a cada 10 min, ver AcaoAdiada), mas produz uma fila
batendo na parede e disputa a janela com os leads ORGÂNICOS do dia, que são os que têm
pressa.

Por padrão este script usa METADE do teto, deixando a outra metade livre para quem chegar
agora. Fora do horário comercial o próprio handler empurra para o próximo dia útil — não é
preciso tratar isso aqui.

A grade também PULA o que está fora do horário comercial. O handler já empurraria sozinho
(AcaoAdiada → próximo dia útil), mas então todo o resto da fila cairia junto às 09h do dia
seguinte, no mesmo minuto — a concentração que o espaçamento existe para evitar. Espalhar
dentro da janela e mostrar a grade real é o que torna "controlado" verdadeiro.

------------------------------------------------------------------------------------------
O QUE ELE CARIMBA, E POR QUÊ ISSO É O PONTO
------------------------------------------------------------------------------------------
`welcome_status = 'skipped'` com motivo explícito de reprocessamento. Sem o carimbo o lead
continuaria elegível a este mesmo script amanhã, e receberia a abertura duas vezes. O
carimbo É a trava de idempotência — é a mesma que o passo 3 do `send_welcome_to_new_lead`
consulta.

IDEMPOTENTE por consequência: rodar duas vezes seguidas não reenfileira ninguém, porque na
segunda passada nenhum deles casa mais `welcome_status IS NULL`.
"""
import argparse
import asyncio
import subprocess
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.database import async_session
from app.models import ExactLead, NatConfig, ORIGEM_EXACT
from app.nat_guard import _agora_sp, dentro_horario_comercial, proximo_horario_util
from app.qualificacao_gatilho import agendar_abertura, wa_id_de

SERVICO = "cenat-backend.service"

# ------------------------------------------------------------------------------------------
# TRIAGEM MANUAL — 25/08/2026. Quem NÃO recebe a abertura do agente, e por quê.
# ------------------------------------------------------------------------------------------
# Cruzamento dos 41 candidatos contra `messages` das últimas 48h. A distinção que decidiu a
# lista foi entre DISPARO EM MASSA e CONVERSA:
#
#   às 15:18–15:19 saíram 43 templates para 43 contatos distintos em dois minutos ("Ola X, é
#   o <curso> do CENAT ✨ Tentei realizar uma nova tentativa de contato"). Isso é campanha, e
#   35 dos 41 leads têm SÓ isso. Tratar esse template como "lead já em atendimento" esvaziaria
#   a lista por um motivo falso — o lead recebeu um disparo, ninguém falou com ele.
#
# Sai quem tem conversa DE VERDADE: texto individual digitado por SDR, dois ou mais inbound,
# ou template individual (fora dos minutos de massa). Ficam inclusive os leads cujo único
# "inbound" é autorresposta do próprio celular deles ("não estou disponível no momento") —
# isso não é resposta.
EXCLUIDOS: dict[int, str] = {
    51532753: "Vera Rosa — inbound próprio + template individual às 14:45, SDR já atuando",
    51537537: "Isabela Guarino — 2 inbound dela, incluindo pergunta sobre 2ª pós",
    51542856: "Bruna Rosa — já passou pela NAT velha em 24/08 e clicou 'Prefiro outro horário'",
    51542913: "Michelle Bittencourt — 4 inbound e 4 respostas digitadas pelo SDR às 15:21",
    51543599: "Cibelle Ferrari — negociando ('Boa tarde, só amanhã, hoje tá corrido'), fica com o SDR",
    51543658: "Andréa Corrêa — negociando ('ainda estou resolvendo com a equipe'), fica com o SDR",
    51543683: "Escola Municipal Profª Amélia Guimarães — instituição, não pessoa; tratamento manual do SDR",
}

# Fração do teto por hora que este backfill pode ocupar. A outra metade fica para os leads
# orgânicos, que são os que têm pressa.
FRACAO_DO_TETO = 0.5

# A primeira abertura não sai no mesmo segundo em que o script roda: dá margem para conferir
# a fila antes de a primeira vencer.
ATRASO_INICIAL = timedelta(minutes=2)


def codigo_no_ar_esta_atualizado() -> tuple[bool, str]:
    """O serviço subiu DEPOIS da última mudança no código? (ok, explicação).

    Isto não é zelo: enfileirar contra o binário antigo é o pior desfecho possível. O
    handler velho descarta por "não existe em contacts" — que é exatamente o bug — e marca
    `executado`. Os leads seriam consumidos de novo, agora com o carimbo `skipped` posto por
    este script, e ficariam DEFINITIVAMENTE fora dos dois caminhos.
    """
    try:
        saida = subprocess.run(
            ["systemctl", "show", SERVICO, "-p", "ExecMainStartTimestampMonotonic"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        subiu_mono = int(saida.split("=", 1)[1])
        if subiu_mono == 0:
            return False, f"{SERVICO} não está rodando"
        agora_mono = float(Path("/proc/uptime").read_text().split()[0]) * 1_000_000
        segundos_no_ar = (agora_mono - subiu_mono) / 1_000_000
    except Exception as e:
        return False, f"não deu para ler o start do serviço ({type(e).__name__}: {e})"

    app = Path(__file__).parent / "app"
    mais_novo = max(p.stat().st_mtime for p in app.rglob("*.py"))
    idade_do_codigo = time.time() - mais_novo

    # O serviço precisa ter subido DEPOIS da última edição, ou seja: fazer MENOS tempo que
    # ele está no ar do que faz que o código mudou. Invertido, este teste aprova exatamente
    # o caso que ele existe para barrar — processo velho com código novo no disco.
    if segundos_no_ar < idade_do_codigo:
        return True, (f"serviço no ar há {segundos_no_ar/60:.0f} min; última edição em "
                      f"app/ há {idade_do_codigo/60:.0f} min — o binário é o novo")
    return False, (f"o serviço subiu há {segundos_no_ar/60:.0f} min e há código alterado há "
                   f"{idade_do_codigo/60:.0f} min — o processo no ar é ANTERIOR ao conserto")


def _grade(inicio, passo, quantos: list | int) -> list:
    """`quantos` horários espaçados de `passo`, TODOS dentro do horário comercial.

    Sem isto a grade atravessaria as 18h30 e o handler empurraria cada retardatário para as
    09h do dia seguinte — todos para o MESMO minuto, refazendo exatamente a concentração que
    o espaçamento evita. `proximo_horario_util` é o mesmo usado pelo handler, para não
    existirem duas definições de "quando dá para falar com alguém".
    """
    horarios, quando = [], proximo_horario_util(inicio)
    for _ in range(quantos):
        horarios.append(quando)
        quando = quando + passo
        if not dentro_horario_comercial(quando):
            quando = proximo_horario_util(quando)
    return horarios


async def perdidos(db):
    """Leads sem decisão de abertura, posteriores ao corte. Em ordem de chegada."""
    cfg = (await db.execute(select(NatConfig).where(NatConfig.id == 1))).scalar_one_or_none()
    if cfg is None or cfg.qualificacao_start_at is None:
        raise SystemExit("❌ nat_config sem qualificacao_start_at — sem corte, sem backfill.")
    res = await db.execute(
        select(ExactLead)
        .where(ExactLead.welcome_status.is_(None),
               ExactLead.register_date >= cfg.qualificacao_start_at)
        .order_by(ExactLead.register_date))
    return cfg, list(res.scalars())


async def main(executar: bool, por_hora: int | None):
    async with async_session() as db:
        cfg, leads = await perdidos(db)
        teto = cfg.max_envios_hora or 20
        ritmo = por_hora or max(1, int(teto * FRACAO_DO_TETO))
        passo = timedelta(minutes=60 / ritmo)

        print(f"\ncorte de admissão : {cfg.qualificacao_start_at} (UTC)")
        print(f"teto do agente    : {teto}/h  →  este backfill usa {ritmo}/h "
              f"(1 a cada {passo.total_seconds()/60:.0f} min)")
        print(f"leads perdidos    : {len(leads)}   "
              f"({len(EXCLUIDOS)} excluídos na triagem manual)\n")

        # Um humano pode ter duas linhas (formulário preenchido duas vezes). `agendar` já
        # cancela o pendente anterior do mesmo (kind, contato), mas contar aqui evita
        # prometer 41 aberturas quando serão 40.
        vistos, fila = set(), []
        for lead in leads:
            wa = wa_id_de(lead.phone1 or "")
            if lead.exact_id in EXCLUIDOS:
                # O telefone entra em `vistos` JUNTO: excluir é decisão sobre a PESSOA, não
                # sobre a linha. Quem preencheu o formulário duas vezes tem duas linhas com
                # exact_id diferente e o mesmo número — sem isto, a segunda escapa da
                # exclusão e a pessoa recebe a abertura da qual acabou de ser tirada.
                # Aconteceu com a Bruna Rosa (51542856 excluída, 51542892 entrou).
                vistos.add(wa)
                print(f"  ⛔ {lead.exact_id} {(lead.name or '')[:34]:<34} "
                      f"{EXCLUIDOS[lead.exact_id]}")
                continue
            if wa and wa in vistos:
                print(f"  ↩️  {lead.exact_id} {(lead.name or '')[:34]:<34} duplicata de {wa}")
                continue
            vistos.add(wa)
            fila.append(lead)
        print()

        grade = _grade(_agora_sp() + ATRASO_INICIAL, passo, len(fila))
        for i, lead in enumerate(fila):
            print(f"  {i+1:>3}. {lead.exact_id}  {(lead.name or '')[:34]:<34} "
                  f"{lead.phone1:<14} {grade[i]:%d/%m %H:%M}")

        if not executar:
            print(f"\n(simulação — nada foi escrito). {len(fila)} lead(s) seriam "
                  f"enfileirados.\nRode com --executar para valer.")
            return

        ok, explicacao = codigo_no_ar_esta_atualizado()
        if not ok:
            raise SystemExit(
                f"\n❌ NÃO vou enfileirar: {explicacao}.\n"
                f"   O handler antigo descarta por 'não existe em contacts' e marca a ação "
                f"como executado —\n   os leads seriam consumidos e perdidos de novo, agora "
                f"carimbados.\n   Rode `sudo systemctl restart {SERVICO}` primeiro.")
        print(f"\n✅ código no ar conferido: {explicacao}")

        enfileirados = 0
        for i, lead in enumerate(fila):
            # `agendar_abertura` põe a ação em agora+5min; sobrescrevemos o run_at logo
            # depois para espalhar. Reusar a função (em vez de montar a linha à mão) é o que
            # mantém UMA definição de payload, de referência UTC e de "já tem estado".
            ok_lead, motivo = await agendar_abertura(
                db, telefone=lead.phone1 or "", lead_id=lead.exact_id, origem=ORIGEM_EXACT,
                nascido_em=(lead.register_date - timedelta(hours=3))
                if lead.register_date else None)
            if not ok_lead:
                lead.welcome_status = "skipped"
                lead.welcome_error = f"backfill 25/08: não enfileirado ({motivo})"
                print(f"  ⏭️  {lead.exact_id} {(lead.name or '')[:30]:<30} {motivo}")
                continue

            from app.models import NatScheduledAction
            from sqlalchemy import update as _update
            await db.execute(
                _update(NatScheduledAction)
                .where(NatScheduledAction.contact_wa_id == wa_id_de(lead.phone1 or ""),
                       NatScheduledAction.kind == "iniciar_qualificacao",
                       NatScheduledAction.status == "pendente")
                .values(run_at=grade[i]))
            lead.welcome_status = "skipped"
            lead.welcome_error = "backfill 25/08: abertura do agente reenfileirada"
            enfileirados += 1

        await db.commit()
        print(f"\n✅ {enfileirados} abertura(s) enfileirada(s) e COMMITADAS, "
              f"de {grade[0]:%d/%m %H:%M} a {grade[-1]:%d/%m %H:%M}.")
        print("   Confira com:  SELECT run_at, contact_wa_id, status, motivo "
              "FROM nat_scheduled_actions WHERE status='pendente' ORDER BY run_at;")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--executar", action="store_true",
                    help="escreve de verdade (o padrão é simular)")
    ap.add_argument("--por-hora", type=int, default=None,
                    help="quantas aberturas por hora (padrão: metade do teto do agente)")
    a = ap.parse_args()
    asyncio.run(main(a.executar, a.por_hora))
