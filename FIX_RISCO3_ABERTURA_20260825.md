# O agente comia lead em silêncio: 4 ações executadas, ZERO estados

**25/08/2026, tarde.** Depois de a fila do agente enfim encher, sobreviver ao commit e drenar
(ver `FIX_GATILHO_ABERTURA_20260825.md`), quatro ações venceram, viraram `executado` — e
`nat_qualificacao_state` continuou com **zero linhas**. Este documento fecha as três perguntas
e implementa o conserto.

---

## 1. Qual das saídas silenciosas matou cada um dos 4

A hipótese estava certa: **contato inexistente**, nos quatro. Nenhum morreu na admissão nem no
corte de data.

| ação | contato | saída que matou |
|---|---|---|
| 60 · Ronaldo Cesar · `5582998307979` | porteiro tolerante casou `558298307979` = **Pablo Valente**, outra pessoa | estado NASCEU; `nat_sender` é estrito, não achou os 13 dígitos → `estado descartado` |
| 61 · Adriana · `5565996306463` | não existia em grafia nenhuma | `contato is None` |
| 63 · `5591985119613` | não existia | `contato is None` |
| 65 · `5591985119613` (mesmo lead, 2ª ação) | não existia | `contato is None` |

Do log, sem ambiguidade:

```
15:18:56  🔒 NAT não enviou (nat_abertura_qualificacao → 5582998307979): contato não existe no banco
15:18:56  ↩️  Agente: abertura de 5582998307979 não saiu — estado descartado
15:18:56  ↩️  Agente: 5565996306463 não existe em contacts — abertura ignorada
17:47:58  ↩️  Agente: 5591985119613 não existe em contacts — abertura ignorada
17:57:58  ↩️  Agente: 5591985119613 não existe em contacts — abertura ignorada
```

### A prova que chegou sozinha

Enquanto este fix era escrito, uma **quinta** ação venceu — e funcionou:

```
 contact_wa_id | etapa              | origem | exact_lead_id
 5583988046720 | aguardando_atuacao | exact  | 51548604
```

É a única das cinco cujo contato **já existia** (`5583988046720`, criado em 18/08). Cinco
ações, uma variável, um resultado diferente. O experimento se completou sem intervenção.

### Causa raiz

`contacts` nascia de dois jeitos: inbound no WhatsApp, ou **efeito colateral do envio da
boas-vindas** — `send_welcome_to_new_lead` cria o `Contact` junto com a `Message` do template,
no passo 7. O passo 4.5 cede a abertura ao agente e **sai antes disso**, e nada passou a criar
o contato no lugar. O agente herdou a dependência da boas-vindas sem herdar quem a satisfazia.

Medido nos 47 leads desde a ativação: **30 sem linha em `contacts`, 17 com**. Quase dois de
cada três leads não podiam receber abertura nenhuma, com a fila cheia e o agente ligado.

### O falso positivo do porteiro tolerante era pior que o bug

`variantes_wa_id("5582998307979")` devolve `("5582998307979", "558298307979")`. A segunda é o
número **do Pablo** — `app/telefone.py` já documenta por que a tolerância é ambígua justamente
para local de 8 dígitos começando em 9. O porteiro abriu na linha de um estranho e o estado
nasceu ali. **Só não houve envio para a pessoa errada porque o `nat_sender` é estrito** — a
inconsistência entre os dois foi o que impediu o estrago.

---

## 2. Por que 47 leads geraram só 6 ações

**Não é gatilho novo quebrado.** Os dois caminhos funcionam depois do fix anterior: dos 5 leads
que chegaram DEPOIS do restart das 15:02, **5 geraram ação**. Os perdidos são rescaldo.

```
 leads desde a ativação (start_at 24/08 23:16:29 UTC) : 47
   welcome_status = 'skipped'  (decisão registrada)   :  5   ← todos posteriores ao restart
   welcome_status = NULL       (nunca decidido)       : 42   ← todos ANTERIORES ao restart
```

O `register_date` máximo entre os 42 NULL é **14:23:51 UTC** — exatamente o último POST da LP
antes do restart. Os dois bugs do documento anterior explicam os 42 inteiros:

