# SPRINT 6 — autoria, higiene do disparo e o follow do agente

**Data:** 01/09/2026. **Origem:** `RECON_FOLLOWS_HUMANO_IA_20260901.md`.
**Commits:** 6, nesta ordem. **Testes novos:** 5 arquivos, ~150 asserções.
**Migrações rodadas em produção:** 2, ambas aditivas.

> **Nada novo saiu para lead nenhum.** O follow do agente subiu **desligado**, e sem
> template. O que mudou de comportamento hoje foi o disparo em massa (S6-2), que passou a
> pular gente, e a assinatura do `tentativa_contato` (S6-3), que parou de mentir.

---

## O que cada passo consertou

| # | Defeito medido | O que subiu | Efeito hoje |
|---|---|---|---|
| **1** | 517 templates humanos em 8 dias e **zero** forma de dizer quem mandou qual | `messages.sent_by` + `messages.template_name` | nenhum — colunas novas, sem backfill |
| **2** | 8 de 9 leads que disseram "não" continuaram recebendo, até **6 toques** depois | `app/higiene_disparo.py`, 3 regras | **32% dos envios em massa** passam a ser pulados |
| **3** | **43 de 82** (52%) `tentativa_contato` assinados com o nome do **curso** | default lê o corpo + tipo `sdr_logado` | a próxima campanha assina certo |
| **4** | 39 conversas do agente caladas sem ninguém tocar; **18** paradas em etapa ativa | `follow_20h` atrás de flag | nenhum — **desligado** |
| **5** | ano de conclusão derruba **37,5%** de quem já conversava | missão de `aguardando_ano` | o agente para de insistir |
| **6** | duas etapas homônimas na Exact; `nat_contact_attempts` com 0 registros | **registro, sem implementação** | nenhum |

---

## 1. `messages.sent_by` e `messages.template_name`

**CHECKPOINT aprovado e EXECUTADO** em 01/09, `migrate_message_autoria.py`.

```sql
-- Fase A: transação curta, lock_timeout 3s
ALTER TABLE messages ADD COLUMN IF NOT EXISTS sent_by       INTEGER;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS template_name VARCHAR(512);
ALTER TABLE messages ADD CONSTRAINT messages_sent_by_fkey
      FOREIGN KEY (sent_by) REFERENCES users(id) NOT VALID;
-- Fase B: AUTOCOMMIT
ALTER TABLE messages VALIDATE CONSTRAINT messages_sent_by_fkey;
CREATE INDEX CONCURRENTLY idx_messages_sent_by       ON messages (sent_by)       WHERE sent_by       IS NOT NULL;
CREATE INDEX CONCURRENTLY idx_messages_template_name ON messages (template_name) WHERE template_name IS NOT NULL;
```

```
BEFORE  messages: 32 857 linhas, 17 MB, PostgreSQL 14.24
        sent_by: não existe · template_name: não existe
AFTER   coluna sent_by integer nullable=YES
        coluna template_name character varying nullable=YES
        índice idx_messages_sent_by       indisvalid=True
        índice idx_messages_template_name indisvalid=True
        FK messages_sent_by_fkey convalidated=True
        0 linhas com autoria preenchida (esperado — sem backfill)
```

Preenchido em **seis** pontos: `routes.send_text` · `routes.send_template` ·
`routes.send_media` · `exact_routes.bulk_send_template` · `nat_sender.enviar_nat` ·
`exact_spotter` (boas-vindas).

### A armadilha que justifica `app/autoria.py`

`bulk_send_template` declara `current_user: User = Depends(get_current_user)` **na
assinatura**, e é chamada de dois jeitos:

```
HTTP (o Hub)                -> o FastAPI resolve: `current_user` é User
main.py:238 (job agendado)  -> chamada Python direta: `current_user` é o objeto `Depends`
```

O segundo caso nunca estourou porque `getattr(x, "id", None)` devolve `None` sem reclamar —
foi por acidente feliz que `_silenciar_agente_apos_envio_manual` sempre funcionou. Com
`sent_by` sendo FK, `current_user.id` direto derrubaria o disparo agendado no meio do lote.
`quem_enviou` usa `isinstance` e fecha as duas portas.

### `sent_by IS NULL` é resposta, não lacuna

Três casos legítimos, cada um distinguível por outra coluna:

