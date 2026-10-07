# RECON: confirmação de reunião, Fluxo B enxuto e régua de no-show (07/10/2026)

**Modo: SOMENTE LEITURA.** Nenhuma alteração de código, banco, Meta ou Exact. Toda consulta SQL
rodou com `default_transaction_read_only=on`; toda chamada à Exact e à Meta foi `GET`.
Medição feita em 07/10/2026 entre 05h50 e 07h00 (SP).

Spec de referência: "IA de Confirmação e No-show" (Isa, 28/09/2026). Escopo: só WhatsApp.

> **Aviso de método.** O texto integral da spec não estava disponível nesta sessão: não está no
> repo, no Drive nem no Notion conectados (buscas feitas). O que este relatório usa da spec é o
> que o próprio pedido do RECON descreve: fluxos, momentos, botões e as 6 situações de CRM. Os
> corpos de template da seção 3 são **rascunho meu** com a estrutura certa. A conferência de
> limites da Meta vale para o rascunho, e precisa ser refeita sobre o texto da Isa antes de
> submeter (o método está na seção 3.3).

Predicado de teste aplicado em toda métrica: `relatorios.PREDICADO_TESTE`
(`app/relatorios.py:216`) sobre o nome, mais a chave de telefone `8388046720` (número
83988046720) fora. Relógios: `agendamentos.*`, `nat_scheduled_actions.run_at` e
`messages.timestamp` são SP naive. `nat_scheduled_actions.created_at` e
`nat_qualificacao_state.created_at` são UTC. `Meetings.startTime` é hora de parede SP (o `Z` não
significa UTC, FINDINGS §1). `Meetings.registerDate` é UTC de verdade.

---

## §0 Resumo executivo

**Ambiente medido.** Produção roda do mesmo diretório deste repo
(`systemctl show cenat-backend`: `WorkingDirectory=/home/ubuntu/pos-plataform/backend`).

| | branch | HEAD |
|---|---|---|
| produção (processo no ar) | `feat/pos-psiclinica-aplicada` | `ca3cd1f` |
| repo local | `feat/pos-psiclinica-aplicada` | `ca3cd1f` |

- Último restart do backend: **05/10/2026 14:48:19 UTC** (`ExecMainStartTimestamp`, PID 1940782).
- O commit `ca3cd1f` é de 14:49:47 UTC (depois do restart), mas só mexe em
  `docs/AGENDAMENTO.md`. `find backend -name '*.py' -newermt '2026-10-05 14:48:19'` devolve
  vazio. Portanto **o código em execução é o código do HEAD**.
- Essa branch está 3 commits à frente da `main` (`6d321d8`, `c61bf40`, `ca3cd1f`), sem merge.
- **Arquivo solto, não versionado e não tocado nesta sessão:** `backend/fix_status_orfao_webhook.py`,
  7 624 bytes, de 28/09/2026 21:50. É um backfill que lê o journal e corrige as linhas de
  `messages` que ficaram `sent` quando o `failed` da Meta chegou antes do commit do envio
  (até o merge `3ea0668`). Tem dry-run por padrão e só grava com `--apply`.

**Os 3 maiores bloqueios:**

1. **O Hub não sabe o que acontece com a reunião depois que ela nasce.** O status da reunião existe
   na Exact (`Meetings.type` = `Vigente` / `Concluido` / `Cancelada`), mas o sync só lê `/Leads`
   (`exact_spotter.py:501`), e `agendamentos.passo` fica `agendado` para sempre. Efeito já
   medido: **4 lembretes T-30 saíram para reuniões que já tinham sido remarcadas**, e **2
   lembretes estão pendentes agora para reuniões já `Cancelada` na Exact**. Um sai **hoje, 07/10,
   às 14:00** (agendamento 959) e o outro amanhã, 08/10, às 13:15 (agendamento 945). Todo o Fluxo A
   e o corte da spec dependem de resolver isto antes.
2. **"Cancela e libera o horário" não existe pela API**, e "no-show" não é um status distinto.
   O `$metadata` não tem nenhuma ação de cancelar ou atualizar reunião, e o `type` não tem valor
   de no-show: `Cancelada` mistura cancelamento prévio, remarcação e falta. **Porém** a Exact
   expõe webhooks `event.cancelschedule`, `event.reschedule`, `event.schedule` e
   **`event.schedulenotheld`** (reunião não realizada), e nenhum está cadastrado
   (`GET /Webhooks` = vazio). É o caminho mais curto para o gatilho de no-show e para enxergar
   remarcações, mas ainda não foi testado.
3. **26% das reuniões não passam pelo Hub.** Desde 07/09, 64 de 249 reuniões da Exact foram
   criadas direto lá (SDR ou consultora) e não existem em `agendamentos`. Mais 27 caem em lead
   conhecido, mas com reunião nova (remarcação). Uma remarcação na Exact **cria reunião nova com
   id novo** e cancela a antiga (0 casos de mesmo id com data nova, 22 leads com 2+ reuniões).
   O Fluxo A, ligado só a `agendamentos`, não alcança essas reuniões.

Números de contexto: das reuniões **marcadas pelo Hub** com horário já passado, só **17%
constam `Concluido`** (26 de 153), 75% `Cancelada`, 8% `Vigente` sem feedback. Um terço dos
agendamentos (46 de 140) acontece entre 20h30 e 8h. O Fluxo B tem cerca de **5 pessoas por dia**
que aplicam e nunca agendam (161 em 30 dias).

---

## §1 Mapa do código hoje (Fase 1)

### 1.1 Fluxo B hoje

- **Perguntas antes da agenda: 4 no roteiro, 3 na prática.** `formacao → ano → atuacao →
  motivacao` (docstring `qualificacao_fluxo.py:11-30`; `MISSOES` em `:179-290`; `PROXIMA`
  `:368-372`). A LP já traz a formação em `extras` (`Profissão`), então quase todos abrem em
  `aguardando_ano` com T2 (`iniciar_qualificacao`, `:1232-1238`, etapa inicial
  `AGUARDANDO_ANO if formacao`). Só depois de `aguardando_motivacao` o código oferta agenda
  (`_avancar`, `:1485-1497`).
- **Template de abertura** (`:1244-1259`, escolha em código):

  | caso | template (Meta) | parâmetros | corpo |
  |---|---|---|---|
  | T2: tem formação | `nat_abertura_qualificacao` (MARKETING) | `{{1}}` nome, `{{2}}` curso, `{{3}}` formação | "Olá, {{1}}! Que bom te ver por aqui ✨ Vi que você aplicou para a nossa Pós-Graduação em {{2}}. Antes de te mostrar os horários com a nossa consultoria, gostaria de entender um pouco melhor a sua trajetória até aqui. Vi que sua formação é em {{3}}. Em que ano você concluiu?" |
  | T3: sem formação | `nat_abertura_sem_formacao` (MARKETING) | nome, curso | "... Me conta: qual é a sua formação?" |
  | T1: tem reunião | `nat_abertura_agendado` | 6 parâmetros | **morto para reunião futura** desde 27/09: `raise AcaoIgnorada(MOTIVO_JA_AGENDADO)` (`:1212-1216`) |

- **Onde a LP sinaliza "aplicou e não agendou":** `POST /lead` → `cadastrar_lead_sem_agendar`
  (`agendamento/agendar.py:602`) grava a linha `lead_criado` e chama `_gatilho_do_agente`
  (`:530`) → `agendar_abertura` (`:561`) → ação `iniciar_qualificacao` em **+5 min**
  (`qualificacao_gatilho.py:37`, `ESPERA`). Quem agenda no `obrigado.html` nesses 5 minutos é
  pulado na execução (`:1212-1216`). **Não existe** evento explícito "não agendou": o sinal é a
  ausência de reunião aos 5 minutos.
- **Filtro "graduação + condição de investimento":** a LP **coleta** os dois campos e
  **ninguém filtra**. Em `agendamentos.extras` (30 dias): `Ensino Superior` Sim 304 / Não 28;
  `Faixa de investimento` (faixas) 250, ou `Investimento possível` Sim/Não 78. Quem responde
  "Não" recebe lead e abertura igual aos outros, e agenda (cruzamento `lead_criado` × agendou:
  `Não/faixa` 20 → 8 agendaram; `Sim/inv=Não` 37 → 12). O agente grava
  `faixa_investimento` e **nunca lê** (`models.py:812-814`). O runbook registra que o
  obrigado é o mesmo para Sim e Não (`docs/AGENDAMENTO.md`, Pendências). **A spec assume um
  filtro que hoje não existe.**

