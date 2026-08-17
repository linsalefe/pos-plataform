"""Agendamento de reunião pela landing page (obrigado.html) contra a Exact Spotter.

Mapa do módulo, na ordem em que uma requisição os atravessa:

    routes.py          endpoints públicos, rate limit por IP, validação de entrada
    disponibilidade.py grade menos ocupação — EXIBIÇÃO, não reserva
    agendar.py         o fluxo box -> lead -> schedule, com compensação
    client.py          HTTP contra a Exact, com os 400 dela traduzidos em exceções
    grade.py           quais horários existem. Configuração nossa, não da Exact
    horarios.py        fronteira de fuso. Único lugar que formata data para a Exact
    faxina.py          job que devolve à agenda os boxes que ficaram pendurados

As três premissas que sustentam o desenho, todas medidas na API real e registradas em
AGENDAMENTO_FINDINGS.md:

  1. `start`/`end` são HORA DE PAREDE com `Z` decorativo. Converter para UTC agenda 3h
     adiantado, em silêncio (§1).
  2. `scheduleAdd` só aceita box `status="available"`, e os blocos da agenda dos consultores
     são `busy` — a API os recusa. Por isso a grade é nossa e o módulo cria o próprio box (§8).
  3. `scheduleAdd` é irreversível: não existe `ScheduleRemove`. Remarcação sai pelo WhatsApp,
     por decisão de produto (§7.2).
"""
