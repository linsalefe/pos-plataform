# SPRINT_NAT_CORRECOES_20260918_REPORT — defeitos do agente de qualificação

**Merge `7add746` em `main`, backend reiniciado em 17/09 20:03 UTC (17:03 SP).** Branch
`nat-correcoes-20260918`, 7 commits. 10 arquivos, +712/−36. Nenhuma mensagem enviada a
lead, nenhum UPDATE de dados, `nat_config` intocado (`qualificacao_enabled=t`,
`qualificacao_start_at=2099-01-01` — o agente continua pausado).

## 1. Diff por critério

| # | critério | arquivo:linha | o que mudou |
|---|---|---|---|
| 1 | follow_20h com inbound | `qualificacao_fluxo.py:2300-2302` | `ultimo >= agora - FOLLOW_APOS` — `_ultimo_inbound` já devolve o `datetime`; `.timestamp` era o método. Comentário registra a medição (60 falhou / 61 executado) |
| 2 | `falhou` grava motivo | `nat_scheduler.py:306-316` (`_finalizar`), `:403-405`, `:439-440` | `ValueError` se `status == falhou` sem motivo; as duas chamadas passam `motivo=` (`f"{type(e).__name__}: {e}"[:500]`, ou "kind sem handler") |
| 3 | reunião por telefone | `telefone.py:131-152` (`formas_gravadas`, novo) · `qualificacao_fluxo.py:563-621` (`reuniao_de`, novo; `_reuniao` vira wrapper) | ordem: `agendamento_id` → `agendamentos.telefone IN (4 grafias)` → `lead_id`. Docstring cita Luciana e Elisangela |
| 4 | guarda em `_agendar` | `qualificacao_fluxo.py:1466-1478` | depois de validar o slot livre, relê `_reuniao`; se existe, `agendamento_id` aponta para ela e `_concluir(confirmar=True)`; `fluxo.agendar` **não** é chamado |
| 5 | sem abertura < 2h | `qualificacao_guard.py:290-315` (`MIN_HORAS_ATE_REUNIAO_PARA_ABERTURA=2`, `MOTIVO_REUNIAO_PERTO`, `reuniao_perto_demais`) · `qualificacao_fluxo.py:1204-1211` | `reuniao_de(telefone=wa_id, lead_id, None)` **antes** de `_contato_ou_criar` → `AcaoIgnorada('reuniao_em_menos_de_2h')`. Reunião que já começou não conta |
| 6 | lembrete independente | `qualificacao_guard.py:318-378` (`guard_de_lembrete(reuniao_id)`, fábrica) · `qualificacao_fluxo.py:1860-1862` | três condições relidas no envio: `agendado`, `slot_inicio` futuro, nenhum `nat_lembrete_reuniao` ao contato nas últimas 24h. **Não lê `nat_config`, sem teto por hora** |
| 6b | lembrete cria o contato | `qualificacao_fluxo.py:1837-1849` | `_contato_ou_criar(wa_id, lead_id=reuniao.lead_id)` — mesmo caminho da abertura (`:495`, `ai_active=False`); contato na outra grafia → envio segue nela (S5-2); sem canal → `skipped` com motivo |
| 7 | recusa de ligação | `nat_copy.py:206-224` (`TEXTO_RECUSA_LIGACAO`) · `qualificacao_llm.py:90-97` (`MOTIVOS_TRANSFERENCIA_VALIDOS`), `:172-173`, `:184`, `:224-237` (`_validar` aceita `motivo`) · `qualificacao_fluxo.py:284-288`, `:305-309` (missões) · `:1338-1346` (ramo) · `_fallback` ganha `texto=` e `aviso_sdr=` | LLM devolve `acao=transferir_humano, motivo=recusa_ligacao, mensagem="ok"`; o código grava `transferido_motivo='recusa_ligacao'`, manda o texto fixo (sem vídeo, sem pergunta) e notifica o SDR com "ele quer mensagem". `motivo` fora do enum ou sem transferência → None com log |
| 8 | rótulo | `models.py:748-764` (`ETAPAS_QUALIFICACAO_LEGIVEIS`) · `nat_routes.py:106-120` (`qualificacao_etapa_legivel`) · `conversations/page.tsx:105-108, 1596-1606` | "Agente: perguntando a motivação"; sem estado, sem rótulo. Toggle e `ai_active` intactos |
| 9 | testes | `backend/test_nat_correcoes_20260918.py` | 8 grupos (1–7 + 6b), 40 asserções. **Não executados** |

## 2. Critério 3 — Luciana e Elisangela casam pela nova chave (só leitura)

