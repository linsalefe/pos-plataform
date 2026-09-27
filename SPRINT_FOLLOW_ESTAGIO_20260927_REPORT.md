# SPRINT_FOLLOW_ESTAGIO_20260927 — relatório

Branch **`follow-estagio`**, 5 commits, pushado. Base: `main` em `ee5c804`.

```
5412396 follow: testes do mapa, idempotência, allowlist e opt-out (não executados)
bdcac40 disparo: pula lead com error_code 131050 (opt-out registrado pela Meta)
86ea495 follow: job por estágio com gate, allowlist de teste, 2s entre envios
88c88e4 follow: tabelas follow_estagio_envios e cursor — migração NÃO executada
783995a follow: mapa estágio->template por id da Exact e montagem de parâmetros
```

```
 backend/app/exact_routes.py        |  12 +-
 backend/app/follow_estagio.py      | 669 ++++++++++++++++
 backend/app/follow_estagio_mapa.py | 311 +++++++++++
 backend/app/higiene_disparo.py     | 100 ++++-
 backend/app/main.py                |  16 +
 backend/app/models.py              | 174 +++++++
 backend/follow_estagios.json       |  14 +
 backend/migrate_follow_estagio.py  | 221 +++++++++
 backend/test_follow_estagio.py     | 770 +++++++++++++++++++++++++
 backend/test_higiene_disparo.py    |  88 ++++-
 10 files changed, 2356 insertions(+), 19 deletions(-)
```

**Nada foi executado nem enviado.** Provado no fim deste documento.

---

# Os critérios de aceite, um por um

### 1. Evento gera UMA linha; reentrada não gera nem linha nem envio ✅

`app/follow_estagio.py::_enfileirar` faz um único INSERT com
`ON CONFLICT (lead_exact_id, estagio_id) DO NOTHING RETURNING id`. `RETURNING` vazio é como o
código sabe que já existia — devolve o rótulo `reentrada`, não grava e não envia.

A UNIQUE é `ux_follow_estagio_lead_estagio ON follow_estagio_envios (lead_exact_id,
estagio_id)`, **não parcial** (`migrate_follow_estagio.py`). A de `nat_scheduled_actions` é
`WHERE status='pendente'` e ali está certo; aqui a linha executada tem de continuar
bloqueando, senão "para sempre" dura só até o envio.

Não há `SELECT` antes do INSERT de propósito: entre um SELECT e um INSERT cabe outro processo,
e quem garante a regra tem de ser o banco.

### 2. Outro funil é ignorado **na query** ✅

```sql
WHERE e.id > :cursor
  AND e.funnel_id = :funil
  AND e.stage_para = ANY(:estagios)
ORDER BY e.id LIMIT :limite
```

`:funil` vem de `funil_alvo()` (18535, do JSON) e `:estagios` de `estagios_do_mapa()` — os nove
nomes byte a byte. Comparação **exata**: sem `ILIKE`, sem `trim()`. Intercâmbio (703 entradas
em 30 dias), `Follow 2 - Vi` do 20647 e `Ultimo follow (Descarte) ` não entram, e nem chegam a
ser lidos.

`estagio_para()` reconfere o funil mesmo assim — não é paranoia: quatro funis têm etapa
chamada `Follow 1`, e um chamador futuro que esqueça o `WHERE` descobriria isso no WhatsApp do
lead.

### 3. Gate fechado não lê eventos nem envia; loga uma linha por ciclo ✅ (verificado)

O gate é a primeira coisa de `processar()`, antes de qualquer `async_session()`.
Executado nesta sessão com um `async_session` que **estoura se for chamado**:

```
_ligado(): False
ℹ️  follow por estágio DESLIGADO (FOLLOW_ESTAGIO_ENABLED != true) — nenhum evento é lido e nada é enviado.
processar(): {'desligado': True}
```

Nenhuma sessão aberta. A linha sai em **toda** passada de propósito: é a única prova, no
journald, de que o gate está fechado por escolha e não porque o job morreu (mesma decisão do
`rd_sender`).

