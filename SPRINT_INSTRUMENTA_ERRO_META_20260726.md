# Sprint NAT — Instrumentação do erro de entrega da Meta

**Data:** 26/07/2026
**Branch:** `feat/instrumenta-erro-meta-20260726` (commit `257f4a0`, sem merge)
**Antecedentes:** `SPRINT_NAT_BLOCOS_0_1_20260726.md`, `SPRINT_NAT_BLOCOS_2_3_4_20260726.md`

Objetivo: persistir o código de erro da Meta, subir, e ler a causa real das falhas de entrega.

---

## 1. Migração

`backend/migrate_message_error.py` **rodada**. Três colunas nullable em `messages`:

```sql
SET lock_timeout = '3s';
ALTER TABLE messages ADD COLUMN IF NOT EXISTS error_code INTEGER;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS error_title TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS error_details TEXT;
```

Primeira migração da série que faz `ALTER` em tabela **quente** (26.766 linhas, escrita a cada
mensagem recebida). Duas coisas tornaram isso seguro:

1. `ADD COLUMN` nullable e **sem default** é operação de catálogo no PostgreSQL 14 — não
   reescreve a tabela nem varre as 26 mil linhas.
2. O `lock_timeout` pesa mais aqui do que nas migrações anteriores. O `ALTER` precisa de
   `ACCESS EXCLUSIVE`, ainda que por um instante, e o `sync_exact_leads` mantém transação
   longa. Sem o timeout, o `ALTER` esperaria o sync **segurando a fila de quem vem depois** — e
   o webhook, que só quer inserir mensagem, ficaria atrás dele.

**Ordem obrigatória: migração antes do restart.** O modelo `Message` passou a declarar as três
colunas, e o SQLAlchemy as inclui em todo `SELECT` sobre `messages`. Subir o código antes do
`ALTER` quebraria toda consulta a mensagens em produção — webhook, conversa e painel.

---

## 2. Persistência do erro

`_erro_do_status()` no topo de `main.py` extrai `errors[0]`, e o loop de `statuses` grava os
três campos e loga.

O parse é defensivo de propósito: `errors` pode não existir, vir vazio, vir como não-lista, ter
item não-dict, ou vir sem `error_data`. Nada ali levanta exceção — um campo inesperado da Meta
não pode derrubar o lote de status e travar a atualização de **todas** as outras mensagens do
mesmo webhook. Verificado contra 8 formatos, incluindo `code` como string e `error_data` como
string; os malformados devolvem `{}`.

O log sai mesmo quando a mensagem não está no banco: o motivo da recusa é informação, ainda que
não haja linha para carimbar.

---

## 3. Consultas diretas à Meta (read-only)

| consulta | resposta |
|---|---|
| Número | `quality_rating: GREEN` · `status: CONNECTED` · `throughput: STANDARD` · `name_status: APPROVED` · `code_verification_status: EXPIRED` |
| WABA | `status: ACTIVE` · `account_review_status: APPROVED` · `business_verification_status: verified` |
| Limite de marketing | **não exposto** — `messaging_limit_tier` volta vazio; `marketing_messages_lite_api_status` e `max_daily_conversation_per_phone` não existem nesta versão da API |
| Templates | os 6 `nat_*` são **MARKETING**, todos `APPROVED`, `rejected_reason: NONE`, `quality_score: UNKNOWN` |

**Nada aqui explica a falha — e isso é informação.** Descarta número banido, WABA suspensa,
template reprovado e queda de qualidade. A hipótese de limite de marketing por usuário **não
foi confirmada nem derrubada**, porque a Meta não expõe esse contador por API. Só o código de
erro decide.

O `code_verification_status: EXPIRED` chama atenção mas é sobre verificação do nome de exibição,
não sobre envio — com `name_status: APPROVED` e `CONNECTED`, não é candidato a causa.

---

## 4. O que subiu no restart

**A premissa do briefing estava desatualizada.** O serviço já havia sido reiniciado às
**01:14 UTC de hoje**, na sprint anterior:

| grupo | estado |
|---|---|
| `9692952` (login no resend-welcome) | **já estava no ar desde 01:14** — não era mais pendente |
| Blocos 0-1 (captura de clique) | **já estavam no ar desde 01:14**, ~40 min sem traceback |
| Blocos 2-3-4 (`17dcee5`) | **subiram agora** |
| Esta sprint | subiu agora |

Pontos de contato dos Blocos 2-3-4 com caminho quente: `main.py` chama
`processar_clique`/`processar_texto` dentro de `begin_nested`; fim de
`send_welcome_to_new_lead` chama `iniciar_fluxo_nat`, também em `begin_nested`; e
`send_template_message` ganhou um parâmetro opcional, com não-regressão coberta por teste.

