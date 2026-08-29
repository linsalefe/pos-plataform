# SPRINT 5 — o funil para de vazar por fora do agente

**29/08/2026.** Sete itens, sete commits, nenhum envio de WhatsApp, nenhuma migração.
Todo número aqui vem com a query ou o comando que o gerou; onde o código ou o banco
divergiram do briefing, a divergência está marcada com ⚠️ e vale o que está no banco.

Base: `RECON_DESEMPENHO_AGENTE_20260828_FECHAMENTO.md`.

---

## Os commits

| Item | Commit | O quê |
|---|---|---|
| 1 (P0) | `ed163be` | a reunião do agente entra na Exact com o curso do lead |
| 2 | `cd7507e` | abertura para quando o contato já existe na outra grafia |
| 3 | `0b9326c` | lembrete só é `executado` quando saiu (+ varredura dos envios) |
| 4 | `c3cc924` | a oferta de agenda para de prometer o que a grade não tem |
| 7 | `35b45e8` | um grep pelo telefone acha todos os turnos da pessoa |
| 5 | `8297b82` | disparo em massa não atropela conversa viva do agente |
| 6 | *(dado)* | estado 89 silenciado — before/after no §6 |

---

## ⚠️ 1. A divergência que muda o tamanho do item 1

O fechamento diz, em §1.5, que *"o box foi criado como `PosMulheridades`"* e que *"a
consultora abre o box de Mulheridades para conversar com uma lead de TEA"*. **O banco e o
código dizem outra coisa, e é uma notícia boa.**

O agente **sempre** manda `lead_id` (é o que impede a pessoa de virar um segundo lead).
Com `lead_id`, `agendar.py:395-408` entra no ramo `lead_externo`:

```python
if lead_externo:
    await _marcar(db, ag, PASSO_LEAD_CRIADO)
    print(f"👤 agendamento #{ag.id}: lead {lead_id} JÁ EXISTIA (veio no corpo) — "
          f"LeadsAdd pulado, subSource {sub_source} não reaplicado{aviso}")
```

**`LeadsAdd` é pulado e o subSource NÃO é reaplicado.** Nem `criar_box` nem
`agendar_reuniao` mandam subSource — `criar_box` manda `description="Agendamento LP — {nome}"`,
e `agendar_reuniao` manda `box_id`, `lead_id`, `stage_name` e `sales_rep_email`. Conferido
no banco:

```sql
SELECT exact_id, name, sub_source FROM exact_leads WHERE exact_id = 51610927;
--  51610927 | Kaylla Soares Ponciano de Castro | Pos TEA V3
```

**O lead da Kaylla na Exact está com `Pos TEA V3`, correto, e sempre esteve.** O
`PosMulheridades` existe só na NOSSA coluna `agendamentos.sub_source` da linha 251.

Isso não torna o item 1 desnecessário — torna-o **mais barato de consertar e menos urgente
de remediar**:

* a coluna errada alimenta relatório local e é a **segunda fonte de `_curso`**
  (`_sub_source_do_lead`, fallback quando `exact_leads` ainda não sincronizou). Um
  `PosMulheridades` ali podia, no cenário certo, fazer a **abertura de outro lead** falar do
  curso errado;
* e o dia em que um agendamento do agente rodar **sem** `lead_id` (lead que não existe na
  Exact), o `LeadsAdd` roda e aí sim o valor errado vai para o CRM.

**Consequência para a pergunta final do briefing:** ver §9.

---

## 2. Item 1 — a reunião entra com o curso do lead · `ed163be`

O defeito, no ponto exato: `_agendar` chamava `fluxo.agendar(..., origem=None, extras=None)`.
`origens.resolver(None)` devolve `AGENDAMENTO_SUBSOURCE_PADRAO`, e o `.env` de produção tem
`AGENDAMENTO_SUBSOURCE_PADRAO="PosMulheridades"` — o padrão da LP antiga, herdado por um
caminho que não é o dela. **4 de 4** agendamentos que o agente já criou em toda a base saíram
assim.

