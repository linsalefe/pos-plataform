# AUDITORIA — o agente calando no meio da conversa (24/08 23:16 → 26/08 13:00 UTC)

Somente leitura. Nenhuma escrita em produção, nenhum envio, nenhum deploy, nenhum
religar/desligar. Todas as correções abaixo são PROPOSTAS — nada foi implementado.

**Convenção de fuso, que é fonte de erro nas próprias tabelas:**
`messages.timestamp`, `agendamentos.*` e `nat_qualificacao_state.transferido_em` estão em
**horário de São Paulo**. `nat_qualificacao_state.created_at/updated_at`, `notifications.*`
e o journald estão em **UTC**. É a mesma tabela com duas réguas (`transferido_em` = SP,
`updated_at` = UTC, na linha id=17). Neste documento marco SP ou UTC sempre.

---

## 0. O veredito curto

O agente não tem UM buraco de silêncio. Tem **seis**, independentes, e o que a hipótese
do chat chamou de causa raiz era o menos grave deles.

E o achado que precede todos: **as duas últimas correções estão commitadas e não estão
rodando.** Os bugs que elas consertam continuaram produzindo silêncio hoje, 26/08.

---

## 1. O ACHADO QUE MUDA A ORDEM DE TUDO — dois fixes não deployados

```
$ ps -o pid,lstart -p 1593018
    PID                  STARTED
1593018 Tue Aug 25 19:19:51 2026        <- processo em produção AGORA (UTC)

$ git log --format="%h %ad %s" --date=iso -- backend/app/nat_sender.py ...
80358e5 2026-08-25 20:36:12 +0000 fix(agente): (#131008) — nome vazio derrubava a abertura
61fa16f 2026-08-25 20:31:04 +0000 fix(agente): o 8o ponto — a conversa morria na janela 24h
```

O processo subiu **19:19:51**. Os dois commits são de **20:31** e **20:36**. O arquivo em
disco tem o conserto (`nat_sender.py:62`, `variantes_wa_id` dentro de `janela_aberta`); o
interpretador carregado, não. Sem restart desde então.

**Prova de que ainda dói, colhida hoje:**

```
2026-08-26T12:36:24+0000 🔒 NAT não enviou (qualif_conversa → 5598984703419):
   template 'qualif_conversa' não pode ser montado ... janela de 24h fechada
2026-08-26T12:36:51+0000 🔒 NAT não enviou (nat_abertura_qualificacao → 5521999424621):
   Meta recusou: (#131008) Required parameter is missing
```

São exatamente os dois erros que 61fa16f e 80358e5 dizem ter matado. **16 horas de leads
perdidos por código já escrito.** Isto é anterior a qualquer P0 desta auditoria: nenhuma
correção nova importa enquanto o deploy não acontece.

---

## 2. Tabela-veredito das 5 hipóteses

| # | Hipótese | Veredito | Evidência |
|---|---|---|---|
| **H1** | `ofertar_agenda` é ação-fantasma | ⚠️ **PARCIAL — real no código, inócua na prática, e NÃO é a causa do caso de 26/08** | Sem branch em `qualificacao_fluxo.py:795-822`; enum em `qualificacao_llm.py:50,117`. Mas nenhum caminho gera silêncio: `etapa_cumprida=false` → `_enviar` manda a mensagem; `true` → `_avancar` faz o certo. O caso de 09h01 tem outra causa (§3.2). Frequência **indeterminável** — o JSON cru do LLM nunca é logado. |
| **H2** | Exceção escapa do savepoint = silêncio absoluto | ✅ **CONFIRMADA — e é a causa da Fabiana** | 3 ocorrências de `Falha no roteamento de fluxo` desde o deploy (`journalctl \| grep -c` = **3**), todas dela. E mais grave que o previsto: **o próprio `_fallback` morreu no meio**, 3×. `notifications` tem **1** `agente_transferiu` no período inteiro, e não é dela. |
| **H3** | Pool esgotado é o gatilho de H2 | ⚠️ **PARCIAL — o esgotamento é real, o nexo causal é falso** | `QueuePool limit of size 5 overflow 10 reached` das **18:18:55 às 18:19:29 UTC** de 25/08, derrubando webhook (`main.py:370`), `scheduled_messages_job`, faxina e NAT scheduler. Mas a Fabiana falhou **20:30–20:32**, ~2h depois, **noutro processo** (restart 19:19:51) e com `InvalidRequestError`, não `TimeoutError`. `echo=True` confirmado em produção (`database.py:10`; journald com SQL cru, 4,0 GB de journal). |
| **H4** | Trava automática pela campanha de massa | ❌ **REFUTADA** | A campanha 15:18–15:19 produziu 47 outbounds; **5583988046720 não está entre eles**. `transferido_motivo` do Álefe é **NULL**, etapa `aguardando_atuacao`. (O `558298307979` do Pablo **estava** na campanha — 2 mensagens — mas também não foi transferido.) |
| **H5** | Fabiana: o fallback deveria disparar e não disparou | ⚠️ **PARCIAL — o fallback DISPAROU e morreu no caminho; o LLM estava certo** | 3× `🛟 Agente transferiu 5517997379129 para humano`. O LLM acertou o slot: `agendamentos` id=197, **27/08 11:15**, o horário exato que ela pediu — inclusive na mensagem com o typo `27:08`. Não houve slot inválido nem falha de leitura. |

