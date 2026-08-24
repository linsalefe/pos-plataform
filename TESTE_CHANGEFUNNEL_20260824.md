# TESTE — `ChangeFunnel` intra-funil — 24/08/2026

Item 2 da sprint de fundações. **Resultado: o endpoint NÃO serve para a cadência.**

## O lead de teste

Criado para isto, via `client.criar_lead` (o mesmo caminho da landing page):

| | |
|---|---|
| `leadId` | **51527070** |
| Nome | `ZZ TESTE ChangeFunnel - ignorar` |
| Telefone | 83999990001 |
| source / subSource | `Landing Page` / `PosMulheridades` (da allowlist) |
| Funil / estágio | 18535 / `Entrada` |
| `description` | "Lead criado em 24/08/2026 para testar POST /ChangeFunnel intra-funil… Não trabalhar. Pode ser descartado." |

**Efeito colateral já na criação:** a Exact atribuiu **SDR Thobias** sozinha
(`sdr: Thobias <sdr@cenatsaudemental.com>`), sem pedirmos. `salesRep` ficou nulo.
`LeadsAdd` dispara distribuição de SDR — vale para todo lead que a LP cria.

## T0 — antes

```
stage      : 'Entrada'
funnelId   : 18535
updateDate : 2026-08-24T23:13:10.713443Z
sdr        : Thobias <sdr@cenatsaudemental.com>
salesRep   : None
```

## A ida — RECUSADA

```
POST https://api.exactspotter.com/v3/ChangeFunnel
     {"leadId": 51527070, "stageId": 129985}      # Entrada -> Follow 1, mesmo funil

HTTP 400   0,18 s
{"error":{"code":"","message":"Lead is already at this funnel"}}
```

**`ChangeFunnel` move entre FUNIS, não entre estágios.** O nome já dizia, e o
`RECON_CADENCIA_20260824.md` §3.1 presumiu o contrário — a premissa estava errada, e é
justamente o que este teste existia para descobrir.

Não houve volta a executar: o lead nunca saiu de `Entrada`. **Zero resíduo** além do
próprio lead, que ficou no estágio em que nasceu.

## O que se descobriu no lugar

### 1. A Exact JÁ MANTÉM o histórico de transições

`GET /LeadStages?$filter=leadId eq X` (idem `StagesLead`; `LeadPipelineStages` é o mesmo
agrupado por lead):

```json
{"leadId": 51527070, "originStage": null, "destinationStage": "Entrada",
 "createdAt": "2026-08-24T23:13:10.713443Z", "cycle": 1,
 "discardedStage": false, "discardDate": null,
 "originFunnelId": null, "destinationFunnelId": 18535}
```

E registra movimento **intra-funil** real — de outro lead:

```json
{"leadId": 31485567, "originStage": "Entrada", "destinationStage": "Follow 4",
 "createdAt": "2025-02-13T17:46:38Z", "originFunnelId": 18535, "destinationFunnelId": 18535}
```

Três consequências:

- **Movimento intra-funil existe** — só não é o `ChangeFunnel` que o faz.
- **`originStage: null` = primeira aparição**, exatamente a semântica que escolhi para
  `exact_stage_events.stage_de = NULL`. Convergência independente.
- **`discardedStage` / `discardDate` são um FLAG, não um estágio.** É por isso que
  `Descartado` não aparece em `GET /stages` do 18535 e mesmo assim volta em `stage`
  (§3.3 do recon). O descarte é ortogonal ao estágio.

### 2. Isso muda o Item 1 — mas não o invalida

Construí `exact_stage_events` fazendo diff no sync. A Exact já tem o mesmo dado.

| | `exact_stage_events` (nosso) | `GET /LeadStages` (deles) |
|---|---|---|
| Custo de leitura | SELECT local | 1 chamada HTTP por lead |
| Latência | até 600 s (passo do sync) | tempo real |
| Cobre movimento feito na tela da Exact | sim (via sync) | sim |
| Histórico anterior a 24/08 | **não** | **sim, desde 2025** |
| Sobrevive à Exact fora do ar | sim | não |

O nosso continua útil como gatilho local e barato. Mas para **backfill** e para conferir
uma transição pontual, `LeadStages` é melhor — e teria evitado escrever o diff, se o recon
tivesse checado antes. Registro como correção ao recon.

## O que continua desconhecido

**Nenhum endpoint de escrita de estágio intra-funil foi identificado.** Preparei uma bateria
de tentativas (`StagesLead`, `LeadStages`, `LeadsUpdate`, `LeadsQualification` com formas
variadas de payload) e **não executei**: sondar POST às cegas em endpoints não documentados
do CRM de produção não é teste, é chute com efeito colateral. A trava de permissões da
sessão bloqueou, e concordo com o bloqueio.

`$metadata` declara os quatro como `EntitySet` **sem parâmetros**, então o payload não é
descobrível por lá.

### Como responder isso sem chutar

1. **Documentação da Exact** ou suporte — a pergunta é de uma linha: "qual endpoint move um
   lead entre estágios do mesmo funil?".
2. **Observar a própria Exact**: mover um lead pela TELA e ler `LeadStages` logo depois
   mostra o que ela grava; o DevTools do navegador mostra a chamada que a tela faz.
3. Só então testar, com payload conhecido, neste mesmo lead 51527070.

## O que isso significa para a cadência

A sprint de cadência pressupõe que o agente faça **envio E movimentação**. A movimentação
**não tem caminho conhecido hoje**. Duas saídas:

- **(A)** Descobrir o endpoint (caminho acima) e manter o desenho.
- **(B)** O agente só ENVIA; a movimentação do card segue humana. Perde-se metade do ganho,
  mas o Bloco 4 da cadência deixa de estar bloqueado.

A decisão é do coordenador. Enquanto ela não vem, **os Blocos 0, 1, 3 e 5 do recon seguem
válidos** — só o Bloco 4 (envio + movimentação) depende disto.

## Limitação declarada

**Não consigo verificar se a Exact dispara e-mail ao lead** numa mudança de estágio. Isso só
aparece na caixa da pessoa ou no log da Exact. Como a chamada foi recusada, a pergunta segue
aberta — e continua sendo pré-requisito antes de qualquer movimentação automática.

## Faxina

O lead **51527070** ficou em `Entrada` no 18535, com SDR Thobias. Pode ser descartado pela
tela a qualquer momento. Não foi apagado por API: `LeadsDelete` é exclusão dura e
`LeadsRecover` responde "Lead not found" (FINDINGS §6).
