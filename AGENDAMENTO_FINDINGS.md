# Agendamento na Exact Spotter — investigação da API (17/08/2026)

Investigação de leitura + chamadas de teste reais contra `https://api.exactspotter.com/v3`,
com limpeza ao final. **Nenhum arquivo do projeto foi alterado** além da criação deste `.md`.

Autenticação: header `token_exact` (valor em `EXACT_SPOTTER_TOKEN`, `backend/.env`). Mesmo
header que `app/exact_spotter.py:81` já usa. Rate limit respeitado (30 req/20s; o pico desta
investigação foi ~6 req em 20s).

Nos `curl` abaixo, exporte o token antes:

```bash
set -a && . backend/.env && set +a
H="token_exact: $EXACT_SPOTTER_TOKEN"
```

---

## 1. Correção da premissa: as datas **não** são UTC

O enunciado da investigação dizia "datas ISO UTC". O que a API faz é outra coisa, e isso muda
a implementação:

**O valor enviado volta verbatim.** Enviei `2026-08-19T11:00:00Z` e o `GET /Boxes` devolveu
`2026-08-19T11:00:00Z`. Nenhuma conversão, nenhum deslocamento.

**O mesmo horário aparece sem `Z` em `GET /Meetings`:**

```json
"meetingDate": "2026-08-19",
"startTime":   "2026-08-19T11:00:00.0000000",
"finalTime":   "2026-08-19T11:45:00.0000000"
```

O `Z` de `/Boxes` é **cosmético**. O campo é hora de parede (wall clock), não instante UTC.

**Confirmação pelo dado de produção.** Os slots recorrentes de `comercial@cenatcursos.com.br`
são `09:00`, `13:30` e `15:00`. Lidos como UTC verdadeiro seriam 06:00, 10:30 e 12:00 em São
Paulo — uma agenda comercial começando às 6 da manhã. Lidos como hora local, são exatamente
um expediente normal.

> **Consequência prática:** converter para UTC antes de enviar (`astimezone(timezone.utc)`)
> desloca a reunião em 3 horas dentro do CRM. Envie o horário local de São Paulo com o sufixo
> `Z` colado no fim, sem conversão. É feio e é o que a API espera.

---

## 2. `POST /BoxesAdd` — criar o slot

JSON **flat** (diferente do `LeadsAdd`, que é aninhado).

```bash
curl -s -w "\n[HTTP %{http_code}]\n" -X POST "https://api.exactspotter.com/v3/BoxesAdd" \
  -H "$H" -H "Content-Type: application/json" \
  -d '{
    "start": "2026-08-19T11:00:00Z",
    "end": "2026-08-19T11:45:00Z",
    "salesRepEmail": "comercial@cenatcursos.com.br",
    "status": "available",
    "typeMeeting": "web",
    "description": "TESTE API - pode excluir"
  }'
```

**Resposta — HTTP 201:**

```json
{"@odata.context":"http://apiv3.exactspotter.com:81/api/v3/$metadata#Edm.Int32","value":43722204}
```

O `value` é o `boxId`. Como o box volta ao ler:

```json
{
  "start": "2026-08-19T11:00:00Z", "end": "2026-08-19T11:45:00Z",
  "salesRep": "Victória Amorim", "salesRepEmail": "comercial@cenatcursos.com.br",
  "status": "available", "description": "TESTE API - pode excluir",
  "typeMeeting": "Online", "address": null, "leadId": 0, "id": 43722204
}
```

`typeMeeting: "web"` **volta normalizado como `"Online"`**. Não confie no eco do valor enviado.

### Validações (4 testadas, todas HTTP 400 com mensagem legível)

| Cenário testado | Mensagem |
|---|---|
| Box idêntico a um existente (sobreposição total) | `Boxes are occupied at the desired time.` |
| Sobreposição **parcial** com box existente (14:00–14:20 dentro de 13:30–14:30) | `Boxes are occupied at the desired time.` |
| `end` anterior ao `start` | `Start time must precede end time.` |
| `salesRepEmail` inexistente | `SDR not found.` |

**Regra de conflito:** qualquer interseção de intervalo com um box do **mesmo** `salesRepEmail`
é rejeitada, **independente do `status`** — a sobreposição parcial acima foi contra um box
`busy`. Não há criação silenciosa de slot duplicado. Nenhum dos 4 casos criou box.

---

## 3. `POST /LeadsAdd` — criar o lead

