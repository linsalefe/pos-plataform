# RECON — Follows e conversas: humano × IA

**Janela:** 24/08/2026 00:00 → 01/09/2026 14:54 (SP). Oito dias e meio, seis dias úteis,
um sábado trabalhado (29/08) e um domingo morto (30/08).

**Natureza:** somente leitura. Nenhum envio, nenhuma escrita, nenhuma migração, nenhum DDL
permanente — o trabalho todo rodou em tabelas `TEMP` que morrem ao desconectar. As consultas
estão no Anexo C.

---

## 0. O veredito curto

**Nesta casa "follow" quer dizer disparo em massa.** Dos 378 follows da janela, **326 (86%)
saíram em 30 rajadas de campanha** — lotes de 4 a 95 pessoas disparados em menos de dois
minutos. **39 foram individuais.** E **zero** foram texto digitado: em 8 dias e meio nenhum
SDR escreveu à mão uma única mensagem para um lead que tinha ficado calado. O follow humano
é, na prática, uma lista sendo varrida.

**Ele funciona três vezes menos que a abertura, e piora a cada toque.** Abertura da IA:
**53,3%** de resposta em 24h (40/75). Abertura humana: **38,3%** (18/47). Follow humano:
**11,2%** (41/365) — e dentro do follow a curva desce **17,4% → 11,7% → 7,8% → 6,8% → 0%**
do 1º ao 5º toque. São populações diferentes e isso está dito no §2.3, mas a decadência
interna do follow não depende de comparação nenhuma: é a mesma gente, medida contra ela mesma.

**O maior buraco não é o follow ruim — é o follow que não existe.** A IA abriu 118 conversas.
Em **39 delas o lead calou e ninguém nunca mais mandou nada**. Dessas 39, **18 estavam paradas
numa etapa ativa da qualificação** — 5 esperando o ano de conclusão, 3 a formação, 3 a
motivação e **2 escolhendo o horário da reunião**. Duas pessoas foram deixadas no ar no
momento em que estavam apontando para um slot na agenda.

**E o custo do follow atual já está aparecendo na fatura.** 8 dos 9 leads que disseram "não
tenho interesse" continuaram recebendo mensagens — um deles cinco vezes depois do não, até
responder em caixa alta. 21 pessoas receberam **5 ou mais templates** na janela e **nunca
responderam uma vez**. A Meta recusou 4 envios com `131049 — "not delivered to maintain
healthy ecosystem"`, que é o código que ela usa quando decide proteger o destinatário de nós.

**Um defeito de parâmetro, achado de passagem, vale sozinho um conserto de 10 minutos:**
**43 das 82** mensagens do template `tentativa_contato` (52%) foram assinadas com o **nome do
curso no lugar do nome da pessoa**. O lead leu, literalmente, *"Ola Rosana, é o
PsicologiaEscolar do CENAT"*.

---

## 1. O que é "follow" nesta base

### 1.1 A definição usada, e por que ela

> **Follow** = mensagem *outbound* para um lead que ficou **≥ 20 h** sem responder ao
> *outbound* anterior daquela thread, sem nenhuma fala do lead no meio.

O N=20 h é escolha, e é defensável por dois motivos. O primeiro é operacional: fica **abaixo
da janela de 24 h** da Meta, então um follow disparado nesse ponto ainda pode sair como
mensagem livre se a conversa estiver aberta — acima de 24 h só sai template pago. O segundo é
empírico e está no §2.4: **é a faixa que mais responde** (13,7% entre 20 h e 24 h, contra 7,9%
entre 48 h e 72 h). Se o número tivesse que ser outro, seria menor, não maior.

Três coisas que **não** são follow e ficaram fora da conta: a **abertura** (1º toque da
thread), a **resposta dentro de conversa viva** (o lead falou no meio) e o **reforço curto**
(2ª mensagem em menos de 20 h, normalmente uma quebra de bloco).

| Ator | Abertura | Resposta em conversa | Reforço < 20 h | **Follow ≥ 20 h** |
|---|---:|---:|---:|---:|
| Humano — template | 45 | 73 | 34 | **365** |
| Humano — texto digitado | 2 | 35 | 58 | **0** |
| IA (NAT) | 75 | 204 | 72 | **13** |

**A linha do meio é o achado.** O humano digitou 95 mensagens na janela e **nenhuma delas foi
um follow**. Todo texto à mão foi resposta a quem já estava falando (35) ou complemento
imediato do que ele mesmo acabara de mandar (58). Quando o lead some, o humano não escreve —
ele adiciona o lead a um lote.

*(Os 13 "follows" da IA são artefato da definição e estão explicados no §1.5. A NAT não tem
cadência de follow — Sprint D adiado.)*

### 1.2 Campanha × individual: como foram separados

`messages` não guarda o nome do template nem quem apertou o botão (§1.4). A separação foi
feita pelo **relógio**: mensagens da mesma família encadeadas por intervalos ≤ 120 s formam
uma ilha; ilha com **≥ 4 destinatários distintos** é campanha, o resto é individual. A
distribuição não deixa dúvida sobre onde cortar — as ilhas ou têm 1–3 pessoas (52 ilhas) ou
saltam para 9, 10, 14, 20, 24, 25, 30, 42, 95.

**30 campanhas na janela**, sempre nos mesmos três horários — ~10h50, ~15h20, ~16h40:

| Dia | Rajadas | Maior lote |
|---|---:|---|
| 24/08 (seg) | 6 | 10 (`f3_guia_ementa`) |
| 25/08 (ter) | 6 | **42** (`tentativa_contato`, 15h18–15h19) |
| 26/08 (qua) | 6 | 30 (`f5_ligacao`, 14h46–14h47) |
| 27/08 (qui) | 2 | 15 (`tentativa_contato`) |
| 28/08 (sex) | 4 | 25 (`f5_ligacao`) |
| 29/08 (**sáb**) | 1 | **95** (`processo_seletivo_fase`, 10h52–11h00) |
| 31/08 (seg) | 5 | 24 (`f3_guia_ementa`) |

### 1.3 Volume por ator

