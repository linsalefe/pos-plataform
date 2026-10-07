# SPRINT Bloco 0: espelho de reuniões da Exact (`reuniao_status`), 07/10/2026

Branch `feat/reuniao-status`, a partir da `main` em `cb8e6f9`. Base:
`RECON_CONFIRMACAO_NOSHOW_20261007_REPORT.md` §0, §2, §5.2 a §5.4, §6.2 e §6.6. Spec da Isa lida
para contexto: `Otimização IA - No show (validar).pdf` (na raiz do repo, não em `docs/spec/`).

**No ar desde 07/10 09:37 UTC (06:37 SP) com `REUNIAO_SYNC_ENABLED=true`.** O primeiro ciclo
bateu com as contagens do RECON §5.2. Nenhuma mensagem enviada, nenhuma escrita na
Exact, nenhum webhook cadastrado.

---

## 1. Critérios de aceite

| # | critério | estado | evidência |
|---|---|---|---|
| 1 | tabela por `migrate_reuniao_status.py`, idempotente, só após checkpoint | ✅ | DDL aprovado em 07/10; seção 2 |
| 2 | `reuniao_sync_job` a cada 10 min, flag lida a cada ciclo; desligado loga e dorme | ✅ | `reuniao_sync.flag_ligada` (sem cache), `ciclo`; log `09:37:18 ℹ️ reuniao_sync DESLIGADO ...` com a flag em `false` |
| 3 | `exact_type × origem` bate com o RECON §5.2 | ✅ | 249 = Cancelada 155 · Concluido 73 · Vigente 21 (seção 3) |
| 4 | lembrete pula com motivo quando não `Vigente` ou existe reunião mais nova do mesmo telefone | ✅ | `qualificacao_guard._espelho_bloqueia`, chamado por `guard_de_lembrete`; motivo sobe inteiro (seção 5) |
| 5 | reunião do Hub que vira `Cancelada` gera `print` claro | ✅ | `⚠️ reunião {id} do Hub (agendamento {ag}) virou Cancelada na Exact` em `reuniao_sync.sincronizar` |
| 6 | testes em `backend/test_reuniao_status.py`, não executados | ✅ | escritos, só `py_compile`; 7 grupos (seção 7) |
| 7 | 1 página por requisição, sempre `$filter`, no máximo 3 requisições por ciclo | ✅ | 2 requisições por ciclo (`client.listar_meetings`, `$top=500`, exige exatamente um filtro) |
| 8 | `python -c "import app.main"` passa; frontend não tocado | ✅ | passa; nenhum arquivo de `frontend/` no diff |

## 2. DDL executado

Aprovado no checkpoint e executado em 07/10. A primeira execução falhou no INSERT do cursor
(`asyncpg DataError`: a data ia como string) e **a transação inteira foi revertida**
(conferido: 0 tabelas). Corrigido para passar `datetime`, e a segunda execução aplicou o mesmo
DDL:

```sql
CREATE TABLE IF NOT EXISTS reuniao_status (
    meeting_id BIGINT PRIMARY KEY, lead_id BIGINT, telefone_chave VARCHAR(10),
    telefone_bruto VARCHAR(30), nome VARCHAR(255), slot_inicio TIMESTAMP NOT NULL,
    slot_fim TIMESTAMP, sales_rep_email VARCHAR(255), origem VARCHAR(10) NOT NULL,
    agendamento_id BIGINT REFERENCES agendamentos(id) ON DELETE SET NULL,
    exact_type VARCHAR(20) NOT NULL, exact_type_visto_em TIMESTAMP NOT NULL,
    exact_type_anterior VARCHAR(20), registrado_em TIMESTAMP,
    confirmado_em TIMESTAMP, confirmado_por VARCHAR(10), cancelado_em TIMESTAMP,
    cancelado_motivo VARCHAR(60), noshow_em TIMESTAMP, regua_encerrada_em TIMESTAMP,
    regua_encerrada_motivo VARCHAR(60),
    created_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'America/Sao_Paulo'),
    updated_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'America/Sao_Paulo'));
CREATE TABLE IF NOT EXISTS reuniao_sync_cursor (
    id INTEGER PRIMARY KEY, register_date_cursor TIMESTAMP, ultimo_ciclo_em TIMESTAMP,
    ultimo_ciclo_resultado TEXT);
-- CHECKs (DROP + ADD): exact_type IN ('Vigente','Concluido','Cancelada');
--   exact_type_anterior IS NULL OR IN (os mesmos); origem IN ('hub','exact')
-- índices: (telefone_chave, slot_inicio), (agendamento_id), (lead_id), (slot_inicio)
INSERT INTO reuniao_sync_cursor (id, register_date_cursor) VALUES (1, '2026-09-07 00:00:00')
  ON CONFLICT (id) DO NOTHING;
```

