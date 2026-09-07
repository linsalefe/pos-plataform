# RECON_RD_STATION_20260907 — reconhecimento para a integração com o RD Station Marketing

**Modo: somente leitura.** Nenhum DDL, nenhum INSERT/UPDATE, nenhuma chamada a API externa
(nem RD, nem Exact, nem Meta). Só leitura de código, do `.env`, do unit do systemd e SELECTs.
Data da medição: **07/09/2026**. Janela padrão das contagens: `created_at >= 2026-08-18`.

Corte de leads de teste: `app/relatorios.py` — 19 chaves excluídas, 1 duvidoso, 56 nomes
casaram. Sobre `agendamentos` o corte remove **13 de 396 linhas** (383 ficam).

---

## Os quatro achados que mexem no desenho

**1. `email` é obrigatório no payload do RD e o agente NUNCA tem e-mail.**
`qualificacao_fluxo.py:1478` passa `email=None` fixo na chamada de `fluxo.agendar`. Medido:
das 21 linhas criadas pelo agente desde 18/08, **0 têm e-mail (0%)**. No caminho da LP são
**375 de 375 (100%)**. Não é lacuna ocasional — é estrutural: o agente conhece a pessoa pelo
WhatsApp e nunca pergunta e-mail.

**2. Uma submissão da LP gera DUAS linhas em `agendamentos`, não uma.**
O fluxo de duas etapas (`POST /lead` → `POST /agendar`) escreve uma linha em cada requisição,
com ids diferentes. Medido: dos 124 e-mails com mais de uma linha, **101 são exatamente
`lead_criado` + `agendado`** e **107 pares acontecem em menos de 30 minutos**. Só **3** e-mails
têm dois `passo='agendado'` de verdade.

**CONTRADIZ o desenho:** `UNIQUE (agendamento_id, conversion_identifier)` não deduplica isso —
os dois `agendamento_id` são distintos, a UNIQUE aceita os dois, e a mesma pessoa dispara o
evento de entrada duas vezes no RD. A chave que deduplica esse caso é `(email,
conversion_identifier)`, ou `(lead_id, conversion_identifier)` quando há `lead_id`.

**3. `agendamentos.telefone` tem DOIS formatos na mesma coluna.**
LP: 10 ou 11 dígitos, **sem** DDI — `routes.py:88-94` (`_normalizar_telefone`) corta o `55`.
Agente: 12 ou 13 dígitos, **com** DDI — `qualificacao_fluxo.py:1480` passa
`estado.contact_wa_id` cru, que não atravessa o validador do Pydantic. Medido desde 18/08:
| dígitos | linhas | começam com `55` |
|---|---|---|
| 10 | 12 | 0 |
| 11 | 363 | 4 (DDD 55, Santa Maria/RS — **não** é DDI) |
| 12 | 9 | 9 (todas do agente) |
| 13 | 12 | 12 (todas do agente) |

`mobile_phone` no RD recebe hoje as duas grafias. E o `55` de 4 linhas é DDD, não DDI: quem
normalizar por "começa com 55" quebra essas quatro.

**4. `extras` não é confiável como fonte de payload: 129 de 396 linhas são o JSON escalar
`null`, não SQL NULL.** `SELECT jsonb_object_keys(extras)` **quebra** com
`cannot call jsonb_object_keys on a scalar` — foi o que aconteceu ao rodar a query do Bloco
4.1 deste próprio documento. Qualquer leitura de `extras` no drenador precisa de
`jsonb_typeof(extras)='object'`. É o defeito já registrado e **ainda não corrigido**.

---

## Bloco 1 — Pontos de escrita em `agendamentos`

### 1.1 Todos os INSERT

Só existem **dois** no código de produção. Nenhum SQL cru (`grep -i "insert into agendamentos"`
não encontra nada); tudo passa pelo ORM.

