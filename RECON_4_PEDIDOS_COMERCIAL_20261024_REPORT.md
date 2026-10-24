# RECON: quatro pedidos do comercial (24/10/2026)

Agenda do Google, duplicidade de aplicação, campos personalizados da Spotter e separação de usuários.

**Natureza:** auditoria somente leitura. Só `SELECT` (e `CREATE TEMP TABLE`, que some com a sessão) no banco, só `GET` na Exact e só `freebusy.query`/`calendarList` no Google. Nada foi escrito no código, no banco, na Exact, na Meta ou no Google. Nenhum teste foi executado. Os scripts de medição ficaram no scratchpad da sessão, fora do repo.

**Estado do repo no início:** `main` em `5cc59fa`, com dois arquivos não rastreados de antes (`INCIDENTE_CHAVE_GOOGLE_20261017.md` e `backend/fix_status_orfao_webhook.py`), que este commit não toca.

**Leitura obrigatória ausente:** `SPRINT_GRADE_GOOGLE_AGENDA_20261015.md` e `RETOMADA_GRADE_GOOGLE_AGENDA_20261017.md` não existem no repo nem em nenhum branch (detalhes em §1.0).

## §0 Resumo

| Item | Achado principal | Plano | Estimativa |
|---|---|---|---|
| 1. Agenda do Google | A conta de serviço lê livre/ocupado nos dois calendários e isso já basta. De 26 a 28/10, **6 dos 27 pares horário/consultora oferecidos (22%) estão ocupados no Google**. A causa: a Exact só tem bloqueios do próximo dia útil, copiados de uma vez na véspera; para D+2 e D+3 não há bloqueio. As 15 reuniões Vigentes desses dias aparecem todas ocupadas no Google, inclusive as que a SDR marcou direto na Exact. | Módulo novo de freebusy (uma consulta, assíncrona, cache de 60 s) somado a `ocupados` em `disponibilidade.py`, atrás de `GOOGLE_GRADE_ENABLED`. | 1 dia + 0,5 dia de comparação em log |
| 2. Duplicidade | Em 30 dias, **50 pessoas aplicaram 2 ou mais vezes e geraram 63 leads a mais**. 5 (6 com um caso incerto) já tinham reunião Vigente ao reaplicar. **9 pessoas ficaram com 2 reuniões Vigentes simultâneas, 5 delas com consultoras diferentes**. 2 desses casos vieram da LP, com o mesmo horário marcado com a outra consultora, e **um está assim agora** (§2.1.5). | Trava por `chave_telefone` nas rotas públicas: com reunião Vigente e futura, responde 200 com a reunião existente, sem `LeadsAdd` nem box. Funciona com os snippets já publicados. | 1,5 dia |
| 3. Campos da Spotter | **A API aceita**: `customFields` está no `LeadsAdd` pelo `$metadata` e pela doc oficial. Os campos `_possuigraduacao` e `_investimentoposgraduacaoonline` já existem e o SDR os **redigita à mão** (137 e 118 leads da LP; 321 de 458 ficaram sem nada). A pergunta atual da LP ("R$272 possível? Sim/Não") não cabe nas 4 faixas. | Teste controlado com um lead `zz` (apagado depois), de/para em config, extras nos campos **e** no `description`, e nova tentativa sem os campos se der 400. | ~1 dia |
| 4. Separação de usuários | Quem dispara vagas afirmativas é a conta id 6 "Victória", não a id 3 "Vi Amorim" (zero envios desde 01/09). Os contatos aparecem para o Thobias porque 7 de 8 usuários são `admin` e a tela não filtra por dono. Além disso, **o dono é o próprio Thobias** (127 de 159), que abre a conversa com `vagasafirmativas_1`. Existe um canal só. Vagas são 29% das conversas com movimento em 7 dias. | (a) papel em `users`; (d) tag automática pelo template; (c) filtro padrão por papel; (b) autor vira dono só se a Isa decidir. | 2 a 2,5 dias |

**Ação operacional para hoje (fora do escopo, nada foi escrito):** a pessoa `19****02` tem duas reuniões Vigentes na **segunda 27/10 às 10:00**, a 4789461 com a Rodrigues e a 4789462 com a Amorim. As duas foram conferidas por `GET /Meetings` em §2.1.5. Alguém do comercial precisa cancelar uma delas na Exact antes de segunda.

## §1 Item 1. horários pelo Google Agenda (livre/ocupado)

### 1.0 Ponto de partida

- `SPRINT_GRADE_GOOGLE_AGENDA_20261015.md` e `RETOMADA_GRADE_GOOGLE_AGENDA_20261017.md` **não existem** no repo nem em nenhum branch (`find / -iname "*GRADE_GOOGLE*" -o -iname "RETOMADA*"` e `git log --all -- '*GRADE_GOOGLE*' '*RETOMADA*'` voltam vazios). O que sobrou dessa sprint é uma linha de comentário em `backend/.env:84-85` ("Paliativo até a grade vir do Google Agenda (GOOGLE_GRADE_ENABLED ainda não existe)"). Esta seção parte do código, de `AGENDAMENTO_FOLGA_ALMOCO_20261014.md` e de `INCIDENTE_CHAVE_GOOGLE_20261017.md`.
- Conta de serviço: `nat-ia-calendar@gen-lang-client-0630066041.iam.gserviceaccount.com`, chave `a9344ad2` em `backend/google-credentials.json` (trocada em 17/10, `INCIDENTE_CHAVE_GOOGLE_20261017.md`).
- O Hub hoje **não lê o Google** para a grade. `app/google_calendar.py:26-41` (`get_busy_slots`) existe, mas só é usado por `calendar_routes.py:6` e por código comentado em `ai_engine.py:232` e `ai_routes.py:268`. Ele aponta para `comercialcenat@gmail.com` (`google_calendar.py:10-15`), fixa a janela em 08h–18h (`:31-32`) e chama `.execute()` síncrono dentro de `async def` (bloqueia o event loop). Não serve como está.
- Configuração em produção: grade de cada consultora `10:00–12:00 + 13:30–19:00`, seg–sex (`backend/consultoras.json`), slot de 45 min (`grade.py:91`, `GRADE_PADRAO["duracao_min"]`), `AGENDAMENTO_JANELA_DIAS=4` (`.env:30`), `AGENDAMENTO_FOLGA_MIN=15` (`.env:86`).
- A subtração atual, por consultora, em `disponibilidade.py:203-233`: boxes da Exact (`:210`, `client.listar_boxes`, só GET), nossos agendamentos em voo (`:218`), reservas de remarcação pendente (`:222-223`), tudo alargado pela folga (`:225`).

Acesso real da conta de serviço (comando só leitura, `events.list` com escopo `calendar.readonly`):

```
processoseletivo@cenatcursos.com.br OK freeBusyReader [(None, {'dateTime': '2026-10-28T12:00:00-03:00'...}), ...]
comercial@cenatcursos.com.br        OK freeBusyReader [(None, {'dateTime': '2026-10-28T09:00:00-03:00'...}), ...]
```

`accessRole = freeBusyReader` e `summary = None` nos dois: confirma que só temos livre/ocupado, sem título. O desenho LIVRE pelo título está fora de alcance até o Pablo liberar "ver detalhes".

### 1.1 Google: blocos ocupados (freebusy.query, 26 a 28/10, 08h–20h SP)

Comando (`scratchpad/fb.py`, escopo `calendar.readonly`):

```python
body={"timeMin":"2026-10-26T08:00:00-03:00","timeMax":"2026-10-28T20:00:00-03:00",
      "timeZone":"America/Sao_Paulo","items":[{"id":"processoseletivo@cenatcursos.com.br"},
                                              {"id":"comercial@cenatcursos.com.br"}]}
s.freebusy().query(body=body).execute()
```

Resposta sem `errors` nos dois calendários. Blocos ocupados:

| Dia | Victória Rodrigues (`processoseletivo@`) | Victória Amorim (`comercial@`) |
|---|---|---|
| seg 26/10 | 08:00–11:30, 12:00–14:45, 15:45–16:30, 16:50–17:20, 18:00–18:50 | 08:00–11:30, 11:35–11:55, 13:30–14:30, 15:00–15:45, 16:30–17:15, 18:00–18:45 |
| ter 27/10 | 09:00–09:30, 10:00–10:45, 12:00–13:30, 18:00–18:50 | 09:00–10:45, 13:30–14:30, 15:00–15:45 |
| qua 28/10 | 09:00–09:30, 10:10–10:40, 12:00–13:30, 18:20–18:50 | 09:00–10:40, 13:30–14:30 |

O 08:00 de 26/10 é corte do `timeMin`: na Exact o bloco correspondente começa 07:00 (box 44204046).

Padrões que aparecem sem precisar de título: Rodrigues tem bloco diário 09:00–09:30, almoço 12:00–13:30 e 18:20–18:50; Amorim tem 09:00–10:40 e 13:30–14:30 todo dia. Em 27/10 os blocos `10:00–10:45` (Rodrigues), `09:00–10:45` (Amorim, união de 09:00–10:40 com a reunião 10:00–10:45), `15:00–15:45` (Amorim) e `18:00–18:50` (Rodrigues, união de 18:00–18:45 com 18:20–18:50) contêm as reuniões da LP.

### 1.2 Exact (boxes) e `/slots` do Hub nos mesmos dias

Boxes por consultora (`client.listar_boxes`, `GET /Boxes` com `$filter` por `salesRepEmail` e `start`, `scratchpad/item1.py`). `leadId=0` é bloco da agenda; `leadId>0` é reunião.

