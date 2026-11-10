# CASE 2: participação da IA e das automações no faturamento (09-10/11/2026)

**Somente leitura.** SELECT em transação `READ ONLY` e o cache de `LeadsSold` do recon 1. Nenhum GET novo na Exact, nenhuma escrita, nenhum deploy. Continua `CASE_FATURAMENTO_AGENTE_20261109.md` e reaproveita as coortes e funções de `backend/case_faturamento.py`. Script: `backend/case_participacao.py`. Testes: `backend/test_case_participacao.py` (escritos, **não executados**). Checkpoint 1.4 aprovado nos 7 pontos.

Cache usado (o `/tmp/leadssold.json` do plano não existe; era o exemplo de comando do relatório 1):

```
/tmp/claude-1000/-home-ubuntu-pos-plataform/dff71a7f-67ab-4b5c-bae2-0a904589d391/scratchpad/exact/leadssold_all.json
```

São 1.506 linhas, lidas da Exact em 09/11/2026 ~22h UTC. O scratchpad é da sessão: para reproduzir depois, passe outro caminho em `--cache` e o script relê a Exact.

```bash
cd backend
venv/bin/python case_participacao.py --de 2026-10-01 --ate 2026-10-31 --cache <cache> --csv <saida.csv>
venv/bin/python case_participacao.py --de 2026-09-07 --ate 2026-11-08 --cache <cache> --csv <saida.csv>
```

Os CSVs por venda (só `lead_id`, valor, datas e flags) estão no scratchpad: `vendas_out.csv` (outubro) e `vendas_0709.csv`.

## Resumo

1. Outubro teve **48 vendas de pós e R$ 281.923** pelo cache. Nenhum corte reproduz os R$ 253 mil do comercial (§1).
2. **Gerou** (a IA marcou a reunião): em outubro, 4 vendas e **R$ 24.500 (8,7%)**; de 07/09 a 08/11, 9 vendas e R$ 48.047 (8,8%).
3. **Recuperou** (reunião cortada por no-show, a IA trouxe de volta, depois houve venda): **2 vendas, R$ 12.094**, nas duas janelas.
4. **Participou** (a conversa do agente passou pela venda, sem contar o follow por template): em outubro, 23 vendas e **R$ 140.188 (49,7%)**.
5. Entre as reuniões com régua de confirmação, **quem confirmou comprou 2,2 vezes mais**: 30% contra 14% em outubro (p = 0,04), e 32% contra 14% de 07/09 a 08/11 (p = 0,01). É correlação: a régua roda em todo mundo e não existe grupo sem ela para comparar.
6. "Qualquer toque da IA" passa por 95,6% do faturamento de outubro. **É esperado e não vai para conteúdo**: a confirmação e o lembrete rodam em toda reunião vigente, inclusive nas que a SDR marca.

---

## 1. A conta de outubro (0.2)

Vendas de `LeadsSold` com `saleDate` em outubro de 2026, em SP. Contar em UTC dá exatamente o mesmo.

| corte | vendas | valor |
|---|---|---|
| tudo no cache | 58 | R$ 281.923 |
| menos fora dos funis de pós (10 de Intercâmbio, 18285, todas com valor 0) | 48 | R$ 281.923 |
| menos leads de teste | 48 | R$ 281.923 (nenhum de teste) |
| menos valor zero | 45 com valor | R$ 281.923 (3 com valor 0) |
| **o que sobra** | **48 vendas, 45 com valor** | **R$ 281.923** |
| *alternativa: só ciclo 1 (tira a 2ª e a 3ª venda do mesmo lead)* | 42 | R$ 244.976 |
| *alternativa: acumulado até 30/10* | | R$ 255.023 |

- **Funil:** todas as 48 são do funil 18537 e todas estão em Vendidos hoje.
- **`saleStage`:** 47 em "Contratos Gerados" e 1 em "Agendamento SDR" (R$ 6.800).
- **Vendedor:** processoseletivo@ R$ 160.488, comercial@ R$ 121.435.

