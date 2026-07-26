# Sprint NAT — Blocos 2, 3 e 4: máquina de estados, envio unificado e horário comercial

**Data:** 26/07/2026
**Branch:** `feat/nat-blocos-2-3-4-20260726` (sem merge — decisão do Álefe)
**Antecedentes:** `AUDITORIA_NAT_20260725.md`, `RECON_NAT_FASE0_20260725.md`,
`SPRINT_NAT_BLOCOS_0_1_20260726.md`

O núcleo do fluxo. **A NAT continua desligada** — nada disto entra em operação.

---

## 1. `nat_flow_state` — onde cada lead está

Migração `backend/migrate_nat_flow_state.py` **rodada**. Uma tabela nova, nenhuma existente
alterada. 0 linhas.

```sql
CREATE TABLE nat_flow_state (
    id BIGSERIAL PRIMARY KEY,
    contact_wa_id VARCHAR(20) NOT NULL UNIQUE,
    exact_lead_id INTEGER,
    sdr_user_id INTEGER,
    etapa VARCHAR(30) NOT NULL,
    tentativas_contato INTEGER NOT NULL DEFAULT 0,
    horario_preferencial TEXT,
    ultimo_wa_message_id TEXT,
    transferido_em TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT nat_flow_state_etapa_valida CHECK (etapa IN (
        'aguardando_horario','aguardando_resposta','aguardando_motivacao',
        'aguardando_ligacao','reagendado','sem_contato','encerrado'))
);
CREATE INDEX idx_nat_flow_etapa ON nat_flow_state(etapa);
```

- **`contact_wa_id` UNIQUE** — a chave real: todo roteamento entra pelo `wa_id` do webhook.
  Sem ela, uma reentrega da Meta criaria dois estados e o fluxo passaria a depender de qual
  linha fosse lida primeiro.
- **`CHECK` em `etapa`** — a máquina é fechada; gravar etapa inexistente é bug, e é melhor o
  banco recusar do que descobrir com o lead parado num estado que nenhuma transição consome.
  `sem_contato` (Bloco 6) já entra para evitar um `ALTER` numa tabela que a essa altura já
  estará sendo escrita em produção.
- **Sem FK** — a tabela é escrita de dentro do webhook e não pode ser a causa de um lote de
  mensagens se perder. Mesma regra de `nat_button_events`.

As 7 etapas também existem como constantes em `models.py`, e um teste confere que a lista bate
com o CHECK — divergir faz o INSERT falhar no banco, que é o comportamento desejado.

---

## 2. Horário comercial — `nat_guard.dentro_horario_comercial()`

```python
def dentro_horario_comercial(quando: datetime | None = None) -> bool
```

09h–19h, **segunda a sexta**, no fuso de SP. `quando` explícito é o que torna a função testável
sem mock de relógio.

**Mora em `nat_guard.py`, não em módulo próprio**, porque responde à mesma pergunta que
`nat_pode_atuar`: "a NAT pode agir agora?". Separar espalharia a resposta por dois arquivos e
quem fosse auditar a segurança do fluxo teria que descobrir que existe um segundo lugar.

**Não é chamada de dentro de `nat_pode_atuar`**, de propósito: o horário decide o *caminho*
(envia agora vs. enfileira), enquanto `nat_pode_atuar` decide se pode haver ação. Fundi-las
faria "fora do horário" virar bloqueio, e o lead que chega às 20h seria **descartado** em vez
de enfileirado para as 09h.

Bordas cobertas: 08h59 fora · 09h00 dentro · 18h59 dentro · **19h00 em ponto fora** · sábado e
domingo fora em qualquer hora.

`datetime` *aware* é convertido para SP; *naive* é assumido **já em SP**, que é como
`messages.timestamp` é gravado. Assumir UTC no naive jogaria toda decisão 3h para frente e a
janela viraria 06h–16h SP na prática, sem nenhum erro visível. O teste cobre isso comparando
12h00 UTC (= 09h00 SP, dentro) com 11h59 UTC (= 08h59 SP, fora).

