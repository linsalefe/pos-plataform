# EMENDA aos recons de 01/09 — as duas conferências, o `POS_FUNNEL_IDS` e a amostra do `LeadStages`

**Data:** 02/09/2026 · **Tipo:** somente leitura.
Nenhuma migração, nenhum deploy, nenhum envio. `SELECT` no nosso banco + as **20 chamadas
`GET /LeadStages`** autorizadas no §4 do prompt. Nada mais foi chamado na Exact.

Emenda a `RECON_JORNADA_LEAD_20260901.md` (§0, §1, §2, §3, §5.2, §5.3, §9.1, §9.2, J-P1) e
confirma o predicado de teste de `RECON_RELATORIOS_20260901.md` §C.10.3 contra esta coorte.

---

## 0. O que mudou, em quatro linhas

1. **A tabela do §3 tem dois erros que se cancelam no total.** Quem atravessou para um funil
   de vendas são **10**, não 11 — e **3 são da IA**, não 2. O JSON do §9.2 vai para a tela
   errado nos dois campos.
2. **Um lead de teste está dentro dos 46**: o próprio SDR Thobias. Sai pela cesta EXCLUIR.
   O total vira **45**. Os `test_agendamento_e2e*` **não** poluem — nenhum deles tem linha
   em `agendamentos`.
3. **Você estava certo sobre o `POS_FUNNEL_IDS`, e mais ainda do que escreveu.** Quem governa
   hoje é a config da tela, não a constante — e a boas-vindas está **desligada**. O 25588
   está **dormente**: zero leads novos desde 19/08, zero boas-vindas, zero NAT.
4. **A amostra do `LeadStages` não responde a pergunta do §5.3, porque o campo não existe.**
   Não há `userAction` em lugar nenhum das 102 transições. Parei, como combinado. Mas as 20
   chamadas trouxeram outra coisa: **a troca de funil É um evento na Exact** — o §5.2 está
   errado ao chamá-la de estrutural.

---

# §3.1 — As contas do §3, refeitas

## 3.1.1 Primeiro: qual é a coorte, exatamente

Os "46" do recon **não reproduzem** com o corte que o cabeçalho declara (01/09, 20h SP).
Reproduzem, na vírgula, com o corte em **≈ 01/09 17:00 UTC**:

| corte de `created_at` | LP proc | LP comercial | IA proc | IA comercial | total |
|---|---:|---:|---:|---:|---:|
| **≤ 01/09 17:00 UTC** | **19** | **18** | **6** | **3** | **46** ✅ igual ao §2 |
| ≤ 01/09 23:05 UTC (20h SP) | 21 | 19 | 6 | 3 | 49 |
| agora (02/09) | 22 | 19 | 6 | 3 | 50 |

Ou seja: as consultas rodaram no meio da sessão e o documento foi escrito às 20h. **Não é
erro de número, é erro de rótulo** — mas ele impede qualquer um de reproduzir a tabela.
Daqui para a frente a coorte congelada é `passo='agendado'` **entre 24/08 23:16 e 01/09
17:00 UTC**; é sobre ela que todo o resto desta emenda fala.

> **Para a página:** o JSON já tem `periodo.ate` e `apurado_em`. O que faltou foi **usá-los
> como o corte real da query**, não como carimbo escrito depois. Este é um bug de página
> esperando para acontecer.

## 3.1.2 A tabela do §3, corrigida

```sql
SELECT el.funnel_id, el.stage, count(*), count(*) FILTER (WHERE a.origem_ip IS NULL) AS da_ia
FROM agendamentos a JOIN exact_leads el ON el.exact_id = a.lead_id
WHERE a.passo='agendado'
  AND a.created_at >= '2026-08-24 23:16' AND a.created_at <= '2026-09-01 17:00'
GROUP BY 1,2 ORDER BY 3 DESC;
```

