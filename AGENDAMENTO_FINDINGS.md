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

- ~~**`source`/`subSource` casam com cadastros existentes; a API não criou origem nova.**~~
  **ERRADO — corrigido em §11.** `subSource` voltou resolvido com o id 176793, e eu li isso
  como prova de que o cadastro já existia. Não era: **o `LeadsAdd` CRIOU o cadastro**, porque
  `"DialogicasTurma"` era um nome que eu inventei. O valor voltar com id não distingue
  "encontrou" de "acabou de criar".
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
sem `$filter` aplica uma janela implícita** (os 276 vão de 2026-07-20 a 2026-11-02). Não é
paginação: 276 é o `$count` completo.

**A janela corta o passado, não o futuro.** Um box criado em 2027-03-10 apareceu normalmente na
listagem sem filtro (277, `$orderby=start desc` trouxe ele no topo). O corte fica ~4 semanas
atrás — o que é pior do que parece para conflito: o passado recente some, mas nada avisa.

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

3. ~~**Corrida entre duas pessoas na LP.**~~ **Resolvido em §8:** o `BoxesAdd` é a trava — quem
   cria o box ganha o horário, e o segundo recebe `Boxes are occupied`. Não há janela de
   check-then-act. Continua valendo para **duplo clique da mesma pessoa**, que o `BoxesAdd` não
   cobre (horários diferentes, mesmo visitante).

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

## 8. Resposta: `scheduleAdd` **só aceita box `available`**

Testado em 17/08/2026 com autorização explícita para deixar o box órfão. Experimento controlado
em **2027-03-10** (data escolhida por estar completamente vazia: `$filter=start ge 2027-01-01`
devolvia 0 boxes), com **o mesmo lead, o mesmo rep, o mesmo dia e o mesmo payload** — variando
apenas o `status` do box.

### O experimento

**Braço A — box `busy` com `leadId: 0`** (a forma exata dos 193 blocos de produção):

```bash
# BoxesAdd aceita status "busy" livremente -> 201, box 43722357
curl -X POST ".../BoxesAdd" -H "$H" -d '{"start":"2027-03-10T11:00:00Z",
  "end":"2027-03-10T11:45:00Z","salesRepEmail":"comercial@cenatcursos.com.br",
  "status":"busy","typeMeeting":"web","description":"TESTE API 2027 - pode excluir"}'
```

Voltou exatamente como um bloco de produção: `status: "busy"`, `leadId: 0`.

```bash
curl -X POST ".../scheduleAdd" -H "$H" -d '{"boxId":43722357,"leadId":51434672,
  "stageName":"Agendados","salesRepEmail":"comercial@cenatcursos.com.br"}'
```

```json
{"error":{"code":"","message":"Box is already occupied or in the process of being occupied. Please choose another box."}}
```

**HTTP 400 — recusado.**

**Braço B — box `available`**, mesmo dia, mesmo rep, mesmo lead (box 43722368, 14:00–14:45):

```json
{"@odata.context":"...#Edm.Boolean","value":true}
```

**HTTP 201 — aceito.** Lead foi para `Agendados`, box virou `busy` com `leadId: 51434672`.

### Conclusão

**O discriminador é o `status`.** `scheduleAdd` exige `status: "available"`. Os blocos `busy`
da agenda dos consultores são **inacessíveis pela API** — não dá para "encaixar" um lead num
horário que a consultora já reservou.

Isso mata a hipótese de "listar blocos livres e agendar neles": **não existem blocos livres para
a API**. O módulo obrigatoriamente **cria o próprio box** (`available`) e só então agenda.

### Corolário: `BoxesAdd` é o lock

Como `BoxesAdd` recusa qualquer sobreposição com box existente (§2), e `scheduleAdd` recusa
qualquer box que não seja `available` (aqui), o par tem uma propriedade útil: **o `BoxesAdd` é,
ele mesmo, a trava de concorrência.** Não existe janela de check-then-act — quem conseguir criar
o box ganhou o horário. Isso responde o risco §7.3.

### Bônus: o que trava o `BoxesRemove` é a reunião, não o status

O box `busy` do braço A saiu limpo com `BoxesRemove` → **HTTP 204**. O box do braço B, que
recebeu `scheduleAdd`, recusou → `400 "It is not possible to change a Box with a scheduled
meeting."` Confirma §6: o bloqueio vem da reunião vinculada, não de `status: busy`.

