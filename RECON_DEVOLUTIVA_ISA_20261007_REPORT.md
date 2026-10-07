# RECON: devolutiva da Isa sobre a IA de Confirmação (07/10/2026)

Auditoria somente leitura. A única escrita foi a da Fase 2: um box de teste criado e removido na
Exact, com a limpeza comprovada. Nenhum código, template ou mensagem a lead foi alterado ou
enviado. Leads de teste fora das métricas (`relatorios.chaves_de_teste`). Chamadas à Exact feitas
com o token lido do `.env`, nunca impresso.

Helper usado em todas as chamadas:

```bash
T=$(grep ^EXACT_SPOTTER_TOKEN= backend/.env | cut -d= -f2-)
curl -s -G -w "\n[HTTP %{http_code}]\n" -H "token_exact: $T" "https://api.exactspotter.com/v3<path>" --data-urlencode '<param>'
```

## §0 Resumo

1. **Corte liberando o horário no site.** A Exact recusa box sobreposto (`Boxes are occupied at
   the desired time.`), então enquanto a reunião cortada estiver Vigente o horário daquela
   consultora não pode ser reaproveitado. Mas há um defeito nosso, maior que o corte: mesmo
   depois de a consultora cancelar na Exact (o box some), a nossa tabela `agendamentos` continua
   bloqueando o horário no site. Hoje às 14h30 a comercial@ não é oferecida só por causa disso.
2. **No-show de quem confirmou e faltou.** É legível pela API. O feedback não está em
   `/Meetings` (a reunião só vira `Cancelada`), está na timeline do lead
   (`GET /ListTimeline/{leadId}`) como texto padronizado: "foi desmarcada. Motivo: Lead não
   compareceu" ou "Motivo: Solicitou Reagendamento". Em 30 dias: 94 "não compareceu", 23
   "solicitou reagendamento". 54 dos "não compareceu" eram do Hub e tinham recebido o T-30.
3. **Filtros para o SDR.** Os dados existem em `reuniao_status`. A tela filtra no navegador sobre
   a lista inteira de `GET /contacts`; acrescentar os 3 filtros custa cerca de 20 ms por carga da
   lista se o casamento for feito em Python (o `LEFT JOIN` em SQL custa 1 s). Estimativa: 3h
   backend, 5h frontend.

## §1 Grade hoje (Fase 1)

### 1.1 O que `/Boxes` devolve

```
GET /Boxes  $filter=salesRepEmail eq 'comercial@cenatcursos.com.br' and start ge 2026-10-07T00:00:00Z and start le 2026-10-08T23:59:00Z
[HTTP 200]  4 boxes; chaves: address, description, end, id, leadId, salesRep, salesRepEmail, start, status, typeMeeting
44099330 busy 2026-10-08T14:30:00Z 2026-10-08T15:15:00Z 'Agendamento LP, Maitê Queiroz'   (leadId 52509719)
44103770 busy 2026-10-08T16:45:00Z 2026-10-08T17:45:00Z ''
44103771 busy 2026-10-08T09:00:00Z 2026-10-08T10:10:00Z ''
44103772 busy 2026-10-08T13:30:00Z 2026-10-08T14:30:00Z ''
```

O vínculo do box com a reunião é o `leadId` (box com reunião) e o `status` `busy`. Não há
`meetingId` no box. Obs.: sem o sufixo `Z` a Exact devolve 400 (`The DateTimeOffset text
'2026-10-07T00:00:00' should be in format ...`); `client.py` sempre manda com `Z`
(`horarios.py:41-53`).

### 1.2 Box de reunião cancelada

Três reuniões `Cancelada` dos últimos dias, com o box gravado em `agendamentos.box_id`, e
controle positivo com boxes de reuniões Vigentes:

| reunião | type | box | `GET /Boxes $filter=id eq <box>` |
|---|---|---|---|
| 4772376 (07/10 10:00, cancelada hoje 10:35) | Cancelada | 44086980 | 0 linhas |
| 4773923 (07/10 14:30) | Cancelada | 44097623 | 0 linhas |
| 4773207 (08/10 13:45) | Cancelada | 44091264 | 0 linhas |
| 4772377 (07/10 10:00) | Vigente | 44086987 | 1 linha, busy |
| 4773672 (09/10 10:00) | Vigente | 44097070 | 1 linha, busy |
| 4774926 (09/10 16:00) | Vigente | 44104060 | 1 linha, busy |