| Funil | Etapa | Leads | da IA | vs. §3 do recon |
|---|---|---:|---:|---|
| 18535 | Agendados | 17 | 4 | ok |
| 18535 | Descartado | 7 | 2 | ok |
| 18535 | Follow 2 | 6 | 0 | ok |
| **18537** | **Vendidos** | **6** | 0 | ok |
| 18535 | Follow 3 | 3 | 0 | ok |
| **18537** | **Em Negociação** | **2** | **1** | ok |
| 18535 | Follow 1 | 1 | 0 | ok (estava fundida com Follow 4) |
| 18535 | Follow 4 | 1 | 0 | ok (idem) |
| 18535 | **Reagendamento.** | **1** | 0 | ⚠️ **linha ausente no recon** |
| **18537** | **Agendados** | **1** | **1** | ⚠️ recon dizia **2** |
| **21007** | **Contrato Gerado** | **1** | **1** | ok |
| | **total** | **46** | **9** | |

**Os dois erros são iguais e opostos** — uma linha inflada em +1, uma linha omitida de 1 — e
por isso o total de 46 fechava e ninguém viu. Foi isso que produziu os "10" do 18537.

## 3.1.3 Quem está certo, item por item

| Onde | O que diz | Veredito |
|---|---|---|
| §3, **texto** | "9 no 18537" | ✅ **certo** (6 + 2 + 1) |
| §3, **tabela** | linhas do 18537 somam 10 | ❌ errado (a linha `Agendados` é 1, não 2) |
| §3, **texto** | "**11** atravessaram" | ❌ errado — **são 10** |
| §9.1, esboço | "18537 Vendas **10** · 21007 **1** → **11**" | ❌ errado — **9 · 1 → 10** |
| §9.2, JSON | `chegou_em_vendas: {ia: 2, lp: 9}, n: 11` | ❌ errado — **`{ia: 3, lp: 7}, n: 10`** |
| §0 | "Dos 9 da IA, **2** já estão do outro lado" | ❌ errado — **3** |
| §9.1 | "Vendidos (6) — nenhum da IA ainda" | ✅ certo |

### De onde nasceu cada divergência

**O "11"** é **contagem dupla, e ela está escrita na própria frase**: *"9 no 18537, 1 no
21007, e mais um em Agendados lá"*. Esse "mais um em Agendados" **já está dentro dos 9** —
o 18537 tem 6 Vendidos + 2 Em Negociação + 1 Agendados. 9 + 1 = **10**.

**O "ia: 2"** é mais sério, porque **o rótulo e o número foram calculados por regras
diferentes**. O `definicao` do próprio JSON diz `funnel_id atual é 18537 ou 21007` — por essa
regra são 3. O número 2 veio do §0 (*"uma em Contrato Gerado e outra em Em Negociação"*), que
conta **etapas avançadas** e esquece o Luigi, que está em `18537 / Agendados`. Ele atravessou:
está no funil de vendas.

### Os 10 que atravessaram, nominalmente (esta é a lista que vai para a tela)

| Lead | Nome | Origem | Consultora | Funil | Etapa |
|---:|---|---|---|---:|---|
| 51644254 | Luigi Silvino D | **IA** | processoseletivo@ | 18537 | Agendados |
| 51666080 | Alexandra Batista Valdevite | **IA** | processoseletivo@ | 18537 | Em Negociação |
| 51610927 | Kaylla Soares Ponciano de Castro | **IA** | processoseletivo@ | 21007 | Contrato Gerado |
| 51554851 | Amanda Pavão Matana | LP | processoseletivo@ | 18537 | Em Negociação |
| 51574518 | Amanda Cristina Gontijo Silva | LP | processoseletivo@ | 18537 | Vendidos |
| 51643663 | Isis Raquel Santos de Sousa | LP | processoseletivo@ | 18537 | Vendidos |
| 51588427 | Lucas Becker Delwing | LP | processoseletivo@ | 18537 | Vendidos |
| 51636347 | Luciana Maria da Silva Ribeiro | LP | comercial@ | 18537 | Vendidos |
| 51573391 | Mikaelle Beatriz de Souza Juliani | LP | processoseletivo@ | 18537 | Vendidos |
| 51579817 | Natália Nordin de Oliveira | LP | comercial@ | 18537 | Vendidos |

## 3.1.4 O `chegou_em_vendas` corrigido

