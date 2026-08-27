# SPRINT 3 — o agente comercial: 4 fixes de baixo risco + 1 proposta — 27/08/2026

Autorizado a partir de `RECON_DESEMPENHO_AGENTE_20260827.md`. **Só os itens de baixo risco.**
As melhorias **#2 (disparo em massa), #3 (abertura T2/T3) e #4 (base de conhecimento)** estão
travadas em decisão da gestão e **não foram tocadas**.

**Estado:** implementado, testado, commitado, pushado e **NO AR** — PID 1611266, subiu
27/08 00:49:16 UTC, rodando `4a8a058`.

---

## 1. Commits

| # | Commit | O que |
|---|---|---|
| S3-1 | `1c8f855` | `_concluir` confirma em vez de se despedir |
| S3-2 | `6dab850` | `dictConfig` no boot — o rastro do P0-E sai do processo, o SQL não |
| S3-3+4 | `4a8a058` | `_curso()` com segunda fonte; `_nome()` com o cadastro primeiro |
| doc | (este) | |

Suíte reexecutada a cada commit: **12 arquivos, rc=0**.

---

## 2. S3-1 — quem termina a qualificação é confirmado, não despedido

### O que estava acontecendo

`_concluir(confirmar=True)` gravava a etapa **antes** de falar, e o guard de envio relia o
estado que ele acabara de gravar:

```
estado.etapa = 'concluido'  ->  db.flush()
_falar -> qualificacao_pode_atuar RELÊ o estado -> vê 'concluido' -> recusa
       -> _fallback -> transferido_humano + TEXTO_FALLBACK + notificação à gestão
```

**4 de 4 (100%)** dos leads T1 que completaram o roteiro depois de 26/08 13:32 UTC. E **4 dos
6** avisos `agente_transferiu` do período eram esse falso alarme.

### A escolha, e por que não foi a outra

O prompt do sprint dava duas formas e pedia a que preservasse *"a etapa nunca anda após
`_fallback`"*. Escolhida a **(b)**:

| | Forma | Veredito |
|---|---|---|
| (a) | confirmar **antes** de gravar `concluido` | **recusada** |
| (b) | gravar a etapa e enviar com guard que não exige etapa ativa | **implementada** |

Três razões contra a (a), e a segunda é decisiva:

1. exigiria uma **terceira cópia** do idioma `if not await _falar(...) and estado.etapa ==
   ETAPA_Q_TRANSFERIDO: return` só para manter a invariante de pé;
2. uma confirmação que não sai levaria o estado a `transferido_humano` pelo `_fallback` — que
   é **exatamente o desfecho que este fix existe para remover**. A reunião já está de pé na
   Exact; falhar em anunciá-la não pode desfazer a conclusão. `_agendar` já diz a mesma regra
   com outras palavras: *"A reunião JÁ EXISTE na Exact neste ponto. Se a confirmação não sai,
   o estado ainda tem de fechar"*;
3. no ramo do teto (`_falar` devolve `False` **sem** transferir) a etapa viraria `concluido`
   com um `responder_pendente` vivo — e o bug **reapareceria 10 min depois**, mais raro e mais
   difícil de achar.

A (b) é o que `lembrete_reuniao` e `concluir_por_agendamento_externo` já fazem, pelo mesmo
motivo. A invariante fica preservada **por construção**: `_concluir` só é alcançado quando o
chamador já checou `etapa != TRANSFERIDO`, e o envio novo **não tem caminho para `_fallback`**.

### O guard é `guard_de_despedida`, não `guard_de_abertura`

Os dois dispensam etapa ativa. A diferença é o **teto por hora**, e o P1-B já decidiu essa
questão: teto é para *business-initiated*. Esta confirmação é a última fala de um turno que o
**lead começou**. O lembrete continua com `guard_de_abertura` de propósito — ele *é*
business-initiated e sai dias depois.

### Recusa aqui não é `_fallback`, e não é silêncio

Sobrou pouco que possa recusar (`guard_de_despedida` checa só a chave geral), e o que sobra
significa "o agente está desligado" ou "a Meta não aceitou". Nenhum desses casos justifica
desfazer uma conclusão correta nem acordar a gestão: a reunião existe, o SDR a vê na Exact e o
lembrete T-30 continua agendado. Fica o `print` — que, graças ao S3-2, **agora aparece de fato
no journald**.

### O teste

