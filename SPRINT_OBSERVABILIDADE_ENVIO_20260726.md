# Sprint — Observabilidade de envio e autenticação dos endpoints abertos (2026-07-26)

Branch `feat/observabilidade-envio-20260726`. **Sem merge** — Álefe faz manual.

O buraco que a sprint fecha: o incidente `131042` durou 4 dias porque o sistema **não sabia que
estava falhando**. `exact_leads.welcome_status` era carimbado `'sent'` quando a Meta *aceitava* o
envio, e o `failed` que chegava depois pelo webhook de status nunca realimentava a tabela. O painel
mostrou 254 sucessos enquanto 100% falhava.

A NAT continua **DESLIGADA** (`nat_enabled=false`, `nat_start_at=NULL`) e a boas-vindas automática
continua **DESLIGADA** (`auto_welcome_config.enabled=false`, fatura da Meta em aberto). Esta sprint
não religa nada e não envia nenhuma mensagem.

---

## ⚠️ DEPENDÊNCIA DE ORDEM — ler antes de religar a boas-vindas

**O critério de reenvio (`welcome_status IN ('failed', NULL)`) é pré-requisito para religar
`auto_welcome_config`. Sem ele, toda falha de entrega vira lead perdido.**

Por quê, na ordem em que a coisa acontece:

1. **Hoje, automação desligada:** lead novo é carimbado `'skipped'` + `"automação desligada — lead
   anterior à ativação"`. É um estado **recuperável por critério explícito** — dá para varrer esses
   leads depois, porque o motivo está escrito.

2. **Depois de religar:** o lead passa a ser carimbado `'sent'` no envio. Se a entrega falhar, a
   Fase 2 desta sprint corrige o carimbo para `'failed'` — que é o ponto da sprint.

3. **O efeito colateral:** a guarda de idempotência em `backend/app/exact_spotter.py:186` é
   `welcome_status is not None`. `'failed'` não é `None`, então o lead fica **permanentemente
   bloqueado para reenvio** e não aparece como pendente em lugar nenhum.

Ou seja: esta sprint troca uma **mentira silenciosa** (`'sent'` que nunca chegou) por uma **perda
silenciosa** (`'failed'` que ninguém reprocessa). É melhor — a perda é contável e o dado é
verdadeiro — mas só deixa de ser perda quando o critério de reenvio existir.

**Portanto: critério de reenvio ANTES de religar a automação, não depois.** Esta sprint
deliberadamente **não** mexe na guarda (era a instrução), só documenta a dependência.

### Quem já está nesse limbo — a população do futuro critério de reenvio

O limbo não é hipotético: a Fase 3 acabou de colocar **68 leads** dentro dele. São exatamente os
que a sprint corrigiu de `'sent'` para `'failed'` — a mensagem foi recusada pela Meta, o lead nunca
recebeu nada, e agora está bloqueado pela guarda da linha 186 e **invisível como pendente**, porque
nenhuma tela lista `welcome_status='failed'` como "a fazer".

Quem for montar a recuperação começa por estas duas populações:

| população | quantos (26/07) | como identificar |
|---|---|---|
| **Falha de entrega** — mensagem recusada pela Meta | **68** | `welcome_status='failed'` |
| **Automação desligada** — nunca teve envio | **8.391** | `welcome_status='skipped'` + `welcome_error` começando com `"automação desligada"` |

As duas têm naturezas diferentes e provavelmente critérios diferentes: os 68 são leads de 13/07 a
26/07 que *deveriam* ter recebido e não receberam; os `skipped` incluem todo o histórico anterior à
ativação e precisam de um corte de data antes de virar fila de envio. Não confundir os dois é o
primeiro trabalho da frente de reenvio.

---

## O que subiu

| arquivo | o que é |
|---|---|
| `backend/migrate_welcome_tracking.py` | **novo** — `exact_leads.welcome_wamid` + índice parcial |
| `backend/fix_welcome_status_falso.py` | **novo** — reconciliação dos carimbos falsos (`--dry-run` é o padrão) |
| `backend/app/delivery_health.py` | **novo** — vigia da saúde de entrega, a cada 15 min |
| `backend/test_observabilidade_envio.py` | **novo** — 33 verificações, nada enviado, nada gravado |
| `backend/app/models.py` | `ExactLead.welcome_wamid` |
| `backend/app/exact_spotter.py` | grava o `wamid` junto do carimbo de envio |
| `backend/app/main.py` | `_realimentar_welcome_status` + chamada no webhook de status + job no `lifespan` |
| `backend/app/routes.py` | auth em `/send/text`, `/send/template`, `/send/media` |
| `backend/app/exact_routes.py` | auth em `/bulk-send-template` |

