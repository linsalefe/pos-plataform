# SPRINT — Lead espontâneo · desenho até o CHECKPOINT da migração — 25/08/2026

**Estado: migração ESCRITA e NÃO RODADA.** Nenhum código de fluxo foi escrito, nada foi ao
ar, nenhuma flag ligada. Este documento é o que precisa do seu ok.

Pré-requisito já entregue: `RECON_ESPONTANEO_20260825.md` (Bloco 0) e a correção do 9º
dígito (`ce13ecc`).

---

## 1. As 4 decisões, aplicadas

| # | decisão | como entrou no desenho |
|---|---|---|
| 1 | chave tolerante | `app/telefone.py`, já no ar. O espontâneo é **imune por construção**: tudo nasce do `wa_id` do inbound |
| 2 | `Espontaneo WhatsApp` | subSource dedicado — **ainda não criado na Exact**, é CHECKPOINT próprio (§6) |
| 3 | congresso → humano | sem filtro de palavra-chave, como você decidiu. Missão 1 transfere |
| 4 | página no Next.js | `hub.cenatdata.online/agendar/<token>`, rota pública |

---

## 2. Admissão — 6 regras, e as duas novas são fail-closed

As 4 do sprint, mais os 2 enrijecimentos. **Todas precisam valer.** Qualquer erro na
checagem → não assume.

| # | regra | por que existe |
|---|---|---|
| 1 | nenhuma mensagem anterior no Hub | primeira conversa da vida |
| 2 | sem lead em `exact_leads` pela **chave tolerante** | com `format_phone`, 147 leads conhecidos/30d passariam e a Nat invadiria conversa de SDR (recon §Achado 1) |
| 3 | sem estado em `nat_qualificacao_state` | um dono por contato |
| 4 | `espontaneo_enabled` + travas vigentes | eixo próprio, ver §5 |
| **5** | **só `message_type == 'text'` com conteúdo não vazio** | 70 dos 554 (13%) chegam como `reaction`/`interactive`/`sticker`/`image`. Uma **curtida** conta hoje como "primeira mensagem da vida" e abriria conversa do nada |
| **6** | **não parece auto-resposta comercial** | 22 em 30 dias. A Nat cumprimenta, o robô do outro lado responde o texto automático, e cada volta gasta LLM e queima a janela de 24h |

**A regra 6 é a única heurística de texto do desenho**, e é deliberadamente estreita:
casa frases inteiras de auto-resposta de WhatsApp Business observadas na base —
`"não estou disponível no momento"`, `"agradece seu contato"`, `"responderemos assim que
possível"`, `"seja bem-vindo(a)"` seguido de apresentação profissional. Ela **não** tenta
adivinhar intenção; isso é trabalho da missão 1. Falso positivo aqui custa um lead não
atendido — que é o comportamento de hoje, não uma piora.

O motivo da não-admissão vai para log estruturado, um por linha, nunca silencioso.

### Onde entra

Dentro de `qualificacao_fluxo.processar_texto`, **não** num terceiro `if` em `main.py:490`.
Aquele bloco existe para haver **um dono por mensagem**; um ramo novo lá recriaria a disputa.

---

## 3. Máquina de etapas

```
                    inbound de número desconhecido
                                 │
                    [6 regras de admissão]  ── falha ──▶ fluxo humano (como hoje)
                                 │
                                 ▼
                    esp_confirmando_interesse ──┬─ não é pós ─────▶ transferido_humano
                                 │              └─ cara de robô ──▶ encerrado
                                 ▼
                       esp_coletando_curso   (lista real dos 13 subSources no contexto)
                                 │
                                 ▼
                      esp_coletando_formacao (formação + atuação numa etapa só)
                                 │
                                 ▼
                        esp_link_enviado  ──── booking na página ──▶ concluido
                                 │
                          72h sem resposta ──────────────────────▶ encerrado
```

**4 etapas, não 6.** O espontâneo é mais curto de propósito: quem escreveu primeiro já
demonstrou interesse, e cada pergunta a mais é uma chance de abandono antes do link.

**Desfechos reaproveitados** (`concluido`, `transferido_humano`, `encerrado`) — não nascem
terminais gêmeos. O encerramento por inatividade de 72h já os consome, e duplicá-los
obrigaria toda régua futura a conhecer duas famílias.

**Robô → `encerrado`, não `transferido_humano`.** Não há humano precisando de nada ali.

---

## 4. O token e a página

### Emissão

`secrets.token_urlsafe(32)` — 256 bits. A URL é pública e sem autenticação: adivinhar um
token é agendar no nome de outra pessoa, e id sequencial seria enumerável em minutos.

**Um token VIVO por contato**, garantido por índice único parcial. Pedir o link de novo
devolve **o mesmo** — é o que dá sentido à regra "não repete mais de 1x".

> ⚠️ **Um furo do meu primeiro desenho, corrigido antes de propor.** O índice ia olhar só
> `usado_em IS NULL`. Um token que **vencesse sem clique** trancaria o contato para sempre:
> `usado_em` seguiria NULL e a emissão seguinte bateria no índice. Aposentar marcando
> `usado_em` resolveria o índice e mentiria no relatório — link abandonado viraria link
> usado. Por isso existe `revogado_em`: duas colunas, dois fatos.

### A página

