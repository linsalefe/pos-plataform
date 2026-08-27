# RECON — Threads divididas no Hub (12 × 13 dígitos)

**27/08/2026 · somente leitura · nada implementado, nada migrado, nada enviado.**

Um mesmo humano aparece como duas conversas no Hub porque o telefone brasileiro tem duas
grafias e `contacts.wa_id` guarda as duas como contatos distintos. `app/telefone.py` já resolve
isso nas BUSCAS do agente (sprints de 26–27/08); o que nunca foi migrado é o cadastro.

Este documento mede o tamanho, aponta a mecânica linha a linha, compara três consertos e
entrega o paliativo para o time comercial hoje.

---

## 0. Preflight — duas divergências contra o enunciado, as duas benignas

| esperado | encontrado | leitura |
|---|---|---|
| HEAD em `f6dd112`/`b5e4c58` | **`6f1f03a`** | commit acima é `docs(agendamento): 14a LP` — tarefa desta máquina hoje, não toca no agente |
| restart 27/08 ~01:52 UTC | **27/08 13:04:36 UTC** | restart da 14ª LP (allowlist de origens), 11h depois |

Nenhuma das duas mexe no agente nem no webhook. `git status` limpo, serviço `active`, boot com
as 7 validações de sempre. **Sigo.**

---

## 1. Tamanho do problema

Base: `contacts` inteiro (8 134 linhas), pareado por `app/telefone.py::variantes_wa_id` — o
mesmo par que o agente usa para buscar. Script: `recon_pares.py` (scratchpad).

```python
from app.telefone import variantes_wa_id
grupos = defaultdict(list)
for wa in todos_os_wa_ids:              # SELECT wa_id FROM contacts
    v = variantes_wa_id(wa)
    if len(v) == 2: grupos[v].append(wa) # a tupla e' identica para os dois membros
pares = {k: v for k, v in grupos.items() if len(v) >= 2}
```

| medida | número | % |
|---|---|---|
| contatos em `contacts` | 8 134 | 100% |
| contatos cujo número não gera par (estrangeiro, fixo, ilegível) | 88 | 1,1% |
| **pares de variantes REALMENTE duplicados** | **406** | — |
| contatos presos nesses pares | 812 | **10,0% do Hub** |
| grupos com 3+ contatos | 0 | — |

Nenhum grupo passa de 2. O problema é estritamente binário: 12 dígitos × 13 dígitos.

### Quantos são conversa de verdade dividida

| classe | pares | o que é |
|---|---|---|
| **A. dividida com fala humana dos dois lados** | **257** | inbound numa grafia, outbound na outra — o SDR vê meia conversa |
| B. dividida, mas sem inbound nenhum | 119 | as duas threads só têm outbound; a pessoa nunca respondeu |
| C. só um lado tem mensagem (thread fantasma) | 30 | contato duplicado vazio |
| D. nenhum lado tem mensagem | 0 | — |

**376 pares (A+B) têm mensagem nas duas grafias.** Os 257 de A são os que doem na tela.

```sql
-- mensagens presas em thread com par
SELECT count(*) FROM messages WHERE contact_wa_id = ANY(:os_812);
-- 3 061  de  31 965 na base  ->  9,6%
```

### Estado do agente

| medida | número |
|---|---|
| pares que envolvem `nat_qualificacao_state` | 45 |
| desses, **com estado nas DUAS grafias** | **0** |
| pares divididos (A/B) que também têm estado | 42 |
| etapas: `transferido_humano` 27 · `aguardando_ano` 11 · `aguardando_formacao` 5 · `escolhendo_slot` 1 · `concluido` 1 |

**Zero estados duplicados.** O `UNIQUE(contact_wa_id)` nunca foi violado porque o estado nasce
sempre por um caminho só (a abertura), e as buscas com `IN (variantes)` dos sprints impedem um
segundo estado. Isso é o que torna a migração (c) muito mais barata do que se supunha — §4.3.

### Ritmo: isto está crescendo hoje

Data em que o par ficou completo (`max(created_at)` dos dois contatos):