| Dia | Rodrigues | Amorim |
|---|---|---|
| 26/10 blocos | 08:00–11:30, 09:00–09:30, 10:30–11:30, 12:00–13:30, 14:00–14:45, 18:20–18:50 | 07:00–11:30, 09:00–10:10, 10:30–11:30, 13:30–14:30 |
| 26/10 reuniões | 10:00, 13:30, 15:45, 16:50 (30 min, criada na Exact), 18:00 | 10:00, 11:35 (20 min, criada na Exact), 13:30, 15:00, 16:30, 18:00 |
| 27/10 blocos | **nenhum** | **nenhum** |
| 27/10 reuniões | 10:00, 18:00 | 10:00, 15:00 |
| 28/10 | **nada** | **nada** |

Achado: **a Exact só tem blocos (`leadId=0`) do próximo dia útil.** Contagem de boxes por dia de 12/10 a 07/11 nas duas agendas: blocos existem em todos os dias passados e em 26/10, e nenhum em 27/10 em diante (`processoseletivo@ [... ('2026-10-26','bloco'),6 ... ('2026-10-27','reuniao'),2]`, idem `comercial@`). Os blocos de 26/10 têm ids sequenciais 44204046 a 44204055, nas duas agendas, e pelos vizinhos em `agendamentos.box_id` (44203167 criado 23/10 10:49 e 44205741 criado 23/10 15:56) foram criados de uma vez na sexta 23/10 entre 10:49 e 15:56. Ou seja: alguém (ou alguma rotina) copia a agenda do Google para a Exact **um dia útil por vez**. Os blocos de 26/10 batem com o Google bloco a bloco (ex.: Rodrigues 12:00–13:30 e 18:20–18:50 nos dois).

`/slots` real, agora (sábado 24/10 18:05 UTC), GET puro na rota local (`routes.py:194-222`, `resumo_por_dia` não grava nada):

```
$ curl -s http://127.0.0.1:8001/api/agendamento/slots
{'fallback': False, 'duracao_min': 45, 'fuso': 'America/Sao_Paulo'}
2026-10-27 7 ['13:30', '14:15', '15:00', '15:45', '16:30', '17:15', '18:00']
```

Com `JANELA_DIAS=4` a janela de sábado é 24 a 27/10. Segunda 26 sai vazia porque as duas agendas estão cheias; 28/10 só entra na janela a partir de domingo. Para 28/10 reproduzi a mesma subtração de `slots_livres` em script (mesmas funções `_ocupados_por_nos`, `ocupados_pendentes`, `folga`, `_sobrepoe`); a união calculada para 27/10 bate exatamente com o `/slots` real acima, o que valida o script.

### 1.3 Tabela por consultora e dia

Colunas: candidatos da grade (9 por dia: 10:00, 10:45, 13:30, 14:15, 15:00, 15:45, 16:30, 17:15, 18:00) | oferecidos hoje | dos quais ocupados no Google | regra nova (grade menos Google menos Exact menos nossos menos remarcação pendente, folga de 15 min em volta de tudo).

| Consultora | Dia | Oferecidos hoje | Ocupados no Google | Regra nova |
|---|---|---|---|---|
| Rodrigues | 26/10 | 0 | 0 | 0 |
| Rodrigues | 27/10 | 5 (13:30, 14:15, 15:00, 15:45, 16:30) | 0 | 4 (14:15, 15:00, 15:45, 16:30) |
| Rodrigues | 28/10 | 9 (todos) | **2** | 5 (14:15, 15:00, 15:45, 16:30, 17:15) |
| Amorim | 26/10 | 0 | 0 | 0 |
| Amorim | 27/10 | 4 (13:30, 16:30, 17:15, 18:00) | **1** | 3 (16:30, 17:15, 18:00) |
| Amorim | 28/10 | 9 (todos) | **3** | 5 (15:00, 15:45, 16:30, 17:15, 18:00) |
| **Total** | | **27** | **6 (22%)** | **17** |

**Horários oferecidos hoje que colidem com ocupado no Google** (interseção real, sem folga):

1. ter 27/10 13:30–14:15, Amorim: Google 13:30–14:30. Está no `/slots` real agora. A Rodrigues também está livre nesse horário, então o slot continua na união; o risco é `escolher_consultora` mandar para a Amorim.
2. qua 28/10 10:00–10:45, Amorim: Google 09:00–10:40.
3. qua 28/10 13:30–14:15, Amorim: Google 13:30–14:30.
4. qua 28/10 14:15–15:00, Amorim: Google 13:30–14:30.
5. qua 28/10 10:00–10:45, Rodrigues: Google 10:10–10:40.
6. qua 28/10 18:00–18:45, Rodrigues: Google 18:20–18:50.

Em 28/10, como hoje não há bloco nenhum na Exact, 10:00 sai das **duas** agendas no Google e só é oferecido porque a Exact está vazia. Esse é o mecanismo da queixa: o dia seguinte é protegido (alguém copiou os blocos), D+2 e D+3 não são.

A diferença entre "oferecidos menos colisões" e "regra nova" vem da folga de 15 min aplicada também aos blocos do Google (ex.: Rodrigues 27/10 13:30 encosta no fim do almoço 12:00–13:30 e sai; Amorim 28/10 10:45 começa 5 min depois do fim de 09:00–10:40 e sai). Sem folga no Google, a regra nova daria 6 em Amorim 28/10 (`10:45` volta) e 7 em Rodrigues 28/10 (`10:45` e `13:30` voltam). Aplicar ou não a folga ao Google é decisão (§1.5).

Variante medida para referência: expediente corrido 10:00–19:00 sem almoço fixo, só Google decidindo o almoço, folga 15. Amorim 27/10 dá 6 (11:30, 12:15, 16:00, 16:45, 17:30, 18:15), Amorim 28/10 dá 7, Rodrigues 5 e 5. A Amorim não tem almoço no Google em 27 e 28/10, então essa variante passa a oferecer 12:15 para ela. Por isso o almoço fixo da `consultoras.json` deve continuar enquanto ela não bloquear o almoço no Google.

### 1.4 Reuniões Vigentes na Exact que não aparecem ocupadas no Google

**Zero de 15.** `reuniao_status` de 26 a 28/10 tem 15 reuniões Vigentes (13 `origem=hub`, 2 `origem=exact`: 4788932 Amorim 26/10 11:35 e 4789326 Rodrigues 26/10 16:50). Cruzando cada box com `leadId>0` contra o freebusy, todas as 15 estão inteiramente dentro de um bloco ocupado do Google (`google=cobre` em todas as linhas de `scratchpad/item1.out`). Inclui as criadas hoje, ex.: box 44208827 (Rodrigues 27/10 18:00, criado 24/10 14:25).

Leitura: reunião marcada na Exact chega ao Google sozinha (provavelmente pelo convite que a Exact manda ao e-mail da consultora, que o Google põe na agenda; não dá para provar qual mecanismo só com livre/ocupado). Consequência boa para o desenho novo: ler o Google cobre também as reuniões que a SDR marca direto na Exact. A subtração de boxes da Exact continua como segunda fonte (o Google pode atrasar alguns minutos para refletir um convite).

Observação fora do escopo (é do Item 2): a pessoa 19****02 (nome omitido) tem **duas** reuniões Vigentes no mesmo horário, 27/10 10:00, uma com cada consultora (boxes 44208796 lead 53195657 e 44208797 lead 53195760, criados 24/10 09:27 e 09:32).

### 1.5 Plano

Diff mínimo, sem sprint anterior para reaproveitar:

1. **Módulo novo `app/agendamento/google_ocupado.py`** (não reaproveitar `google_calendar.py`, que é síncrono e fixo em 8h–18h): uma única `freebusy.query` com os e-mails de todas as consultoras em `items`, janela `[min candidato, max candidato + 1 dia]`, `calendar.readonly`, executada em `asyncio.to_thread`. Devolve `{email: [(ini, fim)]}` naive SP. Cache de 60 s junto do cache de `slots_livres`.
2. **`disponibilidade.slots_livres`** (`disponibilidade.py:203-233`): somar os blocos do Google a `ocupados` antes do alargamento da folga (`:225`). Um ponto só; agente (`qualificacao_fluxo.py:1034,1095,1847`), no-show (`noshow.py:404`), remarcação (`remarcacao.py:414`) e LP (`routes.py:202`) herdam, porque todos passam por `slots_livres`/`resumo_por_dia`.
3. **Expediente = janelas de `consultoras.json`**, sem regra de título. Hoje `10:00–12:00 + 13:30–19:00`; trocar pela grade que a Isa confirmar.
4. **Flag `GOOGLE_GRADE_ENABLED`** no `.env`, desligada por padrão; ligar depois de um dia de comparação em log (o que sairia da grade com o Google).
5. **Falha do Google**: se a consulta der erro, a consultora fica com a grade de hoje (Exact + nossos) e o log grita. Alternativa mais conservadora é tirar a consultora da rodada, como `disponibilidade.py:211-216` faz com a Exact. Decisão abaixo.
6. **Testes**: unitários da subtração com freebusy falso (sem rede), seguindo `test_folga_agenda.py`.

Estimativa: **1 dia** de código e testes, **0,5 dia** de comparação em log com a flag desligada e virada da chave. Sem dependência externa: o acesso livre/ocupado já funciona hoje (medido acima).

Efeito esperado, medido nos 3 dias: 6 dos 27 pares horário/consultora oferecidos (22%) deixam de ser oferecidos por colisão, e mais 4 saem pela folga. A cópia manual de blocos do dia seguinte para a Exact deixa de ser necessária.

**Decisões pendentes**

