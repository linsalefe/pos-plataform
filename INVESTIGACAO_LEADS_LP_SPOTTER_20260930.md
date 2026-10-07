# Investigação — leads da LP que não aparecem no Spotter (30/09/2026)

**Somente leitura.** Nenhuma escrita no banco (sessão psql com `default_transaction_read_only=on`),
nenhuma chamada de escrita à Exact (só `GET /Leads`), nada reiniciado, nada enviado.
Horários em **São Paulo** salvo indicação; journal e nginx estão em UTC (SP = UTC−3).

## Achado principal

**O José Roberto Lopes nunca preencheu o formulário do ponto de vista do servidor.** Nenhuma
requisição dele chegou ao nginx: nem o `POST /lead`, nem o `GET /slots` que o `obrigado.html`
dispara **incondicionalmente** ao carregar. Ele chegou até o obrigado (a mensagem dele é o texto
pré-preenchido do botão de WhatsApp que só existe nessa página) e escreveu pelo WhatsApp. Como o
lead espontâneo não cria lead na Exact (Bloco A nunca implementado), ele não existe em lugar
nenhum além do Hub.

A premissa 3 do pedido ("o POST /lead falhou") está **quase** certa: o POST não *falhou* no
backend, ele **nunca chegou**. A premissa 2 ("0 Origem inválida em 14 dias") está **errada**:
foram 11 pessoas perdidas por origem inválida (`'Pos DH T4'`), ver a Fase 2.

## Fase 1 — José

Telefone real: **`556699050115`** (DDD **66**, e não 56; formato do WhatsApp sem o nono dígito).

