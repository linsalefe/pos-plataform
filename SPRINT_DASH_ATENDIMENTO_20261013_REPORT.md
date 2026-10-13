# SPRINT — Dashboard de Atendimento (13/10/2026)

Pedido da Isa: painel de tela inteira mostrando como o time responde os leads e quem está sem
retorno, com atalho para a conversa. Branch `feat/dash-atendimento`. No ar em `/atendimento`
(admin) desde 13/10/2026, ~15h35 SP.

## 0. O que a Isa deve saber antes de ler a tela

1. **Template não conta como resposta.** Disparo em massa e follow depois de uma pergunta não
   a respondem. Elas aparecem como "recebeu só template" e contam como sem resposta. Ligação
   também não conta: só mensagem de WhatsApp.
2. **Duas leituras do SLA de 2 h.** *Corrido*: relógio de 24 h. *Expediente*: o relógio só
   anda das 8h às 20h30, todos os dias (a janela das réguas; feriado não tratado). Pergunta
   às 23h respondida às 8h30 é falha no corrido e 30 min no expediente. O toggle está no topo.
3. **Quem respondeu (`sent_by`) só existe a partir de 01/09/2026, 16h.** Antes disso as
   respostas do time não têm autor; a tela avisa quando o período cruza essa data.
4. **"De quem era a pergunta" é inferido no histórico.** Respondida: vale quem respondeu.
   Sem resposta: é da automação se a última mensagem nossa antes dela era do agente ou da
   régua (`nat_etapa`), senão do time. O SDR é o **dono atual** do contato, não o da época.
   Na lista de pendentes (agora) o dono é o estado real: agente ativo, régua viva, ou SDR.
5. **A mediana é a mesma do /relatorios/humano.** Mesmo algoritmo, mesmo N: em 30 dias,
   time n=229 / 5 h 11 e IA n=395 / 4,3 s nas duas telas.

## 1. Definições (iguais às do `/relatorios/humano`)

| termo | regra |
|---|---|
| conversa | thread por telefone, tolerante ao 9º dígito (`relatorios.CHAVE_MSG`) |
| pergunta | `inbound` cuja anterior na thread não é `inbound`; rajada conta uma |
| resposta | primeira `outbound` com `message_type <> 'template'` depois da pergunta |
| IA / time | `nat_etapa` da resposta preenchida = automação (agente ou régua); senão time |
| no SLA | resposta em até 2 h; denominador = perguntas respondidas ou com prazo de 2 h vencido |
| janela perdida | 24 h desde a **última** mensagem do lead sem resposta nossa (é assim que a Meta conta) |
| janela na lista viva | `aberta` < 20 h ≤ `perto` < 24 h ≤ `expirada` |
| pendente | lead escreveu nos últimos 7 dias, falou por último, e nada nosso fora template veio depois |

## 2. Endpoints e custo

`GET /api/atendimento/{resumo,serie,sdr,pendentes}`, todos com `get_current_admin` no router.
Envelope de `relatorios.envelope` (período, leads de teste, `definicao`/`limitacao` em cada
métrica); predicado de teste em toda consulta; aviso de cobertura de `sent_by`.

| consulta | 30 dias | 90 dias |
|---|---|---|
| `SQL_PERGUNTAS` (uma linha por pergunta) | 114 ms | 247 ms |
| `SQL_PENDENTES` (lookback 7 d / 30 d) | 39 ms | 77 ms |
| `SQL_AGENTE_ATIVO` · `SQL_REGUA_VIVA` | < 1 ms | < 1 ms |

Rota inteira, em produção, com cache quente: `resumo` 0,36 s (roda `SQL_PERGUNTAS` duas
vezes, período atual e anterior, mais pendentes), `serie` 0,13 s, `sdr` 0,17 s,
`pendentes` 0,06 s.

