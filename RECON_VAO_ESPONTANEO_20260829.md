# Recon — os 19 que ninguém tocou, e o vão do botão da página de obrigado

**Apuração:** 29/08/2026, 17:41 SP (20:41 UTC). **Somente leitura** — nenhum envio, nenhuma
escrita, nenhuma migração. Toda contagem tem a query no Anexo B.

**Janela:** `24/08 23:16:29 UTC` (= `qualificacao_start_at`, lido de `nat_config`) até agora.
O relatório de hoje de manhã fechou às 15:20 UTC; esta reabre até 20:41 UTC. **Não entrou um
único lead novo nessas 5h20** e nenhuma mensagem depois das 12:20 SP tocou qualquer pessoa
deste documento — as duas apurações medem a mesma população.

> **Leia o §0 e a §3.** O §0 diz o que os 19 são. A §3 é o número que decide o Bloco A.

---

## 0. O veredito curto

**Os 19 não são um buraco só; são três, e só um deles é bug.** Onze estão fora do escopo de
funil por configuração — dez são intercâmbio/congresso (funil 18285) e um é busca orgânica
(21007) —, cinco têm a abertura **enfileirada e adiada para segunda 09:00** porque se
candidataram na sexta à noite ou no sábado, e **três são vítimas de bugs que já foram
corrigidos e que ninguém reprocessou**.

**A hipótese do coordenador se confirma, e é maior do que os 19.** Desde a ativação,
**38 pessoas** escreveram primeiro pelo botão da página de obrigado. Com o espontâneo
desligado, **12 delas não receberam uma única palavra de ninguém** — espera mediana de
**18,5 h**, a pior de **106 h**. E **7 dessas 12 não existem em `exact_leads`**: nenhum
gatilho vai nascer para elas nunca, por nenhum caminho. **Só o Bloco A alcança essas sete.**

**A leitura honesta é pior que os 12.** Das 38, apenas **10** receberam algo que fosse
resposta ao que escreveram (conversa do agente ou mensagem humana digitada). Outras **8**
foram alcançadas só pelo disparo em massa — template genérico, entre 1,5 h e 63,6 h depois —
e **14** receberam apenas a **abertura** do agente, que é roteiro business-initiated
disparado pelo gatilho do formulário: coincidência de calendário, não resposta.

---

## 1. Os 19, nominalmente

Reproduzidos com o mesmo critério do relatório da manhã (`§2`): lead real da janela sem
**nenhum** `outbound` casado por variantes de telefone — nem abertura da IA, nem mensagem
dirigida do SDR, nem disparo em massa. **110 leads na janela → 6 de teste → 104 reais → 19
sem contato.** A contagem bate exatamente com a das 12:20.

| # | exact_id | Nome | Telefone | sub_source | register_date (UTC) | SDR | Categoria |
|---|---|---|---|---|---|---|---|
| 1 | 51537537 | ISABELA GUARINO GESTO NODAR | 5511983602996 | Pos Grupos e Oficinas T2 | 25/08 10:41 | Thobias | **BUG — sync abortado** |
| 2 | 51547368 | Josiqueila Martins novais Oliveira | 5591985119613 | Pos Psicologia Clinica T2 | 25/08 17:42 | Thobias | **BUG — contato inexistente** |
| 3 | 51549969 | Adriana Araújo | 5511961866951 | *(vazio)* — Busca Orgânica | 25/08 19:41 | Thobias | Funil 21007 fora do escopo |
| 4 | 51550515 | Francisca Helena Nunes | 5515997952032 | interuruguai2026 | 25/08 20:44 | Thobias | Funil 18285 fora do escopo |
| 5 | 51555807 | Flavia | 5553999932945 | interuruguai2026 | 25/08 23:26 | Thobias | Funil 18285 fora do escopo |
| 6 | 51571464 | Ana Meireles | 5524999561150 | interuruguai2026 | 26/08 14:20 | Thobias | Funil 18285 fora do escopo |
| 7 | 51588082 | Milena Marques Freitas | 5555936195192 | interuruguai2026 | 26/08 22:16 | Thobias | Funil 18285 fora do escopo |
| 8 | 51591647 | Karla Morgana de Barros Ferreira | 5581998155222 | interuruguai2026 | 27/08 02:08 | Thobias | Funil 18285 fora do escopo |
| 9 | 51597057 | Soraya do vale Oliveira | 5581984746535 | interuruguai2026 | 27/08 10:41 | Thobias | Funil 18285 fora do escopo |
| 10 | 51600703 | Natália Santos Marçola | 5532991008314 | intercambioportugal2026 | 27/08 13:18 | Thobias | Funil 18285 fora do escopo |
| 11 | 51610928 | Fernanda Santos Vargas | 5549999333881 | Pos Gestao Psicossocial T5 | 27/08 21:01 | Thobias | **BUG — grafia do telefone** |
| 12 | 51624198 | Elisabete Braga | `5555719999822` ⚠️ | interuruguai2026 | 28/08 11:48 | Thobias | Funil 18285 + **telefone inválido** |
| 13 | 51636330 | Jacqueline Borges | 5522998469680 | PosMulheridades | 28/08 23:26 | Thobias | Adiado p/ segunda 09:00 |
| 14 | 51636347 | Luciana Maria da Silva | 5511913755158 | PosMulheridades | 28/08 23:34 | Thobias | Adiado p/ segunda 09:00 |
| 15 | 51636363 | Lucinete Vencioneck | 5568999382215 | interuruguai2026 | 28/08 23:41 | Thobias | Funil 18285 fora do escopo |
| 16 | 51636706 | Amélia Mayara Frota Ribeiro | 5588997401800 | interuruguai2026 | 29/08 01:55 | Thobias | Funil 18285 fora do escopo |
| 17 | 51639262 | Clovis Palafoz dos Santos | 5531997571939 | Pos Grupos e Oficinas T2 | 29/08 03:37 | Thobias | Adiado p/ segunda 09:00 |
| 18 | 51642327 | DENILRA MENDES FERREIRA | 5598985820874 | Pos TEA V3 | 29/08 11:57 | Thobias | Adiado p/ segunda 09:00 |
| 19 | 51642589 | Ana Paula Justino | 5534996437181 | Pos Suicidio e Luto T3 | 29/08 14:10 | Thobias | Adiado p/ segunda 09:00 |

