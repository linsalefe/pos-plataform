# RECON — desempenho do agente em 27/08 e 28/08 · passada de fechamento

**Somente leitura.** Nenhum envio, nenhuma escrita, nenhuma migração. Todo número vem com a
query ou o comando que o gerou.

Janela: **27/08 00:00 SP → 28/08 17:30 SP**. São **25 estados novos** — 19 em 27/08, 6 em
28/08 — e **33 turnos de LLM**. Amostra pequena, e toda leitura abaixo carrega esse N.

> **Relação com `RECON_DESEMPENHO_AGENTE_20260828.md`.** Aquele documento fechou a janela às
> **11:15 SP**. Este refaz a janela inteira e acrescenta as **6h seguintes**. Ele **confirma**
> os três achados de lá, **corrige um ponto** (§2.2 — a Daniela foi atendida, só que às 11:21,
> depois do corte daquela apuração) e **acrescenta quatro** — sendo um deles, o §1.5, mais caro
> que qualquer coisa já listada. Onde os dois divergem, vale este.

Convenção de fuso, reconferida: `messages.timestamp`, `transferido_em`,
`nat_scheduled_actions.run_at`, `encerrado_em` são **naive-SP**; `created_at` e o journald são
**UTC**.

---

## 0. O veredito curto

**O que a engenharia consertou continua consertado, e agora tem prova de dois dias.** Zero
silêncio do agente em etapa ativa, zero falhas de contrato em 33 turnos, zero esgotamento de
pool, zero 502, zero disparos de vigia (porque nenhum precisou disparar). O `encerrar_inativo`
começou a rodar hoje às 16:28 e **acertou o rótulo nos dois primeiros casos reais** — a
distinção `inatividade` × `sem_resposta_do_agente` deixou de ser teoria.

**E o funil segue vazando por fora do agente, em quatro pontos:**

1. **§1.5 — toda reunião marcada pelo agente entra na Exact com o curso ERRADO.** A Kaylla
   aplicou para TEA, conversou sobre TEA, e o box foi criado como `PosMulheridades`. Não é
   caso de borda: é **4 de 4** dos agendamentos que o agente já fez, por `origem=None` fixo no
   código. **Achado novo, e o de maior impacto comercial deste recon.**
2. **§1.3 — a abertura não sai para 1 em cada 5 leads da janela** (6 de 31). Confirmado, com
   uma boa notícia: parou às 09:47 e não houve caso novo nas 8h seguintes.
3. **§3.5 — o disparo em massa cortou 20 conversas ativas em 2 dias**, e *não* é só às 11h como
   a apuração das 11:15 concluiu: hoje cortou às 10:16, 11:07, 11:21, 11:49, 13:13, 13:46 e
   15:21.
4. **§1.6 — 2 de 15 lembretes marcados `executado` sem terem saído.** Confirmado, inalterado.

E um resíduo vivo: **§1.9 — o Marcos recebeu o mesmo disparo 4× e o agente nunca foi
silenciado nele.** O defeito que causou isso está corrigido desde as 11:04 SP; o estado dele
não foi.

---

## 1. Os números, por dia

### 1.1 Estados novos, entrega e resposta

```sql
-- CTEs est/msg/abertura/resp: ANEXO A
SELECT a.dia, a.origem, a.nat_etapa, count(*),
       count(*) FILTER (WHERE a.status IN ('read','delivered')),
       count(*) FILTER (WHERE a.status='failed'), count(r.est_id)
FROM abertura a LEFT JOIN resp r ON r.est_id=a.est_id WHERE a.dia>='2026-08-27' GROUP BY 1,2,3;
```

| Dia | Origem | Template | Estados | Entregues | `failed` | Responderam | % |
|---|---|---|---:|---:|---:|---:|---:|
| 27/08 | exact | **T1** `agendado` | 3 | 3 | 0 | 2 | **67%** |
| 27/08 | exact | **T2** `qualificacao` | 7 | 6 | **1** | 3 | 43% |
| 27/08 | exact | **T3** `sem_formacao` | 3 | 1 | **2** | 1 | 33% |
| 27/08 | lp | T2 | 5 | 5 | 0 | 1 | 20% |
| 27/08 | lp | T3 | 1 | 1 | 0 | 0 | 0% |
| **27/08 total** | | | **19** | 16 | 3 | **7** | **37%** |
| 28/08 | exact | T1 | 1 | 1 | 0 | 0 | 0% |
| 28/08 | exact | T2 | 2 | 2 | 0 | 1 | 50% |
| 28/08 | exact | T3 | 1 | 1 | 0 | 0 | 0% |
| 28/08 | lp | T2 | 2 | 1 | **1** | 1 | 50% |
| **28/08 total** | | | **6** | 5 | 1 | **2** | **33%** |

**A LP responde pior que a Exact**, e o segundo dia confirma: 8 estados de LP na janela, 2
responderam (25%); 17 da Exact, 7 responderam (41%).

As **7 falhas de entrega** da janela, por código:

| Quando | Número | Código | Título | Origem |
|---|---|---|---|---|
| 27 09:00 | `5571985252525` | 131026 | Message undeliverable | abertura T2 |
| 27 09:01 | `5567999151808` | **131049** | healthy ecosystem engagement | abertura T3 |
| 27 10:10 | `5527999805197` | **131049** | idem | abertura T3 |
| 27 17:47 | `5517992482143` | **131049** | idem | manual/SDR |
| 28 11:21 | `5524988477797` | **131049** | idem | manual/SDR |
| 28 12:53 | `5571983577808` | 131026 | Message undeliverable | abertura T2 |
| 28 15:53 | `554991442164` | 130472 | User's number is part of an experiment | manual/SDR |

**`131049` são 4 em 2 dias** — limite de engajamento da Meta por destinatário, metade nossa
(agente) e metade do disparo manual. Não é bug de código; é volume perdido que nenhuma
correção recupera, e vale à gestora.

### 1.2 Turnos do LLM — o contrato não falhou nenhuma vez

| | 27/08 | 28/08 | Janela |
|---|---:|---:|---:|
| Turnos (`🧠 LLM`) | **23** | **10** | **33** |
| `acao=nenhuma` | 22 | 10 | 32 |
| `acao=agendar_slot` | **1** | 0 | 1 |
| `etapa_cumprida=true` | 15 | 5 | 20 |
| Latência mediana | 1 431 ms | 1 612 ms | **1 455 ms** |
| p90 / máx | 2 023 / 6 590 ms | 2 377 / 2 584 ms | 2 334 / 6 590 ms |
| Prompt / resposta (tokens) | 1 373–2 028 / 59–183 | 1 381–1 884 / 60–152 | teto 1 000, **sem truncagem** |

* **Falhas de contrato: ZERO em 33 turnos.** Nenhum `🛟`, nenhum fallback, nenhum
  `LLM indisponível` (`grep -cE "🛟|LLM indisponível"` = 0).
* **`ofertar_agenda` obsoleta: ZERO** (`grep -c 🏷️` = 0). A dívida do enum segue existindo e
  segue inócua — medida, não presumida.

Distribuição por etapa: `aguardando_ano` 9, `aguardando_atuacao` 8, `aguardando_motivacao` 5,
`escolhendo_slot` 6, `ofertar_agenda` 4, `aguardando_formacao` 1.

> **Nota para quem lê log** (cosmético, mas atrapalha): o rótulo do turno usa **duas grafias
> do telefone** e **um nome de etapa que não existe no banco**. `qualificacao_fluxo.py:1115`
> escreve `rotulo=f"{estado.contact_wa_id}/ofertar_agenda"` (13 dígitos, etapa `ofertar_agenda`)
> enquanto o caminho do turno normal rotula com o wa_id do inbound (12 dígitos). A Clarice
> aparece como `553199818666` em 5 turnos e `5531999818666` em 1; a etapa real no banco é
> `ofertando_agenda`. Um `grep` pelo telefone perde metade dos turnos. Há **um** estado por
> pessoa (conferido) — é só o rótulo.

### 1.3 A abertura que não sai — confirmado, e parou às 09:47

```
$ journalctl | grep "contato não existe no banco"
27/08: 2 aberturas   28/08: 4 aberturas   (+1 lembrete, §1.6)
```

| Dia | `iniciar_qualificacao` executadas | `skipped` | Total agendado | % perdido |
|---|---:|---:|---:|---:|
| 27/08 | 19 | 2 | 21 | **9,5%** |
| 28/08 | 6 | **4** | 10 | **40%** |
| **Janela** | **25** | **6** | **31** | **19%** |

As 6 ações, com horário:

| Ação | Alvo do envio | Quando | Existe em `contacts` como |
|---:|---|---|---|
| 360 | `5549999333881` | 27 18:06 | `554999333881` (Fernanda) |
| 364 | `5549999333881` | 27 18:11 | *(2ª tentativa, mesma pessoa)* |
| 378 | `5585988719031` | 28 09:00 | `558588719031` |
| 379 | `55996238065` | 28 09:00 | — **11 dígitos**, ver abaixo |
| 380 | `5555996238065` | 28 09:00 | `555596238065` (Sandra Diell) |
| 410 | `5551998557793` | 28 09:47 | `555198557793` |

**São 4 pessoas, 6 tentativas.** Em todas as 4, o contato **existe** — na outra grafia.

**Mecânica, com arquivo:linha** (inalterada desde a apuração das 11:15): `nat_sender.py:164`
procura com igualdade crua; `_contato_ou_criar` (`qualificacao_fluxo.py:311`) resolve tolerante
desde `05cea3f`, acha o de 12 dígitos, **decide não criar** o de 13, e descarta o objeto
resolvido (`qualificacao_fluxo.py:921-924` só testa `is None`). O envio então procura o de 13,
não acha, recusa — e o estado é revertido junto. O lead não recebe nada, não vira estado, não
entra em fila nenhuma.

