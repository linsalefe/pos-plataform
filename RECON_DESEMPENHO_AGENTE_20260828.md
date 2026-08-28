# RECON — desempenho do agente em 27/08 e 28/08

**Somente leitura.** Nenhum envio, nenhuma escrita, nenhuma migração. Todo número vem com a
query ou o comando que o gerou.

Janela: **27/08 00:00 SP → 28/08 11:15 SP** (14:15 UTC). São **23 estados novos** — 19 em
27/08, 4 em 28/08 — e **32 turnos de LLM**. É uma amostra pequena, e toda leitura abaixo
carrega esse N. 28/08 é dia parcial e a última abertura foi às 09:00 SP.

Convenção de fuso, verificada contra o banco: `messages.timestamp`, `transferido_em`,
`nat_scheduled_actions.run_at` são **naive-SP**; `created_at` e o journald são **UTC**.

**Interrupção registrada:** este recon parou às 13:53 UTC para diagnosticar o
`bulk-send-template` caindo em 500 e retomou às 14:15. O conserto está em
`FIX_BULK_TEMPLATE_FK_20260828.md`; o restart às **14:04:26 UTC** é meu e está anotado onde
afeta a leitura.

---

## 0. O veredito curto

**O silêncio do agente acabou, e a primeira reunião saiu.** Zero conversas mortas por
silêncio em etapa ativa, zero falhas de contrato em 32 turnos, zero esgotamento de pool,
zero 502 — e Kaylla Soares virou a primeira reunião marcada ponta a ponta pelo agente, com
box na Exact. Os seis buracos da auditoria de 26/08 estão tapados e há caso real provando
quatro deles.

**E três coisas novas estão comendo o funil pela borda**, nenhuma delas visível nas métricas
de silêncio:

1. **A abertura não sai para 1 em cada 4 leads de hoje** — regressão da canonização,
   crescendo (§1.3). O lead não recebe nada e não sobra estado no banco.
2. **O disparo em massa corta conversa viva às ~11h, todo dia** — 8 dos 23 estados (35%)
   morreram assim, incluindo a lead mais quente do período (§3.5).
3. **Lembrete marcado `executado` sem ter sido enviado** — 2 de 21, e um deles é a Mikaelle
   perguntando do próprio horário (§1.6).

O agente está funcionando. O que está falhando agora é o que está **em volta** dele.

---

## 1. Os números, por dia

### 1.1 Estados novos, entrega e resposta

```sql
-- CTEs est/msg/abertura/resp: ANEXO A
SELECT a.dia, a.origem, a.nat_etapa, count(*), count(*) FILTER (WHERE a.status IN ('read','delivered')),
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
| **28/08 total** | | | **4** | 4 | 0 | **1** | **25%** |

**A LP entrou no funil** — 6 estados em 27/08, contra 2 em todo o recon anterior. E responde
mal: **1 de 6 (17%)**, contra 37% da Exact no mesmo dia. O lead que preenche a LP acabou de
falar com a gente pela página; a abertura chega como se fosse a primeira conversa.

As 3 `failed` de 27/08 têm causa nomeada e **não é nossa**:

| Número | Código | Título |
|---|---|---|
| `5571985252525` | 131026 | Message undeliverable |
| `5567999151808` | **131049** | not delivered to maintain healthy ecosystem engagement |
| `5527999805197` | **131049** | idem |

`131049` é limite de engajamento da Meta por destinatário — o mesmo que reapareceu hoje no
disparo manual. **3 ocorrências em 2 dias.** Não é bug nosso, mas é volume perdido que
nenhuma correção de código recupera, e vale à gestora.

### 1.2 Turnos do LLM — a instrumentação P0-E está viva

O recon anterior mediu **zero linhas `🧠 LLM`**. Agora:

| | 27/08 | 28/08 |
|---|---:|---:|
| Turnos | **23** | **9** |
| `acao=nenhuma` | 22 | 9 |
| `acao=agendar_slot` | **1** | 0 |
| `etapa_cumprida=true` | 15 | 4 |
| Latência mediana | **1 431 ms** | 1 548 ms |
| Latência p90 / máx | 2 023 / 6 590 ms | 2 325 / 2 584 ms |

* **Falhas de contrato: ZERO** em 32 turnos. Nenhum `🛟`, nenhum fallback, nenhum
  `LLM indisponível`. Prompt ~1 880 tokens, resposta 59–152, teto 1 000 — **sem truncagem**.
* **`ofertar_agenda` obsoleta: ZERO** (`grep -c 🏷️` = 0). A dívida de contrato da H1 da
  auditoria segue existindo no enum e continua inócua na prática — agora **medida**, não
  presumida.

### 1.3 ⚠️ ACHADO Nº 1 — a abertura não sai, e o lead some sem deixar rastro

```
$ journalctl | grep "contato não existe no banco"
27/08: 2   28/08: 5
```

| Dia | `iniciar_qualificacao` executadas | `skipped` — "contato não existe no banco" | % perdido |
|---|---:|---:|---:|
| 27/08 | 19 | 2 | 10% |
| **28/08** | **4** | **4** | **50%** |

**Mecânica, com arquivo:linha.** `nat_sender.py:164` procura o contato com igualdade crua:

```python
res = await db.execute(select(Contact).where(Contact.wa_id == contact_wa_id))
if contact is None:
    return recusa("contato não existe no banco")