`sdr_name` é **Thobias em todos os 19** — não há dispersão de responsável para explicar nada.

### 1.1 Categoria A — funil fora do escopo (11 leads): legítimo, mas nunca carimbado

`auto_welcome_config.funnel_ids = 18535,18537,25588`. Estes 11 nasceram em **18285**
(intercâmbio/congresso, 10 leads) e **21007** (busca orgânica, 1 lead).

O filtro que os barra **não é** o guardrail documentado do passo 2 de
`send_welcome_to_new_lead`. É um **pré-filtro anterior**, em `app/exact_spotter.py:548`:

```python
if lead_data.get("funnel_id") in funnels:
    new_leads_to_contact.append(lead_data)
```

Quem não passa aqui **nunca chega** a `send_welcome_to_new_lead` e por isso **nunca é
carimbado**: `welcome_status` fica `NULL`, indistinguível de quem foi perdido por bug. Os 11
têm `welcome_status` vazio no banco — conferido.

É a decisão de produto que está pendente desde `AUDITORIA_NAT_20260725`: **a admissão do
lead de intercâmbio/congresso nunca foi decidida.** O agente não sabe falar de "Visita de
Estudos em Trieste 2026"; abrir com o roteiro de pós seria pior que o silêncio. Mas **10 de
104 leads da janela (9,6%)** entram e ninguém decide nada sobre eles.

**⚠️ Telefone inválido — 51624198, Elisabete Braga.** `5555719999822` tem 13 dígitos, mas o
número local (`719999822`) começa em **7**, não em 9. `variantes_wa_id` devolve só a forma
crua, sem variante. É um telefone que não existe: mesmo que o funil entrasse no escopo, o
envio falharia. **Precisa de correção no cadastro, não de contato.**

### 1.2 Categoria B — abertura adiada para segunda 09:00 (5 leads): o sistema funcionando

`qualificacao_fluxo.py:1008-1009` adia a abertura para fora de **09h00–18h30, seg–sex**. Os
cinco se candidataram sexta 20:31/20:39, ou sábado 00:42 / 09:04 / 11:17 — e o sábado inteiro
é fora da janela. As ações estão **`pendente` com `run_at = 2026-08-31 09:00`**, não perdidas:

| Lead | Ação | Enfileirada | run_at | Reunião marcada |
|---|---|---|---|---|
| 51636330 Jacqueline | 422 | 28/08 20:39 | **31/08 09:00** | 31/08 14:15 |
| 51636347 Luciana | 425 | 28/08 21:00 | **31/08 09:00** | 31/08 17:15 |
| 51639262 Clovis | 428 | 29/08 00:52 | **31/08 09:00** | *nenhuma* |
| 51642327 DENILRA | 434 | 29/08 09:11 | **31/08 09:00** | 01/09 15:45 |
| 51642589 Ana Paula | 438 | 29/08 11:17 | **31/08 09:00** | 31/08 12:00 |

**Legítimo pelo desenho — e mesmo assim são dois problemas.** Primeiro: quatro dos cinco
**já marcaram reunião** e a mensagem que os espera é a `nat_abertura_agendado`, que confirma
o horário. Confirmar com 2 dias de atraso um agendamento feito agora não é business-initiated
coisa nenhuma. Segundo, e mais grave: **Clovis e Ana Paula escreveram** — 00:39 e 11:10 de
hoje — e a janela de 24 h deles está **aberta**. Responder a quem perguntou não custa
qualidade de número nenhuma; é exatamente a distinção que o P1-B já fez em
`qualificacao_guard.py` para o teto por hora, e que a regra de horário comercial ainda não
faz.

### 1.3 Categoria C — os 3 bugs, todos já corrigidos, nenhum reprocessado

| Lead | O que aconteceu | Carimbo | Onde foi consertado |
|---|---|---|---|
| **51537537 ISABELA** | O sync morreu com `local variable 'timedelta' referenced before assignment` às **25/08 10:52:35 UTC**, 52 s depois de ela ser ingerida. O laço abortou na primeira iteração e todos do lote ficaram `existing` na passada seguinte. | `welcome_status` **NULL** | savepoint `async with db.begin_nested()` — `exact_spotter.py:578` |
| **51547368 Josiqueila** | Ações 63 e 65 rodaram e o log diz `↩️ Agente: 5591985119613 não existe em contacts — abertura ignorada` (25/08 17:47:58 e 17:57:58 UTC). As duas foram gravadas como **`executado`** — a mesma marca de quem abriu a conversa. A ação 64 (lembrete da reunião de 28/08 09:00) morreu igual. | `skipped` = *"agente assumiu a abertura"* | `b428ae1` (S4-1, saídas mudas) + `_contato_ou_criar` |
| **51610928 Fernanda** | Ações 360 e 364, `skipped` com *"abertura não saiu: contato não existe no banco"*. O contato dela existe — como **`554999333881`** (12 dígitos, nascido do inbound de 11/08); a ação procurava **`5549999333881`** (13, vindo do lead). | `skipped` = *"agente assumiu (enfileirado)"* | `cd7507e`, hoje 11:03 UTC — **no ar desde 11:34 UTC** |