**Nenhum corte bate com R$ 253 mil.** O número do comercial fica registrado como **"número do comercial, fonte a confirmar"**. Os dois cortes em itálico são os mais próximos e nenhum deles é exato: não forcei coincidência. O que pode explicar a diferença, sem prova: data de pagamento em vez de data de venda, cancelamento depois da venda, ou um relatório da Exact com outro recorte.

## 2. Os flags

Regras comuns:

- **Unidade:** uma venda por lead, a primeira com `saleDate` maior ou igual ao dia da primeira marcação (regra do recon 1). Lead sem marcação entra com a primeira venda do período.
- **Escopo:** funis de pós e fora dos leads de teste (`relatorios.chaves_de_teste`).
- **Toque:** vale o último daquele tipo **com dia menor ou igual ao dia da venda**.
- **Telefone:** a chave tolerante (`thread_sql`, espelhada em Python por `case_participacao.thr`).

Relógios medidos, não lidos de comentário:

| coluna | relógio | prova |
|---|---|---|
| `messages.timestamp`, `agendamentos.created_at`, `reuniao_status.*` | SP | recon 1 §7 |
| `nat_scheduled_actions.processed_at` | SP | 230 de 235 `confirm_a_imediata` no mesmo minuto da `nat_a_confirmacao` |
| `nat_qualificacao_state.created_at` | **UTC** | 322 de 322 estados Fluxo B a exatamente 3 h da `nat_b_abertura` |
| `follow_estagio_envios.enviado_em` | **UTC** | 1.993 de 1.993 envios a exatamente 3 h da mensagem |
| `LeadsSold.saleDate` | UTC | campo da Exact |

| flag | definição | query (resumo) |
|---|---|---|
| `abertura` | o agente abriu ou conduziu a conversa | `messages` de saída com `status <> 'failed'` e `nat_etapa IN ('qualif_conversa','follow_up','nat_abertura_qualificacao','nat_abertura_agendado','nat_abertura_sem_formacao')` |
| `fluxo_b` | aplicou na LP sem marcar e o agente entrou | `nat_qualificacao_state WHERE dados_extras->>'fluxo'='b'`, pelo `created_at - 3h` |
| `follow_etapa` | **template automático por etapa, não é conversa** | `follow_estagio_envios WHERE status='enviado' AND lead_exact_id = lead`, pelo `enviado_em - 3h` |
| `marcou_ia` | a primeira marcação do lead é do agente | `agendamentos` com `passo='agendado' AND origem_ip IS NULL`, sendo a mais antiga do lead (coorte `ia`) |
| `confirmacao` | a régua de confirmação rodou e a 1ª mensagem foi entregue | `nat_scheduled_actions kind='confirm_a_imediata' AND status='executado'`, com `payload.meeting_id` de uma reunião do lead e `nat_a_confirmacao` sem falha a até 30 min |
| `confirmou` | a pessoa confirmou | `reuniao_status.confirmado_em IS NOT NULL` (136 por botão, 1 por texto) |
| `lembrete_t30` | lembrete automático 30 min antes | `kind='lembrete_reuniao' AND status='executado'`, por `payload.meeting_id` (o novo) ou `payload.agendamento_id` (o antigo) |
| ↳ lembrete antigo | até 06/10, saía para toda reunião, sem confirmação | o mesmo, com `processed_at < 07/10` |
| ↳ régua nova | desde 07/10, T-30 só para quem confirmou | o mesmo, com `processed_at >= 07/10` |
| `noshow_regua` | a reunião foi cortada sem confirmação ou caiu em no-show | `reuniao_status.noshow_em IS NOT NULL` (o corte `sem_confirmacao` grava os dois campos: 28 de 28) |
| `noshow_recuperado` | **recuperou**: depois do corte, a pessoa voltou e a venda veio depois | `regua_encerrada_em >= noshow_em` com `regua_encerrada_motivo LIKE 'NS_%' OR = 'humano'`, **ou** marcação nova do lead depois do `noshow_em`; e venda no mesmo dia ou depois |
| `remarcou_ia` | a reunião foi remarcada pelo agente ou pelo botão | agendamento do agente que não é a primeira marcação, ou reunião com `cancelado_motivo` / `regua_encerrada_motivo` = `'remarcar'` |

