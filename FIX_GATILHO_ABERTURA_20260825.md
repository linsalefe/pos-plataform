# A fila do agente passou o dia vazia — dois bugs, um em cada caminho

**25/08/2026.** Diagnóstico do caso "o diretor aplicou pela LP às 11h30 e a Nat não abriu".

Estado no momento da investigação (11h47 SP): `nat_config.qualificacao_enabled = true`,
`auto_welcome_config.enabled = false`, **`nat_scheduled_actions` com ZERO linhas** — e 73
leads entrando no dia.

```
 relname               | n_tup_ins | n_live_tup
 nat_scheduled_actions |        57 |          0
```

57 inserts. Nenhuma linha viva. A fila não estava vazia por falta de gatilho: estava vazia
porque **tudo que entrou nela foi desfeito**, e porque o outro caminho **morria antes de
chegar nela**.

---

## 1. Caminho LP — a hipótese do formulário está REFUTADA

> *hipótese: o form em si só manda pra Exact/mídia, e os nossos endpoints só são chamados
> pelo widget da página de obrigado.*

Não é isso. O formulário nativo da LP **posta no nosso servidor**, com `Referer` da própria
landing page:

```
201.80.172.130 - [25/Aug/2026:14:23:51] "POST /api/agendamento/lead" 200
  "https://posmdotrabalhadort3.cenatsaudemental.com/"
179.109.170.167 - [25/Aug/2026:14:21:38] "POST /api/agendamento/lead" 200
  "https://postea.cenatsaudemental.com/"   (Android, in-app browser do Instagram)
```

Foram **31 POSTs** hoje, de 6 domínios de LP diferentes. `POST /lead` chama
`cadastrar_lead_sem_agendar`, que termina em `_gatilho_do_agente` → `agendar_abertura`.
O gatilho de formulário cobre **exatamente quem queríamos**: quem preenche e NÃO agenda.
A cobertura planejada está de pé.

### O bug: a ação é inserida, anunciada no log, e nunca commitada

`nat_scheduler.agendar` é primitiva **por desenho** — dá `flush()` para materializar o id do
BIGSERIAL e não commita, porque "quem chama decide a fronteira da transação"
(`nat_scheduler.py:150`). Só que **nenhum dos dois chamadores da landing page commitava
depois**:

- `cadastrar_lead_sem_agendar` → `_gatilho_do_agente` → `return lead_id`
- `agendar` (booking) → `_gatilho_do_agente` → `return Resultado(...)`

A sessão do `get_db` (`async with async_session() as session: yield session`) fecha **sem
commit** → rollback → a linha some.

E o log **jurava o contrário**, porque o print vem do `flush()`:

```
14:23:51  👤 agendamento #183: lead 51543718 cadastrado sem agendar
14:23:51  ⏰ NAT scheduler: iniciar_qualificacao agendado para 5582998307979 às 11:28:51 (id=57)
```

31 aberturas anunciadas com id (27 a 57). Zero sobreviveram. **Log de sucesso emitido antes
do commit é pior que log nenhum** — foi ele que fez a fila vazia parecer "não enfileirou"
em vez de "enfileirou e perdeu".

O mesmo commit faltante levava junto o **lembrete de reunião** no caminho do booking — e
quem agenda pelo obrigado.html nunca passa pelo fluxo do agente, então era o único lembrete
que essa pessoa teria.

---

## 2. Caminho sync — `UnboundLocalError` no passo 4.5

```
14:45:52  ❌ Erro no sync Exact Spotter: local variable 'timedelta' referenced before assignment
```

`exact_spotter.py` tinha, **dentro** de `send_welcome_to_new_lead` (linha ~330):

```python
from datetime import timezone, timedelta
SP_TZ = timezone(timedelta(hours=-3))
```

Um import dentro da função torna o nome **local à função inteira** — inclusive para as
linhas *acima* dele. O passo 4.5, 80 linhas antes, faz:

```python
nascido = lead_data.get("register_date")
await agendar_abertura(..., nascido_em=(nascido - timedelta(hours=3)) if nascido else None)
```

