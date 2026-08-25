# Agendamento pela Landing Page → Exact Spotter

Documentação consolidada do módulo `backend/app/agendamento/`. **Está em produção** desde
17/08/2026 (`cenat-backend.service`, `hub.cenatdata.online`).

Este arquivo é o ponto de entrada. Ele explica o que o módulo faz, **por que** faz assim, como
operá-lo e onde estão as armadilhas. As medições que sustentam cada decisão estão em
[`AGENDAMENTO_FINDINGS.md`](../AGENDAMENTO_FINDINGS.md) (§1–17) — citado aqui como "FINDINGS
§n". Os relatórios de cada sprint (`SPRINT_AGENDAMENTO_*.md`) guardam o histórico de execução.

> **Se você veio "corrigir o fuso horário": pare e leia a seção 2.4 antes.** É a única parte
> deste módulo que parece errada e está certa.

---

## 1. Visão geral

### O problema

A CENAT captava leads de pós-graduação por landing page e ligava depois. **A ligação do SDR
não era atendida** — número desconhecido, horário aleatório, pessoa no trabalho. O lead
entrava no CRM e morria em follow-up.

### A solução

A própria pessoa escolhe o horário, na hora, ainda quente: a LP passa a oferecer uma grade de
horários na página de obrigado, e o backend marca a reunião na agenda real da consultora
dentro da Exact Spotter. Quem escolheu o horário sabe que vai receber a ligação.

Quando não há horário disponível — feriado, agenda cheia, Exact fora do ar — a página cai no
"deixe seu contato" e o lead é cadastrado do mesmo jeito. **O visitante nunca fica preso.**

### O fluxo

```
┌── LP (Netlify) ──────────────┐        ┌── backend (FastAPI) ──┐      ┌── Exact Spotter ──┐
│                              │        │                       │      │                   │
│ index.html                   │        │                       │      │                   │
│  form nativo ────────────────┼─POST──▶│ /api/agendamento/lead │─────▶│ LeadsAdd          │
│   nome/email/telefone        │        │                       │      │  → lead em Entrada│
│   + origem + extras          │◀──────┤ {ok, lead_id}          │      │    funil 18535    │
│                              │        │                       │      │                   │
│  redirect                    │        │                       │      │                   │
│   obrigado.html?lead=ID      │        │                       │      │                   │
│      &nome=&email=&tel=      │        │                       │      │                   │
│                              │        │                       │      │                   │
│ obrigado.html                │        │                       │      │                   │
│  carrega a grade ────────────┼──GET──▶│ /slots                │─────▶│ GET /Boxes        │
│                              │◀───────┤ {dias, duracao_min}   │      │  (só p/ subtrair) │
│                              │        │                       │      │                   │
│  escolhe horário ────────────┼─POST──▶│ /agendar              │      │                   │
│   {slot, leadId, ...}        │        │   1. BoxesAdd ────────┼─────▶│ box "available"   │
│                              │        │      (É O LOCK)       │      │                   │
│                              │        │   2. lead: verifica   │─────▶│ GET /Leads id eq  │
│                              │        │      (ou LeadsAdd)    │      │                   │
│                              │        │   3. scheduleAdd ─────┼─────▶│ lead → Agendados  │
│                              │        │      (SEM VOLTA)      │      │ box → busy        │
│                              │◀───────┤ {ok, inicio, fim,     │      │ reunião criada    │
│  "confirmado"                │        │  consultora_nome}     │      │                   │
└──────────────────────────────┘        └───────────────────────┘      └───────────────────┘
```

**Duas etapas, um lead.** O `leadId` que viaja na URL é o que impede a pessoa de virar dois
leads no funil (um do formulário, outro do agendamento) e o SDR ligar duas vezes para o mesmo
número. Se o `POST /lead` falhar, o front redireciona **assim mesmo**, sem `lead=` — e o
`/agendar` cria o lead sozinho, no fluxo de uma etapa. Perder o contato na primeira tela é
definitivo; um lead duplicado, no pior caso, é incômodo.

Todo passo é gravado na tabela `agendamentos` **antes** da chamada externa correspondente. É a
única auditoria possível: a Exact não guarda tentativa que falhou.

### Mapa do módulo

| arquivo | responsabilidade |
|---|---|
| `routes.py` | os 3 endpoints públicos, rate limit por IP, validação de entrada |
| `agendar.py` | o fluxo box→lead→schedule, compensações, escolha de consultora, passo 4 |
| `grade.py` | quais horários existem, por consultora e dia da semana. Não consulta a Exact |
| `disponibilidade.py` | grade menos o ocupado. Cache de 60s. Só leitura |
| `consultoras.py` | quem atende, com a grade de cada uma. Validação em `/Sellers` |
| `origens.py` | allowlist de `subSource` + o `source`. Validação em `/Sources` |
| `horarios.py` | **a fronteira de fuso**. Único lugar do módulo que formata data |
| `client.py` | httpx contra a Exact; traduz os 400 conhecidos em exceções tipadas |
| `extras.py` | sanitização dos campos livres e montagem do `description` |
| `faxina.py` | job que devolve à agenda box nosso que ficou pendurado |
| `cors.py` | CORS por sufixo de domínio, só em `/api/agendamento/*` |

Fora do módulo: `app/models.py` (tabela `agendamentos`), `app/main.py` (router, jobs e
validações de startup), `docs/form-nativo-snippet.html` e `docs/obrigado-snippet.html`
(o front que a LP copia).

---

## 2. Decisões de arquitetura, e por quê

Esta é a seção que importa. Quase toda decisão aqui parece estranha até você saber o que a API
da Exact faz — e cada uma delas foi medida contra a API real antes de virar código.

### 2.1 A grade é nossa. A Exact não tem horários livres para listar

**O que se esperava:** perguntar à Exact quais horários a consultora tem livres e mostrar na LP.

**O que a API faz:** não existe esse endpoint. O que existe é `GET /Boxes`, que devolve *blocos*
de agenda — e o experimento controlado de FINDINGS §8 mostrou que eles são inúteis para nós:

- `scheduleAdd` **só aceita box com `status: "available"`**. Testado com o mesmo lead, mesmo
  rep, mesmo dia, variando só o status: `busy` → `400 Box is already occupied`; `available` →
  `201`.
- Os blocos recorrentes das consultoras são **`busy` com `leadId: 0`**. Ou seja, inacessíveis.
- Em **toda a base** existem 4 boxes `available`, e os quatro estão no passado.

**Conclusão:** não há slot da Exact para listar. O módulo **define a própria grade** e **cria o
próprio box** na hora de agendar. `GET /Boxes` entra só para *subtrair* o que já está ocupado —
e isso é cosmético, não é a trava (ver 2.2).

**Consequência operacional:** a grade precisa caber nas **lacunas** dos blocos recorrentes,
porque `BoxesAdd` recusa qualquer interseção com box existente do mesmo rep, independente do
status (FINDINGS §2). Quando a consultora mexe na agenda dela, a grade desencosta da realidade
e o agendamento começa a falhar com `Boxes are occupied`. Por isso a grade é **configuração**
(`consultoras.json`), não constante de código.

> `Boxes are occupied` frequente é **sinal operacional**, não só erro: quer dizer que a grade
> precisa ser revista contra os blocos reais.

### 2.2 `BoxesAdd` é o lock de concorrência

Duas propriedades medidas se encaixam:

- `BoxesAdd` recusa **qualquer** sobreposição com box existente do mesmo rep (FINDINGS §2).
- `scheduleAdd` recusa qualquer box que não seja `available` (FINDINGS §8).

Juntas: **quem consegue criar o box ganhou o horário.** Não existe janela de check-then-act, e
não precisamos de lock nosso para o horário. O `GET /Boxes` de `disponibilidade.py` é só para
não oferecer o que obviamente já era; quem decide é o `BoxesAdd`.

O que o `BoxesAdd` **não** protege é a mesma pessoa pegando dois horários diferentes em dois
cliques. Isso é uma trava nossa: `JANELA_DUPLO_CLIQUE` de 90 segundos por telefone, na tabela
local — e ela devolve o agendamento anterior em vez de criar um segundo, que é o que o
visitante espera ver.

### 2.3 A ordem box → lead → schedule, e a compensação de cada falha

```
1. BoxesAdd (status="available")   ← reversível, e é O LOCK
2. LeadsAdd (ou verificação, se veio leadId)
3. scheduleAdd                     ← PONTO DE NÃO RETORNO
```

