# RECON — Página de Relatórios do Hub

**Data:** 01/09/2026, 16h50 SP · **Tipo:** somente leitura.
Nenhuma migração, nenhum deploy, nenhum envio, nenhum arquivo de produção alterado.
Tudo rodou em tabelas `TEMP` e `EXPLAIN`. Scripts em `/tmp/relq/`.

---

## 0. Veredito curto

**Dá para subir a página, e a maior parte das métricas já tem query validada.** Das 10, **4
estão PRONTAS**, **4 precisam de adaptação pequena**, **1 é nova e barata**, e **1 é cega por
falta de dado** — não por falta de query.

**Cache é otimização prematura, e agora com número.** A agregação mais pesada do painel roda
em **679 ms** como está escrita nos recons e em **39 ms** reescrita numa passada só (17×). As
outras duas custam 29 ms e 3 ms. O painel inteiro fica **abaixo de 200 ms** numa janela de 30
dias. Não construa cache.

**O maior risco da página não é performance nem query: é o número mudar sozinho.** Três
métricas já mudaram de valor entre o recon de origem e hoje, sem nenhum bug — as reuniões
"indeterminadas" caíram de 8 para 2, e os leads do botão "sem resposta" caíram de 12 para 9,
porque **alguém atendeu essas pessoas depois**. Uma página que recalcula a cada abertura vai
mostrar um número diferente do `.md` que a Isa leu ontem, e ela vai achar que um dos dois está
errado. **Isso precisa de tratamento explícito de produto, não de engenharia.**

**Dois achados que valem sozinhos esta rodada.** (a) O predicado de leads de teste usa `zz`
sem âncora e **casa 48 leads reais** — Pozzebon, Rizzato, Azzi, Mazzeo. Copiá-lo para a página
apagaria essas pessoas de todo relatório, em silêncio. (b) O `dashboard_stats` atual compara
`datetime.now()` (UTC no servidor) com `messages.timestamp` (SP): **das 21h às 23h59 SP, todo
dia, o contador de "mensagens hoje" lê zero.**

**A métrica 5 (por SDR) começa em 01/09 16:00 SP** e não tem passado. Hoje ela tem **uma
linha**.

---

## 1. B1 — Inventário: métrica → query → viabilidade

| # | Métrica | Query reaproveitável | Tabelas / colunas | Relógio | Custo medido | Veredito |
|---|---|---|---|---|---|---|
| 1 | Atendimento da IA: aberturas entregues, conversas ≥1 turno, qualificações completas | `RELATORIO_IA_VS_HUMANO` B.5 + `RECON_28/08` §1.4 | `messages.nat_etapa/status`, `nat_qualificacao_state.{formacao,ano_conclusao,atuacao,motivacao}` | SP (`timestamp`) / UTC (`created_at`) | **< 10 ms** | **ADAPTAR** — parametrizar janela e **corrigir o denominador** (§1.2) |
| 2 | Tempo de resposta mediano IA × humano | `RELATORIO_IA_VS_HUMANO` B.4 | `messages` (`direction`, `message_type`, `nat_etapa`, `timestamp`) | SP | **679 ms → 39 ms** reescrita | **ADAPTAR** — B.4 é **prosa, não SQL**; ver §1.2 |
| 3 | Reuniões marcadas pela IA e quantas se realizaram | `RELATORIO_IA_VS_HUMANO` B.6 + §A.3 | `exact_stage_events`, `agendamentos.{origem_ip,passo,lead_id}` | UTC → SP | **3 ms** | **ADAPTAR** — precedência de 4 vias (§1.2) |
| 4 | Reuniões da página de obrigado (`origem_ip` preenchido) | idem #3 | idem | UTC → SP | **3 ms** (mesma query) | **PRONTA** |
| 5 | Quantas pessoas cada SDR está falando | — (não existia antes do S6-1) | `messages.sent_by` | SP | **< 5 ms** (índice parcial) | **ADAPTAR** — só a partir de **01/09 16:00 SP** (§2) |
| 6 | Humano/bulk atrapalhando a IA | `RELATORIO_IA_VS_HUMANO` B.7 | `nat_qualificacao_state.transferido_motivo` | SP (`transferido_em`) | **< 5 ms** | **METADE PRONTA, METADE NÃO MEDÍVEL** — os skips do bulk não são persistidos (§5.1) |
| 7 | Saúde da IA | `RECON_28/08` §1.8 e §1.10 | `nat_qualificacao_state`, `nat_scheduled_actions`, `messages` | SP | **< 20 ms** | **PRONTA** |
| 8 | Funil por etapa + resposta à abertura por template | `RECON_27/08` §1.4 + `SPRINT6` §5 | `nat_qualificacao_state`, `messages.nat_etapa` | SP / UTC | **< 15 ms** | **PRONTA** |
| 9 | Follow humano: bulk × individual, resposta 24h, recusas, falhas Meta | `RECON_FOLLOWS` Anexo C | `messages`, `app/higiene_disparo.PADRAO_RECUSA` | SP | **29 ms** (ilhas) | **PRONTA** |
| 10 | Vão do espontâneo | `RECON_VAO_ESPONTANEO` §3.1 | `messages.content` (prefixo) | SP | **< 20 ms** | **NOVA** — a query do recon está em prosa; escrita e validada aqui (§1.2) |

### 1.1 Onde cada query já roda hoje

Todas as 10 rodam. Nenhuma depende de dado que não exista — **exceto a metade de skips da
métrica 6**, que é o único **NÃO MEDÍVEL** puro do inventário, e o motivo está no §5.1.

### 1.2 A validação obrigatória — e as divergências, que são achado

Rodei cada query adaptada na **mesma janela** do recon de origem. Resultado:

