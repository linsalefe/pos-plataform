# Agendamento — janela de 3 dias + grade no comercial inteiro — 25/08/2026

Duas mudanças no que o `/slots` oferta, com os números recalculados contra os blocos
recorrentes **reais** das duas consultoras, lidos hoje.

**Estado: ATIVADO em 24/08/2026 23:10 (SP)** com `AGENDAMENTO_JANELA_DIAS=4` — ver §7 (por que 4) e §8 (validação no ar).

---

## 1. O que mudou

| | antes | depois |
|---|---|---|
| janela | horizonte de **14 dias** | **3 dias corridos** — hoje + D+1 + D+2 |
| grade | `10:30–12:00` + `15:45–18:00` (5 horários/dia) | **`09:00–18:30`** (12 horários/dia) |
| antecedência dentro de hoje | 2h | 2h (**inalterada**) |
| dias da semana | seg–sex | seg–sex (**inalterado**) |
| duração | 45 min | 45 min (**inalterado**) |

Horários da grade nova: `09:00 · 09:45 · 10:30 · 11:15 · 12:00 · 12:45 · 13:30 · 14:15 ·
15:00 · 15:45 · 16:30 · 17:15`.

### ⚠️ "último início 17:45" não existe nesta grade — e o motivo é medido

O pedido dizia `09:00–18:30, slots de 45min (último início 17:45)`. Os dois não fecham:
`09:00` mais múltiplos de 45 min **não passa por 17:45**. A cadeia é `… 16:30 · 17:15`, e o
`17:15` termina às 18:00 — sobra um rabo de 30 min que não cabe um slot.

Forçar um início às 17:45 exigiria uma faixa extra `17:45–18:30`. Rodei o número, e ele não
compensa:

| | 17:45 na grade |
|---|---|
| Rodrigues | **colide todo dia** com o bloco recorrente dela `18:20–18:50` |
| Amorim | livre seg–qui; **sexta colide** com `18:00–19:00` |
| resultado | +4 slots/semana, **todos sem retry**, todos só com a Amorim |

Um slot que só uma pessoa pode atender e que morre na sexta é o pior tipo de oferta: se o
`BoxesAdd` dela recusar, o visitante toma 409 sem segunda tentativa. **Ficou de fora.** Se
você quiser o 17:45 mesmo assim, é uma faixa a mais no `consultoras.json` — mas então vale
mais pedir para a Rodrigues mover o bloco das 18:20.

---

## 2. Os blocos reais (lidos hoje, não copiados do doc)

`GET /Boxes`, janela −45/+45 dias, `leadId = 0` com 3 ou mais ocorrências no mesmo
dia+horário. 197 boxes da Amorim (55 reuniões reais), 165 da Rodrigues (92 reuniões reais).

| consultora | blocos recorrentes |
|---|---|
| **Amorim** (`comercial@`) | seg–qui `09:00–10:10` · **ter `10:10–13:30`** · seg–sex `13:30–14:30` · seg–sex `15:00–15:45` · sex `08:00–09:10` · sex `18:00–19:00` |
| **Rodrigues** (`processoseletivo@`) | seg `12:00–13:30` · seg `15:00–16:00` · **seg–sex `18:20–18:50`** |

Idênticos aos documentados em 18/08. Nada se moveu na semana.

---

## 3. Os números que você pediu

### 3.1 Slots/dia da união e cobertura de retry

"Retry" = as **duas** livres no mesmo horário. É o que permite ao `/agendar` tentar a segunda
quando o `BoxesAdd` da primeira recusa.

| dia | união | Amorim | Rodrigues | com retry |
|---|---|---|---|---|
| segunda | 11 | 7 | 8 | 4 (**36%**) |
| **terça** | 12 | **3** | 12 | 3 (**25%**) |
| quarta | 12 | 7 | 12 | 7 (58%) |
| quinta | 12 | 7 | 12 | 7 (58%) |
| sexta | 12 | 8 | 12 | 8 (66%) |
| **semana** | **59** | 32 | 56 | **29 (49%)** |

Comparado com a grade em vigor:

| | grade recortada (hoje) | comercial inteiro (proposta) |
|---|---|---|
| união/semana | 25 | **59** (+136%) |
| capacidade | 47 vagas/sem | **88 vagas/sem** (+87%) |
| cobertura de retry | **88%** | **49%** |