### Resíduo desta rodada

| Artefato | Destino |
|---|---|
| Lead 51434672 (`TESTE API Alefe 2027`) | excluído, 204 ✅ |
| Box 43722357 (braço A, `busy`) | removido, 204 ✅ |
| Box 43722400 (sonda de bloqueio) | removido, 204 ✅ |
| **Box 43722368** (braço B, com reunião) | **órfão — autorizado** ⚠️ |

Verificado ao final: `$count` de volta a **276** (baseline), **0** boxes visíveis em 2027, **0**
boxes e **0** leads com "TESTE API". O órfão não bloqueia o horário: um `BoxesAdd` em
2027-03-10 14:00–14:45 foi aceito depois (201, box 43722400, removido em seguida).

**Total de órfãos invisíveis deixados pela investigação: 2** (43722204 e 43722368).
Mais um veio do E2E da implementação — ver §10. **Total geral: 3.**

---

## 9. Arquitetura recomendada para `app/agendamento/`

Desenho fechado sobre as três premissas definidas: **hora de parede de São Paulo**,
**agendamento definitivo** (remarcação sai pelo WhatsApp, fora da API) e **grade própria no
backend**, com `/Boxes` consultado apenas para conflito.

As três se encaixam bem com o que a API é. A irreversibilidade do `scheduleAdd` (§7.2), que
seria o pior problema do módulo, deixa de ser problema quando remarcação não passa pela API. E
a grade própria é a única saída possível, já que §8 provou que não há slots da Exact para listar.

### Estrutura

```
app/agendamento/
  grade.py         # a grade própria: quais horários existem, por consultor e dia da semana.
                   # Fonte da verdade nossa. Não consulta a Exact.
  horarios.py      # fronteira de fuso. Único lugar do módulo que formata data para a Exact.
  client.py        # httpx contra a Exact. Traduz os 400 conhecidos em exceções tipadas.
  disponibilidade.py  # grade.py menos o que a Exact acusa como ocupado. Só leitura.
  agendar.py       # a transação de 3 passos, com estado local persistido.
  models.py        # tabela agendamentos (nossa) — ver "estado local"
```

### 1. `horarios.py` — a fronteira do fuso, isolada

O erro de 3 horas (§1) é silencioso: agenda a reunião no horário errado sem falhar em lugar
nenhum. Por isso a formatação vive num arquivo só, e nada mais no módulo chama `strftime`:

```python
SP = ZoneInfo("America/Sao_Paulo")

def para_exact(dt: datetime) -> str:
    """Hora de parede de SP com 'Z' decorativo.

    O 'Z' é MENTIRA e é proposital: a Exact grava o valor verbatim e o
    devolve sem 'Z' em /Meetings (ver AGENDAMENTO_FINDINGS.md §1).
    Converter para UTC de verdade desloca a reunião em 3 horas.
    """
    return dt.astimezone(SP).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
```

Um teste que trave isso vale mais que o comentário — algo que monte um `datetime` às 14h em SP
e afirme que a string termina em `T14:00:00Z`, nunca `T17:00:00Z`. É a linha que alguém vai
"corrigir" daqui a seis meses.

Atenção: `registerDate` e `updateDate` são UTC **de verdade** (§3). Não passe tudo pela mesma
função — só `start` e `end` de box são hora de parede.

### 2. `grade.py` — a grade própria, nas lacunas dos blocos

A grade precisa nascer **evitando** os blocos recorrentes dos consultores, porque `BoxesAdd`
recusa sobreposição (§2) e esses blocos não são agendáveis (§8). Para `comercial@`, os blocos
observados na janela de agosto são:

```
seg–qui   09:00–10:10 · 13:30–14:30 · 15:00–15:45
sex       08:00–09:10 · 13:30–14:30 · 15:00–15:45 · 18:00–19:00
```

Ou seja, as lacunas úteis são grosso modo **10:15–13:25** e **16:00–18:00**. A grade deve ser
**configuração, não constante no código** — esses blocos mudam quando a consultora mexe na
agenda dela, e no dia em que mudarem a grade passa a colidir e o agendamento começa a falhar
com `Boxes are occupied`.