Aceita `true`/`TRUE`/` true `/`1`/`sim`/`yes`. Tudo o mais — inclusive vazio, `tru`, `truee`,
`nao` — é **desligado**. Falha fechada: variável escrita errada resulta em nenhum follow, não
em 1 255 templates saindo.

### 4. Allowlist pela chave tolerante; evento de fora é consumido **sem criar linha** ✅ (verificado)

```
'83988046720'      -> {'8388046720'}
'5583988046720'    -> {'8388046720'}
'558388046720'     -> {'8388046720'}
'8388046720'       -> {'8388046720'}
'83988046720,abc'  -> {'8388046720'}     (o lixo é descartado)
''  /  '  '  / 'abc' -> frozenset()      (vazia = todos entram)
```

As quatro grafias do número do Álefe colapsam na mesma chave. Chave ilegível (`''`) é
**descartada** da allowlist: `''` casa com `''`, e uma entrada torta no `.env` ligaria o follow
para todo lead de telefone ilegível — o oposto de uma allowlist.

**Por que não pode virar `skipped`** (o ponto da sprint, e vale repetir): a UNIQUE não é
parcial, então uma linha `skipped` bloqueia aquele par **para sempre**. Se os eventos de fora
da allowlist virassem `skipped`, o dia em que o Álefe apagasse a variável do `.env`, todo lead
que tivesse passado por um estágio durante o teste ficaria permanentemente invisível ao follow
real — e de forma silenciosa, porque a linha existe e diz "skipped". O evento é apenas
consumido: o cursor avança e nada é gravado.

O log desse caso é silencioso por linha e contado no resumo (`fora_da_allowlist: N`): com a
allowlist ligada isso é o caso **normal**, e um print por evento afogaria o journald justamente
quando alguém está olhando o teste.

### 5. Envio por `bulk_send_template`, herdando tudo; resultado copiado para a linha ✅

O payload, e a assinatura usada:

```python
# a chamada — dois posicionais, exatamente como main.py:238
resultado = await bulk_send_template(payload, db)
```

Exemplo real para o **Follow 1** (lead 9127, o do Álefe em `PosMulheridades`):

```json
{
  "template_name": "mensagem_flow",
  "language": "pt_BR",
  "channel_id": 1,
  "lead_ids": [9127],
  "param_mappings": [
    {"type": "lead_name"},
    {"type": "sdr_name"},
    {"type": "lead_course"}
  ],
  "origem_envio": "campanha"
}
```

E para o **` Follows 7`**, o do mês (gerado nesta sessão, com `agora = 27/09`):

```json
{
  "template_name": "mensagem_follow7",
  "language": "pt_BR",
  "channel_id": 1,
  "lead_ids": [9127],
  "param_mappings": [
    {"type": "lead_name"},
    {"type": "fixed_text", "value": "Setembro"}
  ],
  "origem_envio": "campanha"
}
```

Herdado de graça, sem uma linha no módulo novo: trava da boas-vindas, **recusa de 30 dias**,
**`opt_out_meta`**, **`nat_ativa`**, canonização das duas grafias do telefone contra o eco da
Meta, criação do `Contact`, vínculo do SDR, `Message` com `template_name` e texto renderizado,
silenciamento do agente na thread, `disparo_skip` durável.

`_desfecho_do_bulk` traduz o retorno (verificado nesta sessão contra a forma real de
`exact_routes.py:647-650`):

| retorno do bulk | linha |
|---|---|
| `sent=1` | `enviado` + `enviado_em` |
| `skipped=[{regra:'recusa', …}]` | `skipped`, motivo `"recusa: pediu para parar"` |
| `skipped=[{regra:'opt_out_meta', …}]` | `skipped`, motivo `"opt_out_meta: 131050"` |
| `skipped=[{regra:'nat_ativa', …}]` | `skipped`, motivo `"nat_ativa: conversa ativa"` |
| `failed=1, errors=[…]` | `falhou`, motivo com o erro da Meta |
| exceção | `falhou`, motivo `"TipoDoErro: mensagem"` |

O retorno inteiro vai para `resposta` em JSON (truncado em 2 000 chars).