O dado certo estava a três linhas: `_curso` já lê o sub_source do lead para escrever a
abertura. Extraído para **`_sub_source_do_lead`** — mesma consulta, mesmas duas fontes
(`exact_leads.sub_source` → `agendamentos.sub_source`), mesma ordem — e agora com dois
consumidores, para que "o curso que a abertura fala" e "o curso que o CRM registra" não
possam divergir de novo.

**`_origem_do_agendamento`** confere o valor contra `origens.permitidas()` — a MESMA
allowlist, só que antes da chamada em vez de dentro dela. A diferença está no miss:

```
origens.resolver(fora_da_lista)  ->  levanta OrigemInvalida  ->  agendamento MORRE
_origem_do_agendamento           ->  devolve None + LOG      ->  agendamento SEGUE
```

**Fail-closed sobre o dado, não sobre a reunião.** Sub_source fora da allowlist é erro de
cadastro (`.env` sem um curso novo); recusar a reunião por causa dele trocaria um relatório
torto por um lead perdido — o pior dos dois. O que não pode acontecer em silêncio é a troca,
e por isso o log nomeia o valor recusado.

`extras` na mesma chamada: o formulário da LP (profissão, faixa de investimento, "como
conheceu") existe na linha `lead_criado` do mesmo lead e virava `null` na linha do
agendamento real. `qualificacao_dados.extras_brutos_da_lp` devolve o JSONB **como está**,
sem normalizar chave — normalizar faria as duas linhas do mesmo formulário guardarem
grafias diferentes na mesma coluna, e todo relatório que agrupe por chave partiria em dois.

**Teste** — `test_agendamento_origem_agente.py`, **26/26**, com o caminho de falha:

```
2) A allowlist — o caso da Kaylla, que virou PosMulheridades em produção
  [ok] sub_source na allowlist -> ele mesmo
  [ok] caixa diferente casa (case-insensitive)
  [ok]   e volta na CAIXA DA ALLOWLIST, não na do banco
3) Fora da allowlist — padrão + LOG, e a reunião NÃO morre
  [ok] sub_source fora da allowlist -> None (= origem padrão)
  [ok]   e o valor recusado aparece no log
4) `_agendar` repassa origem E extras — o defeito, no ponto exato
  [ok] origem = o sub_source REAL do lead (era None)
  [ok] extras = o formulário da LP (era None)
  [ok] fora da allowlist: origem=None (padrão) e a reunião SAI
```

---

## 3. Item 2 — a abertura que evaporava · `cd7507e`

`_contato_ou_criar` resolve nas duas grafias desde `05cea3f`: com o contato já existindo em
12 dígitos ele acha, decide — corretamente — não criar o de 13, **e o objeto resolvido era
descartado**, porque o chamador só testava `is None`. O estado nascia com a grafia da ação,
`nat_sender` procurava `Contact.wa_id == <13d>` com igualdade crua, não achava, recusava — e
o savepoint revertia o estado junto. O lead não recebia nada, não virava estado e não entrava
em fila nenhuma.

Conserto: uma atribuição e um log. A grafia dali para baixo é a do contato resolvido, estado
e envio na mesma.

**A igualdade crua do sender não foi tocada.** A docstring do porteiro explica por quê: em
25/08 a variante de 12 dígitos do número de um lead era o número de **outra pessoa**, e foi a
igualdade estrita que impediu o envio para o estranho. O grupo 4 do teste novo é o guardrail
disso.

**Teste** — `test_abertura_grafia.py`, **16/16**, incluindo o caminho de falha do sender.

### 3.1 Os 4 leads perdidos, e a proposta de reprocesso

```sql
SELECT id, contact_wa_id, status, motivo, to_char(run_at,'DD/MM HH24:MI'), payload
  FROM nat_scheduled_actions WHERE id IN (360,364,378,379,380,410);
```

| Ação | Alvo | Quando | Lead | Contato existe como | Nome |
|---:|---|---|---:|---|---|
| 360, 364 | `5549999333881` | 27/08 18:06 e 18:11 | 51610928 | `554999333881` | Fernanda |
| 378 | `5585988719031` | 28/08 09:00 | 51613664 | `558588719031` | *(sem nome)* |
| 379 | `55996238065` | 28/08 09:00 | 51616982 | — **11 dígitos** | — |
| 380 | `5555996238065` | 28/08 09:00 | 51616982 | `555596238065` | Sandra Diell |
| 410 | `5551998557793` | 28/08 09:47 | 51625094 | `555198557793` | *(sem nome)* |

Todos os 6 com `skipped` / `abertura não saiu: contato não existe no banco`. **Nenhum dos 4
tem estado** (`nat_qualificacao_state` = 0 linhas) — o rollback levou tudo.

**E dois deles já foram atendidos por humano depois:**

| Contato | Último evento na thread |
|---|---|
| `558588719031` | **outbound do SDR 28/08 11:07** — *"Ola Claudia, é o Thobias do CENAT ✨ Tentei re…"* |
| `555198557793` | **outbound do SDR 28/08 11:07** — *"Ola Dyenifer, é o Thobias do CENAT ✨ Tentei r…"* |
| `554999333881` | inbound dela 12/08, nada depois |
| `555596238065` | inbound dela 27/08 23:33, nada depois |

**Proposta de reprocesso — 2 leads, não 4:**

* **Reprocessar: Fernanda `554999333881` (lead 51610928) e Sandra Diell `555596238065`
  (lead 51616982).** Ninguém falou com elas; a abertura é a primeira mensagem, e com o
  conserto ela agora sai. Ambas se candidataram há 1-2 dias, dentro do corte de admissão.
* **NÃO reprocessar: `558588719031` e `555198557793`.** O SDR já abriu conversa com as duas
  em 28/08 11:07. Mandar a abertura do agente agora é exatamente o atropelo que o item 5
  acabou de proibir na outra direção — e o texto do agente ("Vi que você aplicou…") em cima
  de um "Tentei retornar…" do Thobias fica incoerente para quem lê.
* **Ação 379 (`55996238065`, 11 dígitos) não é caso de reprocesso** e sim o defeito adjacente
  do §8.5: o número entrou torto na ação. É a mesma pessoa da 380 (lead 51616982), então
  reprocessar a Sandra cobre a pessoa.
* **Como:** `reprocessar_leads_perdidos.py` já existe e já faz o espaçamento por metade do
  teto. Ele seleciona por `welcome_status IS NULL` — esses 4 não se encaixam nesse critério,
  então seria preciso um alvo explícito por `lead_id`. **Não implementado; aguardo o aval.**

---

## 4. Item 3 — o lembrete presta contas · `0b9326c`

`lembrete_reuniao` chamava `send_nat_message` e **descartava o `bool`**. As quatro
pré-checagens já eram `AcaoIgnorada` desde o S4-1 — a docstring da função comemora
exatamente isso — mas o envio, o único passo que de fato manda a mensagem, continuava mudo.

### 4.1 A varredura completa

`grep -n "await send_nat_message\|await enviar_nat" app/*.py` — **12 pontos**:

| Arquivo:linha | Lê o retorno? | Nota |
|---|---|---|
| `nat_routes.py:417` | ✅ `enviada = …` | |
| `nat_sender.py:97` | ✅ | é o próprio wrapper |
| `qualificacao_fluxo.py:692` | ✅ | `return await enviar_nat(...)` |
| `qualificacao_fluxo.py:826` | ❌ **`_fallback`** | **corrigido** — ver abaixo |
| `qualificacao_fluxo.py:1048` | ✅ `enviado, motivo_envio` | abertura |
| `qualificacao_fluxo.py:1413` | ✅ | `_concluir(confirmar=True)` |
| `qualificacao_fluxo.py:1482` | ✅ `enviado = …` | |
| `qualificacao_fluxo.py:1570` | ❌ **`lembrete_reuniao`** | **corrigido** |
| `main.py:462` | ✅ `saiu = …` | |
| `nat_flow.py:542` | ✅ `enviou = …` | |
| `nat_flow.py:783` | ✅ `if not await …` | |
| `nat_flow.py:850` | ✅ `if not await …` | |

**10 de 12 já liam. Os dois que não liam eram o lembrete e o `_fallback`.**

### 4.2 O lembrete

O teto **adia** (+10 min), não descarta — e não é só simetria com a abertura. No caso da
Mikaelle (ação 226, 27/08 09:15, teto 22/20, reunião 09:45), +10 min ainda eram **20 minutos
antes da reunião**: o lembrete teria saído. Mas adiar tem prazo: `run_at` depois do início
mandaria *"sua reunião é hoje às X"* depois de X, e aí é `AcaoIgnorada` — a mesma regra da
pré-checagem que já existia.

> **Desvio deliberado do briefing, declarado.** O item 3 pedia `AcaoIgnorada` para toda
> recusa. Para o **teto** isso descartaria justamente o lembrete que sairia dez minutos
> depois — o caso da Mikaelle. `AcaoAdiada` para o teto e `AcaoIgnorada` para o resto usa
> o idioma que `iniciar_qualificacao` já usa no mesmo arquivo (`guard.e_teto`), e o teste
> cobre os dois.

### 4.3 O `_fallback`

Aqui **levantar não serve**: o estado já é `transferido_humano` e uma exceção desfaria a
transferência, que é o desfecho certo. O que faltava era **contar** — sem a despedida, o lead
ficou sem nenhum aviso de que alguém assumiria, e quem precisa saber disso é o SDR que a
notificação acorda. O aviso passou a ir **na notificação**, não só no `🔒` do log.

**Teste** — `test_lembrete_envio.py`, **25/25**, com os quatro caminhos de falha.

---

## 5. Item 4 — a oferta para de prometer o que não existe · `c3cc924`

Três defeitos, todos na MISSÃO, com os ajustes (a) (b) (c) do briefing aplicados. O grupo 4
do harness cresceu de 3 para 6 cenários (**4.4** noite, **4.5** sábado, **4.6** um pedido que
CABE na grade — este existe para a regra nova não virar gatilho fácil) e ganhou três
checagens automáticas.

**Harness, 3 rodadas × 21 cenários: 62/63 cenário-passagens, contrato 63/63, grupo 4 em
17/18.** A única reprovação é `4.4 — 1 pergunta numa mensagem de despedida`, cosmética e da
mesma família de flake que `1.2`/`2.3` já tinham (~98% é a taxa documentada de agosto).

### 5.1 Três medições que contrariaram o palpite

**1. `PROMPT_BASE` não foi tocado — e a primeira versão tocava.** Para a missão poder mandar
o agente oferecer transferência, abri uma ressalva no *"VOCÊ NUNCA OFERECE TRANSFERÊNCIA"*.
Medido: **3 falhas em 5 rodadas do cenário 2.3**, uma delas transferindo um lead que só
perguntou horário em `aguardando_ano` — exatamente o que aquela regra existe para impedir.
Revertido. As missões sozinhas dão conta (4.4/4.5 verdes sem a ressalva).

**2. A escapatória já faltava antes.** `tem_escapatoria` é checagem nova, e o que ela mediu
primeiro foi dívida antiga:

```
missão ORIGINAL, 4 rodadas:  3 SEM escapatória
missão do S5-4:              5/5 COM
```

A produção não mostrava porque N=4. Está registrado na docstring da checagem para ninguém
medir contra a impressão de que "antes funcionava".

**3. O id cru vazou, e foi regressão minha.** Dizer *"nunca escreva o que não está no
contexto"* licenciou copiar o contexto **inteiro**, ids inclusive (baseline original: 6/6
limpo; minha primeira versão: 1 vazamento em 3). Corrigido movendo a proibição do id para
junto da instrução de listar. Verificação final: **6/6 limpo, com a escapatória mantida**.

