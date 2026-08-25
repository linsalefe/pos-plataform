# RECON — Lead espontâneo (Bloco 0) — 25/08/2026

Nada foi implementado. Este é o mini-recon que o sprint pede antes de codar, e ele
**muda duas das quatro regras de admissão**.

## Veredito

**A demanda é real e está sendo desperdiçada:** de 554 pessoas que escreveram pela primeira
vez na vida nos últimos 30 dias sem lead na Exact, **553 nunca receberam resposta**. No mesmo
período, quem tinha lead foi respondido em 67% dos casos. Não é impressão — é o controle
abaixo.

**Mas a regra de admissão como está escrita não funciona**, por dois motivos independentes, e
um deles é um defeito **latente que também quebra o agente de pré-qualificação já entregue**.

---

## 0.1 — Volume medido

Contatos cuja **primeira mensagem da vida** foi inbound, últimos 30 dias: **739**.

| | |
|---|---|
| com lead na Exact pelo match **estrito** (o do código hoje) | 38 |
| com lead **só** quando o match tolera o 9º dígito | **+147** ⚠️ |
| sem lead nenhum | **554** = 18,5/dia |

### O que são os 554, pela primeira mensagem

| | | |
|---|---|---|
| **274** | **49%** | **CTWA** — "Olá! Posso ter mais informações sobre isso?" (prefill de anúncio click-to-WhatsApp) |
| 80 | 14% | texto livre não classificado |
| **45** | **8%** | só saudação ("Olá", "Bom dia") |
| 39 | 7% | **reaction** (curtida em mensagem) |
| 29 | 5% | **CONGRESSO** — outro funil |
| 25 | 5% | **interactive** (clique de botão) |
| 22 | 4% | **auto-resposta de outro negócio** |
| 21 | 4% | "Fiz minha aplicação na turma X…" |
| 13 | 2% | **aluno / pós-venda** |
| 6 | 1% | button / sticker / image |

**Plausivelmente lead: ~319 = 10,6/dia.** É essa a carga que a Nat assumiria.
**24% NÃO podem virar Nat** (aluno, congresso, bot, tipo de mensagem não-texto).

### O controle que prova o desperdício

| grupo | contatos | receberam resposta |
|---|---|---|
| **com** lead na Exact | 185 | 124 (**67%**) |
| **sem** lead | 554 | 10 (**1%**) |

O outbound *é* registrado — a diferença de 67% para 1% é real. Quem chega sem cadastro é
ignorado.

### Amostra (as 20 primeiras mensagens estão no §0.1 do scratchpad; aqui o que decide regra)

```
CTWA (lead de anúncio, o caso bom):
  "Olá! Posso ter mais informações sobre isso?"          ← 274 ocorrências, texto idêntico
  "Olá! Posso saber mais informações sobre isto?"

CONGRESSO (funil que não é o nosso):
  "Bom dia. Quero participar do congresso."
  "Boa noite! Não recebi o link de acesso no e-mail cadastrado"
  "Olá, as palestras do congresso ficam gravadas?"
  "Estou na sala e vendo tudinho 💐"

ALUNO (pós-venda):
  "Bom dia, quando será feita a liberação da gravação?"
  "Deixa eu tirar uma dúvida na quarta feira talvez eu precise sair um pouco antes da aula"

AUTO-RESPOSTA DE OUTRO NEGÓCIO (a Nat conversaria com um robô):
  "Olá, tudo bem? Seja bem-vindo(a). Sou Beatriz, psicóloga clínica…"
  "*Pamella Cardoso Decorações* agradece seu contato. Como posso ajudar?"
  "Oi, pessoal! Não estou disponível no momento, assim que possível retorno ✨"
```

---

## ⚠️ ACHADO 1 (bloqueante) — o 9º dígito parte a mesma pessoa em duas threads

O sprint diz *"por telefone normalizado — atenção ao formato +55/DDD, reusar a normalização
existente"*. **A normalização existente é justamente onde está o defeito.**

`exact_spotter.format_phone` (`app/exact_spotter.py:119`) só prefixa `55`:

```python
digits = "".join(c for c in phone if c.isdigit())
if not digits.startswith("55"):
    digits = "55" + digits
```

E os dois lados guardam formatos diferentes:

| | 12 dígitos (sem o 9) | 13 dígitos (com o 9) |
|---|---|---|
| `exact_leads.phone1` | 209 | **8 348** |
| `messages.contact_wa_id` | **3 780** | 2 625 |

