# CASE: faturamento atribuível ao agente de IA × SDR humana (09/11/2026)

**Somente leitura.** SELECT no banco em transação `READ ONLY` e GET na Exact (`$metadata`, `/Leads`, `/LeadsSold`, `/RecommendedProducts`). Nenhuma escrita, nenhum envio pela Meta, nenhum deploy. Script: `backend/case_faturamento.py`. Testes: `backend/test_case_faturamento.py` (escritos, **não executados**). Checkpoint 1.5 aprovado nos 6 pontos antes de somar dinheiro.

Reproduzir:

```bash
cd backend
venv/bin/python case_faturamento.py --de 2026-09-07 --ate 2026-11-08 --cache /tmp/leadssold.json   # comparação
venv/bin/python case_faturamento.py --de 2026-08-27 --ate 2026-11-08 --cache /tmp/leadssold.json   # só agente
```

O cache é o `GET /LeadsSold` inteiro lido em 09/11/2026 ~22h UTC (1.506 linhas). Sem `--cache`, o script relê a Exact.

## Resumo em 6 linhas

1. O valor da venda está em `GET /v3/LeadsSold`, no campo `totalDealValue`. Não está em `/Leads`.
2. De 07/09 a 08/11 o agente marcou a primeira reunião de **40 leads**. **8 compraram**, total de **R$ 43.647,00**, que é 8,0% dos R$ 547.481,00 vendidos por todas as origens no mesmo recorte.
3. 27 desses 40 leads tinham aplicado na LP e não marcado sozinhos. Desses 27, **4 compraram (R$ 26.047,00)**.
4. Reunião marcada pelo agente terminou como `Concluido` em **50% (20/40)**, contra **28% (73/259)** na LP (Fisher p = 0,009). Já reunião→venda é **20% (8/40) contra 13% (34/259)**, diferença **não significativa** (p = 0,23).
5. A SDR fecha mais: 51 vendidos em 88 marcações. 54 dessas 88 pessoas já tinham falado com o agente antes, e 14 vendas da SDR fecharam em até 1 dia da marcação. **Não dá para dizer que o agente vende mais que a SDR.**
6. Achado lateral: `agendamentos.created_at` é hora de SP, não UTC. O comentário de `relatorios.SQL_JORNADA_COORTE` está errado e a página /relatorios desloca 3 h nas pontas do período (§7).

---

## 1. Onde está o valor na Exact (Fase 0)

### 1.1 `$metadata` (`GET /v3/$metadata`, 200, 64.165 bytes)

- `LeadODataDTO` (o que `/Leads` devolve, 31 campos): **nenhum campo de valor.** O único candidato, `leadProduct` (String), vem `null` nos três leads de prova.
- EntitySets com Product/Sale/Sold/Deal/Recommended: `LeadsSold`, `Products`, `ProductsAdd/Remove/Update`, `RecommendedProducts(Add/Remove)`, `PreSalesProduction`, `SellersProduction`, `BusinessForecastByQualificationValue`, `PreSalesPerformance`, `MonthlyDealForecast`.
- **`LeadsSoldODataDTO`**: `id`, `leadId`, `saleDate` (DateTimeOffset), `saleStage`, `cycle` (Int32), **`totalDealValue` (Decimal)**, `products` (Collection de `ProdutoLeadSoldDTO`: `id, quantity, individualValue, discountAmount, discountType, fullValue, finalValue, name`), `salesRep` e `preSales` (`id, name, lastName, email`).
- `RecommendedProductsODataDTO` (`labelValue`, `amount`...) é o produto recomendado, antes da venda.

### 1.2 Leads de prova (JSON, sem os dados pessoais)

Lead 51423437. A UI mostra Vendidos e R$ 6.500,00.

`GET /v3/Leads?$filter=id eq 51423437` (campos pessoais tirados: nome, telefone, descrição com CPF e endereço, links, e-mails):

```json
{"id": 51423437, "stage": "Vendidos", "funnelId": 18537, "registerDate": "2026-08-16T21:17:26.8503987Z",
 "updateDate": "2026-08-25T15:00:51.857734Z", "leadProduct": null, "closingForecastDate": null,
 "subSource": "PosPsicologiaClinicaeSaudeMentalturma2"}
```

