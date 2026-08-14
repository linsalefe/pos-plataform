# Sprint A · Bloco 6 — Recuperação do lead sem contato (14/08/2026)

Branch `sprint-a-bloco-6-recuperacao`. **Sem merge.** A NAT permanece DESLIGADA
(`nat_enabled=false`, `nat_start_at=NULL`): nada do que está aqui envia mensagem hoje.

## O problema

O SDR liga, ninguém atende, e acabava aí. O lead ficava parado em `aguardando_ligacao` — o
SLA do Bloco 5 já tinha escalonado e se esgotado, então nenhum mecanismo olhava mais para
ele. Quem lembrasse, lembrava; quem não lembrasse, perdia o lead em silêncio.

## O que passou a existir

```
SDR clica "Não consegui contato"
  │
  ├─ registra a tentativa (nat_contact_attempts + nat_flow_state.tentativas_contato)
  ├─ cancela o sla_check pendente
  ├─ manda ao lead a ÚNICA mensagem deste fluxo (nat_recuperacao_sdr, 2 botões)
  └─ agenda retry_contato para +10 min  ── só se ainda não for a 2ª tentativa
        │
        └─ 10 min depois: COBRA O SDR (notificação). Nunca manda nada ao lead.
             sai calado se: não há estado · a etapa mudou · alguém assumiu

Lead clica "Tentar novamente agora"  → avisa o SDR na hora, volta para aguardando_ligacao,
                                       zera a escada e arma sla_check novo
Lead clica "Agendar outro horário"   → reagendado, com o aviso ao SDR que já existia
```

## As três travas contra mandar mensagem a mais

O único envio novo da sprint é `nat_routes.py`, dentro do endpoint, disparado por clique
humano — e passa por `send_nat_message` → `nat_pode_atuar` como todo envio da NAT. Além
disso:

1. **`SELECT … FOR UPDATE`** no `nat_flow_state`. Sem ele, dois SDRs clicando no mesmo
   instante leriam `tentativas_contato = 0` juntos e o lead receberia duas mensagens,
   queimando as duas tentativas de uma vez. É a única defesa real contra isso — a janela de
   idempotência sozinha não resolve corrida.
2. **Janela de idempotência de 30s, por CONTATO** (não por usuário). O que a janela protege é
   o lead, e o dano do segundo clique é o mesmo venha de quem vier.
3. **Teto de 2**, aplicado antes de qualquer envio. Na 2ª a mensagem ainda sai — é a última
   chance do lead reagir — mas nenhum retry é agendado e a etapa vai para `encerrado`.

O handler agendado **não envia e não reagenda**: sem reagendamento não existe ciclo. Cada
"sem contato" gera no máximo um retry, e ele termina em si mesmo.

## Duas decisões que o plano não previa

**O clique é atendido também em `encerrado`, quando o encerramento veio do teto.** A 2ª
tentativa manda a mensagem E encerra o fluxo no mesmo ato. Sem esse caso, o lead receberia
dois botões vivos apontando para um estado que descarta cliques em silêncio — exatamente a
classe de bug dos cliques perdidos que esta sprint existe para matar. `encerrado` por
"Assumir ligação" continua calado: ali um humano está conduzindo, e ignorar é a resposta
certa. O corte é `assumido_por`.

**"Tentar novamente agora" zera `escalonamento_nivel` e recarimba `transferido_em`.** Sem
isso o `sla_check` novo nasce morto: o ciclo anterior quase sempre termina no nível 2, que é
a primeira saída de "nada a fazer" do handler do SLA. O relógio que se arma ali é de uma
promessa nova ("um consultor vai te ligar agora") e pede uma escada nova.

## Achado no WABA: dois `nat_recuperacao_sdr` aprovados

Existem **duas** versões aprovadas do mesmo nome, uma em `en` e outra em `pt_BR`, com corpos
**diferentes**. O envio pede `pt_BR` (`nat_sender`, `language=nat_copy.IDIOMA`), então é o
corpo pt_BR que está em `CORPO_APROVADO`, copiado verbatim da API.