É a mesma raiz do §7 de `FIX_BULK_TEMPLATE_FK_20260828.md` — RISCO 3 × canonização, decisão de
produto ainda pendente, suíte vermelha de propósito.

**O que mudou desde as 11:15:** nada vazou depois da ação 410, às **09:47**. Os dois estados da
tarde (103 às 12:53 e 104 às 12:59) abriram normalmente. Os 40% de 28/08 são **todos da manhã**
e o denominador é 10 — a taxa é frágil, e a leitura honesta é "6 leads perdidos em 2 dias", não
"40% e subindo".

**Defeito adjacente, menor:** a ação **379** foi agendada para `55996238065` — **11 dígitos**,
um número truncado que não casa com nada em grafia nenhuma. Não é a canonização; é o número
entrando torto. Só houve outro caso (ação 155, `55996028910`, 26/08). Dois em três dias.

### 1.4 Progressão do funil

| | 27/08 | 28/08 | Janela |
|---|---:|---:|---:|
| Estados | 19 | 6 | **25** |
| Com formação preenchida | 16 | 5 | 21 |
| Deram o ano | 6 | 2 | **8** |
| Deram atuação | 5 | 1 | **6** |
| Deram motivação | 4 | 1 | **5** |
| **Reunião marcada pelo agente** | **1** | 0 | **1** |

Onde estão hoje:

| Dia | Etapa | Motivo | Qtd |
|---|---|---|---:|
| 27/08 | `transferido_humano` | **`outbound_manual_sdr`** | **8** |
| 27/08 | `aguardando_ano` | (ativo) | 7 |
| 27/08 | `concluido` | — | 2 |
| 27/08 | `aguardando_formacao` | (ativo) | 2 |
| 28/08 | `transferido_humano` | **`outbound_manual_sdr`** | **4** |
| 28/08 | `aguardando_ano` | (ativo) | 2 |

**As 12 transferências são `outbound_manual_sdr`. Zero por decisão do agente, zero por falha.**
O agente não desistiu de ninguém em 2 dias — foi interrompido (§3.5).

### 1.5 ⚠️ ACHADO NOVO Nº 1 — a reunião do agente entra na Exact com o curso errado

A Kaylla aplicou para **TEA**. A LP registrou `Pos TEA V3`. A abertura falou de TEA. Os 5
turnos falaram de TEA. O box criado na Exact:

```sql
SELECT id, nome, telefone, sub_source, passo, slot_inicio FROM agendamentos WHERE id IN (249,251);
```

| id | nome | telefone | `sub_source` | passo | slot |
|---:|---|---|---|---|---|
| 249 | Kaylla Soares Ponciano d… | `21951019121` | **`Pos TEA V3`** | lead_criado | 27/08 18:01 |
| 251 | Kaylla Soares | `5521951019121` | **`PosMulheridades`** ❌ | agendado | 28/08 13:30 |

**Não é caso isolado — é 100% do caminho.** Os únicos 4 agendamentos que o agente já criou em
toda a base:

```sql
SELECT id, nome, telefone, sub_source, passo FROM agendamentos
 WHERE length(regexp_replace(telefone,'\D','','g')) >= 12;
```

| id | nome | `sub_source` | passo |
|---:|---|---|---|
| 194, 196, 197 | Fabiana Moreira | `PosMulheridades` | `iniciado` (as 3 do bug P0-A) |
| **251** | **Kaylla Soares** | **`PosMulheridades`** | **`agendado`** |

**Mecânica, com arquivo:linha.** `qualificacao_fluxo.py:1193` chama o fluxo de agendamento com
**`origem=None`**:

```python
r = await fluxo.agendar(
    db_agendamento, nome=nome, email=None,
    telefone=estado.contact_wa_id, slot_id=slot_id,
    origem=None,                                    # <-- aqui
    lead_id=estado.exact_lead_id,
    extras=None, origem_ip=None)
```

`agendar.py:302` faz `sub_source = origens.resolver(origem)`, e `origens.py:173-178` responde:
sem origem, devolve `AGENDAMENTO_SUBSOURCE_PADRAO`. No `.env` de produção:

```
AGENDAMENTO_SUBSOURCE_PADRAO="PosMulheridades"
```

O padrão existe para a **LP antiga que ainda não manda o campo** — está documentado assim em
`origens.py:166`. O agente herdou o padrão sem ser o caso de uso dele.

**E o dado certo está a três linhas de distância.** `_curso_do_lead`
(`qualificacao_fluxo.py:474-483`) já resolve o curso a partir de `ExactLead.sub_source` — é
exatamente o que escreve "Pós-Graduação em TEA" na abertura. E `Pos TEA V3` **está na
allowlist** (`AGENDAMENTO_SUBSOURCES` tem os 14 cursos). Não falta dado nem permissão: falta
passar o parâmetro.

**Consequência prática:** a consultora abre o box de Mulheridades para conversar com uma lead
de TEA, e o relatório de marketing credita a matrícula ao curso errado. Com N=1 o estrago é
pequeno; o caminho é 100%, e o objetivo declarado do sprint é aumentar esse N.

**Relacionado, mesmo ponto do código:** `extras=None` na mesma chamada — o formulário da LP
(profissão, faixa de investimento, "como conheceu") existe no id 249 e vira `null` no 251. É a
`extras jsonb null engole o formulário` já conhecida, agora com caso real e localização exata.

### 1.6 Lembrete marcado `executado` sem ter sido enviado — confirmado

21 ações `lembrete_reuniao` na janela; **15 `executado`**, 6 `cancelado`. Dos 15 `executado`,
**13 saíram de fato** (`📤 NAT enviou 'nat_lembrete_reuniao'`) e **2 não**:

| Ação | Lead | Quando | O que o log diz |
|---:|---|---|---|
| **226** | **Mikaelle** `5541992680313` | 27/08 09:15 | `🔒 teto de envios/hora estourado (22/20)` |
| **64** | `5591985119613` (Josiqueila) | 28/08 08:30 | `🔒 contato não existe no banco` |

**Mecânica:** `qualificacao_fluxo.py:1462` chama `await send_nat_message(...)` e **descarta o
`bool`**. É o mesmo buraco que o P0-B fechou em `processar_texto` e que o S4-1 fechou nas
**pré-checagens** deste handler — a docstring em `:1428-1429` comemora exatamente isso. **O
envio em si continua mudo.**

O caso da Mikaelle fecha um ciclo: ela escreveu **09:13** *"gostaria de confirmar o horário"*;
o lembrete que responderia isso foi descartado em silêncio **09:15**; a reunião era **09:45**;
ninguém respondeu até agora — 32 horas depois.

### 1.7 A reunião — o zero saiu do zero ✅ (com a ressalva do §1.5)

**Kaylla Soares Ponciano de Castro**, `5521951019121`, LP, aplicou em `Pos TEA V3`:

```
27 18:06:33  🚀 Agente abriu: nat_abertura_qualificacao → aguardando_ano
27 18:45:38  📅 Agente ofereceu 2 horário(s)
27 18:46:00  🧠 LLM .../escolhendo_slot | acao=agendar_slot dado={'slot_id': '2026-08-28T13:30:00'}
27 18:46:01  📦 agendamento #251: box 43809078 criado com Victória Rodrigues
27 18:46:05  ✅ agendamento #251: lead 51610927 agendado em 2026-08-28T13:30:00
27 18:46:05  ⏰ NAT scheduler: lembrete_reuniao agendado para 28/08 13:00 (id=376)
27 18:46:06  ✅ Agente concluiu 5521951019121 (reunião 251)
28 13:00:35  📤 NAT enviou 'nat_lembrete_reuniao'          ← o lembrete SAIU
28 13:00:48  LEAD: "Ok"                                     ← e ela confirmou
```

`agendamentos` id **251**, `passo='agendado'`, box 43809078, meeting 4738041, slot **28/08
13:30**. Abertura → reunião em **40 minutos**, dos quais a conversa foram **52 segundos**.

Isto valida **P0-A** (nenhum `InvalidRequestError` — o bug que matou a Fabiana morreu), **P0-D**
(`✅ Agente concluiu`) e agora, com o "Ok" das 13:00, o **lembrete ponta a ponta**. É o primeiro
caso real completo. O curso no CRM está errado (§1.5), mas a reunião existe.

### 1.8 O silêncio — a query definitiva

Inbound sem nenhum outbound posterior, nas duas grafias, na janela inteira:

```sql
SELECT ... FROM inb i
WHERE NOT EXISTS (SELECT 1 FROM msg o WHERE o.chave=i.chave
                  AND o.direction='outbound' AND o.timestamp > i.ts)
```

**21 mensagens sem resposta.** Classificadas:

| Diagnóstico | Qtd | Leitura |
|---|---:|---|
| **SEM ESTADO** (conversa 100% humana) | **14** | fila do time, o agente nunca esteve ali |
| **pós-transferência** | 6 | o agente calou **de propósito** |
| **etapa final** (`concluido`) | 1 | Kaylla, "Ok" após o lembrete |
| **ETAPA ATIVA** | **0** ✅ | — |

**Silêncio do agente em etapa ativa: ZERO**, nos dois dias, com todas as variantes de grafia.
As três camadas (P0-B, P0-C, S4-2) seguraram. Os 29 `vigiar_resposta` armados foram 29
cancelados e **nenhum disparou** — todo turno falou.

**Mas 21 leads escreveram e ninguém respondeu.** O agente parou certo; o passo seguinte não
veio. Entre elas, hoje: *"É possível trocar de oficina?"* (11:48), *"Quero mais informações do
evento"* (10:59), e a Waldelice às 13:51 — *"Estou no Congresso hj e sei q tem desconto e
garante mais uma pós, poderia me confirmar?"*.

### 1.9 ⚠️ ACHADO NOVO Nº 2 — o Marcos, resíduo vivo do bug do disparo