---

## 3. Linha do tempo de cada conversa morta

### 3.1 Fabiana Moreira — 5517997379129 — *lead quente, escolheu horário 3×, silêncio*

Causa raiz: **`agendar.py` commita dentro do savepoint do webhook.**

`_marcar()` (`app/agendamento/agendar.py:232-243`) faz `await db.commit()` — com o
comentário explicando que é de propósito: *"Grava o passo ANTES da próxima chamada à Exact
e commita"*. Correto para uma requisição HTTP própria. Fatal quando chamado de dentro de
`async with db.begin_nested()` (`main.py:492`): o commit fecha a transação aninhada, e a
instrução seguinte levanta
`InvalidRequestError: Can't operate on closed transaction inside context manager`.

| SP | Evento | O que o sistema fez | Onde parou |
|---|---|---|---|
| 17:29:04 | — | `📅 Agente ofereceu 14 horário(s)` | ok |
| 17:30:27 | inbound `"27:08 - 11:15"` (typo) | LLM → `agendar_slot`, slot válido, `slots_livres` ok → `fluxo.agendar` | `_marcar('iniciado')` commita → savepoint morto → `InvalidRequestError` |
| 17:30:32 | — | `🛟 Agente transferiu ... : agendamento falhou (InvalidRequestError...)` | `_fallback` grava `etapa=transferido_humano` e chama `db.flush()` → **mesma exceção** |
| 17:30:32 | — | `⚠️ Falha no roteamento de fluxo (wamid...NzlEQ0E0...)` | rollback do savepoint: etapa volta a `escolhendo_slot`, **zero mensagem, zero notificação** |
| 17:32:18 | inbound `"27/08 às 11:15"` | idem | idem (wamid `...N0IwODFF...`) |
| 17:32:49 | inbound `"27/08/2026 às 11:15"` | idem | idem (wamid `...MDRGQUM3...`) |
| 17:32:52 | — | **`agendamentos` id=197 gravado**: Fabiana Moreira, `slot_inicio 2026-08-27 11:15`, `passo='iniciado'` | órfão |

**Estado hoje:** `etapa=escolhendo_slot`, `transferido_motivo=NULL`,
`ultimo_wa_message_id` = a 3ª mensagem. Ela ficou *ativa* — o agente ainda a "escuta" —
mas a janela de 24h fechou às 17:32 de hoje (26/08).

**Sobre o `agendamentos` id=197:** `PASSO_INICIADO = "iniciado"` significa
*"nada foi para a Exact ainda"* (`models.py:552`). Não há box, nem lead, nem schedule
lá fora — o órfão é **só local**, não exige limpeza externa e não segura o slot na grade
da Exact. Mas o horário 27/08 11:15 **nunca foi reservado**: ela pediu, o sistema disse
nada, e amanhã às 11:15 ninguém vai atendê-la.

Por que `ultimo_wa_message_id` sobreviveu ao rollback: o `db.commit()` do `_marcar`
persistiu tudo o que estava pendente na sessão, inclusive ele. O savepoint reverteu só o
que veio depois.

**Por que só ela:** é a única que chegou a `agendar_slot` no período. As 3 ocorrências de
`Falha no roteamento` são as 3 mensagens dela. Não é um bug raro — é um bug **de 100% dos
agendamentos pelo agente**, que só teve uma vítima porque só uma pessoa chegou lá.

### 3.2 Evelyn ("Eve") — 5511940718388 — *a conversa de 26/08 09h01*

Causa raiz: **a missão promete horários que o código nunca entrega quando o lead já tem
reunião.** Não é H1.

| SP 26/08 | Evento |
|---|---|
| 09:00:40 | abertura `nat_abertura_agendado` (ela **já tinha** reunião: `agendamentos` id=205, 28/08 10:30) |
| 09:01:13→09:01:50 | 3 turnos perfeitos, `aguardando_ano → aguardando_atuacao → aguardando_motivacao` |
| 09:01:58 | inbound `"Exatamente isso"` |
| 09:02:01 | outbound: *"...Vou ver os horários disponíveis para a sua reunião com a Victória Amorim e **te retorno em seguida**."* |
| 09:02:01 | `_avancar` → `_reuniao` != None → `_concluir` → `etapa=concluido`. **`_concluir` não envia nada.** |
| 09:02:14 | inbound `"Obrigada 😃"` → `concluido` está fora de `ETAPAS_QUALIFICACAO_ATIVAS` → agente não escuta mais → silêncio |

A `MISSAO[aguardando_motivacao]` (`qualificacao_fluxo.py:124-130`) manda, **sem condição**:
*"Termine dizendo que vai ver os horários disponíveis."* Mas a bifurcação em `_avancar`
(`:836-848`) tem dois ramos e só um deles fala depois:

- sem reunião → `_ofertar_agenda` → manda os horários ✅
- **com reunião → `_concluir` → cala** ❌

O LLM cumpriu a missão à risca. Quem quebrou a promessa foi o código. E como isto atinge
**todo lead com `nat_abertura_agendado`**, é o buraco de maior volume dos seis: a última
palavra do agente para essa faixa inteira é uma promessa que ele nunca cumpre.

