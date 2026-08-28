# FIX — disparo em massa caindo em 500 (`bulk-send-template`)

**28/08/2026.** Relato do time: *"está acusando erro ao enviar o template"*. Confirmado,
diagnosticado, corrigido e no ar (restart às **14:04:26 UTC**, PID 1627829).

Aberto no meio do `RECON_DESEMPENHO_AGENTE_20260828` (somente leitura), que foi
interrompido para isto e será retomado. Este documento cobre só o incidente.

---

## 1. O sintoma, medido

```
$ journalctl -u cenat-backend.service --since "2026-08-28 00:00" \
    | grep -c 'bulk-send-template HTTP/1.0" 500'
5
$ ... | grep -c 'bulk-send-template HTTP/1.0" 200'
1
```

Cinco 500 em ~35 min (13:16:57, 13:17:05, 13:17:55, 13:26:23, 13:51:01 UTC —
10:16 a 10:51 SP). Todos depois do deploy de 27/08 17:04 UTC; nenhum antes.

A exceção que sobe até o ASGI é `PendingRollbackError`, mas ela é consequência. A
original está na mesma linha do log:

```
ForeignKeyViolationError: insert or update on table "messages"
violates foreign key constraint "messages_contact_wa_id_fkey"
```

---

## 2. Causa raiz — meia correção do commit `05cea3f`

O commit da canonização (27/08 14:11 UTC, no ar desde 17:04) lista, na própria mensagem,
os 7 pontos de escrita que canonizou — incluindo `exact_routes.py:367 disparo em massa`.
Em `exact_routes.py` **só metade entrou**: a busca virou tolerante, o alinhamento da chave
de gravação não veio junto.

Lado a lado, o mesmo commit, dois arquivos:

```python
# routes.py:261 — completo
wa_id = await canonizar(result.get("contacts", [{}])[0].get("wa_id", req.to), db)
contact = await contato_existente(wa_id, db)

# exact_routes.py:367 — sem o alinhamento
wa_id = result.get("contacts", [{}])[0].get("wa_id", phone)   # cru da Meta
contact = await contato_existente(wa_id, db)                   # acha pela OUTRA grafia
if not contact:                                                # logo NÃO cria
    db.add(Contact(wa_id=wa_id, ...))
...
contact_wa_id=wa_id,                                           # :391 FK -> linha inexistente
```

O mecanismo é exatamente o que a mensagem do `05cea3f` descreve ao justificar
`main.py:557` — *"mesma grafia do contato resolvido, senão a FK aponta para contato que a
canonização decidiu não criar"*. O risco foi previsto, tratado em `main.py` e `routes.py`,
e passou batido aqui.

**Meia correção é pior que nenhuma:** a busca exata anterior não achava nada, criava o
contato, e a FK fechava. A busca tolerante acha, decide não criar — corretamente — e
deixa a mensagem apontando para o vazio.

Confirmado no banco nos dois números que falharam. Em ambos existe **só** a grafia de 13
dígitos, criada pelo agente a partir do telefone da Exact, e a Meta devolve a de 12:

| `contacts.wa_id` (existe) | criado em | eco da Meta (usado na FK) |
|---|---|---|
| `5591982668801` | 27/08 21:02 | `559182668801` |
| `5582999810488` | 28/08 12:00 | `558299810488` |

---

## 3. Por que UM lead derruba o lote inteiro

O `msg` ficava pendente na sessão sem flush. Quem flusha primeiro é o
`begin_nested()` do `_silenciar_agente_apos_envio_manual` (`exact_routes.py:409`), que
arrasta os objetos pendentes da transação de fora. A violação estoura lá dentro, o
`except` largo de `routes.py:244` engole (*"O agente segue ativo"*), e a sessão volta
suja. Na volta do laço, `lead.phone1` (`:317`) é atributo expirado → tenta recarregar →
`PendingRollbackError` → 500 no lote inteiro.