**Limitação conhecida: feriado não é tratado.** Em feriado nacional a NAT considera horário
comercial normal e dispara. Precisa de calendário de feriados, que não existe no projeto.

---

## 3. Envio unificado

### 3a. `send_template_message` aceita payload de botão

Parâmetro novo `button_payloads: list`, que monta os componentes `sub_type: "quick_reply"` por
índice. `None` numa posição deixa aquele botão com o payload padrão da Meta.

**Não-regressão garantida por teste:** sem `button_payloads`, o corpo enviado é idêntico ao de
hoje — inclusive a ausência da chave `components` quando não há parâmetros. A boas-vindas em
produção passa por essa função.

### 3b. `nat_copy.py` — texto e payloads

Os corpos estão **verbatim** como aprovados no WABA. Isso serve a duas coisas: o texto livre
tem que soar igual ao template (senão a conversa muda de voz por um detalhe técnico que o lead
não vê), e o teste de drift compara os dois.

Payloads: `NAT_SIM` e `NAT_OUTRO_HORARIO`, valores literais. Não podem ser genéricos tipo
`"SIM"` porque o Cenário 2 (`nat_reativacao_09h`) tem **os mesmos rótulos de botão** e vai
precisar dos seus próprios.

**Títulos de botão em mensagem livre** (limite de 20 caracteres da Cloud API). Os aprovados não
cabem; corte cego deixaria rótulo mutilado na tela do lead, então foram encurtados à mão:

| aprovado no template | livre (interactive) |
|---|---|
| `Sim, Posso conversar agora` (26) | **`Sim, posso agora`** (16) |
| `Prefiro outro horário` (21) | **`Outro horário`** (13) |

**Formação ausente em `nat_sim`** (falta em ~49% dos leads). A frase aprovada é
`"Verifiquei em sua aplicação que sua formação é em {{2}}."` A solução foi **remover a frase
inteira**, não substituí-la:

> Perfeito, Ana 🌻
> Fico feliz em falar com você!
> Gostaria de entender melhor: o que despertou seu interesse na Pós-Graduação em Psicologia? Me conta um pouco mais 🙏

Qualquer preenchimento genérico ("sua área", "uma área ligada a…") seria a NAT afirmando algo
sobre a formação do lead sem saber — e o lead percebe. Sem a frase, o texto continua íntegro:
"Fico feliz em falar com você!" emenda naturalmente em "Gostaria de entender melhor:".

**Consequência assumida:** no caminho de *template* (janela fechada) não dá para fazer o mesmo,
porque o corpo aprovado é fixo. Nesse caso `parametros_template` devolve `None` e a NAT
**não envia**, logando o motivo. É falha fechada: prefere-se não enviar a afirmar um dado que
não temos. Na prática o caso não ocorre — `nat_sim` só sai depois de um clique, e clique abre a
janela de 24h.

### 3c. `send_nat_message` — `backend/app/nat_sender.py`

```python
async def send_nat_message(contact_wa_id: str, etapa: str, db, **vars) -> bool
```

Módulo separado de `nat_flow.py`: aqui mora **como a NAT fala**, lá mora **quando ela fala e
para onde o lead vai depois**. Juntar faria a máquina de estados carregar credencial de canal,
janela de 24h e formato de payload da Meta — e qualquer mudança na Cloud API viraria mudança no
fluxo.

Decide o formato sozinho, pela janela de 24h (última mensagem **inbound** do contato; mensagem
nossa não reabre janela nenhuma):

| janela | etapa com botões | etapa sem botões |
|---|---|---|
| aberta | `interactive` com títulos truncados | texto puro |
| fechada | template + `button_payloads` | template |

Sem inbound algum → janela fechada. É o caso do lead novo, e é por isso que a boas-vindas sai
por template.

**Nada sai daqui sem `nat_pode_atuar` liberar** — é a primeira coisa que a função faz, antes de
qualquer coisa que custe rede. Falha fechada: qualquer exceção devolve `False`.