Os três **já compraram ou avançaram sozinhos**: ISABELA está em `Vendidos` (26/08), Fernanda
em `Contratos Gerados` (28/08), Josiqueila em `Agendados` com reunião em 28/08 09:00 — para a
qual **não recebeu nem abertura nem lembrete**. O funil andou apesar do agente, não por causa
dele. É a mesma leitura do relatório da manhã: **quem se serve sozinho na LP não é de
ninguém.**

**A ISABELA não está sozinha no carimbo NULL.** O crash de 25/08 deixou **6 leads no escopo
com `welcome_status IS NULL`** (todos entre 10:41 e 14:19 UTC daquele dia). Os outros 5
acabaram tocados pelo disparo em massa e por isso não aparecem nos 19 — mas nenhum dos 6 teve
abertura, e nenhum voltou:

`51537537 ISABELA` · `51542856 Bruna da Rosa Gonçalves` · `51542892 Bruna Rosa` ·
`51542913 Michelle Bittencourt Alves` · `51543599 Cibelle Ribeiro Ferrari` ·
`51543658 Andréa Corrêa`

---

## 2. O vão do botão — os 19, um a um

Para cada um dos 19, procurei **inbound nas duas grafias** (`variantes_wa_id`), e em
particular a mensagem-gatilho do botão.

| Grupo | N | Leads |
|---|---:|---|
| **(a) escreveu primeiro pelo botão, na janela, e caiu no vão** | **3** | 51537537 ISABELA · 51639262 Clovis · 51642589 Ana Paula |
| **(b) nunca escreveu e nunca recebeu — vão puro do gatilho** | **14** | Josiqueila + os 10 de intercâmbio + Jacqueline, Luciana, DENILRA |
| **(c) escreveu, mas fora da janela ou por outro texto** | **2** | 51549969 Adriana · 51610928 Fernanda |

**(a) — os três que escreveram e ninguém respondeu**

| Lead | Escreveu (SP) | O que escreveu | Espera até agora |
|---|---|---|---|
| ISABELA 51537537 | 25/08 07:43:43 | botão da T2 de *Grupos e Oficinas* — e 30 s depois: *"Também queria aproveitar a promoçao de agosto e entrar na de Saude Mental e Mulheridades"* | **106,0 h** |
| Clovis 51639262 | 29/08 00:39:12 | botão da T2 de *Grupos e Oficinas* | **17,0 h** |
| Ana Paula 51642589 | 29/08 11:10:50 | botão da T3 de *Autolesão, Comportamento suicida e Luto* | **6,5 h** |

O caso da ISABELA é o desenho inteiro do vão em dois minutos: agendamento `153` criado às
**07:41:58** com `passo='lead_criado'` (preencheu o formulário, **não** marcou horário) →
sem booking, o gatilho da LP não dispara → o gatilho do sync morreria 70 min depois no
`UnboundLocalError` → **07:43:43** ela clica no botão e escreve. Espontâneo desligado, agente
mudo. Ela **comprou assim mesmo**, 33 h depois. A segunda mensagem — o pedido de uma segunda
pós na promoção — está sem resposta há **106 horas**.

**(c) — as duas que não contam como (a), e por quê**

* **Adriana 51549969** escreveu o botão em **13/08** (antes da ativação) e, na janela,
  apenas *"Olá"* (25/08 15:02). Está no funil 21007, fora do escopo. Nunca respondida.
* **Fernanda 51610928** escreveu o botão em **11/08** e mais duas vezes em 12/08
  (*"Gostaria de fazer a pós 👆"*). O lead só nasceu em 27/08 — e a abertura morreu na
  grafia. É a mesma pessoa escrevendo há **18 dias** sem uma resposta.

---

## 3. O custo total do espontâneo desligado

### 3.1 O texto do botão, mapeado no banco

O botão gera duas famílias de mensagem, medidas em `messages.content` (normalizado sem
acento/caixa):

```
"Olá! Tudo bem? Fiz minha aplicação na turma <N> da [da] Pós-Graduação <curso> e gostaria de mais informações."
"Olá! Tudo bem? Manifestei interesse na visita de estudos em Trieste 2026 e gostaria de mais informações sobre..."
```

Entre as 38 mensagens da janela há **10 cursos distintos** e **5 formas de citar a turma**
(`na turma da`, `na turma 2 da`, `na turma 3 da`, `na turma 1 da da`, `na turma 3 da da` — o
*"da da"* é erro de template da LP, e está literal no banco). Por isso o casamento usa o
**prefixo** `ola! tudo bem? fiz minha aplicacao` / `ola! tudo bem? manifestei interesse`, que
é a única parte estável do texto.

### 3.2 O NÚMERO DA DECISÃO

> ## 38 pessoas escreveram primeiro pelo botão desde a ativação.
> ## 12 não receberam uma única palavra de ninguém.
> ## 7 dessas 12 não existem na Exact — nenhum gatilho vai nascer para elas.
>
> Espera mediana das 12: **18,5 h**. Mínima 6,3 h. **Máxima 106,0 h.**
> Espera mediana das 7 sem lead: **20,0 h**.