| Ator | Toques | Leads distintos |
|---|---:|---:|
| Humano — template **BULK** | 443 | 136 |
| IA (NAT) | 364 | 118 |
| Humano — template **individual** | 74 | 67 |
| Humano — **texto digitado** | 95 | 31 |
| **Lead (inbound)** | **504** | **167** |

228 threads receberam algum outbound. **52 delas (23%) só existiram como linha de uma
campanha** — nunca receberam uma mensagem individual, nem da IA nem de gente.

As famílias de template, todas identificadas por texto (não há nome de template gravado):

| Família | Msgs | Leads | Bulk | Indiv. |
|---|---:|---:|---:|---:|
| `processo_seletivo_fase` | 95 | 95 | 95 | 0 |
| `tentativa_contato` | 82 | 76 | 76 | 6 |
| `f5_ligacao` | 75 | 58 | 71 | 4 |
| `f3_guia_ementa` | 54 | 54 | 39 | 15 |
| `f4_audio_confirma` | 48 | 39 | 48 | 0 |
| `ficha_aplicacao` | 36 | 28 | 36 | 0 |
| `consultora_tentou` | 25 | 24 | 14 | 11 |
| `boasvindas_inscricao` | 22 | 21 | 6 | 16 |
| `ainda_ha_interesse` | 22 | 19 | 19 | 3 |
| `sem_retorno_validade` | 20 | 18 | 20 | 0 |
| `reagendamento` | 20 | 18 | 19 | 1 |
| demais (7 famílias) | 18 | 18 | 0 | 18 |

### 1.4 ⚠️ Por SDR nomeado: **a base não permite responder**

O pedido era medir follow **por SDR**. Não dá, e a razão é estrutural, não uma lacuna de
consulta:

```
backend/app/models.py:50   class Message      →  não há sent_by, não há user_id
backend/app/routes.py:249  send_text          →  recebe current_user … e não o grava
backend/app/routes.py:291  send_template      →  recebe current_user … e não o grava
backend/app/routes.py:338  send_media         →  idem
backend/app/exact_routes.py:485  bulk         →  idem
```

As três rotas de envio **sabem** quem está logado — elas usam `current_user` para calar o
agente (`_silenciar_agente_apos_envio_manual`, `routes.py:205`) — e jogam essa informação
fora. Não existe nem o nome do template: `content` guarda o **texto renderizado**, e é por
isso que todas as famílias deste relatório tiveram que ser reconstruídas por `LIKE` sobre o
corpo da mensagem.

**O que sobrou de atribuição, e o quanto vale cada pedaço:**

| Fonte | O que prova | Cobertura |
|---|---|---|
| `nat_qualificacao_state.dados_extras->'assumido_por'` | quem digitou num contato que o **agente estava conduzindo** | **45 envios, 45 do Thobias, 0 de qualquer outro** |
| `contacts.assigned_to` | dono do lead **na Exact** — não quem mandou | Thobias 137 threads, Valéria 19, Victória 7, Vi Amorim 4, Isa 1, sem dono 4 |
| assinatura no corpo do template | parâmetro `{{n}}`, e ele **está errado em 52% dos casos** (§4.3) | Thobias 135 msgs, Victória 25, sem nome 357 |
| `nat_contact_attempts.registrado_por` | tentativas de ligação registradas à mão | **0 registros na janela** |

A leitura honesta das três primeiras linhas juntas: **o follow por WhatsApp desta janela é,
quase inteiramente, operação do Thobias (id 5)**, com a Victória (id 6, `comercialcenat@gmail.com`
— era essa a dúvida do briefing) aparecendo só como nome citado dentro do template
`consultora_tentou`, que é disparado por outra pessoa. Mas isso é inferência a partir de três
sinais tortos, e **não** é o mesmo que medir. Latência por SDR, duplicata por SDR e conversão
por SDR ficam impossíveis até que exista uma coluna.

> **Conserto mínimo:** `ALTER TABLE messages ADD COLUMN sent_by INTEGER REFERENCES users(id)`
> + `ADD COLUMN template_name VARCHAR(512)`, preenchidos nos cinco pontos listados acima.
> Aditivo, sem reescrita de tabela, sem backfill possível (o passado não volta). Todo
> relatório de produtividade individual depende disso e nenhum é possível antes.

### 1.5 Os 13 "follows" da IA não são follows

A NAT não tem cadência de follow. Os 13 casos que a definição do §1.1 capturou são:

* **6 × `nat_lembrete_reuniao`** — lembrete de reunião no dia. Segundo toque legítimo, não follow.
* **7 × `nat_abertura_*`** — **abertura** da NAT caindo numa thread que **um humano já tinha
  tocado** dias ou meses antes. Do ponto de vista da NAT é o primeiro contato; do ponto de
  vista do lead é mais uma mensagem do CENAT. Um deles com 3 713 h (155 dias) de "silêncio"
  anterior.

O caso `3498684095` (Marcio) mostra os dois lados disso ao mesmo tempo — e está no §4.1,
porque é o melhor resultado da janela inteira.

---

## 2. Eficácia

### 2.1 Taxa de resposta em 24 h, por família

| Família | Canal | Follows | Respondidos | Taxa |
|---|---|---:|---:|---:|
| `ainda_ha_interesse` | bulk | 16 | 5 | **31,3%** |
| `f4_audio_confirma` | bulk | 42 | 7 | 16,7% |
| `sem_retorno_validade` | bulk | 19 | 3 | 15,8% |
| `tentativa_contato` | bulk | 28 | 4 | 14,3% |
| `f5_ligacao` | bulk | 49 | 6 | 12,2% |
| `ficha_aplicacao` | bulk | 28 | 2 | 7,1% |
| `reagendamento` | bulk | 14 | 1 | 7,1% |
| `processo_seletivo_fase` | bulk | 81 | 5 | **6,2%** |
| `f3_guia_ementa` | bulk | 34 | 0 | **0,0%** |
| `f3_guia_ementa` | individual | 13 | 3 | 23,1% |
| `boasvindas_inscricao` | individual | 11 | 0 | **0,0%** |
| **Total humano** | — | **365** | **41** | **11,2%** |
| Individual (subtotal) | — | 39 | 6 | 15,4% |
| Bulk (subtotal) | — | 326 | 35 | 10,7% |

