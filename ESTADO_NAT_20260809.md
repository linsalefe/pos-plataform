# Estado do projeto NAT — 09/08/2026

Levantamento de estado verificado no código em execução e no banco. Onde os docs de sprint
contradizem o código, vale o código — as contradições estão listadas na seção 6.

Nada foi alterado para produzir este documento: só leitura de `information_schema`, das tabelas
e da Graph API (GET).

---

## 1. O que está em produção agora

### Commit em execução

| | |
|---|---|
| HEAD de `main` | `2d41c14` (09/08 19:41) |
| Processo backend | PID 1414645, iniciado 09/08 19:34:18 |
| Árvore de trabalho | limpa |
| Arquivos em `backend/app/` modificados após o start | **nenhum** |

O commit `2d41c14` (19:41) tocou só frontend. O backend em execução corresponde ao código de `main`.

### Módulos NAT em `backend/app/`

| Arquivo | Função |
|---|---|
| `nat_guard.py` | Trava central — 5 verificações, falha fechada. Também define horário comercial, `GESTOR_USER_ID=2`, `SDR_IDS_PERMITIDOS={4,5}`, `FUNIL_NAT=18535` |
| `nat_copy.py` | Texto verbatim dos 4 templates + payloads e títulos de botão. Sem banco, sem rede |
| `nat_buttons.py` | Extrai clique de botão do payload do webhook (`button` e `interactive`) |
| `nat_sender.py` | Envio unificado: decide template vs. texto livre pela janela de 24h; grava `messages.nat_etapa` |
| `nat_flow.py` | Máquina de estados: `iniciar_fluxo_nat`, `processar_clique`, `processar_texto`, `transferir_para_sdr` |
| `nat_scheduler.py` | Fila genérica `nat_scheduled_actions` — `agendar`/`cancelar`, execução com lock e retentativa |
| `nat_sla.py` | Handler do `sla_check`: escada 0→1→2 (SDR dono → outro SDR → gestão) |
| `nat_routes.py` | `GET /api/nat/{wa_id}/estado` e `POST /api/nat/{wa_id}/assumir` |
| `delivery_health.py` | Vigia de entrega (não é NAT, mas observa todo template que sai) |

### Jobs no lifespan (`main.py:244-272`) — 6 tarefas

| Job | Intervalo |
|---|---|
| `sync_job` (Exact) | 600 s |
| `cleanup_recordings_job` | 86 400 s |
| `window_alerts_job` | 300 s |
| `scheduled_messages_job` | 60 s |
| `nat_scheduler_job` | 60 s |
| `delivery_health_job` | 900 s |

### Migrações aplicadas

Conferido no `information_schema` e em `pg_indexes`, não nos arquivos `migrate_*`:

- `nat_config` (5 col) · `nat_flow_state` (14 col, inclui `assumido_por`, `assumido_em`,
  `escalonamento_nivel`) · `nat_button_events` (8 col) · `nat_scheduled_actions` (9 col)
- `messages.nat_etapa` (text) + índice parcial `idx_messages_nat_etapa_ts` — existe
- `exact_leads`: `welcome_sent_at`, `welcome_status`, `welcome_error`, `welcome_wamid` — todas existem
- Índices únicos: `nat_flow_state.contact_wa_id`, `nat_button_events.wa_message_id`,
  `uq_nat_sched_pendente_por_contato (kind, contact_wa_id) WHERE status='pendente'`

Tudo que os sprints 0-1, 2-3-4 e 5-7 previram no banco está aplicado.

---

## 2. Estado operacional

**`nat_config`** (id=1, atualizado 25/07 21:49)

```
nat_enabled = false     nat_start_at = NULL     max_envios_hora = 20
```

**`auto_welcome_config`** (id=1, atualizado **28/07 12:15 por Valéria**)

```
enabled = TRUE     template = nat_boasvindas / pt_BR     channel_id = 1
funnel_ids = 18535,18537,25588
```

