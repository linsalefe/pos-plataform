# SPRINT Bloco 1: régua de confirmação de reunião (Fluxo A), 07/10/2026

Branch `feat/confirmacao-reuniao` (a partir de `feat/templates-fluxo-a`, que ainda não estava na
`main`). Base: `RECON_CONFIRMACAO_NOSHOW_20261007_REPORT.md`, Bloco 0 (`reuniao_status`), os 7
templates do Fluxo A e a spec da Isa (`Otimização IA - No show (validar).pdf`, págs. 4 a 8).

**Estado em produção (07/10 07:20 SP):** `CONFIRMACAO_ENABLED=true` com
`CONFIRMACAO_SOMENTE_TELEFONES=83988046720`. Só o número do Álefe entra na régua; todo o resto
segue exatamente como antes. Abrir para todos depende de aprovação explícita.

## 1. Templates na Meta (critério 9)

Os 7 `APPROVED` em 07/10 (`GET /{waba}/message_templates`):

| template | status | categoria |
|---|---|---|
| `nat_a_confirmacao` | APPROVED | **MARKETING** (pedido UTILITY: a Meta reclassificou depois de aprovar) |
| `nat_a_ementa` | APPROVED | MARKETING |
| `nat_a_beneficio` | APPROVED | MARKETING |
| `nat_a_pedido_confirmacao` | APPROVED | UTILITY |
| `nat_a_ultimo_aviso` | APPROVED | UTILITY |
| `nat_a_30min` | APPROVED | UTILITY |
| `nat_ns_d0_corte` | APPROVED | MARKETING |

A confirmação imediata como MARKETING custa mais e entra no limite de frequência da Meta
(`131049`), que não pula o disparo (memória `opt-out-da-meta-131050`).

## 2. Critérios de aceite

| # | critério | estado | evidência |
|---|---|---|---|
| 1 | flag desligada = nada muda | ✅ | deploy desligado às 07:17 SP; ciclo do sync `reguas_armadas=0`; `inbound` devolve False sem tocar no banco; `lembrete_por_espelho` devolve False e o T-30 segue o caminho antigo |
| 2 | agendamento de teste do Álefe recebe a imediata em < 1 min, ações seguintes `pendente` | ⏳ | **aguardando o Álefe agendar pela LP** (seção 4) |
| 3 | "Confirmo"/texto da lista: `confirmado_em`, cancela pedido/último/corte, nota, T-30 `nat_a_30min` | ✅ código / ⏳ ponta a ponta | `confirmacao.confirmar` |
| 4 | outro inbound pausa (menos o corte), notifica o dono, nota `[NAT] Aguardando humano` | ✅ código | `confirmacao.pausar` |
| 5 | Cancelada na Exact ou envio manual do SDR cancela a régua (corte incluído no SDR) | ✅ código | `reuniao_sync._encerrar_regua`; `routes._silenciar_agente_apos_envio_manual` → `cancelar_regua_da_pessoa` |
| 6 | silêncio 20h30–8h, menos a imediata; adiar além do corte/início = skipped com motivo | ✅ | `nat_guard.dentro_janela_envio`/`proxima_janela_envio`; `confirmacao._espinha` |
| 7 | todo "não enviou" grava motivo | ✅ | `AcaoIgnorada`/`AcaoAdiada` em todos os handlers; o corte que não manda o D0 devolve a ressalva e o scheduler grava como motivo do `executado` |
| 8 | testes escritos, não executados; `import app.main` passa | ✅ | `backend/test_confirmacao.py` (só `py_compile`); import ok |
| 9 | flag só ligada com os 7 APPROVED | ✅ | seção 1 |

## 3. Calendário (função real `calcular_regua`, "sai" = depois da janela 8h–20h30)

| caso (corte) | imediata | ementa | benefício | pedido | último aviso | corte |
|---|---|---|---|---|---|---|
| ter 15h → qui 10h (qui 9h) | ter 15:00 | ter 19:00 | 23:00 → qua 08:00 | qua 17:00 | qui 08:00 | qui 09:00 |
| qua 19h → qui 10h (qui 9h) | qua 19:00 | não (colisão) | não (colisão) | não (17h passou) | qui 08:00 | qui 09:00 |
| qui 11h → qui 14h | qui 11:00 | não | não | não | não | não (< 4h) |
| sex 16h → seg 10h (seg 9h) | sex 16:00 | sex 20:00 | 00:00 → sáb 08:00 | **dom 17:00** | seg 08:00 | seg 09:00 |
| ter 15h → qua 16h30 (qua 12h30) | ter 15:00 | ter 19:00 | não (colisão) | qua 08:00 | qua 11:30 | qua 12:30 |

