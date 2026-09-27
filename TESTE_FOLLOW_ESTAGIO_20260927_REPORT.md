# TESTE_FOLLOW_ESTAGIO_20260927 — relatório

**Resultado: FASE 1 completa e verificada. Fases 2–5 NÃO executadas, por impossibilidade
externa.** A API da Exact **não** move um lead entre estágios do mesmo funil, e os dois leads
que o roteiro nomeia **não existem mais na Exact**.

Foi o caminho que o próprio prompt previu: *"Se a API não permitir mudar estágio, parar após o
item 1 e reportar: o arrasto passa a ser manual do Álefe."*

**Resíduo: zero.** Nenhum lead alterado, nenhum evento de estágio criado, nenhuma mensagem
enviada, nenhuma linha em `follow_estagio_envios`. Provado no §4.

---

# 1. Critério 1 — a Fase 1 está completa ✅

| item | estado |
|---|---|
| Migração aplicada | ✅ `follow_estagio_envios` + `follow_estagio_cursor` criadas |
| Cursor em `MAX(id)` | ✅ **4259**, gravado 14:02:56 (o `MAX(id)` exato naquele instante) |
| `.env` | ✅ `FOLLOW_ESTAGIO_ENABLED=true` e `FOLLOW_ESTAGIO_SOMENTE_TELEFONES=83988046720` |
| `nat_config.follow_enabled` | ✅ `false` |
| Merge | ✅ `b96a460` em `main`, pushado |
| Restart limpo | ✅ 14:03:39, `active`, zero `❌` e zero `Traceback` |
| Primeiro ciclo com gate aberto | ✅ 14:04:42 (abaixo) |
| Linhas em `follow_estagio_envios` | ✅ **0** |

```
14:03:42  ✅ Follow por estágio da Exact (checa a cada 60s, envio LIGADO, MODO DE TESTE com 1 telefone(s))
14:04:42  🧪 follow em MODO DE TESTE: só 1 telefone(s) da allowlist entram.
14:04:43  ⏱️  follow por estágio: {'estagios_no_mapa': 9}
```

Detalhe completo em `DEPLOY_FOLLOW_ESTAGIO_20260927.md`. Além do roteiro, rodei as duas suítes
antes de tocar em produção — e havia **uma falha**, na minha própria asserção (`"UPDATE"`
casava com `FOR UPDATE`), corrigida em `3ac4239`. Depois: 232 asserções verdes, incluindo a
§1b que confronta o mapa com `exact_stage_events` no banco real.

---

# 2. **CONTRADIZ o prompt (1):** os leads 9127 e 9134 não existem na Exact

O roteiro é construído sobre `lead_ids` **9127** (`exact_id` 51438018) e **9134**
(`exact_id` 51438436). Os dois foram **apagados da Exact**, provavelmente em 18/08, e só
sobrevivem no nosso espelho.

```
GET /Leads?$filter=id eq 51600542   ->  count=1   (controle: o filtro funciona)
GET /Leads?$filter=id eq 51438018   ->  count=0
GET /Leads?$filter=id eq 51438436   ->  count=0
```

O espelho confirma, e a prova é o `synced_at`: enquanto os outros leads do mesmo telefone
sincronizaram às **14:24 de hoje**, esses dois estão congelados em **18/08 02:38** — a última
vez que a Exact os devolveu.

```
 local_id | exact_id |           name            |   stage    |         synced_at
----------+----------+---------------------------+------------+----------------------------
     9127 | 51438018 | Álefe Guimel Lins Barbosa | Agendados  | 2026-08-18 02:38:13   <-- congelado
     9134 | 51438436 | Álefe Guimel Lins Barbosa | Agendados  | 2026-08-18 02:38:12   <-- congelado
     9324 | 51600542 | teste                     | Descartado | 2026-09-27 14:24:21
```

**O erro é meu, e propagou.** O §5.2 do `RECON_FOLLOW_AUTOMATICO_20260927.md` diz "nove leads,
todos no funil 18535" e apresenta `9127` e `9134` como estando em `Agendados` — aquilo foi lido
de `exact_leads` (o nosso espelho) e **eu não cruzei com a Exact**. O relatório da sprint e este
roteiro herdaram o erro. Na Exact são **7** leads com aquele telefone, não 9.

