# RECON_FOLLOW_AUTOMATICO_20260927 — follow por estágio da Exact

**Modo: SOMENTE LEITURA.** Nenhum envio, nenhum UPDATE, nenhum deploy. Todas as leituras
foram `SELECT` no Postgres de produção e `GET` nas APIs da Exact (`/v3/Funnels`,
`/v3/stages`, `/v3/LeadStages`, `/v3/Leads`) e da Meta (`/message_templates`).

Data da medição: **27/09/2026**, ~12:45 UTC. Janela padrão: **últimos 30 dias**
(28/08 → 27/09).

## Relógios (vale para tudo o que vem abaixo)

| coluna | fuso |
|---|---|
| `exact_stage_events.observado_em` | **UTC** naive (`server_default now() AT TIME ZONE 'utc'`) |
| `messages.created_at` | **UTC** naive |
| `messages.timestamp` | **SP** naive |
| `exact_leads.register_date` / `update_date` | UTC naive |
| `LeadStages.createdAt` (Exact) | UTC, com `Z` |
| `nat_scheduled_actions.run_at` | **SP** naive |

O cruzamento estágio × mensagem usa `observado_em` contra `created_at` — os dois em UTC.
Usar `messages.timestamp` ali deslocaria tudo 3 h (é o defeito do
[`dashboard_stats`](RECON_RELATORIOS_20260901.md)).

Chave de telefone: espelho de `relatorios.chave_sql` (DDD + últimos 8 dígitos).

---

# Bloco 1 — Estágios do funil na Exact

## 1.1 — Os nomes exatos, e eles não são o que o desenho supõe

`SELECT stage, COUNT(*) FROM exact_leads GROUP BY 1` devolve **32 grafias distintas** em 7
funis. A pergunta "quais são os nove estágios de follow" **não tem resposta única**: cada
funil tem a sua escada, com grafias diferentes.

A fonte de verdade não é `exact_leads` (que só tem o estado de agora): é
`GET /v3/stages`, que dá a lista canônica com `position` e `id`. Para o funil
**18535 = `Pos Graduacao`**, as nove etapas de follow são, **literalmente**:

| pos | id na Exact | grafia exata | len |
|---:|---:|---|---:|
| 2 | 129985 | `Follow 1` | 8 |
| 3 | 129984 | `Follow 2` | 8 |
| 4 | 129983 | `Follow 3` | 8 |
| 5 | 129955 | `Follow 4` | 8 |
| 6 | 129967 | `Follows 5` | 9 |
| 7 | 174517 | `Follows 6` | 9 |
| 8 | 174516 | `` ` Follows 7` `` | 10 |
| 9 | 174515 | `Follows 8` | 9 |
| 10 | 174514 | `` ` Follows 9` `` | 10 |

Ou seja, **três armadilhas de grafia de uma vez**:

1. **Singular até 4, plural de 5 a 9** — `Follow 4` mas `Follows 5`.
2. **Espaço à ESQUERDA em 7 e 9** — `" Follows 7"` e `" Follows 9"`. É o caso
   `Reagendamento` vs `Reagendamento.` outra vez, e é a razão de a lista precisar ser
   copiada byte a byte, nunca digitada.
3. Nenhum acento, nenhum ponto final, nenhum `º`.

`Reagendamento` e `Reagendamento.` **já não existem** no 18535: `/v3/stages` só lista
`Reagendamento - IA` (id 197254, `gateType=3`). Na base, `Reagendamento.` tem 66 eventos até
17/09 e `Reagendamento - IA` começa em 17/09 — a etapa homônima foi substituída naquele dia.
`exact_stage_events` é agora o **único** registro da grafia antiga (ver 1.3).

**Os outros funis têm escada de follow própria, e ela colide.** O funil
**18285 = `Intercambio`** tem `Follow 1` … `Follow 8` **todos no singular**, mais
`` `Ultimo follow (Descarte) ` `` (com espaço à direita). Não tem `Follow 9`.
Um filtro por `stage ~* 'follow'` sem `funnel_id` varre Intercâmbio junto — **703 entradas em
30 dias**, leads que nunca deveriam receber template de pós. Ainda:
`Follow 2 - Vi` / `Follow 3 - Vi` no 20647 (`Reativação - SQL`), e `Follow 1` no 20776
(`CONGRESSO PRESENCIAL`).

Funis, por `GET /v3/Funnels`:

```
18285 | Intercambio              2 617 leads
18535 | Pos Graduacao            4 125
18537 | Pós Graduação - Vendas   1 643
20647 | Reativação - SQL           197
20776 | CONGRESSO PRESENCIAL        97
21007 | Vagas Afirmativas        1 112
25588 | Funil - Isa                110
```

## 1.2 — Como o sync grava a mudança de estágio

`exact_stage_events` (`app/models.py:893`):

```
id             bigint
exact_lead_id  integer   -> exact_leads.exact_id (NÃO é o id local; não há FK)
stage_de       varchar(50)   NULL = primeira aparição do lead
stage_para     varchar(50)
funnel_id      integer
observado_em   timestamp     default now() AT TIME ZONE 'utc'
```

**O INSERT:** `app/exact_spotter.py:469`, dentro de `_registrar_transicao`
(`exact_spotter.py:451`), chamada de dois lugares no laço do sync:

* `exact_spotter.py:531-534` — ramo `existing`: `if existing.stage != lead_data.get("stage")`,
  lido **antes** do `setattr` que sobrescreve. É a transição de verdade.
* `exact_spotter.py:549` — lead novo: evento com `stage_de = NULL`.

O INSERT roda em `begin_nested()` (SAVEPOINT) com `except` largo: um erro aqui **nunca**
derruba o sync, e o evento é perdido com aviso no stdout.

**Registra `de -> para`?** Sim, as duas colunas.
**Registra a hora da Exact ou a do sync?** **A do SYNC.** `observado_em` é o `now()` do banco
no momento em que a passada percebeu a diferença. A hora em que o SDR realmente arrastou o
card **não está** em nenhuma coluna nossa.

**Consequência prática, medida:** a grafia gravada é a que valia **naquele dia**. O `/v3/LeadStages`
da Exact, ao contrário, devolve o rótulo **atual** da etapa — renomear uma etapa reescreve a
história dele. Prova: lead 51421841, 03/09 12:29, a Exact hoje diz
`Follows 8 -> Reagendamento - IA`; nosso evento do mesmo instante diz
`Agendados -> Reagendamento.`.

## 1.3 — Latência e cobertura do sync

* **Intervalo:** `asyncio.sleep(600)` — **10 minutos** (`app/main.py:137`, `sync_job`).
* **Janela:** **NENHUMA.** `fetch_leads_from_exact` (`exact_spotter.py:90`) faz
  `GET /v3/Leads?$top=500&$skip=N&$orderby=Id desc` paginando até a página vir incompleta.
  Sem `$filter`, sem `registerDate`, sem corte por N dias, sem restrição de box.
  `INGEST_FUNNEL_IDS` está **vazio** em produção → ingere **todos** os funis.
  A cada 10 min o laço reescreve as ~9 900 linhas e compara o `stage` de todas.

* **Um lead antigo movido para Follow 7 hoje gera evento? SIM.** Medido: **155 eventos** nos
  últimos 30 dias pertencem a leads com `register_date` anterior a 60 dias.