O WhatsApp entrega o `wa_id` **sem o 9** para DDD fora da região 11–28; a Exact guarda **com**
o 9. `format_phone` nunca reconcilia os dois.

**Prova, em produção, na mesma pessoa:**

```
24/08 16:37  558694169303   inbound   "Olá! Tudo bem? Fiz minha aplicação na turma…"
24/08 16:48  5586994169303  outbound  template "Olá, Raimundo Nonato…! 😊 Sou a Nat…"
24/08 17:20  558694169303   inbound   botao:"Sim, Posso conversar agora"
```

Um humano, **dois `contact_wa_id`, duas threads**. Mandamos para uma, ele responde pela outra.

**340 pessoas (5% do Hub) já estão partidas assim** — 680 threads.

### Consequência 1 — a regra de admissão nº 2 falha aberta

147 leads conhecidos em 30 dias (~5/dia) passariam pelo critério "sem match em `exact_leads`".
**A Nat assumiria conversa de lead que já tem SDR** — exatamente o que o sprint chama de
"a Nat invadindo conversa de SDR". Fail-open, não fail-closed.

### Consequência 2 — isto também quebra o agente de pré-qualificação, e ele já está entregue

`qualificacao_gatilho.wa_id_de()` monta a chave **a partir do telefone do lead** (13 dígitos).
`qualificacao_fluxo.py:153` procura o estado por igualdade exata:

```python
NatQualificacaoState.contact_wa_id == contact_wa_id   # o wa_id do INBOUND (12 dígitos)
```

Para todo lead fora do DDD 11–28 — **~59% das threads do Hub** — o estado nasce numa chave e
a resposta chega na outra. O agente **nunca reconheceria a própria conversa**.

Hoje é **latente, não ativo**: `nat_qualificacao_state`, `nat_flow_state`,
`nat_scheduled_actions` e `nat_contact_attempts` estão **todas vazias** — nada rodou em
produção ainda. Aparece na primeira ativação.

> **O fluxo espontâneo é imune a isso por construção**: ele nasce do inbound e chaveia tudo
> pelo `wa_id` que chegou. Quem sofre é o caminho LP/Exact → WhatsApp.

---

## ⚠️ ACHADO 2 — 24% do inbound não pode virar Nat, e a missão 1 não segura sozinha

O sprint resolve "não é interesse em pós" com a **missão 1** (`transferir_humano`). Isso cobre
aluno e engano. **Não cobre dois casos:**

1. **Auto-resposta de outro negócio** (22 em 30 dias). A Nat manda "olá, como posso ajudar?",
   o robô do outro lado responde o texto automático de novo. Duas máquinas conversando, e cada
   volta gasta LLM e queima a janela de 24h.
2. **Tipo de mensagem não-texto** (70 = 13%): `reaction`, `interactive`, `sticker`, `image`.
   Uma **curtida** numa mensagem antiga entra hoje como "primeira mensagem da vida" e abriria
   uma conversa da Nat do nada.

E o **congresso** (29 em 30 dias) é um funil inteiro que passa por aqui e que a missão 1 só
pega depois de já ter falado — gastando uma resposta e confundindo quem só quer o link do
evento.

---

## 0.2 — Onde o webhook decide, e onde a página vive

### O ponto de decisão: `app/main.py:490-506`

Dentro do `SAVEPOINT` de roteamento, com a precedência já documentada no próprio arquivo:

```python
dono_agente = await processar_texto_agente(msg["from"], content, wa_message_id, db)
if not dono_agente:
    from app.nat_flow import processar_clique, processar_texto
    if evento_botao:   await processar_clique(evento_botao, db)
    elif msg_type == "text":  await processar_texto(msg["from"], content, wa_message_id, db)
```

A admissão do espontâneo entra **dentro de `processar_texto_agente`**, não antes: é o único
lugar que já é "um dono por mensagem". Colocar um terceiro `if` no `main.py` recriaria a
disputa que esse bloco existe para evitar.

### A página de obrigado NÃO é uma página nossa

`docs/obrigado-snippet.html` é um **snippet para colar** no `obrigado.html` de outro
repositório, de outro time (`.cenatsaudemental.com`, `.netlify.app`). Ele fala com
`https://hub.cenatdata.online` por CORS. **Não hospedamos essa página.**

Então "a página irmã" **não tem casa** — é decisão, não cópia:

| | |
|---|---|
| backend | FastAPI, **sem `StaticFiles` montado**, atrás de nginx em `/api/`, `/webhook`, `/health` |
| frontend | **Next.js 16** (App Router) na :3001, catch-all `location /` do nginx |
| auth do front | **sem `middleware.ts`** — não há guarda de rota; cada página se protege sozinha |

**Recomendo a rota pública no Next.js** (`/agendar/[token]`): o catch-all do nginx já a serve,
não precisa de mudança de infra, e o visual do obrigado é reaproveitável em componente. A
alternativa (HTML servido pelo FastAPI) exigiria um `location /agendar/` novo no nginx —
mudança de infra para ganhar nada.

---

## 0.3 — O mínimo que o `LeadsAdd` exige

De `app/agendamento/client.py:152`, já medido e em produção:

```python
lead = {"name", "source", "subSource", "funnelId", "ddiPhone", "phone"}   # obrigatórios
lead["description"]                                                        # opcional
```

**Não existe campo de e-mail no `LeadsAdd`.** O e-mail vai dentro de `description`, via
`extras.montar_descricao` (teto de 4000 chars; a Exact trunca 8000 **em silêncio**).

**Consequência para a página:** o telefone vem do token, o nome é o único campo realmente
necessário, e **o e-mail pode ser opcional sem bloquear o agendamento** — ele não é requisito
da Exact, é conveniência do SDR.

### O `subSource` dedicado NÃO existe

Allowlist ativa (13, todas `Pos …`):

```
PosMulheridades · Pos Grupos e Oficinas T2 · Pos Infantojuvenil EAD · Pos Psicologia na RAPS T3
Pos Psicologia Hospitalar · Pos Suicidio e Luto T3 · Pos Psicologia Escolar
Pos Alcool e Drogas T4 · Pos Psicologia Clinica T2 · Pos Gestao Psicossocial T5
Pos TEA V3 · Pos Saude do Trabalhador · Pos Enfermagem em Saude Mental
```

`espontaneo_whatsapp` **não está lá** → **CHECKPOINT**, como o sprint previu. E o cuidado é
maior do que parece: `LeadsAdd` **cria** `source`/`subSource` que não existem, **e não há
endpoint para remover** (FINDINGS §11 — foi assim que `DialogicasTurma` virou lixo permanente
no cadastro). Tem que nascer certo na primeira vez.

---

## O que muda no sprint

| # | onde | mudança |
|---|---|---|
| 1 | regra de admissão 2 | trocar `format_phone` por chave tolerante (**DDD + últimos 8 dígitos**) |
| 2 | regra de admissão | **+5ª: só `message_type == 'text'`** com conteúdo não vazio |
| 3 | regra de admissão | **+6ª: recusar auto-resposta de negócio** (lista de padrões, pré-LLM) |
| 4 | Bloco B | a página é **rota nova no Next.js**, não cópia de uma página existente |
| 5 | Bloco B | e-mail **opcional** — `LeadsAdd` não tem o campo |
| 6 | fora do escopo | o 9º dígito **também quebra o agente de pré-qualificação** — sprint própria |

---

## CHECKPOINT — 4 decisões antes de eu codar

1. **O 9º dígito.** Faço a chave tolerante só na admissão do espontâneo (rápido, cirúrgico, não
   mexe em nada que já roda), e abro sprint separada para consertar `format_phone` no resto —
   que é onde mora o defeito do agente de pré-qualificação? **Recomendo sim**: consertar
   `format_phone` global toca NAT, boas-vindas, `ai_engine` e `twilio_routes` de uma vez, e
   isso não cabe de carona neste sprint.

2. **`espontaneo_whatsapp` na Exact.** Confirma o nome exato antes de eu criar? Sugiro
   `Espontaneo WhatsApp` (mesma grafia ASCII-com-espaço das outras 13). É irreversível.

3. **Congresso.** Os 29/mês que escrevem sobre o congresso — a Nat transfere para humano
   (missão 1) ou é outro tratamento? Hoje eles também não são respondidos.

4. **Onde a página mora.** Confirma rota pública no Next.js (`hub.cenatdata.online/agendar/<token>`)?
   É o caminho sem mudança de infra.

Com esses quatro respondidos eu sigo para a migração (que é o próximo CHECKPOINT do sprint).

---

## CORREÇÃO 1 APLICADA — 24/08/2026 23:30 (SP), antes das 09h

Só a chave tolerante no agente de qualificação. **O fluxo espontâneo não foi começado.**

### `app/telefone.py` (novo)