| Caso | Como se identifica |
|---|---|
| agente | `nat_etapa IS NOT NULL` |
| disparo agendado | `template_name IS NOT NULL` e `nat_etapa IS NULL` |
| boas-vindas automática | `wa_message_id` casa com `exact_leads.welcome_wamid` |

**Sem backfill, e isso é decisão.** O dado nunca existiu no banco. Derivar de
`contacts.assigned_to` (dono na Exact, não remetente) ou da assinatura no corpo — que está
errada em 52% dos casos (§3) — produziria um número que **parece** medição e não é.

---

## 2. Higiene do disparo

Extensão do filtro de 28/08. Eram três perguntas e só uma estava sendo feita.

| Regra | Janela | Vale no individual? |
|---|---|---|
| **(a)** recusa explícita do lead | 30 dias | **sim** |
| **(b)** já recebeu ≥ 3 templates | 7 dias | não |
| **(c)** etapa ativa do agente *(já existia)* | — | não |

### Por que (a) vale no individual e (b) não

O filtro de 28/08 dispensa o individual porque *"o SDR escolheu aquela pessoa e apertou
enviar, e essa é decisão dele"*. Vale para o **ritmo**: quem olha a thread vê os toques.

Não vale para a recusa, e a diferença é de fato, não de grau. Quem aperta enviar na tela de
Automações está olhando uma **lista de leads da Exact** — o "não" não está ali. Ele não está
decidindo ignorar o pedido; **ele não tem como saber que houve um**. A saída continua na tela
certa: quem precisa responder a alguém que recusou faz isso pela tela de Conversas
(`/send/text`), onde o "não" está na frente dele. Foi exatamente o que o SDR fez com a
Michele em 26/08 — e aquilo estava certo. O que errou foi a lista voltar por cima.

### O padrão de recusa foi validado contra o corpus, não imaginado

Rodado sobre **todo** o inbound do banco (6 meses): **72 mensagens casam, e as 72 são recusa
de verdade**. O que ficou de fora foi decidido pelos falsos positivos que a medição mostrou:

| Fora | Por quê |
|---|---|
| `não há mais interesse` | **está dentro do nosso próprio template** `ainda_ha_interesse` ("Na ausência de retorno considerarei que não há mais interesse"). Todo lead que reencaminha a nossa mensagem viraria "recusa" para sempre. Custo de tirar: 1 recusa genuína em 6 meses |
| `não quero` sozinho | *"Não quero perder as aulas"* (seguido de *"Podem enviar o link?"*) é lead comprando. *"não quero falar por telefone"* e *"Não quero informação por ligação — quero pelo WhatsApp"* são preferência de **canal**: bloquear WhatsApp ali é o avesso do pedido |
| `desisti` **solto** | entrou, mas exigindo que não venha depois de "não" — *"não desisti"* é o contrário |

> **Quem mexer no padrão rode a medição de novo antes de commitar.** Falso positivo aqui não
> faz barulho: some um lead real de todas as campanhas por 30 dias, e ninguém percebe.

### Impacto medido, aplicando as regras retroativamente à janela do recon

| Canal | Enviados | Barrados (recusa) | Barrados (teto) | **Total** |
|---|---:|---:|---:|---:|
| em massa | 443 | 14 | 128 | **142 (32%)** |
| individual | 74 | 4 | — | 4 |

**O que o teto corta é a parte morta.** Os 128 barrados produziram **10 respostas (7,8%)**;
os 301 que sobrevivem produziram **59 (19,6%)** — 2,5× a taxa. 75 dos 136 leads são tocados
pela regra.

O teto conta os templates **do agente junto**, de propósito: o lead não distingue quem
mandou, ele conta mensagens.

### O contrato do retorno

`skipped_nat` **não foi redefinido** — continua sendo só conversa ativa, para não mudar em
silêncio o número que a tela já mostra e que o `result` dos agendados já gravou. O total novo
é `skipped_total`; a quebra é `skipped_por_regra`. A tela deixou de afirmar um motivo só.

---

## 3. O `{{2}}` do `tentativa_contato`

**Causa confirmada no dado, não deduzida.** Em todo envio quebrado o `{{2}}` e o `{{3}}`
trazem a **mesma string**:

| `{{2}}` (quem fala) | `{{3}}` (o curso) | n |
|---|---|---:|
| Saúde Mental e Mulheridades | Saúde Mental e Mulheridades | 11 |
| PsicologiaEscolar | PsicologiaEscolar | 9 |
| Transtorno do Espectro Autista (TEA) | Transtorno do Espectro Autista (TEA) | 7 |
| **Thobias** | Grupos e Oficinas em Saúde Mental | 14 ✅ |

Que é exatamente `automacoes/page.tsx:selectTemplate`: `i === 1 -> lead_course` e
`i === 2 -> lead_course`, para **qualquer** template. O chute não era só errado: **era
invisível** — quem não abrisse o dropdown não tinha como saber que a tela decidira por ele.

**Duas metades:**

* **Tela** — o default deixa de olhar a **posição** e passa a ler o **corpo**. A frase
  imediatamente antes do `{{n}}` diz se ali vai uma pessoa (`é o `, `aqui é `, `sou a `,
  `consultora `). É evidência do template, não suposição sobre a ordem das variáveis. O
  preview passa a mostrar o **nome real** de quem está logado — é a única chance de alguém
  ler *"é o Thobias do CENAT"* e conferir antes de a mensagem sair.
* **Backend** — mapeamento novo `sdr_logado`. **Não reusa `sdr_name`**, que resolve
  `exact_leads.sdr_name` — o **dono** do lead, outra pessoa (4 496 leads são da Victória,
  2 091 do Thobias). Um template que diz "tentei falar com você" assinado pelo dono do lead
  mente quando quem tentou foi outro.

`nome_de_quem_enviou` **nunca** devolve vazio: `{{n}}` em branco é `#131008` e a mensagem
inteira não sai. Sem sessão (disparo agendado) cai em `autoria.SDR_PADRAO = "Thobias"` — uma
linha visível no código, não uma configuração escondida.

---

## 4. SPRINT D — o follow de 20h

**Subiu desligado.** `follow_enabled=false`, `follow_template=NULL`.

```
migrate_follow_20h.py
AFTER — nat_config: id=1 follow_enabled=False follow_template=None
```

### O N = 20h não é palpite

| Silêncio até o follow | N | Taxa de resposta |
|---|---:|---:|
| **20–24 h** | 124 | **13,7%** |
| 24–48 h | 58 | 10,3% |
| 48–72 h | 127 | 7,9% |

A operação humana manda hoje com **45,7 h** de mediana — no balde de 7,9%. E 20 h fica
**abaixo da janela de 24 h da Meta**, então o envio ainda pode sair como texto livre em vez
de template pago.

**Um só.** A taxa por *ordem* do follow cai **17,4% → 11,7% → 7,8% → 6,8% → 0%**. Se um dia
houver um segundo, que seja medido antes de virar padrão.

### A idempotência que adiou o sprint já existia

```sql
uq_nat_sched_pendente_por_contato UNIQUE (kind, contact_wa_id) WHERE status = 'pendente'
```

E `nat_scheduler.agendar` **cancela o pendente do mesmo (kind, contato) antes de inserir**.
Dois inbounds seguidos reagendam **um** follow. `_proxima_acao` já pega a ação com
`FOR UPDATE SKIP LOCKED`. **Nada novo foi construído para isso.**

### Agendamento e cancelamento

Agendado nos **mesmos dois pontos** do `_agendar_encerramento` — a abertura e cada inbound —
e **incondicional**, sem olhar a flag: com a decisão no agendamento, ligar só valeria para
conversas novas, e quem já estivesse esperando ficaria sem follow para sempre. Quem decide é
o handler.

Cancelado nos **cinco** caminhos por onde a conversa deixa de ser do agente: `silenciar`,
`_fallback`, `_concluir`, `concluir_por_agendamento_externo` e `encerrar_inativo`. O sexto é
o inbound, que **reagenda** em vez de cancelar.

> `_fallback` não estava na lista pedida e entrou. É a mesma classe de saída, e enumerar 4
> de 5 é a lacuna que morde depois.

### As quatro recusas, nenhuma silenciosa