### 6. Rajada em sequência com `asyncio.sleep(2)`, todos na mesma passada, sem teto ✅

`ESPERA_ENTRE_ENVIOS_SEGUNDOS = 2`, no laço de `drenar`, **depois** do commit de cada linha
(dormir com escrita pendente seguraria a transação por 2 s por lead sem necessidade) e não
depois do último. `bulk_send_template` tem `asyncio.sleep(1)` interno por lead
(`exact_routes.py:601`), então o intervalo real é ~3 s.

Sem adiamento e sem janela de horário. `MAX_POR_CICLO = 100` existe e cobre com folga a maior
rajada medida (45 leads numa passada, 18/09), mas não é teto de negócio — é onde um teto
nasceria se a nota do número cair.

### 7. Parâmetros conforme o mapa ✅ (verificado)

```
129985 'Follow 1'     mensagem_flow      -> [lead_name, sdr_name, lead_course]
129984 'Follow 2'     mensagens_flows2   -> [lead_name, lead_course]
129983 'Follow 3'     mensagem_follow3   -> [lead_name, lead_course]
129955 'Follow 4'     mensagem_follow4   -> [lead_name]
129967 'Follows 5'    mensagem_follow5   -> [lead_name, lead_course]
174517 'Follows 6'    mansagem_follows6  -> [lead_name, lead_course]
174516 ' Follows 7'   mensagem_follow7   -> [lead_name, fixed_text='Setembro']
174515 'Follows 8'    mensagem_follow8   -> [lead_name, lead_course]
174514 ' Follows 9'   mensagem_follow9   -> [lead_name]
```

* **`nome`** → `lead_name`, que a rota resolve como `lead.name.split()[0]`, fallback
  `"Aluno(a)"`. Mesma regra do bulk, como o critério pede.
* **`sdr`** → `sdr_name` (o **dono** do lead na Exact), não `sdr_logado`. Ausente ⇒ `skipped`
  `sem_sdr`, checado **antes** de qualquer chamada. Hoje os 4 125 leads do 18535 têm
  `sdr_name` (0 nulos): é trava para o caso que ainda não aconteceu.
* **`curso`** → `lead_course` → `resolve_course_name(sub_source, db)`.
* **`mes`** → `fixed_text` com `MESES[mes_sp - 1]`, lista literal de doze nomes em português.
  Verificado nos doze meses, com `Março` acentuado, e nos dois casos de borda de fuso:
  naive `01/10 00:30` → **Outubro**; aware `01/10 02:00 UTC` (= 30/09 23:00 SP) → **Setembro**.

Não há resolução duplicada: `nome`, `curso` e `sdr` são resolvidos pela **rota**, para não
haver duas verdades sobre o nome do curso. Só `mes` é resolvido no módulo, porque a rota não
tem o conceito.

### 8. `por_que_pular` lê `messages.error_code`: `131050` pula, `131049` não ✅

Regra **(d) `opt_out_meta`** em `app/higiene_disparo.py`:

```python
CODIGO_OPT_OUT_META = 131050
CODIGOS_OPT_OUT_META = (131050,)
```

`_opt_out_meta(variantes, db)` busca `direction='outbound'` **sem corte de data** — o opt-out
da Meta não expira sozinho, e reabri-lo depois de 30 dias seria decidir por cima da pessoa.
Roda **depois** da recusa: as duas dizem "pediu para parar", mas a recusa traz a **frase**, que
é mais acionável que um código.

`131049` fica de fora, e é o achado: 17 casos nos mesmos 30 dias (17× mais que o `131050`), mas
é a Meta **limitando a frequência**, não o destinatário escolhendo sair — o mesmo lead volta a
receber no dia seguinte. Tratá-lo como opt-out apagaria de todas as campanhas gente que nunca
pediu para sair. `131026` (27 casos) e `131047` (9) também ficam fora.

Vale em todos os modos, inclusive individual, porque quem aperta enviar na tela de Automações
está olhando a lista da Exact — o opt-out não está ali.

