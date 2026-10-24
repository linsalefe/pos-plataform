# SPRINT: trava de reaplicação (24/10/2026)

Item 2 dos quatro pedidos do comercial. Base: `RECON_4_PEDIDOS_COMERCIAL_20261024_REPORT.md` §2.

**Resultado:** no ar desde 24/10 15:29 SP (restart do `cenat-backend` na branch `feat/trava-reaplicacao`, depois merge na `main`). Quando chega uma aplicação nova (LP ou link do token) de um telefone que já tem reunião Vigente e futura, a resposta é 200 com a reunião existente: sem `LeadsAdd`, sem `BoxesAdd`, sem fila do RD e sem abertura do agente. O teste real com o número do Álefe passou nos três casos (§3).

## 1. O que mudou

| arquivo | mudança |
|---|---|
| `backend/app/agendamento/trava.py` (novo) | `reuniao_vigente_futura` (por `chave_telefone` em `reuniao_status`, Vigente e `slot_inicio > agora`, a mais próxima), `identidade_bate`, `whatsapp_url`, `resposta_ja_agendado`, `logar` |
| `backend/app/agendamento/routes.py` | `_travar_reaplicacao` roda antes de qualquer escrita em `POST /agendar`, `POST /lead`, `POST /espontaneo/{token}/agendar` e `/lead`. `_recusar` aceita o telefone explícito (o corpo do token não traz telefone) |
| `backend/app/agendamento/rastro.py` | motivo `JA_AGENDADO = "ja_agendado"` |
| `backend/app/agendamento/agendar.py` | `_duplo_clique` compara por `formas_gravadas` (todas as grafias do número), não pelo telefone bruto. `fluxo.agendar` e `cadastrar_lead_sem_agendar` não conhecem a trava |
| `docs/obrigado-snippet.html` | ramo `ja_agendado`: mostra a reunião existente (ou o texto genérico) e o botão "Remarcar pelo WhatsApp", sem grade. Com `?ja=1` na URL, a grade nem é carregada |
| `docs/form-nativo-snippet.html` | quando o `/lead` responde `ja_agendado`, passa `&ja=1&inicio=&consultora=&wa=` para o obrigado |
| `docs/AGENDAMENTO.md` | resposta `ja_agendado` em §4.1, motivo na tabela de §4.3, SQL de conferência em §3.5, linha no histórico |
| `backend/test_trava_reaplicacao.py` (novo) | 13 casos, **escritos e não executados** |

Sem DDL.

### Desvios do brief, aprovados no checkpoint

1. `exact_leads` não tem e-mail. O e-mail é comparado com o que a pessoa digitou na LP para aquela reunião ou lead (`agendamentos.email`). Na reunião marcada pela SDR na Exact não existe essa linha, e aí só o nome vale.
2. Nas rotas do token, a identidade é dada por provada, porque o telefone vem do link mandado para aquele WhatsApp. A trava roda antes de o token ser consumido, então o link não é queimado.
3. O `form-nativo-snippet.html` também mudou, para a página de obrigado não mostrar a grade a quem já tem reunião.
4. No `/agendar`, a trava roda antes da validação do horário: quem tem reunião e manda um horário vencido recebe a reunião existente, não um 400.

## 2. As respostas

Com reunião, e nome ou e-mail batendo:
```json
{"ok":true,"ja_agendado":true,"agendamento_id":1346,"lead_id":53203786,
 "inicio":"2026-10-27T18:00:00","fim":"2026-10-27T18:45:00","fuso":"America/Sao_Paulo",
 "consultora_nome":"Victória Amorim",
 "mensagem":"Você já tem uma conversa marcada com a nossa consultora.",
 "whatsapp_url":"https://wa.me/5511952137432",
 "aviso":"Para remarcar ou cancelar, fale com a gente pelo WhatsApp."}
```
Com reunião e nada batendo: as mesmas chaves, com `inicio`, `fim` e `consultora_nome` nulos e a `mensagem` "Já recebemos seu contato e sua conversa com a consultora está marcada. Para remarcar, fale com a gente pelo WhatsApp."

Sem reunião: as respostas de antes, sem nenhuma mudança.

Snippet antigo: mostra "Agendado! <data da reunião existente>" com dados, ou "Recebemos seu contato!" sem dados. Nos dois casos, sem erro.

## 3. Teste real com o número do Álefe (83988046720), 24/10 15:30 SP

```
1. POST /agendar  nome "Álefe Lins", slot 27/10 18:00          -> 200 agendado #1346, lead 53203786,
                                                                 box 44208838, Victória Amorim
2. POST /lead     "alefe guimel", tel 5583988046720 (com 55)    -> 200 ja_agendado, COM data e consultora (nome bate)
3. POST /agendar  "Maria Teste", maria@x.com, tel 8388046720    -> 200 ja_agendado, inicio/fim/consultora null (nada bate)
   (sem o 9º dígito)
4. POST /agendar  "Fulano", "AlefeLins01@gmail.com " (e-mail    -> 200 ja_agendado, COM data (e-mail bate)
   igual, caixa e espaço diferentes)
```

