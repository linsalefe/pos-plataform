# Relatório comparativo — agente de IA × atendimento humano

**Janela:** 24/08/2026 20:16 SP (ativação do agente) → 29/08/2026 12:20 SP.
São **4 dias úteis completos** (25, 26, 27 e 28/08) mais a manhã de um **sábado**.

**Natureza deste documento:** somente leitura. Nenhum envio, nenhuma escrita, nenhuma
migração. Todo número do corpo tem a query que o gerou no Anexo B.

> **Leia primeiro o §0.** Ele diz, em quatro linhas, o que estes números sustentam e o que
> não sustentam. O resto do documento é a memória de cálculo.

---

## 0. O veredito curto

**O agente é incomparavelmente mais rápido, e o humano é incomparavelmente mais abrangente.**
A IA responde uma pergunta em **3,7 segundos** (mediana); o humano, em **28 minutos** — e
esses 28 minutos são a mediana *de quem foi respondido*: há **73 perguntas em aberto**
esperando há **70,8 horas** (mediana). Em compensação, o humano tocou **144 pessoas** na
janela e a IA tocou **63** (46 em comum).

**Mas a comparação direta não se sustenta, e é honesto dizer por quê.** Os dois não trabalham
a mesma gente: **100% dos contatos da IA são leads novos desta janela**; o humano dividiu seu
esforço dirigido entre **15 leads novos e 11 leads antigos** da base. Onde dá para cortar
igual — só leads novos —, os volumes ficam quase empatados: a IA conversou com **15**, o
humano com **16**, de **104** leads novos.

**O que mais chama atenção não é nenhum dos dois atores.** Das **27 reuniões** marcadas na
janela, **18 foram marcadas pelo próprio lead na landing page**, sem IA e sem SDR. A IA marcou
**1**. Outras **8** apareceram na Exact **sem nenhuma conversa de WhatsApp que as explique** —
e essas ficam classificadas como **indeterminadas**, não creditadas a ninguém (§4.2).

**E há um atrito ativo entre os dois times.** O disparo em massa do SDR **encerrou 41 das 63
conversas da IA** — 7 delas com o agente respondendo havia menos de 24 horas. Não é opinião:
é o campo `transferido_motivo` do banco. A correção entrou em produção **hoje às 11:31**, ou
seja, **depois** de praticamente toda a janela medida.

---

## 1. O painel — IA × Humano, lado a lado

Toda célula traz o **N**. Amostra pequena: nenhum percentual abaixo tem intervalo estreito.

| # | Métrica | **IA (agente NAT)** | **Humano (SDR)** | Leitura |
|---|---|---|---|---|
| **1** | **Volume** (base: 104 leads novos) | abertura **entregue a 62** (60%); conversa de **≥1 turno com 15** (14%) | mensagem **dirigida a 16** (15%); disparo em massa a **65** (63%) | Empate no atendimento real de lead novo |
| **2** | **Velocidade** | lead entra → 1º contato: **6,9 h** (N=65)<br>responde pergunta em **3,7 s** (N=34) | lead entra → 1º contato: **21,6 h** (N=16)<br>responde pergunta em **28 min** (N=34) | IA ganha por **450×** na resposta |
| **3** | **Profundidade** | **49%** responderam à abertura (31/63)<br>**19%** com qualificação completa (12/63)<br>**21%** chegaram à oferta de horário | **50%** dos 28 contatos dirigidos citaram horário/agenda (14/28)<br>**sem registro estruturado** de qualificação | Só a IA deixa dado reaproveitável |
| **4** | **Conversão a reunião** | **1** reunião / 15 atendidos = **6,7%** | **1** reunião rastreável / 28 contatos = **3,6%**<br>*(+7 sem origem observável)* | **N=1 e N=1.** Não decide nada |
| **5** | **Qualidade do dado** | curso do box divergente em **1/1** — mas **não vazou para o CRM** (§5.1)<br>qualificação completa em **1/1** | **18/18** cursos corretos na via da LP<br>qualificação completa em **6/18** | Defeito da IA era menor do que se supunha |
| **6** | **Perdas** | **6** aberturas não saíram (4 pessoas)<br>**3** envios falharam<br>**3** agendamentos travados | **73** perguntas sem resposta (espera mediana **70,8 h**)<br>**41** conversas da IA cortadas pelo disparo | A maior perda da casa é a fila humana |
| **7** | **Custo-capacidade** | **134** mensagens / 63 contatos<br>ativo **06h–18h**, **zero no sábado** | **84** dirigidas / 28 contatos<br>**373** disparos / 143 contatos<br>**trabalhou no sábado** | O "24/7" **não** se confirma (§7.2) |

