# RECON_CONSULTORAS_20260928 — quem recebe as reuniões e por quê

**Modo: SOMENTE LEITURA.** Nenhuma escrita na Exact, no banco, no `.env` ou no
`consultoras.json`. Fontes: `GET /v3/Sellers`, `/Sdrs`, `/Groups`, `/MeetingSettings`,
`/Meetings` (consultados em 28/09 ~16h UTC), tabela `agendamentos`, `journalctl -u cenat-backend`.
Predicado de teste: `PREDICADO_TESTE` de `app/relatorios.py:216` (com a âncora `^zz`).
Horários do banco são de SP (naive); os do journal e da Exact (`registerDate`) estão em UTC.

## TL;DR

- **A premissa está velha.** `processoseletivo@` (Victória Rodrigues) ficou fora de rotação
  **só entre os boots de 17/09 20:03 e 27/09 14:03 UTC**. Hoje ela está `active: true` na
  Exact e o Hub diz, nos três boots de 27/09: `2 consultora(s) em rotação`. A grade já bate
  com as duas.
- **Ninguém trocou de login.** A Exact tem 4 sellers; as duas Victórias são os mesmos ids
  de sempre (415967 e 430634). A Rodrigues foi **desativada e reativada no mesmo usuário**.
- **O custo da janela: 18 telefones (17 pessoas) perdidos em 16–17/09.** Antes do restart de
  17/09, a Exact já recusava a Rodrigues com `SDR is disabled`, mensagem que o Hub não
  reconhece. O fluxo trata isso como erro de configuração e **não tenta a outra
  consultora**. Resultado: 54 tentativas falhas, nenhuma dessas pessoas agendou depois pelo
  Hub, e só 4 têm reunião criada à mão na Exact.
- **Há uma divergência de expediente que ninguém configurou:** na Exact, a Amorim atende
  **10:00–19:00**; no `consultoras.json`, **09:00–18:30**.

---

## Bloco 1 — O que a Exact diz dos usuários

### 1.1 `GET /Sellers`: todos os vendedores

| id | nome | email | active | em `consultoras.json`? |
|---|---|---|---|---|
| 415967 | Victória Amorim | comercial@cenatcursos.com.br | **true** | sim (1ª entrada) |
| 430634 | Victória Rodrigues | processoseletivo@cenatcursos.com.br | **true** | sim (2ª entrada) |
| 448892 | Marina Serafim | executivadecarreiras@cenatcursos.com.br | true | não |
| 430631 | Isabela Oliveira | isabelaoliveira+vd@cenatcursos.com.br | false | não |

`GET /Groups` diz quem é de qual produto:

| grupo | sellers | SDR |
|---|---|---|
| `grupopos` (15709) | comercial@ (desde 08/08/2025), processoseletivo@ (desde 18/05/2026) | sdr@cenatsaudemental.com (Thobias) |
| `grupointer` (15710) | executivadecarreiras@ (Marina, desde 09/06/2026) | sdr@cenatsaudemental.com |

**As "duas consultoras" do comercial são exatamente as duas do `consultoras.json`.** A
Marina é do intercâmbio e não entra na grade da pós.

### 1.2 `processoseletivo@`

- **Hoje: `active: true`.**
- **Desde quando: não mensurável pela API.** `/Sellers` devolve só `id, name, lastName, email,
  phone, phone2, active`, sem data. Dá para cercar a janela pelo comportamento:

  | evento | quando (UTC) | evidência |
  |---|---|---|
  | último `BoxesAdd` aceito com ela | 15/09 22:23 | reunião 4754841 |
  | primeira recusa `SDR is disabled` | 16/09 17:31 | journal, agendamento #552 (1º de 54; o último é #629) |
  | boot a vê inativa | 17/09 20:03 e 21/09 11:34 | journal: `inativa na Exact — FORA DE ROTAÇÃO` |
  | primeira reunião nela de novo (manual, sem "Agendamento LP") | 23/09 18:24 | reunião 4762858 |
  | boot a vê ativa | 27/09 14:03 (e 17:24, 18:27) | journal: `2 consultora(s) em rotação` |

  **Desativada entre 15/09 22:23 e 16/09 17:31; reativada até 23/09 18:24, no máximo.**
- **Outro usuário com nome parecido ativo: não.** Em `/Sellers` só existe uma Rodrigues. Em
  `/Sdrs` existem perfis antigos das duas Victórias, os dois `active: false`: "Victória
  Amorim" 415875 (`processoseletivo+sdr@…`, o autor que dava 400 nas notas) e "Victória
  Rodrigues" 415878. São perfis de SDR, e o agendamento não usa nenhum dos dois. Não há sinal
  de troca de login.

---

## Bloco 2 — Quem de fato recebe reunião

