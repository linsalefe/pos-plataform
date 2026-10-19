# SPRINT_REMARCACAO_20261019 — remarcação que termina em reunião, e aviso que chega a quem atende

Base: `RECON_REAGENDAMENTO_20261018.md`. Branch `feat/remarcacao-pendente`, em produção desde 19/10 02:32 UTC
(18/10 23:32 SP). `main` **não** foi atualizada: o diretório de produção está na branch.

## Resumo

| Critério | Estado |
|---|---|
| 1. Escolha com a antiga Vigente não chama `scheduleAdd`; grava a pendência, responde "Anotei", avisa | no ar |
| 2. Sync vê a antiga Cancelada → Hub agenda sozinho; ocupado → reoferta; 2 recusas → humano com o erro | no ar, **sem caso real ainda** |
| 3. Texto livre de remarcação vira oferta (régua viva, após o corte, após a pausa) | no ar |
| 4. Sem dono: avisos para `SDR_USER_IDS` + gestão, com a última mensagem; `new_message` com conversa pausada | no ar |
| 5. Filtros "Remarcação pendente" e "Solicitou reagendamento" com badge | no ar |
| 6. Medição do `scheduleAdd` depois do cancelamento manual | **pendente**: aguarda o primeiro caso |
| 7. Folga 15 min | aplicada; não devolveu nenhum horário (abaixo) |
| 8. Testes escritos e não executados; `import app.main`, `tsc --noEmit` e build passam | ok |

## Fase 0 — Thais e Anne

Não avisei o Thobias: não há canal com ele fora do Hub, e criar Notification ou mandar WhatsApp interno seria uma
escrita que ninguém pediu. Passei o texto ao Álefe. As duas aparecem agora no filtro novo "Solicitou
reagendamento":
- **Thais** (5549998013061): reunião 4783324, ter 20/10 às 11:00. Pediu "segunda pela manhã" ou um encaixe.
- **Anne** (5581999963650): reunião 4783426, qua 21/10 às 17:15. Escreveu "Apenas quero desmarcar".

As duas reuniões seguem Vigentes na Exact.

## DDL (checkpoint 1, aprovado e aplicado em 19/10 ~02:25 UTC)

`backend/migrate_remarcacao_pendente.py`, idempotente:

```sql
ALTER TABLE reuniao_status ADD COLUMN IF NOT EXISTS slot_desejado_inicio TIMESTAMP;
ALTER TABLE reuniao_status ADD COLUMN IF NOT EXISTS slot_desejado_consultora VARCHAR(255);
ALTER TABLE reuniao_status ADD COLUMN IF NOT EXISTS remarcacao_tentativas INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reuniao_status ADD COLUMN IF NOT EXISTS remarcacao_expira_em TIMESTAMP;
```

São 4 colunas, e não 3: a decisão 7 do spec diz 3, mas a Fase 1 lista 4. Depois da migração: 339 linhas, nenhuma
com `slot_desejado`, soma de tentativas 0.

## Folga de 15 min

`.env`: `AGENDAMENTO_FOLGA_MIN=15`, com comentário e data. O backup do `.env` anterior ficou fora do repo.
Medido contra a Exact real, logo antes e logo depois do restart:

| | seg 19/10 | ter 20/10 | qua 21/10 |
|---|---|---|---|
| folga 30 | 0 | 0 | 5 |
| **folga 15** | **0** | **0** | 5 |
| folga 0 (só referência) | 3 | 6 | 7 |

**A folga de 15 não devolveu nenhum horário para os 2 próximos dias.** As consultoras estão com reuniões de 45 em
45 min. Entre duas delas não cabe um slot de 45 min mais 15 de folga de cada lado. O que zera segunda e terça é a
ocupação, não a folga. `GOOGLE_GRADE_ENABLED` não existe no código.

## Como ficou o fluxo

1. Clique "Preciso remarcar", "Escolher horário" ou "Reagendar", ou texto que casa o padrão: o agente oferece
   horários, como antes.
2. O lead escolhe. Se a pessoa tem reunião Vigente na Exact (com início a partir de hoje − 2 dias) e a conversa é
   uma remarcação (`dados_extras.fluxo='b'` e a chave `reunioes_remarcadas`), o `_agendar` **não chama a Exact**.
   A escolha fica na linha da reunião antiga, o lead recebe "Anotei {dia} às {hora}, {nome}. A consultora confirma
   por aqui em breve.", a Exact recebe a nota `[NAT] Remarcação pendente: dd/mm hh:mm`, e os SDRs recebem o aviso
   "Remarcação pendente: cancele na Exact". O agente fecha com `concluido` / `remarcacao_pendente`. O horário fica
   reservado na grade daquela consultora por 24h.
3. Um humano cancela a antiga na Exact. O sync (a cada 10 min) vê `Vigente → Cancelada` e enfileira
   `remarcacao_retry`, que roda em menos de 1 min.
4. `remarcacao_retry`:

   | situação | o que acontece |
   |---|---|
   | horário livre | `agendar()` com o lead existente; régua de confirmação arma e o lead recebe a confirmação imediata; nota `[NAT] Remarcada para …` |
   | horário ocupado | o agente oferece de novo |
   | Exact recusou | nova tentativa em 10 min |
   | 2ª recusa | humano, com o erro da Exact verbatim no aviso e na nota |
   | SDR já marcou a nova na Exact | não marca uma segunda; limpa a pendência |

5. 24h sem cancelamento: `remarcacao_expira` avisa o lead ("A consultora vai falar com você") e passa para humano.

