# Sprint: `leadId` opcional e formulário nativo na LP (18/08/2026)

Branch: `feat/agendamento-subsource` · Investigação de referência: `AGENDAMENTO_FINDINGS.md`
(§12 é nova desta sprint)

**Está no ar.** Migração aplicada e `cenat-backend` reiniciado em 18/08/2026 00:08 UTC,
validado em produção — ver "Deploy" no fim.

---

## O problema

A LP vai trocar o formulário do RD Station por form nativo, o que parte o fluxo em duas
requisições:

```
index.html (form nativo) --POST /lead-----> lead criado em Entrada
                         --redirect obrigado.html?lead=ID&nome=&email=&tel=
obrigado.html            --POST /agendar--> agenda
```

O `/agendar` sempre fazia `LeadsAdd`. Nesse fluxo, a mesma pessoa viraria **dois leads** no
funil — um do formulário, outro do agendamento — e um SDR ligaria duas vezes para o mesmo
telefone.

---

## O que mudou

### 1. `leadId` opcional no `POST /agendar`

O corpo aceita `leadId` (int > 0, opcional; `lead_id` também é aceito). Presente:

- o `LeadsAdd` é **pulado**;
- o lead é validado por `GET /Leads?$filter=id eq {leadId}` **antes de qualquer escrita** —
  inclusive antes do `BoxesAdd`, senão um id inválido travaria o horário na agenda da
  consultora até a faxina passar;
- lead inexistente → **404** com mensagem clara, e nada é criado em lugar nenhum.

Ausente: comportamento **idêntico ao anterior**. A LP de Mulheridades, que usa o fluxo de uma
etapa, não precisa de nenhuma mudança. O caso 17 da suíte trava essa retrocompatibilidade.

**Compensação.** Falha no `scheduleAdd` → só `BoxesRemove`. O lead é preservado nos dois
fluxos, mas por razões diferentes, e o log diz qual: no lead nosso é decisão de produto (o
contato vale mais que o horário); no externo é que ele **não nos pertence**. `LeadsDelete`
continua proibido como compensação — é exclusão dura e cascateia (findings §6).

### 2. Coluna `agendamentos.lead_externo`

`lead_id` preenchido tem a mesma cara nos dois fluxos. Sem esta coluna não dá para responder
nem "este lead é nosso para mexer?" nem "quantos agendamentos vieram do form nativo?" — que é
exatamente a medida de conversão entre o index e o obrigado.

`BOOLEAN NOT NULL DEFAULT false`. As linhas antigas são todas do fluxo de uma etapa, onde o
lead foi criado por nós: `false` é o valor historicamente correto, não um placeholder.

Migração: `backend/migrate_agendamentos_lead_externo.py` (idempotente, aditiva).

### 3. `POST /lead` — resposta e erros

Já devolvia `lead_id` no corpo; confirmado e mantido. O que mudou foi o erro:

| situação | antes | agora |
|---|---|---|
| Exact não respondeu (rede, timeout, 5xx) | 502 | **503** |
| Exact respondeu recusando | 502 | 502 |
| origem fora da allowlist | 400 | 400 |

Nenhum dos dois é 500: 500 diria "quebrou aqui dentro", e a falha é de dependência externa.
A distinção é para o **front**, não para o visitante — e o front usa ela para decidir seguir
para o obrigado sem `lead=`.

Chave de resposta: `lead_id` (snake), igual ao `/agendar` e ao resto do corpo. `leadId` em
camelCase é aceito só na **entrada** do `/agendar`, que é o formato que o front tem em mãos.

### 4. Snippets

**`docs/form-nativo-snippet.html`** (novo) — nome/email/telefone, zero dependências, telefone
com DDD validado com a mesma regra do backend, timeout de 20s via `AbortController`.

> **A regra que manda: o visitante nunca fica preso.** Se o POST falhar por qualquer motivo,
> a página **redireciona mesmo assim**, sem `lead=` na URL. O obrigado.html percebe a ausência
> e cai no fluxo de uma etapa. Perder o lead na primeira tela é definitivo; um lead duplicado,
> no pior caso, é incômodo para o SDR.

**`docs/obrigado-snippet.html`** (atualizado) — lê `?lead=`, `?nome=`, `?email=`, `?tel=`,
pré-preenche os campos (editáveis: é a última chance de corrigir um telefone errado) e manda
`leadId` no POST. `?lead=` só é aceito se for inteiro positivo; `?lead=abc` vira ausência em
vez de 422. E se o backend responder 404 (id velho, lead excluído), ele **esquece o id e
reenvia sozinho** — sem laço, porque o id é zerado antes do reenvio.