Estado das flags no momento do commit — **nada foi religado**:

```
nat_config.nat_enabled        = False
nat_config.nat_start_at       = NULL
auto_welcome_config.enabled   = False
```

---

## Fases

### Fase 1 — Vínculo mensagem ↔ lead

`backend/migrate_welcome_tracking.py` (**novo**) — `exact_leads.welcome_wamid` TEXT nullable, com
índice parcial `WHERE welcome_wamid IS NOT NULL`. Aplicada em produção em 26/07.

Sem esse vínculo o webhook de status não tinha como saber a qual lead a falha pertencia: o status
chega com o `wamid` e o `wamid` não estava guardado em lugar nenhum do lado do lead.

Decisões de schema: TEXT (não VARCHAR — o formato é opaco e definido pela Meta, e truncar dentro de
um envio que já saiu seria o pior desfecho); índice **não único** (um `UNIQUE` transformaria
qualquer colisão inesperada num `IntegrityError` dentro do envio); sem FK (a escrita acontece no
fluxo de envio e uma FK só acrescentaria um jeito de derrubá-lo).

`send_welcome_to_new_lead` passou a gravar o wamid junto do carimbo. Comportamento de envio
inalterado.

### Fase 2 — Realimentar o `welcome_status`

`_realimentar_welcome_status` em `backend/app/main.py`, chamada no laço de `statuses[]` do webhook.

- `failed` → `welcome_status='failed'` + `welcome_error` com o código e o `details` **literal** da
  Meta. Foi a ausência do `details` que transformou "está falhando" em quatro dias de investigação:
  o código sozinho (`131042`) não diz que a conta está com pagamento pendente; o `details` diz.
- `delivered` / `read` → `welcome_status='delivered'`. `read` também vira `delivered` porque o que
  a coluna responde é "a mensagem chegou?", e distinguir lido de entregue não muda decisão nenhuma.
- `sent` fica **de fora de propósito**: é exatamente o que o envio já carimbou, e foi acreditar
  nele que produziu o painel mentiroso.

Duas defesas que sobreviveram à revisão do Checkpoint 2:

- **`delivered` não desfaz `failed`.** A Meta não entrega o que recusou, então isso só aconteceria
  com webhook fora de ordem — falha real e difícil de diagnosticar depois. Apagar o `failed`
  devolveria justamente a mentira que a sprint existe para eliminar.
- **Sem `wamid`, sai sem tocar em nada.** `welcome_wamid == None` viraria `IS NULL` no SQL e
  casaria com os 8.391 leads que nunca tiveram envio — um carimbo em massa a partir de um payload
  malformado.

O pareamento por `welcome_wamid` é o próprio teste de "é boas-vindas?": a coluna é escrita por um
caminho só. Status de mensagem de atendente ou de campanha não casa com lead nenhum e sai sem
efeito — não é preciso olhar `message_type`.

Tudo dentro de `begin_nested()` com `except` largo: um erro de banco aqui deixaria a transação do
asyncpg abortada e **todo status seguinte do mesmo lote** falharia com `InFailedSQLTransaction`.

### Fase 3 — Correção dos carimbos falsos

`backend/fix_welcome_status_falso.py` (**novo**), rodado em produção em 26/07. Ver "Quantos estavam
mentindo" abaixo.

O script **não importa `app.whatsapp`** (nem `app.exact_spotter`, que o importa no nível de módulo):
`format_phone` está reimplementada, idêntica ao original. Um script de correção de dados não pode
ter no import um cliente HTTP capaz de enviar mensagem.

Pareamento em dois caminhos, nessa ordem de confiança: `welcome_wamid` quando existe (vínculo exato,
mas nenhum dos 254 tinha — a coluna nasceu depois deles), senão telefone + janela de ±10s em torno
de `welcome_sent_at`, restrito a `message_type='template'` e `direction='outbound'`.

**A janela não é um chute.** A `Message` e o carimbo do lead são gravados na mesma transação do
envio: medido nos 254 leads reais, o maior delta é de **33 milissegundos**, e ±1s já pareava 254 de
254. O padrão de ±10s dá ~300x de folga sobre o pior caso observado e mesmo assim rendeu **0
ambíguos e 0 sem mensagem** — é a melhor evidência disponível de que os 68 são reais.