`timedelta` ali não é mais o do topo do módulo: é o local, ainda não atribuído. Levanta
`UnboundLocalError` **na primeira iteração** do laço de boas-vindas.

### Por que o estrago é permanente, e não passageiro

O laço roda **depois** do `await db.commit()` que grava os leads. Ou seja:

1. os leads entram em `exact_leads` e são commitados;
2. o laço estoura no primeiro lead e aborta o `sync_exact_leads` inteiro;
3. na passada seguinte, todos caem no ramo `existing` e **nunca mais** entram em
   `new_leads_to_contact`.

Resultado: **42 leads de hoje com `welcome_status` NULL** — sem carimbo, sem boas-vindas,
sem abertura do agente, e invisíveis para os dois caminhos para sempre.

---

## 3. Os três suspeitos levantados — o que cada um deu

| # | Suspeita | Veredito |
|---|---|---|
| 1 | "cede a abertura pro agente" vive dentro do bloco gateado por `auto_welcome_config` | **REFUTADO.** `agente_ligado` segura o return do passo 1 (`exact_spotter.py:205`). Foi tratado em 24/08 e está correto — o lead com a automação desligada e o agente ligado *chega* ao 4.5. Ele só não sobrevive a ele. |
| 2 | comparação naive-SP × UTC na trava do `start_at` | **REFUTADO.** `agendar` grava `run_at = _agora_sp() + 5min`; `processar_pendentes` corta com `corte = _agora_sp()`. Mesma referência, naive-SP dos dois lados. |
| 3 | skip silencioso sem log | **REFUTADO como causa** — e invertido. O problema não foi ausência de log: foi um log que **mentia**, afirmando sucesso antes do commit. |

---

## 4. O caso do diretor especificamente: ele não existe em NENHUM dos dois caminhos

- **nginx:** zero requests de qualquer LP depois de **14:23:52 UTC (11:23:52 SP)** — nem
  `POST /lead`, nem `OPTIONS`, nem `GET /slots`. Nada.
- **Exact:** consultada ao vivo (`/v3/Leads?$orderby=Id desc`), o lead mais novo do CRM é
  `51543718 · Ronaldo Cesat · 2026-08-25T14:23:51Z`. **Não existe lead nenhum depois disso.**
- Nosso espelho está em dia com a Exact: mesmo `exact_id` como máximo dos dois lados.

Ou seja: às 11h30 nada chegou, nem a nós nem ao CRM. O rastro do lead dele **não começa**.
As hipóteses restantes são: (a) o "11h30" é aproximado e ele é um dos cadastros de
11:21–11:23; (b) a submissão dele não completou no navegador; (c) foi por outro canal.
**Precisa do nome/telefone dele para fechar** — com isso o rastro sai em um comando.

---

## 5. As correções

**`app/exact_spotter.py`**
- `timezone` sobe para o import do topo; o import local sombreador foi removido, com
  comentário explicando por que ele não pode voltar.
- O laço de boas-vindas passa a **isolar cada lead num SAVEPOINT**. Um lead que estoure não
  derruba mais o lote, e o log nomeia o `exact_id` e o nome — que é a única trilha de
  recuperação, já que o lead não volta na passada seguinte.

**`app/agendamento/agendar.py`** — `_gatilho_do_agente` vira o **dono do commit** das duas
ações. Commita uma vez, depois da abertura e do lembrete, e só se alguma das duas de fato
inseriu. Falha de commit é ruidosa: `❌ ... COMMIT das ações do agente FALHOU`.

**`app/qualificacao_gatilho.py` / `app/qualificacao_fluxo.py`** — `agendar_abertura` e
`agendar_lembrete` passam a devolver `bool`. As duas têm saídas silenciosas legítimas
(contato que já tem estado, reunião cedo demais) e o chamador não tinha como distinguir
"enfileirei" de "decidi não enfileirar" — commitaria por um efeito que não aconteceu.
*Este ponto foi encontrado pelo próprio teste 8, não por leitura.*

---

## 6. O teste — `backend/test_gatilho_abertura.py` (8/8)

```
cd backend && venv/bin/python test_gatilho_abertura.py
```

### Por que a suíte que já existia não pegou