| # | arquivo:linha | função | quem chama | `email` |
|---|---|---|---|---|
| A | `app/agendamento/agendar.py:334` | `agendar()` | `routes.py:200` (`POST /api/agendamento/agendar`) | **opcional** — `DadosLead.email: str \| None` (`routes.py:99`) |
| A | idem | idem | `routes.py:386-388` (`POST /espontaneo/{segredo}/agendar`) | **opcional** — `PedidoEspontaneo.email` (`routes.py:303`) |
| A | idem | idem | `qualificacao_fluxo.py:1477-1495` (o agente) | **NUNCA** — `email=None` fixo em `:1478` |
| B | `app/agendamento/agendar.py:587` | `cadastrar_lead_sem_agendar()` | `routes.py:257` (`POST /api/agendamento/lead`) | **opcional** |
| B | idem | idem | `routes.py:446-448` (`POST /espontaneo/{segredo}/lead`) | **opcional** |

"Opcional" é literal: `DadosLead` tem validadores só para `nome`, `telefone` e `extras`
(`routes.py:112, 129, 136`). **Não há validador de `email`** — nem obrigatoriedade, nem
formato, nem `lower()`, nem `strip()`. O `<input id="lp-email">` da LP também não tem
`required` (`docs/form-nativo-snippet.html:68-70`) e o JS só valida se o campo veio preenchido
(`:143`). Que 100% das linhas da LP tenham e-mail é comportamento observado, **não garantia do
contrato**.

Outras escritas na tabela são só UPDATE de estado: `_marcar` (`agendar.py:231-241`),
`ag.box_id`/`sales_rep_email` (`:390-391`), `ag.lead_id` (`:422`), `ag.meeting_id` (`:456-458`),
e a faxina (`agendamento/faxina.py:55-59`).

### 1.2 O agente cria `Agendamento`? Sim.

`qualificacao_fluxo._agendar` (`:1405`) abre **sessão própria** (`:1476`, `async with
async_session()`) e chama `fluxo.agendar` — o mesmo caminho A da tabela acima. Portanto:

- **`sub_source`**: vem de `_origem_do_agendamento` (`:1436`, definida em `:655`). Lê
  `exact_leads.sub_source`, cai para o último `agendamentos.sub_source` do mesmo lead, e
  confere contra a allowlist. Fora da allowlist → devolve `None` **com log**, e `origens.resolver`
  aplica o padrão `PosMulheridades`. Fail-closed sobre o dado, não sobre a reunião.
- **`email`**: `None`, sempre (`:1478`).
- **`lead_externo`**: sempre `True` — o agente sempre passa `lead_id=estado.exact_lead_id`
  (`:1487`), então o `LeadsAdd` é pulado (`agendar.py:400-408`).
- **`origem_ip`**: `None` (`:1495`). **É o marcador que separa agente de LP** — a LP sempre
  grava o IP (`routes.py:_ip`). Usei-o em todas as contagens abaixo.

O caso Kaylla é a linha `agendamentos` **id 251**, de 27/08, `PosMulheridades`, `email=false`,
`passo=agendado` — a mesma que o S5-1 documenta.

Cuidado com `nat_qualificacao_state.agendamento_id`: ele **não** identifica agendamento do
agente. É preenchido em 4 lugares (`qualificacao_fluxo.py:1205, 1364, 1500, 1661`), e três
deles gravam a reunião que o lead marcou **sozinho** pelo obrigado.html. O JOIN por esse campo
devolve 75 linhas; só 21 são do agente.

### 1.3 Volume por caminho desde 18/08 (383 linhas, sem leads de teste)

| caminho | linhas | `passo='agendado'` | com e-mail | % com e-mail |
|---|---|---|---|---|
| LP (`origem_ip` preenchido) | 375 | 115 | **375** | **100%** |
| Agente (`origem_ip IS NULL`) | 21 | 16 | **0** | **0%** |

(21 + 375 = 396 = total bruto; o corte de teste tira 13 do lado da LP.)

Por `lead_externo` e `sub_source` (com o corte de teste), as maiores fatias:

| `lead_externo` | `sub_source` | total | com e-mail | sem e-mail | e-mails distintos |
|---|---|---|---|---|---|
| false | Pos Grupos e Oficinas T2 | 81 | 81 | 0 | 81 |
| true | Pos Grupos e Oficinas T2 | 47 | 44 | 3 | 44 |
| false | PosMulheridades | 31 | 31 | 0 | 27 |
| false | Pos TEA V3 | 29 | 29 | 0 | 28 |
| false | Pos Saude do Trabalhador | 23 | 23 | 0 | 20 |
| false | Pos Enfermagem em Saude Mental | 22 | 22 | 0 | 22 |
| true | PosMulheridades | 20 | 9 | **11** | 9 |
| true | Pos Enfermagem em Saude Mental | 15 | 13 | 2 | 13 |
| true | Pos TEA V3 | 12 | 11 | 1 | 10 |
| true | Pos Saude do Trabalhador | 11 | 10 | 1 | 10 |

