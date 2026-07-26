# Sprint NAT — Blocos 0 e 1: travas de segurança + captura de clique de botão

**Data:** 26/07/2026
**Branch:** `feat/nat-blocos-0-1-20260725` (sem merge — decisão do Álefe)
**Antecedentes:** `AUDITORIA_NAT_20260725.md`, `RECON_NAT_FASE0_20260725.md`

Duas entregas, nenhuma delas liga nada:

1. **Travas de segurança** — a NAT nasce desligada, com corte por data e teto de disparos.
2. **Captura de clique de botão** — o webhook descartava silenciosamente a resposta de botão.

Não há máquina de estados, roteamento, envio da NAT nem SLA. Isso é Bloco 2+.

---

## 1. O que existe agora no banco

Migração `backend/migrate_nat_config.py` **rodada**. Duas tabelas novas, nenhuma tabela
existente alterada:

| tabela | papel |
|---|---|
| `nat_config` | singleton `id=1`: `nat_enabled`, `nat_start_at`, `max_envios_hora`, `updated_at` |
| `nat_button_events` | captura crua do clique: `contact_wa_id`, `wa_message_id` (UNIQUE), `context_message_id`, `button_payload`, `button_text`, `source`, `created_at` (+2 índices) |

Estado do singleton neste momento:

```
id=1  nat_enabled=False  nat_start_at=None  max_envios_hora=20
nat_button_events: 0 linhas
```

**A NAT nasce desligada em dois eixos independentes.** `nat_enabled=False` é o kill switch;
`nat_start_at=None` é o corte de data. Ligar só o primeiro não faz a NAT atuar — o guard exige
os dois. Foi de propósito: um clique errado no botão de liga/desliga não solta a NAT sobre
3.591 leads.

Duas decisões de schema que não são acidente:

- **`nat_config` tem `CHECK (id = 1)`.** O singleton é garantido pelo banco, não pela
  convenção. Duas linhas ali seria comportamento indefinido no kill switch — o pior lugar
  possível para ambiguidade.
- **`nat_button_events.contact_wa_id` NÃO tem FK para `contacts`**, diferente de `messages`.
  A tabela existe para nunca perder um clique. Uma FK só acrescentaria um modo de falha
  (replay, backfill, contato ainda não criado) capaz de derrubar a transação do webhook e
  levar o lote inteiro de mensagens junto. O índice dá o mesmo desempenho sem esse risco.

---

## 2. As travas — `backend/app/nat_guard.py`

```python
async def nat_pode_atuar(lead_ou_contato, db) -> tuple[bool, str]
```

Cinco verificações, nesta ordem. Todas têm que passar:

| # | verificação | origem do dado |
|---|---|---|
| 1 | `nat_enabled` é true? | `nat_config.nat_enabled` (id=1) |
| 2 | `nat_start_at` definido **e** `register_date >= nat_start_at`? | `nat_config.nat_start_at` × `exact_leads.register_date` |
| 3 | funil é 18535? | `exact_leads.funnel_id` |
| 4 | `assigned_to IN (4, 5)`? | `contacts.assigned_to` |
| 5 | teto/hora não estourado? | `nat_config.max_envios_hora` |

**Falha fechada em todo caminho.** Não existe ramo que libere por omissão:

- `nat_config` inexistente → bloqueia
- `nat_start_at IS NULL` → bloqueia
- `register_date IS NULL` → bloqueia
- funil nulo ou diferente de 18535 → bloqueia
- telefone não resolvível → bloqueia
- contato inexistente no banco → bloqueia
- `assigned_to` nulo → bloqueia
- `max_envios_hora` nulo → bloqueia
- **exceção inesperada** → `except` de fechamento devolve `(False, motivo)`

Toda decisão de bloqueio sai no log com o motivo (`🔒 NAT bloqueada: ...`).

### Por que o corte é por `register_date`

Não é "é novo no banco". `register_date` é a data que o lead tem na Exact — imune a backfill
e a falha de sync. Se o sync cair por três dias e voltar de uma vez, os leads antigos que
entrarem em bloco continuam bloqueados. `register_date IS NULL` bloqueia: ausência de dado
nunca libera.

### Por que `assigned_to` é verificado por id literal

Valéria (4), Thobias (5) e Isa (2) estão **todos com `role = 'admin'`** no banco. Verificar
por `role` incluiria a gestora. Os ids são literais de propósito, em `SDR_IDS_PERMITIDOS`.

### O teto por hora e o marcador que ainda não existe