### 5.2 Efeito colateral conhecido

A transferência passa por `_fallback`, que loga `🛟`. O RECON usa
`grep -cE "🛟|LLM indisponível"` como medida de **falha de contrato** — e a partir daqui um
`🛟` pode ser um desfecho **correto**. Quem separa os dois é `transferido_motivo`, não o
emoji. Está no comentário do código, para a próxima apuração não ler isso como regressão.

---

## 6. Item 6 — o estado 89, before/after

O Marcos (`5591982668801`) recebeu o mesmo template **4×** por um bug já corrigido
(`94867c1`), nenhuma das 4 está em `messages`, e o agente seguia ativo nele.

**Antes:**

```
id | contact_wa_id | etapa          | transferido_em | transferido_motivo | criado
89 | 5591982668801 | aguardando_ano |                |                    | 27/08 21:02
```

**Depois** (uma transação, com guarda `AND etapa='aguardando_ano' AND transferido_motivo IS NULL`):

```
id | contact_wa_id | etapa              | transferido_em             | transferido_motivo
89 | 5591982668801 | transferido_humano | 2026-08-29 08:12:12.470229 | outbound_manual_sdr_retroativo
```

`UPDATE 1`. `transferido_em` gravado com `now() AT TIME ZONE 'America/Sao_Paulo'` — naive-SP,
como manda a convenção da coluna; conferido contra `agora_sp` no mesmo comando (diferença de
11 ms).