O teste de drift indexava os templates só por nome (`{t["name"]: t for t in data}`). Com nome
duplicado, quem ficava no dict era o último que a Graph API devolvesse — hoje o pt_BR, por
acaso, porque a ordem da lista não é contrato. Um dia isso passaria a comparar contra o corpo
em inglês e acusaria drift inexistente. Agora **filtra por idioma antes de indexar**, e
confere também `status == APPROVED` e o limite de 20 caracteres dos títulos livres.

Dívida deixada de fora: o GET usa `limit=100` e o WABA já tem 78 templates — sem paginação, o
drift começa a cegar perto de 100.

## Banco

`nat_contact_attempts` (migração rodada em produção, idempotente, conferida no
`information_schema`):

| coluna | tipo | nota |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `contact_wa_id` | VARCHAR(20) NOT NULL | sem FK, como o resto da NAT |
| `tentativa_num` | INTEGER NOT NULL | 1 ou 2; confere contra o contador vivo |
| `registrado_por` | INTEGER | `users.id`, sem FK |
| `resultado` | VARCHAR(20) | livre, sem CHECK — ponto de extensão |
| `created_at` | TIMESTAMP | escrito por nós em SP; o DEFAULT NOW() é UTC e só serve de auditoria |

Índice `(contact_wa_id, created_at)` — é a consulta da janela de idempotência. **Sem** UNIQUE
em `(contact_wa_id, tentativa_num)`: a corrida é resolvida pelo lock, e um UNIQUE só
transformaria o resto dela num 500 na cara do SDR.

Tabela nova em vez de `call_logs` porque `call_sid` é UNIQUE NOT NULL e uma tentativa marcada
à mão não tem sid — reusar exigiria inventar dado numa tabela hoje fiel ao Twilio.

O CHECK de `nat_flow_state.etapa` já aceitava `sem_contato` desde `migrate_nat_flow_state.py`:
nenhum ALTER foi necessário.

## Testes

`backend/test_nat_recuperacao.py` — 11 casos, nada enviado e nada gravado: registro + envio +
agendamento; clique duplo em menos de 30s; 2ª tentativa encerrando sem retry; 3º clique sem
enviar nada; os três no-ops do handler; os dois cliques do lead (inclusive sem payload,
resolvido por texto, com "Outro horário" desempatado pela etapa); cancelamento do `sla_check`;
`button_payloads` por índice; e o drift contra a Meta.

Regressão verde nas 11 suítes: `test_nat_flow` (13/13), `test_nat_guard` (9/9),
`test_nat_sprint3`, `test_observabilidade_envio`, `test_welcome_guardrail`,
`test_parse_datetime`, `test_nat_reagendado` (5/5), `test_nat_duplicata` (5/5),
`test_nat_caminho_completo`, `test_nat_config_api`, `test_nat_recuperacao`.

O dublê `_estado()` de `test_nat_sprint3` ganhou `tentativas_contato` — sem a coluna, o
`AttributeError` caía no try/except do fluxo e o teste ficaria verde por engano.

## Smoke em produção

Restart do `cenat-backend.service` limpo, sem erro de import no journal. Uma ação
`retry_contato` de smoke (wa_id inexistente, `0000000000000`) foi despachada pelo job no ciclo
seguinte, caiu na primeira saída de "nada a fazer" e foi marcada `executado` — **não**
`falhou`, que é o que aconteceria se o módulo não estivesse em `MODULOS_DE_HANDLERS`. Zero
notificações, zero mensagens; a linha de smoke foi removida em seguida.

Webhook não foi forjado de propósito: `main.py:316` reencaminha todo corpo recebido para um
sistema externo, e um payload sintético viraria dado falso na casa de terceiros.

## Fora de escopo (segue valendo)

Extração de período com IA (Sprint B) — `NAT_AGENDAR_OUTRO` só muda a etapa. Cenário 2 /
reativação 09h (Sprint C). Follow-up (Sprint D). E a dívida registrada aqui: **o lead não
recebe confirmação** ao clicar em "Tentar agora" ou "Outro horário" na mensagem de
recuperação — é o único ponto do fluxo em que a NAT fica muda depois de um clique.
