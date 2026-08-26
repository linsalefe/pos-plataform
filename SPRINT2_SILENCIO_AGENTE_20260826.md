# SPRINT 2 — o conserto do silêncio da NAT (26/08/2026)

Continuação de `AUDITORIA_SILENCIO_AGENTE_20260826.md` (auditoria e plano) e do Sprint 1
(commits `f19fae9` → `b25d233`). Aqui estão o P1-A, o P0-C, o P1-B, a aresta do adiamento
por teto e o checkpoint do P0-A.

**Estado em produção:** PID 1604190, subiu 26/08 **14:03:21 UTC**. Rodam `dde2fd8` (P1-A),
`86d2adc` (P0-C), `722106b` (P1-B) e `7855fc0`. O **P0-A (`fe5b1c6`) NÃO está no ar** — ele
espera o checkpoint e um restart próprio. Ver §9.

---

## 1. Commits

| Commit | Item | O que muda |
|---|---|---|
| `dde2fd8` | **P1-A** | `pool_size=20`, `max_overflow=20`, `pool_timeout=10`, `pool_pre_ping=True`, `echo=False` |
| `86d2adc` | **P0-C** | rede de última instância fora do savepoint + `test_rede_ultima_instancia.py` (26 checagens) |
| `722106b` | **P1-B** | teto por hora sai da conversa; `guard_de_despedida` novo |
| `7855fc0` | **item 4** | fala adiada não chega depois da fala nova |
| `b1e3963` | higiene | `test_risco3_abertura.py` estava vermelho antes do sprint — bomba-relógio, não regressão |
| `653f2e2` | docs | este relatório |
| `fe5b1c6` | **P0-A** | `fluxo.agendar` em `async_session()` própria — **aprovado, ainda não deployado** |

Nenhuma migração. Nenhuma escrita manual em produção. Nenhum WhatsApp enviado.

---

## 2. P1-A — o pool

### O número do Postgres, que era o checkpoint

```
max_connections                    100
superuser_reserved_connections       3   -> 97 utilizáveis
processos da app                     1   (uvicorn sem --workers, um engine, um pool)
conexões `cenat` no momento da medição 4 (todas idle)
```

`pool_size=20 + max_overflow=20` = teto de **40** conexões vindas da app, num orçamento de
97. **O `max_connections` não mandou ajustar nada** — os números aprovados passaram como
estavam.

### Before/after sob carga — medido, e com uma ressalva

O cenário pedido (repetir o bulk-send de 18:18 com polling e webhook) exigiria disparar 8
campanhas de template para leads reais. Em vez disso reproduzi o **shape** do incidente sem
enviar nada: N tarefas concorrentes segurando conexão por 3,0s — a retenção medida de um
turno do agente — contra o banco real, só `SELECT pg_sleep`.

| concorrentes | ANTES (5+10, timeout 30) | | DEPOIS (20+20, timeout 10) | |
|---|---|---|---|---|
| | falhas | parede | falhas | parede |
| 40 | 0 | 9,6s | 0 | **4,6s** |
| 100 | 0 | 27,7s | 0 | **11,2s** |
| 160 | 13 | 33,1s | 40 | 10,7s |
| 240 | 116 | 33,2s | 120 | 10,7s |

**O que isto confirma:** no regime do incidente, zero `QueuePool limit` e 2,5× menos tempo
de parede. E mostra por que 18:18 aconteceu: em n=100 a configuração antiga terminava em
27,7s contra um `pool_timeout` de 30 — **2,3 segundos de margem**. Não era um pool
folgado que teve um dia ruim; era um pool que já vivia na borda.

**A ressalva, que a tabela não deixa esconder:** acima do ponto de ruptura (n≥160) a
configuração nova falha MAIS requisições, não menos — porque `pool_timeout` caiu de 30s
para 10s. Isso é a troca escolhida de propósito: sob sobrecarga extrema o webhook desiste
em 10s e a Meta reentrega, em vez de segurar um worker por 30s para entregar a mesma
falha. Quem quiser "nunca falhar" sob 240 concorrentes precisa de mais pool, não de mais
timeout. **Não é verdade que a mudança dá "zero QueuePool limit" em qualquer carga** — ela
dá zero na carga que derrubou o sistema em 25/08.

### `echo=False`

4,0 GB de journal e 36 750 linhas suprimidas em 25/08: o excesso de log estava apagando o
log que importa. Só foi aceitável porque o P0-E (`f19fae9`) já pôs o turno do LLM numa
linha estruturada — perdemos o SQL, não a rastreabilidade do agente.

---

## 3. P0-C — a rede de última instância