Ajustes feitos para caber nos 300 ms:
- pendentes calculava a chave (regex) nas 39 mil mensagens: 288 ms. Pré-filtro por
  `right(contact_wa_id, 8)` e `MATERIALIZED` nos CTEs (sem ele o planner empurra o predicado
  da chave para dentro da varredura): 39 ms.
- perguntas fazia `JOIN` de volta em `messages` para achar autor e etapa da resposta: troquei
  por `array_agg(...) OVER` na mesma janela.

**Índice proposto, não criado:** `CREATE INDEX ix_messages_timestamp ON messages(timestamp)`.
Hoje toda consulta por período varre `messages` inteira (39 mil linhas, barato). É o
primeiro que vai pesar quando a base crescer.

### 2.1 `EXPLAIN ANALYZE` — `SQL_PERGUNTAS`, 30 dias (linhas longas cortadas em 160 colunas)

```
Hash Left Join  (cost=6397.86..8590.17 rows=1082 width=1181) (actual time=75.143..113.767 rows=893 loops=1)
  Hash Cond: (c.assigned_to = ud.id)
  ->  Hash Left Join  (cost=6386.96..8576.23 rows=1082 width=665) (actual time=75.107..113.506 rows=893 loops=1)
        Hash Cond: ((w.wa)::text = (c.wa_id)::text)
        ->  Hash Left Join  (cost=6007.11..8193.53 rows=1082 width=661) (actual time=71.597..109.647 rows=893 loops=1)
              Hash Cond: (w.sent_by_resp = ur.id)
              ->  Subquery Scan on w  (cost=5996.21..8179.74 rows=1082 width=145) (actual time=71.551..109.383 rows=893 loops=1)
                    Filter: (((w.dir_ant)::text IS DISTINCT FROM 'inbound'::text) AND ((w.direction)::text = 'inbound'::text))
                    Rows Removed by Filter: 4418
                    ->  WindowAgg  (cost=5996.21..8108.56 rows=4745 width=295) (actual time=71.546..108.824 rows=5311 loops=1)
                          ->  Incremental Sort  (cost=5996.21..7989.94 rows=4745 width=218) (actual time=71.534..103.799 rows=5311 loops=1)
                                Sort Key: g.thr, g.rajada
                                Presorted Key: g.thr
                                Full-sort Groups: 137  Sort Method: quicksort  Average Memory: 30kB  Peak Memory: 30kB
                                ->  WindowAgg  (cost=5986.53..7737.30 rows=4745 width=218) (actual time=71.229..100.599 rows=5311 loops=1)
                                      ->  Subquery Scan on g  (cost=5986.53..7511.91 rows=4745 width=138) (actual time=71.190..81.846 rows=5311 loops=1)
                                            ->  WindowAgg  (cost=5986.53..7464.46 rows=4745 width=138) (actual time=71.188..81.084 rows=5311 loops=1)
                                                  ->  WindowAgg  (cost=5986.53..6989.96 rows=4745 width=130) (actual time=71.167..76.680 rows=5311 loops=1)
                                                        ->  Gather Merge  (cost=5986.53..6527.32 rows=4745 width=98) (actual time=71.151..72.993 rows=5311 lo...
                                                              Workers Planned: 1
                                                              Workers Launched: 1
                                                              ->  Sort  (cost=4986.52..4993.50 rows=2791 width=98) (actual time=65.085..65.511 rows=2656 loop...
                                                                    Sort Key: (COALESCE(NULLIF(CASE WHEN (length(CASE WHEN ((regexp_replace((COALESCE(m.conta...
                                                                    Sort Method: quicksort  Memory: 467kB
                                                                    Worker 0:  Sort Method: quicksort  Memory: 472kB
                                                                    ->  Parallel Seq Scan on messages m  (cost=0.00..4826.79 rows=2791 width=98) (actual time...
                                                                          Filter: (("timestamp" >= '2026-09-13 00:00:00'::timestamp without time zone) AND ("...
                                                                          Rows Removed by Filter: 16972
              ->  Hash  (cost=10.40..10.40 rows=40 width=520) (actual time=0.022..0.023 rows=8 loops=1)
                    Buckets: 1024  Batches: 1  Memory Usage: 9kB
                    ->  Seq Scan on users ur  (cost=0.00..10.40 rows=40 width=520) (actual time=0.009..0.011 rows=8 loops=1)
        ->  Hash  (cost=248.27..248.27 rows=10527 width=17) (actual time=3.414..3.415 rows=8722 loops=1)
              Buckets: 16384  Batches: 1  Memory Usage: 538kB
              ->  Seq Scan on contacts c  (cost=0.00..248.27 rows=10527 width=17) (actual time=0.006..1.662 rows=8722 loops=1)
  ->  Hash  (cost=10.40..10.40 rows=40 width=520) (actual time=0.014..0.015 rows=8 loops=1)
        Buckets: 1024  Batches: 1  Memory Usage: 9kB
        ->  Seq Scan on users ud  (cost=0.00..10.40 rows=40 width=520) (actual time=0.007..0.007 rows=8 loops=1)
Planning:
Planning Time: 1.696 ms
Execution Time: 114.295 ms
```

