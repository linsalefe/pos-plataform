# RECON_REAGENDAMENTO_20261018 — remarcação pelo WhatsApp: cliques, texto livre e quem cria a reunião

Somente leitura. Nenhum código, linha de banco ou dado da Exact foi alterado. Fontes: `nat_qualificacao_state`,
`nat_scheduled_actions`, `reuniao_status`, `notifications`, `nat_button_events`, `agendamentos`, `messages`,
journal do `cenat-backend` e, na Exact, só GET (`/Stages`, `/Meetings`, `/ListTimeline/{leadId}`).
Extração em 19/10 ~01:55 UTC (18/10 22:55 SP).

**Fuso.** Horários deste relatório estão em **SP**, salvo indicação. No banco: `messages.timestamp`,
`reuniao_status.*`, `agendamentos.*`, `nat_scheduled_actions.run_at/processed_at` e
`nat_qualificacao_state.transferido_em` são SP naive; `notifications.created_at`,
`nat_scheduled_actions.created_at`, `nat_button_events.created_at` e o journal são UTC.

**Datas.** O relato fala em 14-15/10, mas o caso da Viviane aconteceu em **13/10** (a reunião remarcada era
para 14/10 às 13:40).

---

## Resumo

1. **(a) Viviane.** O "13h45" **não** foi mal interpretado. O LLM escolheu certo
   (`acao=agendar_slot slot_id=2026-10-14T13:45`), o box foi criado e o `scheduleAdd` da Exact recusou com
   **`400 Stage not found`**. O fallback "Deixa eu te conectar..." é a transferência por
   `AgendamentoFalhou`. A reunião de 14/10 às 13:40 foi criada **pelo Thobias, na interface da Exact**, às
   09:52:44: `user` = Thobias França no `/Meetings`, "Reunião agendada com vendedor..." **sem** o "via API",
   e `reuniao_status.origem = 'exact'`. Não foi o agente nem a LP. A confirmação das 10:08 é a régua do
   Fluxo A reagindo à reunião nova que o `reuniao_sync` encontrou.
2. **(b) 6 cliques** de remarcação ou escolha de horário desde 07/10. **0 terminaram em reunião criada pelo
   agente.** Em 3 o lead escolheu um horário e a Exact recusou o `scheduleAdd`. Em 1 o lead pediu
   "Outro dia" e o LLM transferiu. Em 1 o agente não ofereceu horário nenhum (não havia horário livre) e
   mandou a resposta fixa. Em 1 o lead não respondeu à oferta. Nas **3 recusas, a reunião antiga ainda
   estava viva na Exact** no momento da tentativa.
3. **(c) 5 textos livres** batem com `remarcar|reagendar|outro horário|outro dia`, vindos de 4 pessoas.
   Todos acabaram com um humano: 3 por pausa da régua, 1 por transferência do agente e 1 com a conversa
   já pausada antes. A resposta humana veio em 30 min, 2h12 e 9h17 (madrugada). **2 nunca tiveram
   resposta pelo WhatsApp** (Luciana; Anne, até a extração). O aviso só chega a quem é **dono** do
   contato. Sem dono, vai para a gestão (Isa, user 2). As duas sem resposta e a de 9h17 estavam nesse
   caminho.
4. **Mensagem que ninguém vê.** Quando a régua pausa, ela notifica com a prévia **da mensagem que causou a
   pausa**. A mensagem seguinte, que é o pedido de remarcação, não gera aviso nenhum quando o contato não
   tem dono. Lilian: o aviso mostra "Olá! ... gostaria de mais informações". O "Remarcar a conversa para
   após dia 26", 19 s depois, não aparece em lugar nenhum.

---

## 1. Os quatro casos do relato

### 1.1 Viviane — 5511948502987, lead 52141680

**Contexto.** Reunião 4778268 (13/10 10:45, Rodrigues), criada pelo Thobias na Exact em 09/10. Ao ser
agendado pela interface, o lead foi movido por "roteamento inteligente" para o **funil 18537, etapa
`Agendamento SDR`** (`exact_stage_events` 6701).