Todo o "sem e-mail" está em `lead_externo=true`, e é o agente: `lead_externo` é `true` tanto
para o segundo passo da LP quanto para o agendamento do agente, e só o `origem_ip` os separa.

Por `passo` (mesmo corte): `lead_criado` 245 (245 com e-mail), `agendado` 128 (113),
`falhou` 7 (5), `iniciado` 3 (0).

### 1.4 Espontâneo

**Zero.** `nat_agendamento_token`: 0 tokens emitidos, 0 usados, 0 com `agendamento_id` — a
tabela está vazia desde que existe. Nenhuma linha de `agendamentos` tem `sub_source` de
espontâneo; os 13 `sub_source` distintos da base inteira são todos pós da allowlist.

Há um motivo estrutural, não só falta de tráfego: `SUBSOURCE_ESPONTANEO` é
`os.getenv("AGENDAMENTO_SUBSOURCE_ESPONTANEO", "Espontaneo WhatsApp")` (`routes.py:298`), a
variável **não existe no `.env`**, e `"Espontaneo WhatsApp"` **não está** em
`AGENDAMENTO_SUBSOURCES`. Se um token fosse emitido hoje, `origens.resolver` levantaria
`OrigemInvalida` (`origens.py:184`) e o agendamento devolveria 400. É fail-closed deliberado
(está escrito em `routes.py:294-297`), mas quer dizer que o caminho está **desligado na
prática**, não apenas ocioso.

Onde o agente guarda dado extra: `nat_qualificacao_state.dados_extras` (JSONB,
`models.py:784`). Chaves presentes hoje: `como_conheceu` (144 linhas) e `assumido_por` (54).
**Não há e-mail em lugar nenhum** desse estado — as colunas do fluxo são `formacao`,
`ano_conclusao`, `atuacao`, `motivacao`, `faixa_investimento`. `qualificacao_dados.py:184-188`
só relê `agendamentos.extras` do próprio lead. Conclusão: **o e-mail de quem chega pelo agente
não é coletado em ponto nenhum do sistema.**

---

## Bloco 2 — Máquina de estados de `passo`

### 2.1 Valores e o ponto da confirmação

`app/models.py:616-620`:

| constante | valor | significado |
|---|---|---|
| `PASSO_INICIADO` | `iniciado` | nada foi para a Exact |
| `PASSO_BOX_CRIADO` | `box_criado` | `BoxesAdd` passou; reversível, a faxina limpa |
| `PASSO_LEAD_CRIADO` | `lead_criado` | `LeadsAdd` passou (ou foi pulado, no lead externo) |
| `PASSO_AGENDADO` | `agendado` | **`scheduleAdd` passou. Definitivo.** |
| `PASSO_FALHOU` | `falhou` | desistimos; `erro` diz por quê |

**"Reunião confirmada na Exact" = `app/agendamento/agendar.py:448`** — o
`await _marcar(db, ag, PASSO_AGENDADO)` logo depois do `client.agendar_reuniao` da linha 430.
É o único lugar que grava esse valor. `_marcar` (`:231`) commita a cada passo, de propósito.

Não há CHECK constraint em `passo` no banco (conferido: `agendamentos` só tem a PK e dois
índices) — a regra vive nas constantes.

### 2.2 Mais de um `agendamentos` por pessoa: sim, e é o caso comum

Desde 18/08, e-mails com mais de uma linha: **124**. Repetição máxima: 5. Anatomia:

| linhas no grupo | passos | grupos |
|---|---|---|
| 2 | `agendado` + `lead_criado` | **101** |
| 2 | `falhou` + `lead_criado` | 4 |
| 2 | só `lead_criado` | 7 |
| 3 | `agendado` + `lead_criado` | 6 |
| 3 | só `lead_criado` | 1 |
| 4 | `agendado` + `lead_criado` | 3 |
| 4 | só `lead_criado` | 1 |
| 5 | `agendado`+`falhou`+`lead_criado` | 1 |

