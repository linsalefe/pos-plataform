# Sprint NAT — Blocos 5 e 7: transferência, SLA, escalonamento e agendador (2026-07-26)

Branch `feat/nat-blocos-5-7-20260726`, **mergeada em `main` em 26/07 por decisão do Álefe**
(o plano original dizia "não dar merge"; ele sobrepôs). A NAT continua **DESLIGADA** —
`nat_enabled=false`, `nat_start_at=NULL`. Nada disto entra em operação nesta sprint.

O buraco que a sprint fecha: o lead chegava em `aguardando_ligacao` e **ninguém era avisado**.
Agora alguém é avisado, em 2 minutos o SLA cobra, e se ninguém assumir a coisa sobe até a
gestão.

---

## O que subiu

| arquivo | o que é |
|---|---|
| `backend/migrate_nat_sprint3.py` | **novo** — `nat_scheduled_actions`, `messages.nat_etapa`, 3 colunas em `nat_flow_state` |
| `backend/app/nat_scheduler.py` | **novo** — agendador genérico (Bloco 7) |
| `backend/app/nat_sla.py` | **novo** — handler do `sla_check` e a escada de escalonamento |
| `backend/app/nat_routes.py` | **novo** — `GET /api/nat/{wa_id}/estado`, `POST /api/nat/{wa_id}/assumir` |
| `backend/test_nat_sprint3.py` | **novo** — 91 verificações, nada enviado, nada gravado |
| `RECON_NAT_FASE1_EXACT_20260726.md` | **novo** — a recon que matou o passo do estágio no Exact |
| `backend/app/models.py` | `NatScheduledAction`, `Message.nat_etapa`, `assumido_por`/`assumido_em`/`escalonamento_nivel` |
| `backend/app/nat_flow.py` | `transferir_para_sdr` e o conteúdo da notificação |
| `backend/app/nat_guard.py` | marcador de envio da NAT + `GESTOR_USER_ID` |
| `backend/app/nat_sender.py` | grava `nat_etapa` no outbound |
| `backend/app/exact_spotter.py` | `add_timeline_comment` ganhou parâmetro `timeout` |
| `backend/app/main.py` | job do agendador no `lifespan` + router da NAT |
| `frontend/src/app/conversations/page.tsx` | botão "Assumir ligação" e o selo de quem assumiu |
| `backend/test_nat_flow.py` | caso 8 ajustado (ver "Regressão") |

---

## 1. A API do Exact permite mudar estágio? Sim. Mas a etapa não existe.

Não havia doc da v3 no repo, então a fonte foi o próprio serviço: `GET /v3/$metadata`
(64.165 bytes de CSDL, **101 entity sets, zero Actions/Functions** — nesta API toda escrita é
um POST num entity set cujo nome é o verbo, o padrão que `TimelineAdd` já segue).

**`POST /v3/ChangeFunnel` com `{leadId, stageId}`** é o endpoint. O nome engana: o corpo não
tem `funnelId`, só `stageId`, e como cada estágio pertence a um funil, mandar o estágio já
determina o funil.

**Mas `GET /v3/Stages` devolve 65 estágios, todos ativos, e nenhum se chama "Aguardando
Ligação"** — conferido também contra o estágio real dos leads já ingeridos, funil por funil.
Não existe `stageId` para mandar. E **não existe `StagesAdd`**: criar estágio é configuração,
só pela interface do Exact.

**O teste controlado de escrita não foi executado.** O plano mandava usar um lead `Descartado`
e reverter, mas `Descartado` **não é um estágio** (não está nos 65; o metadata tem
`discardedStage`/`discardDate` e os entity sets `LeadsLost`/`LeadsRecover`/`DiscardReasons`).
A escrita seria de mão única, sem `stageId` de volta. A Fase 1 dizia "se qualquer passo for
incerto, não executar" — a reversão era o passo incerto.

**Consequência: a Fase 5 nasceu com 3 passos, não 4.** Plano B definitivo, não temporário. Para
desbloquear no futuro: criar o estágio na interface, ler o `stageId` novo e guardá-lo **em
config, nunca hard-coded** (mesmo motivo que canal e template saíram de constante para
`auto_welcome_config`). Detalhes e as chamadas literais em `RECON_NAT_FASE1_EXACT_20260726.md`.