`GET /v3/LeadsSold?$filter=leadId eq 51423437`:

```json
[{"leadId": 51423437, "saleDate": "2026-08-25T15:00:51.6547185Z", "saleStage": "Contratos Gerados", "cycle": 1,
  "totalDealValue": 6500.0, "id": 1237280,
  "products": [{"id": 135275, "quantity": 1, "individualValue": 6500.0, "discountAmount": 0.0, "discountType": "",
                "fullValue": 6500.0, "finalValue": 6500.0, "name": "<omitido>"}],
  "salesRep": {"id": 415967, "...": "<omitido>"}, "preSales": {"id": 443274, "...": "<omitido>"}}]
```

`GET /v3/RecommendedProducts?$filter=leadId eq 51423437`: `[]`.

Lead 51782459 (origem `ia`):

```json
{"id": 51782459, "stage": "Vendidos", "funnelId": 18537, "leadProduct": null, "subSource": "PosBoasPraticasEAD"}
[{"leadId": 51782459, "saleDate": "2026-09-11T19:48:49.8724551Z", "saleStage": "Contratos Gerados", "cycle": 1,
  "totalDealValue": 4400.0, "id": 1242603,
  "products": [{"id": 273397, "quantity": 1, "individualValue": 4400.0, "discountAmount": 0.0, "fullValue": 4400.0, "finalValue": 4400.0}],
  "salesRep": {"id": 430634}, "preSales": {"id": 443275}}]
```

Lead 51766210 (origem `sdr_exact`):

```json
{"id": 51766210, "stage": "Vendidos", "funnelId": 18537, "leadProduct": null, "subSource": "Pos Enfermagem em Saude Mental"}
[{"leadId": 51766210, "saleDate": "2026-09-09T03:00:00Z", "saleStage": "Contratos Gerados", "cycle": 1,
  "totalDealValue": 6800.0, "id": 1242182,
  "products": [{"id": 285571, "quantity": 1, "individualValue": 6800.0, "discountAmount": 0.0, "fullValue": 6800.0, "finalValue": 6800.0}],
  "salesRep": {"id": 415967}, "preSales": {"id": 443275}}]
```

`RecommendedProducts` volta `[]` nos três.

### 1.3 O campo

| pergunta | resposta |
|---|---|
| campo | `LeadsSold.totalDealValue` (Decimal, R$) |
| endpoint | `GET /v3/LeadsSold`, filtro `leadId eq N`, ou a lista inteira paginada por `$skip` (4 páginas de 500) |
| por lead ou por produto | por **venda**. `products[]` traz cada item, e em 1.506 de 1.506 linhas `sum(finalValue) = totalDealValue`. Uso o total e não somo de novo os produtos |
| mais de um produto | 1.363 vendas com 1 produto, 14 com 2, 2 com 3, 127 com **nenhum** |
| mais de uma venda por lead | `cycle` vai de 1 a 8. 1.506 linhas para 1.497 leads. Regra aprovada: vale a **primeira venda com `saleDate` >= dia da marcação** |
| valor ausente | 128 de 1.506 linhas com `totalDealValue` 0 ou nulo (127 sem produto). Entram como "sem valor informado" e ficam fora da soma |
| data da venda | `saleDate`, UTC. Às vezes é digitada à mão (`T03:00:00Z` = 00:00 SP, data sem hora), então a comparação com a marcação é feita **por dia** |
| `saleStage` | a etapa em que o lead estava quando foi vendido (1.263 "Contratos Gerados", 169 "Contrato Gerado", 21 "Agendamento SDR", 18 "Agendamentos"...). Não é a etapa atual |
| o valor muda depois da venda? | **não verificável com uma leitura.** `LeadsSold` não tem data de alteração e o `updateDate` do lead muda por qualquer edição. O cache de 09/11 é a referência, com releitura em D+7 anotada |
| quem fechou | `LeadsSold.salesRep` (o vendedor da venda). Em 15 vendas da coorte ele difere da consultora da reunião (§4.3) |

---

## 2. Período