| SP | fonte | evento |
|---|---|---|
| 13/10 09:00:25 | `nat_scheduled_actions` 4410 | `confirm_a_corte` executado. `reuniao_status` 4778268 → `cancelado_motivo=sem_confirmacao` (só no Hub; na Exact segue Vigente) |
| 09:00:25 | notif 6849 → **user 5 (Thobias)** | "Reunião sem confirmação: cancelar na Exact" |
| 09:00:26 | messages | template `nat_ns_d0_corte` |
| 09:09:19 | messages / `nat_button_events` 226 | clique `NS_D0_HORARIO` "Escolher horário" |
| 09:09:20 | journal | régua de no-show 4778268 encerrada (`NS_D0_HORARIO`), 8 degraus cancelados (4858–4865) |
| 09:09:20 | notif 6854 → user 5 | "Lead pediu para remarcar … O agente já mandou os horários" |
| 09:09:24 | Exact | nota `[NAT] Pediu remarcação` |
| 09:09:26 | journal | LLM `ofertando_agenda[3 slots]` |
| 09:09:28 | messages | oferta: 14/10 10:00, **13:45**, 17:30. Estado criado em `escolhendo_slot`, `dados_extras={"fluxo":"b","reunioes_remarcadas":[]}` |
| 09:09:28 | sched 4908–4912 | `encerrar_inativo` + `reativ_b_30m/2h/4h/d1` |
| **09:09:54** | messages | inbound **"13h45"** |
| 09:09:56 | journal | `LLM 5511948502987/escolhendo_slot \| acao=agendar_slot etapa_cumprida=True dado={'slot_id': '2026-10-14T13:45:00'}` |
| 09:09:58 | journal | `agendamento #1091: box 44133837 criado ... com Victória Amorim`; `lead 52141680 JÁ EXISTIA — LeadsAdd pulado` |
| 09:09:59 | journal | `box 44133837 removido (scheduleAdd falhou)`; **`scheduleAdd falhou — ExactErro: HTTP 400: Stage not found`** |
| 09:09:59 | `nat_qualificacao_state` | `etapa=transferido_humano`, `transferido_motivo="agendamento falhou (AgendamentoFalhou: HTTP 400: Stage not found)"` |
| 09:09:59 | notif 6856 → user 5 | "Agente passou um lead para você", com o motivo |
| 09:09:59 | messages | "Deixa eu te conectar com uma pessoa da nossa equipe..." |
| 09:44:04 | Exact (Victória Rodrigues) | desmarca 4778268 ("Reunião não confirmada") → **lead volta para 18535 `Follows 7`** |
| **09:52:44** | Exact (**Thobias França**) | "Reunião agendada com vendedor Victória Rodrigues, dia 14/10/2026 às 13:40". Lead volta para 18537 `Agendamento SDR` |
| 09:58:13 | `reuniao_status` | 4778787 nasce com `origem=exact`, `agendamento_id` nulo |
| 10:08:49 | sched 4937 / messages | `confirm_a_imediata` "...14/10, às 13:40" |
| 10:38:51 | messages | clique "Confirmo" → `confirmado_por=botao` |
| 14/10 11:28 | Exact (Thobias) | desmarca 4778787 ("Solicitou Reagendamento") e agenda 4780325 (14/10 15:05) pela interface |
| 14/10 18:05 | Exact (Victória Rodrigues) | Contratos Gerados. **Ela comprou.** |

**Por que "Stage not found".** O `scheduleAdd` manda `stageName: "Agendados"`, e a Exact procura esse nome
**dentro do funil em que o lead está** (AGENDAMENTO_FINDINGS §14). Às 09:09 o lead estava em
18537/`Agendamento SDR`, porque a reunião antiga só foi desmarcada na Exact às 09:44. Hoje o 18537 tem
`Agendamento SDR` (id 133413, posição 1), `Em Negociação`, `Contratos Gerados`, `Vendidos` e `Economia`.
Não existe `Agendados` nesse funil (o id 133413 é a antiga `Agendados` renomeada). E mesmo que o nome
batesse, §14 já mostrou que não dá para agendar pela API um lead do 18537
(`Previous stage is not exit action Scheduling`).

