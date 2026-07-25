# Auditoria — Fluxo IA "NAT" (Processo Comercial Pós-Graduação 2026)

Auditoria somente-leitura. Nenhum arquivo de código foi alterado, criado ou deletado.
Data: 2026-07-25. HEAD do repo no momento: `9692952 fix(welcome): exige login no resend-welcome e no botão + resend respeita o enabled`.

**Achado mais importante logo de cara**: o lado "Meta" está muito mais pronto que o lado "código". Os 6 templates nomeados `nat_*` já existem **aprovados** no WABA (incluindo botões), mas quase nenhuma lógica de orquestração (horário comercial, roteamento por botão, recuperação, follow-up) existe no backend. Ou seja, o trabalho que falta é quase 100% no backend/CRM, não em criar/aprovar templates.

---

## Parte 1 — Tabela de status (requisitos do fluxo NAT)

| # | Requisito | Status | Evidência (arquivo:linha) | O que falta |
|---|---|---|---|---|
| 1.1a | Boas-vindas em horário comercial (09h-19h) | **PARCIAL** | `backend/app/exact_spotter.py:139-306` (`send_welcome_to_new_lead`) dispara 1 mensagem sempre que o lead entra no funil configurado, **a qualquer hora do dia** | Nenhuma condição de horário. Template usado é dinâmico (`config.template_name`, tela admin), na prática `nat_boasvindas` |
| 1.1b | Mensagem "fora de horário" | **NÃO EXISTE** | — (grep amplo por `business_hour`/`fora_de_horario`/`sla` em `app/` → zero) | Tudo: lógica de janela + disparo |
| 1.1c | Reativação 09h do dia seguinte | **NÃO EXISTE** | Jobs existentes (`main.py:31,42,54,103`) não fazem isso | Lógica de agendamento + orquestração. Template `nat_reativacao_09h` já existe aprovado na Meta |
| 1.1d | Confirmação "sim, posso falar" (clique de botão) | **NÃO EXISTE** | Webhook não trata `button`/`interactive` (`main.py:256-275`) | Tudo: parsing do clique + roteamento. Template `nat_sim` existe aprovado |
| 1.1e | Confirmação de transferência (resposta a pergunta aberta) | **NÃO EXISTE** | Agente de IA que responderia está **desativado**: bloco comentado em `main.py:314-395` ("AGENTE IA: DESATIVADO TEMPORARIAMENTE") | Reativar/reescrever lógica de IA + lógica de transferência. Template `nat_confirma_transferencia` existe aprovado |
| 1.1f | Recuperação pós-tentativa (SDR não conseguiu) | **NÃO EXISTE** | Sem campo de tentativa em `Contact`/`AIConversationSummary` (`models.py:30-44,170-186`); `call_logs` não suporta registro manual (ver 1.7) | Tudo. Template `nat_recuperacao_sdr` existe aprovado |
| 1.1g | "Prefiro outro horário" (botão de adiamento) | **NÃO EXISTE** | Mesma causa raiz de 1.1d (sem tratamento de botão) | Tudo. Template `nat_outro_horario` existe aprovado |
| 1.2a | Botões no envio (`send_template_message`) | **PARCIAL** | `backend/app/whatsapp.py:25-53` monta **só** `components: [{type: "body", ...}]`. Nenhuma função no arquivo envia `type: "interactive"` | Não precisa mudar nada para enviar botão de **template** (o botão já vem aprovado dentro do template, a Meta o renderiza sozinha) — só precisa tratar a **resposta** do clique |
| 1.2b | Webhook trata `button`/`interactive` | **NÃO EXISTE** | `backend/app/main.py:256-275`: só trata `text, image, audio, video, document, sticker`. Se chega `button`/`interactive`, `content` fica `""` (linha 257) mas a `Message` **é salva mesmo assim** com `message_type` genérico — não há exceção, mas o `id`/`payload` do botão clicado nunca é lido | Adicionar `elif msg_type in ("button","interactive")` extraindo `msg["button"]["text"]` ou `msg["interactive"]["button_reply"]["id"]` |
| 1.3 | Janela de horário comercial (09h-19h) | **NÃO EXISTE** | `SP_TZ` existe (`main.py:18`, offset fixo `-3h` sem DST) mas é usado **só para timestamps** (`main.py:63,284`; `exact_spotter.py:266,276,295`; `exact_routes.py:261,382`; `routes.py:12,221,266,324,864,867`) — nenhum `hour>=9 and hour<19` em lugar nenhum | Toda a lógica de comparação de janela |
| 1.4a | Status/etapa em `ai_conversation_summaries` | **PARCIAL** | Só 3 valores possíveis: `em_atendimento_ia` (default, `models.py:176`; criado em `exact_spotter.py:287`), `aguardando_humano`, `finalizado` (ambos só via `kanban_routes.py:118-133` ou `ai_routes.py:104-113`). **No banco real, 100% dos 253 registros estão em `em_atendimento_ia`** — nunca houve transição manual | Nenhum estado granular de fluxo NAT existe |
| 1.4b | Campo "etapa do fluxo NAT" | **NÃO EXISTE** | `models.py:170-186` e schema real da tabela não têm esse campo | Migração: nova coluna |
| 1.4c | Contador de tentativas de contato | **NÃO EXISTE** | Nem em `ai_conversation_summaries` nem em `Contact` (`models.py:30-44`); `call_logs` (`models.py:190-216`) registra ligações individuais mas sem contador agregado por lead | Migração: nova coluna/tabela |
| 1.4d | Horário preferencial do lead | **NÃO EXISTE** | Idem acima | Migração: nova coluna |
| 1.4e | Formação acadêmica do lead | **NÃO EXISTE** (no schema local) | `lead_course` (`models.py:179`) é **curso de interesse**, não formação prévia — confirmado em `ai_engine.py:227`, `google_calendar.py:158` | Ver Parte 2.3 — dado existe só como texto livre na Exact |
| 1.4f | Colunas renderizadas pelo Kanban | **EXISTE** | `frontend/src/app/kanban/page.tsx:12-24` (interface `KanbanCard`) espelha exatamente o que `kanban_routes.py:47-62` devolve: `lead_name, lead_course, summary, ai_messages_count, human_took_over, started_at`. 3 colunas fixas hardcoded (linhas 38-75) | Nenhum campo de etapa NAT/tentativa/horário/formação é exibido (porque não existem no backend) |
| 1.5a | Notificação ao SDR | **EXISTE** | Modelo `Notification` (`models.py:229-240`); criada em nova mensagem inbound (`main.py:288-299`) e no `window_alerts_job` (`main.py:54-100`, a cada 5 min, thresholds 1h/3h/5h/20h de janela de 24h do WhatsApp) | É só polling — ver abaixo |
| 1.5b | WebSocket / SSE | **NÃO EXISTE** | Grep em `backend/` e `frontend/` por `websocket`/`WebSocket`/`EventSource`/`sse` → zero ocorrências | Tudo — hoje é 100% HTTP polling: `NotificationBell.tsx:108` (15s), Kanban `page.tsx:97-102` (10s) |
| 1.5c | SLA / timer / escalonamento automático | **NÃO EXISTE** | Único mecanismo temporal é `window_alerts_job` (`main.py:54-100`), que só **notifica o mesmo SDR já atribuído** — nunca reatribui, nunca muda `status` | Tudo |
| 1.5d | Roles de usuário | **PARCIAL** | Código só distingue `admin` (`auth.py:64-65`, `auth_routes.py:64,92,119,140`) de tudo o resto. Banco real: `admin`=7, `atendente`=1. **Não existe role "sdr"** | Se o roteamento/escalonamento do NAT depender de role "SDR" distinta de "atendente", precisa ser criada |
| 1.6a | Jobs em background (`main.py` lifespan) | **EXISTE** | 4 jobs: `sync_job` (`:31`, 10min), `cleanup_recordings_job` (`:42`, 24h), `window_alerts_job` (`:54`, 5min), `scheduled_messages_job` (`:103`, 60s). Criados no `lifespan` (`:154-157`) | — |
| 1.6b | Idempotência sob múltiplos workers | **NÃO EXISTE proteção** | Zero locks no projeto (`grep advisory_lock\|FOR UPDATE\|flock` → nada). Deploy atual roda com 1 worker só (`/etc/systemd/system/cenat-backend.service:8`, sem `--workers`), então hoje não é um problema — mas o código não teria proteção se isso mudasse | `scheduled_messages_job` (`main.py:113-121`) é o mais crítico: sem `SELECT...FOR UPDATE SKIP LOCKED`, dispararia duplicado com N workers |
| 1.6c | `scheduled_messages` como base para retry 10min / reativação 09h | **PARCIAL** | Modelo em `models.py:243-259`. Mecanismo de tempo (`scheduled_at` + job 60s) funciona bem — é o único job do repo que compara contra timestamp de banco, não `datetime.now().hour` | Schema 100% acoplado a "enviar template para lista de leads" (`template_name`/`lead_ids` `NOT NULL`). Sem campo `kind`/tipo de ação, sem vínculo a evento de origem, sem contador de tentativas/retry |
| 1.7 | Registro de tentativa de ligação manual | **NÃO EXISTE** | `call_logs` (21 colunas, 1929 registros) só é escrito por webhooks do Twilio (`twilio_routes.py:142-274`). `call_sid` é `unique=True, nullable=False` (`models.py:194`) — **impossível inserir uma tentativa manual sem inventar um `call_sid` sintético** | Endpoint dedicado + botão no frontend (`calls/page.tsx` só lista/transcreve/apaga, sem ação manual) |