**Desvios do spec, com o porquê:**
- **Expiração:** é ação do `nat_scheduler`, não roda dentro do `reuniao_sync`. O sync não fala com o lead nem
  segura transação durante HTTP; a fila já tem horário e retentativa.
- **Primeira tentativa:** o sync também só enfileira, e quem chama a Exact é o handler, pelo mesmo motivo.
- **Aviso por WhatsApp ao SDR:** não saiu. O `nat_sdr_corte` diz "{{1}} não confirmou a reunião", o que é falso
  numa remarcação. Proposta de template novo (UTILITY), **não submetido**:
  `nat_sdr_remarcar`: *"Aviso da IA do CENAT: {{1}} escolheu {{2}} para remarcar a reunião da Pós em {{3}}.
  Cancele a reunião de {{4}} na Exact para o Hub marcar a nova."*
- **Consultora escolhida:** serve só para a reserva. O `agendar()` decide a consultora pela carga do dia e não
  aceita parâmetro.

## Avisos sem dono

- **Quem recebe:** `SDR_USER_IDS=5` (Thobias) no `.env`. Sem dono, as notificações da régua de confirmação, do
  no-show e das transferências do agente vão para `[5, 2]` (Thobias e Isa). Com dono, só para ele, como antes.
  Ainda não há papel SDR em `users`: todos são `admin`, menos a Ana, que é `atendente`.
- **Corpo:** termina com "Última mensagem: …", lida do banco na hora do aviso.
- **`new_message`:** contato sem dono, com conversa pausada nos últimos 7 dias e sem "Tratado", gera
  `new_message` para o mesmo grupo a cada mensagem. "Pausada" = agente transferiu, régua parou com `humano`, ou o
  lead pediu remarcação. Antes não gerava nada.
- Smoke em produção: `destinatarios(Lilian)` = `[5, 2]`; `conversa_pausada(Anne)` = True.

## Filtros

- "Remarcação pendente" (laranja, com o horário desejado no badge) e "Solicitou reagendamento" (âmbar, com o
  botão "Tratado"). Os dois entram no contador e no "Limpar filtros".
- **Ajuste feito no deploy.** A primeira versão do "Solicitou reagendamento" escondia o pedido só quando havia
  reunião nova **Vigente e futura**, e mostrou 6 contatos, entre eles Viviane, Roseli e Maria, já resolvidas.
  Agora o pedido some quando existe reunião registrada depois dele (qualquer status) ou quando a própria reunião
  aconteceu (`Concluido`). Retrato de 19/10 02:3x UTC: **Rafaela, Thais e Anne**; nenhuma remarcação pendente.

## Testes

`backend/test_remarcacao.py`, escrito e **não executado**. Cobre 11 grupos: padrão de texto, não chamar a Exact
com a antiga Vigente, reserva por consultora, sync enfileira, retry livre, ocupado, 2 recusas, expiração, texto
após a pausa com e sem reunião, destinatários, conversa pausada. Usa dublês e monkeypatch pesado; pode precisar de
ajuste na primeira execução.

Verificado: `py_compile` dos arquivos alterados, `import app.main`, `npx tsc --noEmit` e `npm run build`.
Backend e frontend reiniciados, os dois `active`, boot com as 2 consultoras.

## A medir (critério 6 e contagem de avisos)

- **Primeiro caso real** de pendente → cancelamento manual → `scheduleAdd`. Procurar no journal
  `📌 remarcacao:`, depois `✅ remarcacao:` ou `🔁 remarcacao:`. Registrar aqui se passou e, se não passou, o erro
  verbatim. Até lá, a regra "a Exact aceita depois do cancelamento" **não está provada**, e o fluxo cai para
  humano.
- **Avisos por destinatário nas primeiras 24h:**
  ```sql
  SELECT user_id, type, count(*) FROM notifications
  WHERE created_at >= '2026-10-19 02:32' AND created_at < '2026-10-20 02:32' GROUP BY 1,2 ORDER BY 1,3 DESC;
  ```
  (`created_at` aqui é UTC.)

## Para a Isa e o Thobias

- **Cancelar a reunião antiga na Exact continua sendo o gatilho.** O Hub não desmarca (a API não permite). Quando
  o lead escolhe um horário novo, aparece o aviso "Remarcação pendente: cancele na Exact" e o card ganha o badge
  laranja com o horário escolhido. Cancelem a reunião indicada e **não criem a nova na mão**: o Hub cria em até
  10 min. Se criarem, o Hub percebe e não duplica.
- **Filtro novo "Solicitou reagendamento"**: quem pediu para remarcar e ainda não tem reunião nova. "Tratado"
  tira o card do filtro.
- Lead sem dono agora avisa o Thobias e a Isa, com a última mensagem no aviso.

## Riscos

- **Janela de 24h do WhatsApp.** Se o cancelamento demorar mais de 24h desde a última mensagem do lead, o texto
  livre não sai ("Pronto…", nova oferta). A confirmação imediata da régua é template e sai mesmo assim.
- **Reunião Vigente com início há mais de 2 dias** não bloqueia: o sync não a relê, e esperar por ela seria
  esperar para sempre. Nesse caso o `scheduleAdd` é tentado direto e pode falhar como antes, com fallback para
  humano.
- **Mais avisos.** Sem dono, cada mensagem de conversa pausada notifica todos os SDRs.

## Observações para depois (fora do escopo)

- `ChangeFunnel` para "Reagendamento - IA" após `Cancelada`.
- Dono automático para lead da LP.
- Grade do Google.
- O "Lead não compareceu" registrado em reunião que o lead avisou que não ia (Rafaela, Lilian) distorce o
  no-show.