**`ainda_ha_interesse` é o melhor template da casa e o motivo é o ultimato.** O corpo diz
*"⚠️ Importante: Na ausência de retorno considerarei que não há mais interesse e encerrarei
sua aplicação"*. Ele triplica a taxa média — e vale registrar que boa parte do que ele colhe
é **"não"** (§2.2), que também é informação e libera a lista.

**`f3_guia_ementa` mandado em lote: 34 envios, zero respostas.** O mesmo template mandado
individualmente responde 23,1%. É o contraste mais limpo da tabela entre o canal e o texto:
o texto não é o problema.

**`boasvindas_inscricao` como follow: 11 envios, zero respostas, silêncio mediano de 317 h.**
Mandar "Obrigada por se inscrever" para quem se inscreveu há treze dias e nunca respondeu não
é follow, é ruído.

### 2.2 ⚠️ A taxa de resposta está superestimada — em dois lugares

**(a) Um "sim" contado duas vezes.** Os 41 follows creditados com resposta correspondem a
apenas **36 mensagens distintas** do lead. Quando dois follows caem com menos de 24 h de
diferença, a mesma resposta credita os dois. Exemplo literal:

```
1179926715   25/08 15:53  bulk  sem_retorno_validade   →  resposta 23,1 h depois
1179926715   26/08 14:59  bulk  ainda_ha_interesse     →  "resposta" 0,7 min depois
                                                          ↑ é a MESMA mensagem
             26/08 15:00  lead  "Não tenho mais interesse"
```

**(b) Metade do que responde está dizendo não.** Lendo as 41 respostas uma a uma:

| Natureza | N | Exemplos verbatim |
|---|---:|---|
| **Recusa explícita** | **14** | *"Não tenho mais interesse"* · *"não desejo iniciar a pós graduação no momento"* · *"Infelizmente a equipe considera um valor muito alto"* · *"No momento não tenho condições financeiras"* |
| Engajamento real | 13 | *"amanhã a partir das 16h eu estou livre, se puderem"* · *"Você consegue me ligar para explicar como funciona"* · *"Consigo ter acesso as ementas, carga horária e modalidade?"* |
| Cortesia sem conteúdo | 12 | *"Bom dia"* · *"Oi"* · *"Obrigada"* |
| **Robô** | **2** | *"📌 Mensagem automática Consultório Martha Nery"* · *"estou em recesso em razão de um luto familiar"* |

**Taxa de resposta *útil* do follow humano: 13 em 365 = 3,6%.** Esse é o número que deveria
entrar em qualquer conta de custo por lead reengajado.

### 2.3 Abertura × follow — e a ressalva que anula a comparação direta

| Medida | N | Resp. 24 h | Taxa |
|---|---:|---:|---:|
| **Abertura da IA** (1º toque, business-initiated) | 75 | 40 | **53,3%** |
| **Abertura humana** (1º toque) | 47 | 18 | 38,3% |
| **Follow humano** (2º+ toque, ≥20 h) | 365 | 41 | 11,2% |

> **Populações diferentes, e a diferença é grande.** A abertura pega o lead **quente** — ele
> acabou de preencher a landing page e está esperando contato. O follow pega, por construção,
> **exatamente quem já não respondeu uma vez**. Nenhum time do mundo mostraria o mesmo número
> nas duas colunas. **A comparação 53,3% × 11,2% não prova que a IA é 5× melhor** e este
> relatório não afirma isso.
>
> O que **é** comparável, porque é a mesma população medida contra ela mesma, é a decadência
> interna do follow:

| Ordem do follow na thread | N | Resp. | Taxa |
|---|---:|---:|---:|
| 1º | 144 | 25 | **17,4%** |
| 2º | 103 | 12 | 11,7% |
| 3º | 77 | 6 | 7,8% |
| 4º | 44 | 3 | 6,8% |
| 5º | 10 | 0 | **0,0%** |

Profundidade da régua: 41 leads receberam 1 follow, 26 receberam 2, 33 receberam 3, 34
receberam 4 e 10 receberam 5.

### 2.4 Quando mandar — a evidência para o N do Sprint D

| Silêncio até o follow | N | Resp. | Taxa |
|---|---:|---:|---:|
| **20–24 h** | 124 | 17 | **13,7%** |
| 24–48 h | 58 | 6 | 10,3% |
| 48–72 h | 127 | 10 | 7,9% |
| 3–7 dias | 16 | 1 | 6,3% |
| > 7 dias | 40 | 7 | 17,5% ⚠️ |

A curva desce monotonicamente até 7 dias. A subida no último balde é **outra população** —
são reativações de base antiga (silêncio mediano de 3 807 h no canal individual), onde
qualquer contato é novidade. Não use esse 17,5% para justificar esperar.

**Latência real hoje:** o follow em massa sai com **45,7 h** de silêncio (mediana), o
individual com **54,0 h**. Ou seja, a operação está mandando o follow **no balde de 7,9%**
quando poderia estar mandando no de 13,7%.

### 2.5 Conversão pós-follow — e uma armadilha do CRM

Cruzando `exact_stage_events` (UTC → SP) com o instante de cada follow, janela de 72 h:

| Ator / canal | Leads seguidos | Entraram em Agendados/Reagendamento |
|---|---:|---:|
| Humano — bulk | 122 | **6** (4,9%) |
| Humano — individual | 36 | **4** (11,1%) |
| IA | 13 | 2 (15,4%) — *N pequeno demais* |

> **A primeira medição deu 18/122 e estava errada.** O funil 18535 tem **duas etapas com
> praticamente o mesmo nome** — `Reagendamento` e `Reagendamento.` (com ponto final). Na
> janela houve **20 entradas em `Reagendamento.` contra 1 em `Reagendamento`**, e 11 delas
> foram transições `Reagendamento → Reagendamento.` ocorridas ~1,5 h depois de uma campanha —
> arrumação de cadastro, não conversão. A tabela acima já exclui toda transição cujo
> `stage_de` já era Agendados ou Reagendamento.
>
> **Recomendação:** consolidar as duas etapas na Exact. Enquanto existirem, **todo** relatório
> de funil desta casa vai contar reunião a mais.

