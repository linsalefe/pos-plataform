# RECON — A jornada do lead, da entrada à venda (Bloco J)

**Data:** 01/09/2026, 20h SP · **Tipo:** somente leitura.
Nenhuma migração, nenhum deploy, nenhum envio. Uma única chamada `GET` à Exact (`/Funnels`),
sem escrita, para nomear os funis — o resto é `SELECT` e `EXPLAIN`.

---

## 0. O veredito curto

**A jornada é medível, custa 1,1 ms, e o número que ela devolve é pequeno de propósito.**

Dos **1.176 leads `Vendidos`** no funil de vendas, **28 são rastreáveis** até a origem — 2,4%.
Não é defeito do cruzamento: `agendamentos` começou a existir em **17/08/2026**, e tudo que
foi vendido antes disso não tem como ser ligado a uma reunião. A seção "Jornada" só pode falar
da coorte de 17/08 em diante, e precisa dizer isso em cima do número.

**A passagem de bastão funciona e está rastreada.** A cadeia completa existe no banco e um
lead a percorreu inteira em **11 horas**: Josiane, 29/08 — `Descartado → Entrada → Follow 1 →
Agendados` no funil de prospecção, e então `Agendados → Contratos Gerados → Vendidos` já no
funil de vendas.

**E é a mesma Josiane que estava na lista dos "não receberam nada".** Ela escreveu pelo botão
da página de obrigado às 02:20, ninguém respondeu no WhatsApp, e às 16:07 estava vendida.
**Dos 9 leads dessa lista, 3 estão `Vendidos`.** A métrica 10 não mede lead perdido — mede
**lead não respondido por este canal**, e chamar aquilo de perda exagera o dano em 3×.

**O agente já entregou para a consultoria.** Desde 24/08 são **9 reuniões da IA** (não 1 — a
janela do relatório anterior fechou em 29/08), repartidas entre as duas consultoras. Uma
delas está em `Contrato Gerado` e outra em `Em Negociação`.

**O funil 25588, que nunca foi nomeado em recon nenhum, é o "Funil - Isa"** — um funil pessoal,
103 leads, 20 `Vendidos`. Ele está dentro de `POS_FUNNEL_IDS`, ou seja, **todo agregado de
"pós" hoje inclui silenciosamente o funil pessoal da gestora.**

---

## 1. Os funis, nomeados (J.7)

Uma chamada `GET /v3/Funnels`, somente leitura:

| id | Nome na Exact | Leads | Etapa dominante | Em `POS_FUNNEL_IDS`? |
|---:|---|---:|---|---|
| 18535 | **Pos Graduacao** | 3 775 | Descartado 3 614 · Agendados 25 | ✅ |
| 18285 | **Intercambio** | 2 493 | Descartado 2 258 · **Vendidos 197** | não |
| 18537 | **Pós Graduação - Vendas** | 1 593 | **Vendidos 1 176** · Descartado 395 | ✅ |
| 21007 | **Vagas Afirmativas** | 1 042 | Descartado 891 · Vendido 6 | não |
| 20647 | **Reativação - SQL** | 197 | Descartado 172 | não |
| 25588 | **Funil - Isa** | 103 | Descartado 79 · **Vendidos 20** | ✅ ⚠️ |
| 20776 | **CONGRESSO PRESENCIAL** | 97 | Descartado 60 | não |

> ⚠️ **`POS_FUNNEL_IDS = {18535, 18537, 25588}`** (`exact_spotter.py:22`, default valendo
> porque a env não está setada). O 25588 é um **funil pessoal**, não um funil de produto. Ele
> entra em qualquer contagem de "pós" — inclusive nas 20 vendas dele. Não é bug de código: é
> uma configuração que ninguém revisitou. **Decisão de produto** no CHECKPOINT.

---

## 2. Quem agendou, e para qual consultora (J.1, J.2)

Janela: **24/08 23:16 UTC → agora**. Fonte: `agendamentos`, que é **nossa** — e não
`exact_leads.sdr_name`, pelo motivo do §2.2 do prompt (395 de 500 leads do 18537 têm como
`salesRep` a Isabela, inativa).

