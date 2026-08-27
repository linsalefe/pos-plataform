# RECON — desempenho comercial do agente nas conversas reais — 27/08/2026

**Somente leitura.** Nenhum envio, nenhuma escrita, nenhuma migração. Todos os números
abaixo vêm com a query que os gerou.

Janela nominal: **24/08 23:16 UTC → 27/08 00:10 UTC**. Janela real com dado: o primeiro
estado do agente nasceu em **25/08 18:41 UTC** (o gatilho da abertura só passou a criar
contato naquele dia — `FIX_GATILHO_ABERTURA_20260825.md`), e a última mensagem do período é
de **26/08 19:18 SP**. São, portanto, **~26 horas úteis de operação e 43 leads**. É pouco, e
toda leitura abaixo carrega esse N.

---

## 0. Convenção de tempo — verificada contra o banco, não contra a memória

Duas descobertas que mudam qualquer métrica de latência e que valem para qualquer recon futuro:

| Coluna | O que é |
|---|---|
| `messages.timestamp` | **naive em São Paulo (UTC−3)**, por mensagem. É o relógio bom. |
| `messages.created_at` | UTC, mas é o **início da transação**. Um inbound e a resposta que ele gera **compartilham o mesmo valor**. |
| `nat_qualificacao_state.created_at` | UTC |
| `nat_qualificacao_state.transferido_em` / `encerrado_em` | naive em SP |
| `nat_scheduled_actions.run_at` / `processed_at` | naive em SP; `created_at` em UTC |

```sql
-- a prova: inbound 31885 e as DUAS respostas (31886, 31887) com created_at identico
select id, direction, timestamp, created_at from messages
 where contact_wa_id='554192680313' order by created_at;
--  31886 | outbound | 13:25:04.303112 | 16:25:02.087904
--  31885 | inbound  | 13:25:00        | 16:25:02.087904   <-- mesmo created_at
--  31887 | outbound | 13:25:04.928009 | 16:25:02.087904
```

Uma primeira versão deste recon mediu latência com `created_at` e devolveu **26,8 s de
mediana**. Com `timestamp`, a mesma medida dá **3,7 s**. O número errado era o relógio, não o
agente.

As buscas por telefone usam a chave `DDD || últimos 8 dígitos`, réplica de
`app/telefone.py::chave_telefone` — sem ela 59% das threads não casam com o estado.

---

## BLOCO 1 — o funil quantitativo

### 1.1 – 1.3 Origem, template de abertura, entrega e resposta

```sql
-- ver ANEXO A (base.sql) para as CTEs est/abertura/resp
SELECT e.origem, a.nat_etapa, a.status, count(*), count(r.est_id)
FROM est e JOIN abertura a ON a.est_id=e.id LEFT JOIN resp r ON r.est_id=e.id
GROUP BY ROLLUP(e.origem, a.nat_etapa, a.status);
```

| Origem | Template de abertura | Estados | % do total | Entregue (read+delivered) | Responderam | **% resposta** |
|---|---|---:|---:|---:|---:|---:|
| exact | **T1** `nat_abertura_agendado` | 8 | 19% | 8 (100%) | 7 | **88%** |
| exact | **T2** `nat_abertura_qualificacao` | 23 | 53% | 22 + 1 `sent` | 9 | **39%** |
| exact | **T3** `nat_abertura_sem_formacao` | 10 | 23% | 9 + **1 `failed`** | 3 | **30%** |
| lp | **T2** | 2 | 5% | 2 | 1 | 50% |
| espontâneo | — | **0** | 0% | — | — | — |
| **TOTAL** | | **43** | 100% | **42 / 43 (98%)** | **20** | **47%** |

**A entrega não é o problema.** 42 das 43 aberturas chegaram ao aparelho (19 `read`,
22 `delivered`); 1 `failed` e 1 parada em `sent`.

**T1 responde 2,3× mais que T2 e 2,9× mais que T3.** Lead que já tem reunião marcada e recebe
uma mensagem que **afirma** a reunião engaja quase sempre (88%). Lead que recebe uma pergunta
fria ("em que ano você concluiu?") responde 39%. Lead de quem não sabemos nem a formação
responde 30%. É a evidência mais forte do recon a favor de dar contexto/valor antes de
perguntar.

### 1.4 Progressão por etapa — e onde cada um parou

Etapa máxima **comprovada** por lead (cruzando os campos gravados com a etapa atual, já que
não existe histórico de etapa):

| Etapa máxima alcançada | Chegaram | % dos 43 | Queda para a etapa seguinte |
|---|---:|---:|---:|
| 1. `aguardando_formacao` (nunca passou) | 7 | 16% | — |
| 2. `aguardando_ano` (deu/tinha formação) | 25 | 58% | — |
| 3. `aguardando_atuacao` (deu o ano) | 3 | 7% | |
| 4. `aguardando_motivacao` | 0 | 0% | |
| 5. `ofertando_agenda` (deu a motivação) | 7 | 16% | |
| 6. `escolhendo_slot` | 0 | 0% | |
| 7. `concluido` | 1 | 2% | |

Lido como funil cumulativo: **43 abriram → 36 têm formação → 11 deram o ano → 8 deram atuação
→ 8 deram motivação → 8 chegaram ao ponto de agenda → 0 reuniões novas marcadas.**

Onde cada um **está hoje**:

```sql
SELECT etapa, COALESCE(transferido_motivo, encerrado_motivo, '(ativo)'), count(*)
FROM nat_qualificacao_state GROUP BY 1,2 ORDER BY 3 DESC;
```

| Etapa hoje | Motivo | Qtd | % |
|---|---|---:|---:|
| `transferido_humano` | **`outbound_manual_sdr`** | **22** | **51%** |
| `aguardando_ano` | (ativo) | 9 | 21% |
| `transferido_humano` | **BUG — "envio recusado: … está em 'concluido'"** | **4** | **9%** |
| `aguardando_formacao` | (ativo) | 4 | 9% |
| `transferido_humano` | "o LLM escolheu um horário que não foi oferecido (None)" | 1 | 2% |
| `transferido_humano` | "LLM indisponível ao oferecer a agenda" | 1 | 2% |
| `concluido` | (ativo) | 1 | 2% |
| `aguardando_atuacao` | (ativo) | 1 | 2% |