O teto tem que contar **só o que a NAT enviou**. Contar `direction='outbound'` seria errado:
incluiria resposta manual de SDR, a boas-vindas automática e o disparo em massa da tela de
Automações. Uma campanha de 500 templates estouraria o teto da NAT sem a NAT ter mandado
nada — e a reação natural seria subir o teto, evaporando a proteção.

Hoje **não existe marcador confiável**. Auditado em 25/07: `messages.sent_by_ai` é coluna
morta — nenhum código a escreve, 0 de 26.766 linhas com `true`. Nenhum dos 5 pontos que criam
`Message` outbound a preenche.

Como a NAT ainda não tem caminho de envio, nenhuma mensagem lhe é atribuível e **0 é a
resposta certa, não um fallback**. `COLUNA_MARCADOR_ENVIO_NAT = None` marca o ponto exato onde
isso se resolve quando o primeiro envio da NAT existir (Bloco 2+), e o guard loga um aviso
sempre que libera nessas condições.

### Divergência reportada, não corrigida

`auto_welcome_config.funnel_ids` em produção está com **`18535,18537,25588`** — mais amplo que
o alvo da NAT (só 18535). **Essa config não foi alterada.** É o `nat_guard` que restringe.
Mexer no `funnel_ids` mudaria o comportamento da boas-vindas, que está fora do escopo.

### Não está plugado em lugar nenhum

`nat_pode_atuar` existe e é testada, mas **não foi ligada ao `send_welcome_to_new_lead`** nem a
nenhum outro caminho. Plugar muda comportamento de produção e é decisão separada.

---

## 3. Captura de clique — `backend/app/nat_buttons.py` + webhook

### O bug

`backend/app/main.py` tratava `text, image, audio, video, document, sticker` e **não tinha
`else`**. Com `type: "button"`, a `Message` era gravada com `content=""` e `payload` /
`context.id` eram descartados. **102 cliques perdidos entre 13/07 e 22/07.** O SDR ainda
recebia a notificação — vazia, sem corpo, porque o `preview` vem do `content`.

### O que passou a acontecer

`extrair_evento_botao()` é função pura, sem banco e sem FastAPI — dá para testar por replay
de payload sintético, que é a única validação possível hoje. Trata os dois formatos:

**Quick reply de template** (`type: "button"`) — o que os 6 templates `nat_*` produzem:
```json
{"type":"button","button":{"payload":"...","text":"..."},"context":{"id":"wamid.ORIGINAL"}}
```

**Botão livre** (`type: "interactive"`) — ainda não ocorre, será usado no Bloco 3:
```json
{"type":"interactive","interactive":{"type":"button_reply","button_reply":{"id":"...","title":"..."}}}
```

Para os dois:
- a `Message` continua sendo salva como antes, agora com `content = "botao:<texto>"` — o que
  **também corrige a notificação vazia do SDR**, sem nenhuma mudança no código de notificação;
- uma linha vai para `nat_button_events` com payload, texto, `source` e `context_message_id`;
- `list_reply` e mensagens comuns passam reto. A captura é aditiva, não intercepta nada.

Nenhum roteamento, nenhuma resposta automática. Só persiste e loga.

### `context.id` é obrigatório

**"Prefiro outro horário" é o mesmo texto em `nat_boasvindas` e em `nat_reativacao_09h`.** Sem
`context.id` — o wamid da mensagem que o botão respondeu — os dois cliques são
indistinguíveis. Por isso o campo é indexado: o roteamento do Bloco 2 vai buscar por ele.

### A escrita do evento não pode derrubar o webhook

O `INSERT` em `nat_button_events` roda dentro de **SAVEPOINT** (`db.begin_nested()`) com
`try/except`. `try/except` puro não bastaria: um `IntegrityError` deixa a transação do asyncpg
em estado abortado e toda operação seguinte na mesma sessão falharia com
`InFailedSQLTransaction` — o lote inteiro de mensagens se perderia por causa de uma tabela de
observabilidade. Com o SAVEPOINT, reverte-se só este INSERT e o resto segue intacto.

Se a gravação do evento falhar, perde-se **o evento** — nunca a mensagem. Esta tabela serve ao
fluxo, não o contrário.

---

## 4. Dá para definir payload customizado em botão de template? **Sim — no envio.**

O recon já tinha confirmado que a **definição** do template devolvida pela Meta não carrega
campo de payload. A resposta é que ele é fixado **no envio**, por botão, no componente
`sub_type: "quick_reply"`:

```json
{
  "type": "button",
  "sub_type": "quick_reply",
  "index": 0,
  "parameters": [{"type": "payload", "payload": "nat_boasvindas:outro_horario"}]
}
```