**A troca é essa: mais que o dobro de oferta, metade da cobertura de retry.** A colisão com
bloco deixou de custar erro e passou a custar retry — o horário continua sendo oferecido
(é a união), só não tem segunda tentativa.

### 3.2 Os buracos por colisão

| horário | quem perde | bloco |
|---|---|---|
| `09:00` | Amorim seg–qui | `09:00–10:10` |
| `09:00` | Amorim sex | `08:00–09:10` |
| `09:45` | Amorim seg–qui | `09:00–10:10` (o slot entra às 09:45, o bloco só acaba 10:10) |
| `10:30` `11:15` `12:00` `12:45` | **Amorim, terça** | `10:10–13:30` |
| `12:00` `12:45` | Rodrigues, segunda | `12:00–13:30` |
| `13:30` `14:15` | Amorim, todo dia | `13:30–14:30` |
| `15:00` | Amorim, todo dia | `15:00–15:45` |
| `15:00` `15:45` | Rodrigues, segunda | `15:00–16:00` |

**Um único slot da semana some da união inteira: segunda `15:00`** — é o único horário em que
as duas estão bloqueadas ao mesmo tempo. 59 dos 60 teóricos sobrevivem.

**A terça é o pior dia**: a manhã inteira da Amorim está bloqueada (`10:10–13:30`), então de
`10:30` a `14:15` a oferta é Rodrigues-ou-nada. 25% de retry.

### 3.3 O que a janela de 3 dias alcança — e onde ela seca

Este é o número que você queria ver: janela curta + grade furada em dia ruim.

| cadastro | dias úteis alcançados | slots ofertados | com retry |
|---|---|---|---|
| segunda 09h | seg, ter, qua | 32 | 13 |
| segunda 15h | seg(1), ter, qua | 25 | 11 |
| terça 09h | ter, qua, qui | 33 | 17 |
| quarta 09h | qua, qui, sex | 33 | 21 |
| quinta 09h | qui, sex | 21 | 14 |
| quinta 15h | qui(1), sex | 13 | 9 |
| sexta 09h | sex | 9 | 6 |
| sexta 12h | sex | 5 | 3 |
| **sexta 15h** | sex | **1** (só o `17:15`) | 1 |
| **sexta ≥ 15:15** | **nenhum** | **0 → `fallback:true`** | — |
| sábado (qualquer hora) | seg (D+2) | 11 | 4 |
| domingo (qualquer hora) | seg, ter | 23 | 7 |

O pior caso **não fica pouquíssimo — fica zero**, e é previsível:

> ⚠️ **De sexta 15:15 até a meia-noite de sábado (~9 h por semana), a janela não alcança dia
> útil nenhum.** O `/slots` volta vazio, `fallback:true`, e a LP cai no "deixe seu contato".

Com o horizonte de 14 dias isso nunca acontecia. É o degrade correto e já existia por outras
causas (feriado, agenda lotada, todas fora de rotação) — o que muda é que agora tem hora
marcada, toda semana.

**`AGENDAMENTO_JANELA_DIAS=4` fecha esse buraco**: a sexta passa a enxergar a segunda
(D+3), sábado enxerga seg+ter, e o zero desaparece. Custo: ofertar um dia mais longe. É uma
linha do `.env` e um restart, sem tocar em código — **decisão sua, e é o único ponto em que
eu recomendaria diferente do pedido.**

Sem isso, a grade nova ainda melhora todos os dias ruins em relação à de hoje: sábado
5 → 11, quinta 15h 6 → 13, sexta 12h 3 → 5.

### 3.4 Feriado continua sem tratamento

Não existe calendário de feriados no módulo — feriado dentro da janela é ofertado e o box é
criado. Já era assim com 14 dias; com 3 o efeito é maior, porque um feriado pode comer um
terço da oferta. Não mexi: é sprint própria, e não estava no pedido.

---

## 4. O que foi implementado

### `backend/app/agendamento/grade.py`

- `horizonte_dias` **morreu**. No lugar, `janela_dias`: **dias corridos de calendário, hoje
  incluído** (`range(janela_dias)`, sem o `+1` que o horizonte precisava).