Dois achados de operação, de graça: o `$filter` de `StagesLead` é **ignorado** pelo serviço, e
`LeadPipelineStages` **estourou 30s**. Nenhum dos dois serve para consulta síncrona dentro do
webhook.

O item "role gestor" da migração foi **removido em definitivo**: `users` só tem `users_pkey` e
`users_email_key` — nenhum CHECK em `role`, que é VARCHAR livre — e os 7 gates do código
(`auth.py:65`, `routes.py:346`, `twilio_routes.py:290`, `auth_routes.py:64/92/119/140`) são
todos o literal `role != "admin"`. Não havia a que acrescentar `'gestor'`.

## 2. Migração

Uma transação, idempotente (rodada duas vezes, a segunda limpa), com
`SET lock_timeout = '3s'` porque o `sync_exact_leads` mantém transação longa a cada 10 min.

```sql
CREATE TABLE nat_scheduled_actions (
    id BIGSERIAL PRIMARY KEY, kind VARCHAR(40) NOT NULL,
    contact_wa_id VARCHAR(20) NOT NULL, run_at TIMESTAMP NOT NULL, payload TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pendente', attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(), processed_at TIMESTAMP,
    CONSTRAINT nat_scheduled_status_valido
        CHECK (status IN ('pendente','executado','cancelado','falhou')));
CREATE INDEX idx_nat_sched_status_runat ON nat_scheduled_actions (status, run_at);
CREATE UNIQUE INDEX uq_nat_sched_pendente_por_contato
    ON nat_scheduled_actions (kind, contact_wa_id) WHERE status = 'pendente';
ALTER TABLE messages ADD COLUMN nat_etapa TEXT;
CREATE INDEX idx_messages_nat_etapa_ts ON messages (timestamp) WHERE nat_etapa IS NOT NULL;
ALTER TABLE nat_flow_state ADD COLUMN assumido_por INTEGER;
ALTER TABLE nat_flow_state ADD COLUMN assumido_em TIMESTAMP;
ALTER TABLE nat_flow_state ADD COLUMN escalonamento_nivel INTEGER NOT NULL DEFAULT 0;
```

**`run_at` é naive em horário de São Paulo**, igual a `messages.timestamp`. O banco está em
`Etc/UTC` (verificado): um `run_at <= now()` do Postgres compararia SP contra UTC e dispararia
tudo **3h adiantado, em silêncio**. O corte sempre vem de Python.

**CHECK em `status`, deliberadamente NÃO em `kind`**: `status` é conjunto fechado, `kind` é
ponto de extensão (o Bloco 6 acrescenta pelo menos um). Kind sem handler vira `falhou` com
motivo — ruidoso, nunca `executado` em silêncio.

**Nada da NAT mora em `exact_leads`**, então o `setattr` cego do ramo de update do sync não tem
o que atropelar.

## 3. Agendador: como a execução única é garantida

Três camadas:

1. **`SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1`** — quem rodar o mesmo SELECT no mesmo
   instante **salta** a linha travada em vez de esperar. Com 1 worker é proteção contra o
   futuro (2º worker, restart com sobreposição, alguém rodando o job à mão), não contra o
   presente.
2. **Executa e marca `executado` na MESMA transação.** Sem janela entre "executei" e
   "registrei". Processo morre no meio → commit não sai → linha volta a `pendente` e a ação
   roda **do zero**, nunca meio-executada e marcada como pronta.
3. **Uma transação e uma sessão por ação**, não por lote.

O que **não** é garantido, e está escrito no módulo: se um handler tiver efeito colateral
externo e o commit falhar depois, o efeito externo repete. Para o `sla_check` é inofensivo (o
efeito é uma notificação no banco, que volta atrás junto). Handler futuro que mande WhatsApp
precisa da própria idempotência, no padrão do `ultimo_wa_message_id`.

**O handler recebe `dict`, não objeto ORM**, e o desfecho é gravado por `UPDATE` explícito:
reverter savepoint **expira** objetos ORM tocados nele, e um acesso a atributo depois disso
dispara recarga lazy, que em async estoura `MissingGreenlet`.