```

`_contato_ou_criar` (`qualificacao_fluxo.py:311`) resolve o contato com
`contato_existente` — **tolerante às duas grafias** desde `05cea3f`. Quando o contato já
existe na grafia de 12 dígitos, ele o encontra e **decide não criar** o de 13. O envio então
procura o de 13 com `==`, não acha, e recusa. O objeto resolvido é descartado
(`qualificacao_fluxo.py:921-924` só testa `is None`): o estado e o envio seguem com a grafia
original.

A docstring da própria função, 26 linhas acima, descreve o invariante que foi quebrado:

> *"`Contact.wa_id == contact_wa_id`, igualdade crua. Um porteiro tolerante aqui não ajuda"*

Confirmado no banco — em 4 dos 6 números o contato **existe**, na outra grafia:

| Alvo do envio | Existe em `contacts` como |
|---|---|
| `5549999333881` | `554999333881` (Fernanda) |
| `5585988719031` | `558588719031` |
| `5551998557793` | `555198557793` |
| `5555996238065` | `555596238065` (Sandra Diell) |

**O estado é revertido junto** (`select ... where contact_wa_id in (...)` → **0 linhas**): o
lead não recebe nada, não vira estado, não entra em fila nenhuma. Só existe a linha do
journald. É o desaparecimento mais limpo do sistema.

Isto é a mesma raiz do §7 de `FIX_BULK_TEMPLATE_FK_20260828.md` — a decisão RISCO 3 ×
canonização — agora com **segunda consequência medida** e taxa subindo.

### 1.4 Progressão do funil

| | 27/08 | 28/08 | Janela |
|---|---:|---:|---:|
| Estados | 19 | 4 | **23** |
| Com formação | — | — | 19 |
| Deram o ano | 6 | 1 | **7** |
| Deram atuação | 5 | 1 | **6** |
| Deram motivação | 4 | 1 | **5** |
| **Reunião marcada pelo agente** | **1** | 0 | **1** |

Onde estão hoje:

| Etapa | Motivo | 27/08 | 28/08 |
|---|---|---:|---:|
| `aguardando_ano` | (ativo) | 8 | 1 |
| `transferido_humano` | **`outbound_manual_sdr`** | **5** | **3** |
| `aguardando_formacao` | (ativo) | 3 | — |
| `concluido` | (ativo) | 2 | — |
| `aguardando_atuacao` | (ativo) | 1 | — |

**Todas as 8 transferências são `outbound_manual_sdr`.** Zero transferências por decisão do
agente, zero por falha. O agente não desistiu de ninguém — foi interrompido (§3.5).

### 1.5 A reunião — o zero saiu do zero ✅

**Kaylla Soares Ponciano de Castro**, `5521951019121`, LP, `Pos TEA V3`:

```
21:06:33  🚀 Agente abriu com 5521951019121: nat_abertura_qualificacao → aguardando_ano
21:45:38  📅 Agente ofereceu 2 horário(s)
21:46:00  🧠 LLM .../escolhendo_slot | acao=agendar_slot dado={'slot_id': '2026-08-28T13:30:00'}
21:46:01  📦 agendamento #251: box 43809078 criado ... com Victória Rodrigues
21:46:05  ✅ agendamento #251: lead 51610927 agendado em 2026-08-28T13:30:00
21:46:05  ⏰ NAT scheduler: lembrete_reuniao agendado para 28/08 13:00 (id=375)
21:46:06  ✅ Agente concluiu 5521951019121 (reunião 251)
```

`agendamentos` id **251**, `passo='agendado'`, slot **28/08 13:30**. Abertura → reunião em
**40 minutos**, dos quais a conversa foram **52 segundos**.

Isto valida **P0-A** (nenhum `InvalidRequestError` — o bug que matou a Fabiana morreu) e
**P0-D** (`✅ Agente concluiu`). É o primeiro caso real de ponta a ponta.

### 1.6 ⚠️ ACHADO Nº 3 — lembrete marcado `executado` sem ter sido enviado

21 lembretes na janela. **Dois estão marcados `executado` e não chegaram ao lead:**

| Ação | Lead | Quando | O que o log diz |
|---|---|---|---|
| **226** | **Mikaelle** `5541992680313` | 27/08 09:15 | `🔒 NAT não enviou (nat_lembrete_reuniao): teto de envios/hora estourado (22/20)` |
| **64** | `5591985119613` | 28/08 08:30 | `🔒 NAT não enviou (nat_lembrete_reuniao): contato não existe no banco` |

**Mecânica:** `lembrete_reuniao` (`qualificacao_fluxo.py:1462`) chama
`await send_nat_message(...)` e **descarta o `bool` de retorno**. É exatamente o buraco que
o P0-B fechou em `processar_texto` — e que não foi aplicado aqui.

A docstring do handler (`:1428-1429`) comemora o conserto S4-1: *"eram `return` mudo e
viravam `executado` com motivo NULL… Agora são `AcaoIgnorada`: `skipped` com o motivo
GRAVADO"*. O S4-1 cobriu as **pré-checagens** (sem `agendamento_id`, reunião não agendada,
já começou, sem consultora). **O envio em si continua mudo.**

O caso da Mikaelle é o pior possível e fecha um ciclo do §5: ela escreveu **09:13** *"Oi…
gostaria de confirmar o horário da conversa com a consultora"*; o lembrete que responderia
exatamente isso foi descartado em silêncio **09:15**; a reunião era **09:45**; ninguém
respondeu até agora.

### 1.7 Vigias, rede de última instância e infraestrutura

| Sinal | Resultado |
|---|---|
| `vigiar_resposta` (`agente_mudo`) | **28 armados, 28 cancelados, 0 disparos** |
| `agente_parado` | 0 avisos novos; varredura roda a cada 15 min (`29 em etapa ativa, 1 encalhado, 1 já avisado`) |
| Rede de última instância (P0-C) | **nunca disparou** |
| Falsos positivos | nenhum |
| `QueuePool limit` | **0** (P1-A: `pool_size=20, max_overflow=20, echo=False`) |
| 502 no nginx | **0** |
| Teto 20/h | 8 estouros: 3 aberturas **adiadas corretamente**, 1 lembrete **perdido** (§1.6) |

Os 28 `vigiar_resposta` cancelados são a prova mais limpa de que o silêncio acabou: **todo
turno falou**, e o vigia nunca precisou disparar.

Nota de fundo: **6× `❌ Erro no sync Exact Spotter`** na janela. O sync se recupera sozinho
na tentativa seguinte (`total_synced: 9222`). Não investiguei — fora do escopo.

### 1.8 O silêncio — a query definitiva

Inbound sem resposta do agente, com estado, na janela:

```sql
SELECT ... FROM inb i
WHERE NOT EXISTS (SELECT 1 FROM msg o WHERE o.chave=i.chave
                  AND o.direction='outbound' AND o.timestamp > i.ts)