### 1.2 Reativação hoje

| peça | estado | onde |
|---|---|---|
| `follow_20h` | **desligado**: `nat_config.follow_enabled = f`, `follow_template = follow_up` | handler `:2328`, gate `:2342-2347` |
| `encerrar_inativo` | ligado, 72h | `INATIVIDADE_ENCERRA` `:92`, handler `:2408` |
| vigia | ligado, 10 min (alarme para a gestão, não fala com o lead) | `PRAZO_VIGIA` `:109`, `vigiar_resposta` `:2144` |

Em produção, `nat_scheduled_actions` dos últimos 14 dias:

```
 encerrar_inativo     cancelado 136 | skipped 46 | pendente 26 | executado 5
 follow_20h           cancelado 197 | skipped 15 | pendente 1
 iniciar_qualificacao cancelado 192 | skipped 122 | executado 77 | pendente 4
 lembrete_reuniao     executado 60  | cancelado 12 | pendente 9
 vigiar_resposta      cancelado 136
```

`follow_20h` não executou nenhuma vez em 14 dias. **Não existe hoje nenhuma mensagem de
reativação** para o lead calado do agente: ele recebe a abertura e mais nada.

### 1.3 Fluxo A hoje

- **Única mensagem automática pós-agendamento:** o T-30 `nat_lembrete_reuniao`
  (`agendar_lembrete` `:1830`, `ANTECEDENCIA_LEMBRETE` `:73`, handler `:1863`). Mais a confirmação
  em texto livre só quando a reunião nasce **pelo agente** (`_concluir(confirmar=True)` `:1649`,
  ou a fala do LLM em `_agendar`) ou pela página do token (`concluir_por_agendamento_externo`
  `:1762`). Quem agenda pela LP vê "confirmado" na tela e só recebe o T-30.
- **Não existe**: confirmação imediata com botão, pedido de confirmação, corte, campo ou
  estado "confirmado". Conferido: `models.py` não tem coluna ou constante de confirmação, e
  `grep -rn "confirmad" backend/app` só devolve textos de log e docstrings.
- **Onde nasce um `Agendamento` com `PASSO_AGENDADO`:** só em `agendamento/agendar.py:agendar`
  (`:285`), chamado pela LP (`POST /agendar`) e pelo agente (`_agendar`, sessão própria). Não há
  terceiro caminho.
- **Reunião marcada pela SDR direto na Exact NÃO entra em `agendamentos`.** Medido (seção 5.3):
  desde 07/09, **64 de 249** reuniões não existem na nossa tabela. Janela de 7 dias pedida
  (`startTime ≥ 30/09`): **Exact 76** (Cancelada 40, Concluido 21, Vigente 15) contra
  **`agendamentos` 50** (`passo='agendado' AND slot_inicio ≥ 30/09`). Das 76, **21 não estão no
  Hub**.

### 1.4 No-show hoje

`grep -rn "noshow\|no_show\|no-show\|statusMeeting\|meeting.*status" backend/app` → **vazio**.
Nenhuma leitura de resultado de reunião. O único uso de `/Meetings` é
`meeting_por_lead` (`agendamento/client.py:243`), que pega o `id` logo depois do `scheduleAdd`
(`agendar.py:485`) e nunca mais volta.

### 1.5 Botões hoje

- **Payloads existentes** (`nat_copy.py:27-37`): `NAT_SIM`, `NAT_OUTRO_HORARIO`,
  `NAT_TENTAR_AGORA`, `NAT_AGENDAR_OUTRO`. São todos do fluxo velho de botões, que está
  **desligado** (`nat_config.nat_enabled = f`). Limite de título de botão livre: 20
  (`LIMITE_TITULO_BOTAO`, `:40`).
- **Envio:** `send_template_message(..., button_payloads=)` fixa o payload de cada quick reply
  por índice (`whatsapp.py:61`, laço `:89-97`). `enviar_nat` escolhe sozinho: janela aberta
  vira texto livre com `send_interactive_buttons` se a etapa estiver em `BOTOES_LIVRES`; janela
  fechada vira template com `payloads_dos_botoes(etapa)` (`nat_sender.py:186-232`). **O mecanismo
  de botão com payload próprio existe e serve para templates novos**: basta registrar a etapa
  em `nat_copy.BOTOES_APROVADOS`/`BOTOES_LIVRES`.
- **Webhook** (`main.py:676-764`): o clique é extraído (`nat_buttons.extrair_evento_botao`,
  `:27`), gravado em `nat_button_events` **com** `context_message_id` (wamid original,
  `nat_buttons.py:60`), e depois roteado. A ordem é: agente primeiro (`processar_texto_agente`,
  `main.py:753`), que recebe o clique como texto `"botao:<rótulo>"`; se o agente não é dono,
  `nat_flow.processar_clique` (`:759`). O roteamento do fluxo velho é **por payload + etapa**
  (`nat_flow._payload_do_evento`, `:602`). **Não há roteamento por `context.id`**: ele é
  guardado e nunca lido para decidir.
- **Templates aprovados com quick reply:** só 3, todos do fluxo velho: `nat_boasvindas`,
  `nat_reativacao_09h` ("Sim, posso falar agora" / "Prefiro outro horário") e
  `nat_recuperacao_sdr` (pt_BR e en). Nenhum serve para confirmação.

### 1.6 Horários: onde a janela atual bloqueia a spec

A janela atual é `dentro_horario_comercial`: **09h00–18h30, seg–sex**, sem feriado
(`nat_guard.py:112-146`). `proximo_horario_util` empurra para as 09h00 do próximo dia útil
(`:148`). Quem usa hoje: só a abertura do agente (`qualificacao_fluxo.py:1178`) e o fluxo velho.
**O lembrete T-30 não tem janela nenhuma** (`guard_de_lembrete`, `qualificacao_guard.py:329`).

| ponto da spec | o que a janela atual faria |
|---|---|
| silêncio 20h30–8h, todos os dias | hoje o silêncio é 18h30–9h **e o fim de semana inteiro**. A spec abre 8h–9h, 18h30–20h30 e sábado/domingo |
| confirmação imediata a qualquer hora | bloqueada fora de 9h–18h30 e no fim de semana. **46 de 140** agendamentos (33%) acontecem entre 20h30 e 8h; **38** no fim de semana |
| pedido de confirmação 17h da véspera (reunião de manhã) | reunião de **segunda** tem véspera no **domingo** 17h: bloqueado, empurrado para segunda 9h, **depois do corte das 9h** |
| pedido de confirmação 8h do dia (reunião à tarde) | 8h está fora (abre 9h): empurrado para 9h |
| último aviso 8h (reunião de manhã) | idem, 8h vira 9h, que é a hora do corte |
| corte 9h | coincide com a abertura, passa. Mas o corte de reunião de segunda depende do pedido de domingo, que nunca saiu |
| no-show D0 +8h | reunião às 14h dá 22h: bloqueado pela spec (silêncio) e pela janela atual |
| T-30 só para confirmados | sem janela hoje; com a spec, reunião das 10h tem T-30 às 9h30, que está dentro |

### 1.7 Agenda oferecida

`_fatos` pega os **3 primeiros dias que têm horário livre**, até 6 horários espalhados por dia
(`qualificacao_fluxo.py:872-873`). Isso não é "hoje + 2": `resumo_por_dia` só devolve dia com
vaga (`disponibilidade.py:187`), e o horizonte é `AGENDAMENTO_JANELA_DIAS=4` (`.env`; padrão de
código 3, `grade.py:84`), com antecedência mínima de 2h (`grade.py:92`). Expediente 10h–19h,
45 min, último horário 18h15 (`consultoras.json`; DEPLOY_EXPEDIENTE_10_19).

