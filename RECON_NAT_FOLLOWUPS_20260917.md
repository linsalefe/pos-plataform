# RECON_NAT_FOLLOWUPS_20260917 — os quatro pontos da Isa

**Somente leitura.** Nenhum UPDATE, envio ou deploy nesta investigação. Rodado em 17/09/2026
depois de `PAUSA_QUALIFICACAO_20260917_REPORT.md` (o agente já estava pausado quando as
consultas abaixo rodaram; onde isso muda a leitura, está dito).

Predicado de lead de teste: `relatorios.PREDICADO_TESTE` (`relatorios.py:216`), aplicado sobre
`exact_leads.name`. Chave de telefone tolerante ao 9º dígito: espelho de `relatorios.chave_sql`
(`:219-232`). Relógios: `messages.timestamp`, `agendamentos.created_at`, `disparo_skip.quando`
e `nat_scheduled_actions.run_at` são SP naive; `nat_qualificacao_state.created_at/updated_at`
e `exact_leads.register_date` são UTC (convertidos com −3h onde aparecem).

---

## Bloco 1 — Follow-ups: quem manda, quem pula, e por quê

### 1.1 Quem manda "Follow 1 / Follow 2 / template A / guia / áudio"

**É um humano clicando, não um job.** Não existe régua automática lendo etapa do funil.

- A tela Automações (`frontend/src/app/automacoes/page.tsx`) lista `exact_leads`, o SDR
  filtra por estágio (`stageFilter`, `:116`/`:452`), marca leads (`selectAll`, `:123`) e
  aperta enviar → `POST /exact-leads/bulk-send-template` com `origem_envio: 'campanha'`
  (`:493-501`). O botão de um lead só (`handleSingleSend`, `:558-574`) chama a mesma rota com
  `origem_envio: 'individual'`.
- O "disparo agendado" (`scheduled_messages_job`, `main.py:206-238`, roda a cada 60 s) só
  dispara linhas de `scheduled_messages` cuja hora chegou, com a lista de `lead_ids` **fixada
  no momento em que alguém agendou**. Ele não recalcula nada. **Está morto na prática: 4
  linhas na tabela, todas de 09-11/06/2026, 3 delas com erro de parâmetro.** Nada agendado
  desde então.
- Toda campanha desde 01/09 tem `sent_by = 5` (Thobias). Antes de 01/09 `sent_by` é NULL
  (S6-1 só passou a gravar a partir dessa data) — **não é possível separar campanha de
  envio individual antes de 01/09.**

Periodicidade: a que o SDR escolher. Volume de templates humanos/campanha por dia (fora os
do agente):

| dia | templates | contatos | | dia | templates | contatos |
|---|---|---|---|---|---|---|
| 24/08 | 54 | 52 | | 03/09 | 10 | 9 |
| 25/08 | 93 | 91 | | 04/09 | 8 | 5 |
| 26/08 | 80 | 79 | | 08/09 | 10 | 8 |
| 27/08 | 31 | 31 | | 09/09 | 2 | 2 |
| 28/08 | 77 | 77 | | 10/09 | 22 | 22 |
| 29/08 | 95 | 95 | | 11/09 | 3 | 3 |
| 31/08 | 85 | 85 | | 14/09 | 4 | 4 |
| 01/09 | 3 | 3 | | 15/09 | 19 | 19 |
| 02/09 | 59 | 55 | | 16/09 | 11 | 10 |

A queda de ~80/dia para ~10/dia coincide com o deploy da higiene S6-2 (01/09, `9ecbf07`) — e
com o que o SDR passou a selecionar. Os dois efeitos não são separáveis pelo banco.

### 1.2 Todas as razões de pulo em `bulk_send_template` (`exact_routes.py`)

Antes de qualquer regra por lead, a rota inteira aborta (HTTP 400/404) se: template é a
boas-vindas (`welcome_guard.bloquear_se_boas_vindas`, `:322`), os leads cruzam mais de um
funil (`:331-333`), ou o canal não existe (`:338`). Por lead, na ordem em que rodam:

