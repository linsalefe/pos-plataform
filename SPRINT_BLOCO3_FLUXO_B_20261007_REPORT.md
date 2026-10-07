# SPRINT Bloco 3 — Fluxo B enxuto e reagendamento pelos botões (07/10/2026)

Branch `feat/fluxo-b-enxuto`, mergeada em `main` em 07/10. Status: **LIGADO só para
`83988046720`** desde 07/10 12:15:42 UTC (`FLUXO_B_ENXUTO=true`, boot `✅ Fluxo B enxuto ...:
LIGADO (só 1 telefone(s) de teste)`). O teste ponta a ponta do Álefe ainda não foi feito.

## 0. Resumo

| Critério | Status | Evidência |
|---|---|---|
| 1. flag desligada = agente de 4 perguntas igual, remarcar com resposta fixa | ✅ | §3 (diff do caminho antigo); rodou desligado das 12:10 às 12:15 UTC sem erro |
| 2. abertura `nat_b_abertura` → venda + até 5 horários → reunião + confirmação imediata | ⏳ código pronto; E2E pendente | §2 (texto real da venda gerado pelo LLM com a grade real) |
| 3. reativações +30m/+2h/+4h/D+1 9h; responder cancela | ⏳ código pronto; E2E pendente | §4 |
| 4. prefere ligação → aviso ao SDR, nota `[NAT] Prefere ligação`, encerra | ⏳ código pronto | simulação do LLM: `transferir_humano` + `prefere_ligacao` |
| 5. cliques REMARCAR/HORARIO/REAGENDAR → `ofertando_agenda` + horários | ⏳ código pronto; E2E pendente | §5 |
| 6. hoje+amanhã; senão 2 próximos dias úteis; senão `_fallback` | ✅ código | `dias_da_oferta`, §4 |
| 7. janela 8h–20h30 nas reativações; abertura em dia útil | ✅ código | `calendario_reativacao`, `_reativar` |
| 8. `test_fluxo_b.py` escrito, não executado; `import app.main` passa | ✅ | só `py_compile` foi rodado |

## 1. Templates (Fase 1)

Submetidos em 07/10 com `submit_templates_fluxo_b.py --apply`. Os 5 foram **APPROVED** no mesmo
dia, todos MARKETING, sem botões. Conferido na Meta antes de ligar: o corpo aprovado de cada um é
igual ao de `nat_copy.CORPO_SUBMETIDO_FLUXO_B`. A cópia local em `whatsapp_templates` ainda diz
PENDING; o envio não lê essa coluna.

| nome | id Meta | vars | corpo |
|---|---|---|---|
| `nat_b_abertura` | 2306134753469752 | nome, pós | Oi, {{1}}! Que bom ver você por aqui 😊 Vi que você aplicou para a Pós em {{2}}. Me conta, o que despertou seu interesse por essa pós? |
| `nat_b_reativ_30m` | 1428398522572407 | nome | Oi, {{1}}, está por aí? 👀 |
| `nat_b_reativ_2h` | 1640355274434841 | nome | Oi, {{1}}! Consegue me responder rapidinho? Assim já sigo com seu processo seletivo 😊 |
| `nat_b_reativ_4h` | 1644044833987865 | nome | Oi, {{1}}! Se preferir, já te mostro os horários disponíveis para sua conversa com a consultora! |
| `nat_b_reativ_d1` | 944914248692241 | nome, horários | Oi, {{1}}! Como não tive seu retorno e estamos com pouca disponibilidade de agenda, seguem os horários para você agendar sua conversa diretamente com a nossa consultora: {{2}}. É só me responder com o horário que fica melhor. |

Ajustes em relação ao texto da spec (pág. 3): prefixo "Oi, {{1}}!" no +2h, +4h e D+1 (a Meta não
aceita corpo começando com variável) e a frase final do D+1 (não aceita corpo terminando em
variável).

## 2. Texto real da venda (simulação com a grade de 07/10, sem envio)

Missão nova + horários livres de verdade + motivação inventada, pelo LLM de produção:

> Que legal, Ana! Você disse que atende crianças autistas na clínica e quer se preparar melhor
> para atendê-las — muito pertinente. A próxima etapa do processo seletivo é uma conversa rápida,
> de uns 15 minutos, com nossa consultora, para tirar suas dúvidas e ver se a pós faz sentido para
> o seu momento. Tenho estes horários:
> hoje (07/10) 11:30 · hoje (07/10) 14:30 · hoje (07/10) 18:15 · amanhã (08/10) 10:00 · amanhã (08/10) 13:45
> É só me responder com o horário que fica melhor.

- Clique "Preciso remarcar" (missão `ofertando_agenda` do Fluxo B): "Sem problema, Ana! Tenho estes
  horários para a sua conversa com a consultora:" + 5 horários dos dois dias.
- "prefiro que me liguem": `acao=transferir_humano`, `motivo=prefere_ligacao`, `mensagem="ok"`.
- `{{2}}` do D+1 com a mesma grade: `hoje 11h30, 18h15 ou amanhã 10h00, 18h15`.

**Desvio medido no checkpoint 2:** com 6 horários por dia no contexto (o padrão do caminho antigo)
o modelo encheu a lista com 4 de hoje e 1 de amanhã. O Fluxo B passou a pôr **3 por dia** no
contexto (`HORARIOS_POR_DIA_B`), o que garante horários dos dois dias.

Texto real do teste do Álefe: **pendente** (precisa da flag ligada).

## 3. O caminho antigo (flag desligada)

Cada linha removida do caminho antigo virou uma condição de flag ou um parâmetro opcional cujo
padrão reproduz o comportamento de antes:

| Ponto | Com a flag desligada |
|---|---|
| `reuniao_de(..., ignorar=frozenset())` | conjunto vazio, mesma consulta |
| `_fatos`: ramo antigo virou `elif` | o mesmo corpo |
| `_notificar`/`_fallback` com tipo e título por parâmetro | padrão = o de antes |
| `iniciar_qualificacao`: `caminho_b` | False: mesma etapa, mesmo template |
| `processar_texto`: `com_slots`, `_missao`, ramo `prefere_ligacao` | tudo atrás de `e_fluxo_b(estado)`; `_missao` devolve `MISSOES[etapa]` |
| `_avancar(..., ofertados=)` | ramo novo só no Fluxo B |
| `_agendar_follow` | só desvia com estado do Fluxo B |
| `_cancelar_follow`, `KINDS_DA_CONVERSA` | também cancelam `reativ_b_*` (UPDATE sem linhas no caminho antigo) |
| `encerrar_inativo` | lê `motivo` do payload; no caminho antigo é `{}` |
| `confirmacao.remarcar` | nota, aviso e resposta fixa, na mesma ordem |
| validador do LLM aceita `prefere_ligacao` | fora do Fluxo B cai na transferência genérica, como antes |
| teto por hora conta `nat_b_*` | só conta o que o Fluxo B enviar |

## 4. Reativações

Kinds `reativ_b_30m`, `reativ_b_2h`, `reativ_b_4h` e `reativ_b_d1`, armados a cada pergunta (na
abertura e em cada inbound, por `_agendar_follow`) e cancelados pelas mesmas portas do follow.

- **Janela:** as curtas só são armadas se caem dentro de 8h–20h30 e antes do D+1. Pergunta às 19h
  dá +30 min (19h30) e D+1. Empurrá-las para as 8h as empilharia com o D+1 das 9h.
- **D+1:** sempre às 9h do dia seguinte, com os horários. Depois dele, `encerrar_inativo` em 24h
  com motivo `reativacao_esgotada`. Sem horário na grade, o D+1 é pulado com motivo e fica o
  encerramento de 72h.
- **Handler relê tudo:** flag, estado ativo e do Fluxo B, allowlist, janela, inbound depois da
  pergunta, humano/campanha depois da pergunta, opt-out 131050. Toda recusa vira `AcaoIgnorada`.