- `AGENDAMENTO_JANELA_DIAS`, padrão `3`. Precedência: `janela_dias` explícito na config **>**
  env **>** `JANELA_DIAS_PADRAO`. O env mexe no padrão em vez de atropelar — é o que deixa
  uma linha do `.env` valer para o produto inteiro **e** um E2E alcançar data distante sem
  mexer no ambiente do servidor.
- Env inválido (`"zero"`, `0`, `-3`, vazio) **cai no padrão com aviso**, igual a toda config
  deste módulo. Uma janela de 0 apagaria o `/slots` inteiro em silêncio.
- `horizonte_dias` deixado numa config antiga é **ignorado com aviso no boot** — quem o
  escreveu acredita estar ofertando 14 dias e veria 3, sem nada no log.
- `GRADE_PADRAO` (o fallback de consultora única) também foi para `09:00–18:30`.
- Cabeçalho reescrito: o arquivo argumentava que a grade **precisa caber nas lacunas**. Isso
  inverteu — agora ela oferece o comercial inteiro e quem recorta é a subtração ao vivo.

### `backend/consultoras.json`

`09:00–18:30`, seg–sex, idêntico para as duas. Grade por dia da semana continua
desnecessária: o `/slots` subtrai os blocos reais de cada uma ao vivo.

### `backend/app/qualificacao_fluxo.py` — defeito que esta mudança criaria

O agente monta o contexto do LLM com `3 dias × 6 horários`. Os 6 eram um `[:6]` — **os seis
primeiros do dia**. Com 5 horários/dia isso não cortava nada; com 12, os seis primeiros são
`09:00 … 12:45`, e **o agente nunca mais ofereceria uma tarde**. Sem erro, sem log: quem só
pode à tarde ouviria "não tenho horário" com a tarde inteira livre.

Trocado por `_espalhados()`, que pega 6 pontos distribuídos com os extremos garantidos:
`09:00 · 10:30 · 12:00 · 14:15 · 15:45 · 17:15`. Espalhar em vez de aumentar o limite porque
a lista vai inteira para o prompt, e uma parede de 12 horários empurra o modelo a despejar
tudo no WhatsApp.

O corte de 3 dias do agente agora coincide com a janela — ele mostra a janela inteira.

### Testes

`test_agendamento.py` — **33/33**, dois casos novos:

- **32.** janela com relógio congelado: segunda vê seg/ter/qua e **não** vê D+3; sexta 09h vê
  só a sexta; sexta 16h vê **nada**; sábado vê só a segunda; domingo vê seg+ter; antecedência
  de 2h continua valendo dentro de hoje; env ruim cai no padrão; config explícita vence o
  env; `horizonte_dias` é ignorado.
- **33.** janela seca → `/slots` responde **200 com `fallback:true`**, e **sem falar com a
  Exact** (sem slot candidato não há período para consultar — seria rate limit torrado toda
  sexta).

O caso 1 mudou de sentido e está comentado no código: ele **exigia** que a grade não
colidisse com bloco nenhum. Agora ele afirma o contrário — que `09:00`, `09:45`, `13:30`,
`14:15` e `15:00` **colidem de propósito** — e quem garante que a colisão vira remoção antes
de virar oferta é o caso 4.

`test_qualificacao.py` — 5 checagens novas na amostra de horários (a de cima).

**A suíte não pode depender do dia em que roda.** Com janela de 3 dias, `slots_candidatos()`
volta vazia numa sexta à tarde, e ~20 casos que pedem "o primeiro slot da grade" para
exercitar o **fluxo** quebrariam por um motivo que nenhum deles testa. O fluxo passou a rodar
com `AGENDAMENTO_JANELA_DIAS=7`, e a **regra** da janela é testada à parte com relógio
congelado — o único jeito de afirmar "sábado enxerga só a segunda" sem esperar dar sábado.

Os quatro E2E (`_e2e`, `_leadid`, `_consultoras`, `_funil`) migraram de `horizonte_dias` para
`janela_dias` (`+1`, porque hoje agora conta como dia 1) e passaram a declará-lo
**explicitamente**, para o `AGENDAMENTO_JANELA_DIAS=3` do servidor não encurtar a janela deles
e sumir com o alvo distante.

### Regressão

