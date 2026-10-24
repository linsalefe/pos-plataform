# SPRINT: itens 3 e 4 dos pedidos do comercial (24/10/2026)

Base: `RECON_4_PEDIDOS_COMERCIAL_20261024_REPORT.md` §3 e §4. Duas branches, nesta ordem: `feat/custom-fields-spotter` (A) e `feat/papel-usuarios-vagas` (B). As duas estão no ar e na `main`.

---

## PARTE A: campos personalizados no `LeadsAdd`

**Resultado:** no ar desde 24/10 às 16:02 SP (merge `0489db8`). Todo lead criado pela LP (`POST /agendar` sem `leadId` e `POST /lead`) passa a levar `_possuigraduacao` e `_investimentoposgraduacaoonline` nos campos personalizados da Exact. O `description` continua idêntico.

### A1. Teste controlado (24/10, lead `zz`, apagado na mesma sessão)

Payload válido, por id de opção:
```
POST /LeadsAdd {"duplicityValidation": false, "lead": {"name": "zz teste customfields 20261024 valido",
  "source": "Landing Page", "subSource": "PosMulheridades", "funnelId": 18535, "ddiPhone": "55",
  "phone": "11999998888", "description": "teste",
  "customFields": [{"id": "_possuigraduacao", "options": [{"id": 136999}]},
                   {"id": "_investimentoposgraduacaoonline", "options": [{"id": 137003}]}]}}
  -> HTTP 201 {"value": 53204414}
GET /CustomFieldsLeads?$filter=leadId eq 53204414   (na 1ª leitura, 10 s depois)
  -> 200 [{"key": "_possuigraduacao", "options": [{"id": 136999, "value": "Sim"}]},
          {"key": "_investimentoposgraduacaoonline", "options": [{"id": 137003, "value": "De R$100,00 a R$200,00"}]}]
DELETE /LeadsDelete/53204414  -> 204
GET /CustomFieldsLeads?$filter=leadId eq 53204414  -> 200 {"value": []}
GET /Leads?$filter=id eq 53204414                  -> 200 {"value": []}
```

Opção inválida:
```
POST /LeadsAdd ... "customFields": [{"id": "_possuigraduacao", "options": [{"id": 999999}]}]
  -> HTTP 400 {"error": {"message": "Custom field '_possuigraduacao': Option(s) 999999 not found"}}
```
**A Exact recusa o lead inteiro**, não só o campo. Por isso:
1. só vai para a Exact o valor que casa com uma opção conhecida;
2. `criar_lead` repete sem os campos se a Exact recusar com 4xx mesmo assim.

### A2. Código

| arquivo | mudança |
|---|---|
| `backend/custom_fields.json` (novo) | de/para `chave da LP -> key da Exact -> tipo -> {opção: id}`. Só os 2 campos |
| `backend/app/agendamento/extras.py` | `montar_custom_fields(extras)`: casa chave e valor normalizados (sem acento, caixa ou espaço sobrando) e devolve `[{"id": key, "options": [{"id": n}]}]`. Valor fora das opções sai com log, sem derrubar nada |
| `backend/app/agendamento/client.py` | `criar_lead(..., custom_fields=)`. Se a Exact responder 4xx com campos, repete sem eles e loga `❌ custom_fields`. Rede ou 5xx **não** repete, porque o lead pode ter sido gravado |
| `backend/app/agendamento/agendar.py` | as duas chamadas de `criar_lead` passam `custom_fields` |
| `backend/test_custom_fields.py` (novo) | 8 casos, **escritos e não executados** |

### A3. Prova pelo código de produção, depois do deploy

