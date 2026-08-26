# SPRINT P3-A — o vigia "AGENTE MUDO" (`vigiar_resposta`) — 26/08/2026

Último item estrutural do conserto do silêncio. Fecha a série que começou em
`AUDITORIA_SILENCIO_AGENTE_20260826.md` e passou por
`SPRINT2_SILENCIO_AGENTE_20260826.md`.

Os buracos **conhecidos** foram fechados (P0-A..P0-E, P1-A, P1-B). Este detector existe
para a classe que **ainda não conhecemos** — como a falha de contrato do LLM de 26/08 10:11,
que segue sem nome. Ele não vigia uma causa: vigia o **sintoma original**, que é lead
escreveu e agente não respondeu.

**Estado:** implementado, testado, commitado e pushado. **NÃO deployado** — o processo em
produção (PID 1604426, subiu 14:10:20 UTC) roda até `fe5b1c6`.

---

## 1. Commits

| Commit | O que |
|---|---|
| `ab559cd` | o vigia: kind, constantes, `_armar_vigia`, handler `vigiar_resposta`, cancelamento em `enviar_nat` |
| `3dd5b0d` | `test_vigia_agente_mudo.py` (7 grupos) + ajuste em `test_nat_caminho_completo.py` |

---

## 2. Nenhuma migração — confirmado contra o banco, não contra a memória

```sql
-- CHECKs de nat_scheduled_actions
nat_scheduled_status_valido | CHECK (status IN ('pendente','executado','cancelado','falhou','skipped'))
-- e mais nada. `kind` é VARCHAR livre.

-- o índice único parcial
uq_nat_sched_pendente_por_contato UNIQUE (kind, contact_wa_id) WHERE status = 'pendente'

-- notifications
notifications_pkey | PRIMARY KEY (id)
notifications_user_id_fkey | FOREIGN KEY (user_id) REFERENCES users(id)
-- nenhum CHECK sobre `type`.
```

**O índice é sobre `(kind, contact_wa_id)`, não sobre o contato sozinho.** Era o risco que o
prompt mandava reportar antes de mexer: ele **não** existe. Um `vigiar_resposta` convive com
o `encerrar_inativo` e com o `responder_pendente` do mesmo contato. **Zero ALTER, zero
migração**, nem na tabela de ações nem na de notificações.

---

## 3. A decisão do checkpoint — a régua é a ESPERA, não o `run_at`

**A pergunta:** com uma fala adiada pelo teto (P0-B) pendente, o vigia deve calar ou falar?

**Duas medições decidiram o desenho, e a segunda inverteu a mecânica proposta:**

1. **`ATRASO_POR_TETO` = 10 min e o vigia vence em inbound+10 min — os dois relógios
   coincidem.** Sem supressão, todo adiamento por teto geraria um "AGENTE MUDO" no minuto
   exato em que a resposta ia sair. Alarme que erra é alarme que ninguém lê — que é
   literalmente o diagnóstico da auditoria sobre os `window_*`. Portanto: **(a), suprimir.**

2. **`AcaoAdiada` NÃO consome tentativa** (está na docstring dela em `nat_scheduler.py:133`)
   e `responder_pendente` readia sempre para +10 min. Logo **o `run_at` da pendência fica
   para sempre a menos de 10 min de distância**. Um teto medido no `run_at` — *"não dispara
   se a pendência está agendada para < 30 min"* — **nunca deixaria o vigia disparar**. Seria
   supressão permanente, justo no caso em que o lead mais precisa do alarme.

**Implementado:** a régua é a **espera do lead**, que só cresce.

```
espera do lead   pendência?   vigia
---------------------------------------------------------
10 min           sim          ADIA (+10 min, motivo na linha)
20 min           sim          ADIA
29 min           sim          ADIA
30 min           sim          >> NOTIFICA A GESTÃO <<
45 min           sim          >> NOTIFICA <<
11 min           não          >> NOTIFICA <<
 3 min           —            ADIA (ainda no prazo)
```

**Por que 30 min:** são três readiamentos seguidos — três falhas do "esperar resolve" —, e
ainda sobram 23h30 da janela de 24h para agir.

**Confirmado, como pedido:** **horário comercial não se aplica à conversa.**
`dentro_horario_comercial` aparece em **um único ponto** do módulo
(`qualificacao_fluxo.py:754`), dentro de `iniciar_qualificacao` — a abertura. O
`responder_pendente` não tem essa porta, então ele nunca é empurrado para o dia seguinte, e
a supressão nunca fica pendurada por causa de fim de expediente.

**Nota de realidade:** desde o P1-B o teto não recusa mais conversa, então
`responder_pendente` está dormente — **nunca existiu uma linha desse kind no banco**. Toda
esta interação é sobre um caminho hoje inativo, mantido de pé como rede.

---

## 4. A fronteira de cobertura — quem cobre o quê

Armar no ponto do `_agendar_encerramento` é armar **dentro do savepoint do webhook**. Um
turno que estoura reverte o INSERT do vigia junto. Isso não é descuido: é divisão de
trabalho, e está escrito no docstring de `_armar_vigia` para quem mexer depois não "consertar"
o que é decisão.