`test_concluir_confirma.py`, 6 grupos. **Os guards não são dublês** — o bug morava na conversa
entre eles, e um teste que os mockasse não provaria nada. Inclui a **prova negativa**:

```
2) Prova negativa: com o guard que `_falar` usava, o bug volta
  [ok] qualificacao_pode_atuar RECUSA com etapa 'concluido'
  [ok]   e é a recusa exata que aparecia no log de 26/08
  [ok] guard_de_despedida ACEITA a mesma etapa
```

O critério pedido, travado:

```
1) O caso da regressão: reunião existente + roteiro completo -> CONFIRMAÇÃO
  [ok] etapa final é 'concluido'          [ok] ZERO notificação à gestão
  [ok]   sem transferido_em               [ok] duas falas: a do LLM e a confirmação
  [ok]   sem transferido_motivo           [ok]   a última é a confirmação, não a despedida
  [ok]   com a data e a hora do banco     [ok]   com a consultora
  [ok]   e o TEXTO_FALLBACK não aparece em lugar nenhum
```

**Um cenário do teste estava mal isolado e foi corrigido durante o sprint:** por `_avancar`,
"confirmação recusada" nem existe — a recusa apanha primeiro a fala do LLM e o
`if ... == ETAPA_Q_TRANSFERIDO: return` devolve antes. O caso real é estreito (a chave cair
*entre* as duas falas, ou a Meta recusar só a segunda) e por isso é exercitado direto em
`_concluir`.

---

## 3. S3-2 — o rastro do P0-E saindo do processo

### A causa, reproduzida na mão

```python
logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)
logging.getLogger("agente.llm").isEnabledFor(logging.INFO)     # -> False
logging.getLogger("agente.llm").isEnabledFor(logging.WARNING)  # -> True
```

`LOGGING_CONFIG` do uvicorn **não tem chave `root`** (verificado, e travado em teste).
Configura só `uvicorn`, `uvicorn.error` e `uvicorn.access`; o root fica sem handler, o
`logging` cai no `lastResort` e o `lastResort` corta abaixo de WARNING. Daí a assimetria que o
RECON mediu: *"FORA DO CONTRATO"* (`log.warning`) era mensurável, e o turno bem-sucedido
(`log.info`) não.

**E até o P1-A isso ficava escondido:** o `echo=True` do engine instalava um handler e o INFO
aparecia por acidente, afogado em SQL. O P1-A trocou para `echo=False` — correto, resolveu os
4,0 GB e as 36 750 linhas suprimidas de 25/08 — e levou junto o handler que sustentava o
acidente.

### Por que isto não traz os 4 GB de volta

| Mecanismo | Vale? |
|---|---|
| `getLogger("sqlalchemy.engine").setLevel(WARNING)` | **não basta** — `create_async_engine(echo=True)` chama `setLevel(INFO)` **depois** deste módulo rodar, e sobrescreve sem aviso |
| **Filtro no handler** | **é o que segura** — o registro chega ao handler e é descartado ali, independente de nível, de `echo` e de quem mexeu no logger |

Os dois estão aplicados; o filtro é a defesa. Travado no grupo 3 do teste, que **liga
`echo=True` na mão**, confirma que o *logger* reabilitou, e afirma que mesmo assim nada sai —
sem calar o resto do processo junto:

```
3) O SQL fica de fora — inclusive com `echo=True` de volta
  [ok] SELECT em INFO é descartado
  [ok]   echo=True reabilita o LOGGER
  [ok]   e mesmo assim NADA sai (o filtro está no handler)
  [ok]   sem calar o resto do processo junto
4) WARNING do SQLAlchemy passa — erro é notícia, SELECT não é
```

`SQL_MUDO=0` no ambiente desliga o filtro. É a válvula para depurar SQL por alguns minutos
sem editar código, e existe justamente para ninguém ser tentado a voltar `echo=True`.

Terceiros barulhentos (`httpx`, `openai`, `httpcore`, `urllib3`, `asyncio`, `google`,
`twilio`, `watchfiles`…) em WARNING por lista explícita: o agente faz 1–2 chamadas à OpenAI por
turno, mais Meta e Exact, e uma linha INFO por request não é sinal.

### O que não é tocado

* os `print()` do projeto (🚀 🔒 🛟 ➡️ ✅) — vão para stdout, o journald pega, **nenhum passa a
  duplicar**;
* os loggers do uvicorn — `uvicorn` tem `propagate=False` com handler próprio, e
  `uvicorn.error`/`uvicorn.access` param nele. Nada deles chega ao root, então não há linha
  dobrada.