`\d reuniao_status` depois da migração: 23 colunas, PK, os 4 índices, os 3 CHECKs e a FK
`reuniao_status_agendamento_id_fkey ... ON DELETE SET NULL`.

## 3. Primeiro ciclo em produção

Antes do deploy, um ciclo real (Exact + banco) rodou **dentro de transação com ROLLBACK
forçado**, para pegar erro de SQL sem reiniciar a produção. Ele mostrou o desvio 4 da seção 8
(226 linhas em vez de 249), corrigido antes do deploy. O segundo ensaio deu 249.

Deploy em dois passos, como no plano:

```
09:35:18 ℹ️  Espelho de reuniões da Exact: DESLIGADO (a cada 10 min, 1º ciclo em 2 min)
09:37:18 ℹ️  reuniao_sync DESLIGADO (REUNIAO_SYNC_ENABLED != true) — /Meetings não é lido.
-- flag true, restart 09:37:28 UTC
09:37:30 ✅ Espelho de reuniões da Exact: LIGADO (a cada 10 min, 1º ciclo em 2 min)
09:39:32 🔄 reuniao_sync: novas=249 atualizadas=0 mudancas_status=0 canceladas_hub=121
         lembretes_cancelados=0 lidas=218+249 (2.0s)
```

**Tempo do ciclo: 2,0 s. Requisições: 2** (218 pelo cursor de `registerDate`, 249 pela releitura
de `startTime` desde 07/09, unidas por `meeting_id`).

```
SELECT exact_type, origem, count(*), count(agendamento_id) FROM reuniao_status GROUP BY 1,2;
 Cancelada | exact |  34 |   0
 Cancelada | hub   | 121 | 116
 Concluido | exact |  46 |   0
 Concluido | hub   |  27 |  26
 Vigente   | exact |   2 |   0
 Vigente   | hub   |  19 |  19
```

| | RECON §5.2 (07/10 06h) | espelho (07/10 06h39 SP) |
|---|---|---|
| total | 249 | **249** |
| Cancelada | 155 | **155** |
| Concluido | 73 | **73** |
| Vigente | 21 | **21** |

Nenhuma reunião nova foi registrada na Exact entre as duas medições. `origem='exact'` = 82, que
é a soma das 57 "não está no Hub" com as 25 "lead do Hub, reunião nova sem marcador" do RECON
§5.3 (as 7 com marcador e sem agendamento aparecem aqui como `hub` sem vínculo, ver abaixo).

Cursor depois do ciclo: `register_date_cursor = 2026-10-06 23:23:01` (UTC; a reunião mais nova
foi registrada às 23:28 UTC, menos 5 min de folga), `ultimo_ciclo_em = 2026-10-07 06:39:30` (SP).

**Reuniões `hub` sem vínculo com `agendamentos`: 6.** Cinco são os boxes de teste de 2027 da
investigação de agosto (FINDINGS §6 e §8; o lead foi excluído, a reunião ficou órfã). A sexta,
4753381 (15/09), não tem `meeting_id` nem lead/horário casando em `agendamentos`; não investigada.

## 4. Reuniões `hub` que já nasceram `Cancelada` no backfill

121 reuniões do Hub entraram no espelho já `Cancelada`. **Nenhuma tinha lembrete pendente**
(`lembretes_cancelados=0`). Por que zero:

- as duas com lembrete pendente (agendamentos 959 e 945) foram canceladas à mão hoje às 06:19,
  antes do deploy (ações 4002 e 3964);
- as outras 4 futuras são as reuniões de teste de 2027, sem agendamento.

Histórico dos lembretes dessas 121 (para dimensionar o que o guard teria evitado):

```
 executado | 95
 cancelado | 30
 skipped   | 18
```

95 lembretes saíram para reuniões que hoje constam `Cancelada`. Não dá para saber quantas já
estavam canceladas no momento do envio: a Exact não tem data de cancelamento. O RECON §2
provou 4 casos (remarcação registrada antes do envio). Daqui para a frente `exact_type_visto_em`
grava quando o espelho viu o status mudar, com erro máximo de um ciclo (10 min).