**Desvio:** o brief pedia aplicar pela LP com o número do Álefe. Esse número está travado pela reunião de teste 4789469 até 27/10 às 18:00 (sprint da trava), então a aplicação não criaria lead. No lugar, chamei o código de produção direto (`montar_custom_fields` e `criar_lead`) com um lead `zz`, sem passar pela rota. Assim nada foi para a fila do RD e o agente não abriu conversa com o número de teste.
```
customFields montados: [{'id': '_possuigraduacao', 'options': [{'id': 136999}]},
                        {'id': '_investimentoposgraduacaoonline', 'options': [{'id': 137003}]}]
lead 53204483
CustomFieldsLeads: [('_possuigraduacao', ['Sim']), ('_investimentoposgraduacaoonline', ['De R$100,00 a R$200,00'])]
description: 'E-mail: zz@example.com | Profissão: Teste | Ensino Superior: Sim | Faixa de investimento: De R$100,00 a R$200,00'
LeadsDelete 204 · relido: []
```
**Pendente:** conferir o primeiro lead real da LP depois de 24/10 16:02 SP. Até o fechamento, nenhum lead novo tinha entrado (sábado).
```sql
SELECT id, created_at, lead_id FROM agendamentos
WHERE created_at > '2026-10-24 16:05' AND lead_externo = false AND lead_id IS NOT NULL;
-- e para cada lead_id: GET /CustomFieldsLeads?$filter=leadId eq <lead_id>
```

---

## PARTE B: papel, tag de vagas, filtro por papel, limpeza da conta 3

**Resultado:** migração aplicada em 24/10 às 16:08 SP, código no ar às 16:14 SP, merge na `main`.

### B1. Migração (`migrate_papel_usuarios.py --aplicar`)

DDL: `ALTER TABLE users ADD COLUMN IF NOT EXISTS papel VARCHAR(20) NOT NULL DEFAULT 'outro'`. O script roda em ensaio por padrão (transação com ROLLBACK). O ensaio foi rodado antes do checkpoint, e depois dele não sobrou nem coluna nem tag.

| | resultado |
|---|---|
| papéis | 1 Álefe e 2 Isa `gestao` · **5 Thobias `sdr`** · **6 Victória `consultora`** · 3, 4, 7 e 8 `outro` |
| conta 3 "Vi Amorim" | `is_active=false` (o login recusa com "Usuário inativo") |
| contatos `assigned_to=3 -> 5` | **564** (depois: 0 com a conta 3) |
| notificações não lidas `3 -> 5` | **767**, todas, como o brief pede. Só 45 eram dos últimos 7 dias, e o Thobias já tinha 4.354 não lidas |
| tag `Vagas afirmativas` (id 3, roxa) | criada e aplicada a **177** contatos (todo `template_name ILIKE '%vagasafirmativas%'` desde 01/09) |

### B2. Pontos que passaram a ler `users.papel`

Os pontos abaixo agora leem `app/usuarios.py` (`sdr_ids(db)`: usuários ativos com `papel='sdr'`). Se a consulta voltar vazia ou falhar, a reserva é o `SDR_USER_IDS` do `.env` e, sem ele, o Thobias (5), sempre com aviso no log.

| ponto | antes | agora |
|---|---|---|
| `remarcacao.destinatarios` (sem dono) | `SDR_USER_IDS` do `.env` | `sdr_ids(db)` + gestão |
| `confirmacao._notificar` (confirmação e no-show) | idem, via `remarcacao.destinatarios` | idem |
| `qualificacao_fluxo._notificar` (avisos do agente) | idem, via `remarcacao.destinatarios` | idem |
| `nat_guard` (gate 4, SDR atribuído) | `SDR_IDS_PERMITIDOS = {4, 5}` | `sdr_ids(db)` |
| `nat_sla` (escalonamento) | `SDR_IDS_PERMITIDOS` | `sdr_ids(db)` |

**Ficaram como estavam, de propósito:**
- `aviso_sdr.py` avisa por WhatsApp a partir de **telefones** (`SDR_AVISO_TELEFONES`), não de usuários.
- `main.py:826` notifica o **dono** do contato, sem lista de SDR.