Entre 10:16 e 10:51 SP de hoje, 5 tentativas do disparo em massa caíram em 500. Cada uma
deixou no log:

```
⚠️  Falha ao silenciar o agente em 559182668801 depois de envio manual (IntegrityError:
    ForeignKeyViolationError ... Key (contact_wa_id)=(559182668801) is not present in
    table "contacts") ... O agente segue ativo.
```

O contato dele existe como `5591982668801` (13 dígitos); a gravação tentou `559182668801` (12).
Resultado, conferido no banco e no log:

* **4 wamids distintos aceitos pela Meta** — ele recebeu **o mesmo template 4×**;
* **nenhum deles está em `messages`** — a única linha dele no Hub é a abertura de 27/08 18:02;
* **o agente NÃO foi silenciado** — o estado 89 segue `aguardando_ano`, `transferido_motivo`
  NULL.

O defeito está **corrigido** (`94867c1`, no ar desde 11:04 SP; `0` ocorrências depois — 30
chamadas de `bulk-send-template` entre 11:07 e 16:36 SP, todas limpas). O que continua de pé é
o **estado dele**: se o Marcos responder, o agente vai atender uma conversa em que o SDR já
falou 4 vezes, e o Hub não mostra nenhuma delas. Uma linha de dado, não de código.

### 1.10 Vigias, rede de última instância, encerramentos e infraestrutura

| Sinal | Resultado |
|---|---|
| `vigiar_resposta` (`agente_mudo`) | **29 armados, 29 cancelados, 0 disparos** |
| `agente_parado` | **164 varreduras**, 1 encalhado (a Erica), **0 avisos novos**, 0 falsos positivos |
| Rede de última instância (P0-C) | **nunca disparou** |
| `QueuePool limit` | **0** |
| 502 no nginx | **0** |
| Tracebacks | **5** — todos `bulk-send-template`, todos antes do fix das 11:04 |
| Teto 20/h | 8 estouros: 3 aberturas **adiadas corretamente** (ação 326, 3×), 1 lembrete **perdido** (§1.6) |

**A varredura não tem falso positivo, e o motivo é o critério.** Minha query ingênua
("etapa ativa + parado há >60 min") devolve **15** estados; a varredura acusa **1**. A
diferença é `agente_parado.py:139-158`: só conta conversa em que **o lead falou por último**.
Os outros 14 nunca responderam à abertura — estão esperando o **lead**, não a gente. O critério
está certo e a contagem baixa é a prova, não o sintoma.

**Os encerramentos começaram — e o rótulo saiu certo.** A apuração das 11:15 registrou
`encerrado_motivo IS NOT NULL` = **0 linhas** e previu os primeiros para amanhã. Eles vieram
**hoje**:

```sql
SELECT encerrado_motivo, count(*) FROM nat_qualificacao_state WHERE encerrado_motivo IS NOT NULL GROUP BY 1;
--  inatividade | 2
```

| Estado | Lead | Encerrado | Última mensagem da thread | Rótulo | Correto? |
|---:|---|---|---|---|---|
| 15 | `5511992941919` | 28/08 13:29 | **outbound** 25/08 16:28 (nossa abertura) | `inatividade` | ✅ |
| 25 | `5547992840609` (Laura) | 28/08 14:23 | **outbound** 25/08 17:23 (nossa abertura) | `inatividade` | ✅ |

Nos dois, **nós falamos por último e o lead nunca respondeu** — `inatividade` é o rótulo certo.
`sem_resposta_do_agente` segue com **zero** casos; o primeiro vence amanhã (§5.3).

Ainda no ciclo: 5 ações `skipped` com motivo `já está em 'transferido_humano' — fora das
etapas`, que é o S4-1 funcionando. **60 `encerrar_inativo` pendentes**, o último para 31/08.

Nota de fundo: **6× `❌ Erro no sync Exact Spotter`** na janela; recupera-se sozinho na
tentativa seguinte (`total_synced: 9222`). Fora do escopo, não investigado.

---

## 2. Transcrições

Todas as conversas com **≥1 inbound em 27–28/08**: **34 threads**. Horário SP. Atribuição por
`nat_etapa` — ver a nota metodológica ao fim desta seção.

> **Nota metodológica que muda como se lê o Hub.** `messages.sent_by_ai` está **`false` em
> todas as mensagens do agente**. Quem separa agente de humano é `nat_etapa`: preenchido
> (`nat_abertura_*`, `qualif_conversa`, `nat_lembrete_reuniao`) = **NAT**; nulo e outbound =
> **SDR/humano**. Qualquer contagem que use `sent_by_ai` para medir o agente dá zero.

### 2.1 Kaylla — `5521951019121` — *a reunião, do começo ao "Ok"*

```
27 18:01:31 LEAD  Olá! Tudo bem? Fiz minha aplicação na turma da Pós-Graduação Online: Transtorno do
                  Espectro Autista (TEA)... e gostaria de mais informações.
27 18:06:33 NAT   Olá, Kaylla! Que bom te ver por aqui ✨
                  Vi que você aplicou para a nossa Pós-Graduação em Transtorno do Espectro Autista
                  (TEA). Antes de te mostrar os horários com a nossa consultoria, gostaria de
                  entender um pouco melhor a sua trajetória até aqui.
                  Vi que sua formação é em Psicologia. Em que ano você concluiu?
27 18:45:14 LEAD  2023
27 18:45:18 LEAD  Eu já fui aluna do cenat
27 18:45:18 NAT   Perfeito, Kaylla — você concluiu a graduação em 2023. Como e onde você atua
                  profissionalmente hoje?
27 18:45:21 NAT   Que bom que já foi aluna do CENAT, Kaylla! Como e onde você atua profissionalmente hoje?
27 18:45:24 LEAD  Fiz saúde mental infanto-juvenil
27 18:45:27 NAT   Ótimo — você atuou em saúde mental infanto-juvenil. O que despertou seu interesse
                  por esta pós em TEA?
27 18:45:33 LEAD  Sou psicóloga escolar
27 18:45:35 NAT   Entendi — você é psicóloga escolar. Interessante que vem da prática com crianças e
                  adolescentes; isso pode trazer contribuições importantes para a abordagem clínica
                  e educacional do TEA. Vou ver os horários disponíveis com a consultoria.
27 18:45:38 NAT   Perfeito, Kaylla — obrigado por contar! Vou te oferecer alguns horários com a
                  consultora para conversarmos sobre a pós em TEA: 28/08 às 12:00 ou 28/08 às 13:30.
                  Se nenhum desses servir, me diz que dia e período (manhã/tarde/noite) você prefere
                  que eu procuro outras opções 😊
27 18:45:58 LEAD  Prefiro as 13:30
27 18:46:06 NAT   Perfeito, Kaylla — agendo sua conversa para 28/08 às 13:30 e já confirmo com a
                  consultora. Você pode me passar o celular com DDD para registrarmos no cadastro?
28 13:00:35 NAT   Olá, Kaylla! Passando para lembrar da sua reunião de hoje às 13:30 📅
                  Nossa consultora, Victória Rodrigues, vai te ligar aqui mesmo pelo WhatsApp, por
                  este mesmo número. Fique de olho no celular no horário combinado! 😊
28 13:00:48 LEAD  Ok
```

*(O box foi criado como `PosMulheridades` — §1.5.)*

### 2.2 Daniela — `5582999810488` — *cortada ao meio, e depois atendida*

```
28 09:00:45 NAT   Olá, Daniela! Que bom te ver por aqui ✨
                  Vi que você aplicou para a nossa Pós-Graduação em Transtorno do Espectro Autista
                  (TEA)... Vi que sua formação é em Enfermagem. Em que ano você concluiu?
28 09:00:56 LEAD  Ola Bem vindo(a)! Desde ja, agradeço seu contato , em que posso te ajudar?
28 09:01:00 NAT   Oi Daniela! Sou a assistente do CENAT. Em que ano você concluiu a graduação em
                  Enfermagem?
28 09:05:15 LEAD  2003
28 09:05:17 NAT   Perfeito, Daniela — você concluiu a graduação em Enfermagem em 2003. Como e onde
                  você atua profissionalmente hoje?
28 09:06:15 LEAD  Enfermeira assistencialista em unidade municipal especializada
28 09:06:18 NAT   Entendi: você atua como enfermeira assistencialista em unidade municipal
                  especializada. O que despertou seu interesse pela pós-graduação em Transtorno do
                  Espectro Autista (TEA)?
28 09:06:43 LEAD  Tenho filho e sobrinhos autistas
28 09:06:46 NAT   Entendi — seu interesse pela pós em TEA vem da experiência pessoal com seu filho e
                  seus sobrinhos autistas, e faz todo sentido querer aprofundar esse conhecimento
                  para ajudar na vida deles e na sua prática profissional. Vou ver os horários
                  disponíveis e já te retorno.
28 09:06:49 NAT   Perfeito, Daniela — obrigada por compartilhar 💙
                  Tenho esses horários de consultoria com a consultora para você escolher:
                  - Segunda (31/08) às 09:00   - Segunda (31/08) às 10:30
                  - Segunda (31/08) às 12:00   - Segunda (31/08) às 14:15
                  - Segunda (31/08) às 17:15
                  Se nenhum servir, diga qual dia e período (manhã/tarde/noite) você prefere que eu procure.
28 09:07:45 LEAD  A noite
28 09:07:49 NAT   Entendi que prefere à noite; no entanto, por enquanto só tenho horários disponíveis
                  nesses horários do dia: 09:00, 10:30, 12:00, 14:15 e 17:15 no dia 31/08. Qual
                  desses você prefere?
28 09:07:56 LEAD  A partir das 20 hrs
28 09:07:59 NAT   Entendi que você prefere a partir das 20:00, Daniela, mas por enquanto só temos
                  disponibilidade no dia 31/08 nos horários que te passei: 09:00, 10:30, 12:00,
                  14:15 e 17:15. Qual desses você prefere?
—————————————— 2 HORAS DEPOIS, DISPARO EM MASSA ——————————————
28 11:07:12 SDR   Ola Daniela, é o Thobias do CENAT ✨
                  Tentei realizar uma nova tentativa de contato referente a sua aplicação na Pós
                  Graduação Transtorno do Espectro Autista (TEA) mas até o momento não tive sucesso 🥺
                  Qual seria o melhor horário para contato?
28 11:09:33 LEAD  Da p falar por aqui?
28 11:09:40 LEAD  Pois estou no trabalho
28 11:21:50 SDR   Eu entendo totalmente a sua rotina. O ponto é que essa conversa por ligação não é
                  só apresentação, sabe? Ela é importante pra gente entender melhor seu perfil e ver
                  se a pós realmente faz sentido pra você, até pra não te indicar algo fora do seu momento.
28 11:21:56 SDR   Só te explicando um ponto importante: tanto a primeira etapa quanto a conversa com a
                  consultora são feitas por ligação... Por isso, não conseguimos conduzir esse
                  processo por mensagem.
28 11:22:03 SDR   Mas a gente facilita ao máximo: são conversas bem objetivas, de 5 a 10 minutos cada,
                  e eu posso me adaptar ao melhor horário dentro da sua rotina.
```