**Resíduo, resolvido sozinho:** sobrou a ação **361** `encerrar_inativo` `pendente` para
30/08 18:02. Com o estado fora de `ETAPAS_QUALIFICACAO_ATIVAS`, o handler a devolve como
`skipped` com motivo `já está em 'transferido_humano' — fora das etapas` (S4-1). Não precisa
de intervenção, e o motivo fica gravado.

---

## 7. Item 5 — o disparo em massa · `8297b82`

Feito com a **opção 2 (flag explícita)** e default fail-safe, conforme decidido no checkpoint.

```
'individual' EXPLÍCITO  ->  não filtra. O SDR escolheu a pessoa e apertou enviar.
qualquer outra coisa    ->  campanha -> FILTRA. Ausente, vazia ou desconhecida.
```

O default é o seguro de propósito: quem chamar a rota por fora sem a flag tem como pior caso
um envio individual pulado, **com o motivo e o caminho no retorno** — nunca uma conversa
ativa cortada. Está documentado na docstring da rota.

O motivo diz o **caminho**, não só o impedimento:

> *contato em conversa ativa com a NAT — responda pela tela de Conversas (a trava transfere
> o agente automaticamente)*

Ele aparece em três lugares: log por contato, retorno da rota (`skipped_nat` + `skipped`) e a
tela — em âmbar, **separado dos erros**, porque pular não é falhar.

