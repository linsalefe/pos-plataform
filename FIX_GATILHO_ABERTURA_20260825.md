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