### 1.5 Desfechos

* **`concluido`: 1** — e mais 4 que **chegaram a `concluido` e foram jogados fora por um bug**
  (§1.5.1). Nos 5 casos a reunião era **pré-existente**, nunca marcada pelo agente.
* **`transferido_humano`: 28 (65%)**, dos quais só **2 são transferência legítima por falha do
  LLM**. Os outros 26 são: 22 do disparo em massa do SDR e 4 do bug abaixo.
* **`encerrado` (inatividade): 0.** Existem 43 ações `encerrar_inativo` pendentes e nenhuma
  executada — a régua é de 72 h e a operação tem 26 h.
* **Ativos no meio: 15 (35%)** — 9 em `aguardando_ano`, 4 em `aguardando_formacao`, 1 em
  `aguardando_atuacao`, 1 em `concluido`.

#### 1.5.1 O bug que está no ar agora: quem termina a qualificação recebe a despedida

**4 de 4 leads (100%)** que completaram a qualificação **com reunião já marcada** desde o
deploy das 14:50 UTC receberam, em vez da confirmação da reunião, o texto de fallback
`"Deixa eu te conectar com uma pessoa da nossa equipe…"` — e foram marcados como falha de
sistema, com notificação para a gestão.

A cadeia, verificada no log:

```
_avancar (aguardando_motivacao, reunião existe)
  -> _concluir(confirmar=True)
       estado.etapa = 'concluido'; await db.flush()          <-- grava ANTES de falar
       await _falar("Na verdade você já tem horário reservado: …")
            -> qualificacao_pode_atuar relê o estado -> 'concluido' -> RECUSA
            -> _falar chama _fallback("envio recusado: …")
                 -> etapa = transferido_humano + TEXTO_FALLBACK + notifica a gestão
```

```
2026-08-26T17:09:02  🔒 Agente não enviou (5537999965494): está em 'concluido', etapa em que o agente cala
2026-08-26T17:09:02  🛟 Agente transferiu 5537999965494 para humano: envio recusado: …
2026-08-26T17:09:03  🔔 Agente notificou user 5: Agente passou um lead para você
2026-08-26T17:09:03  ✅ Agente concluiu 5537999965494 (reunião 220)
```

**Origem exata:** o P0-D (`defa955`, 13:26 UTC) escreveu `await _enviar(...)` — que devolve
`(saiu, motivo)` e não faz fallback. Seis minutos depois o **P0-B (`b25d233`, 13:32 UTC)**
trocou por `await _falar(...)` no varrimento que fez "recusa nunca mais é silêncio". A troca
está certa em todos os outros pontos; **neste ela transformou um no-op num lead perdido.**

```
git log -L '/if confirmar and reuniao is not None/,+10:backend/app/qualificacao_fluxo.py'
#  b25d233  -        await _enviar(estado, (
#           +        await _falar(estado, (
```

O que a Amanda leu, às 14:09 SP, depois de contar a trajetória inteira:

> **agente 14:09:02** — "Perfeito — entendi que você busca ampliar conhecimento sobre TEA e expandir sua atuação clínica para o psicodiagnóstico de maneira crítica… Vou ver os horários disponíveis para sua reunião com a Victória Rodrigues."
> **agente 14:09:03** — "Deixa eu te conectar com uma pessoa da nossa equipe para seguir daqui, tá? 🙂"

Ela tem reunião dia 28/08 às 14:15 e nunca foi informada disso pelo agente. Mesma coisa com
Mikaelle (216), Marina (207) e Natália (222).

**Efeito colateral:** dos 6 avisos `agente_transferiu` que chegaram à gestão no período, **4
são este falso alarme** — 67% de ruído no único canal que deveria significar "o agente
falhou de verdade".

### 1.6 Tempos

```sql
-- medido em messages.timestamp (SP), NUNCA em created_at
```

| Métrica | n | p50 | p90 |
|---|---:|---:|---:|
| abertura → 1ª resposta do lead | 20 | **20,5 min** | 1 245,8 min (~21 h) |
| **inbound → resposta do agente** (quando responde) | 32 | **3,7 s** | **5,2 s** |
| abertura → desfecho (28 fechados) | 28 | 343 min | mín 1,9 min / máx 1 301 min |

**Quando o agente responde, ele responde em 3,7 s.** A latência não é problema em lugar
nenhum deste recon. O problema é quando ele **não** responde — §2.5.

### 1.7 Dados colhidos

| Campo | Preenchidos | Base honesta |
|---|---:|---|
| `formacao` | 36 / 43 (84%) | **33 vieram prontos da Exact** (T1+T2). Dos 10 leads T3 que precisavam ser perguntados, **3 responderam — e os 3 deram a formação (100% dos que responderam)** |
| `ano_conclusao` | 11 / 20 respondentes (55%) | |
| `atuacao` | 8 / 11 que deram o ano (73%) | |
| `motivacao` | 8 / 8 que deram a atuação (**100%**) | |
| `faixa_investimento` | 34 | vem da Exact, nunca da conversa; **o fluxo nunca lê** |
| `dados_extras` | 43 | `como_conheceu`, da Exact |

**Quem entra no roteiro, termina o roteiro.** A perda toda está antes: em não responder à
abertura, e em o agente calar no meio.

### 1.8 Reuniões

**Reuniões marcadas PELO agente: ZERO.**

Existem 3 tentativas reais, todas do mesmo lead (Fabiana, 5517997379129), todas paradas em
`passo='iniciado'` — morreram antes do `BoxesAdd`:

```sql
select id, nome, slot_inicio, passo, created_at from agendamentos
 where created_at>='2026-08-24 23:16' and origem_ip is null;
-- 194 | Fabiana Moreira | 2026-08-27 11:15 | iniciado | 2026-08-25 17:30:32
-- 196 | Fabiana Moreira | 2026-08-27 11:15 | iniciado | 2026-08-25 17:32:22
-- 197 | Fabiana Moreira | 2026-08-27 11:15 | iniciado | 2026-08-25 17:32:52
```

E a causa, no log — **não era a Exact, era o P0-A**:

```
2026-08-25T20:30:32  🛟 Agente transferiu 5517997379129 para humano: agendamento falhou
    (InvalidRequestError: Can't operate on closed transaction inside context manager…)
2026-08-25T20:30:32  ⚠️  Falha no roteamento de fluxo (wamid.…): InvalidRequestError: …
```

Isto corrige a nota "3 tentativas todas 502" de 25/08: **não houve 502.** O `_agendar`
operava numa transação que não era dele; a exceção derrubou o turno e **levou junto o próprio
`_fallback`** — por isso o estado dela ficou em `escolhendo_slot`, e não em
`transferido_humano`. Corrigido por `fe5b1c6` (P0-A), no ar desde 26/08 14:10 UTC, **ainda
sem um único caso real para provar que passou.**

Os 8 estados com `agendamento_id` apontam para reuniões **pré-existentes** (criadas na LP
antes da abertura — é justamente o que dispara o T1):

| Reunião | Consultora | Quando | Já aconteceu? |
|---|---|---|---|
| 201 | processoseletivo | 27/08 09:00 | futura |
| 205 | comercial | 28/08 10:30 | futura |
| 207 | processoseletivo | 26/08 14:15 | **já passou** |
| 209 | processoseletivo | 27/08 14:15 | futura |
| 216 | processoseletivo | 27/08 09:45 | futura |
| 218 | comercial | 27/08 17:15 | futura |
| 220 | processoseletivo | 28/08 14:15 | futura |
| 222 | comercial | 27/08 15:45 | futura |

Lembrete T-30 disparou 1 vez (Marina, reunião 207) e chegou (`read`).

---

## BLOCO 2 — leitura qualitativa

Foram lidas as transcrições completas das **20 conversas com resposta** (todas as concluídas,
todas as transferidas com conversa, e todas as paradas no meio com ≥1 inbound). As 23 sem
resposta são só abertura.

> Nota: **5583988046720 (Álefe) é o número de teste do próprio time** e aparece em várias
> medições; onde ele altera o número, está dito.

### 2.1 Perguntas do lead que o agente desviou ou respondeu mal

**Dentro das conversas que o agente conduziu, houve exatamente UMA pergunta de negócio.** Não
é um bom sinal — é a consequência de o funil morrer antes de chegar lá.

**Ivanise (5515998095653), 25/08 17:02**, depois de receber a grade de horários:

> **lead:** "Thiago ja entrou em contato comigo e me informou que a turma de pos em economia criativa fechou"
> **agente:** "Obrigado por avisar, Ivanise. Como você quer proceder: quer que eu passe seu contato para a consultora para checar vagas ou opções em outras turmas/cursos?"
> **lead:** "Nao, meu interesse é nessa pos mesmo, achei que poderia entrar, ja que iniciou na semana passada"
> **agente:** "Entendi, você quer a turma de Economia Solidária mesmo — vou tentar agendar uma conversa para checar isso com a consultora. Qual destes horários abaixo prefere…"

Três defeitos numa troca só: (a) o agente **não sabe se a turma fechou** — é exatamente o tipo
de fato que a base de conhecimento resolveria; (b) **pediu permissão** ("quer que eu passe…?"),
contra instrução explícita do próprio prompt; (c) desviou para a agenda sem responder.

**Bruna (5548998009934), 25/08 16:28** — pergunta feita na thread humana, antes da abertura,
e **nunca respondida por ninguém**:

> "Mas seria somente por ligação?"

**Como o funil não produziu volume de perguntas, o banco útil para a base de conhecimento
está nas threads conduzidas por humanos.** Varredura de 30 dias (`timestamp >= '2026-07-27'`,
inbound texto, excluídas as mensagens-gatilho da LP), classificada por regex de tema —
**159 perguntas**:

| # | Tema | Ocorrências |
|---:|---|---:|
| 1 | **Preço / investimento** | **37** |
| 2 | **Carga horária / ementa / duração** | **28** |
| 3 | **Formato: ao vivo × gravado, dias e horários de aula, plataforma** | **28** |
| 4 | **Pagamento / parcelamento / desconto / bolsa / ex-aluno** | **19** |
| 5 | **Material, acesso à plataforma, congressos inclusos** | **14** |
| 6 | **Matrícula / inscrição / erro no formulário** | **11** |
| 7 | **Por que é por ligação / o que é a reunião** | **9** |
| 8 | **Certificação / reconhecimento MEC** | **5** |
| 9 | **Pré-requisito / quem pode fazer** | **5** |
| 10 | **TCC / estágio / avaliação** | **3** |

*(classificação por primeira correspondência: uma mensagem que pergunta preço **e** carga
horária conta uma vez, em preço. Os números são piso, não teto.)*

Verbatim para a gestora validar a resposta oficial:

* **preço** — "Gostaria de saber o valor da pós graduação saúde mental, quando inicia se tem presencial ou é só online?"; "gostaria de saber o valor"
* **carga/ementa** — "Consigo ter acesso as ementas, carga horária e modalidade do curso?" seguido de **"Sem ter q falar com ninguém ao telefone?"**
* **formato/aulas** — "Quais são os dias que ocorrerão as aulas online?"; "Só dia de quinta-feira que ocorrerão as aulas online?"
* **desconto/ex-aluno** — "Vc não entendeu minha pergunta. Concluí a pós em Saúde Mental no Cenat e neste momento estou interessada nessa de Psicologia Escolar. **Recebo algum desconto por ser ex aluna?**"
* **material/congressos** — "Eu gostaria de saber como eu faço para ter acesso ao material?"; "Eu estou matriculada em uma pós-graduação do Cenat. E gostaria de saber se tenho acesso aos congressos on-line gratuitamente."
* **matrícula/erro** — "Não estou conseguindo me inscrever no curso. Aparece um erro de que não estou colocando meu número de WhatsApp…"
* **a ligação** — "Mas seria somente por ligação?"; "Bom dia, como será feita a conversa?"