- **Reuniões do lead (1.2):** as do espelho com `registrado_em` entre o dia da primeira marcação e o dia da venda. Se valer só a reunião da primeira marcação, quase nada muda. É a coluna "1ª reunião só" da §4.
- **O caso 41809715 (ajuste 3):** a SDR marcou a reunião e o agente não falou com a pessoa antes. Por isso ela é "SDR sem toque do agente" na origem do recon 1. Mesmo assim tem `follow_etapa`, porque o follow é template automático, não conversa, e o recon 1 não o considerava. As duas classificações estão certas e medem coisas diferentes.

## 3. Escada

**Os degraus não somam.** Cada degrau é "vendas que passaram por isso", e uma venda pode estar em todos. A percentagem é sobre o faturamento do período.

### Outubro (01 a 31/10, por `saleDate`)

| degrau | vendas | faturamento | % |
|---|---|---|---|
| total do período | 48 | R$ 281.923 | 100% |
| qualquer toque da IA (*esperado, não vai para conteúdo*) | 44 | R$ 269.476 | 95,6% |
| qualquer toque, sem confirmação e lembrete | 29 | R$ 177.435 | 62,9% |
| toque de conversa (abertura, Fluxo B, follow, remarcação) | 29 | R$ 177.435 | 62,9% |
| conversa do agente (sem o follow por template) | 23 | R$ 140.188 | 49,7% |
| régua pós-marcação (confirmação, lembrete, no-show) | 39 | R$ 239.029 | 84,8% |
| recuperada de no-show | 2 | R$ 12.094 | 4,3% |
| **marcada pela IA (gerou)** | **4** | **R$ 24.500** | **8,7%** |

A régua nova começou em 07/10, então as vendas de 01 a 06/10 não tinham confirmação nem no-show.

### 07/09 a 08/11 (o período do recon 1)

| degrau | vendas | faturamento | % |
|---|---|---|---|
| total do período | 96 | R$ 545.081 | 100% |
| qualquer toque da IA (*esperado, não vai para conteúdo*) | 81 | R$ 477.234 | 87,6% |
| qualquer toque, sem confirmação e lembrete | 59 | R$ 346.499 | 63,6% |
| toque de conversa | 59 | R$ 346.499 | 63,6% |
| conversa do agente (sem o follow) | 52 | R$ 303.305 | 55,6% |
| régua pós-marcação (confirmação e no-show **só desde 07/10**; antes disso só existia o lembrete antigo) | 61 | R$ 360.658 | 66,2% |
| recuperada de no-show (só desde 07/10) | 2 | R$ 12.094 | 2,2% |
| **marcada pela IA (gerou)** | **9** | **R$ 48.047** | **8,8%** |

- **Por que 95,6% é esperado:** a régua de confirmação e o lembrete rodam em **toda** reunião vigente de `reuniao_status`, seja do site, do agente ou da SDR. Quase toda venda passa por uma reunião, então quase toda venda "tem toque". Isso mede alcance, não efeito.
- **Por que o "gerou" difere do recon 1:** aqui deu R$ 48.047 em 9 vendas; o recon 1 dava R$ 43.647 em 8. A unidade é a venda com `saleDate` no período. Um lead marcado pelo agente antes de 07/09 vendeu dentro do período (R$ 4.400) e entra aqui, mas ficava fora da coorte de marcação do recon 1.

### Origem da marcação das vendas