> **Correção ao recon das 11:15.** Aquele documento fechou esta transcrição em *"SEM RESPOSTA.
> Agente silenciado"*. **O SDR respondeu às 11:21:50**, 12 minutos depois do corte daquela
> apuração, e respondeu bem. A leitura correta não é "a lead foi abandonada" — é "a lead foi
> transferida de canal no meio de um agendamento que já estava em curso". O custo é real
> (ela estava escolhendo horário), mas é outro problema.

### 2.3 Cláudia — `5511998250115` — *o corte mais rápido da janela: 14 minutos*

```
28 12:59:34 NAT   Olá, Cláudia! Que bom te ver por aqui ✨
                  Vi que você aplicou para a nossa Pós-Graduação em Enfermagem em Saúde Mental...
                  Vi que sua formação é em Enfermagem. Em que ano você concluiu?
28 13:00:21 LEAD  2008
28 13:00:25 NAT   Perfeito, Cláudia — você concluiu a graduação em 2008. Como e onde você atua
                  profissionalmente hoje?
28 13:13:09 SDR   Ola Cláudia, é o Thobias do CENAT ✨
                  Tentei realizar uma nova tentativa de contato referente a sua aplicação na Pós
                  Graduação Enfermagem em Saúde Mental mas até o momento não tive sucesso 🥺
                  Qual seria o melhor horário para contato?
                  ← 13 min depois de ela responder. "não tive sucesso" para quem respondeu na hora.
```

### 2.4 Lucas — `5551996323362` — *P0-D no ar, e a costura aparecendo*

```
27 09:00:55 NAT   Olá, Lucas! ... Recebi sua aplicação para a Pós-Graduação em Autolesão, Suicídio e
                  Luto e sua reunião com nossa consultora Victória Rodrigues já está confirmada para
                  27/08 às 11:15 📅 ... Vi que sua formação é em Psicologia — em que ano você concluiu?
27 09:06:00 LEAD  2025
27 09:06:08 NAT   Perfeito, Lucas — você concluiu em 2025. Como e onde você atua profissionalmente hoje?
27 09:06:49 LEAD  Na atenção básica e em consultório particular
27 09:06:52 NAT   Entendi: você atua na atenção básica e em consultório particular. O que despertou
                  seu interesse por esta pós-graduação em Autolesão, Suicídio e Luto?
27 09:07:17 LEAD  É uma demanda que aparece muito na atenção básica
27 09:07:20 NAT   Perfeito — ficou claro que é uma demanda que aparece muito na atenção básica,
                  especialmente no seu trabalho na atenção básica e no consultório. Vou ver os
                  horários disponíveis para a consultora Victória Rodrigues e te aviso.
27 09:07:20 NAT   Na verdade você já tem horário reservado: 27/08 às 11:15 com Victória Rodrigues.
                  Te espero lá! Se precisar remarcar, é só me dizer. 🙂
27 10:45:43 NAT   Olá, Lucas! Passando para lembrar da sua reunião de hoje às 11:15 📅 ...
```

A costura do P0-D fica visível — a fala do LLM promete procurar horário e o fecho determinístico
corrige no mesmo segundo. Funciona; lê-se como duas pessoas.

### 2.5 Marcio — `556792894362` — *aplicou no curso errado, e o agente vendeu assim mesmo*

```
27 09:01    NAT   Olá, Marcio! ... Vi que você aplicou para a nossa Pós-Graduação em Infantojuvenil
                  EAD... Vi que sua formação é em Serviço Social. Em que ano você concluiu?
27 09:07:00 LEAD  2022 acho
27 09:07:02 LEAD  Rsrs
27 09:07:03 NAT   Perfeito, Marcio — entendi que você concluiu em 2022. Como e onde você atua...?
27 09:07:05 NAT   Ótimo, Marcio — você concluiu em 2022. Como e onde você atua profissionalmente hoje?
27 09:08:30 LEAD  Coordenadoria Regional de educação Secretaria do estado de educação - MS . Eu
                  trabalho serviço especializado de apoio psico social acompanhando as escolas do
                  interior do MS.
27 09:08:34 NAT   Entendi — você atua na Coordenadoria Regional de Educação do Estado do MS, no
                  serviço especializado de apoio psicossocial, acompanhando escolas do interior.
                  O que despertou seu interesse por esta pós em Infantojuvenil EAD?
27 09:09:44 LEAD  Na verdade eu achei q fosse um curso sobre combate a bullying
                  ..q são muitos casos e q reflete na saúde mental dos estudantes...
27 09:09:46 NAT   Entendi: você achou que o curso seria sobre combate ao bullying, porque há muitos
                  casos que impactam a saúde mental dos estudantes — e é isso que te mobiliza.
27 09:09:49 NAT   Perfeito, Marcio — obrigado por explicar; faz sentido você buscar formação prática
                  sobre bullying na escola. Vou te oferecer alguns horários para conversar com a
                  consultora e tirar todas as suas dúvidas sobre o conteúdo do curso e se ele cobre
                  estratégias de prevenção e intervenção em bullying. Posso te oferecer:
                  - 27/08 às 12:00  - 27/08 às 13:30  - 27/08 às 16:30
                  - 28/08 às 11:15  - 28/08 às 15:00
27 09:10:47 LEAD  Sábado dia 29 no período da manhã as 10:00 hrs . Pode ser?
27 09:10:51 NAT   Marcio, quem passa disponibilidade fora das opções que te ofereci é a consultora na
                  conversa — eu só tenho aqueles horários. Você prefere que eu agende um dos horários
                  disponíveis para a manhã de sábado 27/08 às 12:00, 28/08 às 11:15 ou 28/08 às 12:00?
27 11:11:00 SDR   Ola Marcio, é o Thobias do CENAT ✨ Tentei realizar uma nova tentativa de contato...
28 11:50:05 SDR   Olá Marcio, tudo bem? 🌻 Fiz uma nova tentativa de contato, mas ainda sem sucesso...
```

### 2.6 Clarice — `5531999818666` — *pediu noite, ofereceu transferir, ninguém transferiu*

```
27 09:01:01 NAT   Olá, Clarice! ... Pós-Graduação em Transtorno do Espectro Autista (TEA)...
                  Vi que sua formação é em Psicologia. Em que ano você concluiu?
27 09:30:10 LEAD  2026
27 09:30:14 NAT   Perfeito, Clarice — você concluiu a graduação em 2026. Como e onde você atua...?
27 09:45:30 LEAD  Prestacao de serviço para a prefeitura como psicóloga clinica
27 09:45:34 NAT   Entendi: você atua como psicóloga clínica prestando serviço para a prefeitura.
                  O que despertou seu interesse pela pós em TEA?
27 09:45:52 LEAD  Demanda de muitas crianças com laudo
27 09:45:55 NAT   Entendi que seu interesse pela pós em TEA vem da demanda de muitas crianças com
                  laudo — faz sentido, é um campo com muita procura e você já lida com isso no dia a
                  dia. Vou ver os horários disponíveis e te trago em seguida.
27 09:45:57 NAT   Ótimo, Clarice — obrigado por compartilhar. Seguem algumas opções de horários para
                  conversar com a consultora sobre a pós em TEA (escolha apenas um):
                  - Qui 27/08 às 12:00  - Qui 27/08 às 16:30  - Sex 28/08 às 11:15
                  - Sex 28/08 às 13:30  - Sex 28/08 às 16:30
                  Se nenhum desses servir, me diz que dia e período (manhã/tarde) você prefere que eu
                  procuro outras opções para você. 🙂
27 09:46:21 LEAD  A noite tem?
27 09:46:24 NAT   Quem passa horários fora dessa lista (noite ou outros) é a consultora na conversa;
                  por aqui só tenho os horários que te mostrei. Qual dos horários que te mandei você
                  prefere?
27 09:46:40 LEAD  Nenhum
27 09:46:43 NAT   Entendi que nenhum desses horários serve, Clarice. Quer que eu passe o seu contato
                  para a consultora para ela verificar outras opções de horários noturnos?
27 11:10:54 SDR   Ola Clarice, é o Thobias do CENAT ✨ Tentei realizar uma nova tentativa de contato...
28 11:49:25 SDR   Olá Clarice, tudo bem? 🌻 Fiz uma nova tentativa de contato, mas ainda sem sucesso...
```

O agente perguntou *"quer que eu passe seu contato para a consultora?"* e **nunca soube a
resposta** — o disparo cortou 1h24 depois. A pergunta segue sem responder 32h depois.

