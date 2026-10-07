# Liberação geral das três réguas (07/10/2026)

Confirmação (Bloco 1), no-show (Bloco 2) e Fluxo B (Bloco 3) liberados para todos os telefones.
Monitoramento de 2 horas, de 12:33 a 14:34 UTC.

## 1. O que foi feito

| hora (UTC) | ação |
|---|---|
| 12:24:53 | `.env`: `CONFIRMACAO_SOMENTE_TELEFONES=`, `NOSHOW_SOMENTE_TELEFONES=`, `FLUXO_B_SOMENTE_TELEFONES=` (vazias); as três flags `true`; restart |
| 12:27 | 1º ciclo do espelho: 9 réguas armadas |
| 12:28 | 9 confirmações imediatas enviadas; 2 voltaram 131026 e 1 voltou 130472 |
| 12:29 | **critério de parada** (131xxx em mais de 1 envio): parei e chamei o Álefe, sem desligar |
| 12:32 | limpeza dos dois números inválidos, pela própria trava nova (§4) |
| 12:33:03 | restart com o commit `639fa84` (trava 131026 + linhas de boot); monitor retomado |
| 14:34 | fim das 2 horas |

Linhas de boot depois do restart:

```
✅ Régua de confirmação: LIGADA (todos os telefones) — Victória Amorim: telefone (21) 97007-5652, ...
✅ Régua de no-show (D0 a D8): LIGADA (todos os telefones)
✅ Fluxo B enxuto (uma pergunta, reativações, remarcar pelos botões): LIGADO (todos os telefones)
```

(A linha da confirmação traz um travessão porque é a saída literal do log.)

## 2. Medição antes do restart (itens 2, 3 e 6 do pedido)

**O que o 1º ciclo armaria.** A consulta do pedido, `slot_inicio > now()`, compara um horário de
SP sem fuso com o `now()` do banco, que é UTC, e por isso perde 3 horas. Com `now() AT TIME ZONE
'America/Sao_Paulo'` o resultado é este:

```
query do pedido (now() UTC):  (7, 2026-10-07 17:30, 2026-10-09 18:15)
mesma query em SP:            (9, 2026-10-07 10:00, 2026-10-09 18:15)
armáveis no 1º ciclo: 9 | com menos de 4h (só a imediata): 2
ações a criar: imediata 9, ementa 6, benefício 6, pedido 6, último aviso 7, corte 7
Vigentes já passadas: 12 (_armar_vigentes só seleciona slot_inicio > agora; armar() recusa "já começou")
```

O log do ciclo confirmou as duas reuniões de menos de 4h (4772376 e 4772377, às 10h): "só a
confirmação imediata", 1 ação cada.

**Abertura nova para quem aplicou antes.** Na hora do restart não havia nenhuma
`iniciar_qualificacao` pendente. Quem aplicou antes já tinha estado, que continua no caminho
antigo, porque a marca do Fluxo B é gravada por estado. Ressalva: a proteção é essa, e não o
`qualificacao_start_at`. Ele vale desde 27/09 e não filtra pela hora da liberação; o caminho é
decidido quando a abertura roda. Nenhuma abertura rodou durante as 2 horas (§3).

**Reversão confirmada no código.** Com a flag desligada, cada handler levanta `AcaoIgnorada` com
o nome da flag, e a ação vira `skipped` com motivo:

- confirmação: "CONFIRMACAO_ENABLED desligado", `confirmacao.py` `_espinha`;
- no-show: "NOSHOW_ENABLED desligado", `noshow.py` `_espinha`;
- reativações do Fluxo B: "FLUXO_B_ENXUTO desligado", `qualificacao_fluxo._reativar`.

Nada das réguas sai. Exceção: com `CONFIRMACAO_ENABLED=false` o T-30 volta ao template antigo
para todas as reuniões, que é o comportamento de antes do Bloco 1.

## 3. Números das 2 horas

**Primeiro ciclo (12:27):** 9 réguas, 41 ações.

| reunião | horário | ações | desfecho até 14:34 |
|---|---|---|---|
| 4774899 | 07/10 17:30 | 3 | **confirmou por botão** |
| 4774914 | 08/10 17:40 | 6 | **confirmou por botão** (a resposta fixa não saiu, §5) |
| 4773672 | 09/10 10:00 | 6 | **confirmou por botão** |
| 4774926 | 09/10 16:00 | 6 | respondeu fora do padrão: pausada para humano |
| 4772377 | 07/10 10:00 | 1 | régua encerrada: humano |
| 4772376 | 07/10 10:00 | 1 | imediata recusada (130472); a consultora cancelou às 10:35 por "Lead não compareceu" |
| 4774374 | 08/10 14:30 | 6 | régua viva, aguardando |
| 4774102 | 09/10 18:15 | 6 | telefone inválido (131026): régua encerrada |
| 4774051 | 08/10 18:15 | 6 | telefone inválido (131026): régua encerrada |