| item | data (SP) | fonte |
|---|---|---|
| primeiro agendamento da LP | 17/08/2026 18:29 | `agendamentos` passo='agendado' com `origem_ip` |
| **primeiro agendamento do agente** | **27/08/2026 15:46** | `agendamentos` passo='agendado' sem `origem_ip` |
| primeira reunião no espelho | horário 07/09/2026 | `reuniao_status.slot_inicio`. A carga inicial do Bloco 0 leu reuniões a partir de 07/09 |
| pausa do agente | 17/09 a 27/09/2026 (religado 27/09 15:27 SP) | memória `pausa-qualificacao-2099`. **Zero** marcações `ia` entre 14/09 10:02 e 28/09 09:40 |

- **Comparação: 07/09 a 08/11/2026.** A partir de 07/09 as três origens existem e toda reunião marcada está no espelho, então `concluídas` e `sdr_exact` são medíveis para todo mundo.
- **Só agente: 27/08 a 08/11/2026.** 13 reuniões `ia` têm horário antes de 07/09, e para elas "concluída" não é medível. Nesse recorte `sdr_exact` não é comparável.
- **A pausa não muda o resultado.** Ela não tem marcações, então não há o que separar. O efeito dela é tirar 11 dias de agente das duas janelas, e setembro tem menos marcações `ia` por isso (§4.4). A comparação por taxa não é afetada; os absolutos do agente ficam menores do que seriam.

---

## 3. Definições (aprovadas no checkpoint 1.5)

Toda contagem exclui os leads de teste de `relatorios.chaves_de_teste` (20 chaves de telefone em 09/11) e fica nos funis de pós (18535, 18537, 21007, 25588). Ficaram de fora da coorte de comparação 5 leads cuja primeira marcação foi antes de 07/09 (remarcação de reunião antiga) e 1 lead de Intercâmbio. 2 vendas do período são de lead com marcação anterior a 07/09 e não entram em nenhuma linha.

| termo | definição | relógio | N (comparação) | confiança |
|---|---|---|---|---|
| marcação | `agendamentos` passo='agendado' (`created_at`) ou `reuniao_status` origem='exact' (`registrado_em`). Vale a **primeira** do lead. As outras no período são remarcação e não mudam a atribuição | SP | 387 leads | alta |
| `ia` | primeira marcação = agendamento **sem** `origem_ip`, feito pelo agente na conversa | SP | 40 | alta |
| `landing_page` | primeira marcação = agendamento **com** `origem_ip`, a pessoa marcou no site | SP | 259 | alta |
| `sdr_exact` | primeira marcação = reunião marcada na Exact, em lead **sem** `passo='agendado'` anterior. Inclui quem aplicou na LP e não marcou | SP | 88 | alta |
| ↳ sem toque do agente | nenhuma fala do agente (`qualif_conversa`, aberturas T1/T2/T3, `nat_b_*`) para o telefone antes da marcação | SP | 34 | media |
| ↳ assistida pelo agente | o agente falou com a pessoa antes de a SDR marcar. **Nunca somada com `ia`** | SP | 54 | media |
| concluída | o lead tem alguma reunião `Concluido` no espelho com horário >= dia da marcação. Depende de a consultora registrar o feedback: reunião sem feedback fica `Vigente` | SP | 155 | media |
| vendido | `exact_leads.stage='Vendidos'` **hoje**, tirando quem tem só venda anterior à marcação (2 casos, ambos `sdr_exact`). Vendido sem linha em `LeadsSold` conta como vendido sem valor | UTC (estado de hoje) | 100 | media |
| faturamento | soma de `LeadsSold.totalDealValue` da primeira venda com `saleDate` >= dia da marcação. Valor 0 ou ausente fica fora da soma e é contado em "sem valor" | UTC | 89 vendas com valor | alta |
| ticket médio | faturamento / vendas com valor | | | alta |
| reunião→venda | vendidos / leads da linha. **Taxa só com N >= 30** (`N_MINIMO_TAXA`) | | | media |
| concluída→venda | vendidos com reunião concluída / concluídas. Taxa só com N >= 30 | | | media |
| venda sem reunião nossa | venda em `LeadsSold` com `saleDate` no período, funil de pós, lead **sem nenhuma** marcação nossa nem na Exact | UTC | 7 | alta |
| remarcação | lead com mais de uma marcação no período: 5 `ia`, 29 `landing_page`, 3 sem toque, 5 assistidas. Fora da atribuição | SP | 42 | alta |