### 2.1 Pela Exact: `GET /Meetings`, `startTime` de 29/08 a 28/09

Mensurável. `$filter=startTime ge '2026-08-29'` (o campo é **string**: data sem aspas dá 400)
e `registerDate ge 2026-08-29T00:00:00Z`, unidos por id, somam 236 reuniões.

| vendedor | total | Concluído | Cancelada | Vigente |
|---|---|---|---|---|
| comercial@ (Amorim) | **135** | 35 | 89 | 11 |
| processoseletivo@ (Rodrigues) | **79** | 23 | 52 | 4 |
| sdr@ (Thobias, como rep) | 8 | 4 | 4 | 0 |

Por semana ISO (`startTime`), mostrando o buraco da Rodrigues:

| semana | Amorim | Rodrigues |
|---|---|---|
| 36 (31/08–06/09) | 25 | 34 |
| 37 (07–13/09) | 27 | 26 |
| 38 (14–20/09) | 29 | 13 |
| 39 (21–27/09) | **46** | **1** |
| 40 (28/09– , parcial) | 12 | 7 |

Futuras (após 28/09): Amorim 8, Rodrigues 4, Marina 2.

⚠️ O campo `user` de `/Meetings` **não diz quem marcou**: é `sdr@cenatsaudemental.com` em 222
de 222 reuniões, inclusive nas do Hub (é o dono do token). Para separar Hub de mão, o único
marcador é `managerDescription` começando com `Agendamento LP —`, que o Hub grava no
`BoxesAdd` (`agendar.py:383`). Pelo marcador: Amorim 88 do Hub e 47 sem marcador;
Rodrigues 59 do Hub e 20 sem marcador.

### 2.2 Pelo Hub: `agendamentos`, `passo='agendado'`, `created_at` ≥ 29/08, sem teste

Origem: `origem_ip IS NULL` = agente (mesma regra de `relatorios.py:450`); com IP = site.

| consultora (`sales_rep_email`) | site | agente | total |
|---|---|---|---|
| comercial@ (Amorim) | 78 | 8 | 86 |
| processoseletivo@ (Rodrigues) | 47 | 14 | 61 |

Por dia de criação, em volta da janela:

| dia | Amorim | Rodrigues |
|---|---|---|
| 13/09 | 4 | 2 |
| 14/09 | 1 | 2 |
| 15/09 | 1 | 6 |
| 16/09 | 3 | **0** |
| 17/09 | 0 | 0 |
| 18/09 a 26/09 | 3–9/dia | **0** |
| 27/09 | 0 | 1 |
| 28/09 (até ~13h SP) | 0 | 3 |

A volta da Rodrigues em 27–28/09 com a Amorim em zero é a regra de desempate (3.1): a
Rodrigues começa esses dias com carga 0.

### 2.3 Cruzamento: reuniões na Rodrigues depois de ela sair de rotação

`registerDate` das reuniões com `processoseletivo@` a partir de 16/09 (UTC):

| reunião | registrada | para | marcador LP | origem |
|---|---|---|---|---|
| 4762858 | 23/09 18:24 | 23/09 17:49 | não | **mão, na Exact** (registrada depois do horário: lançamento retroativo) |
| 4765572 | 25/09 18:38 | 28/09 15:35 | não | mão |
| 4765894 | 26/09 14:37 | 28/09 14:00 | não | mão |
| 4765895 | 26/09 15:09 | 28/09 11:00 | não | mão |
| 4765939 | 27/09 21:49 | 28/09 09:45 | sim | Hub, depois do boot de 27/09 14:03 |
| 4765941 / 4765955 / 4766592 | 28/09 | 28–29/09 | sim | Hub |

**Nenhuma reunião do Hub caiu na Rodrigues entre 15/09 22:23 e 27/09 21:49.** As 4 do meio
foram marcadas à mão pelo comercial, o que também prova que ela já estava reativada em 23/09.

**As "5 de 6 reuniões do dia 18/09 com a Rodrigues" vistas em 17/09** são do Hub e foram
registradas até 15/09, antes da desativação. Exemplos: 4754675 (reg. 15/09 19:57 → 18/09
10:30) e 4754008 (reg. 15/09 15:16 → 18/09 16:30).

### 2.4 O que a desativação custou: `SDR is disabled`

`agendamentos` com `erro = 'HTTP 400: SDR is disabled.'`: **54 linhas, 18 telefones, 4 do
agente**, todas entre 16/09 14:31 e 17/09 15:19 (SP). Em 16/09 foram 47 tentativas de 12
telefones; em 17/09, 7 de 6.