| # | regra | critério exato | individual | campanha / agendado |
|---|---|---|---|---|
| 0 | sem telefone | `phone1` vazio após `format_phone` (`:365-369`) — **não grava em `disparo_skip`** | pula | pula |
| a | `recusa` | inbound nos últimos **30 dias** casando `PADRAO_RECUSA` (`higiene_disparo.py:46-57`): "não tenho interesse", "sem interesse", "não desejo", "desisti" (não precedido de "não"), "não quero a pós/receber/dar continuidade"… | **pula** | pula |
| b | `teto` | **≥ 3 templates outbound com `status <> 'failed'` nos últimos 7 dias**, contando os do agente junto (`:98-115`, `TETO_TEMPLATES=3`, `JANELA_TETO=7d`) | não roda (`aplicar_teto=not individual`, `:437-438`) | pula |
| c | `nat_ativa` | `nat_qualificacao_state.etapa ∈ ETAPAS_QUALIFICACAO_ATIVAS` nas duas grafias (`:448-459`) | não roda | pula |

Ordem (a) → (b) → (c) é de importância (`:428-431`): quando duas batem, o SDR lê a recusa.
A regra (c) olha **só a etapa**; não consulta `contacts.ai_active` (ver Bloco 2). Em
`individual` nenhuma das três roda além da recusa, mas o envio bem-sucedido chama
`_silenciar_agente_apos_envio_manual` (`:592` → `routes.py:207`) e transfere o agente.

### 1.3 Medição desde 24/08

`disparo_skip` **só existe desde 02/09 18:37** (criada na S6-2). Pulos entre 24/08 e 02/09:
**não mensurável — a tabela não existia; o filtro `nat_ativa` de 28/08 só imprimia no log.**

| regra | pulos | leads | dias |
|---|---|---|---|
| teto | 44 | 44 | 02/09 (43) · 14/09 (1) |
| nat_ativa | 35 | 27 | 02/09 (16) · 14/09 (9) · 16/09 (10) |
| recusa | 6 | 6 | 02/09 (5) · 16/09 (1) |

Por hora, cruzado com os envios: 02/09 18h — 47 enviados + 64 pulados (111 selecionados);
14/09 12h — 4 enviados + 10 pulados; 16/09 14h — **6 enviados + 9 `nat_ativa` + 1 `recusa`
= 16**, que é exatamente o disparo em Follow 2 que a Isa descreveu. As campanhas de 10/09
(21) e 15/09 (19) não pularam ninguém.

### 1.4 Linha do tempo da Marina (`+55 86 ****-2810`, lead 51514285, estágio "Reagendamento.")

Sem estado do agente (registrada 24/08 15:42 UTC, antes do corte 23:16 UTC), sem
`nat_flow_state`, **zero linhas em `disparo_skip`**.

| quando | o quê | quem |
|---|---|---|
| 24/08 12:44 | `nat_boasvindas` ("Sou a Nat… Recebi sua aplicação") — status `read` | NAT velha |
| 24/08 12:54 | inbound: botão "Prefiro outro horário" | lead |
| 26/08 15:51 | template "A nossa consultora Victória tentou o contato…" | humano (sent_by NULL) |
| 27/08 17:47 | template "é o Thobias… nova tentativa de contato" | humano (sent_by NULL) |
| 28/08 16:36 | template "Fiz uma nova tentativa… primeira etapa" | humano (sent_by NULL) |
| 10/09 10:33 | template "é o Thobias… nova tentativa" (mesmo texto de 27/08) | campanha, Thobias |
| 15/09 12:11 | template "é o Thobias… nova tentativa" (mesmo texto) | campanha, Thobias |

**Buraco 28/08 → 10/09:** nenhuma regra explica. A campanha de 02/09 (111 selecionados) não
tem a Marina nem em enviados nem em pulados; as de 03, 04, 08 e 09/09 tampouco. **Ela não
foi selecionada.** (Se tivesse sido em 02/09, o teto a pegaria — 3 templates em 26-28/08 —
e a linha existiria.)

**Buraco 10/09 → 15/09:** idem. 11/09 (3 envios) e 14/09 (4 envios + 10 pulos) não a
incluem. Não foi selecionada.

O "espaçamento irregular" da Marina é o espaçamento das seleções manuais. Nada a pulou.

### 1.5 Linha do tempo do Roberto Augusto (`+55 41 ****-3643`, lead 51851115, Follow 2)