---

## 2. Volume — quem falou com quem

Entraram **110 leads** na janela. **6 são de teste** e saíram de todas as métricas deste
relatório (lista nominal no Anexo A). Base final: **104 leads reais**.

| | Leads alcançados | % de 104 |
|---|---:|---:|
| IA — abertura **enviada** | 65 | 63% |
| IA — abertura **entregue** | 62 | 60% |
| IA — **conversou** (entregue + ≥1 turno) | **15** | **14%** |
| Humano — **mensagem dirigida** (exclui disparo em massa) | **16** | **15%** |
| Humano — disparo em massa apenas | 65 | 63% |
| **Ninguém tentou contato algum** | **19** | **18%** |

**Os 19 leads que ninguém tocou são o buraco mais barato de tapar da lista.** Não houve
abertura, não houve mensagem dirigida e não houve nem disparo. São leads que pagaram mídia
para entrar e nunca souberam disso. *(Em outros 3, a única tentativa falhou na entrega —
total de 22 leads sem nenhum contato entregue.)*

### 2.1 O viés de população, explicitado

Esta é a ressalva mais importante do relatório, e ela vale para **todas** as sete métricas.

| Ator | Leads novos da janela | Leads antigos da base | Sem lead na Exact |
|---|---:|---:|---:|
| IA (abertura ou turno) | **63** | 0 | 0 |
| Humano — dirigido | 15 | **11** | 2 |
| Humano — disparo em massa | 65 | **75** | 3 |

**A IA só recebe lead novo; o humano trabalha as duas coortes.** Isso não é defeito de
ninguém — é o desenho: o agente é acionado na entrada do lead, o SDR toca também a lista de
reengajamento. Mas significa que **comparar "conversão total" dos dois é comparar times que
jogam campeonatos diferentes**. Onde foi possível, este relatório corta só leads novos.

---

## 3. Velocidade — a única diferença que já é conclusiva

### 3.1 Do lead entrar até o primeiro contato

| | N | Mediana | p90 | Melhor | Pior |
|---|---:|---:|---:|---:|---:|
| **IA** | 65 | **6,9 h** | 22,0 h | 5 min | 22,6 h |
| **Humano** | 16 | **21,6 h** | 2,1 d | 11 min | 3,1 d |

**A mediana da IA está inflada por decisão de produto, não por lentidão.** A abertura é
*business-initiated* e respeita horário comercial (**09h00–18h30, seg–sex**): o lead que se
cadastra às 22h só recebe a mensagem às 09h do dia seguinte, e essas 11 horas entram na
mediana. O **melhor caso de 5 minutos** é o que a IA faz quando o lead chega dentro da janela.

### 3.2 Do lead perguntar até alguém responder

Mesmo método para os dois atores: do **primeiro inbound sem resposta** até a **primeira
resposta dirigida**. Disparos em massa e aberturas **não** contam como resposta.

| | N | Mediana | p90 | Pior |
|---|---:|---:|---:|---:|
| **IA** | 34 | **3,7 s** | 44 min | 11,9 h |
| **Humano** | 34 | **28 min** | 22,0 h | 41,6 h |