- pares que ocorrem em **menos de 30 min**: **107** → é o fluxo de duas etapas, não reagendamento
- grupos com intervalo **≥ 30 min**: **12**
- e-mails com **dois ou mais `passo='agendado'`**: **3** → reagendamento real é raro
- e-mails em **dois ou mais `sub_source`**: **6** → a mesma pessoa aplicando para dois cursos existe
- chaves de telefone com mais de uma linha: 138 (mais que os 124 e-mails, porque inclui as
  linhas sem e-mail do agente)

O `_duplo_clique` (`agendar.py:219-228`) só protege contra clique repetido: mesma `telefone`,
`passo='agendado'`, dentro de **90 segundos** (`JANELA_DUPLO_CLIQUE`, `:126`). Ele não vê o
par `lead_criado` → `agendado`, porque a primeira linha nunca chega a `agendado`.

**Consequência para a idempotência** (ver achado 2 no topo): por `agendamento_id`, a pessoa
que preenche o formulário e agenda em seguida gera dois eventos de entrada. Os 6 e-mails em
dois `sub_source` mostram que a chave também precisa do `conversion_identifier` — não basta o
e-mail sozinho.

---

## Bloco 3 — O padrão do `nat_scheduler_job`

### 3.1 Como funciona (`app/nat_scheduler.py`, 512 linhas)

1. **Intervalo**: `INTERVALO_SEGUNDOS = 60` (`:77`). O loop **dorme antes de trabalhar**
   (`:505-506`), como os outros jobs do `main.py`.
2. **Seleção**: `_proxima_acao` (`:257`) — `status='pendente' AND run_at <= corte`,
   `ORDER BY run_at`, `LIMIT 1`, `with_for_update(skip_locked=True)`. Uma ação por vez.
3. **Teto por ciclo**: `MAX_ACOES_POR_CICLO = 50` (`:82`). O laço de `processar_pendentes`
   (`:463`) roda até 50 vezes e dá `break` na primeira passada sem ação vencida — custo em
   fila vazia: um SELECT por minuto.
4. **Uma transação e uma sessão por ação** (`:475-481`), não uma por lote: handler lento
   segura só o próprio lock; ação que falha não contamina as outras.
5. **Marcação na mesma transação da execução** — não existe janela entre "executei" e
   "registrei". Processo morto no meio → nada commita → a ação volta a `pendente`.
6. **`_finalizar`** (`:293`) grava o desfecho por **UPDATE explícito**, não por atributo do
   ORM, porque o objeto pode estar expirado depois de um savepoint revertido.
7. **Retentativa**: handler levantou → savepoint revertido, `attempts += 1`, linha continua
   `pendente` e o **`run_at` é empurrado** para `agora + ATRASO_RETENTATIVA_SEGUNDOS` (60s,
   `:87`). Sem empurrar, as 3 tentativas queimariam na mesma passada. Na tentativa
   `MAX_TENTATIVAS_ACAO` (3) vira `falhou`.
8. **`skipped`** existe como status de banco (`ACAO_SKIPPED`, `models.py`), com o CHECK
   alargado por `migrate_acao_skipped.py`.
9. **Exceção fora do handler** (commit, lock, conexão): `except` em `:482-488` conta em
   `resumo["erro"]`, **sem `break`** — a ação fica pendente e o ciclo seguinte tenta de novo.
   O `nat_scheduler_job` ainda tem um `try/except` que abraça o ciclo inteiro (`:507-511`)
   porque "este loop não pode morrer".
10. **Criação/cancelamento**: `main.py:268-269`
    (`asyncio.create_task(nat_scheduler_job())`, com import tardio) e `main.py:315`
    (`nat_scheduler_task.cancel()`), dentro do `lifespan` que começa em `main.py:259`.

Detalhe importante para quem for reusar: `agendar` (`:205`) e `cancelar` (`:233`) são
**primitivas que não commitam** — quem chama é dono da transação. Foi exatamente isso que
custou 31 aberturas perdidas em 25/08 (`agendar.py:495-520`).

### 3.2 Limitador de taxa para a Exact: **não existe**

`grep -rn "Semaphore\|AsyncLimiter\|ratelimit\|RateLimit" app/` não devolve **nada**. Não há
limitador de saída para a Exact, nem 30 req/20s nem outro. **Não mensurável: o limitador que a
pergunta supõe não existe no código, então não há o que reaproveitar para o RD.**