| mês | pares novos |
|---|---|
| até 06/2026 | 0 |
| 07/2026 | 191 |
| 08/2026 | 215 |

Agosto, por dia: `25/08=14 · 26/08=19 · 27/08=7` (dia em curso). **Média de ~8/dia, com o pico
ontem.** Nenhum par existe antes de julho, apesar de `contacts` começar em 05/02/2026 — a
divisão nasceu com o disparo automatizado por telefone da Exact, não com o Hub.

---

## 2. Mecânica — onde cada lado nasce

Sete pontos escrevem `contacts.wa_id` / `messages.contact_wa_id`. O que separa os dois lados é
**de onde vem o número**, e há exatamente duas fontes:

> **Fonte META (canônica, 12 dígitos para DDD fora de 11–28)** — o `wa_id` que a Meta entrega
> no webhook ou ecoa na resposta de envio.
> **Fonte NOSSA (Exact, 13 dígitos)** — `format_phone`/`wa_id_de` sobre `phone1` do lead, que
> só prefixa `55` e nunca toca no 9º dígito.

| # | caminho | arquivo:linha | wa_id usado | cai em |
|---|---|---|---|---|
| a | **inbound do webhook** — contato | `app/main.py:505` `wa_id = contact_data["wa_id"]` | cru da Meta | **12d** |
| a | **inbound do webhook** — mensagem | `app/main.py:557`, `app/main.py:643` `contact_wa_id=msg["from"]` | cru da Meta | **12d** |
| b | **abertura + turnos do agente** | `app/nat_sender.py:247` `contact_wa_id=contact_wa_id` | do chamador → `qualificacao_gatilho.py:90` `wa_id_de(telefone)` (`:45`, só prefixa `55`) | **13d** |
| c | **envio manual do SDR** (texto) | `app/routes.py:254` `wa_id = result["contacts"][0]["wa_id"]` → grava em `:265` | **eco da Meta** | **12d** |
| c | envio manual (template / mídia) | `app/routes.py:295`→`:316`, `app/routes.py:362`→`:376` | eco da Meta | **12d** |
| d | **boas-vindas antiga** | `app/exact_spotter.py:326`, msgs em `:358` e `:373` — `phone = format_phone(lead["phone1"])` (`:221`, def em `:119`) | **nossa** | **13d** |
| d | **disparo em massa** (`exact_routes`) | `app/exact_routes.py:367` `wa_id = result["contacts"][0]["wa_id"]` → `:376`, `:392` | eco da Meta | **12d** |

### A regra, em uma frase

**Quem passa pelo eco da Meta cai na mesma thread do inbound. Quem monta o número a partir da
Exact cria a segunda.** Só dois caminhos fazem isso: o **agente** (`nat_sender`) e a
**boas-vindas antiga** (`exact_spotter`).

Confirmado no dado, dentro dos 406 pares:

| grafia | direção | quem escreveu | linhas |
|---|---|---|---|
| 13d | outbound | sem marca (boas-vindas/bulk antigo) | 388 |
| 13d | outbound | **agente NAT** (`nat_etapa` não nulo) | 82 |
| 13d | inbound | webhook | **4** |
| 12d | outbound | sem marca (manual do SDR) | 1 770 |
| 12d | inbound | webhook | 817 |

Na base inteira, o agente escreveu **108** mensagens em 13d contra **7** em 12d. O inbound
quase nunca chega em 13d (4 linhas em 406 pares) — o lado de 13 dígitos é, na prática, um
monólogo nosso.

### O caso Mikaelle, mensagem a mensagem

```
554192680313   in   26/08 13:11  "Olá! Tudo bem? Fiz minha aplicação na turma 3…"
5541992680313  out  26/08 13:20  nat_abertura_agendado
554192680313   in   26/08 13:22  "Oi! Conclui no final de 2023"
5541992680313  out  26/08 13:22  qualif_conversa
554192680313   in   26/08 13:24  "Atuo de forma autônoma com psicologia clínica…"
5541992680313  out  26/08 13:24  qualif_conversa
554192680313   in   26/08 13:25  "Ao longo da graduação me interessei por saúde pública…"
5541992680313  out  26/08 13:25  qualif_conversa
5541992680313  out  26/08 13:25  "Deixa eu te conectar com uma pessoa da nossa equipe…"
554192680313   in   26/08 13:25  "Certo, obrigada."
554192680313   in   27/08 09:13  "Oi… gostaria de confirmar o horário da conversa…"   <- SEM RESPOSTA
```

