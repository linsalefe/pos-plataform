# Investigação — origem dos envios e "queda" de leads

**Data:** 2026-07-26 · **Modo:** somente-leitura (nenhum envio, sync, restart ou migração)
**Fontes:** banco `cenat_whatsapp`, `journalctl -u cenat-backend`, API Exact Spotter v3 (GET), Graph API v21 (GET), código em `backend/app/`

> **Resumo em uma linha:** as duas premissas que motivaram a sprint estão erradas — não houve reenvio
> fantasma e não houve queda de captação. O que existe é **um** incidente: a partir de 23/07 a Meta parou
> de entregar mensagem para número **sem conversa prévia** com a empresa, e a boas-vindas é o único
> template que só fala com esse público.

---

## 1. Um problema ou dois?

**Dois.** Template e mensagem livre são populações independentes e a separação confirma a correção da premissa.

**Mensagem livre — ruído de fundo permanente, não é o incidente:**

| dia | falhas / total | | dia | falhas / total |
|---|---|---|---|---|
| 06/07 | 2 / 9 (22%) | | 20/07 | 18 / 30 (60%) |
| 13/07 | 5 / 32 (16%) | | 21/07 | 8 / 70 (11%) |
| 15/07 | 14 / 44 (32%) | | 22/07 | 0 / 36 (0%) |
| 16/07 | 7 / 11 (64%) | | 23/07 | 12 / 12 (100%) |
| 17/07 | 18 / 18 (100%) | | 24/07 | 0 / 3 (0%) |

Já falhava a 100% em **17/07** e a 60% em **20/07** — dias antes do incidente. Em **24/07**, quando a
boas-vindas estava em 22/22 falhas, a mensagem livre estava em **0/3**. Confirmado: é a janela de 24h
fechando, linha de base de qualquer sistema WhatsApp. **Ignorar nas próximas análises.**

**Template — aí sim há degrau.** A premissa de que "43 falhas de boas-vindas em 23/07" também estava
errada: das 43, só **3** eram do template configurado no painel. O template que falha é o
`nat_boasvindas` real — corpo "*Sou a Nat, assistente virtual do CENAT*":

| dia | nat_boasvindas | demais templates |
|---|---|---|
| 16/07 | 0 / 17 (0%) | 1 / 71 (1,4%) |
| 20/07 | 2 / 16 (12,5%) | 1 / 108 (0,9%) |
| 21/07 | 2 / 32 (6,3%) | 1 / 305 (0,3%) |
| 22/07 | 4 / 20 (20%) | 0 / 181 (0%) |
| **23/07** | **22 / 22 (100%)** | 21 / 129 (16,3%) |
| **24/07** | **22 / 22 (100%)** | 11 / 177 (6,2%) |
| **25/07** | **9 / 9 (100%)** | — |

**53 de 53 envios de boas-vindas falharam em três dias seguidos.**

---

## 2. Reenvio ou lead novo?

**Nenhum reenvio. Zero.**

```
contatos com >1 nat_boasvindas desde 20/07:  0 linhas
```

Cada contato recebeu a boas-vindas **exatamente uma vez**. A distribuição temporal é de um envio por vez,
em cadência de ~10–11 min (`08:02, 08:12, 08:23, 08:33…`) — a assinatura exata do sync. Não há rajada.

A duplicidade que aparecia na consulta original (contatos com 4–6 templates, rajadas às 14:27 e 12:03–12:06)
é **real, mas é outra coisa**: são campanhas de follow-up dos SDRs pela tela de Automações, com templates
diferentes a cada disparo (`ultimo_contato`, `desconto25`, `tentativa_ligacao`). Comportamento esperado.

**O "43 envios para 3 leads" não existe.** O `3` veio de `register_date`, que está NULL para 91% da base
(ver §4). Os leads novos de verdade em 23/07 foram **22**, e receberam 22 boas-vindas. Um para um.

---

## 3. Origem dos envios

Quatro caminhos chamam `send_template_message`:

| origem | arquivo | login? | trava boas-vindas |
|---|---|---|---|
| sync automático | `exact_spotter.py:223` | n/a (job) | é o dono do template |
| reenvio individual | `exact_routes.py:186` | ✅ `Depends(get_current_user)` | única porta com `force=True` |
| envio em massa | `exact_routes.py:224` | ❌ **sem login** | ✅ `bloquear_se_boas_vindas` (l. 275) |
| envio avulso / agendado | `routes.py:230` / `:852` | ❌ **sem login** | ✅ `bloquear_se_boas_vindas` (l. 234, 859) |

