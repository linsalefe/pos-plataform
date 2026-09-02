# SPRINT — MVP da página de Relatórios do Hub (`/relatorios`)

**Data:** 02/09/2026 · **Estado:** NO AR
**Precede:** `RECON_RELATORIOS_20260901.md` (+ Anexo A corrigido), `RECON_JORNADA_LEAD_20260901.md`,
`EMENDA_RECONS_20260902.md`, `RECON_T3_20260902.md`.

---

## 0. O que subiu

| Bloco | O que é | Commit |
|---|---|---|
| **1** | Tabela `disparo_skip` + gravação nos dois caminhos do disparo | `259e5fe` |
| **2** | `app/relatorios.py` — 5 endpoints, registrados em `main.py` | `5d787b0` |
| **3** | `/relatorios` no Next.js, gate de admin, somente leitura | este |

Uma migração aditiva (`migrate_disparo_skip.py`), zero mensagens enviadas, zero linhas de
produção alteradas fora dela. `npm run build` + restart do `cenat-frontend` juntos, e restart
do `cenat-backend` pelo router novo.

**Verificado por HTTP, com token real:** Isa (`admin`) recebe 200 nas cinco rotas; Ana
(`atendente`) recebe **403** nas cinco. `/relatorios` responde 200 e todos os chunks do build
são servidos pelo mesmo build (o 404 de `FIX_FRONTEND_CHUNK_404_20260825` não voltou).

---

## 1. Os números que a página mostra hoje

Janela de 30 dias, apurado em 02/09/2026 11:49 SP.

| Rota | Métrica | Valor | N |
|---|---|---:|---:|
| `/resumo` | Pessoas que a Nat abordou | **113** | 123 |
| | Responderam a Nat | **66** | 113 |
| | Qualificações completas | **40** | 123 |
| | Reuniões marcadas pela Nat | **9** | 58 |
| | Reuniões pela página de obrigado | **41** | 58 |
| `/ia` | Funil — já tinha formação | 89 → 57 → 40 → 36 → 33 · agendou **39** | 89 |
| | Funil — precisou ser perguntado | 24 → 9 → 6 → 5 → 4 · agendou **3** | 24 |
| | Conversas paradas esperando a Nat | **0** ✅ | — |
| | Encerradas por silêncio do agente | **1** | — |
| | Vigias que precisaram disparar | **0** ✅ | — |
| `/humano` | Tempo até responder — Nat | **3,7 s** | 252 |
| | Tempo até responder — time | **2 h 37** | 158 |
| | Mensagens por SDR | Thobias 13 (12 pessoas) | 1 de 30 dias |
| `/atritos` | Conversas da Nat cortadas | **50** | 62 |
| | Escreveram e não receberam resposta | **33** (3 vendidas) | — |
| `/jornada` | Agendaram | **97** (Nat 9 · página 88) | — |
| | Atravessaram para vendas | **29** (Nat 3 · página 26) | — |
| | Vendas ligadas a uma reunião nossa | **28** | 1 176 |

A quebra das 58 reuniões em 5 vias: `landing_page` 41 · `lp_incompleta` 5 · `indeterminada` 3
· `ia` 9 · `ia_incompleta` 0.

**Reprodução da coorte congelada** (`2026-08-24T20:16..2026-09-01T14:00`, que é o corte real
do recon — 24/08 23:16 a 01/09 17:00 UTC): **45 agendaram · 10 atravessaram · `{ia 3, lp 7}` ·
28 rastreáveis**, com `processoseletivo@` 25 e `comercial@` 20. Travado em teste.

---

## 2. O que ficou como NÃO MEDÍVEL, e por quê

Quatro métricas, e nenhuma aparece como zero:

| Métrica | Estado | Motivo |
|---|---|---|
| **Reuniões realizadas** / **Compareceu** | `nao_medivel` | O status vive só na API da Exact e vira `Concluído` no instante da troca de funil, com data no futuro. Exatamente os leads que avançam são os que têm o registro corrompido — medir por aí mediria "avançou de funil" |
| **Follow humano por template** | `nao_medivel` | Fora do MVP por decisão (métrica 9). Quando entrar, vem com a nota de que só conta WhatsApp: `nat_contact_attempts` tem **0 linhas em toda a história**, ligação não deixa rastro |
| **Disparos pulados pela higiene** | `indisponivel` desde 02/09 | O log passou a existir hoje (Bloco 1). O card entra quando houver dias suficientes |
| **Mensagens por SDR** | `indisponivel` (1 de 30 dias) | `sent_by` nasceu em 01/09 16h. Se o período inteiro for anterior, a seção mostra só o aviso e **nenhum gráfico** — barra vazia lê-se como "ninguém trabalhou" |

---

## 3. Cinco achados desta sprint

### 3.1 A coorte T3 do recon se auto-seleciona para o fracasso

`RECON_T3` define a coorte como `nat_qualificacao_state.formacao IS NULL` — **hoje**. Quem
responde a pergunta da formação **sai da coorte por construção**. *"O caminho T3 converte
zero"* é uma tautologia da definição, não uma medição.

Medindo pela abertura que de fato saiu (`messages.nat_etapa = 'nat_abertura_sem_formacao'`,
que é histórico e imutável):

| | recon | pela abertura |
|---|---:|---:|
| receberam a abertura T3 | 19 | **30** |
| … deram a formação | 0 | **11** |
| … chegaram ao ano | 0 | **9** |
| … **agendaram** | **0** | **5** |

Os 19 do recon são exatamente `30 − 11`. As cinco que fecharam o roteiro: Enfermeiro, Técnico
de Enfermagem, e três de Psicologia.

**Isto não derruba os outros achados do `RECON_T3`** — a rajada sem debounce, o curso vazio
(*"Pós-Graduação em ."*) e a abertura que ignora o inbound anterior seguem de pé, verificados
por outro caminho. Derruba só o número. **O painel usa a coorte pela abertura**, e a
`limitacao` do card diz que amostra pequena não vira taxa.

> **Consequência de método:** métrica sobre estado sobrescrito mede quem **falhou**, porque
> quem avança troca de estado e some. Sempre que houver um carimbo histórico (aqui,
> `messages.nat_etapa`), ele é a coorte.

### 3.2 O "27 reuniões" do recon só fecha COM o predicado de teste

A nota C.7 diz *"nenhum lead de teste estava nesse conjunto"*. **Estava**: o Thobias Justino
França — o mesmo que a emenda pegou na coorte vizinha. Sem o predicado dá 28 (21 LP); com ele,
**20 LP / 4 LP-incompleta / 2 indeterminada / 1 IA = 27**, na vírgula.

### 3.3 Dois bugs de chave, pegos validando contra produção

Os dois teriam ido para a tela como número plausível:

* **`count(*)` depois de `LEFT JOIN` conta linhas, não pessoas.** Devolveu **334 pessoas onde
  havia 127** — uma linha por mensagem recebida.
* **A chave vazia casa consigo mesma.** `chave_telefone` devolve `''` para número estrangeiro
  e lixo, e a docstring dela avisa que `''` **nunca** deve casar — mas num `GROUP BY`, `''`
  casa com `''` e todo ilegível vira **uma conversa só**. Era isso que fazia o invariante de
  silêncio acusar **1**. Com o `coalesce(nullif(chave, ''), digitos)`, ele volta a **0**, como
  o recon dizia. Hoje: 65 mensagens de chave ilegível, 51 threads distintas.

### 3.4 `{10,13}` dentro de f-string some sem erro

A normalização dos motivos de encerramento usa `regexp_replace(..., '\y\d{10,13}\y', ...)`
para agrupar *"envio recusado: 5537999965494…"* com os outros três iguais. Numa f-string,
`{10,13}` é campo de formatação: vira `(10, 13)`, o quantificador desaparece e **nada
estoura**. Só se vê olhando o resultado. Com as chaves escapadas, a tela mostra **8 motivos
onde mostrava 12**.

### 3.5 `sem_resposta_do_agente = 1`, e não é regressão

Um único caso: `5598984703419`, 29/08 09:37 — exatamente o que `RECON_28/08` §1.10 previu
(*"o primeiro vence amanhã"*). O teste trava o número em **1**: um segundo caso é que seria
notícia. O invariante que continua valendo é o outro, **silêncio em etapa ativa = 0**.

