# Incidente 09/10/2026 — login fora do ar (pool de conexões esgotado)

## Sintoma
`POST /api/auth/login` e `GET /api/auth/me` devolvendo 500. No backend:
`QueuePool limit of size 20 overflow 20 reached`. Os 500 subiram a partir das 14h UTC de 09/10
(118 às 14h, 264 às 15h, 162 às 16h). Jobs (fila RD, NAT scheduler, follow_estagio,
scheduled_messages, faxina) caíram pelo mesmo motivo.

## Causa
Ciclo de espera entre DUAS sessões do mesmo turno do agente, invisível ao Postgres porque metade
dele está no Python.

1. 07/10 18:29 UTC — Shirley (5512981952632) escolhe horário. O webhook (`main.py`) já tinha feito
   `contact.name = name` na sessão dele → lock na linha de `contacts`, sem commit.
2. `_agendar` abre uma sessão própria (`async_session()`, P0-A de 26/08) para `fluxo.agendar`.
3. Dentro dela, o espelho/régua chama `_contato_ou_criar`, que vê o nome commitado vazio e faz
   `achado.name = ...` → `UPDATE contacts` → espera o lock do webhook.
4. O webhook espera o `agendar` terminar. Ninguém termina.

No banco: pid do webhook `idle in transaction` por 1 dia e 22h56 (última query:
`SELECT agendamentos.extras ...` de `extras_brutos_da_lp`). Atrás dele, ~35 conexões em
`UPDATE contacts SET name` / `INSERT INTO contacts` / `INSERT INTO reuniao_status`, até as 40 do
pool acabarem.

## Ação imediata
`sudo systemctl restart cenat-backend` às ~17:28 UTC de 09/10 (autorizado pelo Álefe). Login
voltou (401 para credencial errada = backend respondendo). Rollback das transações presas: perdeu-se
a troca de nome pendente e o que esperava atrás dela.

## Correção (branch `fix/lock-contato-agendar`)
- `qualificacao_fluxo._contato_ou_criar`: antes de preencher o nome, `SELECT ... FOR UPDATE SKIP
  LOCKED` na linha. Travada por outra transação → não preenche (é cosmético) e loga
  `nome de X NÃO preenchido — linha travada por outra transação`.
- `database.py`: `lock_timeout=30s` em toda conexão da app. Qualquer outro ciclo desse tipo vira
  erro em 30s num lugar só, em vez de derrubar o sistema.

## Verificação
- Reprodução em produção sem gravar nada (sessão A trava a linha, sessão B chama
  `_contato_ou_criar`; tudo em rollback): B volta em 0,05s sem preencher; sem a trava, preenche.
- `SHOW lock_timeout` numa sessão da app → `30s`.
- Testes que tocam `_contato_ou_criar` (`test_abertura_grafia`, `test_fluxo_b`,
  `test_nat_correcoes_20260918`, `test_qualificacao`, `test_religar_agente_20260927`,
  `test_risco3_abertura`, `test_reuniao_contato`, `test_confirmacao`): resultado IDÊNTICO ao de
  `main` sem a mudança. `test_fluxo_b` passa; as falhas dos outros já existiam (mocks
  desatualizados; `risco3` vermelho de propósito).

## Em aberto
- O mesmo padrão (sessão própria aberta enquanto a do webhook segura escrita) pode existir em
  outros pontos; o `lock_timeout` é a rede, não a varredura.
- `idle_in_transaction_session_timeout` no Postgres não foi configurado: exige conferir se algum
  job segura transação ociosa por muito tempo de propósito.
- Não há alerta de pool esgotado: o sistema ficou 47h acumulando e só foi notado quando o login caiu.

## Impacto medido (09/10, depois do restart)
Duas janelas diferentes:

**A) `reuniao_sync` parado de 07/10 18:27 a 09/10 17:30 UTC (47h).** O job ficou preso num
`INSERT INTO reuniao_status` atrás da transação travada e não rodou mais nenhuma vez. Reunião
marcada pelo SITE não depende dele (o `agendar` espelha e arma a régua na hora): as 9 do período
tiveram régua. Ficou sem régua quem dependia do sync ou do agente:

| Reunião | Pessoa | Horário (SP) | Quem marcou | O que faltou | Status na Exact |
|---|---|---|---|---|---|
| 4775777 | Shirley Aparecida (5512981952632) | 08/10 18:15 | agente (travou) | aviso de agendado, régua, lembrete | Cancelada |
| 4777339 | Fábio Vasconcelos (5541984293059) | 09/10 13:45 | agente (travou) | aviso de agendado, régua, lembrete | Cancelada |
| 4776066 | Catia Maria (5521995097910) | 08/10 17:50 | SDR na Exact | régua inteira | Cancelada |
| 4776374 | Andreia Menezes (5521984612850) | 08/10 16:40 | SDR na Exact | régua inteira | Cancelada |
| 4777388 | luciana oliveira (5534996605783) | 13/10 17:20 | SDR na Exact | régua armada atrasada (09/10 14:30) | já confirmou |

Os DOIS agendamentos do agente na janela travaram (2 de 2): o contato criado pelo agente tinha
`name` vazio, e é isso que dispara o preenchimento na segunda sessão.

Depois do restart saíram reativações atrasadas para Shirley e Fábio (09/10 14:29, duas cada), que
estavam presas no mesmo lock. O Fábio respondeu "Mas dia 9 é hoje" e o agente transferiu para humano.
O estado da Shirley no agente segue `escolhendo_slot`.

**B) Pool esgotado em 09/10, ~11h–14h28 SP.** 276 `POST /webhook` com 500. Nenhuma mensagem
recebida entre 12h e 14h SP entrou no banco até agora; a Meta reentrega webhooks com falha por até
7 dias, então podem chegar mais tarde. O lembrete da Solange (14h) saiu às 14h29, 1 minuto antes da
reunião.

## Depois do incidente (09/10, tarde)

### 1. A correção está no ar
`fix/lock-contato-agendar` mergeado em `main` (85e63bb, 17:49:58 UTC); o processo do backend
subiu 17:49:59 e foi reiniciado de novo às 17:58 com o vigia abaixo. Prova tirada de dentro do
processo, não de um script: o `GET /health` novo pega uma conexão do PRÓPRIO pool da app e
devolve `"lock_timeout": "30s"`.

Shirley e Fábio NÃO foram reprocessados depois do fix. Os turnos atrasados deles rodaram às
17:29–17:30 UTC no processo anterior, logo após o restart que soltou o lock (logs acima), e
nenhum passou de novo pelo preenchimento de nome desde então. Não houve log
`NÃO preenchido — linha travada` em produção ainda; a prova do SKIP LOCKED continua sendo a
reprodução da seção Verificação.

### 2. Vigilância (`app/saude_sistema.py`)
- **`GET /health`**: tira uma conexão do pool e roda `SELECT 1`, devolve `pool.checkedout`,
  `overflow`, capacidade (40), a transação `idle in transaction` mais antiga do role da app
  (tempo ocioso e idade da transação) e a idade de `reuniao_sync_cursor.ultimo_ciclo_em`.
  **503** se: pool > 80%, pool não entregou conexão em 10 s, transação ociosa > 5 min ou
  `reuniao_sync` (ligado) sem ciclo há > 30 min. Resultado em cache de 10 s (a rota é pública,
  mas ninguém a chamava: 0 acessos no log do nginx).
- **Diagnóstico fora do pool.** `pg_stat_activity`, o cursor e a Notification do alerta vão
  por um engine `NullPool` próprio. Com o pool esgotado é quando mais se precisa disso; pedir
  conexão ao pool cheio daria o mesmo timeout. Teste 4 de `test_saude_sistema.py` prova:
  engine de 1 conexão presa → 503 e o diagnóstico responde.
- **Vigia a cada 5 min** (`vigia_saude_job`), mesmo check. No 503: Notification
  `saude_sistema_down` para a gestão (`GESTOR_USER_ID`) e WhatsApp para `ALERTA_TELEFONE`
  (`.env`, 5583988046720). Alerta na transição, repete de hora em hora enquanto durar, e
  avisa a volta (`saude_sistema_up`). Não usa `nat_sdr_ligar_agora`.
- **Template `alerta_cenat_hub`** (UTILITY) submetido hoje, id 961273897051217, **PENDING**.
  Texto: "Alerta do Cenat Hub: {{1}}. Confira o servidor assim que puder." O pedido era só
  "Alerta do Cenat Hub: {{1}}", mas a Meta recusa variável no fim (2388299, 07/10). Até
  aprovar, o WhatsApp do vigia volta recusado e fica só o sino. `submit_template_alerta.py`.
