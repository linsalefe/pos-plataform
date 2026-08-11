# Sprint de ativação da NAT — 11/08/2026

Correção dos bloqueadores mínimos do Cenário 1 e criação do kill switch por HTTP.
Fases 1 a 5. A Fase 6 (ativação) é registrada em seção própria, no fim.

Base: `ESTADO_NAT_20260809.md`. HEAD anterior `edfa4e7`.

---

## Resumo

| Fase | Entrega | Arquivos |
|---|---|---|
| 1 | `nat_boasvindas` deixa de sair duas vezes | `nat_flow.py`, `exact_spotter.py`, `nat_guard.py` |
| 2 | `reagendado` deixa de ser beco sem saída | `nat_flow.py` |
| 3 | `assumir` encerra o fluxo | `nat_routes.py` |
| 4 | `GET`/`PATCH /api/nat/config` | `nat_routes.py`, `auth.py`, `COMANDOS_UTEIS.md` |
| 5 | 5 suítes novas, 10 no total, todas verdes | `test_nat_*.py` |

Nenhuma migração. Nenhuma alteração de schema. Tudo reversível por `git revert` + restart.

---

## Fase 1 — o envio duplicado

### O que acontecia

`send_welcome_to_new_lead` (`exact_spotter.py`) enviava `config.template_name`
(= `nat_boasvindas`) e, dez linhas depois, chamava `iniciar_fluxo_nat`, que chamava
`send_nat_message(NAT_BOASVINDAS)`. Um lead novo não tem inbound, logo a janela de 24h da
Meta está fechada, logo o sender cai no ramo de template — e mandava **o mesmo template de
novo**. Nada entre os dois deduplicava.

Inerte até aqui só porque o guard barrava tudo em `nat_enabled=false`.

### A correção

`iniciar_fluxo_nat` ganhou `boas_vindas_wamid` (keyword-only), que separa dois modos:

* **preenchido** — a boas-vindas JÁ saiu; a função não envia nada, só ADOTA o lead criando o
  estado em `aguardando_resposta`. É o que `send_welcome_to_new_lead` passa agora.
* **`None`** — modo antigo, a NAT envia. Sem chamador em produção; sobrevive para os testes.
  Comportamento inalterado, travado pelo caso 4 do `test_nat_duplicata`.

O wamid do envio que já ocorreu fica em `nat_flow_state.ultimo_wa_message_id`. Não exige
coluna nova e não colide com a trava de reentrega: id de mensagem é único global na Meta e
este é de **outbound** — nenhum webhook de inbound chega com ele.

### A prova

`test_nat_duplicata.py`, caso 1, roda `send_welcome_to_new_lead` inteiro com a NAT ligada e
conta o que foi para a Meta. Com a correção revertida à mão:

```
📤 NAT enviou 'nat_boasvindas' para 5583999998888 (template, janela fechada)
FALHOU: 2 mensagens foram para a Meta, esperava 1.
        boas-vindas=1  nat_template=1  texto=0  interativo=0
```

Com a correção: `envios à Meta=1`, 1 linha em `messages`, estado em `aguardando_resposta`.

> O dublê de banco teve que responder **por entidade**, não por ordem de consulta. A primeira
> versão respondia por ordem, e o caminho com bug esgotava a fila e morria num "contato não
> existe" antes de enviar — passava verde pelo motivo errado.

### Decisão nova: fora do horário a NAT não adota

Medido em 11/08, últimos 30 dias:

```
boas-vindas do funil 18535   FORA de 09-19h seg-sex: 109 (55%)   dentro: 88
cliques em nat_button_events FORA: 60 (64%)                      dentro: 34
```

A `sync_job` roda 24/7 e a boas-vindas sai junto. Com a Fase 1, o lead **já está com os dois
botões na mão** quando `iniciar_fluxo_nat` roda — o que invalida a premissa do risco declarado
no sprint ("não recebe nada, então não há dano ao lead").

Decisão do Álefe: **fora de 09h-19h seg-sex o lead não entra no fluxo** (`return None`). As
alternativas eram piores — `aguardando_horario` viraria beco (sem handler que drene, o clique
cairia em "clique fora da etapa" e sumiria para sempre), e adotar assim mesmo faria a NAT
prometer ligação às 22h de um sábado.

Sem estado, o clique noturno segue o caminho que já existe: `messages`, `nat_button_events` e
a notificação de "nova mensagem" ao SDR dono. Atendimento humano.

**Consequências:**

* `aguardando_horario` **deixa de ser risco em produção** — nenhum caminho a alimenta mais.
  A etapa fica com 0 linhas.
* Cobertura cai para **~45%** dos leads elegíveis (~3/dia). Quem recebeu a boas-vindas à noite
  fica fora do fluxo em definitivo, inclusive se clicar às 09h do dia seguinte.

### Docstring do `nat_guard` corrigida

Dizia "só CRIA a função, NÃO está plugada em lugar nenhum". Está plugada em
`nat_flow.py:340` e `nat_sender.py:94` desde o sprint dos Blocos 2-3-4.