**Veredito sobre o endpoint sem autenticação: hipótese derrubada.**

- O commit `9692952` é de **12/07 14:15**, não de ontem. Já estava em produção durante todo o período.
- Mesmo antes dele, `bloquear_se_boas_vindas` (commit `a6ef138`) já impedia que `nat_boasvindas` saísse
  por qualquer porta que não o sync ou o reenvio individual.
- Nos logs retidos (24/07 em diante) há **zero** chamadas a `resend-welcome`.
- Não existem envios duplicados para nenhum contato (§2) — não há o que explicar.

`/bulk-send-template` e `/send/*` **seguem sem login** — 12 chamadas em 24/07, de três IPs distintos, todas
de horário comercial e coerentes com uso humano da tela. É uma exposição real e conhecida (o próprio
`9692952` a registra como "fora do escopo, decisão do dono"), mas **não** é a origem do incidente:
a trava do template continua fechada nesses caminhos.

**Marcador de origem: não existe.** `sent_by_ai` é `false` em **100%** dos templates de 20 a 25/07,
inclusive nos disparados pelo sync automático. Não há `sent_by`, `created_by` nem equivalente na tabela
`messages`. Hoje é impossível distinguir origem humana de automática por dado — só por correlação com
o horário e o log HTTP.

---

## 4. Captação: caiu ou o sync quebrou?

**Nenhum dos dois. A captação não caiu e o sync não perde lead.** A queda de 85% é um artefato de medição.

**Comparação com a fonte** (API Exact, funis de pós 18535/18537/25588):

| dia | Exact (fonte) | banco local (`welcome_sent_at`) | `register_date` (métrica usada) |
|---|---|---|---|
| 20/07 | 11 | 16 | 5 |
| 21/07 | 20 | 32 | 5 |
| 22/07 | 12 | 20 | 3 |
| 23/07 | 10 | 22 | **3** |
| 24/07 | 15 | 22 | **4** |
| 25/07 | 13 | 9 | **1** |

Fonte e banco batem em ordem de grandeza e **ambos são estáveis**. Teste direto de perda:

```
81 leads de pós na fonte entre 20 e 25/07
81 presentes no banco local        →  0 faltando
81 com welcome_status = 'sent'     →  0 pulados
```

**Causa raiz da métrica falsa** — `parse_datetime` em `exact_spotter.py:105`:

```python
return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
```

A Exact devolve **7 dígitos** de fração de segundo (`2026-07-25T16:45:14.2081828Z`). O
`fromisoformat` do Python 3.10 só aceita 3 ou 6 → `ValueError` → `except` → `None`.

```
registerDate presente na API:        500 / 500
parse_datetime devolve datetime:      47 / 500   (só os que têm 6 dígitos)
register_date NULL no banco:       7881 / 8660   (91%)
```

O campo está NULL para quase toda a base — e é justamente o campo em que a "queda de 20/dia para 3, 4, 1"
foi medida. Os números `3, 4, 1` são leads com fração de 6 dígitos, não leads do dia.

**Sync rodando normalmente:** 3 erros isolados (`❌ Erro no sync Exact Spotter`) em 24/07 10:09, 24/07 10:41
e 25/07 10:41, todos com recuperação no ciclo seguinte. Cadência de 10 min mantida. `POS_FUNNEL_IDS`
(`18535,18537,25588`) e `auto_welcome_config` (`enabled=t`, `nat_boasvindas`, mesmos funis, alterado por
Isa em 13/07) **não mudaram** durante a janela.

> **Não avisar a Isa sobre queda de captação — não houve queda.**

---

## 5. Hipótese de categoria MARKETING: **derrubada**

Consulta ao Graph API, os 53 templates do WABA `1360246076143727`:

```
51 templates MARKETING  (inclui nat_boasvindas)
 2 templates UTILITY    (hello_world, zz_teste_plataforma — nenhum em uso)
```

**Todos os templates em produção são MARKETING** — tanto o que falha 100% quanto os que passam a 84–94%
no mesmo dia, no mesmo número, pelo mesmo token (canal único, `id=1`). Uma constante não explica uma
diferença. A hipótese não sobrevive.

