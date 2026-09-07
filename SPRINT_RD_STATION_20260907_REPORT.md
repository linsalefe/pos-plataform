# SPRINT_RD_STATION_20260907 — relatório da Fase 1

Branch `rd-station-fase1`, 7 commits. **Parei no CHECKPOINT.**

Nada foi executado contra o mundo real: a migração **não** rodou, o backfill **não** rodou, o
serviço **não** foi reiniciado, o `.env` **não** foi tocado, e **nenhuma chamada ao RD Station
aconteceu em momento nenhum desta sessão**. Os testes foram escritos e **não** executados.

---

## 1. Arquivos criados e alterados

| arquivo | o que é |
|---|---|
| `backend/rd_conversoes.json` | **novo.** Os 14 pares `sub_source → conversion_identifier`, exatamente como no prompt. |
| `backend/app/rd_station.py` | **novo.** Módulo puro: carrega o mapa, normaliza e-mail e telefone, monta a chave e o payload, faz o POST. Não conhece o banco. |
| `backend/app/models.py` | **alterado.** Acrescenta `RD_PENDENTE/ENVIADO/SKIPPED/FALHOU`, `RD_STATUS` e a classe `RdConversao`. Nada existente foi tocado. |
| `backend/migrate_rd_conversoes.py` | **novo, NÃO EXECUTADO.** Cria a tabela, o CHECK e os dois índices. |
| `backend/app/rd_outbox.py` | **novo.** A árvore de decisão: quem vira `pendente`, quem vira `skipped` e com qual motivo. `INSERT ... ON CONFLICT DO NOTHING`. |
| `backend/app/agendamento/agendar.py` | **alterado.** Import de `rd_outbox` e os dois hooks de enfileiramento. Nenhuma linha do fluxo existente mudou de semântica. |
| `backend/app/rd_sender.py` | **novo.** O drenador, com o gate `RD_ENVIO_ENABLED`. |
| `backend/app/main.py` | **alterado.** Cria e cancela a task do drenador no `lifespan`, e imprime no boot se o envio está ligado. |
| `backend/backfill_rd_conversoes.py` | **novo, NÃO EXECUTADO.** Enfileira o histórico desde 18/08. Dry-run por padrão, e nunca envia. |
| `backend/test_rd_station.py` | **novo, NÃO EXECUTADO.** 70+ asserções sobre normalização, enfileiramento e desfecho do drenador. |

---

## 2. Os dois pontos de enfileiramento

| # | arquivo:linha | função | contexto |
|---|---|---|---|
| A | **`backend/app/agendamento/agendar.py:366`** | `agendar()` | depois de `db.add(ag)` + `await db.commit()` (`:353-354`) |
| B | **`backend/app/agendamento/agendar.py:623`** | `cadastrar_lead_sem_agendar()` | depois de `db.add(ag)` + `await db.commit()` (`:617-618`) |

**Confirmado nos dois: o `ag.id` já existe** — `async_session` é criado com
`expire_on_commit=False` (`app/database.py:62`), então o id atribuído pelo BIGSERIAL sobrevive
ao commit e está disponível na linha seguinte.

**Confirmado nos dois: estão antes de qualquer chamada à Exact.**
- Em `agendar()`, a primeira chamada externa depois do hook é `client.criar_box` (`:394`), no
  laço do passo 1. A verificação `client.buscar_lead_por_id` do lead externo acontece bem
  antes (`:314`), fora deste trecho.
- Em `cadastrar_lead_sem_agendar()`, a primeira é `client.criar_lead` (`:627`).

**CONTRADIZ o prompt: não existe `flush()` em nenhum dos dois pontos.** O prompt pedia "logo
após o `flush()` que dá `ag.id`"; o código real faz `db.add(ag)` seguido de `await db.commit()`
— o commit por passo é decisão explícita de `_marcar` (`:231-241`), documentada, e trocá-lo por
um flush mudaria a durabilidade do fluxo de agendamento, que estava fora do escopo. O hook
ficou logo após o commit, que é o instante equivalente: o primeiro em que `ag.id` existe.