O único limitador do projeto é **de entrada**, por IP, em memória do processo:
`app/agendamento/routes.py:67-80` (`_limitar`), com baldes de deque em `_baldes` (`:51`) e os
limites `LIMITE_LEITURA = (60, 60)` e `LIMITE_ESCRITA = (5, 300)` (`:48-49`). É um bom molde
de janela deslizante, mas seria preciso reescrevê-lo como limitador de saída — e com um
processo `uvicorn` único (sem `--workers`, ver `database.py:31-33`) um contador de módulo
bastaria para os 120/min do RD.

### 3.3 O cliente httpx

`app/agendamento/client.py`:
- `TIMEOUT_PADRAO = 15.0` (`:28`); `_req` (`:93-101`) abre um `httpx.AsyncClient(timeout=...)`
  **por chamada** — sem cliente reaproveitado, sem pool de conexão.
- **Sem retentativa, por decisão escrita** (`:18-22`): um `BoxesAdd` repetido depois de timeout
  pode criar dois boxes.
- Erro: `httpx.HTTPError` → `ExactIndisponivel` (`:99-100`); 4xx → `_levantar` (`:77-90`) casa
  o texto da Exact por **prefixo** contra a tupla `_ERROS` (`:66-73`) e levanta exceção tipada;
  5xx → `ExactIndisponivel`; resto → `ExactErro`. Nada é logado dentro do cliente — quem
  loga é o chamador, com `#id do agendamento` no prefixo.

`app/exact_spotter.py`: mesmo estilo, mais cru — `httpx.AsyncClient(timeout=30)` (`:92`),
`timeout=15` em `add_timeline_comment` (`:52`), `try/except Exception` que **imprime e devolve
`False`** (`:74-81`). Sem retentativa e sem exceção tipada.

---

## Bloco 4 — Dados disponíveis para o payload

### 4.1 Chaves de `extras`

Primeiro, o tipo (desde 18/08):

| `jsonb_typeof(extras)` | linhas |
|---|---|
| `object` | 267 |
| `null` (escalar JSON, **não** SQL NULL) | 129 |

As chaves, sobre as 267 linhas `object`:

| chave | linhas (desde 18/08) | linhas (base inteira) |
|---|---|---|
| `Profissão` | 265 | 272 |
| `Como conheceu` | 265 | 272 |
| `Ensino Superior` | 265 | 272 |
| `Faixa de investimento` | 265 | 272 |
| `profissao` | 2 | 2 |
| `como_conheceu` | 2 | 2 |

Quatro perguntas, com acento e caixa de título — são os nomes que o formulário de produção
manda, e os dois em snake_case são de smoke test (`docs/AGENDAMENTO.md:596`). São candidatos
diretos a `cf_*` no RD, mas o nome do campo lá terá de ser o slug, não a chave crua.

**Nota:** nenhum dos dois snippets versionados em `docs/` manda `extras`
(`form-nativo-snippet.html:150-152` monta o corpo só com `nome`, `email`, `telefone`, `origem`;
`obrigado-snippet.html:230-231` idem). Os 265 registros com as quatro perguntas vêm de uma
versão da LP que **não está no repositório** — os snippets de `docs/` estão atrás da produção.

### 4.2 UTM: **NÃO.**

`grep -rn -i "utm" docs/ app/` devolve **zero ocorrências** relevantes (a única linha que casa é
um `placeholder="(11) 99999-8888"`, por causa do "tm" de "inputmode"). Especificamente:

- `app/agendamento/routes.py:97-110` — `DadosLead` tem `nome`, `email`, `telefone`, `origem`,
  `extras`. Nenhum campo de campanha.
- `app/agendamento/routes.py:147-158` — `PedidoAgendamento` acrescenta só `slot` e `lead_id`.
- `app/agendamento/routes.py:301-305` — `PedidoEspontaneo` tem `nome`, `email`, `slot`.
- `docs/form-nativo-snippet.html:150-152` e `docs/obrigado-snippet.html:230-231` — o corpo do
  POST não lê a query string além de `?lead=`, `?nome=`, `?email=`, `?tel=`
  (`obrigado-snippet.html:299`).
