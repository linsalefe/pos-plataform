# Sprint 4 — a invariante nos handlers, a varredura por estado, e 58% de curso torto

**Data:** 27/08/2026 (UTC) · **em São Paulo ainda é 26/08, 22:50**
**Commits:** `b428ae1` (S4-1), `be6574e` (S4-2), `b5e4c58` (índice único)
**Estado do processo:** PID **1612955**, subido **26/08 22:52 SP**, rodando `b5e4c58`.
**Sprint 4 NO AR e validado em produção** — índice único criado, 10 aliases inseridos, e a
varredura rodando com 2 ciclos confirmados (§5.1). Nada pendente do meu lado até 09:00.

---

## 0. Antes de tudo: o dia 27/08 ainda não começou em SP

Mesma divergência UTC/SP do §0 do `RECON_27_08_PREFLIGHT.md`, e ela vale de novo:

```
agora UTC: 2026-08-27 01:30      |      agora SP: 2026-08-26 22:30
última mensagem do banco, de qualquer natureza:  26/08 19:18:47 SP
mensagens desde o deploy do Sprint 3 (21:49 SP): 0
```

**A Frente 3 (checklist da manhã) continua sem conteúdo** — não por falta de dado, mas
porque as 09:00 de 27/08 estão a ~10 h de distância. O que dá para responder está no §4,
com a pergunta que fica pendente marcada como pendente. Fabricar um recorte alternativo e
chamá-lo de "a manhã" seria trocar a pergunta em silêncio.

---

## 1. S4-1 — 13 saídas mudas viravam `executado` com motivo NULL

`b428ae1`

"Executado sem efeito não existe" é invariante do projeto desde o conserto do Risco 3, mas
só `iniciar_qualificacao` tinha sido varrido. Os demais handlers registrados seguiam com
`return` simples em caminho sem efeito — e `return` simples vira `executado` com `motivo`
NULL, **a mesma marca de quem agiu**.

### Varredura dos 7 handlers registrados

| Handler | Módulo | Saídas mudas | Situação |
|---|---|---|---|
| `encerrar_inativo` | `qualificacao_fluxo` | **2** | corrigido |
| `lembrete_reuniao` | `qualificacao_fluxo` | **4** | corrigido |
| `sla_check` | `nat_sla` | **4** | corrigido |
| `retry_contato` | `nat_recuperacao` | **3** | corrigido |
| `iniciar_qualificacao` | `qualificacao_fluxo` | 0 | já varrido em 25/08 |
| `responder_pendente` | `qualificacao_fluxo` | 0 | nasceu com `AcaoIgnorada` |
| `vigiar_resposta` | `qualificacao_fluxo` | 0 | nasceu com `AcaoIgnorada` |

### As 13 saídas, uma a uma

```
encerrar_inativo   1. sem estado                    -> "não tem estado — nada a encerrar"
                   2. etapa já não é ativa           -> "já está em '<etapa>' — fora das ativas"
lembrete_reuniao   3. payload sem agendamento_id     -> "sem agendamento_id no payload"
                   4. reunião sumiu ou desmarcada    -> "...não está mais agendada (passo=...)"
                   5. reunião já começou             -> "...já começou (DD/MM HH:MM)"
                   6. consultora não resolvível      -> "...sem consultora resolvível (email=...)"
sla_check          7. sem estado de fluxo            -> "sem estado de fluxo — nada a escalonar"
                   8. saiu de aguardando_ligacao     -> "já saiu de ... (está em <etapa>)"
                   9. já assumido por um humano      -> "já assumido por user N em DD/MM HH:MM"
                  10. já no topo da escada           -> "já está no nível N — fim da escada"
retry_contato     11. sem estado de fluxo            -> "sem estado de fluxo — nada a cobrar"
                  12. saiu de sem_contato            -> "já saiu de ... — o lead reagiu"
                  13. já assumido por um humano      -> "já assumido por user N — sem objeto"
```

Todas viraram `AcaoIgnorada`: `skipped` com o motivo **gravado na linha**. Nenhuma consome
tentativa e nenhuma vira `falhou` — nada falhou. Levantar (em vez de `return`) também
reverte o savepoint do handler, o que é o desejado e sai de graça.

**O caso que motivou:** Erica (`5598984703419`) e Amanda Pavão (`5544998336280`) têm
`encerrar_inativo` pendente para 29/08 09:36 e 09:01. Se forem transferidas antes, a ação
saía `executado` sem motivo — indistinguível de um encerramento real. Com o 4a no ar, sai
`skipped` dizendo qual etapa a barrou.

**Sem migração:** `AcaoIgnorada`/`AcaoAdiada` já existem, `skipped` já está no CHECK de
`nat_scheduled_actions` e `motivo` já é coluna.