```

| Estado | Lead | Inbound | Janela |
|---|---|---|---|
| 64 | Mikaelle | 27 09:13 | pós-transferência |
| 37 | Cintia Pessôa | 27 13:30 | pós-transferência |
| 73 | giulliana | 27 13:35 | pós-transferência |
| 67 | Natália Nordin | 27 15:15 | pós-transferência |
| 100 | Daniela | 28 11:09 ×2 | pós-transferência |

**Silêncio do agente em etapa ativa: ZERO.** Os 6 casos são todos posteriores à
transferência — o agente calou **de propósito**, que é o comportamento correto. As três
camadas (P0-B, P0-C, S4-2) seguraram.

**Mas os 6 leads seguem sem atendimento.** O agente parou certo; ninguém assumiu.

---

## 2. Transcrições

Todas as conversas com diálogo real na janela. Horário SP. `LEAD` / `NAT`.

### 2.1 Kaylla — `5521951019121` — *a reunião*

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
```

### 2.2 Daniela — `5582999810488` — *a melhor lead do período, cortada ao meio*

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
                  especializada. O que despertou seu interesse pela pós-graduação em TEA?
28 09:06:43 LEAD  Tenho filho e sobrinhos autistas
28 09:06:46 NAT   Entendi — seu interesse pela pós em TEA vem da experiência pessoal com seu filho e
                  seus sobrinhos autistas, e faz todo sentido querer aprofundar esse conhecimento
                  para ajudar na vida deles e na sua prática profissional. Vou ver os horários
                  disponíveis e já te retorno.
28 09:06:49 NAT   Perfeito, Daniela — obrigada por compartilhar 💙
                  Tenho esses horários de consultoria com a consultora para você escolher:
                  - Segunda (31/08) às 09:00
                  - Segunda (31/08) às 10:30
                  - Segunda (31/08) às 12:00
                  - Segunda (31/08) às 14:15
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
28 11:07:12 NAT   Ola Daniela, é o Thobias do CENAT ✨
                  Tentei realizar uma nova tentativa de contato referente a sua aplicação na Pós
                  Graduação Transtorno do Espectro Autista (TEA) mas até o momento não tive sucesso 🥺
                  Qual seria o melhor horário para contato?