A conversa **alterna perfeitamente por timestamp**. Nada se perdeu, nada se duplicou: é um
diálogo íntegro cortado ao meio por uma chave. É por isso que a proposta (a) resolve a tela
sem tocar em nada.

---

## 3. Mensagens perdidas? Não. Mas há dano operacional real.

Procurei perda de verdade e **não existe**:

```sql
SELECT count(*) FROM messages m LEFT JOIN contacts c ON c.wa_id = m.contact_wa_id
 WHERE c.wa_id IS NULL;                          -- 0 (a FK impede)
SELECT direction, count(*) FILTER (WHERE error_code IS NOT NULL) FROM messages
 WHERE contact_wa_id = ANY(:os_812) GROUP BY 1;  -- inbound 0/821 · outbound 84/2240
```

Os 84 outbounds com erro são de entrega da Meta (`131042` fatura ×45, `131047` re-engajamento
×16, `131026` ×9) — **incidente conhecido e sem relação com a divisão**.

O dano é outro, e é mensurável:

| medida | número |
|---|---|
| **conversas unificadas que terminam em inbound sem resposta** | **71** |
| — há menos de 24h | 6 |
| — 1 a 7 dias | 16 |
| — 7 a 30 dias | 42 |
| threads INDIVIDUAIS terminando em inbound (o que o Hub mostra) | 87 |
| **“pendências” FALSAS — a resposta existe, na outra metade** | **16** |

Ou seja: o Hub hoje mostra 87 conversas “esperando resposta”; **16 já foram respondidas** e o
SDR não vê, e **71 são reais** — entre elas a Mikaelle de ontem, pedindo confirmação do horário
com a consultora. A divisão não perde mensagem; ela **esconde a pergunta e mente sobre a fila**.

Agravantes de cadastro (o mesmo humano com dois registros divergentes):

| campo | pares divergentes |
|---|---|
| `ai_active` | **366 de 406** — o robô genérico ligado num lado e desligado no outro |
| `assigned_to` | **195 de 406** (103 em SDRs diferentes, 92 com um lado órfão) |
| `name` | **338 de 406** têm nome só em um lado |
| `lead_status` (Kanban) | 1 |

---

## 4. As três propostas

### 4.1 (a) LEITURA — o Hub agrupa as duas grafias numa conversa

Agrupar por par de variantes em `GET /contacts`, e mesclar as mensagens das duas grafias por
timestamp em `GET /contacts/{wa_id}/messages`.

**Custo backend — menor do que parece.** Só dois endpoints movem a agulha:
- `app/routes.py:393` `GET /contacts` — hoje `LEFT JOIN LATERAL … WHERE contact_wa_id = c.wa_id`.
  Vira agrupamento por chave de variante; `unread` passa a somar os dois lados.
- `app/routes.py:576` `GET /contacts/{wa_id}/messages` — hoje `WHERE contact_wa_id == wa_id`.
  Vira `IN (variantes_wa_id(wa_id))`, com `ORDER BY timestamp` que já existe. **É uma linha**,
  e é exatamente a mesma troca que os sprints já fizeram em `nat_sender.py:62` e
  `qualificacao_fluxo.estado_de`. Padrão conhecido, reversível.

**Custo frontend — baixo.** `wa_id` aparece **37 vezes em 3 arquivos**: `conversations/page.tsx`
(29), `kanban/page.tsx` (5), `NotificationBell.tsx` (3). A tela já trata `wa_id` como chave
opaca de string; se o backend devolver uma linha por par (com o `wa_id` sobrevivente), a
lista, o deep-link `?wa=` (`page.tsx:244`) e a busca (`page.tsx:801`) continuam funcionando
sem mudança. O ponto de atenção é o **envio**: a tela manda `to: wa_id` — precisa mandar a
grafia que a Meta aceita, e a segura é a que já recebeu inbound (12d).