**`agendar`/`cancelar` não abrem savepoint e não commitam** — a fronteira é de quem chama. É o
que permite ao handler reagendar **atomicamente junto** da própria marcação de `executado`.

### Dois bugs que só o banco real pegou

O smoke da Fase 3 rodou contra o Postgres de produção (tabela nova, `contact_wa_id='__smoke__'`,
limpeza no `finally`, baseline de `messages`/`nat_flow_state`/`nat_button_events`/`notifications`
idêntico antes e depois, `COUNT(*) = 0` ao final).

**Bug 1 — a retentativa não existia.** `processar_pendentes` tem laço interno de até 50 ações;
a ação falhada continuava `pendente` com `run_at` vencido e era **repescada na mesma passada**.
As 3 tentativas queimavam em milissegundos — uma indisponibilidade de rede de 2s mataria a
ação, que é exatamente o cenário que a retentativa deveria cobrir. **Correção:** o `run_at` é
empurrado para `agora + 60s`. Como o atraso vive no banco, sobrevive a restart.

**Bug 2 — dois relógios.** `_executar_acao` empurrava usando `_agora_sp()` real enquanto o
corte vinha do `agora` injetado. Em produção coincidem; com tempo simulado, não. **Correção:**
o relógio do ciclo desce por parâmetro. Um relógio por ciclo.

Mock nenhum pegaria nenhum dos dois.

O smoke também provou o que só o Postgres responde: **duas sessões asyncio no mesmo SELECT** —
uma pegou `id=18`, a outra recebeu `None` (pulou, não esperou) — e o **índice parcial
disparando**: `UniqueViolationError ... "uq_nat_sched_pendente_por_contato"`.

## 4. O teto por hora agora conta o quê

```sql
SELECT count(*) FROM messages
 WHERE direction = 'outbound' AND timestamp > (agora_sp - 1h) AND nat_etapa IS NOT NULL
```

`nat_etapa` é escrito num **único lugar** (`nat_sender.py:159`) e guarda a **etapa** que
originou o envio, não um booleano. `NULL` é a resposta certa para todo o resto: boas-vindas,
resposta manual de SDR, disparo em massa.

O `EXPLAIN` confirma o índice parcial (`Index Scan using idx_messages_nat_etapa_ts`), que
indexa só as linhas da NAT em vez de varrer as 26.767 de `messages` — e isto roda **antes de
cada envio**.

O tamanho do buraco que isso fecha, com dados reais:

| janela | outbound total (o que a versão antiga contaria) | atribuível à NAT |
|---|---|---|
| 1 hora | 0 | 0 |
| 1 dia | 1 | 0 |
| **7 dias** | **1.182** | **0** |

Com o teto de 20/hora e a contagem antiga, uma campanha da tela de Automações travaria a NAT
sem a NAT ter mandado nada — e a reação natural seria subir o teto, evaporando a proteção.

A alternativa descartada foi `sent_by_ai`: coluna **morta**, nenhum código a escreve, 0 de
26.767 linhas com `true`. Escolher booleano foi o que a matou.

## 5. Conteúdo da notificação de transferência

O formato é ditado pelo frontend, não por gosto. Em `NotificationBell.tsx`:

| campo | | consequência |
|---|---|---|
| `title` (linha 211) | sem limite | quebra linha, aparece **inteiro** |
| `body` (linha 214) | **`line-clamp-2`** | **duas linhas**, cobre o corpo inteiro nos casos reais |

Daí: **telefone no título** (único lugar garantido) **e no começo do corpo**, formatado —
o SDR tem 2 minutos, e `5585999865219` é mais lento de ler e mais fácil de errar que
`+55 85 99986-5219`.

```
normal    title: Ligar agora: Maria Lidia — +55 85 99986-5219
          body : +55 85 99986-5219 · Saúde Mental · disse: "quero atender melhor"
sem SDR   title: Ligar agora (SEM SDR): Paulo Alberto — +55 11 98765-4321
          body : +55 11 98765-4321 · Neuropsicologia · disse: "…" · lead sem SDR atribuído
```