**28 dos 34 casos da IA ficaram abaixo de 60 segundos.** Os 6 lentos são, em sua maioria,
mensagens que chegaram fora do expediente e esperaram a abertura da manhã seguinte — e três
deles são de 25–26/08, antes da correção do agente mudo.

Enquanto o agente estava de plantão numa conversa (depois da abertura, antes de qualquer
transferência), ele respondeu **60 de 74 inbounds — 81%**, com mediana de **3,7 s**.

---

## 4. Conversão a reunião — onde os números ainda não decidem nada

### 4.1 As 27 reuniões da janela

Foram **27 leads distintos** que entraram em `Agendados` no funil 18535 durante a janela
(1 lead de teste já excluído).

| Origem | Reuniões | % |
|---|---:|---:|
| **Landing page — o próprio lead marcou** | **18** | 67% |
| **Indeterminado** — apareceu na Exact sem conversa que explique | **8** | 30% |
| **IA (agente)** | **1** | 4% |
| **SDR, rastreável no WhatsApp** | **(1 dos 8 acima)** | — |

**A maior fonte de reunião da casa não é a IA nem o SDR: é a própria landing page.** Dois
terços das reuniões da janela foram marcadas pelo lead sozinho, na página, sem ninguém
conversar com ele.

### 4.2 Por que 8 reuniões ficaram "indeterminadas"

Elas existem na Exact, mas **não passaram pela nossa página** e **não têm conversa de WhatsApp
que as explique**. Das 8, **apenas 1** (Luísa, lead antigo) recebeu mensagem dirigida do SDR
na janela. As outras 7 tiveram **zero** mensagens dirigidas:

| Lead | Nome | Coorte | Msg dirigida | Disparo | Inbound |
|---|---|---|---:|---:|---:|
| 51495138 | Luísa Maria Apolinário | antigo | **1** | 3 | 4 |
| 51488830 | Rosana Miranda | antigo | 0 | 1 | 1 |
| 31559736 | Josiane Silveira Alencastro | antigo | 0 | 0 | 1 |
| 51503544 | Cecília Nascimento | antigo | 0 | 2 | 0 |
| 51491666 | Maria Alyne | antigo | 0 | 0 | 0 |
| 51542809 | Maria Alyne *(lead duplicado)* | novo | 0 | 0 | 0 |
| 51616992 | Julia Torres | novo | 0 | 1 | 2 |
| 51639262 | Clovis Palafoz dos Santos | novo | 0 | 0 | 1 |

**A explicação mais provável é telefone.** O SDR também liga, e ligação não deixa rastro no
Hub. **Creditar essas 8 ao WhatsApp do SDR seria chute; creditá-las à IA seria falso.** Ficam
indeterminadas — e ficam registradas aqui como **o maior ponto cego da medição**.

### 4.3 O corte equivalente

Restringindo aos **leads novos da janela**, que é o único terreno comum:

| | Reuniões | Atendidos | Taxa |
|---|---:|---:|---:|
| **IA** | 1 | 15 | **6,7%** |
| **Humano** | 3* | 16 | 18,8% |

\* **e nenhuma das 3 teve mensagem dirigida do SDR no WhatsApp.** Ou seja: a taxa de 18,8%
mede um canal que não é o canal medido. **Com N=1 de um lado e N=3 não rastreáveis do outro,
esta linha não sustenta conclusão nenhuma** — está no relatório para registrar que ainda não
sustenta, não para ser citada.

---

## 5. Qualidade do dado

### 5.1 O curso da reunião — o defeito era menor do que o diagnóstico anterior dizia

O fechamento de 28/08 afirmava que **toda** reunião marcada pelo agente entrava na Exact com
o curso errado. **Verificado hoje, isso está errado — e a correção é para melhor.**

A Kaylla (lead 51610927) aplicou para **Pos TEA V3**, conversou 5 turnos sobre TEA, e o box
foi criado na nossa tabela como `PosMulheridades`. Mas uma **consulta de leitura à API da
Exact, feita nesta apuração**, mostra o lead no CRM com:

```
source: Landing Page  |  subSource: Pos TEA V3
```

**O curso errado nunca saiu da nossa tabela.** Como o agendamento do agente sempre manda
`lead_id`, o passo que reescreveria o `subSource` na Exact é pulado — então a consultora
abriu o box do curso **certo**, e o relatório de marketing creditou o curso **certo**.

| Via | Reuniões | Curso do box == curso do lead |
|---|---:|---:|
| IA (agente) | 1 | 0/1 **na nossa tabela** · **1/1 no CRM** |
| Landing page | 18 | **18/18** |

O defeito foi corrigido hoje às 11:01 (commit `ed163be`). **Impacto comercial real na janela:
zero.** Fica registrado porque a coluna ainda alimenta o nome do curso escrito na abertura.

### 5.2 Dado de qualificação

| Via | Reuniões | Com qualificação completa |
|---|---:|---:|
| IA (agente) | 1 | **1/1 (100%)** |
| Landing page | 18 | 6/18 (33%) |
| SDR | 8 | **sem registro estruturado** |

**Esta é a vantagem estrutural da IA que os números já sustentam.** Quando o agente marca,
a consultora recebe formação, ano, atuação e motivação preenchidos. Nas outras vias, ou o
dado vem do formulário (parcial), ou não existe em lugar nenhum consultável.

---

## 6. Perdas, por ator

### 6.1 Perdas da IA

| Perda | Quanto | Situação |
|---|---:|---|
| Aberturas que não saíram (contato gravado na outra grafia do telefone) | **6 tentativas, 4 pessoas** | Corrigido hoje 11:03 |
| Envios com falha de entrega da Meta | **3** | Fora do nosso controle |
| Agendamentos travados em `iniciado`, sem virar box | **3** (todos da mesma pessoa) | Não diagnosticado |

As falhas de entrega da janela, por código: **7×** `130472` (número em experimento da Meta),
**3×** `131049` (limite de engajamento por destinatário), **1×** `131026` (indisponível),
**1×** `131053` (erro de mídia). Desses **12** totais, **3 são da IA e 9 do disparo humano**.
Nenhum é bug: é volume que a Meta recusa, e nenhuma correção de código recupera.

### 6.2 Perdas do lado humano

**73 perguntas de leads seguem sem qualquer resposta**, com espera **mediana de 70,8 horas**
e máxima de **110,5 horas** (quase 5 dias). As mais antigas:

| Espera | Contato | Desde |
|---:|---|---|
| 110,5 h | Thaís Gonçalves | 24/08 21:51 |
| 107,5 h | *(sem nome)* | 25/08 00:50 |
| 100,6 h | Anna | 25/08 07:43 |
| 100,6 h | Isa | 25/08 07:43 |
| 99,0 h | *(sem nome)* | 25/08 09:20 |

**Ressalva honesta:** parte desses 73 são mensagens que não pedem resposta ("Obrigado",
reações, recusas). A triagem nominal de 27/08 mostrou que a maioria **pede**. O número exato
de perguntas legítimas está entre 73 e algo menor — mas a ordem de grandeza é a fila, não o
ruído.

### 6.3 A perda que os dois times causam juntos

**O disparo em massa encerrou 41 das 63 conversas da IA.** É a maior causa isolada de
encerramento do agente na janela — maior que todas as outras somadas.

| Motivo do fim da conversa da IA | Casos |
|---|---:|
| **Disparo em massa do SDR** | **41** |
| Mensagem dirigida do SDR (legítimo) | 1 |
| Varredura retroativa | 1 |
| Recusa de envio / erro do agente | 5 |
| Encerrada por inatividade / sem resposta | 5 |
| **Concluída** (chegou ao fim do fluxo) | **3** |
| Ainda ativa, aguardando o lead | 7 |

Das 41, **7 estavam vivas** (o agente havia respondido nas últimas 24h) e **26 eram de leads
que já tinham respondido alguma vez**.