**Por que o box vem primeiro:** é o único passo desfazível. `BoxesRemove` funciona enquanto o
box não tiver reunião. Na ordem inversa, um `BoxesAdd` que falhasse por conflito deixaria lead
órfão no CRM, e a única saída seria `LeadsDelete` — que é **exclusão dura** (o `LeadsRecover`
responde `Lead not found`) e cascateia para reunião e box (FINDINGS §6).

| falha | compensação | o que sobra |
|---|---|---|
| passo 1 (`Boxes are occupied`) | nada a desfazer; tenta a próxima consultora | nada |
| passo 1 (outro erro) | nada a desfazer; **para** o fluxo | nada |
| passo 2 | `BoxesRemove` | nada |
| passo 3 | `BoxesRemove`, **e o lead FICA** | lead em `Entrada` |
| passo 4 | nenhuma — é não-fatal por construção | agendamento intacto |

**O lead que fica não é sujeira.** É uma pessoa real que preencheu o formulário e quer falar
com a CENAT: ela aparece no funil e um SDR liga. O que se perdeu foi o horário, não o contato.
E quando o lead veio pronto (`leadId`), há uma razão a mais: **ele não é nosso** — foi criado
por outra requisição e apagá-lo destruiria o contato de alguém que nem chegou a escolher
horário. A coluna `lead_externo` grava essa distinção.

> **`LeadsDelete` nunca é compensação.** Está escrito no cabeçalho de `agendar.py` porque é a
> tentação óbvia de quem for mexer nisso depois.

Um erro no passo 1 que **não** seja disputa de horário (`SDR not found`, rede, 5xx) para o
fluxo em vez de tentar a próxima consultora: insistir transformaria um erro de configuração em
vários boxes criados por engano.

### 2.4 Datas em hora de parede de São Paulo — NUNCA UTC

**A premissa original do projeto dizia "datas ISO UTC". Está errada** (FINDINGS §1).

- Enviei `2026-08-19T11:00:00Z`; o `GET /Boxes` devolveu `2026-08-19T11:00:00Z`, verbatim.
- O **mesmo** horário aparece em `GET /Meetings` **sem o `Z`**: `2026-08-19T11:00:00.0000000`.
- Os blocos reais das consultoras são 09:00 / 13:30 / 15:00. Lidos como UTC seriam 06:00 /
  10:30 / 12:00 em São Paulo — uma agenda comercial começando às 6 da manhã.

**O `Z` é cosmético.** O campo é hora de parede. Converter para UTC de verdade
(`astimezone(timezone.utc)`) agenda a reunião **3 horas adiantada dentro do CRM**, sem erro em
lugar nenhum — o tipo de bug que só aparece quando o lead não atende a ligação, três semanas
depois, sem rastro.

Por isso a formatação vive em `horarios.py` e **nada mais no módulo chama `strftime`**:

```python
def para_exact(dt: datetime) -> str:
    return dt.astimezone(SP_TZ).strftime("%Y-%m-%dT%H:%M:%S") + "Z"   # o Z é MENTIRA
```

**A prova está no E2E** (FINDINGS §10, passo 4): a grade pediu 11:00 e a Exact gravou
`11:00:00Z`. O teste falha explicitamente com a mensagem `FUSO ERRADO` se algum dia alguém
"corrigir" isso.

⚠️ **Nem tudo na Exact é hora de parede.** `registerDate` e `updateDate` de lead são **UTC de
verdade** (lead criado 15:34 SP voltou como `18:34:22Z`). Campos de agenda: parede. Campos de
auditoria: UTC. Um único `datetime.utcnow()` usado nos dois lugares erra num deles.

Corolário do lado de cá: **nada neste projeto chama `date.today()` ou `datetime.now()` sem
fuso** — inclusive teste. Um E2E já falhou por isso: rodando 00:0x UTC, `date.today()` dava um
dia a mais que `agora_sp().date()` e a janela da grade saiu curta (FINDINGS §12).

### 2.5 `scheduleAdd` é irreversível → remarcação sai pelo WhatsApp

**Não existe `ScheduleRemove` nem `ScheduleUpdate`** no `$metadata` da API. Conferido no
inventário completo de endpoints (FINDINGS, apêndice).

Depois do passo 3 não há desfazer:

- A reunião existe e não sai pela API.
- O box fica preso: `BoxesRemove` responde `400 It is not possible to change a Box with a
  scheduled meeting`. **O que trava a remoção é a reunião, não o status** (FINDINGS §8).
- `LeadsDelete` "resolve" cascateando — e é exclusão dura, então não resolve nada.

**Decisão de produto:** remarcação e cancelamento saem pelo **WhatsApp**, fora da API. A
resposta do `/agendar` já diz isso ao visitante (`"Para remarcar ou cancelar, fale com a gente
pelo WhatsApp."`).

**O preço aceito:** cada remarcação queima um slot da agenda para sempre. A limpeza é manual,
na UI da Exact (ver runbook 3.3). Se a taxa de remarcação crescer, a agenda vaza slots ao
longo do tempo — vale monitorar.

Isso, que seria o pior problema do módulo, deixa de ser problema justamente porque a
remarcação não passa pela API.

### 2.6 A reunião fica no funil 18535 — e o passo 4 existe, mas está DESLIGADO

**Não é escolha nossa.** Duas tentativas, as duas recusadas (FINDINGS §14):

| tentativa | resultado |
|---|---|
| criar o lead direto no funil 18537 e agendar | `400 Previous stage is not exit action Scheduling` |
| lead no 18535, pedindo `stageName` do 18537 | `400 Stage not found` — o nome é resolvido **dentro** do funil do lead |

A causa é estrutural, e a posição da etapa explica tudo:

| funil | etapa `Agendados` | posição |
|---|---|---|
| 18535 `Pos Graduacao` | id 133409 | **14** (última) |
| 18537 `Pós Graduação - Vendas` | id 133413 | **1** (primeira) |

O `scheduleAdd` exige que a etapa **anterior** do lead tenha "Scheduling" como ação de saída.
No 18537 não existe etapa anterior — o portão de agendamento *é* a porta de entrada. Nenhum
lead daquele funil pode ser agendado pela API com essa configuração.

**Existe um caminho depois:** `POST /ChangeFunnel {leadId, stageId}` move o lead já agendado, e
o agendamento sobrevive inteiro — box segue `busy` e vinculado, reunião mantém id, data e
consultora (FINDINGS §15).

⚠️ **Mas cobra um preço:** o `type` da reunião passa de `Vigente` para **`Concluido`** no
instante da transferência, com a data ainda no futuro. Consta como realizada antes de
acontecer. Consequências: relatório de "reuniões realizadas" conta o que não aconteceu;
qualquer fluxo que dependa de `Vigente` (lembrete, formulário de qualidade) pula a reunião.

Por isso o passo 4 **nasceu desligado**: sem `AGENDAMENTO_FUNIL_DESTINO` no env, nada roda e o
lead fica no 18535 em `Agendados`. Ligar é decisão de produto, não de código — depende de a
equipe preferir o lead no funil certo com a reunião mal rotulada, ou o contrário.

Quando ligado, é **não-fatal por construção**: falha vira warning e o agendamento continua
válido. Uma transferência com problema não pode desfazer um horário que a pessoa já viu
confirmado na tela.

### 2.7 Duas consultoras: rodízio por carga, retry, grade comum

O módulo nasceu com `sales_rep_email` fixo em `comercial@` — que é a **pré-venda** (SDR). As
reuniões da LP são de **venda**, e vão para as consultoras. Sendo mais de uma, o horário deixa
de ser "livre ou ocupado" e passa a ser "livre **para quem**".

- **`/slots` mostra a união das grades.** Um horário aparece se ao menos uma consultora pode
  atendê-lo.
- **`/agendar` escolhe pela menor carga do dia**, contada na **nossa** tabela. Não na Exact, de
  propósito: a agenda da consultora tem compromisso pessoal, bloco de equipe e reunião de outro
  funil — distribuir por ela faria a LP evitar quem está cheia por motivos que não têm nada com
  a landing page. O que queremos equilibrar é **o que nós mandamos**. Empate mantém a ordem da
  configuração (sortear tornaria o log irreprodutível).