| Conferência | Publicado | Medido agora | Veredito |
|---|---|---|---|
| Reuniões 24–29/08, total | **27** | **27** | ✅ |
| … das quais da IA | **1** | **1** | ✅ |
| … da página de obrigado | **18** | **20** | ⚠️ |
| … indeterminadas | **8** | **2** (+4 numa categoria nova) | ⚠️ |
| Mediana de resposta — IA | **3,7 s** (N=34) | **4,2 s** (N=77) | ⚠️ |
| Mediana de resposta — humano | **28 min** (N=34) | **23,2 min** (N=38) | ⚠️ |
| Perguntas sem resposta na janela | **73** | **74** | ✅ (±1) |
| Degrau do ano (S6 §5) | 77→72→**45**→40→35, **−37,5%** | 79→74→**47**→42→37, **−36,5%** | ✅ |
| Silêncio do agente em etapa ativa | **0** | **0** | ✅ |
| Botão da LP, 24–29/08 — escreveram | **38** | **38** | ✅ |
| … dessas, não receberam nada | **12** | **9** | ⚠️ |

**Três classes de divergência, e cada uma exige uma decisão diferente.**

#### (a) O número mudou porque a realidade mudou — e vai mudar de novo

`38 → 12` virou `38 → 9`: **três daquelas pessoas foram atendidas depois de 29/08**. O
denominador é histórico, o numerador é vivo. O mesmo vale para as reuniões indeterminadas.

> **Isto não é bug e não tem conserto técnico.** É a natureza de "quantos ainda não foram
> atendidos". A página tem que dizer **em que instante o número foi apurado**, e a Isa precisa
> saber que abrir amanhã dá outro valor. Proposta de tela no §7.

#### (b) O número mudou porque a regra tem duas leituras — `agendamentos` tem estados intermediários

A regra do §A.3 diz "entrou em `Agendados` **sem linha correspondente** em `agendamentos` →
indeterminado". Mas `agendamentos.passo` tem estados intermediários, e um lead pode ter
**várias** linhas. Medido nas 27:

| Situação | Leads |
|---|---:|
| tem linha `passo='agendado'` **sem** `origem_ip` → **IA** | **1** |
| tem linha `passo='agendado'` **com** `origem_ip` → **página de obrigado** | **20** |
| tem linha, mas **nunca chegou** a `passo='agendado'` → *categoria nova* | **4** |
| **nenhuma** linha em `agendamentos` → indeterminado | **2** |

Os **4 do meio** são o achado: o visitante começou o fluxo da página, a linha nasceu, o
agendamento **não fechou lá** — e mesmo assim o lead entrou em `Agendados` na Exact. O relatório
de 29/08 os empilhou em "indeterminado"; eles são outra coisa, e são acionáveis.

> **Proponho a precedência de 4 vias acima como regra canônica da página**, com o rótulo
> `LP incompleta` para os 4. É estritamente mais informativo e não perde nenhuma categoria.
> *(Decisão de produto — §9.)*

#### (c) O número mudou porque a definição nunca foi código

**Esta é a divergência que mais importa.** O `B.4` do relatório de 29/08 descreve o algoritmo
da mediana **em prosa**:

> *"Varre cada conversa em ordem; guarda o primeiro `inbound` sem resposta; fecha no primeiro
> `outbound` que não seja abertura nem template."*

Implementei exatamente isso e obtive **N=77/38** contra o **N=34/34** publicado. Uma diferença
de denominador de 2×. A prosa admite pelo menos três leituras (o que conta como "pergunta", se
`interactive`/`button` contam como outbound, se a abertura entra) e cada uma dá um N diferente.

**As medianas em si são robustas** — a ordem de grandeza não se move: IA em segundos, humano em
dezenas de minutos, razão de 331× medida contra 450× publicada. O que não é robusto é o dígito.

> **Veredito:** a métrica 2 entra na página com o algoritmo **fixado em SQL** (Anexo A.2), e o
> número dela passa a ser o dela — não o do `.md`. Registre no doc de origem que a baseline
> mudou. **Não tente reproduzir 3,7 s**: não há como saber qual das leituras produziu aquele
> número.

#### (d) O funil publicado mistura denominadores

O `RECON_27/08` publica **65% → 61% → 38% → 34% → 30%**. Medindo: 65% é
`respondeu / total_de_conversas`; **61% é `formação_entre_quem_respondeu / total_de_conversas`**.
São duas bases diferentes apresentadas como uma escada. Se eu usar o mesmo denominador para
todos os degraus, o segundo vira **85%** (`formacao IS NOT NULL` sobre tudo, porque a formação
também vem do formulário da LP, não só da conversa).

> **A página deve mostrar o funil sobre UM denominador — quem respondeu** — e dizer isso no
> eixo. Sobre essa base, os degraus de hoje são 79 → 74 → 47 → 42 → 37.

#### (e) `sem_resposta_do_agente = 1`, e não é regressão

O prompt esperava zero. Há **um**: `5598984703419`, encerrado em 29/08 09:37. O
`RECON_28/08` §1.10 previu exatamente este (*"o primeiro vence amanhã"*). O invariante que
continua valendo é o outro — **silêncio em etapa ativa = 0** ✅.

---

## 2. B2 — O que o `sent_by` liberou, e a partir de quando

### 2.1 O que já existe

| | |
|---|---|
| Primeira linha com `template_name` | **01/09/2026 16:00:41 SP** |
| Primeira linha com `sent_by` | **01/09/2026 16:29:38 SP** |
| Linhas com `sent_by` até agora | **1** (Thobias, 01/09) |
| Volume típico de outbound por dia útil | **86 a 221** |

### 2.2 Os três NULL legítimos cobrem 100%? — **sim, mas a amostra é N=2**

Conferência do §"O que observar" do `SPRINT6`, sobre os outbounds posteriores ao deploy:

| Caso | Como se identifica | N |
|---|---|---:|
| humano logado | `sent_by IS NOT NULL` | **1** |
| agente | `sent_by IS NULL` e `nat_etapa IS NOT NULL` | **1** |
| agendado / boas-vindas | `sent_by IS NULL`, `nat_etapa IS NULL`, `template_name IS NOT NULL` | 0 |
| **não explicado** | os três NULL falham | **0** ✅ |

**Zero não explicados — e isso ainda não prova nada.** Dois outbounds é uma amostra sem poder;
o deploy pegou o fim do expediente. **A conferência precisa ser refeita depois de um dia útil
inteiro** (~90–220 outbounds). Está no §10 como item de acompanhamento, não como conclusão.

### 2.3 Conclusão em uma frase, e o texto de tela

