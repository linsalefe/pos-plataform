# SPRINT_DISPARO_SEM_TETO_20260921_REPORT — o disparo não pula mais por teto de templates

**Merge `7338ba4` em `main`, backend reiniciado em 21/09 11:34 UTC (08:34 SP).** Branch
`disparo-sem-teto`, 2 commits (`605ad67`, `4377604`). 7 arquivos, +88/−86. Nenhuma
mensagem enviada a lead, nenhum UPDATE de dados, sem migração, `nat_config` intocado.

Decisão do Álefe (21/09): o processo comercial prevê até **9 follows por lead**; a regra
"3 templates ou mais nos últimos 7 dias" (S6-2, 02/09) bloqueava o time no meio da régua.
**Removida, não configurada** — sem `nat_config`, sem override. O risco da nota de
qualidade do número na Meta fica assumido pelo comercial.

## 1. Diff por critério de aceite

| # | critério | arquivo:linha | o que mudou |
|---|---|---|---|
| 1 | `por_que_pular` não devolve `teto` em nenhum modo | `higiene_disparo.py:108-153` | saíram `JANELA_TETO`, `TETO_TEMPLATES`, `MOTIVO_TETO`, `_quantos_templates` e o bloco `if aplicar_teto`. O parâmetro `aplicar_teto` foi embora com a regra: assinatura é `por_que_pular(wa_id, db, *, agora)`. Import `func` removido (só o `count` usava) |
| 2 | opt-out 30 dias intacto | `higiene_disparo.py:71-84, 96-105` | `PADRAO_RECUSA`, `JANELA_RECUSA`, `MOTIVO_RECUSA` e `_recusou` sem nenhuma mudança de conteúdo |
| 3 | `nat_ativa` intacta | `exact_routes.py:445-456` | não tocado |
| 4 | tela sem citar o teto | `automacoes/page.tsx:76-85, 955-957` | `teto` saiu de `REGRA_LABEL`; comentário "TRÊS motivos" → "DOIS". Regra desconhecida cai no fallback `?? regra`, sem quebrar |
| 5 | `disparo_skips` sem linha nova de `teto` | consequência de (1) | linhas antigas ficam — histórico |
| 6 | registro na docstring | `higiene_disparo.py:3-18` | bloco "O TETO DE 3 TEMPLATES / 7 DIAS FOI REMOVIDO EM 21/09/2026": o que a regra fazia, motivo, medição (44 pulos / 44 leads entre 02/09 e 17/09 — 43 no lote de 02/09 18h, 1 em 14/09), o que fica na tabela, e o primeiro sinal de que fez falta |
| 7 | teste invertido | `test_higiene_disparo.py` seções 2–4 | 3 e 9 templates → `None`; prova que a contagem nem roda (`len(chamadas) == 1`); `regra == 'teto'` nunca sobe; `aplicar_teto=False` → `TypeError`. **Não executado** |
| — | rótulo morto em mock | `test_disparo_skip.py:200-204` | o caminho agendado devolvia `"teto"` só como rótulo; agora `"recusa"` |
| — | comentários | `test_autoria_envio.py:145`, `test_bulk_pula_conversa_ativa.py:95` | "(recusa/teto)" → "(recusa)" |

Chamador: `exact_routes.py:429-436` — `por_que_pular(phone, db, agora=agora_sp())`, e o
comentário deixa de descrever a regra (b).

**Não tocado, de propósito:** `qualificacao_guard.MOTIVO_TETO` é OUTRO teto (envios/hora
do agente de qualificação), aparece em `test_risco3_abertura`, `test_lembrete_envio`,
`test_follow_20h`, `test_qualificacao`. Nada a ver com este.

## 2. Ferramentas

| passo | resultado |
|---|---|
| `py_compile app/higiene_disparo.py app/exact_routes.py` | ok (os dois arquivos de teste também compilam) |
| `npx tsc --noEmit` | ok |
| `npm run build` | ok, todas as rotas |
| `git merge --no-ff` + push | `7338ba4` |
| `systemctl restart cenat-backend` | `Application startup complete`, Uvicorn na 8001, 11:34:07 UTC |
| `systemctl restart cenat-frontend` | reiniciado em 11:38 UTC a pedido do Álefe (`✓ Ready in 749ms`), `/automacoes` 200 — bundle novo servido |

## 3. Regras que ainda pulam lead no disparo (`bulk_send_template`)

| # | regra | critério | individual | campanha / agendado |
|---|---|---|---|---|
| a | `recusa` | inbound nos últimos **30 dias** casando `PADRAO_RECUSA` (`higiene_disparo.py:72-84`) | pula | pula |
| c | `nat_ativa` | `nat_qualificacao_state.etapa ∈ ETAPAS_QUALIFICACAO_ATIVAS` nas duas grafias (`exact_routes.py:445-456`) | não roda | pula |

"Sem telefone" continua sendo erro (`failed`), não pulo — sem mudança. A tabela do
`RECON_NAT_FOLLOWUPS_20260917.md` §1.2 perde a linha (b).

## 4. O que a regra media, para quem revisitar

`disparo_skip` entre 02/09 18:37 (criação da tabela) e 17/09 (§1.3 do recon):

| regra | pulos | leads | dias |
|---|---|---|---|
| teto | 44 | 44 | 02/09 (43) · 14/09 (1) |
| nat_ativa | 35 | 27 | 02/09 (16) · 14/09 (9) · 16/09 (10) |
| recusa | 6 | 6 | 02/09 (5) · 16/09 (1) |

O lote de 02/09 18h (111 selecionados, 47 enviados, 64 pulados) foi o único em que o teto
pesou de verdade; depois disso, 1 pulo em 15 dias. Ou seja: a regra quase não estava
pegando em regime — o que ela custava era a incerteza do time sobre quem ia sair da lista.

## 5. Observação pra depois (não fazer agora)

Se a nota de qualidade do número cair na Meta, o primeiro sinal é o **limite diário de
conversas iniciadas** diminuindo. Vale olhar o Business Manager uma vez por semana no
primeiro mês. Os 4 `131049 — not delivered to maintain healthy ecosystem` da janela
24/08–01/09 (que motivaram a S6-2) são o número a comparar.