**Risco:** baixo e reversível. Pior caso é mostrar junto o que hoje está separado.
**Alcance:** conserta os 406 pares **e todos os futuros**, na tela, de imediato.
**Não conserta:** `ai_active`/`assigned_to` divergentes, o Kanban, nem o cadastro duplicado.

### 4.2 (b) ESCRITA — canonizar no ponto de entrada

Antes de gravar, resolver para o contato **já existente** do par; criar contato novo só quando
nenhuma variante existe. Um helper único chamado nos 7 pontos do §2 — na prática só os dois de
fonte NOSSA (`nat_sender.py:247`, `exact_spotter.py:326/358/373`) mudam de comportamento.

**Risco: baixo na gravação, e há um ponto a não confundir.** `telefone.py` documenta que
*escolher* uma forma canônica poderia quebrar o ENVIO — verdade, e continua valendo: o envio
para 13d funciona hoje (a Mikaelle recebeu e respondeu). Mas (b) **não muda o destinatário do
envio**, só a chave sob a qual o registro é gravado. Envia-se para o mesmo número de sempre;
grava-se na thread que já existe. Essa distinção é o que torna (b) seguro.

**Alcance:** para de criar divisões novas (~8/dia). **Não conserta** nenhum dos 406 já criados.

### 4.3 (c) MIGRAÇÃO — unificar os 812 contatos históricos

Medido hoje, e o resultado **contraria a premissa de 25/08** (“risco desproporcional”):

| tabela | linhas nos 812 | pares com linha nos DOIS lados |
|---|---|---|
| `messages` | 3 061 | 376 |
| `notifications` | 702 | 2 |
| `ai_conversation_summaries` | 366 | **0** |
| `nat_scheduled_actions` | 199 | **0** |
| `nat_button_events` | 113 | **0** |
| `nat_qualificacao_state` | 45 | **0** |
| `contact_tags` · `nat_flow_state` · `nat_contact_attempts` · `nat_agendamento_token` · `call_logs` | **0** | 0 |

**Colisões de UNIQUE, verificadas uma a uma — todas ZERO hoje:**

| constraint | pares que violariam |
|---|---|
| `nat_qualificacao_state_contact_wa_id_key` | **0** |
| `contact_tags_pkey (contact_wa_id, tag_id)` | **0** (tabela vazia) |
| `nat_flow_state_contact_wa_id_key` | **0** (tabela vazia) |
| `uq_nat_sched_pendente_por_contato (kind, contact_wa_id)` | **0** |
| `uq_notif_agente_parado (contact_wa_id, ref)` | **0** |
| `uq_token_vivo (contact_wa_id)` | **0** (tabela vazia) |

**A pedra no caminho é outra, e é estrutural:** as 3 FKs para `contacts.wa_id`
(`messages`, `contact_tags`, `ai_conversation_summaries`) **não têm `ON UPDATE CASCADE`**.
Logo não existe `UPDATE contacts SET wa_id = …`. A migração tem que ser
*mover filhos → apagar o contato perdedor*, nesta ordem, numa transação:

```
BEGIN;
  UPDATE <cada tabela com contact_wa_id> SET contact_wa_id = <sobrevivente>
   WHERE contact_wa_id = <perdedor>;
  -- resolver ai_active / assigned_to / name divergentes (regra explicita, nao COALESCE cego)
  DELETE FROM contacts WHERE wa_id = <perdedor>;
COMMIT;
```

**Quem sobrevive?** O de **12 dígitos** — é onde o inbound chega (817 de 821), onde o SDR já
responde (1 770 outbounds) e a forma que a Meta considera canônica. Migrar para 13d jogaria
2 587 mensagens em cima de 474.

**Rollback:** `pg_dump` das 11 tabelas antes; e como a operação é `UPDATE` + `DELETE` de linhas
identificáveis, um mapa `(perdedor → sobrevivente)` gravado em tabela de auditoria permite
desfazer. **Ponto sem retorno:** o `DELETE` do contato perdedor apaga `name`/`notes`/`created_at`
dele — precisa ser copiado antes, não descartado.