Abre já sabendo **nome** (se coletado), **curso** (pré-selecionado) e **telefone** (do
`wa_id`, read-only — a pessoa nunca digita). Pede o que falta: nome, se não tiver, e
**e-mail — opcional**, porque `LeadsAdd` não tem campo de e-mail (recon §0.3); ele vai em
`description`. Bloquear o agendamento por um campo que a Exact nem armazena seria atrito
inventado.

Grade e booking pelo motor que já existe (`/api/agendamento/slots` e `/agendar`), então a
janela de 4 dias e a grade 09:00–18:30 valem aqui sem nada novo.

Link expirado, usado ou inexistente → a página oferece **retomar a conversa no WhatsApp**
(`wa.me` do canal), nunca um beco sem saída.

### Booking

`LeadsAdd` + box + schedule pelo caminho existente, com `subSource = "Espontaneo WhatsApp"`.
Grava em `agendamentos` com `lead_id`, e `nat_agendamento_token.agendamento_id` fecha o
círculo. Estado vai a `concluido` e a Nat confirma no chat **com data/hora lidas do banco**,
nunca do LLM.

---

## 5. Flag e travas

`nat_config.espontaneo_enabled`, default **false**. Eixo **próprio**: ligar o espontâneo não
pode depender de ligar o fluxo da LP, nem o contrário — mesmo padrão de
`nat_enabled` × `qualificacao_enabled`.

**Teto duro por contato/hora** como rede final contra loop de robô, além da regra 6. O teto
global (`max_envios_hora`) continua valendo.

---

## 6. CHECKPOINTS abertos

### 6.1 A migração (este documento)

`backend/migrate_espontaneo.py` — **escrita, não rodada.** Numa transação:

1. `lock_timeout = 3s` (o `sync_exact_leads` segura transação longa com HTTP dentro)
2. CHECK de `etapa`: 9 → **13** valores (as 4 `esp_*`)
3. CHECK de `origem`: `lp`, `exact`, **`espontaneo`** — e `VARCHAR(10)` → `VARCHAR(20)`, porque `espontaneo` tem exatamente 10 chars e a próxima origem exigiria outra migração
4. `nat_agendamento_token` + 2 índices
5. `nat_config.espontaneo_enabled` **false**

**Por que a mesma tabela do agente, e não uma nova** — é o oposto da decisão de
`migrate_qualificacao.py`, pelo mesmo critério. Lá, `nat_flow_state` foi recusada porque dois
fluxos disputariam a linha e a precedência viraria um `if` sobre `etapa`. Aqui **não há
disputa**: o espontâneo *é* o agente com outra porta. As origens nunca coexistem no mesmo
contato (regra 2 garante), e o webhook faz a mesma pergunta para ambos. Tabela separada
obrigaria `agente_e_dono`, `estado_de` e a precedência a consultar duas tabelas e decidir
quem vence — criando a disputa que a separação de lá evita.

**O CHECK é recriado (DROP+ADD), e agora é grátis:** `nat_qualificacao_state` está **vazia**.
Com a tabela cheia, o padrão correto seria `NOT VALID` + `VALIDATE` separados; não uso porque
`NOT VALID` abriria janela para etapa inválida entrar sem ninguém ver, e validar hoje custa
zero. A migração avisa se encontrar linhas.

Rodar: `cd backend && venv/bin/python migrate_espontaneo.py`

### 6.2 O subSource na Exact — irreversível

`Espontaneo WhatsApp` **não existe** na allowlist (13 origens, todas `Pos …`).
`LeadsAdd` **cria** subSource que não existe e **não há endpoint para remover** — foi assim
que `DialogicasTurma` virou lixo permanente no cadastro. Sequência proposta:

1. criar em `AGENDAMENTO_SUBSOURCES` + restart
2. `GET /Sources` confirmando que nasceu sob `Landing Page` (id 140648)
3. **o primeiro booking real é o teste** ← CHECKPOINT seu

### 6.3 Antes do deploy

Cenários novos no harness manual (`teste_manual_llm.py`), com LLM real: admissão dos 6
critérios, robô que encerra, aluno que transfere, link com token válido, single-use,
expiração.

---

## 7. Fila — item 1 depois do relatório das 10h06

**Risco 3: `abrir()` consome ação sem enviar nada.** Spec sua, registrada aqui para não se
perder:

| situação | hoje | depois |
|---|---|---|
| teto por hora estourado | `executado`, lead perdido | **REAGENDA** para a próxima janela, sem consumir |
| lead anterior ao corte | `executado`, lead perdido | `skipped` + **motivo gravado no banco** |
| contato inexistente | `executado`, lead perdido | `skipped` + **motivo gravado no banco** |

**Nunca `executado` sem envio** — falha silenciosa é a classe de bug que mais mordeu este
projeto. Testes dos três caminhos.

Medido: ~6,1 leads/noite na faixa 23:16→09:00 + ~1,2/h entre 9h e 10h ≈ **7 aberturas caem
juntas às 09h**, contra teto de 20/h. Folgado hoje; a seção 2b do monitor detecta a
assinatura do descarte se acontecer.

---

## 8. O que NÃO foi feito

- Nenhum código de fluxo, missão, admissão, token ou página.
- A migração **não** rodou. `models.py` **não** foi tocado — de propósito: o teste
  "as 9 etapas do CHECK batem com o modelo" protege justamente o alinhamento entre modelo e
  banco, e mexer no modelo antes da migração o tornaria uma afirmação falsa.
- Régua de cadência para `origem='espontaneo'` + `esp_link_enviado`: **registrada como
  entrada futura**, não implementada, como o sprint pede.