> Recomendo tratar `Boxes are occupied` como sinal operacional, não só como erro: se ele passar
> a aparecer com frequência, a grade desencostou da realidade da agenda.

### 3. `disponibilidade.py` — `$filter` sempre explícito

Para exibir horários livres na LP: pega a grade do dia e subtrai o que a Exact reporta ocupado.

```python
# SEMPRE com $filter — o GET sem filtro corta ~4 semanas de passado (§5)
params = {"$filter": (
    f"salesRepEmail eq '{email}' and "
    f"start ge {para_exact(inicio_dia)} and start le {para_exact(fim_dia)}"
)}
```

Isto é **cosmético**, não é a trava: entre exibir e confirmar, alguém pode ter pego o horário.
Quem decide é o `BoxesAdd` (§8, corolário). Nunca confie nesta leitura para garantir vaga.

### 4. `agendar.py` — a ordem importa

```
1. BoxesAdd (status="available")   ← reversível, e é O LOCK do horário
2. LeadsAdd                        ← se falhar: BoxesRemove limpa (204, sem reunião)
3. scheduleAdd                     ← ponto de não retorno
```

O box vem primeiro **porque é o único passo desfazível**. Invertendo, um `BoxesAdd` que falhe
por conflito deixa lead órfão no CRM, e a única saída seria `LeadsDelete` — que é exclusão dura
e cascateia (§6). **Nunca use `LeadsDelete` como compensação.**

Mapeamento dos erros para a LP:

| Erro da Exact | Passo | Resposta ao visitante |
|---|---|---|
| `Boxes are occupied at the desired time.` | 1 | "Esse horário acabou de ser preenchido" + recarrega a grade |
| `SDR not found.` | 1 | erro nosso de configuração — alerta interno, não expõe |
| `Start time must precede end time.` | 1 | bug nosso — nunca deveria chegar à API |
| `Box is already occupied…` | 3 | não deve ocorrer no fluxo (box recém-criado é `available`); se ocorrer, é corrida — alerta |

### 5. Estado local — a única auditoria possível

Tabela nossa, escrita **antes** de cada chamada, no espírito do que `nat_scheduled_actions` já
faz para ações que podem falhar no meio:

| coluna | por quê |
|---|---|
| `id`, `created_at` | |
| `nome`, `telefone`, `email` | o que veio da LP, antes de existir lead |
| `slot_inicio`, `slot_fim` | hora de parede de SP, `TIMESTAMP` sem tz |
| `sales_rep_email` | |
| `box_id`, `lead_id`, `meeting_id` | preenchidos conforme cada passo passa |
| `passo` | `iniciado` → `box_criado` → `lead_criado` → `agendado` \| `falhou` |
| `erro` | mensagem crua da Exact |

Sem isso não há como responder "quantos agendamentos ficaram pela metade ontem?" — a Exact não
guarda a tentativa que falhou, e `scheduleAdd` nem devolve o `meeting_id` (§4: retorna booleano;
o id só sai de `GET /Meetings?$filter=lead/id eq {leadId}`).

### 6. Faxina de boxes abandonados

Um fluxo que morra entre o passo 1 e o 3 deixa box `available` na agenda da consultora — e
`available` é justamente o que a Exact trata como vago, então pode aparecer como oferta na UI.

Job periódico: para cada linha em `passo='box_criado'` há mais de N minutos, `BoxesRemove` no
`box_id` e marca `falhou`. Funciona porque box sem reunião sai limpo (§8, bônus). Depois do
passo 3 não há faxina possível — é definitivo, e é a premissa aceita.

### 7. Idempotência e concorrência

- **Duplicidade:** `duplicityValidation: false` não protege numa página pública. Antes do
  `LeadsAdd`, procurar lead recente com o mesmo telefone (`GET /Leads?$filter=...`). Vale
  decidir se o mesmo telefone pode agendar duas vezes — hoje pode.
- **Corrida entre visitantes:** resolvida pelo `BoxesAdd` (§8, corolário). Não precisa de lock
  nosso para o horário.
- **Duplo clique do mesmo visitante:** precisa de trava nossa (janela curta por telefone), senão
  viram dois leads em dois boxes. O `BoxesAdd` só protege o mesmo horário, não a mesma pessoa.