**Quando a consultora cancela a reunião na UI, o box some dos GETs.** É o mesmo efeito em
cascata já visto no FINDINGS §6.

E o horário volta a ser agendável na Exact: o espelho tem 4 casos reais de reunião nova na mesma
consultora e no mesmo horário, registrada depois do cancelamento da anterior (ex.: 4751410
Cancelada e 4751839 marcada para o mesmo 14/09 17:15, comercial@).

**Mas o site não volta a oferecer.** `disponibilidade._ocupados_por_nos`
(`disponibilidade.py:101-121`) soma toda linha de `agendamentos` com passo fora de
`falhou/iniciado/recusado`, e o passo `agendado` nunca muda (docstring de `ReuniaoStatus`,
`models.py`). Prova ao vivo, grade de hoje (`slots_livres(usar_cache=False)`):

```
13:00 ['comercial']
13:45 ['comercial']
14:30 ['processoseletivo']          <- comercial@ fora
15:15 ['comercial', 'processoseletivo']
agendamentos 959: passo='agendado', slot 07/10 14:30, comercial@, meeting 4773923 (Cancelada, box já removido)
```

A comercial@ não tem nenhum box hoje na Exact. O único bloqueio das 14h30 é a nossa linha 959.
Hoje há 2 linhas nessa situação com horário futuro (959 e 945).

### 1.3 Tamanho do problema

O espelho só existe desde 07/10 06:39 e viu uma única transição (4772376, Vigente para
Cancelada às 10:35, 35 min depois do horário). Para o histórico usei a volta automática
`Agendados -> Entrada` em `exact_stage_events`, que é o efeito do cancelamento da reunião
(`noshow.py`, `TRANSICOES_AUTOMATICAS`). `observado_em` é UTC e foi convertido para SP.

```
reuniões do Hub canceladas, horário nos últimos 30 dias (sem teste): 112
  com a volta Agendados->Entrada observada:                          56
  canceladas ANTES do horário:   3   (antecedência mediana 5,3h)
  canceladas DEPOIS do horário: 53   (atraso mediana 0,5h, p75 5,0h, p90 71h, máx 359h)
    em até 2h depois: 39 · mais de 24h depois: 12
```

A consultora cancela quando o lead falta, raramente antes. No corte, a reunião morta segue
Vigente do corte até depois do horário. É a janela inteira de corte para reunião: 4h nas reuniões
da tarde, e de 9h até o horário nas da manhã (`confirmacao.corte_de`). Durante essa janela a
Exact recusa outro box para a mesma consultora.

## §2 Teste de sobreposição (Fase 2)

Horário fora do expediente: hoje 23:00 a 23:45, processoseletivo@.

```
### 1) listar (antes)
GET /Boxes $filter=salesRepEmail eq 'processoseletivo@...' and start ge 2026-10-07T22:00:00Z and start le 2026-10-08T00:30:00Z
{"value":[]}  [HTTP 200]

### 2) criar box A
POST /BoxesAdd {"start":"2026-10-07T23:00:00Z","end":"2026-10-07T23:45:00Z","salesRepEmail":"processoseletivo@...","status":"available","typeMeeting":"web","description":"TESTE RECON 07/10 sobreposicao - remover"}
{"value":44106217}  [HTTP 201]

### 3) criar box B (mesmo horário, mesma consultora)
{"error":{"code":"","message":"Boxes are occupied at the desired time."}}  [HTTP 400]

### 4) listar
{"value":[]}  [HTTP 200]          <- cache do GET; pelo id ($filter=id eq 44106217) o box A aparece, available
### 5) remover box A (B não foi criado)
DELETE /BoxesRemove/44106217      [HTTP 204]
### 6) listar (depois)
ainda mostrava o box A (cache); sumiu dos dois GETs (listagem e por id) às 13:39 UTC, cerca de 1 min depois
{"value":[]}  [HTTP 200]
DELETE /BoxesRemove/44106217 de novo   [HTTP 204]   (soft delete idempotente, FINDINGS §6)
```

**A Exact recusa a sobreposição.** Nenhum box de teste ficou na Exact.