---

## 3. A régua da Exact × o que aconteceu no WhatsApp

104 leads do funil 18535 estavam numa etapa `Follow N` e tiveram thread na janela. "Toques de
iniciativa" = abertura + follows (exclui resposta dentro de conversa).

| Etapa na Exact | Leads | Mediana de toques | Mín | Máx | **Abaixo da etapa** | Muito acima (>N+2) |
|---|---:|---:|---:|---:|---:|---:|
| Follow 1 | 6 | 1,0 | 1 | 3 | 0 | 0 |
| Follow 2 | 17 | 2,0 | 1 | 17 | **7** | 1 |
| Follow 3 | 35 | 4,0 | 1 | 30 | **6** | **13** |
| Follow 4 | 3 | 6,0 | 5 | 7 | 0 | 1 |
| Follows 5 | 24 | 5,0 | 3 | 8 | **7** | 1 |
| Follows 6 | 14 | 5,0 | 4 | 19 | **10** | 2 |
| Follows 8 | 5 | 5,0 | 2 | 6 | **5** | 0 |

**A etapa mente nas duas direções, e a mediana esconde isso.** Na altura de `Follows 6` e
`Follows 8`, **15 de 19 leads** receberam menos toques do que o número da etapa promete. No
outro extremo, `Follow 3` guarda 13 pessoas com mais de 5 toques — uma delas com **30**.

Casos nominais:

| Etapa | Lead | Toques de iniciativa | Respostas do lead |
|---|---|---:|---:|
| **Follows 8** | Osmari Virginia M Andrade | **2** | 4 |
| Follow 3 | Eliana Vieira | 1 | **0** |
| Follow 2 | Cristiane Kolakowski Busch | 1 | 0 |
| Follow 3 | **Natielle Aline Mertins** | **30** | 1 |
| Follows 6 | Isabel Cristina Vitor de Abreu | 19 | 2 |
| Follow 2 | Robson Félix Miranda Farias | 17 | 4 |

> **Ressalva de método, e ela é grande.** A régua Follow 1–9 da Exact conta **tentativa de
> contato**, não mensagem de WhatsApp — o próprio corpo do `f5_ligacao` diz *"essa **ligação**
> é a primeira etapa do seu processo seletivo"*. Ligação não deixa rastro nesta base
> (`nat_contact_attempts` teve **0 registros na janela**). Então "abaixo da etapa" pode ser
> ligação não registrada, e não necessariamente trabalho não feito.
>
> O que **não** tem essa saída é o outro lado: **Natielle está em Follow 3 depois de 30
> toques.** Nenhuma quantidade de ligação não registrada explica um lead avançar 3 casas
> tendo recebido 30 mensagens. E os dois leads com **0 mensagens** em Follow 2 e Follow 3
> também não: eles avançaram na régua sem que nada tenha saído por este canal.

---

## 4. Leitura qualitativa

### 4.1 Os melhores

**① `3498684095` — Marcio, 31/08. O melhor resultado da janela, e não foi o follow que o produziu.**

```
31/08 10:24  humano  tentativa_contato  "Ola Marcio, é o Thobias do CENAT ✨ Tentei realizar
                                         uma nova tentativa de contato…"      ← 158 dias de silêncio
31/08 10:41  IA      abertura           "Vi que você aplicou para a nossa Pós-Graduação em
                                         Enfermagem em Saúde Mental…"          ← 17 min depois
31/08 12:58  LEAD                       "Boa tarde! Conclui em 2004"           ← responde à IA
31/08 12:58  IA                         "Perfeito, Marcio — concluído em 2004. Me conta como
                                         e onde você atua profissionalmente hoje?"
31/08 13:02  LEAD                       "Saúde da Família"
31/08 13:02  LEAD                       "Meu interesse em atuar na área"
31/08 13:02  IA                         [oferece 4 horários]
31/08 13:03  LEAD                       "03/09 14:15"
31/08 13:03  IA                         "vou agendar o horário que você escolheu ✅"
31/08 13:10  LEAD                       "Obrigado"
```

Qualificação completa e reunião marcada em **5 minutos**, 2h34 depois do toque. **Mas leia o
crédito com cuidado:** o follow humano das 10h24 reabriu a porta; quem conduziu foi a IA
das 10h41; e a resposta do lead ("Conclui em 2004") responde à **pergunta da IA**, não ao
template. Minha própria métrica do §2.5 creditou essa conversão ao `tentativa_contato`
individual. **Quando os dois atores tocam a mesma thread em 17 minutos, atribuição de
conversão é chute.**

**② `1141092790` — Yasmin. O follow que funcionou e a campanha que atropelou.**

```
27/08 17:47  humano  tentativa_contato (bulk, lote de 15)
27/08 19:23  LEAD    "boa noite! amanhã a partir das 16h eu estou livre, se puderem"
28/08 10:19  humano  "Perfeito, Yasmin! 😊"
28/08 10:19  humano  "Combinado! Vou deixar agendado para hoje, às 16h30."
28/08 10:19  humano  "A ligação será feita via WhatsApp pelo número (67) 99915-1808. 🌻"
28/08 16:36  humano  f5_ligacao (bulk, lote de 16) — "Fiz uma nova tentativa de contato,
                      mas ainda sem sucesso" ────────────────────── 6 min depois do horário
                                                                     que ELA escolheu
```

O trecho do meio é atendimento humano de primeira: rápido, nominal, com o número da ligação.
Seis horas depois a lista varre por cima e manda um template genérico de "não consegui falar
com você" para a pessoa que tinha combinado o horário naquela manhã. **A campanha não sabe o
que a conversa combinou.**

**③ `9192312177` — Rosana. O follow funcionou e ninguém apareceu.** *(está aqui pelo toque, não pelo desfecho — o desfecho é o item ⑤ do §4.2)*