**Para "só hoje e amanhã"** o ajuste é em `_fatos:872`: trocar `[:3]` por um filtro de data
(`dia ∈ {hoje, amanhã}` em SP), **não** por `[:2]`. Com `[:2]` "amanhã" vira "os dois
próximos dias com vaga", que na sexta à tarde é segunda e terça. `slots_livres` não muda.
Efeitos medidos: com a ocupação real, os dois primeiros dias tendem a ter pouca vaga (runbook,
"Retry ao vivo": nos dois primeiros dias, 0% de horários com as duas consultoras livres em
24/08). Na sexta depois de 16h15 e no sábado, "hoje e amanhã" dá **zero** horários. A spec
precisa dizer o que fazer nesse caso (seção 8).

### 1.8 Registro na Exact

O que o Hub escreve hoje no lead:

- **Observação** na timeline: `exact_notes.registrar_observacao` (`exact_notes.py:65`),
  `POST /timelineAdd`, prefixo `[NAT]`, autor 415967. Vivo (seção 5.6).
- **Mudança de funil**: `client.mudar_funil` (`client.py:213`, `POST /ChangeFunnel`), desligado
  no agendamento. **Mudança de estágio dentro do funil: não existe pela API** (memória
  `exact-nao-move-estagio-intra-funil`: 4 endpoints tentados). O `scheduleAdd` move para
  `Agendados` como efeito colateral.

Estágios do funil 18535 (seção 5.5): **nenhum** dos 6 status da spec existe.

---

## §2 Números de produção (Fase 2), últimos 30 dias, sem teste

> A query do RECON `SELECT origem, passo ... FROM agendamentos` não roda: **`agendamentos` não
> tem coluna `origem`**. A origem é derivada como em `relatorios.py:450`: `origem_ip IS NULL` =
> agente, com IP = site.

**Reuniões por origem:**

```
 origem | passo       | count
 site   | lead_criado |   325
 site   | agendado    |   121
 site   | falhou      |    56   (47 deles em 16/09: "SDR is disabled")
 agente | agendado    |    19
 site   | recusado    |     7
 agente | falhou      |     6
```

**Lembretes T-30:**

```
 executado | (null)                                              | 122
 cancelado | (null)                                              |  34
 skipped   | lembrete não saiu: contato não existe no banco      |   9
 pendente  | (null)                                              |   9
 skipped   | lembrete não saiu: teto de envios/hora estourado ... |   2
```

Cruzando com o `type` atual na Exact: dos 122 executados, 90 são de reuniões hoje `Cancelada`,
24 `Concluido`, 11 `Vigente`, e 27 sem reunião casável na janela baixada. **4 saíram para reunião
que já tinha sido remarcada** antes do envio (agendamentos 387, 429, 530, 674: em cada um, a
reunião nova do mesmo lead foi registrada antes do `run_at` do lembrete da antiga). **2 pendentes
são de reunião já `Cancelada`**: 959 (run 07/10 14:00) e 945 (run 08/10 13:15).

**Distribuição de hora (agendado, 140):**

```
 total | mais_12h | menos_4h | noite_para_manha | reuniao_manha | reuniao_tarde | agendou 20h30-8h | agendou fds
   140 |      117 |        8 |                5 |            41 |            99 |               46 |          38
```

Mediana entre agendar e a reunião: site 50,2h, agente 25,2h. As exceções da spec são pequenas:
"menos de 4h" 8 (5,7%), "depois das 17h para a manhã seguinte" 5 (3,6%). A regra geral
"reunião em mais de 12h" cobre 84%.

**Fluxo B: aplicou e não agendou.** Linha `lead_criado` não é "não agendou": no fluxo de duas
etapas a reunião vira **outra** linha. Medido: 325 `lead_criado` (293 pessoas); **121 agendaram
em até 10 min**; **161 pessoas nunca tiveram reunião** (nem por `lead_id`, nem pelo telefone).
Por dia: entre 1 e 12, tipicamente 3 a 9; pico de 21 em 16/09 (incidente "SDR is disabled").
Média **~5,4 por dia**.

**Agente:**

```
 etapa               | motivo                                   | count
 encerrado           | inatividade                              |    91
 concluido           |                                          |    34
 transferido_humano  | follow_estagio                           |    33
 encerrado           | pausa_operacional_20260917               |    25
 transferido_humano  | o LLM pediu transferência (...)          |    14
 transferido_humano  | outbound_manual_sdr                      |    10
 transferido_humano  | disparo_manual                           |    10
 aguardando_ano      |                                          |     9
 transferido_humano  | agendamento falhou (SDR is disabled)     |     4
 transferido_humano  | recusa_ligacao                           |     2
 (outros, 1 cada: aguardando_formacao, Previous stage..., Lead is discarded, LLM indisponível, concluido/disparo_manual)
```

237 aberturas, **119 responderam** alguma coisa (50%). 91 encerraram por inatividade sem nenhuma
reativação.

**Taxa de no-show: não medível com precisão.** Motivo: `Meetings.type` não tem valor de
no-show, e `Cancelada` junta cancelamento antes da hora (8 reuniões futuras já estão
`Cancelada`), remarcação (20 das 115 canceladas do Hub têm reunião nova no mesmo lead) e falta.
O que dá para medir:

| reuniões com horário passado (07/09 a 06/10) | total | Concluido | Cancelada | Vigente (sem feedback) |
|---|---|---|---|---|
| todas | 230 | 71 (31%) | 147 (64%) | 12 (5%) |
| marcadas pelo Hub (`managerDescription` "Agendamento LP —") | 153 | **26 (17%)** | 115 (75%) | 12 (8%) |

O teto de "não aconteceu" das reuniões do Hub é 83%. A taxa de no-show propriamente dita fica
dentro disso, sem como separar. O webhook `event.schedulenotheld` (seção 5.2) é o que permitiria
separar daqui para a frente.

---

## §3 Inventário de templates (Fase 3)

### 3.1 O que existe

- `whatsapp_templates` (banco) tem só os 5 criados pelo Hub, e **está defasada**: diz
  `zz_teste_plataforma_20260625 PENDING`, a Meta diz APPROVED.

  ```
  nat_abertura_agendado     pt_BR MARKETING APPROVED
  nat_abertura_qualificacao pt_BR MARKETING APPROVED
  nat_abertura_sem_formacao pt_BR MARKETING APPROVED
  nat_lembrete_reuniao      pt_BR UTILITY   APPROVED
  zz_teste_plataforma_20260625 pt_BR UTILITY PENDING
  ```

- **Meta** (`GET /{WABA …3727}/message_templates?limit=200`, paginado): **97 templates, todos
  APPROVED; 94 MARKETING, 3 UTILITY** (`nat_lembrete_reuniao`, `hello_world`,
  `zz_teste_plataforma_20260625`). Botões: quick reply só nos 3 do fluxo velho (1.5). Botão
  URL nos `f3_guia*` ("Ementa da Pós", 17) e `f4_audio*` ("Áudio do Coordenador", 16), e em
  `vagasafirmativas_*` e `follow1_vagasafirmativas_apresentacao`. Header de mídia: IMAGE
  (`agendamentosdr_*`), DOCUMENT (`follow5_*`). **Nenhum template com header AUDIO**: a Meta não
  aceita AUDIO como header de template (formatos: TEXT, IMAGE, VIDEO, DOCUMENT, LOCATION). O
  padrão da casa para áudio é link em botão URL (`f4_audio*`).
- Parecidos com a spec, mas que **não servem como estão**:

  | template | por que não |
  |---|---|
  | `confirmacaoreuniao_vi` / `_vick` | assinado "Sou o Thobias", "consultora Victória" fixo, número de telefone fixo, "Bom dia" fixo, "hoje" fixo, sem botão |
  | `nat_lembrete_reuniao` | serve de T8 (30 min antes), mas não fala de confirmação |
  | `reagendamento_1`, `reagendamento_2_`, `final_reagendamento` | no-show escrito pelo SDR, sem botão; `final_reagendamento` cita campanha de setembro "até 30/09" (vencida) |
  | `f3_guia<curso>` | serve de T4 (ementa por curso, 16 variantes), mas o texto é de follow ("Me conta o melhor horário…"), incoerente com quem já tem reunião |
  | `f4_audio<curso>` | áudio do coordenador por curso: base do T13, mas texto de follow e sem quick reply |
  | `lead_desistente` | perto do T17, sem botão |
  | `seminario_1` | cupom e data de julho fixos |

### 3.2 Mensagem da spec → template

