# Prompt-base — Bloco A do espontâneo · **para revisão, sem código**

**29/08/2026.** Item 3 das autorizações. **Nada foi implementado.** Este documento é o
desenho para você revisar antes de qualquer linha — e traz três coisas que só apareceram ao
conferir o código e o banco, e que mudam o desenho de 25/08.

Base: `SPRINT_ESPONTANEO_20260825.md` (o desenho original, que continua de pé) e
`RECON_VAO_ESPONTANEO_20260829.md` (a medição que justifica a prioridade).

---

## 0. Antes de tudo — a resposta sobre o `subSource`

**Você perguntou se `Espontaneo WhatsApp` existe na allowlist da Exact. A pergunta tem uma
premissa errada, e ela é a parte importante: a Exact não tem allowlist.**

`LeadsAdd` **cria** o subSource quando o valor não existe. Isso foi medido, não suposto — o
cabeçalho de `app/agendamento/origens.py` registra o teste que virou `DialogicasTurma` no
**id 176793**, o mais alto de toda a base, e **não há endpoint para remover**. O cadastro de
origens é global e alimenta relatório de marketing.

A allowlist é **nossa**, e é a única coisa entre uma página pública e o cadastro da Exact:

```
AGENDAMENTO_SUBSOURCES="PosMulheridades,Pos Grupos e Oficinas T2,Pos Infantojuvenil EAD,
  Pos Psicologia na RAPS T3,Pos Psicologia Hospitalar,Pos Suicidio e Luto T3,
  Pos Psicologia Escolar,Pos Alcool e Drogas T4,Pos Psicologia Clinica T2,
  Pos Gestao Psicossocial T5,Pos TEA V3,Pos Saude do Trabalhador,
  Pos Enfermagem em Saude Mental,Pos Direitos Humanos T4"        (14 valores, todos `Pos …`)
AGENDAMENTO_SOURCE="Landing Page"
```

**Estado conferido hoje no banco:** `Espontaneo WhatsApp` **não existe** — zero leads com
`sub_source ILIKE '%espont%'`, e a tabela `nat_agendamento_token` está **vazia** (o Bloco B
foi construído e nunca emitiu um token). O §10 do sprint de 25/08 dizia *"o usuário cria hoje
de manhã"*; isso não aconteceu, e o desenho segue esperando por ele.

**Então: você não precisa criar nada na Exact — e é justamente por isso que a decisão é sua.**
O primeiro booking espontâneo CRIA o cadastro, e ele é permanente. O que eu preciso de você
são duas decisões, não uma:

| # | Decisão | Por que ela não é minha |
|---|---|---|
| **A** | O nome vai ser mesmo `Espontaneo WhatsApp`? | É irreversível e aparece em relatório de marketing. Sem acento e sem espaço (`EspontaneoWhatsApp`) seria mais consistente com `PosMulheridades` e `posgenerot2`; com espaço é mais legível e o `.env` já lida com isso (aspas, e a vírgula é o separador). **Não tenho preferência técnica — só não dá para desfazer.** |
| **B** | Sob qual `source` ele nasce? | Um subSource pertence a **um** source. Hoje `AGENDAMENTO_SOURCE="Landing Page"`. Um lead que escreveu no WhatsApp sem preencher formulário **não veio de landing page** — pendurá-lo ali mente no relatório, e apontar para o par errado cria cadastro novo do mesmo jeito. Se a resposta for um source novo (`WhatsApp`, por exemplo), ele também nasce por `LeadsAdd` e também é permanente. |

Depois que você decidir, a sequência do §6.2 de 25/08 continua valendo: acrescentar em
`AGENDAMENTO_SUBSOURCES` → restart → `GET /Sources` confirmando sob qual source nasceu → **o
primeiro booking real é o teste**. Até lá, o booking do espontâneo deve devolver **400** — que
é a falha correta.

---

## 1. Quanto isto atende, medido

Rodei as regras de admissão do desenho contra a janela inteira desde a ativação (24/08 20:16
SP → 29/08 17:41 SP), usando `chave_telefone` para a regra 2:

| | N |
|---|---:|
| Contatos cuja **primeira mensagem da vida** no Hub é um inbound da janela | **48** |
| — recusados pela **regra 2** (já têm lead em `exact_leads`) | 30 |
| **Admitidos** (regras 1, 2, 3 e 5) | **18** |
| — destes, chegam com o **texto do botão**, já nomeando o curso | **7** |

**≈3,6 admissões por dia**, distribuídas de forma quase plana (4 · 2 · 4 · 4 · 4). Nenhum dos
18 tinha uma única mensagem antes de 01/08 — a regra 1 é sólida, não uma aproximação.

A regra 2 barrar 30 de 48 é o desenho funcionando: são pessoas que já têm lead, e o dono
delas é a abertura da LP ou o SDR, não o espontâneo.