| Recusa | Por que existe |
|---|---|
| `follow_enabled=false` | o follow é decisão de produto, não efeito de deploy |
| `follow_template` vazio / não aprovado | `{{n}}` vazio é `#131008` e a Meta recusa a mensagem inteira |
| etapa não é ativa | a conversa já não é do agente |
| **alguém já falou nas últimas 20h** | é a regra que faltava em todo o resto do sistema — a NAT sabe quando o SDR digita (é o `silenciar`), mas **não sabia quando uma campanha passou por cima** |

Todas são `AcaoIgnorada` → `skipped` com o motivo **gravado**. `return` mudo viraria
`executado` sem motivo, indistinguível de um follow que de fato saiu.

**Falha de rede não vira `skipped`**, que é terminal: a exceção sobe e o scheduler retenta.
Só um `fetch_template_body` que devolve `None` limpo é recusa. Confundir os dois faria uma
oscilação de rede queimar o follow daquele lead de vez.

### O template ainda não existe — e por que não é o `nat_recuperacao_sdr`

O corpo aprovado dele diz *"Tentamos falar com você **há alguns minutos**"*. É do Bloco 6,
recuperação de ligação que caiu. Mandá-lo 20 h depois de uma pergunta de texto seria o agente
afirmando que tentou ligar quando não tentou. Além disso `nat_copy.py:80` registra que
existem **dois** `nat_recuperacao_sdr` aprovados no WABA, com corpos diferentes (`en` e
`pt_BR`).

**Para ligar, depois de aprovar o texto na Meta:**

```
PATCH /api/nat/config   {"follow_enabled": true, "follow_template": "<nome aprovado>"}
```

O endpoint recusa com **422** quem tentar ligar sem template — mesma regra que já recusa
ligar a NAT sem corte de data. O handler preenche `{{1}}` = nome e `{{2}}` = curso (a
convenção de todos os templates do agente) e **recusa acima de 2 variáveis** em vez de
inventar.

---

## 5. O ano de conclusão virou opcional

É o maior degrau do funil, e sozinho derruba mais gente que todos os outros somados:

```
respondeu alguma vez   77
deu a formação         72     -5
deu o ANO              45    -27  (-37,5%)   <- aqui
deu a atuação          40     -5
deu a motivação        35     -5
```

Perder alguém no ano **não custa o ano**: custa a atuação, a motivação e o agendamento que
vinham depois.

**Por que trava:** é a única pergunta de **memória** do roteiro. Formação, atuação e
motivação a pessoa sabe de cor; o ano de uma graduação de 2004 exige parar e contar. Quem não
lembra na hora não escreve "não lembro" — some.

A saída é **explícita**, não uma tolerância calada:

* *"não lembro"*, *"não sei"*, *"faz muito tempo"*, *"preciso ver o diploma"*, *"ainda estou
  cursando"*, *"por volta de 2010"* passam a **cumprir a etapa**;
* o que ela disse é gravado **literalmente** — `ano_conclusao = "não lembra"` diz uma coisa e
  `NULL` diz outra (que ninguém perguntou), e a consultora lê as duas no contexto;
* o agente **nunca insiste**: a segunda cobrança é o que transforma uma pergunta difícil em
  motivo para sair da conversa;
* quando ela desconversa, a retomada carrega a oferta: *"se não lembrar de cabeça, sem
  problema, seguimos"*.

**Onde a oferta NÃO aparece, e é decisão de produto em aberto:** a *primeira* pergunta vem do
template de abertura (aprovado na Meta, imutável daqui) ou do fecho da missão de
`aguardando_formacao`, e os dois seguem perguntando direto. Levar a oferta para a primeira
pergunta troca **mais conversa concluída por menos ano preenchido**. Está isolado numa linha,
para quando quiserem decidir.

Só esta etapa mudou. Formação, atuação e motivação continuam sendo perguntadas de verdade, e
o teste trava isso.

---

## 6. Registrado, **sem implementar**

### 6.1 `Reagendamento` × `Reagendamento.` — consolidar na Exact, à mão

O funil **18535** tem duas etapas com praticamente o mesmo nome, uma delas com **ponto
final**. Na janela 24/08–01/09 houve **20 entradas em `Reagendamento.` contra 1 em
`Reagendamento`**, e 11 delas foram transições `Reagendamento → Reagendamento.` ocorridas
~1,5 h depois de uma campanha — arrumação de cadastro, não conversão.