**Natureza da coorte `ia` (ajuste 1).** Dos 40 leads, **27 tinham aplicado na LP** (linha `lead_criado`, `falhou` ou `recusado` em `agendamentos` antes da marcação do agente) e não marcaram sozinhos. É a maioria, então a coorte fica registrada como **"leads que a LP perdeu e o agente recuperou"**: 27 leads, 4 vendidos, R$ 26.047,00. Os outros 13 são leads da Exact que o agente abordou pelo roteiro de qualificação sem que tivessem aplicado na LP: 4 vendidos, R$ 17.600,00. Estado do agente nos 40: 19 Fluxo B, 18 qualificação com origem Exact, 1 com origem LP, 2 sem estado gravado.

**O contrafactual dos 27 não é zero**, ao contrário do que o ajuste 1 previa. A SDR faz o mesmo trabalho: 61 dos 88 leads `sdr_exact` também têm registro de aplicação na LP sem agendamento próprio, e quem os marcou foi a SDR. Sem o agente, parte desses 27 seria marcada pela SDR. O número honesto é "o agente marcou primeiro", não "sem o agente seria zero". Ver §7.

**`relatorios.metrica`** (impresso pelo script):

- `fat_ia`: valor 43647.0 · N=8 · confiança media · relógio SP (marcação) e UTC (stage e saleDate). Limitação: o agente marca; quem fecha é a consultora.
- `fat_assistido`: valor 198311.0 · N=33 · confiança **baixa**. Limitação: não diz quanto o agente pesou; nunca somar com o direto.
- `taxa_ia`: 8 · N=40 · media. `taxa_lp`: 34 · N=259 · media.
- `concluida_venda_ia`: **não medível como taxa**, N=20 < 30. Contagem: 8 de 20.

---

## 4. Tabelas

### 4.1 Tabela principal (2.2), 07/09 a 08/11/2026

Coorte = primeira marcação no período. Venda = qualquer venda até hoje (09/11) com `saleDate` >= marcação.

| origem | reuniões (leads) | concluídas | vendidos | com valor | faturamento | ticket médio | reunião→venda | concluída→venda |
|---|---|---|---|---|---|---|---|---|
| ia (marcada pelo agente) | 40 | 20 | 8 | 8 | R$ 43.647,00 | R$ 5.455,88 | 20,0% (8/40) | 8 de 20 (N < 30, sem taxa) |
| landing_page (a pessoa no site) | 259 | 73 | 34 | 31 | R$ 201.282,00 | R$ 6.492,97 | 13,1% (34/259) | 43,8% (32/73) |
| sdr_exact sem toque do agente | 34 | 23 | 17 | 13 | R$ 78.494,00 | R$ 6.038,00 | contagem só | contagem só |
| sdr_exact **assistida pelo agente** | 54 | 39 | 34 | 33 | R$ 198.311,00 | R$ 6.009,42 | contagem só | contagem só |
| venda sem reunião nossa | não se aplica | não se aplica | 7 | 4 | R$ 25.747,00 | R$ 6.436,75 | não se aplica | não se aplica |
| **total** | 387 | 155 | 100 | 89 | **R$ 547.481,00** | R$ 6.151,47 | | |

Detalhe por linha:

- **ia:** 5 remarcaram. 0 sem valor, 0 sem `LeadsSold`, 0 venda antes da marcação. Os 8 vendidos tiveram reunião `Concluido`. **0 vendas em até 1 dia da marcação**; mediana marcação→venda de 2,8 dias.
- **landing_page:** 29 remarcaram. 3 vendidos sem valor (2 com valor 0, 1 sem linha em `LeadsSold`). 2 vendidos sem reunião `Concluido` no espelho. 3 vendas em até 1 dia; mediana de 3,9 dias.
- **sdr_exact sem toque:** 3 remarcaram. 4 sem valor (3 sem linha em `LeadsSold`, 1 com valor 0). 4 vendas em até 1 dia; mediana de 2,9 dias.
- **sdr_exact assistida:** 5 remarcaram. 1 sem valor. 3 vendidos sem `Concluido` no espelho. **10 vendas em até 1 dia**; mediana de 2,1 dias.
- **venda sem reunião nossa:** as 7 estão em Vendidos hoje; 3 sem valor.
- Fora de todas as linhas: 2 vendas `sdr_exact` com `saleDate` **anterior** à marcação (a reunião foi registrada depois da venda).

