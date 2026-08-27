# RECON 27/08 — a janela pedida ainda não começou; o que existe é a linha de base

**Somente leitura.** Nenhuma escrita, nenhum envio.

---

## 0. A janela está vazia, e não por falta de dado

A janela pedida foi **27/08 00:00 → agora, em `timestamp` SP**. Em São Paulo ainda é
**26/08 22:05**. O `currentDate` da sessão diz 27/08 porque é a data em **UTC** — e a
convenção do RECON de 27/08 é justamente que `messages.timestamp` é *naive em São Paulo*.
As duas coisas divergem por 3 h, todo dia, entre 21:00 e 00:00 SP.

```
agora UTC: 2026-08-27 01:05:02   |   agora SP: 2026-08-26 22:05:02
```

```sql
select count(*) from messages where timestamp >= '2026-08-27 00:00';   -- 0
select count(*) from nat_qualificacao_state where created_at >= '2026-08-27 00:00';  -- 0
```

**Não é "nada aconteceu hoje". É "hoje ainda não começou"** — faltam 1 h 55 min para o
27/08 em SP. A última mensagem do banco, de qualquer natureza, é de **26/08 19:18:47 SP**.

Portanto: **§1 (números do dia) e §2 (transcrições) não têm conteúdo.** Não há uma
conversa para colar. Fabricar um recorte alternativo (por exemplo, "desde o deploy") e
chamá-lo de "hoje" seria trocar a pergunta em silêncio — o que este documento faz é
responder o que dá para responder e deixar o resto pronto para quando o dia existir.

---

## 1–2. Números e transcrições do dia — **vazios**

| Métrica (27/08 SP) | Valor |
|---|---|
| Estados novos | **0** |
| Aberturas enviadas / entregues / respondidas | **0 / 0 / 0** |
| Inbounds de leads | **0** |
| Turnos do agente | **0** |
| Conversas com ≥1 inbound | **0** |

Transcrições: **nenhuma**.

### Desde o deploy do Sprint 3 (26/08 21:49 SP / 27/08 00:49 UTC) também não houve tráfego

```sql
select count(*) from messages where created_at >= '2026-08-27 00:49';   -- 0
select kind, status, count(*) from nat_scheduled_actions
 where processed_at >= '2026-08-26 21:49' group by 1,2;                  -- 0 linhas
```

110 linhas no journald desde o restart: o boot, os 5 jobs, um sync da Exact
(`9 195 sincronizados, 0 novos`), 1 alerta de janela e requisições HTTP do Hub. **Zero
linhas do agente.**

---

## 3. Validação dos consertos — **nenhum tem caso real ainda**

Cada item abaixo diz o que é fato hoje, o que ainda falta, e a query/comando exato.

| # | Conserto | Situação | Evidência |
|---|---|---|---|
| S3-1 | `_concluir` confirma | **sem caso** — ninguém completou o roteiro | 0 turnos desde o deploy |
| S3-2 | `🧠 LLM` no journald | **canal PROVADO, linha PENDENTE** | ver abaixo |
| P0-A | reunião marcada pelo agente | **sem caso** — ninguém chegou a `escolhendo_slot`; marcações do agente **seguem em 0** | `agendamentos` com `origem_ip IS NULL`: só as 3 falhas da Fabiana de 25/08 |
| P3-B | oferta ≤ 5 slots | **sem caso** — 0 ofertas desde 25/08 | as únicas 2 ofertas que já existiram são de 25/08, com 14 slots cada (pré-P3-B) |
| P3-A | `vigiar_resposta` | **17 armados / 17 cancelados / 0 disparos**, todos anteriores ao deploy; **0 desde o deploy** | ver abaixo |
| S3-3/4 | curso e nome na abertura | **sem abertura nova**; a última abertura ainda saiu com o bug | ver abaixo |
| — | silêncio do agente | **2 casos abertos**, os dois anteriores ao deploy | ver §3.6 |

### 3.1 A linha `🧠 LLM` — o canal está provado, a linha não

```
grep -c '🧠 LLM'          -> 0      (mas também 0 turnos do LLM: nada a logar)
grep -c '🏷️'              -> 0      (ofertar_agenda obsoleta: sem medição ainda)
grep -c 'FORA DO CONTRATO'-> 0
grep -c '🛑 LLM'          -> 0
grep -c 'sqlalchemy.engine' -> 0    <-- os 4 GB não voltaram
grep -c 'Traceback'       -> 0
```

O que **está** provado é o mecanismo, e é uma linha INFO de um logger do projeto chegando
ao journald:

```
2026-08-27T00:49:16.358 INFO agente.boot: logging configurado —
    root=INFO, handler no stderr, SQL filtrado=True
```

Antes do S3-2 essa linha teria sido descartada no `lastResort`, igual à `🧠 LLM`. O que
falta é só um turno de lead. Comando:

```bash
journalctl -u cenat-backend --since "2026-08-27 00:49" | grep -E "🧠 LLM|🏷️|FORA DO CONTRATO"
```

