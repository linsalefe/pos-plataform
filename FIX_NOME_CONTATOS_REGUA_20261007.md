# Fix: nome do lead no contato criado pela régua (07/10/2026)

## Defeito

As réguas (confirmação, no-show, Fluxo B e o lembrete T-30) criam o `Contact` quando a pessoa
nunca falou com o Hub (`qualificacao_fluxo._contato_ou_criar`). O nome vinha só do lead
(`exact_leads.name` ou `agendamentos.nome`). Para reunião marcada pela SDR na Exact, de lead que
ainda não estava nessas tabelas, o contato nascia sem nome, e o card mostrava só o telefone.

## Mudança

- `_contato_ou_criar(..., nome=...)`: o nome que o chamador já tem. Ele tem precedência quando o
  contato nasce ou já existe sem nome; sem ele, vale o nome do lead, como antes.
- Os chamadores da régua passam `reuniao_status.nome`:
  - `confirmacao._wa_id` (confirmação e no-show);
  - `confirmacao.lembrete_por_espelho` (T-30 novo);
  - `qualificacao_fluxo.lembrete_reuniao` (T-30 antigo, `agendamentos.nome`);
  - `reabrir_para_oferta` (remarcar pelo botão).
- A abertura do Fluxo B continua com o nome do lead.

## Backfill

`backend/backfill_nome_contatos_regua.py`. Pega os contatos com nome vazio cuja chave de telefone
casa com `reuniao_status`. O nome vem da reunião mais recente com nome; se ela não tiver, do lead
dela na Exact.

```
dry-run:  contatos sem nome com reunião no espelho e nome disponível: 162
--apply:  atualizados: 162
contatos sem nome no total: 4911 -> 4749
```