```json
{
  "id": "chegou_em_vendas",
  "rotulo": "Atravessaram para um funil de vendas",
  "valor": { "ia": 3, "landing_page": 7 }, "n": 10,
  "relogio": "UTC (exact_leads.funnel_id, no último sync)",
  "confianca": "alta",
  "definicao": "funnel_id atual é 18537 ou 21007. Conta a TRAVESSIA, não a etapa: um lead em 18537/Agendados já atravessou.",
  "limitacao": "A troca de funil não aparece em exact_stage_events — mas ELA EXISTE no LeadStages da Exact (originFunnelId → destinationFunnelId); ver §5.2 revisto. Quem executou a troca continua sem registro."
}
```

---

# §3.2 — O predicado de teste aplicado aos 46

**Sim, foi aplicado agora. Estava sujo: 1 de 46.**

Predicado das duas cestas do `RECON_RELATORIOS` §C.10.3, com o `translate()` de desacentuação
do §C.1, rodado sobre **`agendamentos.nome` E `exact_leads.name`** dos 50 (não só dos 46,
para cobrir também as linhas novas).

### Cesta EXCLUIR — 1 lead

| Campo | Valor |
|---|---|
| `agendamentos.id` / `lead_id` | 233 / **51593541** |
| Nome | **Thobias Justino França** (casa o token `thobias justino`) |
| `source` / `sub_source` | Landing Page / Pos Saude do Trabalhador |
| **`sdr_name`** | **Thobias** — é o próprio SDR preenchendo o formulário |
| Telefone | 5567999151808 (fora do bloco `558398804xxxx`) |
| Mensagens | 2 outbound, **0 inbound** |
| Situação | 18535 / Descartado, consultora `comercial@`, LP |

Ele entra em **EXCLUIR** pelo ramo **"zero inbound"** — não pelo telefone, que é legítimo.
É o caso que a cesta foi desenhada para pegar: nome de teste + nenhuma conversa.

### Cesta DUVIDOSO — 0 leads

A Ana Cristina (o único duvidoso da base) **não está nesta coorte**: o `agendado` dela é de
**23/08**, antes do corte de 24/08 23:16. Nada a decidir aqui.

### Os `test_agendamento_e2e*` — **não poluem**, e agora está medido

Os cinco telefones fixos (`11999997777`, `11999996666`, `11999996161`, `11999993333`,
`11999995555`) e os cinco nomes (`TESTE API Alefe E2E…`) **não têm uma única linha em
`agendamentos`**. As linhas de teste que existem na tabela são outras, e todas caem fora
sozinhas:

| Linha | Por que não conta |
|---|---|
| `Álefe … teste` (ids 11/12, 15/16, 23/24) | `agendado` em **17/08** — antes da janela |
| `ANA CRISTINA … - TESTE` (136/137) | `agendado` em **23/08** — antes da janela |
| `zzz teste` (193), `teste` (238) | `passo='lead_criado'` — o filtro `passo='agendado'` já derruba |

> **Nota de método:** o `passo='agendado'` está fazendo metade do trabalho de higiene sem
> ninguém ter pedido. Isso é sorte, não desenho — o predicado tem de rodar de qualquer jeito.

### Os números com o predicado aplicado

| | recon (46) | **corrigido (45)** |
|---|---:|---:|
| Total | 46 | **45** |
| Página de obrigado · `processoseletivo@` | 19 | 19 |
| Página de obrigado · `comercial@` | 18 | **17** |
| **IA** · `processoseletivo@` | 6 | **6** |
| **IA** · `comercial@` | 3 | **3** |
| 18535 / Descartado | 7 | **6** |
| Atravessaram para vendas | (11) | **10** — inalterado pelo predicado |
| Vendidos entre eles | 6 | **6** |

**Os 9 da IA não mudam.** O lead de teste é da landing page. Nenhum número da IA nesta
coorte foi contaminado.

Os números do §4 do recon (cobertura do vínculo) também não mudam — o Thobias está no 18535,
e a coorte do §4 é do 18537. Reconferidos hoje: **1 592** leads no 18537, **44** com linha em
`agendamentos`, **1 176** Vendidos, **28** rastreáveis, `agendamentos` com **319** linhas,
primeira em **17/08**, 100% com `lead_id`. (1593→1592 e 45→44: um lead saiu do 18537 desde
ontem. A conclusão do §4 é a mesma.)