`test_welcome_guardrail.caso_4b` exercita exatamente o passo 4.5 com o agente ligado e a
automação desligada — e passava. O motivo é uma linha:

```python
def _lead_data(lead):
    return {"exact_id": ..., "name": ..., "phone1": ..., "sub_source": ..., "funnel_id": ...}
    #  <-- sem register_date
```

Sem `register_date`, `nascido` é `None`, e
`(nascido - timedelta(hours=3)) if nascido else None` **curto-circuita**. `timedelta` nunca
chega a ser avaliado. O teste percorria o passo 4.5 pela metade — a metade sem a data. E
`sync_exact_leads` **sempre** manda essa chave.

### Os 8 casos

| | caso | o que trava |
|---|---|---|
| 1 | sync, lead **com** `register_date` | o caso literal de produção; morria com UnboundLocalError |
| 2 | sync → fila, **sem mock no gatilho** | a cadeia inteira até a `NatScheduledAction`, que o mock do caso 1 esconde |
| 3 | nenhum nome de `datetime` é local em 4.5 | varre `co_varnames` do bytecode — trava a **classe** do bug, não a instância |
| 4 | um lead ruim no meio do lote | os outros 2 seguem e são decididos |
| 5 | `POST /lead` | abertura enfileirada **e commitada**, na ordem `add → flush → commit` |
| 6 | `POST /agendar` | abertura + lembrete no **mesmo** commit |
| 7 | gatilho falhou | **não** commita |
| 8 | contato já tem estado | não enfileira e **não** commita |

O caso 3 é o que mais importa a longo prazo: qualquer `from datetime import ...` que reapareça
dentro daquela função quebra o teste, em vez de esperar a próxima produção.

**Não-regressão:** `test_welcome_guardrail` 17/17 · `test_qualificacao` ok ·
`test_espontaneo` ok · `test_agendamento` 33/33 · `test_nat_flow` 13/13.

---

## 7. Pendências que este fix NÃO resolve

1. **DEPLOY.** O código está no disco e nos testes; o serviço **ainda roda o binário
   antigo**. `sudo systemctl restart cenat-backend.service`.
2. **Os 42 leads órfãos de hoje** (`welcome_status` NULL, `register_date` de 25/08). Não
   voltam sozinhos: já são `existing` no sync. Precisam de decisão — backfill do gatilho ou
   passar a lista para as consultoras à mão.
3. **Ninguém agendou hoje.** `passo='agendado'` = **0** (média de 3 a 9/dia na semana). As
   únicas 3 tentativas de `POST /agendar` deram **502**:
   `HTTP 400: Previous stage is not exit action Scheduling` — as três em leads que já
   existiam na Exact (`lead_externo=true`). Incidente **separado** deste, e não investigado
   aqui.
4. **O log está sendo engolido.** `journald`: `Suppressed 36750 messages from
   cenat-backend.service`. A causa é `create_async_engine(..., echo=True)` em
   `app/database.py`, que joga todo SQL no stdout e afoga as linhas que importam. Enquanto
   isso durar, ausência de log **não é evidência de ausência de evento**.
5. **Fluxo de leads parado.** Nada entrou na Exact entre 11:23:51 e 11:47 SP, depois de um
   ritmo de ~1/min. Pode ser normal; combinado com o relato do diretor, merece um olhar.

---

# ADENDO (15h20 UTC) — deploy feito, fila provada, e um TERCEIRO bloqueio a jusante

## O que ficou provado em produção

Backend reiniciado às **15:02:56 UTC** (PID 1587117, startup limpo). O sync das **15:12:56**
foi o primeiro do dia a atravessar o laço de boas-vindas inteiro, **sem `❌ Erro no sync`**.

```
 id |         kind         | contact_wa_id |        run_at        |   status  | attempts
 60 | iniciar_qualificacao | 5582998307979 | 2026-08-25 12:18:35  | executado |        0
 61 | iniciar_qualificacao | 5565996306463 | 2026-08-25 12:18:35  | executado |        0
```

| | antes | agora |
|---|---|---|
| `n_tup_ins` | 57 | 61 |
| `n_live_tup` | **0** | **2** |