| # | fluxo | mensagem | existe que sirva? | nome proposto | categoria proposta | botões (≤ 20) | header |
|---|---|---|---|---|---|---|---|
| T1 | B | abertura + motivação | **não** (as `nat_abertura_*` perguntam formação/ano) | `nat_b_abertura` | MARKETING | | |
| T2 | B | reativação D+1 9h com horários | **não** | `nat_b_reativacao_d1` | MARKETING | | |
| T3 | A | confirmação imediata | **não** | `nat_a_confirmacao` | UTILITY | Confirmo (8) · Preciso remarcar (16) | |
| T4 | A | +4h ementa | parcial (`f3_guia*`, texto errado) | `nat_a_ementa_<curso>` ou `nat_a_ementa` + URL dinâmica | MARKETING | URL "Ementa da Pós" (13) | |
| T5 | A | +8h benefício | **não** | `nat_a_beneficio` | MARKETING | | |
| T6 | A | pedido de confirmação | **não** | `nat_a_pedido_confirmacao` | UTILITY | Confirmo (8) · Preciso remarcar (16) · Não vou conseguir (17) | |
| T7 | A | último aviso | **não** | `nat_a_ultimo_aviso` | UTILITY | Confirmo · Preciso remarcar | |
| T8 | A | 30 min antes (só confirmados) | **sim, com ressalva**: `nat_lembrete_reuniao` (UTILITY) serve como está; muda só **quem recebe** | manter `nat_lembrete_reuniao` | UTILITY | | |
| T9 | A/NS | cancelamento no corte (= D0) | **não** | `nat_ns_d0_corte` | MARKETING ¹ | Posso falar agora (17) · **"Escolher novo horário" tem 21: estoura** → "Escolher horário" (16) | |
| T10 | NS | D0 +1h | **não** | `nat_ns_d0_1h` | MARKETING | Posso falar agora · Escolher horário | |
| T11 | NS | D0 +8h | **não** | `nat_ns_d0_8h` | MARKETING | Posso falar agora · Escolher horário | |
| T12 | NS | D1 com horários | **não** | `nat_ns_d1` | MARKETING | Escolher horário | |
| T13 | NS | D2 áudio do coordenador | parcial (`f4_audio*`) | `nat_ns_d2_audio_<curso>` | MARKETING | Reagendar (9) · Posso falar agora + URL "Ouvir o áudio" (13) | **link em botão URL**, não header |
| T14 | NS | D3 seminário (muda todo mês) | **não** | `nat_ns_d3_seminario` com o tema em `{{n}}` | MARKETING | Quero participar (16) | |
| T15 | NS | D5 conteúdo | **não** | `nat_ns_d5_conteudo` + URL dinâmica | MARKETING | (URL opcional) | |
| T16 | NS | D7 condição especial | **não** | `nat_ns_d7_condicao` com a condição em `{{n}}` | MARKETING | Reagendar | |
| T17 | NS | D8 encerramento | **não** | `nat_ns_d8_encerramento` | MARKETING | Falar agora (11) · Reagendar (9) | |

¹ T9 avisa que a reunião foi cancelada (seria UTILITY), mas oferece reagendar e falar agora, o
que a Meta costuma reclassificar como MARKETING. Submeter com `allow_category_change=True`
(`whatsapp.py:198`) e aceitar a que vier.

**Reativações +30min / +2h / +4h do Fluxo B** saem dentro da janela de 24h, porque o lead acabou
de aplicar, mas só se a janela estiver **aberta**. A janela é contada a partir de **mensagem
do lead** (`janela_aberta`, `nat_sender.py:31-66`), não da nossa. Um lead que aplicou e **nunca
escreveu** está com a janela **fechada**: `enviar_nat` cai no ramo de template e recusa
`qual_conversa` ("não pode ser montado sem inventar dado", `:200-206`). **Conclusão: o texto
livre só cobre o lead que já respondeu.** Para quem aplicou e ficou calado, as 3 reativações
curtas também precisam de template. Hoje é exatamente o caso dos 91 encerrados por inatividade.

### 3.3 Limites da Meta e o que precisa de ajuste antes de submeter

Regras: body ≤ 1024; botão quick reply ≤ 20; body não pode **começar nem terminar** com
`{{n}}`; variáveis em sequência sem pulo; proporção de variável por palavra (body curto com
muita variável é recusado); quick reply ≤ 10 por template; quick reply e URL podem coexistir.

Achados sobre a lista da spec:

1. **T9 "Escolher novo horário" = 21 caracteres.** Estoura. Proposta: "Escolher horário".
2. **T13 áudio**: header AUDIO não existe. Vai como botão URL (padrão `f4_audio*`), 16 variantes
   por curso, ou um template com URL dinâmica (`https://…/{{1}}`) e o sufixo por curso.
3. **T14 / T16** mudam todo mês: o tema e a condição entram como `{{n}}` no meio da frase. Texto
   fixo vencido é o defeito de `final_reagendamento` ("até 30/09").
4. **T2 / T12 "com horários"**: lista de horários em `{{n}}` não pode ter quebra de linha nem
   tabulação (`#132000`; o `follow_20h` já colapsa espaço, `_parametros_do_follow`, `:2295`).
   Os horários vão numa linha só ("hoje 14h15, 16h30 ou amanhã 10h00"), e a escolha é por texto.
   Quick reply não carrega horário dinâmico.
5. **Corpo da Isa: não conferido** (não tive o texto). Antes da submissão, rodar sobre cada corpo:
   `len(body) ≤ 1024`, `not re.match(r'^\s*\{\{', body)`, `not re.search(r'\{\{\d+\}\}\s*$', body)`,
   e `len(texto_botao) ≤ 20` em cada botão.

### 3.4 JSON de `components` PROPOSTO (não submetido)

Corpo em rascunho meu (o texto final é o da Isa). Exemplos com `{{n}}` preenchidos. Todos
`language: pt_BR`. Nenhum começa ou termina com variável. O maior body aqui tem 330 caracteres.

```json
{"name":"nat_a_confirmacao","category":"UTILITY","components":[
 {"type":"BODY","text":"Olá, {{1}}! Sua conversa com a consultora {{2}} está marcada para {{3}} às {{4}} (horário de Brasília). Ela vai te ligar aqui pelo WhatsApp. Pode confirmar que estará disponível?","example":{"body_text":[["Ana","Victória","quinta, 09/10","14:30"]]}},
 {"type":"BUTTONS","buttons":[{"type":"QUICK_REPLY","text":"Confirmo"},{"type":"QUICK_REPLY","text":"Preciso remarcar"}]}]}
```

```json
{"name":"nat_a_pedido_confirmacao","category":"UTILITY","components":[
 {"type":"BODY","text":"Oi, {{1}}! Passando para confirmar sua conversa de {{2}} às {{3}} com a consultora {{4}}. Se não for possível, me avise por aqui para eu liberar o horário.","example":{"body_text":[["Ana","amanhã","10:00","Victória"]]}},
 {"type":"BUTTONS","buttons":[{"type":"QUICK_REPLY","text":"Confirmo"},{"type":"QUICK_REPLY","text":"Preciso remarcar"},{"type":"QUICK_REPLY","text":"Não vou conseguir"}]}]}
```

```json
{"name":"nat_a_ultimo_aviso","category":"UTILITY","components":[
 {"type":"BODY","text":"Oi, {{1}}! Ainda não recebi sua confirmação para a conversa de hoje às {{2}}. Sem confirmação até {{3}}, o horário é liberado para outra pessoa. Confirma para mim?","example":{"body_text":[["Ana","14:30","10:30"]]}},
 {"type":"BUTTONS","buttons":[{"type":"QUICK_REPLY","text":"Confirmo"},{"type":"QUICK_REPLY","text":"Preciso remarcar"}]}]}
```

> Na primeira versão, este rascunho e o de `nat_a_ementa` começavam com `{{1}}`, que a Meta
> recusa (regra 3.3). Os dois já foram corrigidos para "Oi, {{1}}! ...". Vale a mesma
> conferência para o texto da Isa.

