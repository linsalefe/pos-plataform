# DEPLOY_FOLLOW_ESTAGIO_20260927 — follow por estágio no ar, em modo de teste

Sequência executada em **27/09/2026**, entre 13:58 e 14:04 UTC (10:58–11:04 SP).
Branch `follow-estagio` mergeada em `main` (`b96a460`) e implantada.

**O follow está LIGADO, mas só para o telefone do Álefe.** Nenhum lead real recebe nada
enquanto `FOLLOW_ESTAGIO_SOMENTE_TELEFONES` estiver no `.env`.

---

## 0. Os testes, antes de tudo

Não estavam no roteiro aprovado, mas eram o primeiro item do CHECKPOINT do relatório da
sprint, e rodei antes de tocar em produção. **Foi o certo: houve uma falha.**

```
$ venv/bin/python test_follow_estagio.py
❌ 1 falha(s): ['  e o cursor NÃO foi movido']
```

**A falha era da ASSERÇÃO, não do código.** Eu tinha escrito
`[s for s, _ in sqls if "UPDATE" in s] == []`, e `"UPDATE"` casa com o `FOR UPDATE` da própria
leitura do cursor:

```
obtido=['SELECT ultimo_evento_id FROM follow_estagio_cursor WHERE id = 1 FOR UPDATE']
```

O comportamento estava correto — nenhum `UPDATE follow_estagio_cursor` rodou quando não havia
evento novo. A asserção agora ancora em `startswith("UPDATE follow_estagio_cursor")`
(commit `3ac4239`). Depois disso:

```
$ venv/bin/python test_follow_estagio.py      ✅ Todos passaram. Nada enviado, nada gravado.
$ venv/bin/python test_higiene_disparo.py     ✅ Todos passaram. Nada enviado, nada gravado.
```

Duas verificações da suíte do follow que só existem porque ela roda contra o banco:

* **§1b passou contra produção.** Os nove nomes do JSON são exatamente os nove que
  `exact_stage_events` tem nos últimos 30 dias, nos dois sentidos: nenhum estágio de follow do
  18535 ficou fora do mapa, nenhum nome do mapa é fantasma.
* **§2 confirmou o `mes`:** os doze meses em português, `Março` acentuado, e os dois casos de
  borda de fuso (naive `01/10 00:30` → Outubro; aware `01/10 02:00 UTC` → Setembro).

---

## 1. Migração — **cursor inicial gravado em 4259**

```
$ venv/bin/python migrate_follow_estagio.py

BEFORE — follow_estagio_envios existe: False
BEFORE — follow_estagio_cursor existe: False
  CREATE TABLE IF NOT EXISTS follow_estagio_envios
  CREATE TABLE IF NOT EXISTS follow_estagio_cursor
  follow_estagio_envios_status_valido CHECK (status IN ('pendente','enviado','skipped','falhou'))
  CREATE UNIQUE INDEX ux_follow_estagio_lead_estagio ON follow_estagio_envios (lead_exact_id, estagio_id)
  CREATE INDEX ix_follow_estagio_pendente ON follow_estagio_envios (id) WHERE status = 'pendente'
  CREATE INDEX ix_follow_estagio_estagio_created ON follow_estagio_envios (estagio_id, created_at DESC)

  exact_stage_events: MAX(id) = 4259
  cursor id=1 -> ultimo_evento_id = 4259 (atualizado 2026-09-27 14:02:56.537642)

OK: 0 linha(s) em follow_estagio_envios — 0 é o esperado (sem backfill).
```

**O cursor nasceu em 4259, que era o `MAX(id)` de `exact_stage_events` naquele instante**
(medido imediatamente antes: `max(id) = 4259`, `count(*) = 4225`). É o ponto que mais
importava: com 0, a primeira passada teria enfileirado um follow para cada entrada em estágio
do histórico — **1 255 só nos últimos 30 dias**, para leads já descartados, já vendidos ou que
já receberam a despedida.

Confirmado depois do deploy:

```
 id | ultimo_evento_id |       atualizado_em
----+------------------+----------------------------
  1 |             4259 | 2026-09-27 14:02:56.537642
```

---

## 2. `.env`