### A prova

**Provado agora, no journald de produção** — uma linha INFO de um logger do projeto chegando
ao destino, que é a afirmação central do item:

```
2026-08-27T00:49:16+0000 uvicorn[1611266]: 2026-08-27T00:49:16.358 INFO agente.boot:
    logging configurado — root=INFO, handler no stderr, SQL filtrado=True
```

E o contrapeso, no mesmo boot: **`grep -c 'sqlalchemy.engine'` = 0**.

**Ainda PENDENTE:** a linha `🧠 LLM … acao=…` propriamente dita, que depende de um turno real
de lead. O restart foi às 00:49 UTC (21:49 SP), fora do horário comercial, e as aberturas
pendentes estão agendadas para 27/08 09:00. Um vigia ficou armado sobre o journald. Comando
para conferir a qualquer momento:

```bash
journalctl -u cenat-backend --since "2026-08-27 00:49" | grep -E "🧠 LLM|🏷️"
```

É com essa linha que a pergunta *"com que frequência o modelo devolve `ofertar_agenda`?"* passa
a ter número — a pergunta que a auditoria de 26/08 e o RECON de 27/08 não puderam responder.

---

## 4. S3-3 — `_curso()` com segunda fonte

`_curso()` lia `sub_source` **só** de `exact_leads`. O lead da LP nasce na Exact e só entra
naquela tabela no sync seguinte, enquanto a abertura dispara em 5 minutos. A Sônia
(`5566997112651`):

```sql
select exact_id, sub_source, synced_at from exact_leads where exact_id=51571878;
-- 51571878 | Pos TEA V3 | 2026-08-27 00:19:53   <-- a abertura saiu 26/08 14:55 UTC
```

E o que saiu no WhatsApp dela, literalmente:

> "Vi que você aplicou para a nossa **Pós-Graduação em .** Antes de te mostrar os horários…"

**2 de 2 leads da LP (100%).** Mais duas aberturas foram *recusadas* pelo mesmo campo — o
`#131008` local do `nat_sender`, `parâmetro(s) [2] em branco`.

A segunda fonte é `agendamentos.sub_source`, que tem o dado **desde o instante do formulário**
— a mesma tabela e a mesma ordem (`id DESC`) que `_identidade_do_lead` já usava para salvar o
**nome** no mesmo cenário. Não é fonte nova no módulo: é a fonte que já resolvia metade do
problema.

### O que este fix NÃO resolve — dito, não escondido

Com as duas fontes vazias ainda se devolve `""`, e `""` tem dois destinos conforme a janela de
24 h:

```
janela FECHADA -> nat_sender confere `vazios` e RECUSA o envio inteiro.   Correto.
janela ABERTA  -> vai como texto livre, e o buraco chega ao lead.         Errado.
```

A assimetria mora em `nat_sender.send_nat_message` (a checagem de parâmetro em branco só existe
no ramo do template), **não** em `_curso`, e consertá-la mexe no **único ponto por onde todo
envio da NAT passa**. Fora do escopo de um item de baixo risco. Está na docstring e é candidata
ao próximo sprint.

---

## 5. S3-4 — `_nome()` com o cadastro primeiro

```sql
select wa_id, name from contacts where wa_id='5511940718388';
-- 5511940718388 | Eve 🍒🦖🤞
-- exact_leads.name / agendamentos.nome: "Evelyn Renata Begliomini Manfrim"
```

A abertura saiu **"Olá, Eve!"** para quem se inscreveu como Evelyn e vai aparecer como Evelyn
na reunião com a consultora. O perfil do WhatsApp é apelido; o cadastro é o nome com que a
pessoa se candidatou.

### O `#131008` não volta, e a razão é estrutural

**O conjunto de fontes não mudou — só a preferência.** O caso "vazio" continua sendo os **dois**
lugares vazios, e aí a recusa local do `nat_sender` pega antes da Meta. Trocar a ordem não pode
criar um vazio novo porque nenhuma fonte foi removida. Travado nos grupos 5 e 6 de
`test_identidade_abertura.py`, e no grupo 16 de `test_risco3_abertura.py`.

### E obrigou um `.strip()` — achado pelo próprio teste

`primeiro_nome` devolve a entrada **intacta** quando nenhum token tem letra (está na docstring
dela, e é a decisão certa lá: *"'Olá, 123!' é ruim, 'Olá, !' é pior"*). Logo
`primeiro_nome("   ")` é `"   "`, que é **truthy**.