### 2.7 Morgana — `5522981024236` — *duas formações, tratadas certo*

```
26 22:58:44 LEAD  Olá! ... Pós-Graduação Online em Psicologia Escolar e gostaria de mais informações.
27 09:00:56 NAT   Olá, Morgana! ... Me conta: qual é a sua formação?
27 10:51:55 LEAD  Sou formada em Letras e Pedagogia.
27 10:51:59 NAT   Perfeito, Morgana — entendi que você é formada em Letras e Pedagogia. Em que ano
                  você concluiu cada uma dessas graduações?
27 10:52:47 LEAD  Letras 2003 ⏎ Pedagogia 2018
27 10:52:50 NAT   Perfeito, Morgana — anotado: Letras (2003) e Pedagogia (2018). Como e onde você
                  atua profissionalmente hoje?
27 11:10:56 SDR   Ola Morgana, é o Thobias do CENAT ✨ ... não tive sucesso 🥺
28 11:49:32 SDR   Olá Morgana, tudo bem? 🌻 ... ainda sem sucesso...
```

**O melhor turno do período.** Ela deu duas formações; o agente não escolheu uma nem se
confundiu — perguntou o ano **de cada uma** e anotou as duas. Cortado 18 minutos depois.

### 2.8 Caroline — `5524988477797` — *o lead pede para tirar dúvidas antes*

```
27 17:51:29 NAT   Olá, Caroline! ... Recebi sua aplicação para a Pós-Graduação em Saúde Mental e
                  Mulheridades e sua reunião com nossa consultora Victória Amorim já está confirmada
                  para 28/08 às 11:15 📅 ... sua formação é em Psicologia — em que ano você concluiu?
28 06:21:42 LEAD  2021
28 06:21:48 NAT   Perfeito, Caroline — você concluiu a graduação em 2021. 😊 Como e onde você atua
                  profissionalmente hoje?
28 06:21:50 LEAD  Queria tirar umas dúvidas antes
28 06:21:53 NAT   Entendi, Caroline — você quer tirar algumas dúvidas antes. Vou anotar isso. Me
                  conta: quais dúvidas você tem sobre a pós-graduação?
28 10:45:50 NAT   Olá, Caroline! Passando para lembrar da sua reunião de hoje às 11:15 📅 ...
28 11:21:19 SDR   [FAILED 131049] Olá Caroline✨ A nossa consultora Victória tentou o contato mas não
                  conseguiu falar com você...
```

O agente lidou bem com *"queria tirar umas dúvidas antes"* — reconheceu, não insistiu no
roteiro, e devolveu a pergunta aberta. Ela não respondeu. O lembrete saiu; a mensagem seguinte
do SDR **não foi entregue** (131049).

### 2.9 Reynaldo — `5512982737057` — *T1 limpo, sem resposta*

```
28 06:49:36 LEAD  Olá! ... Pós-Graduação Online: Transtorno do Espectro Autista (TEA)...
28 09:00:43 NAT   Olá, Reynaldo! ... sua reunião com nossa consultora Victória Amorim já está
                  confirmada para 28/08 às 12:00 📅 ... Vi que sua formação é em Medicina — em que
                  ano você concluiu?
28 11:30:30 NAT   Olá, Reynaldo! Passando para lembrar da sua reunião de hoje às 12:00 📅 ...
```

### 2.10 Mikaelle e Cintia — *o topo da fila de triagem, ainda intocado*

```
—— Mikaelle 554192680313 —— (estado 64)
26 13:25:04 NAT   Que bacana, Mikaelle — você se interessou por saúde pública durante a graduação,
                  fez estágio no CAPS e escreveu a monografia sobre políticas públicas...
                  Vou ver os horários disponíveis para sua reunião com a Victória Rodrigues e já te aviso 👍
26 13:25:04 NAT   Deixa eu te conectar com uma pessoa da nossa equipe para seguir daqui, tá? 🙂
26 13:25:27 LEAD  Certo, obrigada.
27 09:13:18 LEAD  Oi… gostaria de confirmar o horário da conversa com a consultora
                  ← SEM RESPOSTA ATÉ AGORA (32h). Lembrete das 09:15 descartado pelo teto (§1.6).
                    Reunião 216 era 27/08 09:45, passo='agendado'.

—— Cintia Pessôa 558185088547 —— (estado 37)
26 15:12:02 LEAD  No momento não tenho interesse. Estou me preparando para o início do ano q vem.
27 13:14:24 SDR   Entendo, Cintia! 😊 Só para eu conseguir compreender melhor e não insistir em um
                  momento que não faça sentido para você: quando você fala que está se preparando
                  para o início do ano que vem, é mais por uma questão de momento/organização,
                  investimento ou porque pretende avaliar outras opções de pós?
27 13:14:32 SDR   Te pergunto porque, dependendo do que está pesando para você agora, talvez eu
                  consiga te orientar melhor. 🌻
27 13:30:12 LEAD  Estou me organizando com relação a tempo
                  ← SEM RESPOSTA (28h). Foi atendida e largada de novo.
```

### 2.11 Julia — `5521983371003` — *perguntou o preço às 23:40; ninguém respondeu*

```
27 23:38:50 LEAD  Olá! ... Pós-Graduação Online em Psicologia Escolar e gostaria de mais informações.
27 23:40:34 LEAD  Por gentileza quero informações sobre o investimento. O pagamento pode ser feito de
                  outra firma, sem ser por cartão? E que valor seria?
28 09:00:44 NAT   Olá, Julia! Que bom te ver por aqui ✨
                  Vi que você se interessou pela nossa Pós-Graduação em Psicologia Escolar. Antes de
                  te mostrar os próximos passos, gostaria de conhecer um pouco da sua trajetória.
                  Me conta: qual é a sua formação?
28 11:07:10 SDR   Ola Julia, é o Thobias do CENAT ✨ ... não tive sucesso 🥺
```

A pergunta sobre preço, feita duas vezes, atravessou 18 horas e três mensagens nossas sem ser
tocada uma vez.

### 2.12 O trabalho humano de hoje — *o time está ativo, na outra lista*

Três conversas em que o SDR conduziu bem, todas hoje à tarde:

```
—— Wilian 5551982890308 ——
28 16:36:22 SDR   Olá Wilian, tudo bem? 🌻 Fiz uma nova tentativa de contato...
28 16:39:17 LEAD  Olá, tudo bem! Eu tenho interesse, mas eu não consigo atender vcs
28 16:39:21 LEAD  Tenho uma rotina de 40h
28 16:39:34 LEAD  Tá muito complexo esse tipo de conversa pra se matricular numa pós
28 16:40:55 SDR   Entendo, Wilian! 😊 E faz sentido você pensar assim, principalmente com uma rotina de 40h.
28 16:41:02 SDR   A primeira etapa é justamente uma ligação rápida, de aproximadamente 5 minutos...
28 16:41:26 SDR   Você consegue me indicar um horário em que esteja com 5 minutinhos livres...? 🌻

—— Monica 5553997107849 ——
28 13:52:16 SDR   Olá Monica... Segue abaixo o link de acesso à ementa da Pós-Graduação...
28 13:52:31 LEAD  Obrigada
28 13:52:36 LEAD  Não tenho mais interesse
28 14:17:33 SDR   Só para eu registrar corretamente sua aplicação: o que fez você decidir não seguir
                  com a Pós em Saúde Mental e Mulheridades? Foi porque o tema deixou de fazer
                  sentido para os seus objetivos profissionais ou aconteceu alguma outra situação...?

—— Yasmin 5511941092790 ——
27 19:23:02 LEAD  boa noite! amanhã a partir das 16h eu estou livre, se puderem
28 10:19:27 SDR   Perfeito, Yasmin! 😊
28 10:19:36 SDR   Combinado! Vou deixar agendado para hoje, às 16h30.
28 10:19:51 SDR   A ligação será feita via WhatsApp pelo número (67) 99915-1808. 🌻
```

**Isto importa para a leitura do §5.** O time não está parado — está trabalhando a lista da
campanha, com qualidade. O que não andou foi a **fila de triagem**.

### 2.13 As demais threads da janela (resumo por linha)

| Thread | Nome | O que aconteceu |
|---|---|---|
| `5511964791220` | Giulliana | abertura T2 27 09:00 → disparo 11:10 → ela deu horário 11:21 → SDR confirmou 13:17 → novo disparo 28 11:49 |
| `5582987011836` | Jacileila | abertura 27 09:01, sem resposta, 2 disparos |
| `5541996596171` | Niuzeth | lembrete 27 13:45 (reunião 14:15) → disparo 28 11:50 → *"Ola estou indisponível, em horario de trabalho"* 13:04, sem resposta |
| `5531984033418` | Isabella Dias | SDR mandou ementa 28 13:16 → autorresposta de luto familiar, sem resposta |
| `5551995304709` | Natália Nordin | lembrete 27 15:15 executado ✅ → ela respondeu 15:15 (reação), sem resposta |
| `5585992987046` | — | abertura 27 09:00, sem resposta; silenciado 28 11:49 |
| `5591982668801` | Marcos | abertura 27 18:02; **4 disparos invisíveis** e agente ainda ativo (§1.9) |
| `5591982274509` / `5581995345775` / `5511999990013` | Marcos Couto / John Doe / SMOKE | abertura, sem resposta (2 dos 3 são teste) |
| `5567999151808` / `5527999805197` / `5571985252525` | — | abertura `failed` (§1.1); estado ficou em `aguardando_*` |
| `5522981434983` / `5575999262561` / `5571983577808` | — | abertura entregue, sem resposta |
| `553171150717` | Adriana | abertura 28 09:00, sem resposta, silenciada 11:07 |
| **Sem estado, na fila humana** | cintia gomes (27 08:40), mariana (27 08:51), Joaciara (27 11:56), Edvânia (27 11:57), Aldiane (27 15:45), Caroline Medeiros (27 17:41), Alice Avelino (27 22:27), Sandra Diell (27 23:33), Arthur (28 10:59), Regiane (28 11:08), `4299368854` (28 11:48), Dyenifer (28 09:35), Claudia (27 20:05), Waldelice (28 13:50) | **14 threads, nenhuma respondida** |