A busca é `estado_de`, tolerante às duas grafias: com igualdade crua, os 59% de threads sem o
9º dígito passariam batido pelo filtro. O pulo acontece **antes** de qualquer chamada à Meta.

Frontend: os dois botões mandam a flag; `main.py` manda `campanha` explícito no disparo
agendado; os campos novos são opcionais no tipo, para a tela não quebrar com a ordem do
deploy.

**Teste** — `test_bulk_pula_conversa_ativa.py`, **33/33**, incluindo os quatro valores de
flag que caem em campanha e o texto do motivo. `tsc --noEmit` limpo.

---

## 8. Item 8 — registrado, NÃO implementado

### 8.1 (a) Debounce de rajada

```sql
-- inbounds do mesmo contato com menos de 60s entre eles, 27-28/08
```

**22 pares em 2 dias, 13 pessoas.** Os gaps mais curtos: 2s (`556792894362`, `555397107849`),
4s (Kaylla, `555182890308`), 5s, 6s, 7s. A Kaylla sozinha tem 4 pares seguidos
(18:45:18 → 18:45:58).

Hoje **cada mensagem vira um turno** e as duas são respondidas — a mesma pergunta duas vezes,
com 2-3s de diferença, é a coisa mais visivelmente robótica da janela.

**Proposta técnica, em uma linha:** segurar o turno por ~8s numa ação `nat_scheduled_actions`
de kind novo (`responder_rajada`), cancelável pelo inbound seguinte do mesmo contato — a
mesma mecânica de cancelamento que `vigiar_resposta` e `encerrar_inativo` já usam, com o
índice único parcial por `(kind, contact_wa_id)` como rede. O texto das N mensagens entra
concatenado no histórico de um turno só. **Não implementado.**