> **A métrica 5 é mostrável a partir de 01/09/2026 16:00 SP**, e para qualquer instante
> anterior a essa data o dado **não existe** — não é zero, não é "sem atividade": nunca foi
> gravado.

Quando o filtro de período cruzar a fronteira, a seção por SDR **não** deve mostrar barras
truncadas. Proponho:

```
┌─ Mensagens por SDR ──────────────────────────────────────────────┐
│                                                                  │
│  ⓘ  Só dá para atribuir mensagem a uma pessoa a partir de         │
│      01/09/2026, 16h. Antes disso o sistema não gravava quem      │
│      enviou — o dado não existe, e não é zero.                    │
│                                                                  │
│      Você pediu 25/08 – 01/09. Os números abaixo cobrem só        │
│      01/09 (16h em diante): 1 de 8 dias do período.               │
│                                                                  │
│  Thobias  ████ 1                                                  │
└──────────────────────────────────────────────────────────────────┘
```

Regra: se `período.início < CORTE_SENT_BY`, o card mostra o aviso **e** declara quantos dias do
período estão cobertos. Se o período inteiro é anterior ao corte, a seção mostra só o aviso,
**sem gráfico** — gráfico vazio lê-se como "ninguém trabalhou".

---

## 3. B3 — Custo, medido

### 3.1 `EXPLAIN ANALYZE`, janela de 30 dias

| Agregação | Plano | Tempo |
|---|---|---:|
| **Mediana pergunta → resposta**, como está nos recons (LATERAL correlacionado) | Seq Scan (1 494 buffers) + WindowAgg + **1 213 loops** de sort | **678,9 ms** |
| **A mesma, reescrita numa passada** (`min(...) FILTER ... OVER` com frame) | Seq Scan + 2 WindowAgg, **zero loops** | **39,2 ms** |
| **Ilhas bulk × individual** (gaps-and-islands por família) | Seq Scan + 2 WindowAgg + Incremental Sort | **29,4 ms** |
| **Reuniões por lead** (precedência de 4 vias) | 66 buffers | **3,1 ms** |

A reescrita foi conferida contra a original na janela de 29/08 e devolve **exatamente** o mesmo
resultado (IA n=77 / 4,2 s · humano n=38 / 1393,3 s). Está no Anexo A.2.

### 3.2 Índices existentes — e o que falta

| Tabela | Linhas | Tamanho | Índice útil ao painel |
|---|---:|---:|---|
| `messages` | 32 873 | 17 MB | `ix_messages_contact_wa_id`; parciais `nat_etapa_ts`, `sent_by`, `template_name` |
| `exact_leads` | 9 299 | 5,8 MB | `exact_id` |
| `contacts` | 8 219 | 1,7 MB | `wa_id`, `assigned_to` |
| `exact_stage_events` | 892 | 320 kB | `(stage_para, observado_em DESC)` ✅ |
| `agendamentos` | 310 | 224 kB | `slot_inicio` — **nada em `lead_id`** |
| `nat_qualificacao_state` | 120 | 144 kB | `etapa` |

> **Não existe índice em `messages.timestamp` sozinho.** O único que o toca é parcial
> (`WHERE nat_etapa IS NOT NULL`), inútil para uma janela que inclui humano. Toda query de
> período faz **Seq Scan de 1 494 buffers (~12 MB)** — que custa ~23 ms e é irrelevante hoje.

### 3.3 Veredito sobre cache

> **Não construa cache. Não materialize.** Com a query da mediana reescrita, o painel inteiro
> soma **≈ 75 ms** de banco numa janela de 30 dias — 26× abaixo do alvo de 2 s.

Construir cache agora custaria: um mecanismo de invalidação, um job, e a pergunta "este número
é de quando?" em cima de uma página que **já** tem esse problema por outro motivo (§1.2a).
Seria pagar complexidade para piorar a confiança.

**O gatilho para revisar** — e vale deixar escrito: quando `messages` passar de **~300 mil
linhas** (10× hoje), o Seq Scan vai para ~230 ms por query e o painel para ~1 s. O conserto de
lá é **um índice em `messages (timestamp)`**, não cache. Ao ritmo atual (~120/dia), isso são
uns 6 anos.

---

## 4. B4 — Os buracos, um a um

### 4.1 Skips do bulk não são persistidos — **CONFIRMADO, e pior do que a suspeita**

`bulk_send_template` devolve `skipped_total` / `skipped_por_regra` / `skipped` **só no corpo da
resposta HTTP** (`exact_routes.py:589-591`). O único ponto que persiste é `main.py:240`
(`sm.result = json.dumps(result)`), no caminho **agendado**.

E o caminho agendado **não é usado**:

```
scheduled_messages:  4 linhas no total,  todas de junho/2026
                     0 desde agosto
```

> Não é que a métrica 6 seja "cega para campanha imediata". **Ela é cega para tudo**: 100% dos
> disparos dos últimos 8 dias saíram pela porta HTTP, cujo retorno ninguém guarda. O
> `skipped_por_regra` que o S6-2 acabou de construir **existe só na tela de quem apertou o
> botão, e some quando ele fecha a aba.**

**Três saídas, com custo — proposta apenas:**

| Opção | O que é | Custo | Risco |
|---|---|---|---|
| **A. Tabela `disparo_skip`** (recomendada) | uma linha por skip: `(quando, template, contact_wa_id, regra, motivo, origem_envio, sent_by)` | migração aditiva + ~10 linhas no laço | baixo; escrita no mesmo savepoint do lote |
| **B. Gravar em `scheduled_messages` também no imediato** | criar uma linha sintética por disparo HTTP | ~15 linhas | **médio** — polui uma tabela cujo sentido é "agendado", e o job varre `status='pending'` |
| **C. Contadores agregados em `nat_config`** | só os totais | trivial | perde a regra, o lead e o motivo — que é o que a métrica precisa |

**Recomendo a A.** É a única que responde "quem foi pulado, por qual regra, quando" — que é a
pergunta da métrica 6. E ela vira, de graça, a auditoria da higiene do S6-2: hoje não há como
provar que o filtro de recusa está funcionando, só que ele rodou.

