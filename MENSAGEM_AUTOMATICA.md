# Envio de Mensagem Automática (Boas-vindas) — Configuração e Ativação

Este documento descreve **como está configurado** o envio automático da mensagem de
boas-vindas para leads novos vindos do **Exact Spotter**, **por que atualmente ele não
dispara**, e **como ativá-lo** no futuro (incluindo como escolher qual template será usado).

> Arquivo principal: `backend/app/exact_spotter.py`
> Auxiliares de WhatsApp: `backend/app/whatsapp.py`
> Rotas: `backend/app/routes.py` e `backend/app/exact_routes.py`

---

## 1. Visão geral do fluxo

Quando o usuário clica em **Sincronizar** na página de Leads (UI):

1. Frontend chama `POST /api/exact-leads/sync`.
2. O backend (`sync_exact_leads`) busca **todos os leads** do Exact Spotter (paginado).
3. Faz *upsert* de cada lead na tabela `ExactLead` (ingestão).
4. Para cada lead **novo** cujo funil está em `POS_FUNNEL_IDS`, chama
   `send_welcome_to_new_lead(...)`, que:
   - envia o **template de boas-vindas** via WhatsApp Cloud API;
   - cria/atualiza o `Contact` com a IA ativa (`ai_active=True`) e SDR atribuído;
   - registra a `Message` enviada;
   - cria um card no Kanban (`AIConversationSummary`).

> Importante: a mensagem só dispara para leads **NOVOS** (primeira vez que entram no banco).
> Lead que já existe conta como "atualizado" e **não** recebe a mensagem novamente.

---

## 2. Configuração atual (constantes)

Em `backend/app/exact_spotter.py`:

| Constante | Valor atual | Significado |
|---|---|---|
| `AUTO_TEMPLATE_NAME` | `"mensagens_de_boas_vindas"` | Nome do template WhatsApp usado na mensagem automática |
| `AUTO_TEMPLATE_LANG` | `"pt_BR"` | Idioma/locale do template |
| `AI_CHANNEL_ID` | `2` | ID do canal (número WhatsApp) por onde a mensagem é enviada |
| `POS_FUNNEL_IDS` | `18535,18537,25588` | Funis que **recebem** boas-vindas + IA + card |
| `INGEST_FUNNEL_IDS` | *(vazio = todos)* | Funis que entram no banco. Vazio puxa **todos** os funis |

`POS_FUNNEL_IDS` e `INGEST_FUNNEL_IDS` podem ser sobrescritos por variáveis de ambiente
de mesmo nome (lista separada por vírgula) no `.env` do backend.

Os parâmetros enviados ao template são **dois**, nesta ordem:

1. `{{1}}` = **nome do lead**
2. `{{2}}` = **nome do curso** (extraído do `subSource` do Exact via `extract_course_name`)

O template escolhido **precisa ter exatamente 2 variáveis no corpo** (`{{1}}` e `{{2}}`),
senão o envio falha na Meta.

---

## 3. Por que NÃO está disparando hoje

O envio busca o canal pelo ID fixo `AI_CHANNEL_ID = 2`:

```python
result = await db.execute(select(Channel).where(Channel.id == AI_CHANNEL_ID))  # id == 2
channel = result.scalar_one_or_none()
if not channel:
    print("❌ Canal da IA não encontrado")
    return   # <- sai aqui, sem enviar
```

No banco **só existe o canal `id = 1`** ("Pós-Graduação (SDR)"). **Não existe canal `id = 2`.**
Por isso a função retorna antes de enviar — sem erro visível na UI, apenas um `print` no log
do backend: `❌ Canal da IA não encontrado`.

Resumo: o envio automático está **inativo por falta do canal id=2**, não por estar
desligado no código.

---

## 4. Como ATIVAR o envio automático

Há duas formas, dependendo de qual número WhatsApp deve enviar a mensagem.

### Opção A — Cadastrar um 2º número dedicado (canal da IA)

Use quando existir um segundo número/WABA para a IA. Crie o canal via API:

```bash
curl -X POST http://localhost:8001/api/channels \
  -H "Content-Type: application/json" \
  -d '{
    "name": "IA (Boas-vindas)",
    "phone_number": "55XXXXXXXXXXX",
    "phone_number_id": "<PHONE_NUMBER_ID_DA_META>",
    "whatsapp_token": "<TOKEN_PERMANENTE_DA_META>",
    "waba_id": "<WABA_ID_DA_META>"
  }'
```

Confirme que o `id` retornado é **2**. Se o banco atribuir outro id (ex.: 3), atualize
`AI_CHANNEL_ID` em `backend/app/exact_spotter.py` para o id real do canal.

### Opção B — Usar o canal existente (id=1)

Use quando **não** houver segundo número e a mensagem puder sair pelo mesmo número do SDR.
Basta ajustar a constante:

```python
# backend/app/exact_spotter.py
AI_CHANNEL_ID = 1
```

### Depois de qualquer uma das opções

1. O template `mensagens_de_boas_vindas` (`pt_BR`) precisa estar **APROVADO** na Meta,
   vinculado ao WABA do canal escolhido, e com **2 variáveis** no corpo (ver seção 5).
2. Reinicie o backend para aplicar mudanças de código:
   ```bash
   sudo systemctl restart cenat-backend.service
   ```
3. Teste sincronizando na UI. Lembre: só dispara para leads **novos**.

---

## 5. Como escolher/configurar QUAL template será enviado

O template usado é definido por **duas constantes** em `backend/app/exact_spotter.py`:

```python
AUTO_TEMPLATE_NAME = "mensagens_de_boas_vindas"
AUTO_TEMPLATE_LANG = "pt_BR"
```

Para trocar o template da mensagem automática:

1. **Descubra o nome exato e o idioma** do template aprovado. Você pode listar os templates
   aprovados de um canal pela API:
   ```bash
   curl "http://localhost:8001/api/channels/1/templates?status=APPROVED"
   ```
2. **Ajuste as constantes** `AUTO_TEMPLATE_NAME` e `AUTO_TEMPLATE_LANG` com o nome e o
   locale do template desejado.
3. Garanta que o novo template tenha **exatamente 2 variáveis** no corpo, na ordem:
   - `{{1}}` → nome do lead
   - `{{2}}` → nome do curso

   Se o template tiver um número diferente de variáveis, é preciso ajustar também a lista
   de `parameters` na chamada de `send_template_message` (linha ~147 do `exact_spotter.py`).
4. Reinicie o backend.

### Criar um novo template pela plataforma (opcional)

A plataforma permite criar templates direto na Meta (admin), via:

```
POST /api/channels/{channel_id}/templates
```

(veja `create_channel_template` em `backend/app/routes.py`). O template criado ainda passa
pela **aprovação da Meta** antes de poder ser usado no envio automático.

---

## 6. Escopo: quais leads recebem a mensagem

- **Recebem** boas-vindas + IA + card: leads **novos** cujo `funnelId` está em
  `POS_FUNNEL_IDS` (hoje `18535, 18537, 25588`).
- **Só entram como dado** (sem mensagem): leads de qualquer outro funil.

Para incluir/remover funis do disparo automático, ajuste `POS_FUNNEL_IDS` (constante ou
variável de ambiente). Isso é **independente** de `INGEST_FUNNEL_IDS`, que controla apenas
quais funis entram no banco.

---

## 7. Checklist rápido de ativação

- [ ] Canal do envio existe e está correto (`AI_CHANNEL_ID` aponta para um canal real)
- [ ] Token / `phone_number_id` / `waba_id` do canal válidos e ativos na Meta
- [ ] Template `AUTO_TEMPLATE_NAME`/`AUTO_TEMPLATE_LANG` **APROVADO** e com 2 variáveis
- [ ] `POS_FUNNEL_IDS` contém os funis que devem receber a mensagem
- [ ] Backend reiniciado após mudanças de código
- [ ] Teste com um lead **novo** (leads já existentes não disparam)