Banco depois do teste:
```
  id  |  passo   | motivo_recusa | lead_id  |  box_id  |       sales_rep_email        | erro
 1346 | agendado |               | 53203786 | 44208838 | comercial@cenatcursos.com.br |
 1347 | recusado | ja_agendado   |          |          |                              | /lead · meeting_id=4789469 lead=53203786 slot=2026-10-27 18:00
 1348 | recusado | ja_agendado   |          |          |                              | /agendar · meeting_id=4789469 ... · slot='2026-10-27T17:15:00' leadId=None
 1349 | recusado | ja_agendado   |          |          |                              | /agendar · meeting_id=4789469 ...
reuniao_status: 4789469 | Vigente | 2026-10-27 18:00 | hub | agendamento 1346
```

No journal, cada reaplicação deixou um `🔁 reaplicação travada: 8388046720 já tem reunião 4789469 em 27/10 18:00` e a linha `agendamento recusa: ... motivo=ja_agendado`. Não apareceu `📦` nem `👤` para as linhas 1347 a 1349, ou seja, nenhum box nem lead foi criado na Exact.

**Reunião de teste mantida (decisão do Álefe, 24/10):** a reunião 4789469 (lead 53203786) continua Vigente na agenda da Victória Amorim na **terça 27/10 às 18:00** e **não** será cancelada; o comercial vai ser avisado de que é teste. Até ela passar, o número do Álefe continua travado na LP, e as reaplicações dele entram na contagem de `ja_agendado` (por isso o filtro `id > 1349` e, depois, excluir a chave `8388046720`).

## 4. Primeiras 24 h

**Ainda não medido:** as 24 h acabam em 25/10 15:29 SP. As consultas estão prontas (também em `docs/AGENDAMENTO.md` §3.5). Elas excluem as linhas do teste (id ≤ 1349):

```sql
-- quantas pessoas travadas, e com dados exibidos vs genérico (o journal diz qual rota)
SELECT count(*) linhas, count(DISTINCT right(regexp_replace(telefone,'\D','','g'),8)) pessoas
FROM agendamentos WHERE motivo_recusa='ja_agendado' AND id > 1349;

-- travou errado? reunião que já tinha passado ou não estava Vigente (tem que dar zero)
SELECT a.id, a.created_at, r.meeting_id, r.exact_type, r.slot_inicio
FROM agendamentos a JOIN reuniao_status r
  ON r.meeting_id = substring(a.erro from 'meeting_id=(\d+)')::bigint
WHERE a.motivo_recusa='ja_agendado' AND a.id > 1349
  AND (r.slot_inicio <= a.created_at                     -- reunião já tinha passado
       OR (r.exact_type <> 'Vigente' AND r.exact_type_visto_em <= a.created_at));
                                                          -- já estava cancelada/concluída
```

Para dados exibidos vs genérico não há coluna: a resposta não é gravada. A contagem sai comparando o nome da linha recusada com `reuniao_status.nome` pelo `meeting_id`, ou pelo journal.

Leitura para o snapshot: no fluxo de duas etapas com o snippet antigo, uma reaplicação gera **duas** linhas, uma no `/lead` e outra no `/agendar`. Contar pessoas, não linhas.

## 5. Para a Isa

- **Republicar as LPs** com o `obrigado-snippet.html` e o `form-nativo-snippet.html` novos. Só assim aparecem a mensagem própria e o botão "Remarcar pelo WhatsApp". Até lá, a trava já funciona e o visitante vê "Agendado! <data>" ou "Recebemos seu contato!".
- **D1:** a reaplicação para **outro curso** fica só no Hub (`sub_source` e `extras` na linha recusada). Vale uma nota na timeline do lead existente?
- **D3:** a reaplicação **sem** reunião continua criando lead novo (57 dos 63 leads a mais medidos no RECON). Reaproveitamos o lead anterior?
- **D4:** o botão abre o WhatsApp do canal do agente (5511952137432). Fica assim, ou passa a ser o número da consultora?

## 6. Testes

`backend/test_trava_reaplicacao.py`: escrito e **não executado** (convenção da sprint). Casos: predicado; grafias do telefone; telefone ilegível; `/agendar` com nome, com e-mail e sem nada batendo; `/lead`; invariantes da linha recusada; fluxo normal sem reunião; reunião `origem=exact`; rotas do token (link não consumido); `fluxo.agendar` sem a trava; `_duplo_clique` por chave. `import app.main` passa.