- O journal mostra as 54 como `BoxesAdd falhou em processoseletivo@cenatcursos.com.br`.
  **O banco grava `comercial@` nessas linhas**: numa falha, a coluna fica com
  `candidatas[0]` (a 1ª da config) e não com quem falhou (`agendar.py:345`, reescrita só no
  sucesso). Quem ler `sales_rep_email` de linha `falhou` lê a consultora errada.
- **Nenhuma das 18 agendou depois pelo Hub.** Na Exact, 4 pessoas (5 telefones: um aparece
  com e sem o 9) têm reunião registrada com a Amorim em 17/09 e 23/09, sem marcador LP, ou
  seja, recuperadas à mão. **~13 pessoas não têm reunião nenhuma na Exact em 30 dias.**
- Por que não caíram na Amorim: `SDR is disabled` **não está em `client._ERROS`**
  (`client.py:66-73`, que só conhece `sdr not found`). Vira `ExactErro` genérico, e o
  `except client.ExactErro` de `agendar.py:392-398` encerra o fluxo sem tentar a próxima consultora,
  de propósito, para erro de configuração. A docstring de `listar_sellers` (`client.py:270-272`)
  e o log do boot (`consultoras.py:193-194`) dizem que seller inativo dá `SDR not found`,
  mas **a mensagem real é outra**.
- A Rodrigues era a 1ª da ordem porque a carga dela no dia era menor, e o desempate a
  escolhia. Ficou "presa" até o restart de 17/09 20:03 UTC.

---

## Bloco 3 — Como o Hub escolhe a consultora

### 3.1 Regra

**Menos carregada do dia, com desempate pela ordem do arquivo.**
`agendar.escolher_consultora`, `app/agendamento/agendar.py:251-277`:

- carga = linhas de **`agendamentos` do Hub** com `slot_inicio` no mesmo dia e `passo` fora
  de `falhou`/`iniciado`. **Não conta** reunião marcada à mão na Exact (é de propósito:
  docstring em `agendar.py:258-261`);
- empate: ordem do `consultoras.json` (a Amorim primeiro);
- devolve lista; `Boxes are occupied` passa para a próxima (`agendar.py:386-391`). **Qualquer
  outro erro para o fluxo**, e é isso que causou o 2.4.

Candidatas = as consultoras em rotação cuja grade contém o slot pedido (`agendar.py:295-301`).
`/slots` mostra a união das grades (`consultoras.py:13-14`). Agente e site usam a mesma função
(o agente chama `agendar` com `origem_ip=None`, `qualificacao_fluxo.py:1635`).

### 3.2 Capacidade com uma consultora só

- **Slots por dia, por consultora: 12.** `duracao_min=45` (`grade.py:91`), 09:00–18:30:
  09:00, 09:45, … 17:15. O comentário está em `grade.py:87-88`. Antecedência mínima de 2h
  e janela de 4 dias (`AGENDAMENTO_JANELA_DIAS=4`). Com as duas em rotação, os mesmos
  12 horários valem por 2.
- **Oferecidos vs. marcados nos últimos 7 dias: não mensurável.** O `/slots` não registra o
  que ofereceu (nenhum log ou tabela de oferta em `app/agendamento/`). O que dá para medir é
  a ocupação contra o teto de 12:

  | dia (slot) | Amorim, Hub | Amorim, total na Exact (inclui canceladas) | não canceladas |
  |---|---|---|---|
  | seg 21/09 | 7 | 10 | 3 |
  | ter 22/09 | 6 | 8 | 4 |
  | qua 23/09 | 10 | **12** | 4 |
  | qui 24/09 | 6 | 11 | 4 |
  | sex 25/09 | 3 | 5 | 2 |

  **Em 23 e 24/09 a Amorim encostou no teto de 12.** E cancelar não devolve o horário: um box
  que recebeu `scheduleAdd` fica ocupado para sempre (`client.py:200-201`, FINDINGS §6).
  Canceladas também saturam. 141 das 222 reuniões dos 30 dias estão `Cancelada`, o que
  torna esse efeito relevante, não marginal.

### 3.3 Fonte de config ativa em produção

- `AGENDAMENTO_CONSULTORAS` (inline): **não definido**, nem no `.env` nem no ambiente do
  processo (`/proc/<pid>/environ` do uvicorn 1863451).
- `AGENDAMENTO_CONSULTORAS_PATH=/home/ubuntu/pos-plataform/backend/consultoras.json`,
  carregado pelo `EnvironmentFile=` do `cenat-backend.service`.
- **A fonte ativa é o `consultoras.json` do repo**, o mesmo arquivo commitado. Conteúdo
  efetivo: Amorim e Rodrigues, as duas com seg–sex (`0`–`4`) 09:00–18:30, sem outras chaves
  (duração, antecedência e `type_meeting=web` vêm do `GRADE_PADRAO`).

### 3.4 Quando `validar_contra_exact` roda