*(O vigia que deixei sobre o journald expira ~01:57 UTC — bem antes das 09:00 SP. A
verificação da manhã é o comando acima.)*

### 3.2 `vigiar_resposta`

```sql
select status, count(*), min(created_at), max(created_at)
  from nat_scheduled_actions where kind='vigiar_resposta' group by 1;
-- cancelado | 17 | 2026-08-26 16:22 UTC | 2026-08-26 18:43 UTC
```

**Zero falsos positivos, zero verdadeiros, zero disparos** — e nenhum armado desde o
deploy, porque nenhum lead escreveu. O número não mudou desde o RECON de 27/08.

### 3.3 Curso e nome na abertura — o fix não repara o que já saiu

Não houve abertura nova. **A última abertura enviada é anterior ao S3-3** e saiu com o
buraco:

```
26/08 18:09:56 SP → 5512991814636:
  "Olá, Natália! ... Vi que você aplicou para a nossa Pós-Graduação em . Antes de..."
```

Esse lead está **vivo, em `aguardando_ano`**. O fix vale para as falas seguintes; a
mensagem já entregue continua como está.

**Verificação prospectiva — as 3 aberturas agendadas para hoje 09:00 SP:**

| Contato | Nome (Exact) | Nome (agendamento) | Curso | Perfil WhatsApp |
|---|---|---|---|---|
| 5585992987046 | Ana Thally Pereira Oliveira | idem | Pos Saude do Trabalhador | (vazio) |
| 5551996323362 | Lucas Becker Delwing | idem | Pos Suicidio e Luto T3 | (vazio) |
| 5571985252525 | **fafaf** | **fafaf** | Pos Grupos e Oficinas T2 | (vazio) |

As três têm **nome e curso resolvíveis nas duas fontes** — nenhuma vai sair com parâmetro
furado, e nenhuma vai sair com apelido, porque nenhuma tem perfil de WhatsApp gravado. O
terceiro caso, `"fafaf"`, é lixo de formulário e vira **"Olá, Fafaf!"** — ver §4.

### 3.4 Silêncio do agente — 2 casos abertos, ambos pré-deploy

A query do §2.5 do RECON, aplicada a todo o período:

```
 contact_wa_id | etapa              | timestamp           | texto                                | espera
 5598984703419 | aguardando_ano     | 2026-08-26 09:36:26 | Formação em Psicologia               | NUNCA
 5598984703419 | aguardando_ano     | 2026-08-26 09:36:21 | Bom dia!                             | NUNCA
 5544998336280 | aguardando_atuacao | 2026-08-26 09:01:53 | Bom dia! Conclui a graduação em 2022 | NUNCA
```

São a Erica e a Amanda Pavão, vítimas da janela de 24 h sem tolerância ao 9º dígito
(o fix `61fa16f` que ficou 17 h 40 sem deploy). **Continuam em etapa ativa, com mensagem
sem resposta, e nada vai acordar o agente para elas** — ele só fala em resposta a inbound.
Ver §4.

---

## 4. As 4 vítimas + Fabiana — nada aconteceu desde ontem 16:00 SP

```sql
-- mensagens das 5, timestamp >= 2026-08-26 16:00
-- (0 rows)
```

Nem mensagem do SDR, nem do agente, nem do lead. Situação de cada uma:

| Lead | Reunião | Lembrete T-30 | Estado |
|---|---|---|---|
| **Marina** (207) | 26/08 14:15 — já passou | id 166 `executado` 13:45:48 | `transferido_humano`; a reunião era ontem e não há registro de desfecho no chat |
| **Mikaelle** (216) | **hoje 09:45** | id 226 **`pendente`** 09:15 | `transferido_humano`; janela de 24 h fecha 13:25 SP |
| **Natália** (222) | **hoje 15:45** | id 266 **`pendente`** 15:15 | `transferido_humano`; janela fecha 15:43 — 2 min antes da reunião |
| **Amanda C.** (220) | 28/08 14:15 | id 240 **`pendente`** 28/08 13:45 | `transferido_humano`; janela fecha hoje 14:08 |
| **Fabiana** | nenhuma | nenhum | `transferido_humano` (`outbound_manual_sdr`); as 3 tentativas de 25/08 seguem em `passo='iniciado'` |

**Os três lembretes pendentes vão disparar sozinhos** — `lembrete_reuniao` usa
`guard_de_abertura`, que não olha etapa, então `transferido_humano` não bloqueia. Os 4
avisos falsos `agente_transferiu` (ids 4421, 4424, 4452, 4453) continuam **não lidos** na
sineta da gestão.

---

## 5. O que este levantamento revelou que ainda precisa de conserto

Nenhum item vem de tráfego de hoje — não houve. Todos vêm da linha de base, e os três
primeiros são novos (não estão no RECON de 27/08).

### 5.1 O encerramento por inatividade vai mentir sobre 2 leads — **NOVO**

```sql
select id, kind, contact_wa_id, run_at, status from nat_scheduled_actions
 where contact_wa_id in ('5598984703419','5544998336280') and status='pendente';
-- 195 | encerrar_inativo | 5598984703419 | 2026-08-29 09:36:27 | pendente
-- 185 | encerrar_inativo | 5544998336280 | 2026-08-29 09:01:54 | pendente
```