| Contato | Nome (contacts) | Escreveu (SP) | Curso pedido | Lead na Exact? | Recebeu algo depois? | Espera |
|---|---|---|---|---|---|---|
| 5511983602996 | Isa *(ISABELA)* | 25/08 07:43 | Grupos e Oficinas T2 | **51537537** | **não** | **106,0 h** |
| 558585011444 | Lú Mello | 25/08 22:09 | Grupos e Oficinas T2 | **NENHUM** | **não** | 91,5 h |
| 5521999790187 | Fabianne | 25/08 22:47 | Psicologia Escolar | 51504166 *(22/08)* | **não** | 90,9 h |
| 5524993348724 | Caroline Medeiros | 27/08 17:41 | Saúde Mental e Mulheridades | **NENHUM** | **não** | 48,0 h |
| 5511995151213 | Waldelice | 28/08 13:50 | SM, Direitos Humanos e Pop. Vulnerabilizadas | **NENHUM** | **não** | 27,8 h |
| 553399148399 | CLAUDIANNA GOMES | 28/08 21:44 | Grupos e Oficinas T2 | **NENHUM** | **não** | 20,0 h |
| 553197571939 | Clovis Palafoz | 29/08 00:39 | Grupos e Oficinas T2 | **51639262** | **não** | 17,0 h |
| 555199297391 | Josiane S. Alencastro | 29/08 02:20 | Psicologia Escolar | 31559736 *(12/02/25)* | **não** | 15,4 h |
| 554799555538 | Juliana | 29/08 09:04 | SM, Direitos Humanos e Pop. Vulnerabilizadas | **NENHUM** | **não** | 8,6 h |
| 553184149897 | Lucas | 29/08 10:13 | SM, Direitos Humanos e Pop. Vulnerabilizadas | **NENHUM** | **não** | 7,5 h |
| 553496437181 | Paulinha *(Ana Paula)* | 29/08 11:10 | Autolesão, Comp. suicida e Luto | **51642589** | **não** | 6,5 h |
| 558198081066 | Katia Cristina | 29/08 11:24 | Grupos e Oficinas T2 | **NENHUM** | **não** | 6,3 h |

**Sem lead na Exact: 7 de 12.** Conferido por `phone1` **e** `phone2`, casando pelos últimos
8 dígitos (imune ao 9º dígito e ao DDI) contra a base inteira de 9.244 leads: zero
resultados. Estas sete pessoas clicaram num botão nosso, escreveram para o nosso número e
**não têm registro em lugar nenhum do CRM**. Enquanto o Bloco A não subir, o único caminho
que existe para elas é alguém abrir o Hub e ler.

**Waldelice (5511995151213) é o caso que resume tudo:** escreveu **6 vezes** em dois dias.
Depois do botão veio *"Estou no Congresso hj e sei q tem desconto e garante mais uma vaga"* e,
na manhã seguinte, *"Bom dia!"* e *"Olá...."*. Nenhuma resposta. Ela estava no congresso, com
cartão na mão, e o sistema não tinha como saber que ela existia.

### 3.3 A leitura honesta das outras 26

Não basta contar quem recebeu **alguma** saída — é preciso contar quem recebeu **resposta**.

| O que a pessoa recebeu | N | % de 38 |
|---|---:|---:|
| **Nada** | **12** | 32% |
| **Só o disparo em massa** (template genérico, 1,5 h a 63,6 h depois) | **8** | 21% |
| **Só a abertura do agente** (roteiro do gatilho, não resposta ao que escreveu) | **14** | 37% |
| **Conversa do agente ou mensagem humana digitada** | **10** | 26% |

*(As duas últimas linhas se sobrepõem: das 26 alcançadas, 10 chegaram a uma resposta de
verdade — 6 por `qualif_conversa` do agente, e as demais por mensagem humana dirigida.)*

**Respondendo à pergunta do enunciado — quantos o disparo em massa acabou tocando:** **8 das
38**, e nenhum deles recebeu outra coisa. É "contato" no relatório de volume e não é resposta
nenhuma para quem perguntou por um curso específico: a pessoa escreveu *"fiz minha aplicação
na turma 2 de Grupos e Oficinas"* e recebeu *"Ola {nome}, é o Thobias do CENAT…"* até
**63,6 h** depois.

**O que o agente faz hoje quando a pessoa escreve primeiro:** nada. Os 14 que receberam a
abertura a receberam porque **também** preencheram o formulário — o gatilho nasceu do
`POST /lead` ou do sync, não da mensagem deles. Em 24 dos 38 casos o texto da pessoa não
produziu efeito nenhum no sistema.

---

## 4. Fechamento

### 4.1 Os 19, por categoria

| Categoria | N | É bug? |
|---|---:|---|
| Funil de intercâmbio/congresso (18285) fora do escopo | 10 | Não — decisão de produto pendente |
| Funil de busca orgânica (21007) fora do escopo | 1 | Não — decisão de produto pendente |
| Abertura enfileirada, adiada para segunda 09:00 (fora do horário comercial) | 5 | Não — mas ver §1.2 |
| Vítima de bug já corrigido, **nunca reprocessada** | 3 | **Sim** |
| **Total** | **19** | |

Dos 19, **1 tem telefone inválido** (51624198) e **3 escreveram e não foram respondidos**
(§2a). Nenhum dos 19 ficou de fora por teto de envios, por corte de data ou por
`espontaneo_enabled` — o corte de data não barrou ninguém desta janela.

### 4.2 O bug que continua aberto: **o carimbo mente e ninguém reconcilia**

Os três defeitos que produziram ISABELA, Josiqueila e Fernanda estão corrigidos. **O que não
existe é o caminho de volta**, e ele falta de um jeito específico.

**A mecânica.** `app/exact_spotter.py:266` carimba no momento em que a ação é **enfileirada**:

```python
stamp("skipped", f"agente de pré-qualificação assumiu a abertura ({motivo})")
```

