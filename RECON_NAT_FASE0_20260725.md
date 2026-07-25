# Recon — Sprint NAT, Fase 0 (Blocos 0 e 1)

Recon **somente-leitura**. Nenhum arquivo de código foi alterado, criado ou deletado. Nenhuma mensagem
foi enviada a lead real. Nenhuma migração foi rodada. O serviço não foi reiniciado. Nenhum sync manual
do Exact foi disparado.

Data: **2026-07-25**. HEAD no momento do recon: `adb9892 docs(nat): auditoria somente-leitura do fluxo de agente NAT`.
Continuação de [`AUDITORIA_NAT_20260725.md`](AUDITORIA_NAT_20260725.md).

> **Correção de contexto:** o briefing da sprint aponta o repo em `/root/pos-plataform`. O caminho real
> no servidor é **`/home/ubuntu/pos-plataform`** (`/root` é inacessível). As referências de linha do
> briefing conferem, com pequeno offset.

**Achado mais importante:** enquanto se planejava capturar o clique de botão, a boas-vindas que gera
esses cliques **parou de ser entregue**. Desde 23/07, **100% dos envios falham na Meta** (53 de 53).
O zero de cliques dos últimos 3 dias não é lead desinteressado — é mensagem que não chega.

---

## 1. A automação de boas-vindas está ligada?

**Sim — ligada, disparando, e falhando na entrega.**

A configuração mora **na tabela** `auto_welcome_config` (linha singleton `id=1`), não em env nem em
constante no código. Modelo em `backend/app/models.py:118-136`; leitura em
`backend/app/exact_spotter.py:40` (`get_auto_welcome_config`); tela admin servida por
`backend/app/auto_welcome_routes.py`.

Valor real em produção:

| campo | valor |
|---|---|
| `enabled` | **`true`** |
| `channel_id` | `1` — Pós-Graduação (SDR), `5511952137432` |
| `template_name` | **`nat_boasvindas`** |
| `template_language` | `pt_BR` |
| `funnel_ids` | `18535,18537,25588` |
| `updated_by_name` | **Isa** |
| `updated_at` | `2026-07-13 22:31:16` |

Carimbo em `exact_leads.welcome_status`: **253 `sent`**, 8.387 `skipped`, 20 nulos.
Primeiro envio real: `2026-07-13 21:15:21`. Último: `2026-07-25 13:52:04`. Ritmo estável de ~20/dia.

Os dois achados da auditoria de 11/07 (canal `2` inexistente, template `mensagens_de_boas_vindas`
inexistente) estão **resolvidos** — a sprint de boas-vindas corrigiu ambos.

---

## 2. 🔴 Incidente aberto — 100% de falha na entrega desde 23/07

Não estava no escopo do recon, apareceu no cruzamento. Status de entrega dos envios de `nat_boasvindas`
(`messages.status`, atualizado pelo webhook de status em `backend/app/main.py:304-312`):

| dia | `read` | `delivered` | `sent` | **`failed`** | total |
|---|---|---|---|---|---|
| 2026-07-17 | 13 | 6 | – | 1 | 20 |
| 2026-07-18 | 15 | 5 | 2 | – | 22 |
| 2026-07-19 | 9 | 7 | 1 | – | 17 |
| 2026-07-20 | 11 | 3 | – | 2 | 16 |
| 2026-07-21 | 15 | 14 | 1 | 2 | 32 |
| 2026-07-22 | 6 | 10 | – | 4 | 20 |
| **2026-07-23** | **0** | **0** | **0** | **22** | 22 |
| **2026-07-24** | **0** | **0** | **0** | **22** | 22 |
| **2026-07-25** | **0** | **0** | **0** | **9** | 9 |

**53 de 53 falharam.** A taxa de falha era ~10% e virou 100% de um dia para o outro, sem deploy no meio
e sem mudança de volume.

O código **não percebe**: `send_welcome_to_new_lead` carimba `welcome_status='sent'` assim que a Meta
devolve um `wamid` (`exact_spotter.py:268-300`). Quem carimba `failed` é o webhook de status, depois —
e esse carimbo não realimenta `exact_leads`. Ou seja, o painel da boas-vindas mostra 253 enviadas com
sucesso enquanto as últimas 53 não chegaram a ninguém.

### O que já foi descartado