### 4.2 `datetime.now()` em `dashboard_stats` — **CONFIRMADO**

`app/routes.py:118`: `now = datetime.now()`. O servidor não tem TZ configurado —
`datetime.now()` devolve **UTC** (conferido: 19:26 UTC enquanto SP marcava 16:26).

`today_start` sai daí, e é comparado contra **duas** colunas de fusos diferentes na mesma
função:

| Comparação | Coluna | Fuso da coluna | Resultado |
|---|---|---|---|
| `Contact.created_at >= today_start` | `created_at` | **UTC** | ✅ correto |
| `Message.timestamp >= today_start` | `timestamp` | **SP** | ❌ errado |

**O erro não é de 3 h no valor — é um zero de 3 h por noite.** Entre 21:00 e 23:59 SP,
`datetime.now()` já virou o dia (00:00–02:59 UTC), então `today_start` aponta para amanhã e
`messages_today` conta **zero**. Das 00:00 às 20:59 SP o número está certo, por coincidência
de as duas datas coincidirem.

Volume afetado: **769 mensagens** históricas caem nessa faixa, média **5,3/dia**, pico **13**
(31/08). O dano não é o volume: é o painel mostrar `0 mensagens hoje` às 22h.

**A página nova não pode copiar isso.** Proposta — um helper único, em
`app/relatorios.py`, e nenhuma query montando janela sozinha:

```python
SP = timezone(timedelta(hours=-3))

def agora_sp() -> datetime:
    """Agora em SP, naive — o mesmo relógio de messages.timestamp."""
    return datetime.now(SP).replace(tzinfo=None)

def janela(periodo: str) -> tuple[datetime, datetime]:
    """(ini, fim) naive-SP. 'hoje' | '7d' | '30d' | 'YYYY-MM-DD:YYYY-MM-DD'."""

def para_utc(ts_sp: datetime) -> datetime:
    """Converte a fronteira para UTC — e é o ÚNICO lugar que soma 3h.
    Usar ao cruzar exact_leads.register_date, exact_stage_events.observado_em
    e qualquer created_at."""
    return ts_sp + timedelta(hours=3)
```

> **Consertar o `dashboard_stats` atual é trabalho separado e fora deste recon.** Registrado no
> CHECKPOINT.

### 4.3 Não existe role `gestor` — **CONFIRMADO**

```
admin      7    (Álefe, Isa, Vi Amorim, Valéria, Thobias, Victória, Marina)
atendente  1    (Ana)
```

O único gate no código é `role != "admin"`. Como 7 de 8 são admin, **"acesso admin" hoje
exclui exatamente uma pessoa: a Ana.**

| Opção | Prós | Contras |
|---|---|---|
| **A. `Depends(get_current_admin)`** (recomendada) | zero código novo, zero migração; Isa e Pablo já são admin | a Ana não vê — e provavelmente é isso mesmo que se quer |
| B. Role `gestor` nova | semântica correta | migração + backfill de 8 linhas + mudar o gate em todo lugar, **para separar 1 pessoa** |
| C. Lista de ids no código | rápido | vira dívida na hora; ninguém lembra de atualizar |
| D. Todo usuário logado | mais simples | expõe faturamento/desempenho individual à operação |

**Recomendo a A**, e o motivo é proporção: criar uma role para excluir uma pessoa que já está
excluída pelo gate existente é cerimônia. Se um dia entrarem atendentes de verdade, a role
nasce junto com a necessidade. *(Decisão de produto — §9.)*

### 4.4 Ligação não deixa rastro — **CONFIRMADO**

`nat_contact_attempts`: **0 linhas em toda a história da tabela**, não só na janela. A régua
Follow 1–9 da Exact conta **ligação**, e o próprio corpo do `f5_ligacao` diz *"essa **ligação**
é a primeira etapa"* — mas nada disso chega ao banco.

**Proposta de rótulo**, para ser honesto sem parecer defeito:

> **"Mensagens enviadas"** — nunca "tentativas de contato".
>
> E, no rodapé da seção de follow, uma linha fixa:
> *"Só mensagens de WhatsApp. Ligações não entram — elas não ficam registradas no sistema."*

A frase diz o escopo, não pede desculpa. Quem lê entende que o número é completo **para o que
ele mede**.

### 4.5 Predicados espalhados — **CONFIRMADO, e um deles está QUEBRADO**

Este é o achado mais caro do bloco. O predicado de teste do `RELATORIO_IA_VS_HUMANO` §A.1 é
`nome casa smoke | teste | test | john doe | fafaf | zz | alefe | thobias justino`. Medido
contra a base real de 9 299 leads:

| Token | Leads que casam | Leitura |
|---|---:|---|
| `zz` **sem âncora** | **48** | ❌ Pozzebon, Pezzi, Lanzzarin, Rizzato, Garbazza, Gavazza, Azzi, mezzomo, andrezza, Mazzeo… |
| `zz` **ancorado** (`^\s*zz`) | **2** | ✅ os `zzz teste` de verdade |
| `test` / `teste` | 43 | ✅ conferidos um a um: todos são teste (`Álefe teste`, `Isa teste`, `giovanna zaraga teste`) |
| `alefe` | 2 | ✅ |
| `fafaf` | 1 | ✅ |
| `smoke` | 0 | ✅ (é dos telefones, não dos nomes) |

> **`zz` sem âncora apaga 46 pessoas reais de todo relatório, em silêncio.** É a mesma classe do
> `não há mais interesse` que o S6-2 pegou: um padrão plausível que ninguém mediu contra o
> corpus. Se a página copiar o predicado como está, ela nasce mentindo.

**Proposta — um lugar canônico para cada regra**, em `app/relatorios.py`, com o predicado
já corrigido:

```python
# ÂNCORA no zz: sem ela, 48 leads reais casam (Pozzebon, Rizzato, Azzi…).
# Medido contra os 9.299 leads em 01/09/2026. Quem mexer, MEÇA DE NOVO.
PREDICADO_TESTE_SQL = r"(^\s*zz|smoke|teste|\mtest|john doe|fafaf|alefe|thobias justino)"
TELEFONES_TESTE = ("5583988046720", "5567999151808", "5571985252525",
                   "5581995345775", "5511999990013")

CHAVE_TELEFONE_SQL = """
  CASE WHEN length(d) IN (10,11) THEN substr(d,1,2)||right(d,8) ELSE '' END
"""  # espelha app/telefone.py:chave_telefone — uma regra, dois idiomas
```