---

## 2. S4-2 — a varredura por ESTADO, e o rótulo que mentia

`be6574e` · `backend/app/agente_parado.py` (novo), registrado no `lifespan`

### 2.1 A fronteira entre os dois detectores

```
vigia (P3-A)      por EVENTO   arma no inbound, vence em 10 min     alarme rápido
varredura (S4-2)  por ESTADO   varre a cada 15 min, régua de 60 min  rede de fundo
```

O vigia é armado **no inbound**. Cobre o turno que termina "com sucesso" e não fala, e nada
mais. Quem ficou preso antes de ele existir não tem vigia; quem cair num buraco cujo inbound
nem chegou a ser processado (pool esgotado no webhook, P1-A) não tem vigia; e ninguém varre
o banco à procura de conversa encalhada.

### 2.2 O desenho, e as decisões

| Item | Valor | Por quê |
|---|---|---|
| Intervalo | 15 min | modelo dos jobs do `lifespan` |
| Régua | **> 60 min** | 6× o prazo do vigia: esta é a REDE, não o alarme rápido |
| Teto | **20/ciclo** | protege a leitura da sineta; ordena pelo mais preso primeiro |
| Destino | GESTÃO (`GESTOR_USER_ID`) | é falha de sistema, não fila de SDR |
| Tipo | **`agente_parado`** | `agente_mudo` é "este turno não falou"; este é "esta conversa encalhou" |
| Anti-repetição | (contato, `wa_message_id` do inbound) | mesma mensagem sem resposta = mesmo caso |
| **Acorda o agente?** | **NUNCA** | decisão fechada — ver abaixo |

**Só notifica.** Um varredor que reinjetasse a mensagem responderia uma pergunta de uma hora
atrás como se nada tivesse acontecido, e faria isso justamente nos casos em que o agente já
demonstrou não saber conduzir aquela conversa. Pior: um bug que mate o turno viraria um LOOP
de turnos mortos a cada 15 min, sem ninguém sabendo. Não há uma única chamada de envio no
arquivo, e o teste trava isso **lendo a fonte**.

**Tolerância ao 9º dígito nas DUAS metades do critério.** Não é detalhe: sem ela, um outbound
gravado na outra grafia viraria falso positivo — a varredura acusaria conversa encalhada
numa thread onde o agente respondeu.

**Sem supressão pela fala adiada.** A régua de 60 min já passa por cima da
`ESPERA_MAXIMA_COM_PENDENCIA` (30 min) do vigia: um lead com fala adiada pelo teto que ainda
espera aos 60 min já é caso de alarme pela régua do próprio vigia. A ausência é deliberada.

**O corte do teto GRITA.** 20 avisos numa sineta com 300 casos por baixo lê-se como "são 20
casos". A varredura ordena pela espera, corta em 20, e imprime quantos ficaram de fora.

**Fail-closed:** `varrer()` levanta sem `GESTOR_USER_ID`; o job imprime batimento a cada
ciclo, inclusive vazio; o `try/except` abraça o ciclo para o loop não morrer.

### 2.3 Decisão 2 — `encerrado_motivo` deixa de mentir

O `encerrar_inativo` gravava sempre `inatividade` ("o lead calou"), **inclusive quando a
inatividade era nossa**. Agora pergunta à MESMA função da varredura quem falou por último:

```
inatividade             falamos por último e o lead sumiu       (o lead calou)
sem_resposta_do_agente  ele falou por último e nós não voltamos (nós calamos)
```

Um critério, um lugar: `agente_parado.encalhada` responde às duas perguntas. Duplicá-lo faria
os dois divergirem no primeiro ajuste da régua.

**CHECKPOINT dispensado — confirmado no banco em 27/08:**

```
nat_qualificacao_state.encerrado_motivo | text | nullable
Check constraints: nat_qualif_etapa_valida, nat_qualif_origem_valida
                   -> NENHUM CHECK sobre encerrado_motivo
notifications.type                      | character varying(30) | NOT NULL, sem CHECK
                   -> 'agente_parado' tem 13 chars e cabe
```

**Nenhuma migração foi feita e nenhuma é necessária.**

### 2.4 Evidência — DRY-RUN contra o banco de produção

Rodado com `rollback` explícito: **nada gravado**.

```
agora SP = 2026-08-26 22:40:16
🧊 AGENTE PARADO: 5544998336280 em 'aguardando_atuacao' há 818 min
🧊 AGENTE PARADO: 5598984703419 em 'aguardando_ano'     há 783 min
resumo: {'ativos': 14, 'encalhados': 2, 'notificados': 2, 'repetidos': 0,
         'cortados_pelo_teto': 0}
ROLLBACK feito — nada gravado.
```