O comentário logo acima é explícito sobre o risco — *"Carimbar 'o agente assumiu' em cima de
um gatilho que NÃO enfileirou fecha a porta do lead pelos dois lados"* — e por isso trata o
caso de `agendar_abertura` devolver `False`. **Mas a abertura pode falhar depois disso**, na
execução da ação, 5 minutos ou 2 dias mais tarde. Quando falha, ninguém volta no carimbo.

O resultado é um lead em estado terminal por todos os lados:

| | ISABELA | Josiqueila | Fernanda |
|---|---|---|---|
| `welcome_status` | `NULL` | `skipped` *("assumiu")* | `skipped` *("assumiu (enfileirado)")* |
| ação | *(nunca criada)* | `executado` ×2 | `skipped` ×2 |
| estado do agente | nenhum | nenhum | nenhum |
| volta pelo sync? | não (`existing`) | não (`existing`) | não (`existing`) |
| volta pelo `reprocessar_leads_perdidos.py`? | **sim** | **não** | **não** |

`reprocessar_leads_perdidos.py:163` seleciona **só** `welcome_status IS NULL`:

```python
.where(ExactLead.welcome_status.is_(None),
```

Ele cobre exatamente **uma** das três formas de perda — a da ISABELA — e mesmo essa continua
por rodar: **os 6 leads NULL de 25/08 ainda estão NULL** (o script tem `--executar` e nunca
foi executado). Josiqueila e Fernanda estão **carimbadas**, e por isso são invisíveis também
para ele.

O `monitor_qualificacao.py:103` (§2b) pega a assinatura da Josiqueila — `executado` sem
estado —, mas só dentro da sua janela recente, e **não** pega a da Fernanda (`skipped`) nem a
carimbada-sem-ação.

**Proposta (não implementada).**

1. **Varredura de reconciliação**, irmã do `reprocessar_leads_perdidos.py`, com o critério
   que falta: `register_date >= qualificacao_start_at` **E** `welcome_status = 'skipped'`
   **E** `welcome_error LIKE '%assumiu a abertura%'` **E** sem linha em
   `nat_qualificacao_state` (por `variantes_wa_id`) **E** sem `messages` com
   `nat_etapa IN (nat_abertura_*)` **E** sem ação `pendente`. Reenfileira com o mesmo
   espaçamento por teto que o script atual já implementa, e recarimba o `welcome_error` para
   não repetir amanhã.

   > **⚠️ CORREÇÃO — 29/08, 18h50.** Esta linha dizia *"hoje isso devolveria Josiqueila e
   > Fernanda, e mais ninguém — verificado"*. **Estava errado, e o "verificado" era falso:**
   > eu inferi o resultado a partir dos 19 do §1 em vez de rodar a varredura. Ela foi
   > escrita e rodada em seguida, e devolve **7 leads**, não 2 — os outros 5 não estão nos 19
   > porque receberam o disparo em massa do SDR, que é `outbound` e os tira daquele
   > critério, sem nunca terem recebido abertura nenhuma. A lista dos 7 e a proposta de
   > triagem estão no **§5**.
2. **Rodar `reprocessar_leads_perdidos.py --executar`** para os 6 NULL de 25/08. É o caminho
   que já existe e já é idempotente; falta só executá-lo.
3. **Adiar sem carimbar como concluído:** quando a ação termina em `skipped`, o
   `welcome_error` do lead deveria ser reescrito com o motivo real da falha em vez de
   continuar dizendo *"o agente assumiu"*. Sem isso, qualquer relatório futuro vai contar
   esses leads como atendidos. — ✅ **FEITO em 29/08**, commit `52ba266`, estendido também ao
   desfecho `falhou`. Ver `SPRINT_CARIMBO_DESMENTIDO_20260829.md`. Vale para o **próximo**
   caso; os 7 que já estão carimbados dependem do item 1.
4. **Latente, sem caso medido — 📌 BACKLOG, com gatilho definido:** o pré-filtro de
   `exact_spotter.py:548` não carimba, então um lead que **nasça** fora dos funis do escopo e
   **migre** para dentro nunca vira candidato a abertura — ele já é `existing`. Hoje isso é
   zero (`0` migrações de fora para dentro em toda a base), e por isso **não** é trabalho
   agora.

   > **O gatilho que torna isto obrigatório: o dia em que o intercâmbio (funil 18285) entrar
   > no escopo de `auto_welcome_config.funnel_ids`.** Nesse dia, os leads de intercâmbio já
   > ingeridos ficam permanentemente invisíveis — são `existing`, nunca voltam a
   > `new_leads_to_contact`, e o `welcome_status` NULL deles não distingue "fora do escopo"
   > de "perdido por falha". São 10 pessoas só nesta janela. **Quem for mexer em
   > `funnel_ids` precisa ler este item antes.**

### 4.3 Sobre o horário comercial — não é bug, é regra a rever

`qualificacao_fluxo.py:1008` adia **toda** abertura para 09h00–18h30 seg–sex. A justificativa
está certa para business-initiated. **Ela não deveria valer para quem acabou de escrever:**
Clovis e Ana Paula estão com a janela de 24 h aberta, perguntaram por um curso, e a resposta
está agendada para segunda. É a mesma distinção que o P1-B já aplicou ao teto por hora —
`qualificacao_guard.py`, *"CONVERSA = user-initiated. A pessoa ACABOU DE ESCREVER e está
esperando"*. **Se o Bloco A subir, essa regra precisa subir junto**, ou o espontâneo nasce
mudo aos sábados — que é exatamente quando metade destes casos aconteceu.

### 4.4 Lista para o time — vale contato humano HOJE