---

## Parte 2 — Dados extraídos

### 2.1 Estágios reais do Exact Spotter

Total: **8.660 leads** em `exact_leads`. `POS_FUNNEL_IDS` (`exact_spotter.py:22`) = `{18535, 18537, 25588}` (default hardcoded; env var `POS_FUNNEL_IDS` **não está setada** no `.env`, então o default vale). Nomes de funil confirmados via `GET /Funnels` real na API do Exact:

| funnel_id | Nome do funil (API) | É pós? | Leads no funil |
|---|---|---|---|
| 18285 | Intercambio | não | 2.451 |
| **18535** | **Pos Graduacao** | **sim** | **3.592** |
| **18537** | **Pós Graduação - Vendas** | **sim** | **1.488** |
| 20647 | Reativação - SQL | não | 105 |
| 20776 | CONGRESSO PRESENCIAL | não | 97 |
| 21007 | Vagas Afirmativas | não | 844 |
| **25588** | **Funil - Isa** | **sim** | **84** |

**Total pós-graduação: 5.164 leads** (3.592+1.488+84), consistente com a auditoria anterior (memória `auditoria-boas-vindas-pendente`, que registrava 5.076 há 13 dias — o número cresceu ~88 leads no período, dentro do esperado).

Principais estágios por funil pós (destaque): `Descartado` domina em todos (3.442 em 18535, 369 em 18537, 5 em 25588) — é um status de perda gravado à parte, **não** é um `stage` formal retornado pelo endpoint `/Stages` da Exact. Em 18537, `Vendidos` = 1.094 (maior estágio de conversão do repo). Vários nomes de stage têm espaço em branco na frente no banco (ex.: `" Follows 7"`, `" Em Negociação"` em 25588) — literal, não erro de transcrição.