- Expediente real de cada consultora (o `10:00–12:00 + 13:30–19:00` é provisório). Rodrigues tem bloco fixo 18:20–18:50 e Amorim 09:00–10:40: são compromissos ou só "não marcar"? Com livre/ocupado, tanto faz; vira ocupado.
- Folga de 15 min vale também em volta dos blocos do Google? Medido: custa 4 horários em 3 dias.
- Google fora do ar: oferecer com a grade antiga (risco de colisão) ou tirar a consultora (risco de oferta zero)?
- Almoço fixo: manter na `consultoras.json` (recomendado: a Amorim não bloqueia almoço no Google em 27 e 28/10) ou pedir que cada uma bloqueie no Google?

**Perguntas para a Isa**

1. Quem copia os blocos do Google para a Exact um dia antes (os de 26/10 foram criados na sexta 23/10 entre 10:49 e 15:56)? Com o Hub lendo o Google isso pode parar.
2. Qual o expediente de cada Victória, por dia da semana?
3. A Amorim almoça em que horário? No Google dela não há bloco de almoço em 27 e 28/10.
4. Confirma que, ligando isto, elas passam a bloquear no Google tudo que não podem (reunião interna, follow, almoço), e não precisam mais marcar nada na Exact?

## §2 Item 2. Bloqueio de nova aplicação depois do agendamento

**Resumo:** em 30 dias, 50 pessoas (por `chave_telefone`) aplicaram 2 ou mais vezes e geraram 63 leads a mais na Exact. Em 6 dessas pessoas já havia reunião Vigente no momento da nova aplicação (5 com certeza e 1 incerta). **Duas pessoas ficaram com 2 reuniões Vigentes no MESMO horário, uma com cada consultora**, e uma delas está assim agora: 27/10 às 10:00, com a Rodrigues e com a Amorim (conferido na Exact hoje, ver 2.1.5). A trava por reunião Vigente resolve esse dano. Os outros 57 leads a mais vêm de quem reaplica sem ter reunião (42 em menos de 10 minutos), e isso é uma decisão à parte (2.4, D3).

### 2.1 Medição (24/09 a 24/10/2026)

#### 2.1.1 Como foi medido e o que é aproximação

- **Janela:** `agendamentos.created_at` de `2026-09-24 00:00` a `2026-10-24 23:59` (SP naive, como a tabela grava).
- **Pessoa:** `chave_telefone` (DDD + 8 últimos, `backend/app/telefone.py:101-113`) reimplementada em SQL na sessão. Linha com chave vazia fica de fora.
- **Predicado de teste:** o mesmo de `backend/app/relatorios.py:216`, **ancorado** (`(^\s*zz|smoke|teste|\mtest|john doe|fafaf|alefe|thobias justino)`), sobre `exact_leads.name` sem acento, com a regra de `chaves_de_teste` (`relatorios.py:299-345`): sai a chave que tem 2 ou mais leads de nome de teste ou que nunca mandou inbound. Resultado: **20 chaves excluídas**. Além disso, o mesmo predicado é aplicado direto em `agendamentos.nome`.
- **"Aplicação":** linha com `lead_externo = false` e `lead_id` preenchido, ou seja, um `LeadsAdd` que deu certo. Explicação: a LP é de duas etapas (`agendar.py:38-41`): `POST /lead` cria o lead (`lead_criado`, `lead_externo=f`) e o `POST /agendar` agenda **o mesmo** lead (`agendado`, `lead_externo=t`). Uma pessoa que aplicou **uma vez** e agendou já tem **2 linhas**. Por isso "2+ linhas em qualquer passo" mede o fluxo, não duplicidade:

```
passo        | lead_externo | linhas | lead_ids distintos   (30 dias, sem filtro de teste)
agendado     | t            |   160  | 160
falhou       | f            |     1  |   0
falhou       | t            |    10  |   8
lead_criado  | f            |   400  | 400
recusado     | f            |    35  |   0
```

- **"Reunião Vigente no instante t":** não existe histórico de status (a memória já registra isso para etapa; aqui vale o mesmo). `reuniao_status` (`backend/migrate_reuniao_status.py:104-130`) guarda o status ATUAL e `exact_type_visto_em` = quando o status atual foi visto pela primeira vez (`backend/app/reuniao_sync.py:184-207`). A reconstrução usada:
  - Vigente em t se `registrado_em <= t` e `t < fim_vigência`;
  - `fim_vigência` = `slot_inicio` para Vigente e Concluido; para Cancelada, `least(cancelado_em, exact_type_visto_em, slot_inicio)`. `cancelado_em` só é escrito pela nossa régua (`backend/app/confirmacao.py:751,1095,1121,1186`); cancelamento feito na Exact só aparece pelo `exact_type_visto_em`, com até 10 min de atraso (`reuniao_sync.py:60`, `INTERVALO_SEGUNDOS = 600`).
  - **Incerteza:** o primeiro ciclo do sync foi em 07/10 06:39 e carimbou 155 reuniões Cancelada com esse horário. Para essas, a hora do cancelamento é desconhecida (está entre `registrado_em` e 07/10 06:39). Elas são contadas à parte como "incertas".

```
$ psql -c "select date_trunc('minute',exact_type_visto_em) m, count(*) from reuniao_status
           where exact_type='Cancelada' group by 1 order by 2 desc limit 3"
 2026-10-07 06:39:00 | 155
 2026-10-09 14:30:00 |  10
 2026-10-13 12:08:00 |   2
```

- `reuniao_status` cobre as reuniões **registradas desde 07/09** (cursor, `migrate_reuniao_status.py:64-73`), da LP (`origem=hub`) e do SDR (`origem=exact`): 386 linhas hoje. Para a janela de 30 dias, a cobertura é completa.
- Tudo foi feito com `SELECT` e `CREATE TEMP TABLE` (morre com a sessão). O script está em `scratchpad/item2.sql` e não foi para o repo.

#### 2.1.2 Números

```
linhas úteis (após filtro de teste)          595 linhas, 345 pessoas
pessoas com 2+ linhas (qualquer passo)       186   <- efeito das duas etapas, NÃO é duplicidade
pessoas com 2+ linhas sem contar recusado    183
pessoas com 2+ aplicações (2+ LeadsAdd)       50   (113 aplicações, 63 leads a mais)
distribuição de aplicações por pessoa        1: 282 · 2: 40 · 3: 7 · 4: 3
```

Intervalo entre uma aplicação e a anterior da mesma pessoa (63 intervalos):

```
< 10 min        42 (37 pessoas)   <- voltou ao formulário na mesma sessão
10 min a 1 dia   3
1 a 7 dias      11
> 7 dias         7
mesmo curso (sub_source) que a anterior: 57 · curso diferente: 6
```

**Quantas tinham reunião Vigente no momento da nova aplicação:**

```
na 2ª aplicação:                         4 com certeza, +1 incerta
em qualquer aplicação a partir da 2ª:    5 pessoas com certeza, 6 contando a incerta (5 aplicações)
```

Conferência sem `reuniao_status`, só com a nossa tabela (aplicação a partir da 2ª com um `agendado` anterior cujo `slot_inicio` ainda não tinha passado): **6 pessoas, 6 aplicações**. Os dois caminhos batem.

**Quantas terminaram com 2 reuniões Vigentes ao mesmo tempo** (pares da mesma chave com intervalos de vigência sobrepostos e a sobreposição começando na janela):

```
pares simultâneos               9 pares, 9 pessoas (7 sem incerteza)
com consultoras diferentes      5 pessoas (4 sem incerteza)
nenhuma das duas cancelada      1 pessoa
por origem: exact+exact 6 · hub+hub 2 · hub+exact 1
```

Leitura: **6 dos 9 pares são exact+exact**, ou seja, reuniões criadas pelo SDR na Exact (remarcação manual em que a antiga foi cancelada depois). Não passam pela LP e a trava da LP não atinge. **Os 2 pares hub+hub são exatamente o caso do comercial**: a pessoa reaplicou pela LP e marcou o mesmo horário com a outra consultora.

#### 2.1.3 Por que a segunda reunião cai com a outra consultora

A grade é a **união** das grades das consultoras (`agendar.py:296-307`). Quando a pessoa marca 10:00 com a Rodrigues, o box dela ocupa só a agenda da Rodrigues; a Amorim continua livre às 10:00, então o `/slots` continua oferecendo 10:00. Na reaplicação, o `BoxesAdd` na Rodrigues dá `Boxes are occupied` e o fluxo tenta a próxima (`agendar.py:376-395`), que é a Amorim. Resultado: o mesmo horário, com duas consultoras. É o "às vezes com outra consultora" do pedido.

#### 2.1.4 Cinco exemplos (telefone mascarado, nome omitido)

```
tel       aplicação k  aplicou em           lead nova   reunião já existente: id, registrada em, slot, consultora, status hoje
18****45  2ª           19/10 09:56          52962730    4783424, 18/10 05:45, 21/10 10:00, processoseletivo, Cancelada (vista 21/10 10:13)
          -> agendou de novo 19/10 09:57: reunião 4783634, 21/10 10:00, comercial    MESMO HORÁRIO, OUTRA CONSULTORA
19****02  2ª           24/10 09:31          53195760    4789461, 24/10 09:27, 27/10 10:00, processoseletivo, Vigente
          -> agendou de novo 24/10 09:32: reunião 4789462, 27/10 10:00, comercial    MESMO HORÁRIO, OUTRA CONSULTORA, AS DUAS VIGENTES HOJE
          (1ª aplicação Pos Psicologia na RAPS T3, 2ª Pos Psicologia Clinica T2)
55****55  3ª           06/10 11:26          52504390    4774102, 06/10 11:24, 09/10 18:15, processoseletivo, Vigente (não agendou de novo)
96****93  2ª           21/10 08:02          53047272    4785878, 21/10 08:01, 23/10 17:15, processoseletivo, Cancelada (não agendou de novo)
88****49  2ª           14/10 11:39          52771184    4779344, 13/10 14:23, 14/10 13:45, comercial, Concluido (não agendou de novo)
```