Também descartados:
- `nat_boasvindas` está **APPROVED**, sem `rejected_reason`.
- Número **GREEN / CONNECTED / APPROVED** — não é bloqueio de conta.
- **Nenhum deploy entre 18/07 e 25/07 20:42** — o degrau de 23/07 não veio do código.
- Erro de parâmetro/estrutura descartado: **todas** as falhas têm `wamid` real e `welcome_status='sent'`.
  A Meta **aceitou** cada envio (HTTP 200) e reportou a falha depois, pelo webhook. Erro de estrutura
  seria 400 síncrono, sem wamid.

### O que a separação das populações revela

O discriminante não é o template — é **o destinatário nunca ter conversado com a empresa**:

| recorte | primeiro contato | já tinha histórico |
|---|---|---|
| 14/07 – 22/07 | 17 / 226 (**7,5%**) | 8 / 1051 (**0,8%**) |
| 23/07 – 25/07 | 57 / 69 (**82,6%**) | 28 / 290 (**9,7%**) |

O degrau é de ~11× e atinge os **dois** grupos ao mesmo tempo, em todos os templates. O `nat_boasvindas`
aparece em 100% porque é o único template que, por construção, só fala com número de primeiro contato —
os demais falam majoritariamente com base já engajada e por isso só degradaram de 0,8% para 9,7%.

**É um só incidente, com um só mecanismo, escalado pela mistura de público de cada template.**

### Achado adicional não previsto na sprint — a entrega parou, não só a boas-vindas

| dia | sent | delivered | read | failed | **% entrega confirmada** |
|---|---|---|---|---|---|
| 20/07 | 25 | 36 | 72 | 21 | **70,1%** |
| 21/07 | 160 | 81 | 155 | 11 | **58,0%** |
| 22/07 | 66 | 95 | 72 | 4 | **70,5%** |
| 23/07 | 108 | **0** | **0** | 55 | **0,0%** |
| 24/07 | 166 | **0** | 3 | 33 | **1,5%** |
| 25/07 | 0 | 0 | 0 | 9 | **0,0%** |

A partir de 23/07 **nenhuma** mensagem foi confirmada como entregue — nem as que não falharam. Elas ficam
em `sent` para sempre. O webhook não está quebrado: os `failed` continuam chegando normalmente.

O inbound acompanha: 55 → 109 → 55 → **28 → 14 → 9** (20 a 25/07). Menos gente recebendo, menos gente
respondendo.

**Isto é maior que o problema da boas-vindas** e não estava no escopo da sprint.

---

## 6. O que ainda depende de esperar um envio real

1. **O código de erro da Meta.** É a peça que fecha o caso. `error_code`/`error_title`/`error_details`
   estão NULL em todas as 225 falhas — a instrumentação (`257f4a0`) subiu em 26/07 01:58, depois da
   última falha (25/07 13:52). O código distingue as hipóteses que sobraram:
   - `131049` — "Meta chose not to deliver" (limite de marketing por usuário) → confirma o mecanismo de §5
   - `130472` — usuário em experimento de limite de marketing
   - `131026` — número não recebe mensagem
   - `132xxx` — problema de template (já improvável, dado o wamid)
2. **Se o degrau persiste ou já passou.** 25/07 teve só 9 envios e nada foi enviado em 26/07 até agora
   (02:26, madrugada). Não dá para dizer se ainda está em curso.
3. **Por que `delivered`/`read` sumiram.** Precisa de um envio novo para saber se voltou.

**Nenhuma outra pergunta da sprint depende de envio novo — as quatro estão respondidas.**

---

## Correções de premissa (consolidado)

| premissa | veredito |
|---|---|
| 43 falhas de boas-vindas em 23/07 | ❌ eram 3 no template do painel; 22 no `nat_boasvindas` real |
| Alguém está reenviando boas-vindas | ❌ zero duplicatas; 1 envio por contato |
| Endpoint sem auth explicaria os envios | ❌ auth desde 12/07, e a trava do template já cobria |
| Volume de leads caiu 85% | ❌ estável; `register_date` NULL em 91% por bug de parser |
| Sync pode estar perdendo lead | ❌ 81/81 conferidos contra a fonte |
| Categoria MARKETING causa a falha | ❌ 100% dos templates em uso são MARKETING, inclusive os que passam |
| Falhas de áudio/documento fazem parte | ❌ ruído de janela de 24h, anterior ao incidente |

**O que se sustenta:** a partir de 23/07, entrega para número sem histórico caiu de 92,5% para 17,4%,
e a confirmação de entrega zerou para todo mundo. Causa externa, sem correspondência em deploy.

---

*Nenhuma alteração de sistema foi feita. Não há proposta de correção neste documento, por escopo.*