Enfileirou, **sobreviveu ao commit** (lido de conexão separada), venceu no horário e drenou
com `attempts=0`. E os leads saíram **carimbados** — `welcome_status='skipped'`, motivo
`agente de pré-qualificação assumiu a abertura` — o que nenhum dos 42 anteriores ficou.

Detalhe que fecha o ciclo: os ids **58 e 59 não existem**. Houve um `POST /agendamento/lead`
às 14:59:56, três minutos antes do restart — esses dois leads passaram pelo caminho LP com o
código velho, foram enfileirados, anunciados no log e desfeitos. O sync das 15:13, já
corrigido, recuperou os mesmos dois como 60 e 61. O bug e o fix no mesmo par de leads.

**Os dois bugs deste documento estão resolvidos.** O caminho LP ainda não passou tráfego
depois do restart (o único POST do período veio antes dele) — falta só a confirmação
orgânica.

## O que NÃO funcionou: a abertura não saiu

```
🔒 NAT não enviou (nat_abertura_qualificacao → 5582998307979): contato não existe no banco
↩️  Agente: abertura de 5582998307979 não saiu — estado descartado
↩️  Agente: 5565996306463 não existe em contacts — abertura ignorada
⏱️  NAT scheduler: {'executado': 2}
```

`nat_qualificacao_state` continua com **zero linhas**. Ação executada sem estado
correspondente — que é exatamente a assinatura que `monitor_qualificacao.py` §2b procura.
Aqui, ao menos, ela **não foi silenciosa**: os três motivos estão no log.

### Causa raiz: quem só preencheu o formulário não tem linha em `contacts`

`contacts` nasce de duas formas: mensagem inbound no WhatsApp, ou como **efeito colateral do
envio da boas-vindas** (`send_welcome_to_new_lead` cria o `Contact` junto com a `Message` do
template, no passo 7). O passo 4.5 **cede a abertura ao agente e sai antes disso** — e nada
passou a criar o contato no lugar.

Quem se candidata pela LP e nunca mandou mensagem simplesmente não existe em `contacts`.
Medido nos leads de hoje:

```
 sem linha em contacts : 33
 com linha em contacts : 11
```

**Três de cada quatro leads não podem receber a abertura**, com fila cheia e agente ligado.

### E os dois leads falharam de formas DIFERENTES — a segunda é pior

`iniciar_qualificacao` usa `_contato_de()`, que é **tolerante ao 9º dígito**
(`variantes_wa_id`). `nat_sender.enviar` faz `Contact.wa_id == contact_wa_id`, **igualdade
estrita**. Os dois discordam, e o resultado depende de qual lead é:

- **5565996306463 (Adriana):** não há contato em grafia nenhuma → porteiro fecha → saída
  limpa, sem estado. Comportamento correto.
- **5582998307979 (Ronaldo Cesar):** o porteiro **abriu** — mas a linha que ele encontrou é

  ```
   wa_id        | name          | created_at
   558298307979 | Pablo Valente | 2026-07-22 19:13:38
  ```

  **outra pessoa.** A variante de 12 dígitos do número do Ronaldo é o número do Pablo. O
  estado foi criado, e só não houve envio porque o `nat_sender` é estrito e não achou os 13
  dígitos. A igualdade estrita — que é a inconsistência — foi o que impediu o estrago.

`contato` é usado **só como porteiro**: é atribuído, testado contra `None` e nunca mais lido.
Então a tolerância não está resolvendo identidade, está só afrouxando uma tranca — e um
falso positivo dela é um lead entrando no fluxo pela linha de um estranho.

## Decisões pendentes (nenhuma tomada aqui)

1. **Quem cria o `Contact` no caminho do agente?** Sem isso a fila enche e drena sem efeito
   para 3 em cada 4 leads. Opções: criar no passo 4.5, criar no handler antes do envio, ou
   deixar o `nat_sender` criar quando a abertura for business-initiated.
2. **O porteiro tolerante × sender estrito.** Precisa ser UMA regra só. E a tolerância ao 9º
   dígito, do jeito que está, casa pessoas diferentes — merece decisão explícita, não
   alinhamento automático para o lado tolerante.
3. As pendências 2 a 5 da seção anterior continuam de pé.