O sexto caso (82****44, 29/09 12:10) é o incerto: a reunião 4767998 está entre as 155 Canceladas carimbadas em 07/10.

Dois casos de "agendou 2 vezes" que **não** são duplicidade (a primeira reunião já tinha passado quando a pessoa voltou): 21****51 (reunião 23/10 16:30, Cancelada; voltou 23/10 21:29 e marcou 26/10 15:00) e 21****89 (três reuniões em 08/10, 16/10 e 22/10, cada uma marcada depois da anterior passar). A trava não deve pegar esses dois: o critério precisa ser `slot_inicio > agora`, não só `exact_type = 'Vigente'`. Exemplo: a 4779236 (16/10 18:15) continua Vigente hoje, oito dias depois do horário, porque ninguém fechou na Exact.

#### 2.1.5 Conferência na Exact (GET, somente leitura)

```
$ curl -s -G "https://api.exactspotter.com/v3/Meetings" \
    --data-urlencode '$filter=lead/id eq 53195657' -H "token_exact: $TOK"
  4789461 Vigente 2026-10-27T10:00:00 processoseletivo@cenatcursos.com.br
$ curl ... '$filter=lead/id eq 53195760'
  4789462 Vigente 2026-10-27T10:00:00 comercial@cenatcursos.com.br
```

**Ação operacional fora desta auditoria:** a pessoa 19****02 tem hoje duas reuniões Vigentes na segunda 27/10 às 10:00, uma com cada consultora. Alguém do comercial precisa cancelar uma das duas na Exact. Nada foi escrito.

### 2.2 Onde a LP decide criar lead (código)

- **A única trava hoje é `_duplo_clique`** (`backend/app/agendamento/agendar.py:227-237`), que olha uma janela de **90 segundos**, não minutos (`agendar.py:131`, `JANELA_DUPLO_CLIQUE = timedelta(seconds=90)`). Ela compara `Agendamento.telefone == telefone` **bruto**, não `chave_telefone`, e só olha linhas `agendado`. Quem volta em 2 minutos, ou digita o telefone com 55 na segunda vez, passa.
- **`agendar()`** (`agendar.py:285-528`, a linha 280-360 do brief deslocou): a trava é chamada em `agendar.py:333`, **depois** da validação do slot, da origem e do lead externo, e **antes** da linha `iniciado` (`:344-360`), da fila do RD (`:372`) e do `BoxesAdd` (`:376-395`). Sem `lead_id`, chama `client.criar_lead` (`:437-443`); com `lead_id` (o caminho de duas etapas), pula o `LeadsAdd` e só verifica (`:428-436`). **Na duplicidade real, o lead novo NÃO nasce no `/agendar`; nasce no `POST /lead` do index**, que vem antes.
- **`cadastrar_lead_sem_agendar()`** (`agendar.py:617-680`, era :592-660 no brief): **confirmado, cria lead novo a cada chamada**. Não consulta nada antes: grava a linha `iniciado` (`:629-643`), enfileira no RD (`:646-649`) e chama `client.criar_lead` incondicionalmente (`:651-657`), depois agenda a abertura do agente (`:672`). Não há trava nem de 90 segundos aqui.
- As mesmas duas funções são chamadas pelas rotas do link com token (espontâneo): `routes.py:507` e `routes.py:568`.
- **Outros chamadores de `fluxo.agendar`:** o agente (`backend/app/qualificacao_fluxo.py:1931`) e a remarcação (`backend/app/remarcacao.py:471-473`). Os dois passam `origem_ip=None` e `lead_id`. **Por isso a trava NÃO pode ir dentro de `fluxo.agendar`**: ela bloquearia a remarcação, que cria a reunião nova enquanto a antiga pode ainda aparecer como Vigente no espelho por até 10 minutos. A trava vai nas **rotas públicas**.
- O agente já tem trava própria: `reuniao_de` (`qualificacao_fluxo.py:693-753`, deslocada da :571 do brief) procura por telefone tolerante (`formas_gravadas`) uma linha `agendado` em `agendamentos`. Ela **não** olha `reuniao_status` nem se a reunião está Vigente e futura. O predicado certo para a LP já existe em dois lugares e pode ser reaproveitado: `confirmacao.py:892-895` (`telefone_chave == chave`, `exact_type == 'Vigente'`, `slot_inicio > agora`) e `qualificacao_guard.py:387-390`.
- O espelho em `reuniao_status` de uma reunião feita **pela LP** nasce na hora (`agendar.py:582-583`, `espelhar_agendamento`). A reunião feita **pelo SDR na Exact** aparece em até 10 minutos (`reuniao_sync.py:60`). Esse é o atraso máximo da trava.

### 2.3 O que a página de obrigado consegue mostrar

- As duas páginas leem JSON do backend:
  - `docs/form-nativo-snippet.html:163-188`: `POST /lead`; com 2xx **e** `corpo.lead_id`, redireciona para `obrigado.html?lead=ID&nome=&email=&tel=` (`:118-126`). Qualquer outra resposta redireciona **sem** `lead=`.
  - `docs/obrigado-snippet.html:201-213`: `GET /slots` (não conhece a pessoa, então não dá para personalizar ali); `:229-266`: `POST /agendar` (ou `/lead` sem grade); `:269-282` `confirmar(d)`: com `d.inicio` mostra **"Agendado! <dia da semana>, <dia> de <mês> às HH:MM"**, sem `inicio` mostra "Recebemos seu contato!", e sempre o aviso "Precisa remarcar ou cancelar? Fale com a gente pelo WhatsApp". Não há link para o WhatsApp, só o texto.
- **Consequência para a compatibilidade:** as LPs são publicadas fora daqui (Netlify e WordPress, `docs/AGENDAMENTO.md:624-629`), e a experiência do alias DH T4 mostra que republicar uma LP demora. Portanto a resposta nova precisa funcionar **com os snippets já publicados**:

| resposta do backend para quem já tem reunião | snippet antigo faz | serve? |
|---|---|---|
| `POST /lead` 200 com `lead_id` = lead da reunião existente e `ja_agendado: true` | redireciona com `?lead=` do lead existente | sim |
| `POST /agendar` 200 com `inicio`/`fim` **da reunião existente**, `consultora_nome` e `ja_agendado: true` | mostra "Agendado! <data da reunião existente>" | sim, e mostra a data certa |
| `POST /agendar` 409 | "Esse horário acabou de ser preenchido" e recarrega a grade | não |
| qualquer 4xx com `detail` | mostra o `detail` como erro | aceitável, mas parece falha |

  O formato 200 é o mesmo que `_duplo_clique` já devolve hoje (`agendar.py:333-342` e `routes.py:286-304`), só que sem a janela de 90 segundos e pela chave do telefone. É o menor diff possível e não depende de republicar LP. O snippet novo só **acrescenta**: com `ja_agendado`, troca o texto para "Você já tem uma conversa marcada para <data> com <consultora>" e mostra um botão "Remarcar pelo WhatsApp" (`wa.me` do número do agente).

- **Risco de privacidade (precisa de decisão, D2):** `/agendar` e `/lead` são públicos. Devolver data, hora e nome da consultora para **qualquer telefone digitado** permite que alguém descubra que uma terceira pessoa tem reunião marcada. O `/agendar` hoje já devolve `consultora_nome`, mas só para quem acabou de agendar. Mitigações possíveis: mostrar os detalhes só quando o primeiro nome ou o e-mail batem com os da reunião existente; caso contrário, uma mensagem genérica ("já recebemos seu contato, fale com a gente pelo WhatsApp") sem data nem consultora.

### 2.4 Plano proposto

1. **`reuniao_vigente_futura(chave, db)`** (perto de `reuniao_sync.py`, reaproveitando o predicado de `confirmacao.py:892-895`): devolve a `ReuniaoStatus` Vigente com `slot_inicio > agora` mais próxima, ou None. Também cobre a reunião que o SDR marcou na Exact (com até 10 min de atraso).
2. **Trava nas rotas públicas**, antes de qualquer escrita, no lugar onde a validação de entrada já acontece: `POST /agendar` (`routes.py:226`), `POST /lead` (`routes.py:308`) e as duas rotas de token (`routes.py:478`, `:549`). Com reunião: **sem `LeadsAdd`, sem `BoxesAdd`, sem fila do RD, sem abertura do agente**. Resposta 200 no formato compatível da tabela de 2.3, com `ja_agendado: true` e `reuniao: {inicio, fim, consultora_nome}`. `fluxo.agendar` e `cadastrar_lead_sem_agendar` ficam como estão (agente e remarcação continuam passando).
3. **Registro para o relatório:** em vez de um passo novo `ja_agendado`, recomendo **reaproveitar o rastro** (`backend/app/agendamento/rastro.py`): `passo='recusado'`, `motivo_recusa='ja_agendado'`, ao lado do `duplo_clique` que já existe (`rastro.py:51`). As invariantes da linha recusada (`rastro.py:16-31`: sem `lead_id`, sem box, sem consultora, fora do RD e da Exact, fora da carga das consultoras) são exatamente as que esta linha precisa, e `relatorios.py:428-452` não passa a contar nada errado. Um passo novo exigiria revisar todo leitor de `agendamentos.passo` (faxina, carga, relatórios, `reuniao_de`). O `meeting_id` existente e o curso pedido vão no `erro`/`sub_source`/`extras`, que a linha já guarda.
4. **Snippets:** `obrigado-snippet.html` ganha o ramo `ja_agendado` (texto + botão WhatsApp); `form-nativo-snippet.html` não precisa mudar (o `lead_id` existente já faz o resto). Atualizar `docs/AGENDAMENTO.md` (seção de respostas e §3.5 do rastro).
5. **Corrigir de carona o `_duplo_clique`** para comparar por chave e não pelo telefone bruto (fica redundante com a trava para `agendado`, mas continua útil para a corrida de dois cliques antes do espelho).
6. **Testes:** reaplicação com reunião Vigente futura (LP e SDR), Vigente com slot passado (não trava), Cancelada (não trava), telefone com e sem 55 e com e sem 9º dígito, snippet antigo recebendo o 200, agente e remarcação não afetados.