Com a ordem antiga isso quase não aparecia: a primeira fonte era o perfil do WhatsApp, que o
próprio WhatsApp normaliza. A primeira fonte agora é `agendamentos.nome`, **campo livre de
formulário e `nullable=False`** — só-espaço é plausível ali. Sem o `strip`, um cadastro em
branco venceria um perfil perfeitamente bom, o parâmetro sairia vazio e a recusa local mataria a
abertura de um lead que **tinha** nome.

Trocar a ordem não podia introduzir um modo de falha novo. O `strip` é o que garante isso.

### Um teste existente foi ATUALIZADO, não removido

`test_risco3_abertura.py` grupo 16 travava a ordem antiga:

```
❌ contato COM nome continua mandando
❌   e nem consulta o lead
```

São exatamente as duas asserções que o S3-4 inverte. O que o grupo protege — **existir nome em
alguma das duas fontes basta para a abertura sair** — continua travado, agora pelos dois lados,
**mais** o caso das duas vazias, que ele não cobria.

---

## 6. Item 5 — PROPOSTA, não implementada: reaction e rajada

Pedido explicitamente como proposta para sprint próprio. **Nenhuma linha escrita.**

### 6.1 O que se observa hoje

**(a) Reaction de emoji dispara um turno inteiro do LLM.** Marina (`5581982397261`), 26/08:

```
14:30:22 lead:   (reaction, sem texto)
14:30:25 agente: "Marina, você concluiu a graduação em que ano?"
14:34:00 lead:   (reaction, sem texto)
14:34:04 agente: "Oi Marina! Em que ano você concluiu a graduação (ou está cursando)?"
```

**(b) Rajada do lead gera turnos concorrentes e perguntas duplicadas.** A mesma conversa, 65
minutos depois:

```
15:34:20 lead:   "Empreendimento. / Atendo a domiciliar"
15:34:23 agente: "Entendi: você atua em um empreendimento e faz atendimentos domiciliares.
                  O que despertou seu interesse pela pós…?"
15:34:31 lead:   "E em locais"
15:34:36 agente: "Você mencionou que atende em domicílio e em locais — ótimo contexto.
                  O que despertou seu interesse pela pós…?"
```

Duas mensagens em 13 segundos fazendo a mesma pergunta. E antes disso, o mesmo mecanismo fez
o agente tratar a resposta do **ano** como se fosse a **atuação**:
*"Entendido — você atua como formanda em 2023."*

### 6.2 A causa, no código

`main.py` chama `processar_texto_agente` para **todo** tipo de mensagem. Só o fluxo velho é
filtrado por tipo:

```python
dono_agente = await processar_texto_agente(msg["from"], content, wa_message_id, db)
if not dono_agente:
    from app.nat_flow import processar_clique, processar_texto
    if evento_botao:
        await processar_clique(evento_botao, db)
    elif msg_type == "text":            # <-- o filtro existe AQUI, e só aqui
        await processar_texto(msg["from"], content, wa_message_id, db)
```

`qualificacao_fluxo.processar_texto` também não olha `message_type` nem conteúdo vazio: uma
`reaction` entra com `content=""`, arma o vigia, monta o contexto e chama o LLM.

**Efeito colateral que vale nomear:** a `reaction` também **arma o vigia do P3-A**
(`_armar_vigia` roda em todo inbound). Se o agente não falar depois de uma reação, a gestão
recebe um "AGENTE MUDO" por causa de um emoji — falso positivo no detector cuja razão de
existir é não errar.

### 6.3 O que a proposta faria

1. **Ignorar `reaction` como gatilho de turno.** A mensagem continua sendo gravada em
   `messages` (o SDR precisa vê-la); o que muda é que ela não abre turno, não arma o vigia e
   não reinicia o relógio de inatividade.
2. **Coalescer rajada.** Janela de ~5 s: o primeiro inbound agenda o turno, os seguintes dentro
   da janela apenas se juntam ao texto e reagendam. Um turno, com as mensagens todas.

### 6.4 Análise de risco na precedência do webhook

**Onde dói.** A precedência é *"um dono por mensagem"* e está montada sobre uma constante só
(`ETAPAS_QUALIFICACAO_ATIVAS`), justamente para que **"o agente escuta" e "o agente fala" nunca
divirjam**. O valor de retorno de `processar_texto_agente` é o que decide se o fluxo velho roda.
Qualquer mudança aqui mexe nesse contrato.