Ironicamente, isto é a confirmação ao vivo de um achado que eu mesmo listei no recon como
"observação pra depois": *"10 leads apagados na Exact que ficam no espelho para sempre."* São
exatamente 10, conferidos um por um contra a API — e **6 deles são leads de teste do Álefe,
apagados no mesmo dia 18/08** (a faxina da sprint de agendamento, que usou
`DELETE /LeadsDelete/{id}`, exclusão dura e sem desfazer):

```
 exact_id  | nome                        | stage no espelho | synced_at  | existe na Exact?
 51438018  | Álefe Guimel Lins Barbosa   | Agendados        | 18/08      | NÃO
 51438271  | Álefe teste de agenda       | Agendados        | 18/08      | NÃO
 51438278  | Álefe Guimel Lins agenda    | Agendados        | 18/08      | NÃO
 51438282  | Álefe Guimel Lins teste     | Agendados        | 18/08      | NÃO
 51438436  | Álefe Guimel Lins Barbosa   | Agendados        | 18/08      | NÃO
 51438444  | Álefe Guimel Lins teste     | Agendados        | 18/08      | NÃO
 47311086  | teste giovanna zaraga       | Descartado       | 28/05      | NÃO
 47398963  | teste teste                 | Entrada          | 24/02      | NÃO
 48276263  | teste 4                     | Agendados        | 13/03      | NÃO
 49750320  | Gustavo Branco              | Reativação…      | 25/06      | NÃO
```

10 de 10 confirmados inexistentes. O espelho tem 9 901 linhas; a Exact, 9 891.

**Consequência para o follow:** inofensiva. Lead apagado na Exact nunca muda de estágio, logo
nunca gera evento, logo nunca dispara follow. O `LEFT JOIN` de `_eventos_novos` já cobre o caso
inverso (evento de lead ausente do espelho). Mas para **este teste** é fatal: não há o que
arrastar.

---

# 3. **CONTRADIZ o prompt (2):** a API da Exact não move estágio intra-funil

Quatro tentativas, todas com **efeito zero** verificado campo por campo. Nenhuma foi chute de
payload: cada uma usou o contrato declarado no `$metadata`.

| # | chamada | resposta | efeito |
|---:|---|---|---|
| 1 | `POST /LeadsUpdate {"lead":{"stage":"Follow 1"},"key":51600542}` | **404** — "No HTTP resource was found that matches the request URI" | nenhum |
| 2 | `POST /ChangeFunnel {"leadId":51527070,"stageId":129985}` (24/08, lead **não** descartado) | **400** — `"Lead is already at this funnel"` | nenhum |
| 3 | `POST /ChangeFunnel {"leadId":51600542,"stageId":129985}` (lead descartado) | **400** — `"Lead is discarded"` | nenhum |
| 4 | `POST /SkipSteps {"id":51600542,"stageId":129985}` | **404** — sem rota | nenhum |

A #2 é o teste de 24/08 (`TESTE_CHANGEFUNNEL_20260824.md`), que já tinha estabelecido que
`ChangeFunnel` move entre **funis**, não entre estágios. As #1, #3 e #4 são de hoje.

**O achado metodológico:** o `$metadata` declara **107 EntitySets**, e a maioria **não tem rota
POST**. `LeadsUpdate` tem um `ComplexType` com uma propriedade `stage` declarada, e
`SkipSteps` tem um DTO de dois campos `{stageId, id}` — os dois parecem exatamente o endpoint
que falta, e os dois dão 404. **O `$metadata` não é um mapa da superfície de escrita.** A
superfície real é o conjunto pequeno que o projeto já usa: `/LeadsAdd`, `/BoxesAdd`,
`/BoxesRemove`, `/scheduleAdd`, `/ChangeFunnel`, `/timelineAdd`, `DELETE /LeadsDelete/{id}`.

