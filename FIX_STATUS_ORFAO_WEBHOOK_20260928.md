# FIX_STATUS_ORFAO_WEBHOOK_20260928: status da Meta que chega antes do commit

Branch `status-orfao-webhook`. Achado durante o §7 de `SPRINT_FOLLOW_POR_CURSO_20260928_REPORT.md`.

## O defeito

O webhook de status procura a `Message` pelo wamid. Quando não acha, joga o status fora.
Só que a mensagem **ainda não foi commitada** quando o status chega:

- `bulk_send_template` (`exact_routes.py`) faz **um commit no fim do lote**, com `sleep(1)` por
  lead. Num disparo de 300 leads, a 1ª mensagem só aparece no banco depois de ~5 min.
- `follow_estagio.drenar` segura a transação até terminar a nota na Exact (até 5 s).
- A Meta devolve `failed` em 1–2 s. No #45 do follow, o `failed` chegou às 21:23:51, **antes**
  do `enviado_em` (21:23:52).

Medido no journal de 21 a 28/09:

| | n |
|---|---|
| falhas logadas (`❌ Meta recusou`) | 154 |
| com `[mensagem não encontrada no banco]` | **130** |
| dessas, a linha existe hoje em `messages` | **130**, todas com status `sent` |
| `sent_by = 5` (disparo manual) / `NULL` (automação) | 124 / 6 |

Nenhuma delas é "mensagem que não é nossa": **as 130 são corrida.** `delivered` e `read` sofrem
o mesmo, mas se perdem sem log, então não há como contar.

## A correção (`backend/app/main.py`)

Do lado do webhook, não do envio. Dar commit a cada mensagem no bulk quebraria a atomicidade do
follow, que grava a mensagem e a linha do follow na mesma transação.

- Status `failed`/`delivered`/`read` cujo wamid não está no banco → `agendar_status_orfao`.
  Isso cria uma tarefa em segundo plano que tenta de novo após 5, 15, 60, 180, 600 e 1200 s
  (~35 min no total), cada tentativa com sessão própria.
- Achou a mensagem: aplica o status e o erro (`error_code/title/details`) **sem rebaixar**
  (`sent < delivered < read < failed`), roda `_realimentar_welcome_status` e dá commit.
- Não achou em 35 min: loga `status órfão desistido` e para.
- `sent` não agenda (é o que o envio já grava). O teto é de 5 000 tarefas simultâneas.
- O log do `failed` passa a dizer `[mensagem ainda não está no banco — reaplicação agendada]`.
  Quando aplica, sai `🔁 status órfão aplicado: <wamid> → failed (tentativa n, ...)`.

**Limite conhecido:** as tentativas ficam em memória. Um restart no meio perde as pendentes, e
essas voltam ao comportamento de antes (nada pior).

## Testes

`backend/test_status_orfao.py`, com banco falso e sem envio. **Executado: TUDO OK.** Cobre:

1. órfão que aparece na 3ª tentativa
2. status atrasado sem rebaixar
3. `sent` → `delivered`
4. desistência sem commit
5. erro de banco numa tentativa
6. realimentação da boas-vindas
7. o que não agenda, e o teto
8. `POST /webhook` ponta a ponta (agenda o órfão e carimba o presente)

Regressão: `test_welcome_guardrail`, `test_nat_config_api` e `test_agendamento_cors` OK.
`test_follow_estagio` tem **1 falha que já existia antes desta mudança**: a asserção "seis
chaves" não conhece o `motivo_agente` que `2722610` (27/09) pôs no payload. Não corrigida aqui.

## Não feito

- **Backfill das 130 linhas `sent`.** O journal tem wamid, código e detalhe de cada uma, então
  dá para corrigir. Fica para decisão, porque mexe em histórico.
- Os `delivered`/`read` perdidos antes do deploy não são recuperáveis (nunca foram logados).