| Ator | Consultora | Leads |
|---|---|---:|
| Página de obrigado | `processoseletivo@cenatcursos.com.br` | 19 |
| Página de obrigado | `comercial@cenatcursos.com.br` | 18 |
| **IA (agente)** | `processoseletivo@cenatcursos.com.br` | **6** |
| **IA (agente)** | `comercial@cenatcursos.com.br` | **3** |
| | **total** | **46** |

**A IA marcou 9 reuniões, não 1.** O "1" do relatório de 29/08 é correto **para aquela
janela**; de lá para cá foram mais 8. A distribuição entre as duas consultoras segue o
rodízio, sem viés visível.

---

## 3. Onde esses 46 estão hoje (J.3)

| Funil | Etapa | Leads | dos quais da IA |
|---|---|---:|---:|
| 18535 Pós Graduação | Agendados | 17 | 4 |
| 18535 | Descartado | 7 | 2 |
| 18535 | Follow 2 | 6 | 0 |
| **18537 Vendas** | **Vendidos** | **6** | 0 |
| 18535 | Follow 3 | 3 | 0 |
| **18537 Vendas** | **Em Negociação** | **2** | **1** |
| **18537 Vendas** | Agendados | 2 | 1 |
| **21007 Vagas Afirmativas** | **Contrato Gerado** | **1** | **1** |
| 18535 | Follow 1 / Follow 4 | 2 | 0 |

**Leitura:** 46 agendaram; **11 atravessaram para um funil de vendas** (9 no 18537, 1 no
21007, e mais um em Agendados lá). Dos 9 da IA, **2 já estão do outro lado** — um em
`Contrato Gerado` e um em `Em Negociação`.

> **Não transforme isso em taxa.** 2 de 9 é 22% e não significa nada com N=9. A seção mostra
> **contagem absoluta e lista nominal**; a taxa entra quando o N sustentar (§7).

---

## 4. A cobertura do vínculo — a pergunta que decide a seção (J.5)

| Pergunta | Resposta |
|---|---:|
| Leads no 18537 (Vendas) | **1 593** |
| … com linha em `agendamentos` (rastreáveis até nós) | **45** |
| … **sem rastro** | **1 548** |
| Leads `Vendidos` no 18537 | **1 176** |
| … **rastreáveis até uma reunião nossa** | **28** |
| Reunião rastreável mais antiga | **17/08/2026** |

**A causa é conhecida e não é um bug:** `agendamentos` tem **310 linhas, a primeira de
17/08/2026, e 100% delas com `lead_id`**. O sistema de agendamento é novo. Tudo que foi
vendido antes de 17/08 — a esmagadora maioria dos 1.176 — foi marcado por outro caminho que
nunca passou pelo nosso banco.

> **Consequência para a página:** a seção Jornada **não pode** mostrar "conversão de vendas".
> Ela mostra **a coorte rastreável**, com o rótulo dizendo desde quando. Qualquer número de
> "% que vendeu" calculado sobre 1.176 seria dividido por um denominador que não conhecemos.

---

## 5. Quem move o lead para o funil de vendas (J.6)

**Medido, e a resposta tem duas metades.**

### 5.1 A cadeia existe e está no banco — o caso Josiane, verbatim

```
lead 31559736 · Josiane Silveira Alencastro
29/08 05:21 UTC  funil 18535   Descartado         → Entrada
29/08 12:15 UTC  funil 18535   Entrada            → Follow 1
29/08 13:29 UTC  funil 18535   Follow 1           → Agendados
29/08 15:04 UTC  funil 18537   Agendados          → Contratos Gerados    ← já no outro funil
29/08 16:07 UTC  funil 18537   Contratos Gerados  → Vendidos
```

Onze horas de `Descartado` a `Vendidos`.

### 5.2 A travessia em si **não deixa evento** — e isso é estrutural

