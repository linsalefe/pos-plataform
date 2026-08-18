# Sprint: campo `extras` no agendamento (18/08/2026)

Branch: `feat/agendamento-subsource` · Investigação: `AGENDAMENTO_FINDINGS.md` §13 (nova)

**Está no ar.** Migração aplicada e `cenat-backend` reiniciado em 18/08/2026 00:24 UTC,
validado em produção — ver "Deploy" no fim.

---

## O achado que definiu o desenho

Antes de escrever qualquer linha, sondei o limite de `description` criando e apagando leads
reais. **A sondagem não deixou resíduo**: sem `BoxesAdd` e sem `scheduleAdd`, o `LeadsDelete`
limpa tudo — o órfão permanente dos outros E2E vem da reunião, não do lead.

| enviado | guardado | veredito |
|---|---|---|
| 200 / 4000 / 7999 / 8000 | idêntico | intacto |
| **8001** | **7999** | **TRUNCADO** |
| 10000 | 7999 | TRUNCADO |

**Nenhuma tentativa devolveu erro.** O `LeadsAdd` responde 201 e corta o texto em silêncio —
nada no corpo, nada em log, nada que distinga "guardei tudo" de "joguei metade fora". E
estourar por 1 caractere custa 2: 8001 vira 7999.

Por isso o módulo trabalha com **orçamento próprio de 4000** e, se passar disso, **corta ele
mesmo e deixa `…`**. Truncar é ruim; truncar sem ninguém saber é pior. O pior caso real do
formulário (e-mail + 10 extras cheios) dá **2868 caracteres**, então o orçamento nunca deveria
ser atingido — ele existe para o dia em que alguém afrouxar um limite de campo sem lembrar
que há um teto do outro lado.

---

## O que mudou

### `app/agendamento/extras.py` (novo)

Sanitização, contrato e montagem do `description`. Isolado porque a formatação depende de
três coisas que não são assunto de cliente HTTP: limpeza de conteúdo, ordem dos campos e
orçamento de tamanho.

**Sanitização** (silenciosa, é sujeira de digitação):

| entrada | vira | por quê |
|---|---|---|
| `Insta\|gram` | `Insta/gram` | `\|` é o separador do formato — viria do conteúdo e partiria o campo em pares falsos |
| `linha1\nlinha2\tfim` | `linha1 linha2 fim` | quebra e tabulação desmontam o layout do CRM |
| `a\x00b` | `a b` | caractere de controle é invisível e corrompe exportação |
| `"   "` | par removido | `Profissão: ` sozinho não informa nada |

Normaliza NFC antes de tudo: `Profissão` com til combinante compara diferente de
`Profissão` pré-composto, e viraria duas chaves "iguais" no JSON.

**Contrato** (recusa com 422): máx 10 chaves, valores até 200 chars, chaves até 60, só texto.

> **Por que recusar e não truncar** — isso contraria o "visitante nunca fica preso" que rege
> o resto do módulo, e foi decisão consciente. Extras alimentam relatório de marketing, e um
> valor cortado pela metade é pior que uma submissão recusada, porque ninguém descobre. Quem
> controla o formulário somos nós: 10 perguntas já é uma LP longa, e uma 11ª significa que
> alguém mexeu no form sem olhar o backend. O 422 aparece no console de quem publicou a
> página — exatamente quem pode consertar.

**Formato** (o que o SDR lê):

```
E-mail: x@y.com | Profissão: Psicologia | Ensino Superior: Sim | Como conheceu: Instagram | Faixa: Até R$100,00
```

E-mail primeiro (é o dado mais usado e o único que a Exact não tem campo próprio para
guardar), extras na ordem das perguntas do formulário.

### `agendamentos.extras` — coluna JSONB

**Divergi do projeto de propósito.** `templates.components` e `nat_scheduled_actions.payload`
são `Text` com `json.dumps`, mas ambos guardam payload opaco, escrito para auditoria e nunca
lido por dentro. Aqui é o contrário — a pergunta que o marketing vai fazer é literalmente
"quantos leads vieram do Instagram?":

```sql
SELECT extras->>'Como conheceu', count(*) FROM agendamentos GROUP BY 1;
```

JSONB dá isso sem parse na aplicação e recusa JSON inválido na escrita. PG 14.23, suporte
nativo. Sem índice GIN: a tabela é pequena e GIN custaria escrita no caminho do agendamento,
que é o que não pode ficar lento. O comando está no cabeçalho da migração para quando crescer.

NULL (nada perguntado) é distinto de `{}` (perguntado, não respondido). A distinção é de
graça e pode importar num relatório.

### Rotas

`extras` foi declarado em `DadosLead`, então vale para **`/lead` e `/agendar`** sem duplicação
— as duas rotas têm o mesmo contrato. `ExtrasInvalidos` herda de `ValueError`, então o
Pydantic já devolve 422 com a mensagem dentro, sem `except` no endpoint.