* **caminho LP:** a ação era inserida, anunciada no log com id (27 a 57) e desfeita no rollback;
* **caminho sync:** `UnboundLocalError` no passo 4.5 abortava o laço no PRIMEIRO lead, e todos
  os outros já entram como `existing` na passada seguinte.

Eles **não voltam sozinhos** — são `existing` no sync e nunca mais entram em
`new_leads_to_contact`. Daí a seção 4.

> **Correção de um número deste diagnóstico:** o corte real é `2026-08-24 23:16:29` **UTC**.
> Uma primeira consulta usou `02:16:29` de 25/08, 3h à frente, e escondia 1 lead. Total correto:
> 47 desde a ativação, 42 perdidos.

### Um terceiro caminho de perda, encontrado de passagem

O passo 4.5 ignorava o retorno de `agendar_abertura` e carimbava `skipped — "agente de
pré-qualificação assumiu a abertura"` **mesmo quando o gatilho não enfileirou nada**. Como
`welcome_status` não-nulo é a trava permanente de idempotência, isso fecha a porta do lead pelos
dois lados e o deixa indistinguível dos leads realmente atendidos. Corrigido na seção 3.

---

## 3. O conserto — Risco 3 + o contato

### 3.1 `executado` passa a significar UMA coisa

`abrir()` tinha cinco `return` mudos, e os cinco viravam `executado` — a mesma marca de quem
abriu a conversa. Nada no banco distinguia "abri" de "desisti deste lead".

| situação | antes | agora |
|---|---|---|
| fora do horário comercial | `executado` + linha nova | **`AcaoAdiada`** → próximo dia útil, sem consumir tentativa |
| teto por hora estourado (admissão **ou** envio) | `executado`, lead perdido | **`AcaoAdiada`** → +10 min, sem consumir tentativa |
| lead anterior ao corte | `executado`, lead perdido | **`skipped`** + motivo gravado |
| já tem estado | `executado`, mudo | **`skipped`** + motivo gravado |
| envio recusado por outro motivo | `executado`, estado apagado à mão | **`skipped`** + o motivo do sender, inteiro |

São **exceções**, não valores de retorno, por um motivo concreto: o handler roda dentro de
`db.begin_nested()`, e levantar **reverte o savepoint**. O `Contact` e o estado criados antes de
se descobrir que a abertura não sairia somem de graça — a limpeza que o `db.delete(estado)`
fazia à mão, e que não cobria o contato.

`AcaoAdiada` **não consome tentativa**, e isso é o ponto: um lead que chega às 22h espera até as
09h, e isso não pode gastar 1 das 3 tentativas que existem para erro de verdade.

### 3.2 O motivo é COLUNA, não log

`nat_scheduled_actions.motivo TEXT NULL` (migração `migrate_acao_skipped.py`, já rodada, com o
CHECK de status ampliado para aceitar `skipped`).

Coluna e não log porque **o log desta aplicação está afogado**: `journald` suprimiu 36 750
linhas em 25/08 por causa do `echo=True` do engine. Um `skipped` cujo motivo só existe no stdout
seria a mesma falha silenciosa que ele veio corrigir. Vale também para `pendente`: uma ação
adiada pelo teto guarda ali por que ainda não rodou. Zerado quando a ação enfim executa — motivo
velho não fica mentindo.

### 3.3 `abrir()` cria o contato, como a boas-vindas fazia

`_contato_ou_criar` faz o que o passo 7 sempre fez: `Contact.wa_id == phone`, cria se não achar,
com nome do lead, canal da config e SDR resolvido.

**A busca aqui é estrita, e isso é a decisão.** Este contato existe para uma coisa: ser
encontrado por `nat_sender`, que faz igualdade crua. Um porteiro tolerante não ajuda o envio — só
decide se a função segue — e em 25/08 fez pior que não ajudar (o caso Ronaldo/Pablo). Passa a
valer **uma regra só**: o contato da abertura é o da grafia para a qual a mensagem vai. Isso
resolve a decisão pendente nº 2 do documento anterior, e resolve para o lado seguro — sem
alinhar automaticamente para o tolerante.