- **`Boxes are occupied` deixou de ser 409 imediato.** Agora significa "ocupada **para esta**
  consultora", e o fluxo tenta a próxima antes de desistir. Só quando todas recusam é que o
  visitante vê 409. Isso importa porque `disponibilidade` é cacheada por 60s: duas pessoas que
  abrem a página juntas veem a mesma oferta, e sem o retry a segunda tomaria 409 mesmo havendo
  consultora livre. **O `BoxesAdd` continua sendo o lock — agora são N locks independentes, um
  por agenda, e perder um não é perder o horário.**

**A grade deixou de ser desenhada à mão (25/08/2026).** Até então ela era recortada para caber
nas lacunas dos blocos recorrentes das duas (`10:30–12:00` + `15:45–18:00`, 5 horários/dia).
Hoje ela é o **horário comercial inteiro** — seg–sex `09:00–18:30`, passo de 45 min, 12
horários/dia (`09:00 … 17:15`; o rabo `18:00–18:30` é curto demais para um slot) — e quem
recorta a colisão é `disponibilidade`, por consultora e ao vivo.

O motivo é que janela desenhada à mão é uma **foto**: envelhece na primeira vez que a
consultora mexe na agenda, e envelhece em silêncio (`Boxes are occupied` no visitante). E com
duas agendas diferentes, a interseção das lacunas custava capacidade.

Medido contra os blocos reais lidos em 25/08/2026 (`GET /Boxes`, −45/+45 d):

| | grade recortada (até 24/08) | comercial inteiro (hoje) |
|---|---|---|
| horários/dia (teórico) | 5 | **12** |
| união/semana | 25 | **59** |
| capacidade | 47 vagas/sem | **88 vagas/sem** |
| com retry (as duas livres) | 22 (**88%**) | 29 (**49%**) |

**O que a colisão custa agora é retry, não erro.** Um horário em que só uma está livre continua
sendo oferecido — é a união — mas se o `BoxesAdd` dela recusar não há segunda tentativa. Um
único slot da semana some da união inteira: **segunda 15:00** (Amorim `15:00–15:45` e Rodrigues
`15:00–16:00` ao mesmo tempo).

Os buracos por colisão, por consultora:

| | slots que a colisão come |
|---|---|
| **Amorim** | `09:00` e `09:45` seg–qui (bloco 09:00–10:10) · `09:00` sex (08:00–09:10) · `13:30` e `14:15` todo dia (13:30–14:30) · `15:00` todo dia (15:00–15:45) · **terça `10:30` a `14:15` inteiros** (10:10–13:30) |
| **Rodrigues** | segunda `12:00` e `12:45` (12:00–13:30) · segunda `15:00` e `15:45` (15:00–16:00) |

Isso deixa a **terça** como o pior dia: 12 horários na união, mas só 3 com retry (25%) — a
Amorim tem a manhã inteira bloqueada. Sexta é o melhor: 8 dos 12 com retry (66%).

Janelas **idênticas** para as duas — não é preciso grade por dia da semana, porque o `/slots`
subtrai os blocos reais de cada uma ao vivo.

### 2.7.1 A janela é curta de propósito: hoje + D+1 + D+2

`AGENDAMENTO_JANELA_DIAS` conta **dias corridos de calendário, hoje incluído**. O horizonte de
14 dias morreu em 25/08/2026. Dentro de hoje, a antecedência mínima de 2h continua valendo.

Fim de semana não tem grade, e a janela **não se estica** para compensar:

| cadastro | dias úteis alcançados | slots ofertados |
|---|---|---|
| segunda 09h | seg, ter, qua | 32 |
| terça 09h | ter, qua, qui | 33 |
| quinta 09h | qui, sex | 21 |
| sexta 09h | sex | 9 |
| **sexta 15h** | sex | **1** (só o 17:15) |
| **sexta 15:15 em diante** | nenhum | **0 → `fallback:true`** |
| sábado | seg (D+2) | 11 |
| domingo | seg, ter | 23 |

⚠️ **O buraco conhecido:** de sexta 15:15 até a meia-noite de sábado (~9 h/semana) a janela não
alcança dia útil nenhum, o `/slots` volta vazio com `fallback:true` e a LP cai no "deixe seu
contato". É o degrade correto e já existia (feriado, agenda lotada, todas fora de rotação) — o
que mudou é que agora ele tem causa **previsível e semanal**. Com o horizonte de 14 dias isso
nunca acontecia. `AGENDAMENTO_JANELA_DIAS=4` fecha esse buraco (sexta passa a enxergar a
segunda) sem tocar em código; é uma linha do `.env` mais restart.

Contar dias corridos em vez de dias úteis é decisão: a promessa ao lead é "a gente fala com
você nos próximos dias", e uma janela que anda para trás no fim de semana faria a oferta de
sexta ser mais longa que a de segunda sem ninguém ter pedido.

**Não há calendário de feriados.** Feriado nacional dentro da janela é ofertado normalmente e o
box é criado — isso já era verdade com 14 dias, mas com 3 o efeito é maior: um feriado pode
consumir metade da oferta. Se virar problema recorrente, é sprint própria.

⚠️ **Um bug que já aconteceu aqui:** a subtração dos nossos agendamentos em voo era **global**,
escrita quando havia uma consultora só. Com duas, um horário reservado com a Amorim sumia
também da grade da Rodrigues, e a equipe rendia o mesmo que uma pessoa — perda silenciosa,
nenhum erro, metade da capacidade. Hoje a subtração é **por par horário+consultora**
(commit `0dba2e5`, caso 27 da suíte trava isso).

E a validação de startup **tira de rotação** a consultora que a Exact disser inativa ou
inexistente: um `salesRepEmail` inválido faria todo `BoxesAdd` falhar com `SDR not found` — a
**mesma** mensagem de um e-mail que nunca existiu, e só `GET /Sellers` separa os dois casos.

### 2.8 O source `Landing Page` foi criado via `LeadsAdd`, e a allowlist existe por isso

**`LeadsAdd` CRIA `source` e `subSource` que não existem.** Isso foi medido do jeito ruim: o
primeiro teste da investigação mandou `"DialogicasTurma"`, um nome inventado, e ele virou o
subSource **id 176793 — o id mais alto de toda a base**. Ficou lá depois que o lead de teste
foi excluído (FINDINGS §11).

> O valor voltar resolvido com um id **não** prova que o id já existia. §3 do findings afirmou
> o contrário e estava errado.

O cadastro de origens é **global e usado em relatório de marketing**. Um campo de texto livre
vindo de página pública significa que qualquer visitante — ou qualquer erro de digitação numa
LP nova — cria uma linha lá dentro, e ninguém percebe até o relatório sair torto.

Daí `origens.py`: **allowlist em env**, conferida antes de a chamada sair. O que não está na
lista é **400, e nada é criado**. A comparação é case-insensitive, mas o valor enviado é o da
allowlist com a **caixa exata** — mandar `posmulheridades` criaria um *segundo* cadastro com o
mesmo nome em caixa diferente, exatamente o problema que o módulo existe para evitar.

**A criação do source é permanente.** Não existe `SourcesAdd` nem `SourcesRemove` no
`$metadata` — o único jeito de criar origem é pelo `LeadsAdd`, usando de propósito o
comportamento que foi acidente em §11. Não há como desfazer: a limpeza é manual, pela UI.

Por isso existe a **validação de startup** (`origens.validar_contra_exact`), que confere source
+ allowlist inteira contra `GET /Sources` a cada boot. Ela nasceu de um incidente evitado em
18/08/2026: chegou um pedido para trocar a allowlist por 12 nomes legíveis e um source novo.
**Onze dos doze não existiam, e o source nenhum.** Aplicar aquilo teria feito o primeiro lead
de cada LP *criar* um cadastro paralelo ao que já existe (`PosPsicologiaEscolar`, 71 leads),
partindo o histórico de 2222 leads em dois nomes para os mesmos cursos — em silêncio, com 201
na resposta.

A validação **nunca levanta**: o backend serve o Hub, o webhook da Meta e a NAT, e não pode
cair porque o CRM respondeu estranho. Ela grita no log com o nome exato do que está errado.

### 2.9 E-mail e extras vão no `description` — o `LeadsAdd` não tem campo de e-mail

Não está no payload documentado, e `GET /Leads` não devolve nenhuma chave de e-mail (as de
contato são `phone1`, `phone2`, `telephones`). Na Exact o e-mail pertence à **pessoa**, não ao
lead — outra entidade (`LeadsAndPersons`), fora do escopo deste módulo. Mandar `"email"` no
payload seria **descartado em silêncio** e a LP perderia o dado que pediu ao visitante.