Backup em `backend/.env.bak_20260927_follow` antes de editar. Duas linhas acrescentadas (54 →
61 linhas, contando os comentários):

```bash
FOLLOW_ESTAGIO_ENABLED=true
FOLLOW_ESTAGIO_SOMENTE_TELEFONES=83988046720
```

Nenhuma variável existente foi tocada.

---

## 3. `nat_config.follow_enabled = false`

```
ANTES:  id=1  follow_enabled=t  follow_template=follow_up
UPDATE 1
DEPOIS: id=1  follow_enabled=f  follow_template=follow_up
```

Por que: `follow_up` é o **segundo template mais usado pelo SDR no `Follow 1` (22 envios) e no
`Follow 2` (18)**. Com o `follow_20h` do agente ligado, a mesma família sairia por duas réguas
que não se conhecem no dia em que o agente religar.

Nada pendente foi cancelado — `follow_20h` já estava parado desde 17/09 (60 `falhou`, 61
`executado`, 404 `cancelado`, **0 pendente**). E o **lembrete de reunião segue de pé**, com 8
pendentes, como combinado.

Duas observações honestas:

* `follow_template` continua `'follow_up'`. Desligar a flag basta; apagar o template apagaria
  a informação de qual era, e religar exige os dois juntos de qualquer forma
  (`nat_routes.py:647`).
* `nat_config.updated_at` **não mudou** (segue 01/09 19:19). A coluna não tem `onupdate` e o
  UPDATE foi SQL cru. Quem for auditar "quando o follow do agente foi desligado" tem de olhar
  este documento ou o git, não aquela coluna.

---

## 4. Merge, push, restart

```
b96a460 merge: follow automático por estágio da Exact (27/09)   <- main, pushado
3ac4239 follow: asserção do cursor era frouxa
fe74b25 docs(follow): relatório da sprint
```

Restart às **14:03:39 UTC**. `systemctl is-active` → `active`.

### O boot

```
✅ Sync Exact Spotter agendado (a cada 10 min)
✅ Alertas de janela 24h agendados (a cada 5 min)
✅ Agendamento de templates ativo (checa a cada 60s)
✅ Agendador NAT ativo (checa a cada 60s)
✅ Fila do RD Station ativa (checa a cada 60s, envio LIGADO)
✅ Alerta de saúde de entrega ativo (checa a cada 15 min)
✅ Follow por estágio da Exact (checa a cada 60s, envio LIGADO, MODO DE TESTE com 1 telefone(s))
✅ Faxina de agendamento ativa (remove box nosso parado há 0:15:00)
✅ Varredura de agente parado ativa (a cada 15 min, régua de 60 min — só notifica)
INFO:     Application startup complete.
✅ agendamento: 2 consultora(s) em rotação — Victória Amorim, Victória Rodrigues
✅ agendamento: source 'Landing Page' (id 140648) com as 14 origens da allowlist confirmadas.
```

A linha do follow diz as três coisas que importam: **60s**, **LIGADO** e **MODO DE TESTE com 1
telefone(s)**. Nenhum `❌` e nenhum `Traceback` no log desde o restart — os outros nove jobs
subiram normalmente.

### O primeiro ciclo, com o gate aberto

```
14:04:42  🧪 follow em MODO DE TESTE: só 1 telefone(s) da allowlist entram.
             Os demais eventos são consumidos SEM criar linha.
14:04:43  ⏱️  follow por estágio: {'estagios_no_mapa': 9}
```

Lido assim:

* o job **leu o cursor** (se não tivesse achado a linha, o resumo seria `{'sem_cursor': True}`
  e o log mandaria rodar a migração);
* o job **carregou o mapa** e achou os nove estágios (`estagios_no_mapa: 9`; mapa torto daria
  `{'mapa_invalido': True}`);
* **nenhum evento novo** acima de 4259 — o resumo não tem `pendente`, `reentrada`,
  `fora_da_allowlist` nem `cursor`, o que significa que `ler_eventos` saiu no
  `if not eventos: return {}` sem mover o cursor;
* **nada para drenar** — nenhuma chave `envio_*`.

O aviso `🧪` sai em toda passada de propósito: é a prova, no journald, de que o modo de teste
está ativo e que os follows dos leads reais estão sendo **descartados** durante a janela.