15 suítes offline, **todas verdes**: `test_agendamento` (33/33), `test_agendamento_cors`
(7/7), `test_qualificacao`, `test_parse_datetime`, `test_primeiro_nome`, `test_nat_flow`
(13/13), `test_nat_guard` (9/9), `test_nat_duplicata` (5/5), `test_nat_reagendado` (5/5),
`test_nat_recuperacao`, `test_nat_sprint3`, `test_nat_config_api`,
`test_nat_caminho_completo`, `test_welcome_guardrail` (17/17),
`test_observabilidade_envio`. Nada real tocado — nenhum box, nenhum lead, nenhum WhatsApp.

### Fallback do front — conferido, continua ok

`docs/obrigado-snippet.html:205` faz `if (d.fallback) { dias = {}; }` → `pintarDias()` liga
`semGrade` → o `enviar()` roteia para `/api/agendamento/lead` em vez de `/agendar`. O
comportamento é o de sempre; o que muda é a frequência com que ele vai acontecer (§3.3). O
caso 33 trava o lado do backend.

---

## 5. Ativação

```bash
sudo systemctl restart cenat-backend.service
```

O que conferir: `/health` **200**, `GET /slots` com `fallback:false`, no máximo
**`janela_dias` dias** em `dias`, e todos os horários dentro de `09:00–17:15`.

Feito em 24/08 23:10 — resultado no §8.

**O botão fica no `.env`**, em `AGENDAMENTO_JANELA_DIAS`: trocar 3↔4↔5 é uma linha mais
restart, sem tocar em código nem no `consultoras.json`.

---

## 6. Decisão sua

1. **Janela 3 ou 4 dias?** Medido contra a chegada real dos leads no §7: com 3, **5,3% dos
   leads (~9/semana) veem oferta ZERO**, e o sábado — maior dia da LP — enxerga só a segunda,
   o pior dia de retry. Com 4 o zero some, e o 4º dia **não custa nada** para quarta e quinta
   (o D+3 delas é fim de semana). Recomendo **4**, com número.
2. **Retry em 49% incomoda?** É o preço medido de ofertar o comercial inteiro. Se
   `Boxes are occupied` começar a aparecer no log, a saída não é encolher a grade de volta —
   é rever com as consultoras os blocos que mais custam. A terça da Amorim (`10:10–13:30`)
   sozinha responde por boa parte do buraco.
3. **17:45 mesmo assim?** §1. Sai zero-retry e morre na sexta.

---

## 7. Adendo — 3 vs 4 dias, medido contra a chegada real dos leads

A pergunta "qual o melhor" não se responde pela grade, e sim por **quando o lead chega**.
Medido em `exact_leads.register_date` (UTC de verdade, FINDINGS §3 — convertido para SP),
120 dias, **2 933 leads**. O recorte `Landing Page` tem só 76 leads / 8 dias (o source nasceu
em 17/08) — pequeno demais para decidir sozinho, mas **concorda** com a base inteira.

### 7.1 Chegada por dia da semana

| | seg | ter | qua | qui | sex | **sáb** | **dom** |
|---|---|---|---|---|---|---|---|
| base inteira (2 933) | 13,9% | 19,0% | 16,5% | 14,7% | 12,6% | **11,5%** | **11,9%** |
| Landing Page (76) | 7,9% | 14,5% | 17,1% | 10,5% | 14,5% | **22,4%** | 13,2% |

**23,4% da base chega no fim de semana** — e na LP o sábado é o **maior dia isolado** (22,4%).
Faz sentido: é tráfego pago de página, não horário comercial.

### 7.2 O que cada janela entrega, ponderado pela chegada real

| janela | leads com oferta **ZERO** | média de slots ofertados | média com retry |
|---|---|---|---|
| **3 dias** | **155 (5,3%)** | 20,6 | 10,7 |
| **4 dias** | **0 (0,0%)** | 28,8 | 14,8 |
| 5 dias | 0 (0,0%) | 36,4 | 18,5 |

**5,3% dos leads — ~9 por semana — abririam a LP e não veriam horário nenhum** com janela de 3.

### 7.3 O argumento decisivo: o 4º dia é de graça na metade da semana