A saída: e-mail e extras entram no `description`, que é o texto que o SDR lê antes de ligar. Um
SDR que sabe que a pessoa é psicóloga e conheceu pelo Instagram liga diferente de quem só tem
nome e telefone. O dado estruturado fica em `agendamentos.extras` (JSONB, consultável por
`extras->>'Como conheceu'`).

⚠️ **O `description` tem teto de 8000 e a Exact TRUNCA EM SILÊNCIO** (FINDINGS §13):

```
enviado 200 / 4000 / 7999 / 8000  ->  guardado idêntico
enviado 8001                      ->  guardado 7999   (TRUNCADO)
enviado 10000                     ->  guardado 7999   (TRUNCADO)
```

**Nenhuma tentativa devolveu erro.** 201 na resposta, texto cortado no banco, nada em log.
Estourar por 1 caractere custa 2: 8001 vira 7999. Por isso `extras.py` trabalha com orçamento
próprio de **4000** e corta com marca visível (`…`). O pior caso real do formulário (e-mail +
10 extras cheios) dá ~2850 caracteres, então o orçamento nunca deveria ser atingido — ele
existe para o dia em que alguém afrouxar um limite de campo sem lembrar do teto do outro lado.

Os extras são **sanitizados** (o `|` do separador vira `/`, quebra de linha vira espaço,
controle some) mas **recusados** quando estouram contrato (>10 chaves, valor >200 chars → 422).
Recusar em vez de truncar vai contra o "visitante nunca fica preso" que rege o resto do módulo,
e é deliberado: extras alimentam relatório, um valor cortado pela metade é pior que uma
submissão recusada porque ninguém descobre. Quem controla o formulário somos nós.

### 2.10 CORS em middleware isolado, o mais externo da pilha, sem credenciais

**Por que não mexer no `CORSMiddleware` global do Hub:** ele vale para a aplicação inteira. Um
`allow_origin_regex` ali valeria também para `/api/messages`, `/api/nat/config` e todo o resto
— que roda com `allow_credentials=True` e responde a token. Afrouxar a origem dessas rotas para
"qualquer subdomínio `.netlify.app`" é exatamente o que não se quer: bastaria um site nesse
domínio para fazer o navegador de um usuário logado disparar requisição autenticada.

A LP precisa de origem larga porque o domínio dela muda (preview do Netlify gera um subdomínio
por deploy). O Hub não precisa de nada disso. **São políticas diferentes, então são middlewares
diferentes.**

**Por que precisa ser o mais externo:** o `CORSMiddleware` global **responde o preflight ele
mesmo** — origem fora da lista dele vira `400 Disallowed CORS origin` e a requisição nunca
chega ao router. Um sub-app montado com CORS próprio não resolveria. Como `add_middleware`
insere na posição 0 e a pilha é embrulhada em ordem reversa, **o último registrado é o mais
externo** — este é registrado *depois* do CORS do Hub, de propósito.

**O que ele não faz:** não manda `Access-Control-Allow-Credentials`. A LP é anônima e não envia
cookie nem token; permitir credenciais sobre uma faixa larga de origens seria juntar as duas
metades do problema que o arquivo existe para separar. Caminho que não casa com
`/api/agendamento` passa direto, sem tocar em header nenhum.

Sufixo de hospedagem compartilhada (`netlify.app`, `vercel.app`, `pages.dev`, …) libera **só
subdomínio**, nunca o ápice: `netlify.app` é da Netlify, não da CENAT. Para domínio próprio
vale o contrário — o ápice é o site principal. Sempre `https`.

### 2.11 A tabela `agendamentos` é a única auditoria possível

A Exact não guarda a tentativa que falhou: um fluxo que morre entre o `BoxesAdd` e o
`scheduleAdd` não deixa rastro nenhum lá. Sem a tabela local não há como responder "quantos
agendamentos ficaram pela metade ontem?", e o job de faxina não teria como saber **quais boxes
são nossos** para remover.

O `passo` é gravado e **commitado antes** de cada chamada externa. Sem o commit por passo, um
processo morto no meio perderia a linha inteira e a faxina nunca saberia que existe um box para
limpar. O efeito colateral é externo e não volta atrás, então o registro vem na frente.

Sem FK para `exact_leads`: o lead nasce na Exact e só entra em `exact_leads` no sync seguinte
(até 10 min depois) — uma FK recusaria a linha justamente no instante do agendamento.

### 2.12 Os endpoints são públicos, e isso muda o que precisa de cuidado

São a **única superfície pública** do backend; todo o resto exige token. Quem chama é o
`obrigado.html` no navegador de um visitante anônimo.

- **Rate limit por IP, em memória** (60 req/60s leitura, 5 req/300s escrita). Sem ele, um laço
  de `curl` cria leads e boxes na agenda real de uma consultora até estourar o rate limit da
  própria Exact — e aí derruba junto o `sync_job`, que divide o mesmo token. É por processo: com
  dois workers o limite efetivo dobra, e aí é hora de trocar por Redis.
- **A grade valida a entrada.** `slot_id` vai a `grade.slot_por_id`, que só devolve slot da
  grade e dentro da antecedência. Sem isso, um POST forjado agenda 03:00 de domingo — o
  `BoxesAdd` aceitaria numa boa, porque a Exact não conhece a nossa grade.
- **Mensagem de erro não vaza detalhe da Exact.** `SDR not found` significa que a *nossa*
  configuração está errada, e o visitante não tem o que fazer com isso. O log guarda o
  original. A mensagem de `Origem inválida` também não lista as origens permitidas.
- **O `X-Forwarded-For` é lido**: o backend roda atrás de nginx, e sem isso o rate limit
  trataria o mundo inteiro como um único visitante.

---

## 3. Operação (runbook)

### 3.1 Adicionar uma LP nova (nova `subSource`)

Procedimento validado na 12ª e na 13ª LP. **Leia isto inteiro antes de rodar qualquer coisa:
criar origem é permanente** — não existe `SourcesAdd` nem `SourcesRemove`, e a limpeza só é
possível pela UI da Exact.

**Pré-requisito:** o nome da origem tem que estar combinado com quem gerou a página. O padrão
é **ASCII puro, sem acento** (`Pos Enfermagem em Saude Mental`, não `Saúde`), e o valor no
backend precisa ser **byte a byte** igual ao que a LP envia. A página dará `400 Origem
inválida` até o passo 5 terminar — por isso ela não deve ser publicada antes.

**1. Dry-run.** Monte o payload e confira o estado atual **sem escrever nada**:

```python
# GET /Sources: o source existe? a subSource já existe? há nome parecido em outro source?
sources = await client.listar_sources()
lp = next(s for s in sources if s["value"] == "Landing Page")
print(len(lp["subSources"]))          # o que existe hoje
print(NOVA.encode("utf-8"), NOVA.isascii())   # confira os bytes do valor novo
```

O payload do disparo — uma chamada só, porque o source **já existe**:

```json
{
  "duplicityValidation": false,
  "lead": {
    "name": "TESTE CRIACAO ORIGEM - excluir",
    "source": "Landing Page",
    "subSource": "<A ORIGEM NOVA, byte a byte>",
    "funnelId": 18535,
    "ddiPhone": "55",
    "phone": "11999990001"
  }
}
```

> **Use sempre o mesmo telefone de lote** (`11999990001`). É o que permite uma varredura única
> no fim, em vez de caçar lead por lead.

**Peça aprovação antes de disparar.** Este passo escreve no cadastro global.

**2. Disparo.** Uma chamada `POST /LeadsAdd`. Guarde o `leadId` que volta.

**3. Verificação byte a byte.** `GET /Sources` de novo: a contagem subiu em 1, a nova aparece
com id e `active: true`, e `valor_recebido.encode() == valor_enviado.encode()`. Confira também
que **nenhum subSource inesperado** apareceu — é isso que prova ausência de lixo, e **não** a
sequência de ids (ver 4.5).

**4. Limpeza.** `DELETE /LeadsDelete/{id}` → 204. Confirme por `id eq` (**o único filtro
consistente na hora**) e depois por varredura `phone1 eq '5511999990001'` → 0. Sem box e sem
`scheduleAdd`, o `LeadsDelete` limpa 100% e **não deixa órfão**.

**5. Allowlist.** Acrescente o valor ao fim de `AGENDAMENTO_SUBSOURCES` no `backend/.env`,
**mantendo as aspas**:

```bash
AGENDAMENTO_SUBSOURCES="...,Pos Saude do Trabalhador,Pos Enfermagem em Saude Mental"
```

