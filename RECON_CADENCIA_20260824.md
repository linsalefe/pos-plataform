# RECON — Cadência de follow-ups executada pelo agente — 24/08/2026

Levantamento verificado no código em execução, no banco, na Graph API da Meta e na API da
Exact Spotter.

**Somente leitura.** Nenhuma migração, nenhum envio, nenhum estágio movido. A exceção
controlada do Bloco 3 (mover um lead de teste) **não foi executada** — ver §3.4.

---

## 1. A tabela para a Isa confirmar

A coluna **Intervalo** não está em branco: foi **medida** no histórico (§1.4).
Confirme, corrija ou preencha o que está `PENDENTE`.

| Estágio (id) | Template proposto | Intervalo medido | Evidência | Confirmar |
|---|---|---|---|---|
| **Follow 1** (129985) | `PENDENTE` — candidatos abaixo | — | nenhum template com esse nome | ☐ |
| **Follow 2** (129984) | `PENDENTE` — candidatos abaixo | — | idem | ☐ |
| **Follow 3** (129983) | `f3_guia<curso>` (13 variantes) **ou** `mensagem_follow3` | — | corpo = "link de acesso à **ementa**"; nome `f3_` = follow 3 | ☐ |
| **Follow 4** (129955) | `f4_audio<curso>` (11 variantes) **ou** `mensagem_follow4` | **1,9 d** (n=116) | corpo = "**áudio do coordenador**", idêntico ao `mensagem_follow4` | ☐ |
| **Follows 5** (129967) | `mensagem_follow5` | **1,1 d** (n=66) | 114 envios/30 d | ☐ |
| **Follows 6** (174517) | `mansagem_follows6` *(o nome tem o typo mesmo)* | **1,1 d** (n=77) | 184 envios/30 d | ☐ |
| **Follows 7** (174516) | `mensagem_follow7` | **1,1 d** (n=110) | 119 envios/30 d | ☐ |
| **Follows 8** (174515) | `mensagem_follow8` | **1,1 d** (n=175) | 131 envios/30 d | ☐ |
| **Follows 9** (174514) | `mensagem_follow9` | **1,0 d** (n=144) | 74 envios/30 d; corpo **encerra** o contato | ☐ |

**Candidatos para Follow 1 e 2** — os três dizem "tentei ligar, qual o melhor horário?",
que é o que faz sentido no começo da régua:

| Candidato | Corpo | Envios/30 d |
|---|---|---|
| `mensagens_flows2` | "Fiz uma nova tentativa de contato… **essa ligação é a primeira etapa** do seu processo seletivo" | 134 |
| `mensagem_flow` | "é o {{2}} do CENAT… tentei… não tive sucesso. Qual seria o melhor horário?" | 89 |
| `sdr_tentativa_ligacao` | "Recebi sua aplicação… tentei entrar em contato via ligação" | (baixo) |

O `mensagens_flows2` diz literalmente "primeira etapa" — é o melhor candidato a Follow 1.

### Três perguntas que só a Isa responde

1. **Follow 3 e 4: genérico ou por curso?** Existem as duas famílias, com o mesmo texto.
   `f3_guia*`/`f4_audio*` têm uma variante por curso (link e áudio específicos);
   `mensagem_follow3`/`4` são genéricos. Por curso é melhor para o lead e exige mapear
   `sub_source → template`; genérico é uma linha só.
2. **Follows 9 encerra?** O corpo diz "encerro aqui meu contato". Depois dele o lead vai
   para `Descartado`?
3. **A régua roda em dias corridos ou úteis?** A medição não distingue.

---

## 1.4 De onde vem o intervalo

Não foi chutado. Medi o intervalo entre passos consecutivos da régua, em 90 dias:
**393 contatos** receberam 2+ passos, gerando **688 intervalos**.

```
passo   n    mediana   min    max
 3→4   116     1,9 d   0,9    5,8
 4→5    66     1,1 d   0,8    3,9
 5→6    77     1,1 d   0,8    3,9
 6→7   110     1,1 d   0,8    4,0
 7→8   175     1,1 d   0,0    8,1
 8→9   144     1,0 d   0,0    6,7
                GERAL: mediana 1,1 d
```

**A régua real é de ~1 dia por passo**, com o 3→4 em ~2 dias. O mínimo de 0,0 em 7→8 e 8→9
mostra disparos no mesmo dia — provavelmente o SDR "colocando em dia" leads atrasados.