Lembretes pendentes agora, todos de reunião `Vigente` no espelho:

```
 3820 | 07/10 09:30 | ag 930 | 4772376 | Vigente
 3824 | 07/10 09:30 | ag 932 | 4772377 | Vigente
 4028 | 08/10 14:00 | ag 971 | 4774374 | Vigente
 4006 | 08/10 17:45 | ag 961 | 4774051 | Vigente
 3976 | 09/10 09:30 | ag 954 | 4773672 | Vigente
 4032 | 09/10 15:30 | ag 973 | 4774926 | Vigente
 4016 | 09/10 17:45 | ag 967 | 4774102 | Vigente
```

## 5. O guard do lembrete

`qualificacao_guard.guard_de_lembrete` chama `_espelho_bloqueia` depois de "a reunião já
começou?" e antes de "lembrete já saiu nas últimas 24h?":

1. linha de `reuniao_status` com `agendamento_id = reuniao.id` e `exact_type <> 'Vigente'` →
   `"reunião {meeting_id} está {exact_type} na Exact"`;
2. linha `Vigente`, futura, do mesmo `telefone_chave`, com `registrado_em` maior e outro
   `meeting_id` → `"existe reunião mais nova para esta pessoa (remarcação): {id} em {dd/mm hh:mm}"`;
3. sem linha nenhuma → passa, com `↩️ lembrete sem espelho em reuniao_status (agendamento N), segue`.

O motivo chega inteiro em `nat_scheduled_actions.motivo` (TEXT): `enviar_nat` devolve o motivo do
guard e `lembrete_reuniao` levanta `AcaoIgnorada(f"lembrete não saiu: {motivo}")`
(`qualificacao_fluxo.py`, handler do lembrete). Exceção dentro do guard continua bloqueando
(fail-closed já existente, `"erro inesperado no guard do lembrete"`).

**O que o guard bloqueou nas primeiras 24h:** ainda não medível (deploy às 06:37 SP, o primeiro
lembrete do dia é 09:30). Consulta pronta:

```sql
SELECT motivo, count(*) FROM nat_scheduled_actions
 WHERE kind='lembrete_reuniao' AND status='skipped' AND created_at > now() - interval '1 day'
 GROUP BY 1;
```

> Atenção na leitura: `created_at` é a data em que o lembrete foi AGENDADO, não executado. Para
> "o que foi pulado nas últimas 24h" o filtro certo é `processed_at > now() at time zone
> 'America/Sao_Paulo' - interval '1 day'` (processed_at é SP naive).

## 6. Arquivos

| arquivo | o quê |
|---|---|
| `backend/app/models.py` | `EXACT_TYPES`, `ORIGENS_REUNIAO`, `PREFIXO_REUNIAO_HUB`, `ReuniaoStatus`, `ReuniaoSyncCursor` |
| `backend/migrate_reuniao_status.py` | migração idempotente, docstring com os porquês |
| `backend/app/agendamento/client.py` | `listar_meetings` (exatamente um filtro, uma página, aviso se encher) |
| `backend/app/reuniao_sync.py` | `flag_ligada`, `_normalizar`, `_vincular`, `UPSERT`, `_cancelar_lembrete`, `sincronizar`, `ciclo`, `reuniao_sync_job` |
| `backend/app/qualificacao_guard.py` | `_espelho_bloqueia` e a chamada em `guard_de_lembrete` |
| `backend/app/main.py` | task no `lifespan` + cancelamento no shutdown + linha de boot |
| `backend/test_reuniao_status.py` | testes, não executados |
| `backend/.env` (fora do git) | `REUNIAO_SYNC_ENABLED=true` (cópia de antes em scratchpad) |

## 7. Testes (escritos, não executados)

`cd backend && venv/bin/python test_reuniao_status.py`, padrão dos `test_*.py` (script com
`checa`, Exact injetada, banco dublê):

1. `_normalizar`: `startTime` 18:30 fica 18:30; `registerDate` 16:06:50Z vira 13:06:50 SP; a chave
   de telefone; o UTC do cursor.