⚠️ **As aspas são obrigatórias em valor com espaço.** Não por causa do systemd nem do dotenv —
os dois leem bem sem elas — mas do **bash**: um operador que faça `set -a && . .env` recebe
`AGENDAMENTO_SOURCE=Landing` e o shell tenta executar `Page` como comando. A variável fica pela
metade, o código cai no padrão (`Rd Marketing`, 3 origens) e **nada avisa**. Foi assim que o
problema apareceu: a validação imprimiu `source: 'Rd Marketing' | allowlist: 3` numa linha e
`✅ 'Landing Page' … 12 origens` na seguinte, no mesmo comando (FINDINGS §16).

Confira nos dois leitores antes de reiniciar:

```bash
bash -c 'set -a && . backend/.env && set +a; echo "[$AGENDAMENTO_SOURCE]"; \
         echo "$AGENDAMENTO_SUBSOURCES" | tr "," "\n" | wc -l'
```

**6. Restart e validação de startup.**

```bash
sudo systemctl restart cenat-backend.service
sudo journalctl -u cenat-backend.service --since "2 min ago" --no-pager | grep "agendamento"
# esperado: ✅ agendamento: source 'Landing Page' (id 140648) com as N origens da allowlist confirmadas
```

Se aparecer `❌ … NÃO existem sob o source`, **pare**: a grafia divergiu e o primeiro lead da
LP vai criar cadastro duplicado.

**7. Smoke em produção.**

```bash
curl -s -w "\n%{http_code}\n" -X POST http://127.0.0.1:8001/api/agendamento/lead \
  -H "Content-Type: application/json" \
  -d '{"nome":"SMOKE - excluir","email":"smoke@example.com","telefone":"11999990013",
       "origem":"<A ORIGEM NOVA>","extras":{"profissao":"Enfermeira"}}'
```

Espere **200**, confira o lead na Exact (`Entrada`, `funnelId 18535`, source 140648, subSource
nova, `description` com os extras) e **exclua**. Varra o telefone do smoke e o de lote.

**8. Documente.** Acrescente a origem à tabela da seção 5 deste arquivo e registre a operação
no `AGENDAMENTO_FINDINGS.md` — inclusive "nenhum órfão" quando for o caso.

**Se a LP nova for a primeira de um source novo:** a mesma chamada cria as duas coisas de uma
vez (foi o que aconteceu com `Landing Page` + `PosMulheridades`). Aí também é preciso trocar
`AGENDAMENTO_SOURCE`.

### 3.2 Mudar a grade ou as consultoras

A config ativa é **`backend/consultoras.json`**, apontada por
`AGENDAMENTO_CONSULTORAS_PATH`. O arquivo é **versionado de propósito** — é a grade em vigor,
vale ter histórico de quando mudou, e não contém segredo (e-mails internos, não credenciais).

```jsonc
[
  { "email": "comercial@cenatcursos.com.br",
    "nome_exibicao": "Victória Amorim",
    "grade": { "janelas": { "0": [["09:00","18:30"]], /* 1..4 iguais */ } } }
]
```

Chaves de `janelas`: `0` = segunda … `6` = domingo (padrão `date.weekday()`). O que não vier é
herdado de `GRADE_PADRAO` — na prática só `janelas` varia, porque duração (45 min) e
antecedência (2h) são política do produto, não da pessoa. A **janela** (`janela_dias`) nem mora
aqui: é `AGENDAMENTO_JANELA_DIAS`, uma linha para o produto inteiro (precedência: `janela_dias`
explícito na config > env > padrão 3). O `sales_rep_email` de dentro da grade é **ignorado** e
sobrescrito pelo `email` da consultora: duas fontes para o mesmo dado é convite para divergirem.

⚠️ `horizonte_dias` é **chave morta** desde 25/08/2026. Deixá-la na config não faz nada além de
um aviso no boot — quem a escreveu acha que está ofertando 14 dias e vai ver 3.

**Config por arquivo e não por JSON inline** porque o `.env` é `EnvironmentFile` do systemd
além de ser lido pelo dotenv, e o parser do systemd é mais restrito — uma linha com JSON entre
aspas pode impedir o serviço de subir, derrubando o Hub, o webhook da Meta e a NAT junto.

Depois de editar: **restart**. A config é cacheada em singleton preguiçoso, e recarregar exige
reiniciar o processo.

**A grade não precisa mais fugir dos blocos** (2.7) — a subtração ao vivo cuida disso. Mas vale
conferir os blocos reais antes de mudar janelas, porque é o que decide quanta **cobertura de
retry** a mudança custa:

```bash
curl -s "https://api.exactspotter.com/v3/Boxes?\$top=500&\$filter=salesRepEmail%20eq%20'EMAIL'%20and%20start%20ge%20'2026-08-01T00:00:00Z'" -H "$H"
# bloco recorrente = leadId 0 e o mesmo horário se repetindo; reunião real = leadId != 0
```

**Adicionar uma consultora nova** exige que ela exista e esteja **ativa** em `GET /Sellers` —
senão a validação de startup a tira de rotação e loga `❌ … FORA DE ROTAÇÃO`.

### 3.3 Remarcação e cancelamento (é manual, na UI, e são dois passos)

Não há endpoint. Quem remarca fala pelo WhatsApp, e alguém faz na UI da Exact:

1. **Cancelar a reunião** no lead.
2. **Excluir o box** na agenda da consultora.

**Por que dois passos:** são duas entidades. Cancelar a reunião não devolve o horário — o box
continua ocupando a agenda, e a consultora vê um bloco que não existe mais. E pela API o box
sequer sai: `BoxesRemove` recusa box com reunião vinculada, mesmo com a reunião cancelada e o
lead excluído (FINDINGS §6). **Só a UI consegue desfazer os dois.**

Depois disso, o novo horário é um agendamento novo (a pessoa pode reabrir a LP, ou alguém marca
manualmente na UI).

### 3.4 Faxina de boxes e os órfãos

**O job** (`faxina.py`) roda a cada 60s e devolve à agenda os boxes que ficaram pendurados:
linha em `passo='box_criado'` parada há **15 minutos**, com `box_id` preenchido, no máximo 20
por ciclo (o rate limit da Exact é dividido com o `sync_job` e com a própria LP).

O prazo é folgado de propósito: remover cedo demais tiraria o box de baixo de um fluxo que
ainda vai chamar o `scheduleAdd`, trocando uma falha rara por uma constante.

Três desfechos:

| situação | o que faz |
|---|---|
| box sem reunião | `BoxesRemove` → linha vira `falhou` |
| box **com** reunião (`BoxComReuniao`) | linha é **promovida a `agendado`** — a reunião existe, a linha é que mentia |
| box já não existe | linha vira `falhou` |
| erro de rede | **deixa em `box_criado`** e tenta no próximo ciclo |

**Ela só toca em box cujo id está na nossa tabela.** Não varre a agenda da Exact procurando o
que remover — não teria como distinguir um box nosso de um bloco criado pela consultora na UI,
e remover o bloco dela seria destruir agenda real por engano.

**O que é órfão:** box que recebeu `scheduleAdd` e depois teve o lead excluído. Ele fica preso
à reunião para sempre — `BoxesRemove` recusa, e não há `ScheduleRemove`. Mitigantes medidos:
é **invisível** em toda consulta testada, e **não bloqueia a agenda** (um `BoxesAdd` no mesmo
intervalo é aceito depois).

**9 órfãos documentados**, todos de teste autorizado, nenhum de tráfego real:

| box | origem |
|---|---|
| 43722204 | investigação §6 |
| 43722368 | experimento do `scheduleAdd` §8 |
| 43722680 | E2E do módulo §10 |
| 43726883, 43726884 | E2E do fluxo de duas etapas §12 |
| 43727109, 43727121 | experimento e E2E das consultoras §14 |
| 43727398, 43727399 | experimento e E2E do `ChangeFunnel` §15 |

**Cada reexecução de E2E que chegue ao `scheduleAdd` custa um box permanente.** Vale conferir a
asserção antes de rodar, não depois — um dos nove veio de uma verificação errada que reprovou
um resultado correto.

### 3.5 Troubleshooting