A chave de telefone já tem dono em Python (`app/telefone.py`). O que falta é a **versão SQL**
ter um dono também, em vez de ser recopiada em cada `.md`. Proponho que `app/relatorios.py`
seja esse dono, e que o teste do módulo compare as duas implementações sobre a base inteira —
é barato e trava a divergência.

---

## 5. B5 — Proposta de endpoint

### 5.1 Vários endpoints, não um

**Recomendo um router `/api/relatorios` com uma rota por seção**, e não uma rota monolítica.

O motivo não é performance — tudo soma 75 ms. É **isolamento de falha e de disponibilidade**: a
seção 5 (por SDR) tem dado só desde 01/09, a métrica 6 tem metade cega, e a 3 depende do sync da
Exact. Numa rota só, um `NULL` inesperado em qualquer uma derruba a página inteira; separadas, a
tela mostra 8 seções e um card com "indisponível" na nona. O front dispara as chamadas em
paralelo no `useEffect`.

```
GET /api/relatorios/resumo         métricas 1–4  (cards do topo)
GET /api/relatorios/ia             métricas 7, 8 (saúde + funil)
GET /api/relatorios/humano         métricas 5, 9 (por SDR + follow)
GET /api/relatorios/atritos        métricas 6, 10 (IA×humano + vão)
```

Gate: `dependencies=[Depends(get_current_admin)]` **no decorator, não na assinatura** — é a
convenção já documentada em `exact_routes.bulk_send_template`, e mantém a função chamável de
dentro do processo sem que a dependência vaze.

Registro em `app/main.py`, junto dos 10 routers já existentes (linha ~350).

### 5.2 Período — convertido uma vez, no helper

O parâmetro é sempre **hora de São Paulo**: `?periodo=hoje|7d|30d` ou
`?periodo=2026-08-01:2026-08-31`. O backend chama `janela(periodo)` (§4.2) uma vez, e passa
`(ini_sp, fim_sp)` às queries. **Só quem cruza `exact_*` ou `created_at` chama `para_utc()`** —
e chama no ponto do bind, nunca dentro do SQL, para a conversão aparecer no código e não numa
string.

### 5.3 Esquema: valor + N + relógio + limitação

Nenhuma métrica devolve número solto.

```json
{
  "periodo": { "de": "2026-08-02T00:00:00", "ate": "2026-09-01T16:50:00",
               "relogio": "America/Sao_Paulo", "dias": 30 },
  "apurado_em": "2026-09-01T16:50:12",
  "secao": "resumo",
  "metricas": [
    {
      "id": "ia_aberturas",
      "rotulo": "Aberturas entregues pela Nat",
      "valor": 108, "n": 120, "unidade": "mensagens",
      "relogio": "SP (messages.timestamp)",
      "confianca": "alta",
      "definicao": "Templates nat_abertura_* com status delivered ou read.",
      "limitacao": null
    },
    {
      "id": "resposta_mediana",
      "rotulo": "Tempo até responder",
      "valor": { "ia": 4.2, "humano": 1393.3 }, "unidade": "segundos",
      "n": { "ia": 77, "humano": 38 },
      "relogio": "SP (messages.timestamp)",
      "confianca": "media",
      "definicao": "Da primeira mensagem do lead até o primeiro outbound que não é template.",
      "limitacao": "Populações diferentes: a Nat responde lead novo que acabou de escrever; o time responde base de follow. A comparação mostra velocidade, não eficácia.",
      "comparacao_ressalvada": true
    },
    {
      "id": "mensagens_por_sdr",
      "rotulo": "Mensagens por SDR",
      "valor": null, "n": 0,
      "relogio": "SP (messages.timestamp)",
      "confianca": "indisponivel",
      "limitacao": "Só dá para atribuir mensagem a uma pessoa a partir de 01/09/2026 16h. Antes disso o dado não existe — e não é zero.",
      "cobertura": { "desde": "2026-09-01T16:00:00", "dias_cobertos": 1, "dias_pedidos": 30 }
    },
    {
      "id": "bulk_pulou",
      "rotulo": "Disparos pulados pela higiene",
      "valor": null, "n": null,
      "confianca": "nao_medivel",
      "limitacao": "O filtro roda e funciona, mas o resultado só existe na resposta HTTP do disparo e não é gravado. Ver RECON_RELATORIOS §4.1."
    }
  ]
}
```

Quatro estados de `confianca` — `alta` · `media` (ressalva na tela) · `indisponivel` (dado
começa depois) · `nao_medivel` (não existe). **Nenhum deles é `0`.** O front renderiza cada um
com um tratamento visual distinto, e `nao_medivel` **nunca** vira barra.

---

## 6. B6 — Proposta de layout

### 6.1 Biblioteca de gráfico: **zero dependência nova** — recomendada

Confirmado no `package.json`: as dependências são `@twilio/voice-sdk`, `axios`, `lucide-react`,
`next`, `react`, `react-dom`, `sonner`. **Nenhuma biblioteca de gráfico.**

| Opção | Custo | Contras |
|---|---|---|
| **A. Barras CSS + SVG inline** (recomendada) | zero instalação; o Dashboard atual já faz isso | linha/área dão trabalho à mão |
| B. `recharts` | ~500 kB no bundle, +1 dependência, `npm install` + build + restart | o build do frontend é o passo que já quebrou uma vez (`FIX_FRONTEND_CHUNK_404_20260825`) |

**Recomendo a A**, e a razão é o formato dos dados: as métricas deste painel são
**comparações de poucas categorias** (IA × humano, 6 etapas do funil, 5 códigos de erro, 3
templates). Barra horizontal com número ao lado resolve todas — e barra horizontal é
`div` + `width: %`. Nenhuma pede série temporal densa, que é onde `recharts` ganharia.