**O que o SDR fez diferente:** desmarcou a reunião antiga na Exact antes de criar a nova. Isso devolve o
lead para o 18535, e de lá o agendamento passa.

Notificações deste caso: todas para o **user 5 (Thobias)**, que é o dono do contato (`contacts.assigned_to=5`).

### 1.2 Rafaela — 5521983805324, lead 52750065

Reunião 4779881 (14/10 10:00, Amorim), criada pela LP (`origem=hub`, agendamento 1099).

| SP | evento |
|---|---|
| 13/10 20:18 | `nat_a_confirmacao` |
| 14/10 08:00 | `nat_a_ultimo_aviso` |
| **08:10:35** | clique `A_ULT_REMARCAR` "Preciso remarcar" (`nat_button_events` 235) |
| 08:10:36 | `reuniao_status`: `cancelado_motivo=remarcar`, `regua_encerrada_motivo=remarcar`. Ações 5034 e 5037 canceladas (`remarcar`) |
| 08:10:36 | notif 6954 → **user 2 (Isa)**, porque o contato não tinha dono nesse momento |
| 08:10:41 | oferta: 15/10 10:00, 15:00, 18:00 |
| 08:41 / 10:11 | `reativ_b_30m` e `reativ_b_2h` executados. Ela não respondeu |
| 10:32 | Exact (Amorim): 4779881 desmarcada, "Lead não compareceu" |
| 10:47:17 | Thobias manda pelo Hub "Havíamos agendado... não conseguimos falar com você". Estado vira `transferido_humano / outbound_manual_sdr`, `assumido_por=Thobias`; 5062 e 5063 canceladas ("o SDR assumiu a conversa") |
| 14/10 12:20, 15:30 · 15/10 17:03 | templates de follow (`mensagem_flow`, `mensagens_flows2`, `f3_guiatrabalhot3`) |

O sistema funcionou como desenhado: ofereceu horários e reativou duas vezes. Ela não respondeu, e o
agente não chegou a tentar agendar. Observações:
- A mensagem do SDR às 10:47 trata o caso como no-show, mas ela tinha pedido para remarcar às 08:10.
- A Exact registrou "Lead não compareceu" numa reunião que a pessoa avisou que não ia fazer.

### 1.3 Lilian — 5551999942166, lead 52792280

Reunião 4781041 (16/10 18:00, Rodrigues), `origem=hub`. Não há linha em `nat_qualificacao_state`.

| SP | evento |
|---|---|
| 15/10 00:18:21 | `nat_a_confirmacao` |
| 00:18:40 | inbound "Olá! ... gostaria de mais informações" (texto padrão da LP) |
| 00:18:43 | LLM de dúvida → `outro`. **`pausar`**: 5598–5601 canceladas (`humano`), `regua_encerrada_motivo=humano`, nota `[NAT] Aguardando humano` |
| 00:18:41 | notif 7045 → **user 2 (Isa)** · "Lead respondeu a confirmação: assuma", prévia = **a mensagem das 00:18:40** |
| **00:18:59** | inbound **"Remarcar a conversa para após dia 26"**. Journal: só `Dados salvos`. Nenhuma notificação, porque o contato não tem dono |
| 09:35:49 | Thobias responde (3 mensagens, propondo antecipar). Ações 5596 e 5602 canceladas (`sdr_assumiu`) |
| 16/10 18:06 | Exact: 4781041 desmarcada, "Lead não compareceu" |

Tempo até a primeira resposta humana: **9h17**, das quais 35 min dentro do expediente (a partir das 09:00).

### 1.4 Luciana — 5511941351304, lead 52745328

Reunião 4779798 (14/10 17:30, Rodrigues), `origem=hub`, confirmada pelo botão em 13/10 17:23. Sem linha em
`nat_qualificacao_state`, contato sem dono.

