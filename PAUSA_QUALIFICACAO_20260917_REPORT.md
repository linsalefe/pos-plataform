# PAUSA_QUALIFICACAO_20260917_REPORT — agente da LP pausado, disparo manual liberado

**Executado em 17/09/2026, 16:0x SP.** Pedido operacional da Isa (16/09): suspender o agente
de pré-qualificação para quem aplicou na LP e não agendou, e liberar o disparo manual que era
pulado com "contato em conversa ativa com a NAT".

Nenhuma mensagem foi enviada a lead nesta sessão. Nenhum código foi alterado. Só SQL, cada
UPDATE precedido do SELECT equivalente e executado após aprovação.

## 0. O que mudou em relação ao plano (decisão tomada no CHECKPOINT)

O plano previa `qualificacao_enabled = false`. **Não foi isso que se fez**, porque a Fase 1
achou um efeito colateral: o lembrete T-30min de **toda** reunião (`lembrete_reuniao`, venha
ela do agente ou do obrigado.html) sai com `guard_de_abertura`, e esse guard recusa quando
`qualificacao_enabled=false` (`backend/app/qualificacao_guard.py:273-274`, chamado em
`backend/app/qualificacao_fluxo.py:1786`). Desligar o flag calaria os 6 lembretes pendentes,
o primeiro às 16:45 de hoje.

**Opção 4, aprovada:** manter `qualificacao_enabled = true` e mover o corte de data
`qualificacao_start_at` para `2099-01-01`. Verificado antes de executar:

- (a) a admissão recusa todo lead nascido antes do corte:
  `qualificacao_guard.py:148-150` — `if referencia_utc < config.qualificacao_start_at:
  bloqueia(...)`; referência ausente também bloqueia (`:146`). É o único leitor de
  `start_at` fora da tela de config (`nat_routes.py`).
- (b) `guard_de_abertura` (`:273-278`) checa só `qualificacao_enabled` e o teto por hora.
  Não compara `start_at`. Lembretes seguem saindo.

Valor original guardado para reversão: `qualificacao_start_at = '2026-08-24 23:16:29.709119'`.

## 1. Contagens antes/depois

| bloco | o quê | antes | depois |
|---|---|---|---|
| 1 | `nat_config.qualificacao_start_at` | 2026-08-24 23:16:29 | **2099-01-01 00:00:00** |
| 1 | `nat_config.qualificacao_enabled` | true | true (não mudou) |
| 2 | `nat_scheduled_actions` pendentes do agente com estado ativo | 41 (encerrar_inativo 24, follow_20h 17, iniciar_qualificacao 0) | **0** — 41 `cancelado`, motivo `pausa_operacional_20260917` |
| 3 | `nat_qualificacao_state` em etapa ativa | 25 (aguardando_ano 13, aguardando_formacao 5, escolhendo_slot 3, aguardando_motivacao 2, aguardando_atuacao 2) | **0** — 25 `encerrado`, `encerrado_motivo = pausa_operacional_20260917` |

Ficaram pendentes de propósito: 16 `encerrar_inativo` de estados já terminais (7 concluido,
9 transferido_humano — o handler as ignora sozinho, `qualificacao_fluxo.py:2265`) e os 6
`lembrete_reuniao`.

Outros eixos, conferidos e intocados: `nat_enabled=false` (já estava assim antes desta
sessão — a "NAT de botões" **não estava ligada**), `espontaneo_enabled=false`,
`follow_enabled=true`, `auto_welcome_config.enabled=false` (desde 24/08).

Verificação final:

```
qualificacao_enabled=t  qualificacao_start_at=2099-01-01 00:00:00
estados em etapa ativa ............ 0
pendentes do agente c/ estado ativo 0
pendentes restantes ............... encerrar_inativo 16 · lembrete_reuniao 6
```

Sem restart: `_carregar_config` (`qualificacao_guard.py:76-79`) faz SELECT em `nat_config` a
cada chamada; `exact_spotter._agente_assume_a_abertura` (`:151-155`) idem, por lead.

## 2. Lista para a Isa distribuir

Todos os 25 eram `sdr_name = Thobias` na Exact. Telefone mascarado (DDD + últimos 4).
"Último inbound" é a última mensagem **do lead**, relógio SP.

### 2a. No meio da conversa (o lead respondeu depois da abertura) — assumir na mão

| telefone | nome | etapa em que parou | curso | estágio Exact | último inbound |
|---|---|---|---|---|---|
| +55 51 ****-4800 | Jane Senna | aguardando_motivacao | Pos Grupos e Oficinas T2 | Agendados (18/09 15:00) | 17/09 09:20 |
| +55 69 ****-3275 | Mariana Psicóloga | aguardando_motivacao | Pos Grupos e Oficinas T2 | Follow 1 | 17/09 14:24 |
| +55 96 ****-7230 | Lucélia Monteiro Silva | escolhendo_slot | Pos Grupos e Oficinas T2 | Entrada | 17/09 14:14 |
| +55 62 ****-4176 | Angelita Campos Bandeira | escolhendo_slot | Pos Grupos e Oficinas T2 | Follow 1 | 17/09 13:32 |
| +55 12 ****-6192 | Fatima Belai | escolhendo_slot | PosMulheridades | Follow 1 | 16/09 19:46 |
| +55 15 ****-3001 | Marilza Espairane | aguardando_atuacao | Pos TEA V3 | Descartado | 17/09 09:03 |
| +55 87 ****-0876 | Denise Maria da Silva | aguardando_atuacao | posenfermagemsm | Descartado (Agendada 14/09) | 15/09 07:49 |