- **Formato:** janela aberta sai em texto livre com o corpo de `CORPO_SUBMETIDO_FLUXO_B`; fechada
  sai como template (quem decide é `enviar_nat`).

Reativações recebidas no teste: **pendente**.

## 5. Remarcar pelos botões

Todos os cliques de remarcar dos Blocos 1 e 2 (`A_*_REMARCAR`, `NS_*_HORARIO`, `NS_*_REAGENDAR`)
passam por `confirmacao.remarcar`, e o gancho mora só ali. Com o Fluxo B ativo para o telefone,
`qualificacao_fluxo.reabrir_para_oferta`:

- cria o estado (origem `exact`) ou o renasce de qualquer etapa em `ofertando_agenda`;
- guarda a etapa, o `encerrado_motivo` e o `transferido_motivo` anteriores em
  `dados_extras["reaberturas"]`;
- põe a reunião remarcada em `dados_extras["reunioes_remarcadas"]`. É a exceção explícita à trava
  de 27/09: na Exact ela segue Vigente até a consultora cancelar, e sem isto o agente encerraria a
  conversa por "já tem reunião";
- oferece hoje e amanhã e arma as reativações.

A nota "Pediu remarcação" e o aviso à consultora e ao SDR continuam; o aviso passa a dizer que os
horários já foram. A resposta fixa só sai se a oferta nem foi tentada (sem horário, agente
desligado, erro em savepoint próprio).

Ponta a ponta (clique → horários → reunião nova na Exact → confirmação imediata): **pendente**.

## 6. Desvios e decisões tomadas na implementação

1. Abertura nova só para quem não tem reunião nenhuma; com reunião que já passou, segue o T1 antigo.
2. 3 horários por dia no contexto do Fluxo B (§2).
3. "2 próximos dias úteis" é limitado pela grade (`AGENDAMENTO_JANELA_DIAS=4`): numa sexta à noite
   é só a segunda.
4. A missão nova aceita a escolha direta de um horário ainda em `aguardando_motivacao` (resposta ao
   D+1) e trata "quer marcar logo" como etapa cumprida.
5. Linha de boot nova em `main.py`.

## 7. Riscos e pendências

- **Reunião nova com outra Vigente:** não verificado se a Exact aceita `BoxesAdd` para um lead que
  ainda tem reunião Vigente. O teste do "Preciso remarcar" responde.
- **Relatórios:** `relatorios.ABERTURAS` só conhece T1/T2/T3; a abertura do Fluxo B não entra no
  funil da página `/relatorios`.
- `test_fluxo_b.py` não foi executado (convenção da sprint).

## 8. Deploy

- 12:10 UTC: restart com `FLUXO_B_ENXUTO=false`, boot limpo.
- 12:15 UTC: restart com `FLUXO_B_ENXUTO=true` e allowlist `83988046720`, boot limpo.
- O número de teste tinha um estado do agente de 25/08 (`id=10`, `transferido_humano`, "LLM
  indisponível ao oferecer a agenda"), que impediria a abertura ("já tem estado"). Apagado com
  autorização do Álefe; nenhuma ação pendente para o número.

### Roteiro do teste (pendente)

```bash
# 1. conferir
SELECT name, status FROM whatsapp_templates WHERE name LIKE 'nat_b_%';   -- os 5 APPROVED
# 2. backend/.env: FLUXO_B_ENXUTO=true (allowlist já é 83988046720); sudo systemctl restart cenat-backend
# 3. Álefe: aplicar na LP sem agendar; responder a motivação; escolher horário; clicar "Preciso remarcar"
SELECT etapa, encerrado_motivo FROM nat_qualificacao_state WHERE contact_wa_id LIKE '%88046720' ORDER BY created_at DESC LIMIT 3;
SELECT kind, status, run_at, left(motivo,60) FROM nat_scheduled_actions WHERE contact_wa_id LIKE '%88046720' AND kind LIKE 'reativ%' ORDER BY run_at;
```

Abrir a allowlist só com aprovação explícita.
