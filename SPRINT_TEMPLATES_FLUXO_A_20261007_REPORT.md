# SPRINT: submissão dos templates do Fluxo A (confirmação) à Meta, 07/10/2026

Branch `feat/templates-fluxo-a`, a partir da `main` em `8f4146c`. Texto: spec da Isa, "IA de
Confirmação e No-show" (28/09), seção "Textos", páginas 7 e 8
(`Otimização IA - No show (validar).pdf`, na raiz do repo). Nenhum envio a lead, nenhuma mudança
de fluxo, sem restart.

## 1. Resultado

**7 de 7 na Meta, nenhum recusado na análise.** Um foi recusado na **criação** e ressubmetido
com o texto ajustado (seção 4). Status ao vivo em 07/10 09:53 UTC:

| template | `template_id` (Bloco 1) | status | categoria pedida | devolvida |
|---|---|---|---|---|
| `nat_a_confirmacao` | 28174126795619519 | PENDING | UTILITY | UTILITY |
| `nat_a_ementa` | 1132061579475069 | PENDING | MARKETING | MARKETING |
| `nat_a_beneficio` | 1568762097912454 | **APPROVED** | MARKETING | MARKETING |
| `nat_a_pedido_confirmacao` | 1667489198282546 | PENDING | UTILITY | UTILITY |
| `nat_a_ultimo_aviso` | 2528299630971333 | PENDING | UTILITY | UTILITY |
| `nat_a_30min` | 1100087952720335 | PENDING | UTILITY | UTILITY |
| `nat_ns_d0_corte` | 2140148133247822 | PENDING | MARKETING | MARKETING |

Nenhuma reclassificação: a Meta devolveu a categoria pedida nos 7. Gravados em
`whatsapp_templates` (canal 1) com `meta_template_id`, categoria, `components` e status do
momento da submissão. `whatsapp_templates` é um retrato: `nat_a_beneficio` consta `PENDING` lá e
já está `APPROVED` na Meta. A fonte de status continua sendo a Meta (`routes.list_templates`).

## 2. Os 7 JSONs finais

Todos com `"language": "pt_BR"` e `"allow_category_change": true`. Os corpos saem de
`nat_copy.CORPO_SUBMETIDO_FLUXO_A`, e os quick replies de `nat_copy.BOTOES_FLUXO_A`.