O `except Exception` do roteamento fazia **uma** coisa: `print`. Não enviava, não
notificava, não marcava — e o `begin_nested` revertia junto a etapa `transferido_humano`
que o `_fallback` já tinha escrito. Foi assim que as 3 mensagens da Fabiana viraram 3
rollbacks, **zero** notificações e **zero** mensagens ao lead.

Agora, em `main.py`, `_rede_de_ultima_instancia`:

1. **sonda** a sessão do webhook (`SELECT 1`) e só reverte se ela estiver quebrada. Um
   `rollback()` incondicional — que era a proposta original — apagaria a `Message` do
   inbound que o lote acabou de gravar: o lead sumiria da tela do SDR por causa de um erro
   que não tinha nada com ele;
2. em `async_session()` **própria**, notifica o `GESTOR_USER_ID` com contato,
   `wa_message_id` e traceback;
3. marca `transferido_humano` e manda **uma** despedida — só quando existe estado ativo do
   agente. Sem estado, o inbound era do fluxo velho, e o agente aparecendo ali seria uma
   conversa que nunca foi dele. A gestão é avisada nos dois casos;
4. `try/except` final: uma rede que derruba o webhook não é rede.

**Um defeito que o teste pegou e que teria ido para produção:** `traceback.format_exc()` lê
a exceção "em voo" do `except` ambiente e devolve `NoneType: None` para quem for chamado
fora dele. Trocado por `format_exception(type, erro, erro.__traceback__)`, que formata a
partir do objeto.

### Teste — `test_rede_ultima_instancia.py`

O caminho de falha pedido pela auditoria (`raise RuntimeError` em `_fatos`) roda como
exceção de verdade, com traceback real. 26 checagens, nada enviado, nada gravado, nenhuma
conexão aberta:

```
1) sessão sadia -> NÃO faz rollback   |   sessão quebrada -> rollback, o lote segue
2) gestão notificada, com contato, wa_message_id e traceback no corpo E no log
3) etapa -> transferido_humano, despedida UMA vez, guard de despedida
4) etapa terminal ou sem estado -> notifica, mas NÃO manda despedida
5) sessão nova indisponível (pool esgotado) -> falha alto no log, não levanta
   despedida recusada pelo guard -> não levanta, e a transferência PERMANECE
```

---

## 4. P1-B — o teto que calava quem já estava conversando

`qualificacao_pode_atuar` perde o `_teto_ok`. O fundamento é a natureza da mensagem:

```
ABERTURA = business-initiated -> é este volume que a Meta pontua. TETO CONTINUA.
CONVERSA = user-initiated     -> a pessoa acabou de escrever. Não responder é que custa.
```

Medido em 25/08: 20:32:00 e 20:32:12, duas mensagens do 5583988046720 mortas em
`teto de envios/hora estourado (20/20)` — e mortas em silêncio, porque até o P0-B ninguém
lia a recusa.

**O volume continua contido:** a conversa só existe depois de uma abertura, e as aberturas
seguem limitadas a 20/h. O agente não pode responder mais gente do que teve permissão de
abordar — o freio age uma porta antes.

### Emenda que o item não previa — a despedida herdava o teto

`_fallback` usava `guard_de_abertura` (a etapa já é `transferido_humano`, e
`qualificacao_pode_atuar` exige etapa ativa). Só que com ele vinha o **teto por hora** — e
a despedida é exatamente a mensagem que o P0-B e o P0-C usam para que falha nunca vire
silêncio. Bloqueá-la por congestionamento de *aberturas* devolveria o silêncio pela porta
dos fundos: lead transferido, gestão notificada, e a pessoa sem uma palavra.

`guard_de_despedida`: só a chave geral. Sem teto, sem exigir etapa ativa. Não há risco de
enxurrada porque `_fallback` e a rede gravam `transferido_humano` **antes** de enviar e
recusam agir sobre etapa não-ativa — estruturalmente uma despedida por conversa.

### Teste — o cenário pedido, teto artificial em 1

```
teto ESTOURADO + lead ativo   -> RESPONDE assim mesmo   (era o silêncio de 25/08)
teto ESTOURADO + ABERTURA     -> continua bloqueando
teto ESTOURADO + guard_abertura -> continua bloqueando  (abertura e lembrete)
teto ESTOURADO + despedida    -> ENVIA                  (senão o fail-closed vira silêncio)
chave geral desligada         -> nem despedida
config ausente / exceção      -> nem despedida          (falha FECHADA)
```

O teste que dizia `"o teto vale também no envio" -> False` foi **substituído**, não
removido: ele estava fiel ao código, e o código estava errado.

---

## 5. Item 4 — a aresta do adiamento por teto: **existe, e agora está fechada**