| Risco | Gravidade | Nota |
|---|---|---|
| **Ignorar `reaction` mudar o retorno para `False`** e a mensagem cair no fluxo velho | **alto** | Uma reação de um lead do agente iria para `nat_flow.processar_texto`. Hoje não vai, porque o agente sempre devolve `True`. Uma reação tem `content=""`, então o dano seria pequeno — mas o princípio "um dono por mensagem" seria quebrado. **Mitigação:** devolver `True` (dono, sem turno), não `False`. |
| **Coalescer exige guardar o turno pendente** — nova ação agendada, novo kind, novo estado durável | **alto** | É estado novo dentro do webhook, que é onde P0-A, P0-C e Risco 3 já mostraram que erro custa lead. O `KIND_RESPONDER_PENDENTE` é precedente, mas ele é *saída* adiada; isto seria *entrada* adiada, coisa diferente. |
| **A janela de coalescência atrasa a resposta** | médio | Latência medida hoje: p50 3,7 s. Uma janela de 5 s mais que dobraria a mediana. Não é fatal, mas o único número bom do RECON piora. |
| **Interação com a idempotência (`ultimo_wa_message_id`)** | médio | `_ja_processado` compara UM wamid. Um turno coalescido cobre N mensagens; se a Meta reentregar a 2ª, ela não bate com o wamid gravado e vira turno duplicado. Exige repensar a trava. |
| **Interação com o vigia (P3-A) e com `encerrar_inativo`** | médio | Os dois são armados por inbound. Coalescer significa decidir se rearmam por mensagem ou por turno — e o vigia mede *espera do lead*, que é medida do **primeiro** inbound da rajada, não do último. |
| **A rede do P0-C** | baixo | Já cobre o turno inteiro estourando; um turno coalescido não muda a natureza dela. |

**Conclusão da análise:** o item (1), reaction, é pequeno e quase todo o ganho — **desde que a
mitigação seja devolver `True`**. O item (2), coalescer, é uma mudança de arquitetura do
webhook, não um fix: mexe em idempotência, no vigia, no encerramento por inatividade e na
latência de uma vez só. **Recomendação: separar os dois.** Reaction cabe num sprint de baixo
risco com o teste certo; coalescer merece sprint próprio, com decisão explícita sobre a régua
de idempotência antes de escrever a primeira linha.

---

## 7. Checklist de boot — 27/08 00:49:16 UTC

```
1. serviço ativo ......... active
2. PID / commit .......... 1611266 / 4a8a058
3. startup complete ...... 1
4. linha do logging ...... 1   <-- a prova do S3-2
   2026-08-27T00:49:16.358 INFO agente.boot: logging configurado —
       root=INFO, handler no stderr, SQL filtrado=True
5. SQL no journald ....... 0 linhas   (esperado 0 — os 4 GB não voltaram)
6. tracebacks ............ 0
7. erros/exceções ........ 0
8. jobs subiram:
   ✅ CORS do agendamento          ✅ Alertas de janela 24h (a cada 5 min)
   ✅ Sync Exact Spotter (10 min)  ✅ Agendamento de templates (60s)
   ✅ Agendador NAT ativo (60s)
9. banco intacto ......... 43 estados, 55 ações pendentes (idêntico ao pré-restart)
```

O processo anterior (1605282, 9 h 58 min) consumiu 29 min 51 s de CPU e parou limpo
(`Deactivated successfully`).

---

## 8. O que continua fora — e por quê

| Item | Situação |
|---|---|
| **#2 disparo em massa não excluir conversa viva** | **travado na gestão.** É a maior perda do funil (22 de 43, 51%) e muda o comportamento de uma ferramenta que o SDR usa todo dia |
| **#3 abertura T2/T3 afirmar antes de perguntar** | **travado na gestão.** Exige template novo aprovado pela Meta |
| **#4 base de conhecimento no prompt** | **travado na gestão.** Exige texto oficial validado — LLM afirmando preço errado é pior que não responder |
| **#7 reaction + rajada** | proposta acima, §6. Recomendado partir em dois |
| Parâmetro em branco no ramo de janela ABERTA | descoberto no S3-3, §4. Mexe em `send_nat_message` |
| Trajetória de etapas (histórico) | lacuna de instrumentação do RECON §4; não é fix, é tabela nova |