Consequência para o corte (ramo "recusa" do plano): liberar no site significaria oferecer o
horário só para a OUTRA consultora. Medido nas 157 reuniões do Hub de 30 dias atrás até daqui a
3 dias: a outra consultora tinha o mesmo horário na grade em 54 (as grades das duas não têm os
mesmos horários) e estava sem box sobreposto em 29, **18% do total**. É ganho pequeno.

## §3 Feedback da consultora (Fase 3)

### 3.1 Opções da tela

Não houve print nesta sessão. As opções aparecem no próprio texto que a Exact grava (3.3):
"Lead não compareceu", "Solicitou Reagendamento", e o feedback pós reunião com qualificação.

### 3.2 `$metadata`

```
Meetings          -> ReuniaoODataDTO: lead, salesRep, user, type, registerDate, meetingType, meetingDate, startTime,
                     finalTime, managerDescription, sdrDescription, reference, meetingFeedbackUrl, score (String),
                     qualificationDate (DateTimeOffset), id
PendingFeedbacks  -> meetingId, leadId, leadName, stageId, stageName, sellerId, sellerName, sellerLastName, date
MeetingQuality    -> quantities: Collection(QualificationChartDTO{qualification, quantity, score}),
                     totalMeetings, pendingFeedbacks, completedFeedbacks
MeetingQualitySQL -> sql (Int32), rejected (Int32)
ListTimeline      -> user, leadId, text, createdAt, id
QualificationHistories -> questionAnswers, leadId, funnelId, originStage, stage, cycle, score, points,
                     qualificationDate, meetingDate, userAction
```

`MeetingQuality` e `MeetingQualitySQL` são **agregados por período**, sem id de reunião. Os dois
pedem `initialDate`/`finalDate` e recusaram 6 formatos de parâmetro testados (query string com
data, data e hora, `dd/mm/aaaa`, entre aspas, header, `$filter`): sempre `Invalid period.
'initialDate' and 'finalDate' are required`. Não identificam reunião de qualquer forma.

`GET /PendingFeedbacks` [HTTP 200]: reuniões Vigentes sem feedback (ex.: 4751839, 4754009,
4758927), com `date` em UTC.

### 3.3 Qual campo muda

`/Meetings` dos últimos 30 dias (234 reuniões):

```
type=Cancelada score=None qualificationDate=None: 149
type=Concluido score=None qualificationDate=None:  60
type=Vigente   score=None qualificationDate=None:  13
type=Concluido score=Muito Quente / Quente / Congelada / Morna, com qualificationDate: 12
```

Nenhum valor de `type`, `score` ou campo de texto da reunião separa a falta. `score` é a
temperatura do lead no feedback pós reunião, não o comparecimento. A falta vira só `Cancelada`.

**O feedback está na timeline do lead.** `GET /ListTimeline/{leadId}` (a forma com
`$filter=leadId eq` dá 404; `/ListTimeline/52450489` e `/ListTimeline(52450489)` dão 200):

Reunião em que o lead faltou (4772376, lead 52450489, hoje):

```json
{"type":"Cancelada","meetingDate":"2026-10-07","startTime":"2026-10-07T10:00:00.0000000","finalTime":"2026-10-07T10:45:00.0000000",
 "meetingFeedbackUrl":"https://app.exactspotter.com/reuniao/NDc3MjM3Ng2","score":null,"qualificationDate":null,"id":4772376,
 "lead":{"id":52450489},"salesRep":{"email":"comercial@cenatcursos.com.br"}}
```
```
2026-10-07T13:19:47Z  A reunião de 07/10/2026 10:00 com o vendedor Victória Amorim foi desmarcada. Motivo: Lead não compareceu;  Observações:
2026-10-07T13:22:10Z  Lead movido de Entrada para Follow 1
```

Reunião que aconteceu (4752526, lead 51846973):