Lead registrado 12/09 20:42 UTC, `welcome_status='skipped'` ("agente assumiu a abertura").

| quando | o quê |
|---|---|
| 14/09 09:00 | abertura T3 `nat_abertura_sem_formacao` (agente) — `delivered` |
| 14/09 09:46-09:47 | 4 inbounds ("Musicoterapeuta", "Final de 202", "2022", "Atuo… CAPS em Curitiba") e 4 respostas do agente; **duas respostas em 2 s para "Final de 202"/"2022"** |
| 14/09 09:47 | agente pergunta a motivação → etapa `aguardando_motivacao`. Lead nunca respondeu |
| 14/09 12:52 | **pulado** `nat_ativa` (template `mensagem_flow`, campanha) |
| 15/09 05:47-05:49 | `follow_20h` (ação 2314) **falhou 3×** — `TypeError` (ver Defeito 1) |
| 16/09 14:22 | **pulado** `nat_ativa` (template `mensagens_flows2`, campanha) |
| 17/09 09:47 | `encerrar_inativo` (72 h) → `encerrado` / `inatividade` |

Enquanto o Roberto esteve em `aguardando_motivacao` (14/09 09:47 → 17/09 09:47): o agente não
fez o follow (bug), o humano não pôde disparar (regra c), e ninguém respondeu pela tela.
Três dias de silêncio de todos os lados.

---

## Bloco 2 — A trava `nat_ativa` vs "IA Desligada"

### 2.1 O que o toggle grava e quem mais grava

`contacts.ai_active` (`models.py:39`). Escritores:

| quem | arquivo:linha | valor | quando |
|---|---|---|---|
| toggle da tela de Conversas | `ai_routes.py:97` (`PATCH /ai/contacts/{wa_id}/toggle`) | o que o SDR clicou | clique |
| Kanban → "aguardando_humano" | `kanban_routes.py:135` | False | mover card |
| boas-vindas automática | `exact_spotter.py:348,355` | True | ao enviar `nat_boasvindas` |
| **o agente, ao criar o contato** | `qualificacao_fluxo.py:495` | **False** | abertura |

`nat_guard.py`, `nat_routes.py` (Assumir conversa) e `qualificacao_fluxo.silenciar` **não
escrevem `ai_active`**: o takeover humano grava `nat_qualificacao_state.transferido_motivo =
'outbound_manual_sdr'` / `'assumido_sdr'` e `dados_extras.assumido_por` (`:1040-1049`), em
outra tabela. Não há coluna nem log de quem/quando mudou `ai_active` — o `PATCH` só grava o
booleano.

### 2.2 Quem lê `ai_active`

**Ninguém do lado NAT/agente.** `grep ai_active backend/app/*.py`: além dos escritores acima,
só `routes.py:432-585` (listagem de contatos para a tela) e o motor legado de IA em
`main.py:737` — **comentado**. Nem a trava do disparo (`exact_routes.py:448-459`) nem o
handler de inbound (`qualificacao_fluxo.processar_texto`, `:1272-1274`) consultam a coluna.

O rótulo "IA Ativa / IA Desligada" (`conversations/page.tsx:1601`) descreve um motor que
está desligado no código. Para o agente, ele é decorativo.

Caso Roberto: `contacts` criado 14/09 12:00:51 UTC **pelo próprio agente, com
`ai_active=False`** (`:495`), no mesmo instante do estado. A tela mostrou "IA Desligada"
desde o primeiro segundo da conversa com a Nat.

### 2.3 Quantos estavam assim antes da pausa

Sobre os 25 estados ativos que a pausa encerrou (`encerrado_motivo='pausa_operacional_20260917'`):

| `ai_active` | estados |
|---|---|
| false | **24** |
| true | 1 (o lead de teste) |

Sobre todos os 312 estados do agente com contato: 299 `false`, 13 `true`. **"IA Desligada" é
o estado normal de quem o agente atende.**

### 2.4 Por que o Roberto ficou "sem motivo aparente"