| fonte | o que registra |
|---|---|
| `agendamentos` | **nada.** 0 linhas por telefone (`%9050115%`) ou nome, em qualquer data. Entre 13:43 (#812, teste) e 14:46 (#813, Nayla) de 29/09 não há linha nenhuma |
| nginx `/api/agendamento/*` | **nada** entre 13:08 e 14:46 de 29/09. O servidor estava no ar: o webhook da Meta com a mensagem dele entrou às 14:16 (17:16 UTC) |
| journal | **nada** do agendamento na janela. Último reinício às 13:42 (deploy do alias), 34 min antes |
| nginx error.log | só dois `SSL bad key share` de scanners (167.172.146.235, 87.236.176.188), não ele |
| `contacts` | id 10090, `wa_id 556699050115`, criado 29/09 14:16:31 |
| `messages` | 14:16:29 inbound: *"Olá! Tudo bem? Fiz minha aplicação na turma 2 da Pós-Graduação Online Grupos e Oficinas…"* · 15:01 outbound do Thobias |
| Exact | **0 leads** em `phone1` e `phone2` para `556699050115`, `5566999050115`, `6699050115`, `66999050115`, `555699050115`, `5556999050115`; `contains(phone1/phone2,'99050115')` e `'9050115'` → 0; `contains(lead,'José Roberto'/'Jose Roberto')` → 0. Controle: `phone1 eq '5524998121272'` → 2 e `contains(phone1,'24998121272')` → 2, então os filtros funcionam |
| Exact subSource 176808 em 29/09 | 4 leads (João Paulo, Nayla, Kelen, Humberto), batendo **1:1** com as 4 linhas de T2 na nossa tabela. Não há lead "invisível" |

**Linha do tempo:** ~14:1x preenche (ou não) o form na LP → o navegador **não alcança**
`hub.cenatdata.online` → o obrigado abre de qualquer jeito (o form redireciona no `catch` e no
timeout de 8s) → a grade não carrega, então aparece "Não há horários abertos" → 14:16 clica no
botão de WhatsApp → 15:01 o Thobias responde manualmente → nenhum lead nasce.

**Causa raiz:** a requisição ficou do lado do visitante (rede, DNS, bloqueador, navegador
embutido), ou ele chegou ao obrigado sem submeter o form. Não dá para distinguir as duas
hipóteses: sem requisição, não há User-Agent nem IP. O que está **provado** é que o nosso lado
não recebeu nada, e que o único caminho que sobra para quem cai nessa situação (o botão de
WhatsApp) não cria lead.

### Divergências da LP publicada (Grupos e Oficinas T2) em relação a `docs/form-nativo-snippet.html`

- O timeout é de **8s** (o snippet documenta 20s, dimensionado para o timeout de 15s do backend contra a Exact). Um `LeadsAdd` lento pode redirecionar sem `lead=` enquanto o lead ainda nasce; aí, se a pessoa agendar, nasce um duplicado.
- A validação de telefone do front é `≥10 dígitos`, e a do backend é `10 ou 11 após tirar o 55`. Um número com 0 na frente (`0 66 9…`) passa no front e toma 422 no backend.

## Fase 2 — 14 dias (16/09 a 29/09)

Fonte principal: nginx (`access.log` até `.14.gz`, começa em 16/09 00:07 UTC), porque 422 e 429
morrem no Pydantic ou no rate limit **antes** de gerar linha em `agendamentos`.

### POSTs por status

| rota | 200 | 400 | 422 | 429 | 502 |
|---|---|---|---|---|---|
| `/lead` | 169 | 19 | 1 | 0 | 0 |
| `/agendar` | 55 | 34 | 0 | 44 | 51 |

`agendamentos` no mesmo período: **toda linha tem `lead_id`** (170 `lead_criado`, 56
`agendado`, 56 `falhou`, todas estas com `lead_externo=true`, ou seja, o lead sobreviveu).

### Pessoas sem lead: IPs sem nenhum POST 200

| motivo | pessoas | dias | observação |
|---|---|---|---|
| **400 origem `'Pos DH T4'`** | **11** | 16/09 (2), 17/09 (2), 18/09, 19/09 (2), 21/09, 22/09, 26/09, 28/09 | O `/lead` toma 400, o obrigado repete com a mesma origem e também toma 400. Os 400 de 29/09 (45.167.53.59, 10:16–10:25) são **anteriores** ao alias (13:42). Depois do alias, 0 |
| **422 contrato** | 1 | 21/09 20:29, Grupos T2 (170.83.189.63) | O corpo do 422 não é logado. Carregou a grade 2s depois e não tentou agendar |
| sem requisição nenhuma (padrão José) | 1 confirmado | 29/09 | Só é visível quando a pessoa escreve pelo WhatsApp |
| 502 `SDR is disabled` | 0 leads perdidos | 16–17/09 (54 linhas) | O **horário** se perdeu, o lead ficou (incidente já conhecido: seller inativo) |
| 429 | 0 isolados | 16/09, 17/09, 26/09 | Todos de IPs que já tinham outra falha (repetição do mesmo visitante) |

### Quem escreveu pelo botão do obrigado sem ter linha na tabela

Das **68** pessoas que mandaram *"Fiz minha aplicação…"* desde 16/09, **15** não têm linha em
`agendamentos`. Conferidas na Exact por `phone1`/`phone2`, com e sem o nono dígito:

| wa_id | 1ª msg | LP | Exact | leitura |
|---|---|---|---|---|
| 558299601206 | 16/09 14:17 | DH T4 | só lead antigo (49149142, abr/26) | vítima do 400 (IP 177.3.171.3 às 14:15) |
| 558695611190 | 17/09 08:10 | DH T4 | **nenhum** | vítima do 400 (IP 131.72.184.249 às 08:10) |
| 5528999866041 | 17/09 11:46 | Grupos T2 | **nenhum** | provavelmente o **Vitor** (#624, lead 51956904, DDD 28) escrevendo de outro número depois do 502 |
| 554299747910 | 18/09 12:05 | DH T4 | **nenhum** | vítima do 400 (IP 186.236.2.204 às 12:05) |
| 559985409927 | 21/09 21:22 | DH T4 | **nenhum** | vítima do 400 (IP 189.89.12.70 às 21:22) |
| 5512997040201 | 26/09 20:07 | DH T4 | **nenhum** | vítima do 400 (IP 189.47.239.112 desde 19:49) |
| **556699050115** | **29/09 14:16** | **Grupos T2** | **nenhum** | **José: nenhuma requisição** |
| 5521982251862 | 19/09 16:58 | Grupos T2 | 52004611 (posinfantoead, mesmo dia) | tem lead em outra origem |
| 5511950792215 | 28/09 11:21 | TEA | 46326319 (dez/25) | só lead antigo |
| 559888568363, 5521979526411, 553171316325, 556798521375, 557781533673, 556791889498 | — | EAD Saúde Mental / Boas Práticas | — | LPs **fora** do fluxo nativo (fora da allowlist, zero hits no nginx) |

**Para o Thobias:** não achei nenhum caso de "lead na Exact, mas invisível na busca". A
conferência foi exaustiva para T2 em 29/09 e pontual para os 15 acima. Não conferi os 226
`lead_id` da tabela um a um contra a Exact. A lista útil para ele é outra: as **5 pessoas do DH
T4 identificáveis pelo WhatsApp e sem lead** (558695611190, 554299747910, 559985409927,
5512997040201 e 558299601206, esta com lead só de abril), mais o José. As outras 6 vítimas do
DH T4 não deixaram telefone: a requisição foi recusada antes de gravar a linha.

## Recomendações (NÃO implementadas)

1. **O botão de WhatsApp do obrigado é o ralo.** É a única saída de quem não alcança o backend,
   e não cria lead. A correção durável é do lado do Hub: uma mensagem inbound com o texto
   pré-preenchido de uma LP, vinda de um número sem lead, cria o lead (é o Bloco A do espontâneo,
   `SPRINT_BLOCO_A_ESPONTANEO_20260829.md`). A rede do visitante não se conserta daqui.
2. **Gravar a tentativa recusada por origem.** Hoje o `OrigemInvalida` é levantado antes da
   linha em `agendamentos`, então 6 pessoas do DH T4 se perderam sem telefone registrado. Uma
   linha `passo='recusado'` (ou o log com nome e telefone) tornaria o caso recuperável.
3. **Logar o detalhe do 422** (qual campo) no journal. Hoje ele não deixa rastro.
4. **Alinhar a LP publicada ao snippet:** timeout de 20s e mesma regra de telefone do backend.
5. Para depois (já listado no pedido): retry/fila local do `POST /lead` e alerta de falha recorrente no journal. O alerta teria pegado os 400 do DH T4 no primeiro dia, em vez de 13 dias depois.