**O savepoint não isola isto, e a docstring dele diz que deveria.** Ela afirma que o
`begin_nested` existe para que *"um IntegrityError não deixe a transação abortada"*. Vale
para o que o `silenciar` escreve — não para o que o chamador deixou pendente. Um savepoint
protege contra os erros de dentro dele, não contra objetos de fora que ele arrasta no
flush.

---

## 4. Impacto real

Cinco mensagens foram **aceitas pela Meta e não existem no Hub** — wamids órfãos,
cruzando o journald com `messages.wa_message_id`:

| destinatário | disparos aceitos pela Meta | linhas no banco |
|---|---:|---:|
| `559182668801` (Marcos) | **4** | 0 |
| `558299810488` (Daniela) | 1 | 0 |

Os 4 do Marcos são o mesmo template repetido: o SDR reenviava a cada erro. O ciclo é o
pior possível — **o lead recebe, o SDR vê erro, reenvia, o lead recebe de novo** — e os
leads restantes do lote nunca saem, porque o request aborta no primeiro par dividido.

Consequência de segunda ordem, visível no log: `❌ Meta recusou wamid... [mensagem não
encontrada no banco]`. O callback de status não acha a linha porque ela nunca foi gravada.

---

## 5. O que mudou

### (a) `exact_routes.py` — a chave de gravação passa a ser a do contato resolvido

```python
eco_meta = result.get("contacts", [{}])[0].get("wa_id", phone)
contact = await contato_existente(eco_meta, db)
wa_id = contact.wa_id if contact is not None else eco_meta
```

`contato_existente` + a grafia dele é, literalmente, o corpo de `canonizar`. Resolvido
assim numa consulta só — chamar `canonizar` aqui repetiria a busca da linha seguinte, e
foi por isso que não segui o formato de `routes.py`.

### (b) `exact_routes.py` — `await db.flush()` logo após o `db.add(msg)`

Dentro do `try` do lead. A falha de um lead passa a ser contabilizada como falha **daquele
lead** (`failed`/`errors`) e o laço segue — que é o contrato que o próprio laço anuncia.
Sem isto, qualquer erro de escrita futuro volta a envenenar o lote pelo mesmo caminho.

### (c) `exact_spotter.py` — o mesmo defeito, latente

`contato_existente(phone)` + `Message(contact_wa_id=phone)`, a 30 linhas de distância.
Não estava disparando porque a boas-vindas automática está desligada desde 26/07 —
**religar sem isto traria o mesmo 500.** Agora grava em `wa_gravacao`, também em
`AIConversationSummary`. O `to=phone` do envio ficou intacto: canonizar decide chave de
gravação, nunca destinatário.

### Validação contra os números reais (leitura, sem envio)

```
eco da Meta 559182668801   -> grava contact_wa_id=5591982668801  (contato ACHADO na outra grafia)
eco da Meta 558299810488   -> grava contact_wa_id=5582999810488  (contato ACHADO na outra grafia)
```

Suítes: `test_welcome_guardrail` 17/17, `test_threads_divididas`, `test_qualificacao`,
`test_nat_flow` 13/13, `test_espontaneo`, `test_gatilho_abertura` 8/8, `test_nat_guard`
9/9, `test_observabilidade_envio`, `test_nat_sprint3`, `test_nat_recuperacao`,
`test_identidade_abertura`, `test_concluir_confirma`, `test_agente_parado`,
`test_vigia_agente_mudo`, `test_rede_ultima_instancia` — todas verdes. O dublê do
`test_welcome_guardrail` **não** precisou de ajuste: a contagem de `execute` não mudou.

---

## 6. Achado colateral — o dublê estava cego, e escondia uma regressão

`test_risco3_abertura` estava **vermelho no HEAD limpo** (confirmado com `git stash`),
tendo sido `PASS` no sprint 4. A falha aparecia como *"NÃO criou Contact novo"*.