2. origem: prefixo → `hub`; nulo ou texto da SDR → `exact`.
3. upsert: estrutura do SQL (`IS DISTINCT FROM` para `anterior` e `visto_em`, `created_at` fora
   do SET, `COALESCE` no vínculo); primeira passada = nova e cursor −5 min; segunda passada com
   tipo diferente = atualizada com mudança; mesma reunião nas duas leituras = um upsert; primeiro
   ciclo relê desde 07/09 e os seguintes, hoje −2.
4. `Vigente → Cancelada` de `hub` cancela o lembrete e loga; origem `exact` e "já estava
   Cancelada" não mexem.
5. guard: Cancelada bloqueia; reunião mais nova bloqueia; Vigente sem nova passa; sem espelho
   passa e loga.
6. flag: desligada não chama `sincronizar` nem abre o banco; grafias aceitas e recusadas.

A semântica do `ON CONFLICT` (o banco usar o valor antigo no CASE) só é provada contra Postgres
real; o dublê confere a estrutura. O ensaio com rollback da seção 3 rodou o UPSERT de verdade
em 249 linhas.

## 8. Desvios do plano, com evidência

1. **Branch a partir da `main`, não da `feat/pos-psiclinica-aplicada`.** A `main` já tinha o merge
   da feat (`28a517d`) e mais o commit da spec (`cb8e6f9`). Aprovado no checkpoint.
2. **`agendamento_id BIGINT` com `ON DELETE SET NULL`; `created_at`/`updated_at` em SP; CHECK
   também em `exact_type_anterior`; índices só na migração.** Aprovados no checkpoint.
3. **Vínculo por `lead_id` exige o mesmo horário** (`_vincular`, regra 2). Com `lead_id` puro, as
   25 reuniões de remarcação feitas pela consultora em lead do Hub (RECON §5.3) seriam penduradas
   no agendamento antigo, e o guard leria o status da reunião errada.
4. **Primeiro ciclo relê o status desde o cursor (07/09), não desde hoje −2.** O ensaio com
   rollback deu 226 linhas: ficavam de fora as reuniões registradas antes de 07/09 que acontecem
   depois. Com a correção, 249, igual ao RECON. Do segundo ciclo em diante, hoje −2.
5. **Cancelamento do lembrete por `agendamento_id` do payload, não por
   `nat_scheduler.cancelar(kind, wa_id)`.** `cancelar` não grava motivo e cancela por contato,
   levando junto o lembrete de outra reunião da mesma pessoa. É o mesmo UPDATE das ações 3964 e
   4002 de hoje cedo. Motivo gravado: `reunião {id} Cancelada na Exact (reuniao_sync)`.
6. **Reunião `hub` que já nasce `Cancelada` no espelho também cancela o lembrete**, e não só a
   transição `Vigente → Cancelada`: cobre o backfill e a reunião criada e cancelada entre dois
   ciclos. O `print ⚠️` sai só na transição (é o que o critério 5 pede); o cancelamento loga 🚫.
7. **`exact_type_visto_em` = quando o status ATUAL foi visto pela primeira vez** (muda só junto
   com o tipo), e não "última vez visto". É o que dá ao bloco 1 o "cancelada desde quando".
   `updated_at` já registra a última passada.
8. **A regra "reunião mais nova" do guard roda mesmo sem a linha da própria reunião**, usando
   `agendamentos.created_at` como referência. Reunião mais nova `Vigente` da mesma pessoa é
   evidência positiva por si só; "sem linha nenhuma" continua passando.
9. **Sem `FOR UPDATE` no cursor.** Um worker só, e o lock seguraria a transação aberta durante as
   duas chamadas HTTP.
10. **`pypdf` instalado só no scratchpad** (`pip --target`) para ler a spec. Nada no venv nem no
    sistema.

## 9. Dúvidas e o que fica para depois

- A sexta reunião `hub` sem vínculo (4753381, 15/09) não foi investigada.
- O guard pula o lembrete da reunião antiga numa remarcação, mas **ninguém arma lembrete para a
  reunião nova** quando ela é marcada pela consultora na Exact (origem `exact`). É o bloco 1.
- Notificação ao SDR quando reunião do Hub vira `Cancelada`: bloco 1 (hoje só `print`).
- Paginação de `/Meetings` se `$top=500` encher (o aviso já existe). Hoje, 249 em 30 dias na
  releitura do primeiro ciclo; nos seguintes, ~45.
- Webhooks da Exact: sessão própria.
- `backend/fix_status_orfao_webhook.py` segue solto e não foi tocado.