Também é a resposta ao pedido do Bloco 2.2 sobre o JSON do LLM: **não logamos o JSON cru**
(`qualificacao_llm.py:216-219` só imprime quando a resposta viola o contrato). Aqui não
precisou — o estado `concluido` + `agendamento_id=205` provam o caminho percorrido.

### 3.3 Álefe — 5583988046720 — *janela de 24h medida na grafia errada*

Causa raiz: **o inbound dele chega no telefone de 12 dígitos, o agente responde no de 13,
e a janela de 24h era calculada só no de 13.** É exatamente o bug que 61fa16f consertou —
e que não está rodando (§1).

```
outbound abertura   -> 5583988046720   (13 díg.)  15:41:33 SP
inbound "2020"      -> 558388046720    (12 díg.)  15:45:49 SP
inbound "Olá" ×3    -> 558388046720    (12 díg.)  17:27–17:32 SP
```

São **duas linhas em `contacts`**: `5583988046720` "Álefe Guimel Lins Barbosa"
(assigned_to=5) e `558388046720` "Álefe Lins" (assigned_to=3, de 05/02/2026).

`estado_de` e `_historico` são tolerantes (usam `variantes_wa_id`) — então o agente
**achou** o estado, **leu** o histórico e **chamou o LLM**. Só a janela era estrita:

```
2026-08-25T18:45:55+0000 🔒 NAT não enviou (qualif_conversa → 5583988046720):
   template 'qualif_conversa' não pode ser montado sem inventar dado do lead
   (formação ausente e janela de 24h fechada)
2026-08-25T20:27:40+0000 🔒 NAT não enviou (qualif_conversa → 5583988046720): idem
2026-08-25T20:32:00+0000 🔒 Agente não enviou: teto de envios/hora estourado (20/20)
2026-08-25T20:32:12+0000 🔒 Agente não enviou: teto de envios/hora estourado (20/20)
```

Sem inbound algum na grafia de 13 dígitos, `janela_aberta` respondia FECHADA; o sender ia
para o ramo de template; `qualif_conversa` não tem template montável sem `formacao`;
recusa. As duas últimas mensagens bateram noutro muro: o **teto de 20 envios/hora**.

**H4 fica refutada aqui:** não houve transferência nenhuma — `transferido_motivo` é NULL,
`etapa=aguardando_atuacao`, e ele não estava na campanha das 15:18.

### 3.4 Paulo/Pablo — 5582998307979 — *mesmo bug do Álefe, mesma noite*

```
outbound abertura -> 5582998307979  ("Olá, Paulo!")  18:12:22 SP
inbound "Olá, em 2023"        -> 558298307979   21:02:26 SP
inbound "Olá, me formei 2023" -> 558298307979   22:28:21 SP

2026-08-26T00:02:29+0000 🔒 NAT não enviou (qualif_conversa → 5582998307979): ...janela fechada
2026-08-26T01:28:24+0000 🔒 NAT não enviou (qualif_conversa → 5582998307979): ...janela fechada
```

Idêntico ao §3.3. Estado id=36, `etapa=aguardando_atuacao`, `transferido_motivo=NULL`.

Agrava: a linha `558298307979` chama-se **"Pablo Valente"** no Hub, o lead da Exact é
**"Paulo Martind"** (`agendamentos` id=199) e a campanha de 15:18 mandou para ela um
template dizendo **"Ola Ronaldo"**. Três nomes, uma thread — é a ambiguidade do 9º dígito
documentada em `qualificacao_fluxo.py:202-260`, agora com consequência visível na tela do
SDR. **A janela de 24h dele fechou às 22:28 de hoje (26/08).**

### 3.5 Osmari — 5517997472204 — *lacuna de roteamento, não do agente*

```
2026-08-25 18:41:35 SP  inbound "Ok tenho interesse"   -> nenhuma resposta, nunca
```

- `nat_qualificacao_state`: **0 linhas** para este número (qualquer grafia).
- `contacts`: existe, `name = "."`, `assigned_to = 6`.
- Nenhuma abertura da NAT — a conversa nasceu de mensagem manual do time.

**Dono do inbound: ninguém.** Sem estado, `processar_texto` do agente devolve `False`
(`qualificacao_fluxo.py:790-792`), o webhook cai no `nat_flow.processar_texto` do fluxo
velho, e o fluxo velho também não tinha nada engatilhado para ela. Nenhuma exceção,
nenhum log — o caminho "ninguém é dono" é **mudo por construção**.

O único sinal emitido foi para o SDR 6: `new_message` às 21:41 UTC e `window_1h/3h/5h` às
22:44 / 00:45 / 02:45 UTC — com o título *". sem resposta"*, porque o contato não tem nome.
Ninguém agiu. **A janela de 24h dela fechou às 18:41 de hoje (26/08).**

Este caso não é bug do agente. É a prova de que o alerta existente (§8) não é lido.

---

## 4. Bloco 2 — H1 em detalhe

1. **Confirmado no código.** `processar_texto` (`qualificacao_fluxo.py:795-822`) ramifica
   por `transferir_humano`, `agendar_slot`+`not com_slots`, `agendar_slot`,
   `not etapa_cumprida`, e cai em `_avancar`. **Não há `acao == "ofertar_agenda"` em
   lugar nenhum do módulo** — as 3 ocorrências (`:845`, `:853`, `:891`) são a função
   interna `_ofertar_agenda`, chamada por código, nunca pelo enum.