Com as 4 grafias que `formas_gravadas` gera para o `contact_wa_id` do estado:

| estado | wa_id | lead do estado | reunião | lead da reunião | `agendamentos.telefone` | pela chave antiga (`lead_id`) |
|---|---|---|---|---|---|---|
| 310 Luciana Zola | 553194386668 | 51861285 | **517** (15/09 09:45) | 51861228 | `31994386668` | nada |
| 301 Elisangela | 5541996390611 | 51846975 | **498** (14/09 10:30) | 51846973 | `41996390611` | nada |

## 3. Critério 6 — lembretes de amanhã elegíveis; Vera Lima registrada como perdida

Depois do restart (17/09 17:05 SP):

| ação | quem | status | run_at | reunião | `agendado` | futura | contato | lembretes 24h |
|---|---|---|---|---|---|---|---|---|
| 2509 | Vera Lima | **skipped** — `lembrete não saiu: contato não existe no banco` (16:45, antes do deploy) | 17/09 16:45 | 528 (17:15) | sim | — | existe só como `555199333063` (12 dígitos) | 0 |
| 2512 | Bruna Giovana Modesto | pendente | 18/09 10:00 | 543 (10:30) | sim | sim | sim | 0 |
| 2628 | Natalia Cardoso | pendente | 18/09 11:30 | 568 (12:00) | sim | sim | sim | 0 |
| 2625 | Jane Senna | pendente | 18/09 14:30 | 566 (15:00) | sim | sim | sim | 0 |
| 2480 | Regina Coeli C. T. Bayer | pendente | 18/09 16:00 | 540 (16:30) | sim | sim | sim | 0 |
| 2451 | Juraciara | pendente | 18/09 16:45 | 535 (17:15) | sim | sim | sim (2 grafias) | 0 |

Os 5 passam nas três condições do `guard_de_lembrete`. A Vera Lima ficou registrada na
ação 2509 como `skipped` com motivo legível; a reunião (17:15) já passou e o lembrete não
é recuperável. O caso dela era o S5-2 do lembrete: o contato **existia**, na grafia de 12
dígitos, e `enviar_nat` compara por igualdade crua com os 13 da ação. A partir de agora
`_contato_ou_criar` resolve nas duas grafias e o envio segue na que existe.

## 4. Saída das ferramentas

```
py_compile  app/qualificacao_fluxo.py app/nat_scheduler.py app/telefone.py
            app/qualificacao_guard.py app/nat_copy.py app/qualificacao_llm.py
            app/models.py app/nat_routes.py test_nat_correcoes_20260918.py   → OK (todas)
tsc --noEmit                                                                → exit 0
npm run build                                                               → exit 0
systemctl is-active cenat-backend (após restart)                            → active
journalctl: "Application startup complete", agendador NAT ativo, sem traceback
```

## 5. CONTRADIZ o prompt

- **Critério 6, "não enviado":** `messages` não guarda `agendamento_id`; a condição virou
  "nenhum `nat_lembrete_reuniao` a este contato nas últimas 24h". Duas reuniões reais da
  mesma pessoa em 24h receberiam um lembrete só (lado seguro; docstring do guard).
- **Critério 8:** a etapa já chegava à tela por `GET /nat/{wa_id}/estado`
  (`qualificacao_etapa`), não por `routes.py:432-585`. `routes.py` não foi tocado; o nome
  legível entrou no endpoint que a tela já chama, com o mapa em `models.py` (uma fonte).
- **Critério 5:** reunião que **já começou** não bloqueia a abertura — o critério diz
  "nas próximas 2 h"; o outro caso está anotado na docstring como de outra regra.
- **Decisão 6:** `ValueError`, não `assert` (assert some com `-O`).

## 6. Observações pra depois (não feitas)

- Boot avisa: `consultora processoseletivo@cenatcursos.com.br inativa na Exact — FORA DE
  ROTAÇÃO`; só a Victória (`comercial@`) em rotação. Pré-existente, fora da sprint — mas 5
  das 6 reuniões de amanhã foram marcadas com `processoseletivo@`.
- Debounce de inbound (defeito 5 do recon); decisões da Isa (régua de follow humano,
  override de `nat_ativa`, destino do toggle); duplicata pela própria página (Janice).
- Religar o agente: `qualificacao_start_at` de volta (PAUSA §6). Os 25 estados
  `pausa_operacional_20260917` não reabrem.
- Os testes desta sprint estão escritos e compilam; rodar `venv/bin/python
  test_nat_correcoes_20260918.py` antes de religar.