| sintoma | causa provável | o que fazer |
|---|---|---|
| **`400 Origem inválida`** | a `origem` que a LP manda não está na allowlist, ou diverge em byte (acento, espaço a mais) | compare byte a byte com `AGENDAMENTO_SUBSOURCES`; se for LP nova, rode 3.1 |
| **`409`** | o horário foi tomado entre a exibição e o clique, **em todas** as consultoras | é o comportamento correto; o front recarrega a grade. Frequente = grade desencostada dos blocos reais |
| **`fallback: true` no `/slots`** | grade vazia (feriado/lotada), Exact fora do ar, ou **nenhuma consultora em rotação** | veja o log de boot: `🚨 NENHUMA consultora válida` aponta e-mail inválido em `/Sellers` |
| **`404` no `/agendar`** | `?lead=` velho na URL, ou lead excluído do CRM | o front reenvia sozinho **sem** `leadId` e o fluxo de uma etapa cria o lead. Nada foi escrito |
| **`422`** | contrato do formulário: >10 extras, valor >200 chars, telefone sem DDD, nome vazio | alguém mexeu no form sem olhar o backend; o 422 aparece no console de quem publicou |
| **`429`** | rate limit por IP (5 escritas/5 min) | se for tráfego legítimo, revise `LIMITE_ESCRITA` |
| **`502` / `503`** | 503 = Exact não respondeu; 502 = respondeu recusando | veja o log; se `e.lead_id` existe, o lead sobreviveu e o SDR ainda pode ligar |
| **agendamento 3h adiantado no CRM** | alguém "corrigiu" `para_exact` para UTC de verdade | **reverta** e leia 2.4 |
| **`SDR not found`** | e-mail da consultora errado ou inativo | confira `GET /Sellers`; a validação de startup já avisa |
| **allowlist "sumiu" num script** | `.env` lido por `set -a && . .env` **sem aspas** | reponha as aspas; ver 3.1 passo 5 |
| **grade rendendo metade** | subtração de slots em voo aplicada globalmente | já corrigido em `0dba2e5`; se voltar, olhe `_ocupados_por_nos` |

**Onde estão os logs.** Tudo vai para o journal do serviço:

```bash
sudo journalctl -u cenat-backend.service -f | grep agendamento     # ao vivo
sudo journalctl -u cenat-backend.service --since "1 hour ago" --no-pager | grep -E "❌|⚠️|🚨"
sudo journalctl -u cenat-backend.service --since "5 min ago" | grep -E "boot:|✅"   # startup
```

Os prefixos são estáveis e servem de filtro: `📦` box criado · `👤` lead · `✅` agendado ·
`↪️` retry de consultora · `↩️` compensação · `🧹` faxina · `🔁` duplo clique · `➡️` passo 4.

E o estado local responde o que o log não guarda:

```sql
SELECT passo, count(*) FROM agendamentos WHERE created_at >= now() - interval '1 day'
GROUP BY passo;
SELECT id, nome, telefone, slot_inicio, sales_rep_email, passo, erro
FROM agendamentos ORDER BY id DESC LIMIT 20;
```

---

## 4. Referência

### 4.1 Endpoints nossos

Prefixo `/api/agendamento`. **Públicos, sem autenticação.**

#### `GET /slots`

Horários livres agrupados por dia. Cache de 60s do processo inteiro (a grade é a mesma para
todo mundo). Rate limit: 60 req/60s por IP.

```json
{
  "dias": { "2026-08-19": [ {"id": "2026-08-19T10:30:00", "hora": "10:30", "fim": "11:15"} ] },
  "fallback": false,
  "duracao_min": 45,
  "fuso": "America/Sao_Paulo"
}
```

Sem horário nenhum, ou com a Exact fora do ar:

```json
{"dias": {}, "fallback": true, "mensagem": "Não há horários abertos no momento."}
```

`fallback: true` é o que faz o front cair no "deixe seu contato" em vez de exibir grade vazia.

#### `POST /agendar`

Rate limit: 5 req/300s por IP.

```json
{
  "nome": "Fulana de Tal",
  "email": "fulana@example.com",
  "telefone": "11999998888",
  "origem": "Pos Enfermagem em Saude Mental",
  "extras": {"profissao": "Enfermeira", "como_conheceu": "Instagram"},
  "slot": "2026-08-19T10:30:00",
  "leadId": 51441824
}
```

`origem` ausente → `AGENDAMENTO_SUBSOURCE_PADRAO`. `leadId` ausente → o lead é criado aqui
(fluxo de uma etapa). `lead_id` em snake_case também é aceito na entrada.

```json
{
  "ok": true, "agendamento_id": 12, "lead_id": 51441824,
  "inicio": "2026-08-19T10:30:00", "fim": "2026-08-19T11:15:00",
  "fuso": "America/Sao_Paulo",
  "consultora_nome": "Victória Amorim",
  "aviso": "Para remarcar ou cancelar, fale com a gente pelo WhatsApp."
}
```

O e-mail da consultora **não** vai na resposta: é endpoint público, e endereço interno não é
dado do visitante.

| status | quando |
|---|---|
| 400 | origem fora da allowlist · slot fora da grade ou vencido |
| 404 | `leadId` não existe na Exact — **nada foi escrito** |
| 409 | horário tomado em todas as consultoras |
| 422 | corpo mal formado, contrato dos extras, telefone sem DDD |
| 429 | rate limit |
| 502 | falha depois do lock (`e.lead_id` diz se o lead sobreviveu) |

#### `POST /lead`

Cadastra sem agendar — a primeira etapa do form nativo, e o fallback de quem não quer escolher
horário. Mesmo corpo do `/agendar`, sem `slot` e sem `leadId`. Rate limit: 5 req/300s.

```json
{"ok": true, "lead_id": 51441824,
 "aviso": "Recebemos seu contato. Nossa equipe fala com você em breve."}
```

| status | quando |
|---|---|
| 400 | origem fora da allowlist |
| 502 | Exact respondeu recusando |
| 503 | Exact não respondeu (rede, timeout, 5xx) |

A distinção 502/503 é para o **front**, não para o visitante: ele segue para o obrigado de
qualquer jeito, sem `lead=`. Nenhum dos dois é 500 — 500 diria "quebrou aqui dentro", e a falha
é de dependência externa.

`lead_id` (snake) é a chave canônica de **resposta** em todo o módulo. `leadId` camelCase é
aceito só na **entrada** do `/agendar`, porque é o formato que o front tem em mãos.

### 4.2 Variáveis de ambiente

Em `backend/.env` (lido pelo `EnvironmentFile` do systemd **e** pelo python-dotenv). Nenhuma
delas é segredo; o token da Exact é `EXACT_SPOTTER_TOKEN`, que **não** pertence a este módulo.

| variável | exemplo | padrão se ausente |
|---|---|---|
| `AGENDAMENTO_SOURCE` | `"Landing Page"` | `Rd Marketing` (o source antigo, de propósito) |
| `AGENDAMENTO_SUBSOURCES` | `"PosMulheridades,Pos TEA V3,…"` | as 3 origens antigas |
| `AGENDAMENTO_SUBSOURCE_PADRAO` | `"PosMulheridades"` | `PosPraticasDialogicasTurma1` |
| `AGENDAMENTO_JANELA_DIAS` | `3` (hoje + D+1 + D+2) | `3` |
| `AGENDAMENTO_CONSULTORAS_PATH` | `/home/ubuntu/pos-plataform/backend/consultoras.json` | — |
| `AGENDAMENTO_CONSULTORAS` | JSON inline (tem precedência sobre o `_PATH`) | consultora única |
| `AGENDAMENTO_GRADE_PATH` / `_JSON` | grade global, sem consultoras | `GRADE_PADRAO` |
| `AGENDAMENTO_FUNIL_DESTINO` | `133413` | **vazio = passo 4 desligado** |
| `AGENDAMENTO_CORS_ORIGIN_SUFFIXES` | `.cenatsaudemental.com,.netlify.app` | esse mesmo valor |
| `AGENDAMENTO_CORS_ORIGINS` | `http://localhost:5500` | vazio (escape p/ dev) |

**Aspas obrigatórias em qualquer valor com espaço** — ver 3.1 passo 5. Vírgula é o separador
da allowlist, então um valor que *contenha* vírgula quebraria (nunca foi preciso).

Config inválida **nunca derruba o processo**: grade ilegível cai no padrão e grita no log, JSON
de consultoras inválido cai na consultora única, `FUNIL_DESTINO` ilegível desliga o passo 4 com
aviso, `JANELA_DIAS` não-inteiro ou menor que 1 volta para 3 (uma janela de 0 apagaria o
`/slots` inteiro em silêncio). Derrubar o backend inteiro por causa de uma vírgula num env seria pior — ele serve o
Hub, o webhook da Meta e a NAT.