O `var ORIGEM` já existia da sprint anterior. Está nos dois snippets e deve ter o mesmo valor
na mesma LP.

---

## TAREFA 3 — subSource: a resposta

**`posgenero` não é a pós de Mulheridades.** É a turma 1 de Gênero, um curso diferente, e
está morta (sem lead novo desde 31/10/2025).

A que existe é **`PosMulheridades`, id 173358, ATIVA** — confirmada hoje em `GET /Sources` e
com 120 leads em `exact_leads`. **Não precisa criar nada na Exact.**

Ela já estava na allowlist desde o commit `bb219c5`, junto com as outras duas em uso:

```
AGENDAMENTO_SUBSOURCES=PosMulheridades,posgenerot2,PosPraticasDialogicasTurma1
AGENDAMENTO_SUBSOURCE_PADRAO=PosPraticasDialogicasTurma1
```

Duas divergências entre o enunciado da sprint e o repositório, ambas já resolvidas antes
desta entrega:

- a env é `AGENDAMENTO_SUBSOURCE_PADRAO`, não `..._DEFAULT`;
- o padrão **não** é mais `DialogicasTurma` — aquilo era lixo criado por engano na
  investigação (findings §11) e nunca deveria ter sido valor de produção.

`GET /Sources` tem **40 subSources começando com `pos`**, todas ativas, todas sob
`Rd Marketing` (id 106847). A lista completa está no findings; as relevantes:

| subSource | id | o que é |
|---|---|---|
| `PosMulheridades` | 173358 | **a pós de Mulheridades** |
| `posgenerot2` | 168707 | pós de Gênero, turma 2 (viva) |
| `PosPraticasDialogicasTurma1` | 170904 | pós de Práticas Dialógicas |
| `posgenero` | 137321 | pós de Gênero turma 1 — morta, fora da allowlist |
| `DialogicasTurma` | 176793 | lixo da investigação — segue no cadastro, limpeza manual na UI |

---

## Dois bugs encontrados no caminho

### `client.buscar_lead_por_telefone()` nunca encontrou lead nenhum

O `LeadsAdd` recebe `ddiPhone` e `phone` separados; o `GET /Leads` devolve `phone1` com os
dois **grudados**. A função montava o filtro sem o DDI:

```
phone1 eq '83988046720'    -> 0 leads
phone1 eq '5583988046720'  -> 4 leads
```

Consultar errado **não dá erro** — devolve lista vazia, indistinguível de "não existe". A
função existia como defesa antiduplicata e não defendia nada. Não causou dano porque a trava
de duplo clique usa a tabela local, não ela. Corrigida.

> Lição para qualquer consulta nova à Exact: **filtro que não casa devolve vazio, não erro.**
> Verifique contra um registro que você sabe que existe, senão o silêncio passa por resposta.

### O fuso pegou o próprio teste

O E2E falhou com `esperava 1 slot em 2027-03-18, achei 0`. Nada a ver com a Exact:
`date.today()` usa a hora do sistema (UTC) e a grade conta os dias a partir de `agora_sp()`.
Rodando 00:0x UTC, um dava `2026-08-18` e o outro `2026-08-17` — horizonte um dia curto, alvo
fora da grade. O mesmo defeito latente estava no E2E de uma etapa. Os dois passaram a usar
`_horizonte_ate()`, que conta em SP.

É a mesma classe de erro do findings §1, do lado do teste. **Nada neste projeto deve chamar
`date.today()` ou `datetime.now()` sem fuso — inclusive teste.**

---

## Testes

### Offline — `test_agendamento.py`: **17/17** (eram 13)

Quatro casos novos:

| # | caso |
|---|---|
| 14 | `leadId` válido: `LeadsAdd` **pulado**, schedule usa o lead do corpo, `lead_externo=True` |
| 15 | `leadId` inexistente: para **antes do BoxesAdd** — nenhuma escrita em lugar nenhum |
| 16 | `leadId` + `scheduleAdd` falho: box removido, lead externo **intocado** |
| 17 | **regressão**: sem `leadId`, cria o lead como sempre, `lead_externo=False` |

### E2E real — `test_agendamento_e2e_leadid.py`: **9/9**

Alvo 2027-03-18 14:00, telefone exclusivo `11999995555` para a contagem ser conclusiva.