- `app/models.py:623-681` — a tabela não tem coluna de campanha.

Origem de campanha só existe como `sub_source` (o curso), e isso não é UTM.

### 4.3 Formato do telefone

Ver o achado 3 no topo. Cinco exemplos, últimos 4 dígitos mascarados, os mais recentes:

```
55799858****   (13, agente — DDI 55 + DDD 79)
1199884****    (11, LP — DDD 11)
1199884****    (11, LP)
7999858****    (11, LP)
499968****     (10, LP — fixo com DDD)
```

Regra da LP: `routes.py:88-94` tira tudo que não é dígito e corta o `55` inicial **só quando o
resultado tem mais de 11 dígitos**; depois `:136-143` recusa o que não tiver 10 ou 11. Regra do
agente: nenhuma — o `wa_id` vai como está.

### 4.4 Normalização do e-mail: **nenhuma no servidor**

Não existe `field_validator("email")` em `routes.py` (os validadores são `extras`:112,
`nome`:129, `telefone`:136 e `nome`:307). O único `trim` é do lado do cliente
(`docs/form-nativo-snippet.html:135-137`, `.value.trim()`).

Medido na base inteira (389 linhas com e-mail): **1** com maiúscula, **0** com espaço nas
bordas, **0** sem `@`. Está limpo por sorte e pelo JS, não por contrato — o `lower()`/`strip()`
tem de ser feito no drenador, e o `1` com maiúscula prova que a caixa varia.

O e-mail é usado hoje em um lugar só: `extras.montar_descricao(email, extras)`
(`app/agendamento/extras.py:133`), que o costura no `description` do lead, porque **o `LeadsAdd`
da Exact não tem campo de e-mail** (`models.py:646`, `docs/AGENDAMENTO.md:410-420`).

---

## Bloco 5 — Convenções para a implementação futura

### 5.1 Segredos

- Arquivo: **`/home/ubuntu/pos-plataform/backend/.env`**, carregado por **duas** vias:
  - `EnvironmentFile=/home/ubuntu/pos-plataform/backend/.env` no unit
    `/etc/systemd/system/cenat-backend.service`
  - `load_dotenv()` do `python-dotenv`, em `app/database.py:4-6` e `app/auth.py:10-15`
    (funciona porque `WorkingDirectory` é o `backend/`)
- Leitura: sempre `os.getenv` no ponto de uso. `EXACT_SPOTTER_TOKEN` é lido em
  **`app/exact_spotter.py:86`**, dentro de `get_headers()` — chamada a cada request, sem cache
  de módulo. `RD_API_KEY` deve seguir exatamente isso.
- **Aspas são obrigatórias em valor com espaço** (`app/agendamento/origens.py:28-31`): não por
  causa do systemd nem do dotenv, mas de quem fizer `set -a && . .env` no shell.

### 5.2 Convenção dos `migrate_*.py`

Mais recente e melhor modelo: **`backend/migrate_disparo_skip.py`** (02/09). Cabeçalho:

1. Docstring longa, começando pela linha de comando exata
   (`cd backend && venv/bin/python migrate_disparo_skip.py`);
2. afirmação explícita de **idempotência** (`CREATE TABLE IF NOT EXISTS`, índices conferidos
   por nome contra `pg_indexes`);
3. seção "o que esta migração destrava", com o número medido que a justifica;
4. seção dizendo o que **não** se copiou de uma migração anterior e por quê
   (`migrate_message_autoria.py` tem `lock_timeout`, FK `NOT VALID` + `VALIDATE` e índices
   `CONCURRENTLY` — cerimônia para tabela quente, dispensável em tabela que não existe);
5. "SEM BACKFILL" ou o critério do backfill, explícito;
6. "NÃO altera comportamento nenhum por si só".

Corpo: `DDL` e `INDICES` como constantes de módulo, `async def migrar()` sob
`async with engine.begin()`, e o ritual **BEFORE → operação → AFTER**, imprimindo colunas,
índices, FKs (`convalidated`) e a contagem final. `if __name__ == "__main__": asyncio.run(migrar())`.