### 4.3 Tabela `agendamentos`

Uma linha por **tentativa**, inclusive as que falharam. Migrações idempotentes e aditivas:
`migrate_agendamentos.py`, `_subsource.py`, `_extras.py`, `_lead_externo.py`.

| coluna | tipo | nota |
|---|---|---|
| `id` | BIGSERIAL | |
| `nome`, `email`, `telefone` | VARCHAR | `email` só existe aqui — a Exact não tem campo de e-mail |
| `slot_inicio`, `slot_fim` | TIMESTAMP | **naive em São Paulo**, igual ao que a Exact grava |
| `sales_rep_email` | VARCHAR NOT NULL | a consultora escolhida; reescrito quando o `BoxesAdd` define a vencedora |
| `sub_source` | VARCHAR | de qual LP veio — em `exact_leads` isso só aparece no sync seguinte, e some se o lead for excluído |
| `box_id`, `lead_id`, `meeting_id` | BIGINT | preenchidos conforme cada passo passa |
| `lead_externo` | BOOL NOT NULL | `true` = o `leadId` veio pronto no corpo; **o lead não é nosso para desfazer** |
| `extras` | JSONB | respostas livres. JSONB e não Text porque existe para ser consultado (`extras->>'Como conheceu'`) |
| `passo` | VARCHAR | `iniciado` → `box_criado` → `lead_criado` → `agendado` \| `falhou` |
| `erro` | TEXT | mensagem **crua** da Exact, sem tradução |
| `origem_ip` | VARCHAR(45) | 45 = IPv6 textual |
| `created_at`, `updated_at` | TIMESTAMP | naive SP |

`meeting_id` NULL **não** significa que a reunião não existe: o `scheduleAdd` devolve booleano,
e o id é lido best-effort depois.

### 4.4 `curl` reproduzíveis contra a Exact

```bash
set -a && . backend/.env && set +a          # as aspas do .env importam aqui
H="token_exact: $EXACT_SPOTTER_TOKEN"
B="https://api.exactspotter.com/v3"
```

```bash
# origens (source + subSources aninhados)
curl -s "$B/Sources" -H "$H" | python3 -m json.tool | head -40

# consultoras
curl -s "$B/Sellers" -H "$H"

# agenda de uma consultora — SEMPRE com $filter e $top<=500
curl -s "$B/Boxes?\$top=500&\$filter=salesRepEmail%20eq%20'comercial@cenatcursos.com.br'" -H "$H"

# um lead pelo id  (o ÚNICO filtro consistente na hora)
curl -s "$B/Leads?\$filter=id%20eq%2051441824" -H "$H"

# lead pelo telefone — o DDI VAI GRUDADO
curl -s "$B/Leads?\$filter=phone1%20eq%20'5511999998888'" -H "$H"

# reunião de um lead
curl -s "$B/Meetings?\$filter=lead/id%20eq%2051441824" -H "$H"

# etapas de um funil
curl -s "$B/Stages?\$filter=funnelId%20eq%2018535" -H "$H"

# excluir um lead de teste (204, IRREVERSÍVEL e cascateia)
curl -s -w "%{http_code}\n" -X DELETE "$B/LeadsDelete/51441824" -H "$H"
```

Funis: Intercambio 18285 · **Pos Graduacao 18535** · Pós Graduação - Vendas 18537 ·
Reativação - SQL 20647 · CONGRESSO PRESENCIAL 20776 · Vagas Afirmativas 21007 · Funil - Isa 25588.

Etapas do 18535: `Entrada`(1) → `Primeiro Contato` → `Follow 1..4` → `Follows 5..9` →
`Objeções - Whatsapp` → `Reagendamento` → `Pré Qualificado`(14, gate 3) → **`Agendados`(15, id
133409, gate 2)**. Atenção: há **espaço à esquerda** em `" Follows 7"` e `" Follows 9"`, e o
singular muda (`Follow 1..4` vs `Follows 5..9`) — nunca gere `stageName` por concatenação.

### 4.5 Armadilhas da API (todas medidas)

| armadilha | detalhe |
|---|---|
| **`phone1` volta com o DDI grudado** | `LeadsAdd` recebe `ddiPhone` e `phone` **separados**; `GET /Leads` devolve juntos. `phone1 eq '83988046720'` → **0 leads**; `phone1 eq '5583988046720'` → **4**. `ddiPhone` volta `None` na leitura, então a concatenação tem que ser feita na consulta. A função `buscar_lead_por_telefone` viveu meses errada assim, devolvendo `None` — indistinguível de "não existe" |
| **Filtro que não casa devolve lista vazia, não erro** | toda consulta nova merece uma verificação contra um registro que você **sabe** que existe, senão o silêncio passa por resposta |
| **`contains()` e `phone1 eq` atrasam depois do DELETE** | o índice de texto demora alguns segundos; `contains(lead,'TESTE')` devolve lead que `id eq` já não encontra. **`id eq` é o único filtro consistente na hora** — qualquer confirmação de exclusão por outro campo precisa insistir |
| **`description` demora a materializar** | recém-escrito, volta `null` por alguns segundos mesmo com `id eq`. Quem conferir sem insistir conclui que o dado não foi gravado |
| **`GET /Boxes` sem `$filter` tem janela implícita** | sem filtro: 276 linhas; `status eq 'busy'`: **1472**. O corte fica ~4 semanas atrás e **nada avisa**. Sempre `$filter` explícito |
| **`$top` máximo é 500** | `$top=1000` devolve **erro sem a chave `value`** — um `resp.json().get("value", [])` transforma isso em lista vazia e a agenda parece livre. Já aconteceu: três consultoras "sem nenhum box" que tinham 358 |
| **`@odata.nextLink` aparece com zero resultados** | apontando para `$skip=500` de um conjunto vazio. Quem seguir o link para "confirmar que acabou" pagina para sempre. **Lista vazia é resposta final** |
| **Filtro de data em `/Meetings` é STRING** | `meetingDate` e `startTime` são `Edm.String`. `ge 2026-08-18` → 400; `ge '2026-08-18'` → 200 |
| **`typeMeeting` não ecoa o que você manda** | `web` → volta `Online`. Não use o eco para conferir |
| **Rate limit 30 req/20s é do token inteiro** | dividido com o `sync_job` (a cada 600s, paginando 500 leads). Um pico na LP concorre com a ingestão — daí o teto de 20 por ciclo da faxina e o rate limit por IP |
| **id de subSource é global e não sequencial por source** | as 12 primeiras saíram em 176807–176818; a 13ª saiu **176822**, não 176819. O contador é da Exact inteira. **Ausência de lixo se prova pela verificação pós-disparo** (nenhum subSource inesperado), nunca pela sequência |
| **`LeadsDelete` cascateia** | a reunião vira `Cancelada` e o box **some de todos os `GET`**. Não use como compensação |
| **`BoxesRemove` é idempotente** | 204 de novo no mesmo id; id que nunca existiu dá `400 The informed box does not exist.` A diferença de mensagem é o que distingue "removido" de "inexistente" |
| **`.env` de produção vaza para a suíte offline** | `app.database` chama `load_dotenv()` no import, então todo o `.env` entra em `os.environ` antes do primeiro teste. A suíte limpa as `AGENDAMENTO_*` logo após os imports — um teste offline que muda de resultado conforme o servidor não é teste |

### 4.6 Testes

| arquivo | o que cobre | deixa órfão? |
|---|---|---|
| `test_agendamento.py` | 27 casos offline: fuso, grade, as duas compensações, faxina, rate limit, subtração por consultora | não (sem rede) |
| `test_agendamento_e2e.py` | fluxo de uma etapa contra a Exact real | **sim** |
| `test_agendamento_e2e_leadid.py` | fluxo de duas etapas; o passo 4 afirma **exatamente 1 lead** para o telefone | **sim** |
| `test_agendamento_e2e_extras.py` | `description` e JSONB — só `LeadsAdd` | **não** |
| `test_agendamento_e2e_consultoras.py` | retry com recusa **real** da Exact (cria um box bloqueador) | **sim** |
| `test_agendamento_e2e_funil.py` | passo 4 / `ChangeFunnel` | **sim** |
| `test_agendamento_cors.py` | sufixos, preflight, ápice recusado | não |