### Contagens

| Tabela | Linhas |
|---|---|
| `nat_flow_state` | **0** |
| `nat_button_events` | **82** (75 contatos distintos, 29/07 → 09/08) |
| `nat_scheduled_actions` | **0** |
| `messages` com `nat_etapa` | **0** |
| `messages` total | 29 820 |

Os 82 cliques são todos `source='template'`: 46 "Sim, Posso conversar agora" e 36 "Prefiro outro
horário". O `button_payload` é **idêntico ao `button_text`** — vieram da boas-vindas, que é
enviada sem `button_payloads`.

### `welcome_status` agregado (8 908 leads)

| Status | Leads | Com `welcome_wamid` |
|---|---|---|
| `skipped` | 8 451 | 0 |
| `sent` | 190 | 4 |
| `delivered` | 146 | 146 |
| `failed` | 118 | 50 |
| NULL | 3 | 0 |

### Últimas mensagens

- Outbound: 09/08 **12:36:54** — template `nat_boasvindas` para 5547999351501, `nat_etapa=NULL`
- Inbound: 09/08 **16:00:35** — texto de 5521973622690

A boas-vindas está viva e entregando: 09/08 → 2 `delivered`, 08/08 → 8 `delivered` + 1 `failed`,
07/08 → 9 `delivered`.

---

## 3. O fluxo NAT, ponta a ponta

| Etapa | Entrada | Saída |
|---|---|---|
| `aguardando_horario` | ✅ `nat_flow.py:336` — lead fora de 09h-19h ou fim de semana | ❌ **não existe**. Nenhum handler registrado, nenhum job varre. `MODULOS_DE_HANDLERS` só tem `app.nat_sla` (`nat_scheduler.py:94`). Lead entra e fica |
| `aguardando_resposta` | ✅ `nat_flow.py:355` após `nat_boasvindas` sair | ✅ `processar_clique` (`nat_flow.py:427-430`) para os dois payloads |
| `aguardando_motivacao` | ✅ clique `NAT_SIM` | ✅ **qualquer** texto (`nat_flow.py:475`) → envia `nat_confirma_transferencia`, transfere, agenda SLA |
| `aguardando_ligacao` | ✅ `nat_flow.py:488` | ⚠️ **parcial**. `POST /assumir` grava `assumido_por` e cancela o SLA, mas **não muda a etapa**. `sla_check` escalona 0→1→2 e para. Nenhum caminho leva a `encerrado` — o lead morre aqui |
| `reagendado` | ✅ clique `NAT_OUTRO_HORARIO` | ❌ **não existe**. `processar_texto:467-473` grava `horario_preferencial` e devolve a mesma etapa. Nada reagenda envio, nada lê o campo |
| `sem_contato` | ❌ constante declarada em `models.py:359`, **nunca atribuída** | ❌ nenhuma |
| `encerrado` | ❌ constante declarada em `models.py:360`, **nunca atribuída** | ❌ nenhuma |

Ponto de entrada do fluxo: `exact_spotter.py:321-324`, dentro de `send_welcome_to_new_lead`,
**depois** do envio da boas-vindas.

Roteamento do webhook: `main.py:432-441` (`processar_clique` / `processar_texto`), em savepoint,
depois de gravar a `Message` e o `NatButtonEvent`.

---

## 4. O que falta para ligar a chave

### Código nosso, ainda não existe

1. **Drenagem de `aguardando_horario`.** Sem um handler, o lead que chega às 20h fica parado para
   sempre. Hoje isso não acontece só porque ninguém entra no fluxo.
2. **Saída de `reagendado`.** O período preferencial é gravado como texto livre e nunca lido.
3. **Encerramento.** `sem_contato` e `encerrado` são constantes mortas; nenhum lead sai do fluxo.
4. **Superfície de controle do `nat_config`.** Nenhum endpoint e nenhuma tela escrevem
   `nat_enabled` / `nat_start_at` — `grep` em `app/*.py` só encontra leitura em `nat_guard.py`.
   Ligar a NAT hoje é `UPDATE` manual no Postgres.