**Só no boot.** `main.py:305-318`: uma única `asyncio.create_task` no startup, sem laço e
sem outro chamador no código. Consequências, as duas observadas:

- **Desativar na Exact não tira do Hub até o restart.** Entre a desativação e o restart de
  17/09, o Hub seguiu mandando gente para ela, e isso gerou o 2.4.
- **Reativar na Exact não devolve ao Hub até o restart.** Ela estava ativa desde, no máximo,
  23/09 18:24 e só voltou no restart de 27/09 14:03 (deploy do follow). **~4 dias úteis com
  a Amorim sozinha sem necessidade.**

Além disso, `desativar()` é uma via de mão única dentro do processo (`consultoras.py:158-163`):
nada recoloca uma consultora no `_cache`.

---

## Bloco 4 — O que falta para adicionar (ou manter) a segunda consultora

**A segunda consultora já está configurada e em rotação.** Para uma entrada nova, ou para
manter a atual correta:

### No `consultoras.json` (`consultoras._montar`, `consultoras.py:97-112`)

| campo | obrigatório? | observação |
|---|---|---|
| `email` | **sim** | chave de tudo; tem que ser o `email` exato do seller em `/Sellers` |
| `nome_exibicao` | não | se faltar, vira a parte antes do `@` |
| `grade.janelas` | não | se faltar, herda seg–sex 09:00–18:30. Chaves `"0"`–`"6"` (0 = segunda), lista de faixas `["HH:MM","HH:MM"]` |
| `grade.*` (duração, antecedência, `type_meeting`) | não | herdam `GRADE_PADRAO`; `sales_rep_email` dentro da grade é ignorado |

Mudança no arquivo **só vale após restart** do `cenat-backend` (singleton, `consultoras.py:118-119`).

### Na Exact

- **Obrigatório para o Hub:** usuário em `/Sellers` com `active: true`. É a única coisa que
  `validar_contra_exact` confere.
- **Observado, mas o Hub não confere:**
  - estar no grupo `grupopos` (`/Groups`), como as duas atuais. Não medi se o `BoxesAdd` ou o
    `scheduleAdd` recusam um seller fora do grupo, então não dá para afirmar que é
    obrigatório;
  - expediente em `/MeetingSettings.usersBusinessHours`. **Não é aplicado pela API**: 2
    reuniões do Hub com a Amorim antes das 10h foram aceitas. Mas é o que a consultora vê
    como "horário dela".
- **Divergência atual:**

  | | Exact (`usersBusinessHours`) | Hub (`consultoras.json`) |
  |---|---|---|
  | Amorim (415967) | seg–sex **10:00–19:00** | seg–sex 09:00–18:30 |
  | Rodrigues (430634) | seg–sex 09:00–18:30 | seg–sex 09:00–18:30 ✓ |

  Na prática, só 2 de 86 reuniões do Hub com a Amorim foram antes das 10h, contra 12 de 61 com
  a Rodrigues. É consistente com a Amorim ter compromissos nesses horários, mas é inferência.

---

## Fechamento

**Quem atende hoje segundo a Exact:** Victória Amorim (`comercial@`, 415967) e Victória
Rodrigues (`processoseletivo@`, 430634), as duas `active: true` e no grupo `grupopos`.
Reuniões em 30 dias: 135 e 79. A Rodrigues ficou desativada de ~16/09 a ~23/09.

**Quem atende hoje segundo o Hub:** as mesmas duas, em rotação desde o boot de 27/09 14:03
UTC. De 17/09 20:03 a 27/09 14:03 foi só a Amorim, e de 16/09 à tarde até 17/09 20:03 o Hub
mandou para a Rodrigues já desativada: 54 falhas, ~13 pessoas sem reunião.

**Para a grade bater:**
1. **Avisar antes de desativar ou reativar alguém na Exact**, porque o Hub só percebe no
   restart. Desativar sem restart = visitantes perdidos (2.4). Reativar sem restart = uma
   consultora ociosa (3.4).
2. **Confirmar o expediente da Amorim**: 10:00–19:00 (Exact) ou 09:00–18:30 (Hub)? Corrigir
   o lado errado.
3. **Dizer se a Rodrigues tem folga ou meio período** em algum dia. Hoje as duas grades são
   iguais, seg–sex cheio.
4. Para uma 3ª pessoa: e-mail exato do seller, ativo, no `grupopos`, e as janelas por dia da
   semana.

**Do lado do código (não feito aqui, é recon):**
- mapear `SDR is disabled` em `client._ERROS` e deixar o fluxo pular para a próxima
  consultora nesse caso;
- revalidar `/Sellers` periodicamente, não só no boot;
- gravar em `sales_rep_email` quem de fato falhou;
- corrigir a docstring de `client.py:270-272` e o log de `consultoras.py:193-194`.