---

## 3. Leitura qualitativa

### 3.1 Perguntas fora do roteiro — insumo para a base de conhecimento

Verbatim, com o que o agente fez. **A tabela cresceu em relação à apuração das 11:15.**

| Tema | Verbatim | Quem | O que aconteceu |
|---|---|---|---|
| **Horário noturno** | *"A noite tem?"* | Clarice | Recusou certo, ofereceu transferir. **Ninguém transferiu.** |
| **Horário noturno** | *"A noite"* → *"A partir das 20 hrs"* | Daniela | Repetiu a mesma lista **duas vezes** |
| **Fim de semana** | *"Sábado dia 29 no período da manhã as 10:00 hrs. Pode ser?"* | Marcio | Recusou e **alucinou** (§3.3) |
| **Preço / forma de pagamento** | *"quero informações sobre o investimento. O pagamento pode ser feito de outra firma, sem ser por cartão? E que valor seria?"* | Julia | **Ignorado por completo** |
| **Dúvidas antes da reunião** | *"Queria tirar umas dúvidas antes"* | Caroline | **Tratou bem** — reconheceu e devolveu pergunta aberta |
| **Canal (mensagem × ligação)** | *"Da p falar por aqui?"* / *"Pois estou no trabalho"* | Daniela | Agente já silenciado; **o SDR respondeu bem** às 11:21 |
| **Canal (mensagem × ligação)** | *"Tá muito complexo esse tipo de conversa pra se matricular numa pós"* | Wilian | **Sem estado** — o SDR respondeu bem |
| **Desconto de congresso** | *"Estou no Congresso hj e sei q tem desconto e garante mais uma pós, poderia me confirmar?"* | Waldelice | **Nunca respondida** (28 13:51) |
| **Troca de turma/oficina** | *"É possível trocar de oficina?"* | `4299368854` | **Nunca respondida** (28 11:48) |
| **Modalidade** | *"Será on-line ?"* | Alice Avelino | **Nunca respondida** |
| **Carga horária de congresso** | *"Congresso ... Boas Práticas em Gêneros e Sexualidades Vale quantas horas?"* | Aldiane | **Nunca respondida** — produto diferente |
| **Local do evento** | *"Gostaria de saber onde será o evento"* / *"Gênero e sexualidade"* | Edvânia | **Nunca respondida** — produto diferente |
| **Submissão de resumo** | *"os resumos a serem submetidos sao expandidos, isso?"* | mariana | **Nunca respondida** — produto diferente |

**Dois padrões para a gestora:**

1. **Horário fora da grade é o tema nº 1** — 3 das 13, e é estrutural, não de conhecimento (§3.4).
2. **Quatro perguntas são sobre CONGRESSO/EVENTO, não sobre pós** — Aldiane, Edvânia, mariana,
   Arthur. Essas conversas caem no mesmo número e não têm dono nenhum: o agente não as pega (não
   têm lead na Exact) e a fila do SDR é de pós. É um funil inteiro sem atendimento.

### 3.2 Validação de motivação — específica, não genérica ✅

O agente **cita o que o lead disse**, em todos os 5 casos que chegaram lá:

* Daniela — *"vem da experiência pessoal com seu filho e seus sobrinhos autistas"*
* Clarice — *"vem da demanda de muitas crianças com laudo — faz sentido, é um campo com muita procura e você já lida com isso"*
* Lucas — *"é uma demanda que aparece muito na atenção básica"*
* Marcio — *"você achou que o curso seria sobre combate ao bullying"*
* Kaylla — *"vem da prática com crianças e adolescentes"*

Nenhuma validação genérica. Segue sendo o ponto mais forte da qualidade conversacional.

**Ressalva que permanece:** aceita não-resposta como motivação. Kaylla respondeu *"Sou
psicóloga escolar"* à pergunta *"o que despertou seu interesse?"*; o LLM gravou
`motivacao='Sou psicóloga escolar'` com `etapa_cumprida=True` e seguiu.

### 3.3 Alucinação de data — Marcio (1 caso em 33 turnos)

Ele pediu **sábado 29/08 de manhã**. O agente respondeu:

> *"…horários disponíveis para a **manhã de sábado 27/08 às 12:00**, 28/08 às 11:15 ou
> **28/08 às 12:00**?"*

Três erros numa frase: **27/08 era quinta**, **12:00 não é manhã**, e **28/08 às 12:00 nunca
foi ofertado** (a lista tinha 11:15 e 15:00). Único caso na janela — mas é a classe de erro que
marca reunião no horário errado, e o guard de `_agendar` só protege o `slot_id` da **ação**, não
o texto da **mensagem**.

### 3.4 Ofertas de agenda — P3-B cumprido, e uma promessa que a grade não sustenta

**4 ofertas em toda a janela** (`📅 Agente ofereceu`):

| Lead | Slots dados ao LLM | Slots apresentados | Escapatória | Escolheu? |
|---|---:|---:|---|---|
| Marcio | 9 | **5** | ✅ | não |
| Clarice | 9 | **5** | ✅ | "Nenhum" |
| Kaylla | 2 | **2** | ✅ | **sim → reunião** |
| Daniela | 6 | **5** | ✅ | não |

**P3-B cumprido em 4 de 4.** O corte de 9→5 é regra da missão (`qualificacao_fluxo.py:564`), não
corte no código, e o LLM obedeceu sempre; a escapatória apareceu sempre.

**Mas a escapatória promete o que não existe.** O texto oferece *"manhã/tarde/**noite**"* e
`consultoras.json` tem grade **09:00–18:30, seg–sex**. Duas das quatro pediram noite; uma pediu
sábado. **3 de 4 ofertas bateram no limite da grade** — e nas 3 o agente não tinha para onde
procurar, então repetiu a lista.

Agrava para a Daniela: `AGENDAMENTO_JANELA_DIAS=4` numa sexta devolve **só a segunda-feira** —
5 slots, um único dia, nenhum à noite.

### 3.5 Colisão SDR × agente — 20 conversas em 2 dias, o dia todo

```sql
SELECT to_char(transferido_em,'DD HH24:MI'), contact_wa_id FROM nat_qualificacao_state
 WHERE transferido_motivo='outbound_manual_sdr' AND transferido_em >= '2026-08-27';
```

**20 leads distintos** — 6 em 27/08, **14 em 28/08**. Por horário SP:

```
27/08  09:32 ×1                          28/08  10:16 ×1   (Julia)
27/08  11:10–11:11 ×5                    28/08  11:07 ×3   11:21 ×1   11:49–11:50 ×2
                                         28/08  13:13 ×1   13:15–13:16 ×2   13:40–13:46 ×3
                                         28/08  15:21 ×1
```

> **Correção à caracterização anterior.** O recon das 11:15 concluiu *"todo dia às ~11h"*. Com o
> dia inteiro à vista: **7 rajadas distintas hoje, de 10:16 a 15:21**. É contínuo, não é um
> horário.

De onde os leads foram cortados: `aguardando_ano` ×8, `aguardando_formacao` ×5,
`aguardando_atuacao` ×4, **`escolhendo_slot` ×3** (Clarice, Marcio, Daniela).

O texto disparado afirma sempre *"não tive sucesso"* 🥺. Ele foi para:

* **Daniela**, escolhendo horário **2 horas antes**;
* **Cláudia**, que tinha respondido **13 minutos antes**;
* **Morgana**, que tinha dado as duas formações **18 minutos antes**;
* **Clarice**, a quem o agente acabara de oferecer transferência;
* **Marcio**, no meio da negociação de horário;
* **Julia**, que tinha perguntado o preço na noite anterior.

**O código faz o certo ao silenciar** (`silenciar` evita duas vozes, e o log registra o motivo).
O problema é **quem entra na lista do disparo**. Não é bug: é critério de seleção.

### 3.6 Fórmulas repetidas

**72 falas do agente** na janela (`nat_etapa IS NOT NULL`):

| Fórmula | Ocorrências | % das falas |
|---|---:|---:|
| Contém `Perfeito, ` | 13 | 18% |
| Contém `Entendi` | 14 | 19% |
| Contém `Ótimo` | 3 | 4% |
| **Abrem com `Perfeito`/`Entendi`/`Ótimo`** | **29** | **40%** |

Duas em cada cinco falas abrem com a mesma fórmula. E o gênero oscila: **"obrigado" 3× contra
"obrigada" 1×** — a Nat se apresenta como *"a assistente do CENAT"* (feminino) e concorda no
masculino na maioria das vezes. Na mesma conversa da Kaylla: *"obrigado por contar"*; na da
Daniela: *"obrigada por compartilhar"*.

### 3.7 Resposta duplicada quando o lead manda 2 mensagens

Quando duas mensagens chegam em poucos segundos, **cada uma vira um turno** e as duas são
respondidas:

```
Marcio  27 09:07  "2022 acho" + "Rsrs"
        → "Perfeito, Marcio — entendi que você concluiu em 2022. Como e onde você atua?"
        → "Ótimo, Marcio — você concluiu em 2022. Como e onde você atua?"          [2s]

Kaylla  27 18:45  "2023" + "Eu já fui aluna do cenat"
        → "Perfeito, Kaylla — você concluiu a graduação em 2023. Como e onde você atua?"
        → "Que bom que já foi aluna do CENAT, Kaylla! Como e onde você atua?"      [3s]

Daniela 28 09:07  "A noite" + "A partir das 20 hrs"
        → duas recusas quase idênticas                                             [10s]
```

