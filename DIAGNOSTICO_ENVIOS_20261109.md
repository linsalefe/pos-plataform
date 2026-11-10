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

---

## Adendo 10/11: investigação do 131049 (somente leitura)

Fontes: banco (SELECT), `GET /{waba_id}/message_templates` e `GET /{phone_number_id}` na Graph
API v22.0. A categoria vem da Meta, não da tabela `whatsapp_templates`. "Marketing recebido" =
template MARKETING com status sent/delivered/read (sem as falhas). O telefone é casado pelos
**últimos 8 dígitos**, porque o mesmo humano aparece com 12 e 13 dígitos. Na primeira conta,
por `contact_wa_id`, o …5186 das 18:37 saía com 0, embora tivesse recebido 3 de manhã sob a
outra grafia.

### Conclusão

**O 131049 de ontem é frequência nossa: o próprio Fluxo B estoura o limite.** O lote `abertura
→ reativ_30m → reativ_2h` deixa a pessoa com 3 marketing em 4h, e o quarto (`reativ_4h`, ou o
follow ou o Hub que vier depois) é barrado. Nos 30 dias, com 3 marketing nas 24h anteriores o
131049 vai a **71%**; com 0 a 2, fica entre 5% e 8%. O número está **GREEN**, então não é
qualidade. Também não é tendência: a taxa está estável perto de 10% desde 07/10. Mas o teto só
resolve cerca de 28% do 131049 total: mais da metade (193 de 361) acontece com **zero** marketing
nosso antes. É frequência de outras empresas ou critério de engajamento da Meta, que não
controlamos.

### 1. Os 20 com 131049 em 09/11

| Tel | Hora | Template que falhou | Mkt 24h antes | Mkt 7d antes | Origem dos de 24h |
|---|---|---|---:|---:|---|
| …8721 | 09:31 | nat_b_reativ_30m | 1 | 2 | abertura B |
| …1593 | 13:01 | nat_b_reativ_4h | 3 | 3 | abertura B + reativações |
| …5186 | 13:01 | nat_b_reativ_4h | 3 | 4 | abertura B + reativações |
| …0369 | 13:01 | nat_b_reativ_4h | 3 | 5 | abertura B + reativações |
| …2207 | 13:01 | nat_b_reativ_4h | 3 | 4 | abertura B + reativações |
| …2420 | 13:01 | nat_b_reativ_4h | 3 | 3 | abertura B + reativações |
| …1992 | 13:01 | nat_b_reativ_4h | 3 | 3 | abertura B + reativações |
| …6487 | 13:01 | nat_b_reativ_4h | 3 | 3 | abertura B + reativações |
| …2420 | 13:39 | mensagem_flow (follow est.) | 3 | 3 | abertura B + reativações |
| …0369 | 15:57 | mensagens_flows2 (follow est.) | 3 | 5 | abertura B + reativações |
| …6910 | 16:08 | mensagens_flows2 (follow est.) | 0 | 3 | — |
| …2420 | 16:40 | mensagens_flows2 (follow est.) | 3 | 3 | abertura B + reativações |
| …7176 | 17:02 | f3_guiarapst3 (follow est.) | 0 | 1 | — |
| …7916 | 18:27 | f4_audiosmenfermagem (follow est.) | 0 | 2 | — |
| …6640 | 18:37 | follow1_vagasafirmativas (Hub) | 0 | 1 | — |
| …5186 | 18:37 | follow1_vagasafirmativas (Hub) | 3 | 4 | abertura B + reativações |
| …2207 | 18:38 | follow1_vagasafirmativas (Hub) | 3 | 4 | abertura B + reativações |
| …6487 | 18:39 | follow1_vagasafirmativas (Hub) | 3 | 3 | abertura B + reativações |
| …1992 | 18:39 | follow1_vagasafirmativas (Hub) | 3 | 3 | abertura B + reativações |
| …5616 | 19:51 | mensagem_flow (follow est.) | 3 | 3 | abertura B + reativações |

Confirmação, no-show e agente não aparecem como origem em nenhum caso. Os mesmos 9 telefones do
Fluxo B das 09:00 respondem por 15 das 20 falhas: depois do `reativ_4h` barrado, o follow por
estágio e o Hub tentaram de novo no mesmo dia e falharam de novo.