---

## 3. Caminhos de rollback antes do primeiro `_marcar`

**Sim, existem — e a linha do outbox se perde neles.** Só descrevo, como pedido.

`enfileirar` não commita: a linha viaja no commit do `_marcar` seguinte. Percorrendo os
caminhos a partir do hook:

**Em `agendar()` (hook em `:366`):**

| caminho | o que acontece | a linha do outbox |
|---|---|---|
| `criar_box` levanta `SlotOcupado` | `continue`, tenta a próxima consultora | segue viva na sessão |
| `criar_box` levanta `ExactErro` | `_marcar(PASSO_FALHOU)` → **commita** (`:383`) | **preservada** |
| nenhuma consultora livre | `_marcar(PASSO_FALHOU)` → **commita** (`:390`) | **preservada** |
| sucesso | `_marcar(PASSO_BOX_CRIADO)` → **commita** (`:398`) | **preservada** |
| **exceção não tratada** entre o hook e o primeiro `_marcar` | propaga até o endpoint; `get_db` fecha a sessão sem commit e o `async with` do sessionmaker dá **rollback** | **PERDIDA** |

A janela real são duas chamadas: `escolher_consultora(db, ...)` (`:371`, um SELECT — um erro de
pool ou de conexão aqui cai nesse caso) e qualquer exceção de `criar_box` que **não** seja
`SlotOcupado` nem `ExactErro` (hoje não há uma conhecida, mas o `except` é tipado, não amplo).

**Em `cadastrar_lead_sem_agendar()` (hook em `:623`):** mesma forma, janela menor — só
`client.criar_lead` (`:627`), cujo `except client.ExactErro` leva a `_marcar(PASSO_FALHOU)`
(**commita**). Qualquer outra exceção perde a linha.

**O que isso custa, e por que não corrigi:** nesses caminhos o `Agendamento` também não sai de
`iniciado` — a fila e a tabela de origem contam a mesma história, e `backfill_rd_conversoes.py`
repesca a linha depois, porque varre `agendamentos` e é idempotente. A alternativa (commitar
dentro de `enfileirar`) romperia a regra de que quem chama é dono da transação e criaria um
commit a mais no caminho de request da landing page — mudança no fluxo de agendamento, que
estava fora do escopo. Fica registrado para decisão.

O que **não** acontece: um erro no INSERT do outbox abortar a transação do agendamento. O
INSERT roda dentro de `db.begin_nested()` — ver o item 6.

---

## 4. CHECK e índices (o que a migração vai criar)

Construídos, não digitados — `CHECK_SQL` é gerado a partir de `RD_STATUS` de `app/models.py`,
no padrão de `migrate_espontaneo.py:145-172`.

```sql
-- constraint rd_conversoes_status_valido
CHECK (status IN ('pendente', 'enviado', 'skipped', 'falhou'))

-- índice 1 — a idempotência
CREATE UNIQUE INDEX IF NOT EXISTS ux_rd_conversoes_chave_ident
  ON rd_conversoes (chave, conversion_identifier);

-- índice 2 — a única consulta do drenador. PARCIAL de propósito: `enviado` e `skipped` são
-- terminais e crescem para sempre; um índice completo carregaria o histórico numa busca que
-- só olha a cauda viva.
CREATE INDEX IF NOT EXISTS ix_rd_conversoes_pendente
  ON rd_conversoes (run_at) WHERE status = 'pendente';
```

O CHECK é aplicado por `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` dentro da mesma
transação do `engine.begin()` — ou a tabela fica com o CHECK novo, ou com o velho, nunca sem
nenhum. Sem CHECK e sem FK em `conversion_identifier`, `sub_source` e `agendamento_id`, pela
lição de `migrate_agendamentos_subsource.py:26-27`.