Os três em `escolhendo_slot` **já tinham recebido horários** e estavam escolhendo — são os
mais quentes. Jane Senna já tem reunião marcada para 18/09 15:00 (caso do Bloco 4 do RECON).

### 2b. Receberam só a abertura e nunca responderam — entram no disparo manual normal

| telefone | nome | etapa | curso | estágio Exact | abertura em |
|---|---|---|---|---|---|
| +55 28 ****-3012 | Vitor Benevenuto de Freitas | aguardando_ano | Pos Grupos e Oficinas T2 | Descartado | 17/09 11:46 |
| +55 47 ****-2281 | Mara Santos | aguardando_ano | Pos Grupos e Oficinas T2 | Entrada | 17/09 09:01 |
| +55 11 ****-3205 | Luick Cardoso Soares | aguardando_ano | Pos Grupos e Oficinas T2 | Entrada | 17/09 09:01 |
| +55 18 ****-9490 | Carolina Canola | aguardando_ano | Pos Grupos e Oficinas T2 | Entrada | 17/09 09:01 |
| +55 13 ****-6460 | Pedroilto de Souza Villanova | aguardando_ano | Pos Gestao Psicossocial T5 | Entrada | 17/09 09:01 |
| +55 14 ****-3633 | Luiza Bosco | aguardando_ano | Pos Grupos e Oficinas T2 | Entrada | 17/09 09:00 |
| +55 71 ****-4339 | José Carlos Santos Silva | aguardando_ano | Pos Grupos e Oficinas T2 | Descartado | 17/09 09:00 |
| +55 21 ****-2643 | Marcela Cutier | aguardando_ano | Pos Grupos e Oficinas T2 | Entrada | 17/09 09:00 |
| +55 14 ****-5797 | Fernanda | aguardando_ano | Pos Grupos e Oficinas T2 | Entrada | 17/09 09:00 |
| +55 51 ****-7082 | Natalia Cardoso | aguardando_ano | Pos TEA V3 | Agendados (18/09 12:00) | 17/09 09:00 |
| +55 87 ****-4353 | Simone Rodrigues Ferreira | aguardando_ano | PosPsicologiaEscolar | Descartado | 16/09 09:00 |
| +55 71 ****-8983 | Juraciara | aguardando_ano | PosGraduacaoTEA | Descartado (Agendada 18/09 17:15) | 15/09 11:36 |
| +55 51 ****-1877 | Luciane de Souza | aguardando_ano | PosGraduacaoTEA | Descartado | 15/09 09:00 |
| +55 71 ****-6110 | Alba Valéria Santos Querino | aguardando_formacao | Pos Grupos e Oficinas T2 | Entrada | 17/09 09:01 |
| +55 21 ****-7359 | Tania | aguardando_formacao | Pos TEA V3 | Follow 1 | 17/09 09:00 |
| +55 51 ****-3881 | Fernanda Ribeiro Guimarães | aguardando_formacao | PosBoasPraticasEAD | Descartado | 15/09 09:00 |
| +55 99 ****-4677 | Sirlene Adriana Prates da Cruz | aguardando_formacao | posenfermagemsm | Descartado (Agendada 09/09) | 09/09 09:00 |
| +55 21 ****-2658 | giovanna zaraga teste | aguardando_formacao | posinfantoead | — | **lead de teste** |

Observação para a operação: **10 dos 25 contatos não têm dono no Hub** (`contacts.assigned_to`
nulo). Para esses, uma resposta do lead a partir de agora **não gera notificação** para
ninguém (ver §4) — só aparece na tela de Conversas.

## 3. `agendar_abertura` e o flag — arquivo:linha

`backend/app/qualificacao_gatilho.py:112-118` (docstring de `agendar_abertura`): *"Nada aqui
verifica se o agente está ligado: quem decide é a ADMISSÃO, no handler, +5 min depois."* O
gatilho **não lê** `qualificacao_enabled` nem `qualificacao_start_at`; enfileira sempre.

Quem decide é `qualificacao_pode_iniciar` (`qualificacao_guard.py:126-156`), chamada pelo
handler `iniciar_qualificacao` em `qualificacao_fluxo.py:1143`, a cada execução, com SELECT
fresco. Com o corte em 2099 a saída é `AcaoIgnorada("não admitido: lead de <data> é anterior
ao corte 2099-01-01")` → ação `skipped` com motivo gravado (`:1147-1148`).

Os dois chamadores do gatilho (`exact_spotter.py:249-252` e `agendamento/agendar.py:531`)
continuam enfileirando durante a pausa. Consequências, **ambas permanentes por desenho**:

- **LP:** a abertura vira `skipped`. `skipped` é terminal — o lead não é abordado depois,
  quando o corte voltar.
- **Sync da Exact:** `_agente_assume_a_abertura` lê só o booleano (`exact_spotter.py:155`) e
  segue true, então o sync cede o lead ao agente e carimba
  `welcome_status='skipped'` com o texto *"agente de pré-qualificação assumiu a abertura
  (enfileirado)"* (`exact_spotter.py:266`). O carimbo é a trava de idempotência do passo 3
  (`:212-214`), então esse lead nunca volta a ser candidato — e **o texto do carimbo mente
  durante a pausa**: o agente não assumiu ninguém.

Ou seja: religar (§6) religa o agente para leads **novos a partir da reversão**. Quem chegou
durante a pausa fica com o time, na mão, como a Isa pediu.

## 4. Lead `encerrado` que responde — o que acontece hoje

1. `qualificacao_fluxo.processar_texto` (`:1272-1274`): estado fora de
   `ETAPAS_QUALIFICACAO_ATIVAS` → devolve `False` ("não sou o dono").
2. Webhook (`main.py:646-651`): cai no fluxo velho `nat_flow.processar_texto`, que só age se
   houver `nat_flow_state` para o contato (`nat_flow.py:819-821`). Nenhum dos 25 tem, e
   `nat_enabled=false` de qualquer forma.
3. Motor legado por `ai_active`: comentado (`main.py:737`). Não responde.
4. Notificação "nova mensagem" (`main.py:657-675`): só se `contacts.assigned_to` estiver
   preenchido, nas duas grafias. **10 dos 25 não têm.**

Resultado: nada automático sai; a mensagem fica em Conversas. Sem dono, fica sem sino.

## 5. `disparo_skip` desde 24/08

A tabela só existe desde 02/09 — pulos anteriores não foram registrados (não mensurável).
Tudo `origem_envio = campanha`.

| regra | pulos | leads distintos | dias |
|---|---|---|---|
| teto | 44 | 44 | 02/09 (43), 14/09 (1) |
| **nat_ativa** | **35** | **27** | 02/09 (16), 14/09 (9), 16/09 (10) |
| recusa | 6 | 6 | 02/09 (5), 16/09 (1) |

Os 10 de 16/09 por `nat_ativa` são exatamente os "10 pulados" do disparo de 16 leads em
Follow 2 que a Isa relatou. A partir de agora `nat_ativa` não pula ninguém: a regra olha
`etapa ∈ ETAPAS_QUALIFICACAO_ATIVAS` (`exact_routes.py:443-447`), e a contagem é 0.

## 6. Reversão (SQL exato)

Ordem inversa da execução. Rodar só depois de o RECON fechar e com decisão de religar.

```sql
-- 3) estados: de volta à etapa em que pararam. A etapa original NÃO foi guardada em coluna
--    (não existe histórico de etapa — ver memória "nao-ha-historico-de-etapa-do-agente").
--    Este relatório é o registro: §2a/2b têm a etapa de cada um dos 25.
--    Reabrir em massa NÃO é recomendado — dias depois, o agente retomaria "escolhendo
--    horário" com quem já foi trabalhado na mão. Se for reabrir, é lead a lead:
UPDATE nat_qualificacao_state
SET etapa = '<etapa da tabela §2>', encerrado_em = NULL, encerrado_motivo = NULL
WHERE contact_wa_id = '<wa_id>' AND encerrado_motivo = 'pausa_operacional_20260917';

-- 2) ações canceladas: só faz sentido junto com o estado correspondente reaberto.
UPDATE nat_scheduled_actions
SET status = 'pendente', processed_at = NULL, motivo = NULL
WHERE motivo = 'pausa_operacional_20260917' AND contact_wa_id = '<wa_id>';

-- 1) o corte de data — é ISTO que religa o agente para leads novos:
UPDATE nat_config SET qualificacao_start_at = '2026-08-24 23:16:29.709119' WHERE id = 1;
-- (ou 'agora' em UTC, se a decisão for "só quem chegar depois de religar":
--  UPDATE nat_config SET qualificacao_start_at = now() AT TIME ZONE 'UTC' WHERE id = 1;)
```

Conferência pós-reversão: `SELECT qualificacao_enabled, qualificacao_start_at FROM nat_config
WHERE id = 1;` deve mostrar `t | 2026-08-24 ...`.

## 7. Pendências que esta sessão NÃO resolveu

- **Código mínimo da opção 3** (amanhã): `lembrete_reuniao` e a confirmação de booking pela
  página (`qualificacao_fluxo.py:1675, 1786`) dependerem de algo que não seja o kill switch
  do agente. Enquanto isso, **não desligar `qualificacao_enabled`** — é o que calaria os
  lembretes.
- O carimbo `welcome_status` do sync mente durante a pausa (§3). Se a pausa durar, considerar
  fazer `_agente_assume_a_abertura` olhar também o corte.
- Trava `nat_ativa` ignora o toggle "IA Desligada" do contato (caso Roberto Augusto) — objeto
  do `RECON_NAT_FOLLOWUPS_20260917.md`.