**O caso que resume a janela inteira** — Morgana, 26–29/08:

```
26/08 22:58  lead      "Fiz minha aplicação na turma da Pós-Graduação…"
27/08 09:00  IA        abertura (esperou o horário comercial)
27/08 10:51  lead      "Sou formada em Letras e Pedagogia."
27/08 10:51  IA        resposta em 4 segundos
27/08 10:52  lead      "Letras 2003 Pedagogia 2018"
27/08 10:52  IA        resposta em 3 segundos
27/08 11:10  SDR       DISPARO EM MASSA: "Tentei realizar uma nova tentativa de contato"
             ─────────  o agente é encerrado. Ninguém mais conversa com ela.
28/08 11:49  SDR       disparo em massa
29/08 10:53  SDR       disparo em massa
```

Ela respondeu duas perguntas em 90 segundos, estava a duas perguntas de uma reunião, e
recebeu três avisos automáticos de que não conseguiram contato com ela.

**A correção entrou em produção hoje às 11:31.** A janela deste relatório termina às 12:20 —
**não há dados suficientes para dizer que funcionou.** É a primeira coisa a medir na semana
que vem.

---

## 7. Custo-capacidade

### 7.1 Esforço na janela

| | IA | Humano |
|---|---:|---:|
| Turnos de conversa | **71** | — |
| Aberturas e lembretes | **63** | — |
| Mensagens manuais dirigidas | — | **84** |
| Disparos em massa | — | **373** |
| **Total de mensagens enviadas** | **134** | **457** |
| **Pessoas alcançadas** | **63** | **144** |
| *(dessas, tocadas pelos dois)* | **46** | **46** |

A IA conduz conversas em paralelo sem fila, e a duração mediana de uma conversa dela
(≥2 turnos) é de **2 minutos**. Este relatório **não estima custo em reais** — não há dado de
custo confiável para isso, e inventá-lo enfraqueceria o resto.

### 7.2 O "24/7" não se confirma nesta janela

Esta é a correção mais importante deste relatório a uma crença corrente.

**Distribuição por dia (mensagens enviadas):**

| Dia | IA | Humano dirigido |
|---|---:|---:|
| 25/08 ter | 32 | 21 |
| 26/08 qua | 47 | 37 |
| 27/08 qui | 39 | 6 |
| 28/08 sex | 16 | 13 |
| **29/08 sáb** | **0** | **7** *(+95 disparos)* |

**No sábado a IA não enviou nada e o humano trabalhou.** Isso é **desenho, não falha**: a
abertura respeita 09h–18h30 de segunda a sexta, e as 6 aberturas dos leads que entraram no
sábado foram **empurradas para segunda-feira 31/08 às 09h** — corretamente, e sem perder
nenhum lead.

**E fora do horário?** Restringindo aos inbounds que chegaram enquanto o agente era o dono
da conversa:

| Faixa | Inbounds | Respondidos pela IA | Mediana |
|---|---:|---:|---:|
| 09h–19h | 70 | 58 | **3,7 s** |
| Fora | **4** | 2 | 5 s |

**Chegaram apenas 4 mensagens fora do expediente com o agente de plantão.** Isso não prova
que ele atende de madrugada nem que não atende — **prova que a janela não testou isso**.
A afirmação "a IA atende 24/7" é hoje uma **expectativa de projeto, não um resultado medido**.

---

## 8. O que os números sustentam, e o que ainda não

### 8.1 Sustentam

1. **A IA responde em 3,7 segundos e o humano em 28 minutos** (N=34 de cada lado, mesmo
   método). É a diferença mais robusta do relatório.
2. **A IA alcança o lead novo mais cedo** — 6,9h contra 21,6h até o primeiro contato — mesmo
   carregando a espera do horário comercial na mediana.