| Situação | Quem cobre |
|---|---|
| Turno termina "com sucesso" e **não fala** | **o vigia** — o savepoint commita, o vigia sobrevive e dispara. **Esta é a classe-alvo:** a falha de 10:11 sem nome e qualquer outra com a mesma assinatura |
| Turno **estoura** no meio | a rede do **P0-C** — notifica o MESMO `GESTOR_USER_ID`, em sessão nova, com traceback, e ainda se despede do lead |
| Webhook morre **antes** do roteamento | **ninguém, e nem podia ser diferente** — nada foi escrito, nem a `Message` do inbound. É o caso do pool esgotado em `main.py:370`, cujo dono é o P1-A |

Armar em sessão própria cobriria a segunda linha também — ao custo de **uma conexão a mais
por mensagem de lead**, num pool dimensionado para a retenção de uma só, e para duplicar um
aviso que o P0-C já manda. Não vale o preço.

---

## 5. Onde o cancelamento mora, e por quê

Em **`enviar_nat`**, depois do envio confirmado — não em `_falar`.

Este é o **único ponto por onde todo envio da NAT passa** (é o mesmo motivo por que
`nat_etapa` é gravado ali). Cancelar em `_falar` deixaria de fora a despedida do
`_fallback`, a confirmação do `_concluir`, a oferta de agenda e o lembrete — e vigia
sobrevivente depois de o agente ter falado é falso positivo, a doença que este detector veio
curar, não espalhar.

**Depois do envio, nunca antes:** recusa do guard e recusa da Meta saem por `recusa(...)` e
não chegam nessa linha. O vigia continua de pé justamente porque, nesses casos, o lead
continua sem resposta. E o cancelamento não levanta: falhar ao cancelar não pode desfazer
uma mensagem já entregue.

---

## 6. Os testes — `test_vigia_agente_mudo.py`

```
1) agente falou -> vigia cancelado (kind e contato certos)
   recusa do guard NÃO cancela · Meta recusando NÃO cancela
   cancelamento que falha NÃO desfaz o envio
2) mudo aos 11 min -> notifica a GESTÃO, título "AGENTE MUDO — lead esperando há 11 min",
   corpo com etapa e com o horário do inbound, tipo próprio `agente_mudo`,
   e NADA enviado ao lead
   etapa que mudou desde o armar -> o corpo registra as duas
   GESTOR_USER_ID inexistente -> levanta ALTO (detector de silêncio não pode virar silêncio)
3) transferido_humano / concluido / encerrado -> ignora, com motivo na linha
   sem estado · sem inbound · lead escreveu há 3 min -> ignora ou adia, nunca notifica cedo
4) pendência viva a 10, 20 e 29 min -> ADIA, com motivo gravado
   >> pendência readiada 3× (30 min de espera) -> NOTIFICA mesmo com pendência viva <<
   45 min com pendência -> notifica · 11 min sem pendência -> notifica
5) armar grava no agendador (banco) para +10 min, com a etapa no payload
   "restart": o handler roda só com a linha do banco (dict), sem estado de processo
   armar que falha NÃO levanta
6) dois inbounds -> cada armada cancela a anterior antes de inserir; um vigia só
7) o 9º dígito: inbound e pendência procurados nas DUAS grafias
```

O grupo 7 não estava no pedido e é o que impede o bug se repetir dentro do próprio detector:
um vigia estrito não veria a mensagem do lead que ele vigia e calaria — o silêncio
reproduzido dentro do detector de silêncio.

**Regressão consertada, e ela é do próprio P3-A:** `test_nat_caminho_completo.py` comparava
a lista de cancelamentos por **igualdade exata** (`cancelados == [("sla_check", WA_ID)]`).
Como agora todo envio da NAT cancela o vigia, a travessia de 3 mensagens traz 3
cancelamentos a mais. A asserção passou a afirmar a mesma coisa sem a igualdade frágil:
`("sla_check", WA_ID) in cancelados`, e os demais são só do vigia.

**16 suítes verdes:** vigia, qualificação, rede de última instância, guard, risco3, gatilho,
sprint3, caminho completo, espontâneo, observabilidade, nat_flow, recuperação, duplicata,
reagendado, agendamento, welcome guardrail.

---

## 7. Os vigias de validação do Sprint 2

| Vigia | Estado às 14:37 UTC |
|---|---|
| Primeira hora depois do restart | **rodando** — fecha às 15:04 UTC |
| Primeiro agendamento orgânico (P0-A) | **rodando** — espera `agendamentos.id > 209` até ~18:10 UTC |

Nenhum dos dois fechou. Números parciais, colhidos às 14:07: **0** linhas de SQL cru, **0**
`QueuePool limit`, contra **98.780** linhas de journald na hora anterior ao restart.
O log do P0-E ainda não tem o que mostrar — não houve inbound de lead desde o restart.

---

## 8. Pendências

- **Deploy do P3-A** — `ab559cd` e `3dd5b0d` não estão no ar. Um restart resolve, e ele
  precisa de aviso.
- Fechamento dos dois vigias do Sprint 2.
- Operacional, com o time: Isa assumir a Fabiana (reunião pedida para **27/08 11:15**,
  amanhã, **sem reserva**), cortesia para a Eve, SDR 6 responder a Osmari, desambiguação do
  Pablo.
- Backlog: sprint do `format_phone` / unificação de threads (12 vs 13 dígitos no Hub); a
  causa indeterminada da falha de contrato de 10:11 — que o P0-E nomeia na próxima
  ocorrência e que **este vigia agora alarma em 10 minutos**, mesmo sem nome.