**Sobre `sdr_exact` (ajuste 3).** Pela regra, a linha entra só com contagem e faturamento. A SDR marca quem já está pronto: **14 das 51 vendas `sdr_exact` fecharam em até 1 dia da marcação** (4 sem toque, 10 assistidas). No agente foram **0 de 8**. A diferença de conversão reflete em boa parte o momento em que cada um marca, não a qualidade de quem marca.

**Comparação de taxas, só `ia` × `landing_page`** (os dois com N >= 30):

| taxa | ia | landing_page | intervalo 95% (Wilson) | teste exato de Fisher |
|---|---|---|---|---|
| reunião→venda | 20,0% (8/40) | 13,1% (34/259) | ia 10,5–34,8% · LP 9,5–17,8% | p = 0,23, **não significativo** |
| reunião concluída | 50,0% (20/40) | 28,2% (73/259) | ia 35,2–64,8% · LP 23,1–34,0% | p = 0,009, significativo |

### 4.2 Três leituras do faturamento (ajuste 4)

| leitura | o que é | valor | vendas com valor | parte do total |
|---|---|---|---|---|
| (a) **direto do agente** | coorte `ia` | **R$ 43.647,00** | 8 | 8,0% |
| ↳ incremental: a LP perdeu e o agente marcou primeiro | `ia` que aplicou na LP antes | R$ 26.047,00 | 4 | 4,8% |
| (b) **assistido pelo agente** | `sdr_exact` em que o agente falou antes | **R$ 198.311,00** | 33 | 36,2% |
| (c) **total do período** | todas as origens + venda sem reunião nossa | **R$ 547.481,00** | 89 | 100% |

**(a) e (b) nunca se somam como "do agente".** Em (b) a SDR marcou e a consultora fechou. O agente pode ter pesado muito ou nada, e o dado não separa isso.

No recorte só agente (27/08 a 08/11): `ia` = 53 leads, 12 vendidos, **R$ 68.147,00**. Desses, 37 a LP perdeu (7 vendidos, R$ 46.147,00) e 16 foram abordados na Exact (5 vendidos, R$ 22.000,00). Reunião→venda de 22,6% (12/53). Concluídas: 20, com 12 sem espelho, não medível para elas.

### 4.3 Consultora da primeira marcação × origem (2.3), 07/09 a 08/11

| consultora | origem | leads | concluídas | vendidos | faturamento | reunião→venda |
|---|---|---|---|---|---|---|
| comercial@ | ia | 19 | 8 | 2 | R$ 10.900,00 | 2 de 19 (N < 30) |
| comercial@ | landing_page | 165 | 36 | 18 | R$ 102.441,00 | 10,9% (18/165) |
| comercial@ | sdr_exact sem toque | 18 | 11 | 8 | R$ 48.600,00 | 8 de 18 (N < 30) |
| comercial@ | sdr_exact assistida | 32 | 21 | 20 | R$ 120.229,00 | 62,5% (20/32) |
| processoseletivo@ | ia | 21 | 12 | 6 | R$ 32.747,00 | 6 de 21 (N < 30) |
| processoseletivo@ | landing_page | 94 | 37 | 16 | R$ 98.841,00 | 17,0% (16/94) |
| processoseletivo@ | sdr_exact sem toque | 11 | 8 | 6 | R$ 23.094,00 | 6 de 11 (N < 30) |
| processoseletivo@ | sdr_exact assistida | 21 | 17 | 13 | R$ 72.135,00 | 13 de 21 (N < 30) |
| sdr@cenatsaudemental | sdr_exact sem toque | 5 | 4 | 3 | R$ 6.800,00 | 3 de 5 (N < 30) |
| sdr@cenatsaudemental | sdr_exact assistida | 1 | 1 | 1 | R$ 5.947,00 | 1 de 1 (N < 30) |