5. **Bloco 6** (botão "não consegui contato", `nat_recuperacao_sdr`, retry de 10 min) e
   **Bloco 8** (IA para motivação e período) — não iniciados.
6. **Duplicação do `nat_boasvindas`** — ver risco 1. Impede ligar a chave sem o lead receber a
   mesma mensagem duas vezes.

### Depende de terceiro

- **Meta:** nada bloqueando. Os 4 templates estão `APPROVED` em pt_BR: `nat_boasvindas`
  (2 quick replies), `nat_sim`, `nat_confirma_transferencia`, `nat_outro_horario`. Também estão
  lá `nat_reativacao_09h` e `nat_recuperacao_sdr`, do Cenário 2 / Bloco 6.
- **Exact:** a etapa "Aguardando Ligação" não existe em nenhum funil e a API não permite criá-la
  (`RECON_NAT_FASE1_EXACT_20260726.md`). O passo 4 da transferência foi removido de propósito —
  não é bloqueio, é escopo fechado.
- **Financeiro:** o 131042 (fatura) aparece em 47 leads, mas o último `failed` por esse motivo é
  antigo; 09/08 entregou normal. Não bloqueia hoje.

### Decisão do Álefe

- **Valor de `nat_start_at`.** Está NULL, e NULL bloqueia tudo (`nat_guard.py:208`). Sem uma data,
  ligar `nat_enabled` não muda nada.
- **Funil.** O guard restringe a 18535; a boas-vindas roda em 18535+18537+25588. Nos últimos
  30 dias: 219 leads em 18535, dos quais **196 passariam** nas travas de funil + SDR (107 da
  Valéria, 89 do Thobias, 18 sem SDR, 5 de outros).
- **`max_envios_hora = 20`** contra ~196 leads/30 dias em 18535 (~6,5/dia). O teto não aperta no
  volume atual, mas aperta em pico.
- **Ligar de vez ou por lote** — não há mecanismo de amostragem; a única alavanca é a data de corte.

---

## 5. Riscos e dívidas abertas

### 1. `nat_boasvindas` sai duas vezes quando a NAT ligar — `exact_spotter.py:226` e `nat_flow.py:347`

`send_welcome_to_new_lead` envia `config.template_name` (= `nat_boasvindas`). Em seguida,
`iniciar_fluxo_nat` chama `send_nat_message(NAT_BOASVINDAS)`, que com a janela fechada (lead novo,
sem inbound) manda **o mesmo template de novo**. Nada entre os dois deduplica. Hoje é inerte porque
o guard barra em `nat_enabled=false`; no dia em que ligar, todo lead elegível de 18535 recebe a
boas-vindas duplicada. Não está registrado em nenhum doc de sprint.

### 2. Varredura O(n) de `exact_leads` a cada envio da NAT — `nat_guard.py:167-171`

`_resolver_lead_e_wa_id` recebe um `Contact` (é o que `nat_sender.py:94` passa), e o ramo de
`Contact` carrega **todos** os leads com telefone e compara `format_phone` em Python. São 8 908
linhas hoje, sem índice possível, dentro do caminho de cada mensagem. Nunca reportado.

### 3. Os 82 cliques chegaram com payload = texto do botão — `exact_spotter.py:226-233`

A boas-vindas não passa `button_payloads`, então `NAT_SIM`/`NAT_OUTRO_HORARIO` nunca chegam. O
fallback por texto (`nat_flow.py:383-395`) cobre isso, mas **só quando o lead está em
`aguardando_resposta`** — e o fallback compara com `BOTOES_APROVADOS[NAT_BOASVINDAS]`, que casa com
os rótulos observados. Funciona; depende de o rótulo aprovado na Meta nunca mudar.