| SP | evento |
|---|---|
| 14/10 17:00 | `nat_a_30min` |
| 17:15:26 | inbound "Não vou conseguir. Estou presa no trânsito, tá caótico" |
| 17:15:29 | LLM de dúvida → `outro` → **`pausar`**, nota `[NAT] Aguardando humano` |
| 17:15:28 | notif 7022 → **user 2 (Isa)**, prévia = mensagem das 17:15:26 |
| **17:15:31** | inbound **"Podemos remarcar?"** Journal: só `Dados salvos`. Nenhuma notificação |
| — | **nenhuma mensagem humana para ela pelo WhatsApp até a extração** |
| 15/10 18:12 | Exact (Rodrigues): contrato registrado; reunião "concluída devido a mudança de funil"; "Tornou-se cliente!" em 16/10 |

Ela comprou, mas o contato que levou à venda não passou pelo WhatsApp do Hub. Pelo WhatsApp, o pedido de
remarcação ficou sem resposta.

---

## 2. (a) — resposta direta

- **Por que "13h45" caiu em fallback:** não foi o LLM. Ele agendou o slot certo. O fallback veio da Exact:
  `scheduleAdd` → `400 Stage not found`, porque o lead ainda estava no funil 18537 por causa da reunião
  anterior, que só foi desmarcada na Exact 35 min depois.
- **Quem criou a reunião de 14/10 13:40:** o **Thobias, pela interface da Exact**, às 09:52:44 de 13/10.
  Evidências: `/Meetings` 4778787 com `user.name = "Thobias França"`, timeline sem "via API",
  `reuniao_status.origem='exact'` e nenhum `agendamentos` correspondente. A confirmação imediata das 10:08
  foi a régua do Fluxo A, armada quando o `reuniao_sync` encontrou a reunião às 09:58.

---

## 3. (b) — cliques REMARCAR / HORARIO / REAGENDAR desde 07/10

Fonte: `nat_button_events.button_payload ~ 'REMARC|HORARIO|REAGEND'`, conferida contra
`messages.content LIKE 'botao:%'`, que dá 4 "Preciso remarcar" e 2 "Escolher horário". Nenhum clique dos
botões de no-show do D0+1h em diante (`NS_1H_HORARIO`, `NS_D2_REAGENDAR` etc.) neste período.

| # | quem | clique (SP) | botão | o que o agente fez | desfecho do agente | reunião nova depois? | por quem |
|---|---|---|---|---|---|---|---|
| 1 | Roseli 5521994324556 | 12/10 08:58 | `A_CONF_REMARCAR` | ofereceu 13/10 13:45 / 16:00; ela respondeu "13:45" | **fallback**: `400 Lead has already gone through this stage in this cycle.` | não. O SDR manteve a reunião original ("Sua reunião já está marcada hoje às 16:45", 13/10 13:19); comprou em 13/10 | — |
| 2 | Viviane 5511948502987 | 13/10 09:09 | `NS_D0_HORARIO` | ofereceu 3; ela respondeu "13h45" | **fallback**: `400 Stage not found` | sim, 14/10 13:40, criada 43 min depois | Thobias, na Exact |
| 3 | Rafaela 5521983805324 | 14/10 08:10 | `A_ULT_REMARCAR` | ofereceu 3 + 2 reativações | **sem resposta do lead** | não | — |
| 4 | Maria 5511991174062 | 14/10 14:59 | `NS_D0_HORARIO` | ofereceu 15/10 18:00; ela respondeu "18:00" | **fallback**: `400 Lead has already gone through this stage in this cycle.` | sim, 14/10 18:20, criada 60 min depois | Thobias, na Exact |
| 5 | Thais 5549998013061 | 16/10 18:34 (sex) | `A_CONF_REMARCAR` | journal: "sem horário hoje, amanhã nem nos 2 próximos dias úteis — segue a resposta fixa" | **resposta fixa** ("Vou pedir para a consultora te mandar os horários") | **não**, e **sem resposta humana até a extração** (~52h). A reunião 4783324 (20/10 11:00) segue **Vigente na Exact** | — |
| 6 | Anne 5581999963650 | 18/10 14:42 (dom) | `A_CONF_REMARCAR` | ofereceu 21/10 10:00 / 13:30 / 18:00; ela respondeu "Outro dia" | **fallback**: o LLM pediu transferência | não. Ela respondeu "Não precisa. Apenas quero desmarcar." **Sem resposta humana até a extração**; a reunião 4783426 (21/10 17:15) segue **Vigente na Exact** | — |