**CHECK espelhando constantes de `models.py`**: o padrão existe e é
`migrate_espontaneo.py:145-172` — as listas são construídas a partir das constantes importadas
(`", ".join(f"'{e}'" for e in ETAPAS)`) e aplicadas com **DROP + ADD** na mesma transação,
porque o Postgres não alarga um CHECK. `migrate_acao_skipped.py:40-49` é a versão mínima do
mesmo ritual, com a regra do "CHECK largo antes do código novo".

**Contra-exemplo deliberado**: `migrate_agendamentos_subsource.py:26-27` — **sem** CHECK e
**sem** FK, "a allowlist vive em env, não no banco". O mesmo raciocínio se aplica a
`conversion_identifier`.

### 5.3 Predicado de lead de teste (`app/relatorios.py`)

```python
# app/relatorios.py:210-216
ACENTOS_DE = "áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ"
ACENTOS_PARA = "aaaaeeiooouucaaaaeeiooouuc"

# ⚠️ ÂNCORA no `zz`. Sem ela, 48 leads REAIS casam.
PREDICADO_TESTE = r"(^\s*zz|smoke|teste|\mtest|john doe|fafaf|alefe|thobias justino)"
```

Aplicado assim (`:317-321`), sobre `exact_leads`, não sobre `agendamentos`:

```sql
SELECT exact_id, name, phone1 FROM exact_leads
WHERE lower(translate(name, :de, :para)) ~ :pred
```

O resultado vira **chaves de telefone**, não ids: `chaves_de_teste` (`:299`) cruza com quem tem
inbound e com o "bloco conhecido" (chave com ≥2 leads de nome-de-teste, `:334`), devolve
`ConjuntoTeste.excluir` e `.duvidosos`, e cacheia por 600 s. O filtro no SQL é
`NOT (thread_sql(col) = ANY(:teste))`, com `thread_sql` (`:235`) e `chave_sql` (`:219`).

Para `agendamentos` use `thread_sql("a.telefone")` — foi o que fiz aqui. **Duas ressalvas
medidas:** a âncora `^\s*zz` é obrigatória, e `ANA CRISTINA … - TESTE` (lead 51507231) é uma
**pessoa real** que o predicado apagaria — por isso as duas cestas.

### 5.4 Tabela de configuração por curso além de `course_aliases`: **não existe**

Tabelas do schema `public` (26): `agendamentos, ai_configs, ai_conversation_summaries,
auto_welcome_config, call_logs, channels, contact_tags, contacts, course_aliases, disparo_skip,
exact_leads, exact_stage_events, knowledge_documents, messages, nat_agendamento_token,
nat_button_events, nat_config, nat_contact_attempts, nat_flow_state, nat_qualificacao_state,
nat_scheduled_actions, notifications, scheduled_messages, tags, users, whatsapp_templates`.

- `course_aliases` — `id, alias, full_name, short_name, is_active, created_at`. É
  `sub_source → nome legível`, nada mais. **Não tem coluna livre onde caiba um identifier.**
- `nat_config` — `id, nat_enabled, nat_start_at, max_envios_hora, updated_at,
  qualificacao_enabled, qualificacao_start_at, espontaneo_enabled, follow_enabled,
  follow_template`. É config **global**, uma linha, sem chave por curso.
- `knowledge_documents` — material por curso, para o LLM. Não é config.
- `app/sdr_mapping.py:2-10` — o único "mapa de configuração" do projeto é um **dict Python
  hard-coded**, não uma tabela.

Ou seja: `sub_source → conversion_identifier` não tem casa hoje. As duas opções que o repo já
usa para dado desse tipo são o `.env` (como `AGENDAMENTO_SUBSOURCES`) e uma coluna nova em
`course_aliases` — e a lição de `migrate_agendamentos_subsource.py:26-27` é que a allowlist
ficou no env justamente para não exigir migração a cada curso novo.

---

## Bloco 6 — Mapa `sub_source → conversion_identifier` (parcial)

`conversion_identifier` fica **em branco de propósito**: não é inferível daqui, tem de ser lido
no gatilho de cada fluxo dentro do RD. Contagens desde 18/08, com o corte de leads de teste.