### `client.criar_lead`

Deixou de receber `email` e passou a receber `description` pronto. O cliente HTTP virou
transporte puro; quem monta o texto é `extras.montar_descricao`. Os dois únicos chamadores
estão em `agendar.py` e foram atualizados.

### Um detalhe do fluxo de duas etapas

Com `leadId` (lead já existe), os extras vão **só para a nossa tabela**. Não há `LeadsUpdate`
neste fluxo, e sobrescrever o `description` que o formulário do index já gravou seria pior que
não escrever. Na prática o index é quem pergunta, então o dado já está no CRM. O log avisa
com `(extras só na tabela local)`.

---

## Testes

### Offline — `test_agendamento.py`: **21/21** (eram 17)

| # | caso |
|---|---|
| 18 | sanitização (pipe, quebra, controle, vazios) e 5 violações de contrato recusadas |
| 19 | formato exato do `description`, pior caso real, e o corte com `…` no orçamento |
| 20 | extras chegam ao `LeadsAdd` **e** à coluna JSONB, nos 3 caminhos |
| 21 | **regressão**: sem extras, `description` = só o e-mail; sem e-mail, sem `description` |

### E2E real — `test_agendamento_e2e_extras.py`: **8/8, resíduo zero**

É o **único E2E do módulo que não deixa órfão** — exercita só o `LeadsAdd`.

```
  3. a Exact guardou os 134 chars IDÊNTICOS — nada truncado
  4. acentos intactos: 'Profissão', 'Até R$100,00'
  5. agendamentos#7.extras é dict Python com 4 chaves, sem parse na aplicação
  6. SELECT extras->>'Como conheceu' -> 'Instagram'
```

O passo 3 é o ponto: o teste offline verifica a string que **montamos**, este verifica a que
a Exact **guardou**. São coisas diferentes quando existe truncamento silencioso.

### Regressão — 10 suítes, todas verdes

`test_agendamento` 21/21 · `test_agendamento_cors` 7/7 · `test_nat_flow` 13/13 ·
`test_nat_guard` 9/9 · `test_nat_duplicata` 5/5 · `test_nat_reagendado` 5/5 ·
`test_nat_recuperacao`, `test_nat_sprint3`, `test_nat_config_api`,
`test_nat_caminho_completo` OK.

Tabela `agendamentos` de volta a **0 linhas**. **Órfãos acumulados continuam 5** — esta sprint
não acrescentou nenhum.

---

## Dois achados de brinde (findings §13)

**O `description` demora a aparecer na leitura.** Três dos cinco leads da sondagem voltaram
com `description: null` logo após o `LeadsAdd`, e os mesmos leads relidos segundos depois
tinham o campo. Não é o índice de texto do §10 — o filtro era `id eq`, que acha o lead na
hora. É o **campo** que demora a materializar.

**O atraso de índice não é só do `contains()`.** O §10 registrou isso para busca textual.
Esta rodada mostrou que **`phone1 eq` também atrasa** — o E2E falhou confirmando a exclusão
de um lead que o `DELETE` já tinha removido com 204. **`id eq` é o único filtro consistente
na hora.**

---

## Deploy — FEITO em 18/08/2026 00:24 UTC

```bash
venv/bin/python migrate_agendamentos_extras.py   # antes, aditiva
sudo systemctl restart cenat-backend.service
```

### Validação em produção

| verificação | resultado |
|---|---|
| `cenat-backend` ativo, `/health` | **200** |
| log de inicialização | limpo |
| `GET /slots` | **200**, `fallback:false`, 10 dias com vaga |
| CORS de `lp.cenatsaudemental.com` | **204** |
| `extras` com 11 chaves | **422** |
| `extras` com valor de 201 chars | **422** |
| `extras` com valor não-texto | **422** |
| `extras` que não é objeto | **422** |
| `/agendar` com `extras` válido + `leadId` inexistente | **404** (extras passaram, parou no lead) |
| `agendamentos` depois de tudo | **0 linhas** — nenhuma escrita |

O 404 do último caso é a confirmação que interessa: os `extras` atravessaram a validação e o
fluxo só parou na verificação do lead, que é onde deveria parar.

Os 422 não consomem rate limit — a validação do corpo acontece antes do limitador.

O caminho de escrita bem-sucedido já tinha sido provado contra a Exact de produção pelo
`test_agendamento_e2e_extras.py` (8/8, resíduo zero), então não repeti aqui para não criar
lead de teste à toa.

---

## Fora de escopo

- **Snippets** — não foram alterados. Mandar `extras` do formulário é uma linha
  (`corpo.extras = {...}`), mas o pedido era backend. As LPs atuais não mandam o campo e
  seguem funcionando.
- **RD Marketing, NAT, kanban, checkout, CORS do Hub** — nada tocado.
- **`LeadsUpdate`** — continua não existindo no fluxo. Extras enviados no `/agendar` com
  `leadId` não reescrevem o `description` do lead.
