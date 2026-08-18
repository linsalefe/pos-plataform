# Sprint: múltiplas consultoras no agendamento (18/08/2026)

Branch: `feat/agendamento-subsource` · Investigação: `AGENDAMENTO_FINDINGS.md` §14 (nova)

**O serviço NÃO foi reiniciado.** Nenhuma migração foi necessária — a coluna
`sales_rep_email` já existia e passou a guardar a consultora escolhida.

> **Mecanismo pronto, mas INERTE.** Sem `AGENDAMENTO_CONSULTORAS` no env, o módulo se
> comporta exatamente como hoje: uma consultora só, `comercial@`, grade atual. Ativar é
> preencher o env — e para isso preciso das três respostas do fim deste documento.

---

## ⛔ Item 2 não pode ser feito como especificado

**A reunião não pode ir para o funil 18537.** Não é limitação de implementação, é estrutural
na configuração do CRM. Duas tentativas, as duas recusadas:

```
lead criado direto em 18537  ->  400 Previous stage is not exit action Scheduling
lead em 18535, stageName do 18537  ->  400 Stage not found
```

A posição da etapa explica:

| funil | etapa `Agendados` | **posição** |
|---|---|---|
| 18535 `Pos Graduacao` | id 133409, gate 2 | **14** — última, com `Entrada` na 1 |
| 18537 `Pós Graduação - Vendas` | id 133413, gate 2 | **1** — é a PRIMEIRA |

O `scheduleAdd` exige que a etapa **anterior** do lead tenha "Scheduling" como ação de saída.
No 18537 não existe etapa anterior: o portão de agendamento é a porta de entrada. E o
`stageName` é resolvido dentro do funil do lead — não é ponteiro global.

Consequência: a reunião continua nascendo em **18535 / Agendados (133409)**, que é o que o
módulo já faz. Levar ao 18537 depois é outro mecanismo — `LeadsTransfer` (existe no
`$metadata`, não testado) ou automação do próprio CRM. Reordenar as etapas do 18537 pela UI
também resolveria, mas mexe num funil com 385 leads vendidos: não é decisão de código.

**Nada foi alterado no funil.** `FUNIL_POS_GRADUACAO = 18535` e `STAGE_AGENDADOS = "Agendados"`
seguem como estavam.

---

## O que foi implementado

### `app/agendamento/consultoras.py` (novo)

```
AGENDAMENTO_CONSULTORAS='[{"email":"...","nome_exibicao":"...","grade":{"janelas":{...}}}]'
AGENDAMENTO_CONSULTORAS_PATH=/etc/cenat/consultoras.json
```

A grade de cada uma herda de `GRADE_PADRAO` o que não vier — na prática só `janelas` varia,
porque duração e antecedência são política do produto, não da pessoa. O `sales_rep_email` de
dentro da grade é ignorado e sobrescrito pelo `email`: duas fontes para o mesmo dado é
convite para divergirem.

Config inválida **não derruba o backend** — cai na consultora única e grita no log, mesma
política da grade.

### Validação de startup

`validar_contra_exact()` roda em task de fundo no `lifespan`, sem bloquear o boot.

| situação | efeito |
|---|---|
| e-mail ativo em `/Sellers` | segue em rotação |
| e-mail **inativo** ou **inexistente** | **sai de rotação**, log em ERRO |
| Exact inacessível | **ninguém sai** — não dá para distinguir "inválida" de "não perguntei" |
| nenhuma válida | log CRÍTICO, `/slots` degrada para `fallback:true` |

Sem isso, um e-mail errado faria todo `BoxesAdd` responder `SDR not found` — e o visitante
veria "não consegui agendar" sem ninguém entender por quê. Não é fatal de propósito: o
backend serve o Hub, o webhook da Meta e a NAT, e derrubar tudo porque o CRM piscou seria
trocar um problema por um maior.

### `/slots` — união das grades

`slots_livres` passou a devolver `SlotDisponivel(slot, consultoras)`. Um horário aparece se
ao menos uma pode atendê-lo, e carrega **quem** está livre nele — sem isso o `/agendar`
refaria toda a consulta, com dados de até 60s atrás. Cache de 60s mantido.

Uma consulta a `/Boxes` por consultora, por chamada não-cacheada. Com duas, 2 de 30 req/20s.
Se uma agenda falhar na leitura, aquela consultora sai da rodada e as outras continuam — uma
consultora ilegível não pode apagar a grade das demais.

### `/agendar` — escolha e retry

Escolha por **menor carga do dia**, contada na nossa tabela. Empate mantém a ordem da config
(sortear tornaria o log irreprodutível).

A carga vem da nossa tabela e **não** da Exact de propósito: a agenda da consultora tem
compromisso pessoal, bloco de equipe e reunião de outro funil. Distribuir por ela faria a LP
evitar quem tem agenda cheia por motivos que não têm nada com a landing page.

**O 409 ficou raro.** `Boxes are occupied` numa consultora não significa mais "o horário
morreu" — significa "morreu para ela", e o fluxo tenta a próxima. Só quando todas recusam é
que o visitante vê 409. Erro que **não** é disputa (`SDR not found`, rede, 5xx) para na
primeira: insistir transformaria um env errado em vários boxes criados por engano.

Resposta ganhou `consultora_nome`. O e-mail **não** vai junto — é endpoint público e o
endereço interno não é dado do visitante.

### Onde fica registrado quem atendeu

Na coluna `sales_rep_email`, que já existia. Ela é escrita com a primeira candidata e
**reescrita** quando o `BoxesAdd` define a vencedora — assim uma tentativa que morra no passo
1 ainda diz a quem era destinada. Não criei coluna nova: seria dado redundante.