### 2.2 `EXPLAIN ANALYZE` — `SQL_PENDENTES`, lookback de 7 dias

```
Nested Loop Left Join  (cost=13010.74..13100.88 rows=13 width=700) (actual time=38.037..38.642 rows=48 loops=1)
  CTE cand
    ->  Unique  (cost=5626.94..5655.59 rows=242 width=32) (actual time=11.165..11.380 rows=101 loops=1)
          ->  Gather Merge  (cost=5626.94..5654.98 rows=246 width=32) (actual time=11.164..11.342 rows=220 loops=1)
                Workers Planned: 1
                Workers Launched: 1
                ->  Sort  (cost=4626.93..4627.29 rows=145 width=32) (actual time=7.946..7.954 rows=110 loops=2)
                      Sort Key: (COALESCE(NULLIF(CASE WHEN (length(CASE WHEN ((regexp_replace((COALESCE(m.contact_wa_id, ''::character varying))::text, '\D':...
                      Sort Method: quicksort  Memory: 30kB
                      Worker 0:  Sort Method: quicksort  Memory: 29kB
                      ->  Parallel Seq Scan on messages m  (cost=0.00..4621.72 rows=145 width=32) (actual time=2.693..7.805 rows=110 loops=2)
                            Filter: (("timestamp" >= '2026-10-06 15:32:06.507932'::timestamp without time zone) AND ((direction)::text = 'inbound'::text) AND...
                            Rows Removed by Filter: 19518
  CTE mk
    ->  Hash Join  (cost=9.95..4196.54 rows=19615 width=257) (actual time=11.918..34.577 rows=1112 loops=1)
          Hash Cond: ("right"((m_1.contact_wa_id)::text, 8) = "right"(cand.thr, 8))
          ->  Seq Scan on messages m_1  (cost=0.00..2291.30 rows=39230 width=225) (actual time=0.008..9.764 rows=39256 loops=1)
          ->  Hash  (cost=7.45..7.45 rows=200 width=32) (actual time=11.449..11.450 rows=101 loops=1)
                Buckets: 1024  Batches: 1  Memory Usage: 13kB
                ->  HashAggregate  (cost=5.45..7.45 rows=200 width=32) (actual time=11.377..11.400 rows=101 loops=1)
                      Group Key: "right"(cand.thr, 8)
                      Batches: 1  Memory Usage: 48kB
                      ->  CTE Scan on cand  (cost=0.00..4.84 rows=242 width=32) (actual time=11.168..11.319 rows=101 loops=1)
  CTE k
    ->  Hash Join  (cost=7.87..1274.99 rows=23734 width=234) (actual time=11.981..35.699 rows=1110 loops=1)
          Hash Cond: (mk.thr = cand_1.thr)
          ->  CTE Scan on mk  (cost=0.00..392.30 rows=19615 width=234) (actual time=11.921..35.217 rows=1112 loops=1)
          ->  Hash  (cost=4.84..4.84 rows=242 width=32) (actual time=0.039..0.040 rows=101 loops=1)
                Buckets: 1024  Batches: 1  Memory Usage: 13kB
                ->  CTE Scan on cand cand_1  (cost=0.00..4.84 rows=242 width=32) (actual time=0.001..0.016 rows=101 loops=1)
  CTE q
    ->  Hash Join  (cost=718.52..1256.05 rows=7990 width=234) (actual time=36.840..37.311 rows=341 loops=1)
          Hash Cond: (k.thr = k_1.thr)
          Join Filter: (((max(k_1.ts) FILTER (WHERE (((k_1.direction)::text = 'outbound'::text) AND ((k_1.message_type)::text <> 'template'::text)))) IS NULL...
          Rows Removed by Join Filter: 769
          ->  CTE Scan on k  (cost=0.00..474.68 rows=23734 width=234) (actual time=11.983..12.189 rows=1110 loops=1)
          ->  Hash  (cost=716.02..716.02 rows=200 width=40) (actual time=24.839..24.841 rows=101 loops=1)
                Buckets: 1024  Batches: 1  Memory Usage: 14kB
                ->  HashAggregate  (cost=712.02..714.02 rows=200 width=40) (actual time=24.799..24.813 rows=101 loops=1)
                      Group Key: k_1.thr
                      Batches: 1  Memory Usage: 48kB
                      ->  CTE Scan on k k_1  (cost=0.00..474.68 rows=23734 width=136) (actual time=0.000..24.377 rows=1110 loops=1)
  ->  Nested Loop Left Join  (cost=627.42..716.15 rows=13 width=191) (actual time=38.024..38.476 rows=48 loops=1)
        ->  Merge Join  (cost=627.13..628.43 rows=13 width=178) (actual time=37.993..38.185 rows=48 loops=1)
              Merge Cond: (q.thr = q_2.thr)
              ->  GroupAggregate  (cost=446.30..446.65 rows=13 width=88) (actual time=37.846..37.971 rows=48 loops=1)
                    Group Key: q.thr, o.ult_tpl, o.primeira_sem_resposta
                    ->  Sort  (cost=446.30..446.33 rows=13 width=56) (actual time=37.826..37.835 rows=68 loops=1)
                          Sort Key: q.thr, o.ult_tpl, o.primeira_sem_resposta
                          Sort Method: quicksort  Memory: 30kB
                          ->  Hash Join  (cost=266.18..446.06 rows=13 width=56) (actual time=37.718..37.789 rows=68 loops=1)
                                Hash Cond: (q.thr = o.thr)
                                Join Filter: ((o.ult_tpl IS NULL) OR (q.ts > o.ult_tpl))
                                Rows Removed by Join Filter: 64
                                ->  CTE Scan on q  (cost=0.00..179.78 rows=40 width=40) (actual time=36.847..36.885 rows=132 loops=1)
                                      Filter: ((direction)::text = 'inbound'::text)
                                      Rows Removed by Filter: 209
                                ->  Hash  (cost=263.68..263.68 rows=200 width=48) (actual time=0.844..0.845 rows=79 loops=1)
                                      Buckets: 1024  Batches: 1  Memory Usage: 13kB
                                      ->  Subquery Scan on o  (cost=259.68..263.68 rows=200 width=48) (actual time=0.803..0.822 rows=79 loops=1)
                                            ->  HashAggregate  (cost=259.68..261.68 rows=200 width=48) (actual time=0.802..0.814 rows=79 loops=1)
                                                  Group Key: q_1.thr
                                                  Batches: 1  Memory Usage: 40kB
                                                  ->  CTE Scan on q q_1  (cost=0.00..159.80 rows=7990 width=78) (actual time=0.000..0.682 rows=341 loops=1)
              ->  Unique  (cost=180.84..181.04 rows=36 width=138) (actual time=0.142..0.177 rows=61 loops=1)
                    ->  Sort  (cost=180.84..180.94 rows=40 width=138) (actual time=0.142..0.152 rows=132 loops=1)
                          Sort Key: q_2.thr, q_2.ts DESC, q_2.id DESC
                          Sort Method: quicksort  Memory: 48kB
                          ->  CTE Scan on q q_2  (cost=0.00..179.78 rows=40 width=138) (actual time=0.002..0.046 rows=132 loops=1)
                                Filter: ((direction)::text = 'inbound'::text)
                                Rows Removed by Filter: 209
        ->  Index Scan using ix_contacts_wa_id on contacts c  (cost=0.29..6.75 rows=1 width=26) (actual time=0.005..0.005 rows=1 loops=48)
              Index Cond: ((wa_id)::text = (q_2.wa)::text)
  ->  Memoize  (cost=0.15..0.17 rows=1 width=520) (actual time=0.001..0.001 rows=1 loops=48)
        Cache Key: c.assigned_to
        Cache Mode: logical
        Hits: 43  Misses: 5  Evictions: 0  Overflows: 0  Memory Usage: 1kB
        ->  Index Scan using users_pkey on users u  (cost=0.14..0.16 rows=1 width=520) (actual time=0.003..0.003 rows=1 loops=5)
              Index Cond: (id = c.assigned_to)
Planning:
Planning Time: 1.081 ms
Execution Time: 38.991 ms
```

