# Diagnóstico dos envios de WhatsApp — 48h até 09/11/2026 20:36 SP

Somente leitura: SELECTs no banco, `journalctl -u cenat-backend` e `GET /health`. Nenhuma
escrita, nenhum envio, nenhum restart. Janela: `messages.timestamp` (SP naive) de 07/11 20:36
a 09/11 20:36. Telefones mascarados (últimos 4).

## Resumo

| | Estado |
|---|---|
| **O que está saindo** | 294 envios, quase todos na segunda 09/11 (fim de semana só régua de confirmação e agente). Tudo saindo pelos caminhos esperados. |
| **O que está falhando** | 50 falhas (17%): 27 × 131026 (número inexistente), 20 × 131049 (limite de frequência da Meta), 2 × 131047, 1 × 130472. Nenhum erro de template, de pagamento ou de conta (132xxx/131042). |
| **🔴 O que está preso** | **Espelho de reuniões parado desde 13:57 SP** (40 ciclos abortados, `/health` = 503 há 410 min). Causa: a Exact devolveu `exact_type='Reagendada'`, que a constraint não aceita. |
| **🟠 Webhook** | **178 respostas 500** no `/webhook` em 48h (659 nos 12 dias anteriores): `variantes_wa_id` não acha contato com wa_id de 11 dígitos começando por 55, e o INSERT bate na chave única. |
| Fila do agente | Nada atrasado. Scheduler rodando (último processado 19:51 SP). |
| Inbound | Webhook vivo: 56 recebidas, sem buraco em horário comercial. |

## 1. Envios por origem

Como cada origem é identificada: `nat_etapa` nula com `sent_by` = disparo manual do Hub;
nula sem `sent_by` = follow por estágio (bate 30 × 30 com `follow_estagio_envios.enviado`);
`qualif_conversa` = agente; `nat_a_*`/`confirm_*` = confirmação (Fluxo A); `nat_b_*` = Fluxo B;
`nat_ns_*` = no-show. `aviso_sdr`: zero na janela.

| Origem | Dia | Total | sent | delivered | read | failed |
|---|---|---:|---:|---:|---:|---:|
| Disparo manual do Hub (`bulk_send_template`, vagas afirmativas + 1 confirmação) | 09/11 | 113 | 1 | 63 | 24 | **25** |
| Humano, texto livre | 09/11 | 6 | 0 | 2 | 2 | 2 |
| Follow por estágio (job que chama `bulk_send_template`) | 09/11 | 30 | 2 | 15 | 6 | 7 |
| Agente (`qualif_conversa`) | 08 + 09/11 | 2 + 19 | 2 | 4 | 15 | 0 |
| Régua no-show | 09/11 | 3 | 0 | 0 | 3 | 0 |
| Régua Fluxo B | 09/11 | 64 | 2 | 25 | 21 | **16** |
| Régua confirmação (Fluxo A) | 07 / 08 / 09 | 4 / 28 / 25 | 4 | 28 | 25 | 0 |
| **Total** | | **294** | 11 | 137 | 96 | **50** |

Disparo do Hub: concentrado entre 18:36 e 18:39 SP (`follow1/2/3_vagasafirmativas_*`, 112 envios).

## 2. Falhas por código

| Código | Qtd | Significado | Onde |
|---|---:|---|---|
| **131026** Message undeliverable | 27 | Número sem WhatsApp, inválido ou com o app desatualizado. Não adianta tentar de novo. | 8 `nat_b_abertura` às 09:00, 19 no disparo do Hub às 18:36 |
| **131049** Healthy ecosystem engagement | 20 | A Meta segurou marketing para quem já recebeu marketing demais (de qualquer empresa) em pouco tempo. Pode passar depois, não é falha nossa de formato. | 7 de 8 `nat_b_reativ_4h` às 13:01, 7 no follow por estágio, 5 no Hub, 1 `reativ_30m` |
| **131047** Re-engagement message | 2 | Texto livre fora da janela de 24h (13:26 e 13:52, humano no Hub). Precisava ser template. | Hub |
| **130472** Number part of an experiment | 1 | A Meta excluiu o número de marketing por um experimento dela. | Hub, `follow2` |

Dois padrões que valem atenção (não são incidente, mas custam envio):