28 11:09:33 LEAD  Da p falar por aqui?
28 11:09:40 LEAD  Pois estou no trabalho
                  ← SEM RESPOSTA. Agente silenciado (outbound_manual_sdr).
```

### 2.3 Lucas — `5551996323362` — *P0-D no ar, e a costura aparecendo*

```
27 09:00:55 NAT   Olá, Lucas! Que bom te ver por aqui ✨
                  Recebi sua aplicação para a Pós-Graduação em Autolesão, Suicídio e Luto e sua
                  reunião com nossa consultora Victória Rodrigues já está confirmada para
                  27/08 às 11:15 📅
                  Enquanto isso, quero te conhecer um pouco melhor. Vi que sua formação é em
                  Psicologia — em que ano você concluiu?
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
27 10:45:43 NAT   Olá, Lucas! Passando para lembrar da sua reunião de hoje às 11:15 📅
                  Nossa consultora, Victória Rodrigues, vai te ligar aqui mesmo pelo WhatsApp, por
                  este mesmo número. Fique de olho no celular no horário combinado! 😊
```

### 2.4 Marcio — `556792894362` — *aplicou no curso errado, e o agente vendeu assim mesmo*

```
27 09:01    NAT   Olá, Marcio! Que bom te ver por aqui ✨
                  Vi que você aplicou para a nossa Pós-Graduação em Infantojuvenil EAD... Vi que sua
                  formação é em Serviço Social. Em que ano você concluiu?
27 09:07    LEAD  2022 acho
27 09:07    LEAD  Rsrs
27 09:07    NAT   Perfeito, Marcio — entendi que você concluiu em 2022. Como e onde você atua
                  profissionalmente hoje?
27 09:07    NAT   Ótimo, Marcio — você concluiu em 2022. Como e onde você atua profissionalmente hoje?
27 09:08    LEAD  Coordenadoria Regional de educação Secretaria do estado de educação - MS . Eu
                  trabalho serviço especializado de apoio psico social acompanhando as escolas do
                  interior do MS.
27 09:08    NAT   Entendi — você atua na Coordenadoria Regional de Educação do Estado do MS... O que
                  despertou seu interesse por esta pós em Infantojuvenil EAD?
27 09:09    LEAD  Na verdade eu achei q fosse um curso sobre combate a bullying
                  ..q são muitos casos e q reflete na saúde mental dos estudantes...
27 09:09    NAT   Entendi: você achou que o curso seria sobre combate ao bullying, porque há muitos
                  casos que impactam a saúde mental dos estudantes — e é isso que te mobiliza.
27 09:09    NAT   Perfeito, Marcio — obrigado por explicar; faz sentido você buscar formação prática
                  sobre bullying na escola. Vou te oferecer alguns horários para conversar com a
                  consultora e tirar todas as suas dúvidas sobre o conteúdo do curso e se ele cobre
                  estratégias de prevenção e intervenção em bullying. Posso te oferecer:
                  - 27/08 às 12:00
                  - 27/08 às 13:30
                  - 27/08 às 16:30
                  - 28/08 às 11:15
                  - 28/08 às 15:00
                  Se nenhum desses horários servir, diga que dia e período (manhã/tarde) você prefere
                  que eu procure.
27 09:10    LEAD  Sábado dia 29 no período da manhã as 10:00 hrs . Pode ser?
27 09:10    NAT   Marcio, quem passa disponibilidade fora das opções que te ofereci é a consultora na
                  conversa — eu só tenho aqueles horários. Você prefere que eu agende um dos horários
                  disponíveis para a manhã de sábado 27/08 às 12:00, 28/08 às 11:15 ou 28/08 às 12:00?
27 11:11    NAT   Ola Marcio, é o Thobias do CENAT ✨ Tentei realizar uma nova tentativa de contato...
```

### 2.5 Clarice — `5531999818666` — *pediu noite, ofereceu transferir, ninguém transferiu*

```
27 09:01    NAT   Olá, Clarice! ... Vi que sua formação é em Psicologia. Em que ano você concluiu?
27 09:30    LEAD  2026
27 09:30    NAT   Perfeito, Clarice — você concluiu a graduação em 2026. Como e onde você atua
                  profissionalmente hoje?
27 09:45    LEAD  Prestacao de serviço para a prefeitura como psicóloga clinica
27 09:45    NAT   Entendi: você atua como psicóloga clínica prestando serviço para a prefeitura. O que
                  despertou seu interesse pela pós em TEA?
27 09:45    LEAD  Demanda de muitas crianças com laudo
27 09:45    NAT   Entendi que seu interesse pela pós em TEA vem da demanda de muitas crianças com
                  laudo — faz sentido, é um campo com muita procura e você já lida com isso no dia a
                  dia. Vou ver os horários disponíveis e te trago em seguida.