---

## 4. Bloco 1 — `disparo_skip`

Tabela aditiva, 12 colunas, dois índices. **Um ponto de escrita cobre os dois caminhos**:
`main.py` chama `bulk_send_template` como função Python, não por HTTP, e os dois atravessam o
mesmo laço; `origem_envio` os separa (`campanha` inclui o agendado, `individual` é o
`handleSingleSend`).

Três decisões que tiveram alternativa:

* **Sem FK em `telefone`.** O pulo acontece antes da criação do contato — a FK faria o log
  falhar exatamente nos casos mais interessantes.
* **`chave` gravada, não derivada.** Todo join do relatório usa a chave tolerante; derivar em
  SQL custa `translate()` sobre a tabela toda, gravar custa uma chamada que já existe.
* **`skips` é lista separada de `pulados`.** `pulados` é serializado por `json.dumps` no
  caminho agendado; um `datetime` dentro dele estouraria em `TypeError` e mataria o único
  caminho que já persistia alguma coisa.

Gravação única em `begin_nested()` antes do commit do lote: **falha de log é log de falha**, o
envio segue. Cobre inclusive a janela em que o código suba antes da migração.

A tabela só **acumula** nesta sprint. Zero linhas até agora — o primeiro disparo depois do
deploy escreve as primeiras.

---

## 5. Desempenho

| | medido | orçamento |
|---|---:|---:|
| Painel completo, primeira abertura (em série) | **527 ms** | 2 000 ms |
| Seguintes, cache de chaves quente | **445 ms** | — |
| Rota mais lenta (`/ia`, é o relógio real da página) | **254 ms** | — |

O recon estimava 146/76 ms. A diferença tem dois donos: o `thread_sql` (dois `regexp_replace`
por linha — é o preço de o `''` não colidir, §3.3) e a query de silêncio, que varre `messages`
inteiro por não ter recorte de tempo, porque é o card "situação agora". **Não otimizei**: 4×
abaixo do alvo, e qualquer corte aqui trocaria correção por milissegundos.

Uma otimização foi feita, e por medição: a query do vão do espontâneo custava **3,4 s** com
três subqueries escalares correlacionadas, cada uma recalculando a chave sobre os 9 299 nomes.
Reescrita numa passada: **105 ms**.

---

## 6. As regras de leitura, e onde elas estão no código

1. **N ao lado de todo percentual.** `metrica()` recusa número solto; o card só imprime `%`
   quando tem denominador.
2. **Não medível é estado visual próprio** — card tracejado cinza, sem barra, sem número, com
   o motivo. Cinco estados de confiança e nenhum é `0`.
3. **Taxa por ator só com N ≥ 30** (`N_MINIMO_TAXA`). A tabela por consultora mostra contagem
   absoluta e diz na tela por quê.
4. **`definicao` e `limitacao` vêm do backend e são renderizadas como estão.** O front não
   reescreve nenhuma das duas — uma fonte, senão o texto da tela e o do relatório divergem e
   ninguém sabe qual vale.
5. **O aviso de cobertura vai EM CIMA do número.** Na Jornada, antes dos cards.
6. **O card de saúde ignora o seletor**, com rótulo fixo *"situação AGORA"*. Reconstruir a
   etapa histórica é impossível com o dado de hoje: `nat_qualificacao_state.etapa` é
   sobrescrita, `nat_flow_state` está vazia, não há log de transição.

---

## 7. Testes

`test_disparo_skip.py` (banco dublê, nada sai) e `test_relatorios.py` (lê produção, não
escreve). Os dois verdes.

O que travam, e o defeito de cada um:

| Teste | Contra o quê |
|---|---|
| `periodo` do JSON == par do `WHERE`, espionando os binds | os "46" não reproduziam com o corte que o cabeçalho declarava: o período era **carimbado depois** |
| `chave_sql` == `chave_telefone` sobre a base inteira | duas implementações da mesma regra divergem se ninguém comparar |
| 53 nomes casam · 18 chaves excluídas · 1 duvidoso listado | a Ana Cristina é uma pessoa real cujo nome tem `- TESTE` |
| `Pozzebon`, `Rizzato`, `Azzi`, `Mazzeo`… **não** casam | o `zz` sem âncora apagava 48 pessoas reais |
| o `''` vira 51 threads, não 1 | §3.3 |
| silêncio = 0 · `sem_resposta_do_agente` = 1 · vigias = 0 | os invariantes de saúde |
| jornada = 45 / 10 / {ia 3, lp 7} / 28 | reprodução da coorte congelada |
| a guarda barra `Reagendamento` **e** `Reagendamento.` | as duas homônimas já inflaram uma conversão de 6 para 18 |
| toda query de funil filtra `funnel_id` | `INGEST_FUNNEL_IDS` está vazio: a base tem 9 306 leads, só 3 782 são de pós |
| rota que estoura devolve erro tratado e a vizinha responde | uma seção quebrada não derruba a página |
| painel < 2 s | §5 |

O predicado de teste roda **no Postgres**, não no `re` do Python: `\m` é sintaxe do Postgres e
o `re` nem compila. Testar num motor e usar no outro é o jeito de aprovar um predicado que o
banco lê de outro jeito.

---

## 8. O que ficou de fora, e por decisão de quem

**Fora por escopo da sprint:** métrica 9 (follow humano detalhado), o card que consome o
`disparo_skip`, os quatro consertos do T3, a tabela `nat_etapa_events`, o backfill do
`LeadStages`, a cópia local das transições de funil.

**Decisões que sobraram:**

| # | Para quem | O que |
|---|---|---|
| **A1** | Álefe | **O `dashboard_stats` antigo continua zerando das 21h às 24h** (`routes.py:118`, `datetime.now()` é UTC contra `messages.timestamp` que é SP). A página nova não copia o defeito — tem helper próprio — mas o painel antigo segue mentindo. São 2 linhas, e é trabalho separado |
| **A2** | Álefe | **`RECON_T3` precisa de emenda** com o §3.1: a coorte muda de 19 para 30 e o "converte zero" vira "5 de 30 agendaram" |
| **A3** | Álefe | **`RECON_RELATORIOS` C.7 precisa de correção**: o Thobias estava no conjunto das reuniões (§3.2) |
| **A4** | Álefe | Dois prompts próprios, já identificados e **saindo para lead real agora**: a mensagem com o curso vazio (*"Pós-Graduação em ."*) e a rajada sem debounce (mesma pergunta 4× em 23 segundos) |
| **I1** | Isa | **T3-4 — o roteiro T3.** O caminho em que a primeira coisa que o lead recebe é uma exigência. Agora com o número certo: 30 abordadas, 9 responderam, 5 agendaram |
| **I2** | Isa | **A Ana Cristina entra ou sai dos relatórios?** Nome com `- TESTE`, conversa real, 4 mensagens dela, matrícula em Follow 4. Hoje ela **fica na conta**, e a página diz isso no rodapé |
| **I3** | Isa | **A NAT deve agir no funil pessoal dela (25588)?** Hipotético hoje — o funil está dormente desde 19/08 |
| **I4** | Isa/Pablo | **O limiar de N ≥ 30 para mostrar taxa.** A página hoje recusa percentual por ator; quando o volume subir, alguém decide se afrouxa |

---

## 9. O risco que sobrevive ao deploy

**O número que muda sozinho.** Três métricas mudam de valor quando recalculadas sobre a
**mesma janela**, sem bug nenhum — "reuniões indeterminadas", "escreveram e não receberam
resposta", "perguntas em aberto". São todas da forma *"quantos ainda não foram atendidos"*, e
o "ainda" se move.

A página trata isso com o carimbo `Apurado em <hora> (SP)` no topo, sempre visível, e uma
frase fixa acima de tudo:

> *Alguns números contam **quem ainda não foi atendido**. Se alguém do time responder essas
> pessoas hoje, o número cai — mesmo você escolhendo o mesmo período.*

Sem ela, a página e os `.md` vão parecer contradizer um ao outro, e a primeira dúvida da Isa
vai ser sobre a confiabilidade da ferramenta em vez de sobre o dado.

---

*Sprint de 02/09/2026. Uma migração aditiva. Nenhuma mensagem enviada.*