`variantes_wa_id()` devolve as formas em que o mesmo humano pode estar gravado — sempre com
DDI, sempre com a de 13 dígitos primeiro. Os **quatro** formatos colapsam no mesmo par:

```
5586994169303 ─┐
 558694169303 ─┤
  86994169303 ─┼─→ ("5586994169303", "558694169303")
   8694169303 ─┘
```

`chave_telefone()` reduz a **DDD + últimos 8 dígitos**, para casar conjuntos (é o que a
admissão do espontâneo vai usar contra `exact_leads`, com custo constante em vez de varrer
8 636 telefones).

**Nada foi convertido, nada migrou.** Só a BUSCA mudou: `== wa_id` virou `IN (variantes)`.
Reescrever `contact_wa_id` em 6 451 threads vivas com UNIQUE no caminho é risco
desproporcional para um problema de leitura — e ninguém sabe qual das duas formas entrega
mensagem, então eleger uma canônica poderia quebrar o envio, que hoje funciona.

**Fixo não ganha um 9.** `86 2234-5678` com um 9 na frente é o celular de outra pessoa; a
variante só nasce quando o número local começa em 6–9. Estrangeiro (`447834239129`,
`245956444415` — os dois existem na base) passa inteiro, sem variante.

### Os 7 pontos de comparação corrigidos

Eram 2 no meu recon. São **7** — o `abrir()` sozinho tinha quatro.

| arquivo:linha | o que era | efeito do defeito |
|---|---|---|
| `qualificacao_fluxo.py:152` `estado_de` | `== contact_wa_id` | o agente não achava o próprio estado |
| `qualificacao_fluxo.py:180` `_historico` | `== contact_wa_id` | o modelo via **metade** do diálogo — sem o template que ele mesmo mandou |
| `qualificacao_fluxo.py:230` `_nome` | `Contact.wa_id ==` | lead sem nome no contexto |
| `qualificacao_fluxo.py:316` `_notificar` | `Contact.wa_id ==` | aviso ia para a gestão em vez do SDR dono |
| `qualificacao_fluxo.py:427` `abrir` | `Contact.wa_id ==` | **abertura abortada** com "não existe em contacts" — mentira: existia, na outra grafia |
| `qualificacao_fluxo.py:636` agendamento | `Contact.wa_id ==` | agendava com nome "Lead" |
| `qualificacao_guard.py:170` `pode_atuar` | `== wa_id` | o agente era barrado no envio |

`scalar_one_or_none()` virou escolha ordenada em toda busca de linha única: com as duas
threads existindo, ele levantaria `MultipleResultsFound`.

### Verificado contra dados de produção

```
busca 5586994169303 → contato 5586994169303 / Raimundo Nonato Coêlho Júnior · histórico 3 msg
busca  558694169303 → contato 5586994169303 / Raimundo Nonato Coêlho Júnior · histórico 3 msg
busca 5548988036257 → contato 5548988036257 / Bruna Da Rosa Gonçalves       · histórico 2 msg
busca  554888036257 → contato 5548988036257 / Bruna Da Rosa Gonçalves       · histórico 2 msg
```

As duas grafias resolvem no mesmo humano, e o histórico vem **unificado** — as 3 mensagens do
Raimundo estavam partidas em duas threads (inbound na de 12, template na de 13, clique na de
12).

### Testes e ativação

16 checagens novas em `test_qualificacao.py` §2b: os quatro formatos, ordem estável, chave de
conjunto única, fixo que não vira celular, estrangeiro intocado, lixo que não casa, o defeito
**nos dois sentidos**, número de outra pessoa que continua não casando, duas threads com
escolha determinística sem levantar, e o contato achado na grafia gêmea.

O dublê de banco **executa o `IN` de verdade** (lê os binds do statement e filtra) — um mock
que devolvesse tudo passaria mesmo se o código voltasse para `==`.

Dois testes do guard falharam quando o `IN` entrou, e o motivo importa: o dublê deles só
respondia `scalar_one_or_none`, então devolvia `None` calado e "libera" virava "bloqueia" por
defeito do teste, não do código. Dublê corrigido para responder as duas APIs.

**15 suítes offline verdes. Restart feito 23:30, `/health` 200, `/slots` 200.**

### Fica para a sprint global (prioridade logo após o espontâneo)

`format_phone` continua ingênuo em `nat_guard._resolver_lead_e_wa_id` (que ainda varre os
8 636 leads em laço), `nat_flow`, boas-vindas, `ai_engine:363` e `twilio_routes:335`.