**Efeito no NAT:** o guard e o SLA passam a reconhecer só o Thobias; antes valiam a Valéria e o Thobias. Hoje não muda nada, porque o NAT está desligado (`nat_enabled=false`). Se ele for religado, os 16 contatos ativos da Valéria deixam de ser elegíveis.

### B3. Tag no envio

`app/tags_auto.py:marcar_vagas` grava num savepoint e nunca levanta. É chamada:
- no disparo em lote (`exact_routes.bulk_send_template`, depois do flush da mensagem);
- no envio individual de template (`routes.py`, `/send/template`).

### B4. Filtro padrão da tela de conversas

O `GET /contacts` passou a devolver `last_sent_by`, que é o autor da última mensagem. A regra mora em `frontend/src/app/conversations/page.tsx` (`passaNoPapel`):
- **sdr:** esconde o contato com a tag de vagas quando a última mensagem é outbound de um usuário `consultora` (a rajada de follows). Quem respondeu continua visível.
- **consultora:** mostra os contatos com a tag de vagas **ou** com `assigned_to` igual a ela.
- **gestao/outro:** tudo.
- Botão **"Ver tudo"** para o sdr e a consultora, guardado no `localStorage`. O filtro manual de SDR continua existindo. Nenhuma mudança de `role` nem de `WHERE` no backend.

Tela de usuários: o papel aparece ao lado da função e é editável na criação e na edição. `/auth/login`, `/auth/me`, `/auth/users` e `PATCH /auth/users/{id}` levam `papel`; papel inválido dá 400.

### B5. Checkpoint 2: filtro reproduzido sobre a lista real

**Desvio:** sem navegador e sem as senhas, não houve print. A regra foi aplicada em Python sobre o retorno real de `list_contacts`, só em leitura.

| | vê | nos últimos 7 dias |
|---|---|---|
| Thobias (sdr) | 6.239 de 6.374 | 233 de 297, com **64 escondidos** |
| Victória (consultora) | 1.717 de 6.374 | 96 de 297 |

- Thobias: das 90 conversas de vagas com movimento em 7 dias, os 64 escondidos são a rajada sem resposta. As 6 que responderam continuam visíveis, e as 20 em que a última mensagem foi do Thobias ou do agente também.
- Victória: os 177 contatos de vagas mais os que já eram dela. O sync da Exact atribui a ela os leads em que ela é a SDR na Exact (`sdr_mapping`).

### B6. Deploy
- `npx tsc --noEmit` passou e `npm run build` passou.
- `import app.main` passa.
- Backend e frontend reiniciados.
- `/conversations` e `/users` respondem 200.
- `/auth/me` (Álefe) devolve `"papel": "gestao"`.
- `GET /contacts` devolve 6.374 contatos, 177 com a tag, e a chave `last_sent_by` está presente.

`backend/test_papel_usuarios.py`: 9 casos, **escritos e não executados**.

---

## Para a Isa

- **O SDR pode parar de preencher graduação e faixa de investimento à mão** nos leads da LP: os campos já chegam preenchidos. A pergunta "R$272 mensal seria possível? Sim/Não" continua só no `description` até decidirem o campo.
- **A Victória (conta `comercialcenat@gmail.com`) vê por padrão só vagas afirmativas e os contatos dela.** O Thobias deixa de ver a rajada de follows que ninguém respondeu, mas vê quem respondeu. Os dois têm o botão "Ver tudo".
- **A conta "Vi Amorim" (`processoseletivo@cenatsaudemental.com`) foi desativada.** Os 564 contatos e as notificações pendentes dela foram para o Thobias.
- O papel de cada pessoa pode ser trocado na tela de Usuários, sem código.

## Pendências
- Conferir os campos no primeiro lead real da LP (A3).
- Observações do brief que ficam para depois: campo "Investimento R$272", `LeadsUpdate` para o caminho do agente e backfill dos 321 leads, `Canal Pós graduação`, troca de dono para a consultora, bloqueio por `role`.