```json
{"name":"nat_a_ementa","category":"MARKETING","components":[
 {"type":"BODY","text":"Oi, {{1}}! Enquanto a conversa com a consultora não chega, separei a ementa da Pós-Graduação em {{2}} para você já ir conhecendo as disciplinas. É só tocar no botão abaixo.","example":{"body_text":[["Ana","Saúde Mental"]]}},
 {"type":"BUTTONS","buttons":[{"type":"URL","text":"Ementa da Pós","url":"https://drive.google.com/file/d/{{1}}","example":["1tv9smwk9AHcj9TefufQVL1SweoMbhvCj/view"]}]}]}
```

> A URL dinâmica troca 16 templates
> por curso por 1. A alternativa é 16 templates `nat_a_ementa_<curso>`, espelhando `f3_guia*`.

```json
{"name":"nat_a_beneficio","category":"MARKETING","components":[
 {"type":"BODY","text":"Oi, {{1}}! Um lembrete importante: participando da conversa no horário marcado, você garante {{2}}. Até lá!","example":{"body_text":[["Ana","a isenção da taxa de matrícula e um e-book exclusivo"]]}}]}
```

```json
{"name":"nat_ns_d0_corte","category":"MARKETING","components":[
 {"type":"BODY","text":"Oi, {{1}}. Como não recebemos sua confirmação, o horário de {{2}} foi liberado. Ainda dá para conversar com a consultora: pode ser agora, ou você escolhe um novo horário.","example":{"body_text":[["Ana","hoje às 14:30"]]}},
 {"type":"BUTTONS","buttons":[{"type":"QUICK_REPLY","text":"Posso falar agora"},{"type":"QUICK_REPLY","text":"Escolher horário"}]}]}
```

Os demais (T1, T2, T10–T17) seguem o mesmo esqueleto: BODY com `{{1}}` nome no meio da primeira
frase, e o BUTTONS da tabela 3.2. T13 combina dois QUICK_REPLY com um URL:

```json
{"type":"BUTTONS","buttons":[{"type":"QUICK_REPLY","text":"Reagendar"},{"type":"QUICK_REPLY","text":"Posso falar agora"},{"type":"URL","text":"Ouvir o áudio","url":"https://drive.google.com/file/d/{{1}}","example":["<id>/view"]}]}
```

---

## §4 Tabela de gap (spec × código)

| item | estado | onde hoje | o que falta | risco |
|---|---|---|---|---|
| B: 1 pergunta (motivação) → ofertar hoje+amanhã → A | **parcial** | roteiro de 4 etapas `MISSOES` `qualificacao_fluxo.py:179-290`; `PROXIMA` `:368`; abertura `:1232` | etapa inicial direto em `aguardando_motivacao` (já existe no CHECK); template T1 novo (as aberturas atuais perguntam ano/formação); `_fatos:872` com filtro hoje/amanhã | baixo no código; o dado de formação/ano deixa de ser coletado e a consultora pergunta ao vivo |
| B: reativação +30min/+2h/+4h/D+1 9h, parando se responder | **não existe** | só `follow_20h` (desligado) e encerramento 72h | 4 kinds novos; reagendar/cancelar no inbound (o padrão de `_agendar_follow`, `:1987`, serve); templates para quem nunca escreveu (3.2) | lead calado tem janela fechada: sem template, a reativação curta não sai |
| B: "prefere ligação" → avisa SDR | **parcial / inverso** | existe o oposto: `recusa_ligacao` (lead **não** quer ligação) → `_fallback` + notificação + nota `[NAT]` (`:1427-1440`) | a spec descreve quem **quer** ligação. Não é o mesmo caso. Precisa de motivo novo e decidir o destino (SDR ou "Posso falar agora") | confundir os dois rótulos em relatório |
| A: gatilho = reunião nova (LP, agente, **SDR na Exact**) | **parcial** | só LP e agente nascem em `agendamentos` (`agendar.py:285`); lembrete armado em `_gatilho_do_agente` `:570` | ler `/Meetings` (sync por `registerDate`) ou webhook `event.schedule`; criar espelho em tabela própria; casar por telefone (`Meetings.lead.phone` existe) | 26% das reuniões invisíveis (5.3) |
| A: remarcação reinicia | **não existe** | nada | remarcação na Exact = **reunião nova + antiga `Cancelada`** (5.4): tratar como "cancela a régua da antiga, arma a da nova" | 4 lembretes já saíram para reunião remarcada |
| A: confirmação imediata a qualquer hora, com botões | **não existe** | texto livre só no caminho do agente (`_concluir`, `concluir_por_agendamento_externo`) | T3 + payloads + kind; exceção ao silêncio | template UTILITY reclassificado |
| A: +4h ementa / +8h benefício se reunião > 12h | **não existe** | | 2 kinds; condição `slot_inicio - criado > 12h` (84% dos casos) | +8h de agendamento às 15h cai às 23h: silêncio empurra para 8h, colado no pedido de confirmação |
| A: pedido de confirmação (17h véspera manhã / 8h dia tarde) | **não existe** | | kind + regra de horário + domingo | véspera de segunda é domingo (1.6) |
| A: último aviso (8h / 1h antes do corte) | **não existe** | | kind | |
| A: corte (9h / 4h antes): cancela, libera, entra no no-show | **não existe, e "libera" é impossível pela API** | `scheduleAdd` irreversível; `BoxesRemove` recusa box com reunião (FINDINGS §6, §8) | só dá: nota `[NAT]` + aviso à consultora para cancelar e excluir o box na UI (runbook 3.3, dois passos) | horário prometido ao próximo lead continua ocupado na Exact até alguém agir |
| A: exceções (após 17h; < 4h; "ok/👍" = confirmado) | **não existe** | | regra determinística de "confirmado" por texto (lista curta, fail-closed); < 4h = 8 em 30 dias | LLM decidindo "isto é confirmação" viola a decisão 1 se não for contrato fechado |
| A: T-30 só para confirmados | **parcial** | T-30 existe e sai para todos (`lembrete_reuniao` `:1863`); guard `qualificacao_guard.py:329` | condição "confirmado" no guard | sem o espelho do status da Exact, sai para cancelada (2 pendentes agora) |
| A: dúvida simples → responde e repete pedido; outra → pausa + SDR (corte continua) | **não existe** | o agente fica calado em `concluido` (`processar_texto` devolve False, `:1378`) e o fluxo velho está desligado: **hoje a resposta do lead ao T-30 não é tratada por ninguém**, só gera `new_message` ao dono (`main.py:766-781`) | etapa/estado do Fluxo A que escuta; contrato do LLM para "dúvida simples" | corte valendo com o humano no meio: cancelar reunião de quem está conversando com o SDR |
| A: reunião cancelada/remarcada pela equipe no CRM → para tudo | **não existe** | `agendamentos.passo` nunca sai de `agendado` | espelho de status (sync ou webhook) + cancelamento de todos os kinds | é o bloqueio 1 |
| NS: gatilho (consultora marca no CRM; corte) | **não existe** | | `event.schedulenotheld` (não testado) ou leitura de `Cancelada`, que é ambígua | sem o webhook, "Cancelada" dispara no-show em quem só remarcou |
| NS: régua D0+1h, +8h, D1, D2, D3, D5, D7, D8 → funil SDR | **não existe** | | 8 kinds; após D8, nota `[NAT]` e o follow por estágio continua com o SDR (decisão 8) | a régua sai junto com `follow_estagio` para o mesmo lead (2 réguas no mesmo número) |
| Parada: qualquer texto/áudio/figurinha pausa todas as réguas | **parcial** | inbound chega a `processar_texto_agente` com `content` (texto, `media:` para áudio e figurinha, `botao:` para clique) (`main.py:753`); o padrão "inbound cancela/reagenda" existe (`:1401-1412`) | um `cancelar_reguas(wa_id)` que cancele os kinds A/B/NS; hoje `cancelar(kind, wa)` é por kind (`nat_scheduler.py:233`) | esquecer um kind = mensagem depois de o lead já ter falado |
| Parada: "não tenho interesse" encerra e registra motivo | **parcial** | `higiene_disparo.PADRAO_RECUSA` (recusa 30d para disparo) | reusar o padrão no inbound do Fluxo A/NS + nota `[NAT]`. Atenção: o padrão **não pode** casar "não há mais interesse" (memória `higiene-disparo-recusa-e-teto`) | |
| Parada: opt-out bloqueia | **parcial** | `131050` pula o disparo (memória `opt-out-da-meta-131050`) | conferir 131050 antes de cada envio da régua; `enviar_nat` não confere | |
| Botão "Posso falar agora" → consultora livre; se ninguém, SDR | **não existe** | `nat_flow` tinha notificação de SDR para `NAT_SIM` (fluxo velho, desligado) | não existe noção de "consultora livre" no Hub: as consultoras são users (Victória id 6) sem presença; a agenda da Exact diz quem tem reunião naquele horário (`_ocupados_na_exact`) | "livre na agenda" não é "disponível agora" |
| Status no CRM (6 status) | **não existe** | nenhum estágio equivalente (5.5); estágio intra-funil não move pela API | nota `[NAT]` padronizada por status (único caminho vivo) | relatório da Exact não filtra por nota |
| Silêncio 20h30–8h, adia para 8h, exceto confirmação imediata | **não existe** | janela única 9h–18h30 seg–sex (`nat_guard.py:121`) | `dentro_janela_envio(kind)` novo (6.5); T-30 hoje não tem janela | trocar a função antiga muda a abertura do agente e o fluxo velho junto |
| SDR manda mensagem manual quando assume | **existe** | `/send/text`, `/send/template`, `/send/media` chamam `_silenciar_agente_apos_envio_manual` (`routes.py:207`, `:293`, `:344`, `:405`) | `silenciar` só mexe em `nat_qualificacao_state` (`:1058`); precisa também cancelar as réguas A/B/NS | régua continuando depois de o SDR assumir |