2. **Frequência: o dado não existe.** `qualificacao_llm.py` só imprime quando a resposta
   **viola** o contrato (`:216-219`). Um `acao="ofertar_agenda"` bem-formado é aceito,
   consumido e descartado sem deixar rastro. Não há como contar retroativamente. Vira
   correção proposta (§7, P0-D).
3. **As MISSÕES não induzem a ação** — nenhuma das 5 menciona `ofertar_agenda`, e o
   preâmbulo diz *"'acao' é 'nenhuma' salvo instrução em contrário na missão"*
   (`qualificacao_llm.py:125`). Mas o enum a **oferece** em dois lugares (`:50` e `:117`,
   este dentro do JSON de saída que o modelo lê). O modelo tem a opção listada e nenhuma
   instrução de quando usá-la — é convite a usar por analogia.
4. **A missão de `aguardando_motivacao` NÃO deixa clara a bifurcação** — e é justamente
   por isso que §3.2 acontece. Ela manda prometer horários incondicionalmente; o código
   decide entre oferecer e concluir. **Correção certa: mudar o código, não a missão** —
   o modelo não tem como saber se existe reunião.

**Conclusão:** `ofertar_agenda` é dívida de contrato, não fonte do silêncio observado.

---

## 5. Bloco 3 — o fail-closed, ponto a ponto

### 5.1 Onde uma exceção escapa até `main.py:505`

Tudo dentro do `async with db.begin_nested()` de `main.py:492-504`. Nada em
`processar_texto` tem `try/except` próprio, exceto os 3 pontos marcados ✅.

| Função | Escapa? | Como |
|---|---|---|
| `estado_de` / `_ja_processado` | ✅ escapa | qualquer erro de conexão/pool |
| `db.flush()` de `ultimo_wa_message_id` | ✅ escapa | — |
| `_agendar_encerramento` | ✅ escapa | grava em `nat_scheduled_actions` |
| `_fatos` → `_reuniao`/`_curso`/`_nome` | ✅ escapa | 4 queries sem guarda |
| `_fatos` → `disponibilidade.resumo_por_dia` | ❎ protegido | `try/except` em `:459-462` |
| `_historico` | ✅ escapa | — |
| `llm.conversar` | ❎ protegido | `except Exception` em `:218`, devolve `None` → `_fallback` |
| `_enviar` → `send_nat_message` | ✅ escapa | e pior: **falha "com sucesso"** (§5.3) |
| `_agendar` → `fluxo.agendar` | ❎ protegido | `try/except` em `:884-887` → `_fallback` … **que então morre** |
| `_agendar` → `disponibilidade.slots_livres` | ✅ escapa | fora do try |
| `_ofertar_agenda` | ✅ escapa | `_enviar` sem guarda |
| `_avancar` / `_concluir` / `agendar_lembrete` | ✅ escapa | — |
| `_fallback` | ✅ **escapa** | `db.flush()` e `send_nat_message` sem guarda |
| `_notificar` | ❎ protegido | `except Exception` em `:500-502` |

O `except Exception` de `main.py:505-507` faz **só `print`**. Não envia, não notifica, não
marca. E o `begin_nested` reverte inclusive a etapa `transferido_humano` já escrita.

### 5.2 Ocorrências reais

```
$ journalctl -u cenat-backend.service --since "2026-08-24 23:00" | grep -c "Falha no roteamento"
3
```

As 3 são a Fabiana (§3.1). O buraco é largo; a exposição medida até agora é de 1 lead —
mas era o único lead quente do período.

### 5.3 **Sim, o fallback pode falhar em silêncio. Falhou 3×.** — as três formas

**(a) Exceção dentro do próprio `_fallback`.** Confirmado empiricamente. `_fallback`
(`:504-520`) faz `db.flush()` e depois `send_nat_message`, **nenhum dos dois protegido**.
Com a transação já fechada pelo commit do `agendar`, o `flush()` levanta e o `🛟` fica
sendo só um print bonito no log. A etapa `transferido_humano` volta atrás no rollback.

**(b) `send_nat_message` recusando pelo guard — o buraco mais largo dos seis.**
`_enviar` (`:476-480`) **retorna `bool`**, e `processar_texto` **descarta o retorno** em
`:817` e em `_avancar:839,845`. Recusa do guard (teto por hora, janela fechada, chave
desligada, template não montável) devolve `False`, ninguém lê, `processar_texto` devolve
`True` ("tratei") e **o turno termina normalmente**. Sem mensagem, sem fallback, sem
notificação, sem exceção. É o que matou Álefe (4×) e Pablo (2×) — e é a única falha desta
auditoria que não deixa **nenhum** rastro correlacionável ao lead sem ler o journald.

**(c) Rollback levando embora a transferência já escrita.** Confirmado: `notifications`
tem exatamente **1** `agente_transferiu` desde 24/08 (contato `5515998095653`, 20:03:55
UTC — o fallback que deu certo, por comparação). Os 3 da Fabiana sumiram junto com a etapa.

### 5.4 O teto de 20/h como fonte de silêncio

```
20:29:09 🔒 Agente bloqueado: teto de envios/hora estourado (20/20)
20:32:00 🔒 Agente não enviou:  teto de envios/hora estourado (20/20)
20:32:12 🔒 Agente não enviou:  teto de envios/hora estourado (20/20)
20:39:11 / 20:47:13 / 20:49:13 / 20:57:14 / 20:59:16  🔒 Agente bloqueado
```