Note o pulo entre a linha 3 e a 4: o lead sai de `Agendados` no 18535 e **reaparece** em
`Agendados` no 18537, sem nenhuma linha registrando a mudança de funil.
`exact_stage_events` grava a transição de **etapa dentro do funil em que o lead está no
momento do sync** — a troca de funil é lida como "o `funnel_id` mudou entre dois syncs", e
não como um evento.

O que se vê no 18537, para todo lead que chega:

| Transição observada no 18537 | n | Leitura |
|---|---:|---|
| `Entrada → Agendados` | 4 | chegou já no funil de vendas |
| `Follow 1/2/3/5 → Agendados` | 11 | idem |
| `(NULO) → Agendados` | 2 | primeira vez que o sync viu o lead ali |
| `Agendados → Contratos Gerados` | 19 | avanço interno |
| `Contratos Gerados → Vendidos` | 21 | **o fechamento** |

De 1.593 leads hoje no 18537, **32 têm histórico no 18535** e **54 têm algum evento no 18537**
— porque `exact_stage_events` só começa em 24/08.

### 5.3 **Se foi humano ou automação do CRM: PENDENTE**

`exact_stage_events` **não tem coluna de ator**. Não há como responder pelo nosso banco, e não
vou chutar.

**O que faltaria:** o endpoint `LeadStages` da Exact, que traz `userAction`,
`originFunnelId` e `destinationFunnelId` por transição. Uma chamada por lead. Para responder
a pergunta bastaria uma amostra de ~20 leads do 18537 — **20 requisições, dentro do limite de
30 req/20 s**, ~15 segundos de execução. **Não fiz** porque o prompt pede propor, não executar,
e porque uma amostra de leitura da API merece decisão explícita.

---

## 6. O que NÃO é medível, com o motivo (J, §2.3)

| Item | Por que não |
|---|---|
| **Comparecimento à reunião** | O `type` (`Vigente`/`Concluido`/`Cancelada`) vive só na API e não é sincronizado. E é **circular**: ele vira `Concluido` no instante da transferência de funil, com data no futuro (`AGENDAMENTO_FINDINGS` §15) — exatamente os leads que avançam para vendas são os que têm o registro corrompido. Medir "reunião realizada" por aí mediria "avançou de funil", que é a outra métrica |
| **Taxa de conversão por ator** | N=9 para a IA. Contagem absoluta e lista nominal; a taxa entra no limiar do §7 |
| **Venda anterior a 17/08** | `agendamentos` não existia. 1.548 dos 1.593 leads do 18537 não têm rastro, e isso não se recupera |
| **Quem executou a troca de funil** | sem coluna de ator; ver §5.3 |
| **`Descartado` como etapa** | é **flag**, não etapa (`discardedStage`/`discardDate` no `LeadStages`), e por isso volta em `stage` sem estar em `/Stages`. Contar "descartados" por `stage` mistura o motivo do descarte com a posição no funil |

---

## 7. ⚠️ O achado que muda um rótulo do painel

Cruzei os leads da métrica 10 (escreveram pelo botão, ninguém respondeu) com a situação atual:

| Contato | Nome | Funil hoje | Etapa hoje |
|---|---|---|---|
| `554192680313` | Mikaelle Beatriz de Souza Juliani | 18537 | **Vendidos** |
| `555199297391` | Josiane Silveira Alencastro | 18537 | **Vendidos** |
| `5511983602996` | ISABELA GUARINO GESTO NODAR | 18537 | **Vendidos** |
| `5521999790187` | RODRIGUES Fabianne dos Santos | 18535 | Pre Qualificado |
| outros 5 | — | (sem lead na Exact) | — |

> **Três de nove estão vendidos.** A pessoa escreveu no nosso WhatsApp, ninguém respondeu, e
> ela comprou assim mesmo — por telefone, pela página, ou com a consultora.

**A métrica 10 não mede lead perdido.** Ela mede **"escreveu neste canal e não foi respondida
neste canal"**. É uma falha de atendimento real e vale ser mostrada — mas rotulá-la como
perda **exagera o dano em 3×** e levaria a decisão errada.