**O volume real é maior que os 18.** Os 12 do §3.2 do recon incluem gente com lead antigo
(Fabianne, Josiane de fev/2025) que a regra 2 recusa — corretamente, porque o espontâneo não
deve invadir conversa de quem o SDR já conhece. Mas hoje **ninguém** os atende. Essa
sobra é a régua de cadência, não o Bloco A, e continua sendo entrada futura.

---

## 2. O que muda em relação ao desenho de 25/08

O desenho original está de pé. Três acréscimos, e o primeiro é o que dá economia real.

### 2.1 O texto do botão é um atalho de duas missões — parcialmente

Sete dos 18 admitidos já dizem, na primeira mensagem, **que é pós** e **qual curso**. Para
eles, `esp_confirmando_interesse` e `esp_coletando_curso` perguntam o que a pessoa acabou de
informar. O desenho deve entrar direto em `esp_coletando_formacao`.

**As duas famílias, verificadas no banco** (normalizado sem acento/caixa):

```
prefixo A: "ola! tudo bem? fiz minha aplicacao ..."          38 mensagens na janela
prefixo B: "ola! tudo bem? manifestei interesse ..."          (intercâmbio/Trieste)
```

Casar por **prefixo**, não por regex do meio: há **5 formas** de citar a turma —
`na turma da`, `na turma 2 da`, `na turma 3 da`, `na turma 1 da da`, `na turma 3 da da`. O
`da da` é erro de template da LP e está literal no banco; qualquer regex que assuma uma forma
só perde casos.

**⚠️ Mas o curso não se resolve sozinho, e isto é o achado que trava o atalho.** O botão manda
o **nome completo** do curso; `course_aliases` guarda `alias → short_name`. Testei casar o
`short_name` como substring do texto do botão, sem tabela nova:

| | textos distintos | mensagens |
|---|---:|---:|
| **Casam** | 4 de 10 | **28 de 38 (74%)** |
| **Não casam** | **6 de 10** | 10 de 38 |

Os 6 que falham, nominalmente — e a razão de cada um importa:

* *Saúde Mental, Direitos Humanos e Populações Vulnerabilizadas* — `Pos Direitos Humanos T4`
  está na allowlist, mas **não tem linha em `course_aliases`**
* *Novas Abordagens em Saúde Mental: Autolesão, Comportamento suicida e Luto* — o short_name
  é `Autolesão, Suicídio e Luto`; **"Comportamento suicida" ≠ "Suicídio"**, substring não salva
* *Novas Abordagens em Saúde Mental e Boas Práticas do Cuidar* (EAD)
* *Saúde Mental, Economia Solidária, Arte e Cultura*
* *Boas Práticas em Saúde Mental nas Organizações e no Trabalho*
* *Psicologia na atenção psicossocial: Elementos para o trabalho*

**Consequência para o desenho:** o atalho é uma **otimização, nunca um caminho obrigatório**.
`esp_coletando_curso` continua sendo o fallback, e é ele que roda nos 26% que não casam. E o
sprint precisa de um passo antes: **6 aliases novos em `course_aliases`** (ou uma coluna de
nome completo), com um teste que trave os 10 textos reais medidos. Sem isso, o atalho acerta
3 em 4 e erra 1 em 4 — e errar o curso é justamente o defeito que o `ed163be` acabou de
consertar do outro lado.

### 2.2 Horário comercial não pode valer para quem escreveu

`qualificacao_fluxo.py:1008` adia **toda** abertura para 09h00–18h30, seg–sex. A justificativa
está certa para business-initiated. **Para o espontâneo ela é fatal**: a pessoa escreveu, a
janela de 24 h dela está aberta, e adiar até segunda entrega a mesma espera de 106 h que o
recon mediu.

**Metade dos casos medidos aconteceu fora da janela comercial** — sexta 20h, sábado 00h39,
sábado 11h24. Se o Bloco A subir sem isto, ele nasce mudo exatamente quando mais é preciso.

A distinção já existe no código, e o desenho deve **repetir a mesma regra, não inventar
outra**. `qualificacao_guard.py` (P1-B, 26/08) tirou o teto por hora da conversa com este
argumento:

> *ABERTURA = business-initiated. Nós escolhemos falar com alguém que não pediu nada. (…)
> CONVERSA = user-initiated. A pessoa ACABOU DE ESCREVER e está esperando. Não há risco de
> qualidade em responder a quem perguntou; há risco em não responder.*

O espontâneo é **inteiro** user-initiated. Proposta: a regra de horário fica onde está, valendo
para `iniciar_qualificacao`, e o fluxo espontâneo simplesmente **não passa por ela**. Nada de
flag nova nem de exceção condicional dentro do handler da abertura — são dois caminhos
diferentes, e misturá-los é o que criaria o próximo bug de precedência.

> **Isto abre uma pergunta que é sua, não minha:** com o Bloco A no ar, o agente passa a
> responder de madrugada e no fim de semana. É o comportamento certo para quem perguntou —
> mas é uma mudança visível de postura da marca. Se a preferência for uma janela mais larga
> em vez de 24/7 (por exemplo 07h–23h todos os dias), **é uma constante, e eu prefiro que ela
> venha de você.**