---

## §5 Medições contra a Exact (Fase 5)

Helper usado (token lido do `.env`, nunca impresso):

```bash
T=$(grep ^EXACT_SPOTTER_TOKEN= backend/.env | cut -d= -f2-)
curl -s -G -w "\n[HTTP %{http_code}]\n" -H "token_exact: $T" \
  "https://api.exactspotter.com/v3<path>" --data-urlencode '<param>'
```

### 5.1 Cancelar reunião

```
GET /$metadata                                  -> HTTP 200, 64 177 bytes, 107 EntitySets
<Action>/<Function> no documento                -> 0
EntitySets com Meeting|Schedul|Box|cancel|show:  Boxes, BoxesAdd, BoxesUpdate, BoxesRemove,
                                                 Meetings, ScheduleAdd, MeetingSettings,
                                                 MeetingQuality, MeetingQualitySQL
ReuniaoODataDTO (Meetings): lead, salesRep, user, type, registerDate, meetingType, meetingDate,
                            startTime, finalTime, managerDescription, sdrDescription, reference,
                            meetingFeedbackUrl, score, qualificationDate, id
ScheduleAddODataDTO:        leadId, boxId, stageName, salesRepEmail
```

**Não existe** `MeetingsUpdate`, `scheduleCancel`, `scheduleRemove`, PATCH/PUT de Meeting, nem
qualquer Action. `Meetings` só tem leitura documentada. **Liberar o horário só é possível com a
consultora cancelando a reunião e excluindo o box na UI** (runbook 3.3). O Hub pode no máximo
gravar uma observação. Mudar estágio dentro do funil também não dá (1.8). **Isto muda a spec e
vai para a Isa (§8, pergunta 1).** O `PUT/POST` em `Meetings` não foi tentado: é escrita, fora
do escopo.

**Achado que muda o desenho**, também no `$metadata`: `WebhookEvent`, `WebhooksAdd`,
`Webhooks`, `WebhooksDelete`.

```
GET /WebhookEvent -> HTTP 200
 9 event.schedule      14 event.reschedule     15 event.cancelschedule
33 event.scheduleunchecked                     34 event.schedulenotheld
(+ 23 eventos de lead/atividade/ligação)
GET /Webhooks     -> HTTP 200 {"value":[]}      <- nenhum webhook cadastrado
```

### 5.2 Status de reunião

```
GET /Meetings?$filter=startTime ge '2026-09-07'&$top=500        -> HTTP 200, 249
GET /Meetings?$filter=registerDate ge 2026-09-07T00:00:00Z&$top=500 -> HTTP 200, 218
união por id: 249 | type: Cancelada 155 · Concluido 73 · Vigente 21
```

Registro completo de uma reunião passada (lead e textos pessoais omitidos):

```json
{"type":"Concluido","registerDate":"2026-09-04T16:06:50.4609863Z","meetingType":"Online",
 "meetingDate":"2026-09-08","startTime":"2026-09-08T18:30:00.0000000",
 "finalTime":"2026-09-08T18:50:00.0000000","managerDescription":null,
 "sdrDescription":"<resumo da ligação do SDR, omitido>","reference":null,
 "meetingFeedbackUrl":"https://app.exactspotter.com/reuniao/NDc0NTYyOQ2","score":null,
 "qualificationDate":null,"id":4745629,
 "lead":{"id":51705390,"name":"<omitido>","site":"","phone":"<omitido>"},
 "salesRep":{"id":415967,"name":"Victória","lastName":"Amorim","email":"comercial@cenatcursos.com.br","active":true},
 "user":{"id":443275,"name":"Thobias","lastName":"França","email":"sdr@cenatsaudemental.com","active":true}}
```

**Há campo de resultado (`type`), mas não há valor de no-show**: são só 3 valores.
`Vigente` com data passada = reunião sem feedback (12 casos), e é o que `GET /PendingFeedbacks`
lista (HTTP 200; `meetingId, leadId, stageName, sellerName, date`; atenção: ali `date` vem em
**UTC de verdade**, `2026-09-14T20:15:00Z` para uma reunião das 17h15 SP). `Cancelada` cobre
cancelamento prévio, remarcação e falta, sem data de cancelamento.

**O gatilho "consultora marca no-show no CRM" não é detectável por polling.** Alternativas, em
ordem: (a) webhook `event.schedulenotheld`, a confirmar com teste controlado (cadastrar
webhook é escrita, por isso fica para a sprint com aprovação); (b) botão "não compareceu" no
Hub; (c) a consultora mover o lead para um estágio novo, que o sync já detecta
(`exact_stage_events`).

### 5.3 Reuniões criadas fora do Hub

O mesmo `GET /Meetings` com filtro de data lista **todas**, inclusive as da SDR, com `lead.id`,
`lead.phone`, `salesRep.email`, `startTime` e `registerDate`. Atenção: `user` é sempre o dono do
token (Thobias) e **não diz quem marcou**. O marcador do Hub é
`managerDescription` começando com "Agendamento LP —" (`agendar.py:389`).

Casamento das 249 reuniões com `agendamentos` (sem teste):

| como casou | marcador LP | qtd |
|---|---|---|
| `meeting_id` | sim | 158 |
| `lead_id` (lead do Hub, reunião nova) | não | 25 |
| `lead_id` | sim | 2 |
| **não está no Hub** | não | **57** |
| não está no Hub | sim | 7 (provavelmente teste) |

Das 64 fora do Hub: `Concluido` 38, `Cancelada` 24, `Vigente` 2; todas têm telefone. **Dá para
o sync descobri-las** (`$filter=registerDate ge <cursor>`, sempre com `$filter`, FINDINGS §5) e
criar o espelho para o Fluxo A. O webhook `event.schedule` faria o mesmo sem polling.

### 5.4 Remarcação

**O `meeting_id` muda.** Evidência:

- 0 de 158 reuniões do Hub têm `startTime` diferente do `slot_inicio` gravado: a Exact não
  remarca no mesmo id.
- 22 leads têm 2 ou mais reuniões. Padrão sempre igual: a primeira (marcador LP) vira `Cancelada`,
  e uma nova, sem marcador, é registrada depois. Exemplos: lead 51734704 → 4746234 Cancelada
  (07/09 13h30) + 4746597 (09/09 09h50); lead 51747320 → 3 reuniões, duas Cancelada e a terceira
  Concluido.

"Remarcação reinicia o fluxo" = **detectar reunião nova no mesmo telefone/lead, cancelar a
régua da antiga e armar a da nova**. Não há evento de "data mudou" no polling. O webhook
`event.reschedule` existe, mas não foi testado.

### 5.5 Estágios

