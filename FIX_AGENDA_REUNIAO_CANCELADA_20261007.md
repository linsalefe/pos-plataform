# Fix: horário de reunião cancelada na Exact volta para o site (07/10/2026)

Sprint 1 do `RECON_DEVOLUTIVA_ISA_20261007_REPORT.md` §5, sem checkpoint.

## Defeito

`disponibilidade._ocupados_por_nos` bloqueava o horário de toda linha de `agendamentos` com passo
`agendado`, e esse passo nunca muda. Quando a consultora cancela a reunião na Exact, o box some e
a Exact aceita reunião nova no horário, mas o site continuava sem oferecer.

## Mudança

`_ocupados_por_nos` ignora a linha cuja reunião no espelho (`reuniao_status.agendamento_id`) está
`Cancelada` ou tem `cancelado_motivo` preenchido.

Com `cancelado_motivo` preenchido (corte, remarcar, lead avisou, sem interesse), a reunião pode
seguir Vigente na Exact. Nesse caso quem segura o horário é o box dela, em `_ocupados_na_exact`,
até a consultora cancelar.

Agendamento sem linha no espelho continua bloqueando: é o caso "em voo", que é a razão de a
consulta existir.

## Antes e depois (`slots_livres(usar_cache=False)`)

| horário | agendamento | antes | depois |
|---|---|---|---|
| 07/10 14:30 | 959 (reunião 4773923 Cancelada) | só processoseletivo | **comercial e processoseletivo** |
| 08/10 13:45 | 945 (reunião 4773207 Cancelada) | só processoseletivo | só processoseletivo |

O 08/10 13:45 continua sem a comercial@ por outro motivo: ela tem um bloqueio manual na Exact das
13:30 às 14:30 (box 44103772, `busy`, sem lead). Esse bloqueio é legítimo e deve continuar.

## Teste

`backend/test_grade_cancelada.py`, escrito e não executado:

- confere o SQL compilado (`NOT EXISTS` sobre `reuniao_status`);
- em transação desfeita, testa 4 cenários: Vigente, Cancelada, Vigente cortada e sem espelho.