- **Rate limit 30 req/20s é do token inteiro**, dividido com o `sync_job` da Exact que já roda a
  cada 600s paginando 500 leads (`exact_spotter.py:88`). Um pico na LP concorre com a ingestão.

### 8. `source` / `subSource` validados na origem

São texto livre resolvido contra cadastro global (§3). Valor errado polui o cadastro de origens,
que é usado em relatório. Fixar como constante do módulo e não aceitar da query string da LP.

### O que ficou fora e continua verdadeiro

- **Não há cancelamento nem remarcação pela API** — premissa aceita, sai pelo WhatsApp. Mas
  vale registrar: o box do agendamento cancelado fica ocupado para sempre. Se a taxa de
  remarcação for alta, a agenda vaza slots ao longo do tempo, e a limpeza é manual na UI.
- **Não testei `duplicityValidation: true`** nem o erro de duplicidade que ele produz.
- **Não testei `BoxesUpdate`** — existe no `$metadata` e pode ser caminho para mover um box sem
  reunião; provavelmente recusa box com reunião, pela mesma mensagem "not possible to change".

---

## 10. E2E da implementação (17/08/2026)

`backend/test_agendamento_e2e.py --sim-eu-quero` — atravessa o caminho **real** de
`fluxo.agendar()`, o mesmo que o `POST /api/agendamento/agendar` chama. Nada mockado: Exact
de produção e banco de produção. Só a grade é trocada por env, para o alvo cair em **2027**.

| # | verificação | resultado |
|---|---|---|
| 1 | `2027-03-17` sem nenhum box para `comercial@` | vazio |
| 2 | fluxo completo | agendamento #1, lead **51434831**, box **43722680**, reunião **4724744** |
| 3 | lead no funil | `etapa=Agendados`, `funil=18535`, `salesRep=comercial@`, `source=Rd Marketing`, `subSource=DialogicasTurma` |
| 4 | box | `status=busy`, `leadId=51434831`, `start=2027-03-17T11:00:00Z` |
| 5 | estado local | `passo=agendado`, slot `2027-03-17 11:00`, e-mail guardado |
| 6 | limpeza | lead excluído (204); box **não removível** (tem reunião) |
| 7 | confirmação | 0 leads "TESTE API", 0 boxes visíveis em 2027-03-17, `$count` de volta a 276 |

**A prova de fuso está no passo 4.** A grade pediu 11:00 e a Exact gravou `11:00:00Z`. Se o
módulo convertesse para UTC, teria gravado `14:00:00Z` e a reunião cairia 3 horas adiantada —
o teste falha explicitamente nesse caso, com a mensagem `FUSO ERRADO`.

### O que o passo 7 ensinou

Na primeira execução ele falhou: `contains(lead,'TESTE API')` ainda devolvia o lead que
`id eq 51434831` já não encontrava. **O `DELETE` não falhou — o índice de texto da Exact
atrasa alguns segundos.** O teste passou a insistir (6 tentativas, 5s) em vez de afirmar de
primeira. Vale para qualquer código que confirme exclusão por busca textual na Exact.

### Resíduo

Box **43722680** — órfão, invisível em todo GET, não bloqueia a agenda. Autorizado de
antemão. A linha de `agendamentos` foi removida e a tabela voltou a zero.

### Suíte offline

`backend/test_agendamento.py` — 11 casos, sem rede e sem banco: grade e antecedência; o fuso
que não converte; slot forjado recusado; subtração de disponibilidade (sobrepor remove,
encostar não); caminho feliz na ordem box->lead->schedule; compensação do passo 2; compensação
do passo 3 **com o lead preservado**; slot ocupado sem tocar em lead nem schedule; duplo
clique; os três desfechos da faxina; e o rate limit por IP.

---

## 11. `subSource`: a API cria o cadastro, e eu criei um sem querer (17/08/2026)

### A correção

§3 afirmava que `LeadsAdd` só casa com cadastros existentes. **Está errado.** O `subSource`
`"DialogicasTurma"` — um nome que inventei para o primeiro teste — voltou resolvido com o
**id 176793**, e eu li o id como prova de que já existia.

`GET /Sources` desmente: 176793 é **o id mais alto de toda a base**, acima de qualquer curso
real. O `LeadsAdd` criou o cadastro na hora. Ele continua lá depois que o lead de teste foi
excluído — a exclusão do lead não desfaz a origem.