**Rótulo proposto:** *"Escreveram no WhatsApp e não receberam resposta"*, com a subnota
*"algumas dessas pessoas foram atendidas por outro canal — 3 das 9 desta janela fecharam
matrícula."*

*(Nota de método: a Josiane aparece no WhatsApp como `555199297391` e na Exact como
`5551999297391`. O cruzamento só a encontrou por causa da chave tolerante ao 9º dígito.
Com igualdade, este achado não existiria.)*

---

## 8. Custo (J, §2.4)

`EXPLAIN ANALYZE` da consulta da jornada, janela de 30 dias:

```
Seq Scan on agendamentos  (rows=100)  actual time=0.009..0.159
Planning Time:  1,127 ms
Execution Time: 1,138 ms
```

> **1,1 ms.** A falta de índice em `agendamentos.lead_id`, que registrei no recon anterior,
> **não importa aqui**: são 310 linhas e o seq scan custa 0,16 ms. Não crie o índice.

A seção Jornada acrescenta **~1 ms** ao painel. Orçamento total revisado:
**70 ms** (chaves de teste, uma vez por request) + **~76 ms** (todas as queries) ≈ **146 ms**.

---

## 9. Proposta de seção "Jornada"

### 9.1 Esboço

```
┌─ Jornada do lead ────────────────────────────────────────────────────────────┐
│  ⓘ Só dá para ligar uma venda à sua origem desde 17/08/2026, quando o        │
│    sistema de agendamento começou a gravar. Antes disso: 1.548 leads no      │
│    funil de vendas sem rastro — não é ausência de venda, é ausência de       │
│    registro.                                                                 │
│                                                                              │
│  Agendaram (46)      →   Foram para vendas (11)   →   Vendidos (6)           │
│  ├ Página obrigado 37    ├ 18537 Vendas       10       └ nenhum da IA ainda  │
│  └ Agente (Nat)     9    └ 21007 Vagas Afirm.  1                             │
│                                                                              │
│  Por consultora            Agendou   Em vendas   Vendido                     │
│  processoseletivo@             25         6          4                       │
│  comercial@                    21         5          2                       │
│                                                                              │
│  ── Os 46, um a um ──────────────────────────────────────────────────────    │
│  Nome              Origem    Consultora        Situação hoje    Última transição
│  Josiane S. A.     LP        processoseletivo  Vendidos         29/08 16:07  │
│  Marcio ...        Nat       comercial         Contrato Gerado  31/08 10:22  │
│  ...                                                                         │
└──────────────────────────────────────────────────────────────────────────────┘
```

**A tabela nominal é o que torna a seção acionável.** As contagens dizem que o sistema
funciona; a lista diz **quem ligar hoje**.

### 9.2 Esquema JSON (contrato do §5.3 do recon)

```json
{
  "secao": "jornada",
  "periodo": { "de": "2026-08-02T00:00:00", "ate": "2026-09-01T20:00:00",
               "relogio": "America/Sao_Paulo", "dias": 30 },
  "apurado_em": "2026-09-01T20:05:00",
  "metricas": [
    {
      "id": "agendaram",
      "rotulo": "Reuniões marcadas", "valor": { "ia": 9, "landing_page": 37 },
      "n": 46, "relogio": "UTC (agendamentos.created_at) → SP",
      "confianca": "alta",
      "definicao": "Leads com linha em agendamentos, passo='agendado'. origem_ip nulo = agente.",
      "limitacao": null
    },
    {
      "id": "chegou_em_vendas",
      "rotulo": "Atravessaram para um funil de vendas",
      "valor": { "ia": 2, "landing_page": 9 }, "n": 11,
      "relogio": "UTC (exact_leads.funnel_id, no último sync)",
      "confianca": "alta",
      "definicao": "funnel_id atual é 18537 ou 21007.",
      "limitacao": "A troca de funil não gera evento: é inferida da mudança de funnel_id entre syncs. Quem executou a troca não é registrado."
    },
    {
      "id": "vendidos_rastreaveis",
      "rotulo": "Vendas ligadas a uma reunião nossa",
      "valor": 28, "n": 1176,
      "relogio": "UTC (exact_leads.stage)",
      "confianca": "media",
      "definicao": "Leads em 18537/Vendidos que têm linha em agendamentos.",
      "limitacao": "agendamentos começou em 17/08/2026. Os outros 1.148 não são vendas sem origem — são vendas anteriores ao registro. NÃO calcular percentual sobre 1.176.",
      "cobertura": { "desde": "2026-08-17", "rastreaveis": 28, "sem_rastro": 1148 }
    },
    {
      "id": "compareceu",
      "rotulo": "Compareceu à reunião",
      "valor": null, "n": null, "confianca": "nao_medivel",
      "limitacao": "O status da reunião vive só na API e vira 'Concluído' no instante da troca de funil, com data no futuro. Exatamente os leads que avançam são os que têm o registro corrompido."
    }
  ],
  "tabela": [
    { "lead_id": 31559736, "nome": "Josiane Silveira Alencastro", "origem": "landing_page",
      "consultora": "processoseletivo@cenatcursos.com.br", "funil": 18537,
      "etapa": "Vendidos", "ultima_transicao": "2026-08-29T16:07:53" }
  ]
}
```