O canal vem de `contact.channel_id` e, na falta, de `auto_welcome_config.channel_id` — **só
leitura**, a config não é alterada. É onde o WABA do projeto está configurado; duplicar isso em
`nat_config` criaria duas fontes de verdade para a mesma credencial.

---

## 4. Máquina de estados — `backend/app/nat_flow.py`

| gatilho | origem | ação | destino |
|---|---|---|---|
| lead entra, dentro do horário | — | envia `nat_boasvindas` | `aguardando_resposta` |
| lead entra, fora do horário | — | **nada** | `aguardando_horario` |
| payload `NAT_SIM` | `aguardando_resposta` | envia `nat_sim` | `aguardando_motivacao` |
| payload `NAT_OUTRO_HORARIO` | `aguardando_resposta` | envia `nat_outro_horario` | `reagendado` |
| texto qualquer | `aguardando_motivacao` | envia `nat_confirma_transferencia` | `aguardando_ligacao` |
| texto qualquer | `reagendado` | grava `horario_preferencial` | `reagendado` |
| qualquer outro | qualquer | nada, só loga | inalterado |

Sem IA: **qualquer** texto em `aguardando_motivacao` avança. O refino é Bloco 8.

### Idempotência

Antes de agir, o `wa_message_id` que chegou é comparado com
`nat_flow_state.ultimo_wa_message_id`. Igual → já processado: retorna sem enviar e sem mexer no
estado.

E a ordem importa: **o estado só avança depois do envio dar certo**. Se a Meta recusar, o lead
permanece na etapa anterior e nada afirma uma mensagem que ele nunca recebeu. Vale também no
início do fluxo — se a boas-vindas não sai, **nenhum estado é criado**.

### Clique fora da etapa

Não faz nada. Um "Sim" clicado quando o lead já está em `aguardando_ligacao` é ruído (rolou a
conversa e clicou no botão antigo); reprocessar mandaria o fluxo para trás e reenviaria uma
mensagem que ele já recebeu.

### Roteamento por payload, com texto como fallback

O mecanismo principal é o `button_payload`. Existe um fallback por texto do botão, mas ele **só
age quando o lead está em `aguardando_resposta`** — a etapa é que elimina a ambiguidade, não o
texto. Ele serve aos cliques que cheguem sem payload (template disparado antes desta sprint,
quando o payload ainda não era fixado no envio).

### Ligação no webhook

`processar_clique` / `processar_texto` entram **depois** da persistência do evento (o registro
do clique não pode depender do fluxo dar certo) e dentro de `begin_nested()`, com `try/except`.
Com a NAT desligada nada disto age; se um dia agir e falhar, a mensagem do lead já está salva e
o lote segue.

---

## 5. Ponto de entrada — a única mudança em código de produção

No fim de `send_welcome_to_new_lead` (`exact_spotter.py`), após o envio bem-sucedido e depois
do contato existir (`iniciar_fluxo_nat` precisa dele para checar `assigned_to`):

```python
try:
    async with db.begin_nested():
        from app.nat_flow import iniciar_fluxo_nat
        await iniciar_fluxo_nat(lead_row if lead_row is not None else lead_data, db)
except Exception as e:
    print(f"⚠️  NAT: fluxo não iniciado para {phone}: {type(e).__name__}: {e}")
```

**É inerte com a NAT desligada** — `iniciar_fluxo_nat` chama `nat_pode_atuar` como primeira
instrução e sai em `nat_enabled=false`. Confirmado no teste 4 e observado rodando o guardrail
da boas-vindas: o caso 12 (automação enviando normalmente) loga `🔒 NAT não iniciou fluxo` e
segue, com os 15/15 intactos.

**Detalhe que muda o resultado:** passa `lead_row` (o `ExactLead`), não `lead_data`. A trava de
data lê `register_date`, que o dict montado pelo sync **não carrega** — com o dict,
`nat_pode_atuar` bloquearia sempre por "register_date ausente". Falha fechada correta, mas pelo
motivo errado: a NAT nunca sairia do lugar depois de ligada, e o log culparia o dado do lead.