O único gráfico que pediria mais é a evolução diária de volume; um sparkline SVG de 30 pontos é
~20 linhas de `polyline`.

> **Deploy:** `npm run build` **e** restart do `cenat-frontend` juntos, sempre — chunk servido
> por um build e HTML por outro dá 404 (`FIX_FRONTEND_CHUNK_404_20260825`).

### 6.2 Esboço

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Relatórios            [ Hoje ][ 7 dias ][• 30 dias ][ Personalizado ]        │
│  Apurado em 01/09/2026 16:50 (horário de São Paulo)                           │
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐     │
│  │ Nat atendeu   │ │ Responde em   │ │ Reuniões      │ │ Pela página   │     │
│  │      108      │ │    4,2 s   ⓘ  │ │      1        │ │      20       │     │
│  │ de 120 (90%)  │ │ time: 23 min  │ │ marcadas      │ │ de obrigado   │     │
│  │ aberturas     │ │ ⚠ populações  │ │ pela Nat      │ │ (auto-serviço)│     │
│  │               │ │   diferentes  │ │               │ │               │     │
│  └───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘     │
│                                                                              │
│  Onde a conversa para                     Resposta por template de abertura  │
│  ─────────────────────                    ─────────────────────────────────  │
│  Respondeu      ████████████ 79           Qualificação  ██████ 20/60 (33%)   │
│  Deu formação   ███████████  74           Já agendado   ███████ 13/32 (41%)  │
│  Deu o ano      ███████      47  ← -36%   Sem formação  █████ 9/28 (32%)     │
│  Deu atuação    ██████       42                                              │
│  Deu motivação  █████        37           Base: 120 aberturas entregues      │
│                                                                              │
│  Base: 120 conversas · o funil é sobre quem RESPONDEU                        │
├──────────────────────────────────────────────────────────────────────────────┤
│  Saúde da Nat                             Atritos                            │
│  Silêncio em etapa ativa      0  ✅       Conversas cortadas por envio        │
│  Vigias disparados            0  ✅       humano: 45 (43 antes do fix         │
│  Encerrado por inatividade   15           de 29/08, 2 depois)                 │
│  Transferido ao humano       53                                              │
│                                           Disparos pulados pela higiene:     │
│                                           ⚠ não medível — ver nota           │
├──────────────────────────────────────────────────────────────────────────────┤
│  Follow do time                                                              │
│  ⓘ Só mensagens de WhatsApp. Ligações não entram — não ficam registradas.    │
│  ┌──────────────────┬─────────┬────────────┬──────────────┐                  │
│  │ Template         │ Enviados│ Responderam│ Taxa (24h)   │                  │
│  ├──────────────────┼─────────┼────────────┼──────────────┤                  │
│  │ ainda_ha_interes.│      16 │          5 │ 31,3%        │                  │
│  │ f4_audio_confirma│      42 │          7 │ 16,7%        │                  │
│  │ f3_guia (lote)   │      34 │          0 │  0,0%        │                  │
│  └──────────────────┴─────────┴────────────┴──────────────┘                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Regras de renderização

* **N sempre visível**, ao lado ou embaixo do %. Nunca "31%" sozinho.
* **Definição em `title`/tooltip** no ⓘ de cada card — o texto vem do campo `definicao` do JSON,
  não do front. Uma fonte.
* **Ressalva de comparação na tela, não no rodapé.** Onde `comparacao_ressalvada: true`, o card
  ganha uma linha visível em âmbar: *"populações diferentes — a Nat pega lead novo, o time pega
  base de follow"*.
* **`nao_medivel` nunca vira barra nem zero** — vira um bloco de texto com o motivo e o link
  para o recon.
* Página **somente leitura**. Sem botão, sem ação, sem exportar (por ora).

---

## 7. O risco que nenhum bloco cobre: o número que muda sozinho

Vale isolar, porque é o que vai gerar a primeira dúvida da Isa.

Três métricas mudam de valor quando recalculadas sobre a **mesma janela**, sem bug nenhum:
"reuniões indeterminadas", "leads sem resposta", "perguntas em aberto". São todas da forma
*"quantos ainda não foram atendidos"* — e o "ainda" se move.

**Proposta:** carimbo `Apurado em <data hora> (SP)` no topo, sempre visível, e o texto de tooltip
nessas métricas específicas:

> *"Este número conta quem ainda não foi atendido até agora. Se alguém do time responder essas
> pessoas hoje, o número cai — mesmo você escolhendo o mesmo período."*

É uma frase. Sem ela, a página e o `.md` vão parecer contradizer um ao outro.

---

## 8. B7 — O corte do MVP

**Sua aposta era 1–4, 6 e 7 no MVP; 5 depois; 8–10 por último. A medição muda em dois pontos.**

| # | Métrica | Custo | Entra? | Por quê |
|---|---|---|---|---|
| 1 | Atendimento da IA | < 10 ms | **MVP** | pronta |
| 2 | Tempo de resposta | 39 ms | **MVP** | é o número que mais impressiona, e o mais robusto em ordem de grandeza |
| 3 | Reuniões da IA | 3 ms | **MVP** | pronta |
| 4 | Reuniões da página | 3 ms (mesma query) | **MVP** | sai de graça junto com a 3 |
| 7 | Saúde da IA | < 20 ms | **MVP** | pronta, e é o card que dá confiança no resto |
| **8** | **Funil por etapa + template** | **< 15 ms** | **MVP** ⬆️ | **você pôs para depois; é das mais baratas e é a que responde "por que o lead some"** |
| **10** | **Vão do espontâneo** | **< 20 ms** | **MVP** ⬆️ | **idem — uma query, e é a métrica com ação direta: uma lista de gente para ligar hoje** |
| **6** | **Atritos IA × humano** | — | **MVP parcial** ⬇️ | **a metade dos skips não é medível (§4.1). Entra só a metade das transferências, com nota** |
| 9 | Follow humano | 29 ms | **v2** | a mais cara e a mais complexa (ilhas, famílias por `LIKE`); nada nela é urgente |
| **5** | **Por SDR** | < 5 ms | **v2** ⬆️ | **entra quando tiver ~1 semana de `sent_by`. Hoje mostraria uma barra com "1"** |