27 09:45    NAT   Ótimo, Clarice — obrigado por compartilhar. Seguem algumas opções de horários para
                  conversar com a consultora sobre a pós em TEA (escolha apenas um):
                  - Qui 27/08 às 12:00
                  - Qui 27/08 às 16:30
                  - Sex 28/08 às 11:15
                  - Sex 28/08 às 13:30
                  - Sex 28/08 às 16:30
                  Se nenhum desses servir, me diz que dia e período (manhã/tarde) você prefere que eu
                  procuro outras opções para você. 🙂
27 09:46    LEAD  A noite tem?
27 09:46    NAT   Quem passa horários fora dessa lista (noite ou outros) é a consultora na conversa;
                  por aqui só tenho os horários que te mostrei. Qual dos horários que te mandei você
                  prefere?
27 09:46    LEAD  Nenhum
27 09:46    NAT   Entendi que nenhum desses horários serve, Clarice. Quer que eu passe o seu contato
                  para a consultora para ela verificar outras opções de horários noturnos?
27 11:10    NAT   Ola Clarice, é o Thobias do CENAT ✨ Tentei realizar uma nova tentativa de contato...
```

### 2.6 Julia — `5521983371003` — *perguntou o preço às 23:40; ninguém respondeu*

```
27 23:38    LEAD  Olá! Tudo bem? Fiz minha aplicação na turma da Pós-Graduação Online em Psicologia
                  Escolar e gostaria de mais informações.
27 23:40    LEAD  Por gentileza quero informações sobre o investimento. O pagamento pode ser feito de
                  outra firma, sem ser por cartão? E que valor seria?
28 09:00    NAT   Olá, Julia! Que bom te ver por aqui ✨
                  Vi que você se interessou pela nossa Pós-Graduação em Psicologia Escolar. Antes de
                  te mostrar os próximos passos, gostaria de conhecer um pouco da sua trajetória.
                  Me conta: qual é a sua formação?
28 11:07    NAT   Ola Julia, é o Thobias do CENAT ✨ Tentei realizar uma nova tentativa de contato...
```

### 2.7 Mikaelle e Cintia — *o topo da fila de triagem*

```
—— Mikaelle 554192680313 ——
26 13:25    LEAD  Certo, obrigada.
27 09:13    LEAD  Oi… gostaria de confirmar o horário da conversa com a consultora
                  ← SEM RESPOSTA ATÉ AGORA. Lembrete das 09:15 descartado pelo teto (§1.6).
                    Reunião era 27/08 09:45.

—— Cintia Pessôa 558185088547 ——
26 15:12    LEAD  No momento não tenho interesse. Estou me preparando para o início do ano...
27 13:14    NAT   Entendo, Cintia! 😊 Só para eu conseguir compreender melhor e não insistir...
27 13:14    NAT   Te pergunto porque, dependendo do que está pesando para você agora, ta...
27 13:30    LEAD  Estou me organizando com relação a tempo
                  ← SEM RESPOSTA. Foi atendida e largada de novo.
