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