- `test_saude_sistema.py`: 10/10 ok (saudável, ociosa, pool acima do limite, pool esgotado
  de verdade, reuniao_sync parado, transição do vigia).
- Com isso, o incidente de 07/10 teria alertado por volta das 18:35 UTC de 07/10 (ociosa > 5
  min no ciclo seguinte), e não 47h depois.

### 3. `idle_in_transaction_session_timeout = 10min` (AINDA NÃO APLICADO)
Pedido: mostrar a lista antes de aplicar. Auditoria do código (jobs do lifespan e caminhos
pesados) + amostragem de `pg_stat_activity` a cada 1 s em produção:

| Job/caminho | Segura transação durante chamada externa? | Pior intervalo ocioso | Risco a 10 min |
|---|---|---|---|
| sync_job (`exact_spotter.py:487-622`) | sim: páginas de /Leads e boas-vindas | ≤30 s por página | não |
| scheduled_messages → bulk_send_template (`exact_routes.py:241-631`) | sim: um commit no fim; SQL entre os leads | ~15–20 s por lead | não |
| nat_scheduler (FOR UPDATE SKIP LOCKED, `nat_scheduler.py:274`) | sim: handler com LLM | ≤~80 s | não |
| rd_sender (`rd_sender.py:118`) | sim: 1 linha por transação | ≤15–30 s | não |
| follow_estagio (`follow_estagio.py:417`) | sim: por linha; o `sleep(2)` vem depois do commit | ~20 s | não |
| faxina (`agendamento/faxina.py:54-95`) | **sim**: até 20 × remover_box sem SQL até o commit | 300 s se a Exact pendurar | não (o mais perto) |
| reuniao_sync (`reuniao_sync.py:249-265`) | sim: 2 × listar_meetings | ≤30–60 s | não |
| webhook → turno do agente (`qualificacao_fluxo.py:591`) | sim: LLM 10 s × 2 tentativas | ≤~80 s | não |
| webhook → fluxo.agendar (sessão própria) | sim: a do webhook fica ociosa durante o agendar | ~3 min; teórico 4–5 min | não |
| window_alerts, delivery_health, agente_parado | só banco | ms | não |
| kanban generate-summary, toggle IA → nota na Exact, test_chat da IA | sim: OpenAI pelo `ai_engine.py:15` **sem timeout** | normal <1 min; sem teto se a OpenAI pendurar | teórico |

Nenhum `pg_advisory*` no código; nenhum job segura transação ociosa DE PROPÓSITO (todos os
`FOR UPDATE` soltam no commit do item). Sem cron nem timer rodando script com o role `cenat`.
Amostragem: maior ociosa vista foi de segundos. Efeito da aplicação: sessão morta → rollback e
erro no próximo comando; o pior estrago seria um `bulk_send_template` (mensagens já saíram,
linhas de `messages` desfeitas), só se um intervalo passar de 10 min, o que não se vê hoje.

### 4. Limpeza
- **Shirley (5512981952632)**: estado `escolhendo_slot` → `encerrado`, motivo
  `reuniao_cancelada_incidente_20261009`, às 14:57 SP. Ação pendente cancelada com o mesmo
  motivo: 4119 `encerrar_inativo`. Nenhuma régua pendente da reunião 4775777.
- **Fábio (5541984293059)**: segue `transferido_humano`. O SDR remarcou na Exact: reunião
  **4778131, 13/10 10:45, Vigente** (a 4778113 de 09/10 15:04 foi cancelada). As 5 ações
  `confirm_a_*` pendentes (4386–4390) são a régua dessa reunião nova e **ficam**; a imediata
  saiu às 14:53 SP. Cancelado só o `encerrar_inativo` 4378, resto do agente.
- **Reuniões perdidas por causa do incidente**: Shirley 4775777, Fábio 4777339, Catia 4776066
  e Andreia 4776374 ficaram sem régua (aviso, confirmação, lembrete) e estão **Cancelada** na
  Exact. Nada a enviar agora. As 4 entram como perda do incidente; só o Fábio foi recuperado,
  por remarcação humana.
- **Reentrega dos webhooks de 12h–14h SP**: `backend/consulta_reentrega_webhook_20261009.py`
  (só lê). Em 09/10 ~15h SP: **0** mensagens com hora da Meta na janela entraram no banco,
  nem atrasadas. Há inbound às 11h e de novo às 14h, nenhum entre 12h e 14h. Rodar de novo até
  10/10 14h SP para fechar as 24h.