**Parei aqui, e de propósito.** O passo seguinte seria adivinhar nomes de rota (`skipSteps`
minúsculo, `LeadsSkipSteps`, `StagesUpdate`…) com POST no CRM de produção. É exatamente o que a
sessão de 24/08 recusou — *"sondar POST às cegas em endpoints não documentados do CRM de
produção não é teste, é chute com efeito colateral"* — e continuo concordando. A diferença
entre as quatro tentativas acima e aquilo é que cada uma tinha um contrato declarado para citar.

## O obstáculo extra: os 7 leads que existem estão todos `Descartado`

```
 31485567  'Álefe Guimel Lins Barbosa'   Descartado   18535
 32196408  'a'                           Descartado   18535
 36773908  'kikjd'                       Descartado   18535
 48525996  'Alefe Lins'                  Descartado   18535
 51548604  'Álefe Guimel Lins Barbosa'   Descartado   18535
 51550281  'zzz teste'                   Descartado   18535
 51600542  'teste'                        Descartado   18535
```

E `ChangeFunnel` recusa lead descartado (tentativa #3). Então mesmo a rota de contorno
—  tirar do 18535 e trazer de volta em `Follow 1`, que seria um uso **documentado** do
`ChangeFunnel` — está bloqueada: ela exigiria um lead não descartado, e não há nenhum com
aquele telefone.

`LeadsRecover` existe no `$metadata` (`{leadId, userEmail, funnelId}`) e poderia tirar do
descarte. **Não executei**: tirar um lead do descarte o devolve ao board de trabalho de alguém,
e isso não estava autorizado neste prompt — a decisão foi "mudar estágio", não "ressuscitar
lead".

---

# 4. Resíduo: zero, verificado

**Na Exact** — os 7 leads do Álefe, depois das quatro sondagens:

```
count = 7                                  (era 7 antes)
51600542  T0 vs AGORA: campos alterados = NENHUM
updateDate de TODOS os 7 intacto:
  31485567  2026-07-09T18:31:13Z      51548604  2026-08-25T18:34:18Z
  32196408  2026-07-13T20:30:29Z      51550281  2026-08-25T20:28:06Z
  36773908  2025-06-23T13:55:24Z      51600542  2026-08-27T13:52:35Z
  48525996  2026-03-20T12:58:58Z
```

`updateDate` inalterado é a prova mais forte: a Exact o move em qualquer escrita, e nenhuma das
quatro chamadas o tocou.

**No nosso lado:**

```
 max_evento | cursor | linhas_follow      outbound desde 14:25 = 0
       4259 |   4259 |             0      eventos novos (id > 4259) = 0
```

## Critérios 6, 7 e 8

* **6 — nenhum lead fora dos dois recebeu nada.** ✅
  `SELECT COUNT(*) FROM follow_estagio_envios` = **0**, portanto zero para qualquer
  `lead_exact_id`. Zero outbound de template no período.
* **7 — restauração.** ✅ **Nada a restaurar**: nenhum estágio mudou. Os estágios originais
  ficaram registrados no §3 e nos JSONs de T0, e conferem com o estado de agora.
* **8 — allowlist intacta.** ✅ `FOLLOW_ESTAGIO_SOMENTE_TELEFONES=83988046720` segue no `.env`.
  Nada foi liberado.

## A trava de telefone funcionou

Toda escrita passou por `assert_telefone(lead_id)`, que faz GET no lead e compara a **chave
tolerante** (DDD + últimos 8). Testada contra leads reais antes de ser usada:

```
 52250054: ✅ barrado — phone1='5541984961185' (chave '4184961185') != '8388046720'
 51591580: ✅ barrado — phone1='556792894362'  (chave '6792894362') != '8388046720'
 51600542: ✅ passou  — 'teste'     Descartado
 51550281: ✅ passou  — 'zzz teste' Descartado
```

Nenhuma chamada de escrita foi feita a lead que não fosse do Álefe.

---

# 5. Fases 2 a 5 — não executadas

| fase | estado |
|---|---|
| 2 — preparação | Parcial: estágios e telefones registrados (§2 e §3); `MAX(id)` = 4259 |
| 3 — escada do 9127 | **Não executada.** O lead não existe na Exact, e não há como mudar estágio por API |
| 4 — reentrada e 9134 | **Não executada.** Mesmo motivo |
| 5 — restauração | **Nada a restaurar** (§4) |

Nenhum `skipped`, nenhum `falhou`, nenhum timeout de poll — porque nenhuma linha chegou a ser
criada. Os quatro erros HTTP estão no §3, com o corpo da resposta.

---

# 6. Recomendação

**Não está pronto para liberar, e o que falta não é código: é um lead que se possa arrastar.**
O teste ponta a ponta tem de ser manual, e o caminho mais limpo é o Álefe **preencher o
formulário da landing page com o telefone dele** — isso cria um lead novo em `Entrada` do funil
18535 pelo caminho real, não descartado — e depois arrastá-lo pelos nove estágios, um por vez,
esperando cada template.

Por que a LP e não recuperar um dos 7 descartados: o lead novo nasce limpo, pelo caminho que a
produção usa todo dia, sem tirar nada do descarte e sem tocar no board de ninguém. E dá para
conferir a variável `{{curso}}` escolhendo o curso no formulário.

Enquanto isso, o que já está provado e o que não está:

| | |
|---|---|
| ✅ provado | o job sobe, lê o cursor, carrega os nove estágios e roda a 60s (11 ciclos limpos) |
| ✅ provado | o gate fechado não toca no banco; a allowlist casa nas 4 grafias |
| ✅ provado | mapa, parâmetros, `mes`, idempotência, payload, desfechos — 232 asserções |
| ❌ não provado | **o caminho completo em produção: evento real → linha → envio → entrega** |

Duas coisas para decidir, e as duas são suas:

1. **O teste manual** — o Álefe cria o lead pela LP e arrasta. ~9 arrastos, ~11 min de espera
   entre cada um (latência do sync: p50 4,8 min, p90 9,5 min). Eu acompanho pelo banco e pelo
   log e reporto cada degrau.
2. **Esperar segunda-feira** — hoje é domingo, e o 18535 tem 54 eventos de domingo contra 530
   de segunda em 30 dias. Com a allowlist ligada, nenhum lead real recebe nada; o que se ganha
   esperando é ver o contador `fora_da_allowlist` subir, provando que o filtro está de fato
   descartando os eventos reais. Isso valida metade do caminho (leitura de evento) sem enviar
   nada a ninguém.

Minha sugestão: **(2) primeiro, de graça, e (1) quando o Álefe tiver 10 minutos.** O (2) não
custa nada e fecha a única lacuna que não depende dele — se na segunda o log mostrar
`fora_da_allowlist: N` com N > 0, o gatilho está provado em produção e só o envio fica
pendente.

---

# 7. Correções que este teste obriga

1. **`RECON_FOLLOW_AUTOMATICO_20260927.md` §5.2 está errado.** Diz 9 leads na Exact com o
   telefone do Álefe; são 7. `9127` e `9134` foram lidos do espelho e estão apagados na Exact
   desde 18/08. A recomendação de usar esses dois, que viajou para o relatório da sprint e para
   este roteiro, é inválida.
2. **`$metadata` não descreve a superfície de escrita da Exact.** 107 EntitySets declarados,
   e `LeadsUpdate`/`SkipSteps` — os dois que declaram propriedade de estágio — dão 404. Quem
   for procurar endpoint novo na Exact tem de confirmar a rota, não o DTO.
3. **A pergunta de 24/08 segue aberta e agora está mais fechada por eliminação:** não há
   endpoint conhecido de movimentação de estágio intra-funil. As saídas continuam sendo as duas
   que aquele documento listou — perguntar ao suporte da Exact, ou observar no DevTools a
   chamada que a própria tela dela faz ao arrastar um card. A segunda é barata e o Álefe pode
   fazê-la no mesmo arrasto do teste manual: abrir o DevTools, arrastar, e copiar a requisição.

---

*Teste interrompido na Fase 1 por impossibilidade externa, como o prompt previu. Quatro
chamadas de escrita tentadas, todas recusadas pela Exact com efeito zero. Nenhum lead alterado,
nenhuma mensagem enviada, allowlist intacta.*