| origem | outubro: vendas | R$ | 07/09 a 08/11: vendas | R$ |
|---|---|---|---|---|
| ia | 4 | 24.500 | 9 | 48.047 |
| LP sem toque antes de marcar | 20 | 125.994 | 32 | 194.482 |
| LP com toque do agente antes | 1 | 6.800 | 1 | 6.800 |
| SDR sem toque do agente | 4 | 23.094 | 14 | 78.494 |
| SDR assistida pelo agente | 15 | 89.088 | 33 | 191.511 |
| sem reunião nossa | 4 | 12.447 | 7 | 25.747 |
| **total** | **48** | **281.923** | **96** | **545.081** |

O recon 1 dava 97 vendas e o mesmo valor. A diferença de 1 é a segunda venda de um lead cuja primeira venda é anterior ao período: pela regra da primeira venda, ela não entra.

## 4. Por automação

"Só essa" conta as vendas em que essa automação foi o **único** toque da IA. Duas automações nunca aparecem sozinhas por construção: `fluxo_b` sempre vem com `abertura`, e `marcou_ia` sempre vem com `abertura` e confirmação. O 0 delas na coluna "só essa" é estrutural, não falta de efeito. "1ª reunião só" é a contagem se valer apenas a reunião da primeira marcação.

### Outubro

| automação | o que faz | vendas | R$ | só essa (vendas · R$) | 1ª reunião só |
|---|---|---|---|---|---|
| abertura | o agente abriu ou conduziu a conversa | 19 | 119.988 | 1 · 4.400 | não se aplica |
| fluxo_b | aplicou na LP sem marcar e o agente entrou | 16 | 96.741 | 0 (estrutural) | não se aplica |
| follow_etapa | **template automático por etapa, não é conversa** | 20 | 122.488 | 2 · 12.747 | não se aplica |
| marcou_ia | o agente marcou a primeira reunião (**gerou**) | 4 | 24.500 | 0 (estrutural) | não se aplica |
| confirmacao | régua de confirmação, 1ª mensagem entregue (desde 07/10) | 34 | 212.129 | 5 · 33.700 | 33 |
| confirmou | a pessoa confirmou (resposta, não toque) | 28 | 176.982 | não se aplica | 27 |
| lembrete_t30 (lembrete automático) | 30 min antes, antigo e novo | 27 | 163.382 | 3 · 13.600 | 25 |
| ↳ lembrete antigo (sem confirmação) | até 06/10, para toda reunião | 6 | 33.400 | 3 · 13.600 | 6 |
| ↳ régua nova (desde 07/10) | T-30 só para quem confirmou | 22 | 136.482 | 0 | 19 |
| noshow_regua | corte sem confirmação ou no-show (desde 07/10) | 2 | 12.094 | 0 | 1 |
| noshow_recuperado | **recuperou** | 2 | 12.094 | 0 | 1 |
| remarcou_ia | remarcação pelo agente ou pelo botão | 2 | 12.747 | 0 | não se aplica |

### 07/09 a 08/11

| automação | vendas | R$ | só essa (vendas · R$) | 1ª reunião só |
|---|---|---|---|---|
| abertura | 47 | 278.705 | 16 · 90.529 | não se aplica |
| fluxo_b | 23 | 136.682 | 0 (estrutural) | não se aplica |
| follow_etapa (template, não é conversa) | 25 | 152.776 | 2 · 12.747 | não se aplica |
| marcou_ia (gerou) | 9 | 48.047 | 0 (estrutural) | não se aplica |
| confirmacao (desde 07/10; em setembro não existia) | 43 | 264.817 | 5 · 33.700 | 41 |
| confirmou | 36 | 223.723 | não se aplica | 34 |
| lembrete_t30 (lembrete automático) | 44 | 258.370 | 9 · 45.494 | 41 |
| ↳ lembrete antigo (sem confirmação) | 19 | 102.341 | 9 · 45.494 | 19 |
| ↳ régua nova (desde 07/10) | 26 | 162.529 | 0 | 22 |
| noshow_regua (desde 07/10) | 2 | 12.094 | 0 | 1 |
| noshow_recuperado (recuperou) | 2 | 12.094 | 0 | 1 |
| remarcou_ia | 2 | 12.747 | 0 | não se aplica |