A linha 214 era `truncate` (uma linha, ~50 ch) e virou `line-clamp-2` na revisão do
Checkpoint 7: com uma linha só, sobreviviam o telefone e o começo do nome — o curso e a fala do
lead ficavam fora, e o SDR tinha que abrir a conversa dentro dos 2 min do SLA. Nada mais depende
do corpo ser uma linha: o `showPopup` passa o body para a Notification API nativa (indiferente a
CSS) e o `truncate` de `templates/page.tsx:167` é de outra entidade (corpo de template).

### Os três passos, em savepoints separados

| # | passo | se falhar |
|---|---|---|
| 1 | **notificação** + `transferido_em` | **aborta os outros dois** |
| 2 | timeline no Exact (`timeout=5`) | registra e ignora |
| 3 | `sla_check` +2min — o mais descartável | notificação permanece; só não há escalonamento |

`add_timeline_comment` **tinha** timeout, mas de 15s. Em vez de baixar o default (afetaria
`ai_engine.py:415`, fora de caminho crítico), ganhou parâmetro; a NAT passa 5s. Com a Exact
fora do ar, 15s segurariam o lote de mensagens de **todos** os leads daquele webhook.

**A `etapa` não é um dos passos.** Ela avança em `processar_texto`, sempre, depois de o envio ao
lead dar certo — não avançar deixaria a reentrega do webhook remandar a mensagem. A
transferência é o efeito colateral da transição, não a transição.

**Lead sem SDR na hora da transferência** (o `assigned_to` pode ser limpo entre a entrada e a
transferência) → notifica a gestão, com "SEM SDR" no título. A existência do destinatário é
**conferida**, não presumida: `notifications.user_id` tem FK, e um id inexistente estouraria no
passo 1 — justamente o passo cuja falha cancela os outros.

## 6. Transições de escalonamento

| nível de entrada | ação | saída | reagenda? |
|---|---|---|---|
| **0** | avisa **o outro SDR** (4 ↔ 5) | 1 | **sim**, +2 min |
| **0**, sem SDR dono | avisa **AMBOS os SDRs** (4 e 5) | **2** | **não** |
| **1** | avisa a **gestão** (id 2) | **2** | **não** |
| **2** | nada | 2 | não |

**Não reagendar no nível 2 é o que encerra o ciclo** — sem novo `sla_check`, nenhum ciclo
futuro volta ao lead. O nível 2 persistido é a defesa contra uma ação atrasada chegar depois.

`outro_sdr` é subtração de conjunto, não round-robin: são exatamente dois.

Três saídas de "nada a fazer", todas terminando em `executado` (não é falha): sem estado,
etapa diferente de `aguardando_ligacao`, ou **`assumido_por` preenchido**. O estado é **relido
a cada execução**, nunca vem do payload — entre agendar e executar passam minutos.

O título diz que é escalonamento porque quem recebe no nível 1 **não é o dono do lead**: se
parecesse transferência normal, ele assumiria achando que o lead é dele e o dono nunca saberia
que perdeu o SLA.

**Interação sutil com o índice único:** quando o handler reagenda, a ação em execução ainda
está `pendente` (o `executado` só é gravado depois). Inserir um segundo `pendente` violaria o
índice. Não viola porque `agendar()` cancela o pendente do mesmo `(kind, contato)` antes de
inserir — **ele cancela a própria ação em curso** — e o `_finalizar` a sobrescreve para
`executado` em seguida. O cancelamento dentro do `agendar()` deixou de ser conveniência: é o
que torna o reagendamento possível.

## 7. Endpoint `assumir` + frontend

```
GET  /api/nat/{wa_id}/estado    autenticado
POST /api/nat/{wa_id}/assumir   autenticado
```

**`pode_assumir` é calculado no backend**, não no TSX: é a mesma regra que o handler do SLA
aplica, e replicá-la no frontend daria dois lugares para ela divergir — o frontend perderia
primeiro. `GET` devolve `em_fluxo: false` em vez de 404 para quem está fora do fluxo (a tela
pergunta isso para **todo** contato aberto, e a maioria não está no fluxo).