```

Conversas sem estado do agente e sem nenhuma resposta na janela (fila humana):
`cintia gomes` (27 08:40), `mariana` (27 08:51), `Joaciara Franco` (27 11:56),
`Edvânia Alves` (27 11:57–11:58), `Aldiane` (27 15:45), `Caroline Medeiros` (27 17:41),
`Alice Avelino` (27 22:27), `Sandra Diell` (27 23:33), `Arthur` (28 10:59).

---

## 3. Leitura qualitativa

### 3.1 Perguntas fora do roteiro — insumo da base de conhecimento

Verbatim, com o que o agente fez:

| Tema | Verbatim | O que o agente fez |
|---|---|---|
| **Horário noturno** | *"A noite tem?"* (Clarice) | Recusou certo e ofereceu transferir. **Não transferiu.** |
| **Horário noturno** | *"A noite"* / *"A partir das 20 hrs"* (Daniela) | Repetiu a mesma lista **duas vezes**, verbatim |
| **Fim de semana** | *"Sábado dia 29 no período da manhã as 10:00 hrs. Pode ser?"* (Marcio) | Recusou e **alucinou** (§3.3) |
| **Preço / pagamento** | *"quero informações sobre o investimento. O pagamento pode ser feito de outra firma, sem ser por cartão? E que valor seria?"* (Julia) | **Ignorou por completo** — respondeu 9h20 depois perguntando a formação |
| **Modalidade** | *"Será on-line ?"* (Alice Avelino) | Nunca respondida (sem estado) |
| **Carga horária de congresso** | *"Congresso Online Internacional Boas Práticas em Gêneros e Sexualidades Vale quantas horas?"* (Aldiane) | Nunca respondida — **produto diferente**, fora do funil de pós |
| **Canal** | *"Da p falar por aqui?"* (Daniela) | Sem resposta — agente já silenciado |

**Horário fora da grade é o tema nº 1: 3 das 7.** E é estrutural, não de conhecimento —
ver §3.4.

### 3.2 Validação de motivação — específica, não genérica ✅

O agente **cita o que o lead disse**, em todos os casos:

* Daniela: *"vem da experiência pessoal com seu filho e seus sobrinhos autistas"*
* Clarice: *"vem da demanda de muitas crianças com laudo — faz sentido, é um campo com muita procura e você já lida com isso"*
* Lucas: *"é uma demanda que aparece muito na atenção básica"*
* Marcio: *"você achou que o curso seria sobre combate ao bullying"*

Nenhuma validação genérica. É o ponto mais forte da qualidade conversacional.

**Mas aceita não-resposta como motivação:** Kaylla respondeu *"Sou psicóloga escolar"* à
pergunta *"o que despertou seu interesse?"* — o LLM gravou
`motivacao='Sou psicóloga escolar'` com `etapa_cumprida=True` e seguiu.

### 3.3 ⚠️ Alucinação de data — Marcio

Ele pediu **sábado 29/08 de manhã**. O agente respondeu:

> *"…horários disponíveis para a **manhã de sábado 27/08 às 12:00**, 28/08 às 11:15 ou
> **28/08 às 12:00**?"*

Três erros numa frase: **27/08 era quinta**, **12:00 não é manhã**, e **28/08 às 12:00 nunca
foi ofertado** (a lista tinha 11:15 e 15:00). O modelo inventou um slot que a grade não deu.
Único caso na janela, mas é a classe de erro que marca reunião no horário errado.

### 3.4 Ofertas de agenda — P3-B cumprido, e uma promessa que a grade não sustenta

| Lead | Slots dados ao LLM | Slots apresentados | Escapatória | Escolheu? |
|---|---:|---:|---|---|
| Marcio | 9 | **5** | ✅ | não |
| Clarice | 9 | **5** | ✅ | "Nenhum" |
| Kaylla | 2 | **2** | ✅ | **sim → reunião** |
| Daniela | 6 | **5** | ✅ | não |

**P3-B está cumprido nas 4 ofertas reais** — o LLM corta 9 para 5 e sempre inclui a
escapatória. (O `[N slots]` do log é o contexto dado ao modelo, não o que o lead vê; P3-B é
regra da missão — `qualificacao_fluxo.py:564` — e não corte no código.)

**Mas a escapatória promete o que não existe.** O texto oferece *"manhã/tarde/**noite**"*, e
`consultoras.json` tem grade **09:00–18:30, seg–sex**. Não há horário noturno nem de fim de
semana em lugar nenhum. Duas das quatro leads pediram noite; uma pediu sábado. O agente não
tem para onde procurar, e repete a mesma lista.

Agrava para a Daniela: a janela `AGENDAMENTO_JANELA_DIAS=4` numa sexta devolve **só a
segunda-feira** — 5 slots, um único dia, nenhum à noite.

### 3.5 ⚠️ ACHADO Nº 2 — colisão SDR × agente, todo dia às ~11h

**8 dos 23 estados (35%) morreram por `outbound_manual_sdr`**, em duas rajadas:

```
27/08 11:10–11:11 SP → 5 estados   (Clarice, Marcio, giulliana, Jacileila, 5522981024236)
28/08 11:07–11:14 SP → 3 estados   (Julia aguardando_formacao, Adriana aguardando_ano,
                                     Daniela escolhendo_slot)
```

Do log de hoje:

```
14:07:12  🤝 Agente silenciado em 5582999810488: escolhendo_slot → transferido_humano
          (motivo=outbound_manual_sdr, por Thobias)
```

O texto disparado é sempre o mesmo: *"Tentei realizar uma nova tentativa de contato… mas até
o momento **não tive sucesso** 🥺"*. Ele foi para:

* **Daniela**, que estava escolhendo horário **2 horas antes**;
* **Clarice**, a quem o agente tinha acabado de oferecer transferência;
* **Marcio**, no meio da negociação de horário;
* **Julia**, que tinha perguntado o preço na noite anterior.

O mecanismo funciona como projetado — `silenciar` evita duas vozes, e é o certo. O problema
é **quem entra na lista do disparo**: leads em conversa ativa, com uma mensagem que afirma o
contrário do que está na tela. Não é bug de código; é critério de seleção do disparo.

### 3.6 Fórmulas repetidas

58 falas do agente na janela:

| Fórmula | Ocorrências | % das falas |
|---|---:|---:|
| `Perfeito, <nome> —` | **12** | 21% |
| `Entendi…` | **12** | 21% |
| `Ótimo…` | 3 | 5% |
| **Abrem com uma das três** | **27** | **47%** |

Quase metade das falas abre com a mesma fórmula. E o gênero oscila: **"obrigado" 3× contra
"obrigada" 1×** — a Nat se apresenta como *"a assistente do CENAT"* e concorda no masculino
na maioria das vezes.

### 3.7 Resposta duplicada quando o lead manda 2 mensagens

Quando duas mensagens do lead chegam em poucos segundos, **cada uma vira um turno** e as
duas são respondidas:

```
Marcio  27 09:07  "2022 acho" + "Rsrs"
        → "Perfeito, Marcio — entendi que você concluiu em 2022. Como e onde você atua?"
        → "Ótimo, Marcio — você concluiu em 2022. Como e onde você atua?"   [2s depois]