Detalhe operacional que vale registrar: **o deploy é "o que estiver checked out"**, não o
`main`. O restart publicou a branch desta sprint, que é a única forma de subir sem merge.

`nat_config` confirmado antes e depois: `nat_enabled=false`, `nat_start_at=NULL`.

---

## 5. Smokes após o restart (01:56:56 UTC)

| # | smoke | resultado |
|---|---|---|
| 1 | Serviço subiu | `Application startup complete`, sem traceback |
| 2 | Leitura de mensagem inbound | `GET /api/contacts/{wa_id}/messages` → 200 com histórico real |
| 3 | Notificação ao SDR | rota viva (401 sem token); 2.801 notificações legíveis via ORM |
| 4 | Envio manual por atendente | rota viva (`POST /api/send/text` → 422 de validação). **Nenhuma mensagem real enviada** — a regra da sprint proíbe, então o caminho foi exercitado sem entregar nada a lead |
| 5 | Sync do Exact | `✅ Sync Exact Spotter agendado`, ciclo rodou às 01:57:53 e às 02:06:59 sem erro |
| 6 | Tabelas da NAT | `nat_flow_state` e `nat_button_events` seguem em **0 linhas** |
| 7 | Painel de boas-vindas | `GET /api/auto-welcome/config` → 200, config intacta |

O smoke mais relevante era o 2: é ele que prova que o `ALTER` na tabela quente não quebrou a
leitura de mensagens. Passou lendo uma conversa real, com `error_code: None` nas linhas antigas.

Curiosidade encontrada nessa leitura: a conversa mostra uma mensagem `type: "button"` de 16/07
com `content: ""` — o bug dos 102 cliques perdidos, agora corrigido para os próximos.

---

## 6. Leitura do erro real — **pendente, e não por falta de instrumentação**

A instrumentação está no ar e funcionando. O que falta é **um envio para observar**, e aqui a
premissa do briefing também mudou:

> "Sync do Exact roda a cada 10 min e envia ~20 boas-vindas/dia. **Há envio real acontecendo**,
> então basta observar."

**Não há mais.** O volume de leads novos despencou:

```
leads por register_date:   19/07: 3   21/07: 5   22/07: 3   23/07: 3   24/07: 4   25/07: 1
último welcome_sent_at:    2026-07-25 13:52 (SP)  — ~9h antes desta sprint
outbound desde o restart:  NENHUM
```

Sem lead novo em funil de pós, `send_welcome_to_new_lead` não é chamado e nada é enviado. Não
há como forçar sem violar a regra de não enviar mensagem manualmente.

Um monitor read-only ficou observando a primeira mensagem com `error_code` preenchido.

### Achado lateral que vale investigar depois

As falhas de `template` por dia não batem com o número de leads novos:

```
23/07: 43 falhas de template  (mas só 3 leads novos naquele dia)
24/07: 33 falhas de template  (4 leads)
25/07:  9 falhas de template  (1 lead)
```

Boas-vindas não explica esse volume. Há **outra fonte de disparo de template** no mesmo período
— provavelmente o envio em massa da tela de Automações. Isso importa para o diagnóstico: se o
que estourou algum limite foi uma campanha em massa, a boas-vindas pode estar sendo vítima e
não causa. Fica registrado, fora do escopo desta sprint.

Também vale notar que em 20-23/07 houve falhas de `audio`, `document`, `image` e `text` — ou
seja, **nem todas as falhas do período são de template de marketing**, o que enfraquece um pouco
a hipótese de que o problema seja exclusivamente da categoria MARKETING.

---

## 7. Estado de produção

| item | estado |
|---|---|
| Mensagem enviada a lead real | **nenhuma** |
| Serviço | reiniciado 26/07 01:56:56 UTC, autorizado |
| Sync do Exact rodado manualmente | não — só os ciclos automáticos |
| NAT | **desligada** (`nat_enabled=false`, `nat_start_at=NULL`) |
| `nat_flow_state` / `nat_button_events` | 0 linhas |
| `auto_welcome_config` | **não alterada** |
| Merge | **não feito** |

---

## 8. Fora de escopo (confirmado, não tocado)

- Corrigir a causa (reclassificar template, mudar categoria, ajustar volume).
- Realimentar `exact_leads.welcome_status` com o `failed` que chega depois — é por isso que o
  painel mostra 253 sucessos enquanto dezenas não chegaram a ninguém.
- Extração dos 99 leads que clicaram e não foram atendidos.
- Qualquer coisa do fluxo NAT (Blocos 5 em diante).