### 2.2 Templates aprovados na Meta (canal único: id=1, "Pós-Graduação (SDR)", waba_id `1360246076143727`)

Só existe **1 canal cadastrado, e está ativo**. 53 templates no total, **todos `APPROVED`** (51 `MARKETING`, 2 `UTILITY`).

**Templates NAT (6, todos `pt_BR`/`MARKETING`/`APPROVED`):**

| Nome | Variáveis | Botões (tipo / texto / tamanho) |
|---|---|---|
| `nat_boasvindas` | {{1}} nome, {{2}} curso | QUICK_REPLY "Sim, Posso conversar agora" (**26 car.**) / QUICK_REPLY "Prefiro outro horário" (**21 car.**) |
| `nat_sim` | {{1}}, {{2}}, {{3}} | — |
| `nat_confirma_transferencia` | {{1}} | — |
| `nat_outro_horario` | (nenhuma) | — |
| `nat_reativacao_09h` | {{1}}, {{2}} | QUICK_REPLY "Sim, posso falar agora" (**22 car.**) / QUICK_REPLY "Prefiro outro horário" (**21 car.**) |
| `nat_recuperacao_sdr` | {{1}}, {{2}} | QUICK_REPLY "Tentar novamente agora" (**22 car.**) / QUICK_REPLY "Agendar outro horário" (**21 car.**) |