**As respostas que a operação já usa estão nas mensagens dos SDRs** (`sent_by_ai=false`) e são
o rascunho pronto da base: *"a formação conta com 390 horas, duração…"*, *"estamos com 15% de
desconto até 31/08"*, *"até 31/08 comprando uma ganha a segunda pós"*, *"as aulas acontecem…"*.

### 2.2 Qualidade da validação de motivação

**Boa, e é o melhor pedaço do agente.** As 8 validações citam o conteúdo real, com as palavras
do lead:

> **Mikaelle:** "Que bacana, Mikaelle — você se interessou por saúde pública durante a graduação, fez estágio no CAPS e escreveu a monografia sobre políticas públicas e equipamentos de saúde."
> **Amanda:** "entendi que você busca ampliar conhecimento sobre TEA e expandir sua atuação clínica para o psicodiagnóstico de maneira crítica; é uma motivação super pertinente ao curso."
> **Fabiana:** "Entendi: você está migrando de profissão e tem um emprego em vista em um hospital de saúde mental — faz sentido buscar essa pós para apoiar essa transição."

Nenhum "que interessante" genérico em 8 casos.

**O ruim é quando a entrada não faz sentido e o agente valida assim mesmo** (Marina, 15:35):

> **lead:** "A necessidade do parcialmente"
> **agente:** "Entendi que o que despertou seu interesse foi *"a necessidade do parcialmente"*."

Não há caminho para "não entendi, me explica melhor?" — o modelo **sempre** dá `etapa_cumprida`
e ecoa.

### 2.3 Tom e naturalidade

```sql
select case when content like 'Perfeito%' then 'Perfeito…' when content like 'Entendi%' then 'Entendi…'
            when content like '%Ótimo%' then 'Ótimo…' when content like 'Que bacana%' then 'Que bacana…'
            else 'outro' end, count(*)
from messages where nat_etapa='qualif_conversa' and direction='outbound' group by 1;
```

| Fórmula de abertura | Qtd | % das 41 falas |
|---|---:|---:|
| "Perfeito…" | 12 | 29% |
| "Entendi…" | 10 | 24% |
| "Ótimo…" | 3 | 7% |
| "Que bacana…" | 1 | 2% |
| outro | 15 | 37% |

**54% das falas começam com "Perfeito" ou "Entendi".** Comprimento: média 171 caracteres
(mín 45, máx 445) — bom para WhatsApp.

**Eco robótico**, presente e visível: *"Perfeito — você atua como psicólogo."*, *"Entendido —
você atua como formanda em 2023."* (esta última é o agente confundindo o ano com a atuação).

**Duplicação de mensagem sob rajada** — o mesmo lead escrevendo em sequência gera dois turnos
concorrentes e duas perguntas quase iguais (Marina, 26/08):

```
15:34:23 agente: "Entendi: você atua em um empreendimento e faz atendimentos domiciliares. O que despertou seu interesse…"
15:34:31 lead:   "E em locais"
15:34:36 agente: "Você mencionou que atende em domicílio e em locais — ótimo contexto. O que despertou seu interesse…"
```

**O agente responde a reactions de emoji como se fossem mensagem.** Marina reagiu (sem texto)
às 14:30 e recebeu *"Marina, você concluiu a graduação em que ano?"*; reagiu de novo e recebeu
a mesma pergunta reescrita 4 minutos depois.

### 2.4 Oferta de agenda

**Só existiram 2 ofertas em todo o período, ambas em 25/08, ambas ANTES do P3-B.** As duas
listaram **14 horários** — a missão pede no máximo 5:

```sql
select contact_wa_id, timestamp, (length(content)-length(replace(content,'/2026 às','')))/8 n_slots
from messages where nat_etapa='qualif_conversa' and content like '%/2026 às%';
-- 5515998095653 | 2026-08-25 17:01:26 | 14
-- 5517997379129 | 2026-08-25 17:29:04 | 14
```

**Depois do P3-B entrar no ar (26/08 14:10 UTC): ZERO ofertas.** O corte de 5 slots está no
código e coberto por teste, mas **não tem nenhuma medição em produção** — porque desde então
todos os que chegaram ao fim do roteiro já tinham reunião marcada e caíram no bug de §1.5.1.

**As duas leads entenderam a oferta e escolheram na primeira tentativa.** As duas foram
perdidas mesmo assim:

* **Ivanise** escolheu "14h15 de 26/08" — um horário **que estava na lista** — e o LLM não
  conseguiu mapear para um `slot_id`: `"o LLM escolheu um horário que não foi oferecido (None)"`
  → transferida.
* **Fabiana** escolheu 3 vezes ("27:08 - 11:15", "27/08 às 11:15", "27/08/2026 às 11:15"),
  o agendamento morreu no P0-A nas 3 e ela **nunca recebeu resposta nenhuma** — até levar, 21 h
  depois, um template dizendo que tentamos ligar e não conseguimos.

**2 de 2 ofertas terminaram em lead perdido.** Nenhuma por desinteresse.

### 2.5 Abandonos — e o padrão

O padrão não é o lead sumir depois de uma pergunta. **É o agente sumir.**

```sql
-- inbound recebido com o estado AINDA ATIVO e sem outbound nos 3 min seguintes
```

**16 episódios, 8 leads** (7 reais + o número de teste). Nenhum deles é "o lead parou de
responder".