```json
{"name":"nat_a_confirmacao","category":"UTILITY","components":[
 {"type":"BODY","text":"Olá, {{1}}! Sua reunião do processo seletivo da Pós em {{2}} está agendada para {{3}}, às {{4}}. É uma ligação rápida, de cerca de 15 minutos, com a consultora {{5}}, para tirar suas dúvidas e ver se a pós faz sentido para você.\n\nParticipando no horário combinado, você garante a isenção da taxa de matrícula e um e-book exclusivo CENAT.",
  "example":{"body_text":[["Ana","Saúde Mental","quinta-feira, 09/10","14:30","Victória"]]}},
 {"type":"BUTTONS","buttons":[{"type":"QUICK_REPLY","text":"Confirmo"},{"type":"QUICK_REPLY","text":"Preciso remarcar"}]}]}

{"name":"nat_a_ementa","category":"MARKETING","components":[
 {"type":"BODY","text":"Oi, {{1}}! Enquanto sua reunião não chega, separei a ementa da Pós em {{2}} para você conhecer melhor o curso. É só tocar no botão abaixo. Nos falamos {{3}}, às {{4}}. Até lá!",
  "example":{"body_text":[["Ana","Saúde Mental","quinta-feira","14:30"]]}},
 {"type":"BUTTONS","buttons":[{"type":"URL","text":"Ementa da Pós","url":"https://drive.google.com/file/d/{{1}}",
  "example":["https://drive.google.com/file/d/1tv9smwk9AHcj9TefufQVL1SweoMbhvCj/view"]}]}]}

{"name":"nat_a_beneficio","category":"MARKETING","components":[
 {"type":"BODY","text":"Oi, {{1}}! Esqueci de te avisar: participando da reunião com a consultora no horário combinado, você garante a isenção da matrícula + um e-book exclusivo CENAT!",
  "example":{"body_text":[["Ana"]]}}]}

{"name":"nat_a_pedido_confirmacao","category":"UTILITY","components":[
 {"type":"BODY","text":"Oi, {{1}}! Sua ligação com a consultora {{2}} é {{3}}, às {{4}}. Nossa agenda está bem disputada e, sem confirmação, o horário é liberado para outro candidato. Você confirma?",
  "example":{"body_text":[["Ana","Victória","amanhã","10:00"]]}},
 {"type":"BUTTONS","buttons":[{"type":"QUICK_REPLY","text":"Confirmo"},{"type":"QUICK_REPLY","text":"Preciso remarcar"},{"type":"QUICK_REPLY","text":"Não vou conseguir"}]}]}

{"name":"nat_a_ultimo_aviso","category":"UTILITY","components":[
 {"type":"BODY","text":"Oi, {{1}}! Ainda não recebemos sua confirmação para a ligação de hoje, às {{2}}. Se não confirmar até as {{3}}, vamos liberar seu horário para outro candidato.",
  "example":{"body_text":[["Ana","14:30","10:30"]]}},
 {"type":"BUTTONS","buttons":[{"type":"QUICK_REPLY","text":"Confirmo"},{"type":"QUICK_REPLY","text":"Preciso remarcar"}]}]}

{"name":"nat_a_30min","category":"UTILITY","components":[
 {"type":"BODY","text":"Oi, {{1}}! Aqui é do CENAT. Daqui a 30 minutos a consultora {{2}} vai entrar em contato pelo número {{3}}. Fique de olho, porque o DDD pode ser diferente do seu. Até já!",
  "example":{"body_text":[["Ana","Victória","(11) 91234-5678"]]}}]}

{"name":"nat_ns_d0_corte","category":"MARKETING","components":[
 {"type":"BODY","text":"Oi, {{1}}. Como não recebemos sua confirmação, liberamos seu horário para outro candidato. Ainda quer participar do processo seletivo?",
  "example":{"body_text":[["Ana"]]}},
 {"type":"BUTTONS","buttons":[{"type":"QUICK_REPLY","text":"Posso falar agora"},{"type":"QUICK_REPLY","text":"Escolher horário"}]}]}
```

**Payloads** (fixados no envio, não na definição; ordem = índice do botão), em `nat_copy.py`:

| template | payloads |
|---|---|
| `nat_a_confirmacao` | `A_CONF_SIM`, `A_CONF_REMARCAR` |
| `nat_a_pedido_confirmacao` | `A_PED_SIM`, `A_PED_REMARCAR`, `A_PED_NAO` |
| `nat_a_ultimo_aviso` | `A_ULT_SIM`, `A_ULT_REMARCAR` |
| `nat_ns_d0_corte` | `NS_D0_AGORA`, `NS_D0_HORARIO` |

## 3. Ajustes de texto em relação ao PDF

| template | PDF | submetido | por quê |
|---|---|---|---|
| `nat_a_confirmacao` | `{dia}, {data}` | um parâmetro `{{3}}` ("quinta-feira, 09/10") | decisão 2: menos variável |
| `nat_a_ementa` | "{nome}, enquanto…" | "Oi, {{1}}! Enquanto…" | body não pode começar com variável |
| `nat_a_ementa` | "…conhecer melhor o curso: {link}." | "…conhecer melhor o curso. É só tocar no botão abaixo." + botão URL | decisão 4: link em botão com sufixo dinâmico, padrão `f3_guia*` |
| `nat_a_ementa` | "Nos falamos {dia}, às {hora}!" | "Nos falamos {{3}}, às {{4}}. Até lá!" | recusa da Meta na 1ª submissão (seção 4); final escolhido pelo Álefe |
| `nat_a_beneficio` | "{nome}, esqueci…" | "Oi, {{1}}! Esqueci…" | body não pode começar com variável |
| `nat_a_pedido_confirmacao` | "{saudação}, {nome}!" | "Oi, {{1}}!" | decisão 3 |
| `nat_a_ultimo_aviso` | "{nome}, ainda…" | "Oi, {{1}}! Ainda…" | body não pode começar com variável |
| `nat_ns_d0_corte` | sem nome | "Oi, {{1}}." na frente | corpo 100% fixo com botão de marketing é o perfil mais recusado |
| `nat_ns_d0_corte` | botão "Escolher novo horário" (21) | "Escolher horário" (16) | limite de 20 |
| `nat_a_confirmacao` | quebra de linha antes de "Participando" | `\n\n` | o PDF mostra parágrafo novo |