- **`nat_b_abertura` saiu duas vezes para o mesmo telefone.** Às 09:00 os números …0280, …1416
  e …0167 receberam 2 aberturas com 7 a 11 s de intervalo (ids 44689/44698, 44693/44700,
  44705/44706), todas 131026. Os três são **contatos de 11 dígitos** (número truncado); é
  provável que a mesma pessoa esteja em dois leads e a régua não tenha visto o primeiro envio.
  Não investiguei mais a fundo.
- **O disparo do Hub foi para números que já tinham falhado de manhã.** …0280, …1416, …8138 e
  …0167 deram 131026 às 09:00 e receberam `follow1_vagasafirmativas` às 18:39 (131026 de novo).
  …5186, …2207, …6487, …1992 deram 131049 no `reativ_4h` às 13:01 e foram atingidos de novo às
  18:37 (131049 de novo). O bulk não pula telefone com 131026 recente, e o 131049 não pula por
  regra já conhecida (só o 131050 é opt-out).

## 3. Entregue × lido por template

Lista: entrega (`delivered` + `read`) abaixo de 80% ou nenhum `read` em 48h.

| Template | n | Entregue | Lido | Motivo |
|---|---:|---:|---:|---|
| `nat_b_reativ_4h` | 8 | **13%** | 0% | 7 × 131049 no mesmo minuto (13:01) |
| `mensagens_flows2` | 7 | 43% | 14% | 3 × 131049 |
| `nat_b_abertura` | 24 | 63% | 38% | 8 × 131026 (5 números, 3 em dobro) |
| `mensagem_flow` | 7 | 71% | 29% | 2 × 131049 |
| `follow1_vagasafirmativas_apresentacao` | 74 | 73% | 22% | 20 falhas (131026 + 131049) |
| `follow3_vagasafirmativas_despedida` | 11 | 73% | 18% | 3 × 131026 |
| `f3_guiarapst3`, `f4_audiosmenfermagem` | 1 cada | 0% | 0% | 131049 |
| `nat_a_30min` | 2 | 50% | 0% | 1 ainda em `sent` |
| Sem leitura com entrega 100%: `mensagem_follow3` (3), `f4_audiotea`, `f4_audiogrupot2`, `f3_guiatea`, `f3_guiaenfermagemsm`, `confirmacaoreuniao_vick` (1 cada) | | | 0% | Amostra pequena e enviados à tarde; não é sinal |

Acima de 80%: `nat_a_confirmacao` 94%, `follow2_vagasafirmativas` 89%, `nat_a_ementa` 86%,
`nat_b_reativ_30m` 83%, `nat_a_beneficio` 80%, `nat_b_reativ_2h` e `mensagem_follow4` 100%.

## 4. Fila (`nat_scheduled_actions`)

- **Pendentes com `run_at` vencido: zero.** `run_at` é SP naive (`nat_scheduler.py`), comparado com
  `now() at time zone 'America/Sao_Paulo'`.
- Nenhum `falhou` em 72h. Último `processed_at`: 09/11 19:51 SP. Scheduler vivo.
- Até amanhã 12h: `confirm_a_beneficio` (1, 23:15 hoje), `confirm_a_pedido` (3, 08h),
  `iniciar_qualificacao` (2), `reativ_b_d1` (5), `confirm_a_ultimo_aviso` (2),
  `lembrete_reuniao` (1, 10:15), `noshow_d7`, `remarcacao_expira`, `confirm_a_corte` (1 cada).
- `follow_estagio_envios` pendentes: zero.

### Journal: ❌ e ⚠️ nas 48h (115 linhas)

| Qtd | Linha |
|---:|---|
| **40** | `❌ reuniao_sync: ciclo abortado, cursor NÃO avançou — CheckViolationError reuniao_status_exact_type_valido` |
| 48 | `❌ Meta recusou …` (as falhas da seção 2; 18 chegaram antes do commit e foram reaplicadas) |
| 16 | `⚠️ status órfão desistido` (10 delivered, 6 read): o status chegou e a linha não apareceu em 120 s; essas mensagens ficam em `sent` |
| 2 | `❌ Erro no sync Exact Spotter` |
| 4 | `⚠️ rd: conversão PULADA` (2 sem mapa `pos psicologia clinica aplicada`, 2 sem e-mail) |
| 2 | `⚠️ agendamento recusa: origem_nao_permitida` (`'Pos Saude Mental no Territorio'`) |