### Como os templates foram identificados

`messages` guarda o texto **renderizado**, não o nome do template. Casei cada mensagem
com o maior trecho literal do corpo aprovado (sem variáveis): **2.782 de 2.782** mensagens
de template dos últimos 30 dias foram identificadas.

---

## 2. Entrada e saída da cadência

### 2.1 Opções de entrada — recomendação

| Opção | Volume medido | Prós | Contras |
|---|---|---|---|
| **(a)** Qualificado que **não agendou** após X h | **3,4 leads/dia** | Só quem o agente já conheceu; a régua fala com quem tem contexto | Ignora quem nunca respondeu |
| **(b)** Todo lead novo do 18535 | 7,3/dia | Cobertura total | Inclui quem já está em conversa; duplica com o agente |
| **(c)** `transferido_humano` sem resolução após X | (0 hoje) | Rede para o que o humano largou | Precisa definir "sem resolução" — não há sinal de "SDR atendeu" |
| **(d)** `encerrado` por silêncio | (0 hoje) | — | **A etapa `encerrado` nunca é atribuída** por nenhum caminho do código hoje |

**Recomendo (a)**, com (c) numa segunda fase. Motivos: é o menor volume (3,4/dia, previsível),
é o único que garante que o lead já foi abordado uma vez, e não compete com o agente —
que é o dono do inbound enquanto a etapa dele está ativa.

⚠️ **(d) não é implementável hoje**: `ETAPA_Q_ENCERRADO` existe no CHECK e nas constantes,
mas **nenhum código a atribui**. É o mesmo defeito que o `ESTADO_NAT_20260809` apontou no
fluxo velho (`sem_contato` e `encerrado` como constantes mortas) — repetido no novo.

### 2.2 Paradas: como detectar cada uma

| Parada | Sinal | Latência | Confiável? |
|---|---|---|---|
| Lead respondeu | `messages` inbound | **imediata** (webhook) | ✅ |
| Reunião marcada | `agendamentos.passo='agendado'` | **imediata** (é nosso) | ✅ |
| Descartado | `exact_leads.stage='Descartado'` | **até 600 s** | ⚠️ ver §2.3 |
| Vendido / em negociação | `funnel_id=18537` (`Em Negociação`, `Contratos Gerados`, `Vendidos`) | até 600 s | ⚠️ idem |

### 2.3 A janela de corrida, com o exemplo do sprint

> Lead descartado às 10:00, sync às 10:09, follow agendado para 10:05.

**O follow sai.** Às 10:05 o `exact_leads.stage` local ainda diz `Follow 4`; o descarte só
chega às 10:09. O lead recebe uma mensagem de régua depois de ter sido descartado.

Janela: **0 a 600 s**, média 300 s. Com 20,3 leads mudando de estágio por dia no 18535 e
~9 envios de régua por dia, a colisão é rara — mas não é zero, e o custo é uma mensagem
para quem a equipe já decidiu não abordar.

**Três mitigações**, em ordem de custo:
1. **Reler antes de enviar** (o padrão de `nat_recuperacao`) — não resolve, só encurta a
   janela para o instante do envio.
2. **Consultar a Exact no momento do envio** (`GET /Leads?$filter=id eq X`, ~1 chamada por
   envio, ~9/dia) — fecha a janela. É o mesmo padrão on-demand já aprovado no Bloco C do
   agente, e pelo mesmo motivo.
3. Aumentar a frequência do sync — caro e não fecha a janela.

**Recomendo a 2.** O custo é irrisório e a janela some.

---

## 3. Escrita de estágio na Exact

### 3.1 O endpoint

**`POST /v3/ChangeFunnel`** com `{"leadId": int, "stageId": int}`. Já implementado em
`agendamento/client.py:213` (`mudar_funil`) e usado pelo passo 4 do agendamento.

Não existe parâmetro de funil: **o funil é inferido da etapa**. Para mover dentro do 18535
basta passar o `stageId` de destino — os 13 ids estão em §3.5.

Não confundir com `LeadsTransfer` (troca o SDR, não mexe no funil). `LeadStages`,
`LeadPipelineStages` e `StagesLead` existem no `$metadata` e são **leitura**.

### 3.2 Restrições conhecidas