```
  2. ETAPA 1 (POST /lead): lead 51437955 criado, Entrada, subSource PosMulheridades
  3. ETAPA 2 (POST /agendar com leadId): box 43726884, reunião 4725239
  4. EXATAMENTE 1 lead com 11999995555 — nenhum LeadsAdd extra
  5. lead: Entrada -> Agendados, subSource intacto
  6. box: start=2027-03-18T14:00:00Z (hora de parede preservada)
  7. agendamentos#5: passo=agendado, lead_externo=True
```

O passo 4 é a razão de o arquivo existir: se o `leadId` for ignorado em qualquer ponto,
aparecem 2 leads. Nenhum teste offline pega isso — o que quebra é a integração inteira.

### Regressão — 10 suítes, todas verdes

```
test_agendamento.py            17/17     test_nat_duplicata.py           5/5
test_agendamento_cors.py        7/7      test_nat_reagendado.py          5/5
test_nat_flow.py               13/13     test_nat_recuperacao.py          OK
test_nat_guard.py               9/9      test_nat_sprint3.py              OK
test_nat_config_api.py           OK      test_nat_caminho_completo.py     OK
```

### Resíduo

Dois boxes órfãos em 2027-03-18: **43726883** e **43726884**. Invisíveis em todo `GET`, não
bloqueiam a agenda (findings §8). O 43726883 é o preço da asserção errada do telefone — o
fluxo tinha funcionado, quem reprovou foi a verificação. **Total acumulado: 5 órfãos**,
todos registrados no findings §12.

Leads de teste excluídos, tabela `agendamentos` de volta a **0 linhas**.

---

## Deploy — FEITO em 18/08/2026 00:08 UTC

Migração aplicada antes (aditiva, com default; o código antigo ignorava a coluna), depois:

```bash
sudo systemctl restart cenat-backend.service
```

### Validação em produção

| verificação | resultado |
|---|---|
| `cenat-backend` ativo, `/health` | **200** `{"status":"online"}` |
| log de inicialização | sem erro, sem traceback |
| `GET /slots` | **200**, `fallback:false`, 10 dias com vaga |
| `POST /agendar` com `leadId` inexistente | **404** com a mensagem certa |
| `leadId: 0` | **422** (recusado no corpo) |
| slot fora da grade | **400** |
| origem fora da allowlist | **400** |
| nome curto / telefone sem DDD | **422** |
| `POST /lead` alcançável | **400** por origem inválida (sem criar lead) |
| preflight CORS de `lp.cenatsaudemental.com` | **204** com `allow-origin` |
| preflight CORS de domínio estranho | **sem `allow-origin`** — navegador bloqueia |
| `agendamentos` depois de tudo | **0 linhas** — nenhuma escrita |

### Correção do comando de fumaça

A primeira versão deste documento mandava usar `"slot":"2027-03-18T14:00:00"`. **Está
errado** e daria 400, não 404: a validação do slot vem **antes** da do lead em `agendar()`, e
2027 está fora do horizonte de 14 dias da grade de produção. O comando certo pega um slot
real de `GET /slots`:

```bash
SLOT=$(curl -s https://hub.cenatdata.online/api/agendamento/slots \
  | python3 -c "import json,sys;d=json.load(sys.stdin)['dias'];print(d[sorted(d)[0]][0]['id'])")

curl -s -X POST https://hub.cenatdata.online/api/agendamento/agendar \
  -H 'Content-Type: application/json' \
  -d "{\"nome\":\"Fumaca Teste\",\"telefone\":\"11999990000\",
       \"slot\":\"$SLOT\",\"leadId\":999999999}"
# esperado: 404 "O cadastro informado não foi encontrado."
```

Continua **sem escrever nada**: a verificação do lead acontece antes do `BoxesAdd`, então um
`leadId` inventado não chega a criar box nem consumir o slot. Confirmado — a tabela seguiu
em 0 linhas depois de todos os testes acima.

> Note que o rate limit de escrita é 5 requisições / 300s por IP, e os 422 não contam (a
> validação do corpo acontece antes do limitador). Uma bateria de fumaça maior que isso
> começa a receber 429.

### O que falta

Ajustar `var ORIGEM` nos dois snippets para o curso da LP e publicar no repositório da
landing page. O backend está pronto para os dois fluxos.

---

## Fora de escopo (não implementado)

- **RD Marketing** — conversão via API. Decisão pendente, conforme combinado.
- **NAT, kanban, checkout, CORS do Hub** — nada tocado.
- **`LeadsUpdate`** — corrigir nome/telefone no obrigado.html **não** atualiza o lead já
  criado. O valor corrigido vai para a tabela `agendamentos`, e é lá que o SDR confere. Se
  isso incomodar na prática, é uma sprint própria.
