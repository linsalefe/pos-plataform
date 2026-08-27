# Teste de ponta a ponta do funil — preparação

**27/08/2026 · 14:35 (SP) · nada foi enviado.**

---

## 1. Harness do LLM — verde, e desta vez em três rodadas

```
cd backend && venv/bin/python teste_manual_llm.py
```

| | rodada 1 | rodada 2 | rodada 3 |
|---|---|---|---|
| cenários | 18/18 ✅ | 18/18 ✅ | 18/18 ✅ |
| contrato JSON (`_validar`) | 18/18 | 18/18 | 18/18 |

**54 de 54 cenário-passagens, 54 de 54 no contrato.** Rodei três vezes de propósito: o
critério do `TESTE_LLM_20260824.md` é a **taxa**, não uma rodada escolhida a dedo — em agosto
ela era ~98% por cenário (59/60, com o 1.3 caindo numa checagem de estilo). Hoje foi 100%.
São 18 cenários e não os 15 do doc: o grupo 4 cresceu com `4.3`, o typo `27:08 - 10:30`.

Modelo `gpt-5-mini`, timeout 10s, 2 tentativas.

### O veredito humano (os pontos `👁`), lido nas três rodadas

| cenário | o que a Nat respondeu | leitura |
|---|---|---|
| 2.1 preço | *"Os valores e condições são passados pela consultora... Agora me diz: em que ano você concluiu?"* | ✅ recusa e devolve o roteiro na mesma frase |
| 2.3 marcar horário | *"eu não marco nem confirmo horários — a agenda quem passa é a consultora"* | ✅ recusa sem pedir permissão |
| 3.4 pede para parar | `transferir_humano` + *"você será removida da nossa lista"* | ⚠️ ver abaixo |
| 3.5 agressiva | *"entendo a irritação — peço desculpas por te incomodar"* e segue o roteiro | ✅ |
| 4.2 / 4.3 slot | `agendar_slot`, `slot_id=d21` nos dois — inclusive com o typo `27:08` | ✅ copia o id, não inventa |

Duas observações que as checagens automáticas não pegam:

* **3.4 promete mais do que executa.** *"você será removida da nossa lista"* é uma promessa de
  descadastro; o que o código faz é `transferir_humano` + silenciar aquele contato. Na prática
  o agente para, mas ninguém foi removido de lista nenhuma. Não bloqueia o teste — fica
  anotado.
* **4.1 recomeça a conversa.** Nas três rodadas a oferta de agenda abriu com
  *"Oi Marina! Que bom ter você por aqui 😊 Sou a Nat do CENAT"* — uma saudação de primeira
  mensagem, na etapa em que já houve 3 turnos. **Provavelmente é artefato do harness**: o
  cenário 4.1 monta um histórico de UM turno só, enquanto em produção `_historico` carrega a
  conversa real. É exatamente o que o teste real vai desempatar — está na lista do que eu vou
  observar.

---

## 2. Gatilho da LP simulado até a porta do envio

Número fictício `11987654321` (confirmado ausente de `contacts`), tudo numa transação com
**ROLLBACK** no fim — conferido: 0 linhas residuais.