**14 estados ativos varridos, 2 encalhados — exatamente a Amanda Pavão e a Erica, os dois
casos já conhecidos. Zero falsos positivos.**

Corpo da notificação gerada:

> **AGENTE PARADO — conversa encalhada há 818 min**
> +55 44 99833-6280 escreveu 26/08 09:01 e segue sem resposta. Etapa:
> `aguardando_atuacao`. O agente NÃO será acordado — alguém precisa assumir a conversa.

### 2.5 Testes

`backend/test_agente_parado.py` — 8 grupos, sem banco, sem envio:

1. encalhado > 60 min → 1 notificação à gestão, com etapa, espera e ref
2. ciclo seguinte **não repete** (anti-repetição pelo `wa_message_id`)
3. inbound **novo** → aviso novo (o lead insistiu = caso diferente)
4. respondido / dentro da régua / sem inbound / fora das etapas ativas → nada
   (inclusive a fronteira: 61 min **é** caso, 30 min não é)
5. o 9º dígito nas duas metades, e o falso positivo do outbound na outra grafia
6. o teto de 20 corta os **mais novos** e conta os cortados
7. a fonte sem nenhuma chamada de envio; e falha fechada sem gestor
8. os 4 cenários do rótulo do encerramento (lead calou / nós calamos / sem outbound
   nenhum / lead que nunca escreveu), mais o `skipped` com motivo do S4-1

**Bateria completa, toda verde:**

```
test_agente_parado.py     PASS      test_vigia_agente_mudo.py  PASS
test_qualificacao.py      PASS      test_nat_flow.py           PASS
test_nat_recuperacao.py   PASS      test_nat_guard.py          PASS
test_nat_sprint3.py       PASS      test_welcome_guardrail.py  PASS
test_risco3_abertura.py   PASS
```

Cada saída convertida no S4-1 ganhou asserção **do motivo** — "não notificou" deixou de
bastar como prova.

### 2.6 Uma proposta que NÃO foi executada: idempotência por constraint

A anti-repetição usa `SELECT`-antes-de-`INSERT` sobre `idx_notifications_dedup`
(`contact_wa_id, type, ref`), que é a mecânica do `window_alerts_job`. **Esse índice não é
UNIQUE.** Aqui não há corrida (o job é uma única task asyncio, sequencial), mas a regra do
projeto é idempotência *por constraint*.

O conserto seria um índice único parcial:

```sql
CREATE UNIQUE INDEX CONCURRENTLY uq_notif_agente_parado
    ON notifications (contact_wa_id, ref) WHERE type = 'agente_parado';
```

**CHECKPOINT aprovado e EXECUTADO** em 26/08 22:51 SP (`migrate_agente_parado_dedup.py`,
commit `b5e4c58`). Construção de índice apenas — sem ALTER de coluna, sem CHECK, sem
reescrita de tabela.

```
BEFORE  idx_notifications_dedup, idx_notifications_unread,
        idx_notifications_user, notifications_pkey            (4, nenhum único na tripla)
pré-checagem  0 linhas com type='agente_parado', 0 duplicatas
              tabela: 4 484 linhas, 2 392 kB
AFTER   + uq_notif_agente_parado
        CREATE UNIQUE INDEX uq_notif_agente_parado ON public.notifications
          USING btree (contact_wa_id, ref) WHERE ((type)::text = 'agente_parado'::text)
        indisvalid=t  indisunique=t
```

PARCIAL e não global: `nat_sla` e `nat_recuperacao` gravam `ref = '<kind>:<acao_id>'` de
propósito, para que dois escalonamentos do mesmo lead sejam dois avisos — único sobre a
tripla inteira quebraria isso.

**O que muda no comportamento:** o `SELECT`-antes-do-`INSERT` continua sendo o caminho
normal, e é ele que evita o erro. O índice é a rede. Numa corrida, o `INSERT` duplicado
levanta `IntegrityError`, o `commit` do ciclo falha inteiro e o job imprime ❌ — perda de UM
ciclo, ruidosa, e que se cura sozinha: 15 min depois o `SELECT` já enxerga a linha vencedora.
Perder um ciclo com barulho é melhor que duplicar aviso em silêncio.

---

## 3. Aliases — 10 executados, 42% → 81%, e o resto virou backlog

**58% das primeiras impressões saem com o curso quebrado.** Duas convenções de `sub_source`
convivem e `course_aliases` só cobre uma. Medido hoje, agosto/2026:

```
leads de agosto com sub_source:                 416
   com alias hoje:                              176   (42%)
   SEM alias (caem no fallback cru):            240   (58%)
```