**Taxa de confirmação:** 3 de 6 entregues (50%), todas por botão e todas em menos de 2h.

**Ações** (janela de 3h, última leitura às 14:34):

```
confirm_a_imediata  executado 9
cancelado "confirmou"                 corte 3, último aviso 3, pedido 2
cancelado "humano"                    ementa 1, benefício 1, pedido 1, último aviso 1
cancelado "telefone_invalido_131026"  ementa 2, benefício 2, pedido 2, último aviso 2, corte 2
pendente                              ementa 3, benefício 3, pedido 1, último aviso 1, corte 2, lembrete_reuniao 3
```

Nenhuma ação `falhou`. Nenhum `skipped` com motivo fora do previsto.

**Mensagens** (`nat_etapa`, janela de 3h em SP):

```
nat_a_confirmacao   9  (delivered 3, read 2, sent 1, failed 3: 131026 ×2, 130472 ×1)
confirm_a_resposta  2  (delivered 1, read 1)   + 1 que não saiu (§5)
```

`nat_abertura_qualificacao` com 2 falhas 131026 é do caminho antigo do agente, antes da
liberação; a trava não cobre essa etapa.

**Envios da régua por hora:** pico de 9, às 12:28. O teto de parada era 20.

**Fluxo B:** nenhum lead novo aplicou na LP durante as 2 horas. 0 estados do Fluxo B, 0
`nat_b_*` enviados, 0 reativações. **O Fluxo B ainda não foi exercido em produção.**

**No-show:** nenhum corte nas 2 horas, então nenhuma régua de no-show armada.

## 4. Telefone inválido (131026): parada e trava

Duas confirmações imediatas voltaram `131026 Message undeliverable`: `5555555555555` (reunião
4774102) e `5555519999891` (4774051), telefones digitados errado na LP. Sem trava, cada uma teria
mais 5 mensagens fadadas a falhar e, no corte, mais 8 do no-show.

Decisão do Álefe: opção 2. Commit `639fa84`:

- `confirmacao.encerrar_por_telefone_invalido`: cancela confirmação, T-30 e no-show da reunião
  com o motivo `telefone_invalido_131026`; grava `regua_encerrada_motivo='telefone_invalido'`;
  registra a nota "[NAT] Telefone inválido para WhatsApp (erro 131026), régua encerrada"; notifica
  o SDR dono (tipo `telefone_invalido`).
- `qualificacao_fluxo.encerrar_por_telefone_invalido`: a mesma coisa para a `nat_b_abertura`;
  estado `encerrado` com motivo `telefone_invalido`, sem reativação.
- `telefone_invalido.ao_status_falho`, chamada nas duas portas do `failed`: o webhook de status e
  a reaplicação de status órfão. Só age com 131026 e só sobre a 1ª mensagem de cada régua.

A limpeza dos dois números foi feita rodando essa mesma função sobre as duas mensagens que
falharam: 6 ações canceladas em cada número, as notas gravadas nos leads 52504376 e 52503799, e
2 notificações ao user 5.

**O número do 130472** (`5531997457815`, reunião 4772376 às 10h): a régua tinha só a imediata
(menos de 4h). O T-30 das 9h30 foi pulado com "não confirmou — o aviso de 30 min é só para
confirmados (spec)" (motivo literal do código). Não houve envio seguinte para saber se a
exclusão da Meta vale só para MARKETING. A pessoa não recebeu nada antes da reunião, faltou, e a
consultora registrou "Lead não compareceu".

## 5. Defeito encontrado: resposta a quem clica sem o 9º dígito

A Ana Caroline (reunião 4774914) clicou "Confirmo" às 10:01. A confirmação foi gravada, mas a
resposta fixa não saiu:

```
🔒 NAT não enviou (confirm_a_resposta → 556198525281): contato não existe no banco
```

O clique chega com 12 dígitos e o contato está gravado com 13. `confirmacao.inbound` repassa o
número do inbound sem resolver o contato, e o envio procura por igualdade exata. Atinge toda
resposta imediata das réguas de confirmação e de no-show para DDD fora de 11 a 28 (cerca de 59%
das conversas). Os envios agendados, o T-30 e o Fluxo B resolvem o contato e não são afetados.

Correção proposta, **aguardando aprovação**: `wa_id = await canonizar(wa_id, db)` no início de
`confirmacao.inbound`, restart, e reenviar à Ana a confirmação que não saiu.

## 6. Outros avisos do log

- 13:25 UTC: `reuniao_sync: ciclo abortado, cursor NÃO avançou — ExactIndisponivel` (literal do
  log). Pontual: os 5 ciclos anteriores e os seguintes foram limpos, e o ciclo abortado não perde
  dado.

## 7. Pendências

1. Correção do §5 (aprovação do Álefe).
2. Fluxo B sem nenhum caso real ainda: acompanhar a primeira abertura e as reativações.
3. A consulta de monitoramento do pedido usa `now()` UTC contra horários de SP; as do script
   usado aqui já estão corrigidas.