**A rota não mudou de comportamento.** `regra` já viajava cru de `por_que_pular` para
`pulados`, `disparo_skip.regra` (varchar(40), cabe) e `skipped_por_regra`. Só o comentário que
dizia *"a recusa é a única regra que fala de um pedido explícito"* foi corrigido, porque deixou
de ser verdade.

Custo: uma consulta a mais por lead, barata pelo **mesmo** índice que a recusa já usa
(`ix_messages_contact_wa_id`) — o filtro por contato vem primeiro. Não há índice em
`error_code`, e nem precisa.

### 9. Migração e o UPDATE de `nat_config` **não executados** ✅ (provado)

```
$ SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'follow_estagio%';
(0 rows)

$ SELECT id, follow_enabled, follow_template, updated_at FROM nat_config;
 id | follow_enabled | follow_template |         updated_at
----+----------------+-----------------+----------------------------
  1 | t              | follow_up       | 2026-09-01 19:19:15.372665
```

`follow_enabled` segue `true` e `updated_at` segue 01/09 — `nat_config` não foi tocado.

### 10. Testes escritos, não executados; `py_compile` ok ✅

```
$ venv/bin/python -m py_compile app/follow_estagio_mapa.py app/follow_estagio.py \
    app/models.py app/main.py app/higiene_disparo.py app/exact_routes.py \
    migrate_follow_estagio.py test_follow_estagio.py test_higiene_disparo.py
TODOS OK
```

### 11. Nenhuma mensagem enviada ✅ (provado)

```
$ SELECT count(*) FROM messages WHERE direction='outbound' AND created_at >= '2026-09-27 12:40';
 0
$ SELECT count(*) FROM disparo_skip WHERE quando >= '2026-09-27 09:40';
 0
```

O backend em produção continua rodando `main` (`ee5c804`) — a branch não foi mergeada nem
implantada.

---

# O SELECT que prova os nove nomes

```sql
SELECT stage_para AS nome_cru, '['||stage_para||']' AS entre_colchetes,
       length(stage_para) AS len, count(*) AS entradas
FROM exact_stage_events
WHERE funnel_id = 18535
  AND observado_em >= now() - interval '30 days'
  AND stage_para ~* 'follow'
GROUP BY 1 ORDER BY 1;
```

```
  nome_cru  | entre_colchetes | len | entradas
------------+-----------------+-----+----------
  Follows 7 | [ Follows 7]    |  10 |      102
  Follows 9 | [ Follows 9]    |  10 |       66
 Follow 1   | [Follow 1]      |   8 |      201
 Follow 2   | [Follow 2]      |   8 |      186
 Follow 3   | [Follow 3]      |   8 |      172
 Follow 4   | [Follow 4]      |   8 |      163
 Follows 5  | [Follows 5]     |   9 |      150
 Follows 6  | [Follows 6]     |   9 |      125
 Follows 8  | [Follows 8]     |   9 |       83
(9 rows)
```

Nove linhas, nove nomes, e os comprimentos **8, 8, 8, 8, 9, 9, 10, 9, 10** conferem com o JSON.
O `[…]` é o que torna o espaço à esquerda visível. Este SELECT está no teste
(`test_follow_estagio.py` §1b), como asserção de conjunto nos dois sentidos: nenhum nome do
banco fora do mapa, nenhum nome do mapa fantasma.

---

# CONTRADIZ o prompt

### 1. `exact_stage_events` **não guarda o id do estágio** — o casamento é pelo nome

O prompt previu isso ("Se `exact_stage_events` não guarda o id do estágio…"), e é o caso: a
tabela tem `stage_de` e `stage_para`, dois `varchar(50)` com o **nome**
(`app/models.py:893`; INSERT em `exact_spotter.py:469`). A Exact devolve `lead["stage"]` como
string e o sync grava a string.

O JSON continua chaveado pelo id — é a chave de **registro**, o que um humano confere contra
`/v3/stages`, e o que vai para `follow_estagio_envios.estagio_id` (estável a rename). O
casamento em tempo de execução é por `_POR_NOME`, um índice **construído** no carregamento,
nunca digitado. `carregar()` recusa dois ids com o mesmo nome, porque a busca ficaria ambígua.