---

## Fase 2 — saída de `reagendado`

Clique em "Prefiro outro horário" passa a **notificar o SDR dono**, depois de enviar o
`nat_outro_horario` e depois da transição (mesma ordem de `processar_texto`: a mensagem já
está com o lead, o que pode falhar é o efeito colateral).

```
título  Reagendar: Ana Prado — +55 83 99999-8888
corpo   +55 83 99999-8888 · Psicologia · pediu outro horário — ainda não disse quando
```

Quando o lead informa o período, o **mesmo aviso é atualizado** (não é criado um segundo):

```
título  Reagendar — pode ser de manhã, antes das …: Ana Prado — +55 83 99999-8888
corpo   +55 83 99999-8888 · Psicologia · prefere: "pode ser de manhã, antes das 10h"
```

**Por que atualizar e não criar outro.** Os dois falam do mesmo pedido, para a mesma pessoa, e
o primeiro diz estritamente *menos*. Dois itens no sino poriam o SDR diante de um aviso
obsoleto e um atual sem nada que os distinga, e agir pelo obsoleto é ligar sem saber o horário
que o lead acabou de informar. (O `nat_sla` cria um aviso por degrau de propósito — mas lá
cada evento vai para uma **pessoa diferente**.)

* `is_read` volta para `False` — é o que faz o aviso reaparecer em negrito no sino. Sem o
  reset, quem já tinha lido nunca saberia do período.
* `created_at` **não** é tocado: ele responde "desde quando este lead espera".
* `ref` continua apontando para o clique.

Título **nunca** diz "Ligar agora" — um título parecido com o da transferência faria o SDR
ligar na hora, o oposto do que o lead pediu. Travado por assert.

Sem SDR → gestão (id=2), mesmo fallback da transferência. `_destinatario_da_transferencia`
virou **`_destinatario_do_aviso`**, já que serve aos dois avisos.

Só o **primeiro** texto conta, como já era antes da sprint.

---

## Fase 3 — `assumir` encerra o fluxo

`POST /api/nat/{wa_id}/assumir` passa a gravar `etapa = encerrado`, no mesmo savepoint do
carimbo (é a mesma escrita lógica: "este lead é do humano agora").

Antes, o lead ficava em `aguardando_ligacao` para sempre — `encerrado` era constante morta em
`models.py:360`. Todo clique posterior caía em "clique fora da etapa" e sumia, com um humano
já conduzindo a conversa.

Depois de `encerrado`, os três caminhos já faziam a coisa certa; o que faltava era o lead
**chegar** ao estado:

```
↩️  NAT SLA: já saiu de aguardando_ligacao (está em encerrado) — nada a fazer
↩️  NAT: clique 'NAT_SIM' fora da etapa esperada (lead está em encerrado) — ignorado
↩️  NAT: texto em encerrado — nenhuma transição
```

**Frontend:** não quebra e não muda. `conversations/page.tsx` lê só `pode_assumir`,
`assumido_por`, `assumido_por_nome` e `assumido_em` — **nunca `etapa`**. O botão some pelo
mesmo motivo de antes (`pode_assumir` exige `assumido_por is None`) e o selo verde aparece.

**Ordem que passou a importar:** a checagem de idempotência (`assumido_por is not None` → 200)
tem que continuar vindo **antes** da checagem de etapa. Na segunda chamada a etapa já não é
`aguardando_ligacao`, e inverter trocaria o 200 idempotente por um 409. Documentado no código.

---

## Fase 4 — kill switch por HTTP

```
GET   /api/nat/config     lê o estado       admin
PATCH /api/nat/config     liga/desliga      admin
```

Campos: `nat_enabled`, `nat_start_at`, `max_envios_hora`. PATCH puro.

A resposta traz **`atuando`**, que é o que vale de fato: a NAT só age com `nat_enabled=true`
**e** `nat_start_at` preenchido.

### ⚠️ `nat_start_at` é UTC

`date_parse.parse_datetime` grava `register_date` **naive em UTC**. Conferido no banco em
11/08:

```
max(register_date) = 14:53:07     now() UTC = 15:18     now() SP = 12:18
```

Todo o resto do fluxo é horário de São Paulo (`_agora_sp`, horário comercial,
`messages.timestamp`), **este campo não**. Escrever o relógio de SP poria o corte **3 horas no
passado** e deixaria entrar todo lead registrado nas 3h anteriores — retroativo, contra a
decisão nº 2. Sem exceção, sem erro visível.

| entrada | resultado |
|---|---|
| `"agora"` | servidor resolve em UTC — **caminho da ativação** |
| `"2026-08-11T12:00:00-03:00"` | → `15:00:00` UTC |
| `"2026-08-11T12:00:00"` | **422** — sem fuso é ambíguo |
| `null` | apaga o corte (desligamento duro) |

O GET devolve `nat_start_at` **e** `nat_start_at_sp` lado a lado: conferir o corte de relance
é a única defesa contra ativação retroativa.

### Três recusas deliberadas