`nat_a_30min` sai verbatim. Nenhum emoji, nenhum travessão.

## 4. O que foi recusado e por quê

`nat_a_ementa`, na criação (não chegou a existir na Meta):

```json
{"error": {"message": "Invalid parameter", "type": "OAuthException", "code": 100,
 "error_subcode": 2388299, "is_transient": false,
 "error_user_title": "Parâmetros iniciais ou finais não permitidos",
 "error_user_msg": "As variáveis não podem estar no início ou no fim do modelo.",
 "fbtrace_id": "AYuMN5F6yPiVl6hjXCFxk7q"}}
```

O corpo terminava em "às {{4}}!": **para a Meta, pontuação final não conta como texto**. O
validador local olhava só o último caractere e deixou passar. Corrigido: `validar` trata
`[\s!?.,;:)]*` depois da variável como fim (e já recusa o texto antigo). Texto novo escolhido
pelo Álefe ("… às {{4}}. Até lá!") e ressubmetido com `--somente nat_a_ementa`: aceito,
`PENDING`, id 1132061579475069.

## 5. Arquivos

| arquivo | o quê |
|---|---|
| `backend/submit_templates_fluxo_a.py` | dry-run por padrão; `--apply` submete; `--somente NOME…` ressubmete um subconjunto; valida, grava em `whatsapp_templates` (idempotente por canal+nome+idioma) e relê o status na Meta; nunca imprime o token |
| `backend/app/nat_copy.py` | 7 nomes, 9 payloads, `CORPO_SUBMETIDO_FLUXO_A` (fonte do texto submetido) e `BOTOES_FLUXO_A` |

## 6. Desvios do plano

1. **Os corpos ficam em `CORPO_SUBMETIDO_FLUXO_A`, não em `CORPO_APROVADO`.** O teste de drift
   (`test_nat_flow.py`, caso 13) percorre `CORPO_APROVADO` exigindo `APPROVED` na Meta e os
   botões em `BOTOES_APROVADOS`; com `PENDING` lá dentro ele falharia por um motivo que não é
   drift. O Bloco 1 promove quando a Meta aprovar. Aprovado no checkpoint.
2. **O texto mora no `nat_copy`, e o script o importa.** Ninguém redigita o corpo em dois
   lugares: o que o Bloco 1 vai usar é, por construção, o que foi submetido.
3. **Canal por `auto_welcome_config.channel_id`** (canal 1, WABA …3727). `nat_config` não tem
   coluna de canal; é a leitura de `nat_sender._resolver_canal`.
4. **Exemplo do botão URL é a URL completa**, como a Meta exige. O id é o do botão do
   `f3_guiatea` na Meta (o `follow_estagios.json` não tem URLs).
5. **`--somente`** acrescentado para ressubmeter o recusado sem tocar nos 6 já em análise.
6. **Spec na raiz**, não em `docs/spec/`.

## 7. Para o Bloco 1

- Conferir em até 48h: `GET /{waba}/message_templates?name=<nome>`. Recusa na análise →
  reescrever e `--somente`.
- `nat_a_ementa` precisa do sufixo do Drive por curso no `{{1}}` do botão: a tabela curso → id
  sai dos botões dos `f3_guia*` na Meta. Se a URL dinâmica for recusada, vira 16 templates.
- `nat_a_30min` precisa do telefone de cada consultora (não existe no `consultoras.json`).
- Ao promover para `CORPO_APROVADO`/`BOTOES_APROVADOS`, o drift passa a vigiar os 7.
- `nat_lembrete_reuniao` segue aprovado e em uso até lá.