As duas consultoras convertem diferente na mesma origem: na LP, 10,9% contra 17,0%. No agente as contagens vão na mesma direção (2 de 19 e 6 de 21), sem taxa. Quem fecha pesa tanto quanto quem marca, e o N do agente por consultora não permite separar uma coisa da outra. Em 15 vendas, quem fechou (`LeadsSold.salesRep`) não é a consultora da reunião.

### 4.4 Agente por mês da marcação (2.4), recorte 27/08 a 08/11

Contagem só: nenhum mês tem N >= 30.

| mês | marcações ia | concluídas | vendidos | faturamento | reunião→venda |
|---|---|---|---|---|---|
| ago (desde 27/08) | 6 | 0 (6 sem espelho) | 1 | R$ 6.800,00 | 1 de 6 |
| set (**pausa 17 a 27/09**) | 18 | 5 (6 sem espelho) | 6 | R$ 32.447,00 | 6 de 18 |
| out | 24 | 11 | 4 | R$ 24.500,00 | 4 de 24 |
| nov (até 08/11) | 5 | 4 | 1 | R$ 4.400,00 | 1 de 5 |

Leads marcados em outubro e novembro ainda têm tempo para comprar. A mediana marcação→venda é de 2,8 dias, mas a cauda existe. Não leia queda de conversão nesta tabela.

### 4.5 Vendas fechadas no período por `LeadsSold.saleDate` (2.5), 07/09 a 08/11

Aqui o relógio é a data da venda, não a data da marcação.

| origem do lead | vendas | com valor | faturamento |
|---|---|---|---|
| ia | 8 | 8 | R$ 43.647,00 |
| landing_page | 33 | 31 | R$ 201.282,00 |
| sdr_exact sem toque | 14 | 13 | R$ 78.494,00 |
| sdr_exact assistida | 33 | 32 | R$ 191.511,00 |
| venda sem reunião nossa | 7 | 4 | R$ 25.747,00 |
| marcação antes do período | 2 | 1 | R$ 4.400,00 |
| **total** | **97** | 89 | **R$ 545.081,00** |

Por mês da venda: set, 40 vendas, R$ 210.470,00; out, 48 vendas, R$ 281.923,00; nov (até 08/11), 9 vendas, R$ 52.688,00.

Esta tabela difere da 4.1 por três motivos:

- os 4 vendidos sem linha em `LeadsSold` (1 LP, 3 sem toque) não têm data de venda;
- 1 venda assistida tem `saleDate` 09/11, fora da janela (R$ 6.800);
- as 2 de marcação anterior entram aqui.

### 4.6 Coorte `ia` por roteiro de abertura (2.6)

O roteiro é a primeira família de abertura que o agente mandou antes da marcação (`messages.nat_etapa`). Fluxo B ganhou linha própria. N baixo, contagem só.

| roteiro | 07/09 a 08/11: leads | vendidos | faturamento | 27/08 a 08/11: leads | vendidos | faturamento |
|---|---|---|---|---|---|---|
| Fluxo B (aplicou na LP sem marcar) | 21 | 4 | R$ 22.100,00 | 21 | 4 | R$ 22.100,00 |
| t1_t2 (formação conhecida) | 10 | 2 | R$ 12.747,00 | 19 | 5 | R$ 32.847,00 |
| t3 (precisa perguntar a formação) | 9 | 2 | R$ 8.800,00 | 13 | 3 | R$ 13.200,00 |

O T3, que em 25/08 "convertia zero" (memória `t3-e-quem-nao-veio-do-formulario`), tem 3 vendas no recorte longo.

---

## 5. Limitações