Dentro de `begin_nested()` porque falha aqui não pode desfazer o carimbo de `welcome_status`
nem o registro da mensagem que **já saiu** para o lead.

---

## 6. Testes — `backend/test_nat_flow.py`, 13/13

Banco falso, nenhum envio, nada gravado. A única saída de rede é o caso 13 (GET read-only na
definição dos templates); se a rede falhar ele avisa em vez de reprovar.

```
 1. 08h59 fora | 09h00 dentro | 18h59 dentro | 19h00 fora
    12h00 UTC = 09h00 SP -> dentro | 11h59 UTC = 08h59 SP -> fora
 2. sab 14h fora | dom 10h fora | sex 18h59 dentro | seg 09h00 dentro
 3. fora do horario            -> aguardando_horario   envios=0
 4. NAT desligada              -> etapa=None  envios=0  estados criados=0
 5. NAT_SIM em aguardando_resposta  -> aguardando_motivacao (enviou nat_sim)
 6. mesmo wa_message_id reentregue  -> envios=0, etapa intacta
 7. NAT_SIM em aguardando_ligacao   -> ignorado, etapa intacta
 8. texto em aguardando_motivacao   -> aguardando_ligacao, transferido_em marcado
 9. texto em aguardando_resposta    -> ignorado, envios=0
10. janela ABERTA  -> interactive, botoes=['Sim, posso agora', 'Outro horário']
    janela FECHADA -> template, button_payloads=['NAT_SIM', 'NAT_OUTRO_HORARIO']
    etapa sem botoes, janela aberta -> texto puro
11. nat_sim sem formacao -> frase removida, sem placeholder e sem buraco
12. send_template_message sem button_payloads -> corpo IDENTICO ao de hoje
    sem parametros -> sem chave 'components'
    com button_payloads -> body + quick_reply index 0 e 1
13. drift: nenhum — 4 corpos e os botoes de nat_boasvindas batem com a Meta
```

Regressão das sprints anteriores: `test_welcome_guardrail.py` **15/15**,
`test_nat_guard.py` **9/9**.

---

## 7. Drift de copy

**Nenhuma divergência.** Os 4 corpos em `nat_copy.py` e os dois botões de `nat_boasvindas`
batem exatamente com o que está aprovado no WABA hoje.

O caso 13 fica no suite justamente para o dia em que alguém editar o template no WhatsApp
Manager sem mexer no código — é assim que a cópia apodrece em silêncio.

---

## 8. Estado de produção

| item | estado |
|---|---|
| Mensagem enviada a lead real | **nenhuma** |
| Serviço reiniciado | **não** — o código desta sprint **não está no ar** |
| Sync do Exact rodado manualmente | não |
| NAT | **desligada** (`nat_enabled=False`, `nat_start_at=None`) |
| `nat_flow_state` | 0 linhas |
| `auto_welcome_config` | **não alterada** (`enabled=true`, `18535,18537,25588`) |
| Merge | **não feito** — decisão do Álefe |

A migração criou a tabela, mas nada a escreve enquanto o serviço não for reiniciado — e, mesmo
depois, nada escreve enquanto a NAT estiver desligada.

---

## 9. O que falta para a NAT rodar de fato

Fora do escopo desta sprint, mas é o que separa o que existe de um fluxo em operação:

- **Notificação ao SDR, escrita de estágio no Exact, timeline, SLA e escalonamento** (Bloco 5).
  Hoje o lead chega em `aguardando_ligacao` e **ninguém é avisado**.
- Botão "não consegui contato", `nat_recuperacao_sdr`, retry de 10 min (Bloco 6).
- Agendador `nat_scheduled_actions` — sem ele, `aguardando_horario` é uma fila **que ninguém
  varre**: o lead que chega às 20h fica lá parado (Bloco 7).
- IA para interpretar motivação e período (Bloco 8).
- Cenário 2 inteiro: `nat_fora_horario`, `nat_reativacao_09h`.
- **O incidente de entrega aberto desde 23/07.** Nada disto é observável em produção enquanto
  as mensagens não voltarem a ser entregues.
