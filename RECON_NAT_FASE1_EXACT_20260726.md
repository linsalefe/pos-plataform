# Recon Fase 1 — a API do Exact permite mudar estágio? (2026-07-26)

Sprint NAT Blocos 5 e 7, Fase 1. Trava o item 3 da Fase 5 ("estágio no Exact para Aguardando
Ligação"). Tudo aqui foi obtido com chamadas **somente de leitura**. **Nenhuma escrita foi
executada** — o motivo está na seção "Por que o teste controlado não foi executado".

## Resposta curta

| Pergunta | Resposta |
|---|---|
| Existe endpoint para alterar estágio na v3? | **Sim** — `POST /v3/ChangeFunnel` com `{leadId, stageId}` |
| A etapa "Aguardando Ligação" existe? | **Não.** Nenhum dos 65 estágios ativos da conta tem esse nome, em nenhum funil |
| O teste controlado de escrita foi feito? | **Não** — não é reversível no lead escolhido (ver abaixo) |
| Consequência para a sprint | **Plano B**: só anotação na timeline. Fase 5 item 3 sai do escopo |

## Como o endpoint foi descoberto

O `exact_spotter.py` só usa `GET /Leads` e `POST /timelineAdd`; `exact_routes.py` acrescenta
`GET /Funnels`, `GET /Persons`, `GET /QualificationHistories`. Nenhum deles escreve estágio, e
não há doc da v3 no repo. A fonte de verdade foi o próprio serviço:

    GET https://api.exactspotter.com/v3/$metadata     (OData CSDL, 64.165 bytes)

O metadata lista **101 entity sets** e **zero Actions/Functions** — nesta API toda escrita é um
`POST` num entity set cujo nome é o verbo (é o padrão que `TimelineAdd` já segue no código).

Candidatos a "mudar estágio", com o DTO que o metadata declara:

| Entity set | DTO | Serve? |
|---|---|---|
| **`ChangeFunnel`** | `{leadId: Int32, stageId: Int32}` | **Sim.** É o alvo |
| `StagesLead` / `LeadStages` | `{leadId, originStage, destinationStage, createdAt, cycle, discardedStage, discardDate, originFunnelId, destinationFunnelId}` | Não — é o **histórico** de movimentação, leitura |
| `LeadPipelineStages` | `{leadId, stages: Collection(...)}` | Não — leitura do pipeline do lead |
| `Stages` | `{id, value, active}` | Não — é o **catálogo** de estágios, leitura |
| `LeadsUpdate` | `{key, lead: LeadEstruturaCriacao..., duplicityValidation, ...}` | Update genérico do lead; caminho mais pesado e arriscado que o `ChangeFunnel` |
| `SkipSteps` | `{id, stageId}` | Configuração de pular etapas, não movimentação |

O nome `ChangeFunnel` engana: o corpo **não** tem `funnelId`, só `stageId`. Como cada `stageId` é
único e pertence a um funil, mandar o estágio já determina o funil — é a assinatura de um
"mover lead para o estágio X", que é exatamente o que a Fase 5 pediria.

Note também: **não existe `StagesAdd`**. A lista de `*Add` da API é `BoxesAdd`,
`CustomFieldsAdd`, `GroupsAdd`, `LeadsAdd`, `OrganizationAdd`, `PersonsAdd`, `ProductsAdd`,
`RecommendedProductsAdd`, `ScheduleAdd`, `TaskAdd`, `TimelineAdd`, `UserAdd`, `WebhooksAdd`,
`WhatsAppAdd`. Criar estágio é mudança de configuração, só pela interface do Exact.

## A etapa "Aguardando Ligação" não existe

`GET /v3/Stages` devolve **65 estágios, todos `active: true`**. Nenhum contém "aguard", "ligac"
ou "ligaç". Os nomes existentes são do vocabulário de funil de vendas: `Entrada`,
`Primeiro Contato`, `Pré Qualificado`, `Follow 1`..`Follow 9`, `Reagendamento`, `Agendados`,
`Em Negociação`, `Contrato Gerado`, `Vendidos`, `Sem contato`, `Objeções - Whatsapp`,
`Reativação - Final do Mês`, e variantes com sufixo de pessoa (`- Vick`, `- Vi`, `- Vi Amorim`).

O catálogo global não diz a que funil cada estágio pertence, então a checagem foi cruzada com o
estágio real dos leads já ingeridos, por funil de pós (`exact_leads`, 2026-07-26):

    18535 Pos Graduacao         Descartado 3442 · Follows 5 28 · Entrada 20 · Follow 3 17 ·
                                Follow 2 17 · Follows 8 14 · Follow 4 13 · Follows 7 9 ·
                                Reagendamento 9 · Follow 1 7 · Primeiro Contato 5 ·
                                Pré Qualificado 4 · Follows 6 3 · Follows 9 2 · Agendados 1 ·
                                Reativação - Final do Mês 1
    18537 Pós Graduação-Vendas  Vendidos 1094 · Descartado 369 · Em Negociação 14 ·
                                Agendados 8 · Contratos Gerados 3
    25588 Funil - Isa           Reativação - Final do Mês 64 · Vendidos 14 · Descartado 5 ·
                                Em Negociação 1

Confirma o catálogo: **não há estágio de "aguardando ligação" em nenhum funil de pós**. Não
existe `stageId` para mandar no `ChangeFunnel`, e o endpoint funcionar ou não é irrelevante
enquanto isso for verdade.

## Por que o teste controlado não foi executado

O plano mandava: um lead já `Descartado`, de funil que não seja 18535, anotar o estágio
original, alterar, **reverter imediatamente**. O candidato natural era o lead 51007323
(`Descartado`, funil 18537). A leitura mostrou que **a reversão não é garantida**:

**`Descartado` não é um estágio.** Não aparece nos 65 itens de `/Stages`, logo **não tem
`stageId`**. É um estado paralelo do lead — o metadata confirma, com `discardedStage: Boolean` e
`discardDate` no DTO de histórico, e com entity sets próprios `LeadsLost`, `LeadsRecover` e
`DiscardReasons`.

Então o `ChangeFunnel` num lead `Descartado` seria de mão única: ele **tiraria o lead do
descarte** e o poria num estágio ativo do funil de vendas, e não haveria `stageId` de volta para
`Descartado`. Desfazer exigiria `LeadsLost` — endpoint nunca usado por este código, com DTO não
verificado, e que provavelmente pede motivo de descarte, gravando um descarte novo com data de
hoje em vez de restaurar o original. Ou seja: o teste sujaria permanentemente um lead de
produção do funil de vendas, e ainda geraria movimentação falsa no histórico e nas métricas de
pré-vendas que o funil 18537 alimenta.

A instrução da Fase 1 é explícita — "se qualquer passo for incerto, **não executar** e reportar".
A reversão é o passo incerto. **Não executei.**

A alternativa de usar um lead **não** descartado (ex.: um dos 8 `Agendados` do 18537, cujo
estágio tem `stageId` e portanto seria revertível) foi descartada por ser pior: seria escrever
num lead de venda **ativo**, e o plano escolheu `Descartado` justamente para não fazer isso.
Como a etapa de destino não existe, o teste não desbloquearia nada de todo modo.

## O que isso muda na sprint

**Fase 5 item 3 (estágio no Exact) sai do escopo desta sprint.** A transferência fica com
notificação ao SDR + anotação na timeline via `add_timeline_comment` (que já funciona, é o único
`POST` de escrita no Exact hoje) + `sla_check` agendado + `transferido_em`. O plano B já estava
previsto no próprio plano.

**Para desbloquear depois, na ordem:**

1. **Álefe cria o estágio "Aguardando Ligação"** na interface do Exact, no funil 18535 (não há
   API para criar estágio). Definir se ele entra antes ou depois de `Primeiro Contato`.
2. Ler o `stageId` novo com `GET /v3/Stages` e guardá-lo em config, **nunca** hard-coded — pelo
   mesmo motivo que canal e template da boas-vindas saíram de constante para
   `auto_welcome_config`: constante apontando para id que não existe é falha silenciosa.
3. Só então testar `POST /v3/ChangeFunnel` — e aí o teste é seguro de verdade, porque mover um
   lead **de** `Aguardando Ligação` **para** o estágio anterior é reversível: os dois lados têm
   `stageId`.

Enquanto (1) não acontecer, `ChangeFunnel` não tem para onde apontar.

## Registro literal das chamadas

Todas com header `token_exact: <EXACT_SPOTTER_TOKEN>` e `Content-Type: application/json`.

    GET /v3/$metadata                          200 · 64.165 bytes de CSDL
    GET /v3/Funnels                            200 · 7 funis ativos
    GET /v3/Stages                             200 · 65 estágios, todos active=true
    GET /v3/Leads?$filter=id eq 51007323       200 · stage "Descartado", funnelId 18537
    GET /v3/StagesLead?$filter=leadId eq ...   200 · value: [] (o $filter é ignorado; devolve
                                                     @odata.nextLink com $skip=500)
    GET /v3/LeadPipelineStages?$filter=...     TIMEOUT em 30s

Dois achados de operação, de graça: o `$filter` do `StagesLead` é **ignorado** pelo serviço (ele
devolveu lista vazia e um `nextLink` paginando o conjunto todo) e o `LeadPipelineStages`
**estourou 30s**. Nenhum dos dois serve para consulta síncrona dentro do webhook.

**Nenhum POST foi emitido. Nenhuma mensagem de WhatsApp foi enviada. Nenhum dado do Exact foi
alterado.**