## 🔴 O espelho de reuniões está parado desde 13:57 SP

```
❌ reuniao_sync: ciclo abortado, cursor NÃO avançou — CheckViolationError:
   new row for relation "reuniao_status" violates check constraint "reuniao_status_exact_type_valido"
   meeting_id=4799364  lead_id=53622983  tel …1204  slot 09/11 14:15  origem=hub  exact_type='Reagendada'
```

- Constraint: `exact_type IN ('Vigente','Concluido','Cancelada')`. A Exact passou a devolver
  **`Reagendada`** para a reunião 4799364. No espelho ela está `Vigente`, atualizada pela última vez às 13:47.
- O upsert é um só para o ciclo: **uma linha derruba tudo** e o cursor não anda. Desde 13:57
  foram 40 ciclos abortados (a cada 10 min), o último às 20:28 SP. Vai continuar assim até alguém
  mexer, porque a Exact vai devolver a mesma reunião a cada ciclo.
- `/health` agora: **HTTP 503 `degradado` — "espelho de reuniões parado há 410 min"**. Ninguém
  foi avisado: o 503 está no ar há quase 7 horas.

Impacto (enquanto não destravar):

- Reunião **nova** marcada na Exact depois de 13:47 não entra no espelho, então não arma
  confirmação nem lembrete.
- Reunião **cancelada** na Exact depois de 13:47 não é vista, então o lembrete e a confirmação dela
  **continuam armados**. Há 19 `lembrete_reuniao` e 7 `confirm_a_pedido` pendentes; o
  primeiro dispara amanhã às 08h. Esse é o risco concreto: mandar lembrete de reunião cancelada.
- Desfecho: 6 reuniões `Vigente` com horário entre 13:47 e agora ficaram sem desfecho
  (Concluído / no-show). A régua de no-show de hoje à tarde não armou para elas.
- Os 20 `Vigente` futuros estão com status congelado.

O conserto é decisão de produto e não foi feito aqui: aceitar `Reagendada` na constraint (e decidir
como a régua trata: é a mesma coisa que `Cancelada` + nova reunião?) ou pular a linha
desconhecida com log, sem abortar o ciclo. Precisa entrar **antes das 08h de 10/11** para os
lembretes não saírem com o espelho congelado.

## 🟠 `/webhook` devolve 500 para wa_id de 11 dígitos

- **178 × HTTP 500** no `POST /webhook` em 48h; **659** nos 12 dias anteriores. É crônico, não é de hoje.
- Todos com a mesma exceção: `UniqueViolationError: duplicate key ... "ix_contacts_wa_id"` no
  autoflush de `main.py:877`.
- Causa: `telefone.variantes_wa_id("55219716514")` devolve `('5555219716514',)`. Um wa_id de **11
  dígitos que começa com 55** é lido como "sem DDI" e ganha outro 55. A busca nunca acha o contato
  que existe com a grafia crua, o webhook tenta criar de novo e bate na chave única.
- São 9 contatos, todos números truncados (8 com 11 dígitos e 1 de 13). A Meta reenvia o
  mesmo payload: só …4030 respondeu 72 vezes com 500.
- Efeito: o POST inteiro sofre rollback. Se a Meta mandar no mesmo POST o status ou a mensagem de
  outro contato, isso também se perde. Hoje esses 9 não têm nenhum inbound salvo.
- Ligação com a seção 2: os mesmos números truncados (…0280, …1416, …0167) são os que levaram
  abertura em dobro e 131026.

## 5. Webhook de status da Meta

O status não fica datado no banco (`messages.status` é sobrescrito), então usei o journal:
`POST /webhook` por hora, que inclui status e inbound. Horário comercial de segunda (08h–19h SP
= 11h–22h UTC): 34, 118, 59, 29, 7, 35, 38, 17, 22, 36, 305, 27. **Nenhuma hora vazia.** O
pico de 305 às 18h SP é o retorno do disparo de vagas afirmativas. No fim de semana há horas sem
POST, o que é esperado com envio quase zero. Fora os 500 acima, nenhum outro status de erro.

## 6. Inbound

- 48h: **56 recebidas** de 32 contatos. Mesma janela uma semana antes: 101 de 46.
- Segunda, 08h–19h SP: 40 contra 74 em 02/11. O pico das 09h–10h (15) e das 18h (13) segue os
  disparos das 09:00 e das 18:36.