A causa era o dublê, não o código. Desde `05cea3f` o `_contato_ou_criar` busca com
`Contact.wa_id.in_(variantes)` em vez de `== wa_id`, e um `IN` expandido do SQLAlchemy não
deixa literal no `str(stmt)` — vira `IN (__[POSTCOMPILE_wa_id_1])`, com a lista inteira num
único parâmetro:

```
params -> {'wa_id_1': ['5582998307979', '558298307979']}
```

`_parametros` fazia `str(v)` disso e comparava elemento a elemento contra a lista
formatada como string. Nunca casava. **Corrigido: `_parametros` agora achata sequências.**

E aí o teste passou a reprovar o que realmente importa — ver §7.

---

## 7. ⚠️ NÃO CORRIGIDO — decisão de projeto, não minha

Com o dublê enxergando, `test_risco3_abertura` reprova o **teste 3**:
*"só existe a variante de 12 dígitos, de OUTRA PESSOA -> não a usa"*.

`FIX_RISCO3_ABERTURA_20260825.md` documenta o caso literal de produção: `558298307979`
existia em `contacts` como **Pablo Valente**, o lead era **Ronaldo Cesar**, e o porteiro
tolerante *"abriu na linha de um estranho"*. A correção de 25/08 foi tornar a abertura
**estrita**, deixando a tolerância só onde ela não escreve (`estado_de`, histórico).

`05cea3f` trocou aquilo por `contato_existente` — tolerante — em `qualificacao_fluxo.py:311`.
**A docstring logo acima da linha ainda afirma a regra antiga**, e contradiz o código que
vem abaixo dela:

> *"Então a regra passa a ser UMA: o contato da abertura é o da grafia para a qual vamos
> mandar a mensagem. (…) A tolerância continua onde ela é certa e não pode escrever nada."*

Os dois lados têm razão e se excluem:

* **RISCO 3** quer grafia exata, porque a variante do 9º dígito pode ser outra pessoa.
* **Canonização (b)** quer tolerância, porque a grafia exata cria thread dividida nova.

`telefone.py` mitiga (só gera variante quando o número local tem cara de celular), mas
não elimina — o caso Ronaldo/Pablo é justamente um local de 8 dígitos começando em 9, e o
próprio `telefone.py` marca essa faixa como ambígua.

**Não escolhi por conta própria.** É decisão de produto: aceitar thread dividida para nunca
escrever na linha de um estranho, ou o contrário. Isto está no ar desde 27/08 17:04 —
o restart de hoje não muda o risco, apenas não o aumenta.

**A suíte fica vermelha de propósito**, apontando um conflito real. Devolvê-la ao verde
sem decidir exigiria cegar o dublê de novo, que é como o problema chegou até aqui.

---

## 8. Separado — `131049` não é este bug

Duas ocorrências hoje, ambas para `559182668801`:

```
❌ Meta recusou ... code=131049 title='This message was not delivered to maintain
   healthy ecosystem engagement.'
```

Limite de engajamento da Meta para aquele destinatário. É lado deles, independente da FK,
e provavelmente agravado pelas 4 repetições do §4 — mais um motivo para o reenvio manual
não ser o caminho normal. **Não investigado além disto.**

---

## 9. Pendências que este documento deixa em aberto

1. **§7 — RISCO 3 × canonização.** Decisão de projeto. É o item de maior risco aqui.
2. **As 5 mensagens órfãs.** Foram entregues e não estão no Hub; o histórico do Marcos e
   da Daniela está incompleto e o SDR não vê que já mandou. Backfill possível (os wamids
   estão no journald), não feito — é escrita em produção.
3. **A docstring de `_silenciar_agente_apos_envio_manual`** promete um isolamento que o
   savepoint não dá (§3). O `flush` de (b) resolve no chamador; o texto segue impreciso.
4. **`RECON_DESEMPENHO_AGENTE_20260828`** interrompido no Bloco 1, a retomar.