**3 casos em 25 estados.** A mesma pergunta duas vezes é a coisa mais visivelmente robótica da
janela.

### 3.8 Aberturas — nome e curso ✅

**25 de 25** com primeiro nome correto e curso expandido corretamente:

```sql
SELECT count(*) FROM messages WHERE nat_etapa LIKE 'nat_abertura%' AND timestamp >= '2026-08-27'
  AND (content LIKE 'Olá, !%' OR content LIKE '%Graduação em .%'
       OR content ~ 'Pós-Graduação em [A-Z][a-z]+[A-Z]');
-- 0 linhas
```

**Nenhum `Pós-Graduação em .`, nenhum CamelCase cru, nenhum nome vazio.** Os 10 aliases novos e
o S3-3/S3-4 seguraram em volume — **este item está fechado no caminho do agente**.

**Mas o CamelCase vazou pelo outro caminho.** Os templates do **disparo manual** não passam pelo
`resolve_course_name`:

```
27 17:47  SDR → Yasmin:   "...aplicação na Pós Graduação BoasPraticasEAD..."
28 11:07  SDR → Dyenifer: "...aplicação na Pós Graduação BoasPraticasEAD..."
26 09:55  SDR → Yasmin:   "...um encaixe *BoasPraticasEAD*as *16:30*..."
```

Confere com o buraco de alias: `PosBoasPraticasEAD` tem **29 leads em agosto e nenhum alias**.

```sql
SELECT l.sub_source, count(*) FROM exact_leads l
 WHERE l.register_date >= '2026-08-01' AND l.sub_source IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM course_aliases a WHERE lower(a.alias)=lower(l.sub_source))
 GROUP BY 1 ORDER BY 2 DESC;
```

| `sub_source` sem alias | leads em agosto |
|---|---:|
| **`PosBoasPraticasEAD`** | **29** |
| `interuruguai2026` | 28 |
| `PosGraduacaoEconomiaSolidariaTurma1` | 13 |
| `intercambiotrieste2026` | 7 |
| `PosPraticasDialogicasTurma1` | 5 |
| `intercambioportugal2026` | 1 |

**Cobertura de agosto: 362 de 445 = 81,3%**, exatamente o esperado (42%→81%). Dos 6 buracos, 3
são intercâmbio/congresso (produto diferente) e **3 são pós que precisam de alias** — 47 leads.

**Ressalva de dado:** **4 das 25 aberturas foram para leads de teste** — *"Olá, Fafaf!"*,
*"Olá, Thobias!"*, *"Olá, Smoke!"*, *"Olá, John!"*. Todas em 27/08; **nenhuma em 28/08**.
Consumiram teto de envio e entraram nas métricas. Se descontadas, 27/08 vira **15 estados
reais, 7 respostas = 47%**.

---

## 4. Antes e depois

Amostra pequena dos dois lados — 43 estados no recon de 26/08, 25 aqui. Não force conclusão.

| | 26/08 (recon anterior) | 27/08 | 28/08 (até 17:30) |
|---|---|---|---|
| Estados | 43 | 19 | 6 |
| Resposta à abertura | 47% | **37%** (47% sem os testes) | 33% |
| Turnos de LLM instrumentados | **0** (sem instrumentação) | 23 | 10 |
| Falhas de contrato | indeterminável | **0** | **0** |
| Latência mediana do turno | não medida | **1 431 ms** | 1 612 ms |
| **Conversas mortas por silêncio em etapa ativa** | **≥5** | **0** ✅ | **0** ✅ |
| Disparos do vigia `agente_mudo` | — |  **0 / 20 armados** | 0 / 9 armados |
| Avisos `agente_parado` novos | 2 | **0** | **0** |
| Esgotamento de pool | ~70 tracebacks (25/08) | **0** | **0** |
| **Reuniões marcadas pelo agente** | **0** | **1** ✅ | 0 |
| Transferências por falha do agente | 6 | **0** | **0** |
| Aberturas que não saíram | — | 2 de 21 (9,5%) | 4 de 10 (40%, **todas até 09:47**) |
| Conversas cortadas por `outbound_manual_sdr` | 22 | 6 | **14** |
| Lembretes falsamente `executado` | não medido | 1 de 8 | 1 de 7 |
| Encerramentos com rótulo | 0 | 0 | **2, ambos corretos** ✅ |

**A queda de 47% → 37% não é comparável de forma limpa** — a janela anterior era 88% Exact, e
27/08 trouxe 6 estados de LP (17% de resposta) e 4 leads de teste. Descontando os testes, 27/08
dá **47%**, idêntico. Não houve regressão de resposta.

**O que mudou de verdade, em duas linhas:** o silêncio virou zero e ficou zero por dois dias; o
contrato não falhou nenhuma vez em 33 turnos; a primeira reunião saiu e o lembrete dela foi
confirmado pela lead. **Em troca**, apareceu um vazamento na entrada (§1.3) e um erro de
gravação na saída (§1.5), e a colisão com o disparo manual **dobrou**.

---

## 5. A fila e os casos nominais

### 5.1 As 69 da triagem — 63 sem nada, 6 com template, ZERO respostas

Critério: qualquer outbound, em qualquer das duas grafias, depois de **27/08 14:15** (a hora em
que a lista foi entregue).

```
total = 69   |   recebeu algo depois = 6   |   sem nada = 63
```

E os 6 são **todos template de campanha**, nenhum é resposta à pergunta que os pôs na fila:

| wa_id | Quando | O que recebeu |
|---|---|---|
| `558388046720` (Álefe) | 28 10:43 | *"Havíamos agendado seu processo seletivo…"* |
| `556697112651` (Sônia) | 28 11:49 | *"Fiz uma nova tentativa de contato…"* |
| `559284118443` (Ana) | 28 11:50 | *"Fiz uma nova tentativa de contato…"* |
| `556281727120` (Pricilla) | 28 15:21 | *"A nossa consultora Victória tentou o contato…"* |
| `555185440615` (Juliana) | 28 15:34 | *"Obrigada por se inscrever na nossa Pós-Graduação…"* |
| `558388041204` (Diana) | 28 16:36 | *"Fiz uma nova tentativa de contato…"* |

**Nenhuma das 69 recebeu resposta humana em ~27 horas.**

| Caso | Situação |
|---|---|
| **Cintia Pessoa** (nº 1) | **Não atendida.** O time escreveu 27/08 13:14, ela respondeu 13:30 *"Estou me organizando com relação a tempo"* — **nada desde então (28h)**. Foi respondida uma vez e largada de novo. |
| **Mikaelle** (nº 2) | **Não atendida.** Última mensagem dela 27/08 09:13. **32 horas.** |

**Sobre a reunião da Mikaelle (era 27/08 09:45):** `agendamentos` id **216**, `passo='agendado'`,
box 43789295, meeting 4735740 — **inalterado**. Não houve reagendamento, não há registro de
comparecimento no Hub, e o lembrete que ela pediu foi descartado (§1.6). **Daqui não dá para
saber se ela compareceu** — o Hub não registra presença. O que dá para afirmar: ela pediu
confirmação e ninguém confirmou.

**A leitura justa do §5**, à luz do §2.12: o time **não** está parado — trabalhou bem a lista da
campanha hoje (Wilian, Monica, Yasmin, Daniela, Giulliana). A fila de triagem é que não foi
tocada. É priorização, não capacidade.

### 5.2 As reuniões — os 3 lembretes pendentes de ontem, todos resolvidos

| Reunião | Quando | Lembrete | Situação **agora** |
|---|---|---|---|
| **Natália Nordin** (222) | 27/08 15:45 | ação 266 — `executado` 15:15 | ✅ enviado, ela respondeu 15:15 |
| **Amanda Cristina** (220) | **28/08 14:15** | ação 240 — `executado` **13:45** | ✅ **saiu** (era `pendente` na apuração das 11:15) |
| **Kaylla** (251) | **28/08 13:30** | ação 376 — `executado` **13:00** | ✅ **saiu**, e ela respondeu *"Ok"* |
| Caroline (246) | 28/08 11:15 | ação 354 — `executado` 10:45 | ✅ enviado |
| Reynaldo (257) | 28/08 12:00 | ação 392 — `executado` **11:30** | ✅ **saiu** (era `pendente`) |
| Niuzeth (209) | 27/08 14:15 | ação 171 — `executado` 13:45 | ✅ enviado |
| Quezia (243) | 28/08 15:00 | ação 348 — `executado` 14:30 | ✅ enviado |
| Josiqueila (187) | 28/08 09:00 | ação 64 — `executado` 08:30 | ❌ **não saiu** (§1.6) |

**Os três lembretes que estavam pendentes às 11:15 saíram todos.** 13 de 15 no total.

**Dois agendamentos com slot hoje estão `falhou`**, ambos com `HTTP 400: Previous stage is
no…` — Beatriz (157, 28/08 15:00) e Vera Rosa (152, 28/08 16:30). Criados em 24-25/08, anteriores
à janela; não investiguei, fora do escopo, mas são duas reuniões de hoje que não existem na Exact.

### 5.3 Erica e Amanda Pavão — vencem amanhã, como previsto

```sql
SELECT id, contact_wa_id, etapa, transferido_motivo, updated_at FROM nat_qualificacao_state
 WHERE contact_wa_id IN ('5598984703419','5544998336280');
```

| Lead | Estado | Situação | `encerrar_inativo` |
|---|---|---|---|
| **Amanda Pavão** `5544998336280` | 44, `transferido_humano` | **transferida por mensagem manual** 27/08 09:32. Foi atendida. | ação 185 — **29/08 09:01**, `pendente` |
| **Erica** `5598984703419` | 20, **`aguardando_ano`** | **ainda ATIVA**, sem movimento desde **26/08 09:36** | ação 195 — **29/08 09:36**, `pendente` |