3. **Só a IA produz dado de qualificação reaproveitável.** 100% das reuniões dela chegam com
   os quatro campos; a via da landing page entrega 33% e a via do SDR não entrega nada
   consultável.
4. **O disparo em massa destruiu 41 das 63 conversas da IA.** Não é inferência: é o campo de
   motivo no banco, com data e hora de cada corte.
5. **A fila humana tem 73 perguntas paradas há 70,8 horas (mediana).** É a maior perda
   mensurável da operação, maior que qualquer defeito do agente.
6. **A landing page é a maior fonte de reuniões** — 18 de 27, sem nenhum atendimento.

### 8.2 Não sustentam

1. **Qual ator converte melhor.** IA marcou 1 reunião; o SDR tem 1 rastreável e 7
   indeterminadas. **N=1 contra N=1.** Qualquer taxa citada daqui seria ruído.
2. **Que a IA atende 24/7.** Só 4 mensagens chegaram fora do expediente com o agente de
   plantão (§7.2).
3. **Que a IA "cansa menos" ou "custa menos".** Não há dado de custo neste relatório, de
   propósito.
4. **Que a correção do disparo em massa funcionou.** Entrou às 11:31 de hoje; a janela fecha
   às 12:20.
5. **Comparação de conversão global entre os dois.** As populações são diferentes por
   desenho (§2.1) e não foram aleatorizadas.
6. **Qualquer tendência.** São 4 dias úteis. Não há série temporal aqui, só um retrato.

### 8.3 As três alavancas de maior impacto — IA

1. **Confirmar que o disparo parou de atropelar a conversa viva.** 41 conversas foram
   perdidas por isso em 4 dias — é a maior perda isolada do agente, e a correção ainda não
   tem uma única hora de dado. **Medir na segunda-feira.**
2. **Fazer a segunda pergunta funcionar.** 84% dos leads entregam a formação, mas só **29%**
   entregam o ano de conclusão. A queda de 84% → 29% é o gargalo do funil da IA, e está numa
   pergunta só.
3. **Atender os 19 leads que ninguém tocou.** A abertura só alcançou 60% dos leads novos.
   Elevar a cobertura da abertura é o ganho mais barato disponível — não exige nenhuma
   melhoria de conversa.

### 8.4 As três alavancas de maior impacto — Humano

1. **Zerar a fila de 73 perguntas sem resposta.** Uma pessoa esperando 110 horas por uma
   resposta já foi perdida; o custo dela já foi pago na mídia.
2. **Parar de disparar sobre quem já está conversando.** Além de matar 41 conversas, manda
   "não consegui contato com você" para alguém que respondeu **18 minutos antes**. É o pior
   dano de marca da janela.
3. **Registrar o que acontece fora do WhatsApp.** 7 das 8 reuniões indeterminadas
   provavelmente vieram de telefone. Enquanto isso não for registrado, **o SDR aparece pior
   do que é** em qualquer relatório como este — e a gestão decide com o número errado.

---

## Anexo A — Decisões de classificação

### A.1 Leads de teste excluídos (6 de 110)

| Lead | Nome | Telefone | Entrou |
|---|---|---|---|
| 51548604 | Álefe Guimel Lins Barbosa | 5583988046720 | 25/08 15:31 SP |
| 51550281 | zzz teste | 5583988046720 | 25/08 17:14 SP |
| 51585608 | fafaf | 5571985252525 | 26/08 18:43 SP |
| 51593541 | Thobias Justino França *(o próprio SDR)* | 5567999151808 | 27/08 01:10 SP |
| 51600542 | teste | 5583988046720 | 27/08 10:07 SP |
| 51604359 | John Doe | 5581995345775 | 27/08 13:17 SP |

Também excluídos: **5 estados do agente** (os 4 acima que geraram estado, mais o smoke
`5511999990013` / lead 51600526, que já não existe em `exact_leads`) e **1 reunião de teste**
(lead 51593541). Regra aplicada: nome casa `smoke | teste | test | john doe | fafaf | zz |
alefe | thobias justino`, **ou** telefone pertence ao operador ou ao SDR.