### Os três primeiros ciclos, de 60 em 60s

```
14:04:43  ⏱️  follow por estágio: {'estagios_no_mapa': 9}
14:05:43  ⏱️  follow por estágio: {'estagios_no_mapa': 9}
14:06:43  ⏱️  follow por estágio: {'estagios_no_mapa': 9}
```

Cadência exata, resumo idêntico, nenhum erro. O job está em regime — **11 ciclos** entre
14:04:43 e 14:14:43, todos com o mesmo resumo.

### A passada do sync, às 14:14:18

```
🔄 Sync Exact Spotter: {'total_synced': 9891, 'new': 0, 'updated': 9891, 'welcome_sent': 0, ...}
14:14:43  ⏱️  follow por estágio: {'estagios_no_mapa': 9}
```

9 891 leads varridos, **0 novos, 0 eventos de estágio**. O cursor continua em 4259 e
`follow_estagio_envios` continua vazia — correto: sem transição, não há nada a enfileirar.

### **HOJE É DOMINGO — e por isso não haverá evento natural nenhum**

Isto não estava previsto no roteiro e muda como o teste tem de ser lido.

```
$ TZ=America/Sao_Paulo date        Sunday, 27/09 11:14

último evento do 18535:
 4259 | <NULL> -> Entrada | 00:10 SP     <- lead chegando pela LP de madrugada, não arrasto de SDR
```

Atividade de estágio por dia da semana no 18535, últimos 30 dias:

| Dom | Seg | Ter | Qua | Qui | Sex | Sáb |
|---:|---:|---:|---:|---:|---:|---:|
| **54** | 530 | 463 | 384 | 386 | 426 | 78 |

Domingo tem **54 eventos em 30 dias (2,3 %)**, e são quase todos `<NULL> -> Entrada` — lead
novo entrando pela landing page, que não é estágio de follow e não dispara nada.

**Consequências práticas:**

1. **O job está verificado em regime, mas ainda não foi exercitado contra um evento real.** O
   caminho de leitura e envio está coberto pelos testes (232 asserções), não por tráfego de
   produção. A primeira prova real vem do primeiro arrasto de card.
2. **O Álefe pode testar agora mesmo** — o arrasto dele É o evento, e o sync o vê em até
   ~10 min independentemente do dia. A janela de horário não existe neste job, de propósito
   (decisão de 27/09), então domingo não atrapalha o teste.
3. **`fora_da_allowlist` só vai aparecer na segunda.** É o contador dos leads reais que
   passaram por um estágio e não receberam por causa do modo de teste. Hoje ele fica em zero
   porque ninguém move card no domingo — não porque o filtro não esteja funcionando.

---

## 5. Nenhuma linha criada, nenhuma mensagem enviada

```
$ SELECT count(*) FROM follow_estagio_envios;
 0

$ SELECT count(*) FROM messages WHERE direction='outbound' AND created_at >= '2026-09-27 14:00';
 0
```

**`follow_estagio_envios` está vazia** e nenhum outbound saiu depois do restart. Era o
esperado: o cursor está no fim do histórico e o sync (a cada 10 min) ainda não produziu evento
de estágio novo no 18535 desde a migração.

---

## O que acontece a partir de agora, sem ninguém fazer nada

A cada 60s o job acorda, lê os eventos de `exact_stage_events` com `id > cursor`,
`funnel_id = 18535` e destino em um dos nove nomes, e:

* se for o telefone do Álefe → cria `pendente` e envia na mesma passada;
* se for **qualquer outro lead** → o evento é **consumido sem criar linha**, e conta como
  `fora_da_allowlist` no resumo. Esses follows **não saem e não voltam** — é o preço do modo
  de teste, e é por isso que ele não pode gravar `skipped` (a UNIQUE não é parcial: uma linha
  `skipped` bloquearia o par para sempre, e ao liberar o gate aqueles leads ficariam invisíveis).

Nos números medidos, isso é ~42 eventos/dia sendo descartados enquanto a allowlist estiver
ligada. Olhar `fora_da_allowlist` no resumo é a forma de saber quantos.

---

## Roteiro de teste — pronto para o Álefe