Todos os 19 leads têm **4,4 dias ou menos**. Mas a urgência não é igual, e a lista abaixo está
ordenada por ela.

**🔴 PRIORIDADE 1 — escreveram e estão esperando resposta agora (12 pessoas)**
São as 12 da tabela §3.2. Sete delas **não estão no CRM**: só existem no Hub.

| Contato | Nome | Curso que pediu | Esperando há |
|---|---|---|---|
| 5511983602996 | Isa (ISABELA) — *já é `Vendidos`; pendente é a **2ª** pós na promoção* | Saúde Mental e Mulheridades | 106,0 h |
| 558585011444 | Lú Mello — **sem lead** | Grupos e Oficinas T2 | 91,5 h |
| 5521999790187 | Fabianne | Psicologia Escolar | 90,9 h |
| 5524993348724 | Caroline Medeiros — **sem lead** | Saúde Mental e Mulheridades | 48,0 h |
| 5511995151213 | Waldelice — **sem lead**, escreveu 6×, estava no congresso | SM, Direitos Humanos e Pop. Vulner. | 27,8 h |
| 553399148399 | Claudianna Gomes — **sem lead** | Grupos e Oficinas T2 | 20,0 h |
| 553197571939 | Clovis Palafoz | Grupos e Oficinas T2 | 17,0 h |
| 555199297391 | Josiane S. Alencastro | Psicologia Escolar | 15,4 h |
| 554799555538 | Juliana — **sem lead** | SM, Direitos Humanos e Pop. Vulner. | 8,6 h |
| 553184149897 | Lucas — **sem lead** | SM, Direitos Humanos e Pop. Vulner. | 7,5 h |
| 553496437181 | Paulinha (Ana Paula) | Autolesão, Comp. suicida e Luto | 6,5 h |
| 558198081066 | Katia Cristina — **sem lead** | Grupos e Oficinas T2 | 6,3 h |

**🟠 PRIORIDADE 2 — vítimas de bug, nunca contatadas (2 pessoas)**

| Lead | Nome | Telefone | Por que agora |
|---|---|---|---|
| 51547368 | Josiqueila Martins novais Oliveira | 5591985119613 | Reunião marcada para **28/08 09:00** — sem abertura e **sem lembrete**. Ninguém sabe se ela apareceu. |
| 51610928 | Fernanda Santos Vargas | 5549999333881 *(thread em `554999333881`)* | Escreveu em **11 e 12/08**, nunca respondida; já está em `Contratos Gerados`. |

**🟡 PRIORIDADE 3 — o agente vai abrir segunda 09:00; contato humano é opcional (3 pessoas)**
51636330 Jacqueline (reunião 31/08 14:15) · 51636347 Luciana (31/08 17:15) ·
51642327 DENILRA (01/09 15:45). *Clovis e Ana Paula, também deste grupo, já estão na
Prioridade 1 porque escreveram.*

**⚪ NÃO CONTATAR SEM DECISÃO — 11 leads fora do escopo**
Os 10 de intercâmbio/congresso (18285) e Adriana Araújo (21007). O agente não tem roteiro
para o produto deles. **51624198 Elisabete Braga tem telefone inválido** (`5555719999822`) —
corrigir o cadastro antes de qualquer tentativa.

**⚪ SEM AÇÃO DE VENDA — 51537537 ISABELA** já está em `Vendidos`; o contato dela é a
Prioridade 1 por causa da segunda pós, não do funil.

**Fora dos 19, mas do mesmo crash:** `51542856 Bruna da Rosa Gonçalves`,
`51542892 Bruna Rosa`, `51542913 Michelle Bittencourt Alves`,
`51543599 Cibelle Ribeiro Ferrari`, `51543658 Andréa Corrêa` — nunca tiveram abertura,
só o disparo em massa.

### 4.5 Divergências com o relatório das 12:20

Nenhuma. Mesma base de 110 → 104, os mesmos 19, mesmo com a janela estendida de 15:20 para
20:41 UTC. **Zero leads novos e zero mensagens relevantes nesse intervalo** — a única
atividade posterior às 12:20 foi um atendimento humano ao contato `555591696252`, que
começa com *"conforme nos falamos por ligação a pouco"* e reforça a leitura do §4.2 daquele
relatório sobre as reuniões indeterminadas virem do telefone.

---

## 5. Reconciliação — o dry-run dos dois caminhos (29/08, 18h50)

Autorizado o levantamento, **não a execução**. Os dois caminhos foram simulados; nada foi
escrito, nada foi enfileirado.

### 5.1 `reprocessar_leads_perdidos.py` — 🛑 **NÃO rodar como está**

O dry-run enfileiraria **11 leads**. E os 11 estão **todos fora do escopo de funil**: os 10 de
intercâmbio/congresso (18285) e a Adriana Araújo (21007). **Nenhum dos 6 leads NULL no escopo
entra** — os 6 já estavam na triagem manual do próprio script (`EXCLUIDOS`, ISABELA entre
eles) ou são duplicata de telefone.

**O número correto de leads que este script deveria enfileirar hoje é ZERO.**

O motivo é uma assimetria entre os dois filtros: `perdidos()` seleciona por
`welcome_status IS NULL` **sem olhar funil**, e a admissão
(`qualificacao_pode_iniciar`) **também não checa funil** — ela checa chave, corte de data,
referência e teto. O guardrail de funil só existe em `send_welcome_to_new_lead` e no
pré-filtro da linha 548, e o backfill passa por fora dos dois.