| chegada | leads | slots 3 → 4 | retry 3 → 4 |
|---|---|---|---|
| segunda | 13,9% | 27,5 → **39,5** | 11,4 → 18,4 |
| terça | 19,0% | 27,9 → **39,9** | 15,6 → 23,6 |
| **quarta** | 16,5% | 27,6 → **27,6** | 17,3 → 17,3 |
| **quinta** | 14,7% | 16,3 → **16,3** | 10,7 → 10,7 |
| **sexta** | 12,6% | **4,5 → 15,5** | 3,1 → 7,1 · **155 secos com 3** |
| **sábado** | 11,5% | **11,0 → 23,0** | 4,0 → 7,0 |
| domingo | 11,9% | 23,0 → **35,0** | 7,0 → 14,0 |

Repare em **quarta e quinta: não muda nada.** O 4º dia delas é sábado e domingo, que não têm
grade. Ou seja, **o 4º dia não "oferta mais longe" para 31% dos leads — ele simplesmente não
existe.** O custo só é pago exatamente nos dias que estão passando fome.

E a propriedade que fecha o caso: com janela de 4, **nenhuma chegada em dia útil é ofertada
além da sexta da mesma semana** (seg→qui, ter→sex, qua e qui param no fim de semana). O único
dia útil cuja oferta atravessa o fim de semana é a **sexta** — que é precisamente o resgate.

### 7.4 O sábado é o pior atendido, e é o maior dia da LP

Com janela de 3, quem chega no sábado enxerga **só a segunda**: 11 horários e apenas **4 com
retry** — a segunda é o pior dia de cobertura da semana (36%), por causa dos blocos
`12:00–13:30` e `15:00–16:00` da Rodrigues. Com 4, o sábado passa a enxergar segunda **e**
terça: 23 horários, 7 com retry.

Juntando: na LP, **22,4% dos leads (o maior dia) recebem hoje a oferta mais magra e de pior
cobertura da semana.** Isso, e não o buraco da sexta, é o argumento mais forte para o 4.

### 7.5 Por que não 5

5 dias não resgata ninguém a mais (o zero já morreu no 4) e começa a ofertar reunião para a
semana seguinte em chegada de dia útil — que é justamente o que matar o horizonte de 14 dias
queria evitar. **4 é a menor janela sem zona morta**, e é esse o critério.

### Recomendação

`AGENDAMENTO_JANELA_DIAS=4`. Não é "um dia a mais": é o menor valor que elimina a oferta zero,
e ele é **gratuito para 31% dos leads** (quarta e quinta não mudam em nada).

---

## 8. ATIVADO — 24/08/2026 23:10 (SP)

`AGENDAMENTO_JANELA_DIAS=4` no `.env`, `sudo systemctl restart cenat-backend.service`.

| verificação | resultado |
|---|---|
| serviço | `active` · `Application startup complete` |
| `/health` | **200** |
| `janela_dias` carregado nas duas consultoras | **4** |
| `/slots` | **200**, `fallback:false`, `duracao_min:45` |
| dias ofertados | **3** — 25, 26 e 27/08 (a segunda 24 já tinha esgotado às 23:10; `hoje + D+3` = 27) |
| grade nova no ar | `09:00` e `17:15` presentes no dia 27 ✅ |
| horários fora de `09:00–17:15` | nenhum ✅ |

### O que a primeira leitura ao vivo mostrou

| dia | teórico | ofertado | com retry |
|---|---|---|---|
| ter 25/08 | 12 | 5 | **0 (0%)** |
| qua 26/08 | 12 | 5 | **0 (0%)** |
| qui 27/08 | 12 | 11 | 5 (45%) |
| **total** | 36 | **21** | **5 (23%)** |

**A ocupação real removeu 41% dos horários teóricos**, e a cobertura de retry ao vivo ficou em
**23%** — não nos 49% do §3.1. Não é erro de conta: os 49% são **capacidade** (agenda vazia), e
os dois primeiros dias da janela já estão vendidos.

Isso é estrutural da janela curta e vale registrar: **dia próximo já está tomado**. Com o
horizonte de 14 dias havia dia distante e vazio para inflar a média de retry; com 4 dias, não
há. Consequência prática: **um 409 num slot de D+1 ou D+2 tende a ser terminal** — não existe
segunda consultora para tentar. Se isso aparecer no log com frequência, o caminho é rever os
blocos recorrentes com as consultoras (a terça `10:10–13:30` da Amorim é o maior deles), não
encurtar a grade de volta.