`cadastrar_lead_sem_agendar` fala com a Exact (CRM externo), então a simulação grava direto a
linha que ele gravaria, com a forma exata do lead real de hoje (`agendamentos` #242).

```
agora (SP): 27/08/2026 14:29:00 · horário comercial: True

1. POST /api/agendamento/lead -> agendamentos #244 (passo=lead_criado,
   lead_id=99999001, sub_source='Pos Grupos e Oficinas T2')

2. _gatilho_do_agente -> agendar_abertura -> enfileirou=True (enfileirado)
   nat_scheduled_actions #350  kind=iniciar_qualificacao  status=pendente
   >>> RUN_AT = 27/08/2026 14:34:00 (SP) = agora + 5 min
   payload  = {"lead_id": 99999001, "origem": "lp",
               "referencia_utc": "2026-08-27T17:29:00"}

3. iniciar_qualificacao executa...
   👤 contato criado (Fernanda Testes da Silva, canal 1)
   ⏰ encerrar_inativo agendado para 30/08 14:29
   🚀 abriu: nat_abertura_qualificacao → aguardando_ano
```

### A porta do envio — o que sairia

| | |
|---|---|
| destinatário | `5511987654321` |
| **template** | **`nat_abertura_qualificacao`** (T2 — tem formação, não tem reunião) |
| `{{1}}` nome | `Fernanda` |
| `{{2}}` curso | `Grupos e Oficinas em Saúde Mental` |
| `{{3}}` formação | `Psicologia` |
| **run_at** | **agora + 5 min** |

Texto renderizado (GET na Meta, leitura — nenhum envio):

> Olá, Fernanda! Que bom te ver por aqui ✨
>
> Vi que você aplicou para a nossa Pós-Graduação em Grupos e Oficinas em Saúde Mental. Antes
> de te mostrar os horários com a nossa consultoria, gostaria de entender um pouco melhor a
> sua trajetória até aqui.
>
> Vi que sua formação é em Psicologia. Em que ano você concluiu?

Estado criado: `etapa=aguardando_ano`, `formacao='Psicologia'`,
`faixa='De R$100,00 a R$200,00'`, `extras={'como_conheceu': 'Instagram'}`.
Relógios armados: `iniciar_qualificacao` 14:34 · `encerrar_inativo` 30/08 14:29.

O curso veio de `agendamentos.sub_source` → `resolve_course_name`, não de `exact_leads` — que
é o fix do S3-3 funcionando: `exact_leads` só teria esse lead no sync seguinte, horas depois.

---

## 3. ⚠️ Defeito encontrado na preparação: quem AGENDA na página perde o formulário

O tail do funil, apontado para o lead real de hoje, mostrou a **Quezia** (`5585986911107`)
saindo em **T3** (`nat_abertura_sem_formacao`) — e ela tinha preenchido a Profissão.

```
14:05:14  agendamentos #242  passo=lead_criado  extras={"Profissão": "Terapia Ocupacional",
                                "Como conheceu": "Instagram", "Ensino Superior": "Sim",
                                "Faixa de investimento": "De R$100,00 a R$200,00"}
14:05:31  agendamentos #243  passo=agendado     extras=  jsonb 'null'     <-- ela agendou
14:11:23  🚀 abriu: nat_abertura_sem_formacao → aguardando_formacao
```

### A mecânica

`qualificacao_dados.dados_da_lp` filtra `extras.isnot(None)` e pega `ORDER BY id DESC LIMIT 1`.
Só que a linha de `agendado` tem **`extras` = JSON `null`**, que **não é SQL NULL** — ela passa
pelo filtro, vence por ser a mais nova, e devolve `{}`.

O ponto amargo: a própria docstring de `dados_da_lp` já registra a existência dessas linhas
("54 com JSON null, todas agendado") — a observação estava certa, o filtro é que não a
implementa.

Confirmado no banco:

```
resolver_dados(lead_id=51605197, origem='lp')
  -> {'formacao': None, 'ensino_superior': None,
      'faixa_investimento': None, 'como_conheceu': None}
```

### O tamanho

| a linha que vence o `ORDER BY id DESC` | leads | tinham o formulário preenchido |
|---|---|---|
| `object` (o dado chega) | 78 | 78 |
| **`null` (o dado é engolido)** | **68** | **68** |

**68 de 146 leads (47%)** — todos os que agendaram na página. Não é retroativo: atinge cada
lead da LP que agenda, daqui pra frente.

### O que o lead vê

A Quezia **tem reunião marcada para 28/08 14:30** (`lembrete_reuniao` pendente, id 348), disse
que é Terapeuta Ocupacional, e recebeu:

> *"Vi que você se interessou pela nossa Pós-Graduação em Grupos e Oficinas em Saúde Mental.
> (...) Me conta: qual é a sua formação?"*

Sem formação, o ramo `reuniao is not None and formacao` não fecha e ela cai em T3 — em vez do
T1, que diria o dia e a hora da conversa que ela já marcou. Perde-se também
`faixa_investimento` e `como_conheceu`, que ficam `NULL` no estado.

**Por que a Mikaelle não sofreu disso:** ela é `origem='exact'`, e aí `resolver_dados` tenta a
segunda fonte (o `description` da Exact) quando a LP vem vazia. Quem é `origem='lp'` não tem
essa rede — o `if not dados and origem != ORIGEM_LP` corta o fallback justamente para ela.

### Impacto no teste combinado: **nenhum, se não agendarmos pela página**

O roteiro do teste é agendar **no chat** (`agendar_slot`), não no `obrigado.html`. Nesse
caminho a linha de `agendado` não existe quando a abertura dispara, e o T2 sai correto — foi o
que a simulação do §2 mostrou. **Não agendar na página de obrigado é, ao mesmo tempo, o
roteiro do teste e o que desvia deste bug.**

O conserto é o filtro (`jsonb_typeof(extras) = 'object'`), mas é mudança de comportamento em
produção e **não vou aplicar sem sua ordem** — nem no meio de um teste ao vivo.

---

## 4. O que eu preciso de você

| # | preciso | por quê |
|---|---|---|
| 1 | **o número do chip** | filtro do tail e das queries; e eu rodo o pré-voo antes para garantir que ele está limpo |
| 2 | **qual LP** (das 14 da allowlist) | define o `{{2}}` curso. Origem fora da allowlist = 400 no POST |
| 3 | **o nome e a Profissão que você vai digitar** | Profissão preenchida com formação real ⇒ **T2**; vazia ou "Outra profissão" ⇒ **T3**. Diga qual ramo você quer testar |
| 4 | **NÃO agendar no `obrigado.html`** | é o roteiro (agendar no chat) e evita o bug do §3 |

Regras de janela, já conferidas agora:

* **abertura só entre 09:00 e 18:30, seg–sex.** Fora disso ela é *empurrada* para o próximo
  horário útil, não perdida — mas o teste não acontece hoje. **Agora são 14:35: temos até
  18:30.**
* `qualificacao_enabled = true`, teto **20/hora** com **2 usados** na última hora. Folga.
* corte de data: 24/08 23:16 UTC. Um lead criado hoje passa.
* **a grade está magra: 3 slots, todos de 28/08** (11:15, 12:00, 13:30) — o slot de hoje 16:30
  saiu da grade entre 14:30 e 14:33. A oferta precisa de pelo menos 1, então dá; mas se a
  grade zerar, o passo `agendar_slot` não tem o que oferecer. **Vale conferir com o pré-voo na
  hora do "vai".**

---

## 5. Comando de acompanhamento — pronto

`backend/acompanhar_funil.sh`, quatro modos:

```bash
cd backend

./acompanhar_funil.sh <telefone> --preflight   # ANTES: o número está limpo? dá para abrir?
./acompanhar_funil.sh <telefone>               # DURANTE: tail do journald, filtrado
./acompanhar_funil.sh <telefone> --estado      # foto do banco, uma vez
./acompanhar_funil.sh <telefone> --watch       # foto do banco a cada 10s
```

Filtra pelas **duas grafias** do telefone (12 e 13 dígitos), pela mesma
`telefone.variantes_wa_id` que o backend usa — a abertura pode nascer numa grafia e o inbound
chegar na outra.

O `grep -v` do access log do uvicorn não é cosmético: o Hub faz polling de
`/api/contacts/<wa>/messages` a cada 3s enquanto um SDR tiver a conversa aberta, e essas linhas
carregam o `wa_id`. Sem o corte, elas afogam a narração do funil — foi o que aconteceu no
primeiro teste do filtro.

**Marcadores que eu vou narrar:**

| | |
|---|---|
| `👤` | contato criado para a abertura |
| `🚀 Agente abriu com …` | **abertura** — mostra qual template (T1/T2/T3) e a etapa inicial |
| `🧠 LLM <wa>/<etapa> \| acao=… etapa_cumprida=… dado=…` | **cada turno**, com a ação e o dado extraído |
| `📅 Agente ofereceu N horário(s)` | **oferta de agenda** |
| `⏰ NAT scheduler: <kind> agendado` | relógios: `encerrar_inativo`, `lembrete_reuniao` |
| `✅ Agente concluiu` / `🤝 Agente silenciado` | fecho ou transferência |
| `🔒 bloqueado` · `⚠️` · `❌ Meta recusou` | o que der errado |

O pré-voo confere de uma vez: contato/estado/ação pendente no número, `nat_config`
(chave, teto, corte), a janela comercial e os slots livres da grade.

---

## 6. O roteiro que eu vou observar

1. **abertura** — template certo para o ramo escolhido, `{{1}}` nome e `{{2}}` curso
   preenchidos (é aqui que o `#131008` aparecia)
2. **turnos `🧠`** — ano → atuação → motivação, `etapa_cumprida` avançando uma etapa por vez,
   sem inventar pergunta e sem pedir permissão
3. **a oferta** — até 5 horários, todos da grade, sem id cru; **e se ela recomeça a conversa
   com "Oi! Sou a Nat"**, que é a dúvida que sobrou do harness
4. **`agendar_slot` com o typo no slot** — o caso 4.3 contra dados reais
5. **`lembrete_reuniao`** agendado para T-30 do slot escolhido
6. **thread única** — com (b) no ar, inbound e outbound têm que cair no mesmo `contact_wa_id`,
   sem thread dividida nova

Diga **"vai"** com o número e eu rodo o pré-voo e abro o tail.