| Lead | Etapa | O que ele escreveu | Espera até QUALQUER resposta |
|---|---|---|---|
| Fabiana (…379129) | escolhendo_slot | "27:08 - 11:15" / "27/08 às 11:15" / "27/08/2026 às 11:15" | 1 274–1 276 min |
| Ronaldo (…307979) | aguardando_ano | "Olá, em 2023" / "Olá, me formei em 2023" | 979–1 065 min |
| Hosmana (…028910) | aguardando_ano | "Ciências Biológicas" | 327 min |
| Bruna (…009934) | aguardando_atuacao | "2014" | 311 min |
| Erica (…703419) | aguardando_ano | "Bom dia!" / "Formação em Psicologia" | **NUNCA** |
| Amanda P. (…336280) | aguardando_atuacao | "Bom dia! Conclui a graduação em 2022" | **NUNCA** |
| Evelyn (…718388) | concluido | "Obrigada 😃" | **NUNCA** |
| Ivanise (…095653) | escolhendo_slot | "14h15 de 26/08" | **NUNCA** |

**Causa raiz — e são três, todas nomeáveis:**

**(a) A janela de 24 h calculada sem tolerância ao 9º dígito — 17h40 de fix parado na
prateleira.** O log da manhã de 26/08 mostra o mecanismo:

```
2026-08-26T12:36:24  🔒 NAT não enviou (qualif_conversa → 5598984703419): template 'qualif_conversa'
    não pode ser montado sem inventar dado do lead (formação ausente e janela de 24h fechada)
2026-08-26T12:36:28  ➡️  Agente: 5598984703419 aguardando_formacao → aguardando_ano
```

O lead escreveu **7 segundos antes** — a janela estava aberta. Mas o agente envia para a
grafia de 13 dígitos e o inbound foi gravado com 12:

```sql
select distinct contact_wa_id, direction from messages
 where contact_wa_id in ('5598984703419','559884703419');
-- 559884703419  | inbound      <-- 12 digitos
-- 5598984703419 | outbound     <-- 13 digitos
```

`61fa16f` conserta exatamente isso e foi commitado em **25/08 20:31 UTC**. O processo em
produção era o **PID 1593018, no ar desde 25/08 19:19:53 UTC**, e só foi reiniciado em
**26/08 12:59:33**. **17 h 40 min** com o fix escrito, testado, commitado — e não deployado.
Vítimas: Erica, Amanda P., Bruna, Hosmana, Evelyn e Marina.

**(b) O teto de 20 envios/hora, quando ainda valia para conversa** (25/08, pré-P1-B):

```
2026-08-25T20:31:59  🔒 Agente não enviou: teto de envios/hora estourado (20/20)
```

```sql
-- contagem MOVEL de 1h no instante em que a Fabiana escolheu o horario
-- 25/08 17:30 SP -> 20 ; 17:40 -> 20 ; 17:45 -> 20   (teto = 20)
```

**(c) O P0-A** (§1.8), que derrubou o turno **e** o `_fallback` da Fabiana três vezes.

(a) e (b) estão corrigidos e no ar. (c) está corrigido e no ar, **sem caso real ainda**.

### 2.6 Casos de honestidade — "é robô?"

```sql
select … where content ~* '(rob[ôo]|\mbot\M|intelig[êe]ncia artificial|\mIA\M|chatgpt|
                           pessoa de verdade|pessoa real|falar com (um|uma|algu)|[ée] autom[áa]tic)'
-- (0 rows)
```

**Ninguém perguntou.** Em 26 h e 20 conversas, zero suspeitas verbalizadas. Não é prova de que
a Nat passa despercebida, mas nenhum lead levantou a questão.

### 2.7 Três defeitos de identidade que só aparecem lendo as transcrições

**(i) Curso vazio na abertura — 2 de 2 leads da LP (100%):**

```
"Vi que você aplicou para a nossa Pós-Graduação em . Antes de te mostrar os horários…"
```

`_curso()` (`qualificacao_fluxo.py:411`) lê `sub_source` **só** de `exact_leads`. O lead da LP
ainda não foi sincronizado quando a abertura sai:

```sql
select exact_id, sub_source, synced_at from exact_leads where exact_id=51571878;
-- 51571878 | Pos TEA V3 | 2026-08-27 00:19:53   <-- abertura saiu 26/08 14:55 UTC
```

`_nome()` já resolve o mesmo problema com uma segunda fonte (`_identidade_do_lead` cai em
`agendamentos`); `_curso()` não tem esse segundo passo — e `agendamentos.sub_source` tem o
dado desde o instante do formulário. Quando a janela está fechada o guard de parâmetro em
branco pega e **recusa a abertura inteira** (2 ocorrências, `#131008` local); quando está
aberta, sai o texto com o buraco.

**(ii) Nome do perfil do WhatsApp ganha do nome do cadastro:**

```sql
select wa_id, name from contacts where wa_id='5511940718388';
-- 5511940718388 | Eve 🍒🦖🤞
```

O lead se chama **Evelyn Renata Begliomini Manfrim** em `exact_leads` **e** em `agendamentos`.
`_nome()` prefere `contacts.name` e a abertura saiu **"Olá, Eve!"**. A ordem das duas fontes
está invertida: o perfil do WhatsApp é apelido, o cadastro é nome.

**(iii) Três leads no mesmo telefone, e nenhum lado sabe do outro:**

```sql
select exact_id, name, sub_source, register_date from exact_leads where phone1='5582998307979';
-- 51550694 | Paulo Martind | Pos Enfermagem em Saude Mental | 25/08 21:04
-- 51544032 | Ronaldo Cesar | Pos Saude do Trabalhador      | 25/08 14:59
-- 51543718 | Ronaldo Cesat | Pos Saude do Trabalhador      | 25/08 14:23
```

O agente abriu como **"Olá, Paulo!… Pós-Graduação em Enfermagem em Saúde Mental"**; o SDR
disparou template para **"Ronaldo… Saúde Mental do Trabalhador"**. Mesmo aparelho, mesmo dia.
Ele respondeu duas vezes ("Olá, em 2023" / "Olá, me formei em 2023") e não teve resposta.

---

## BLOCO 3 — saúde residual

Recorte: **desde o deploy atual, 26/08 14:50:44 UTC** (PID 1605282, código `a55bc01`).
8 552 linhas de log analisadas.

### 3.1 Turnos com falha de contrato

**Zero desde o P0-E no ar.** E o canal foi verificado antes de afirmar isso:

```bash
python -c "from uvicorn.config import LOGGING_CONFIG; import logging, logging.config; \
           logging.config.dictConfig(LOGGING_CONFIG); log=logging.getLogger('agente.llm'); \
           print(log.isEnabledFor(logging.INFO), log.isEnabledFor(logging.WARNING))"
# False True
```

`log.warning` (FORA DO CONTRATO) e `log.error` (esgotou) **chegam** ao journald pelo
`lastResort`. Zero linhas ⇒ zero falhas de contrato. **A causa indeterminada de 26/08 10:11
não reapareceu** (era o PID 1600810, antes do P0-E; o log dela ainda é o formato velho:
`⚠️ Agente/LLM: resposta fora do contrato (tentativa 1/2)`, sem motivo).

### 3.2 `ofertar_agenda` normalizada — **NÃO MEDÍVEL HOJE**

A linha `🏷️ LLM devolveu 'ofertar_agenda' (obsoleta…)` e a linha de turno bem-sucedido
`🧠 LLM %s | acao=%s …` são **`log.info`**. O uvicorn não instala handler para o root logger e
o `lastResort` só emite a partir de WARNING — **as duas são descartadas antes de sair do
processo**:

```
grep -c '🧠 LLM' log.txt     -> 0     (e o agente rodou ~10 turnos nesse período)
grep -c 'acao='  log.txt     -> 0
```

**A instrumentação criada no P0-E precisamente para responder "com que frequência o modelo
devolve `ofertar_agenda`?" está muda.** O `echo=False` do P1-A (correto, e que resolveu 4 GB
de journald) removeu o único handler que fazia o INFO aparecer por acidente. O que falta é uma
linha de `logging.basicConfig`/`dictConfig` no boot, ou promover essas duas linhas a WARNING.

### 3.3 Disparos do `vigiar_resposta`

```sql
select kind, status, count(*) from nat_scheduled_actions where kind='vigiar_resposta' group by 1,2;
-- vigiar_resposta | cancelado | 17
```

**17 armados, 17 cancelados, 0 disparos. Zero falsos positivos e zero verdadeiros.** Todos os
17 são de 3 leads (Mikaelle, Amanda C., Marina) — os únicos com inbound depois de 14:50 UTC.
O vigia funciona (arma e cancela no `enviar_nat`, como projetado), mas **26 h de operação e 3
leads não são amostra**. Nota importante: **ele não teria pegado nenhum dos 16 episódios de
silêncio de §2.5** — todos aconteceram antes de ele existir.

### 3.4 Skips do scheduler, por motivo

```sql
select kind, status, left(motivo,60), count(*) from nat_scheduled_actions
 where created_at >= '2026-08-24 23:16' and motivo is not null group by 1,2,3;
```

| Kind | Status | Motivo | Qtd | Quando |
|---|---|---|---:|---|
| `iniciar_qualificacao` | skipped | `Meta recusou: (#131008) Required parameter is missing` | **6** | 25/08 16:22 → 26/08 09:36 SP — **todos antes** do deploy de `80358e5` (26/08 09:59 SP) |
| `iniciar_qualificacao` | skipped | `template … com parâmetro(s) [2] em branco` (o **curso** vazio, §2.7-i) | **2** | 26/08 15:30 e 18:29 SP — **depois** do deploy |
| `iniciar_qualificacao` | skipped | `já tem estado (aguardando_formacao)` | 1 | benigno |
| `iniciar_qualificacao` | pendente/cancelado | `fora do horário comercial (18:36 / 18:58 / 20:32 / …)` | 6 | reagendados para 27/08 09:00 |

**O `#131008` remoto acabou** e virou recusa local e legível — o `80358e5` fez o que prometeu.
Mas as 2 recusas novas são o **curso**, não o nome: uma classe que o fix não cobre.

### 3.5 Infra

`QueuePool` esgotado: **0**. Tracebacks: **0**. `Falha no roteamento`: **0**.
`echo=True` fora do log confirmado (0 linhas de `sqlalchemy.engine` após 14:50). P1-A e P0-C
sem um único acionamento — o que aqui é a boa notícia.

---

## RELATÓRIO FINAL

### 1. O funil, e as 3 maiores perdas

| # | Etapa | Qtd | % dos 43 | Retenção do passo |
|---|---|---:|---:|---:|
| 1 | Estados criados | 43 | 100% | — |
| 2 | Abertura entregue | 42 | 98% | 98% |
| 3 | **Respondeu à abertura** | **20** | **47%** | **48%** |
| 4 | Deu ≥1 dado novo **na conversa** | 13 | 30% | 65% |
| 5 | Completou o roteiro (motivação) | 8 | 19% | 62% |
| 6 | Recebeu oferta de agenda | 2 | 5% | 25% |
| 7 | Escolheu um horário | 2 | 5% | 100% |
| 8 | **Reunião marcada pelo agente** | **0** | **0%** | **0%** |

**Perda #1 — 23 leads (53%) nunca responderam à abertura.**
Hipótese: **é o conteúdo da abertura, não a entrega** (98% chegou). O contraste é o dado:
T1, que **afirma** a reunião marcada e a consultora, responde **88%**; T2, que abre pedindo o
ano de conclusão, responde **39%**; T3, que abre pedindo a formação, **30%**. Quem recebe valor
antes da pergunta responde; quem recebe um formulário, não. Reforçam a hipótese os 2 casos de
abertura com **"Pós-Graduação em ."** (100% dos leads da LP) e o "Olá, Paulo!" para o Ronaldo.

**Perda #2 — 22 leads (51% de TODO o funil) mortos por um disparo em massa do SDR.**
Em 60 segundos, 26/08 14:46:49 → 14:47:42 SP, um template de recuperação foi para ~30 contatos
e a trava automática silenciou o agente em 22 deles:

```
2026-08-26T17:46:51  🤝 Agente silenciado em 5517997379129: escolhendo_slot → transferido_humano
                        (motivo=outbound_manual_sdr, por Thobias)     … ×22
```