Os dois leads dele em `Agendados` no 18535:

| `lead_ids` | `exact_id` | `sub_source` | curso que vai renderizar |
|---:|---:|---|---|
| **9127** | 51438018 | `PosMulheridades` | Saúde Mental e Mulheridades |
| **9134** | 51438436 | `Pos Saude do Trabalhador` | Saúde Mental do Trabalhador |

1. **`Agendados → Follow 1`** no lead 9127. Em até ~11 min (latência do sync: p50 4,8 min,
   p90 9,5 min, p99 10,6 min) chega `mensagem_flow`:
   *"Ola Álefe, é o Thobias do CENAT ✨ … Pós Graduação Saúde Mental e Mulheridades"*.
2. **Follow 2 … ` Follows 9`**, um por vez. No ` Follows 7`, conferir que o texto diz
   **"neste mês de Setembro"** e **não** o nome do curso — é o defeito que esta sprint existe
   para não repetir (15 dos 40 envios manuais saíram errados).
3. **Reentrada:** `Follows 9 → Follows 8 → Follows 9`. **Nada** deve chegar. No log:
   `↩️ follow: lead … já tem linha para ' Follows 9' — reentrada`.
4. **Lead 9134:** `Agendados → Follows 5` direto. Só o follow 5 chega (o gatilho é o evento,
   não o estado — não há varredura dos degraus anteriores).

Para acompanhar:

```sql
SELECT id, lead_exact_id, estagio_nome, template, status, motivo, created_at, enviado_em
  FROM follow_estagio_envios ORDER BY id DESC LIMIT 12;
```

```bash
sudo journalctl -u cenat-backend -f | grep -E "follow|➕|✅ follow|⏭️|↩️|❌ follow"
```

Duas coisas para vigiar durante o teste:

* Se o Álefe **responder** algo que case `PADRAO_RECUSA`, todos os degraus seguintes viram
  `skipped` por 30 dias, com a linha gravada e o motivo citando a frase. É o comportamento
  certo — mas para o teste significa parar e usar outro lead.
* O `resumo` traz `fora_da_allowlist: N`. N > 0 é normal e esperado: são os leads reais que
  passaram por um estágio e não receberam.

---

## Para liberar de verdade (NÃO feito)

```bash
# apagar a linha FOLLOW_ESTAGIO_SOMENTE_TELEFONES do backend/.env
sudo systemctl restart cenat-backend
# conferir no boot: "envio LIGADO" SEM "MODO DE TESTE"
```

**Avisar o comercial antes.** A partir daí todo arrasto de card no funil 18535 dispara
template: ~42 por dia, **sem janela de horário** (inclusive 21h e sábado) e **sem teto de
rajada** (a maior medida foi 45 leads numa passada, 18/09 às 18:18 SP — seriam 45 despedidas
do `mensagem_follow9` em ~90 s). As duas são decisões registradas do Álefe (27/09), e o
`131049` da Meta ("not delivered to maintain healthy ecosystem", 17 casos em 30 dias no volume
atual) é o primeiro sinal de que um teto faria falta.

---

## Rollback

Em ordem de reversibilidade, do mais barato ao mais caro:

```bash
# 1. Desligar (instantâneo, não perde nada). FOLLOW_ESTAGIO_ENABLED=false no .env + restart.
#    O job volta a não tocar no banco; as linhas já criadas ficam como histórico.

# 2. Religar o follow do agente, se for a decisão:
#    UPDATE nat_config SET follow_enabled = true WHERE id = 1;

# 3. Reverter o código: git revert -m 1 b96a460 && restart.
#    As tabelas ficam (DROP não é necessário — ninguém mais escreve nelas).

# 4. Reprocessar um estágio de propósito (só se alguém pedir):
#    DELETE FROM follow_estagio_envios WHERE lead_exact_id = <id> AND estagio_id = <id>;
#    Baixar o cursor é decisão explícita, nunca efeito de rodar a migração de novo
#    (ON CONFLICT DO NOTHING garante isso).
```

---

*Deploy conferido: cursor em 4259, primeiro ciclo limpo às 14:04:42 com o gate aberto,
`follow_estagio_envios` com 0 linhas e 0 outbound desde o restart.*