Os E2E exigem `--sim-eu-quero` e escrevem na Exact **de produção**, com alvo em 2027 para não
colidir com agenda real. O do retry protege um acoplamento invisível: `client._ERROS` casa
`Boxes are occupied` **por prefixo** — se a Exact mudar o texto, o erro deixa de virar
`SlotOcupado`, o retry nunca acontece e o visitante toma 502 em vez de ser atendido pela outra
consultora. Só teste real pega isso.

---

## 5. Estado atual (18/08/2026)

### As 13 LPs / `subSources`

Todas sob o source **`Landing Page` = id 140648**, ativas, ASCII puro sem acento.

| id | subSource | id | subSource |
|---|---|---|---|
| 176807 | `PosMulheridades` | 176814 | `Pos Alcool e Drogas T4` |
| 176808 | `Pos Grupos e Oficinas T2` | 176815 | `Pos Psicologia Clinica T2` |
| 176809 | `Pos Infantojuvenil EAD` | 176816 | `Pos Gestao Psicossocial T5` |
| 176810 | `Pos Psicologia na RAPS T3` | 176817 | `Pos TEA V3` |
| 176811 | `Pos Psicologia Hospitalar` | 176818 | `Pos Saude do Trabalhador` |
| 176812 | `Pos Suicidio e Luto T3` | **176822** | **`Pos Enfermagem em Saude Mental`** |
| 176813 | `Pos Psicologia Escolar` | | |

Padrão (quando a LP não manda `origem`): `PosMulheridades`.

### Consultoras em rotação

| nome | e-mail | id |
|---|---|---|
| Victória Amorim | `comercial@cenatcursos.com.br` | 415967 |
| Victória Rodrigues | `processoseletivo@cenatcursos.com.br` | 430634 |

Grade idêntica para as duas — **seg–sex, 09:00–18:30**, reuniões de 45 min, 12 horários/dia:
`09:00 · 09:45 · 10:30 · 11:15 · 12:00 · 12:45 · 13:30 · 14:15 · 15:00 · 15:45 · 16:30 · 17:15`.
Antecedência mínima 2h, **janela de 3 dias corridos** (hoje + D+1 + D+2), `type_meeting: web`.
Capacidade 88 vagas/semana, união de 59 horários/semana; 49% deles têm retry (as duas livres).
Ver 2.7 para os buracos por colisão e 2.7.1 para o que a janela curta alcança.

Fora de rotação: **Marina** (`executivadecarreiras@`, id 448892) está ativa em `/Sellers` mas
não está no `consultoras.json` — agenda praticamente vazia, 0 reuniões em 90 dias.
**Isabela** (id 430631) está **inativa** na Exact, num domínio diferente (`@ceos.com.br`),
apesar de ser quem trabalhou o funil de vendas historicamente (395 de 500 leads lidos no 18537).

### Ligado / desligado

| | estado |
|---|---|
| `POST /lead`, `POST /agendar`, `GET /slots` | ✅ no ar, públicos |
| fluxo de duas etapas (`leadId`) | ✅ ativo — e o de uma etapa continua funcionando |
| extras + `description` | ✅ ativo |
| rodízio de 2 consultoras com retry | ✅ ativo |
| validação de startup (origens, consultoras, funil) | ✅ ativa a cada boot |
| faxina de boxes | ✅ ativa (60s, remove box nosso parado há 15 min) |
| CORS da LP | ✅ `.cenatsaudemental.com`, `.netlify.app`, só em `/api/agendamento/*` |
| **passo 4 — mover para o funil de vendas** | ⛔ **DESLIGADO** (`AGENDAMENTO_FUNIL_DESTINO` vazio) |
| reunião no funil 18537 | ⛔ impossível pela API — limitação estrutural (2.6) |
| remarcação/cancelamento pela API | ⛔ não existe — WhatsApp + UI |

Log de boot esperado:

```
✅ agendamento: 2 consultora(s) em rotação — Victória Amorim, Victória Rodrigues
✅ agendamento: source 'Landing Page' (id 140648) com as 13 origens da allowlist confirmadas
ℹ️ agendamento: passo 4 (mover para funil de vendas) DESLIGADO
✅ Faxina de agendamento ativa (remove box nosso parado há 0:15:00)
✅ CORS do agendamento: .cenatsaudemental.com,.netlify.app (somente /api/agendamento/*)
```

### Pendências conhecidas

**Decisões de produto, esperando alguém:**

- **Passo 4 / funil de vendas.** Ligar move o lead para o 18537 mas marca a reunião como
  `Concluido` antes de acontecer (2.6). A alternativa é automação interna do CRM, ou mudar a
  posição de `Agendados` no 18537 pela UI — que mexe num funil com 385 leads vendidos e **não é
  decisão de código**.
- **RD Marketing.** A conversão das origens antigas via API ficou pendente, conforme combinado.
  Nada foi tocado.
- **Janela de 3 vs 4 dias.** Com 3, sexta a partir das 15:15 não alcança dia útil nenhum e a LP
  cai no fallback até sábado à meia-noite (~9 h/semana). `AGENDAMENTO_JANELA_DIAS=4` fecha o
  buraco ao custo de ofertar mais longe. Uma linha do `.env` + restart (2.7.1).
- **Cobertura de retry em 49%.** É o preço medido de ofertar o comercial inteiro (2.7). Se
  `Boxes are occupied` começar a aparecer no log com frequência, a saída não é encolher a grade
  de volta: é rever os blocos recorrentes com as consultoras. A terça da Amorim
  (`10:10–13:30`) sozinha responde por boa parte do buraco.

**Dívida técnica:**

- **Pares duplicados intencionais.** `PosMulheridades` existe em **dois** sources: 173358 sob
  `Rd Marketing` (125 leads históricos) e 176807 sob `Landing Page`. O mesmo vale para
  `posenfermagemsm` (176805, `Rd Marketing`, 2 leads) e `Pos Enfermagem em Saude Mental`
  (176822). É de propósito — o par enviado hoje é sempre o novo, e o antigo preserva o
  histórico. **Em relatório de marketing são o mesmo curso**: não somar às cegas nem tratar
  como origens distintas.
- **`DialogicasTurma` (176793)** continua no cadastro de origens: lixo criado pelo primeiro
  teste da investigação. Sem lead nenhum apontando para ele, é cosmético — mas aparece na lista
  de quem for montar relatório. **Limpeza só pela UI** (não há endpoint de escrita para origem).
- **9 boxes órfãos** (3.4), todos de teste autorizado. Invisíveis, não bloqueiam agenda.
- **`LeadsUpdate` não é chamado.** Corrigir nome ou telefone no `obrigado.html` **não** atualiza
  o lead já criado pelo `index.html`. O valor corrigido vai para a tabela `agendamentos`, e é lá
  que o SDR confere. Se incomodar na prática, é uma sprint própria.
- **Rate limit em memória.** Um processo, um contador. Com dois workers o limite efetivo dobra —
  aí é hora de Redis.

**Fora deste módulo, mas registrado aqui porque apareceu na varredura:**

- **`POST /api/exact-leads/sync` está aberto**, sem autenticação. É o gatilho manual do sync do
  Exact, e o sync chama `send_welcome_to_new_lead` — um POST anônimo pode disparar uma rodada de
  boas-vindas. Hoje é inerte porque `auto_welcome_config.enabled=false`, mas volta a ter dentes
  no dia em que a automação religar. Entra na lista de pré-requisitos do religamento.
- Outras rotas de escrita sem auth (`/api/tags`, `/api/kanban/*`) são risco de outra natureza e
  não foram tocadas.

---

## Histórico

| data | o que |
|---|---|
| 17/08 | investigação da API (FINDINGS §1–8), módulo `app/agendamento/`, CORS isolado |
| 17/08 | `subSource` vem do corpo, contra allowlist (§11) |
| 18/08 | `leadId` opcional + form nativo na LP (§12) |
| 18/08 | `extras` e `description` (§13) |
| 18/08 | múltiplas consultoras, escolha por carga e retry (§14) |
| 18/08 | correção: subtração de slots em voo por consultora |
| 18/08 | ativação de Amorim + Rodrigues com a grade da opção A |
| 18/08 | passo 4 opcional (`ChangeFunnel`), desligado (§15) |
| 18/08 | source `Landing Page` + as 12 primeiras origens (§16) |
| 18/08 | 13ª origem: `Pos Enfermagem em Saude Mental` (§17) |
| 25/08 | janela de 3 dias corridos (o horizonte de 14 dias morreu) + grade no comercial inteiro 09:00–18:30, com os números recalculados contra os blocos reais (`AGENDAMENTO_JANELA_GRADE_20260825.md`) |