**Estimativa:** backend 0,5 dia; testes 0,5 dia; snippet e doc 0,5 dia. **Total de 1,5 dia** de desenvolvimento, mais a republicação das LPs, que não está nas nossas mãos (o comportamento principal funciona sem ela).

**O que a trava NÃO resolve:** 57 dos 63 leads a mais vêm de quem reaplica **sem** reunião, a maioria (42) em menos de 10 minutos. Esses continuam virando 2 leads na Exact (D3).

### 2.5 Decisões pendentes e perguntas para a Isa

- **D1. Curso diferente.** O caso 19****02 reaplicou para **outro curso** (RAPS T3 e depois Psicologia Clínica T2). Com a trava, o segundo interesse não vira lead; fica só na nossa tabela. Isso basta, ou vale escrever uma nota na timeline do lead existente ("aplicou também para X") com `timelineAdd` (já usado em `app/exact_notes.py`)?
- **D2. Privacidade.** Mostrar data e consultora para qualquer telefone digitado, ou só quando nome ou e-mail batem (mensagem genérica no outro caso)?
- **D3. Reaplicação sem reunião.** Os 42 retornos em menos de 10 minutos (e os 21 mais espaçados) devem reaproveitar o lead anterior (devolver o `lead_id` mais recente da mesma chave dentro de N horas) em vez de criar outro? Isso reduziria a maior parte dos 63 leads a mais, mas muda a regra "um lead por aplicação" da Exact, que o comercial pode estar usando para contar aplicações.
- **D4. Remarcar pelo WhatsApp.** O botão abre conversa com qual número: o do agente (canal da boas-vindas) ou o da consultora (`consultoras.json` tem telefone)? Lembrando que a criação da reunião nova depois do cancelamento na remarcação ainda não foi provada com caso real (5cc59fa, 19/10).
- **D5. RD Station.** Hoje toda submissão vai para a fila do RD (`agendar.py:372`, `:646`). A reaplicação travada deve ir também (o RD quer saber de quem preencheu) ou não (é a mesma pessoa)? A recomendação do item 3 acima é não ir.
- **D6. Os 6 pares exact+exact** são reuniões marcadas pelo SDR sem cancelar a anterior na hora. Não é escopo deste pedido, mas é a maior fonte de "duas reuniões ao mesmo tempo" medida (6 de 9). Vale um aviso ao SDR?

## §3 Item 3. campos personalizados da Spotter

**Resposta curta:** a API da Exact **declara e documenta** escrita de campo personalizado no próprio `LeadsAdd` (e no `LeadsUpdate`). Os campos que o comercial quer já existem na conta: `Possui Graduação?` e `investimento pós graduação online`, e hoje são **preenchidos à mão**: 137 leads da LP desde 19/09 têm `Possui Graduação?` e 118 têm o investimento, enquanto outros 321 leads da LP do mesmo período estão sem nada. Nós nunca mandamos `customFields`: os extras vão só para o `description`. A única coisa que não dá para provar sem escrever é se a conta aceita o payload de verdade, e o teste controlado está em 3.5.

### 3.1 `$metadata`: existe custom field no lead?

Existe, em três lugares.

```bash
curl -s -H "token_exact: $TOKEN" "https://api.exactspotter.com/v3/\$metadata"   # 200, 64165 bytes
```

**(a) No payload de criação e atualização.** `LeadsAdd` e `LeadsUpdate` usam o mesmo DTO (`LeadCriacaoAtualizacaoODataDTO`: `lead`, `key`, `duplicityValidation`, `validateEmail`, `linkedIn`). O `lead` é este `ComplexType`, que termina em `customFields`:

```xml
<ComplexType Name="LeadEstruturaCriacaoODataDTO">
  <Property Name="name" .../> ... <Property Name="description" Type="Edm.String" /> ...
  <Property Name="funnelId" Type="Edm.Int32" /> ... <Property Name="stage" Type="Edm.String" />
  <NavigationProperty Name="customFields" Type="Collection(Exact.LeadCampoPersonalizadoODataDTO)" />
</ComplexType>
<EntityType Name="LeadCampoPersonalizadoODataDTO"><Key><PropertyRef Name="id" /></Key>
  <Property Name="id" Type="Edm.String" Nullable="false" />
  <Property Name="value" Type="Edm.String" />
  <Property Name="options" Type="Collection(Exact.KeyValueODataDTO)" />
</EntityType>
```

**(b) Na leitura do lead, NÃO.** `LeadODataDTO` (o `GET /Leads`) não tem `customFields`. Confirmado com `$expand` em 3.2.

**(c) EntitySets próprios:**

| EntitySet | DTO | Para quê | GET hoje |
|---|---|---|---|
| `CustomFields` | `CampoPersonalizadoODataDTO {id, name, key, type, options, required, onlyApi, ...}` | definição dos campos | 200 |
| `CustomFieldsLeads` | `CustomFieldsLeadsDTO {id, key, value, leadId, type, options, registerDate}` | valores por lead | 200, filtro só por `leadId` (ver abaixo) |
| `LeadsCustomFields` | `LeadsCustomFieldsDTO` | idem | **500** "An error has occurred." |
| `CustomFieldsHistories` | `CampoPersonalizadoHistoricoODataDTO {leadId, name, value, userId, ...}` | quem preencheu | **400** timeout sem filtro; com `$filter=leadId eq` dá 400 "Could not find a property named 'leadId' on type 'Exact.CampoPersonalizadoODataDTO'" (rota amarrada ao DTO errado) |
| `CustomFieldsAdd` | `CampoPersonalizadoAdicaoODataDTO` | CRIAR definição de campo | não chamado (escrita) |
| `CustomFieldsLeadsRemove` | `{id, customFieldId}` | apagar valor | não chamado (escrita) |

Tipos (`eTipoAtributo`): `Texto=0, TextoLongo=1, Numero=2, EscolhaUnica=3, EscolhaMultipla=4, Link=5`.

Bug de rota da Exact anotado: em `CustomFieldsLeads`, `$filter=key eq '...'` dá 400 "Could not find a property named 'key' on type 'Exact.LeadsCustomFieldsDTO'", e `$filter=id eq 136998` dá 400 de tipo (o filtro valida contra um DTO, a resposta sai de outro). **Só `leadId` filtra.** Por isso as contagens abaixo varrem por faixa de `leadId`.

### 3.2 Um lead recente da LP e onde estão graduação e investimento

Lead 53203017, criado pela LP em 24/10 14:52 SP (`agendamentos.id = 1345`, `passo = lead_criado`).

```bash
curl -s -G -H "token_exact: $TOKEN" "https://api.exactspotter.com/v3/Leads" --data-urlencode "\$filter=id eq 53203017"
```

```json
{
 "lead": "<omitido>", "registerDate": "2026-10-24T17:52:34.3357102Z",
 "phone1": "<omitido>", "phone2": null, "telephones": "<omitido>",
 "description": "E-mail: <omitido> | Profissão: Enfermagem | Ensino Superior: Sim | Ano de formação: 2026 | Como conheceu: Facebook | Investimento possível: Não | Pergunta de investimento: O investimento de R$272,00 mensal seria possível para você?",
 "stage": "Entrada", "funnelId": 18535, "id": 53203017,
 "source": {"id": 140648, "value": "Landing Page"},
 "subSource": {"id": 176822, "value": "Pos Enfermagem em Saude Mental"},
 "sdr": {"id": 443275, "name": "Thobias", "email": "sdr@cenatsaudemental.com", "active": false},
 "salesRep": {"id": null, ...}
}
```

Graduação e investimento estão **só no `description`**, como texto. Não há chave de campo personalizado no JSON, e o `$expand` não existe:

```bash
curl ... "/Leads" --data-urlencode "\$filter=id eq 53203017" --data-urlencode "\$expand=customFields"
# HTTP 400 {"error":{"message":"Could not find a property named 'customFields' on type 'Exact.LeadODataDTO'."}}
curl ... "/CustomFieldsLeads" --data-urlencode "\$filter=leadId eq 53203017"
# HTTP 200 {"value":[]}     <- nenhum campo personalizado neste lead
```

**Leads que o comercial preencheu à mão existem, e são muitos.** Varredura de todos os valores de campo personalizado de leads com `leadId > 52000000` (546 linhas, 2 páginas, sem `nextLink` restante), cruzada com `agendamentos` (leads da LP, `lead_externo = false`, criados de 19/09 a 24/10: 458 leads):

```bash
curl -s -G -H "token_exact: $TOKEN" ".../CustomFieldsLeads" \
  --data-urlencode "\$filter=leadId gt 52000000" --data-urlencode "\$orderby=leadId desc" --data-urlencode "\$top=500"   # + $skip=500
```

| campo (`key`) | leads com valor | dos quais são da LP |
|---|---|---|
| `_possuigraduacao` | 162 | **137** |
| `_investimentoposgraduacaoonline` | 147 | **118** |
| `_situacao` | 129 | 125 |
| `_canalposgraduacao` | 108 | 105 |
| leads da LP **sem** `_possuigraduacao` | | **321 de 458** |