**O que isso custou na medição:** a conversão pós-follow deu **18** até eu notar; excluindo a
troca entre as duas, são **6**. Um erro de 3×.

**Por que não implementei:** as etapas vivem na **Exact**, não neste banco. Consolidá-las é
ação manual no CRM, com efeito sobre leads que hoje estão lá — não é migração nossa e não é
decisão de engenharia.

**Enquanto existirem as duas**, toda consulta de conversão precisa da guarda:

```sql
AND NOT (stage_de ILIKE '%Agendad%' OR stage_de ILIKE '%Reagendament%')
```

### 6.2 `nat_contact_attempts` sem uso — **0 registros na janela**

A tabela existe, tem índice `(contact_wa_id, created_at)` e a janela de idempotência de 30s
documentada no `SPRINT_NAT_BLOCO_6_RECUPERACAO_20260814.md`. Na janela 24/08–01/09 ela tem
**zero linhas**.

Consequência concreta, medida no §3 do recon: a régua Follow 1–9 da Exact conta **tentativa
de contato**, e o próprio corpo do `f5_ligacao` diz *"essa **ligação** é a primeira etapa do
seu processo seletivo"* — mas **ligação não deixa rastro nesta base**. Por isso 15 dos 19
leads em `Follows 6` e `Follows 8` aparecem com menos toques do que a etapa promete, e não dá
para saber se foi trabalho não feito ou ligação não registrada.

**São duas saídas, e a escolha é do time, não do código:**

1. **O time registra a ligação** — a tabela e o endpoint já existem; o que falta é o hábito
   e, provavelmente, um botão mais perto de onde a ligação acontece.
2. **A régua da Exact segue sem rastro** — e então nenhum relatório desta casa pode afirmar
   quantas tentativas um lead recebeu, só quantas **mensagens**.

Registrado aqui para que a ambiguidade seja uma decisão e não um esquecimento.

---

## Checklist de saída

| Item | Estado |
|---|---|
| Migrações rodadas em produção | 2, aditivas, idempotentes, com BEFORE/AFTER no log |
| Backfill | nenhum, e o motivo está no §1 |
| Testes novos | `test_autoria_envio` · `test_higiene_disparo` · `test_sdr_logado` · `test_follow_20h` · `test_ano_opcional` |
| Suíte backend | **36 OK · 7 falhas, todas pré-existentes** (ver abaixo) |
| Typecheck frontend | `tsc --noEmit` limpo |
| Envios durante a sprint | **zero** |
| Follow do agente | **desligado**, e sem template |

### As 7 falhas da suíte, e por que nenhuma é desta sprint

| Teste | Natureza |
|---|---|
| `test_agendamento_e2e*.py` (5) | recusam rodar sem `--sim-eu-quero` — **escrevem na Exact de produção**. Comportamento por design |
| `test_exact_detail2.py` | script contra a API viva da Exact; devolveu não-JSON |
| `test_risco3_abertura.py` | **vermelho de propósito** desde 25/08 — `05cea3f` desfez a abertura estrita e a decisão de produto está pendente (ver `FIX_RISCO3_ABERTURA_20260825.md`) |

As duas últimas foram **conferidas em worktree no commit `e5c16fa`** (antes da sprint) e
falham exatamente igual lá.

---

## O que observar nos próximos dias

1. **A primeira campanha depois do deploy.** O painel vai mostrar `skipped_por_regra`. Se o
   número de `teto` vier muito acima dos 30% medidos, o ritmo mudou e o valor merece revisão
   — ele está numa constante em `app/higiene_disparo.py`.
2. **`SELECT sent_by, template_name, count(*) FROM messages WHERE timestamp >= '2026-09-02'`**
   — se `sent_by` vier NULL num envio que passou pela tela, algum caminho de escrita ficou de
   fora.
3. **A assinatura do `tentativa_contato`.** A consulta do §3 do recon deve devolver só nomes
   de gente:
   ```sql
   SELECT substring(content from 'é o ([^\n]*?) do CENAT'), count(*)
   FROM messages WHERE content LIKE '%Tentei realizar uma nova tentativa%'
     AND timestamp >= '2026-09-02' GROUP BY 1;
   ```
4. **`ano_conclusao` com texto em vez de número.** É o sinal de que a saída está sendo usada —
   e o degrau de 37,5% deve encolher no próximo recon.