## 3. Números de hoje (13/10/2026, ~15h35 SP, 30 dias, `quem=time`)

| | período (13/09 a 13/10) | período anterior (13/08 a 13/09) |
|---|---|---|
| Sem resposta agora | **47** (15 abertas · 0 perto · 32 expiradas) | — |
| Mediana, corrido / expediente | **5 h 11 / 3 h 46** (n=229) | 1 h 56 |
| No SLA de 2 h, corrido / expediente | **20,8% / 21,3%** (n=451) | 12,2% |
| Janelas de 24 h perdidas | **259** de 453 perguntas | 355 |
| Taxa de resposta | **50,6%** | 24,1% |

Por SDR (dono atual do contato):

| SDR | perguntas | respondidas | no SLA corrido | no SLA expediente | mediana | janelas perdidas | sem resposta agora |
|---|---|---|---|---|---|---|---|
| Thobias | 280 | 161 | 22,6% | 22,6% | 6,0 h | 150 | 18 |
| sem dono | 102 | 32 | 14,9% | 16,8% | 2,7 h | 70 | 20 |
| Vi Amorim | 39 | 21 | 23,1% | 23,1% | 4,8 h | 21 | 6 |
| Victória | 21 | 11 | 23,8% | 23,8% | 2,6 h | 10 | 2 |
| Valéria | 11 | 4 | 18,2% | 18,2% | 11,1 h | 8 | 1 |