1. **Vendas antes de 17/08/2026 não têm origem.** `agendamentos` começou em 17/08 e o espelho de reuniões em 07/09. Dos 1.283 Vendidos do funil 18537, 111 estão ligados a uma reunião nossa (`SQL_VENDIDOS_RASTREAVEIS`). Não calcule percentual sobre 1.283.
2. **"Vendido" é estado de hoje.** Um lead que saiu de Vendidos não conta, e outro que vai entrar amanhã ainda não conta. Os leads marcados em out e nov ainda estão em andamento.
3. **Valor ausente:** 11 vendidos da coorte sem valor (3 LP, 4 sem toque, 1 assistida, 3 sem reunião nossa). Estão fora da soma e não foram estimados por preço de tabela. Na base inteira, 128 de 1.506 vendas têm valor 0.
4. **O agente não fecha venda.** Ele marca a reunião; a consultora fecha. Na mesma origem, a conversão muda bastante de uma consultora para outra (§4.3).
5. **`sdr_exact` inclui leads que o agente tocou antes: 54 de 88** (34 dos 51 vendidos). Fica a linha "assistida", que não diz quanto o agente pesou.
6. **A SDR marca no fim do funil:** 14 vendas em até 1 dia da marcação, contra 0 no agente. Comparar a conversão do agente com a da SDR compara momentos diferentes, não competência.
7. **N pequeno no agente:** 40 leads e 8 vendas. A diferença de conversão contra a LP não é estatisticamente significativa (p = 0,23). Só a diferença de reunião concluída é (p = 0,009).
8. **"Concluída" depende do feedback da consultora.** Reunião realizada sem registro fica `Vigente`. Se as consultoras registram diferente por origem, a taxa de concluídas absorve isso.
9. **O toque do agente** é medido pela chave tolerante do telefone (`thread_sql`). Um lead que conversou com o agente por outro número aparece como "sem toque".
10. **`saleDate` às vezes é só a data**, por isso a comparação com a marcação é feita por dia. Uma venda registrada no mesmo dia da marcação, antes dela, conta como posterior.
11. **O valor pode ter sido editado** depois da venda e não há como saber. O retrato é de 09/11.
12. **Contrafactual:** os 27 leads "que a LP perdeu" não seriam todos perdidos sem o agente, porque a SDR também recupera esse perfil (61 dos 88 `sdr_exact`).

---

## 6. Números para o conteúdo

Cada frase vem com a ressalva que precisa ir junto. Nada de nome de pessoa nem de cliente sem autorização escrita do CENAT.

1. **"Em dois meses, as reuniões marcadas pela nossa IA geraram R$ 43,6 mil em matrículas de pós-graduação."**
   Ressalva: a IA marca a reunião e quem fecha a venda é a consultora. São 8 matrículas em 40 reuniões, de 7 de setembro a 8 de novembro de 2026, e o agente ficou 11 dias pausado nesse intervalo.

2. **"Mais da metade das pessoas que a IA levou até a reunião tinha preenchido o formulário do site e desistido de marcar sozinha. Dessas, saíram R$ 26 mil em matrículas."**
   Ressalva: a equipe comercial também recupera esse tipo de contato, então não dá para dizer que todo esse valor estaria perdido sem a IA. O que dá para dizer é que a IA chegou primeiro.

3. **"Reuniões marcadas pela IA acontecem com mais frequência: metade delas foi realizada, contra pouco mais de um quarto das marcadas direto no site."**
   Ressalva: "realizada" é o registro que a consultora faz depois da reunião. A diferença é estatisticamente consistente, mas a amostra da IA é de 40 reuniões.

4. **"Das reuniões marcadas pela IA, 1 em cada 5 virou matrícula; nas marcadas direto no site, pouco mais de 1 em cada 8."**
   Ressalva: com 40 reuniões, essa diferença ainda pode ser acaso. Use como indício, não como prova, e diga o tamanho da amostra.

5. **"Em duas de cada três vendas em que a equipe comercial marcou a reunião, a pessoa já tinha conversado com a IA antes."**
   Ressalva: isso mostra que a IA está presente no caminho, não quanto ela pesou na decisão. Esse faturamento não pode ser somado ao da IA.

6. **"No período, o comercial de pós vendeu R$ 547 mil; as reuniões marcadas diretamente pela IA respondem por 8% disso."**
   Ressalva: os 8% são só o que a IA marcou sozinha. Não incluem as vendas em que ela conversou antes e a equipe marcou depois.

7. **"A IA marca a reunião mais cedo na jornada: nenhuma das vendas dela fechou no mesmo dia da marcação, enquanto a equipe comercial marca muitas vezes quem já está pronto para comprar."**
   Ressalva: por isso as taxas de conversão da IA e da equipe não são comparáveis entre si.