---

## 10. CHECKPOINT

### 10.1 Engenharia — só o Álefe

| # | Decisão | Recomendação |
|---|---|---|
| **J-E1** | Chaves de teste calculadas **1× por request** e passadas como array (não por query) | **sim** — é o que mantém o painel em 146 ms |
| **J-E2** | Margem de **15 min** no invariante de silêncio (não 10) | **sim** — p99 do agente é 14,3 min |
| **J-E3** | Precedência de **5 vias** nas reuniões (com `ia_incompleta`) | **sim** — hoje é 0, mas o caso `SlotIndisponivel` existe |
| **J-E4** | **Não** criar índice em `agendamentos.lead_id` | **sim** — 1,1 ms; seria peso morto |
| **J-E5** | Seção Jornada entra no MVP | **sim** — 1 ms e é a única que fala de venda |
| **J-E6** | `disparo_skip` antes da página, como você decidiu | **confirmado** — prompt próprio |

### 10.2 Produto — podem precisar da Isa

| # | Decisão | Por quê |
|---|---|---|
| **J-P1** | **O 25588 ("Funil - Isa") deve continuar em `POS_FUNNEL_IDS`?** | Um funil pessoal está dentro do conjunto que define "pós". As 20 vendas dele entram em todo agregado. É configuração, não código — e quem decide é quem usa o funil |
| **J-P2** | **O rótulo da métrica 10** (§7): "não receberam resposta" em vez de "perdidos", com a subnota das 3 vendas | muda como a gestão lê o número. 3 de 9 é diferença de 3× no dano percebido |
| **J-P3** | **O funil por coorte T1/T2 × T3** (C.9 do recon) — e o que fazer com o caminho T3, que converteu **zero** em 19 aberturas | é decisão de roteiro, não de tela |
| **J-P4** | **Amostra de 20 leads no `LeadStages`** para responder quem move o lead (§5.3) | 20 requisições de leitura na API de produção; ~15 s. Barato, mas é acesso a sistema de terceiro e merece um "pode" |
| **J-P5** | **Limiar para mostrar taxa de conversão por ator** | proponho **N ≥ 30 por ator**; abaixo disso, só contagem absoluta e lista nominal |
| **J-P6** | **Backfill do `LeadStages`** (9.299 leads, ~2 h no rate limit) para comparar o mundo antes do agente | **não recomendo agora**: a coorte rastreável começa em 17/08 e o backfill não cria `agendamentos` retroativo — ele daria histórico de etapa, não de origem. Só vale se a pergunta virar "como o funil andava antes", que não é a pergunta desta página |

---

*Recon de 01/09/2026, 20h SP. Somente leitura — nenhum dado alterado, nenhuma mensagem
enviada. Uma chamada GET à Exact (`/Funnels`), sem escrita.*