---

## Testes

### Offline — `test_agendamento.py`: **26/26** (eram 21)

| # | caso |
|---|---|
| 22 | config: herança de grade, e-mail soberano, 3 configs ruins caindo no fallback |
| 23 | união 10:00(Ana) 10:45(Ana+Bia) 11:30(Bia); agenda ilegível de uma não apaga a outra |
| 24 | carga: empate mantém config, 3×1 inverte, ausente conta zero |
| 25 | Ana ocupada → agenda com a Bia; as duas → 409; `SDR not found` para na 1ª |
| 26 | startup: inativa e inexistente saem com motivos distintos; Exact fora não tira ninguém |

### E2E real — `test_agendamento_e2e_consultoras.py`: **10/10**

Cria um box **bloqueador** na agenda da primeira consultora e deixa o `BoxesAdd` bater nele
de verdade, sem mock:

```
  4. box bloqueador 43727120 criado na agenda da A
 ↪️ Consultora A ocupada em 2027-04-21T10:00:00 — tentando a próxima
  5. agendou com a B: lead 51438172, box 43727121, reunião 4725244
  6. lead na Exact: etapa=Agendados, salesRep=executivadecarreiras@
```

Isso protege um acoplamento invisível: `client._ERROS` casa `Boxes are occupied` **por
prefixo**. Se a Exact mudar o texto, o erro deixa de virar `SlotOcupado`, o retry nunca
acontece, e o visitante toma 502 em vez de ser atendido pela outra consultora.

### Regressão — 10 suítes verdes

`test_agendamento` 26/26 · `test_agendamento_cors` 7/7 · `test_nat_flow` 13/13 ·
`test_nat_guard` 9/9 · `test_nat_duplicata` 5/5 · `test_nat_reagendado` 5/5 · as outras 4 OK.

### Resíduo

2 órfãos novos: **43727109** (experimento do `scheduleAdd` com consultora) e **43727121**
(E2E do retry). **Total acumulado: 7.** As duas tentativas de funil recusadas **não**
custaram órfão — sem reunião criada, o box sai com 204.

---

## Uso real detectado em produção

A tabela tinha 2 linhas que não são de teste — alguém usou a LP de verdade às 21:26 de 17/08:

| linha | rota | `lead_externo` | extras | resultado |
|---|---|---|---|---|
| 8 | `/lead` | `False` | 4 chaves no JSONB | lead 51438018 |
| 9 | `/agendar` com `leadId` | **`True`** | — | **mesmo** lead, reunião 4725240 |

`description` na Exact: `E-mail: linsalefe@gmail.com | Profissão: Psicologia | Ensino
Superior: Sim | Como conheceu: Google | Faixa de investimento: De R$300,00 a R$400,00`

É a validação em produção das duas sprints anteriores: fluxo de duas etapas sem duplicar
lead, e extras no formato certo. **Linhas preservadas** — há uma reunião real marcada para
18/08 11:00 com `comercial@`.

---

## Três decisões suas antes de ativar

### 1. Quem são as consultoras?

Só existem **3 sellers ativos**, e você disse que `comercial@` é a pré-venda. Sobram duas:

| candidata | e-mail | reuniões reais / 90d | agenda |
|---|---|---|---|
| **Victória** | `processoseletivo@cenatcursos.com.br` | **80** | quem de fato atende hoje |
| **Marina** | `executivadecarreiras@cenatcursos.com.br` | **0** | praticamente vazia |

Nota: quem trabalhou o funil de vendas historicamente foi a **Isabela** — 395 dos 500 leads
lidos em 18537 são dela — e ela está **inativa** em `/Sellers`, num domínio diferente
(`@ceos.com.br`). Se as consultoras forem pessoas novas, precisam ser criadas na Exact antes.

### 2. O funil fica em 18535?

Dado que o 18537 é impossível pela API (acima), a reunião continua em 18535/Agendados. As
opções são: aceitar assim, mover depois com `LeadsTransfer`, ou reordenar as etapas do 18537
pela UI. **Não fiz nada disso** — todas são decisão sua.

### 3. A grade inicial

Proposta, **idêntica para as duas** — validei programaticamente contra os blocos recorrentes
reais de cada uma e deu **zero conflitos**:

```
seg–sex   09:00–12:00  e  13:30–15:00
slots de 45 min:  09:00 · 09:45 · 10:30 · 11:15 · 13:30 · 14:15   (6/dia cada)
```

Por que idêntica: quando as duas oferecem os mesmos horários, a união fica limpa na tela (6
opções, não 12 em horários quebrados) e **todo** slot ganha o retry da segunda consultora.

Blocos que ela respeita:

| consultora | blocos recorrentes | folga |
|---|---|---|
| `processoseletivo@` | seg 12:00–13:30 · seg 15:00–16:00 · seg–sex 18:20–18:50 | 11:15–12:00 e 14:15–15:00 encostam sem sobrepor |
| `executivadecarreiras@` | seg 16:10–17:00 | nenhum slot depois das 15:00 |

Atenção: `processoseletivo@` tem 80 reuniões reais em 90 dias, espalhadas das 09:00 às 18:00.
A grade vai colidir com frequência na agenda dela — e é exatamente para isso que servem a
subtração do `/slots` e o retry na outra consultora.

---

## Fora de escopo

- Coluna nova para a consultora — `sales_rep_email` já cumpre o papel.
- `LeadsTransfer`, RD Marketing, NAT, kanban, checkout, CORS do Hub — nada tocado.
- Snippets — não precisam mudar: `consultora_nome` é campo novo na resposta, e ignorá-lo
  não quebra nada.