**④ `8592987046` — Ana.** Escreveu **espontaneamente** em 23/08 00:52 (*"Fiz minha aplicação
na turma 3 … e gostaria de"*). Ficou 4 dias sem resposta. Em 29/08 19:23, depois de dois
templates em lote, escreveu o pedido mais explícito da janela: *"Possuo sim.. Você consegue
me ligar para explicar como funciona, como são as aulas, tem artigo para conclusão.. você me
liga na segunda"*. Na segunda (31/08 16:20) ela recebeu o `f3_guia_ementa` **em lote**.
Respondeu no mesmo minuto: *"Como funciona as aulas"* — a mesma pergunta, pela terceira vez.

**⑤ `1142288064` e `5185440615` — o ultimato funciona.** Os dois responderam *"Tenho sim"* /
*"Oi sim"* ao `ainda_ha_interesse`, um deles **1,1 minuto** depois. É o template com maior
taxa da casa (31,3%) e a razão é o aviso de encerramento.

### 4.2 Os piores

**① `4195901498` — Michele. Três negativas, cinco toques depois da primeira.**

```
26/08 15:08  LEAD    "Oi, eu nao tenho mais interesse. Obrigada"
26/08 15:09  humano  "Sem problemas, Michele! 😊 Obrigado por me avisar."
26/08 15:09  humano  "Só para eu registrar corretamente sua aplicação: o que fez você
                      decidir não seguir com a pós neste momento?…"
29/08 10:54  humano  processo_seletivo_fase  (bulk, lote de 95)   ← sábado
31/08 16:53  humano  f4_audio_confirma       (bulk, lote de 20)
31/08 17:15  LEAD    "Eu NÃO TENHO INTERESSE!
                      Já é a quarta mensagem que me mandam sobre e eu sempre digo que nao tenho"
```

O atendimento individual foi **impecável** — reconheceu, agradeceu, pediu o motivo. A lista
não leu nada disso. **A campanha não consulta o histórico da conversa.**

**② A mesma coisa, 8 vezes.** Dos 9 leads que disseram "não" de forma inequívoca, **8
continuaram recebendo**:

| Lead | Disse não em | Toques depois |
|---|---|---:|
| `1179926715` | 26/08 15:00 — *"Não tenho mais interesse"* | **6** |
| `4195901498` | 26/08 15:08 | 5 |
| `5195253240` | 26/08 14:59 | 5 |
| `8196326394` | 26/08 15:04 — *"não desejo iniciar a pós graduação no momento"* | 5 |
| `5397107849` | 28/08 13:52 | 5 |
| `8185088547` | 26/08 15:12 | 4 |
| `5391907058` | 26/08 16:48 | 2 |
| `4498992623` | 03/08 17:04 | 2 |

O caso `8196326394` (Maria) disse **três vezes**: *"não desejo iniciar"* (26/08), *"não seguir
com essa formação"* (26/08) e *"Não tenho interesse em seguir minha inscrição"* (31/08) — a
última já em resposta ao quinto toque.

**③ Nove pessoas receberam o mesmo template duas vezes em 23,5 h.** A onda de
`f4_audio_confirma` de 24/08 16h24 (9 leads) foi repetida em 25/08 15h52 para exatamente os
mesmos 9. São **9 das 12 duplicatas** (mesma família, mesmo lead, < 24 h) da janela inteira.

**④ 21 pessoas receberam ≥ 5 templates em 8 dias e nunca responderam uma vez.** Nenhum lead
recebeu a mesma família 3×, então formalmente a régua está sendo respeitada — o problema é a
**soma das réguas**: 5 famílias diferentes, cada uma com sua lista, chegando na mesma pessoa.

**⑤ `9192312177` — Rosana. A thread termina assim:**

```
21/08 07:37  humano  [texto da NAT enviado como template humano, sem carimbo]
24/08 14:54  humano  tentativa_contato  "…é o Thobias do CENAT ✨"
25/08 15:18  humano  tentativa_contato  "…é o Saúde Mental do Trabalhador do CENAT ✨"  ← §4.3
25/08 16:33  LEAD    "A noite! As 21h , se puder"
─────────────────────────────────────────────────────────────────── (fim. 7 dias.)
```

Ela leu as três (`status='read'`), disse a que horas podia, e **nunca mais recebeu nada**.
Não é caso isolado de intenção: 37 leads deram sinal de horário ou disponibilidade na janela,
e ao menos 3 deles não tiveram nenhum outbound depois — nem da IA, nem de gente.

### 4.3 O defeito de parâmetro do `tentativa_contato`

O template abre com *"Ola {{1}}, é o {{2}} do CENAT ✨"*. O `{{2}}` deveria ser o SDR. Em
**43 dos 82 envios (52%)** ele recebeu o **nome do curso**:

| O que foi para o `{{2}}` | Envios | Leads |
|---|---:|---:|
| **Thobias** ✅ | 39 | 39 |
| Saúde Mental e Mulheridades ❌ | 11 | 11 |
| PsicologiaEscolar ❌ | 9 | 9 |
| Transtorno do Espectro Autista (TEA) ❌ | 7 | 7 |
| Saúde Mental do Trabalhador ❌ | 4 | 3 |
| Autolesão, Suicídio e Luto / BoasPraticasEAD / Grupos e Oficinas ❌ | 9 | 9 |
| Psicologia na RAPS / Infantojuvenil EAD / Enfermagem em SM ❌ | 3 | 3 |

O que 42 pessoas leram: *"Ola Daiane, é o **PsicologiaEscolar** do CENAT"*, *"Ola Vitória, é o
**Transtorno do Espectro Autista (TEA)** do CENAT"*. E como isso é o mesmo campo que o §1.4
usaria para inferir remetente, **a assinatura no corpo não serve nem para atribuir o envio**.

Corolário útil: `9192312177` recebeu o mesmo template duas vezes assinado por dois "remetentes"
diferentes — Thobias em 24/08, o curso em 25/08. É a mesma pessoa mandando.

### 4.4 Follow caindo em conversa ativa da IA — o filtro de 28/08 **funcionou**

`nat_qualificacao_state.transferido_motivo = 'outbound_manual_sdr'` é o registro de quando um
envio humano calou o agente:

| Período | Cortes |
|---|---:|
| Antes do fix (até 29/08 11:31) | **43** |
| Depois do fix | **3** |

E os 3 de depois **não são bulk** — são envio individual pela tela, todos do Thobias
(31/08 10:40, 31/08 16:36, 01/09 13:49). O caso do 01/09 é um `consultora_tentou` mandado à
mão numa thread em que a NAT tinha aberto às 09h01 e o lead tinha respondido.

**O filtro do disparo em massa está confirmado em produção.** O que sobrou é a porta
individual, que é justamente onde a trava **deve** existir mas ser silenciosa (o SDR assume
de propósito). Sobre a janela inteira, 51 follows caíram em threads onde a IA tinha falado
nas 72 h anteriores — **48 deles antes do fix**.

### 4.5 Onde o lead some na conversa da IA

Funil dos campos, entre as 118 conversas abertas pela NAT:

| Etapa | Chegaram | Perda no passo |
|---|---:|---:|
| Abertura entregue | 118 | — |
| **Respondeu alguma vez** | **77** (65%) | −41 |
| Deu a **formação** | 72 | −5 |
| Deu o **ano de conclusão** | **45** | **−27 (−37,5%)** ⚠️ |
| Deu a **atuação** | 40 | −5 |
| Deu a **motivação** | 35 | −5 |
| **Agendou** | 36 | — |

**O ano de conclusão é o degrau.** Sozinho ele derruba 37,5% de quem já estava conversando —
mais do que todos os outros passos somados (15 perdas em quatro passos). Isso **confirma com
janela maior** a medida do relatório de 29/08.

E a foto de quem calou e nunca mais voltou (39 conversas):

| Etapa em que ficou parado | Leads |
|---|---:|
| `encerrado` / inatividade (72 h) | 14 |
| **`aguardando_ano`** | **9** |
| **`aguardando_formacao`** | **4** |
| **`aguardando_motivacao`** | **3** |
| **`escolhendo_slot`** | **2** |
| `concluido` (nada devido) | 3 |
| `transferido_humano` | 4 |

**18 leads estão parados numa etapa ativa, esperando uma pergunta ser respondida, sem que
ninguém tenha mandado mais nada.** Dois deles estavam **escolhendo o horário da reunião**.

---

## 5. Fechamento

### 5.1 Painel

| Métrica | IA (NAT) | Humano — individual | Humano — **bulk** |
|---|---:|---:|---:|
| Toques na janela | 364 | 74 tpl + 95 texto | **443** |
| Leads tocados | 118 | 67 / 31 | 136 |
| **Follows (≥20 h)** | 13 *(não são follow — §1.5)* | **39** | **326** |
| Silêncio mediano até o follow | — | 54,0 h | 45,7 h |
| Taxa de resposta ao follow (24 h) | — | 15,4% | 10,7% |
| **Resposta *útil*** (exclui recusa/robô) | — | \| — 3,6% no total humano — \| | |
| Conversão pós-follow 72 h (estrita) | 2/13 | **4/36 (11,1%)** | **6/122 (4,9%)** |
| Duplicatas (mesma família, <24 h) | 0 | 0 | **12** |
| Taxa de leitura do outbound | 47,5% | 37,8% | 41,8% |
| Falhas de entrega | 7 | \| — 11 — \| | |

**Abertura, para contexto:** IA 53,3% (40/75) · humano 38,3% (18/47) · follow humano 11,2%
(41/365). *Populações diferentes — §2.3.*

**Falhas Meta na janela (18):** `130472` User's number is part of an experiment (9) ·
`131026` Message undeliverable (4) · **`131049` "not delivered to maintain healthy ecosystem" (4)** ·
`131053` Media upload error (1).

### 5.2 Os três achados de maior impacto

---

**#1 — Existe um follow de 13,7% e a operação está mandando o de 7,9%.**

*Evidência:* §2.4. Taxa de resposta por faixa de silêncio: 20–24 h → **13,7%** (N=124);
48–72 h → **7,9%** (N=127). A latência mediana real é **45,7 h** no bulk e **54,0 h** no
individual. E 18 conversas da IA estão paradas **agora** numa etapa ativa, sem follow nenhum,
2 delas escolhendo horário (§4.5).

*Por que importa:* não é um pedido de mais mensagem — é o mesmo volume, mais cedo. A IA já
tem o relógio (`nat_scheduled_actions` roda `encerrar_inativo` em +72 h para essas mesmas
threads). Falta usar o de +20 h.

---

**#2 — A campanha não lê a conversa, e o lead percebe.**

*Evidência:* §4.2. 8 de 9 leads que disseram "não" continuaram recebendo, até 6 toques
depois — um respondeu *"Já é a quarta mensagem que me mandam sobre e eu sempre digo que nao
tenho"*. 21 pessoas receberam ≥5 templates sem nunca responder. 9 receberam o mesmo template
2× em 23,5 h. E a Yasmin, que tinha combinado ligação às 16h30, recebeu às 16h36 um template
de "não consegui falar com você" (§4.1②).

*Por que importa:* já saiu do campo da eficácia e entrou no da **entregabilidade**. Quatro
envios da janela voltaram com `131049 — not delivered to maintain healthy ecosystem`, que é a
Meta protegendo o destinatário de nós. O ativo em risco é o número, não a campanha.

*Conserto mais barato:* antes de montar qualquer lote, excluir (a) quem tem inbound com
recusa nos últimos 30 dias, (b) quem já recebeu ≥3 templates nos últimos 7 dias, (c) quem tem
`nat_qualificacao_state.etapa` numa etapa ativa. O item (c) **já existe** e é o filtro de
28/08, que provadamente funcionou (§4.4) — os outros dois são a mesma ideia com outro campo.

---

**#3 — Não é possível medir SDR nenhum, e nada nesta base vai mudar isso sozinho.**

*Evidência:* §1.4. `messages` não tem `sent_by` nem `template_name`; as cinco rotas de envio
recebem `current_user` e o descartam; `nat_contact_attempts` teve **0** registros na janela;
e a assinatura no corpo do template — a última fonte que restaria — **está errada em 52% dos
casos** (§4.3). O único traço durável é `assumido_por`, que só existe quando o agente estava
no meio de uma qualificação: **45 envios, 45 do Thobias**.

*Por que importa:* metade do briefing deste recon ("por SDR nomeado", latência por SDR,
duplicata por SDR) é hoje inexequível, e vai continuar sendo em todo relatório futuro. Duas
colunas aditivas resolvem — e o passado não volta, então cada dia sem elas é dado perdido.

*Bônus do mesmo parágrafo:* consertar o `{{2}}` do `tentativa_contato` é meia hora e para de
mandar *"é o PsicologiaEscolar do CENAT"* para 5 pessoas por dia.

### 5.3 Recomendação para o follow da IA (Sprint D) — **proposta, nada executado**

**a) O N: 20 horas, um único follow.**