As duas linhas do lembrete somam mais que o total porque uma venda pode ter tido os dois. As 16 vendas "só abertura" de 07/09 a 08/11 são quase todas de setembro (15 de 16) e quase todas SDR assistida (13 de 16): lead que a SDR marcou depois de o agente conversar, quando ainda não existia régua.

## 5. Distância e influência plausível

Dias entre o **último toque de conversa antes da marcação** (abertura, Fluxo B ou follow) e a marcação. Para venda sem reunião nossa, a distância é até a venda, mas nenhuma delas tem toque (§6).

| faixa | outubro: vendas | R$ | 07/09 a 08/11: vendas | R$ |
|---|---|---|---|---|
| mesmo dia | 14 | 82.288 | 22 | 126.829 |
| 1 a 3 dias | 5 | 30.747 | 11 | 61.888 |
| 4 a 7 dias | 2 | 13.300 | 4 | 25.747 |
| 8 a 30 dias (toque antigo) | 0 | não medível | 3 | 18.694 |
| mais de 30 dias (toque antigo) | 0 | não medível | 0 | não medível |
| toque de conversa só depois da marcação | 8 | 51.100 | 19 | 113.341 |
| **influência plausível (até 7 dias)** | **21** | **126.335** | **37** | **214.464** |

- **"Mesmo dia"** inclui todas as vendas `ia`: o agente marca durante a conversa.
- **"Só depois da marcação"** é a pessoa que marcou e só depois recebeu follow por etapa, foi remarcada pelo agente ou entrou no Fluxo B da remarcação. A conversa não levou à marcação.
- **"Influência plausível"** inclui o follow por template.

## 6. LP dividida, venda sem reunião nossa e comparecimento por régua

### 6.1 `landing_page` por toque antes de marcar (critério 5)

| lado | outubro: vendas | R$ | 07/09 a 08/11: vendas | R$ |
|---|---|---|---|---|
| sem toque antes de marcar | 20 | 125.994 | 32 | 194.482 |
| a IA falou antes, a pessoa marcou no site | 1 | 6.800 | 1 | 6.800 |

Na LP, quase toda venda é de quem marcou sozinho. O caso "a IA falou antes" existe, mas tem N = 1. O toque pós-marcação na LP (confirmação, lembrete, remarcação) aparece na §4, não aqui.

### 6.2 Venda sem reunião nossa (critério 6)

07/09 a 08/11: 7 vendas (50520217, 51828653, 51325509, 50594862, 49975569, 52615871, 52457104), R$ 25.747, sendo 3 sem valor. **Nenhuma tem toque da IA**, nem conversa, nem follow, nem régua. Em outubro são 4 dessas 7. São vendas que o Hub não tocou.

### 6.3 Comparecimento por régua, confirmou × não confirmou (2.6 e 2.7)

Unidade: o **lead**, na primeira reunião com régua de confirmação **entregue** no período e com **horário já passado**. Reunião futura fica fora, porque entraria como "não compareceu, não comprou". Venda é qualquer venda até hoje com `saleDate` maior ou igual ao dia da régua. Concluída é `exact_type = 'Concluido'` naquela reunião.

| período da régua | lado | reuniões | concluídas | vendas | R$ | reunião→venda |
|---|---|---|---|---|---|---|
| outubro (07 a 31/10) | **confirmou** | 96 | 43,8% (42/96) | 29 | 183.782 | **30,2% (29/96)** |
| outubro (07 a 31/10) | não confirmou | 44 | 29,5% (13/44) | 6 | 35.147 | **13,6% (6/44)** |
| 07/10 a 08/11 | **confirmou** | 110 | 46,4% (51/110) | 35 | 217.776 | **31,8% (35/110)** |
| 07/10 a 08/11 | não confirmou | 64 | 31,2% (20/64) | 9 | 53.841 | **14,1% (9/64)** |

Teste exato de Fisher:

- **Venda:** outubro p = 0,038; 07/10 a 08/11 p = 0,011.
- **Concluída:** outubro p = 0,14, não significativo; 07/10 a 08/11 p = 0,056, no limite.