A tolerância continua onde ela é certa e não escreve nada: `estado_de` (o mesmo humano não pode
ganhar dois estados) e o histórico da conversa.

Uma diferença deliberada em relação à boas-vindas: **`ai_active=False`**. Lá o `True` entrega a
thread ao `ai_engine`; aqui quem conduz é o agente, e marcar o lead como "a IA genérica responde"
seria pedir dois robôs na mesma conversa no dia em que aquele trecho do webhook voltar.

### 3.4 O teto ficou nomeado

`qualificacao_guard.MOTIVO_TETO` + `e_teto(motivo)`. O teto é o único "não" deste módulo que vira
"sim" sozinho — corte de data e chave desligada não mudam de ideia em dez minutos. Tratar os dois
igual era descartar lead por causa de uma janela cheia.

### 3.5 O sender passou a dizer por que recusou

`nat_sender.enviar_nat()` devolve `(saiu, motivo)`; `send_nat_message()` continua devolvendo
`bool` e os sete chamadores do fluxo de botões não mudaram uma linha. Sem isso, o handler não
conseguiria distinguir "o teto estourou, tente daqui a pouco" de "desista deste contato" —
e tratava os dois como a mesma coisa.

### 3.6 O carimbo do passo 4.5 não mente mais

`agendar_abertura` devolve `(enfileirou, motivo)`. Gatilho que falhou de verdade carimba
`failed` com o motivo em `welcome_error` — o lead fica **achável para reprocessar** em vez de
disfarçado de atendido. `já tem estado` continua sendo `skipped`, porque aí o carimbo é
literalmente verdadeiro.

### 3.7 O monitor ficou afiado, não frouxo

`monitor_qualificacao.py` §2b procurava ação **executada** sem estado e não conseguia separar
"descartei o lead" de "não havia o que fazer" — um booking espontâneo entrava como falso
positivo. Agora `executado` sem estado tem uma causa só, e o alerta ficou **mais** severo. A
nova §2b' lista as decisões gravadas (`skipped` / adiadas): "quem o agente deixou de fora e por
quê" virou uma consulta, não uma caçada no log.

---

## 4. Os 42 leads perdidos — `reprocessar_leads_perdidos.py`

```
venv/bin/python reprocessar_leads_perdidos.py              # LISTA, não escreve nada
venv/bin/python reprocessar_leads_perdidos.py --executar   # enfileira de verdade
```

**34 leads**, depois de triagem manual. Partindo de 42 linhas: 1 duplicata (Bruna Rosa
preencheu duas vezes) e **7 excluídos**, gravados em `EXCLUIDOS` no próprio script, com o
motivo de cada um.

### A distinção que decidiu a lista: disparo em massa ≠ conversa