Em 29/08 a Erica e a Amanda Pavão serão gravadas com
`encerrado_motivo = 'inatividade'` — "o lead calou". **O lead não calou: nós calamos.** As
duas escreveram, foram ignoradas por um bug, e vão sair da base rotuladas como desinteresse.
O `encerrar_inativo` mede o tempo desde o último inbound e não sabe distinguir "ela parou de
responder" de "nós paramos de responder" — e é justamente essa distinção que a coluna
`encerrado_motivo` foi criada para preservar (docstring de `NatQualificacaoState`).

**Sem conserto, isso contamina a régua de follow-up** que vier a usar `encerrado`.

### 5.2 Lead em etapa ativa com mensagem pendente não tem quem o acorde — **NOVO**

Consequência da mesma dupla. O vigia do P3-A cobre "o lead escreveu e o agente não
respondeu **em 10 min**", mas ele é **armado no inbound** — quem ficou preso antes de ele
existir não tem vigia, e ninguém varre o estado à procura de conversa parada. Hoje:

```
etapa ativa + último inbound sem resposta  ->  2 leads, há ~36 h
```

A cobertura que falta é a inversa da do vigia: uma varredura periódica por **estado**, não
por evento. Sem ela, todo lead que cair num buraco novo fica invisível até o
`encerrar_inativo` de 72 h fechá-lo com o rótulo errado (§5.1).

### 5.3 Lixo de formulário vira "Olá, Fafaf!" — **NOVO, e o S3-4 aumentou a exposição**

```
5571985252525 | exact_leads.name = "fafaf" | agendamentos.nome = "fafaf" | abertura hoje 09:00
```

Já havia `"zzz teste"` e `"fafaf"` em `agendamentos` no RECON. O S3-4 fez o **cadastro** ser
a fonte preferida de `_nome()`, o que está certo para o caso "Eve × Evelyn" — mas significa
que lixo digitado no formulário agora **ganha** de um perfil de WhatsApp legítimo. Neste
caso concreto não muda nada (o perfil está vazio), mas a classe existe e é nova.

`primeiro_nome` já filtra token sem letra; não filtra token *com* letra e sem sentido, e não
tem como. O lugar de resolver é a admissão (`qualificacao_pode_iniciar`) ou o formulário —
não a formatação do nome.

### 5.4 Lead antigo que se re-candidata não recebe nada — **NOVO, fora do agente**

```
26/08 19:18:47 SP  5521983878925 (Erica Dias):
  "Olá! Tudo bem? Fiz minha aplicação na turma da Pós-Graduação EAD: Novas Abordagens..."
```

Sem estado, sem ação agendada, sem resposta — **2 h 47 min** até agora. `exact_leads` diz
`register_date = 25/07`, anterior ao corte de admissão do agente, então a recusa está
**correta**. O buraco é que ninguém mais pega: o lead manda a mensagem-gatilho da LP, o
agente recusa por data e o fluxo velho não responde. Mesmo caso em `5517997472204`
(18:25:19 SP). Os dois têm SDR dono (`assigned_to` 5 e 6), então é fila humana — mas é fila
humana silenciosa, e o lead não sabe disso.

### 5.5 Já conhecidos, sem novidade hoje

* Reuniões marcadas pelo agente: **ainda 0**. P0-A sem caso real.
* `ofertar_agenda` obsoleta: **ainda não medível** — falta turno, não falta instrumentação.
* Parâmetro em branco no ramo de janela **aberta** (RECON §S3-3): continua de pé.
* Os 4 avisos falsos na sineta da gestão: continuam não lidos.

---

## 6. Para rodar quando o dia existir

```bash
# turnos do LLM, falhas de contrato e a acao obsoleta
journalctl -u cenat-backend --since "2026-08-27 09:00" | grep -E "🧠 LLM|🏷️|FORA DO CONTRATO|🛑 LLM"

# o S3-1 funcionando: concluido COM confirmacao e SEM notificacao
journalctl -u cenat-backend --since today | grep -E "✅ Agente concluiu|🛟 Agente transferiu"
```

```sql
-- o dia, em SP
select count(*) from nat_qualificacao_state where created_at - interval '3 hours' >= '2026-08-27';
select etapa, transferido_motivo, count(*) from nat_qualificacao_state
 where created_at - interval '3 hours' >= '2026-08-27' group by 1,2;

-- o S3-1: nenhum transferido por "envio recusado ... concluido" pode aparecer
select count(*) from nat_qualificacao_state
 where transferido_motivo like '%está em ''concluido''%' and transferido_em >= '2026-08-27';

-- o vigia disparou?
select status, count(*) from nat_scheduled_actions
 where kind='vigiar_resposta' and created_at >= '2026-08-27 03:00' group by 1;

-- reuniao marcada PELO agente (o zero que precisa sair do zero)
select id, nome, slot_inicio, passo from agendamentos
 where origem_ip is null and created_at >= '2026-08-27';
```