Consequência que fica registrada: **se alguém renomear ` Follows 7` na Exact, o follow daquele
degrau para de sair em silêncio.** O teste §1b contra o banco é a única defesa.

### 2. A chave do payload é **`param_mappings`**, não `mappings`

O prompt diz `montar_mappings(entrada, lead) -> payload.mappings` e "o `payload` de exemplo".
A rota lê **`param_mappings`** (`exact_routes.py:316`).

Isto não é detalhe de nomenclatura: mandar `mappings` **não daria erro**. A rota cairia no modo
legado (`parameters`), que monta `[nome, curso]` **por posição** — exatamente o chute que põe o
nome do curso no `{{2}}` do `mensagem_follow7`, onde vai o mês. Silencioso e errado, que é o
pior par. Há teste explícito: `"param_mappings" in payload` e `"mappings" not in payload`.

### 3. `montar_mappings` devolve **uma tupla**, não só a lista

`(param_mappings, motivo)`. O critério 7 exige um `skipped`/`sem_sdr` quando o lead não tem
SDR, e esse motivo tem de subir para a linha do banco. Devolver só a lista obrigaria o chamador
a repetir a checagem — duas regras para a mesma coisa, e a que ficasse para trás mandaria
*"Ola Marina, é o Equipe CENAT do CENAT"* para o lead (é o fallback de `sdr_name` na rota).

### 4. A lista de pulos do retorno chama-se **`skipped`**, não `pulados`

**Este foi um bug meu, encontrado escrevendo o teste.** Eu tinha escrito
`resultado.get("pulados")`. `pulados` é o nome da **variável local** dentro da rota; a chave do
dicionário devolvido é `skipped` (`exact_routes.py:650`).

Ler a chave errada não daria erro: daria `[]`, e **todo** pulo — recusa, opt-out, conversa ativa
— cairia no ramo de `falhou` com o motivo genérico *"sem `sent` e sem erro no retorno"*. A linha
diria "falhou" para um lead que foi **corretamente poupado**, e ninguém investigaria um `falhou`
de motivo genérico. Corrigido em `86ea495`/`5412396`, com `skipped_total` como cinto de
segurança e um teste para cada metade.

### 5. `test_higiene_disparo.py` **precisou mudar**, e a Fase 5 não previa isso

A sprint lista só `test_follow_estagio.py`. Mas a regra (d) acrescenta uma **segunda** consulta
a `por_que_pular`, e o dublê de `pergunta()` naquele arquivo respondia **por omissão** a partir
da segunda chamada — `MagicMock().scalar_one_or_none()` devolve um mock **truthy**, não `None`.
Sem a correção, **todo caso de "sem recusa" viraria `opt_out_meta`** e o arquivo ficaria
vermelho de propósito, o que não é aceitável.

Corrigido: `opt_out` nasce `None` **explicitamente** (com comentário dizendo que um dublê que
responde por omissão mente para o lado perigoso), as duas contagens de `"só UMA consulta"`
viraram 2, e foi acrescentada a seção 8 com `131050` vs `131049`. A seção nova ficou **antes**
do bloco de resumo — appendada no fim, ela rodaria depois do `raise SystemExit`.

### 6. Sobre "parâmetros por template exatamente conforme o mapa"

Cumprido, com uma nota: `primeiro_nome()` em `follow_estagio_mapa.py` é **espelho** da regra do
bulk (`nome.split()[0]`, sem capitalizar), e **não** é `app/nomes.primeiro_nome`, que é melhor
(pula token sem letra, capitaliza `maria-clara` e `d'ávila`). O critério pede "mesma regra do
bulk", e um espelho que **melhora** a regra mente: o log diria `"Marina"` e o lead leria
`"marina"`. A função existe só para log e teste — o envio usa o tipo `lead_name` e é a rota que
resolve, então as duas não podem divergir. Unificar é assunto de outra sprint: mexer em
`lead_name` muda o `{{1}}` de todo disparo manual.

---

# Decisões de implementação que o prompt deixou abertas