Kaylla  27 18:45  "2023" + "Eu já fui aluna do cenat"
        → "Perfeito, Kaylla — você concluiu a graduação em 2023. Como e onde você atua?"
        → "Que bom que já foi aluna do CENAT, Kaylla! Como e onde você atua?"  [3s depois]

Daniela 28 09:07  "A noite" + "A partir das 20 hrs"
        → duas recusas quase idênticas, 10s de intervalo
```

**3 casos em 23 estados.** A mesma pergunta duas vezes é a coisa mais visivelmente robótica
da janela.

### 3.8 Aberturas — nome e curso ✅

**23 de 23** com primeiro nome correto e curso expandido corretamente. **Nenhum
`Pós-Graduação em .`, nenhum CamelCase cru.** Os 10 aliases novos e o S3-3/S3-4 seguraram
em volume — este item está fechado.

Ressalva de dado, não de código: **4 das 23 aberturas foram para leads de teste** —
*"Olá, Smoke!"*, *"Olá, John!"* (John Doe), *"Olá, Thobias!"*, *"Olá, Fafaf!"*. Consumiram
teto de envio e entraram nas métricas.

---

## 4. Antes e depois

Amostra pequena dos dois lados — 43 estados no recon anterior, 23 aqui. Não force conclusão.

| | 26/08 (recon anterior) | 27/08 | 28/08 (parcial) |
|---|---|---|---|
| Estados | 43 | 19 | 4 |
| Resposta à abertura | 47% | **37%** | 25% |
| Turnos de LLM instrumentados | **0** (sem instrumentação) | 23 | 9 |
| Falhas de contrato | indeterminável | **0** | **0** |
| Latência mediana do turno | não medida | **1 431 ms** | 1 548 ms |
| Conversas mortas por silêncio em etapa ativa | **≥5** | **0** | **0** |
| Disparos do vigia `agente_mudo` | — | **0/20 armados** | 0/8 |
| Esgotamento de pool | ~70 tracebacks (25/08) | **0** | **0** |
| **Reuniões marcadas pelo agente** | **0** | **1** ✅ | 0 |
| Transferências por falha do agente | 6 | **0** | **0** |
| Aberturas que não saíram | — | 2 (10%) | **4 (50%)** ⚠️ |
| Transferências por `outbound_manual_sdr` | 22 (51%) | 5 (26%) | 3 (75%) |

**A queda de 47% → 37% na resposta à abertura não é comparável de forma limpa:** a janela
anterior era 88% Exact, e 27/08 trouxe 6 estados de LP (17% de resposta) que puxam a média.
Só Exact em 27/08 dá **6/13 = 46%**, praticamente igual.

O que mudou de verdade: **o silêncio virou zero, o contrato não falhou nenhuma vez, e a
primeira reunião saiu.** Em troca, apareceu um vazamento novo na entrada (§1.3).

---

## 5. A fila e os casos nominais

### 5.1 As 69 da triagem — 68 seguem abertas

```sql
-- outbound em qualquer das duas grafias depois de 27/08 14:15 (entrega da lista)
respondidas = 1   ainda_abertas = 68
```

E a única "respondida" é **`558388046720` (Álefe)**, com um **template de disparo em massa**
às 28/08 10:43 — *"Olá, Álefe! Tudo bem? ✨ Havíamos agendado seu proc…"*, não uma resposta
humana à pergunta dele.

**Nenhuma das 69 recebeu resposta humana em ~21 horas.**

| | |
|---|---|
| **Cintia Pessoa** (nº 1) | **Parcialmente.** O time escreveu 27/08 13:14; ela respondeu 13:30 *"Estou me organizando com relação a tempo"*; **sem resposta desde então** (~22h). Voltou para a fila. |
| **Mikaelle** (nº 2) | **Não.** Última mensagem 27/08 09:13. Reunião 216 era **27/08 09:45**, `passo='agendado'`. O lembrete das 09:15 foi descartado pelo teto (§1.6). Não há como saber daqui se ela compareceu — mas ela pediu confirmação e ninguém confirmou. |

### 5.2 As reuniões

| Reunião | Quando | Lembrete | Situação |
|---|---|---|---|
| **Natália Nordin** (222) | 27/08 15:45 | **ação 266 — `executado` 27/08 15:15 ✅** | passo `agendado` |
| **Amanda Cristina** (220) | **28/08 14:15** | **ação 240 — `pendente` para 13:45 ✅ de pé** | passo `agendado` |
| **Kaylla** (251) | **28/08 13:30** | ação 376 — `pendente` para 13:00 | a reunião do agente |
| Caroline (246) | 28/08 11:15 | ação 354 — `executado` 10:45 ✅ | passo `agendado` |
| Reynaldo (257) | 28/08 12:00 | ação 392 — `pendente` 11:30 | passo `agendado` |

### 5.3 Erica e Amanda Pavão

* **Amanda Pavão** `5544998336280` — **transferida por mensagem manual** em 27/08 09:32
  (`outbound_manual_sdr`). Foi atendida. O `encerrar_inativo` 185 vence **29/08 09:01**.
* **Erica** `5598984703419` — **ainda ATIVA** em `aguardando_ano`, sem nenhum movimento desde
  **26/08 09:36**, quando ela escreveu *"Bom dia!"* e *"Formação em Psicologia"*. Ninguém
  respondeu. O `encerrar_inativo` 195 vence **29/08 09:36**.

Como **o lead falou por último** nos dois casos, ambos sairão como
**`sem_resposta_do_agente`** — o rótulo correto, e a leitura correta: **nós calamos**. Vale
registrar que a distinção `inatividade` × `sem_resposta_do_agente` **ainda não tem um único
caso real**: `select encerrado_motivo ... where encerrado_motivo is not null` = **0 linhas**.
Os primeiros encerramentos vencem amanhã.

---

## 6. Fechamento — 6 itens, em ordem de impacto

### (a) Conserto de código

1. **A abertura não sai quando o contato existe na outra grafia** — §1.3.
   `nat_sender.py:164` usa `==`; `qualificacao_fluxo.py:311` resolve tolerante e descarta o
   objeto. **10% das aberturas em 27/08, 50% em 28/08**, sem estado e sem rastro. É a mesma
   decisão RISCO 3 × canonização do §7 de `FIX_BULK_TEMPLATE_FK_20260828.md` — resolvê-la
   resolve os dois. Conserto mínimo independente: usar o `contato.wa_id` já resolvido em
   `:921` para o estado e o envio, em vez do `wa_id` de entrada.

2. **`lembrete_reuniao` descarta o retorno do envio** — §1.6.
   `qualificacao_fluxo.py:1462`. Ler o `bool` e levantar `AcaoIgnorada` com o motivo, como o
   P0-B fez em `processar_texto`. **2 de 21 lembretes** marcados `executado` sem terem
   saído — um deles para a Mikaelle, que estava perguntando exatamente aquilo.

3. **Resposta duplicada quando chegam 2 mensagens juntas** — §3.7. 3 casos em 23 estados.
   Uma janela curta de agrupamento (debounce) antes de montar o turno resolveria os três.

### (b) Dado e configuração

4. **A escapatória da oferta promete "noite" e a grade vai até 18:30** — §3.4. Duas leads
   pediram noite, uma pediu sábado; o agente repete a mesma lista porque não há o que
   procurar. Ou a grade ganha faixa noturna, ou o texto da missão para de oferecer
   "noite"/fim de semana. Hoje ele promete o que o sistema não tem.

5. **4 das 23 aberturas foram para leads de teste** (`SMOKE`, `John Doe`, `Thobias`,
   `Fafaf`) — §3.8. Consomem teto de envio e sujam toda métrica. Filtro no gatilho ou limpeza
   na Exact.

### (c) Decisão de gestão

6. **O disparo em massa está cortando conversa viva todo dia às ~11h** — §3.5.
   **8 dos 23 estados (35%)**, incluindo a Daniela em `escolhendo_slot` e a Julia que tinha
   perguntado o preço. A mensagem afirma *"não tive sucesso"* para quem falou com a gente
   2 horas antes. O código faz o certo ao silenciar o agente; **o critério de quem entra na
   lista é decisão do time.** Excluir do disparo quem tem estado do agente em etapa ativa
   resolveria, e é a mudança de maior retorno deste recon.

**E, fora da lista, o que mais custa hoje:** a fila de 69 não andou — **68 abertas, zero
respostas humanas em 21 horas** — e 6 leads da janela seguem esperando depois de o agente
ter transferido corretamente. O agente parou de perder gente por silêncio; agora quem perde
é o passo seguinte.

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
msg AS (   -- mesma expressao de chave sobre messages
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

Sanidade: **23 estados / 23 aberturas / 8 respostas** na janela — bate com
`count(*) from nat_qualificacao_state where created_at >= '2026-08-27 03:00'`.