### A.2 Atribuição das mensagens

Conforme instruído, e **sem usar `sent_by_ai`** (que é `false` em toda a base):

| Regra | Ator |
|---|---|
| `nat_etapa` não-nulo | **IA** |
| `outbound` + `nat_etapa` nulo + `message_type != 'template'` | **Humano — dirigido** |
| `outbound` + `nat_etapa` nulo + `message_type = 'template'` | **Humano — disparo em massa** |

A separação por `message_type` foi conferida: os templates saem em lotes de 31 a 95 por dia,
com ~1 mensagem por contato e texto de campanha ("Ola {nome}, é o Thobias do CENAT…"),
enquanto os `text` são conversa. Disparo em massa **não conta como atendimento**.

### A.3 Atribuição das reuniões

| Condição | Classificação |
|---|---|
| `agendamentos.origem_ip IS NULL` + `passo='agendado'` | **IA (agente)** |
| `agendamentos.origem_ip` preenchido + `passo='agendado'` | **Landing page (auto-serviço)** |
| Entrou em `Agendados` sem linha correspondente em `agendamentos` | **Indeterminado** |

O agente é o único caminho sem IP de origem — ele agenda a partir da conversa, não de um
navegador. As 8 indeterminadas **não** foram creditadas ao SDR: 7 delas não têm nenhuma
mensagem dirigida que as explique (§4.2).

### A.4 Convenções de fuso (reconferidas nesta apuração)

| Campo | Fuso |
|---|---|
| `messages.timestamp`, `transferido_em`, `encerrado_em`, `nat_scheduled_actions.run_at` | **naive SP** |
| `created_at` (todas as tabelas), `exact_leads.register_date`, `exact_stage_events.observado_em` | **UTC** |

Confirmado em produção: o estado 70 tem `created_at` 27/08 12:00:51 UTC e a abertura
correspondente saiu às 09:00 SP. O corte de ativação é `2026-08-24 23:16:29` **UTC**
(= 20:16:29 SP) — a janela do enunciado está em UTC.

### A.5 Limitações da instrumentação

* **A telemetria de LLM só existe a partir de 27/08.** O `journalctl` guarda log desde março,
  mas a linha `🧠 LLM` foi instrumentada na sprint 4: são **33 turnos logados** (23 em 27/08,
  10 em 28/08) contra **71 turnos de conversa** contados no banco na janela inteira. As
  métricas de latência de modelo, tokens e falha de contrato **cobrem só 2 dos 5 dias** e por
  isso não entram no painel.
* **Ligações telefônicas não são visíveis.** É a causa provável das 8 reuniões indeterminadas.
* **`sent_by_ai` é inútil** — `false` em 100% das linhas, inclusive nas do agente.

---

## Anexo B — Queries

Janela padrão em todas: `INI_SP = 2026-08-24 20:16:29`, `FIM_SP = 2026-08-29 12:20:00`,
`INI_UTC = 2026-08-24 23:16:29`, `FIM_UTC = 2026-08-29 15:20:00`.

**B.1 — Leads novos da janela (base de 110 → 104)**
```sql
SELECT exact_id,name,phone1,sub_source,register_date,sdr_name
  FROM exact_leads WHERE register_date >= '2026-08-24 23:16:29'
                     AND register_date <= '2026-08-29 15:20:00';
```

**B.2 — Volume por ator, por dia**
```sql
SELECT date_trunc('day',timestamp)::date AS dia, direction,
       CASE WHEN nat_etapa IS NOT NULL THEN 'IA'
            WHEN message_type='template'  THEN 'humano-disparo'
            ELSE 'humano-dirigido' END AS ator, count(*)
  FROM messages
 WHERE timestamp >= '2026-08-24 20:16:29' AND timestamp <= '2026-08-29 12:20:00'
 GROUP BY 1,2,3 ORDER BY 1,2,3;
```