**Risco: médio, e MUITO menor que o presumido** — 3 061 linhas de mensagem, zero colisão.
**Alcance:** conserta os 406 no cadastro inteiro, inclusive `ai_active` e `assigned_to`, que
(a) não alcança. **Não impede** que novos apareçam — só (b) faz isso.

### 4.4 Recomendação

**Concordo com a inclinação do coordenador em (a)+(b) primeiro, e discordo em parte de (c).**

Ordem que eu defendo:

1. **(a) primeiro, sozinho, e já.** Custo mais baixo, risco mais baixo, e é o único que
   devolve hoje as 71 perguntas sem resposta e mata as 16 pendências falsas. Uma linha em
   `routes.py:576` já entrega metade do valor.
2. **(b) em seguida.** Sem ela, (a) vira tela bonita sobre um cadastro que engorda ~8 pares por
   dia. É a única que estanca.
3. **(c) merece ser reavaliada para cedo, não para “se compensar”.** A justificativa original
   para adiar era risco de migração sobre 6 451 threads com UNIQUE no caminho; medido, são
   **3 061 linhas e zero colisão**. O que (c) conserta e (a) não: **`ai_active` divergente em
   366 pares** — o robô genérico ligado numa metade é uma bomba com pino solto no dia em que
   aquele trecho do webhook voltar, e **`assigned_to` divergente em 195**, que hoje só não
   machuca porque todo o comercial é `admin`. Basta um usuário `atendente` (já existe um, com
   107 contatos) para o Hub esconder metade da conversa de quem precisa dela.

Ou seja: **(a) + (b) agora**, e **(c) logo depois de (b) estar no ar** — não porque a tela
peça, mas porque o cadastro divergente é dívida que já tem juros.

---

## 5. Paliativo para o time comercial — hoje

Validado contra a busca real do Hub (`conversations/page.tsx:801-802`), que filtra no cliente
por `name.includes(busca) || wa_id.includes(busca)` — **substring**, sobre a lista completa que
`GET /contacts` devolve sem paginar.

Testado sobre os 406 pares: **os últimos 8 dígitos acham as DUAS metades em 406 de 406 (100%)**.
Buscar pelo nome **não** serve — 338 dos 406 têm nome em um lado só.

> **Como achar a outra metade de uma conversa**
>
> 1. Se a conversa parecer cortada (“ela respondeu mas não vejo o que mandamos”, ou o
>    contrário), copie **só os 8 últimos dígitos** do telefone — sem o 55, sem o DDD, sem o 9.
>    Exemplo: para `(41) 99268-0313`, busque **`92680313`**.
> 2. A busca vai mostrar **duas conversas com o mesmo número**. A que tem o 9 extra é onde o
>    robô falou; a outra é onde a pessoa escreveu. Leia as duas na ordem do relógio: juntas,
>    são uma conversa só.
> 3. **Responda sempre pela conversa onde a mensagem DELA aparece** (a sem o 9 extra). No
>    celular da pessoa é tudo o mesmo chat — ela recebe normalmente.
> 4. Não crie contato novo e não apague nenhum dos dois. Estamos consertando a tela.

Ressalva para quem for repassar: isso funciona para todo o comercial porque **os 7 usuários do
time são `admin`** e recebem a lista inteira. O usuário `atendente` (Ana, 107 contatos) recebe
só `assigned_to = ela` (`routes.py:409`) — para ela, em **195 dos 406 pares** a outra metade
não está na lista e a busca **não** a encontra. Mesma coisa para qualquer admin que use o
filtro por SDR. Nesses casos, só um admin sem filtro enxerga as duas.

---

## CHECKPOINT

Nada implementado. Nenhuma escrita, nenhum envio, nenhuma migração. Todas as consultas foram
feitas em sessão `READONLY`. Scripts em
`…/scratchpad/recon_{pares,ritmo,quem_escreve,paliativo,migracao,dano}.py`.

Aguardando decisão sobre (a), (b) e (c) antes de qualquer linha de código.