### Por que o SLA é baixo (é real, não é bug)

O que derruba o número é a pergunta que **nunca** foi respondida, não a resposta de
madrugada (por isso corrido e expediente quase empatam no %). Das 224 sem resposta em 30 dias:

- **62** são a mensagem do botão da LP ("Fiz minha aplicação…" / "Manifestei interesse…") —
  o vão do espontâneo, já conhecido;
- **107** receberam só template depois;
- ruído: **10 reações** e **12** "ok"/"obrigada" (~10%). Mantidos, para não divergir do
  `/relatorios/humano`, que conta reação como pergunta. Excluir `message_type='reaction'`
  muda as duas telas juntas: decisão de produto em aberto.

Fim de semana e feriado (10, 11 e 12/10) quase sem pergunta do time: quem respondeu foi a
automação, que o filtro `quem=time` esconde.

## 4. Exemplo de JSON (`/pendentes`, um item; nome e telefone mascarados)

```json
{
 "wa_id": "5538•••••521",
 "nome": "S••••• R••••",
 "dono_inbound": "sdr",
 "dono_detalhe": null,
 "sdr_id": 5,
 "sdr_nome": "Thobias",
 "esperando_desde": "2026-10-06T18:35:34",
 "ultimo_inb": "2026-10-06T18:35:34",
 "horas_esperando": 164.95,
 "janela": "expirada",
 "janela_fecha_em": "2026-10-07T18:35:34",
 "ultima_msg": "Aguardo sobre o valor mensal",
 "so_template": true,
 "primeira_sem_resposta": "2026-10-01T19:04:11",
 "anomalia": false
}
```