```
GET /Stages?$filter=funnelId eq 18535 -> HTTP 200, 14
 1 'Entrada'(129959)  2 'Follow 1'(129985)  3 'Follow 2'(129984)  4 'Follow 3'(129983)
 5 'Follow 4'(129955) 6 'Follows 5'(129967) 7 'Follows 6'(174517) 8 ' Follows 7'(174516)
 9 'Follows 8'(174515) 10 ' Follows 9'(174514) 11 'Telefone incorreto'(198498)
12 'Pre Qualificado'(131957) 13 'Reagendamento - IA'(197254, gate 3) 14 'Agendados'(133409, gate 2)
GET /Stages?$filter=funnelId eq 18537 -> 1 '-'(133413, gate 2) 2 'Em Negociação' 3 'Contratos Gerados' 4 'Vendidos' 5 'Economia '
```

Nenhum dos 6 status existe. A etapa 1 do 18537, antes `Agendados` (FINDINGS §14), hoje se chama
`-`. Mapeamento proposto:

| status da spec | o que existe | proposta |
|---|---|---|
| Agendado – aguardando confirmação | `Agendados` (133409) | estágio = `Agendados` (o `scheduleAdd` já põe) + nota `[NAT] Aguardando confirmação` |
| Confirmado | nada | nota `[NAT] Confirmado em dd/mm hh:mm` |
| Remarcado | nada | nota `[NAT] Remarcado para dd/mm hh:mm` |
| Cancelado pelo lead | nada | nota + pedido de cancelamento à consultora |
| Cancelado – sem confirmação | nada | nota + pedido de cancelamento à consultora |
| Aguardando humano | `Reagendamento - IA` (197254) é o mais próximo | nota; mover estágio **não é possível pela API** |

Criar estágios novos é configuração na UI da Exact, e mover para eles só manualmente. Por isso
a nota é o único status que o Hub consegue gravar sozinho.

### 5.6 Observação com marcador

Sem escrita nova nesta sessão. O caminho atual está vivo:

```
journalctl -u cenat-backend --since 2026-09-27 | grep -c "📝 exact_note"  -> 522
journalctl ... | grep "❌ exact_note"                                     -> 2 (ReadTimeout, 30/09 15:00)
GET /ListTimeline(51902367) -> HTTP 200
  2026-10-06T20:13:28Z autor 415967 len=106
  '[NAT] Follows 6 enviado pela IA em 06/10 17:13 (template mansagem_follows6). [Comentário inserido via API]'
```

"Confirmado em dd/mm hh:mm" tem 32 caracteres e cabe com folga. O teto do `text` do
`timelineAdd` **não foi medido** (precisaria de escrita); a maior nota no ar tem cerca de 110
caracteres.

---

## §6 Proposta de desenho (para aprovação, não implementar)

### 6.1 Kinds novos em `nat_scheduled_actions`, sem DDL

`kind` é `VARCHAR(40)` sem CHECK (`models.py:559`; só `status` tem CHECK). Cabe sem migração.
**Restrição que define os nomes:** `uq_nat_sched_pendente_por_contato (kind, contact_wa_id) WHERE
status='pendente'` (`migrate_nat_sprint3.py:135`), e `agendar()` cancela o pendente do mesmo par
antes de inserir (`nat_scheduler.py:205`). Logo, **cada degrau precisa de kind próprio**: um
`noshow` genérico com o degrau no payload faria o D1 apagar o D0+8h.

```
reativ_b_30m  reativ_b_2h  reativ_b_4h  reativ_b_d1_9h
confirm_a_imediata  confirm_a_ementa_4h  confirm_a_beneficio_8h
confirm_a_pedido  confirm_a_ultimo_aviso  confirm_a_corte  (lembrete_reuniao segue)
noshow_d0_1h  noshow_d0_8h  noshow_d1  noshow_d2  noshow_d3  noshow_d5  noshow_d7  noshow_d8
```

Todos com handler que **relê tudo** (padrão do módulo) e `AcaoIgnorada` com motivo. Um módulo
novo entra em `MODULOS_DE_HANDLERS` (`nat_scheduler.py:95`). Consequência do índice: uma pessoa
com duas reuniões futuras ao mesmo tempo terá a régua da segunda substituindo a da primeira.
Isso é aceitável (é remarcação na prática) e precisa ficar escrito.

### 6.2 Onde guardar confirmação, cancelamento e no-show (precisa de aprovação de DDL)

Não em `agendamentos`: ela não enxerga as 26% de reuniões feitas na Exact. Não em `exact_leads`
(decisão 2). Proposta: **tabela nova `reuniao_status`**, uma linha por `meeting_id` da Exact:

```
meeting_id BIGINT PK, lead_id BIGINT, telefone_chave VARCHAR(10), slot_inicio TIMESTAMP (SP),
sales_rep_email, origem ('hub'|'exact'), agendamento_id BIGINT NULL,
exact_type VARCHAR(20), exact_type_visto_em TIMESTAMP,
confirmado_em, confirmado_por ('botao'|'texto'), cancelado_em, cancelado_motivo,
noshow_em, regua_encerrada_em, regua_encerrada_motivo, created_at, updated_at
```

Alimentada pelo sync de `/Meetings` (ou webhook) e pelo `agendar()`. O guard do T-30 passa a ler
`exact_type = 'Vigente' AND confirmado_em IS NOT NULL`.

### 6.3 Payloads e roteamento

Payloads novos com prefixo por mensagem, não por intenção (mesma regra de `nat_copy.py:14-24`):
`A_CONF_SIM`, `A_CONF_REMARCAR` (T3); `A_PED_SIM`, `A_PED_REMARCAR`, `A_PED_NAO` (T6);
`A_ULT_SIM`, `A_ULT_REMARCAR` (T7); `NS_D0_AGORA`, `NS_D0_HORARIO` (T9); `NS_1H_*` (T10),
`NS_8H_*` (T11), e assim por diante.

Com payload distinto por template, o **payload já distingue T3/T6/T7/T9/T10**. O `context.id`
(já gravado em `nat_button_events`) serve para a segunda checagem: o wamid de origem pertence à
reunião **atual** dessa pessoa? Um "Confirmo" num T3 de reunião remarcada não pode confirmar a
nova. Isso exige gravar o wamid enviado junto do `meeting_id` (em `messages` já fica o
`wa_message_id`; falta o vínculo com a reunião, que vai no payload da ação ou na tabela 6.2).

Fallback por texto (clique sem payload) só se a etapa da régua eliminar a ambiguidade, como faz
`_payload_do_evento` (`nat_flow.py:602`).

### 6.4 "Lead respondeu com texto livre pausa TUDO"

Precedência no webhook (`main.py:750-764`): hoje é agente → fluxo velho. Proposta:

1. **Antes** do agente: `regua_de(wa_id)`. Se há régua A/B/NS ativa para a pessoa (tabela 6.2),
   a régua é dona do inbound.
2. Clique com payload conhecido → handler determinístico (confirma, remarca, "posso falar agora").
3. Qualquer outro inbound (texto, `media:` de áudio/figurinha, clique desconhecido) →
   `cancelar_reguas(wa_id, motivo)`: um laço sobre os kinds A/B/NS chamando
   `nat_scheduler.cancelar(kind, wa_id)` (`:233`), mais notificação ao dono. **Exceção da spec:**
   o `confirm_a_corte` **continua** pendente ("o corte continua valendo"). É um kind fora do laço.
4. `silenciar` (`qualificacao_fluxo.py:1058`) e `_silenciar_agente_apos_envio_manual`
   (`routes.py:207`) chamam o mesmo `cancelar_reguas`: SDR assumiu, régua para (decisão 4).

Dúvida simples respondida pelo LLM entra aqui com contrato JSON fechado
(`{"tipo":"duvida_simples"|"outro","resposta":...}`, fail-closed para `outro`), sem decidir
fluxo (decisão 1).

### 6.5 Janela de silêncio

**Não substituir** `dentro_horario_comercial`: a abertura do agente e o fluxo velho dependem
dela, e o follow por estágio tem a própria decisão. Criar `dentro_janela_envio(kind, quando)` e
`proxima_janela_envio(kind, quando)` em `nat_guard.py`:

- padrão 08h00–20h30, **todos os dias**;
- `confirm_a_imediata` → sempre dentro;
- regra de prazo: se adiar para 8h passar do corte ou do início da reunião, a ação vira
  `AcaoIgnorada` com motivo (o mesmo cuidado do T-30, `:1956-1962`);