---

# §2 — O `POS_FUNNEL_IDS`: você está certo, e o caso é ainda mais fraco do que o §1 dizia

## 2.1 Item 1 — quem governa na prática

```
SELECT id, funnel_ids, enabled FROM auto_welcome_config WHERE id = 1;

 id | enabled | funnel_ids        | updated_at
  1 | f       | 18535,18537,25588 | 2026-08-24 21:32:28
```

**Quem governa é a config da tela.** `funnel_ids` está preenchido, então
`_funnels_from_config` devolve o CSV parseado e **`POS_FUNNEL_IDS` nunca é alcançado** — o
`return POS_FUNNEL_IDS` da linha 40 é fallback morto enquanto essa coluna tiver conteúdo.

Os dois conjuntos são **idênticos por coincidência**, não por vínculo. Consequência prática:
**mexer na env não muda nada**; quem quiser tirar o 25588 tem de fazê-lo pela tela.

E o dado que muda a urgência da pergunta: **`enabled = false`.** A boas-vindas automática
está desligada desde **24/08 21:32** — duas horas antes de o agente ser ligado
(`nat_config.qualificacao_start_at = 24/08 23:16`). Foi o checklist de ativação do agente.
**Hoje ninguém recebe boas-vindas automática, em funil nenhum.**

## 2.2 Item 2 — os outros usos do conjunto

`POS_FUNNEL_IDS` tem **exatamente dois consumidores**, ambos via `_funnels_from_config`:

| Local | O que decide |
|---|---|
| `exact_spotter.py:210` — passo 2 de `send_welcome_to_new_lead` | **guardrail de funil**: `funnel_id` fora do conjunto → `skipped / not_pos_funnel` |
| `exact_spotter.py:553` — dentro de `sync_exact_leads` | só lead **novo** cujo funil está no conjunto entra em `new_leads_to_contact` |

**Um lead no 25588 É elegível ao agente.** O passo 2 está **antes** do passo 4.5, que é onde
o agente assume a abertura no lugar da boas-vindas. Reprovar no guardrail de funil mata as
duas coisas; passar libera as duas. Não há um conjunto para a boas-vindas e outro para a NAT
— **é o mesmo conjunto para os dois**.

> **Mas o guardrail só governa o caminho do sync.** O caminho da LP não é filtrado por funil
> — não tem como ser, porque o funil é atribuído pela Exact *depois* da criação do lead.
> **Prova no dado:** das 126 conversas da NAT, **1 é de um lead no funil 21007 (Vagas
> Afirmativas), que não está no conjunto** — a Kaylla, `origem='lp'`. E das 20 do 18537, 2
> também são `origem='lp'`.
>
> | funil | `origem='exact'` (passa pelo guardrail) | `origem='lp'` (não passa) |
> |---:|---:|---:|
> | 18535 | 92 | 12 |
> | 18537 | 18 | 2 |
> | **21007** | **0** | **1** ⚠️ |
>
> Ou seja: **o conjunto de funis não é o escopo do agente. É o escopo do sync.** Qualquer
> texto de painel ou de política que disser "a NAT atende os funis X, Y, Z" está errado.

## 2.3 Item 3 — o que o 25588 recebeu desde 24/08

**Nada. Zero nos três.**

| Pergunta | Resposta | Como foi medido |
|---|---:|---|
| Leads **novos** no 25588 desde 24/08 | **0** | `register_date` máximo do funil é **19/08/2026** |
| Boas-vindas enviadas no 25588 desde 24/08 | **0** | `welcome_sent_at` máximo é **18/08/2026** |
| Conversas da NAT com lead do 25588 | **0** | nenhum dos 126 `nat_qualificacao_state` aponta para lead do 25588 |

Histórico completo do funil, para contexto: 103 leads (o mais antigo de **24/05/2025**),
`welcome_status` = 89 `skipped` · 12 `delivered` (a última em 18/08) · 2 `failed`.