---

## 5. Saída do `py_compile`

```
OK   app/rd_station.py
OK   app/rd_outbox.py
OK   app/rd_sender.py
OK   app/models.py
OK   app/main.py
OK   app/agendamento/agendar.py
OK   migrate_rd_conversoes.py
OK   backfill_rd_conversoes.py
OK   test_rd_station.py
```

Além do `py_compile`, três verificações de import/leitura (permitidas pelo critério 8, nenhuma
escreve nada):

- `import app.main` sobe sem erro — o `lifespan` novo não quebra o boot, e o print do gate
  responde `envio DESLIGADO`.
- `rd_station` à mão: `identifier_para('POSMULHERIDADES')` → `formulario-pos-mulheridades-2`;
  `normalizar_telefone_rd('5599858 1234')` → `+5555998581234` (**o DDD 55 sobreviveu**);
  `normalizar_email('  Maria@X.com ')` → `maria@x.com`.
- O SELECT do backfill, isolado, contra o banco real: **383 linhas**, a primeira sendo o
  agendamento `#25` de 18/08 06:37. Bate exatamente com o número do RECON (383 após o corte de
  leads de teste). Foi um `SELECT` em `agendamentos`, sem tocar em `rd_conversoes`.

**`test_rd_station.py` não foi executado**, conforme o critério 8. Ele é um script solto no
estilo de `test_higiene_disparo.py` (não usa `pytest`), e roda com
`venv/bin/python test_rd_station.py`.

---

## 6. O que ficou diferente do prompt

**CONTRADIZ o prompt: `agendar.py` não tem `flush()`.** Detalhado no item 2. O hook ficou após
o `await db.commit()`, que é o instante equivalente.

**CONTRADIZ o prompt: o backfill não tem `--dry-run` como a flag que muda o comportamento.**
Uma flag `--dry-run` que já é o padrão não faz nada quando digitada, e a que importa — a que
escreve — ficaria implícita. Inverti: `--executar` é quem grava, e o padrão continua sendo
dry-run como pedido. `--dry-run` **é aceito e ignorado**, de propósito, porque é o que está
escrito no plano de deploy do CHECKPOINT e é o que a mão de quem opera vai digitar; sem isso, o
procedimento morreria num `unrecognized arguments` no meio da produção.

**Acrescentado ao prompt: o INSERT do outbox roda dentro de `db.begin_nested()`.**
`rd_outbox._gravar` abre um savepoint. Sem ele, um INSERT que falhasse deixaria a transação da
sessão **abortada**, e o `_marcar` seguinte — que grava `box_criado` depois do BoxesAdd —
falharia no commit com `InFailedSQLTransactionError`. O agendamento morreria por causa da fila,
que é o inverso exato da prioridade do critério 6. É a mesma lição do P0-A
(`qualificacao_fluxo.py:1440-1460`), onde uma transação emprestada derrubou 100% dos
agendamentos do agente por três dias. O `try/except` do prompt continua lá, como cinto e
suspensório.

**Acrescentado ao prompt: `conversion_identifier` de um `skipped/sem_mapa`.** A coluna é NOT
NULL e o prompt não dizia o que gravar quando não há identifier. Gravo
`sem-mapa:<sub_source em minúsculas>` (`rd_outbox._identifier_orfao`). Duas razões: a UNIQUE
continua valendo por curso, então dois cursos diferentes fora do mapa não colapsam numa linha
só; e o prefixo garante que isto nunca colida com um identifier real nem seja postado por
engano se alguém repescar a fila.

**Detalhado além do prompt: `sem_email` × `email_invalido`.** O prompt já previa os dois
motivos; a regra que escrevi é `email_invalido` quando o campo tem conteúdo mas não passa na
peneira, e `sem_email` quando está vazio ou nulo. Distinguir importa porque o primeiro é dado
sujo de formulário e o segundo é decisão de produto (o agente não pergunta e-mail) — e quem for
decidir o que fazer com cada um faz contas diferentes.