**⚠️ Todos os 6 botões QUICK_REPLY do fluxo NAT excedem o limite documentado de 20 caracteres da Meta** (de +1 a +6 caracteres) — e mesmo assim estão `APPROVED`. Vale confirmar manualmente no WhatsApp Manager se a regra mudou ou se há tolerância; o dado bruto da API é: aprovados, com esses textos exatos.

Restam 15 templates de **follow-up** (`follow1_vagasafirmativas_apresentacao`, `follow5_gestao`, `mensagem_follow3` etc.) e 32 templates diversos (`agendamento`, `reagendamento_1..4`, `sdr_tentativa_ligacao`, `hello_world` de teste, etc.) — nenhum com botão fora do padrão de 20/25 caracteres, exceto os 3 CTAs de URL já dentro do limite de 25.

### 2.3 Formação acadêmica do lead

- `GET /api/exact-leads/{exact_id}/details` (`exact_routes.py:118-183`) devolve `lead` (sem campo de formação estruturado), `persons` (`jobTitle`, sem formação) e `qualifications`.
- Chamada real à API do Exact para 5 leads de pós: campos de `Lead`/`Persons` não têm nenhuma chave `education`/`graduation`/`escolaridade`.
- **Achado**: em amostra de 1000 leads, o campo `description` (texto livre), quando preenchido (514/1000 = 51,4%), contém rótulos digitados manualmente pelo SDR: `Nível de escolaridade:` (186×), `Possui graduação:` (264×), `Profissão:` (233×), etc. **Não é campo estruturado** — é parsing de texto livre no formato `"Rótulo:\nValor\n\n"`.
- Conclusão: o dado existe, mas só via regex sobre `description`, e só para ~51% dos leads (os que já passaram por qualificação do SDR — leads recém-chegados, que é justamente o momento em que o NAT atuaria, tendem a ter `description=null`).

### 2.4 SDRs — `sdr_mapping.py` vs banco

`backend/app/sdr_mapping.py` (17 linhas) mapeia 6 nomes → 6 ids: `Victória→6, Valéria→4, Thobias→5, Isabela→2, Marina→7, Ana→8`.

Banco (`SELECT id, name, role, is_active FROM users`): 8 usuários ativos, roles só `admin`(7)/`atendente`(1). **Não existe role "sdr"**.

Divergências:
- `Isabela`(dicionário) vs `Isa`(banco, id=2) — discrepância proposital e já comentada no código (`# Isa no Hub`), não é bug.
- `id=1 (Álefe Lins)`, `id=3 (Vi Amorim)` — ativos no banco, **fora do dicionário**. `Vi Amorim` (id=3) tem **482 contatos atribuídos** (`assigned_to=3`) — é usado de fato no Hub, mas nunca recebe atribuição automática vinda do Exact via `resolve_sdr_user_id`.

---

## Parte 3 — Gaps por criticidade