**O 25588 está dormente.** Ele já recebeu boas-vindas automática no passado — 12 pessoas —
mas não recebe nada desde 18/08, e não recebe lead novo desde 19/08.

## 2.4 §1 do `RECON_JORNADA_LEAD`, reescrito

> ~~O 25588 está dentro de `POS_FUNNEL_IDS`, ou seja, todo agregado de "pós" hoje inclui
> silenciosamente o funil pessoal da gestora.~~
>
> **`POS_FUNNEL_IDS` não é filtro de agregado — é filtro de automação, e nem isso ele é
> hoje.** A ingestão é governada por `INGEST_FUNNEL_IDS`, que está **vazio** = puxa todos os
> funis da Exact (é por isso que este mesmo §1 conseguiu contar Intercâmbio, Vagas
> Afirmativas e Congresso, nenhum deles no conjunto). Os agregados do relatório saem das
> nossas queries, que filtram `funnel_id` explicitamente. **O 25588 não polui agregado
> nenhum.**
>
> O que o conjunto decide é **quem recebe abertura automática pelo caminho do sync** — hoje,
> a abertura do agente, já que a boas-vindas está desligada (`auto_welcome_config.enabled =
> false` desde 24/08 21:32). E quem governa esse conjunto na prática é a coluna
> `funnel_ids` da tela, não a env: os dois valores coincidem, mas é a config que manda.
>
> **Um lead novo no funil pessoal da gestora seria atendido pela NAT.** Não foi, porque o
> funil está dormente: zero leads novos desde 19/08, zero boas-vindas desde 18/08, zero
> conversas da NAT — sempre.

## 2.5 J-P1, reescrito

| # | Decisão | Por quê |
|---|---|---|
| **J-P1** *(revisto)* | **A NAT e a boas-vindas devem agir no funil pessoal da gestora (25588)?** | Não é sobre contagem — o 25588 não entra em agregado nenhum. É sobre **atendimento**: enquanto ele estiver na lista de funis da tela, um lead novo lá ganha abertura automática do agente. Hoje isso é hipotético (funil dormente desde 19/08), e por isso **a pergunta pode esperar a Isa sem prejuízo**. O que **não** pode continuar é a redação: nenhum documento pode voltar a dizer que o 25588 "entra na contagem de pós" |
| **J-P1b** *(novo)* | **`INGEST_FUNNEL_IDS` vazio é intencional?** | É o que traz Intercâmbio (2 493), Vagas Afirmativas (1 042), Reativação e Congresso para dentro de `exact_leads`. Toda query de relatório precisa filtrar `funnel_id` **explicitamente** — e uma que esquecer vai contar 9 300 leads em vez de 3 800, sem erro visível. Isso é armadilha de página, e vale um teste |

---

# §4 — A amostra do `LeadStages` (J-P4): **a pergunta não é respondível por aqui**

## 4.1 O que foi feito

20 chamadas `GET /v3/LeadStages?$filter=leadId eq X`, somente leitura, 0,8 s entre elas
(dentro do teto de 30 req/20 s), **20/20 com HTTP 200**, **102 transições** devolvidas.

Amostra escolhida como o prompt pediu — **todos rastreáveis**, todos do 18537, todos com
linha em `agendamentos`: os **9 da era do agente** (25/08 em diante: Amanda Pavão, Mikaelle,
Amanda Cristina, Natália, Lucas, Luciana, Isis, Luigi, Alexandra) e **11 anteriores**
escolhidos para cobrir as etapas (Vendidos, Descartado, Agendados, Contratos Gerados).

## 4.2 O resultado: **não existe `userAction`**

O payload tem **nove campos, e nenhum é ator**. Inventário sobre as 102 transições:

```
leadId · originStage · destinationStage · createdAt · cycle
discardedStage · discardDate · originFunnelId · destinationFunnelId
```