1. **Cursor ausente é falha fechada, não zero.** `create_tables.py` existe e cria as tabelas
   **sem** a linha do cursor (ele não é chamado no boot, mas é um script que alguém roda).
   `_cursor()` devolve `None` nesse caso e `ler_eventos` **recusa processar**, com log mandando
   rodar a migração. Tratar como 0 varreria os 1 255 eventos de histórico — e o gate fechado
   não protege disso, só adia para o dia em que abrir.

2. **`MAX_EVENTOS_POR_CICLO = 400`.** Não é teto de rajada (a sprint decidiu não ter): é a
   trava contra o acidente de alguém zerar o cursor à mão. Com 400, um cursor zerado leva 4
   passadas para chegar ao presente em vez de uma — 4 minutos é tempo de alguém ver no journald
   e fechar o gate.

3. **`LEFT JOIN exact_leads`, não `INNER`.** Um evento de lead que já não está no espelho (há
   10 assim: 9 901 no espelho contra 9 891 na Exact) tem de ser **consumido**, não ficar preso
   bloqueando os seguintes para sempre. Sai com `lead_ausente` e nada é gravado.

4. **`sem_sdr`/`sem_telefone` gravam `skipped`; a allowlist não.** A diferença é de fato: na
   allowlist o lead está fora do **teste** (condição nossa, temporária, e bloquear o par
   seria um dano permanente); aqui falta dado **dele**, que só muda se alguém consertar o
   cadastro — reenviar em loop um follow que não pode ser montado seria pior.

5. **Um commit por linha em `drenar`, lote inteiro numa transação em `ler_eventos`.** No envio,
   uma mensagem já entregue ao lead nunca pode ficar com a linha `pendente`: se o processo
   morrer na rajada, o que saiu está marcado. Na leitura, o cursor só avança se o lote inteiro
   entrou, e o pior caso de um rollback é um `ON CONFLICT DO NOTHING` a mais.

6. **`falhou` sem retentativa.** A sprint não pediu retry, e um follow reenviado horas depois
   do arrasto do card já não é o follow daquele momento. O motivo fica gravado, que é o que
   permite decidir se vale um retry numa próxima sprint.

---

# O que o `.env` precisa

Nada para o código subir. As duas variáveis são **opcionais** e ausentes = desligado:

```bash
# Gate. Ausente, vazio ou qualquer coisa que não seja true/1/sim/yes = DESLIGADO.
FOLLOW_ESTAGIO_ENABLED=true

# Modo de teste. Lista por vírgula, em qualquer grafia (casa pela chave DDD+8 dígitos).
# Vazio ou ausente = TODOS os leads do 18535 entram.
FOLLOW_ESTAGIO_SOMENTE_TELEFONES=83988046720

# Opcional. Só para apontar o mapa para outro arquivo (teste). Padrão:
# backend/follow_estagios.json
# FOLLOW_ESTAGIOS_PATH=
```

No boot o journald passa a imprimir:

```
✅ Follow por estágio da Exact (checa a cada 60s, envio DESLIGADO)
✅ Follow por estágio da Exact (checa a cada 60s, envio LIGADO, MODO DE TESTE com 1 telefone(s))
```

---

# CHECKPOINT — o que falta, na ordem

Nada abaixo foi feito.

```bash
# 0. RODAR OS TESTES. Eles não foram executados (critério 10) e é o primeiro passo.
cd /home/ubuntu/pos-plataform/backend
venv/bin/python test_follow_estagio.py
venv/bin/python test_higiene_disparo.py      # mudou nesta sprint — ver CONTRADIZ #5

# 1. Migração. Cria as duas tabelas e põe o cursor em MAX(id) de exact_stage_events.
venv/bin/python migrate_follow_estagio.py

# 2. .env
#    FOLLOW_ESTAGIO_ENABLED=true
#    FOLLOW_ESTAGIO_SOMENTE_TELEFONES=83988046720

# 3. Desligar o follow_20h do agente (para não haver duas réguas quando ele religar)
psql ... -c "UPDATE nat_config SET follow_enabled = false WHERE id = 1;"

# 4. Merge e restart
cd .. && git checkout main && git merge --no-ff follow-estagio && git push
sudo systemctl restart cenat-backend && sudo journalctl -u cenat-backend -n 50 --no-pager
```