**A pergunta:** se o lead escreve antes de o `responder_pendente` disparar, o turno novo
roda na etapa já avançada (sem o lead ter recebido a fala adiada) e a pendência dispara
depois — duas falas fora de ordem?

**Resposta: sim, num dos dois desfechos.** O mecanismo, passo a passo:

1. turno N: o teto recusa → `_falar` agenda `responder_pendente` (+10 min) com o texto
   T_N e devolve `False`; `_avancar` **move a etapa assim mesmo** (decisão documentada: o
   dado extraído não pode se perder). O lead nunca recebeu T_N;
2. o lead escreve de novo — e escreve justamente porque não recebeu resposta;
3. o turno N+1 roda na etapa já avançada. O histórico **não** contém T_N (envio recusado
   não gera `Message`), então o LLM produz T_{N+1} para a etapa nova;
4. dois desfechos:
   - **turno novo TAMBÉM recusado pelo teto** → `nat_agendar` cancela o pendente do mesmo
     `(kind, contato)` antes de inserir. Só o texto mais novo sobrevive. **Já estava certo**,
     por construção do agendador;
   - **turno novo CONSEGUE falar** — o teto é contagem MÓVEL de 1h, ele libera sozinho
     dentro dos 10 min → a fala nova sai agora e a **velha dispara depois**. O lead recebe
     a pergunta do passo anterior depois da do passo seguinte, perguntando o que ele
     acabou de responder. **Este é o caso, e ele era real.**

**Conserto (`7855fc0`):** `_descartar_fala_adiada` cancela o `responder_pendente` nos dois
pontos em que o agente **efetivamente fala** — quando a fala sai (`_falar`) e quando ele se
despede (`_fallback`).

**Nada se perde ao descartar.** T_N era o reconhecimento + a pergunta da etapa em que o
lead já está; como nunca saiu, o turno novo faz a mesma pergunta com contexto mais fresco.
Descarta-se uma duplicata velha, não informação. O cancelamento é blindado: se ele falhar,
vira log, não exceção.

**Nota de escopo:** com o P1-B, `qualificacao_pode_atuar` não recusa mais por teto, então
este ramo fica **dormente** em produção. Ficou inteiro de propósito — é a rede se o teto
voltar a valer para a conversa (a "opção B" prevista na auditoria), e `enviar_nat` repassa
o motivo do guard tal e qual.

---

## 6. Divergência encontrada no recon

`test_risco3_abertura.py` **já estava vermelho antes deste sprint** — confirmado rodando o
arquivo com o `database.py` anterior ao P1-A. Não é regressão: o `teste_15` comparava um
inbound falso contra o relógio **real**, e passou a falhar 24h depois de ter sido escrito,
quando a própria janela de 24h fechou sobre o dublê. Um suite que fica vermelho pelo
calendário deixa de ser lido — e este chegou ao sprint escondendo qualquer regressão real
no arquivo. Corrigido em `b1e3963` prendendo `_agora_sp` em `AGORA`.

### Suites verdes ao fim do sprint

```
test_qualificacao.py · test_rede_ultima_instancia.py · test_nat_guard.py
test_gatilho_abertura.py · test_nat_sprint3.py · test_nat_caminho_completo.py
test_espontaneo.py · test_observabilidade_envio.py · test_risco3_abertura.py
```

---

## 7. P0-A — decidido, implementado, **ainda não no ar**

**O bug:** `_marcar` (`app/agendamento/agendar.py:232-243`) faz `await db.commit()` a cada
passo. Correto na requisição HTTP da LP, que é dona da sessão. Fatal quando o agente chama
`fluxo.agendar(db, ...)` com a sessão do **webhook**, de dentro de
`async with db.begin_nested()`: o commit fecha a transação aninhada, a instrução seguinte
levanta `InvalidRequestError`, o `_fallback` morre no mesmo erro e o savepoint reverte tudo.
**100% dos agendamentos pelo agente falham** — só teve uma vítima porque só uma pessoa
chegou lá.

**O que o commit por passo protege:** a faxina (`app/agendamento/faxina.py`) procura linhas
em `passo='box_criado'` com `box_id` não nulo e `updated_at` de 15+ min, e devolve o box à
agenda da consultora. Ela **só enxerga box cujo id está na nossa tabela** — uma linha que
nunca foi commitada é um box `available` pendurado na agenda real, invisível para sempre.

### A comparação que levou à decisão