**O que sairia, se rodasse.** `interuruguai2026` não tem linha em `course_aliases`, então
`resolve_course_name` cai no fallback (o nome só perde o prefixo `pos`, que ali nem existe) e
o `{{2}}` do template recebe a string crua:

> *"Olá, Francisca! Que bom te ver por aqui ✨ Vi que você se interessou pela nossa
> **Pós-Graduação em interuruguai2026**. Antes de te mostrar os próximos passos, gostaria de
> conhecer um pouco da sua trajetória. Me conta: qual é a sua formação?"*

Para 10 pessoas que se inscreveram numa **visita de estudos ao Uruguai**. Mais a Elisabete
Braga, cujo telefone (`5555719999822`) é inválido.

**Proposta:** não rodar. Antes de qualquer `--executar`, o script precisa de um filtro de
funil — `ExactLead.funnel_id.in_(funis_do_config)` no `perdidos()` — e aí ele passa a
devolver zero, que é a resposta certa. Enquanto isso, os 6 NULL no escopo continuam cobertos
pela triagem manual que já existe.

### 5.2 A varredura irmã — **7 leads**, e a lista para você aprovar

Critério do §4.2 item 1, rodado em simulação. Nenhum dos 7 recebeu **uma única mensagem
humana digitada** — só disparo em massa, quando recebeu algo.

| # | Lead | Nome | Stage | Desfecho real da ação | Escreveu? |
|---|---|---|---|---|---|
| 1 | 51544018 | Adriana Palhana Moreira | Follow 3 | `61:executado` (saída muda) | não |
| 2 | 51547368 | Josiqueila Martins novais Oliveira | **Agendados** | `63,65:executado` (saída muda) | não |
| 3 | 51548796 | Elidilza da Costa Nunes | Follow 3 | `73:executado` (saída muda) | **sim, 25/08** |
| 4 | 51610928 | Fernanda Santos Vargas | **Contratos Gerados** | `360,364:skipped` (grafia) | **sim, 11-12/08** |
| 5 | 51613664 | Claudia Maria Farias Costa | Follow 2 | `378:skipped` (grafia) | **sim, 27/08** |
| 6 | 51616982 | Sandra Maria Diell Graf | Follow 2 | `380:skipped` (grafia) | **sim, 27/08** |
| 7 | 51625094 | Dyenifer Luana Garbin | Follow 2 | `410:skipped` (grafia) | **sim, 28/08** |

Os 4 da grafia são **exatamente** as 4 pessoas que o commit `cd7507e` nomeia no próprio
comentário de código (*"MEDIDO em 27-28/08: 6 ações, 4 pessoas"*). O conserto entrou; a
recuperação delas, não.

### 5.3 Proposta de EXCLUÍDOS — 6 dos 7

**Você estava certo sobre os três casos que citou, e a razão vale para mais gente.** A
abertura do agente é um roteiro de qualificação (*"qual é a sua formação?"*). Mandá-la para
quem já avançou no funil é regressivo; mandá-la para quem **fez uma pergunta específica** não
é resposta — é mudar de assunto.

| Lead | Proposta | Por quê |
|---|---|---|
| 51547368 Josiqueila | 🛑 **EXCLUIR** | `Agendados`, reunião era **28/08 09:00** — já passou. A abertura confirmaria um horário no passado. **Caso de SDR: descobrir se ela compareceu.** |
| 51610928 Fernanda | 🛑 **EXCLUIR** | `Contratos Gerados`. Qualificar quem já está fechando é andar para trás. **Caso de SDR.** |
| 51548796 Elidilza | 🛑 **EXCLUIR** | Escreveu em 25/08 e espera há 4 dias. **Resposta humana, não abertura.** *(E o `sub_source` do lead — `Pos Saude do Trabalhador` — não bate com o curso que ela citou no botão: `Boas Práticas em Saúde Mental nas Organizações`. Conferir antes de falar com ela.)* |
| 51613664 Claudia | 🛑 **EXCLUIR** | Escreveu 27/08, recebeu 2 templates de massa. **Resposta humana.** |
| 51616982 Sandra Diell | 🛑 **EXCLUIR** | Escreveu 27/08, recebeu 1 template de massa. **Resposta humana.** |
| 51625094 Dyenifer | 🛑 **EXCLUIR** | Escreveu 28/08, recebeu 2 templates de massa. **Resposta humana.** |
| **51544018 Adriana Palhana** | ✅ **ÚNICA candidata** | **Zero inbound** — nunca escreveu, nada a responder. Follow 3, `PosPsicologiaEscolar`, curso resolve certo. É o caso puro: a abertura é exatamente o que deveria ter acontecido e não aconteceu. |

**Uma ressalva honesta sobre a única candidata:** a Adriana Palhana já recebeu **4 templates
de massa em 4 dias** e não respondeu a nenhum. A abertura seria a 5ª mensagem business-initiated
para alguém com zero engajamento — e é volume que a Meta pontua em qualidade. O argumento a
favor é que a abertura é a única mensagem **personalizada** que ela receberia, e que o custo de
mídia dela já foi pago. **É uma decisão de 1 lead; eu não a tomo sozinho.**

**Ou seja: se a proposta for aceita inteira, a varredura enfileira 1 lead — ou nenhum.** O
valor dela não está no volume de hoje; está em **enxergar** os 7, que até esta manhã eram
invisíveis para todos os caminhos. Os 6 excluídos entram na lista de contato humano do §4.4
como **Prioridade 2**, junto com Josiqueila e Fernanda.

### 5.4 Estado dos scripts

* `reprocessar_leads_perdidos.py` — **existe no repo**, dry-run rodado, `--executar`
  **não** rodado. Precisa do filtro de funil antes de qualquer execução.