**`POST /assumir`** — dois savepoints: o carimbo (`assumido_por` + `assumido_em`), que é o que
para o relógio, e depois o cancelamento do `sla_check`. Cancelamento falhando **não** custa o
carimbo: o handler relê o estado e vê `assumido_por` preenchido. O cancelamento é a via limpa;
a verificação no handler é a rede.

**Idempotente:** `assumido_por` já preenchido devolve 200 com `ja_assumido: true` e **não
sobrescreve**. Sobrescrever seria pior que um erro — apagaria quem pegou o lead primeiro, que é
o dado que a escada usa. Cobre dois SDRs clicando quase juntos: o segundo **vê quem ficou com o
lead** em vez de tomá-lo.

**Frontend:** botão âmbar `PhoneCall` "Assumir ligação" quando `pode_assumir`; selo verde
`CheckCircle2` com **nome e hora** depois de assumido; nada fora do fluxo. O POST usa a
**resposta** para atualizar o estado em vez de um segundo GET, para o botão não piscar. Polling
de 15s (o passo do `NotificationBell`), porque o estado muda por fora da tela.

`npm ci && npm run build` limpo: compilado em 20.4s, TypeScript OK, 16/16 páginas, zero warning.

⚠️ **O `npm run build` sobrescreveu o `.next` por baixo do `cenat-frontend.service`**, que roda
`next start -p 3001`. Verificado depois: `GET /` e `GET /conversations` → 200, chunk servido →
200, nada quebrado (os chunks do Next 16 têm nome por hash de conteúdo e são lidos do disco por
requisição). O código novo ficou **inerte** porque o backend ainda não havia sido reiniciado —
`GET /api/nat/{wa_id}/estado` devolvia 404 e o `catch` silencioso deixava `natEstado = null`.

## 8. Testes

`backend/test_nat_sprint3.py` — **91 verificações, todas verdes. Nada enviado, nada gravado,
nenhuma conexão de banco.** Confirmado depois de rodar: `nat_scheduled_actions=0`,
`messages=26767`, `notifications=2803`, `nat_flow_state=0`.

`aiosqlite` não está no venv e instalar pacote no venv de produção não estava autorizado, então
segui o padrão da casa (os quatro suites existentes usam `MagicMock`). Isso implica uma divisão
de trabalho declarada no docstring do arquivo, para não fingir cobertura:

* **semântica de banco** (SKIP LOCKED com sessões concorrentes, índice parcial) → só o Postgres
  responde, e foi provada no smoke da Fase 3 contra o banco real. Um dublê que "confirmasse"
  SKIP LOCKED estaria confirmando a si mesmo.
* **lógica** → `_executar_acao`, `processar_pendentes`, `transferir_para_sdr`, `sla_check`,
  `assumir_ligacao` e `send_nat_message` **rodam de fato**. Só `_proxima_acao` e `_finalizar`
  são substituídos, por uma fila em memória.

O `SavepointFalso` **desfaz de verdade** o que foi adicionado dentro dele — sem isso, o teste 6
("a notificação sobreviveu") passaria mesmo num código que a perdesse.

| # | teste | checks |
|---|---|---|
| 1 | `agendar` cria pendente; job executa e marca `executado` | 5 |
| 2 | job roda 2x → executa **1x** | 2 |
| 3 | falha 3x → `falhou`, sem loop; 1 passada = 1 tentativa | 5 |
| 4 | `cancelar` só mexe em `pendente`, filtra kind **e** contato; 0 não é erro | 5 |
| 5 | transferência completa: notificação + carimbo + timeline(5s) + SLA +2min | 12 |
| 6 | **Exact falha → notificação sobrevive**; e o inverso (SLA falha → sobrevive) | 7 |
| 7 | `sla_check` já assumido → nada (+ etapa diferente, + sem estado) | 5 |
| 8 | nível 0 → outro SDR e reagenda; sem SDR dono → **ambos os SDRs**, nível 2, sem reagendar | 15 |
| 9 | nível 1 → gestão, **não** reagenda | 6 |
| 10 | nível 2 → nada | 3 |
| 11 | `assumir` cancela o SLA; falha no cancelamento preserva o carimbo | 7 |
| 12 | `assumir` 2x → não sobrescreve quem assumiu primeiro | 5 |
| 13 | teto conta só `nat_etapa IS NOT NULL`; manual e massa ficam NULL | 11 |
| 14 | `sdr_user_id` nulo → gestão, título "SEM SDR" | 5 |