### 2. Comparação com os entregues do disparo das 18h

O disparo de vagas afirmativas das 18:30–18:45 teve **86** delivered/read. O "70" é o total de
delivered da hora 18h somando todas as origens.

| Grupo | n | Mkt 24h (média / mediana) | Mkt 7d (média / mediana) | 0 nas 24h | ≥ 2 nas 24h | ≥ 3 nos 7d |
|---|---:|---|---|---:|---:|---:|
| 131049 em 09/11 | 20 | 2,30 / 3 | 3,10 / 3 | 4 | **15** | 16 |
| Entregues do Hub 18h | 86 | 0,05 / 0 | 0,84 / 0 | 83 | **1** | 8 |

Distribuição de marketing nas 24h antes: o grupo 131049 tem **15 com 3** e o dos entregues tem
**nenhum com 3**. **Sim, a diferença é o número de marketing recebidos antes.**

Nos 30 dias (07/10–09/11, todos os envios MARKETING):

| Mkt nas 24h antes | Envios | 131049 | Taxa |
|---:|---:|---:|---:|
| 0 | 2.336 | 193 | 8,3% |
| 1 | 874 | 54 | 6,2% |
| 2 | 306 | 14 | 4,6% |
| **3** | **140** | **100** | **71,4%** |
| 4+ | 10 | 0 | 0% (quem passou do 3º) |

### 3. Categoria dos templates na Meta

**124 de 133 templates são MARKETING; 9 são UTILITY.** Entre os usados desde 07/10, os únicos
UTILITY são `nat_a_30min`, `nat_a_pedido_confirmacao` e `nat_a_ultimo_aviso`.

| Template | Categoria | Observação |
|---|---|---|
| `nat_a_confirmacao` | **MARKETING** | `previous_category=UTILITY`: a Meta reclassificou |
| `nat_abertura_agendado` | **MARKETING** | reclassificado de UTILITY |
| `follow_up` | **MARKETING** | reclassificado de UTILITY |
| `sdr_agradecimento` | **MARKETING** | reclassificado de UTILITY |
| `nat_a_beneficio`, `nat_a_ementa` | MARKETING | conteúdo, correto |
| `nat_b_abertura`, `nat_b_reativ_30m/2h/4h/d1` | MARKETING | prospecção, correto |
| `nat_ns_d0_1h`, `nat_ns_d0_8h`, `nat_ns_d0_corte`, `nat_ns_d2_audio` | MARKETING | |
| `confirmacaoreuniao_vick` | MARKETING | |
| follow por estágio (`mensagem_flow*`, `mensagem_follow*`, `f3_*`, `f4_*`) e vagas afirmativas | MARKETING | |
| `nat_a_30min`, `nat_a_pedido_confirmacao`, `nat_a_ultimo_aviso` | UTILITY | |

Nenhum template tem `quality_score` (todos `UNKNOWN`).

### 4. 131049 por dia desde 07/10

| Semana | Mkt enviados (dias úteis) | 131049 | Taxa |
|---|---:|---:|---:|
| 07–11/10 | 466 | 39 | 8,4% |
| 12–16/10 | 627 | 70 | 11,2% |
| 19–23/10 | 740 | 83 | 11,2% |
| 26–31/10 | 1.017 | 93 | 9,1% |
| 02–07/11 | 558 | 56 | 10,0% |
| 09/11 | 208 | 20 | 9,6% |

**Não está crescendo.** O que mudou foi a origem. Até 30/10 o 131049 vinha quase todo do follow
e do Hub (o Fluxo B dava 0 a 2 por dia). Desde 02/11 o Fluxo B passou a gerar uma parte grande:
14 de 14 em 02/11, 9 de 16 em 03/11, 8 de 20 em 09/11. Fim de semana: zero.

### 5. Qualidade do número

`GET /978293125363835?fields=quality_rating,messaging_limit_tier,...` devolve
`quality_rating=GREEN`, `throughput.level=STANDARD`, `status=CONNECTED`, `name_status=APPROVED`.
`messaging_limit_tier` não veio na resposta da v22.0. **Qualidade não é a causa.**