Exemplo (lead 52509719, LP de 06/10): a LP mandou `Ensino Superior: Sim | Investimento possível: Sim`; na Exact alguém pôs `_possuigraduacao = Sim` e `_investimentoposgraduacaoonline = De R$200,00 a R$300,00`. Ou seja: o SDR **redigita** o que já está no `description`, e no investimento escolhe uma faixa que a LP atual nem perguntou. O último valor manual é de 22/10 (`_canalposgraduacao`, lead 53103449, `registerDate 2026-10-22T12:15:14Z`).

Quem preencheu não é verificável pela API: `CustomFieldsHistories` (que tem `userId`) está quebrado, ver 3.1.

### 3.3 `LeadsAdd` aceita custom fields?

**Pelo `$metadata`, sim** (3.1 a). **Pela documentação oficial, sim**, com exemplo. A doc pública (blueprint Apiary, `https://jsapi.apiary.io/apis/exactspotter.apib`, 228 KB, título "API - Exact Spotter V2" mas `HOST: https://api.exactspotter.com/v3/`), seção `## Leads - Inserção [/LeadsAdd]`:

> "Também é possível neste momento fazer a criação de campos personalizados para este lead"
> "Campos utilizados para o Custom Fields: id = identificação do campo personalizado; value = valor ... quando o campo personalizado for do tipo que contenha mais de uma opção, o usuário pode entrar com o value, o identificador da opção ou ambos."

```json
"customFields": [
  {"id": "_valordoticket", "value": "150,00"},
  {"id": "_escolhamultipla", "options": [{"value": "Opção 1"}, {"id": 3128}, {"id": 3128, "value": "Opção 1"}]}
]
```

O `id` é a **`key`** do campo (com sublinhado), não o número. Na seção `## Leads - Atualização [/LeadsUpdate/{id}]`: "O "id" será a "key" do campo personalizado; Para "options" o "id" será o id da opção", verbo **`PUT /LeadsUpdate/{id}`**.

**Achado lateral sobre o `LeadsUpdate`:** o 404 registrado em `TESTE_FOLLOW_ESTAGIO_20260927_REPORT.md:106` foi `POST /LeadsUpdate` com `key` no corpo. A doc manda `PUT /LeadsUpdate/{id}`. O 404 pode ter sido rota errada, não ausência do recurso. Isso importa porque o agendamento pelo agente (com `lead_id`) pula o `LeadsAdd` (`agendar.py:436-437`) e só um `LeadsUpdate` levaria campos para esse lead. **Não testado (seria escrita).** Cuidado: o `LeadsUpdate` documentado manda o lead inteiro; se ele sobrescrever `description` ou `subSource` com vazio, apaga o e-mail e os extras. Precisa de teste em lead de teste antes de qualquer uso.

Endpoints separados: só `CustomFieldsAdd` (cria a DEFINIÇÃO de um campo, não o valor) e `CustomFieldsLeadsRemove` (apaga valor). Não existe `CustomFieldsLeadsAdd`: o valor por lead se escreve pelo `LeadsAdd`/`LeadsUpdate`.

**O que o código faz hoje:**

- `backend/app/agendamento/client.py:181-191` monta `lead = {name, source, subSource, funnelId, ddiPhone, phone}` + `description`, e `POST /LeadsAdd`. Nenhum `customFields`.
- `backend/app/agendamento/extras.py:133-160` (`montar_descricao`) junta `E-mail: ... | chave: valor | ...` com orçamento de 4000 caracteres.
- Chamado em `backend/app/agendamento/agendar.py:440-445` (`agendar`) e `:653-658` (`cadastrar_lead_sem_agendar`).
- Docstring de `extras.py:1-15`: os extras têm dois destinos, `agendamentos.extras` (JSONB) e `description`. Campo personalizado nunca foi considerado; `AGENDAMENTO_FINDINGS.md:1345-1346` lista `LeadsCustomFields` e `CustomFieldsLeads` no inventário mas sem uso.

### 3.4 De/para

Campos personalizados de lead na conta (`GET /v3/CustomFields`, 200, 4 itens, `$skip=500` vem vazio):

| id | name | key | type | opções (id: valor) |
|---|---|---|---|---|
| 129875 | Canal Pós graduação: | `_canalposgraduacao` | Texto | |
| 136998 | Possui Graduação? | `_possuigraduacao` | EscolhaUnica | 136999: Sim, 137000: Não |
| 137001 | investimento pós graduação online | `_investimentoposgraduacaoonline` | EscolhaUnica | 137002: Até R$100,00, 137003: De R$100,00 a R$200,00, 137004: De R$200,00 a R$300,00, 137005: De R$300,00 a R$400,00 |
| 138177 | Situação | `_situacao` | EscolhaUnica | 138178: Reagendamento |

Há também `_profissao` (id 88645, TextoLongo) e `_datadecriacao`/`_datadoultimocontato` com valores em leads de fev/2025 (`CustomFieldsLeads leadId eq 31559765`), mas eles **não aparecem** no `GET /CustomFields` atual (`$filter=id eq 88645` volta vazio): campo desativado ou apagado.

Chaves que a LP manda (`agendamentos.extras`, todas as linhas):

| chave da LP | valores medidos | campo na Exact | situação |
|---|---|---|---|
| `Ensino Superior` | Sim 779, Não 65 | `_possuigraduacao` (Sim/Não) | **casa 1:1** |
| `Faixa de investimento` | De R$100,00 a R$200,00 201, De R$200,00 a R$300,00 153, Até R$100,00 122, De R$300,00 a R$400,00 46 | `_investimentoposgraduacaoonline` | **casa 1:1**, texto idêntico às 4 opções. Só 70 aplicações nos últimos 30 dias: as LPs atuais trocaram a pergunta |
| `Investimento possível` + `Pergunta de investimento` | Sim 201, Não 121 ("O investimento de R$272,00 mensal seria possível para você?") | **nenhum** | é a pergunta das LPs atuais (323 de 393 aplicações em 30 dias). Não cabe nas 4 faixas: precisa de campo novo ou de regra (decisão) |
| `Profissão` | texto livre | `_profissao` sumiu da lista | decisão: reativar ou criar |
| `Ano de formação` | texto (298 em 30 dias) | nenhum | decisão |
| `Como conheceu` | Instagram 519, Facebook 98, Google 41, Outro 37, Indicação 35, Já sou aluno 28, WhatsApp 26, YouTube 24 | `_canalposgraduacao`? | os valores manuais são "Não" (95) e "?" (13): não parece ser "como conheceu". Perguntar à Isa |
| (nenhuma) | | `_situacao` = Reagendamento | uso interno do comercial, não é da LP |

### 3.5 Plano proposto

1. **Teste controlado (Fase 0 da sprint, única escrita):** um `LeadsAdd` com nome `zz teste customfields`, telefone de teste, funil 18535, e `customFields: [{"id":"_possuigraduacao","options":[{"id":136999}]}, {"id":"_investimentoposgraduacaoonline","options":[{"value":"De R$100,00 a R$200,00"}]}]`. Reler com `CustomFieldsLeads?$filter=leadId eq X` (insistir: o `description` já demorou a materializar, FINDINGS §13), conferir na UI com a Isa, e `LeadsDelete/{id}` (sem box, limpa 100% segundo FINDINGS §13). Testar também uma opção inválida para ver se a Exact recusa (400) ou ignora calada, porque isso decide se precisamos validar antes. Opcional no mesmo teste: `PUT /LeadsUpdate/{id}` só com `customFields` no lead de teste, relendo depois `description` e `subSource` para ver se o PUT apaga o que não foi enviado.
2. **Código:** um `backend/custom_fields.json` (no molde do `consultoras.json`) ou constante em `extras.py`, com o de/para chave da LP → `key` da Exact + tipo; `extras.montar_custom_fields(extras)` devolve a lista só com o que casa (valor fora das opções é descartado com log, nunca derruba o `LeadsAdd`); `client.criar_lead(..., custom_fields=...)`. O `description` continua igual (decisão já tomada).
3. **Rede:** se o `LeadsAdd` com `customFields` der 400, repetir sem eles (o lead vale mais que o campo) e logar `❌ custom_fields`.
4. **Fora do escopo desta entrega:** o caminho do agente (`lead_id` existente), que dependeria do `LeadsUpdate` provado no passo 1, e backfill dos 321 leads.

**Estimativa:** teste controlado 1h; código + testes 0,5 dia; conferência na UI com a Isa e deploy 1h. **Total ~1 dia.** Se a Exact recusar no teste, o item vira pedido para a Exact com o print do 400 e a citação da doc acima.

**Perguntas para a Isa:**

1. A pergunta atual da LP é "R$272 mensal seria possível? Sim/Não", e o campo da Exact tem 4 faixas. Criamos um campo novo "Investimento R$272 possível?" (Sim/Não), ou o relatório do funil precisa das faixas e a LP deve voltar a perguntar faixa?
2. `Canal Pós graduação:` é "como conheceu"? Os valores preenchidos hoje são "Não" e "?".
3. Profissão e Ano de formação devem virar campo? O campo `_profissao` existia em 2025 e sumiu.
4. Quem preenche hoje `Possui Graduação?` à mão (SDR na ligação?) e deve parar quando a LP passar a preencher?
5. Quer backfill dos leads da LP desde 19/09 que estão sem campo (321)? Isso exige o `LeadsUpdate` provado.

## §4 Item 4. Separação dos usuários no Hub (disparos de vagas afirmativas na lista do SDR)