* A varredura irmã — **escrita e rodada em simulação**, ainda **fora do repositório**. Ela
  não tem caminho `--executar`: levantar a lista é read-only e não precisa de autorização;
  enfileirar precisa, e a triagem é humana. **Commito quando a lista do §5.3 for aprovada.**

---

## Anexo A — Convenções e critérios

* **Fusos.** `messages.timestamp`, `run_at`, `transferido_em`, `encerrado_em` → **naive SP**.
  `created_at`, `register_date`, `observado_em`, journald → **UTC**. Corte de ativação lido do
  banco: `nat_config.qualificacao_start_at = 2026-08-24 23:16:29.709119` **UTC**.
* **Telefone.** Todo casamento por `app/telefone.py`: `variantes_wa_id` para buscar mensagens
  e ações, `chave_telefone` (DDD + últimos 8) para casar conjuntos lead↔thread. Nunca por
  igualdade — 5 dos 19 têm a thread gravada na grafia oposta à do lead.
* **Atribuição.** `nat_etapa` não-nulo = IA; `outbound` + `nat_etapa` nulo +
  `message_type='template'` = disparo em massa; `outbound` + `nat_etapa` nulo + outro tipo =
  humano dirigido. `sent_by_ai` não usado (`false` em toda a base).
* **Leads de teste.** Os mesmos 6 do `RELATORIO_IA_VS_HUMANO_20260829` §A.1, reproduzidos
  pela mesma regra de nome e telefone.
* **"Sem nenhum contato".** Zero `outbound` casado por variantes — critério idêntico ao §2
  daquele relatório, que devolve os mesmos 19.

## Anexo B — Queries

**B.1 — Os 104 e os 19.** `exact_leads` com `register_date >= '2026-08-24 23:16:29'` (110),
menos os 6 de teste; para cada um, `messages` por `chave_telefone(phone1)`; fica quem não tem
nenhum `direction='outbound'`.

**B.2 — Por que cada um não recebeu abertura**
```sql
SELECT l.exact_id, l.name, l.phone1, l.sub_source, l.funnel_id, l.register_date,
       l.welcome_status, l.welcome_error
  FROM exact_leads l WHERE l.exact_id IN (…os 19…);

SELECT id, kind, contact_wa_id, run_at, status, motivo, payload
  FROM nat_scheduled_actions WHERE contact_wa_id IN (…variantes…);
```

**B.3 — Funil de ingestão (não o atual)**
```sql
SELECT exact_lead_id, stage_para, funnel_id, observado_em
  FROM exact_stage_events WHERE stage_de IS NULL AND exact_lead_id IN (…os 19…);
```
→ 10 em 18285, 1 em 21007, 8 em 18535. `auto_welcome_config.funnel_ids = 18535,18537,25588`.

**B.4 — O crash de 25/08**
```
journalctl -u cenat-backend.service --since '2026-08-25 10:45' --until '2026-08-25 11:15'
  -> 10:52:35  ❌ Erro no sync Exact Spotter: local variable 'timedelta' referenced before assignment
journalctl -u cenat-backend.service --since '2026-08-25 17:40' --until '2026-08-25 18:05'
  -> 17:47:58  ↩️  Agente: 5591985119613 não existe em contacts — abertura ignorada
  -> 17:57:58  (idem)
```

**B.5 — Leads no escopo sem carimbo**
```sql
SELECT exact_id, name, phone1, sub_source, funnel_id, stage, register_date
  FROM exact_leads
 WHERE funnel_id IN (18535,18537,25588)
   AND register_date >= '2026-08-24 23:16:29' AND welcome_status IS NULL;   -- 6
```

**B.6 — A mensagem-gatilho do botão.** `messages` com `direction='inbound'` e
`timestamp >= '2026-08-24 20:16:29'`, cujo conteúdo normalizado (sem acento, minúsculo,
espaços colapsados) começa em `ola! tudo bem? fiz minha aplicacao` ou
`ola! tudo bem? manifestei interesse`. → **38 mensagens, 38 contatos distintos.** Para cada
contato, o primeiro `outbound` com `timestamp >=` o da mensagem, agrupado por variantes.

**B.7 — Quem tem lead na Exact.** Últimos 8 dígitos de `phone1` **e** de `phone2` contra os
9.244 leads da base — imune ao 9º dígito e ao DDI. **7 dos 12 não casam com nada.**

**B.8 — Conversa de verdade.** Dos 38, quem recebeu depois de escrever um `outbound` com
`nat_etapa='qualif_conversa'` (**6**) ou `nat_etapa IS NULL AND message_type <> 'template'`
(humano dirigido). **União: 10.**

**B.9 — Migração de funil de fora para dentro do escopo**
```sql
WITH nasc AS (SELECT DISTINCT ON (exact_lead_id) exact_lead_id, funnel_id AS f0
                FROM exact_stage_events WHERE stage_de IS NULL
               ORDER BY exact_lead_id, observado_em)
SELECT count(*) FROM nasc n JOIN exact_leads l ON l.exact_id = n.exact_lead_id
 WHERE n.f0 NOT IN (18535,18537,25588) AND l.funnel_id IN (18535,18537,25588);   -- 0
```

**B.10 — Estado do deploy.** `cd7507e` (grafia da abertura) commitado às **11:03:25 UTC** de
hoje; `cenat-backend.service` reiniciado às **11:34:10 UTC**. A correção está no ar — mas é
posterior a todos os casos deste documento.

---

*Recon de 29/08/2026, 17:41 SP. Somente leitura — nenhum dado de produção foi alterado,
nenhuma mensagem foi enviada, nenhuma ação foi reenfileirada.*