### 2.3 Os 7 sem lead são o alvo, e eles nunca vão ter gatilho

O recon mediu: das 12 pessoas que escreveram pelo botão e não receberam nada, **7 não existem
em `exact_leads`** (conferido por `phone1` e `phone2`, últimos 8 dígitos, contra 9.244 leads).
Elas não têm booking, não têm formulário, não têm lead. **Nenhum dos dois gatilhos existentes
pode alcançá-las** — o da LP nasce do booking, o do sync nasce do lead.

É o argumento inteiro do Bloco A, e vale dizer explicitamente no sprint: **ele não é uma
melhoria de cobertura, é o único caminho que existe para essa população.**

---

## 3. O prompt-base do sprint

> **Sprint — Bloco A do lead espontâneo.**
>
> **Contexto obrigatório de leitura:** `SPRINT_ESPONTANEO_20260825.md` (§2 admissão, §3
> máquina de etapas, §5 flag e travas), `RECON_ESPONTANEO_20260825.md`,
> `RECON_VAO_ESPONTANEO_20260829.md` (§3 e §4.3) e este documento.
>
> **Pré-requisito bloqueante:** `Espontaneo WhatsApp` (ou o nome que o coordenador decidir)
> precisa estar em `AGENDAMENTO_SUBSOURCES` e o `source` decidido. Enquanto não estiver, o
> booking do espontâneo devolve 400 — e o sprint pode ser inteiramente desenvolvido e testado
> assim, porque o 400 é a falha correta.
>
> **Entregar, nesta ordem:**
>
> 1. **`course_aliases`: 6 aliases novos** para os cursos do §2.1, mais um teste que trave os
>    **10 textos reais** de botão medidos em 24-29/08. Sem isto o passo 4 não é confiável.
> 2. **Admissão restritiva** — as 6 regras do §2 de 25/08, todas *fail-closed*, dentro de
>    `qualificacao_fluxo.processar_texto` e **não** num terceiro `if` em `main.py:490`
>    (aquele bloco existe para haver um dono por mensagem). Regra 2 por `chave_telefone`,
>    nunca por igualdade. Cada não-admissão vira log estruturado com motivo, nunca silêncio.
> 3. **Máquina de 4 etapas** `esp_*` — o CHECK de `nat_qualificacao_state` **já aceita as
>    quatro**; nada de migração de etapa. Desfechos reaproveitados (`concluido`,
>    `transferido_humano`, `encerrado`). Robô → `encerrado`; congresso/não-pós →
>    `transferido_humano`.
> 4. **Atalho do botão** — prefixo das duas famílias do §2.1; quando casar E o curso resolver,
>    entra direto em `esp_coletando_formacao`. Quando não casar, cai no fluxo completo.
>    **Nunca adivinhar o curso**: sem match, pergunta.
> 5. **Sem regra de horário comercial** neste caminho (§2.2), com o motivo no comentário.
> 6. **Teto duro por contato/hora** como rede contra loop de robô, além da regra 6. O teto
>    global (`max_envios_hora`) continua valendo.
> 7. **Emissão do token** reusando `nat_agendamento_token` (tabela pronta, vazia): um token
>    vivo por contato, `revogado_em` e `usado_em` como **dois fatos distintos** — o furo já
>    documentado no §4 de 25/08.
>
> **Travas de segurança que não se negociam:** `espontaneo_enabled` default `false`, eixo
> próprio; nada envia sem guard; toda busca de telefone por `variantes_wa_id`.
>
> **Testes:** admissão pelos 6 critérios (um caso por regra, todos fail-closed), robô que
> encerra, não-pós que transfere, atalho do botão nas 5 formas de citar turma, curso que **não**
> resolve (cai no fluxo completo), token válido/single-use/expirado, e o cenário de sábado
> 00h39 provando que o horário comercial **não** adia.
>
> **Fora de escopo, explicitamente:** régua de cadência para `esp_link_enviado`,
> reprocessamento dos 7 leads já carimbados, e qualquer mudança no caminho
> `iniciar_qualificacao`.

---

## 4. O que eu preciso de você antes de escrever código

1. **Nome do subSource** e **source** sob o qual ele nasce (§0, decisões A e B). É o único
   item verdadeiramente bloqueante — e é irreversível.
2. **24/7 ou janela larga** para o espontâneo (§2.2). Se for janela, qual.
3. **Os 6 aliases de curso** — eu proponho os nomes a partir dos textos reais medidos, mas o
   `short_name` é o que a pessoa vê na conversa, então prefiro que você confirme a redação.
4. **Confirmar que o atalho do botão pode pular duas missões.** Ele encurta a conversa para
   39% dos admitidos; o risco é assumir intenção de quem só clicou num botão. Meu voto é
   sim — o texto é explícito e a pessoa o enviou —, mas é decisão de produto.