Payload **aninhado** sob `lead`, com `duplicityValidation` fora do objeto
(confere com <https://developers.rdstation.com/reference/postleadsadd.md>).

```bash
curl -s -w "\n[HTTP %{http_code}]\n" -X POST "https://api.exactspotter.com/v3/LeadsAdd" \
  -H "$H" -H "Content-Type: application/json" \
  -d '{
    "duplicityValidation": false,
    "lead": {
      "name": "TESTE API Alefe",
      "source": "Rd Marketing",
      "subSource": "DialogicasTurma",
      "funnelId": 18535,
      "ddiPhone": "55",
      "phone": "11999998888"
    }
  }'
```

**Resposta — HTTP 201:**

```json
{"@odata.context":"http://apiv3.exactspotter.com:81/api/v3/$metadata#Edm.Int32","value":51434608}
```

Como o lead ficou:

```
stage: Entrada          funnelId: 18535
source:    {'id': 106847, 'value': 'Rd Marketing'}
subSource: {'id': 176793, 'value': 'DialogicasTurma'}
sdr:       {'id': 443275, 'name': 'Thobias', 'lastName': 'França', 'active': False}
salesRep:  {'id': None, ...}
registerDate: 2026-08-17T18:34:22.8874557Z
```

Observações:

- **`source`/`subSource` são strings que casam com cadastros existentes.** Vieram resolvidos
  para os ids 106847 e 176793 — a API não criou origem nova. Um valor não cadastrado
  provavelmente cria lixo no cadastro; **valide antes de enviar**.
- **`funnelId` é `18535`** (`Pos Graduacao`), confirmado em `GET /Funnels`. É obrigatório se
  você for informar `stage`; sem ele o lead cai no primeiro estágio do funil padrão.
- **Sem `stage`, o lead nasce em `Entrada`** (posição 1 do funil 18535).
- **O SDR é atribuído automaticamente** (aqui, Thobias — `active: false`). O payload aceita
  `sdrEmail` para controlar isso; não informar deixa a distribuição do CRM decidir.
- `registerDate` **esse sim** vem em UTC real (18:34Z ≈ 15:34 SP). Ou seja: campos de auditoria
  são UTC, campos de agenda são hora local. Não são o mesmo padrão.

### Etapas do funil 18535 (`GET /Stages?$filter=funnelId eq 18535`)

```
 1 Entrada            2 Primeiro Contato    3 Follow 1      4 Follow 2      5 Follow 3
 6 Follow 4           7 Follows 5           8 Follows 6     9  Follows 7   10 Follows 8
11  Follows 9        12 Objeções - Whatsapp 13 Reagendamento
14 Pré Qualificado (gateType 3)            15 Agendados (gateType 2, id 133409)
```

Atenção aos nomes: há espaço à esquerda em `" Follows 7"` e `" Follows 9"`, e o singular muda
(`Follow 1..4` vs `Follows 5..9`). Se algum dia o `stageName` for parametrizável, não gere o
nome por concatenação.

---

## 4. `POST /scheduleAdd` — vincular lead ao slot

```bash
curl -s -w "\n[HTTP %{http_code}]\n" -X POST "https://api.exactspotter.com/v3/scheduleAdd" \
  -H "$H" -H "Content-Type: application/json" \
  -d '{
    "boxId": 43722204,
    "leadId": 51434608,
    "stageName": "Agendados",
    "salesRepEmail": "comercial@cenatcursos.com.br"
  }'
```

**Resposta — HTTP 201:**

```json
{"@odata.context":"http://apiv3.exactspotter.com:81/api/v3/$metadata#Edm.Boolean","value":true}
```

Retorna **booleano**, não o id da reunião. Para obter o id é preciso consultar `GET /Meetings`
depois (`$filter=lead/id eq {leadId}`).

### Efeitos confirmados (item 3 do escopo)

**No lead** — `GET /Leads?$filter=id eq 51434608`:

```
stage: Entrada  →  Agendados          ✅
salesRep: {id: None}  →  {id: 415967, name: 'Victória', email: 'comercial@cenatcursos.com.br'}
updateDate: 2026-08-17T18:34:43Z
```

**No box** — `GET /Boxes?$filter=id eq 43722204`:

```
status:  available  →  busy           ✅
leadId:  0          →  51434608       ✅
```

**Reunião criada** — `GET /Meetings?$filter=lead/id eq 51434608`:

```json
{
  "type": "Cancelada", "meetingType": "Online", "meetingDate": "2026-08-19",
  "startTime": "2026-08-19T11:00:00.0000000", "finalTime": "2026-08-19T11:45:00.0000000",
  "managerDescription": "TESTE API - pode excluir", "id": 4724640,
  "meetingFeedbackUrl": "https://app.exactspotter.com/reuniao/NDcyNDY0MA2"
}
```

(o `type: "Cancelada"` é consequência do `LeadsDelete` da limpeza — ver §6.)
O `description` do **box** virou `managerDescription` da **reunião**.

Um `scheduleAdd` faz portanto **três** escritas de uma vez: move o lead de etapa, atribui o
salesRep e cria a reunião. Não é uma operação isolada de agenda.

---

## 5. `GET /Boxes` não é confiável sem `$filter` — armadilha séria

| Consulta | Resultado |
|---|---|
| `GET /Boxes/$count` (sem filtro) | **276** |
| `GET /Boxes/$count?$filter=status eq 'busy'` | **1472** |
| `GET /Boxes/$count?$filter=status eq 'available'` | **4** |

Um filtro devolvendo 5× mais linhas que a consulta sem filtro significa que **o `GET /Boxes`
sem `$filter` aplica uma janela implícita** (os 276 vão de 2026-07-20 a 2026-11-02 — grosso
modo ~4 semanas para trás e o futuro agendado). Não é paginação: 276 é o `$count` completo.

> Qualquer código que decida disponibilidade lendo `GET /Boxes` sem `$filter` está lendo um
> recorte não documentado que a Exact pode mudar sem aviso. **Sempre passe `$filter` explícito.**

### O modelo de agenda real da CENAT

Dos 276 boxes da janela: **todos `busy`**, sendo **193 com `leadId: 0`** e 83 com `leadId` real.
Em toda a base existem apenas **4 boxes `available`** — e os quatro estão no passado
(2025-08-11, 2025-08-12, 2026-05-05 ×2).

Leitura: os boxes `busy` com `leadId: 0` são os **blocos de agenda** dos consultores (os slots
recorrentes de 09:00 / 13:30 / 15:00), e `leadId != 0` é reunião de fato marcada. O status
`available` praticamente não é usado em produção.

Reps na janela: `comercial@` 160 · `processoseletivo@` 99 · `executivadecarreiras@` 17.

---

## 6. Limpeza — o que saiu e o que **não** saiu

### `DELETE /LeadsDelete/{id}` — HTTP 204, corpo vazio

```bash
curl -s -w "\n[HTTP %{http_code}]\n" -X DELETE \
  "https://api.exactspotter.com/v3/LeadsDelete/51434608" -H "$H"
```

É **exclusão dura**: `GET /Leads` devolve 0, e `POST /LeadsRecover {"leadId":51434608}`
responde `400 {"error":{"message":"Lead not found"}}`. Não há desfazer.

**Efeito em cascata, não documentado:** a reunião virou `type: "Cancelada"` e o box
**desapareceu de todos os `GET`** — some do `$filter=id eq ...`, do listado sem filtro
(voltou de 277 para 276) e dos filtros por `status` `busy` e `available`.

### `DELETE /BoxesRemove/{id}` — HTTP 204, e é soft delete

```bash
curl -s -w "\n[HTTP %{http_code}]\n" -X DELETE \
  "https://api.exactspotter.com/v3/BoxesRemove/43722264" -H "$H"
```

Chamar de novo no mesmo id devolve **204 outra vez** (idempotente), enquanto um id que nunca
existiu devolve `400 "The informed box does not exist."`. A diferença entre as duas mensagens é
o que permite distinguir "removido" de "inexistente".

### ⚠️ Resíduo que a API não deixa remover

O box **43722204** ficou órfão e **não é removível**:

```
DELETE /BoxesRemove/43722204
→ 400 {"error":{"message":"It is not possible to change a Box with a scheduled meeting."}}
```

Ele continua preso à reunião 4724640, mesmo com a reunião `Cancelada` e o lead excluído.
Confirmei que a mensagem é específica (id inexistente dá `The informed box does not exist.`),
ou seja: **a linha ainda existe no banco da Exact**.

Mitigantes verificados:

- **Não bloqueia a agenda.** Um `BoxesAdd` no mesmo intervalo (19/08 11:00–11:45) foi aceito
  depois, com HTTP 201 (box 43722264, removido em seguida).
- **É invisível** em toda consulta testada.
- Não há `ScheduleRemove` no `$metadata` da API — os únicos endpoints de agenda são
  `Boxes`, `BoxesAdd`, `BoxesUpdate`, `BoxesRemove`, `ScheduleAdd` e `Meetings`.

**Ordem correta de limpeza (a que eu deveria ter usado):** `BoxesRemove` **antes** de
`LeadsDelete` — mas note que um box já vinculado a reunião também recusa remoção, então na
prática **um `scheduleAdd` é irreversível pela API**.

### Estado final verificado

| Verificação | Resultado |
|---|---|
| `GET /Leads?$filter=contains(lead,'TESTE API')` | **0 encontrados** ✅ |
| `GET /Boxes?$filter=contains(description,'TESTE API')` | **0 encontrados** ✅ |
| `GET /Boxes/$count` | **276** — idêntico ao pré-teste ✅ |
| Agenda de 19/08 | 3 slots originais (09:00, 13:30, 15:00), intactos ✅ |
| Box 43722204 | invisível, sem ocupar agenda, **não removível** ⚠️ |
| Reunião 4724640 | `Cancelada`, órfã ⚠️ |

Nada visível a usuário permaneceu. Vale registrar que a base **já tinha** resíduo de testes
anteriores: a primeira reunião de `GET /Meetings` é de um lead `"TESTE ROTEAMENTO"` (2025).

---

## 7. Riscos e limitações para o fluxo LP → lead → agendamento

1. **Nenhuma transação.** O caminho são 3 chamadas (`LeadsAdd`, `BoxesAdd`, `scheduleAdd`) e a
   API não oferece rollback. Falha no `scheduleAdd` deixa **lead criado + box criado + nada
   agendado**; e como `scheduleAdd` é irreversível, a compensação não existe nos dois sentidos.
   O desenho tem que tolerar estado parcial, não tentar evitá-lo.

2. **`scheduleAdd` é porta de mão única.** Não há cancelar/remarcar pela API. Remarcar um lead
   exige um segundo `scheduleAdd` em outro box — e o box antigo fica ocupado para sempre. Num
   fluxo de LP com pessoas trocando de horário, isso vaza slots da agenda real dos consultores.
   **É a limitação mais grave para o produto.**

3. **Corrida entre duas pessoas na LP.** A trava contra sobreposição existe no `BoxesAdd`
   (`Boxes are occupied`), mas **não sei se existe no `scheduleAdd`** — ver §8. Se dois
   visitantes escolherem o mesmo slot, o segundo pode sobrescrever ou duplicar.

4. **Fuso.** Enviar UTC de verdade desloca a reunião em 3h. E como `registerDate` é UTC real
   enquanto `start` é local, um único `datetime.utcnow()` usado nos dois lugares erra num deles.

5. **`GET /Boxes` sem `$filter`** devolve recorte implícito (§5). Disponibilidade calculada em
   cima disso fica errada silenciosamente.

6. **`duplicityValidation: false` gera duplicata de propósito.** Numa LP pública, o mesmo lead
   preenchendo duas vezes vira dois leads. Com `true`, é preciso tratar o erro de duplicidade —
   que eu **não testei** (não quis criar um segundo lead de teste).

7. **`source`/`subSource` são texto livre resolvido contra cadastro.** Valor errado
   provavelmente polui o cadastro de origens, que é global e usado em relatório.

8. **`LeadsDelete` é irreversível e cascateia** para reunião e box (§6). Não use como
   compensação de erro.

9. **`typeMeeting` não ecoa o que você manda** (`web` → `Online`). Não use o eco para conferir.

10. **Rate limit de 30 req/20s** é global do token — dividido com o `sync_job` da Exact, que já
    roda a cada 600s e pagina 500 leads por vez (`exact_spotter.py:88`). Um pico na LP concorre
    com a ingestão existente.

---

## 8. A pergunta em aberto — deliberadamente não testada

**`scheduleAdd` aceita um box `busy` com `leadId: 0`?**

É a questão central do desenho, porque em produção **não existem boxes `available`** (§5): a
agenda real é feita de blocos `busy` com `leadId: 0`. Meu teste usou um box `available` criado
por mim, que é justamente o caso que **não** ocorre em produção.

Não testei porque a única forma honesta seria fazer `scheduleAdd` num bloco real de
`comercial@cenatcursos.com.br`, e §6 mostra que isso é **irreversível**: eu deixaria um slot
real de uma consultora ocupado por um lead de teste, sem meio de desfazer pela API.

Duas leituras possíveis, com implicações opostas:

- **Se aceita** → o módulo **nunca deve criar box**. Lista blocos com `leadId == 0`, oferece na
  LP e chama `scheduleAdd` no id escolhido. Simples e sem lixo de agenda.
- **Se recusa** → o módulo precisa criar box novo, e aí esbarra em `Boxes are occupied` sempre
  que o horário coincidir com um bloco existente — ou seja, só conseguiria agendar **fora** dos
  horários que os consultores realmente reservaram. Seria um furo de produto.

**Como resolver com segurança**, em ordem de preferência:

1. Perguntar à Exact (suporte) — custo zero, sem escrita.
2. Pedir a um consultor que crie um bloco de teste na agenda dele pela UI, num horário
   irrelevante, e testar contra esse bloco. O resíduo fica num slot combinado.
3. Testar num box `busy` criado por nós numa data distante (ex.: 2027), aceitando de antemão
   mais um box órfão. Replica a forma de produção sem tocar em agenda real.

Posso executar a opção 3 se você autorizar o resíduo.

---

## 9. Recomendação para `app/agendamento/`

### Forma

Módulo em `backend/app/agendamento/`, seguindo o que o repo já faz em `exact_spotter.py`:
`httpx.AsyncClient` com timeout explícito, `get_headers()` reaproveitado, e nunca deixar
exceção de rede subir para o request da LP.

```
app/agendamento/
  client.py       # httpx puro contra a Exact: boxes_add, boxes_remove, leads_add,
                  # schedule_add, meetings_by_lead. Traduz os 400 conhecidos em exceções
                  # tipadas (SlotOcupado, SdrInexistente, IntervaloInvalido, SdrNaoEncontrado).
  disponibilidade.py  # lê blocos livres. SEMPRE com $filter explícito.
  agendar.py      # orquestra o caminho LP -> lead -> agendamento, com registro de estado.
  horarios.py     # a regra de fuso do §1, isolada num lugar só.
```

### Cinco decisões que eu tomaria

1. **Isolar o fuso numa função única.** Nada no módulo chama `datetime` direto:

   ```python
   SP = ZoneInfo("America/Sao_Paulo")

   def para_exact(dt: datetime) -> str:
       """Hora de parede de SP com 'Z' cosmético. NÃO converter para UTC — ver §1."""
       local = dt.astimezone(SP)
       return local.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
   ```

   Um comentário explicando *por que* o `Z` é mentira, senão alguém "corrige" isso em 6 meses.

2. **Persistir o estado do agendamento em tabela nossa, antes de chamar a Exact.** Dado que não
   há transação (§7.1) nem desfazer (§7.2), a única forma de auditar o que ficou pela metade é
   ter linha local com `lead_id`, `box_id`, `meeting_id` e o passo alcançado. É o mesmo padrão
   que `nat_scheduled_actions` já usa para ações que podem falhar no meio.

3. **Ordem: box → lead → schedule.** Criar o box primeiro porque é o único passo **reversível**
   enquanto não há reunião (§6). Se o `LeadsAdd` falhar, `BoxesRemove` limpa e não sobra nada.
   A ordem inversa deixa lead órfão, que só sai com exclusão dura.

4. **Nunca chamar `LeadsDelete` como compensação.** É irreversível e cascateia (§7.8). Lead
   parcial deve ser marcado no nosso lado e resolvido por humano.

5. **Idempotência por lead na LP.** Antes de criar, procurar lead recente com o mesmo telefone
   (`GET /Leads?$filter=...`) — `duplicityValidation: false` não protege ninguém numa página
   pública. E envolver o `scheduleAdd` num lock por `box_id` do nosso lado, já que não se sabe
   se a Exact trava (§8).

### Antes de escrever código

Resolver §8. A resposta decide se `disponibilidade.py` **lista** blocos existentes ou se
`agendar.py` **cria** boxes — são módulos diferentes, e implementar o errado é retrabalho
inteiro, não ajuste.

---

## Apêndice — inventário de endpoints (do `$metadata`)

Agenda: `Boxes` · `BoxesAdd` · `BoxesUpdate` · `BoxesRemove` · `ScheduleAdd` · `Meetings` ·
`MeetingQuality` · `MeetingQualitySQL` · `MeetingSettings`

Leads: `Leads` · `LeadsAdd` · `LeadsUpdate` · `LeadsDelete` · `LeadsRecover` · `LeadsTransfer` ·
`LeadsLost` · `LeadsWon` · `LeadsSold` · `LeadsQualification` · `LeadsAndPersons` ·
`LeadsCustomFields` · `LeadStages` · `LeadPipelineStages` · `StagesLead` ·
`CustomFieldsLeads` · `CustomFieldsLeadsRemove`

**Não existe `ScheduleRemove` nem `ScheduleUpdate`** — a base de §7.2.

Funis (`GET /Funnels`): Intercambio 18285 · **Pos Graduacao 18535** · Pós Graduação - Vendas
18537 · Reativação - SQL 20647 · CONGRESSO PRESENCIAL 20776 · Vagas Afirmativas 21007 ·
Funil - Isa 25588.