Nove estavam em `aguardando_ano`, um estava em **`escolhendo_slot`** (a Fabiana, com o horário
já escolhido). O texto que receberam:

> "Olá Fabiana, tudo bem? 🌻 Fiz uma nova tentativa de contato, **mas ainda sem sucesso**, essa ligação é a primeira etapa do seu processo seletivo… Qual o melhor horário para te retornar?"

…enquanto conversavam por escrito, no mesmo aparelho, minutos antes. A trava está **certa**
(humano assumiu ⇒ agente cala). O que está errado é **disparo em massa não distinguir de
atendimento individual**, e a lista da campanha não excluir quem tem conversa viva.

**Perda #3 — 8 dos 20 respondentes (40%) bateram no silêncio do agente.**
Três causas nomeadas em §2.5: a janela de 24 h sem tolerância ao 9º dígito (**17 h 40 com o
fix commitado e não deployado** — a maior causa isolada), o teto de 20/h aplicado à conversa, e
o P0-A. As três estão corrigidas e no ar; **nenhuma tem confirmação em produção ainda**.

**Perda #4, nova e ATIVA agora — 4 de 4 (100%) que terminaram a qualificação com reunião
marcada foram despedidos em vez de confirmados** (§1.5.1). Não estava na lista das 3 maiores
porque só existe desde ontem às 13:32 UTC — mas é a única que continua acontecendo hoje.

### 2. Top-10 temas para a gestora comercial validar

Formato pronto para levar. Base: 159 perguntas de leads em 30 dias (§2.1); a coluna "onde já
existe resposta" aponta para o que os SDRs já respondem à mão hoje.

| # | Tema | N | Pergunta-tipo (verbatim) | Onde já existe resposta |
|---:|---|---:|---|---|
| 1 | Preço / investimento | 37 | *"gostaria de saber o valor"* | mensagens do SDR; régua R$100/200/300 |
| 2 | Carga horária / ementa / duração | 28 | *"Consigo ter acesso as ementas, carga horária e modalidade do curso?"* | *"a formação conta com 390 horas, duração…"* |
| 3 | Formato: ao vivo × gravado, dias/horários, plataforma | 28 | *"Quais são os dias que ocorrerão as aulas online?"* | *"as aulas acontecem…"* |
| 4 | Pagamento / parcelamento / desconto / ex-aluno | 19 | *"Recebo algum desconto por ser ex aluna?"* | *"15% de desconto até 31/08"*, *"comprando uma ganha a segunda pós até 31/08"* |
| 5 | Material / acesso / congressos inclusos | 14 | *"tenho acesso aos congressos on-line gratuitamente?"* | — **sem resposta padronizada** |
| 6 | Matrícula / inscrição / erro no formulário | 11 | *"Aparece um erro de que não estou colocando meu número de WhatsApp"* | — **é suporte, não venda** |
| 7 | Por que é por ligação / o que é a reunião | 9 | *"Mas seria somente por ligação?"* / *"Sem ter q falar com ninguém ao telefone?"* | *"são conversas bem objetivas…"* |
| 8 | Certificação / reconhecimento MEC | 5 | *"por essa promoção, eu tenho acesso aos certificados dos congressos?"* | — **sem resposta padronizada** |
| 9 | Pré-requisito / quem pode fazer | 5 | *"Posso fazer?"* | — |
| 10 | TCC / estágio / avaliação | 3 | — | — |
| **+** | **Status da turma (aberta/fechada/quando começa)** | (não classificável por regex) | *"Thiago… me informou que a turma de pos em economia criativa fechou"* — **o agente não soube responder** | — **é dado vivo, não texto fixo** |

O item extra não tem contagem porque a pergunta chega em mil formas, mas é o único caso real
em que o agente foi confrontado com um fato de negócio e desviou. **Turma aberta/fechada é
estado, não conteúdo** — se entrar na base como texto, envelhece em uma semana.

### 3. Melhorias propostas, por impacto no funil — **NADA IMPLEMENTADO**