### 6. Proposta (nada aplicado)

**(a) Ressubmeter como UTILITY.** É preciso criar um template novo, com outro nome: a Meta não
devolve a categoria de um aprovado e reclassifica de novo se o texto for promocional. A regra
dela: UTILITY é sobre uma transação ou pedido **que a pessoa já fez**, sem oferta.

| Atual | Por que caiu em MARKETING | Nova versão UTILITY |
|---|---|---|
| `nat_a_confirmacao` | "você garante a isenção da taxa de matrícula e um e-book exclusivo" | Tirar a frase. Fica só data, hora, consultora e duração. A isenção pode ir no `nat_a_beneficio`, que já é marketing. |
| `confirmacaoreuniao_vick` | Mesma frase da isenção + e-book | Mesmo corte. Ou aposentar e usar a confirmação nova. |
| `nat_abertura_agendado` | "Que bom te ver ✨" + pergunta de qualificação | Separar: um UTILITY só com "sua reunião com X está confirmada para D às H" e a pergunta da formação como texto livre, já dentro da janela se a pessoa responder. |
| `nat_ns_d0_1h` | "a agenda está apertada e restam poucas vagas" | "Sua reunião de hoje às H não aconteceu. Quer escolher outro horário?" sem escassez. |
| Lembrete T-30 (`nat_a_30min`) | Já é UTILITY | Manter. |
| Fluxo B, follow, Hub | Prospecção e conteúdo | **Não ressubmeter.** Se a Meta reclassificar, é pior. |

Efeito esperado: a confirmação e o lembrete deixam de contar para o limite de marketing. Ontem
isso não pesou nos 20 casos (nenhum veio de confirmação), mas protege quem tem reunião marcada,
que é quem mais importa.

**(b) Teto de marketing por pessoa.** Recomendação: **no máximo 3 MARKETING em 24h por humano**
(chave por `variantes_wa_id` / últimos 8 dígitos, não por `contact_wa_id`), somando todas as
origens: Fluxo B, follow por estágio, Hub manual, no-show e confirmação marketing.

- Por que 3: é onde está o salto. O 4º falha 71% das vezes. Nos 30 dias o teto teria pulado 140
  envios, dos quais 100 iam falhar de qualquer jeito, e preservado os 40 que passaram (dá para
  aceitar a perda ou subir para 4 se o comercial preferir).
- Como: quem envia consulta antes. A régua (`nat_scheduled_actions`) grava `skipped` com
  `motivo='teto_marketing_24h'`, o follow por estágio grava `skipped` com o mesmo motivo, e o bulk
  do Hub mostra na prévia "N contatos pulados pelo teto" e pula. Não reagendar automaticamente: o
  degrau seguinte da régua segue normal.
- Efeito direto no Fluxo B: `abertura + 30m + 2h` já são 3, então o `reativ_4h` passa a ser
  pulado sempre que os três anteriores entraram. Vale decidir se o `reativ_4h` continua existindo
  ou se vira D+1.
- Custo do teto: ele só ataca cerca de 28% do 131049. Os 53% sem marketing nosso antes não mudam.
- Junto: **pular 131026 recente** no bulk e no follow (seção 2 do primeiro relatório). Não é
  131049, mas é o mesmo desperdício.

**(c) Frontend.**
- `getStatusIcon` (`conversations/page.tsx:896`): caso próprio para `failed`, com ícone de
  alerta vermelho e tooltip com `error_title` e código ("131049 · limite de frequência da Meta").
  A API (`routes.py:755`) precisa passar a devolver `error_code` e `error_title`, que já estão na
  tabela.
- Filtro "Falhou" na lista de conversas: contatos cuja última outbound está `failed`, com o
  código como etiqueta. Hoje esses contatos não se distinguem de "mensagem a caminho".
- Traduzir os 4 códigos mais comuns para texto de gente: 131026 "número sem WhatsApp", 131049
  "a Meta segurou por excesso de marketing", 131047 "fora da janela de 24h, use template",
  130472 "número em teste da Meta".