* **Ligar sem `nat_start_at` → 422.** Painel diria LIGADA, guard bloquearia 100% dos leads.
* **Campo desconhecido → 422.** `{"nat_enable": false}` aceito em silêncio devolveria 200 com
  a NAT ligada.
* **`max_envios_hora` não-inteiro ou negativo → 422.** `0` é aceito (estrangulamento).

### Desligar nunca é barrado

Nenhuma validação roda no caminho de `nat_enabled: false`, e o `nat_start_at` **não** é
apagado junto. Comando exato em `COMANDOS_UTEIS.md` § "NAT — kill switch".

### Log de quem alterou

```
🎛️  NAT CONFIG alterado por Álefe Lins (id=1) em 11/08/2026 12:21:37 (SP):
    nat_enabled: False → True, nat_start_at: None → '2026-08-11T15:21:37' | atuando=True
```

`journalctl -u cenat-backend | grep "NAT CONFIG"`.

**Limitação aceita:** o "quando" está persistido (`nat_config.updated_at`), o **"quem" só está
no journal** — `nat_config` não tem coluna de autor e criá-la exigiria migração, fora do
escopo. O `auto_welcome_config` tem `updated_by_name`; a paridade é um `ALTER TABLE` de uma
linha quando for aprovado.

`get_current_admin` teve a mensagem de 403 generalizada — dizia "podem gerenciar templates" e
agora também protege o kill switch.

---

## Fase 5 — testes

### Os 8 itens do sprint

| # | verificação | onde |
|---|---|---|
| 1 | boas-vindas → 1 envio, `aguardando_resposta` | `test_nat_duplicata` 1-2, `test_nat_caminho_completo` 1 |
| 2 | "Sim" → `nat_sim` → texto → transferência + notificação + SLA | `test_nat_caminho_completo` 2-3 |
| 3 | "outro horário" → `nat_outro_horario` + notificação | `test_nat_reagendado` 1-3 |
| 4 | `assumir` → `encerrado`, SLA cancelado | `test_nat_sprint3` 12b, `test_nat_caminho_completo` 4 |
| 5 | clique após `encerrado` → ignorado sem erro | `test_nat_sprint3` 12b, `test_nat_caminho_completo` 5 |
| 6 | `PATCH /config` sem token → 401, não-admin → 403 | `test_nat_config_api` 1-2 |
| 7 | guard: fora do 18535, sem SDR, `register_date` < corte → bloqueado | `test_nat_guard` 3-7 |
| 8 | regressão completa | abaixo |

O item 2 só estava coberto em pedaços — daí o `test_nat_caminho_completo.py`, que atravessa o
Cenário 1 inteiro com **o mesmo lead, o mesmo banco e o mesmo estado**, cobrindo a emenda
entre as peças. Só as chamadas à Cloud API e à Exact são substituídas.

```
Total na travessia: 3 mensagens à Meta (1 boas-vindas + 2 da NAT),
1 notificação, 1 SLA agendado, 1 cancelado.
```

### Regressão — 10 suítes

```
test_nat_caminho_completo   rc=0   Cenário 1 atravessa inteiro
test_nat_duplicata          rc=0   5/5
test_nat_reagendado         rc=0   5/5
test_nat_config_api         rc=0   8 grupos, 30 asserções
test_nat_flow               rc=0   13/13
test_nat_guard              rc=0   9/9
test_nat_sprint3            rc=0   TODOS (inclui o novo 12b)
test_observabilidade_envio  rc=0   TODOS
test_welcome_guardrail      rc=0   15/15
test_parse_datetime         rc=0   TODOS
```

---

## Riscos que entram em produção assim mesmo

1. **O teto por hora não conta a entrada do lead.** A boas-vindas é gravada com
   `nat_etapa=NULL` (quem escreve o marcador é só o `nat_sender`), então `max_envios_hora`
   protege as respostas da NAT, não as entradas. Não marquei de propósito: marcar faria a
   boas-vindas das 22h aparecer como envio da NAT fora do horário e disparar o critério de
   aborto por um envio que não é da NAT. Com ~3 leads/dia adotados, o teto não aperta.
2. **Cobertura de ~45%** — consequência aceita da decisão de não adotar fora do horário.
3. **Varredura O(n) de `exact_leads`** a cada envio da NAT (`nat_guard.py:167-171`). Tolerável
   no volume atual, vira problema em pico. Registrado, não corrigido.
4. **`delivery_health` com `MAX_FALHAS_PARA_VOLTAR = 0`** — o vigia está mudo desde 30/07.
   Verificado, não corrigido nesta sprint.
5. **Bloco 6 e IA ausentes** — o lead que pede outro horário depende de ação humana. É o que
   a Fase 2 tornou possível: antes não dependia de ninguém, porque ninguém sabia.
6. **`sem_contato` segue constante morta** — só o botão "não consegui contato" do Bloco 6 a
   atribuiria.

---

## Fase 6 — ativação

_Pendente. Requer restart aprovado e smoke do caminho comum._