Há **duas** mensagens diferentes, e a diferença importa:

- `🔒 Agente bloqueado` = **abertura**. Trata certo: `AcaoAdiada`, volta a `pendente`,
  reagenda em 10 min (`ATRASO_POR_TETO`). Nenhum lead perdido.
- `🔒 Agente não enviou` = **conversa em andamento**. Trata **errado**: o lead já mandou a
  mensagem, está esperando, e o turno acaba mudo. Não há readiantamento porque não há
  ação agendada — o gatilho era o inbound, que já passou.

O teto de 20/h foi dimensionado para **aberturas** (o comentário em `:83-86` mede
"~7 aberturas no pico das 09h contra teto de 20/h"). Ele está sendo aplicado também à
**resposta a quem perguntou**, que não é business-initiated e não tem risco de qualidade
na Meta. Um lead que escreve durante um pico de aberturas simplesmente não é respondido.

---

## 6. Bloco 4 — pool e 502

1. **Dimensionamento.** `database.py:10` — `create_async_engine(DATABASE_URL, echo=True)`,
   sem `pool_size`: default **5 + 10 overflow = 15**, `timeout=30s`. Consumidores
   concorrentes: webhook (rajadas da Meta, várias por segundo), NAT scheduler, sync de
   600s, `scheduled_messages_job`, faxina de agendamento, rotas do Hub (o frontend faz
   polling de `/api/notifications` **a cada ~15s por aba aberta**) e as rotas públicas da
   LP. **15 é baixo demais** para esse conjunto.

   Retenção por turno do agente: a sessão fica presa durante `llm.conversar`
   (`TIMEOUT_SEGUNDOS` × 2 tentativas), `fetch_template_body` (Meta) e `fluxo.agendar`
   (Exact, múltiplos round-trips). Medido nos prints: turnos normais 3–4s
   (17:27:47→17:27:51, 17:28:26→17:28:29), turno com agendamento **5s**
   (17:30:27→17:30:32). **Uma conexão presa por 3–5s a cada mensagem de lead**, num pool
   de 15, com 47 outbounds de campanha em 60s.

2. **Esgotamento medido.** `QueuePool limit of size 5 overflow 10 reached` de
   **18:18:55 a 18:19:29 UTC** em 25/08 (~70 tracebacks). Vítimas nomeadas:
   `❌ Erro no scheduled_messages_job`, `❌ Erro na faxina de agendamento`,
   `❌ NAT scheduler: erro ao processar ação: TimeoutError`. Os tracebacks do webhook
   batem todos em **`main.py:370`** (`await db.execute` logo na entrada) — ou seja,
   **mensagens de lead recusadas na porta**. Gatilho na janela: 8× `POST
   /api/exact-leads/bulk-send-template` + rajada de `POST /api/contacts/<n>/read`
   (~20 no minuto) + o polling do frontend.

   **Não cruza com as conversas mortas:** nenhuma delas cai em 18:18–18:19, e o processo
   que sofreu o esgotamento (1587117) foi substituído às 19:04 e 19:19. Fabiana falhou
   20:30–20:32 com `InvalidRequestError`, causa independente.

3. **502 do agendamento: não encontrado nos logs disponíveis.** `grep -c " 502 "
   /var/log/nginx/*access*log` = **0**. Os bookings de 25/08 estão consistentes
   (`agendamentos` 199–205, `passo` progride normalmente). **Nenhum booking de LP perdido
   identificado no período desta auditoria.** O incidente de 502 registrado na memória
   (3 tentativas, agendamento zerado) é de outra janela e permanece não diagnosticado —
   fora do escopo desta auditoria.

   O único booking perdido do período é **o da Fabiana** (§3.1), e não foi por 502.

4. **`echo=True` confirmado em produção.** Journald traz o SQL cru (`INFO
   sqlalchemy.engine.Engine SELECT ... FROM messages ...`) para toda query. Custo:
   `journalctl --disk-usage` = **4,0 GB**. Efeito prático nesta auditoria: filtrar os
   prints do agente exigiu grep pesado e um comando estourou 120s de timeout. Em
   incidente, o log é ilegível — é custo operacional real, não estética.

---

## 7. Correções propostas — ordem de impacto

Nada abaixo foi implementado. **CHECKPOINT: cada item exige aprovação explícita.**

### P0-0 — Deployar o que já está commitado ⚠️ *antes de qualquer código novo*

- **O que muda:** nada. `systemctl restart cenat-backend.service`.
- **Efeito:** ativa 61fa16f (janela de 24h tolerante ao 9º dígito → resolve §3.3 e §3.4 de
  hoje em diante) e 80358e5 (`#131008` → destrava aberturas).
- **Risco:** baixo, mas **não é zero** — o código em disco tem 4 commits à frente do
  processo (`2fd3928`, `61fa16f`, `80358e5` e o que veio antes das 19:19). Reler o diff
  `19af69f..HEAD` antes de reiniciar.
- **Teste:** após o restart, mandar inbound de teste pela grafia de 12 dígitos de um
  contato com estado ativo na de 13 e confirmar resposta em texto livre; conferir que
  `🔒 ... janela de 24h fechada` some do journald.