T-30 só depois de confirmar. **Regra de colisão** (aprovada no checkpoint): ementa e benefício
que, depois da janela, sairiam junto ou depois da primeira mensagem de confirmação não são
criados. Sem ela, o 2º caso mandaria ementa, benefício e último aviso às 08:00.

## 4. Teste ponta a ponta do Álefe

**Pendente.** Roteiro, com a flag no estado atual:

1. Agendar pela LP com o 83988046720.
2. Em até ~1 min: confirmação imediata com "Confirmo" e "Preciso remarcar". Conferir:
   ```sql
   SELECT kind, status, run_at, left(motivo,60) FROM nat_scheduled_actions
    WHERE contact_wa_id LIKE '%88046720' AND created_at > now() - interval '1 hour' ORDER BY run_at;
   SELECT meeting_id, confirmado_em, confirmado_por, cancelado_motivo, regua_encerrada_motivo
     FROM reuniao_status WHERE telefone_chave = '8388046720' ORDER BY registrado_em DESC LIMIT 3;
   ```
3. Repetir com: "Confirmo" (botão), "ok" (texto), "Preciso remarcar", "Não vou conseguir",
   uma pergunta ("é por vídeo?", deve responder e pedir confirmação de novo), e um texto livre
   qualquer (deve pausar e notificar). A nota `[NAT]` de cada evento aparece em
   `GET /ListTimeline(<leadId>)`.

Se o `meeting_id` não vier na hora (é best-effort), a régua nasce no próximo ciclo do sync
(até 10 min) em vez de < 1 min.

## 5. Primeiras 24h com a allowlist aberta

Não medido: a allowlist continua só com o Álefe. Consulta pronta:

```sql
SELECT kind, status, left(motivo,60), count(*) FROM nat_scheduled_actions
 WHERE (kind LIKE 'confirm\_a\_%' OR kind = 'lembrete_reuniao')
   AND created_at > now() - interval '1 day' GROUP BY 1,2,3 ORDER BY 1,2;
```

## 6. Arquivos

| arquivo | o quê |
|---|---|
| `app/confirmacao.py` (novo) | gates, `calcular_regua`, `armar`, `cancelar_regua`(+`_da_reuniao`/`_da_pessoa`), `guard_de_regua`, 6 handlers, `lembrete_por_espelho`, `armar_t30`, `inbound` (botões, lista fechada, recusa, dúvida simples, pausa), `confirmar`/`remarcar`/`cancelado_pelo_lead`/`ligar_agora`/`sem_interesse`/`pausar` |
| `app/models.py` | `KIND_CONFIRM_A_*`, `KINDS_CONFIRMACAO`, `TIPO_NOTIF_CONFIRMACAO`, `TIPO_NOTIF_LIGAR_AGORA` |
| `app/nat_guard.py` | `JANELA_REGUA_*`, `dentro_janela_envio`, `proxima_janela_envio` (`dentro_horario_comercial` intocado) |
| `app/nat_scheduler.py` | `cancelar(..., motivo=)`; handler pode devolver string = `executado` com motivo; `app.confirmacao` em `MODULOS_DE_HANDLERS` |
| `app/whatsapp.py`, `app/nat_sender.py` | `url_suffixes` (botão URL dinâmico do `nat_a_ementa`) |
| `app/nat_copy.py` | `BOTOES_LIVRES` da régua e da dúvida, respostas fixas, ementa em texto livre |
| `app/qualificacao_guard.py` | etapas da régua no teto por hora (`ETAPAS_REGUA_CONFIRMACAO`) |
| `app/qualificacao_llm.py` | `classificar_duvida` (contrato fechado, uma tentativa, fail-closed) |
| `app/qualificacao_fluxo.py` | `lembrete_reuniao` tenta `lembrete_por_espelho` antes do caminho antigo |
| `app/reuniao_sync.py` | encerra a régua quando a reunião sai de Vigente; arma as Vigentes sem régua; `espelhar_agendamento` |
| `app/agendamento/agendar.py` | `_gatilho_do_agente` espelha e arma na hora |
| `app/agendamento/consultoras.py` | campos opcionais `telefone` e `user_id_hub` |
| `app/main.py` | webhook: régua antes do agente |
| `app/routes.py` | envio manual de humano logado encerra a régua da pessoa |
| `backend/ementas.json` (novo) | 14 cursos → sufixo do Drive |
| `backend/test_confirmacao.py` (novo) | testes, não executados |
| `backend/.env` (fora do git) | `CONFIRMACAO_ENABLED=true`, `CONFIRMACAO_SOMENTE_TELEFONES=83988046720` |

