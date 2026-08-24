# SPRINT — Agente de pré-qualificação (núcleo) — 24/08/2026

Blocos A–G entregues. **Nada ligado**: `nat_enabled=false`, `qualificacao_enabled=false`,
`qualificacao_start_at=NULL`. Nenhum WhatsApp saiu, nenhuma chamada real ao LLM, nenhum
estado gravado.

---

## 1. Mapa arquivo → função

### Nasceu

| Arquivo | O que faz |
|---|---|
| `backend/migrate_qualificacao.py` | Cria `nat_qualificacao_state` (9 etapas no CHECK) e acrescenta `qualificacao_enabled` / `qualificacao_start_at` a `nat_config`. Idempotente, transação única, `lock_timeout=3s`. **Rodada.** |
| `app/qualificacao_guard.py` | `qualificacao_pode_iniciar` (admissão, corte por data) · `qualificacao_pode_atuar` (envio, é o `guard=`) · `guard_de_abertura` (abertura e lembrete) · `contar_envios_ultima_hora` |
| `app/qualificacao_gatilho.py` | `agendar_abertura` (+5 min) · `wa_id_de`. Módulo magro: não carrega a cadeia de envio |
| `app/qualificacao_dados.py` | `resolver_dados` · `dados_da_lp` · `dados_do_exact` · `parse_description` |
| `app/qualificacao_llm.py` | `conversar` · `_validar` (contrato) · `montar_contexto` · `PROMPT_BASE` |
| `app/qualificacao_fluxo.py` | `iniciar_qualificacao` (handler) · `processar_texto` · `agente_e_dono` · `_avancar` · `_ofertar_agenda` · `_agendar` · `_concluir` · `_fallback` · `agendar_lembrete` · `lembrete_reuniao` (handler) |
| `backend/test_qualificacao.py` | 91 asserts, 8 seções |

### Mudou

| Arquivo | Mudança |
|---|---|
| `app/models.py` | 9 etapas + `ETAPAS_QUALIFICACAO_ATIVAS` + 2 origens + 2 kinds + `NatQualificacaoState` + 2 colunas em `NatConfig` |
| `app/nat_sender.py` | `guard` / `corpo_livre` / `parametros` keyword-only, todos `None` por padrão |
| `app/nat_scheduler.py` | `app.qualificacao_fluxo` em `MODULOS_DE_HANDLERS` |
| `app/nat_routes.py` | `GET`/`PATCH /api/nat/config` com os eixos do agente |
| `app/main.py` | Precedência no webhook |
| `app/exact_spotter.py` | Passo 4.5: um dono por abertura |
| `app/agendamento/agendar.py` | `_gatilho_do_agente` nos dois caminhos |
| `backend/test_welcome_guardrail.py` | Stub de `nat_config` (a consulta nova deslocava a fila posicional) |

---

## 2. As decisões que o código tomou

**A abertura é escolhida por código, não pelo modelo.** `iniciar_qualificacao` relê o estado
+5 min depois e decide T1/T2/T3 com dois `if`. O LLM nunca vê essa bifurcação.

**Ação impossível não é ignorada — transfere.** `acao="agendar_slot"` chegando em
`aguardando_motivacao` vira `transferido_humano`. Ignorar seria seguir conversando depois de
a pessoa ter ouvido uma promessa que não vai ser cumprida.

**O fallback muda a etapa ANTES de enviar.** `transferido_humano` está fora de
`ETAPAS_QUALIFICACAO_ATIVAS`, então a partir dali o agente nem escuta nem fala — é isso que
impede o laço "falhou → tenta de novo → falhou".

**Uma constante governa os dois lados.** `ETAPAS_QUALIFICACAO_ATIVAS` decide se o agente
escuta (precedência do webhook) e se pode falar (`qualificacao_pode_atuar`). Um lugar, então
os dois não podem divergir.

**O slot é validado duas vezes.** Contra o que foi de fato oferecido nesta rodada (o modelo
não inventa id) e contra `slots_livres(usar_cache=False)` — entre oferecer e escolher passam
minutos e o cache é de 60s. Corrida reoferta a grade; não é falha.

**O carimbo da boas-vindas é reaproveitado.** Com o agente ligado, o passo 4.5 de
`send_welcome_to_new_lead` carimba `welcome_status='skipped'` com motivo. É a mesma trava
permanente de idempotência, então um lead que o agente assumiu **nunca** volta a ser
candidato à boas-vindas — nem se o agente for desligado depois.

**O gatilho enfileira sempre, ligado ou não.** Quem decide é a admissão, no handler, 5 min
depois. É o que torna a ativação instantânea: ligar a chave vale para quem já está na fila,
sem backfill.

---

## 3. Divergências entre o prompt do sprint e o código

| O sprint disse | O código impôs |
|---|---|
| 8 etapas | **9.** Faltava `aguardando_formacao`: o T3 pergunta *qual é* a formação, então a primeira resposta nesse ramo é a formação, não o ano |
| "reusar `nat_sender.send_nat_message`, que já decide" | Ele decide a janela, mas estava **soldado ao `nat_pode_atuar`** — reusá-lo faria ligar o agente exigir ligar o fluxo de botões, e barraria os 21 de 80 leads da LP que já migraram de funil. Guard virou injetável (checkpoint 3, aprovado) |
| Trava de data por `register_date` | Para a LP, **não dá**: aos 5 min o lead pode não existir em `exact_leads` (sync de 600s; medido, welcome em mediana 4min24s e máximo 11min19s). Origem `lp` usa `agendamentos.created_at` |
| Bloco C — "avaliar e propor" | On-demand, aprovado no checkpoint 2. +6 chamadas/dia sobre 2 736 (**+0,2%**) contra reescrever uma coluna de até 8 000 chars em 9 133 linhas a cada 10 min |