**Totais:** reunião nova criada pelo agente **0** · fallback **4** (3 recusas da Exact + 1 transferência
pelo LLM) · resposta fixa **1** (sem horário livre) · sem resposta do lead **1**. Considerando o que veio
depois: 2 reunião nova feita à mão pelo SDR (43 e 60 min depois), 2 sem nenhuma ação humana até a
extração (Thais e Anne).

**O agente nunca concluiu uma remarcação.** As 5 linhas de `nat_qualificacao_state` com
`dados_extras ? 'reunioes_remarcadas'` estão todas em `transferido_humano`, e nenhuma tem
`agendamento_id`. Nos `agendamentos` sem `origem_ip` (feitos pelo agente) desde 07/10: 11 `agendado`,
todos de primeira qualificação; 3 `falhou`, que são exatamente as 3 remarcações acima.

**As 3 recusas têm a mesma causa: a reunião antiga ainda estava viva na Exact.** A régua só cancela a
reunião no Hub. Para a Exact, ela pede a um humano ("Cancele a reunião antiga na Exact"), porque a API não
desmarca. O agente oferece horário no mesmo minuto, sem esperar esse cancelamento:
- lead agendado pelo **SDR na interface** (Viviane): fica no 18537 → `Stage not found`;
- lead agendado **pela LP** (Roseli, Maria): fica no 18535 com o ciclo já tendo passado por `Agendados` →
  `Lead has already gone through this stage in this cycle.`

O SDR contorna isso desmarcando primeiro (o lead volta para uma etapa de Follow) e agendando depois.
**Não está provado** que o `scheduleAdd` do agente passaria depois desse cancelamento: não há nenhum caso
observado em que o agente tenha tentado com a reunião antiga já desmarcada.

---

## 4. (c) — texto livre "remarcar | reagendar | outro horário | outro dia" desde 07/10

Filtro: `messages` inbound de texto desde 07/10, sem `botao:`, sem acento e em minúsculas, casando
`(remarc|reagend|outro horario|outro dia)`. Resultado: **5 mensagens de 4 pessoas.**

"Primeira resposta humana" = primeiro outbound com `sent_by` preenchido (alguém digitando no Hub) depois
da mensagem.

| # | quem | inbound (SP) | texto | o que o sistema fez | aviso para | 1ª resposta humana | tempo |
|---|---|---|---|---|---|---|---|
| 1 | Luciana | 14/10 17:15:31 | "Podemos remarcar?" | nada nesta mensagem. A régua já tinha pausado 2 s antes, com "Não vou conseguir..." | Isa (user 2), só pela mensagem anterior | **nenhuma pelo WhatsApp** | — |
| 2 | Lilian | 15/10 00:18:59 | "Remarcar a conversa para após dia 26" | nada nesta mensagem. A régua tinha pausado 16 s antes, com o texto padrão da LP | Isa (user 2), com a prévia **da outra mensagem** | Thobias 09:35:49 | **9h17** (35 min no expediente) |
| 3 | Thais | 16/10 08:04:46 | "Posso reagendar para segunda de manhã?" | **`pausar`** (LLM de dúvida → `outro`), 22 s depois de ela clicar "Confirmo" | Thobias (dono), notif 7124 + `new_message` 7125 | Thobias 10:16:22 | **2h12** |
| 4 | Thais | 16/10 10:46:10 | "...estarei em uma reunião hoje. Sinto muito, mas preciso remarcar" | nada (a conversa já estava pausada) | Thobias, `new_message` 7129 | Thobias 11:16:31 | **30 min** |
| 5 | Anne | 18/10 14:42:56 (dom) | "Outro dia" | **transferência do agente** (Fluxo B, `escolhendo_slot`) | Isa (user 2), notif 7198 | **nenhuma até a extração** | > 8h |