> **A regra verdadeira:** `source` e `subSource` são texto livre, e o que não existe **é
> criado**. O cadastro de origens é global e usado em relatório de marketing. Um campo aberto
> vindo de página pública é uma porta para poluir esse cadastro, e o dano é silencioso.

Foi por isso que o módulo ganhou `app/agendamento/origens.py`: allowlist em env, conferida
antes de a chamada sair. O que não está na lista é 400, e nada é criado.

### `PosMulheridades` — a resposta da pergunta

`posgenero` **não** é a pós de Mulheridades. São cursos diferentes, e `posgenero` ainda por
cima é a turma velha.

| subSource | id | leads em `exact_leads` | último lead | o que é |
|---|---|---|---|---|
| **`PosMulheridades`** | 173358 | **120** | 17/08/2026 | **a pós de Mulheridades** |
| `posgenerot2` | 168707 | 325 | 17/08/2026 | pós de Gênero, turma 2 — a viva |
| `posgenero` | 137321 | 109 | 31/10/2025 | pós de Gênero, turma 1 — morta |
| `PosPraticasDialogicasTurma1` | 170904 | 90 | 16/08/2026 | pós de Práticas Dialógicas |
| `DialogicasTurma` | 176793 | 0 | — | **lixo criado por este teste** |

`PosMulheridades` já existe, está ativo e recebe lead hoje. **Não precisa criar nada.**

Todos sob o source `Rd Marketing` (id 106847), que tem 61 subSources no total.

### O que a allowlist tem, e o que ficou de fora

```
AGENDAMENTO_SUBSOURCES=PosMulheridades,posgenerot2,PosPraticasDialogicasTurma1
AGENDAMENTO_SUBSOURCE_PADRAO=PosPraticasDialogicasTurma1
```

Fora de propósito: `posgenero` (turma morta) e `DialogicasTurma` (o lixo). Note que o padrão
mudou — era `DialogicasTurma`, que **nunca deveria ter sido o valor de produção**. O certo é
`PosPraticasDialogicasTurma1`.

A comparação é case-insensitive, mas o valor enviado é o da allowlist com a caixa exata: os
nomes reais misturam convenções (`posgenerot2` e `PosMulheridades` convivem), e mandar
`posmulheridades` criaria um **segundo** cadastro com o mesmo nome em caixa diferente.

### Dívida deixada

`DialogicasTurma` (176793) continua no cadastro de origens. Não há endpoint de escrita para
origem no `$metadata` — só `Sources`, sem `SourcesAdd`/`SourcesRemove`. **A limpeza é manual,
pela UI da Exact.** Não tem lead nenhum apontando para ele, então é cosmético; mas aparece na
lista de origens de quem for montar um relatório.

---

## 12. `leadId` no `/agendar`: o fluxo de duas etapas (18/08/2026)

A LP trocou o formulário do RD Station por form nativo, o que parte o fluxo em duas
requisições — e cria o risco de a mesma pessoa virar dois leads. Três medições novas contra a
API real saíram desta sprint.

### `$filter=id eq {leadId}` é consistente, mas mente na paginação

É o filtro certo para validar um `leadId`: responde na hora, sem o atraso de índice que a
busca textual tem (§10). Id existente devolve o lead; id inexistente devolve **HTTP 200 com
`value: []`**.

A armadilha está no que vem junto:

```json
{"@odata.context":"...#Leads","value":[],
 "@odata.nextLink":"https://api.exactspotter.com/v3/Leads?$filter=id%20eq%20999999999&$skip=500"}
```

**O `@odata.nextLink` aparece mesmo com zero resultados**, apontando para `$skip=500` de um
conjunto vazio. Quem seguir o link para "confirmar que acabou" pagina para sempre. Lista
vazia é resposta final.

Vale também registrar que um `leadId` válido pode apontar para lead em qualquer etapa —
o primeiro lead que peguei de amostra estava em `Descartado`. O módulo valida **existência**,
não estado: um `scheduleAdd` sobre lead descartado o move para `Agendados`, o que é o
comportamento desejado (alguém descartado que voltou a se interessar).

### ⚠️ `phone1` volta com o DDI grudado — e o código estava errado por isso