- **Migração:** não.

### P0-A — `agendar.py` não pode commitar dentro do turno *(causa da Fabiana)*

- **O que muda:** `app/agendamento/agendar.py:232-243` (`_marcar`). Duas saídas:
  - **(preferida)** `_marcar` passa a usar `db.begin_nested()`/`flush` quando já há
    transação externa, ou o `commit` vira injetável pelo chamador;
  - **(alternativa)** o agente não chama `fluxo.agendar` na sessão do webhook — enfileira
    um `nat_scheduled_actions` novo (`kind='agendar_slot'`) e o scheduler executa em
    sessão própria. Mais invasiva, mas devolve ao `agendar` a transação que ele espera.
- **Risco:** **alto** — `_marcar` é o mecanismo de recuperação da faxina (*"um processo
  morto no meio do fluxo perderia toda a linha"*). Qualquer mudança precisa preservar a
  durabilidade por passo nas chamadas HTTP normais da LP.
- **Teste:** turno de agendamento ponta a ponta com o webhook real; forçar exceção após
  `PASSO_BOX_CRIADO` e conferir que a faxina ainda enxerga a linha; conferir que
  `agendamentos.passo` chega a `agendado` e o lead recebe confirmação.
- **Migração:** não. **Checkpoint: sim, e este merece revisão a quatro olhos.**

### P0-B — `_enviar` recusado nunca mais pode ser silêncio *(o buraco mais largo)*

- **O que muda:** `qualificacao_fluxo.py:817` e `:839,845` passam a ler o `bool` de
  `_enviar`. Recusa → `_fallback(estado, f"envio recusado: {motivo}", db)`. Exige
  `_enviar` devolver `(bool, motivo)` — `enviar_nat` já retorna a tupla (`:102-104`),
  `send_nat_message` a descarta (`:93-98`).
  **Exceção necessária:** recusa por **teto** não deve transferir para humano — deve
  reenfileirar a resposta (mesmo tratamento de `AcaoAdiada`), senão um pico de aberturas
  passa a queimar leads em `transferido_humano`. Ver P1-B.
- **Risco:** médio — pode aumentar o volume de transferências. É o resultado desejado:
  transferência ruidosa é melhor que silêncio.
- **Teste:** com o guard forçado a recusar (chave desligada), mandar inbound e conferir
  mensagem de despedida + `notifications.agente_transferiu`.
- **Migração:** não. Checkpoint: sim.

### P0-C — Rede de última instância FORA do savepoint

- **O que muda:** `main.py:505-507`. O `except Exception` deixa de ser só `print`:
  1. `await db.rollback()` para limpar a sessão abortada;
  2. **em sessão nova** (`async_session()` própria), gravar `Notification` para
     `GESTOR_USER_ID` com o `wa_message_id`, o contato e o traceback;
  3. tentar UMA vez o `TEXTO_FALLBACK` + marcar `transferido_humano`, também na sessão
     nova, com `try/except` próprio;
  4. `traceback.format_exc()` no print — hoje só sai `type: msg`, e foi por sorte que a
     mensagem do `InvalidRequestError` era autoexplicativa.
- **Risco:** médio — sessão nova durante tratamento de erro pode esbarrar no pool
  esgotado. Fazer **depois** de P1-A, e blindar com `try/except` final que no pior caso só
  loga.
- **Teste:** injetar `raise RuntimeError` em `_fatos` e conferir: lead recebe a despedida,
  gestão recebe notificação, traceback completo no journald.
- **Migração:** não. Checkpoint: sim.

### P0-D — A promessa dos horários e o enum fantasma

- **O que muda:** dois pontos, ambos pequenos:
  1. **`qualificacao_fluxo.py:124-130`** — a `MISSAO[aguardando_motivacao]` não pode
     prometer horários incondicionalmente. Como o modelo não sabe se há reunião, a
     promessa tem de sair da missão e virar frase determinística no ramo certo de
     `_avancar`. **OU** (mais simples e menos regressivo) `_concluir` passa a enviar,
     quando vem de `_avancar` com reunião existente, uma confirmação curta
     — *"Sua reunião com {consultora} já está marcada para {dia} às {hora} — te espero
     lá!"* — fechando a promessa em vez de ignorá-la.
  2. **`qualificacao_llm.py:50,117`** — remover `ofertar_agenda` do enum e do JSON de
     saída. Não há branch que a trate e nenhuma missão que a peça (§4).
- **Risco:** baixo. É o item de **maior alcance por menor risco** de toda a lista — atinge
  todo lead `nat_abertura_agendado`.
- **Teste:** lead com `agendamento` existente percorre as 4 perguntas e recebe fecho
  explícito; `test_qualificacao.py` do validador continua verde sem `ofertar_agenda`.
- **Migração:** não. Checkpoint: sim.

### P0-E — Instrumentar o JSON cru do LLM *(pré-requisito das próximas auditorias)*

- **O que muda:** `qualificacao_llm.py` passa a logar por turno, mesmo em sucesso:
  `contact_wa_id`, `etapa`, `acao`, `etapa_cumprida`, `dado_extraido`, latência. Print
  estruturado numa linha basta; tabela `nat_llm_turnos` é melhor mas custa migração.
- **Risco:** nenhum funcional. Só faça **depois** de `echo=False` (P1-A), ou o log some no
  meio do SQL.
- **Teste:** um turno produz exatamente uma linha legível.
- **Migração:** não (versão print). Checkpoint: não, se for só print.

### P1-A — Pool e `echo`

- **O que muda:** `database.py:10` →
  `create_async_engine(DATABASE_URL, echo=False, pool_size=20, max_overflow=20,
   pool_timeout=10, pool_pre_ping=True)`.
  Justificativa dos números: 15 esgotou com carga real; 40 cobre a rajada da campanha
  (47 envios) + polling do frontend + scheduler com folga. `pool_timeout=10` faz o
  webhook falhar rápido e a Meta reentregar, em vez de segurar 30s. Conferir
  `max_connections` do Postgres antes.
  **Avaliar em separado** (não junto): soltar a conexão durante `llm.conversar` — corta a
  retenção de 3–5s para <1s, mas exige reabrir a sessão e reler o estado no meio do turno.
- **Risco:** baixo–médio. `echo=False` reduz o journal de 4,0 GB e **remove a única
  visibilidade de SQL que temos hoje** — só depois de P0-E.
- **Teste:** repetir a carga de 18:18 (bulk-send + polling + webhooks) e confirmar zero
  `QueuePool limit`.
- **Migração:** não. Checkpoint: sim (mexe em conexão de banco em produção).

### P1-B — Teto por hora não pode calar quem já está conversando

- **O que muda:** `qualificacao_guard.py:160-205` (`qualificacao_pode_atuar`) deixa de
  aplicar `_teto_ok` à **conversa**, mantendo-o na **abertura**
  (`qualificacao_pode_iniciar`, `:126-158`). Fundamento: o teto existe para proteger a
  qualidade de mensagens business-initiated; responder a quem acabou de escrever é
  user-initiated e não conta para esse risco.
  Se o teto tiver de continuar valendo para a conversa, então a recusa **precisa**
  reenfileirar a resposta (`nat_scheduled_actions` novo, `kind='responder_pendente'`) —
  nunca terminar o turno em silêncio.
- **Risco:** médio — remove um freio. Mitigar com alarme de volume/hora.
- **Teste:** com o teto artificialmente em 1, mandar inbound de lead ativo e confirmar
  resposta.
- **Migração:** não (opção A) / sim (opção B, novo `kind`). Checkpoint: sim.

### P2 — Destino dos 5 contatos mortos *(decisão do Álefe, item a item)*

**Todas as janelas de 24h já fecharam** — qualquer retomada exige template aprovado. Não
existe caminho de texto livre para nenhum destes cinco.

| Contato | Estado hoje | Proposta | Por quê |
|---|---|---|---|
| **Fabiana** 5517997379129 | `escolhendo_slot`, ativo, janela fechada 17:32 hoje | **Humano, hoje, com prioridade máxima.** Ela pediu 27/08 11:15 — é **amanhã**. Transferir para SDR com notificação, marcar `transferido_humano` para o agente não reagir, e um humano reabre por template e confirma o horário. `agendamentos` id=197 fica `iniciado` (nada foi para a Exact) — decidir se o humano reaproveita a linha ou abre nova. | Lead mais quente do período, escolheu horário 3×, e a reunião é amanhã. |
| **Eve** 5511940718388 | `concluido`, reunião 28/08 10:30 confirmada | **Só uma mensagem de cortesia.** A reunião **existe** e está agendada. Falta fechar a promessa ("vou ver os horários") e responder ao "Obrigada". | Nenhum risco de perder o lead; risco de ela achar que ficou pendente. |
| **Álefe** 5583988046720 | `aguardando_atuacao`, ativo | **Reprocessar após P0-0.** É o Álefe — teste seguro para validar o fix da janela de 24h de ponta a ponta antes de aplicar a leads reais. | Custo zero, valor de validação alto. |
| **Paulo/Pablo** 5582998307979 | `aguardando_atuacao`, ativo | **Humano, com desambiguação de identidade antes.** Não reprocessar automático: a thread de 12 dígitos tem 3 nomes (Pablo Valente / Paulo Martind / "Ronaldo" da campanha) e uma resposta automática pode ir para a pessoa errada. | O 9º dígito aqui é ambíguo de verdade, não é caso de tolerância. |
| **Osmari** 5517997472204 | sem estado | **Humano (SDR 6).** Não criar estado retroativo. | Nunca foi do agente; criar estado agora ia gerar abertura fora de contexto. |

**Higiene, sem lead envolvido:** as 3 linhas `agendamentos.passo='iniciado'` (uma é a
id=197) são órfãs locais sem efeito na Exact. Inventariar antes de qualquer limpeza —
não há urgência e não seguram slot.

### P3-A — Detector persistente *(Bloco 7)*

**O alerta já existe e não resolve.** `window_1h/3h/5h/20h` dispararam para **todos** os
cinco casos (27+26+25+9 notificações desde 24/08). Falharam em três eixos: vão para o
**SDR dono** (Osmari → user 6, Álefe → user 3), o título é *"Lead aguardando há 1h"* —
indistinguível de um lead que só está esperando um humano — e ninguém leu (`is_read=f` em
100% delas).

Proposta — sinal **novo e diferente**, não mais um `window_*`:

- **Regra:** existe `nat_qualificacao_state` com `etapa ∈ ETAPAS_QUALIFICACAO_ATIVAS`;
  existe inbound (em **qualquer** grafia, `variantes_wa_id`) depois do último outbound do
  agente; e `now - inbound > X`.
- **X = 10 minutos.** Um turno saudável leva 3–5s (§6.1). 10 min não gera falso positivo e
  ainda cabe dentro da janela de 24h para agir.
- **Onde:** `kind` novo no `nat_scheduler` (`vigiar_resposta`), agendado no mesmo ponto em
  que `processar_texto` faz `_agendar_encerramento` (`:801`) e cancelado quando o agente
  fala. Sobrevive a restart porque vive em `nat_scheduled_actions`. Aproveita o índice
  único parcial `uq_nat_sched_pendente_por_contato` — um vigia por contato, sem acúmulo.
- **Destinatário: `GESTOR_USER_ID`**, não o SDR. Título explícito: *"AGENTE MUDO — lead
  esperando há 10 min"*. Isto é falha de sistema, não fila de atendimento.
- **Sem falso positivo:** `transferido_humano`, `concluido` e `encerrado` estão fora de
  `ETAPAS_QUALIFICACAO_ATIVAS` — a mesma constante que já governa escutar e falar.
- **Migração:** nova `kind` (o CHECK de `nat_scheduled_actions` é sobre `status`, não
  sobre `kind` — **não precisa de ALTER**). Checkpoint: sim.

### P3-B — UX da oferta de slots *(Bloco 6)*

1. **Hoje:** `_fatos` (`:431-473`) monta 3 dias × `_espalhados(…, 6)` = até 18 rótulos.
   A Fabiana recebeu **14** (`📅 Agente ofereceu 14 horário(s)`) numa mensagem só.
   **Proposta:** manter os 18 no **contexto** (a regra *"o LLM só veste os slots do
   contexto"* é o que impede horário inventado — não mexer nela) e instruir a **missão** a
   apresentar **no máximo 5**, distribuídos entre os dias, terminando com *"se nenhum
   servir, me diz que dia e período são melhores para você"*. Zero mudança no código de
   grade; muda só `MISSOES[ETAPA_Q_OFERTANDO_AGENDA]` (`:131-135`).
2. **Tolerância de formato: não é problema.** O LLM leu `"27:08 - 11:15"` (com typo)
   **corretamente** — `agendamentos` id=197 prova o slot certo, 27/08 11:15. Ele acertou
   nas três variações. **Nenhuma instrução nova é necessária.** A hipótese de que o
   formato torto atrapalhou está refutada pelos dados.

---

## 8. O que NÃO foi possível determinar

| Pergunta | Por quê | Instrumentação que falta |
|---|---|---|
| Quantos turnos devolveram `ofertar_agenda` | JSON cru do LLM nunca logado (`qualificacao_llm.py:216-219` só loga violação) | **P0-E** |
| Latência real do LLM por turno | Só dá para inferir do delta entre `messages.timestamp` | **P0-E** (campo de latência) |
| Se algum lead da LP perdeu booking no esgotamento das 18:18 | `main.py:370` rejeita antes de qualquer log de identidade; nginx sem 502 registrado | log de rejeição por pool com contato/rota |
| O 502 do agendamento da memória (25/08) | `grep -c " 502 " /var/log/nginx/*access*log` = 0. Bookings de 25/08 consistentes. Incidente de outra janela | fora do escopo — permanece aberto |
| Quantas recusas de `_enviar` houve antes de 24/08 | Retenção do journald cobre desde 30/03, mas o print `🔒 Agente não enviou` não nomeia o contato | incluir `contact_wa_id` no print (trivial, P0-B) |
| Se algum dos 47 da campanha de 15:18 tinha estado ativo | Verifiquei os 4 do Bloco 1 (nenhum transferido). Cruzamento completo dos 47 não feito | consulta pontual, se o Álefe quiser |

---

## 9. Testes de validação — resumo por correção

| Correção | Teste do caminho feliz | **Teste do caminho de falha** |
|---|---|---|
| P0-0 | inbound de 12 díg. → resposta em texto livre | conferir que `janela de 24h fechada` sumiu do journald |
| P0-A | agendamento completo até `passo='agendado'` | exceção após `PASSO_BOX_CRIADO` → faxina ainda enxerga a linha |
| P0-B | turno normal responde | guard forçado a recusar → despedida + `agente_transferiu` |
| P0-C | turno normal não muda | `raise RuntimeError` em `_fatos` → lead recebe despedida, gestão notificada, traceback no log |
| P0-D | lead com reunião recebe fecho explícito | `test_qualificacao.py` verde sem `ofertar_agenda` no enum |
| P1-A | carga de bulk-send + polling + webhooks | zero `QueuePool limit` |
| P1-B | teto em 1 → lead ativo ainda é respondido | teto estourado → resposta reenfileirada, nunca silêncio |
| P3-A | agente responde em 3s → vigia cancelado | agente mudo 10 min → notificação para gestão; `transferido_humano` **não** dispara |

---

## CHECKPOINT

Nada de P0 a P3 foi implementado. **P0-0 (restart) é o único item cujo benefício é
imediato e cujo código já foi revisado e commitado** — e é o que está custando leads
neste minuto. Recomendo decidir sobre ele primeiro, separado do resto.