```json
{"type":"Concluido","meetingDate":"2026-09-18","startTime":"2026-09-18T10:40:00.0000000",
 "meetingFeedbackUrl":"https://app.exactspotter.com/reuniao/NDc1MjUyNg2","score":"Morna","qualificationDate":"2026-09-18T15:44:16.4474632Z",
 "id":4752526,"lead":{"id":51846973},"salesRep":{"email":"comercial@cenatcursos.com.br"}}
```
```
2026-09-14T15:20Z  A reunião de 14/09/2026 10:30 com o vendedor Victória Rodrigues foi desmarcada. Motivo: Solicitou Reagendamento;  Observações:
2026-09-18T12:31Z  Reunião sinalizada como confirmada.
2026-09-18T15:44Z  Aprovado em Feedback pós reunião [ Isa ]. Qualificação: Morna (20 pontos)
```

Resposta: **o campo é o texto da timeline**, endpoint `GET /ListTimeline/{leadId}`, padrão
`A reunião de <dd/mm/aaaa hh:mm> com o vendedor <nome> foi desmarcada. Motivo: <motivo>;`. A
reunião em `/Meetings` vira `Cancelada`, e o espelho (`reuniao_sync`) já detecta essa transição a
cada 10 min. Basta uma leitura da timeline daquele lead quando o espelho vê `Vigente -> Cancelada`.

### 3.4 Tamanho do público

Timeline dos 196 leads com reunião `Cancelada` ou `Concluido` em 30 dias (0 falhas de leitura):

```
94 desmarcada, Motivo: Lead não compareceu
36 desmarcada, sem motivo
23 desmarcada, Motivo: Solicitou Reagendamento
```

Casando com a reunião do recorte, sem teste:

| motivo | origem | recebeu T-30 | n |
|---|---|---|---|
| Lead não compareceu | Hub | sim | **54** |
| Lead não compareceu | SDR na Exact | não | 25 |
| Lead não compareceu | Hub | não | 13 |
| Solicitou Reagendamento | Hub | sim | 15 |
| Solicitou Reagendamento | SDR na Exact | não | 4 |
| Solicitou Reagendamento | Hub | não | 2 |
| sem motivo | Hub/Exact | | 35 |

**92 faltas em 30 dias, cerca de 3 por dia útil.** 54 delas receberam o lembrete T-30 e faltaram
mesmo assim: é o público "confirmou e faltou" do antes. `confirmado_em` ainda não tem histórico
(a régua começou hoje).

### 3.5 Alternativas

Não são necessárias: o feedback é legível. O webhook `event.schedulenotheld` continua sem teste e
sem necessidade imediata.

## §4 Filtros do SDR (Fase 4)

### 4.1 A tela hoje

- `statusFilter` (`page.tsx:154`, aplicado em `:817`) usa `contacts.lead_status`. Valores
  (`page.tsx:127-132`): `novo`, `em_contato`, `qualificado`, `negociando`, `convertido`,
  `perdido`. Origem: `novo` na criação (`exact_spotter.py:360`, `qualificacao_fluxo.py:601`);
  o resto só por PATCH manual do SDR (`routes.py:627`). Não reflete reunião nem confirmação.
- Filtros rápidos (`page.tsx:1030-1060`): Não lidos, IA ativa, IA off. Filtro de tag
  (`:186`, `:818`) e de SDR (`:190`, `:821`, `:1061-1090`).
- Tudo é filtrado no navegador (`filteredContacts`, `page.tsx:811-823`) sobre a lista inteira de
  `GET /contacts` (`routes.py:431-480`): uma consulta com 2 `LATERAL` em `messages`, sem
  paginação, 8 643 contatos.
- **Kanban IA** (`kanban_routes.py`): lê `AIConversationSummary`, do motor de IA antigo que está
  desligado (`main.py`, bloco "AGENTE IA: DESATIVADO"). Não cobre nada disto.

### 4.2 Custo da consulta

```
ATUAL      (GET /contacts):                                   Execution Time: 165.6 ms
PROPOSTA A (+ LEFT JOIN LATERAL reuniao_status por chave_sql): Execution Time: 1228.9 ms
           Index Scan Backward using ix_reuniao_status_telefone_slot ... (actual time=0.002..0.002 loops=8589)
PROPOSTA B (1 consulta separada + casamento em Python):
           SELECT DISTINCT ON (telefone_chave) ... FROM reuniao_status   Execution Time: 0.286 ms (212 pessoas)
           chave_telefone() sobre 8 643 wa_ids + dict lookup:           18 a 20 ms
```