Cada métrica do `/resumo` vem no molde de `relatorios.metrica`, com `valor` e `n` por
relógio e a variação já calculada contra o período anterior de mesma duração:

```json
{"id": "pct_sla", "rotulo": "Respondidas em até 2 h",
 "valor": {"corrido": 20.8, "expediente": 21.3},
 "n": {"corrido": 451, "expediente": 451},
 "confianca": "media", "unidade": "%",
 "variacao": {"corrido": {"anterior": 12.2, "delta": 8.6, "pct": 70.5}, "expediente": {...}},
 "definicao": "Das perguntas cujo prazo de 2 h já venceu ...", "limitacao": "No relógio corrido ..."}
```

## 5. A página

`frontend/src/app/atendimento/page.tsx` + `frontend/src/components/atendimento/`
(`KpiCard`, `SerieChart`, `SlaBarChart`, `HistogramaResposta`, `TabelaSdr`, `ListaPendentes`,
`Dica`, `tipos`). Recharts 2.15.4, versão fixa. Sem `any`.

- Linha 1: período (7/14/30/90 dias e intervalo livre), SDR, Time/IA/Ambos, SLA corrido/expediente.
- Linha 2: 5 cartões com valor, N, seta contra o período anterior (verde quando melhora:
  mediana e janelas melhoram caindo) e ⓘ com a definição e a limitação do backend.
- Linha 3: mediana e % no SLA por dia (ou por hora do dia), barras empilhadas no SLA / fora /
  sem resposta, com "ver tabela".
- Linha 4: histograma (até 15 min · 1 h · 2 h · 6 h · 24 h · mais) e tabela por SDR,
  ordenável; clicar no nome filtra a página.
- Linha 5: lista viva com busca, filtro de janela, badge de dono (SDR, agente, régua), tempo
  esperando, "recebeu só template", linha vermelha para expirada e âmbar para perto, botão
  "Abrir conversa" (`/conversations?wa=`). Atualiza a cada 60 s.
- Sidebar: "Atendimento" (ícone `Timer`), só admin.

Prints com dados reais tirados numa prévia isolada (backend só com as rotas de leitura numa
porta local, front de uma cópia, Chromium headless com toda requisição não-GET bloqueada).
Estão no transcript do checkpoint 2, não no repositório.

## 6. O que mudou na tela de conversas

- **Filtro rápido "Aguardando resposta"**: lead falou por último nos **últimos 7 dias**,
  do mais antigo para o mais novo. Lido do `direction` da mensagem mais recente que o
  `GET /contacts` já funde entre as duas grafias: o endpoint (polling de 5 s) não mudou.
  Em 13/10 trouxe 48 conversas, na mesma ordem da lista do painel (47 do time + 1 do agente).
- **Badge de tempo** em cada conversa em que o lead falou por último: cinza < 2 h, âmbar
  2 h a 20 h, vermelho > 20 h. Conta da última mensagem do lead.
- **`?wa=`**: já era lido no mount (sprint anterior, casando a outra grafia). Nada novo.
- **Correção da carga completa** (fora do escopo, mas o "Abrir conversa" em nova aba
  dependia dela): o `useEffect` da página chamava `/channels` e `/tags` antes de o
  `AuthProvider` pôr o token, 401, e a tela ficava em "Nenhum canal" sem lista. Medido no
  nginx em 13/10: **3 de 23** aberturas de `/conversations`. Agora a carga espera o usuário.