- `index` é a posição do botão (0, 1, 2 — máximo 3 quick replies).
- O payload **não é visível** para o lead e volta em `button.payload` no webhook quando ele
  clica. É exatamente o campo que `nat_button_events.button_payload` já persiste.

Isso resolve o problema de roteamento na raiz: hoje o único discriminador entre dois botões de
texto idêntico é o `context.id`, que exige uma segunda consulta para descobrir de qual template
veio. Com payload próprio por botão, o clique se identifica sozinho.

**Não implementado nesta sprint.** `send_template_message` (`backend/app/whatsapp.py:25`) hoje
só monta `components` para o `body`; aceitar componentes de botão é mudança da próxima sprint,
junto com o roteamento que vai consumir isso.

Fontes: [YCloud — WhatsApp Messaging Examples](https://docs.ycloud.com/reference/whatsapp-messaging-examples),
[Picky Assist — Sending WhatsApp Interactive Buttons](https://help.pickyassist.com/api-documentation-v2/push-api/sending-whatsapp-template-messages/sending-whatsapp-interactive-buttons),
[Yeastar — WhatsApp Message Template Component Description](https://help.yeastar.com/en/p-series-cloud-edition/developer-guide/whatsapp-message-template-component-description.html)

---

## 5. Testes — `backend/test_nat_guard.py`, 9/9 passando

Banco falso (`MagicMock`), nenhuma conexão aberta, nenhuma linha gravada, nenhum envio. Os
casos 8 e 9 são replay de payload sintético — **não dá para validar com clique real**, porque
nada está sendo entregue desde 23/07.

```
 1. nat_enabled=false (tudo o mais ok)  -> BLOQUEADO  nat_enabled=false
 2. register_date < nat_start_at        -> BLOQUEADO  register_date 2026-07-20 anterior ao corte 2026-07-25
 3. register_date IS NULL               -> BLOQUEADO  register_date ausente no lead
    nat_start_at IS NULL (2o eixo)      -> BLOQUEADO  corte de data ausente
 4. funil 18537                         -> BLOQUEADO  fora do alvo da NAT (18535)
    funil 25588                         -> BLOQUEADO  fora do alvo da NAT (18535)
 5. assigned_to=2 (gestora)             -> BLOQUEADO  fora dos SDRs permitidos [4, 5]
    assigned_to IS NULL                 -> BLOQUEADO
    contato inexistente no banco        -> BLOQUEADO
 6. teto estourado (20/20)              -> BLOQUEADO  teto de envios/hora estourado
 7. lead valido, tudo ligado            -> LIBERADO   funil=18535 SDR=5
 8. replay type="button"                -> source=template payload='Prefiro outro horário'
                                           context='wamid.ORIGINAL_BOASVINDAS'
    Message.content                     -> 'botao:Prefiro outro horário'  (antes era "")
 9. replay type="interactive"           -> source=interactive payload='nat_confirma_sim'
                                           context='wamid.ORIGINAL_LIVRE'
    texto comum e list_reply            -> ignorados (captura e aditiva)
```

O caso 7 é o que dá sentido aos outros seis: sem ele, uma função que retornasse `False` sempre
passaria em 1–6 e a NAT nunca atuaria depois de ligada.

Rodar: `cd backend && venv/bin/python test_nat_guard.py`

---

## 6. Estado de produção

| item | estado |
|---|---|
| Mensagem enviada a lead real | **nenhuma** |
| Serviço reiniciado | **não** — `cenat-backend.service` segue no processo antigo |
| Sync do Exact rodado manualmente | não |
| NAT | **desligada** (`nat_enabled=False`, `nat_start_at=None`) |
| `auto_welcome_config` | **não alterada** (`enabled=true`, `18535,18537,25588`, `nat_boasvindas`) |
| Merge | **não feito** — decisão do Álefe |

**O código do webhook ainda não está no ar.** O processo em produção é mais velho que o `main`;
um restart traria commits não revisados junto. Enquanto não houver restart, **cliques de botão
continuam sendo descartados** — a captura só passa a valer quando o serviço subir.

---

## 7. O que ficou fora, de propósito

- Incidente de entrega aberto desde 23/07 e instrumentação de `statuses[].errors[]`
- Extração dos 99 leads que clicaram e não foram atendidos
- Máquina de estados `nat_flow_state`, roteamento de botão, envio de mensagem da NAT
- Plugar `nat_pode_atuar` no `send_welcome_to_new_lead`
- Payload customizado no `send_template_message` (investigado acima, não implementado)
- Escrita de estágio no Exact, anotação na timeline, SLA, escalonamento
- Cenário 2 (`nat_fora_horario`, `nat_reativacao_09h`)