O `LeadsAdd` recebe `ddiPhone` e `phone` **separados**. O `GET /Leads` devolve `phone1` com
os dois **grudados**. Não é simetria óbvia, e consultar do jeito errado não dá erro nenhum:

| filtro | resultado |
|---|---|
| `phone1 eq '83988046720'` | **0 leads** |
| `phone1 eq '5583988046720'` | **4 leads** |

`client.buscar_lead_por_telefone()` montava o filtro **sem** o DDI desde que foi escrita.
Ela nunca encontrou lead nenhum, e nunca falhou — devolvia `None`, que é indistinguível de
"não existe". Não causou dano porque a trava de duplo clique usa a tabela local e não ela,
mas era uma defesa antiduplicata que não defendia nada. Corrigida nesta sprint.

Detalhe que fecha o diagnóstico: **`ddiPhone` volta `None` em todo lead lido**. O campo existe
na escrita e não na leitura, então não dá para remontar o número a partir dos dois campos —
a concatenação tem que ser feita na consulta.

> Lição geral: na Exact, **filtro que não casa devolve lista vazia, não erro**. Toda consulta
> nova merece uma verificação contra um registro que você sabe que existe, senão o silêncio
> passa por resposta.

### O fuso pegou o próprio teste

O E2E falhou com `esperava 1 slot em 2027-03-18, achei 0`. A causa não tinha nada a ver com a
Exact: `_preparar_grade` calculava o horizonte com `date.today()` (hora do sistema, UTC)
enquanto a grade conta os dias a partir de `agora_sp()`. Rodando 00:0x UTC, `date.today()`
dava `2026-08-18` e `agora_sp().date()` dava `2026-08-17` — horizonte um dia curto, alvo fora
da grade. O mesmo defeito latente estava no E2E de uma etapa. Ambos passaram a usar
`_horizonte_ate()`, que conta em SP.

É a mesma classe de erro de §1, do lado do teste. Vale como aviso: **nada neste projeto deve
chamar `date.today()` ou `datetime.now()` sem fuso** — inclusive teste.

### E2E do fluxo de duas etapas

`backend/test_agendamento_e2e_leadid.py --sim-eu-quero`, alvo **2027-03-18 14:00**, telefone
exclusivo `11999995555` para a contagem ser conclusiva.

| # | verificação | resultado |
|---|---|---|
| 1 | telefone sem lead, data sem box | limpo |
| 2 | etapa 1 (`POST /lead`) | lead **51437955** em `Entrada`, subSource `PosMulheridades` |
| 3 | etapa 2 (`POST /agendar` com `leadId`) | agendamento #5, box **43726884**, reunião **4725239** |
| 4 | **exatamente 1 lead com o telefone** | **1** — nenhum `LeadsAdd` extra ✅ |
| 5 | o lead andou de etapa | `Entrada` → `Agendados`, subSource intacto |
| 6 | fuso | `start=2027-03-18T14:00:00Z` — hora de parede preservada |
| 7 | estado local | `passo=agendado`, `lead_externo=True` |
| 8-9 | limpeza | lead excluído (204), 0 leads, 0 boxes visíveis |

O passo 4 é a razão de o arquivo existir. Se o `leadId` for ignorado em qualquer ponto do
caminho, aparecem 2 leads e um SDR liga duas vezes para o mesmo número — falha que nenhum
teste offline pega, porque o que quebra é a integração inteira.

### Resíduo desta rodada

| Artefato | Destino |
|---|---|
| Leads 51437948 e 51437955 | excluídos, 204 ✅ |
| Linhas em `agendamentos` | removidas, tabela de volta a 0 ✅ |
| **Box 43726883** | **órfão** — da execução que falhou na asserção do telefone ⚠️ |
| **Box 43726884** | **órfão** — da execução boa ⚠️ |

Os dois em 2027-03-18, invisíveis em todo `GET`, sem bloquear a agenda (§8).

**Total de órfãos invisíveis acumulados: 5** (43722204, 43722368, 43722680, 43726883,
43726884).

O primeiro deles é o preço de uma asserção errada minha, não do código: o fluxo tinha
funcionado, e foi a verificação por telefone — sem DDI — que reprovou um resultado correto.
Cada reexecução do E2E custa um box permanente, então **vale conferir a asserção antes de
rodar**, não depois.


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