| hipótese | verificação | resultado |
|---|---|---|
| WABA suspensa/em revisão | `GET /{waba_id}` | `status=ACTIVE`, `account_review_status=APPROVED`, `business_verification_status=verified` |
| Número com qualidade baixa | `GET /{phone_number_id}` | `quality_rating=**GREEN**`, `status=CONNECTED`, `name_status=APPROVED` |
| Template reprovado/pausado | `GET /{waba_id}/message_templates` | `nat_boasvindas` **`APPROVED`**, com os 2 botões presentes |
| Número de destino malformado | `length(contact_wa_id)` dos que falham | 13 dígitos, mesmo padrão dos que funcionavam |
| Erro/exceção no backend | `journalctl -u cenat-backend` desde 22/07 | nenhum traceback, nenhum `IntegrityError`, nenhum rollback |
| Deploy quebrou algo | `systemctl show -p NRestarts` | `NRestarts=0`, serviço no ar desde 12/07 |
| Campanha em massa que acabou | contagem diária de envios | envio segue constante, ~20/dia, até hoje |

### Por que não dá para confirmar a causa

**O webhook descarta o motivo do erro.** Em `backend/app/main.py:304-312` o loop de `statuses` copia
apenas `status["status"]` para `Message.status`. O array `statuses[].errors[]` — que traz o código e a
mensagem da Meta (`131049`, `131026`, `132015`, etc.) — **nunca é lido nem persistido**.

Hipótese mais provável: limite de mensagens de MARKETING por usuário (as 6 templates `nat_*` são todas
categoria `MARKETING`). Mas é hipótese; sem o código de erro é chute.

**Correção sugerida (fora do escopo desta sprint, aditivo, ~5 linhas):** persistir
`statuses[].errors[0].code` e `.title` numa coluna nova de `messages`. Sem isso não há diagnóstico
possível, nem agora nem no próximo incidente.

---

## 3. Já estamos perdendo clique de botão?

**Sim. 102 cliques perdidos, de 99 contatos distintos, entre `2026-07-13 22:53:01` e `2026-07-22 20:38:38`.**

| métrica | valor |
|---|---|
| linhas `message_type='button'`, `direction='inbound'` | **102** |
| contatos distintos | **99** |
| linhas com `content` vazio ou nulo | **102 / 102 (100%)** |
| linhas `message_type='interactive'` | **0** |
| contatos que clicaram **e** receberam boas-vindas | **99 / 99 (100%)** |

Distribuição diária:

| dia | cliques | dia | cliques |
|---|---|---|---|
| 13/07 | 3 | 19/07 | 10 |
| 14/07 | 11 | 20/07 | 9 |
| 15/07 | 14 | 21/07 | 13 |
| 16/07 | 11 | 22/07 | 8 |
| 17/07 | 12 | **23/07** | **0** |
| 18/07 | 11 | **24/07 e 25/07** | **0** |

Três leituras:

1. **A correlação é total.** Todo clique de botão registrado no sistema é resposta ao `nat_boasvindas` —
   o primeiro clique é de 22:53 do dia 13/07, 22 minutos depois da Isa ligar a automação às 22:31.
2. **A taxa de clique era alta:** ~12 cliques/dia sobre ~20 envios/dia (~60%). Não é volume marginal —
   é a maior parte dos leads respondendo, e 100% dessa informação foi descartada.
3. **O zero desde 23/07 é o incidente da seção 2**, não desinteresse. O volume de inbound de texto no
   mesmo período seguiu normal (26, 15, 11/dia), então o webhook está recebendo — só não chega mais
   template com botão a ninguém. Dos 53 leads que receberam boas-vindas desde 23/07, **2 responderam**.

Ninguém digitou o texto dos botões manualmente: busca no inbound por `posso conversar` / `prefiro outro`
/ `posso falar` retorna 1 ocorrência em 13/07 e ruído esparso de meses anteriores.

### Estado dos templates no WABA

Consulta read-only a `GET /{waba_id}/message_templates` (53 templates no total, 6 com prefixo `nat_`):

| template | status | categoria | botões |
|---|---|---|---|
| `nat_boasvindas` | APPROVED | MARKETING | `QUICK_REPLY` "Sim, Posso conversar agora" · `QUICK_REPLY` "Prefiro outro horário" |
| `nat_reativacao_09h` | APPROVED | MARKETING | `QUICK_REPLY` "Sim, posso falar agora" · `QUICK_REPLY` "Prefiro outro horário" |
| `nat_recuperacao_sdr` | APPROVED | MARKETING | `QUICK_REPLY` "Tentar novamente agora" · `QUICK_REPLY` "Agendar outro horário" |
| `nat_sim` | APPROVED | MARKETING | — |
| `nat_outro_horario` | APPROVED | MARKETING | — |
| `nat_confirma_transferencia` | APPROVED | MARKETING | — |

Todos os 6 botões são `QUICK_REPLY` de **template**, logo chegam no webhook como `type: "button"` —
o que explica as 0 linhas de `interactive` no banco. A definição devolvida pela Meta traz apenas
`{"type": "QUICK_REPLY", "text": "..."}`, **sem campo de payload** — confirma a premissa do briefing de
que o payload precisa ser fixado no momento do envio, não na definição do template.