Pelo lado da venda: das 34 vendas de outubro com régua, 28 confirmaram (R$ 176.982) e 6 não (R$ 35.147).

**Este é o elo entre a régua e o dinheiro, e ele é correlação.** Quem confirma é quem já estava mais decidido, e a régua não cria essa decisão necessariamente. Não existe grupo de reuniões sem régua para comparar, porque desde 07/10 ela roda em todas. A tabela mostra que a confirmação **separa** quem vai comprar, o que serve para priorizar a consultora. Ela **não prova** que a régua aumenta a venda.

## 7. Limitações

1. **Régua de confirmação e de no-show só desde 07/10/2026.** Em setembro, "não existia" (não é zero). O lembrete antigo existia desde 26/08 e saía para todo mundo.
2. **O toque é casado pelo telefone tolerante.** Uma pessoa que falou com o agente por outro número aparece sem toque, e dois números do mesmo DDD com os mesmos 8 últimos dígitos seriam a mesma pessoa (não medido aqui).
3. **Valor zero:** 3 vendas sem valor em outubro (2 sem reunião nossa, 1 LP) e 7 de 07/09 a 08/11. Ficam fora da soma e entram na contagem.
4. **Retrato de hoje:** `LeadsSold` lido em 09/11. Venda cancelada depois e valor editado depois não aparecem. A releitura em 16/11 está anotada.
5. **"Participou" não é "causou".** A régua pós-marcação roda em toda reunião, e a conversa do agente roda em todo lead da LP que não marcou e em toda qualificação. Uma venda com toque teria acontecido sem ele, em proporção que este dado não mede.
6. **N pequeno nos degraus de impacto:** o agente gerou 4 vendas em outubro e 9 no período; houve 2 recuperações de no-show. Nenhuma taxa sai deles.
7. **`reagendou` nunca é gravado** em `regua_encerrada_motivo` (0 linhas). A recuperação por remarcação foi medida como "marcação nova depois do corte". Pode haver recuperação que não passou por isso.
8. **Por construção, `fluxo_b` e `marcou_ia` nunca aparecem sozinhos** (§4).
9. **`follow_etapa` é template, não conversa.** Está em "toque de conversa", como manda a decisão 3, e tem linha própria. O degrau "conversa do agente" é o mesmo sem ele.
10. **Comparação por dia:** um toque no mesmo dia da venda, mas depois dela, conta como anterior.

## 8. Números para o conteúdo

Separados pelo que dá para afirmar. Cada frase vem com a ressalva que precisa ir junto.

### Gerou (só a marcação feita pela IA)

1. **"Em outubro, as reuniões marcadas pela nossa IA viraram R$ 24,5 mil em matrículas de pós-graduação, quase 9% do faturamento do mês."**
   Ressalva: são 4 matrículas. A IA marca a reunião e quem fecha é a consultora.

2. **"De setembro ao começo de novembro, foram R$ 48 mil em matrículas que começaram com uma reunião marcada pela IA na conversa."**
   Ressalva: são 9 matrículas de 7 de setembro a 8 de novembro de 2026, e o agente ficou 11 dias pausado nesse intervalo.

### Recuperou (só a recuperação de no-show)

3. **"Duas matrículas, somando R$ 12 mil, vieram de pessoas que tinham faltado à reunião e voltaram depois que a IA retomou o contato."**
   Ressalva: a régua de recuperação começou em 7 de outubro, e o número ainda é pequeno demais para dizer quanto ela recupera em média.

### Participou (o resto)

4. **"Em metade do faturamento de outubro, a pessoa conversou com a nossa IA em algum momento antes de fechar a matrícula."**
   Ressalva: participar não é causar. Essas vendas passaram por uma conversa com a IA, mas a decisão foi construída também pela equipe comercial, e não dá para dizer quantas aconteceriam sem a IA.