| | (i) `_marcar` nested/injetável | (ii) enfileirar `agendar_slot` | **(iii) `async_session()` própria — ESCOLHIDA** |
|---|---|---|---|
| **Durabilidade da faxina** | ⚠️ **perde-se no caminho do agente**: sem commit por passo, queda entre o `BoxesAdd` e o commit final do webhook deixa box órfão sem linha — o pior desfecho, porque é invisível | ✅ intacta | ✅ **intacta e idêntica à da LP** |
| **Latência para o lead** | = igual | ❌ **até 60s** (`nat_scheduler.INTERVALO_SEGUNDOS=60`) no momento mais quente da conversa | = igual (mesmo turno) |
| **Risco ao caminho da LP** | ⚠️ alto — mexe na função compartilhada do caminho de maior volume | ✅ nenhum | ✅ **nenhum: `_marcar` não é tocado** |
| **Superfície** | 1 função, 11 pontos de chamada | novo `kind` + handler + etapa estacionada + fala migrada | ~1 função em `qualificacao_fluxo.py` |
| **Migração** | não | não | não |

### Como ficou (`fe5b1c6`)

```python
from app.database import async_session
async with async_session() as db_agendamento:
    r = await fluxo.agendar(db_agendamento, nome=nome, ..., lead_id=estado.exact_lead_id, ...)
```

**A sessão abre só no instante do `fluxo.agendar`** — não no começo do turno. O turno já
segura a conexão do webhook durante `llm.conversar` (3–5s medidos); abrir a segunda cedo
dobraria a retenção num pool que acabou de ser dimensionado. Ela vive o tempo do
agendamento e fecha antes de qualquer outra coisa. Coberto por teste: nas rodadas que
**não** chegam a agendar (slot inventado, slot que saiu da grade), **zero** sessões abertas.

**`read committed` é o que faz isto funcionar** (conferido em produção): o `_reuniao()`
seguinte roda na sessão do webhook — cuja transação começou antes — e ainda assim enxerga a
linha commitada pela sessão do agendamento.

### O modo de falha residual, testado dos dois lados

Se o turno estourar **depois** de `fluxo.agendar` commitar, o savepoint reverte
`estado.agendamento_id` enquanto a reunião existe de verdade na Exact e em `agendamentos`.

A exceção **escapa de propósito**. Um `try/except` local ali engoliria o caso e a gestão
nunca saberia da reunião órfã do estado. Escapando, ela cai na rede do P0-C:

```
test_qualificacao.py          exceção APÓS o agendamento commitado ESCAPA
                              e a sessão do agendamento fecha assim mesmo (async with)
test_rede_ultima_instancia.py gestão notificada, com o caso e o contato no corpo
                              lead NÃO fica em silêncio — despedida sai
                              agente para de escutar (a reunião já existe)
                              traceback do caso no log
```

**O resíduo é aceitável; o silêncio sobre ele não é.** Órfão local em `passo='iniciado'`
não tem efeito externo (nada foi para a Exact) e não segura slot na grade.

### Não rodado, e por quê

`test_agendamento_e2e.py` exercita o caminho real ponta a ponta, mas **escreve na Exact de
produção** e exige `--sim-eu-quero`. Não foi rodado. A validação de ponta a ponta do P0-A
depende de um agendamento real pelo agente — o primeiro lead que escolher horário depois do
restart do P0-A é o teste, e o P0-E vai deixar o rastro dele.

---

## 8. O restart de 14:03 — o que ele mudou no log

```
linhas no journald, última hora ANTES do restart .... 98 780
linhas de SQL cru depois do restart ................. 0
QueuePool limit depois do restart ................... 0
estados do agente antes / depois .................... 37 / 37 (intactos)
```

Todos os jobs subiram: sync Exact, alertas de janela, templates agendados, agendador NAT,
saúde de entrega, faxina, 2 consultoras em rotação, 13 origens confirmadas.

O log do **P0-E** só aparece quando um lead real escreve, e não houve inbound nenhum na
primeira meia hora depois do restart. Um vigia fecha a primeira hora e reporta os três
números (journald, `QueuePool`, turnos do P0-E).

---

## 9. Pendências

**Deste sprint:** o restart do **P0-A** (`fe5b1c6`), que ainda não está no ar. É o único
commit do sprint fora de produção.

**Fora deste sprint, não esquecer:**

- Operacional, com o time: Isa assumir a Fabiana (reunião pedida para **27/08 11:15**,
  amanhã, **sem reserva**), cortesia para a Eve, SDR 6 responder a Osmari, desambiguação do
  Pablo.
- P3-A — detector "AGENTE MUDO" (`kind` `vigiar_resposta`).
- Sprint global do `format_phone` / unificação de threads (12 vs 13 dígitos no Hub).
- Causa indeterminada da falha de contrato do LLM de 26/08 10:11 — o P0-E vai nomeá-la na
  próxima ocorrência.
- Avaliar em separado: soltar a conexão durante `llm.conversar` (corta a retenção de 3–5s
  para <1s, mas exige reabrir sessão e reler o estado no meio do turno).