**Ordem importa:** a migração antes do restart. Se o backend subir com o gate aberto e sem as
tabelas, o job recusa processar e loga — não quebra —, mas os eventos daquele intervalo ficam
abaixo do cursor quando ele nascer, e aqueles follows não saem.

---

# Roteiro de teste (o que conferir em cada passo)

Com `FOLLOW_ESTAGIO_SOMENTE_TELEFONES=83988046720`, os dois leads do Álefe em `Agendados`:

| `lead_ids` | `exact_id` | `sub_source` | curso que vai renderizar |
|---:|---:|---|---|
| 9127 | 51438018 | `PosMulheridades` | Saúde Mental e Mulheridades |
| 9134 | 51438436 | `Pos Saude do Trabalhador` | Saúde Mental do Trabalhador |

1. **`Agendados → Follow 1`.** Em até ~11 min (latência p50 4,8 min / p90 9,5 min do sync)
   chega `mensagem_flow`: *"Ola Álefe, é o Thobias do CENAT ✨ … Pós Graduação Saúde Mental e
   Mulheridades"*. Conferir:
   ```sql
   SELECT id, estagio_id, estagio_nome, template, status, motivo, enviado_em
     FROM follow_estagio_envios ORDER BY id DESC LIMIT 5;
   ```
2. **Follow 2 … ` Follows 9`**, um por vez, esperando a mensagem de cada. No ` Follows 7`,
   conferir que o texto diz **"neste mês de Setembro"** (ou Outubro, conforme o dia) e **não** o
   nome do curso — é o defeito que esta sprint existe para não repetir.
3. **Reentrada:** `Follows 9 → Follows 8 → Follows 9`. **Nada** deve chegar e nenhuma linha
   nova deve aparecer. No log: `↩️ follow: lead … já tem linha para ' Follows 9' — reentrada`.
4. **Segundo lead (9134):** `Agendados → Follows 5` direto. Só o follow 5 chega — não há
   varredura de degraus anteriores, porque o gatilho é o evento.
5. **Liberar:** apagar `FOLLOW_ESTAGIO_SOMENTE_TELEFONES` do `.env` e reiniciar. **Avisar o
   comercial antes**: a partir daí todo arrasto de card no 18535 dispara template, ~42 por dia,
   inclusive fora do horário comercial e em rajadas de até 45.

Duas coisas para olhar no journald durante o teste:

* `⏱️ follow por estágio: {...}` a cada minuto, com `fora_da_allowlist: N` — é o número de
  leads reais que passaram por um estágio e **não** receberam por causa do modo de teste. Esses
  follows não saem e não voltam.
* Se o Álefe **responder** algo que case `PADRAO_RECUSA`, todos os degraus seguintes viram
  `skipped` por 30 dias, com a linha gravada. É o comportamento certo, mas para o teste
  significa parar e usar outro lead.

---

# Observações que ficaram de fora (como o prompt pediu)

* Endpoint/tela de status do follow (contagem por estágio e status, últimos `skipped`).
* Nomes dos templates na Meta (`mansagem_follows6`, `mensagens_flows2`) e o texto dos degraus
  3/4/5 — o áudio prometido no 4 e cobrado no 5 não é anexado por nenhum dos dois: o Hub não
  sabe montar component `header`, e o áudio vive nos `f4_audio<curso>`. Assunto do comercial.
* 8 leads em estágio de follow com `sub_source` sem alias renderizam curso torto
  (`BoasPraticasEAD`, `psiclinicaaplicada`) — 6% dos 150. Alias em `course_aliases` resolve.
* Gatilho por `GET /v3/LeadStages` (relógio da Exact, `cycle`, sem perda do estágio do meio) se
  a perda de 1,5% passar a incomodar.
* 10 leads apagados na Exact que ficam no espelho para sempre.
* `primeiro_nome` do bulk vs `app/nomes.primeiro_nome` — ver CONTRADIZ #6.

---

*Sprint somente-código. Nenhuma migração rodada, nenhum `nat_config` alterado, nenhuma
mensagem enviada, nenhum deploy.*