**O critério do corte, dito:** entra no MVP o que é **barato de medir** *e* **caro de não saber**.
Sai o que precisa de dado que ainda não existe (5), o que é caro de construir sem ser urgente (9),
e a metade da 6 que a instrumentação não alcança.

**Duas discordâncias com sua aposta, e a evidência:**

1. **A 8 e a 10 são mais baratas que a 6.** A 8 é um `GROUP BY` sobre 120 linhas; a 10 é um
   `LIKE` de prefixo. A 6, que você pôs no MVP, é a **única do inventário com metade não
   medível**. Trocar as duas por ela melhora o MVP em conteúdo e reduz o número de notas de
   ressalva na tela.
2. **A 10 é a única métrica da lista que produz uma ação.** As outras nove descrevem; a 10
   devolve **nomes de pessoas que escreveram e ninguém respondeu**. Para uma página que a
   gestora vai abrir sozinha, essa é a que justifica abrir de novo amanhã.

---

## 9. CHECKPOINT

### 9.1 Decisões de ENGENHARIA — precisam só do Álefe

| # | Decisão | Recomendação | Se aprovado |
|---|---|---|---|
| E1 | Reescrever a mediana numa passada (39 ms) e **re-baselinar** o número | **sim** | o `.md` de 29/08 ganha nota de que a baseline mudou |
| E2 | `app/relatorios.py` como dono único de `agora_sp` / `janela` / `para_utc` / predicado de teste / chave SQL | **sim** | ~80 linhas + teste comparando com `app/telefone.py` |
| E3 | **Corrigir o `zz` do predicado de teste** (48 leads reais afetados) | **sim, e é urgente** | uma linha; vale independente da página |
| E4 | Gate por `get_current_admin`, sem role nova | **sim** | zero migração |
| E5 | Layout sem dependência nova (CSS + SVG) | **sim** | evita mexer no build |
| E6 | Vários endpoints por seção, não um monolítico | **sim** | isolamento de falha |
| E7 | **Não** construir cache | **sim** | revisitar só acima de ~300 mil linhas em `messages` |
| E8 | Tabela `disparo_skip` para destravar a métrica 6 | **sim, mas fora do MVP** | migração aditiva; a métrica 6 entra completa na v2 |
| E9 | Consertar o fuso do `dashboard_stats` atual | **sim, trabalho separado** | 2 linhas; hoje o painel antigo zera das 21h às 24h |

### 9.2 Decisões de PRODUTO — podem precisar da Isa

| # | Decisão | Por que não é minha |
|---|---|---|
| **P1** | **A precedência de 4 vias das reuniões**, com a categoria nova `LP incompleta` (4 casos) | muda o número que já circulou (18 → 20). Quem usa o número decide se quer a categoria separada ou empilhada em "indeterminada" |
| **P2** | **O denominador do funil.** Sobre quem respondeu (79) ou sobre todas as conversas (120)? | os dois são defensáveis e dão gráficos diferentes; o publicado hoje mistura os dois |
| **P3** | **O texto do aviso de `sent_by`** (§2.3) e o de "número que muda sozinho" (§7) | são as duas frases que decidem se a Isa confia na página ou desconfia dela |
| **P4** | **O corte do MVP** — aceita trocar a 6 pelas 8 e 10? | é escolha de o que a gestora vê primeiro |
| **P5** | A Ana (`atendente`) deve ver a página? | E4 assume que não |

### 9.3 O que NÃO precisa de decisão

Nada foi implementado nesta rodada. Nenhuma linha de produção mudou, nenhuma migração rodou,
nenhuma mensagem saiu. As queries do Anexo estão prontas para virar código no momento em que o
checkpoint fechar.

---

## Anexo A — Queries finais, com o relógio declarado

> Todas parametrizadas por `:ini` e `:fim` **naive-SP**. Onde a tabela é UTC, a conversão está
> marcada com `-- UTC:` e é feita no bind, não no SQL.

### A.1 Chave de telefone e predicado de teste — a fonte única

```sql
-- RELÓGIO: n/a. Espelha app/telefone.py:chave_telefone (DDD + últimos 8 dígitos).
-- Sem isto, 340 pessoas contam como duas.
CASE WHEN length(d) IN (10,11) THEN substr(d,1,2)||right(d,8) ELSE '' END
FROM (SELECT CASE WHEN wa LIKE '55%' AND length(wa) IN (12,13)
                  THEN substr(wa,3) ELSE wa END AS d) x

-- ⚠️ ÂNCORA no zz. Sem ela, 48 leads REAIS casam (Pozzebon, Rizzato, Azzi, Mazzeo…).
-- Medido contra 9.299 leads em 01/09/2026. Quem mexer, MEÇA DE NOVO.
name ~* '(^\s*zz|smoke|teste|\mtest|john doe|fafaf|alefe|thobias justino)'
```

### A.2 Métrica 2 — tempo de resposta (39 ms, substitui a versão de 679 ms)

```sql
-- RELÓGIO: SP (messages.timestamp). Uma passada, sem LATERAL correlacionado.
-- Confere com a versão antiga na janela de 29/08: ia n=77/4,2s · humano n=38/1393,3s.
WITH mk AS (
  SELECT m.id, m.direction, m.message_type, m.timestamp AS ts, m.nat_etapa,
         CASE WHEN length(d.dd) IN (10,11) THEN substr(d.dd,1,2)||right(d.dd,8)
              ELSE m.contact_wa_id END AS thr
  FROM messages m,
  LATERAL (SELECT CASE WHEN m.contact_wa_id LIKE '55%' AND length(m.contact_wa_id) IN (12,13)
                       THEN substr(m.contact_wa_id,3) ELSE m.contact_wa_id END AS dd) d
  WHERE m.timestamp >= :ini AND m.timestamp <= :fim
), w AS (
  SELECT thr, ts, direction, id,
    lag(direction) OVER p AS dir_ant,
    min(ts) FILTER (WHERE direction='outbound' AND message_type<>'template')
            OVER (PARTITION BY thr ORDER BY ts, id
                  ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING) AS ts_resp,
    (array_agg(nat_etapa) FILTER (WHERE direction='outbound' AND message_type<>'template')
            OVER (PARTITION BY thr ORDER BY ts, id
                  ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING))[1] AS etapa_resp
  FROM mk WINDOW p AS (PARTITION BY thr ORDER BY ts, id))
SELECT CASE WHEN etapa_resp IS NOT NULL THEN 'ia' ELSE 'humano' END AS quem,
       count(*) AS n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM (ts_resp-ts))) AS mediana_seg
FROM w
WHERE direction='inbound' AND dir_ant IS DISTINCT FROM 'inbound' AND ts_resp IS NOT NULL
GROUP BY 1;
```