## 7. Desvios do plano, com evidência

1. **Branch a partir de `feat/templates-fluxo-a`**, que não estava na `main` (sem ela, o
   `nat_copy` não tem os corpos e payloads).
2. **Só reunião de consultora da pós** (`consultoras.json`). RECON §5.3: há reuniões com `sdr@`
   como rep e 2 da Marina (intercâmbio). "Com a consultora sdr" ou uma confirmação de pós para
   quem marcou intercâmbio é pior que não mandar.
3. **Cancelamento escopado pela reunião**, não por contato (`_cancelar_da_reuniao`). Remarcar é
   reunião nova e a antiga vira Cancelada (RECON §5.4): por contato, o sync derrubaria a régua da
   reunião nova ao ver a antiga cancelar. O SDR que assume continua cancelando tudo da pessoa.
4. **SDR que assume = humano logado.** `bulk_send_template` chamado pelo job do follow por
   estágio passa pela mesma função sem `User`; um follow automático não é "o SDR assumiu".
5. **Handler pode devolver string** (vira `executado` com motivo). Necessário para o corte: a
   marcação e o aviso à consultora não podem ser revertidos quando só o D0 falha, e AcaoIgnorada
   reverte o savepoint.
6. **`url_suffixes` no envio de template.** O `send_template_message` só sabia fixar payload de
   quick reply; o `nat_a_ementa` precisa do sufixo do Drive. Com a janela aberta a ementa vai em
   texto livre com o link no corpo.
7. **Regra de colisão** de ementa/benefício com o pedido (aprovada no checkpoint, seção 3).
8. **Corte encerra a régua** (`regua_encerrada_motivo='corte'`) e a pausa por humano grava
   `'humano'`; o corte e o T-30 só ignoram o encerramento quando ele é `'humano'` (spec: "o corte
   continua valendo").
9. **Clique do D0 depois do corte:** só os dois botões são da régua; texto livre segue o caminho
   de sempre (dono notificado pelo webhook). A régua D0+1h em diante é o Bloco 2.
10. **Dúvida simples:** uma tentativa de LLM (não duas), resposta sem "?" e até 300 caracteres,
    uma por reunião (contada em `messages.nat_etapa='confirm_a_duvida'` desde o registro da
    reunião). Os botões são os do pedido (`A_PED_SIM`/`A_PED_REMARCAR`).
11. **T-30 sem telefone da consultora** cai em `nat_lembrete_reuniao` (template antigo, aprovado).

## 8. Dados pendentes (do checkpoint, não respondidos)

- **Telefone de cada consultora** (`consultoras.json`, campo `telefone`). Sem ele, o T-30 sai com
  o template antigo, que não diz o número.
- **Usuário do Hub de cada consultora** (`user_id_hub`). Os e-mails do Hub não batem com os da
  Exact; hipótese não confirmada: Amorim = id 3 "Vi Amorim", Rodrigues = id 6 "Victória". Sem ele,
  os avisos de corte/remarcação vão ao dono do contato e, sem dono, à Isa (`GESTOR_USER_ID`).
- **Ementas de DH T4 e Psicologia Clínica Aplicada:** `f3_guiadht4` e `f3_guiapsiaplicada` existem
  na Meta mas não estão no `follow_estagios.json`; ficaram fora do `ementas.json` (curso sem
  ementa → `AcaoIgnorada("sem ementa cadastrada")`).
- Restart necessário depois de preencher `consultoras.json` (é carregado uma vez).

## 9. Para o Bloco 2

- Régua de no-show D0+1h a D8 (templates `nat_ns_*` a submeter), disparada pelo corte
  (`cancelado_motivo='sem_confirmacao'`) e pelos cliques do D0.
- Trava "uma régua por pessoa" com o follow por estágio e teto de mensagens por pessoa.
- "Preciso remarcar"/"Escolher horário" mostrando hoje+amanhã (Bloco 3).