* **Latência real, medida contra o relógio da Exact** (`/v3/LeadStages` filtrado por
  `createdAt ge 2026-08-28`, cruzado com `exact_stage_events` por `(leadId, destinationStage)`;
  1 259 transições casadas no 18535):

| | |
|---|---|
| p50 | **4,8 min** |
| p90 | **9,5 min** |
| p99 | **10,6 min** |
| máx | **5,3 dias** (3 casos > 1 dia — ver abaixo) |

  A cauda até ~10 min é exatamente o ciclo de 600 s. **Um follow automático por este
  gatilho chega ao lead entre 0 e ~11 minutos depois do arrasto do SDR.**

  Os 3 outliers (> 1 dia): leads 51503724 (`Entrada`→`Follow 3`, 5,3 dias), 51644254 e
  51691740 (`Entrada`→`" Follows 9"`, ~1 dia). **Não diagnosticados** — os três são
  `Entrada -> <follow>` e provavelmente são segunda entrada no mesmo estágio, cuja primeira
  ocorrência caiu fora da janela que baixei. Fica aberto.

* **1,5 % das transições NUNCA geram evento.** Das 1 278 entradas em follow do 18535 que a
  Exact registra desde 28/08, **19 não têm linha correspondente** em
  `exact_stage_events`. A causa foi diagnosticada caso a caso e é sempre a mesma:
  **o SDR move o lead DUAS VEZES dentro da mesma passada de 10 min, e o estágio do meio é
  invisível.** O sync só compara "onde estava" com "onde está".

  ```
  lead 51591580  02/09 18:45
     EXACT : Follow 3->Follow 4@18:45, Follow 4->Follows 5@18:46
     NOSSO : Follow 3->Follows 5@18:54          <- Follow 4 nunca existiu para nós
  lead 51775943  11/09 16:45
     EXACT : Entrada->Follow 1@16:45, Follow 1->Follow 2@16:45
     NOSSO : Entrada->Follow 2@16:55            <- Follow 1 nunca existiu
  lead 52050552  24/09 15:26
     EXACT : Follow 1->Follow 2@15:26, Follow 2->Follow 3@15:28
     NOSSO : Follow 1->Follow 3@15:36           <- Follow 2 nunca existiu
  ```

  Perdidos por estágio: `Follow 1` ×10, `Follow 3` ×2, `Follow 4` ×3, `Follow 2` ×2,
  `Follows 6` ×1, `Follows 8` ×1. **`Follow 1` é o mais atingido** — é o degrau em que o SDR
  passa mais rápido.

* **10 leads a mais do que a Exact tem.** `GET /v3/Leads?$count=true` = **9 891**;
  `SELECT count(*) FROM exact_leads` = **9 901**. São leads apagados/arquivados na Exact que
  ficam no nosso espelho para sempre. Inofensivo para o follow (o `stage` deles nunca muda,
  logo nunca há evento), mas o espelho não é um espelho.

## 1.4 — Volume das entradas e quanto já é mandado na mão

**Entradas em estágio de follow, últimos 30 dias:**

| funil | estágio | entradas | leads | /dia |
|---|---|---:|---:|---:|
| **18535** | `Follow 1` | 208 | 203 | 6,9 |
| | `Follow 2` | 186 | 183 | 6,2 |
| | `Follow 3` | 172 | 172 | 5,7 |
| | `Follow 4` | 163 | 162 | 5,4 |
| | `Follows 5` | 150 | 148 | 5,0 |
| | `Follows 6` | 125 | 125 | 4,2 |
| | `" Follows 7"` | 102 | 102 | 3,4 |
| | `Follows 8` | 83 | 75 | 2,8 |
| | `" Follows 9"` | 66 | 57 | 2,2 |
| | **total 18535** | **1 255** | | **~42/dia** |
| 18285 (Intercâmbio) | `Follow 1`…`Follow 8` | 700 | | ~23/dia |
| 18285 | `"Ultimo follow (Descarte) "` | 3 | | |

**Quanto disso já virou template em até 24 h** — cruzamento por chave de telefone, apenas
**01/09 → 27/09** (26 dias), porque `messages.template_name` só passa a ser preenchido em
01/09 (S6-1): antes disso 259 outbounds de template têm `template_name` NULL e o cruzamento
não sabe dizer qual template era.

| estágio (18535) | entradas | seguidas de template ≤24h | % |
|---|---:|---:|---:|
| `Follow 1` | 174 | 72 | **41 %** |
| `Follow 2` | 156 | 55 | **35 %** |
| `Follow 3` | 133 | 52 | **39 %** |
| `Follow 4` | 136 | 47 | **35 %** |
| `Follows 5` | 125 | 44 | **35 %** |
| `Follows 6` | 109 | 56 | **51 %** |
| `" Follows 7"` | 89 | 35 | **39 %** |
| `Follows 8` | 77 | 34 | **44 %** |
| **`" Follows 9"`** | **63** | **1** | **2 %** |

**É esta a medida do "quanto o SDR mandou na mão": entre um terço e metade.** Automatizar
não é transferir trabalho — é **mais que dobrar** o volume de follows que sai do número
(de ~396 em 26 dias para ~1 062), e **multiplicar por ~60** a despedida do `Follows 9`.

**Qual template segue cada estágio** (mesma janela, ≥3 ocorrências):

| estágio | template que o SDR usa | n |
|---|---|---:|
| `Follow 1` | `mensagem_flow` 22 · `follow_up` 22 · `mensagens_flows2` 8 | |
| `Follow 2` | **`mensagens_flows2` 23** · `follow_up` 18 | |
| `Follow 3` | `mensagem_follow3` 11 · **`f3_guiagrupot2` 11, `f3_guiagestaot5` 4, `f3_guiaescolar` 3, `f3_siteinfantoead` 3** | |
| `Follow 4` | `mensagem_follow4` 28 · `mensagem_follow5` 12 · **`f4_audioorgtrabalho` 7, `f4_audiogestaot5` 3** | |
| `Follows 5` | **`mensagem_follow5` 30** | |
| `Follows 6` | **`mansagem_follows6` 27** · `sdr_tentativa_ligacao` 6 | |
| `" Follows 7"` | `mensagem_follow7` 14 | |
| `Follows 8` | `template_sexta_feira` 27 · `mensagem_follow8` 7 | |
| `" Follows 9"` | (nada; 1 envio, e foi `mensagem_follow3`) | |

E, atravessando **todos** os estágios, `reativaojunho` (233 envios de 18 a 24/09: 52 no
`Follows 8`, 27 no `Follows 6`, 21 no `Follows 7`, 18 no `Follow 1`…). É uma campanha
independente da escada, e é o ruído que suja qualquer leitura de "1 estágio = 1 template".

**Achado:** nos degraus **3 e 4 o SDR não manda um template — manda o template DO CURSO.**
`f3_guia<curso>` (ementa, 14 variantes aprovadas) e `f4_audio<curso>` (áudio do coordenador,
16 variantes). Um `mensagem_follow3` único apaga essa escolha.

**Rajadas: o SDR move em lote.** Distribuição de eventos por passada do sync (18535, 30 d):

| eventos na mesma passada | passadas |
|---:|---:|
| 45 | 1 |
| 33 | 1 |
| 25 | 1 |
| 13 | 2 |
| 10 | 5 |
| 8 | 18 |
| 7 | 20 |