Não é opinião: é o balde de maior taxa (13,7%, N=124) e fica **dentro da janela de 24 h** da
Meta, o que permite tentar mensagem livre antes de gastar template. **Um só** — a curva de
ordem do §2.3 (17,4% → 11,7% → 7,8% → 6,8% → 0%) diz que o segundo follow rende menos que o
primeiro e o quinto rende zero. Se um dia houver um segundo, ele deve ser medido antes de ser
padronizado, não o contrário.

**b) O texto: não use `nat_recuperacao_sdr`.**

Ele está aprovado (`nat_copy.py:47`) e é o candidato óbvio, mas o corpo não serve:

> *"Tentamos falar com você **há alguns minutos**, mas não conseguimos concluir o contato."*

Esse texto é do Bloco 6 — recuperação de ligação que caiu, minutos depois. Mandá-lo 20 h
depois de uma pergunta de texto seria a NAT afirmando que tentou ligar quando não tentou.
Além disso `nat_copy.py:80` registra que **existem dois `nat_recuperacao_sdr` aprovados no
WABA com corpos diferentes** (`en` e `pt_BR`) — usá-lo em contexto novo herda essa ambiguidade
de graça.

**O que o dado sugere no lugar:** o template de maior taxa da casa é o `ainda_ha_interesse`
(31,3%), e o que ele tem de diferente é **o aviso de encerramento**. A NAT já encerra por
inatividade em 72 h — ela pode dizer isso, que é verdade, em vez de inventar uma ligação. Um
corpo novo, submetido à Meta, na linha de:

> *"Olá {{1}}! Ficou faltando só uma informação para eu conseguir separar os horários da sua
> Pós em {{2}} 🙏 Se preferir, respondo por aqui mesmo — e se não fizer sentido agora, é só me
> dizer que eu encerro sua aplicação sem problema."*

Retoma **a pergunta pendente** (que a NAT sabe: é a `etapa` do estado), dá saída honesta, e
não afirma nada falso. Aprovação de template leva dias — vale começar por aí, não pelo código.

**c) A trava de idempotência — ela já existe e é a razão pela qual o risco do Sprint D é menor
do que parecia.**

O risco que adiou o sprint é mandar follow duplicado (dois jobs, um restart, uma corrida). A
resposta já está construída em `nat_scheduled_actions`:

```
uq_nat_sched_pendente_por_contato
    UNIQUE (kind, contact_wa_id) WHERE status = 'pendente'
```

Índice **único parcial** — exatamente o padrão de "idempotência por constraint" que o projeto
adotou em `uq_notif_agente_parado` (S4-1, 26/08). E `nat_scheduler.agendar()` (linha 205)
**cancela o pendente do mesmo par antes de inserir**, então reagendar substitui em vez de
acumular; o índice é a rede, não o mecanismo. `_proxima_acao` já pega a ação com
`FOR UPDATE SKIP LOCKED`, o que fecha a corrida entre dois workers.

**Nada disso precisa ser construído.** O Sprint D é, na prática:

1. `kind = 'follow_20h'`, agendado por `agendar()` quando a NAT faz uma pergunta e fica
   esperando — mesma transação que grava a etapa, dentro do `begin_nested()` do fluxo.
2. `cancelar('follow_20h', wa_id)` em **três** gatilhos que já existem e já são chamados:
   inbound do lead, `silenciar()` (SDR assumiu) e transição para `concluido`/`encerrado`.
3. No handler, antes de enviar, reconferir que a etapa **continua** ativa e que não houve
   inbound depois — o padrão `skipped` com `motivo`, igual ao que `iniciar_qualificacao` já
   faz (há 16 `skipped` na tabela, com motivo legível).

**A trava que ainda falta, e é a do §5.2#2, não a do sprint:** o `follow_20h` precisa checar
se **um humano** tocou a thread nesse intervalo. Hoje a NAT sabe quando o SDR digitou (é o
`silenciar`), mas **não** sabe quando uma campanha passou por cima — `bulk_send_template`
chama `_silenciar_agente_apos_envio_manual`, então uma thread em etapa ativa sai do ar
corretamente; o que não está coberto é a thread já **encerrada** que recebe campanha e depois
receberia o follow da NAT como se nada tivesse acontecido. Um `NOT EXISTS` sobre `messages`
outbound nas últimas 20 h resolve, e não depende de coluna nova.

---

## Anexo A — Convenções

* **Fusos.** `messages.timestamp` é SP naive; `exact_stage_events.observado_em` e
  `exact_leads.register_date` são UTC. Todo cruzamento converteu UTC → SP com `− 3 h`.
* **Telefone.** Threads foram agrupadas pela chave tolerante ao 9º dígito (DDD + últimos 8),
  espelhando `chave_telefone` de `app/telefone.py`. Sem isso, 340 pessoas da base contam como
  duas.
* **Ator.** `nat_etapa IS NOT NULL` → IA. `outbound` + `template` sem `nat_etapa` → template
  humano. `outbound` + texto/mídia sem `nat_etapa` → humano digitado.
* **Família de template.** Reconstruída por `LIKE` sobre o corpo renderizado — `messages` não
  guarda o nome do template (§1.4). 17 famílias, 0 mensagens não classificadas.
* **Campanha × individual.** Ilha de mensagens da mesma família encadeadas por ≤ 120 s;
  ≥ 4 destinatários distintos → campanha.