| # | Melhoria | Evidência | Tamanho | Risco |
|---:|---|---|---|---|
| **1** | **Não transferir quem acabou de concluir.** Em `_concluir`, mandar a confirmação **antes** de gravar `etapa='concluido'`, ou enviá-la com `guard_de_despedida`/`guard_de_abertura` (como `lembrete_reuniao` e `concluir_por_agendamento_externo` já fazem). | §1.5.1 — 4/4 leads, todos com reunião real, receberam a despedida; 4 dos 6 alarmes da gestão são falsos | **código**, ~3 linhas + teste | **baixo**. É reordenar o que já existe; a assimetria com os outros dois caminhos é o próprio bug |
| **2** | **Excluir do disparo em massa quem tem estado ativo do agente** — e, se o SDR insistir, exigir confirmação explícita por lead. | §Perda #2 — 22 de 43 (51%), inclusive uma lead com horário já escolhido, recebendo "tentei ligar e não consegui" | **código** (filtro na rota de bulk-send) + combinado com o time | **médio**. Muda o comportamento de uma ferramenta que o SDR usa todo dia; precisa da gestora |
| **3** | **Trocar a abertura T2/T3: afirmar antes de perguntar.** Dar ao lead, na primeira mensagem, o que o T1 dá — o que vem a seguir e por quê — antes da primeira pergunta. | §1.2 — T1 **88%** × T2 **39%** × T3 **30%** de resposta, com entrega igual (98%) | **template Meta** (aprovação) + `nat_copy` | **médio**. Template novo leva aprovação da Meta; e T1/T2/T3 não são grupos aleatórios (T1 já tinha comprado a reunião) — o ganho é hipótese, não certeza |
| **4** | **Base de conhecimento no prompt** — os 4 primeiros temas de §2 cobrem 112 das 159 perguntas (70%). | §2.1 — hoje o agente desvia a única pergunta de negócio que recebeu; o funil ainda não gerou volume porque morre antes | **missão/prompt** + tabela de FAQ | **médio-alto**. LLM afirmando preço e desconto errado é pior que não responder. Exige texto **validado pela gestora**, versionado, e uma saída explícita "não sei, vou confirmar" |
| **5** | **`_curso()` com segunda fonte** (`agendamentos.sub_source`), espelhando o que `_nome()` já faz. | §2.7-i — 2/2 leads da LP com **"Pós-Graduação em ."**, mais 2 aberturas recusadas por parâmetro em branco | **código**, ~5 linhas | **baixo**. Padrão já existente no mesmo arquivo |
| **6** | **Inverter a ordem de `_nome()`**: cadastro primeiro, perfil do WhatsApp como fallback. | §2.7-ii — **"Olá, Eve!"** para Evelyn Renata; `contacts.name` é `"Eve 🍒🦖🤞"` | **código**, ~4 linhas | **baixo**, mas medir: `_nome()` existe porque `contacts.name` vazio derrubava a abertura (#131008). Inverter não pode reintroduzir vazio |
| **7** | **Ignorar `reaction` como gatilho de turno** e coalescer inbounds em rajada (janela de ~5 s). | §2.3 — Marina recebeu a mesma pergunta 2× por reagir com emoji, e 2 perguntas quase idênticas em 13 s | **código** (roteamento do webhook) | **médio**. Coalescer mexe na precedência do webhook, que é onde mais dói errar |
| **8** | **Desligar o INFO mudo**: `dictConfig` no boot com handler no root, ou promover a WARNING as duas linhas do P0-E. | §3.2 — a instrumentação feita para contar `ofertar_agenda` **não sai do processo**; 0 linhas `🧠 LLM` com ~10 turnos rodados | **código**, ~6 linhas | **baixo**, com um porém: foi `echo=True` que encheu 4 GB de journald. Handler no root sem filtrar `sqlalchemy.engine` traz o problema de volta |

**Fora da lista, e de propósito:** mexer no `ofertar_agenda` do enum (não há número que
justifique — §3.2), e o corte de 5 slots do P3-B (já está no código; falta caso real).

### 4. O que não foi medível — e o que faltou instrumentar

| Não medível | Por quê | O que instrumentar |
|---|---|---|
| **Frequência de `ofertar_agenda` e de qualquer turno bem-sucedido do LLM** | `log.info` descartado antes de sair do processo (§3.2) | handler no root logger, **filtrando `sqlalchemy.engine`** |
| **Trajetória de etapas de um lead** | `nat_qualificacao_state.etapa` guarda só o estado atual. Toda a §1.4 é **inferida** dos campos preenchidos | tabela de eventos de etapa (1 linha por transição), ou `dados_extras.trilha` |
| **"Onde o lead abandonou"** de verdade | Não houve abandono por desinteresse em nenhuma das 20 conversas — os 16 casos são silêncio do agente. **A pergunta não pôde ser respondida por falta de caso, não por falta de dado** | — |
| **Slots por oferta pós-P3-B** | Zero ofertas desde o deploy (§2.4) | — (é volume, não instrumentação) |
| **Se o agente marca reunião** | Zero marcações; 3 tentativas, todas mortas no P0-A antes do `BoxesAdd` (§1.8) | — |
| **Vigia: verdadeiro × falso positivo** | 17 armados, 17 cancelados, 0 disparos, 3 leads (§3.3) | — |
| **Custo/tokens por conversa** | `_uso()` só aparece nas linhas de turno, que são INFO | mesmo fix do item 1 |
| **Por que o lead não respondeu à abertura** | Temos `read` × `delivered` da Meta, e nada além. 19 leram e não responderam | nada barato; é pesquisa, não telemetria |

---

## ANEXO A — `base.sql` (as CTEs usadas em todo o Bloco 1)

```sql
WITH est AS (
  SELECT s.*, s.created_at - interval '3 hours' AS criado_sp,
         CASE WHEN length(regexp_replace(s.contact_wa_id,'\D','','g')) IN (12,13)
                   AND regexp_replace(s.contact_wa_id,'\D','','g') LIKE '55%'
              THEN substr(regexp_replace(s.contact_wa_id,'\D','','g'),3,2)
                   || right(regexp_replace(s.contact_wa_id,'\D','','g'),8)
              ELSE regexp_replace(s.contact_wa_id,'\D','','g') END AS chave
  FROM nat_qualificacao_state s
),
msg AS (   -- mesma expressao de chave sobre messages
  SELECT m.*, CASE WHEN length(regexp_replace(m.contact_wa_id,'\D','','g')) IN (12,13)
                        AND regexp_replace(m.contact_wa_id,'\D','','g') LIKE '55%'
                   THEN substr(regexp_replace(m.contact_wa_id,'\D','','g'),3,2)
                        || right(regexp_replace(m.contact_wa_id,'\D','','g'),8)
                   ELSE regexp_replace(m.contact_wa_id,'\D','','g') END AS chave
  FROM messages m
),
abertura AS (            -- a PRIMEIRA abertura de cada estado
  SELECT DISTINCT ON (e.id) e.id AS est_id, m.nat_etapa, m.status, m.timestamp AS ts
  FROM est e JOIN msg m ON m.chave = e.chave
  WHERE m.nat_etapa IN ('nat_abertura_agendado','nat_abertura_qualificacao',
                        'nat_abertura_sem_formacao')
    AND m.timestamp >= e.criado_sp - interval '5 minutes'
  ORDER BY e.id, m.timestamp
),
resp AS (                -- o PRIMEIRO inbound de texto apos a abertura
  SELECT DISTINCT ON (a.est_id) a.est_id, m.timestamp AS ts
  FROM abertura a JOIN est e ON e.id=a.est_id JOIN msg m ON m.chave = e.chave
  WHERE m.direction='inbound' AND m.message_type='text' AND m.timestamp > a.ts
  ORDER BY a.est_id, m.timestamp
)
```

Sanidade: `43 estados / 43 aberturas / 20 respostas` — a mesma contagem que
`select count(*) from nat_qualificacao_state` e que os 43 outbounds de abertura em `messages`.