O índice `ix_reuniao_status_telefone_slot` é usado, mas a expressão regular de `chave_sql` sobre
cada contato custa 1 s. **Recomendo a B**: o endpoint já pós-processa as linhas em Python (fusão
das duas grafias e tags), e a chave canônica é a de Python (`telefone.chave_telefone`).

Quantos contatos cada filtro pegaria hoje: reunião marcada 7, confirmou 3, respondeu fora do
padrão 2 (`regua_encerrada_motivo='humano'`).

### 4.3 Desenho mínimo

Backend (`routes.py`, cerca de 3h): `GET /contacts` devolve por contato `reuniao`:
`{slot_inicio, exact_type, confirmado, fora_do_padrao}` da reunião mais recente da pessoa (B).
`fora_do_padrao` = `regua_encerrada_motivo` em (`humano`, `sem_interesse`) ou `cancelado_motivo`
em (`remarcar`, `lead_avisou`, `sem_interesse`).

Frontend (`page.tsx`, cerca de 5h): 3 botões nos filtros rápidos, "Reunião marcada" (Vigente
futura), "Confirmou" e "Respondeu fora do padrão", que ordenam por `slot_inicio`; badge com dia e
hora da reunião no card. Sem dependência das outras sprints.

## §5 Proposta de sprints, em ordem

1. **Grade libera o que a consultora cancelou** (cerca de 2h, sem decisão de produto).
   `_ocupados_por_nos` passa a ignorar a linha de `agendamentos` cuja reunião está `Cancelada`
   no espelho (`reuniao_status.agendamento_id`). É bug, não feature: hoje 2 horários futuros estão
   bloqueados no site por reunião que a Exact já liberou.
2. **Filtros do SDR** (cerca de 8h, §4.3). Decisão da Isa: os nomes dos 3 filtros e se o badge
   aparece também na lista do Kanban.
3. **No-show por feedback da consultora** (cerca de 6h). Quando o espelho vê `Vigente ->
   Cancelada`, ler `ListTimeline/{leadId}` uma vez e extrair o motivo. Decisão da Isa:
   - "Lead não compareceu": entra na régua de no-show atual (D0 a D8) ou numa variante para quem
     confirmou?
   - "Solicitou Reagendamento": manda direto os horários (`reabrir_para_oferta`, Bloco 3)?
   - "sem motivo" (35 em 30 dias): fica de fora?
4. **Corte e agenda** (decisão do Álefe e da Isa antes de qualquer código). A Exact não deixa
   reaproveitar o horário enquanto a reunião estiver Vigente, e a outra consultora só cobre 18%.
   O caminho de maior efeito é de processo: a consultora cancelar a reunião quando recebe o aviso
   do corte (o aviso já pede isso, `confirmacao.py` no handler do corte); com a sprint 1, o site
   libera no mesmo ciclo.

## §6 O que contradiz o que foi dito à Isa hoje

1. "Quem confirma e falta fica fora": **deixa de ser verdade**. A falta é legível na timeline
   (§3.3) e o espelho já vê o cancelamento; só falta ligar uma coisa na outra (sprint 3).
2. "Quando a consultora cancela, o horário volta para o site": **não volta**, por causa da nossa
   tabela `agendamentos` (§1.2). Volta na Exact, não no site.
3. RECON de confirmação §5.2 e §7 item 2: "o gatilho consultora marca no-show não é detectável
   por polling". É detectável: `/Meetings` só diz `Cancelada`, mas a timeline diz o motivo.
4. Achado lateral: as notas `[NAT]` que o Hub grava aparecem na timeline com autor **Victória**
   (`EXACT_NOTE_USER_ID` 415967 é a Victória Amorim), lado a lado com as notas reais dela. Vale
   avisar as consultoras, ou trocar o autor por um usuário técnico se a Exact tiver um ativo.
5. A Exact tem um marcador próprio, "Reunião sinalizada como confirmada", na timeline (§3.3). Não
   foi investigado se é gravável pela API; se for, a confirmação da régua poderia aparecer na
   reunião e não só como nota.

## Fechamento

```
git status:  ?? backend/fix_status_orfao_webhook.py   (já conhecido) + este relatório
Boxes de teste na Exact: listagem 23:00-00:30 de processoseletivo@ vazia antes ({"value":[]}) e depois ({"value":[]}); box 44106217 removido
```