Não houve desligamento. O contato nasceu desligado por decisão de código
(`qualificacao_fluxo.py:491-495`: "marcar o lead como 'a IA genérica responde' seria pedir
dois robôs na mesma thread no dia em que aquele trecho do webhook voltar"). Não existe regra
em `nat_guard` que desligue `ai_active`; `silenciar` transfere o agente sem tocar na coluna.

---

## Bloco 3 — "Vídeo ou mensagem" quando o lead recusa ligação

### 3.1 Origem da frase

**É o LLM, dentro da etapa `ofertando_agenda`.** A frase não existe em `nat_copy.py`, em
`MISSOES` (`qualificacao_fluxo.py:179-296`) nem em `PROMPT_BASE` (`qualificacao_llm.py:119-170`)
— `grep -i "vídeo|por mensagem|contato da consultora"` nos três não encontra nada. A mensagem
da Míriam tem `nat_etapa='qualif_conversa'`, o marcador de "fala livre gerada pelo LLM"
(`qualificacao_guard.py:64`). `typeMeeting` da Exact é fixo `"web"` (`agendamento/grade.py:93,160`)
e nunca vira opção de texto.

E a frase **contradiz duas regras que já estavam no prompt desde 24/08** (`d720ebb`):
"NUNCA PEÇA PERMISSÃO PARA AGIR… isso vale inclusive para passar o contato à consultora"
(`qualificacao_llm.py:129`) e "VOCÊ NUNCA OFERECE TRANSFERÊNCIA… nunca como pergunta"
(`:151`). O modelo desobedeceu; nada no código validou a mensagem contra essas regras
(`_validar` checa o contrato JSON, não o conteúdo).

### 3.2 Saídas possíveis de `ofertando_agenda` quando o lead recusa ligação — como o código está

A missão (`qualificacao_fluxo.py:272-288`) prevê três ramos: (1) escolheu um dos 5 →
`acao="agendar_slot"`; (2) "JÁ TIVER PEDIDO noite ou fim de semana" → avisa que vai passar
o contato e `acao="transferir_humano"`; (3) "qualquer outro caso" → repete o convite ("diga
que dia e período prefere"). **"Não quero ligação" não está em nenhum ramo.** Não há
instrução para recusa de canal — o modelo escolhe sozinho, e a regra geral do prompt
(`:147-149`: "pedir horário, querer agendar… NADA disso é motivo de transferência") o empurra
para continuar oferecendo. As três saídas de código depois da resposta são: `agendar_slot`
→ `_agendar` (`:1405`); `transferir_humano` → `_fallback`; senão a etapa vira
`escolhendo_slot` (`:1401`) e a próxima mensagem cai em `MISSOES[ESCOLHENDO_SLOT]`.

### 3.3 Quantos receberam a oferta e o que escolheram

Busca em outbound desde 24/08 por "por vídeo" / "por video" / "contato da consultora":
**1 mensagem, 1 lead** — a Míriam, 01/09 15:30:59. Ela respondeu "mensagem"; o agente
respondeu "vou agendar por mensagem com a consultora" e **reofereceu os mesmos 5 horários**;
ela não respondeu mais; `encerrado`/`inatividade` em 04/09. **Nenhum agendamento.**

Recusas de ligação no inbound desde 24/08 (busca por "não quero ligação", "por mensagem",
"sem ligação", "prefiro mensagem"): **3 leads**.

| lead | disse | o agente fez |
|---|---|---|
| Ana (`+55 47 ****-8038`), 31/08 12:43 | "Não consigo falar por ligação, o ideal é por mensagem" | "vou agendar por mensagem com a consultoria. Qual dos horários…?" → ela: "Pode ser às 09h" → **`_fallback`** (transferido). Sem agendamento. |
| Míriam, 01/09 15:30 | "Não quero ligação" | oferta vídeo/mensagem (acima) |
| Anariele (`+55 64 ****-0807`), 02/09 13:03 | "Vai ser por mensagem? Ou ligação?" | já estava `concluido` (reunião pré-existente) — o agente cala; **ninguém respondeu** |

"Vídeo": 0 escolhas. "Mensagem": 2 (Ana, Míriam), nenhuma virou reunião.

### 3.4 O que iria para a Exact se o lead escolhesse "mensagem"

O mesmo de sempre. `_agendar` (`:1405-1475`) chama `fluxo.agendar` com o slot; o box é
criado com `type_meeting=tentativa.grade.type_meeting` (`agendamento/agendar.py:382`), que
vem da grade e é `"web"` (`grade.py:93`). Não há campo de canal preferido em `agendamentos`
nem no `scheduleAdd`. A consultora veria uma reunião "web" igual às outras — a promessa "por
mensagem" ficaria só no WhatsApp. **Não aconteceu nenhuma vez** (3.3).

---

## Bloco 4 — Duplicidade de agendamento

### 4.1 A guarda, e onde ela está

Existe, em um ponto: `_avancar` (`qualificacao_fluxo.py:1357-1368`). Ao cumprir
`aguardando_motivacao`, relê `_reuniao(estado)`; se há reunião → `_concluir(confirmar=True)`
("Na verdade você já tem horário reservado…", caso Anariele 02/09 13:02); se não →
`ofertando_agenda`. Também na abertura (`:1195-1206`): com reunião, sai o T1
`nat_abertura_agendado` e `agendamento_id` é gravado.

`_reuniao` (`:563-583`) procura **por `agendamento_id` do estado, senão por
`agendamentos.lead_id == estado.exact_lead_id AND passo='agendado'`**. Não olha telefone.
Não olha o estágio "Agendados" da Exact.

**Não há guarda em `_agendar`** (`:1405-1475`): entre oferecer e o lead escolher, uma reunião
criada pela página não é relida; `_reuniao` só é consultado depois (`:1501`) para
concluir.

### 4.2 Por qual gatilho um lead que agendou pelo site ainda recebe abertura

**Pelos dois, e de propósito**: o agente abre para quem agendou (T1 confirma a reunião) e
continua qualificando. A abertura em si não é o defeito. O que deixa a duplicidade passar
é a **chave por `lead_id`**:

1. **Duas aplicações → dois leads na Exact para o mesmo telefone.** A pessoa agenda pela
   página (LeadsAdd cria o lead A, `agendamentos.lead_id = A`), volta ao formulário minutos
   depois e nasce o lead B. O sync enfileira abertura para B; `nat_scheduler.agendar`
   cancela a pendente de A (mesmo `contact_wa_id`) e a que executa carrega `lead_id = B`.
   `_reuniao` busca `lead_id = B` → nada → abertura T3 e, no fim, **oferta de agenda para
   quem já tem reunião**. Medido: **149 telefones com ≥ 2 leads desde 24/08 (sem testes),
   41 deles com reunião marcada, 5 com estado do agente preso ao lead sem reunião.**
2. Reunião marcada pela página **depois** de o agente ter oferecido horários e antes de o
   lead escolher (`_agendar` não relê — 4.1). Nenhum caso medido; é janela de código.
3. Reunião com `lead_id` NULL: **0 dos 126 agendados desde 24/08.** Não é caminho real.

### 4.3 Candidatos medidos (chave DDD + 8 dígitos; agendado antes de o agente chegar à agenda)

| lead | reunião pelo site | lead da reunião | lead do estado | o que o agente fez |
|---|---|---|---|---|
| **Luciana Zola Bahia** (`+55 31 ****-6668`) | 13/09 22:11 → reunião 15/09 09:45 | 51861228 | 51861285 (nasceu 2 min depois) | 14/09 09:31 **ofereceu 5 horários** ("Tenho estes horários disponíveis"); ela: "Nenhum desses consigo" → transferido. 15/09 09:15 recebeu o lembrete da reunião que já tinha. |
| **Elisangela F. S. Silva** (`+55 41 ****-0611`) | 12/09 10:18 → reunião 14/09 10:30 | 51846973 | 51846975 (2 min depois) | abertura 14/09 09:00 (1h30 antes da reunião), follow 15/09 05:01, conversa 15/09 09:35, **ofereceu horários e tentou marcar sexta 10:30** → `AgendamentoFalhou: HTTP 400: Lead is discarded` → transferido. A 2ª reunião só não nasceu porque a Exact recusou o lead B. |
| Brenda R. F. da Silva | 13/09 11:17 | 51857185 | 51857191 | nunca respondeu; `encerrado`. Teria chegado à oferta. |
| Anne Caroline Schlogl | 08/09 16:27 | 51766238 | 51766210 | idem |
| Andrea Cristina Elias | 31/08 10:39 | 51652157 | 51652151 | idem |

Os dois primeiros são o caso da Isa. Não há registro de qual lead ela viu; a SDR pode
conferir pelo telefone.

Fora do agente, mesmo padrão pela própria página: Janice Vianna agendou 05/09 (lead
51734601, reunião 07/09) e de novo 08/09 (lead 51754289, reunião 11/09) — duas reuniões, dois
leads, zero participação do agente. Jacqueline dos S. Freire: 23/08 e 07/09, cursos
diferentes — provavelmente legítimo.

---

## O que precisa de decisão de produto (máx. 5)

1. **Recusa de ligação em `ofertando_agenda`.** Hoje não há ramo; o modelo improvisa
   (3.2). Precisa de uma instrução: transferir? oferecer só WhatsApp? seguir oferecendo
   horário "para a consultora te chamar por mensagem"? — e se a última, o `typeMeeting`
   continua `"web"` (3.4).
2. **`nat_ativa` vs o SDR que quer disparar mesmo assim.** A regra (c) pula por etapa e não
   tem override na tela de campanha (1.2). O caminho previsto é responder por Conversas ou
   usar o envio individual (que transfere o agente). Decidir se isso é o desejado ou se a
   campanha deve poder "assumir" em lote.
3. **O rótulo "IA Ativa/Desligada"** descreve um motor comentado (2.2). Para o agente, o
   estado real está em `nat_qualificacao_state.etapa`. Decidir se a tela passa a mostrar
   a etapa do agente, se o toggle passa a silenciá-lo, ou se some.
4. **Chave de identidade do lead: telefone ou `lead_id`?** A Exact cria um lead por
   aplicação (149 telefones duplicados em 24 dias). Enquanto `_reuniao` casar por `lead_id`,
   a segunda aplicação apaga a reunião da primeira aos olhos do agente (4.2). Casar por
   telefone tolerante resolve o agente; não resolve a Janice (duplicata da própria página).
5. **Follow humano sem régua.** Não existe automação de Follow 1/2 (1.1): a
   "irregularidade" é a agenda de quem seleciona. Decidir se o `scheduled_messages` (morto
   desde junho) volta, se nasce uma régua por estágio, ou se fica manual e a expectativa é
   ajustada.

## O que é defeito claro (máx. 5)

1. **`follow_20h` quebra para todo lead que já escreveu alguma vez.**
   `qualificacao_fluxo.py:2197` faz `ultimo.timestamp >= …`, mas `_ultimo_inbound` (`:1956-1969`)
   devolve o `datetime` cru — `.timestamp` é o método, não o valor →
   `TypeError: '>=' not supported between 'builtin_function_or_method' and 'datetime'`.
   Medido: **60 `falhou`, todos com inbound; 61 `executado`, todos sem inbound**. Desde
   02/09 o follow do agente só alcançou quem nunca respondeu — o oposto do público que
   mais rende (13,7% de resposta, `models.py:509-512`). O Roberto é um dos 60.
2. **Ação `falhou` não grava motivo.** `nat_scheduler.py:439` chama `_finalizar(...,
   ACAO_FALHOU, attempts=…)` sem `motivo`; a exceção fica só no log (que o `echo=True`
   afoga). 60 linhas com `motivo NULL` — o defeito 1 ficou 15 dias invisível no banco
   por causa deste.
3. **`_reuniao` casa por `lead_id`, não por telefone** (`:579`). Duas reuniões oferecidas a
   quem já tinha reunião (Luciana Zola, Elisangela — 4.3); a segunda só não foi gravada
   porque a Exact devolveu 400.
4. **Abertura para quem tem reunião em menos de 2 h.** Elisangela: reunião 14/09 10:30,
   abertura 14/09 09:00 perguntando a formação. `iniciar_qualificacao` não olha a
   distância até a reunião (efeito colateral do 3, mas vale mesmo com o lead certo: T1
   também abre qualificação para quem vai falar com a consultora daqui a pouco).
5. **Duas respostas do agente para dois inbounds em 2 s** (Roberto, 14/09 09:46:33 e
   09:46:34: "Final de 202" e "2022" geraram duas falas, a segunda repetindo a pergunta).
   Sem pool/debounce de inbound por turno; a idempotência (`ultimo_wa_message_id`) é por
   mensagem, não por janela.