O fallback tira o prefixo "Pos" e devolve o resto: `PosPsicologiaEscolar` →
**"PsicologiaEscolar"**; `PosSMTrabalhadorT3` → **"SMTrabalhadorT3"**.

### 3.1 Divergência do enunciado, reportada e não silenciada

O briefing pedia "mais a variante `PsicologiaEscolar` (caso Rita)". **Essa variante não
existe como `sub_source`** — nem em `exact_leads`, nem em `agendamentos`:

```sql
select 'exact_leads', sub_source, count(*) from exact_leads
 where sub_source ilike '%psicologiaescolar%' group by 1,2
union all select 'agendamentos', ... ;
--  exact_leads | PosPsicologiaEscolar | 86     <- única linha
```

`PsicologiaEscolar` é a **saída** do fallback sobre `PosPsicologiaEscolar`, não uma segunda
chave a cadastrar. Inserir um alias `PsicologiaEscolar` seria cadastrar um valor que nunca
chega. **Removido da proposta.**

A varredura também achou **2 buracos que não estavam na lista dos 12**:
`PosPraticasDialogicasTurma1` (5) e `posenfermagemsm` (2). São 14 no total.

### 3.2 A tabela — 9 CONFIRMADOS (+1 aprovado em separado)

Cada `short_name` vem de uma linha **já existente** na tabela para o mesmo curso (coluna
"pareado com"). Nenhum foi inventado.

| # | alias a inserir | ago | pareado com (linha existente) | **short_name proposto** |
|---|---|---:|---|---|
| 1 | `PosPsicologiaEscolar` | 41 | `Pos Psicologia Escolar` | **Psicologia Escolar** |
| 2 | `PosSMTrabalhadorT3` | 38 | `Pos Saude do Trabalhador` | **Saúde Mental do Trabalhador** |
| 3 | `posinfantoead` | 17 | `Pos Infantojuvenil EAD` | **Infantojuvenil EAD** |
| 4 | `PosPsicologianaRAPST3` | 16 | `Pos Psicologia na RAPS T3` | **Psicologia na RAPS** |
| 5 | `PosGraduacaoTEA` | 16 | `Pos TEA V3` | **Transtorno do Espectro Autista (TEA)** |
| 6 | `PosAutolesaoComportamentoSuicidaeLutoTurma3` | 14 | `Pos Suicidio e Luto T3` | **Autolesão, Suicídio e Luto** |
| 7 | `PosGestaoAvaliacaoePlanejamentoTurma5` | 12 | `Pos Gestao Psicossocial T5` | **Gestão, Avaliação e Planejamento** |
| 8 | `posgruposeoficinasturma2` | 6 | `Pos Grupos e Oficinas T2` | **Grupos e Oficinas em Saúde Mental** |
| 9 | `posenfermagemsm` | 2 | `Pos Enfermagem em Saude Mental` | **Enfermagem em Saúde Mental** |
| 10 | `posgruposeoficinas` | 0¹ | `Pos Grupos e Oficinas T2` | **Grupos e Oficinas em Saúde Mental** |

¹ zero em agosto — são **111 leads históricos**. Entrou depois dos 9, aprovado em separado;
ver §3.7 para como apareceu e por que o alarme inicial que levantei sobre ele não procedia.

