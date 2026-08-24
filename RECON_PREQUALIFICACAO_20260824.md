# RECON — Agente de pré-qualificação pós-aplicação — 24/08/2026

Levantamento de estado verificado no código em execução, no banco, na Graph API da Meta e na
API da Exact Spotter. Onde os docs de sprint contradizem o código, vale o código.

Nada foi alterado para produzir este documento: só leitura de `information_schema`, das
tabelas, e `GET` na Graph API e na Exact. Nenhum WhatsApp saiu daqui. `nat_enabled` continua
`false` e `nat_config` não foi tocada.

> **O roteiro funcional não está no repo.** `docs/roteiro-prequalificacao.md` não existe, e
> não há nenhum `.docx` em `/home/ubuntu`. Tudo que este documento afirma sobre o ROTEIRO vem
> do resumo de 5 passos do pedido; tudo que ele afirma sobre o SISTEMA foi medido. Onde o
> roteiro for citado como requisito, está marcado como **[roteiro]** — confira contra o
> original antes de tratar como especificação.

---

## 1. Estado atual

### 1.1 Commit em execução

| | |
|---|---|
| HEAD | `f29395d` (18/08 13:25) — commit só de doc |
| Último commit que tocou `backend/app/` | 18/08 02:29 |
| Processo backend | PID 1500356, iniciado **18/08 12:46:38**, `uvicorn app.main:app --port 8001` |
| Árvore de trabalho | limpa |
| Arquivos em `backend/app/` modificados após o start | **nenhum** |

O código em execução é o de `main`. Vale como fonte.

### 1.2 Por onde uma aplicação entra hoje — os 3 caminhos

| # | Caminho | Fonte | O que cria | Dispara WhatsApp? |
|---|---|---|---|---|
| 1 | `POST /api/agendamento/lead` | `agendamento/routes.py:244` | `agendamentos` (`passo=lead_criado`) + `LeadsAdd` na Exact | **Não** |
| 2 | `POST /api/agendamento/agendar` | `agendamento/routes.py:190` | `agendamentos` (`passo=agendado`) + box + reunião | **Não** |
| 3 | `sync_exact_leads` (600 s) | `exact_spotter.py:347` | `exact_leads` + **envia `nat_boasvindas`** | **Sim** |

**Não existe webhook de entrada de lead.** A Exact não chama o backend; quem pergunta somos
nós, de 10 em 10 minutos (`main.py:246`, `sync_job`).

E o ponto que decide a arquitetura do agente novo: **o módulo `agendamento/` não tem uma
única chamada de WhatsApp.** `grep -rn "whatsapp\|send_" backend/app/agendamento/*.py` só
acha comentário e o `send` do middleware ASGI (`cors.py:135`). O formulário da LP hoje é
mudo. O único disparo automático nasce do sync, um passo depois.

### 1.3 Os campos que chegam de fato

`sync_exact_leads` monta o `lead_data` em `exact_spotter.py:378-388` com **exatamente 10
campos**: `name`, `phone1`, `phone2`, `source`, `sub_source`, `stage`, `funnel_id`,
`sdr_name`, `register_date`, `update_date`. E `exact_leads` (18 colunas) não tem coluna
nenhuma para formação, profissão ou descrição.

Mas o dado existe, e em dois lugares:

**a) `agendamentos.extras` (JSONB), local, desde 17/08.** Medido — 80 dos 81 leads com
`passo='lead_criado'` têm objeto:

| Chave | Presente em | Valores observados |
|---|---|---|
| `Profissão` | 80 | Psicologia 37 · Terapia Ocupacional 16 · Enfermagem 13 · Outra 6 · Serviço Social 5 · Fisio/Pedagogia/Ed. Física 1 cada |
| `Ensino Superior` | 80 | Sim 74 · Não 6 |
| `Como conheceu` | 80 | Instagram, YouTube, Google |
| `Faixa de investimento` | 80 | R$100-200: 35 · R$200-300: 20 · até R$100: 15 · R$300-400: 10 |

Só nas linhas `passo='lead_criado'`: as 54 linhas `passo='agendado'` têm `extras` = JSON
`null`, porque o `obrigado.html` não reenvia o que o `index.html` já mandou. **A chave de
junção entre as duas linhas é `lead_id`** — 54 pares confirmados, um por pessoa.

**b) `description` do lead na Exact.** `montar_descricao` (`agendamento/extras.py:133`)
grava os extras lá, e o `GET /Leads` **devolve** o campo. Medido no lead 51514285 (24/08):

```
"description": "E-mail: marinamilk@gmail.com | Profissão: Enfermagem | Ensino Superior: Sim
                | Como conheceu: Instagram | Faixa de investimento: De R$100,00 a R$200,00"
```

Cobertura medida nos 200 leads mais recentes da Exact (`GET /Leads?$top=200&$orderby=Id desc`):

| `source` | Total | Com profissão no `description` | Formato |
|---|---|---|---|
| Landing Page | 73 | **73 (100 %)** | nosso, `chave: valor \| chave: valor`, uma linha |
| Rd Marketing | 126 | 41 (33 %) | multilinha do RD, **rótulos variáveis** |
| Outros \| engajamento180 | 1 | 1 | — |

Os rótulos do RD divergem entre si: `Profissão escolha:` / `Profissão:`, `Nível de
escolaridade:`, `Canal Pós graduação:`, `investimento pós graduação online:` /
`Disponibilidade financeira opções:`. E SDRs escrevem texto livre no mesmo campo, depois:
*"VI AMORIM: Psicóloga, trabalha no CRAS. Aten…"*.