- feriado continua sem tratamento (registrado).

### 6.6 Ordem de entrega, cada bloco com flag

| bloco | conteúdo | flag | pré-requisito |
|---|---|---|---|
| **0** | espelho de reunião: sync de `/Meetings` por `registerDate`/`startTime` → `reuniao_status`; T-30 passa a pular `Cancelada`; aviso quando uma reunião do Hub vira `Cancelada` | `REUNIAO_SYNC_ENABLED` | DDL aprovada. **Fecha o bug dos lembretes para reunião cancelada sozinho** |
| 1 | Fluxo A sem corte: T3, T4, T5, T6, T7, T8 só para confirmado, botões, pausa por inbound | `CONFIRMACAO_ENABLED` | bloco 0 + templates aprovados |
| 2 | corte + régua de no-show D0–D8 (gatilho = corte e webhook `schedulenotheld`, se o teste confirmar) | `NOSHOW_ENABLED` | resposta da Isa sobre "liberar o horário"; teste do webhook |
| 3 | Fluxo B enxuto: 1 pergunta, hoje+amanhã, reativações | `FLUXO_B_ENXUTO` | templates T1/T2 e das reativações curtas |

Abrir cada gate em duas etapas (teto 1 com conferência humana, depois o normal), padrão já
adotado (memória `abrir-gate-de-envio-em-duas-etapas`).

---

## §7 Onde a spec contradiz o código ou a Exact

1. **"Cancela e libera o horário"**: impossível pela API (5.1). O Hub não cancela reunião nem
   remove box com reunião (`It is not possible to change a Box with a scheduled meeting`,
   FINDINGS §6). O que o Hub pode fazer no corte: parar a régua A, gravar a nota, avisar a
   consultora e iniciar o no-show. O horário só volta à grade quando a consultora excluir o box
   na UI. Até lá, `disponibilidade` continua vendo o slot ocupado (`_ocupados_na_exact`).
2. **"Consultora marca no-show no CRM" como gatilho**: o `type` não tem no-show (5.2).
   `Cancelada` é ambíguo: 20 das 115 canceladas do Hub são remarcação, e 8 reuniões futuras já
   estão `Cancelada`. Sem o webhook `event.schedulenotheld` (não testado) ou um sinal novo, o
   gatilho não existe.
3. **"Remarcação reinicia o fluxo"**: na Exact remarcação não é edição, é reunião nova (5.4). O
   fluxo reinicia por "reunião nova da mesma pessoa", não por "data mudou".
4. **6 status no CRM**: não existem como estágio, e estágio intra-funil não se move pela API
   (5.5, 1.8). Só dá como nota na timeline.
5. **Reativações curtas do Fluxo B "como texto livre na janela de 24h"**: a janela só abre com
   mensagem do lead (`nat_sender.py:31`). Para quem aplicou e não escreveu, que é o público do
   Fluxo B, a janela está fechada: precisa de template.
6. **"Silêncio 20h30–8h"** contradiz a janela do agente (9h–18h30 seg–sex,
   `nat_guard.py:112-113`), decidida pelo coordenador em 24/08. Liberar fim de semana e 18h30–20h30
   é decisão nova, que precisa ser explícita (vale só para as réguas novas).
7. **"Só hoje e amanhã"** zera a oferta na sexta depois das 16h15 e no sábado (1.7). O runbook
   escolheu janela de 4 dias exatamente para não ter oferta zero (`docs/AGENDAMENTO.md` 2.7.1).
8. **Filtro "graduação + condição de investimento"** que a spec assume na LP não existe (1.1):
   os campos são coletados e ninguém filtra; quem responde "Não" agenda normalmente.
9. **"Prefere ligação → avisa SDR"**: o caso que existe é o inverso (`recusa_ligacao`, lead que
   **não** quer ligação). São dois motivos diferentes.

---

## §8 Perguntas para a Isa (só o que não dá para decidir tecnicamente)

1. **No corte, o horário não é liberado automaticamente** (a Exact não deixa). O que a gente faz:
   (a) avisar a consultora para cancelar na Exact, (b) não fazer corte e só marcar
   "não confirmou", ou (c) outro?
2. **Como a consultora vai dizer que o lead faltou?** A Exact não tem "não compareceu" separado
   de "cancelada". Opções: um evento da própria Exact que vamos testar, um botão no Hub, ou mover
   o lead para um estágio novo.
3. **"Só hoje e amanhã"** zera a oferta na sexta à tarde e no sábado. Nesses casos: ofertar os 2
   próximos dias úteis, ou passar para a SDR?
4. **Fim de semana:** a spec libera sábado e domingo das 8h às 20h30 para todas as mensagens?
   (Hoje o agente não fala no fim de semana.) Para reunião de segunda de manhã, o pedido de
   confirmação sai domingo às 17h?
5. **Quem responde "Não" para graduação ou investimento** entra no Fluxo B, ou sai do fluxo?
6. **"Posso falar agora":** como saber se a consultora está livre naquele minuto? A agenda só
   mostra reunião marcada. Proposta: avisar as duas consultoras e a SDR ao mesmo tempo; quem
   pegar, assume.
7. **"ok / 👍 = confirmado":** fechar a lista do que conta como confirmação (ex.: ok, 👍,
   confirmo, sim, certo, combinado, estarei lá). Fora dela, vai para humano.
8. **Conteúdos mensais** (D3 seminário, D7 condição, D2 áudio por curso, D5 conteúdo): quem atualiza
   todo mês e com quantos dias de antecedência? Template novo leva até 48h na Meta.

---

## §9 Riscos

- **Número da Meta.** Hoje já há `131049` (limite de frequência, 17 em 30 dias, RECON_FOLLOW §2.4)
  e `131050` (opt-out). A régua de no-show soma até 8 mensagens MARKETING em 8 dias por lead, por
  cima do follow por estágio do SDR, que continua (decisão 8). Uma pessoa pode receber as duas
  réguas no mesmo dia. Precisa de trava "uma régua por pessoa" e do teto que foi removido em 21/09.
- **Templates rejeitados ou reclassificados.** UTILITY com botão de remarcar costuma virar
  MARKETING (preço e regra de frequência diferentes). Corpo começando ou terminando com variável
  é recusado (os rascunhos da 3.4 foram conferidos contra isso). Botão de 21 caracteres (T9) é
  recusado.
- **Reunião cancelada que não libera.** Corte sem cancelamento manual = agenda da consultora com
  bloco morto, e a grade do Hub deixa de oferecer o horário. Pior: se a régua de no-show
  oferecer "Escolher horário", o lead pode pegar outro slot enquanto o antigo segue ocupado.
- **Lembrete para reunião cancelada**, já acontecendo: 2 pendentes agora (959 hoje 14:00,
  945 amanhã 13:15) e 4 já enviados para reuniões remarcadas. Sem o bloco 0, a confirmação, o
  pedido e o corte herdam o mesmo defeito, multiplicado por 6 mensagens.
- **Feriado** continua sem tratamento (`nat_guard.py:136`): o corte das 9h de um feriado cancela
  a reunião de quem não confirmou num dia em que ninguém trabalha.
- **Webhook da Exact não testado.** Formato do payload, latência, retry e autenticação são
  desconhecidos. O desenho do bloco 0 por polling não depende dele; o no-show depende.
- **Rate limit da Exact** (30 req/20s, global do token): um sync de `/Meetings` a cada 10 min
  divide a cota com o sync de leads (~20 páginas por ciclo) e com a LP.
- **Duas reuniões futuras da mesma pessoa:** o índice único por `(kind, contato)` faz a régua da
  segunda substituir a da primeira (6.1).

---

## Fechamento

```
git status (antes do commit do relatório):
  ?? RECON_CONFIRMACAO_NOSHOW_20261007_REPORT.md
  ?? backend/fix_status_orfao_webhook.py        (pré-existente, não tocado)
```

Nenhum código, banco, template ou configuração alterado. Nenhuma escrita na Exact nem na Meta.
Consultas SQL com `default_transaction_read_only=on` (a tentativa de `CREATE TEMP VIEW` foi
recusada pelo próprio Postgres, que é a prova).