### 4. 190 leads presos em `sent`, 186 sem `wamid` — `models.py:139`

Sem `welcome_wamid`, o webhook de status não tem como achar o lead. Esses 186 nunca vão virar
`delivered` nem `failed` — ficam `sent` para sempre. É o resíduo anterior à coluna.

### 5. `failed` bloqueia reenvio permanentemente — `exact_spotter.py:186`

A idempotência é `welcome_status is not null`. Os 118 `failed` nunca serão reprocessados pelo sync;
o único caminho é o `POST /reenviar` com `force=True`, lead a lead (`exact_routes.py:188`).

### 6. Docstring do `nat_guard` afirma o oposto do código — `nat_guard.py:6-7`

> "Esta fase só CRIA a função. Ela NÃO está plugada em `send_welcome_to_new_lead` nem em lugar nenhum"

Está plugada: `nat_flow.py:306` e `nat_sender.py:94`. Quem ler o módulo para decidir se é seguro
ligar a chave lê uma afirmação falsa.

### 7. `delivery_health` com `MAX_FALHAS_PARA_VOLTAR = 0` — `delivery_health.py:139`

Basta **uma** falha na janela de 60 min para o alerta nunca anunciar recuperação. Está documentado
como decisão deliberada, mas na prática o par down/up disparou uma vez cada (27/07 e 30/07) e não
voltou a falar desde então, apesar dos `failed` de 04, 05 e 08/08.

### 8. Escalonamento do SLA presume 2 minutos como tempo humano — `nat_flow.py:49` + `nat_scheduler.py:76`

O job varre a cada 60 s, então o SLA de 2 min dispara entre 2:00 e 3:00. Documentado. O que não
está: `assumir` não muda a etapa, então após o nível 2 o lead fica em `aguardando_ligacao`
indefinidamente, e qualquer clique posterior dele cai em "clique fora da etapa" e é ignorado.

---

## 6. Divergências entre docs e código/banco

| Doc | Afirma | Realidade |
|---|---|---|
| `SPRINT_NAT_BLOCOS_5_7` § Estado final | `nat_button_events = 0` | **82** linhas, de 29/07 a 09/08 |
| `SPRINT_NAT_BLOCOS_5_7` § Estado final | `auto_welcome_config` com `enabled=false` "por decisão do Álefe por causa da fatura da Meta" | **`enabled = TRUE`**, religada em 28/07 12:15 por Valéria |
| `SPRINT_NAT_BLOCOS_0_1` § "Não está plugado em lugar nenhum" e `nat_guard.py:6-7` | `nat_pode_atuar` não foi ligada a nada | Ligada em `nat_flow.py:306` e `nat_sender.py:94` desde o sprint 2-3-4 |
| `SPRINT_NAT_BLOCOS_0_1` § "o marcador que ainda não existe" (`COLUNA_MARCADOR_ENVIO_NAT = None`) | marcador ausente | `COLUNA_MARCADOR_ENVIO_NAT = "nat_etapa"` (`nat_guard.py:65`), coluna e índice parcial aplicados |
| `SPRINT_NAT_BLOCOS_2_3_4` § 9 | "Hoje o lead chega em `aguardando_ligacao` e ninguém é avisado" · "agendador — sem ele `aguardando_horario` é uma fila que ninguém varre" | Notificação, SLA e agendador entregues no sprint 5-7. Mas a segunda metade continua verdadeira por outro motivo: o agendador existe e **`aguardando_horario` segue sem handler** |
| `models.py:125` | `welcome_status` é `sent \| skipped \| failed` | Existe um quarto valor em produção, **`delivered`** (146 leads), escrito em `main.py:106` |
| `SPRINT_NAT_BLOCOS_5_7` § Fora de escopo | "`welcome_status` + alerta de falha de entrega" pendente | Entregue no sprint de observabilidade (26/07), commits `c81a3f7`/`d90f11e` |