| `sub_source` (Exact) | alias em `course_aliases`? | subm. desde 18/08 | com e-mail | destas, do agente | `conversion_identifier` (RD) |
|---|---|---|---|---|---|
| Pos Grupos e Oficinas T2 | ✅ Grupos e Oficinas em Saúde Mental | 128 | 125 | 3 | |
| PosMulheridades | ✅ Saúde Mental e Mulheridades | 51 | 40 | 11 | |
| Pos TEA V3 | ✅ Transtorno do Espectro Autista (TEA) | 41 | 40 | 1 | |
| Pos Enfermagem em Saude Mental | ✅ Enfermagem em Saúde Mental | 37 | 35 | 2 | |
| Pos Saude do Trabalhador | ✅ Saúde Mental do Trabalhador | 34 | 33 | 1 | |
| Pos Infantojuvenil EAD | ✅ Infantojuvenil EAD | 24 | 24 | 0 | |
| Pos Psicologia na RAPS T3 | ✅ Psicologia na RAPS | 18 | 17 | 1 | |
| Pos Psicologia Escolar | ✅ Psicologia Escolar | 17 | 16 | 1 | |
| Pos Suicidio e Luto T3 | ✅ Autolesão, Suicídio e Luto | 11 | 11 | 0 | |
| Pos Gestao Psicossocial T5 | ✅ Gestão, Avaliação e Planejamento | 9 | 9 | 0 | |
| Pos Alcool e Drogas T4 | ✅ Álcool e Outras Drogas | 9 | 9 | 0 | |
| Pos Psicologia Clinica T2 | ✅ Psicologia Clínica e Saúde Mental | 3 | 3 | 0 | |
| **Pos Direitos Humanos T4** | ❌ **sem alias** (cai no fallback) | 1 | 1 | 0 | |
| Pos Psicologia Hospitalar | ✅ Psicologia Hospitalar | **0** | 0 | 0 | |

Totais: 383 linhas, 363 com e-mail, 20 do agente. As 14 linhas da tabela são a allowlist
inteira do `.env` (`AGENDAMENTO_SUBSOURCES`, `.env:45`) — ver `LISTA_LP_20260907.md`.

`Pos Psicologia Hospitalar` é o único da allowlist com zero submissão desde que existe: o
fluxo do RD para esse curso não terá evento nenhum para escutar até a primeira submissão.

---

## O que muda no desenho

1. **A idempotência não pode ser por `agendamento_id`.** O fluxo de duas etapas da LP escreve
   duas linhas para a mesma pessoa (101 dos 124 casos medidos), e `UNIQUE (agendamento_id,
   conversion_identifier)` deixaria as duas passarem. A chave precisa ser por pessoa +
   identifier — `(lower(email), conversion_identifier)`, com `lead_id` como alternativa quando
   houver.
2. **`skipped` por falta de e-mail não é caso de borda: é 100% do caminho do agente.** 21 de 21
   linhas, e o e-mail não existe em nenhuma outra tabela para ser buscado. Ou o agente passa a
   perguntar e-mail, ou o evento de entrada do agente simplesmente não existe — e isso precisa
   ser decisão consciente, não um `skipped` acumulando em silêncio.
3. **O drenador tem de normalizar telefone e e-mail, porque o banco não normaliza.** Duas
   grafias de telefone convivem na mesma coluna (com e sem DDI), o `55` de 4 linhas é DDD e não
   DDI, e não há validador de e-mail no servidor — a limpeza atual é do JS da LP.
4. **Ler `extras` exige `jsonb_typeof(extras)='object'`.** 129 de 396 linhas guardam o escalar
   JSON `null`, e a query ingênua **quebra** com `cannot call jsonb_object_keys on a scalar`.
   Os `cf_*` só existem para 2 em cada 3 linhas.
5. **Não há limitador de saída para reaproveitar, e não há tabela onde pôr o
   `conversion_identifier`.** Os 120/min do RD precisam de um limitador novo (o `_limitar` de
   `routes.py` é de entrada, por IP); e o mapa `sub_source → identifier` só tem duas casas
   possíveis hoje: o `.env`, no molde do `AGENDAMENTO_SUBSOURCES`, ou uma coluna nova em
   `course_aliases`.

---

## O que NÃO foi feito

Nenhum DDL, nenhum INSERT, nenhum UPDATE, nenhum `migrate_*` executado. Nenhuma chamada a API
externa — RD, Exact ou Meta. Nenhum serviço reiniciado, nenhum `.env` alterado. Todo o
conteúdo acima vem de leitura de arquivos e de SELECTs.