Regra de ouro: **na dúvida, não mexe.** Com >1 template na janela o lead vai para `AMBÍGUO` e não é
tocado — sem desempate por proximidade, que seria um palpite com cara de precisão. Subestimar a
correção deixa um lead a menos na lista; superestimar apaga uma entrega real e alimenta a mesma
desconfiança no dado que a sprint existe para curar.

### Fase 4 — Alerta de saúde de entrega

`backend/app/delivery_health.py` (**novo**), registrado no `lifespan` de `main.py` junto dos outros
jobs. Roda a cada **15 min**, janela de **1 hora**, só `direction='outbound'` e
`message_type='template'`.

| limiar | valor | |
|---|---|---|
| `MINIMO_ENVIOS` | 5 | piso de volume, para quebra **e** para recuperação |
| `LIMIAR_QUEBROU` | ≥ 50% | taxa de falha que dispara o alerta |
| `LIMIAR_VOLTOU` | < 10% | taxa que permite anunciar normalização |
| `MAX_FALHAS_PARA_VOLTAR` | 0 | teto absoluto de falhas para anunciar normalização |

**Job próprio, não handler do `nat_scheduler`.** Três razões, a terceira decisiva: o scheduler é
por contato (índice único em `(kind, contact_wa_id, pendente)`) e esta varredura é global; ele é
one-shot, então uma varredura recorrente dependeria de a execução anterior ter conseguido
reagendar; e **ele desiste** — handler que falha 3 vezes vira `falhou` e sai de circulação para
sempre. Num vigia isso é fatal: três indisponibilidades transitórias do banco e o monitor deixa de
existir em silêncio, que é exatamente a falha invisível que a sprint existe para eliminar. O
`while True` com `except` largo não tem como morrer — um ciclo ruim é um ciclo perdido.

**O estado do alerta mora na própria tabela `notifications`**: é "qual das duas notificações foi a
última" (`ORDER BY id DESC`, que é exato, em vez de `created_at`, que vem do relógio UTC do banco).
Sem tabela nova, sem migração, e **sobrevive a restart** — estado em memória seria pior que não
ter, porque um deploy no meio de um incidente zeraria o alerta e a gestão receberia tudo de novo.
Se alguém apagar as notificações, o estado volta a "normal" e um incidente em curso é anunciado de
novo: barulho a mais, nunca silêncio. É o mesmo padrão que o `window_alerts_job` já usa.

**A repetição é evitada por transição, não por ciclo:** só há notificação quando
`estado_anterior != estado`. Entre 10% e 50% nada acontece — a distância entre os dois limiares é
histerese de propósito, senão uma taxa oscilando em volta de um limiar único geraria
alerta/normalização/alerta a cada 15 minutos.

**Batimento por ciclo.** O resumo sai no log SEMPRE, inclusive na janela vazia:

```
⏱️  Saúde de entrega: 0 template(s) na janela, 0 falha(s), taxa 0%, estado=normal
```

É a tese da sprint aplicada ao próprio vigia. Na primeira versão o job só logava em transição, e
isso o tornava **indistinguível de um job morto**: "nada no log" significaria tanto "rodou e está
tudo bem" quanto "o loop caiu há três dias". Um alerta que pode morrer em silêncio é exatamente a
falha invisível que o 131042 expôs — não faria sentido corrigi-la no envio e reproduzi-la aqui.
Mesmo padrão do resumo do `nat_scheduler`.

#### O desvio do enunciado: recuperação exige zero falhas

O enunciado pedia `voltou = taxa < 10%`. Rodando essa regra hora a hora sobre o incidente real:

```
23/07 08h  QUEBROU  total=6    falhas=6   taxa=100%
23/07 15h  voltou   total=49   falhas=4   taxa=  8%   ← FALSO
24/07 11h  QUEBROU  total=7    falhas=4   taxa= 57%
24/07 16h  voltou   total=128  falhas=3   taxa=  2%   ← FALSO
estado ao final de 26/07: NORMAL
```

Duas normalizações anunciadas no meio de um incidente que não tinha acabado, e o estado final
dizendo "normal" com 100% das boas-vindas ainda falhando.