A Erica é **o único `encalhado` que a varredura acusa** — notificada uma vez, em 26/08 23:07
(`AGENTE PARADO — conversa encalhada há 811 min`), e **ninguém agiu em 42 horas**. A
anti-repetição do S4-2 está funcionando como projetada: avisa uma vez e cala. O efeito colateral
é que um aviso ignorado some.

Como **o lead falou por último** nos dois casos, ambos sairão como **`sem_resposta_do_agente`** —
o rótulo correto, e a leitura correta: **nós calamos**. Com os dois `inatividade` de hoje
(§1.10), amanhã a distinção terá casos dos dois lados.

---

## 6. Fechamento — 6 itens, em ordem de impacto

### (a) Conserto de código

**1. Toda reunião do agente entra na Exact com o curso errado — §1.5.** ⭐ *novo*
`qualificacao_fluxo.py:1193` passa `origem=None`; `origens.py:173-178` devolve o padrão da LP
(`PosMulheridades`). **4 de 4** agendamentos do agente, incluindo a única reunião real. O curso
certo já está resolvido a 700 linhas dali (`_curso_do_lead`, `:474-483`) e o valor está na
allowlist. Custa um parâmetro. Vale aproveitar e passar `extras` junto — o formulário da LP
vira `null` na mesma chamada.

**2. A abertura não sai quando o contato existe na outra grafia — §1.3.**
`nat_sender.py:164` usa `==`; `qualificacao_fluxo.py:311` resolve tolerante e descarta o objeto
(`:921-924`). **6 leads em 2 dias**, sem estado e sem rastro. É a mesma decisão RISCO 3 ×
canonização do §7 de `FIX_BULK_TEMPLATE_FK_20260828.md` — resolvê-la resolve os dois. Conserto
mínimo independente: usar o `contato.wa_id` já resolvido em `:921` para o estado e o envio.

**3. `lembrete_reuniao` descarta o retorno do envio — §1.6.**
`qualificacao_fluxo.py:1462`. Ler o `bool` e levantar `AcaoIgnorada` com o motivo, como o P0-B
fez em `processar_texto`. **2 de 15** lembretes `executado` sem terem saído — um deles para a
Mikaelle, que perguntava exatamente aquilo.

*Menores, do mesmo lote:* resposta duplicada quando chegam 2 mensagens juntas (§3.7, 3 casos —
uma janela curta de agrupamento resolve); e o rótulo do turno em `:1115`, que usa grafia e nome
de etapa diferentes do resto (§1.2 — cosmético, mas quebra o `grep`).

### (b) Dado e configuração

**4. Três buracos de alias e uma limpeza — §3.8.**
`PosBoasPraticasEAD` (**29 leads em agosto**), `PosGraduacaoEconomiaSolidariaTurma1` (13) e
`PosPraticasDialogicasTurma1` (5) não têm alias, e o CamelCase já está chegando ao lead pelos
templates manuais (*"Pós Graduação BoasPraticasEAD"*). Junto: **4 leads de teste** (`SMOKE`,
`John Doe`, `Thobias`, `Fafaf`) receberam abertura em 27/08 e sujam toda métrica; e o **estado 89
(Marcos)** precisa ser silenciado à mão (§1.9) antes que ele responda.

**5. A escapatória da oferta promete "noite" e a grade vai até 18:30 — §3.4.**
**3 das 4 ofertas** bateram nesse limite. Ou a grade ganha faixa noturna, ou o texto da missão
para de oferecer "noite"/fim de semana. Hoje ele promete o que o sistema não tem, e o agente
repete a mesma lista porque não há o que procurar.

### (c) Decisão de gestão

**6. O disparo em massa está cortando conversa viva o dia todo — §3.5.**
**20 leads em 2 dias, 14 só hoje**, em 7 rajadas de 10:16 a 15:21 — incluindo a Cláudia 13
minutos depois de ela responder e a Daniela em `escolhendo_slot`. A mensagem afirma *"não tive
sucesso"* para quem falou com a gente minutos antes. **O código faz o certo ao silenciar; o
critério de quem entra na lista é decisão do time.** Excluir do disparo quem tem estado do agente
em etapa ativa é a mudança de maior retorno deste recon, e é de configuração, não de engenharia.

---

**E, fora da lista, as duas coisas que mais custam hoje:**

* **A fila de 69 não andou** — 63 sem nada, 6 com template, **zero respostas humanas em 27
  horas**. Não é falta de capacidade: o time trabalhou bem hoje (§2.12), só que na lista da
  campanha. É priorização.
* **Existe um funil sem dono.** Quatro leads perguntaram sobre **congresso/evento** (carga
  horária, local, submissão de resumo, informações) no mesmo número, e nenhuma foi respondida —
  nem pelo agente (não têm lead de pós na Exact) nem pelo SDR (a fila dele é de pós). Ninguém
  está errado; ninguém está atendendo.

O agente parou de perder gente por silêncio, e agora tem dois dias de prova disso. Quem perde
gente hoje é o passo seguinte — e, no caso do §1.5, o passo anterior à consultora.

---

## ANEXO A — `base.sql`

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
msg AS (   -- mesma expressão de chave sobre messages
  SELECT m.*, CASE WHEN length(regexp_replace(m.contact_wa_id,'\D','','g')) IN (12,13)
                        AND regexp_replace(m.contact_wa_id,'\D','','g') LIKE '55%'
                   THEN substr(regexp_replace(m.contact_wa_id,'\D','','g'),3,2)
                        || right(regexp_replace(m.contact_wa_id,'\D','','g'),8)
                   ELSE regexp_replace(m.contact_wa_id,'\D','','g') END AS chave
  FROM messages m
),
abertura AS (
  SELECT DISTINCT ON (e.id) e.id est_id, e.origem, date(e.criado_sp) dia,
         m.nat_etapa, m.status, m.timestamp ts
  FROM est e JOIN msg m ON m.chave = e.chave
  WHERE m.nat_etapa IN ('nat_abertura_agendado','nat_abertura_qualificacao',
                        'nat_abertura_sem_formacao')
    AND m.timestamp >= e.criado_sp - interval '5 minutes'
  ORDER BY e.id, m.timestamp
),
resp AS (
  SELECT DISTINCT ON (a.est_id) a.est_id, m.timestamp ts
  FROM abertura a JOIN est e ON e.id=a.est_id JOIN msg m ON m.chave = e.chave
  WHERE m.direction='inbound' AND m.timestamp > a.ts
  ORDER BY a.est_id, m.timestamp
)
```

Sanidade: **25 estados / 25 aberturas / 9 respostas** na janela — bate com
`count(*) from nat_qualificacao_state where created_at >= '2026-08-27 03:00'`.

**Armadilha de shell, para quem repetir isto:** `regexp_replace(...,'\D','','g')` dentro de
`psql -c "…"` no bash tem o `\D` comido antes de chegar ao Postgres, e a query devolve 0 linhas
em silêncio. Cometi o erro uma vez nesta apuração (concluí que o Marcos não tinha nenhuma
mensagem; ele tem). Passar o SQL por **stdin** (`… | psql`) em vez de `-c` resolve. `psql -f`
não serve: o usuário `postgres` não lê o diretório de scratch.

---

## ANEXO B — divergências entre o estado esperado e o encontrado

Conferidas antes de qualquer número; nenhuma invalida a análise.

| Item do briefing | Encontrado | Leitura |
|---|---|---|
| "NAT ativa desde 24/08" | `qualificacao_enabled=true`, `qualificacao_start_at=24/08 23:16` ✅ · **`nat_enabled=false`, `nat_start_at=NULL`** | Correto: são switches diferentes. O `nat_enabled` é o fluxo NAT **antigo** (`nat_flow_state`), desligado. O agente de qualificação roda pelo `qualificacao_enabled`. |
| "Sprints 1-4 deployados" | Todos verificados em produção: `🧠` vivo (33 turnos), `_concluir` com fecho (Lucas), P3-B em 4/4, teto adiando (ação 326 ×3), `AcaoIgnorada` (5 skips), varredura a cada 15 min (164 ciclos), `encerrado_motivo` distinguindo (2 casos) | Sem divergência |
| "Threads unificadas, divisão nova não nasce mais" | Confirmado para o **Hub** e para a **leitura**. Mas a canonização meia-feita produziu **dois defeitos novos** — §1.3 (abertura) e §1.9 (gravação do disparo, já corrigido em `94867c1`) | A afirmação é verdadeira para o sintoma original; a decisão RISCO 3 × canonização segue aberta e agora tem 2 consequências medidas |
| "Migração (c) dos 812 históricos não feita" | Confirmado — não há sinal de migração | Sem divergência |
| "Aliases: cobertura 42%→81%" | **81,3%** (362/445 em agosto) ✅ | Bate. Os 5+2 pendentes com a gestora seguem pendentes; os 3 que faltam para pós estão no §3.8 |
| "Fila de 69, entregue 27/08 à tarde" | 69 confirmadas; **63 sem nada, 6 só com template** | Sem divergência na lista; ver §5.1 |
| "Relógios: `messages.timestamp` naive-SP, `created_at` UTC" | Confirmado, e vale também para `transferido_em`, `run_at`, `encerrado_em` (naive-SP) | Sem divergência |
| `sent_by_ai` como marcador do agente | **`false` em 100% das mensagens do agente** | **Divergência de leitura, não do briefing.** Quem separa agente de humano é `nat_etapa`. Registrado no §2 porque qualquer métrica futura que use `sent_by_ai` vai dar zero. |

**Interrupções e restarts na janela** (todos anotados onde afetam a leitura): backend reiniciado
em 27/08 10:04 SP, 27/08 14:04 SP e **28/08 11:04 SP** (este último é o deploy do `94867c1`). O
journald cobre a janela inteira sem lacuna.