**Resposta curta:** os contatos de vagas afirmativas aparecem para o Thobias por três motivos somados, e nenhum deles é o canal: (1) **todo mundo no Hub é `admin`**, e admin recebe a lista inteira em `GET /contacts`; (2) a tela de conversas **não filtra por dono por padrão**; (3) **127 dos 159** contatos que a conta "Victória" disparou nos últimos 30 dias **são do Thobias de fato**: o SDR deles na Exact é o Thobias (159 de 159) e foi o próprio Thobias quem mandou o primeiro template de vagas (156 de 159). Existe um único canal. Separar "por canal" não é opção; separar "por dono" sozinho também não resolve, porque o dono é o Thobias.

Achado lateral que muda a premissa: **a conta do Hub chamada "Vi Amorim" (id 3) não enviou nenhuma mensagem desde que `sent_by` existe (01/09).** Quem dispara vagas afirmativas é a conta id 6 "Victória" (`comercialcenat@gmail.com`), que mandou **só** templates de vagas: 372 de 372.

### 4.1 Quem é a "Vi Amorim" no Hub, de onde e o que dispara

```
$ sudo -u postgres psql cenat_whatsapp -c "SELECT id, name, email, role, is_active FROM users ORDER BY id;"
 id |    name    |                  email                   |   role    | is_active
  1 | Álefe Lins | linsalefe@gmail.com                      | admin     | t
  2 | Isa        | isabelaoliveira@cenatcursos.com.br       | admin     | t
  3 | Vi Amorim  | processoseletivo@cenatsaudemental.com    | admin     | t
  4 | Valéria    | processoseletivosdr@cenatsaudemental.com | admin     | t
  5 | Thobias    | sdr@cenatsaudemental.com                 | admin     | t
  6 | Victória   | comercialcenat@gmail.com                 | admin     | t
  7 | Marina     | executivadecarreiras@cenatcursos.com.br  | admin     | t
  8 | Ana        | ana@hub.com                              | atendente | t

$ ... -c "SELECT id, name, phone_number, is_active FROM channels;"
 id |        name         | phone_number  | is_active
  1 | Pós-Graduação (SDR) | 5511952137432 | t
```

Um canal só. Sete de oito usuários são `admin`; não existe papel "SDR" nem "consultora" (`auth_routes.py:23` cria com `role="atendente"`; `frontend/src/app/users/page.tsx:130` só conhece "Administrador" e "Atendente").

**Disparos por autor, 30 dias** (`messages.sent_by`, `direction='outbound'`):

```
 sent_by | channel_id | count | contatos | com_template |    min     |    max
       5 |          1 |  1421 |      406 |          936 | 2026-09-25 | 2026-10-23
       6 |          1 |   372 |      159 |          372 | 2026-10-01 | 2026-10-20
  (NULL) |          1 |  2704 |      531 |         2030 | 2026-09-25 | 2026-10-24
```

Nenhuma linha com `sent_by = 3`. Desde 01/09 (início de `sent_by`, ver memória S6-1) só os ids 2, 5 e 6 aparecem:

```
 sent_by | count |            min             |            max
       2 |    84 | 2026-09-18 17:48:53 | 2026-09-18 18:04:04
       5 |  2708 | 2026-09-01 16:29:38 | 2026-10-23 14:34:11
       6 |   372 | 2026-10-01 19:01:18 | 2026-10-20 13:23:11
```

**Templates de vagas afirmativas, por autor (todo o histórico):**

```
 sent_by |              template_name              | count | contatos |    min     |    max
       5 | vagasafirmativas_1                      |   113 |      107 | 2026-09-23 | 2026-10-23
       5 | follow1_vagasafirmativas_apresentacao   |    68 |       67 | 2026-09-21 | 2026-09-21
       6 | follow2_vagasafirmativas_acompanhamento |   153 |      147 | 2026-10-01 | 2026-10-20
       6 | follow3_vagasafirmativas_despedida      |   144 |      135 | 2026-10-06 | 2026-10-20
       6 | follow1_vagasafirmativas_apresentacao   |    60 |       58 | 2026-10-13 | 2026-10-16
       6 | vagasafirmativas_1                      |    15 |       15 | 2026-10-06 | 2026-10-20
```

O id 6 não mandou nenhum texto livre (`SELECT ... WHERE sent_by=6 AND template_name IS NULL` = 0 linhas): ela só dispara a régua de vagas, em rajadas pela tela de automações (`frontend/src/app/automacoes/page.tsx:494` e `:565` chamam `POST /exact-leads/bulk-send-template`, `exact_routes.py:240`). O desenho operacional que os dados mostram é: **o Thobias manda o `vagasafirmativas_1` um a um (113 envios espalhados em 30 dias), e a Victória (id 6) roda os follows 1, 2 e 3 em lote** (ex.: 13/10 12:15-12:18, 16/10 12:15-12:18, 20/10 13:16-13:23).

**Quem é quem (não resolvido, precisa da Isa).** O pedido fala de "Vi Amorim". Há três pistas que não fecham:

| sinal | aponta para |
|---|---|
| quem dispara vagas no Hub | id 6 "Victória", `comercialcenat@gmail.com` |
| consultora Amorim na agenda (`backend/consultoras.json`) | `comercial@cenatcursos.com.br`, "Victória Amorim" (o prefixo "comercial" bate com o id 6) |
| consultora Rodrigues na agenda | `processoseletivo@cenatcursos.com.br` (o prefixo "processoseletivo" bate com o id 3 "Vi Amorim") |
| `SPRINT_BLOCO1_CONFIRMACAO_20261007_REPORT.md:142` | hipótese oposta, não confirmada: Amorim = id 3, Rodrigues = id 6 |
| `sdr_mapping.py:2-8` | Exact "Victória" → id 6; nenhum nome da Exact leva ao id 3 |

Então: a "Vi Amorim" do pedido, pela operação, é a conta id 6. A conta id 3 "Vi Amorim" está viva só como **dona**: 564 contatos com `assigned_to = 3`, 11 deles criados em outubro, todos atribuídos à mão (`PATCH /contacts/{wa_id}/assign`, `routes.py:644-656`, porque `resolve_sdr_user_id` nunca devolve 3). Não há tabela de login para saber se alguém ainda entra com ela (`\d users` não tem `last_login`).

### 4.2 Dez contatos disparados pela id 6 e por que aparecem para o Thobias

Os 159 contatos disparados pela id 6 em 30 dias, por dono no Hub e com a última mensagem da conversa:

```
   dono    | canal | contatos | ultima_msg_e_da_victoria | ultima_e_resposta_do_lead | thobias_ja_escreveu
 Thobias   |   1   |   127    |           112            |             9             |        126
 Vi Amorim |   1   |    22    |            15            |             7             |         20
 Valéria   |   1   |     5    |             4            |             0             |          5
 Victória  |   1   |     4    |             3            |             1             |          4
 Marina    |   1   |     1    |             1            |             0             |          1
 (total)   |       |   159    |           135            |            17             |        156
```

SDR desses 159 no espelho da Exact (`exact_leads.sdr_name` por telefone): **Thobias, 159 de 159**. O id 6 nunca é dono (só 4 contatos), porque `bulk_send_template` atribui o dono pelo SDR **da Exact**, não por quem apertou enviar, e só se o contato não tiver dono (`exact_routes.py:532-539`).

Amostra de 10 (telefone mascarado, nome omitido; `va` = vagasafirmativas, `f1/f2/f3` = follows; prefixo = `sent_by`):

| tel | dono Hub | canal | lead_status | SDR Exact | último disparo id 6 | templates de vagas no histórico | última msg |
|---|---|---|---|---|---|---|---|
| xx7976 | Marina | 1 | novo | Thobias | 06/10 | 5:f1, 6:f2, 6:f3 | outbound id 6 |
| xx9253 | Thobias | 1 | novo | Thobias | 06/10 | 5:f1, 6:f2, 6:f3 | outbound id 6 |
| xx4800 | Thobias | 1 | novo | Thobias | 06/10 | 5:va_1, 6:f2, 6:f3 | outbound id 6 |
| xx3794 | Thobias | 1 | novo | Thobias | 20/10 | 5:va_1, 6:f1, 6:f2, 6:f3 | outbound id 6 |
| xx2632 | Thobias | 1 | novo | Thobias | 20/10 | 5:va_1, 6:va_1 | outbound id 6 |
| xx6539 | Valéria | 1 | novo | Thobias | 20/10 | 5:va_1, 6:f1, 6:f2 | outbound id 6 |
| xx4952 | Vi Amorim | 1 | novo | Thobias | 20/10 | 5:va_1, 6:f1, 6:f2 | inbound |
| xx7571 | Vi Amorim | 1 | novo | Thobias | 20/10 | 5:f1, 5:va_1, 6:f1, 6:f2, 6:f3 | outbound id 6 |
| xx4937 | Vi Amorim | 1 | novo | Thobias | 20/10 | 5:va_1, 6:f1, 6:f2 | inbound |
| xx9174 | Victória | 1 | novo | Thobias | 20/10 | 5:va_1, 6:f1, 6:f2 | inbound |

Todos `lead_status = novo` (a tela não é usada para marcar estágio nesses contatos).

**Reprodução do filtro da tela para o Thobias:**

- Backend, `routes.py:430-447`: `GET /contacts` só filtra por dono quando `current_user.role != "admin"`. O Thobias é `admin`, então o `WHERE` fica só com `c.channel_id = :channel_id`.
- Frontend, `frontend/src/app/conversations/page.tsx:386-387`: chama `/contacts?channel_id=<canal ativo>`, sem `assigned_to`.
- `page.tsx:250`: `sdrFilter` nasce `null`; `page.tsx:925`: `null` deixa passar todos. O filtro "SDR" (`page.tsx:1270-1300`) é opcional e não persiste.

O SQL efetivo para o Thobias é portanto `SELECT ... FROM contacts c ... WHERE c.channel_id = 1`, ou seja, **os 8 891 contatos**, ordenados pela mensagem mais recente. Como os follows de vagas saem em rajada, eles empurram para o topo da lista dezenas de conversas de uma vez. Peso hoje:

```
 conversas_7d | com_vagas_30d | vagas_dono_thobias
          306 |            90 |                 69
```

**29% das conversas com movimento nos últimos 7 dias (90 de 306) são da régua de vagas**, e 69 delas têm o Thobias como dono.

**Resposta à pergunta do brief:** aparecem (a) porque a tela não filtra por dono por padrão e todo mundo é admin, e (b) porque, mesmo que filtrasse, **o dono é o Thobias** na grande maioria (127/159) e é o Thobias quem abre a conversa com o `vagasafirmativas_1`. Não é por canal (há um só) nem por falta de dono (0 dos 159 estão sem dono).

### 4.3 O que a Vi Amorim (e qualquer um) vê ao entrar

- Login leva a `/dashboard` (`frontend/src/app/login/page.tsx:19,27`).
- Sendo `admin`, a barra lateral mostra tudo, inclusive Templates, Relatórios e Atendimento (`frontend/src/components/Sidebar.tsx:34,40,41,110`).
- Em Conversas, vê os 8 891 contatos do canal 1, igual ao Thobias. **Não existe visão "meus contatos"**: o único recorte por pessoa é o botão do filtro SDR, manual, com a lista de `/auth/users` (`page.tsx:389-393`), que zera ao recarregar.
- O único usuário que hoje veria "só os seus" é a Ana (`atendente`), pela regra de `routes.py:442-443` e `_e_dono_ou_admin` (`routes.py:700-712`).

Já há no código a ideia de "quem é SDR", mas espalhada e fixa: `SDR_USER_IDS=5` no `.env` (linha 90, lido em `remarcacao.py:68,138`) e `SDR_IDS_PERMITIDOS = frozenset({4, 5})` em `nat_guard.py:50`. `remarcacao.py:50` registra: "Não há papel SDR em `users` (todos são `admin`...)".

### 4.4 Plano proposto

Premissa medida: o dono não separa nada, porque o lead de vagas é do Thobias na Exact e é o Thobias quem o abre. O que separa é **a régua de que o contato faz parte**. Por isso a ordem do brief muda: (d) antes de (b).

**(a) Papel em `users` (0,5 dia).** Coluna nova `papel` (`sdr`, `consultora`, `gestao`), independente de `role` (que continua sendo permissão: admin/atendente). Migração preenche 4 e 5 como `sdr`, 2 como `gestao`, 6 (e 3, se ativo) como `consultora`. Passa a ser a fonte de `SDR_USER_IDS` e de `SDR_IDS_PERMITIDOS`, com o `.env` como fallback no primeiro deploy. Tela de usuários ganha o seletor.

**(d) Marca "vagas afirmativas" pelo template, primeiro (0,5 dia).** Ao gravar um envio cujo `template_name` casa `%vagasafirmativas%` (`exact_routes.py:553-567` no lote; o envio individual em `routes.py`), aplicar uma tag `Vagas afirmativas` ao contato (tabela `contact_tags`, já existe). Backfill com os ~110 contatos de hoje, a partir de `messages.template_name` (dado existe desde 01/09). É o critério que de fato distingue esses contatos; dono e canal não distinguem.

**(c) Filtro padrão da tela por papel (1 dia).** Em `page.tsx`, estado inicial do filtro calculado pelo papel de quem está logado, e persistido em `localStorage` (conveniência por pessoa):
- SDR: esconde contatos com a tag de vagas **cuja última mensagem não é inbound** (ou seja, esconde a rajada de follows, mas mostra quem respondeu, porque hoje quem responde é o Thobias: ver `xx4400`, quatro respostas dele em 22/10 09:52-09:54).
- Consultora: só contatos com a tag de vagas, ou com `assigned_to` = ela.
- Botão "ver tudo" sempre disponível (todos seguem admin).
Fazer no frontend sobre a lista que já vem inteira; mexer no `WHERE` do backend só se a Isa quiser bloqueio de fato, e aí é decisão de permissão, não de filtro.

**(b) Disparo em lote atribui dono ao autor (0,5 dia, só se a Isa decidir que a conversa passa a ser da consultora).** Hoje `exact_routes.py:536-539` usa o SDR da Exact e só preenche se vazio. Alternativa: quando o autor tem papel `consultora`, gravar `assigned_to = autor` **mesmo com dono** (o que tira o contato do Thobias). Isso é uma troca de dono, e no caso de vagas tiraria do Thobias contatos que ele mesmo abriu. Por isso fica condicionado à decisão abaixo.

**Estimativa total:** 2 a 2,5 dias com testes ((a) 0,5 + (d) 0,5 + (c) 1 + (b) 0,5 opcional).

**Decisões para a Isa:**

1. **Quem é quem:** a pessoa que dispara vagas afirmativas usa a conta id 6 "Victória" (`comercialcenat@gmail.com`)? A conta id 3 "Vi Amorim" (`processoseletivo@cenatsaudemental.com`, nenhum envio desde 01/09, 564 contatos como dona) é de quem, e ainda é usada? Qual delas é a consultora Amorim e qual é a Rodrigues da agenda?
2. **De quem é a conversa de vagas:** o Thobias abre (`vagasafirmativas_1`) e responde quem retorna; a Victória só roda os follows. A conversa deve continuar do Thobias (então só esconder a rajada, item c) ou passar para a consultora quando ela dispara (item b)? Um contato pode trocar de dono no meio da régua?
3. **Esconder ou bloquear:** basta o filtro padrão (todo mundo continua podendo ver tudo com um clique) ou a consultora não deve ver as conversas do SDR e vice-versa (aí vira mudança de permissão, `role`, e o Thobias deixa de ser admin)?
4. Os 22 contatos de vagas com dono "Vi Amorim" (id 3) e as respostas que chegam neles: hoje caem para quem? (Os avisos vão ao dono; se ninguém usa a conta 3, ninguém vê o aviso.)

## §5 Ordem sugerida de entrega

A hipótese do brief era 2, 1, 4, 3. As medições sugerem **2, 1, 3, 4**:

1. **Item 2 primeiro (1,5 dia).** É o único que causa dano neste momento (§0) e a mudança é pequena, só nas rotas públicas. Também não depende de republicar LP, porque o formato 200 é o mesmo do `_duplo_clique`. A única decisão que bloqueia é a D2 (privacidade); as demais podem vir depois.
2. **Item 1 em seguida (1,5 dia).** Não depende de nada externo: o livre/ocupado já funciona, medido em §1.1. Precisa do expediente de cada consultora, e o provisório 10:00–12:00 + 13:30–19:00 serve para o deploy com a chave desligada. Depois dele, a cópia manual de bloqueios para a Exact pode parar.
3. **Item 3 antes do 4 (~1 dia).** O brief supunha que o item 3 dependia da Exact. Não depende: a API documenta a escrita, e falta só um `LeadsAdd` de teste. Graduação e faixa de investimento casam 1:1 e podem ir já. O campo da pergunta "R$272" espera a decisão da Isa sem travar o resto.
4. **Item 4 por último (2 a 2,5 dias).** Só pode começar depois que a Isa disser quem é quem (contas id 3 e id 6) e se a conversa de vagas continua do Thobias. Sem isso, o filtro é desenhado no escuro. A tag (d) e o papel (a) podem adiantar, porque valem para qualquer decisão.

Total: 6 a 6,5 dias de desenvolvimento, mais a conferência com a Isa em cada item.

## §6 Perguntas para a Isa

As perguntas detalhadas estão no fim de cada seção. Estas são as que bloqueiam alguma coisa:

**Agenda (item 1)**
1. Quem copia os bloqueios do Google para a Exact na véspera? Os de 26/10 foram criados na sexta 23/10, entre 10:49 e 15:56. Com o Hub lendo o Google, essa cópia pode parar.
2. Qual é o expediente de cada Victória por dia da semana, e em que horário a Amorim almoça? Ela não tem almoço bloqueado no Google em 27 e 28/10.
3. Confirma que, a partir disso, elas bloqueiam no Google tudo o que não podem e deixam de marcar na Exact?

**Duplicidade (item 2)**
4. Para quem reaplica com reunião marcada: mostramos data e consultora para qualquer telefone digitado, ou só quando o nome ou o e-mail batem?
5. Reaplicação para **outro curso** com reunião marcada: basta registrar no Hub, ou vale uma nota na timeline do lead existente?
6. Quem reaplica **sem** reunião (57 dos 63 leads a mais, 42 em menos de 10 minutos): reaproveitamos o lead anterior ou mantemos "um lead por aplicação"?
7. O botão "remarcar pelo WhatsApp" abre conversa com o número do agente ou com o da consultora?

**Campos da Spotter (item 3)**
8. A LP pergunta "R$272 mensal é possível? Sim/Não", e o campo da Exact tem 4 faixas. Criamos um campo novo Sim/Não ou a LP volta a perguntar a faixa?
9. O campo `Canal Pós graduação:` é o "como conheceu"? Profissão e ano de formação devem virar campo?
10. Quer o backfill dos 321 leads da LP sem campo? Ele exige provar antes o `PUT /LeadsUpdate/{id}`.

**Usuários (item 4)**
11. Quem usa a conta id 3 "Vi Amorim" e quem usa a id 6 "Victória"? Qual delas é a Amorim e qual é a Rodrigues da agenda?
12. A conversa de vagas afirmativas continua do Thobias, ou passa para a consultora quando ela dispara?
13. Basta um filtro padrão, em que todos continuam vendo tudo com um clique, ou é para bloquear de verdade? Bloquear muda a permissão e o Thobias deixa de ser admin.