**Frase que NÃO pode ser dita:** "o agente vende mais que a SDR". O dado mostra o contrário no absoluto (a SDR marcou 88 reuniões e teve 51 vendas; o agente marcou 40 e teve 8). O agente e a SDR atuam em momentos diferentes da jornada, e a maior parte das vendas da SDR passou antes pelo agente. Também não pode ser dito: "a IA gerou R$ 241 mil" (a soma de direto com assistido) e "sem a IA essas vendas não existiriam".

---

## 7. Desvios do plano, com motivo

1. **`agendamentos.created_at` é SP, não UTC.** O plano e o comentário de `relatorios.SQL_JORNADA_COORTE` dizem UTC. Medido: 322 de 322 agendamentos com `meeting_id` batem na hora com `reuniao_status.registrado_em` (o `registerDate` UTC da Exact convertido para SP), com diferença de 0 h nas duas origens. Tratar como UTC punha a marcação do agente 3 h antes da conversa que a originou e zerava o toque do agente. O script usa SP. **`relatorios.py` não foi tocado** (só leitura). Os números do §1.2 do checkpoint (40 / 259 / 8 / 34, rastreáveis 111 de 1.283) vieram das funções da página, com o bind `para_utc`, e portanto com as pontas deslocadas em 3 h. É uma correção a abrir.
2. **`sdr_exact` redefinido** (aprovado no checkpoint): a reunião marcada na Exact conta em lead sem `passo='agendado'` anterior, não "sem linha em `agendamentos`". A regra literal perdia 61 leads, 37 deles vendidos.
3. **`LeadsSold` lido inteiro** (4 GETs paginados) em vez de um GET por lead. Dá o mesmo dado com menos requisições contra a cota de 30 req/20 s.
4. **2.5 por `LeadsSold.saleDate`** no lugar de `exact_stage_events` (aprovado). `exact_stage_events` tem 161 eventos para Vendidos desde 25/08 e perde transições.
5. **O contrafactual do ajuste 1 não é zero.** A coorte foi registrada como "a LP perdeu e o agente recuperou", como pedido, mas com a ressalva de que a SDR também recupera esse perfil (61 dos 88 `sdr_exact`). Escrever "contrafactual zero" seria falso.
6. **2.6 ganhou a linha Fluxo B**, porque metade da coorte `ia` (21 de 40) entrou por ele e não por T1/T2/T3.
7. **Dados pessoais tirados dos JSONs de prova.** A descrição do lead 51423437 traz CPF, endereço e e-mail. A decisão 6 pede nenhum nome, e o resto foi tirado pelo mesmo motivo. Os JSONs completos ficaram só no scratchpad da sessão.
8. **Commit:** a atribuição usa o modelo que fez o trabalho (Claude Opus 5.5) em vez da linha "Fable 5.1" do plano, e não leva o link de sessão do plano, que é de outra sessão.

## 8. Observações pra depois (NÃO feitas agora)

- **Reler `LeadsSold` em 16/11 (D+7)** e comparar `totalDealValue` linha a linha com o cache de 09/11, para saber se o valor muda depois da venda.
- **Corrigir o relógio de `agendamentos.created_at` em `relatorios.py`:** o comentário e o bind `para_utc` de `SQL_JORNADA_COORTE`. Conferir também `case_metrics.py` e quem mais converte `agendamentos.created_at`.
- Custo por venda (tokens, template da Meta, hora da SDR): outro recon.
- Gravar `totalDealValue` e `saleDate` em `exact_leads` no sync de 10 min, para a /relatorios mostrar faturamento sem bater na Exact.
- Tempo até a venda por origem: a mediana já saiu aqui (ia 2,8 d, LP 3,9 d, SDR assistida 2,1 d), mas falta a distribuição.
- Medir quanto tempo separa o último toque do agente da marcação da SDR na linha "assistida", para separar "o agente aqueceu ontem" de "o agente falou há dois meses".
- Se o case for publicado, pedir autorização do CENAT por escrito e combinar o que pode sair (números absolutos ou só taxas).