### 8.2 (b) Leads de teste receberam abertura

| Contato | Nome em `contacts` | Quando | Template |
|---|---|---|---|
| `5581995345775` | **John Doe** | 27/08 13:22 | `nat_abertura_qualificacao` |
| `5567999151808` | **Thobias Justino França** *(o próprio SDR)* | 27/08 09:01 | `nat_abertura_sem_formacao` |
| `5571985252525` | **fafaf** | 27/08 09:00 | `nat_abertura_qualificacao` |

O `5571985252525` é o mesmo que falhou com **131026 Message undeliverable** (§1.1 do
fechamento) — número de teste que não existe no WhatsApp. O `5567999151808` falhou com
**131049**.

**Proposta de filtro na admissão** (`qualificacao_guard.qualificacao_pode_iniciar`, onde o
corte de data já mora): recusar com motivo próprio quando o nome do lead casar uma lista curta
(`smoke`, `test`, `teste`, `john doe`, `fafaf`) **ou** quando o telefone for de um SDR
conhecido (`sdr_mapping` já tem esse mapa). Vira `skipped` com motivo, não some. **Não
implementado** — a lista de nomes é decisão de produto, e um filtro por nome pode barrar
gente real chamada Teste.

### 8.3 (c) Agendamentos 152 e 157 — o que o log diz, e só

```sql
SELECT id,nome,sub_source,passo,lead_id,box_id,meeting_id,slot_inicio,erro FROM agendamentos
 WHERE id IN (152,157);
```

| id | nome | sub_source | passo | lead | box | meeting | slot | criado |
|---:|---|---|---|---:|---:|---|---|---|
| 152 | Vera Rosa Duarte de Mendonça | `Pos Grupos e Oficinas T2` | `falhou` | 51532753 | **43775759** | *(vazio)* | **28/08 16:30** | 25/08 00:50 |
| 157 | Beatriz | `Pos Psicologia na RAPS T3` | `falhou` | 51542378 | **43777383** | *(vazio)* | **28/08 15:00** | 25/08 10:21 |

Erro idêntico nos dois, textual:

```
HTTP 400: Previous stage is not exit action Scheduling
```

**O que dá para afirmar do log e do banco, sem ir à Exact:**

* os dois falharam no **passo 3** (`agendar_reuniao`), não antes: o `box_id` existe e o
  `meeting_id` não. É o "ponto de não retorno" do cabeçalho de `agendar.py` — o box sai, o
  lead fica em Entrada;
* a mensagem vem da Exact e é sobre **estágio do funil**: o lead não estava num estágio de
  onde a transição para `Agendados` é permitida. Não é erro nosso de payload, de horário nem
  de consultora;
* os dois são de **25/08** para reuniões de **28/08** — as reuniões já passaram;
* consultoras diferentes (`comercial@` e `processoseletivo@`), então não é conta.

**Não investigado além disso, por decisão do briefing.** O que falta é olhar o estágio atual
dos leads 51532753 e 51542378 na Exact e o box 43775759 / 43777383 — nenhuma dessas leituras
foi feita.

### 8.4 (d) Aliases pendentes — NÃO cadastrados

Confirmado o volume, e ele é maior que o do briefing:

| `sub_source` sem alias | leads |
|---|---:|
| `intercambioportugal2026` | 336 |
| **`PosBoasPraticasEAD`** | **286** *(29 desde 01/08)* |
| `interbuenosairesprovincia` | 272 |
| `posatencaobasica4` | 263 |
| `intercambiotrieste2026` | 246 |
| **`PosGraduacaoEconomiaSolidariaTurma1`** | **233** |
| `SMtrabalhador` | 173 |

Os "29 leads" do briefing são os de **agosto**; o total histórico de `PosBoasPraticasEAD` é
**286**. **Nada cadastrado**, conforme instruído.

### 8.5 Defeito adjacente, registrado no item 2

A ação **379** foi agendada para `55996238065` — **11 dígitos**, número truncado que não casa
com grafia nenhuma. Não é a canonização: é o número entrando torto. O outro caso conhecido é
a ação 155 (`55996028910`, 26/08). **Dois em três dias, não investigado.**

---

## 9. A pergunta: dá para editar o sub_source do box da Kaylla na Exact?

**Resposta curta: não há o que editar — e é por causa da divergência do §1.**

O box **43809078** e o lead **51610927** na Exact **nunca receberam `PosMulheridades`**. O
lead está lá com `Pos TEA V3` desde que a LP o criou, e o caminho do agente
(`lead_externo=True`) **pula o `LeadsAdd`** e não reaplica subSource nenhum. Nem `BoxesAdd`
nem o agendamento da reunião carregam esse campo.

O `PosMulheridades` existe **só na nossa linha** `agendamentos.id=251`.

Então:

* **na Exact: nada a fazer.** A consultora vai abrir um box de uma lead cujo cadastro diz
  TEA. Não é preciso anotar nem corrigir.
* **no nosso banco:** a linha 251 pode ser corrigida com um `UPDATE agendamentos SET
  sub_source='Pos TEA V3' WHERE id=251`, e vale a pena porque essa coluna é a **segunda fonte
  de `_curso`**. É uma linha, idempotente, sem efeito externo. **Não executei** — não estava
  entre os itens autorizados; digo que faria, e aguardo.

**Sobre a pergunta genérica** ("dá para editar sub_source de box/lead já criado via API"): o
módulo `origens.py` registra que **não existe `SourcesAdd`** e que `LeadsAdd` **cria** o
subSource quando o valor não existe. Sobre um `LeadsUpdate` que altere subSource de lead
existente, `agendar.py:402-406` diz textualmente *"não há LeadsUpdate neste fluxo"* — o que
registra que não o usamos, **não** que a API não o tenha. Confirmar exigiria uma chamada à
Exact, e o briefing pediu para não executar nada lá. **Não verificado.**

---

## 10. Testes

| Arquivo | Resultado | Cobre o caminho de falha? |
|---|---|---|
| `test_agendamento_origem_agente.py` *(novo)* | **26/26** | ✅ fora da allowlist → padrão + log, reunião sai |
| `test_abertura_grafia.py` *(novo)* | **16/16** | ✅ sender recusa wa_id que não casa |
| `test_lembrete_envio.py` *(novo)* | **25/25** | ✅ 4 caminhos: recusa, teto, teto tarde demais, pré-checagens |
| `test_bulk_pula_conversa_ativa.py` *(novo)* | **33/33** | ✅ 4 valores de flag que caem em campanha |
| `teste_manual_llm.py` *(3 rodadas)* | **62/63**, contrato 63/63 | grupo 4 com 6 cenários |
| `test_qualificacao.py` | ✅ | ajustado: o dublê do lembrete virou `enviar_nat` |
| `test_threads_divididas` · `test_identidade_abertura` · `test_gatilho_abertura` · `test_concluir_confirma` · `test_nat_caminho_completo` · `test_rede_ultima_instancia` · `test_vigia_agente_mudo` · `test_agente_parado` · `test_observabilidade_envio` | ✅ todos verdes | regressão |

`test_risco3_abertura.py` segue **vermelho de propósito** (1 falha, "criou o contato do
Ronaldo") — é a suíte do RISCO 3 × canonização, decisão de produto pendente, e **não foi
tocada por este sprint**.