| | |
|---|---|
| Permissão especial | Não — o mesmo token do sync já executa (medido no passo 4, FINDINGS §15) |
| Dispara automação na Exact? | **Não observado** no teste cross-funil de 18/08. **Não testado** para movimento dentro do mesmo funil |
| Reversível? | **Só parcialmente — ver §3.3** |
| Efeito colateral conhecido | Reunião `Vigente` vira `Concluido` (FINDINGS §15). Não se aplica a lead de follow, que não tem reunião |

### 3.3 ⚠️ O movimento NÃO é simétrico

`GET /v3/stages` lista **13 etapas** para o funil 18535, e **`Descartado` não é uma delas** —
mas é um valor de `stage` que a API **devolve** (confirmado num lead real).

Consequência: **`ChangeFunnel` move um lead PARA os follows, mas não consegue trazê-lo de
volta para `Descartado`** — não há `stageId` para passar. O caminho de descarte é outro
endpoint (`LeadsLost`, no `$metadata`, **não testado**).

Isso muda o desenho: a régua pode empurrar um lead pela escada, mas **não sabe encerrá-lo**
no fim. O que fazer no Follows 9 é a pergunta 2 da §1.

### 3.4 O teste de escrita — NÃO EXECUTADO

Preparei o teste no lead **47398963** ("teste teste"), que está em `Entrada` no 18535 —
lead de teste antigo, e o movimento `Entrada → Follow 1 → Entrada` seria **reversível pelo
mesmo endpoint**. Preferi reusá-lo a criar um lead novo: `LeadsDelete` é exclusão dura e
`LeadsRecover` responde "Lead not found" (FINDINGS §6), então um lead de teste novo seria
lixo permanente no CRM.

**A chamada foi bloqueada pela trava de permissões da sessão.** Não contornei.

Fica como **NÃO TESTADO**. Para executar, basta liberar o `POST /ChangeFunnel` e rodar:

```
POST https://api.exactspotter.com/v3/ChangeFunnel
     {"leadId": 47398963, "stageId": 129985}     # Entrada -> Follow 1
     {"leadId": 47398963, "stageId": 129959}     # e de volta
```

O que ainda precisa ser respondido por esse teste: **movimento dentro do mesmo funil
dispara automação da Exact?** (e-mail ao lead, redistribuição de SDR). Se disparar, a régua
do agente aciona coisas que ninguém pediu — é o único risco real que sobra no Bloco 3.

### 3.5 Ids das etapas do funil 18535

| pos | id | nome |
|---|---|---|
| 1 | 129959 | `Entrada` |
| 2 | 129985 | `Follow 1` |
| 3 | 129984 | `Follow 2` |
| 4 | 129983 | `Follow 3` |
| 5 | 129955 | `Follow 4` |
| 6 | 129967 | `Follows 5` |
| 7 | 174517 | `Follows 6` |
| 8 | 174516 | `` Follows 7`` ⚠️ |
| 9 | 174515 | `Follows 8` |
| 10 | 174514 | `` Follows 9`` ⚠️ |
| 11 | 131957 | `Pre Qualificado` |
| 12 | 197223 | `Reagendamento` |
| 13 | 133409 | `Agendados` |

⚠️ **`Follows 7` e `Follows 9` têm ESPAÇO no início do nome**, na Exact e no nosso espelho.
Casar estágio por nome quebra nesses dois. **Usar sempre o id.**

---

## 4. As quatro defesas — o que existe

| # | Defesa | Existe? | Onde se pluga |
|---|---|---|---|
| 1 | Disparo por **transição** observada | ❌ **Não existe nada** | ver abaixo |
| 2 | `UNIQUE (exact_lead_id, estagio)` | ❌ Não existe tabela parecida | tabela nova |
| 3 | Teto de envios/hora | ⚠️ Existe, mas compartilhado | `nat_config.max_envios_hora` |
| 4 | Horário comercial + trava de data | ⚠️ Parcial | ver abaixo |

### 4.1 Transição — a fundação que falta

`sync_exact_leads` faz `setattr(existing, key, value)` para os 10 campos, a cada passada
(`exact_spotter.py:455-457`). **Sobrescreve sem comparar.** Não há histórico de estágio:
`exact_leads.stage` é uma coluna só, e nenhuma outra tabela guarda o valor anterior.