As três maiores:

```
2026-09-18 21:18 UTC (18:18 SP)   45 leads -> " Follows 9"
2026-09-17 21:16 UTC (18:16 SP)   33 leads -> "Follows 8"
2026-09-14 17:53 UTC (14:53 SP)   25 leads -> " Follows 7"
```

**No desenho proposto, 18/09 às 18:18 SP teriam saído 45 `mensagem_follow9` — a despedida,
"encerro aqui meu contato" — em um único instante, 12 minutos antes de o expediente fechar.**
`bulk_send_template` tem `asyncio.sleep(1)` entre envios (`exact_routes.py:601`), então
seriam ~45 s de rajada. A Meta já devolveu 17 × `131049` ("not delivered to maintain healthy
ecosystem") nos últimos 30 dias no volume atual.

**Horário das entradas** (convertido para SP): **1 191 de 1 254 (95 %) caem dentro de
09:00–18:30 seg–sex**. 63 (5 %) caem fora — 6 num sábado, 57 depois das 18:30 numa
segunda/quarta. Respeitar a janela custa adiar 5 % para as 09:00 do dia útil seguinte.

---

# Bloco 2 — Envio de template hoje

## 2.1 — `bulk_send_template`

`app/exact_routes.py:245`, rota `POST /api/exact-leads/bulk-send-template`.

```python
async def bulk_send_template(request: dict,
                             db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(get_current_user))
```

`request` é um dict cru (não Pydantic):

| chave | o que é |
|---|---|
| `template_name` | nome na Meta, obrigatório |
| `language` | default `"pt_BR"` |
| `channel_id` | default `1` (é o único canal que existe) |
| `lead_ids` | **`exact_leads.id` (PK local), NÃO `exact_id`** — obrigatório |
| `param_mappings` | lista `[{type, value}]`, um item por `{{n}}` |
| `parameters` | modo legado (nome, curso) |
| `origem_envio` | `"campanha"` (default fail-safe) ou `"individual"` |

**Como resolve o template pelo nome:** não resolve localmente. `template_name` vai cru para
`send_template_message` → `POST /{phone_number_id}/messages`. A única leitura da Meta é
`fetch_template_body(waba_id, token, template_name, language)` (`exact_routes.py:344`), **uma
vez por lote**, e serve só para gravar o texto renderizado em `messages.content`. Um nome
inexistente só falha no envio, lead por lead.

**Como preenche `{{1}}`** (`exact_routes.py:466-488`), por `param_mappings[i].type`:

| type | valor |
|---|---|
| `lead_name` | `lead.name.split()[0]` → **primeiro nome**, fallback `"Aluno(a)"` |
| `lead_full_name` | `lead.name` |
| `lead_course` | `resolve_course_name(lead.sub_source, db)` — `course_aliases`, fallback tira o prefixo `pos` |
| `sdr_name` | `lead.sdr_name` (dono do lead na Exact), fallback `"Equipe CENAT"` |
| `sdr_logado` | `nome_de_quem_enviou(current_user)`; sem sessão → `autoria.SDR_PADRAO = "Thobias"` |
| `fixed_text` | o `value` literal |

**Canal/número:** `channel_id` do payload → `channels` → `phone_number_id` + `whatsapp_token`.
Não há escolha automática; há um canal só (`id=1`, `Pós-Graduação (SDR)`,
`phone_number_id=978293125363835`).

**O que grava em `messages`** (`exact_routes.py:549`):

```
wa_message_id  = eco da Meta
contact_wa_id  = grafia canônica da Meta, resolvida por contatos.contato_existente
channel_id, direction='outbound', message_type='template'
content        = render_template_text(template_body, lead_params)  (texto completo)
timestamp      = agora em SP (naive)
status         = 'sent'
sent_by        = autoria.quem_enviou(current_user)   -> NULL quando chamada por job
template_name  = o nome do template          <- SIM, grava
```

**Não existe coluna `origem_envio` em `messages`.** `origem_envio` só existe (a) como flag do
payload e (b) em `disparo_skip.origem_envio`, ou seja **só nos PULOS**. Um envio que saiu não
registra se foi campanha, individual ou agendado. Quem quiser isso hoje infere por
`sent_by IS NULL`.

Travas e efeitos colaterais no caminho:

* `bloquear_se_boas_vindas(template_name, db)` — `exact_routes.py:324`. Recusa 400 para
  `nat_boasvindas` e para o template configurado em `auto_welcome_config`
  (`app/welcome_guard.py`).
* **Guardrail de funil:** se os `lead_ids` cruzarem mais de um `funnel_id`, HTTP 400.
* `por_que_pular` (recusa) — `exact_routes.py:436`.
* `nat_ativa` — `exact_routes.py:449`, **só quando `origem_envio != "individual"`**.
* `_silenciar_agente_apos_envio_manual(wa_id, current_user, db)` — `exact_routes.py:590`.
  Silencia o agente na thread com motivo `outbound_manual_sdr`. **Roda em TODOS os modos,
  inclusive o agendado.**
* `await asyncio.sleep(1)` por lead — `exact_routes.py:601`.
* **Não há noção de horário comercial** nem teto de rajada.

## 2.2 — Existe função de envio de template para UM lead, chamável por job?

**Sim: a própria `bulk_send_template`.** Ela já é chamada como função Python, sem HTTP, em
`app/main.py:238`:

```python
result = await bulk_send_template(payload, db)
```

Isso funciona **por decisão documentada**, não por acidente: `current_user` recebe o próprio
objeto `Depends`, e `app/autoria.py` existe exatamente para isso —
`quem_enviou()` devolve `None` se não for `isinstance(x, User)`, e
`nome_de_quem_enviou()` cai em `SDR_PADRAO = "Thobias"` (um `{{n}}` em branco faria a Meta
recusar a mensagem inteira com `#131008`).

**É o menor pedaço reaproveitável, e é grande.** Com `lead_ids=[um_id]` ela entrega, de
graça: trava da boas-vindas, recusa de 30 dias, `nat_ativa`, canonização do telefone,
criação do contato, vínculo do SDR, `Message` com texto renderizado e `template_name`,
silenciamento do agente, e `disparo_skip` durável. Reimplementar "enviar um template" fora
dela significa reimplementar cada uma dessas nove coisas — foi o que produziu os 5 × HTTP 500
de 28/08 quando metade de uma correção foi trazida e a outra não.

**As alternativas são piores:**

* `whatsapp.send_template_message` (`app/whatsapp.py:61`) — é o fio nu. Nenhuma regra,
  nenhuma gravação. Só serve como andar de baixo.
* `nat_sender.enviar_nat` (`app/nat_sender.py:102`) — passa por `nat_pode_atuar`
  (`nat_guard.py:246`): `nat_enabled` (**hoje `false`**), funil 18535, `assigned_to ∈ {4,5}`,
  teto de 20 envios/h. Grava `nat_etapa`, ou seja **atribui a mensagem ao agente** — o que é
  falso para um follow do SDR, e corromperia `contar_envios_nat_ultima_hora` e todos os
  números de "IA vs humano".
* `exact_spotter.send_welcome_to_new_lead` — é só a boas-vindas, e está travada.

## 2.3 — `scheduled_messages`

**Não morreu. Está viva, completa e simplesmente sem uso.** A cadeia inteira existe hoje:

```
frontend/src/app/automacoes/page.tsx:522   POST /scheduled-messages
app/routes.py:1030  create_scheduled_message   -> INSERT scheduled_messages (status='pending')
app/main.py:206     scheduled_messages_job     -> a cada 60 s, pega os vencidos
app/main.py:238     bulk_send_template(payload, db)  com origem_envio="campanha"
```

Também existem `GET /scheduled-messages` (`routes.py:1067`) e
`POST /scheduled-messages/{id}/cancel` (`routes.py:1089`), e o job sobe em toda inicialização
("✅ Agendamento de templates ativo (checa a cada 60s)").

O que morreu foi o **uso**: a tabela tem **4 linhas, todas `sent`, criadas em 10–11/06/2026**.
Nada `pending`, nada `error`. Ninguém usa o botão.

Detalhes que importam para quem pensar em reaproveitar:

* `create_scheduled_message` **recusa `scheduled_at <= now`** (HTTP 400). Um job que quisesse
  "manda agora" teria de inserir na tabela direto, contornando a rota.
* O job **não olha horário comercial** — só `scheduled_at <= now`.
* `origem_envio: "campanha"` é **fixo** no payload de `main.py:236`, então o filtro
  `nat_ativa` sempre vale no caminho agendado.
* `result` guarda o retorno de `bulk_send_template` em JSON. `pulados` é serializado ali, e é
  por isso que aquela lista não pode conter `datetime` (ver o comentário em
  `exact_routes.py:390`).
* `sent_by` sai **NULL** (não houve humano). Quem montou está em
  `scheduled_messages.created_by`.

**Veredito:** é um mecanismo de *agendamento por data-hora escolhida à mão*, com granularidade
de lote e TTL de 60 s. Serve de referência para "como chamar `bulk_send_template` de um job"
(é a prova de que funciona), **não** como fila do follow por estágio: o gatilho do follow é
um evento, não um horário, e a tabela não tem onde guardar "por causa de qual estágio".

## 2.4 — Regras de pulo que ainda existem

**Confirmado, com uma correção de escopo:** `higiene_disparo.por_que_pular` tem **só a
recusa**. `nat_ativa` **não mora lá** — está inline na rota.

`app/higiene_disparo.py:108`:

```python
async def por_que_pular(wa_id: str, db: AsyncSession, *, agora: datetime) -> tuple[str,str] | None
```

* Única regra: **`recusa`** — `JANELA_RECUSA = 30 dias` (`higiene_disparo.py:73`),
  `PADRAO_RECUSA` (`:74`) casado com `~*` contra `Message.content` de inbounds nas
  `variantes_wa_id` do telefone.
* O teto de 3 templates/7 d **saiu em 21/09** (decisão do Álefe): sem `nat_config`, sem
  override. Linhas antigas com `regra='teto'` em `disparo_skip` são histórico.
* **`nat_ativa` está em `exact_routes.py:449`**, dentro do laço, sob `if not individual`:
  `estado_de(phone, db)` e `ativo.etapa in ETAPAS_QUALIFICACAO_ATIVAS`
  (`models.py:729`). **Um job que chame `por_que_pular` e envie por conta própria fica SEM a
  regra `nat_ativa`.**
* **Chamável por job? SIM.** É função pura de `(wa_id, db, agora=)`, sem `Depends`, sem
  `current_user`, e **nunca levanta** (qualquer exceção → `None` + log; "higiene que derruba
  disparo é pior que disparo sem higiene").

**Quanto isso pularia, medido** nas 1 254 entradas em follow do 18535 (30 d):

| regra | pulos |
|---|---:|
| `recusa` (30 d) | **44** (3,5 %) |
| `nat_ativa` | **0** |

`nat_ativa` dá zero **porque o agente está pausado**: `nat_config.qualificacao_start_at =
2099-01-01` e `nat_enabled = false`, e as 312 linhas de `nat_qualificacao_state` estão todas
em `encerrado` (165), `transferido_humano` (95) ou `concluido` (52) — nenhuma etapa ativa.
**Religar o agente reativa esse filtro**, e o número deixa de ser zero.

**Buraco na higiene, não coberto por nenhuma regra:** a Meta já devolve opt-out explícito e
ninguém lê. Nos últimos 30 dias: **1 × `131050`** ("This recipient has chosen to stop
receiving marketing messages on WhatsApp from your business") e **17 × `131049`**. O código
grava `messages.error_code` (`main.py:698`) e `delivery_health.py` conta para alertar, mas
**`por_que_pular` não consulta `error_code`**: quem a Meta marcou como opt-out continha
entrando em todo disparo. É a mesma doença do §4.2 do RECON_FOLLOWS_HUMANO_IA, um nível
abaixo — o "não" agora vem da Meta, não do lead.

## 2.5 — Janela de envio (horário comercial)

Existe, em **um lugar só**: `app/nat_guard.py`.

```python
ABERTURA   = time(9, 0)    # nat_guard.py:112  inclusive
FECHAMENTO = time(18, 30)  # nat_guard.py:113  EXCLUSIVE

dentro_horario_comercial(quando=None) -> bool     # nat_guard.py:121
proximo_horario_util(quando=None) -> datetime     # nat_guard.py:148  (naive SP)
```

09:00–18:30 SP, **segunda a sexta**. Aceita aware (converte) ou naive (assume SP).
**Feriado não é tratado** — limitação declarada nas duas docstrings.
`HORA_ABERTURA` / `HORA_FECHAMENTO` existem só por compatibilidade e **perdem os minutos**;
não usar.

**Quem chama hoje:**

| arquivo:linha | o quê |
|---|---|
| `qualificacao_fluxo.py:1174-1175` | `if not dentro_horario_comercial(agora): raise AcaoAdiada(proximo_horario_util(agora), …)` |
| `nat_flow.py:511` e `:530` | abertura da NAT |

**Quem NÃO tem janela nenhuma:** `nat_scheduler.nat_scheduler_job` (só menciona a função numa
docstring, `nat_scheduler.py:480` — quem empurra o `run_at` é quem *agenda*, não o scheduler),
`nat_sla.py`, `agente_parado.py`, `delivery_health.py`, `scheduled_messages_job`,
`sync_job` e **`bulk_send_template`**.

**O padrão a seguir é o do `qualificacao_fluxo`:** o handler acorda, vê que está fora, e
**adia** com `proximo_horario_util` em vez de recusar — recusar deixaria o lead sem o follow
para sempre; enviar mandaria WhatsApp às 22h.

---

# Bloco 3 — Templates no Hub

## 3.1 — Como o Hub conhece os templates

**Ao vivo, direto da Meta. Não há sincronização.**

`GET /api/channels/{id}/templates` (`app/routes.py:737`) faz
`GET /{waba_id}/message_templates` com `fields=name,language,status,category,components,
rejected_reason`, `limit=100`, seguindo `paging.next` (teto de 20 páginas), filtrando
`status=APPROVED` por default. Extrai o BODY e conta os `{{n}}` com
`re.findall(r'\{\{(\d+)\}\}', body)`.

A tabela local `whatsapp_templates` **não é um cache** — ela guarda só os templates
**criados pelo Hub** (`POST /api/channels/{id}/templates`, `routes.py:795`). Tem **5 linhas**:
`zz_teste_plataforma_20260625`, `nat_abertura_agendado`, `nat_abertura_qualificacao`,
`nat_abertura_sem_formacao`, `nat_lembrete_reuniao`.

**Onde `mensagem_follow1..9` aparecem no banco/código:**

* `whatsapp_templates` — **em nenhuma linha**.
* código-fonte — **em nenhum arquivo** (`grep -rn 'mensagem_follow'` não devolve nada).
* `messages.template_name` — sim, é o **único** registro local de que existem.
* Meta — ver 3.2. E **não são nove, nem se chamam assim.**

## 3.2 — **CONTRADIZ o desenho:** os nove templates não existem como descritos

Puxei os **90 templates** do WABA `1360246076143727` ao vivo. Confrontando com
"`mensagem_follow1` … `mensagem_follow9`, variável `{{1}}` = primeiro nome":

| degrau | o desenho diz | o que existe na Meta | vars | o que é o `{{2}}` |
|---:|---|---|---:|---|
| 1 | `mensagem_follow1` | **NÃO EXISTE** — o usado é `mensagem_flow` | **3** | `{{2}}` = **nome do SDR**, `{{3}}` = curso |
| 2 | `mensagem_follow2` | **NÃO EXISTE** — o usado é `mensagens_flows2` | 2 | curso |
| 3 | `mensagem_follow3` | existe | 2 | curso |
| 4 | `mensagem_follow4` | existe | **1** ✅ | — |
| 5 | `mensagem_follow5` | existe | 2 | curso |
| 6 | `mensagem_follow6` | **NÃO EXISTE** — o usado é **`mansagem_follows6`** (erro de grafia: "man~~s~~agem") | 2 | curso |
| 7 | `mensagem_follow7` | existe | 2 | **MÊS** ("Março") |
| 8 | `mensagem_follow8` | existe | 2 | curso |
| 9 | `mensagem_follow9` | existe | **1** ✅ | — |

**Só 2 dos 9 batem com "uma variável, o primeiro nome": o 4 e o 9.**
Três não existem com o nome do desenho. Um tem o nome escrito errado na própria Meta. Um tem
três variáveis. E **um `{{2}}` não é o curso — é o mês.**

`mensagem_follow7`:

> Oi {{1}}, tudo bem? … Os candidatos inscritos **neste mês de {{2}}** estão tendo isenção da
> taxa de matrícula …

**Isso já está saindo errado em produção. Medido:** dos 40 envios de `mensagem_follow7`,
**25 receberam "Setembro" e 15 receberam o NOME DO CURSO no lugar do mês**:

```
"Os candidatos inscritos neste mês de Autolesão, Suicídio e Luto estão tendo isenção…"   ×4
"…neste mês de Saúde Mental…"          ×3
"…neste mês de Psicologia Clínica…"    ×2
"…neste mês de Infantojuvenil EAD…"    ×2
"…neste mês de Psicologia Escolar…"    ×1   (+ Grupos e…, BoasPraticasEAD, Transtorno do…)
```

A causa é a heurística da tela (`frontend/src/app/automacoes/page.tsx:399-405`,
`tipoPadrao`): ela acerta o `{{2}}` de apresentação (`"é o "` → `sdr_logado`, o conserto S6-3
do `tentativa_contato`), mas para todo o resto cai em `i <= 2 → 'lead_course'`. É **o mesmo
defeito do S6-3, num template que aquele conserto não cobria.**

Os demais conferem: `mensagem_flow` saiu com "Thobias" no `{{2}}` nos 105 envios;
`mensagem_follow5` saiu com curso nos 192.

**Corolário para o follow automático:** ele **não pode** ter uma regra única de parâmetros.
Precisa de uma tabela `estágio → (template, lista de mappings)` escrita à mão e conferida
contra o corpo de cada template, porque os nove corpos pedem coisas diferentes: nome, nome+SDR+curso,
nome+curso, nome+mês.

**Curso resolvido?** Dos 150 leads hoje parados em estágio de follow no 18535,
**141 têm alias em `course_aliases`**, 8 caem no fallback cru (`PosBoasPraticasEAD` →
"BoasPraticasEAD", `pospsiclinicaaplicada` → "psiclinicaaplicada") e 1 tem `sub_source` NULL
(vira "Pós-Graduação"). **6 % renderizariam um nome de curso torto.**

## 3.3 — Mídia nos templates

**Sim, há templates com mídia, e o Hub NÃO sabe enviar dois dos três tipos.**

`whatsapp.send_template_message` (`app/whatsapp.py:61`) monta **apenas dois tipos de
component**: `body` (parâmetros de texto) e `button` (`sub_type=quick_reply`, payload).
**Não existe nenhum caminho para um component `header`.**

O que isso significa, por família:

| família | estrutura | o Hub consegue enviar? |
|---|---|---|
| `f3_guia*` (14), `f3_site*` (2) | `BODY + BUTTONS` com botão **URL estático** (link do Drive) | **SIM.** O link está na definição do template, não é parâmetro. Nada a anexar. |
| `f4_audio*` (14, inclui **`f4_audiosmtrabalho`**) | idem, botão URL para o áudio do coordenador no Drive | **SIM**, mesma razão |
| `follow5_gestao`, `follow5_mulheridades`, `follow5_tea` | `HEADER format=DOCUMENT` + BODY | **NÃO.** A Meta exige um component `header` com o handle/link do PDF; `send_template_message` não sabe montá-lo. |
| `agendamentosdr_vi`, `agendamentosdr_vick` | `HEADER format=IMAGE` + BODY (3 vars) | **NÃO**, mesma razão |

Confirmação empírica: nenhum dos cinco templates de header com mídia aparece em
`messages.template_name` — **nunca saíram pelo Hub.**

**Como o Hub anexa mídia hoje:** só **fora** de template. `upload_media`
(`whatsapp.py:119`) → `media_id` → `send_media_message` (`whatsapp.py:134`), que manda uma
mensagem `image`/`document`/`audio`/`video` avulsa. Isso **só funciona com a janela de 24 h
aberta** — não serve para um follow, cujo pressuposto é justamente que o lead não responde.

**Achado colateral na escada:** `mensagem_follow4` diz *"Segue algumas informações do
coordenador sobre a Pós para que ouça 🙏"* — e **não tem botão nem mídia nenhuma**. O áudio
está nos `f4_audio*`. E `mensagem_follow5` pergunta *"você conseguiu ouvir o áudio do
coordenador que te enviei?"*, pressupondo o degrau 4. Automatizar `mensagem_follow4` sozinho
**promete um áudio que não é enviado**, e o degrau 5 cobra um áudio que nunca chegou. É
exatamente por isso que o SDR manda `f4_audio<curso>` à mão no degrau 4 (10 envios medidos).

---

# Bloco 4 — Idempotência e o que já existe de "follow"

## 4.1 — `follow_20h` e a recuperação: colidem?

`nat_scheduled_actions` (`app/models.py`):

```
kind           varchar(40)  NOT NULL
contact_wa_id  varchar(20)  NOT NULL     <- por TELEFONE, não por lead
run_at         timestamp    (naive SP)
payload        text (JSON)
status         pendente|executado|cancelado|falhou|skipped   (CHECK)
attempts       int
```

**Índice que decide a idempotência:**
`uq_nat_sched_pendente_por_contato UNIQUE (kind, contact_wa_id) WHERE status = 'pendente'`.

**`kind`s com linhas no banco hoje:**

| kind | pendente | executado | cancelado | falhou | skipped | última |
|---|---:|---:|---:|---:|---:|---|
| `iniciar_qualificacao` | 15 | 317 | 472 | — | 143 | 27/09 |
| `lembrete_reuniao` | 8 | 125 | 58 | — | 27 | 27/09 |
| `encerrar_inativo` | — | 140 | 572 | — | 148 | 17/09 |
| `follow_20h` | — | 61 | 404 | **60** | — | 17/09 |
| `vigiar_resposta` | — | — | 515 | — | — | 17/09 |

Mais três constantes **sem nenhuma linha**: `sla_check` (`models.py:487`),
`retry_contato` (`:491`), `responder_pendente` (`:521`).

**Colidem com o follow por estágio?** Não pelo `kind` — nenhum se chama nada parecido.
**Mas colidem de duas outras maneiras, e as duas importam:**

1. **`nat_scheduler.agendar()` (`nat_scheduler.py:205`) CANCELA o pendente anterior do mesmo
   `(kind, contact_wa_id)` antes de inserir.** É a semântica de "no máximo um pendente por
   tipo por contato", e o índice único é a rede de segurança. **Se o follow por estágio usar
   um `kind` único (`follow_estagio`), um lead que entre em Follow 3 e depois em Follow 4
   antes do primeiro rodar perde o Follow 3 em silêncio** — `agendar` cancela, e o lead
   recebe só o último. O `kind` precisa carregar o estágio
   (`follow_estagio_3`, `follow_estagio_4`, …) ou a fila precisa ser outra.

2. **`follow_20h` usa `nat_config.follow_template`, que hoje vale `'follow_up'`** — e
   `follow_up` é **o segundo template mais usado pelo SDR no `Follow 1` (22) e no
   `Follow 2` (18)**. `follow_enabled = true`, mas o agente está pausado
   (`qualificacao_start_at = 2099`), então nada sai. **Ao religar o agente, a mesma família
   de template passa a sair por duas réguas independentes.** E o `{{2}}` de `follow_up` é a
   *pergunta pendente do agente*, não o curso — se o follow por estágio usar `follow_up`
   com `lead_course`, produz a mesma classe de erro do `mensagem_follow7`.

Contexto: `follow_20h` teve **60 `falhou`** (o `TypeError` do RECON_NAT_FOLLOWUPS_20260917,
corrigido em 17/09 por `7add746`) e nunca voltou a rodar porque o agente foi pausado no mesmo
dia. Toda a tabela para em 17/09, exceto `iniciar_qualificacao` e `lembrete_reuniao`, que
seguem entrando (guard próprio).

## 4.2 — Existe tabela que registre "template X enviado ao lead Y por causa do estágio Z"?

**NÃO.** Varri `information_schema` por toda coluna com `stage`, `etapa` ou `follow` no nome:

```
disparo_skip.etapa                 <- etapa do AGENTE (varchar 30), num PULO, não num envio
exact_leads.stage                  <- estado atual, sobrescrito
exact_stage_events.stage_de/para    <- a transição, sem nada sobre envio
messages.nat_etapa                 <- etapa do AGENTE
nat_config.follow_enabled/template  <- config do follow_20h
nat_flow_state.etapa                nat_qualificacao_state.etapa
```

O mais perto que se chega hoje é juntar `messages.template_name` + `contact_wa_id` +
`created_at` com `exact_stage_events` por chave de telefone e janela de tempo — **é
exatamente o que fiz no §1.4, e é inferência, não registro.** Ela erra por construção quando
duas coisas acontecem em 24 h, e é cega antes de 01/09 (quando `template_name` passou a ser
gravado).

**O follow por estágio precisa de escrita nova.** O mínimo é `(exact_lead_id, stage_para,
observado_em_do_evento, template_name, quando_enviou, resultado)` com UNIQUE na definição de
"uma entrada" que for escolhida em 4.3. Sem isso, nenhum religamento é seguro: o job não sabe
o que já mandou, e a reinicialização do backend remanda.

## 4.3 — Um lead que volta a um estágio já visitado

Nos últimos 30 dias, no 18535:

| entradas no MESMO estágio | pares (lead, estágio) | eventos |
|---:|---:|---:|
| 1 | 1 198 | 1 198 |
| 2 | **28** | 56 |

**28 pares se repetem, em 20 leads distintos.** Nenhum par chega a 3. Sobre 1 254 entradas,
**2,2 % são reentrada.**

Confirmação independente pelo `cycle` do `/v3/LeadStages` (entradas em follow do 18535 desde
28/08): `cycle=1` → 1 237, `cycle=2` → 31, `cycle=3` → 10.

**O caso que decide a regra.** A trajetória mais comum entre os 20 é um vaivém no fim da
escada, e ele aparece em lote:

```
lead 51407750 (e 51418385, e outros — mesmos timestamps, foi arrasto em lote)
  31/08 18:10  Follows 6  ->  Follows 7
  02/09 21:01   Follows 7 ->  Follows 8
  14/09 17:22  Follows 8  ->  Follows 9
  17/09 21:16   Follows 9 ->  Follows 8     <- voltou
  18/09 21:18  Follows 8  ->  Follows 9     <- entrou DE NOVO
  22/09 21:11   Follows 9 ->  Descartado
```

**"Uma vez por entrada" mandaria `mensagem_follow9` duas vezes para a mesma pessoa** — e
`mensagem_follow9` é a despedida: *"entendo que não há mais interesse … e encerro aqui meu
contato"*. Mandar isso duas vezes em 32 horas é a Michele de 26/08 outra vez, com a nossa
assinatura em cima.

**Recomendação medida: "uma vez por ESTÁGIO por lead", não por entrada.** Custo do que se
perde: 28 envios em 30 dias (2,2 %), e são justamente os que não se quer mandar. Custo de
"por entrada": 28 duplicatas, algumas delas na despedida. Se um dia se quiser reentrada,
`cycle` do `/v3/LeadStages` é o discriminador pronto (`Follows 9` do `cycle=1` ≠ do `cycle=2`),
mas `exact_stage_events` não tem essa coluna.

---

# Bloco 5 — Número de teste `83988046720`

## 5.1 — Onde ele existe, e em qual grafia

**As DUAS grafias, com duas threads separadas** — o caso canônico de `app/telefone.py`
(DDD 83 está fora da faixa 11–28, então o WhatsApp entrega sem o 9º dígito):

| tabela | linhas | grafia |
|---|---:|---|
| `contacts` | **2** | `5583988046720` (13, `name='Álefe Guimel Lins Barbosa'`, `assigned_to=5`, criado 18/08) e `558388046720` (12, sem nome, `assigned_to=3`, criado 05/02) |
| `exact_leads.phone1` | **9** | todas `5583988046720` (13) |
| `messages` | **377** | `558388046720`: 217 inbound + 153 outbound · `5583988046720`: 7 outbound |
| `nat_qualificacao_state` | 1 | `5583988046720`, etapa `transferido_humano`, atualizado 26/08 |
| `nat_scheduled_actions` | 10 | `5583988046720` — 8 `encerrar_inativo`, 2 `iniciar_qualificacao`; nenhuma pendente |
| `agendamentos` | 7 | — |
| `nat_flow_state` | 0 | — |
| `disparo_skip` | 0 | — |
| `nat_contact_attempts` | 0 | — |

Última atividade: inbound em **26/08 10:11**, outbound em **28/08 10:43**. Ou seja, **a
janela de recusa de 30 dias está vazia hoje** (o inbound mais recente tem 32 dias).

**Está no predicado de teste de `relatorios.py`? SIM, e por dois caminhos.**
`PREDICADO_TESTE` (`relatorios.py:216`) é
`(^\s*zz|smoke|teste|\mtest|john doe|fafaf|alefe|thobias justino)` aplicado a
`lower(translate(name, acentos))`. "Álefe Guimel Lins Barbosa" → `alefe…` **casa em `alefe`**;
e há ainda `zzz teste` e `teste` entre os 9 nomes.
Depois, em `chaves_de_teste` (`relatorios.py:299`), a chave
`chave_telefone('5583988046720') = '8388046720'` carrega **9 leads** ≥ 2, então cai na regra
`bloco` e entra em `excluir` **independentemente de ter inbound**. Confirmado: é lead de teste
para todo relatório.

## 5.2 — Leads na Exact com esse telefone

**Nove, todos no funil 18535**, e portanto o sync já os traz (não é preciso criar nada):

| `lead_ids` (PK local) | `exact_id` | nome | estágio hoje | `sub_source` |
|---:|---:|---|---|---|
| 1355 | 36773908 | kikjd | Descartado | posgenero |
| 1975 | 32196408 | a | Descartado | pospsihospitalar |
| 2124 | 31485567 | Álefe Guimel Lins Barbosa | Descartado | PosAutolesao…Turma3 |
| 2524 | 48525996 | Alefe Lins | Descartado | posat |
| **9127** | **51438018** | Álefe Guimel Lins Barbosa | **Agendados** | PosMulheridades |
| **9134** | **51438436** | Álefe Guimel Lins Barbosa | **Agendados** | Pos Saude do Trabalhador |
| 9285 | 51548604 | Álefe Guimel Lins Barbosa | Descartado | Pos Saude do Trabalhador |
| 9289 | 51550281 | zzz teste | Descartado | Pos Saude do Trabalhador |
| 9324 | 51600542 | teste | Descartado | Pos Saude do Trabalhador |

**Nenhum está em estágio de follow.** Para percorrer a escada basta arrastar **51438018** ou
**51438436** (hoje em `Agendados`) por `Follow 1` … `" Follows 9"`. `Agendados -> Follow 1` é
um movimento que a base já registra como rotineiro (5 casos nos 30 dias).

Três notas para o teste:

* A coluna `lead_ids` acima é o que `bulk_send_template` espera — **`exact_leads.id`, não
  `exact_id`.** Confundir os dois é um lote vazio silencioso.
* `sub_source = 'PosMulheridades'` e `'Pos Saude do Trabalhador'` **têm alias**, então o
  `{{curso}}` renderiza legível. `posat` e `posgenero` também são válidos como origem
  (`source = Rd Marketing` / `Landing Page`) — nada no sync filtra por allowlist de
  source/subSource; o filtro é só `INGEST_FUNNEL_IDS` (vazio) e, para boas-vindas,
  `funnel_id ∈ auto_welcome_config.funnel_ids`.
* Se o Álefe **responder** algo que case `PADRAO_RECUSA` durante o teste, todos os degraus
  seguintes ficam pulados por 30 dias — e `disparo_skip` registraria, mas a escada pararia.
  Também: a thread ativa de 24 h muda o formato quando se usa `enviar_nat`; por
  `bulk_send_template` sai template sempre, independentemente da janela.

## 5.3 — Como o predicado de teste afeta o ENVIO

**Não afeta. É métrica, e só.** `chaves_de_teste` / `PREDICADO_TESTE` / `ConjuntoTeste` são
referenciados em **exatamente dois arquivos**:

```
app/relatorios.py                      (definição + uso em relatorios.py:716)
backfill_rd_conversoes.py:64,95        (script de backfill)
```

Nenhum caminho de envio (`exact_routes`, `whatsapp`, `nat_sender`, `nat_flow`,
`exact_spotter`, `higiene_disparo`, `main.py`) importa qualquer um dos três.

**Consequência dupla, e ela é boa e ruim:**

* **Bom:** o teste do Álefe vai realmente disparar os nove templates. Nada o pula.
* **Ruim:** os nove envios **não aparecerão em nenhum relatório** — `/relatorios` exclui a
  chave `8388046720`. Conferir o teste tem de ser por `SELECT` direto em `messages` (ou pelo
  WhatsApp do próprio Álefe), nunca pela tela.

---

# Achados que CONTRADIZEM o desenho

1. **"Nove estágios, nove templates `mensagem_follow1..9`, `{{1}}` = primeiro nome."**
   **CONTRADIZ.** Na Meta (90 templates, lidos ao vivo hoje): `mensagem_follow1`,
   `mensagem_follow2` e `mensagem_follow6` **não existem**; o degrau 6 é
   **`mansagem_follows6`** (grafia errada na própria Meta); o degrau 1 é `mensagem_flow` com
   **3 variáveis**; **só `mensagem_follow4` e `mensagem_follow9` têm uma variável**; e o
   `{{2}}` de **`mensagem_follow7` é o MÊS**, não o curso — erro que já saiu para **15 de 40
   pessoas** ("neste mês de Autolesão, Suicídio e Luto"). Ver §3.2 e
   `frontend/src/app/automacoes/page.tsx:404`.

2. **"Quando um lead entra no estágio Follow N."**
   **CONTRADIZ para 1,5 % das transições.** `exact_spotter.py:531` compara estado com estado a
   cada 600 s: quando o SDR move duas vezes na mesma janela, **o estágio do meio nunca gera
   evento**. 19 de 1 278 transições perdidas em 30 dias, **10 delas no `Follow 1`**. Ver §1.3.

3. **"Sem estado próprio além de 'já mandei este follow para este lead nesta entrada'."**
   **CONTRADIZ no mecanismo disponível.** `nat_scheduler.agendar()`
   (`nat_scheduler.py:205`) **cancela** o pendente anterior do mesmo `(kind, contact_wa_id)`,
   e o índice `uq_nat_sched_pendente_por_contato` reforça isso no banco. Com um `kind` único,
   entrar em Follow 3 e depois em Follow 4 **apaga o Follow 3 em silêncio**. Ver §4.1.

4. **"Nove templates" para nove degraus.**
   **CONTRADIZ o que o time faz.** Nos degraus **3 e 4** o SDR manda o template **do curso**
   (`f3_guia<curso>`, 14 variantes; `f4_audio<curso>`, 16 variantes) — 21 e 10 envios medidos.
   E `mensagem_follow4` promete o áudio do coordenador **sem anexar nada**
   (`whatsapp.send_template_message` não monta component `header`), enquanto
   `mensagem_follow5` cobra esse áudio. Ver §1.4 e §3.3.

5. **"O funil da Exact."**
   **CONTRADIZ por ambiguidade perigosa.** Há **quatro** funis com escada de "Follow":
   18535 (`Pos Graduacao`), **18285 (`Intercambio`, `Follow 1..8` no singular, 703 entradas em
   30 dias)**, 20647 (`Follow 2 - Vi`) e 20776. Um predicado `stage ~* 'follow'` sem
   `funnel_id = 18535` manda template de pós para Intercâmbio. Ver §1.1.

6. **"Opt-out ('pediu para parar') continua valendo."**
   **Vale só para o texto do lead.** `por_que_pular` lê `messages.content` de inbound; **não
   lê `messages.error_code`**, onde a Meta já registrou `131050` ("this recipient has chosen
   to stop receiving marketing messages") 1× e `131049` 17× nos últimos 30 dias. Ver §2.4.

---

# O que muda no desenho

1. **A tabela `estágio → template → mappings` é escrita à mão, conferida contra o corpo de
   cada template na Meta, e é o coração da feature — não um detalhe.** Os nove corpos pedem
   coisas diferentes (nome; nome+SDR+curso; nome+curso; **nome+mês**). Copiar a lista de
   estágios byte a byte de `GET /v3/stages` (com o espaço à esquerda de `" Follows 7"` e
   `" Follows 9"`) e travar num teste que compara com a Exact. **Só o degrau 4 e o 9 são
   "{{1}} = primeiro nome".**

2. **Escopo: `funnel_id = 18535` e mais nada** — na query do gatilho, não num comentário.
   Volume esperado: **~42 entradas/dia**, contra ~15/dia que hoje viram template. E o gatilho
   é o **evento** (`exact_stage_events`), nunca o estado (`exact_leads.stage`), senão a
   primeira passada varre os 150 leads parados nos follows.

3. **Reusar `bulk_send_template(payload, db)` com `lead_ids=[um]`, como `main.py:238` já faz.**
   É o único caminho que traz de graça as nove coisas do §2.2 (recusa, `nat_ativa`,
   canonização do telefone, `Message` com `template_name`, silenciamento do agente,
   `disparo_skip`). Mandar `origem_envio: "campanha"` (para o `nat_ativa` valer) e lembrar que
   `lead_ids` é **`exact_leads.id`**. Envolver com o que `bulk_send_template` **não** tem:
   `dentro_horario_comercial` / `proximo_horario_util` (`nat_guard.py:121,148`) e um **teto de
   rajada** — 18/09 às 18:18 SP teriam saído **45 despedidas de uma vez**.

4. **"Uma vez por ESTÁGIO por lead", não por entrada, e em tabela nova.** Não existe hoje
   nenhum registro de "template X ao lead Y por causa do estágio Z" (§4.2). Reentrada é 2,2 %
   (28 casos em 30 dias) e o padrão observado é `Follows 9 → Follows 8 → Follows 9`: "por
   entrada" manda a **despedida duas vezes em 32 h**. Se for para a fila do
   `nat_scheduler`, o `kind` tem de carregar o estágio (`follow_estagio_3`, …), senão
   `agendar()` cancela o anterior.

5. **O gatilho melhor é `GET /v3/LeadStages`, não `exact_stage_events`.** Ele tem o **relógio
   da Exact** (o nosso tem o do sync, com p50 de 4,8 min), tem **`cycle`** (o discriminador de
   reentrada que nos falta), é filtrável (`$filter=createdAt ge …`), e **não perde a transição
   do meio** — os 19 casos do §1.3 estão lá. Duas ressalvas: ele devolve o rótulo **atual** da
   etapa (renomear a etapa reescreve a história dele), e é uma segunda dependência de rede no
   caminho do envio.

---

# Decisões que faltam

1. **Os templates: renomear na Meta ou mapear a bagunça no código?** Criar
   `mensagem_follow1`/`2`/`6` limpos (e corrigir `mansagem_follows6`) custa nova aprovação da
   Meta e um dia de espera; mapear `mensagem_flow` / `mensagens_flows2` / `mansagem_follows6`
   no código custa uma tabela que ninguém vai lembrar de conferir. **E o `{{2}}` do
   `mensagem_follow7` (o mês) precisa de uma resposta separada: fixo por mês corrente,
   `fixed_text` na configuração, ou o template sai da automação?**

2. **Os degraus 3 e 4 mandam o template genérico ou o do curso?** Se for o do curso
   (`f3_guia<curso>` / `f4_audio<curso>`), a tabela de mapeamento passa a ser
   `(estágio, sub_source) → template` com ~30 linhas, e é preciso decidir o que fazer com
   curso sem variante aprovada. Se for o genérico, `mensagem_follow4` **promete um áudio que
   não vai** e `mensagem_follow5` cobra esse áudio — o texto dos dois teria de mudar.

3. **Automatizar o `" Follows 9"`?** Hoje a despedida sai em **2 % das entradas** (1 de 63).
   Automatizar multiplica por ~60 um template que declara fim de contato, num número que já
   levou 17 × `131049` e 1 × `131050` em 30 dias. É a decisão com maior risco para a nota de
   qualidade do número, e a única em que o teto de 3 templates/7 d removido em 21/09 fazia
   diferença.

4. **Teto de rajada e o que acontece com quem transborda.** 45 entradas numa passada já
   aconteceu. Manda 45 em 45 s? Manda N e adia o resto para a próxima passada? Adia para o dia
   seguinte? E os **5 % que entram fora da janela** (63 em 30 dias, incluindo 6 num sábado) —
   `proximo_horario_util` empurra para as 09:00 de segunda, o que significa um follow chegando
   **três dias** depois do arrasto do SDR.

5. **A colisão com o `follow_20h` ao religar o agente.** `nat_config.follow_enabled = true` e
   `follow_template = 'follow_up'`; `follow_up` é o 2º template mais usado no `Follow 1` e no
   `Follow 2`. Com o agente religado, a mesma família sai por duas réguas que não se conhecem.
   Quem cala: o `follow_20h`, o follow por estágio, ou nenhum e aceita-se o dobro?

---

## Não mensurável

* **"A hora em que o SDR moveu o card" (antes de 28/08).** Não mensurável: `observado_em` é a
  hora do sync, e o `/v3/LeadStages` só foi baixado a partir de 28/08 nesta medição (ele tem
  61 068 linhas no total e cobre 2025 inteiro, então é recuperável — só não foi feito aqui).
* **Qual template saiu antes de 01/09.** Não mensurável: `messages.template_name` só passa a
  ser preenchido em 01/09 (S6-1, sem backfill). São 259 outbounds de template com
  `template_name` NULL nos 30 dias, todos entre 23/08 e 01/09.
* **Se um envio foi campanha, individual ou agendado.** Não mensurável: não existe
  `messages.origem_envio`. A flag só sobrevive nos PULOS (`disparo_skip.origem_envio`). O
  único proxy é `sent_by IS NULL`, que junta agente, boas-vindas e agendado.
* **Os 3 outliers de latência > 1 dia** (§1.3). Não diagnosticados.
* **6 leads com telefone de 15 dígitos** (`555565992789963` — `55` duplicado; leads 52104385,
  51423373, 51650632, 51806601, 51422641, 51419877, com 18 entradas em follow nos 30 dias).
  `chave_telefone` devolve `''` para eles, então **somem de todo relatório e de todo
  cruzamento por chave**. Para o ENVIO não há problema: `variantes_wa_id` devolve a forma crua,
  que é exatamente como o `contact_wa_id` deles está gravado, e os 6 envios que já saíram
  constam como `read`/`delivered`. É defeito de medição, não de entrega.

---

*Recon somente-leitura. Nada foi enviado, alterado ou implantado.*