O critério ingênuo — "qualquer outbound sem `nat_etapa` é atendimento humano" — tirava **40
dos 41**. E tirava errado: às 15:18–15:19 saíram **43 templates para 43 contatos distintos em
dois minutos** ("Ola X, é o *curso* do CENAT ✨ Tentei realizar uma nova tentativa de
contato"). É campanha, não atendimento — o lead recebeu um disparo, ninguém falou com ele.
35 dos 41 tinham só isso.

Sai quem tem conversa de verdade: texto individual digitado por SDR, dois ou mais inbound, ou
template individual (fora dos minutos de massa). **Ficam** os leads cujo único "inbound" é
autorresposta do próprio celular deles — *"Assim que puder respondo"*, *"não estou disponível
no momento"* — que não é resposta.

| exact_id | quem | por que sai |
|---|---|---|
| 51532753 | Vera Rosa | inbound próprio + template individual às 14:45 |
| 51537537 | Isabela Guarino | 2 inbound dela, incluindo pergunta sobre 2ª pós |
| 51542856 | Bruna Rosa | passou pela NAT velha em 24/08 e clicou "Prefiro outro horário" |
| 51542913 | Michelle Bittencourt | 4 inbound e 4 respostas digitadas pelo SDR às 15:21 |
| 51543599 | Cibelle Ferrari | negociando: *"Boa tarde, só amanhã, hoje tá corrido"* |
| 51543658 | Andréa Corrêa | negociando: *"ainda estou resolvendo com a equipe"* |
| 51543683 | Escola Municipal Profª Amélia | instituição, não pessoa — tratamento manual |

**Excluir vale para a PESSOA, não para a linha.** Na primeira versão a exclusão era por
`exact_id`, e a Bruna Rosa voltou pela linha duplicada dela (51542856 excluída, 51542892
entrou — mesmo telefone). O telefone de um excluído entra em `vistos` junto.

### Três Beatrizes, e a que importa

Ficou a dúvida se a Beatriz `5512996755533` era quem recebeu o template da ementa às 15:47.
**Não é.** Ela tem exatamente UMA mensagem na vida: o disparo em massa das 15:18. Quem
recebeu às 15:47:39 é `5511988816237`, que nem está entre os candidatos. A terceira é a
Beatriz Gang Mizrahi (`5521999424621`), que fica na lista.

Critério: `welcome_status IS NULL` **e** `register_date >= qualificacao_start_at`. O primeiro é a
marca de quem nunca teve a abertura decidida; o segundo evita produzir `skipped` em massa com
leads que a admissão recusaria de qualquer jeito.

**Grade espaçada, dentro do horário comercial.** Metade do teto (10/h de 20), deixando a outra
metade para os leads orgânicos, que são os que têm pressa. E a grade **pula as 18h30** em vez de
deixar o handler empurrar cada retardatário para as 09h do dia seguinte — todos no mesmo minuto,
refazendo a concentração que o espaçamento evita:

```
  23. 51543054  Stela                               25/08 18:27
  24. 51543064  Daniela Carvalho Moura Bittencourt  26/08 09:00   ← salta a janela
  25. 51543496  Marilda Barreto                     26/08 09:06
```

23 leads hoje até 18:27, 11 a partir de 26/08 09:00.

**Trava de deploy.** O script se **recusa** a enfileirar se o processo no ar for anterior à
última edição em `app/`:

```
❌ NÃO vou enfileirar: o serviço subiu há 234 min e há código alterado há 7 min
   — o processo no ar é ANTERIOR ao conserto.
```

Não é zelo: com o handler antigo, os 41 seriam descartados por "não existe em contacts", marcados
`executado`, e agora **também** carimbados por este script — definitivamente fora dos dois
caminhos. Idempotente por consequência: na segunda passada nenhum deles casa mais
`welcome_status IS NULL`.

---

## 5. Testes

`backend/test_risco3_abertura.py` — **15/15**:

| | caso | o que trava |
|---|---|---|
| 1 | contato inexistente | **CRIA** e a abertura sai — o bug literal |
| 2 | contato já existe | reusa, não duplica |
| 3 | só a variante de 12 dígitos, de OUTRA pessoa | não usa a linha do estranho; a do Pablo fica intacta |
| 4 | sem canal | `AcaoIgnorada`, e nenhum `Contact` órfão |
| 5 | já tem estado | `skipped` com a etapa no motivo |
| 6 | anterior ao corte | `skipped` com o corte no motivo |
| 7 | teto na **admissão** | `AcaoAdiada`, não ignorada |
| 8 | teto no **envio**, já tendo passado na admissão | `AcaoAdiada` — a corrida real entre as duas checagens |
| 9 | envio recusado por outro motivo | `skipped`; o handler **não** apaga o estado à mão |
| 10 | fora do horário | sexta 19h → segunda 09h |
| 11 | agendador: `AcaoIgnorada` | `skipped` + motivo + `attempts` intacto |
| 12 | agendador: `AcaoAdiada` | `pendente` + `run_at` empurrado + `attempts` intacto |
| 13 | agendador: executar | **limpa** o motivo de um adiamento anterior |
| 14 | passo 4.5 | gatilho que falhou carimba `failed`, não "assumiu" |
| 15 | janela de 24h com inbound de 12 dígitos | vê as duas grafias; a escrita continua na do envio |

**Não-regressão, 15 suites:** `test_gatilho_abertura` 8/8 · `test_welcome_guardrail` 17/17 ·
`test_qualificacao` ok · `test_nat_flow` 13/13 · `test_agendamento` 33/33 · `test_espontaneo` ok ·
`test_nat_sprint3` ok · `test_nat_guard` 9/9 · `test_nat_duplicata` 5/5 · `test_nat_reagendado`
5/5 · `test_nat_recuperacao` ok · `test_observabilidade_envio` ok · `test_parse_datetime` ok ·
`test_primeiro_nome` ok · `test_nat_config_api` ok.

Um deles precisou mudar de forma, e vale registrar: `test_qualificacao` afirmava que fora do
horário o handler **cria uma linha nova**. Ele agora adia a mesma — a versão anterior chamava
`agendar`, que começa cancelando o pendente do par `(kind, contato)`, ou seja, **cancelava a
própria ação em execução**, e só não estragava nada porque o `_finalizar` logo depois a
reescrevia para `executado`.

---

---

## 5b. ADENDO — o agente abria, a pessoa respondia, e ele calava

Encontrado **em produção**, num teste manual, depois do deploy. `nat_sender.janela_aberta`
comparava `Message.contact_wa_id == contact_wa_id`: era o **8º ponto de comparação estrita**,
o único que o commit da chave tolerante (`ce13ecc`, "os 7 pontos") não pegou.

O agente ENVIA para a grafia de 13 dígitos (montada do telefone do lead) e o WhatsApp ENTREGA
o inbound **sem o 9º dígito** para todo DDD fora de 11–28 — 59% das threads do Hub. Com
igualdade, o inbound do próprio lead ficava invisível.

**E o estrago não era "não achou": era o caminho errado.** Sem inbound, a função concluía
"janela FECHADA", o sender ia para o ramo de **template aprovado**, e a fala livre do LLM
(`qualif_conversa`) não tem template — recusa com *"não pode ser montado sem inventar dado do
lead"*. Os dois casos lado a lado, no mesmo minuto de 25/08:

```
17:27:47  5517997379129  inbound gravado com 13 digitos -> janela aberta -> respondeu  ✅
17:27:36  558388046720   inbound gravado com 12 digitos -> "fechada"     -> calou      ❌
```

A abertura funcionava para todos; a **conversa** funcionava só para a minoria cujo inbound
chega na mesma grafia do envio. Corrigido com `variantes_wa_id`, mantendo a regra do
`app/telefone.py`: tolerância é de LEITURA, a Message continua sendo gravada na grafia do
envio. Caso 15 do suite tranca as duas metades.

Vale o registro de método: este bug não apareceu em nenhuma das 15 suites nem no monitor. Ele
só existe quando um humano de DDD 83 responde — e foi um teste manual que o produziu.

---

## 6. Pendências

1. **DEPLOY — bloqueia o backfill.** `sudo systemctl restart cenat-backend.service`. A migração
   já rodou, e banco à frente do código é a direção segura: com o CHECK largo, o processo velho
   simplesmente nunca escreve `skipped`.
2. **Rodar o backfill** depois do restart, com `--executar`. A trava confere sozinha.
   Os 7 excluídos e a Cibelle/Andréa **ficam com os SDRs** — não voltam por este caminho.
3. **QueuePool esgotado, incidente separado.** Às 18:18 UTC, dezenas de
   `sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached` — e o ciclo do
   agendador das 18:19 fechou com `{'erro': 1}`. Cheira a conexão vazando; **não investigado
   aqui**.
4. **`echo=True` em `app/database.py`** continua afogando o log. Enquanto durar, ausência de log
   não é evidência de ausência de evento — foi por isso que o motivo virou coluna nesta sprint.
5. **Ninguém agendou em 25/08** (`passo='agendado'` = 0, contra 3–9/dia). As 3 tentativas deram
   502 `Previous stage is not exit action Scheduling`. Segue sem diagnóstico.
6. **Sprint global do `format_phone`** — a tolerância ao 9º dígito casa pessoas diferentes
   (Ronaldo/Pablo). Contida no caminho da abertura por esta sprint; não resolvida no resto.