---

## 4. Testes

`test_qualificacao.py` — **91 asserts**, tudo mockado:

| Seção | Cobre |
|---|---|
| 1 | Parser: nosso formato, texto de SDR colado, formato do RD ignorado, vazio, snake_case, "Outra profissão" → ausência |
| 2 | Contrato do LLM: válido, cercado em markdown, e **8 formas de sair do contrato** → `None` |
| 3 | Máquina: transição válida, não-cumprida não anda, 4 caminhos de fallback, bifurcação 4a/4b |
| 4 | Agendamento: slot inventado → sem escrita; slot tomado → reoferta; sempre com `lead_id` |
| 5 | Precedência: ativo/terminal/ausente |
| 6 | Idempotência: mesma `wa_message_id` não chama o LLM nem envia |
| 7 | Gatilho e lembrete: 30 min exatos, reunião no passado/sumida/morta → silêncio |
| 8 | Guard: 7 bloqueios, exceção → fechado, e que **não olha `nat_enabled`** |

Suíte completa verde: 15 arquivos.

> `test_agendamento_e2e_funil.py` **não foi rodado**: ele se recusa sem `--sim-eu-quero`
> porque escreve na Exact de produção e deixa box órfão permanente.

---

## 5. Checklist de ativação

Ordem importa. Nada disto foi feito.

### Antes

1. ✅ **Templates `APPROVED`** — conferido em 24/08 por `hsm_id` + `language`. Os 4
   aprovados, `pt_BR`, corpo idêntico ao submetido:

   | Template | `hsm_id` | Categoria FINAL |
   |---|---|---|
   | `nat_abertura_agendado` | `2913902048954833` | **MARKETING** (a Meta recategorizou; pedimos UTILITY) |
   | `nat_abertura_qualificacao` | `1068302605748380` | MARKETING |
   | `nat_abertura_sem_formacao` | `1036680979112055` | MARKETING |
   | `nat_lembrete_reuniao` | `4036914996610587` | UTILITY |

   3 dos 4 são MARKETING — contam no limite por usuário e são pausáveis por qualidade.

2. **`OPENAI_API_KEY` no `.env`** — já está. O cliente é preguiçoso: chave ausente não
   derruba o boot, só o fluxo.

3. ✅ **Teste manual do LLM** — feito em 24/08, `TESTE_LLM_20260824.md`. 15 cenários,
   4 rodadas, 59/60 passagens, contrato 60/60. Achou 6 defeitos, um deles de arquitetura
   (as missões não carregavam a próxima pergunta do roteiro).
   ⚠️ **As correções de `PROMPT_BASE`/`MISSOES` exigem um novo restart para valer.**

4. ✅ **Cursos** — os 13 subSources da LP têm alias desde 24/08. Nenhum sai mais com
   código de turma ou sem acento.

5. **`restart` do serviço** — o processo em execução (PID 1500356, de 18/08) não conhece
   nenhum módulo novo. Sem restart, nada disto existe em produção.

### O desligamento coordenado

6. **`auto_welcome_config.enabled` → `false`, COM a Valéria.** Ela religou em 28/07; tem
   dono. Enquanto o agente estiver ligado, o passo 4.5 já cede a abertura e carimba — mas
   deixar a automação ligada mantém um segundo caminho vivo para o dia em que o agente for
   desligado.

### Ligar

7. `PATCH /api/nat/config` com **os dois campos juntos** — ligar sem corte é 422 de
   propósito:
   ```json
   {"qualificacao_enabled": true, "qualificacao_start_at": "agora"}
   ```
   `nat_enabled` **continua `false`**. São eixos independentes.

8. **Conferir `max_envios_hora`** (hoje 20). É compartilhado entre os dois fluxos como
   valor, mas cada um conta os SEUS envios por `nat_etapa`.

### Depois

9. Primeira hora: `nat_qualificacao_state`, `nat_scheduled_actions` (kind
   `iniciar_qualificacao`), e `transferido_motivo` — que é onde um LLM instável apareceria.

---

## 6. Fora de escopo, registrado

- **Follow-up de silêncio** — decisão pendente. Nenhuma cadência automática fala com o lead
  hoje; a base do 18535 tem 3 680 leads, 3 579 descartados.
- **Remarcação pelo agente** — não existe `ScheduleRemove`, cada remarcação queima um slot.
  Pedido de remarcar vira `transferido_humano`.
- **Régua R$100/200/300** — `faixa_investimento` é coletada e **nunca lida** pelo fluxo.
- **`ai_configs` / `main.py:537-618`** — não tocados. Continuam desligados; ligar aquele
  bloco armaria a IA antiga para 637 contatos.
- **`exact_routes.bulk_send_template`** — `.split()[0]` sem capitalizar. Mesma classe de
  defeito do primeiro nome, mas é tela de disparo humano.