| # | Gap | Esforço | Depende de |
|---|---|---|---|
| 1 | Webhook não trata `button`/`interactive` — sem isso, **nenhum** dos 4 estágios de resposta do lead (sim/outro horário/transferência/recuperação) pode funcionar | **M** | — (bloqueador de tudo abaixo) |
| 2 | Nenhuma lógica de janela 09h-19h (nem para decidir template nem para decidir se reativa às 09h) | **M** | — |
| 3 | Agente de IA está desativado (`main.py:314-395`) — sem ele, não há como interpretar resposta aberta de "motivação" para a etapa de transferência | **G** | #1 |
| 4 | `ai_conversation_summaries` não tem etapa de fluxo, contador de tentativa, horário preferencial — precisa de migração de schema | **M** | — |
| 5 | `call_logs.call_sid` é `UNIQUE NOT NULL` — impede registro manual de tentativa de ligação sem gambiarra | **P/M** | decisão: nova tabela vs relaxar constraint |
| 6 | `scheduled_messages` só dispara `bulk_send_template` — sem campo de tipo/ação genérica nem contador de retry, não serve puro para "retry de 10min" de um evento arbitrário | **M** | #4 (se retry for por lead/evento, não por lista de disparo em massa) |
| 7 | Sem SLA/timer/escalonamento — só notifica o mesmo SDR, nunca reatribui | **G** | #4, decisão de regra de negócio (quem reatribui, depois de quanto tempo) |
| 8 | Jobs sem lock — hoje não é problema (1 worker), mas se o fluxo NAT crescer e alguém escalar para `--workers N`, `scheduled_messages_job` duplicaria disparos | **P** (adicionar `FOR UPDATE SKIP LOCKED`) | — |
| 9 | Formação acadêmica só via regex em texto livre, presente em ~51% dos leads, e ausente nos leads recém-chegados (justamente quando o NAT atua) | **M** (parsing) | aceitar dado ausente/incompleto como regra de negócio |
| 10 | `sdr_mapping.py` não cobre `Vi Amorim` (id=3, 482 contatos ativos) — se o roteamento do NAT usar esse mapa, esse SDR fica sem receber leads automaticamente | **P** | decisão humana (ver Parte 5) |
| 11 | Botões QUICK_REPLY do NAT excedem 20 caracteres (regra documentada da Meta) apesar de aprovados — risco de comportamento inconsistente entre dispositivos/versões do WhatsApp | **P** (encurtar texto e re-submeter para aprovação, se confirmado que é problema real) | validar com WhatsApp Manager antes |
| 12 | Kanban board não reflete nenhum estado do fluxo NAT (só 3 colunas fixas) e está com 100% dos registros reais travados em `em_atendimento_ia` — sinal de que o board manual pode já estar sendo ignorado na operação | **M** (novo board/colunas) | #4 |

---

## Parte 4 — Riscos e armadilhas

1. **Concorrência em `scheduled_messages_job`** (`main.py:113-121`): sem `SELECT...FOR UPDATE SKIP LOCKED`, se o processo algum dia rodar com `--workers > 1`, o mesmo agendamento pode ser processado 2x e disparar mensagem duplicada para os mesmos leads. Hoje mitigado só porque o deploy roda 1 worker — é uma bomba-relógio de configuração, não de código.
2. **`window_alerts_job` tem race condition parcial**: o `SELECT` de deduplicação (linhas 83-85) não é atômico com o `INSERT` — sob múltiplos workers, poderia duplicar notificações. Mesma mitigação frágil (1 worker).
3. **Job "às 09h" com padrão `while True: sleep; if hour==9`** (se implementado seguindo o padrão ingênuo, que NENHUM job atual usa) não sobrevive a restart do processo sem estado persistido — pode pular o dia inteiro se o restart cair logo após as 09h, ou disparar 2x se o sleep for curto e não houver flag "já rodei hoje". `scheduled_messages_job` já resolve isso corretamente (compara contra `scheduled_at` de uma linha de banco) — usar o mesmo padrão para a reativação de 09h, não o `while True` ingênuo.
4. **Perda silenciosa de dados de clique de botão**: hoje, se um lead clicar em qualquer botão de template (inclusive os NAT, que já estão em produção no WABA), a mensagem chega ao webhook, é salva no banco com `content=""` e tipo genérico — sem erro visível, mas a informação de negócio (qual botão) desaparece. Isso já pode estar acontecendo agora com leads que recebem `nat_boasvindas` hoje via a automação de boas-vindas configurada na tela admin, mesmo sem o fluxo NAT completo existir.
5. **Botões acima do limite de 20 caracteres approved pela Meta**: comportamento não documentado — pode truncar em alguns clientes WhatsApp. Não testado nesta auditoria em dispositivo real.
6. **`call_sid` único/obrigatório**: qualquer tentativa de "encaixar" registro manual de ligação em `call_logs` sem alterar o schema vai exigir gerar um valor sintético de `call_sid`, arriscando colidir com um `call_sid` real do Twilio no futuro (ou exigindo um prefixo namespaced, o que já seria uma decisão de schema, não trivial).
7. **Formação acadêmica ausente exatamente quando mais se precisa dela**: o parsing de `description` só teria dado em ~51% dos leads, e a amostra sugere que são os leads *já qualificados* pelo SDR — ou seja, o NAT (que atua na entrada do lead, antes da qualificação humana) provavelmente não teria esse dado disponível na maioria dos casos reais de uso.
8. **Kanban "morto" na prática**: 100% dos 253 registros reais estão em `em_atendimento_ia` — nenhuma transição manual jamais ocorreu no banco de produção, apesar do código de mover card existir e funcionar. Isso é um sinal de operação, não só de código: pode indicar que os atendentes não usam esse Kanban hoje, o que é relevante para decidir se vale reaproveitar esse board para o fluxo NAT ou desenhar um novo.
9. **Import circular latente** (herdado da auditoria anterior, ainda não reverificado nesta rodada): se `exact_spotter.py` vier a importar de `exact_routes.py` no nível de módulo (e vice-versa), o backend não sobe. Vale atenção ao adicionar novas integrações entre esses dois arquivos.