**Regressão:** `test_nat_flow` 13/13 · `test_nat_guard` 9/9 · `test_welcome_guardrail` 15/15 ·
`test_parse_datetime` ✅

O caso 8 de `test_nat_flow` foi ajustado: `db = MagicMock()` não suporta `async with`, então
`begin_nested()` estourava. Artefato do dublê, não bug — em produção `db` é `AsyncSession` e
savepoint aninhado é suportado (`main.py` já abre um antes de chamar `processar_texto`). O caso
agora dubla `transferir_para_sdr` e verifica que a **resposta do lead e o `wa_message_id`
chegam** nela.

---

## Achado fora de escopo, mas urgente: 54 leads carimbados `sent` que não receberam nada

Levantado ao responder à pergunta sobre desligar a automação, e registrado aqui porque não é
desta sprint e não pode se perder.

Com `enabled=false`, o lead novo de funil de pós é carimbado `welcome_status='skipped'` +
`welcome_error='automação desligada — lead anterior à ativação'`. **Não** fica NULL. Não é
recuperável automaticamente **nunca** — o guarda de idempotência testa `welcome_status is not
None`, e o carimbo sobrevive aos syncs (o `setattr` cego só cobre as 10 chaves de `lead_data`).
Única porta: `POST /api/exact-leads/{exact_id}/resend-welcome`, autenticado, **um lead por
chamada** — e ela **exige `enabled=true`**, então a ordem é: quitar a fatura → religar →
reenviar um por um. Volume: ~12 leads de pós/dia.

**Deixar ligado é pior que desligar.** A Meta **aceita** o envio (200 com `messages[0].id`) e só
falha na entrega depois, via webhook — e o carimbo `sent` acontece na aceitação:

| dia | templates | status real |
|---|---|---|
| 24/07 | 199 | 166 sent / **33 failed** |
| 25/07 | 9 | **9 failed (100%)** |
| 26/07 | 1 | **1 failed (100%)** |

Cruzando `exact_leads` carimbados `sent` desde 23/07 com o status real da mensagem:
**54 leads estão marcados `welcome_status='sent'` e a mensagem falhou — 100%, zero entregue.**
Esses 54 carregam uma mentira: ninguém vai saber que precisa reenviar. `'skipped'` +
`'automação desligada'` é marcador honesto e greppável; `'sent'` é falso.

Passivo separado desta sprint. Candidato a anexo em `ERRO_META_131042_20260726.md`.

---

## Fora de escopo (não feito, de propósito)

Bloco 6 (botão "não consegui contato", `nat_recuperacao_sdr`, retry de 10 min) · Bloco 8 (IA) ·
Bloco 9 (dashboard) · `welcome_status` + alerta de falha de entrega · autenticação em
`/bulk-send-template` e `/send/*` · recuperação dos ~463 leads · Cenário 2 e follow-up ·
estágio no Exact (ver Fase 1).

## Estado final

- `nat_config`: `nat_enabled=false`, `nat_start_at=NULL`, `max_envios_hora=20`
- `auto_welcome_config`: **intacta** pela sprint — `channel_id=1`, `template=nat_boasvindas`,
  `funis=18535,18537,25588`. O `enabled=false` foi decisão do Álefe por causa da fatura da Meta,
  não desta sprint.
- `nat_scheduled_actions=0`, `nat_flow_state=0`, `nat_button_events=0`
- **Nenhuma mensagem de WhatsApp enviada. Nenhum sync do Exact rodado à mão.**
- Merge em `main` e restart feitos em 26/07 com aprovação explícita do Álefe, fora do plano
  original. Smoke pós-restart: 5 jobs no ar, inbound ponta a ponta (com limpeza), rotas novas
  respondendo, sync do ciclo seguinte com `new: 0, sent: 0, failed: 0`.