Nota: **"Prefiro outro horário" é literalmente o mesmo texto em `nat_boasvindas` e em
`nat_reativacao_09h`.** Sem o `context.id` da mensagem original, os dois cliques são indistinguíveis —
exatamente o cenário que o Bloco 1 precisa resolver.

---

## 4. O parser de tipo do webhook

`backend/app/main.py:256-275` (o briefing estimava ~L250-275 — confere).

Trata `text`, `image`, `audio`, `video`, `document`, `sticker`. **Não há `else`.**

Com `type: "button"`, hoje acontece exatamente isto:

1. `content` é inicializado como `""` em `main.py:257` e nenhum `elif` bate — permanece vazio.
2. A `Message` **é salva mesmo assim** (`main.py:277-287`), com `message_type="button"` e `content=""`.
   Não há exceção, não há log, não há alerta. Falha silenciosa.
3. `msg["button"]["payload"]`, `msg["button"]["text"]` e `msg["context"]["id"]` **nunca são lidos**.
4. Efeito colateral: a notificação para o SDR dono do contato (`main.py:288-302`) sai com corpo vazio —
   o SDR recebe "Nova mensagem de Fulano" sem nada dentro, e não tem como saber que houve um clique.

`type: "interactive"` cairia no mesmo buraco. A coluna `messages.message_type` é `String(20)`
(`models.py:57`), então `"interactive"` (11 caracteres) cabe sem migração.

---

## 5. Infra

| item | valor |
|---|---|
| repo | **`/home/ubuntu/pos-plataform`** (não `/root/pos-plataform`) |
| serviço | `cenat-backend.service`, user `ubuntu`, porta 8001 |
| workers | **1** — `uvicorn app.main:app --host 0.0.0.0 --port 8001`, sem `--workers` ✅ |
| deploy | manual: `git pull` + `sudo systemctl restart cenat-backend` (`COMANDOS_UTEIS.md:10-20`) |
| uptime | desde `2026-07-12 14:09:24 UTC`, `NRestarts=0` |
| banco | PostgreSQL 14 local, `cenat_whatsapp` |
| working tree | limpo |

> ⚠️ **O processo em produção é mais velho que o `main`.** O serviço subiu às `14:09:24` de 12/07; o
> commit `9692952` ("fix(welcome): exige login no resend-welcome e no botão") é de `14:15:37` — seis
> minutos depois. **Esse fix não está rodando em produção.** Não foi reiniciado nada; fica registrado.

---

## 6. Dados confirmados para as fases seguintes

**Funis** (contagem em `exact_leads`):

| funil | leads | papel na sprint |
|---|---|---|
| **18535** | **3.591** | **alvo da NAT** |
| 18537 | 1.488 | fora do alvo — o guard tem que bloquear |
| 25588 | 84 | fora do alvo — o guard tem que bloquear |

**Usuários** (`users`): `4 = Valéria`, `5 = Thobias`, `2 = Isa`.

> ⚠️ Os três estão com **`role='admin'`**. Não existe role que distinga SDR de gestor no banco, então a
> verificação nº 4 do `nat_guard` não pode se apoiar em `role` — tem que ser `assigned_to IN (4, 5)`
> literal, como o briefing já determina.

**Teto por hora:** `messages.sent_by_ai` (`Boolean`, `models.py:61`) existe e serve de marcador. A
contagem sai de `direction='outbound' AND timestamp > now() - interval '1 hour'`. Baseline no momento
do recon: 0 outbound na última hora.

**Vínculo lead → SDR:** `Contact.assigned_to` (`models.py:42`, FK para `users.id`), preenchido no envio
da boas-vindas via `resolve_sdr_user_id` (`exact_spotter.py:238-242`, `app/sdr_mapping.py`).

**Corte por data:** `exact_leads.register_date` (`DateTime`, nullable — `models.py:104`). Nullable
importa: `register_date IS NULL` tem que **bloquear**, para a trava falhar fechada.

---

## 7. Decisão pendente antes da Fase 1

A Fase 1 (branch + script de migração) não depende do incidente e pode começar. Mas o incidente muda a
prioridade: **construir o Bloco 1 em cima de um canal que não entrega significa capturar cliques que
não vão acontecer.**

Duas ordens possíveis, a definir com o Álefe:

- **(a)** Seguir o briefing como está — Fase 1 → 5, e tratar o incidente numa sprint separada.
- **(b)** Instrumentar antes o erro da Meta no webhook de status (persistir `statuses[].errors[]`,
  aditivo, ~5 linhas), rodar, descobrir o código de erro real, e só então seguir.

Nada foi decidido nem implementado.