**Detalhado além do prompt: `montar_payload` omite `name` em branco**, pela mesma razão que
omite `mobile_phone` — campo presente e vazio pode gravar por cima de um dado bom que o RD já
tenha no contato.

**Acrescentado ao prompt: `processar_pendentes` devolve `{"sem_chave": True}`** quando o gate
está aberto e `RD_API_KEY` está vazia, sem tocar no banco. O prompt pedia o log `❌`; o retorno
distinto é o que permite ao teste afirmar que o banco não foi tocado.

Fora isso, tudo seguiu o prompt: as 12 decisões de arquitetura, os 8 critérios de aceite, os
nomes dos arquivos, as constantes (`60s`, `50`, `3`, `300s`, timeout `15s`), o mapa JSON com os
14 pares **exatos**, e o vocabulário de status.

---

## 7. O que o `.env` precisa

**Obrigatório para ligar o envio (Fase 1):**

```
RD_API_KEY="<a API Key da conta, do painel do RD>"
RD_ENVIO_ENABLED=false
```

**Nada mais é obrigatório.** `RD_CONVERSOES_PATH` é opcional: o padrão é `rd_conversoes.json`
relativo ao diretório de trabalho, e o unit do systemd tem
`WorkingDirectory=/home/ubuntu/pos-plataform/backend` — o arquivo versionado no repo é
encontrado sem configuração. Só vale definir se um dia o mapa sair do repo:

```
RD_CONVERSOES_PATH=/etc/cenat/rd_conversoes.json
```

Três avisos de operação:

1. **Aspas em valor com espaço**, como manda `agendamento/origens.py:28-31`. Nenhum dos valores
   acima tem espaço hoje, mas a API Key vem colada do painel e ninguém confere.
2. **`RD_ENVIO_ENABLED` falha fechada.** Só `true`, `1`, `sim` ou `yes` (em qualquer caixa)
   ligam. Qualquer outra coisa — inclusive `True` escrito errado, vazio ou ausente — deixa
   desligado. Se a variável for escrita errada, a fila acumula; ela nunca abre sozinha.
3. **As duas chaves hexadecimais que vieram no fim do prompt (`público` / `privado`) não são o
   `RD_API_KEY` desta fase.** Esse par é `client_id` / `client_secret` de OAuth, que é a
   Fase 2. **Não as coloquei em nenhum arquivo** — não estão no repo, não estão no `.env`, não
   estão em log nenhum. Quando forem usadas, vão só para o `.env`. E como trafegaram por uma
   conversa, o certo é **rotacioná-las** no painel do RD antes de pôr em produção.

---

## 8. Estado da branch

```
a3311b7 rd: backfill aceita --dry-run explícito (é o padrão)
7b7834e rd: testes de normalização, enfileiramento e drenador (não executados)
3131e1c rd: backfill do outbox desde 18/08 (dry-run por padrão) — não executado
c1f2dd1 rd: drenador do outbox com gate RD_ENVIO_ENABLED (padrão false)
6279345 rd: enfileira conversão na mesma sessão do Agendamento
2031b6f rd: tabela rd_conversoes (outbox) e migração — não executada
bd3c71d rd: mapa sub_source->conversion_identifier, normalização e cliente
```

**Nada foi mesclado em `main`.** A branch está pushada e aguarda aprovação para a sequência do
CHECKPOINT — migração, `.env`, deploy, backfill em dry-run, e só depois `RD_ENVIO_ENABLED=true`
com o checklist dos fluxos no RD feito.

Enquanto isso não acontece, o efeito de subir esta branch é: `rd_conversoes` ganha linhas a
cada submissão da LP, o drenador imprime uma linha por minuto dizendo que o envio está
desligado, e **nenhuma conversão sai**.