**B.3 — Velocidade: lead entra → primeiro contato.** Para cada lead de B.1, casar
`messages` por `variantes_wa_id(phone1)` (o mesmo módulo `app/telefone.py` que o agente usa,
por causa das duas grafias do telefone), tomar a primeira `nat_abertura_*` (IA) e o primeiro
`outbound` não-template (humano) com `timestamp >= register_date − 3h`.

**B.4 — Velocidade: pergunta → resposta.** Varre cada conversa em ordem; guarda o primeiro
`inbound` sem resposta; fecha no primeiro `outbound` que **não** seja abertura nem template;
classifica pelo `nat_etapa` desse outbound. Mesmo código para os dois atores.

**B.5 — Profundidade da IA**
```sql
SELECT count(*),
       count(*) FILTER (WHERE formacao IS NOT NULL),
       count(*) FILTER (WHERE formacao IS NOT NULL AND ano_conclusao IS NOT NULL),
       count(*) FILTER (WHERE formacao IS NOT NULL AND ano_conclusao IS NOT NULL
                          AND atuacao IS NOT NULL),
       count(*) FILTER (WHERE formacao IS NOT NULL AND ano_conclusao IS NOT NULL
                          AND atuacao IS NOT NULL AND motivacao IS NOT NULL)
  FROM nat_qualificacao_state;   -- menos os 5 de teste do §A.1
```

**B.6 — Reuniões da janela**
```sql
SELECT e.exact_lead_id, e.observado_em, l.name, l.sub_source, l.register_date
  FROM exact_stage_events e LEFT JOIN exact_leads l ON l.exact_id = e.exact_lead_id
 WHERE e.observado_em >= '2026-08-24 23:16:29' AND e.observado_em <= '2026-08-29 15:20:00'
   AND e.stage_para = 'Agendados' AND e.funnel_id = 18535;
```
Cruzada com `agendamentos` pelo `lead_id`, aplicando a regra de `origem_ip` do §A.3.

**B.7 — Conversas da IA cortadas pelo disparo**
```sql
SELECT s.contact_wa_id, s.transferido_em, s.transferido_motivo, s.etapa
  FROM nat_qualificacao_state s
 WHERE s.transferido_motivo LIKE 'outbound_manual_sdr%'
 ORDER BY s.transferido_em;
```
Para cada linha, procurar o `outbound` humano mais próximo de `transferido_em` (±600 s) e ler
o `message_type`: **41 template**, **1 text**, **1 sem correspondência** (varredura
retroativa).

**B.8 — Fila de perguntas sem resposta.** Mesma varredura de B.4; conta os `inbound` que
chegam ao fim da janela sem nenhum `outbound` dirigido depois. **73 casos.**

**B.9 — Aberturas que não saíram**
```sql
SELECT id, contact_wa_id, run_at, motivo FROM nat_scheduled_actions
 WHERE kind='iniciar_qualificacao' AND status='skipped'
   AND motivo LIKE '%não existe no banco%';
```

**B.10 — Falhas de entrega**
```sql
SELECT error_code, error_title, nat_etapa, count(*) FROM messages
 WHERE status='failed' AND timestamp >= '2026-08-24 20:16:29'
                       AND timestamp <= '2026-08-29 12:20:00'
 GROUP BY 1,2,3;
```

**B.11 — Verificação na API da Exact (somente leitura, 1 chamada)**
```
GET https://api.exactspotter.com/v3/Leads?$filter=id eq 51610927
 -> 200 | subSource: "Pos TEA V3" | source: "Landing Page"
```
Usada só para o §5.1, para confirmar que o `sub_source` errado do agendamento **não** chegou
ao CRM. Nenhuma escrita, nenhuma chamada em lote, dentro do limite de 30 req/20 s
compartilhado com o sync.

---

*Apuração de 29/08/2026, 12:20 SP. Somente leitura — nenhum dado de produção foi alterado.*