### A.3 Métricas 3 e 4 — reuniões, precedência de 4 vias (3 ms)

```sql
-- RELÓGIO: exact_stage_events.observado_em = UTC (bind já convertido).
--          agendamentos.created_at = UTC; slot_inicio = SP.
WITH ev AS (
  SELECT DISTINCT e.exact_lead_id FROM exact_stage_events e
  WHERE e.observado_em >= :ini_utc AND e.observado_em <= :fim_utc
    AND e.stage_para = 'Agendados' AND e.funnel_id = 18535)
SELECT CASE
  WHEN EXISTS (SELECT 1 FROM agendamentos a WHERE a.lead_id=ev.exact_lead_id
                 AND a.passo='agendado' AND a.origem_ip IS NULL)  THEN 'ia'
  WHEN EXISTS (SELECT 1 FROM agendamentos a WHERE a.lead_id=ev.exact_lead_id
                 AND a.passo='agendado')                          THEN 'landing_page'
  WHEN EXISTS (SELECT 1 FROM agendamentos a WHERE a.lead_id=ev.exact_lead_id)
                                                                  THEN 'lp_incompleta'
  ELSE 'indeterminada' END AS origem, count(*)
FROM ev GROUP BY 1;
-- ⚠️ Conversão para etapa: sempre com a guarda das duas etapas homônimas —
--    AND NOT (stage_de ILIKE '%Agendad%' OR stage_de ILIKE '%Reagendament%')
```

### A.4 Métrica 8 — funil e resposta por template (< 15 ms)

```sql
-- RELÓGIO: nat_qualificacao_state.created_at = UTC; messages.timestamp = SP.
-- DENOMINADOR: quem RESPONDEU (ver §1.2d — o publicado misturava duas bases).
WITH q AS (
  SELECT s.*, coalesce(nullif(kk.k,''), s.contact_wa_id) AS thr
  FROM nat_qualificacao_state s
  LEFT JOIN LATERAL (SELECT CASE WHEN length(d) IN (10,11)
                                 THEN substr(d,1,2)||right(d,8) ELSE '' END AS k
    FROM (SELECT CASE WHEN s.contact_wa_id LIKE '55%'
                       AND length(s.contact_wa_id) IN (12,13)
                      THEN substr(s.contact_wa_id,3) ELSE s.contact_wa_id END AS d) x) kk ON true
  WHERE s.created_at >= :ini_utc AND s.created_at <= :fim_utc)
SELECT count(*) AS respondeu,
       count(*) FILTER (WHERE formacao      IS NOT NULL) AS deu_formacao,
       count(*) FILTER (WHERE ano_conclusao IS NOT NULL) AS deu_ano,
       count(*) FILTER (WHERE atuacao       IS NOT NULL) AS deu_atuacao,
       count(*) FILTER (WHERE motivacao     IS NOT NULL) AS deu_motivacao
FROM q WHERE EXISTS (SELECT 1 FROM messages i, LATERAL (SELECT 1) _
                     WHERE i.direction='inbound' AND i.timestamp >= :ini
                       AND i.contact_wa_id = q.contact_wa_id);
```

### A.5 Métrica 10 — vão do espontâneo (< 20 ms)

```sql
-- RELÓGIO: SP. ⚠️ PARÊNTESES no OR: sem eles o predicado vira (direction AND A) OR B
-- e captura outbound — foi o erro que devolveu 908 em vez de 38 na primeira tentativa.
WITH bot AS (
  SELECT contact_wa_id, min(timestamp) AS escreveu
  FROM messages
  WHERE direction='inbound' AND timestamp >= :ini AND timestamp <= :fim
    AND ( lower(translate(content,'áàâãéêíóôõúüç','aaaaeeiooouuc'))
            LIKE 'ola! tudo bem? fiz minha aplicacao%'
       OR lower(translate(content,'áàâãéêíóôõúüç','aaaaeeiooouuc'))
            LIKE 'ola! tudo bem? manifestei interesse%' )
  GROUP BY 1)
SELECT count(*) AS escreveram,
       count(*) FILTER (WHERE NOT EXISTS (
         SELECT 1 FROM messages o WHERE o.contact_wa_id = bot.contact_wa_id
           AND o.direction='outbound' AND o.timestamp > bot.escreveu)) AS sem_resposta
FROM bot;
```

### A.6 Métrica 7 — saúde (< 20 ms)

```sql
-- RELÓGIO: SP (transferido_em, encerrado_em, run_at).
-- Invariante: silêncio em etapa ativa DEVE ser 0.
SELECT count(*) AS silencio_em_etapa_ativa
FROM messages i JOIN nat_qualificacao_state s ON s.contact_wa_id = i.contact_wa_id
WHERE i.direction='inbound' AND i.timestamp >= :ini
  AND s.etapa IN ('aguardando_formacao','aguardando_ano','aguardando_atuacao',
                  'aguardando_motivacao','ofertando_agenda','escolhendo_slot')
  AND NOT EXISTS (SELECT 1 FROM messages o WHERE o.contact_wa_id = i.contact_wa_id
                    AND o.direction='outbound' AND o.timestamp > i.timestamp);

SELECT coalesce(encerrado_motivo, transferido_motivo, '-') AS motivo, count(*)
FROM nat_qualificacao_state
WHERE coalesce(encerrado_em, transferido_em) BETWEEN :ini AND :fim GROUP BY 1;
```

---

*Recon de 01/09/2026, 16h50 SP. Somente leitura — nenhum dado de produção foi alterado,
nenhuma mensagem foi enviada.*