5. **"Quem confirmou presença na reunião pela mensagem automática comprou duas vezes mais do que quem não confirmou: 30% contra 14%."**
   Ressalva: isso mostra que a confirmação separa quem já está decidido, não que a mensagem aumenta a venda. Não existe grupo de comparação sem a mensagem.

6. **"Em 21 das 48 vendas de outubro, a IA ou uma mensagem automática falou com a pessoa até uma semana antes de ela marcar a reunião."**
   Ressalva: o número inclui mensagens automáticas por etapa, que não são conversa da IA. É proximidade no tempo, não prova de influência.

### O que NÃO pode ser dito

- "A IA está em 96% das vendas" ou "a IA participou de quase todo o faturamento". O 95,6% vem da confirmação e do lembrete, que rodam em toda reunião, inclusive as marcadas pela equipe.
- "A IA gerou R$ 140 mil", "a IA gerou R$ 177 mil" ou qualquer soma de participação chamada de gerada. Só os R$ 24,5 mil (outubro) e os R$ 48 mil (período) são gerados.
- "A mensagem de confirmação dobra a venda." É correlação.
- "A IA recupera faltosos e vira venda" como regra. São 2 casos.
- "O agente vende mais que a SDR." Vale a ressalva do recon 1.
- "O comercial fez R$ 253 mil" lado a lado com os números deste relatório. A fonte é outra e não foi reproduzida (§1).

## 9. Desvios do plano, com motivo

1. **Cache em outro caminho:** `/tmp/leadssold.json` não existe (era o exemplo do relatório 1). Usei o cache real do recon 1, no scratchpad, com o caminho escrito no topo. Aprovado no checkpoint.
2. **`agendamentos.created_at`, `nat_qualificacao_state.created_at` e `follow_estagio_envios.enviado_em` foram medidos antes de usar.** Os dois últimos são UTC (a 3 h de `messages`), e o script converte.
3. **`follow_up` (o follow 20h do Sprint D, 03 a 17/09)** entrou na família `abertura`. É fala do agente sobre a pergunta pendente e não cabe em nenhum outro flag.
4. **`noshow_recuperado` usa "marcação nova depois do corte"** no lugar do motivo `reagendou`, que nunca é gravado. Aprovado no checkpoint.
5. **Unidade da venda:** o recon 1 contava 97 vendas por `saleDate`; aqui são 96, porque a regra da primeira venda depois da marcação exclui a segunda venda de um lead já vendido antes do período. O valor é idêntico (R$ 545.081).
6. **2.6 e 2.7 viraram uma tabela só (§6.3),** com reunião passada como corte e venda até hoje. Junta o "comparecimento por régua" do plano com a tabela 2.7 pedida no checkpoint.
7. **Escada com dois degraus a mais:** "qualquer toque, sem confirmação e lembrete" (ajuste 1) e "conversa do agente, sem o follow" (para isolar o template, ajuste 3).
8. **Commit:** a atribuição usa o modelo que fez o trabalho (Claude Opus 5.5), sem o link de sessão do plano.

## Observações pra depois (NÃO feitas agora)

- **`regua_encerrada_motivo='reagendou'` nunca é gravado** (0 de 492 reuniões). O `case_metrics.py` conta `REAGENDOU_NOSHOW = {"reagendou"}`, que sempre dá zero. Investigar se é bug no `noshow.py`/`remarcacao.py` ou caminho morto.
- Descobrir a fonte dos R$ 253 mil do comercial e reproduzir o corte.
- Gravar os flags em tabela própria (`venda_toques`) no sync, para a /relatorios mostrar a escada sem rodar script.
- Custo por automação (tokens, templates da Meta) para fechar o ROI por régua.
- Reler `LeadsSold` em 16/11 (D+7) e comparar com o cache.
- Corrigir o relógio de `agendamentos.created_at` em `relatorios.py` (recon 1).
- Teste de efeito da régua de confirmação: uma fração de reuniões sem régua por algumas semanas seria a única forma de medir causa. É decisão de produto.
- Se o case for publicado, autorização por escrito do CENAT.