O pareamento do #6 merece nota: o `full_name` de `Pos Suicidio e Luto T3` é *"Novas
Abordagens em Saúde Mental — Autolesão, Comportamento Suicida e Luto"*, que casa palavra por
palavra com o alias, e `Turma3`↔`T3`. **Não** é o `posautolesao` ("Autolesão e Prevenção do
Suicídio"), que é outro curso.

**Efeito medido dos 9:** cobertura de agosto vai de **176/416 (42%)** para **338/416 (81%)**.

### 3.3 Os 5 PENDENTES — não inventei nenhum

| alias | ago | total | por que está pendente |
|---|---:|---:|---|
| `PosBoasPraticasEAD` | 28 | 285 | **ambíguo.** Dois cursos da tabela têm "Boas Práticas" no `full_name`: `poscuidaremliberdadeturma5` ("Boas Práticas do Cuidar em Liberdade") e `PosPsicologiaClinicaeSaudeMentalturma2` ("Boas Práticas em Psicologia Clínica"). Nenhum tem "EAD". Cruzei com `agendamentos` por telefone e não desambigua — dá gente que se candidatou a um e agendou outro. **Precisa da gestora.** |
| `interuruguai2026` | 25 | 92 | **parece intercâmbio, não pós.** `source = 'Rd Marketing'`. Se for intercâmbio, não deve entrar em `course_aliases` — a abertura do agente diria "aplicou para a nossa Pós-Graduação em Intercâmbio Uruguai". |
| `PosGraduacaoEconomiaSolidariaTurma1` | 13 | 233 | é pós, mas **não há linha legível na tabela** para Economia Solidária. Precisa do nome comercial. Sugestão de partida, a confirmar: *Economia Solidária*. |
| `intercambiotrieste2026` | 7 | 247 | mesmo caso do Uruguai. |
| `PosPraticasDialogicasTurma1` | 5 | 90 | é pós, sem precedente na tabela. Sugestão de partida, a confirmar: *Práticas Dialógicas*. |

Os dois intercâmbios juntos são **339 leads no total** — se de fato não forem pós, o buraco
não é de alias, é de **admissão**: o agente não deveria abrir conversa de pós com eles.
Registro como achado, fora do escopo desta sprint.

**Nota sobre `posenfermagemsm` — uma instrução conflitante, levantada e resolvida.**
O ok de 27/08 pedia duas coisas incompatíveis: *"EXECUTE o INSERT dos 9 confirmados"* (e
`posenfermagemsm` era o #9 da tabela) e, logo abaixo, *"registre PosPraticasDialogicasTurma1
e posenfermagemsm na lista pendente"*. Executei os 9 e **reportei a contradição em vez de
escolher em silêncio**. Confirmado depois: **mantido executado** — a contradição era do
prompt e o mérito do pareamento (`Pos Enfermagem em Saude Mental` → *Enfermagem em Saúde
Mental*) se sustenta. `PosPraticasDialogicasTurma1` continua pendente (§3.3).

### 3.4 O INSERT — **EXECUTADO** em 26/08 22:52 SP

Aprovado para os 9 do §3.2. `INSERT 0 9`, dentro de `BEGIN/COMMIT`, com `ON_ERROR_STOP=1`.

```sql
-- Idempotente por constraint: course_aliases_alias_key (UNIQUE em alias).
INSERT INTO course_aliases (alias, full_name, short_name, is_active)
SELECT v.alias, ca.full_name, ca.short_name, true
  FROM (VALUES
    ('PosPsicologiaEscolar',                        'Pos Psicologia Escolar'),
    ('PosSMTrabalhadorT3',                          'Pos Saude do Trabalhador'),
    ('posinfantoead',                               'Pos Infantojuvenil EAD'),
    ('PosPsicologianaRAPST3',                       'Pos Psicologia na RAPS T3'),
    ('PosGraduacaoTEA',                             'Pos TEA V3'),
    ('PosAutolesaoComportamentoSuicidaeLutoTurma3', 'Pos Suicidio e Luto T3'),
    ('PosGestaoAvaliacaoePlanejamentoTurma5',       'Pos Gestao Psicossocial T5'),
    ('posgruposeoficinasturma2',                    'Pos Grupos e Oficinas T2'),
    ('posenfermagemsm',                             'Pos Enfermagem em Saude Mental')
  ) AS v(alias, par)
  JOIN course_aliases ca ON ca.alias = v.par
ON CONFLICT (alias) DO NOTHING;
```

O `JOIN` é de propósito: o `short_name` e o `full_name` são **copiados da linha existente**,
não digitados de novo. Se alguém corrigir o nome comercial de um curso amanhã, a linha nova
não vira uma segunda verdade divergente.

### 3.6 Cobertura DEPOIS do INSERT — medida, não projetada

```
leads de agosto com sub_source:  416
   com alias ANTES:              176   (42,3%)
   com alias DEPOIS:             338   (81,3%)
```

O que sobra em agosto são exatamente os 5 pendentes do §3.3: `PosBoasPraticasEAD` (28),
`interuruguai2026` (25), `PosGraduacaoEconomiaSolidariaTurma1` (13), `intercambiotrieste2026`
(7), `PosPraticasDialogicasTurma1` (5). Nenhum outro.

O 10º alias (`posgruposeoficinas`, §3.7) não move este número — ele não tem lead em agosto.
Total de linhas inseridas hoje: **10**.

### 3.7 O lead que chegou às 22:47, e um alarme meu que se desfez

Às **22:47 SP**, enquanto esta sprint era escrita, chegou um lead novo — Giulliana Nunes
Pereira (`5511964791220`), pela mensagem-gatilho da LP. O agendador fez a coisa certa:

```
279 | iniciar_qualificacao | 5511964791220 | 2026-08-27 09:00 | pendente
    | motivo: "fora do horário comercial (22:51)"
```

`AcaoAdiada` com motivo gravado, empurrada para as 09:00, **sem consumir tentativa** — o
comportamento do P0-D/Risco 3 validado em produção, ao vivo.

#### O alarme que levantei sobre o curso dela estava errado — a correção

Casei a Giulliana com `exact_leads` **pelo telefone** e achei uma linha de 26/12/2025 com
`sub_source = posgruposeoficinas` (sem o sufixo `turma2`, sem alias). Concluí daí que a
abertura das 09:00 diria *"Pós-Graduação em gruposeoficinas"*.

**Não é o que acontece.** O handler não casa por telefone: ele usa o `lead_id` do payload da
ação, que é **51591599** — um lead NOVO na Exact, criado hoje pela LP —, e não o 46395426 de
dezembro. Rodando o `_curso()` e o `_nome()` REAIS contra o banco (somente leitura):

```
exact_leads[exact_id=51591599]  -> None            (o sync ainda não trouxe)
agendamentos[lead_id=51591599]  -> (229, 'Giulliana Nunes Pereira', 'Pos Grupos e Oficinas T2')

_curso() -> 'Grupos e Oficinas em Saúde Mental'
_nome()  -> 'Giulliana'

  "Olá, Giulliana! ... aplicou para a nossa Pós-Graduação em Grupos e Oficinas em Saúde Mental."
```

**A abertura sai correta** — e sai correta **pelo S3-3**: `exact_leads` está vazia por atraso
de sync, e a segunda fonte (`agendamentos.sub_source`) entrega o dado certo. É exatamente o
cenário que o S3-3 foi escrito para cobrir, funcionando num caso real.

E quando o sync trouxer o 51591599, ele virá na convenção boa — os leads criados pela LP
chegam a `exact_leads` já com espaço:

```
51591580 | Pos Infantojuvenil EAD    | 27/08 | Infantojuvenil EAD
51585608 | Pos Grupos e Oficinas T2  | 26/08 | Grupos e Oficinas em Saúde Mental
51588082 | interuruguai2026          | 26/08 | (sem alias — ver §3.8b)
```

#### O alias foi inserido assim mesmo, e por outro motivo

`posgruposeoficinas` foi cadastrado em 26/08 22:57 SP (`INSERT 0 1`, pareado com
`Pos Grupos e Oficinas T2` → **Grupos e Oficinas em Saúde Mental**). Ele **não** era
necessário para a Giulliana; vale pelos **111 leads históricos** que carregam essa grafia e
que voltam à tona sempre que alguém se re-candidata. Mérito próprio, prazo nenhum.

**O que fica de lição:** casar lead por telefone é heurística de investigação; o código casa
por `lead_id`. Quando os dois discordam, quem manda é o código — e foi por isso que rodei o
`_curso()` de verdade em vez de deduzir da tabela.

### 3.8 O que sobra são DUAS coisas diferentes, e não uma

O recorte de agosto esconde a escala. Sem filtro de data, os `sub_source` sem alias com ≥3
leads somam dezenas, e o topo é dominado por duas famílias:

| Família | Exemplos | Ordem de grandeza |
|---|---|---|
| **Intercâmbios** | `intercambioportugal2026` (335), `interbuenosairesprovincia` (272), `intercambiotrieste2026` (247), `intertrieste2025` (197), `intercambioSp2025` (195), `Intercambiomanchester2026` (193)… | **milhares** |
| **Convenções antigas de pós** | `posatencaobasica4` (263), `SMtrabalhador` (173), `posalcoolt3` (145), `posgestao4` (136), `posgruposeoficinas` (111), `posgenero` (109) | centenas |

Decidido em 27/08: são **dois itens de backlog separados**, com donos e naturezas distintas.

#### (a) Segunda leva de aliases de pós antigas — MEU, sem prazo

`posatencaobasica4` (263), `SMtrabalhador` (173), `posalcoolt3` (145), `posgestao4` (136),
`posgenero` (109), `CampanhaPsicologiaClinica` (143) e os demais da mesma família.

**Mesmo método dos 9:** pareamento com precedente legível já existente na tabela; onde não
houver precedente, entra como PENDENTE em vez de nome inventado. `posgruposeoficinas` (§3.7)
foi o primeiro desta leva, adiantado por ter aparecido num caso ao vivo.

Não é urgente: são leads antigos, e eles só voltam a importar quando alguém se re-candidata
pela LP — que foi o que a Giulliana quase demonstrou. **O sprint só é gerado depois que a
gestora validar os 5+2 pendentes** (§3.3), para não abrir duas frentes de decisão comercial
ao mesmo tempo.

#### (b) Intercâmbios — questão de ADMISSÃO, não de alias. NÃO cadastrar nada.

`intercambioportugal2026` (335), `interbuenosairesprovincia` (272), `intercambiotrieste2026`
(247), `intertrieste2025` (197), `intercambioSp2025` (195), `Intercambiomanchester2026`
(193), `interbuenosaires2026` (174), `interuruguai2026` (92)… — milhares de leads.

O agente **provavelmente não deve abrir qualificação de pós para lead de intercâmbio.**
Cadastrar alias seria consertar a frase e manter o erro: o lead receberia "aplicou para a
nossa Pós-Graduação em Intercâmbio Trieste" bem escrito, quando o problema é que a conversa
não deveria começar. O lugar do conserto é `qualificacao_pode_iniciar`.

E não é hipotético — `interuruguai2026` aparece entre os leads da LP de **26/08**, quer dizer,
esses leads estão chegando à porta do agente agora.

**Decisão da gestão, não minha. Nenhum alias de intercâmbio foi ou será cadastrado sem isso.**

### 3.5 O que o INSERT NÃO resolve

`_curso()` lê `exact_leads` **primeiro** e só cai para `agendamentos` quando a primeira está
vazia. Como `exact_leads` é a fonte da convenção ruim e `agendamentos` a da boa, a fonte
preferida entrega o resultado pior — e o S3-3 não muda isso, porque ele só age quando a
primeira está *ausente*, não quando está *feia*. Com os aliases preenchidos o problema
desaparece na prática; a assimetria de precedência continua de pé como dívida.

---

## 4. Checklist da manhã — o que dá para responder às 22:50 SP

| Item | Resposta |
|---|---|
| Primeiro turno com `🧠 LLM` | **AINDA PENDENTE.** 0 ocorrências em 325 linhas desde o restart — e 0 turnos do LLM: nada a logar. O canal segue provado (a linha `agente.boot` chega ao journald), a linha não. |
| `🏷️`, `FORA DO CONTRATO`, `🛑 LLM` | 0 cada. Sem turno, sem medição. |
| `Traceback`, `sqlalchemy.engine`, `❌ Erro` | **0 cada.** Os 4 GB de log SQL não voltaram. |
| S3-1 sem falso alarme | **0** transferências com motivo contendo `concluido` desde o deploy. Sem caso ainda. |
| Vigia (`vigiar_resposta`) | 17 cancelados, **0 disparos**, nenhum armado desde o deploy. Inalterado. |
| Reuniões marcadas **pelo agente** | **ainda 0.** As 3 linhas com `origem_ip IS NULL` são as tentativas da Fabiana de 25/08, todas em `passo='iniciado'` — nenhuma chegou a `agendado`. P0-A segue sem caso real. |
| Estados novos de 27/08 SP | **0** — o dia não começou. |
| As 3 aberturas de 09:00 (Ana Thally, Lucas, "fafaf") | **NÃO SAÍRAM AINDA.** Faltam ~10 h. A verificação do S3-3/S3-4 continua marcada para depois das 09:00. |
| Erica / Amanda Pavão transferidas? | **NÃO.** Seguem em `aguardando_ano` e `aguardando_atuacao`, `transferido_motivo` NULL, `updated_at` de 26/08 09:36 e 09:01. O SDR não digitou nada. Ver §4.2. |
| Reuniões de hoje | Amanda Pavão 09:00 (lembrete 152 `pendente` 08:30), Mikaelle 09:45 (226 `pendente` 09:15), Natália 15:45 (266 `pendente` 15:15). **Todos ainda pendentes** — vencem amanhã de manhã. |
| Mensagens do time | Nenhuma. **Zero mensagens de qualquer natureza desde 26/08 19:18:47 SP.** |

### 4.1 Segunda divergência reportada

O `RECON_27_08_PREFLIGHT.md` §5.2 diz que a Erica e a Amanda estão sem resposta **"há ~36 h"**.
Não é o caso: os inbounds são de 26/08 09:36 e 09:01, e às 22:40 SP a espera medida é de
**783 min (13 h 03)** e **818 min (13 h 38)**. O preflight errou o número; os leads e o
diagnóstico estão certos. Corrijo aqui e mantenho o resto do §5.2 válido.

### 4.2 Erica e Amanda Pavão — a rede já está armada nas duas pontas

Combinado em 27/08: **a meta continua sendo a transferência manual amanhã cedo**, pelo SDR.
O que o Sprint 4 muda é o que acontece se ninguém agir.

```
23:07 SP (hoje)   varredura -> 2 notificações AGENTE PARADO para a gestão
                  (e não repete: anti-repetição pelo wa_message_id, agora por constraint)
29/08 09:01/09:36 encerrar_inativo -> se o SDR tiver transferido antes:
                                        `skipped` COM MOTIVO  (S4-1)
                                      se ninguém agir:
                                        `encerrado` + motivo `sem_resposta_do_agente` (S4-2)
                                        — o rótulo verdadeiro: nós calamos, não elas
```

Antes desta sprint os dois desfechos eram indistinguíveis: `executado` sem motivo num caso,
`inatividade` (= "o lead calou") no outro. As duas mentiras acabaram.

### 4.3 O que o dia 27/08 ainda precisa responder

```bash
journalctl -u cenat-backend --since "2026-08-27 09:00" | grep -E "🧠 LLM|🏷️|FORA DO CONTRATO|🛑 LLM"
journalctl -u cenat-backend --since "2026-08-27 09:00" | grep -E "🧊 AGENTE PARADO|⏱️  Varredura"
```

```sql
-- as 3 aberturas de 09:00 saíram com nome e curso certos? (S3-3/S3-4)
select contact_wa_id, content from messages
 where direction='outbound' and timestamp >= '2026-08-27 09:00'
   and contact_wa_id in ('5585992987046','5551996323362','5571985252525');

-- a varredura notificou?
select id, contact_wa_id, title, created_at from notifications
 where type='agente_parado' order by id desc;
```

---

## 5. Restart — feito, e o boot conferido

`sudo systemctl restart cenat-backend` às **26/08 22:52:42 SP** (27/08 01:52:42 UTC).
Estado imediatamente antes: 0 ações pendentes vencidas, tráfego parado. PID 1611266 →
**1612955**, rodando `b5e4c58`.

```
INFO agente.boot: logging configurado — root=INFO, handler no stderr, SQL filtrado=True
✅ Sync Exact Spotter agendado (a cada 10 min)
✅ Alertas de janela 24h agendados (a cada 5 min)
✅ Agendamento de templates ativo (checa a cada 60s)
✅ Agendador NAT ativo (checa a cada 60s)
✅ Alerta de saúde de entrega ativo (checa a cada 15 min)
✅ Faxina de agendamento ativa (remove box nosso parado há 0:15:00)
✅ Varredura de agente parado ativa (a cada 15 min, régua de 60 min — só notifica)   <-- NOVO
✅ agendamento: 2 consultora(s) em rotação
✅ agendamento: source 'Landing Page' (id 140648) com as 13 origens da allowlist confirmadas
```

**Os 7 jobs de pé, o novo entre eles.** Zero `Traceback`, zero `❌`, zero `sqlalchemy.engine`.
A linha `agente.boot` do S3-2 voltou a chegar ao journald — o canal segue provado.

### 5.1 Os dois primeiros ciclos — a varredura funcionando em produção

O job dorme 15 min antes de trabalhar, como todos os jobs do `lifespan`.

```
23:07:44 SP   🧊 AGENTE PARADO: 5544998336280 em 'aguardando_atuacao' há 845 min
              🧊 AGENTE PARADO: 5598984703419 em 'aguardando_ano'     há 811 min
              ⏱️  Varredura: 14 em etapa ativa, 2 encalhado(s), 2 aviso(s) novo(s), 0 já avisado(s)

23:22:44 SP   ⏱️  Varredura: 14 em etapa ativa, 2 encalhado(s), 0 aviso(s) novo(s), 2 já avisado(s)
```

**O segundo ciclo é a prova que importa.** Os mesmos 2 casos continuam encalhados, e nenhum
aviso novo saiu: a anti-repetição por `wa_message_id` funciona em produção, não só no teste.
Sem ela, esses 2 leads gerariam 4 avisos por hora até alguém agir.

No banco:

```
 id  | user_id | contact_wa_id | type          | title                                         | is_read
 4488|       2 | 5544998336280 | agente_parado | AGENTE PARADO — conversa encalhada há 845 min | f
 4489|       2 | 5598984703419 | agente_parado | AGENTE PARADO — conversa encalhada há 811 min | f
```

Duas linhas, e continuam duas depois do segundo ciclo. O índice único parcial já registra uso
(`idx_scan=2`) — é ele que a checagem de anti-repetição percorre.

Zero `❌ Erro no agente_parado_job`. Os dois casos são a Amanda Pavão e a Erica, exatamente os
previstos no dry-run — **zero falsos positivos em produção**.

---

## 6. Pendências que não são minhas (só registro)

* Regra do **disparo em massa** com o time — aconteceu de novo em 26/08 14:46.
* **Respostas oficiais do top-10** com a gestora (base de conhecimento).
* **Template novo T2/T3**.
* **Apresentação do deck**.
* Decisão da gestora sobre os **5+2 pendentes** (§3.3), com `PosBoasPraticasEAD` na frente.
* **Backlog (a):** segunda leva de aliases de pós antigas (§3.8a) — sem prazo, gerado só
  depois que os pendentes forem validados.
* **Backlog (b):** **intercâmbios** (§3.8b) — questão de **admissão**, decisão da gestão.
  Nenhum alias a cadastrar ali.
* Lixo de formulário (`"fafaf"`) e os 4 avisos falsos `agente_transferiu` não lidos.