- A queda não indica webhook morto: há inbound em toda hora com envio, os POSTs chegam e o volume
  acompanha o que saiu. Saíram 294 mensagens para 171 contatos agora, contra 224 para 58 na
  semana passada. É outro público: muito disparo frio, pouca conversa.

## 7. `/health` agora (23:38 UTC)

```json
{"status":"degradado","problemas":["espelho de reuniões parado há 410 min"],
 "pool":{"checkedout":0,"overflow":0,"capacidade":40,"uso":0.0,"teste":{"ok":true,"ms":9}},
 "ociosas":{"quantidade":0},
 "reuniao_sync":{"ligado":true,"ultimo_ciclo_em":"2026-11-09T13:47:19","idade_s":24645}}
```

Pool zerado, nenhuma transação ociosa. O único problema é o `reuniao_sync`.

## Pendências (nada aplicado)

1. **Urgente, antes das 08h de 10/11:** destravar o `reuniao_sync` para `Reagendada`.
2. Corrigir `variantes_wa_id` para wa_id de 11 dígitos com prefixo 55: incluir a grafia crua na busca.
3. Fazer o bulk pular telefone com 131026 recente.
4. Investigar a abertura do Fluxo B em dobro para o mesmo telefone (ids 44689/44698, 44693/44700, 44705/44706).
5. Alertar quando o `/health` ficar em 503 (hoje ninguém é avisado).

---

## Adendo 21:05 SP: "mensagens no relógio desde ~13h"

**Conclusão: o relógio não é status pendente. É `failed` desenhado como relógio.** Não é o
webhook nem lock, então os consertos 1 e 2 **não** foram aplicados (era a condição para aplicar).

1. **Não existe status `pending` no banco.** Desde 09/11 00h, os outbound são: 120 delivered,
   80 read, 50 failed, 11 sent. Todas as horas depois das 13h têm delivered e read (18h: 70
   delivered + 34 read de 132). O último delivered chegou pelos POSTs das 20:59 SP; o webhook
   continua respondendo 200.
2. **A Meta está mandando e nós estamos gravando.** `POST /webhook` com 200 todas as horas de
   09/11 (10h–23h UTC). Os 500 do `variantes_wa_id` já existiam de manhã, inclusive em proporção
   maior (11h UTC: 18 × 500 para 16 × 200) e não mudaram às 13h. O journal não separa
   `statuses` de `messages` por POST, então essa conta não dá para fazer. O painel de webhooks
   da Meta não foi consultado, porque não tenho acesso a ele daqui.
3. **Locks: nenhum.** `pg_stat_activity` mostra 20 conexões, todas `idle` e nenhuma em transação.
   `pg_locks` não tem nada em `messages` nem `contacts`. O `reuniao_sync` faz ROLLBACK a cada
   ciclo e não segura nada.
4. **Não há como perguntar à Meta o status de uma mensagem:** a Cloud API não tem
   `GET /{wamid}`, e o status só chega pelo webhook. Mesmo assim, as 3 mensagens das 18:3x no
   relógio que amostrei estão gravadas como `failed`, com código (131026 ×2, 131049 ×1).
5. **Por que o relógio:** `frontend/src/app/conversations/page.tsx:896` (`getStatusIcon`)
   mostra ✓ para `sent`, ✓✓ para `delivered` e `read`, e **relógio para qualquer outro valor,
   inclusive `failed`**. A falha aparece exatamente como "enviando…". Desde 13h são 41 `failed`
   (relógio) e 5 `sent` (✓ só). O "~13:00" bate com o lote `nat_b_reativ_4h` das 13:01: 7 de
   8 falharam com 131049.

**Essas mensagens foram entregues? Não.** Quem está no relógio levou recusa da Meta (131026
número inexistente, 131049 limite de frequência) e **não recebeu**. Mas o disparo das 18:3x não
falhou inteiro. Dos 113 do Hub: 63 delivered + 24 read = **87 chegaram (77%)**, 25 falharam e
1 está em `sent`.

Conserto sugerido (não aplicado, é frontend): ícone próprio para `failed` (⚠ vermelho com
`error_title` no tooltip). A API já devolve `status` (`routes.py:755`); falta incluir
`error_code`/`error_title` na resposta se o tooltip for usar o motivo.