## 7. Desvios, com evidência

| roteiro | feito | por quê |
|---|---|---|
| gráfico de linha com dois eixos | dois painéis com o mesmo eixo X | minutos e % sobrepostos fazem o cruzamento das linhas parecer significativo |
| print claro e escuro | só claro | o Hub desliga o dark mode de propósito (`globals.css`) |
| "expirada = pergunta há mais de 24 h" | conta da última mensagem do lead | é ela que abre a janela de 24 h na Meta |
| lista viva sem recorte | lead que escreveu nos últimos 7 dias (`dias`, até 30) | sem recorte acumulam expiradas de meses |
| "esperando há" desde a pergunta | volta depois de 24 h recomeça a pergunta | caso real: lead escreveu 27/03 e 08/10 sem resposta entre as duas; a lista dizia 4 804 h |
| "Aguardando resposta" sem recorte | últimos 7 dias | sem recorte: 1 103 conversas, as primeiras com 221 dias |
| eixo da mediana livre | limitado a 48 h, dias acima escritos embaixo | um dia de ~290 h achatava todos os outros contra o zero |
| filtro de canal | não exibido | há um canal só |
| papel "gestão" | admin | não existe papel `gestor` (Isa é admin) |
| régua dona do inbound | aproxima `confirmacao._reuniao_dona` sem checar a mensagem imediata | aqui só se rotula; quem roteia é o webhook |

## 8. Achados fora da sprint

- **`chaves_de_teste` custa 3,7 s, não os 75 ms documentados.** `exact_leads` tem 618 MB
  de heap para ~10 mil linhas (inchaço do sync) e o predicado de teste a lê inteira. O cache
  de 600 s esconde quase sempre; a primeira chamada depois dele paga (o `/resumo` levou
  6,8 s logo após o restart). Afeta `/relatorios` também. Resolver pede `VACUUM FULL` ou
  `pg_repack`, que travam a tabela: não feito.
- **No celular o Hub inteiro não cabe**: a sidebar tem 250 px fixos em qualquer largura.

## 9. Testes

`backend/test_atendimento.py`, **escrito e não executado** (compila). Três partes, nenhuma
escreve no banco: (A) funções puras — SLA corrido × expediente (23h → 8h30), bordas
8h/20h30, janela nos limiares exatos de 20 h e 24 h, janela perdida, IA × time por
`nat_etapa`, dono inferido, template contado à parte, pergunta recente fora do SLA,
pendentes com `quem=time` escondendo agente e régua, casamento pela outra grafia, início da
pergunta atual, variação e período anterior, faixas do histograma; (B) `SQL_PERGUNTAS` de
produção sobre tabelas temporárias que sombreiam as reais, com `ROLLBACK` — rajada conta
uma, template não é resposta, IA por `nat_etapa`, lead de teste excluído; (C) leitura da
base real — mediana e N iguais aos do `/relatorios/humano`.

## 10. Deploy

```
tsc --noEmit                         ok
npm run build                        ok (/atendimento na lista de rotas)
import app.main, app.atendimento_routes   ok
systemctl restart cenat-backend cenat-frontend   active / active
/api/atendimento/resumo?periodo=30d  200 (6,8 s frio, 0,36 s quente)
/api/atendimento/serie               200 0,13 s
/api/atendimento/sdr                 200 0,17 s
/api/atendimento/pendentes           200 0,06 s
sem token                            401
chunks do /atendimento               200
```

## Pra depois (não feito)

Alerta para a gestão quando as expiradas do dia passarem de N; CSV da tabela por SDR e dos
pendentes; meta por SDR com cor no cartão; ligação atendida contar como resposta (cruzar
`call_logs`); resposta automática de conta comercial marcada como ruído; decidir se reação
sai da contagem de pergunta (nas duas telas); índice em `messages(timestamp)`.