**Contagem pedida:**
- Caíram em pausa para humano **por causa da própria mensagem**: 2. A #3 pela régua; a #5 pelo agente.
  Esta última é, a rigor, um fallback do Fluxo B, e não pausa de régua.
- Já estavam em humano quando a mensagem chegou: 3 (#1, #2, #4). Nas duas sem dono (#1, #2) a mensagem de
  remarcação **não gerou aviso nenhum**.
- Tempo até a primeira resposta humana: 30 min, 2h12 e 9h17, mais 2 sem resposta. Mediana entre os que
  tiveram resposta: 2h12. Amostra pequena demais para chamar de taxa.

**O que separa quem foi respondido de quem não foi é ter dono.** As duas pessoas atendidas pelo Thobias
pelo próprio aviso (#3 e #4) tinham `contacts.assigned_to=5`. As três sem dono (#1, #2, #5) caíram na
gestão. Dessas, uma foi atendida pelo Thobias na manhã seguinte e duas ficaram sem resposta. Nenhuma das
notificações dos 6 casos deste relatório está com `is_read=true`, então o sino não indica se alguém viu.

**Checagem de sensibilidade** (frases fora do filtro pedido: "não vou conseguir", "desmarcar", "outro
momento"): +6 mensagens. Uma delas mostra o mesmo caminho com dono. Yalli (5586998285848, 15/10 16:09,
"Não vou conseguir estar presente na chamada") → `pausar` → aviso para o Thobias (dono) → resposta em
**27 min**, e reunião nova feita por ele na Exact para 19/10.

---

## 5. Achados para decisão (nenhum aplicado)

1. **A remarcação pelo agente não funciona hoje** (0 de 3 tentativas). O agente oferece e tenta agendar
   antes de a reunião antiga sair da Exact, e a Exact recusa. Qualquer conserto passa por uma destas
   opções:
   - o agente não oferecer horário enquanto a reunião antiga estiver Vigente na Exact, e mandar a resposta
     fixa;
   - medir se o `scheduleAdd` passa depois do cancelamento manual. Precisa de teste controlado, porque
     não houve caso observado.

   Até lá, cada "Escolher horário" ou "Preciso remarcar" que chega ao Fluxo B **promete ao lead um
   horário que o sistema não consegue marcar**. Em 2 casos o lead escolheu um horário e recebeu "Deixa eu
   te conectar com uma pessoa".
2. **Contato sem dono → aviso na gestão (Isa).** `confirmacao._notificar` e a notificação
   `new_message` (`main.py:826`) só alcançam `assigned_to`. Lead novo da LP não tem dono, e o SDR que
   realmente atende (Thobias) não recebe. Foram 3 casos neste recorte: 1 respondido 9h depois, 2 sem
   resposta.
3. **A mensagem seguinte à pausa é invisível sem dono.** A prévia do aviso é a mensagem que causou a pausa,
   não a que pede a remarcação (Lilian, Luciana).
4. **"Preciso remarcar" deixa a reunião Vigente na Exact.** O Hub marca `cancelado_motivo=remarcar`, mas
   só o humano desmarca na Exact. Thais (20/10 11:00) e Anne (21/10 17:15) seguem Vigentes na agenda das
   consultoras, com pedido de desmarcar sem resposta.
5. **Sem horário em 4 dias.** Na sexta 16/10 18:34 o agente não achou horário "hoje, amanhã nem nos 2
   próximos dias úteis". No domingo 18/10 ofereceu só quarta 21/10. Não investiguei se é agenda cheia ou
   grade (folga de 30 min + almoço fixo, 3a65044, de 14/10). Merece um recon próprio.