A causa é **diluição**. `messages` não guarda o nome do template, só o texto renderizado, então a
taxa é global. Às 16h de 24/07 saíram 128 templates: **125 de uma campanha em massa** ("Obrigada
por se inscrever…"), que a Meta aceitou, e **3 da boas-vindas da Nat**, que falharam. A boas-vindas
estava em 100% de falha e a taxa global marcou 2% — uma campanha saudável escondendo um fluxo morto.

Com `MAX_FALHAS_PARA_VOLTAR = 0`, o mesmo replay dá:

```
23/07 08h  QUEBROU  total=6    falhas=6   taxa=100%
estado ao final de 26/07: ALERTA          ← uma notificação, e a verdade
```

Nos 4 dias do incidente **não houve uma única hora com ≥5 templates e zero falhas**, então a regra
corrigida não teria produzido nenhum alarme falso de volta.

**Limitação conhecida, do outro lado:** a mesma diluição pode *esconder* uma quebra. Se a campanha
das 16h tivesse rodado às 08h, a taxa global de 23/07 08h seria baixa e o alerta não dispararia
naquele momento. Neste incidente ele disparou, mas foi sorte de ordenação, não projeto.

> **Frente própria (fora do escopo):** `messages.template_name`, para medir saúde **por template**
> em vez de no agregado. É a correção de verdade da diluição, e exige migração.

### Fase 5 — Autenticação nos endpoints de disparo

`POST /api/send/text`, `/send/template`, `/send/media` e `/api/exact-leads/bulk-send-template`
passaram a exigir token. Os quatro devolvem **401** sem `Authorization` (verificado com
`TestClient`, sem subir os jobs).

#### As três verificações antes de fechar

**1. Algum caminho interno chama por HTTP? Não — mas existe uma chamada direta em Python.**

`scheduled_messages_job` (`main.py:223`) faz `await bulk_send_template(payload, db)` — importando a
função e chamando dentro do processo, sem HTTP. Por isso a autenticação foi para o **decorator**
(`dependencies=[Depends(get_current_user)]`) e **não para a assinatura**. A diferença é de correção,
não de estilo: um parâmetro `usuario: User = Depends(get_current_user)` receberia, nessa chamada
direta, o próprio objeto `Depends` em vez de um `User` — silenciosamente, até alguém usar o valor.
Dependência de decorator só é avaliada pelo pipeline de request do FastAPI, então a porta HTTP fecha
e a chamada interna segue idêntica. Confirmado: a assinatura continua `(request, db)`.

É também o padrão que já existia em `/{exact_id}/resend-welcome` (`exact_routes.py:186`).

**2. O frontend manda token nas quatro? Sim — conferido no código.**

`auth-context.tsx` seta `api.defaults.headers.common['Authorization'] = Bearer <token>` na linha 43
(login) e na 29 (restauração a partir do `localStorage`), e as quatro chamadas passam pela mesma
instância `api` de `src/lib/api.ts`. As duas chamadas a `/send/media` passam
`headers: {'Content-Type': 'multipart/form-data'}` por request, mas o axios **mescla** headers de
request com os defaults — o `Authorization` sobrevive, só seria perdido se elas o sobrescrevessem
explicitamente, o que não fazem.

**3. Existe integração externa apontando para eles? Não.**

15 dias de log do nginx (12/07 a 26/07), todas as chamadas aos quatro endpoints:

| chamador | chamadas | desfecho |
|---|---|---|
| Chrome, referer `hub.cenatdata.online` | 562 | 200 (+8 `504` e 1 `499`, timeouts de disparo em massa) |
| `curl`, do IP público do próprio servidor e de um IP de casa | 6 | **todas 400/422** |

As 6 de `curl` são todas de **12/07** e todas rejeitadas por validação — é o smoke de uma sprint
anterior (registrado em `SPRINT_INSTRUMENTA_ERRO_META_20260726.md`: "`POST /api/send/text` → 422 de
validação, nenhuma mensagem real enviada"). Nenhum consumidor automatizado, nenhum serviço externo,
nenhum webhook de terceiro aponta para esses caminhos. O nginx expõe só `/api/`, `/webhook`,
`/mirror_webhook` e `/health`.

#### Achado colateral, FORA do escopo desta sprint

A varredura de todas as rotas de escrita encontrou **24 sem autenticação**. A maioria é legítima
(`/api/auth/login`, `/webhook`, os 5 callbacks do Twilio) ou é risco de outra natureza
(`/api/tags`, `/api/kanban/*`). Uma merece atenção e **não foi tocada** porque está fora do escopo:

> **`POST /api/exact-leads/sync` está aberto.** É o gatilho manual do sync do Exact, e o sync é o
> caminho que chama `send_welcome_to_new_lead` — ou seja, um POST anônimo pode disparar uma rodada
> de boas-vindas. Hoje é inerte porque `auto_welcome_config.enabled=false` (o primeiro guard-rail
> carimba `skipped` e retorna), mas ele volta a ter dentes no dia em que a automação religar. Entra
> na mesma lista de pré-requisitos do religamento.

### Fase 6 — Testes

`backend/test_observabilidade_envio.py` (**novo**) — 33 verificações, **todas passando**. Nada
enviado, nada gravado, nenhuma conexão de banco e nenhuma chamada de rede.

O relay do webhook para a CS Platform (`main.py:316`) é mockado: sem isso o teste 4 faria um POST
real para `pedagogico.cenatdata.online` a cada execução do suite.

| # | caso | resultado |
|---|---|---|
| 1 | `failed` → `welcome_status='failed'` + `details` literal da Meta | ✅ |
| 2 | `delivered` / `read` → `'delivered'` | ✅ |
| 3 | status que não é boas-vindas → `exact_leads` intacta | ✅ |
| 4 | falha ao atualizar o lead → o lote de status segue | ✅ |
| 5 | 10 envios / 6 falhas → notifica a gestão | ✅ |
| 6 | mesma condição no ciclo seguinte → não notifica | ✅ |
| 7 | taxa cai a 0 → normaliza, uma vez só | ✅ |
| 8 | 3 envios / 3 falhas → não alerta | ✅ |
| 9 | os 4 endpoints sem token → 401 | ✅ |
| 10 | regressão dos 5 suites existentes | ✅ |

Verificações que passam do enunciado, cada uma cobrindo uma decisão que teria como regredir em
silêncio:

- **`delivered` não desfaz `failed`** e `sent` não mexe em nada (teste 2).
- **`wamid` vazio sai antes de consultar** — sem isso `welcome_wamid == None` viraria `IS NULL` e
  carimbaria os 8.391 leads sem envio. Verificado contando as queries emitidas: zero (teste 3).
- **Falha sem detalhe ainda grava um motivo legível** — um `'failed'` sem motivo é a mesma cegueira
  de antes com outro rótulo (teste 1).
- **Savepoint revertido, não a transação** — 3 savepoints, 1 rollback, e os status anterior *e
  posterior* ao erro aplicados (teste 4).
- **Histerese**: taxa de 30%, entre os dois limiares, não normaliza nem re-alerta (teste 6).
- **Anti-diluição**: 128 envios com 3 falhas (2%) **não** anuncia normalização — é o cenário exato
  de 24/07 (teste 7).
- **Janela vazia não normaliza**: 0 envios não vira "voltou ao normal" (teste 8).
- **Token inválido também dá 401**, não só a ausência de token (teste 9).

O dublê do alerta (`SessaoSaude`) deriva o estado das notificações que os próprios ciclos criaram,
como o código faz em produção — com estado chumbado, "não notifica de novo" passaria mesmo num
código que notificasse.

Confirmado após a execução: `notifications` segue em 2.805, zero notificações de saúde no banco, e
`welcome_status` inalterado (8.391 / 186 / 68 / 20).

---

## Quantos estavam mentindo

**68 dos 254.** A estimativa da sprint era ~54 e ficou por baixo: os 54 são só a janela do incidente.

```
CORRIGIDOS   ('sent' -> 'failed', a mensagem falhou)              68
JÁ CORRETOS  (mensagem entregue/lida/a caminho)                  186
AMBÍGUOS     (>1 template na janela — NÃO tocados)                 0
SEM MENSAGEM (nenhuma template casou — NÃO tocados)                0
TOTAL                                                            254
```

Conferido por SQL direto, sem passar pelo script: dos 254 `'sent'`, a mensagem pareada estava
`read` 108, `delivered` 71, **`failed` 68**, `sent` 7.

| data | falhas | |
|---|---|---|
| 13/07 a 22/07 | **14** | falhas esparsas (1, 3, 1, 1, 2, 2, 4) — anteriores ao incidente |
| 23/07 | 22 | |
| 24/07 | 22 | |
| 25/07 | 9 | |
| 26/07 | 1 | |
| **23/07 em diante** | **54** | a janela do `131042` — exatamente a estimativa original |

Os 14 esparsos de antes de 23/07 nunca tinham sido contados por ninguém, porque o painel também os
mostrava como sucesso. A taxa de falha "de ~10%" que se supunha normal antes do incidente era, ela
própria, invisível.

Só **1** das 68 tem `error_code`: o `131042` de 26/07. As outras 67 são anteriores à persistência de
`statuses[].errors[]` (que entrou na sprint de instrumentação, também em 26/07) e receberam o texto
`"recusada pela Meta — motivo não capturado (falha anterior à persistência de erro no webhook)"`.
Dizer "motivo não capturado" é a resposta honesta; inventar um código seria repetir, ao contrário, o
erro que causou a sprint.

### Prova de que nada além das duas colunas foi tocado

Antes e depois do `--apply`, um `md5` do agregado de **todas as colunas de `exact_leads` exceto
`welcome_status` e `welcome_error`**, sobre as 8.665 linhas:

```
[antes]  linhas=8665  digital(sem welcome_*)=39c5ef4f170c191f9f099f990d75d707
[depois] linhas=8665  digital(sem welcome_*)=39c5ef4f170c191f9f099f990d75d707
```

Idêntico — o que inclui `welcome_sent_at` e `welcome_wamid`, que não estão na exclusão. Além disso:

- **Contagem final:** `skipped` 8.391 · `sent` **186** · `failed` **68** · NULL 20 = 8.665.
- **Conjunto, não só contagem:** o conjunto de `exact_id` com `welcome_status='failed'` é
  exatamente o conjunto cuja mensagem pareada estava `failed`. Nenhum lead a mais, nenhum a menos.
- **Os 186 seguem intactos** em `'sent'`, e a reexecução os reclassifica como "já corretos".
- **Nenhum dos 68 ficou sem motivo:** 0 linhas com `welcome_status='failed'` e `welcome_error` vazio.
- **Idempotência provada:** a segunda passada em dry-run vê 186 leads `'sent'` e reporta
  **0 correções**. O script só olha `welcome_status='sent'`, e os corrigidos já não estão lá.

### Uma ressalva registrada

Dos 186 "já corretos", **7** têm a mensagem ainda em `status='sent'` no banco — nunca chegou
`delivered`, `read` nem `failed` para elas. Ficam como `'sent'`, o que é consistente com a decisão de
que `'sent'` significa "entregue ou a caminho", mas são leads sobre os quais a Meta nunca deu
desfecho. Não são mentira comprovada, então não foram tocados; só não são confirmação de entrega.
A Fase 2 resolve isso daqui para a frente, não retroativamente.

---

## O que esta sprint NÃO faz, e as frentes que ela abre

Fora de escopo por decisão, não por esquecimento:

- **Religar a boas-vindas.** Depende da fatura da Meta **e** do critério de reenvio (ver a
  dependência de ordem no topo). `auto_welcome_config.enabled` continua `false`.
- **A NAT.** Continua desligada. Esta sprint não tocou o fluxo.
- **A guarda de idempotência** (`exact_spotter.py:186`). Continua `welcome_status is not None`, de
  propósito: mudá-la é decisão da frente de reenvio, não desta.

Frentes que ficam registradas, cada uma com o que já se sabe:

| frente | por que existe | o que já se sabe |
|---|---|---|
| **Critério de reenvio** | pré-requisito para religar a automação | 68 leads em `failed` + 8.391 em `skipped`; as duas populações precisam de critérios diferentes |
| **`messages.template_name`** | a taxa de falha global dilui: campanha saudável esconde fluxo morto | exige migração; é a correção de verdade do limiar do alerta |
| **Auth em `/api/exact-leads/sync`** | endpoint aberto que dispara o sync, e o sync manda boas-vindas | inerte hoje (automação desligada), com dentes no dia do religamento |
| **Os 7 leads sem desfecho** | mensagem em `sent` que nunca recebeu `delivered`/`read`/`failed` | não são mentira comprovada; a Fase 2 cobre isso daqui para a frente |

---

## Como verificar depois do restart

```bash
# 1. os jobs subiram
sudo journalctl -u <serviço> -n 40 | grep "✅"
#    esperado, entre os outros: "Alerta de saúde de entrega ativo (checa a cada 15 min)"

# 2. o endpoint de disparo está fechado
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://hub.cenatdata.online/api/send/text \
     -H 'Content-Type: application/json' -d '{"channel_id":1,"to":"5511999999999","text":"x"}'
#    esperado: 401

# 3. o alerta, sem esperar 15 min (LEITURA PURA, não grava)
cd backend && PYTHONPATH=$PWD venv/bin/python -c "
import asyncio
from app.database import async_session
from app import delivery_health as dh
async def m():
    async with async_session() as db:
        print(await dh.medir(db)); print('estado:', await dh.estado_atual(db))
asyncio.run(m())"
```

`avaliar()` **grava** notificação quando há transição — para inspeção use `medir()` e
`estado_atual()`, que são leitura pura.