Não há `userAction`, `user`, `userId`, `createdBy` nem equivalente — **em nenhuma das 102
linhas, em nenhum dos 20 leads**. A hipótese do §5.3 (*"o endpoint `LeadStages` traz
`userAction`"*) **está errada** para esta conta / esta versão da API.

> **§5.3 continua PENDENTE, e o caminho proposto para resolvê-lo está fechado.** Parei aqui,
> como combinado — nenhuma segunda rodada de chamadas.

**O que resta, se a pergunta importar:** ou um endpoint diferente da Exact (timeline /
auditoria — teria de ser descoberto, e é outra conversa com o fornecedor), ou aceitar que a
pergunta não é respondível e **tirá-la do escopo da página**. Recomendo o segundo: nenhuma
métrica do painel depende dela.

## 4.3 O subproduto: **o §5.2 está errado, e isso é bom**

O §5.2 afirma que a travessia de funil *"não deixa evento e isso é estrutural"*. **Deixa.**
Só não deixa **no nosso banco**:

```
lead 51573391 · Mikaelle
  2026-08-27T13:57:00Z   originFunnelId 18535  Agendados
                      →  destinationFunnelId 18537  Contratos Gerados
```

**20 de 20 leads da amostra têm a travessia registrada** — 22 travessias no total, todas
saindo do 18535. O que se perde é a **nossa** cópia: `exact_stage_events` grava
`stage_de → stage_para` carimbando o `funnel_id` do momento do sync, e por isso a mudança de
funil vira "o `funnel_id` era outro na passada anterior". **O dado existe na origem e é
recuperável lead a lead.** Se algum dia a seção Jornada quiser a data exata da travessia (e
não a etapa de hoje), o caminho é este — uma chamada por lead, não um backfill.

Correção de redação para o §5.2: trocar *"a travessia não deixa evento"* por **"a travessia
não deixa evento **no nosso banco**; na Exact ela é um evento com funil de origem e de
destino"**.

## 4.4 Indício circunstancial — e está rotulado como indício

Não responde a pergunta, mas é o que os dados permitem dizer:

| | travessias de funil | demais transições |
|---|---:|---:|
| n | 22 | 80 |
| hora SP | **10h52 – 18h26** | 00h – 23h |
| fora de 08h–19h | **0 / 22** | 18 / 80 |
| dias | seg–sex (+ 1 sábado) | inclui **domingos** |

**Todas as 22 travessias caem no expediente comercial; as outras transições, não.** É o
padrão de alguém clicando, não de uma regra disparando. Reforçando: dois leads (51554851 e
51495138) passam por **18285 (Intercâmbio)** a caminho do 18537 e ficam lá **18 e 50
segundos** — parece funil errado escolhido e corrigido na hora, que é comportamento humano.

> **Isto é inferência de padrão temporal, não medição de ator.** Não pode virar número na
> tela e não fecha o §5.3. Fica registrado porque é o melhor que existe hoje.

---

## 5. Efeito no CHECKPOINT

Nada do §10.1 muda: J-E1 a J-E6 seguem como aprovados. Do §10.2:

| # | Estado |
|---|---|
| **J-P1** | **reescrito** (§2.5): deixa de ser "tirar da contagem" e vira "a NAT deve agir no funil pessoal?" — e não é urgente, o funil está dormente |
| **J-P1b** | **novo**: `INGEST_FUNNEL_IDS` vazio, e o risco de query de página sem filtro de funil |
| **J-P2** | inalterado (aprovado) |
| **J-P3** | ver `RECON_T3_20260902.md` |
| **J-P4** | **encerrado**: feito, 20/20, e o endpoint não tem o campo. §5.3 fica PENDENTE por impossibilidade, não por falta de execução |
| **J-P5, J-P6** | inalterados (aprovados) |

Correções a aplicar no `RECON_JORNADA_LEAD_20260901.md` antes de a página usá-lo: §0 (2→3 da
IA do outro lado), §1 + J-P1 (§2.4/§2.5 desta emenda), §3 (tabela e o "11"), §5.2 (a
travessia é evento na Exact), §5.3 (o `userAction` não existe), §9.1 (9 · 1 → 10) e §9.2
(`chegou_em_vendas`).

---

*Emenda de 02/09/2026. Somente leitura — nenhum dado alterado, nenhuma mensagem enviada.
20 chamadas GET à Exact (`/LeadStages`), sem escrita, todas autorizadas no §4 do prompt.*