Isso **corrige** o comentário de `nat_flow.py:93` ("no Exact ela não é campo estruturado, só
texto livre dentro de `description`") e o de `nat_copy.py:95` ("falta em ~49% dos leads"):
para o lead que vem da LP, hoje, a formação é estruturada, é nossa, e falta em 0 %.

### 1.4 Como saber se o lead "já agendou"

Tabela `agendamentos`, `passo='agendado'`, junção por `lead_id` (= `exact_leads.exact_id`) ou
por `telefone`. Não precisa perguntar à Exact.

E a corrida entre formulário e agendamento não existe na prática. Medido nos 54 pares:

| Intervalo `lead_criado` → `agendado` | |
|---|---|
| mediana | **28 s** |
| mínimo | 6,6 s |
| **máximo** | **3 min 14 s** |

Ou seja: **5 minutos depois do formulário, a resposta "agendou ou não" é definitiva** em
100 % dos casos observados. Quem não agendou em 3 min não agendou mais (27 pessoas, 33 %).

Já a latência até o disparo de HOJE é outra, e é grande:

| Intervalo formulário → `nat_boasvindas` sair | 80 leads |
|---|---|
| mediana | **4 min 24 s** |
| mínimo | 41 s |
| máximo | **11 min 19 s** |

É o passo de 600 s do `sync_job`. Consequência medida: em **53 dos 54** agendamentos, a
boas-vindas saiu **depois** de a pessoa já ter escolhido o horário.

> ⚠️ **Fuso.** `exact_leads.register_date` vem em UTC e `agendamentos.created_at` é naive em
> SP: a diferença medida entre os dois é 03:00:00 em todos os 80 casos, com variação de
> milissegundos. Qualquer comparação entre as duas tabelas precisa somar 3 h. É a mesma
> armadilha documentada em `nat_guard._agora_sp` (`nat_guard.py:168`).

### 1.5 Volume

| Métrica | Valor |
|---|---|
| Aplicações pela LP (`agendamentos`, `lead_criado`) | **~10/dia** — 81 em 8 dias (17→24/08) |
| Agendamentos concluídos | ~6,7/dia — 54 em 8 dias (**67 %** de conversão) |
| Leads novos na Exact, todos os funis (`register_date`, 30 d) | **~15,6/dia** (468/30) |
| Leads novos no funil 18535 (30 d) | 220 (~7,3/dia) |
| Cliques em botão da boas-vindas (`nat_button_events`, 30 d) | **~8/dia** |
| Mensagens inbound (30 d) | 1 456 texto + 194 botão + 77 interactive |
| Templates outbound (30 d) | **2 577** (campanhas humanas, não automação) |

Dimensionamento de LLM: a ~10 aplicações/dia, com 2 pontos de interpretação por lead
(motivação + eventual período), são **~20 chamadas/dia**. Custo irrelevante. O risco de
volume **não é a operação normal** — é o disparo retroativo sobre base parada (§3.5).

### 1.6 Templates da Meta — o inventário completo

`GET /1360246076143727/message_templates?limit=200` (24/08): **81 templates, todos
`APPROVED`**, sem paginação pendente. WABA `account_review_status=APPROVED`, número
`+55 11 95213-7432` (id 978293125363835) `CONNECTED` / `quality_rating=GREEN`.

**Drift com `whatsapp_templates`: total.** A tabela local tem **1 linha** —
`zz_teste_plataforma_20260625`, `PENDING`, criada pelo Álefe em 25/06 — contra 81 na Meta.
Ela nunca foi espelho do WABA; é só o registro de quem cria template pela tela. Nada no
código lê essa tabela para decidir envio (o envio busca o corpo direto na Meta, via
`whatsapp.fetch_template_body`, `exact_spotter.py:212`). **Não é bug de sincronismo, é uma
tabela com outra função** — mas quem procurar "os templates do projeto" no banco encontra 1.

Um drift real de idioma continua de pé, e é o já conhecido: **`nat_recuperacao_sdr` existe em
`pt_BR` e em `en`, com corpos diferentes** (ids 1499378494752849 e 1586372356357534). Some-se
`sdr_encerramento`, que existe **só em `en`**. Filtrar por `language` antes de indexar por
nome não é opcional — está anotado em `nat_copy.py:80-84`.

**Categoria.** 79 dos 81 são `MARKETING`. Só `hello_world` (en_US) e
`zz_teste_plataforma_20260625` são `UTILITY`. Isso importa para o lembrete de 30 min: um
lembrete de reunião agendada é o caso de uso canônico de `UTILITY`, que não conta no limite
de marketing por usuário e não é pausado por qualidade da mesma forma.

#### Serviriam de abertura (business-initiated, fora da janela)

| Template | Vars | Botões | Serve? |
|---|---|---|---|
| `nat_boasvindas` | `{{1}}` nome, `{{2}}` curso | 2 quick reply | **É o que já sai hoje.** Pergunta "tem alguns minutos para conversar?" — errado para quem já agendou (§3.1) |
| `nat_sim` | `{{1}}` nome, **`{{2}}` formação**, `{{3}}` curso | — | **A frase do passo 1 do roteiro já está aprovada**: *"Verifiquei em sua aplicação que sua formação é em {{2}}"* |
| `primeiro_contato_pos` | `{{1}}` nome, `{{2}}` curso | — | Abertura genérica, sem pergunta de qualificação |
| `nat_reativacao_09h` | `{{1}}` nome, `{{2}}` curso | 2 quick reply | Reativação 09h, cenário 2 |

#### Serviriam de lembrete

| Template | Corpo | Serve para 30 min? |
|---|---|---|
| `confirmao_da_reunio` | "a consultora entrará em contato **hoje às {{2}}**" | Perto. Só nome + hora; **não tem o nome nem o número da consultora** |
| `agendamento` | "nossa consultora entrará em contato no dia {{2}} às {{3}} … pós {{4}}" | Confirmação D-x, não T-30min. Abre com "conforme nos falamos por ligação" — premissa falsa aqui |

### 1.7 Infra de IA existente

| Item | Estado medido |
|---|---|
| `ai_configs` | 1 linha (canal 1), **`is_enabled = false`**, `model=gpt-5-mini`, `temperature=0.7`, `max_tokens=500`, atualizada 19/06 |
| `knowledge_documents` | 18 chunks, 11 cursos, 1 canal, carregados 18/06. **Nenhum contém `R$`** |
| `contacts.ai_active = true` | **637 contatos** |
| `ai_conversation_summaries` | 635 linhas, todas `em_atendimento_ia` |
| Motor no webhook | **Comentado.** `main.py:537-618`, bloco inteiro sob `# === AGENTE IA: DESATIVADO TEMPORARIAMENTE ===` |

Os 637 `ai_active=true` são resíduo de `exact_spotter.py:254` e `:261`, que ligam a flag em
todo lead que recebe boas-vindas. **A flag não faz nada** — o único leitor era o bloco
comentado. Quem ligar aquele bloco de volta liga a IA para 637 contatos de uma vez.

Modelo e provedor: OpenAI, `gpt-5-mini`, `OPENAI_API_KEY` no `.env`
(`ai_engine.py:15,17`). Não há cliente Anthropic no projeto.

Os dois pontos de LLM previstos para a NAT (motivação e período preferido) são o **Bloco 8**,
**não iniciado** — `nat_flow.py:475` aceita hoje *qualquer* texto como motivação e transfere.
O padrão determinístico + fallback existe e está implementado, mas em `nat_copy`, não em LLM:
`parametros_template` devolve `None` quando não dá para montar a mensagem com honestidade
(`nat_copy.py:169-181`), e o chamador trata `None` como "não envio". É o precedente certo.

### 1.8 Infra NAT reaproveitável

| Módulo | Reaproveita como está? | Por quê |
|---|---|---|
| `nat_sender.send_nat_message` | **Sim** | Decide sozinho template × texto livre pela janela de 24 h (`nat_sender.py:29,101`) e carimba `messages.nat_etapa` |
| `nat_scheduler` | **Sim** | Fila genérica `(kind, contato, run_at)`, `FOR UPDATE SKIP LOCKED`, ação+marcação na mesma transação, 3 retentativas com `run_at` empurrado. Handler novo = decorator + registrar o módulo em `MODULOS_DE_HANDLERS` (`nat_scheduler.py:94`) |
| `nat_guard.nat_pode_atuar` | **Não como está** | 5 travas, mas 3 delas são específicas da NAT: funil == 18535, `assigned_to ∈ {4,5}`, `register_date ≥ nat_start_at`. Ver §3.4 |
| `nat_guard.dentro_horario_comercial` | **Sim** | 09-19 h, seg-sex, SP. Sem feriado (limitação declarada, `nat_guard.py:200`) |
| Padrão `begin_nested()` no webhook | **Sim** | `main.py:449,470,538` — 3 savepoints já em produção |
| `nat_buttons.extrair_evento_botao` | **Sim** | Cobre `button` (template) e `interactive` |

Estado operacional da NAT, medido agora:

```
nat_config: nat_enabled = false   nat_start_at = NULL   max_envios_hora = 20  (25/07 21:49)
nat_flow_state          0 linhas
nat_scheduled_actions   0 linhas
nat_contact_attempts    0 linhas
messages com nat_etapa  0 linhas
nat_button_events     194 linhas   (175 contatos, 29/07 → 24/08, ~8/dia)
```

**Correção ao `ESTADO_NAT_20260809.md`:** o risco 1 daquele documento ("`nat_boasvindas` sai
duas vezes quando a NAT ligar") **foi resolvido**. `send_welcome_to_new_lead` agora passa
`boas_vindas_wamid=welcome_wamid` para `iniciar_fluxo_nat` (`exact_spotter.py:330`), e o modo
adoção (`nat_flow.py:510-526`) grava o estado sem enviar nada. Também mudou: `nat_button_events`
foi de 82 para 194 linhas.

### 1.9 Agendamento e agenda da consultoria

Endpoints reutilizáveis de dentro de um fluxo de WhatsApp — os três são funções Python
comuns, não dependem de HTTP:

| Função | Arquivo | Uso a partir do WhatsApp |
|---|---|---|
| `disponibilidade.resumo_por_dia(db)` | `disponibilidade.py:185` | Oferecer a grade. Cache de 60 s do processo inteiro (`CACHE_SEGUNDOS`, `:57`) |
| `disponibilidade.slots_livres(db, usar_cache=False)` | `disponibilidade.py:122` | Antes de escrever — o caminho do POST já usa `usar_cache=False` |
| `fluxo.agendar(db, nome=…, slot_id=…, lead_id=…)` | `agendar.py:275` | Agendar com o lead que já existe. **`lead_id` é o que impede o lead duplicado** |

Premissas do `AGENDAMENTO_FINDINGS.md` que continuam valendo, e mandam no desenho:

- **O `BoxesAdd` É o lock** (`agendar.py`, cabeçalho; FINDINGS §8). Não existe check-then-act.
- **Não existe `ScheduleRemove`** (FINDINGS §6). Depois do passo 3 não há desfazer: cada
  remarcação **queima um slot para sempre**. Um agente que ofereça remarcar por WhatsApp
  precisa saber disso antes de oferecer.
- **`LeadsAdd` cria `subSource` que não existe** (FINDINGS §11) — allowlist em `origens.py` é
  o que separa "configurável" de "qualquer um escreve no cadastro global".
- **Passo 4 (`ChangeFunnel`) está DESLIGADO** — sem `AGENDAMENTO_FUNIL_DESTINO` no `.env`,
  não roda (`agendar.py:129`). Quando roda, a reunião vira `Concluido` (FINDINGS §15).
- **Janela e grade:** duração 45 min, antecedência mínima 2 h (`grade.py:52-53`), janelas
  10:30-12:00 e 15:45-18:00, seg-sex, idênticas para as duas consultoras
  (`backend/consultoras.json`).
- **Antecedência real medida:** mediana **1 d 23 h** entre agendar e a reunião; mínimo 3 h 16;
  máximo 8 d 11 h. Um lembrete T-30min sempre cai bem depois da conversa de qualificação.

### 1.10 Quem é a consultora

`consultoras.json` (via `AGENDAMENTO_CONSULTORAS_PATH`) tem `email`, `nome_exibicao` e grade:

| E-mail | Nome exibido | Reuniões (8 d) |
|---|---|---|
| `processoseletivo@cenatcursos.com.br` | Victória Rodrigues | 29 |
| `comercial@cenatcursos.com.br` | Victória Amorim | 25 |

O nome já chega ao visitante: `POST /agendar` devolve `consultora_nome`
(`agendamento/routes.py:239`), lido de `nome_de()` (`consultoras.py:155`). E `agendamentos`
guarda `sales_rep_email` na linha, então o par (reunião → consultora) é recuperável para
qualquer lembrete.

**O número de telefone não existe em lugar nenhum.** Verificado nos quatro lugares plausíveis:

| Fonte | Tem telefone da consultora? |
|---|---|
| `consultoras.json` | Não — só `email`, `nome_exibicao`, `grade` |
| `users` (8 linhas) | **Não há coluna de telefone na tabela** |
| Exact, `GET /Leads` → `salesRep` | Devolve `name`, `lastName`, `email`, mas `"phone": ""` e `"phone2": ""` |
| `sdr_mapping.py` | Só nome do SDR → id de usuário. 6 entradas |

Pior: **os e-mails não se cruzam.** `consultoras.json` usa `@cenatcursos.com.br`; `users` tem
`processoseletivo@cenatsaudemental.com` e `comercialcenat@gmail.com`. Não há junção possível
hoje entre a consultora que atende e uma linha de `users` — nem para pegar telefone, nem
para notificar.

### 1.11 Exact e régua comercial

Campos úteis à qualificação em `exact_leads`: `sub_source` (curso), `funnel_id`, `stage`,
`sdr_name`, `register_date`. Formação: **não existe coluna** (§1.3).

**O lembrete que continua valendo:** `sync_exact_leads` faz `setattr(existing, key, value)`
para todos os 10 campos a cada passada (`exact_spotter.py:391-393`), de 10 em 10 minutos.
**Estado do agente NUNCA pode morar em `exact_leads`.** As colunas `welcome_*` sobrevivem
só porque não estão no `lead_data`; qualquer coluna nova que entre na lista é sobrescrita.

**A régua R$100/R$200/R$300 [roteiro] não existe em código nem em banco.** Verificado:

- `grep -rniE "R\$ ?[0-9]|investimento|faixa|preco|mensalidade"` em `backend/app/**/*.py`:
  nenhuma lógica de preço. Só o comentário de `ai_engine.py:23` ("Nunca invente informações
  sobre preços") e as menções à chave do formulário.
- `knowledge_documents`: 0 de 18 chunks contêm `R$`.
- `whatsapp_templates` / templates da Meta: nenhum com valor.

O que existe é **a pergunta** ("Faixa de investimento", 4 opções) e **a resposta guardada**
(§1.3). A decisão do que fazer com cada faixa é processo humano — não está escrito em lugar
nenhum que este levantamento alcance.

### 1.12 Cadência de follow-up hoje

Mapeado, como pedido, **sem propor implementação**:

| Mecanismo | Automático? | Estado |
|---|---|---|
| `scheduled_messages` + `scheduled_messages_job` (60 s) | Agendado por humano | 4 linhas, todas `sent`, últimas de **11/06** |
| Disparo em massa `exact_routes.py:355` (tela Automações) | Não — humano escolhe leads | É de onde saem os 2 577 templates/30 d |
| Réguas `f3_*`, `f4_*`, `follow*`, `reagendamento_*`, `mensagem_follow*` | Não | ~45 templates aprovados, disparados à mão |
| `nat_recuperacao` retry 10 min | Sim, mas **cobra o SDR, nunca o lead** (`nat_recuperacao.py:12-21`) | 0 linhas — NAT desligada |
| `nat_sla` escada 0→1→2 | Sim | 0 linhas |

**Não existe hoje nenhuma cadência automática que fale com o lead por silêncio.** Toda régua
é humana. O follow-up de silêncio do roteiro seria a primeira — e é exatamente onde mora o
risco do §3.5.

---

## 2. Gaps — o que o roteiro exige e não existe

| # | Gap | Onde deveria estar | Gravidade |
|---|---|---|---|
| **G1** | **Nenhum gatilho no formulário.** O disparo só nasce do sync, 4-11 min depois | `agendamento/agendar.py` não tem chamada de WhatsApp | Alta — é o gatilho pedido |
| **G2** | **`[formação]` não chega ao envio.** `_dados_do_lead` devolve `"formacao": ""` **hardcoded** | `nat_flow.py:115` | Alta — mas o dado existe (§1.3); é fiação, não coleta |
| **G3** | **`description` não é sincronizado.** O campo existe na Exact e o `GET /Leads` devolve; o sync não o lê | `exact_spotter.py:378-388` | Média |
| **G4** | **Sem parser de `description`.** O formato da LP é nosso e trivial; o do RD tem 4+ rótulos variáveis e texto de SDR colado | não existe | Média — só para leads não-LP |
| **G5** | **Sem telefone da consultora.** Nem em JSON, nem em `users` (sem coluna), nem na Exact (`phone: ""`) | §1.10 | Alta — o passo 5 do roteiro **não é implementável** hoje |
| **G6** | **Sem template de lembrete T-30min.** `confirmao_da_reunio` chega perto mas não tem nome nem número da consultora | Meta | **Alta — caminho crítico** |
| **G7** | **Sem `kind` de lembrete no scheduler.** Existe a fila, não existe o handler | `nat_scheduler.MODULOS_DE_HANDLERS` tem 2 módulos | Baixa — é o padrão mais fácil do projeto |
| **G8** | **Nenhuma etapa do roteiro cabe em `nat_flow_state`.** A coluna `etapa` tem CHECK com 7 valores fixos; nenhum é "aguardando motivação pós-agendamento" ou "confirmando horário" | `nat_flow_state_etapa_valida` | Média — migração ou tabela nova |
| **G9** | **194 cliques capturados, 0 roteados.** `nat_flow_state` está vazia, então todo clique cai em "fora da etapa" | `nat_flow.py:427` | Alta — é intenção sendo jogada fora, ~8/dia |
| ~~**G10**~~ | ~~13 subSources da LP sem `course_aliases`~~ | **10 de 13 resolvidos em 24/08** (`seed_course_aliases_lp.py`). Faltam 3, pendentes de confirmação do time — ver pergunta 11 | Baixa |
| **G11** | **Sem validação de LLM sobre a motivação.** O passo 3 pede resposta gerada do conteúdo real; hoje qualquer texto passa | `nat_flow.py:475` (Bloco 8, não iniciado) | Média |
| **G12** | **`ai_configs.is_enabled = false` e motor comentado.** Não há caminho ligado de LLM em produção | `main.py:537-618` | Média |
| **G13** | **Sem superfície para ligar o agente.** `nat_config` tem `PATCH /api/nat/config` (`nat_routes.py:476`), mas não há equivalente para o fluxo novo | — | Baixa |

---

## 3. Conflitos e riscos

### 3.1 O lead que já agendou recebe uma mensagem que contradiz o agendamento — **acontecendo agora**

`nat_boasvindas` diz, verbatim:

> *"Nossa equipe está disponível **neste momento** e um dos nossos consultores pode falar com
> você **nos próximos minutos**. […] Você tem alguns minutos disponíveis para conversar?"*

Medido: **52 pessoas que já tinham reunião marcada receberam essa mensagem.** Em 53 dos 54
agendamentos a boas-vindas saiu depois de a pessoa ter escolhido o horário — e a antecedência
mediana da reunião é de **quase 2 dias**. A pessoa acabou de marcar terça às 16h e recebe
"posso falar agora?".

E ela **responde**: dos que já tinham agendado, 14 clicaram — 9 em "Prefiro outro horário" e 5
em "Sim, Posso conversar agora". Ninguém do outro lado. `nat_flow_state` = 0 linhas.

Isto não é risco do agente novo. É o estado de hoje, e é o melhor argumento para o passo 4a
do roteiro ("lead já agendou → confirma data/hora").

### 3.2 O nome do curso vaza código de turma

Nenhum dos 13 subSources da LP tem linha em `course_aliases`, então `resolve_course_name` cai
no fallback (`course_names.py:29-34`), que só tira o prefixo `Pos`. Mensagem real, enviada:

> *"Recebi sua aplicação para a Pós-Graduação em **Grupos e Oficinas T2**"*

Também observado: `[NOME]` é o nome **completo** do cadastro — *"Olá, Marina leite Guimaraes
serra! 😊"*. O roteiro usa `[NOME]` em tom de conversa; hoje sai o campo inteiro, com a
capitalização que a pessoa digitou.

### 3.3 Cinco caminhos independentes mandam WhatsApp pelo mesmo número

| # | Caminho | Automático? | Trava |
|---|---|---|---|
| 1 | `exact_spotter.py:226` — boas-vindas | **Sim, ligada** | `welcome_status is not null` |
| 2 | `exact_routes.py:355` — massa (tela Automações) | Não | `welcome_guard.bloquear_se_boas_vindas` |
| 3 | `routes.py:207,242` — SDR na tela de conversa | Não | idem |
| 4 | `nat_sender.py:114,119,133` — NAT | Sim, **desligada** | `nat_pode_atuar`, fail-closed |
| 5 | `main.py:scheduled_messages_job` → `bulk_send_template` | Sim, por agendamento humano | herda a do #2 |

**Um agente novo seria o sexto**, e é o único que competiria diretamente com o #1 pelo mesmo
lead, no mesmo minuto, com a mesma intenção. `welcome_guard` protege o *template*
`nat_boasvindas` de sair pelas portas erradas (`welcome_guard.py:21,46`) — **não protege o
lead de receber duas mensagens de abertura diferentes**.

Foi exatamente esse tipo de duplicação que o `boas_vindas_wamid` resolveu entre boas-vindas e
NAT (`exact_spotter.py:330`). O mesmo desenho — **um dono por abertura, e adoção em vez de
reenvio** — é o que precisa valer aqui, e precisa ser auditado **antes** de qualquer ativação.

### 3.4 O guard da NAT barra quase todo lead da LP

Se o agente novo reusar `nat_pode_atuar` como está:

| Trava | `nat_guard.py` | Efeito nos leads da LP |
|---|---|---|
| `nat_enabled` | :211 | `false` — bloqueia tudo |
| `nat_start_at` | :217 | `NULL` — bloqueia tudo, mesmo com `enabled=true` |
| `funnel_id == 18535` | :224 | Nasce em 18535, mas **21 dos 80 já saíram** para 18537/21007. O guard lê o funil ATUAL, que o sync sobrescreve |
| `assigned_to ∈ {4,5}` | :234 | 75/80 passam (Thobias 53, Valéria 22); 5 caem em Vi/Isa/Victória |
| `max_envios_hora = 20` | :245 | Folgado a ~10/dia; aperta em pico ou em disparo retroativo |

Além disso, `_resolver_lead_e_wa_id` no ramo `Contact` **carrega todos os `exact_leads` com
telefone e compara em Python** (`nat_guard.py:172-176`) — hoje são **9 005 linhas** (`phone1 is not null` de 9 132), dentro do
caminho de cada mensagem. É o risco 2 do `ESTADO_NAT_20260809.md`, ainda aberto e agora maior.

### 3.5 Janela de 24 h e disparo retroativo

A abertura é sempre business-initiated: lead novo não tem inbound, `janela_aberta` devolve
`False` (`nat_sender.py:44`), e **só template aprovado passa**. Depois do primeiro clique ou
resposta a janela abre e texto livre é permitido — é o que faz o Bloco 8 (LLM) ser viável sem
aprovar template para cada variação.

O risco de volume não é o fluxo novo: são **3 680 leads no funil 18535**, dos quais 3 579 em
`Descartado`. Um follow-up de silêncio ou uma trava de data mal posta e a régua varre a base
inteira. As duas defesas que existem hoje:

1. `nat_start_at` por `register_date`, **imune a backfill e a falha de sync** (`nat_guard.py:219`);
2. `welcome_status is not null` como carimbo permanente, inclusive para "pulado"
   (`exact_spotter.py:170-185`).

Ambas precisam de equivalente explícito no agente novo. **Nenhuma delas nasce de graça.**

### 3.6 Riscos herdados que continuam de pé

| Risco | Fonte | Situação |
|---|---|---|
| `failed` bloqueia reenvio para sempre | `exact_spotter.py:186` | **128 leads** `failed` hoje, mais 195 presos em `sent`. Só saem pelo `POST /reenviar` com `force=True`, um a um |
| `delivery_health` com `MAX_FALHAS_PARA_VOLTAR = 0` | `delivery_health.py:139` | Uma falha na janela de 60 min e o alerta nunca anuncia recuperação |
| Docstring de `nat_guard.py` com referências de linha erradas | `nat_guard.py:6-8` | **Corrigido em 24/08.** A afirmação "não está plugada" já tinha caído em 11/08 (commit `39ac2cf`) — este RECON a reportou como aberta por erro. O que restava era `nat_flow.py:340`, linha que nunca teve a chamada (é 481) |
| Sem calendário de feriados | `nat_guard.py:200` | Em feriado o horário comercial passa e o agente dispara |
| `whatsapp_templates` com 1 linha contra 81 na Meta | §1.6 | Não é espelho; quem assumir que é, erra |

### 3.7 Quem responde a uma mensagem recebida

Hoje, no webhook, uma mensagem inbound passa por: gravar `Message` → gravar `NatButtonEvent`
(savepoint) → `processar_clique`/`processar_texto` (savepoint) → notificar o SDR dono
(`main.py:412-501`). O bloco da IA vem depois e está inteiro comentado.

Um agente novo se pluga **no mesmo lugar**, no terceiro savepoint. E aí a pergunta fica:
`processar_texto` da NAT e o handler novo veriam o mesmo texto. Com `nat_flow_state` vazia a
NAT devolve cedo, mas isso é acidente de configuração, não desenho. **A precedência precisa
ser explícita** — um dono por contato, decidido antes de qualquer envio.

Some-se o tráfego humano: 1 456 mensagens inbound de texto em 30 dias, contra 194 cliques. A
maioria do que chega é conversa com SDR, não resposta a fluxo.

---

## 4. Perguntas abertas para o time

1. **O roteiro.** `docs/roteiro-prequalificacao.md` não está no repo. Sem ele, os textos
   exatos, a ordem das perguntas e os critérios de ramificação são inferidos. **Precisa entrar
   antes de qualquer implementação.**
2. **`[formação]` — "Profissão" basta?** O formulário coleta *Profissão* (Psicologia,
   Enfermagem, TO…) e *Ensino Superior* (Sim/Não). O roteiro diz `[formação]`, e o template
   `nat_sim` já aprovado diz *"sua formação é em {{2}}"*. "Sua formação é em Psicologia" ✓;
   "sua formação é em Outra profissão" ✗. **Qual é a regra quando a resposta é "Outra
   profissão" (6 casos) ou "Ensino Superior: Não" (6 casos)?**
3. **Leads que não vêm da LP.** 63 % dos leads recentes vêm de `Rd Marketing` (126 de 200), e só 33 %
   deles têm profissão no `description`, em formato variável. **O agente atende só quem vem
   da LP, ou atende todos com degradação para quem não tem formação?**
4. **Número da consultora (G5).** Não existe em nenhuma fonte do sistema. **Quem fornece — e
   é número fixo por consultora, ou o lembrete deve mandar o número do canal (11 95213-7432),
   que é por onde a conversa já acontece?**
5. **Consultora fixa por lead?** Hoje quem atende é escolhida por menor carga do dia
   (`agendar.py:246`), no instante do agendamento. **Se o lead remarcar, muda de consultora?**
   (Lembrando: sem `ScheduleRemove`, remarcar queima o slot antigo para sempre.)
6. **A régua R$100/R$200/R$300.** A resposta é coletada e guardada, mas não existe nenhuma
   regra escrita sobre ela. **O que muda no atendimento por faixa — e isso vira lógica do
   agente ou continua critério do consultor na ligação?**
7. **Substituir ou coexistir com a boas-vindas?** Ligar o agente sem decidir isto significa
   duas aberturas para o mesmo lead. E se substituir: **`auto_welcome_config.enabled` vai a
   `false`?** (Foi religada em 28/07 pela Valéria — há dono.)
8. **Follow-up de silêncio.** Ponto em aberto do roteiro e **decisão pendente registrada, não
   proposta**. Hoje não existe nenhuma cadência automática que fale com o lead por silêncio;
   a base do 18535 tem 3 680 leads, 3 579 descartados.
9. **NAT: fica, morre, ou vira o agente novo?** `nat_flow_state` está vazia há um mês, mas
   4 templates NAT estão aprovados, `nat_sim` é literalmente o passo 1 do roteiro, e 194
   cliques já chegaram.
10. **Nome comercial de 3 cursos.** `Pos Infantojuvenil EAD` (há DOIS cursos infantojuvenis
    no cadastro — qual é o EAD?), `Pos Psicologia Escolar` e `Pos Enfermagem em Saude Mental`
    não têm nome completo em nenhuma fonte do projeto. Até a resposta, o lead desses três
    recebe o código cru ("Pós-Graduação em Enfermagem em Saude Mental", sem acento).
11. **Os 194 cliques órfãos.** ~8/dia, 175 pessoas, nenhuma resposta. **Alguém deveria
    responder retroativamente, ou a régua começa do zero?** (A janela de 24 h já fechou para
    quase todos.)

---

## 5. Blocos de implementação sugeridos

Sem código. Dependências explícitas. **Nada aqui deve ser iniciado antes de o roteiro entrar
no repo (pergunta 1) e das perguntas 2, 4 e 7 terem resposta** — elas mudam o conteúdo dos
templates, que é o caminho crítico.

### Bloco 0 — Decisões (bloqueia todo o resto)
Roteiro no repo. Respostas às perguntas 2, 4, 7. Sem isso, submeter template à Meta é
gastar dias de aprovação em texto que vai mudar.

### Bloco 1 — Templates da Meta ⚠️ **caminho crítico, começa primeiro**
Aprovação leva dias. Submeter **em paralelo** ao resto.

| Template | Variáveis | Categoria | Por quê |
|---|---|---|---|
| Abertura pós-aplicação — **já agendou** | nome, curso, data, hora, consultora | UTILITY | Passo 4a. Não existe. Hoje esses 52 leads recebem o texto errado (§3.1) |
| Abertura pós-aplicação — **não agendou** | nome, curso, formação | MARKETING | Passo 4b. `nat_sim` cobre a frase da formação, mas é resposta a clique, não abertura |
| **Lembrete T-30min** | nome, hora, **nome da consultora**, **número da consultora** | **UTILITY** | Passo 5 (G6). Bloqueado pela pergunta 4 |

Reaproveitar sem submeter nada: `nat_sim` (formação, aprovado), `nat_boasvindas` (abertura
atual), `nat_outro_horario`, `nat_confirma_transferencia`.

Nota de categoria: 79 dos 81 templates do WABA são MARKETING. Lembrete de reunião agendada é
o caso canônico de UTILITY — vale submeter assim e medir.

### Bloco 2 — Fiação da formação (independente do Bloco 1, pode ir junto)
`agendamentos.extras` → mensagem. Fecha G2 e o `"formacao": ""` de `nat_flow.py:115`. Para
leads da LP não precisa tocar na Exact nem no sync: o dado já está no nosso banco, com
cobertura de 100 % e chave de junção (`lead_id`) confirmada em 54 pares.
Opcional, depois: `description` no sync (G3) + parser (G4) para cobrir leads do RD.
**Depende de:** pergunta 2.

### Bloco 3 — Gatilho e estado (depende do 0)
Onde o fluxo nasce, e onde o estado mora.
- Gatilho no formulário, **com espera** — os dados dizem 5 min (máximo observado 3 min 14 s
  entre formulário e agendamento). Antes disso a ramificação 4a/4b decide errado.
- Estado em **tabela nova**, não em `nat_flow_state`: o CHECK `nat_flow_state_etapa_valida`
  fixa 7 etapas e nenhuma serve (G8). Reusar exigiria alterar o CHECK e misturar dois fluxos
  numa linha por contato — a chave é `contact_wa_id` UNIQUE.
- Estado **nunca** em `exact_leads` — o sync sobrescreve de 10 em 10 min.
- Trava de data equivalente a `nat_start_at`, por `register_date` (§3.5).

### Bloco 4 — Precedência e envio único (depende do 3) ⚠️ **auditar antes de ligar**
A lição do 131042 e do `boas_vindas_wamid`: **auditar caminhos de envio duplicado antes de
qualquer ativação**, não depois.
- Um dono por abertura. Decidir `auto_welcome_config.enabled` (pergunta 7).
- Um dono por mensagem recebida, explícito no webhook (§3.7).
- Guard próprio: reusar `dentro_horario_comercial` e o padrão fail-closed; **não** reusar as
  travas de funil/SDR sem revisar (§3.4).
- Corrigir `_resolver_lead_e_wa_id` (varredura O(n) sobre 9 005 linhas) se o guard for reusado.

### Bloco 5 — Agendamento pelo WhatsApp (depende do 3)
Passo 4b. `resumo_por_dia` para ofertar, `slots_livres(usar_cache=False)` + `agendar(lead_id=…)`
para escrever. Passar sempre `lead_id` — é o que impede o lead duplicado.
**Sem `ScheduleRemove`**: cada remarcação queima um slot. Se o fluxo oferecer remarcar, isso
precisa ser decisão consciente, não efeito colateral (pergunta 5).

### Bloco 6 — Lembrete T-30min (depende dos Blocos 1 e 3, e da pergunta 4)
`nat_scheduler` com `kind` novo — não `scheduled_messages`, que é fila de disparo em massa
criada por humano e passa por `bulk_send_template`. O scheduler dá: lock por linha, ação e
marcação na mesma transação, 3 retentativas, e o índice único
`uq_nat_sched_pendente_por_contato (kind, contact_wa_id) WHERE status='pendente'`, que já
impede dois lembretes pendentes para o mesmo contato.
Agendar no instante do `passo='agendado'`, para `slot_inicio - 30min`. Reler o estado na
execução, nunca confiar no payload — padrão de `nat_recuperacao.py:32-42`.
**Bloqueado por G5**: sem número da consultora, o lembrete não é o do roteiro.

### Bloco 7 — LLM nos pontos de interpretação (depende do 3)
Passo 3: validação da motivação gerada do conteúdo real. `ai_configs.is_enabled=false` e o
motor no webhook está comentado (`main.py:537-618`) — ligar aquele bloco de volta liga a IA
para **637 contatos** de uma vez (§1.7). O caminho novo deve ser próprio e restrito ao fluxo.
Fallback determinístico no padrão de `nat_copy.parametros_template`: quando não dá para
afirmar com honestidade, **não afirma** — devolve `None` e quem chama não envia.
Volume: ~20 chamadas/dia. Custo não é fator.

### Bloco 8 — Higiene (independente, barato, melhora hoje)
- ~~13 linhas em `course_aliases`~~ **Feito em 24/08**: 10 inseridas, 3 pendentes de nome
  comercial. Também corrigiu a **falta de acento** — o fallback devolvia "Alcool e Drogas T4"
  e "Saude do Trabalhador", o que o §3.2 não tinha capturado.
- ~~Primeiro nome em vez do cadastro completo em `[NOME]`.~~ **Feito em 24/08** (`app/nomes.py`).
- ~~Corrigir a docstring de `nat_guard.py:6-7`, que afirma o oposto do código.~~ **Premissa errada**: aquilo caiu em 11/08. Feito em 24/08 o que de fato faltava — as duas referências de linha da docstring, ambas defasadas.

### Fora de escopo, registrado
**Follow-up de silêncio.** Decisão pendente (pergunta 8). Não implementar sem critério de
parada e trava de data: 3 680 leads no 18535, 3 579 descartados. Nenhuma cadência automática
fala com o lead hoje — esta seria a primeira.

---

## 6. Divergências entre docs e código/banco

| Doc | Afirma | Realidade medida (24/08) |
|---|---|---|
| `ESTADO_NAT_20260809.md` risco 1 | "`nat_boasvindas` sai duas vezes quando a NAT ligar" | **Resolvido.** `boas_vindas_wamid` passado em `exact_spotter.py:330`; modo adoção em `nat_flow.py:510-526` |
| `ESTADO_NAT_20260809.md` §2 | `nat_button_events` = 82 | **194** (175 contatos, até 24/08) |
| `ESTADO_NAT_20260809.md` §2 | 8 908 leads; `failed` 118, `sent` 190, `delivered` 146 | **9 132** leads; `failed` **128**, `sent` **195**, `delivered` **329** |
| `nat_flow.py:93` | "`formacao` volta sempre vazia… no Exact ela não é campo estruturado" | Verdade para o código, **falso para o dado**: 100 % dos leads da LP têm profissão estruturada em `agendamentos.extras` e no `description` da Exact |
| `nat_copy.py:95` | "A formação vem do Exact e falta em ~49 % dos leads" | Medido nos 200 mais recentes: falta em **0 %** dos leads da LP, **67 %** dos do RD |
| ~~`nat_guard.py:6-7`~~ **este RECON** | que a docstring ainda dizia "NÃO está plugada em lugar nenhum" | **Errado.** A docstring foi corrigida em 11/08 (`39ac2cf`) e já dizia "ONDE ESTÁ PLUGADA". O achado veio copiado do `ESTADO_NAT_20260809.md` sem reconferir o arquivo — o conserto entrou 2 dias depois daquele doc. Defeito real e menor: as linhas citadas (`nat_flow.py:340`, `nat_sender.py:94`) estavam defasadas; corrigidas em 24/08 |
| `docs/form-nativo-snippet.html:91` | "Valores válidos hoje: PosMulheridades, posgenerot2, PosPraticasDialogicasTurma1" | 13 origens em produção (`AGENDAMENTO_SUBSOURCES`); 11 já com agendamento real |
| `agendamento/extras.py:6` | extras "variam por página e por campanha" | Na prática **as mesmas 4 chaves em 80 de 81 casos** — só 1 linha usa `profissao`/`como_conheceu` em snake_case |
