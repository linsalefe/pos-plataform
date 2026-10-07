# Case: métricas antes/depois da IA de confirmação

Script: `backend/case_metrics.py`. Faz só leitura: apenas SELECT, sem commit e sem chamada à
Meta ou à Exact.

```bash
cd backend && venv/bin/python case_metrics.py                          # 07/10 até hoje
cd backend && venv/bin/python case_metrics.py --de 2026-10-07 --ate 2026-11-06
```

Período em datas de SP, com as duas pontas inclusive. Os leads de teste ficam fora de todas as
contas, pela mesma regra da página /relatorios (`relatorios.chaves_de_teste`).

## O "antes"

O "antes" são as constantes no topo do script, copiadas do
`RECON_CONFIRMACAO_NOSHOW_20261007_REPORT.md` §2 (07/09 a 06/10, 30 dias, sem teste). Onde não
existia régua, o valor é 0 ou "não existia". Como o antes tem 30 dias, compare **taxas**, não
números absolutos.

| Métrica | Antes |
|---|---|
| Reuniões passadas, todas | 230: Concluido 71 (31%), Cancelada 147, Vigente 12 |
| Reuniões passadas, marcadas pelo Hub | 153: Concluido 26 (17%), Cancelada 115, Vigente 12 |
| Confirmação de presença | não existia |
| Corte e régua de no-show | não existia |
| Fluxo B | 293 aplicaram, 121 agendaram em 10 min, 172 sem agendar, 161 nunca tiveram reunião, 19 reuniões do agente |
| Mensagens automáticas pós-agendamento | só o T-30: 122 (4,1/dia) |
| Reuniões da SDR na Exact | 64 de 249, nenhuma recebia confirmação |

## Definições do "depois"

1. **Confirmação:** reuniões cuja `confirm_a_imediata` foi executada no período. O denominador
   da taxa exclui quem teve a primeira mensagem recusada pela Meta (131026, 130472), porque essa
   pessoa nunca viu o pedido.
2. **Comparecimento:** reuniões com horário no período que já passaram, agrupadas pelo `type` na
   Exact, separando quem tem régua e confirmou de quem tem régua e não confirmou. `Concluido` é
   o único sinal de que a reunião aconteceu.
3. **Cortes e recuperados:** `cancelado_motivo='sem_confirmacao'`, contados por dia. Um
   recuperado é uma régua de no-show encerrada por um destes motivos:
   - clique (payload `NS_*`);
   - texto (`humano`);
   - reunião nova (`reagendou`).
4. **Fluxo B:** estados marcados `fluxo=b` criados no período. "Agendou pelo agente" significa
   `concluido` com `agendamento_id`. As remarcações pelos botões aparecem em linhas separadas.
5. **Mensagens:** outbound por `nat_etapa`, agrupadas por régua, com as falhas da Meta.
6. **SDR na Exact:** `reuniao_status.origem='exact'` com horário no período, e quantas receberam
   a confirmação imediata.

## Primeira leitura (07/10 09h53, 3h30 depois da liberação)

- 9 réguas armadas. 3 tiveram a primeira mensagem recusada pela Meta: 2 com 131026 (telefones
  falsos) e 1 com 130472.
- 2 das 6 entregues já confirmaram por botão (33%).
- 1 reunião da SDR na Exact recebeu a confirmação e confirmou.
- Ainda sem cortes, sem no-show e sem Fluxo B no período. Os números úteis começam com alguns
  dias de dados.