* **Cobertura do vínculo com a Exact.** 231 das 275 threads da janela (84%) casaram com um
  lead. As 44 restantes são números sem lead na Exact e ficaram fora do §2.5 e do §3.

## Anexo B — O que este relatório **não** sustenta

1. **Nada por SDR individual.** §1.4. A base não tem o dado.
2. **Comparação IA × humano em taxa de resposta.** §2.3. Populações diferentes.
3. **Conversão da IA no follow.** N=13, e 6 desses 13 são lembrete de reunião. O 15,4% do
   painel não decide nada.
4. **Atribuição de conversão quando os dois atores tocam a mesma thread.** §4.1①.
5. **"Abaixo da etapa" no §3 como trabalho não feito.** Ligação não deixa rastro nesta base.
6. **Qualquer número de funil que some `Reagendamento` e `Reagendamento.`** §2.5.

## Anexo C — Consultas

Reprodução: as consultas montam três tabelas `TEMP` (`m` com ator+família, `mk` com a chave de
telefone, `msg_canal` com bulk/individual) e derivam `toques` e `follows` delas. Nenhuma
escrita, nenhum DDL permanente.

```sql
-- Classificação de ator e família (base de tudo)
SELECT id, contact_wa_id AS wa, direction, message_type, content, timestamp AS ts, status, nat_etapa,
  CASE WHEN direction='inbound' THEN 'lead'
       WHEN nat_etapa IS NOT NULL THEN 'ia'
       WHEN message_type='template' THEN 'hum_tpl'
       ELSE 'hum_txt' END AS ator,
  CASE WHEN direction<>'outbound' OR nat_etapa IS NOT NULL THEN NULL
       WHEN content LIKE '%Tentei realizar uma nova tentativa de contato%'        THEN 'tentativa_contato'
       WHEN content LIKE '%Fiz uma nova tentativa de contato, mas ainda sem suc%' THEN 'f5_ligacao'
       WHEN content LIKE '%link de acesso à ementa da Pós-Graduação%'             THEN 'f3_guia_ementa'
       WHEN content LIKE '%conseguiu ouvir o *áudio do coordenador*%'             THEN 'f4_audio_confirma'
       -- … 13 famílias restantes, mesmo padrão
       WHEN message_type='template' THEN 'outro_template' ELSE NULL END AS familia
FROM messages;

-- Chave de telefone tolerante ao 9º dígito (= app/telefone.py:chave_telefone)
SELECT DISTINCT wa,
  CASE WHEN length(d) IN (10,11) THEN substr(d,1,2)||right(d,8) ELSE '' END AS k
FROM (SELECT wa, CASE WHEN wa LIKE '55%' AND length(wa) IN (12,13)
                      THEN substr(wa,3) ELSE wa END AS d FROM m) x;

-- Campanha × individual: ilhas de ≤120s, ≥4 destinatários
WITH x AS (
  SELECT id, wa, ts, familia,
         CASE WHEN ts - lag(ts) OVER (PARTITION BY familia ORDER BY ts) <= interval '120 seconds'
              THEN 0 ELSE 1 END AS novo
  FROM m WHERE ator='hum_tpl' AND ts>='2026-08-24'
), y AS (SELECT *, sum(novo) OVER (PARTITION BY familia ORDER BY ts ROWS UNBOUNDED PRECEDING) AS ilha FROM x)
SELECT familia, ilha, min(ts), max(ts), count(*), count(DISTINCT wa) FROM y GROUP BY 1,2;
   -- ilha com count(DISTINCT wa) >= 4  →  'bulk'

-- Toques: outbound anterior, lead falou no meio, respondeu em 24h
WITH o AS (
  SELECT id, thr, ts, ator, familia,
         lag(ts)   OVER (PARTITION BY thr ORDER BY ts) AS ts_prev,
         lag(ator) OVER (PARTITION BY thr ORDER BY ts) AS ator_prev
  FROM mk WHERE direction='outbound')
SELECT o.*,
  EXISTS (SELECT 1 FROM mk i WHERE i.thr=o.thr AND i.direction='inbound'
            AND i.ts>o.ts_prev AND i.ts<=o.ts) AS lead_falou_no_meio,
  EXISTS (SELECT 1 FROM mk i WHERE i.thr=o.thr AND i.direction='inbound'
            AND i.ts>o.ts AND i.ts<=o.ts+interval '24 hours') AS respondido_24h
FROM o;

-- FOLLOW = ts_prev IS NOT NULL AND NOT lead_falou_no_meio AND ts-ts_prev >= interval '20 hours'

-- Conversão ESTRITA (exclui Reagendamento → Reagendamento.)
SELECT f.ator, f.canal, count(DISTINCT f.thr),
 count(DISTINCT f.thr) FILTER (WHERE EXISTS (
   SELECT 1 FROM thr_lead tl JOIN ev e ON e.exact_lead_id=tl.exact_id
   WHERE tl.thr=f.thr AND e.ts_sp>f.ts AND e.ts_sp<=f.ts+interval '72 hours'
     AND (e.stage_para ILIKE '%Agendad%' OR e.stage_para ILIKE '%Reagendament%')
     AND NOT (coalesce(e.stage_de,'') ILIKE '%Agendad%'
           OR coalesce(e.stage_de,'') ILIKE '%Reagendament%')))
FROM follows f GROUP BY 1,2;

-- Defeito de parâmetro do tentativa_contato (§4.3)
SELECT substring(content from 'é o ([^\n]*?) do CENAT'), count(*), count(DISTINCT thr)
FROM mk WHERE familia='tentativa_contato' AND ts>='2026-08-24' GROUP BY 1 ORDER BY 2 DESC;

-- Leads que recusaram e continuaram recebendo (§4.2②)
SELECT r.thr, r.ts_nao,
  (SELECT count(*) FROM mk o WHERE o.thr=r.thr AND o.direction='outbound'
    AND o.ts>r.ts_nao AND o.status<>'failed') AS toques_depois
FROM recusa r ORDER BY toques_depois DESC;
   -- recusa = primeiro inbound casando 'não tenho (mais) interesse|não desejo|desistir|
   --          não irei fazer|não tenho condições'
```