Ou seja: hoje é **impossível** distinguir "o lead acabou de entrar em Follow 1" de "o lead
está em Follow 1 há três semanas". Sem isso, a régua dispararia sobre **estado**, não sobre
transição — e na primeira execução varreria os **54 leads** parados nos follows de uma vez.

Duas fundações possíveis:
- **(i)** comparar `existing.stage` com o novo valor **antes** do `setattr` e gravar o
  evento. Três linhas no sync, mas põe escrita nova no caminho quente que reescreve 9.133
  linhas a cada 600 s;
- **(ii)** o agente registra a transição que **ele mesmo** provoca (ele move o lead), e o
  sync só serve de parada. Não cobre movimento feito por humano na tela da Exact.

**Recomendo (i)**, e note que ela é pré-requisito de tudo: sem transição não há gatilho.

### 4.2 Teto de envios

`max_envios_hora = 20` é lido por `nat_guard` e por `qualificacao_guard`, cada um contando
os SEUS envios por `messages.nat_etapa`. A cadência pode fazer o mesmo — **teto próprio,
sem coluna nova**, filtrando pelos nomes de template dela.

Volume em regime: entrada de 3,4/dia × 9 passos ≈ **31 envios/dia** ≈ 1,3/hora. Folgado.
**O risco não é o regime, é a largada:** os 54 leads parados hoje nos follows.

### 4.3 Horário e data

- **Trava de data:** o padrão `start_at` vs data de referência é reaproveitável como está.
- **Horário comercial:** `nat_guard.dentro_horario_comercial()` (9h-19h, seg-sex) existe e
  é reusável — mas ⚠️ **o agente de pré-qualificação NÃO a usa** (nenhum dos 5 módulos a
  referencia). Se a cadência usar e o agente não, teremos dois comportamentos diferentes no
  mesmo número. Decisão pendente, já levantada na ativação.

---

## 5. Riscos, e o que eles mudam no desenho

| # | Risco | O que muda |
|---|---|---|
| 1 | **Sem detecção de transição** | Bloco 0 obrigatório. Sem ele a régua dispara sobre estado e varre a base |
| 2 | **A largada sobre 54 leads parados** | A trava de data precisa valer para a TRANSIÇÃO, não para o `register_date` — senão lead antigo que mudar de estágio amanhã entra |
| 3 | **Não há volta para `Descartado`** | A régua não sabe encerrar. Definir o destino do Follows 9 antes de implementar |
| 4 | **Espaço no nome de 2 estágios** | Casar por id. Nunca por nome |
| 5 | **Janela de 600 s no descarte** | Consultar a Exact no envio (§2.3, mitigação 2) |
| 6 | **`ChangeFunnel` intra-funil não testado** | Pode disparar automação da Exact. **Testar antes de qualquer implementação** |
| 7 | **Follow 1 e 2 sem template definido** | Bloqueia 2 dos 9 passos. É a pergunta mais urgente para a Isa |
| 8 | Régua e agente no mesmo número | Precedência explícita, como a do webhook: enquanto o agente é dono, a régua não fala |

---

## 6. Blocos de implementação sugeridos

**Bloco 0 — Detecção de transição** *(pré-requisito de tudo)*
Diff de `stage` no sync + tabela `exact_stage_events (exact_lead_id, de, para, em)`.
Sem isso nenhum outro bloco existe.

**Bloco 1 — Confirmação da Isa** *(paralelo, bloqueia o 3)*
A tabela da §1. Sem Follow 1 e 2 a régua não fecha.

**Bloco 2 — Teste do `ChangeFunnel` intra-funil** *(paralelo, bloqueia o 4)*
§3.4. Uma chamada e a volta. Responde o risco 6.

**Bloco 3 — Estado e travas** *(depende do 0 e do 1)*
Tabela de log com `UNIQUE (exact_lead_id, estagio)`, teto próprio, trava de data **sobre a
transição**, e a decisão de horário comercial.

**Bloco 4 — Envio + movimentação** *(depende do 2 e do 3)*
Enviar o template e mover o estágio. A ordem importa: **mover primeiro, enviar depois** —
uma mensagem enviada não volta atrás, um estágio sim.

**Bloco 5 — Paradas** *(depende do 3)*
Inbound, reunião, descarte. Com a consulta on-demand da §2.3.

**Fora de escopo, registrado:** o que fazer no fim da régua (§3.3) e a convivência
agente × cadência (risco 8) são decisões de produto, não de implementação.