---

## Parte 5 — Perguntas em aberto (decisão humana necessária)

1. **Mapeamento dos 6 templates `nat_*` para as 7 etapas do fluxo**: encontramos 6 templates nomeados (`nat_boasvindas`, `nat_sim`, `nat_confirma_transferencia`, `nat_outro_horario`, `nat_reativacao_09h`, `nat_recuperacao_sdr`) para 7 etapas do enunciado. Falta confirmar: existe um template dedicado para "fora de horário" (a etapa 1.1b) ou ele reaproveita `nat_boasvindas` ou `nat_sim`? Peço confirmação de qual template serve cada etapa antes de codar o roteamento.
2. **Botões acima de 20 caracteres**: a Meta aprovou mesmo assim — é intencional (talvez a regra real seja diferente do documentado publicamente) ou os templates foram submetidos e aprovados sem essa checagem? Precisa de validação manual no WhatsApp Manager / teste em device real antes de confiar no comportamento.
3. **`Vi Amorim` (id=3, banco)**: tem 482 contatos atribuídos hoje mas está fora de `sdr_mapping.py` e não tem role distinta de SDR. Ele deveria receber leads automaticamente do fluxo NAT? É uma conta operacional diferente do "SDR Victória/Vitória Amorim" já referenciada em `exact_spotter.py:27-28` como bot de timeline (`EXACT_BOT_USER_ID = 415875`)? Preciso de confirmação para não deixar esse SDR sem leads automáticos nem duplicar identidade com o bot.
4. **Registro de tentativa de ligação manual**: dado que `call_logs.call_sid` é `UNIQUE NOT NULL`, prefere-se (a) nova tabela dedicada a tentativas manuais, ou (b) relaxar a constraint em `call_logs` e gerar um `call_sid` sintético (ex.: `manual-{uuid}`)? Isso muda o desenho do endpoint/UI.
5. **Formação acadêmica ausente em ~49% dos leads (e provavelmente na maioria dos leads recém-chegados, que é quando o NAT atua)**: o fluxo deve funcionar com esse campo vazio (mensagem sem menção à formação) ou é bloqueante (NAT não atua até o dado existir)? Isso muda drasticamente o desenho do template/mensagem.
6. **Escalonamento/SLA**: não existe nenhuma regra de negócio hoje sobre "depois de quanto tempo sem resposta o lead deve ser reatribuído a outro SDR, e para quem". Preciso da regra (tempo, critério de escolha do novo SDR, se é automático ou vira só uma notificação de alerta) antes de desenhar o job.
7. **Reaproveitar o Kanban atual ou criar um novo board**: dado que 100% dos registros reais nunca saíram de `em_atendimento_ia`, vale confirmar com quem usa a ferramenta hoje se o board é realmente consultado, antes de investir em novas colunas para o fluxo NAT.
8. **Multi-worker**: o deploy roda hoje 1 worker (`systemd`, sem `--workers`). Há plano de escalar isso? Se sim, os jobs (`scheduled_messages_job` em especial) precisam de lock antes do fluxo NAT ir para produção, para evitar disparo duplicado de mensagens reais a leads.
