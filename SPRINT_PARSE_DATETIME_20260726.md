# Sprint — correção do `parse_datetime` e backfill de `register_date`

**Data:** 2026-07-26 · **Branch:** `fix/parse-datetime-backfill-20260726`
**Executado direto em produção.** NAT desligada durante toda a sprint. Nenhuma mensagem enviada.

---

## O bug

`datetime.fromisoformat` no Python 3.10 aceita fração de segundo de **exatamente 3 ou 6 dígitos**.
A API do Exact devolve fração de tamanho variável. Tudo que não fosse 6 caía no `except` e virava `None`.

Amostra de 3.000 leads em 6 páginas da API:

| fração | `registerDate` | `updateDate` | parse antigo |
|---|---|---|---|
| 4 dígitos | 2 | 6 | ❌ falha |
| 5 dígitos | 37 | 27 | ❌ falha |
| 6 dígitos | 263 | 267 | ✅ ok |
| **7 dígitos** | **2.698** | **2.700** | ❌ falha |

Todas com `Z`; nenhuma com offset explícito, sem timezone, vazia ou nula.

> O diagnóstico inicial citava só os 7 dígitos. **Fração de 4 e 5 também quebrava** — por isso a
> correção normaliza qualquer comprimento em vez de truncar 7→6.

**Impacto:** `register_date` NULL em 91,0% e `update_date` em 91,1% da base (8.660 leads).

**Por que era bloqueador de go-live:** a verificação 2 do `nat_guard` falha fechada quando
`register_date` é NULL. Ligar a NAT nesse estado ignoraria **91% dos leads em silêncio** — sem erro,
sem alerta, só log.

---

## A correção

`parse_datetime` foi movida de `app/exact_spotter.py` para **`app/date_parse.py`** (novo, só stdlib).

**Por que mover:** `exact_spotter.py:7` faz `from app.whatsapp import send_template_message` no topo.
O backfill precisa do mesmo parser, e importá-lo de lá carregaria o módulo de envio no processo —
colidindo com a regra absoluta da sprint. `from app.exact_spotter import parse_datetime` segue
funcionando (re-export), e `app.main` importa sem erro.

Núcleo:

```python
_ISO = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?$")

frac = (m.group("frac") or "0")[:6].ljust(6, "0")   # trunca se maior, zero à DIREITA se menor
```

`.9519` são 951900µs, não 9519µs — daí `ljust`, não `zfill`. O que não casa no regex cai num
fallback que preserva exatamente o comportamento antigo.

**Mudança de comportamento deliberada:** data com offset explícito passa a ser convertida para UTC
antes de virar naive. O parser antigo descartava o offset e mantinha a hora de parede, gravando hora
errada. Na prática a Exact só devolve `Z`, onde é idêntico — nenhum dado real muda.

### Testes — `backend/test_parse_datetime.py`, 40 asserções, 9 grupos

Roda sem banco, sem rede e sem token:

```bash
cd /home/ubuntu/pos-plataform/backend && venv/bin/python test_parse_datetime.py
```

Cobre: fração de 7 (o bug), de 6 (não-regressão), de 4/5/3, sem fração, `Z`/offset/sem-tz,
entrada inválida → `None` sem exceção, 9 payloads reais capturados da API, e sanidade de faixa.

**Grupo 6b — não-regressão.** Duas expectativas minhas estavam erradas, não o parser:
`"2026-07-25T16:45"` (ISO válido, precisão de minuto) e `"2026-07-25T16:45:14.Z"` já devolviam
`datetime` na implementação antiga. Fazê-los devolver `None` seria regressão; viraram teste explícito.

---

## O backfill — `backend/backfill_register_date.py`

O parser corrigido só vale para o que a Exact devolver daqui pra frente. Este script recupera o
que já estava no banco.

### Isolamento (a regra absoluta da sprint)

`sync_exact_leads` dispara boas-vindas para lead que considera novo. Reaproveitar aquele caminho
mandaria milhares de mensagens numa WABA com entrega já degradada. Travas:

1. **Não importa `app.whatsapp`**, nem transitivamente — por isso também não importa
   `app.exact_spotter` nem `app.models`. Único import de `app/` é `app.date_parse`.
2. Não chama `sync_exact_leads` nem `send_welcome_to_new_lead`. A paginação é reimplementada em
   10 linhas, espelhando `fetch_leads_from_exact`.
3. Só `UPDATE`, nunca `INSERT`. Lead da fonte ausente do banco é contado e ignorado.
4. Só as duas colunas de data. Nunca `welcome_status`, `contacts`, `messages`, `nat_*`.
5. Só onde o valor é NULL, garantido de novo no `WHERE` — não sobrescreve dado bom nem corre
   com o sync de 10 em 10 min.

**Verificado no interpretador, não por leitura** — importando o script e inspecionando `sys.modules`:

```
modulos proibidos carregados: NENHUM
modulos app.* carregados    : ['app', 'app.date_parse']
```

Todo o SQL que o script pode emitir:

```sql
SELECT exact_id, register_date, update_date FROM exact_leads WHERE ... IS NULL
UPDATE exact_leads SET <col> = :val WHERE exact_id = :exact_id AND <col> IS NULL
```

### Uso

```bash
cd /home/ubuntu/pos-plataform/backend
venv/bin/python backfill_register_date.py            # dry-run (padrão)
venv/bin/python backfill_register_date.py --apply    # grava
```

Extras: data anterior a 2020 ou futura **nunca é gravada** e aborta com código 2 em `--apply`.

---

## Resultado

| | antes | depois |
|---|---|---|
| `register_date` preenchido | 779 / 8.660 (**9,0%**) | 8.656 / 8.660 (**99,95%**) |
| `update_date` preenchido | 772 / 8.660 (**8,9%**) | 8.657 / 8.660 (**99,97%**) |

8.577 leads atualizados. **Idempotência provada:** o dry-run seguinte caiu de 8.581 pendentes para 4,
com 0 atualizações. Os 4 restantes (`48276263`, `47311086`, `47398963`, `49750320`) não existem mais
na Exact — seguem NULL e seguem bloqueados pelo guard, corretamente.

**Universo real da NAT** — funil 18535 + `assigned_to IN (4,5)`:

```
550 leads no funil e com SDR permitido
550 com register_date válido    ← 100%
  0 ainda bloqueados pela verificação 2
```

Antes do backfill, ~91% desses 550 seriam ignorados em silêncio.

**Sanidade:** faixa `2025-02-10` → `2026-07-25`; 0 datas futuras, 0 anteriores a 2020, 0 casos de
`update_date` anterior ao `register_date`. Distribuição mensal entre 149 e 927, crescente.

### Nada foi enviado, nada colateral foi tocado

| | antes | depois |
|---|---|---|
| `messages` outbound | 21.670 | **21.670** |
| `messages` total | 26.766 | **26.766** |
| última mensagem | `2026-07-25 18:14:08` | **`2026-07-25 18:14:08`** |
| `welcome_status` | 253 / 8.387 / 20 | **253 / 8.387 / 20** |

---

## Merge e restart — e uma armadilha de ordem

Merge em `main` (`1782af0`) e restart do `cenat-backend.service` às **03:38** foram feitos a pedido do
Álefe, ampliando o escopo original da sprint. O merge trouxe junto a instrumentação do erro da Meta e a
máquina de estados da NAT, que **já rodavam em produção** desde o restart de 01:56 mas não estavam
registradas na `main` — acerto de registro, não código novo em produção.

### ⚠️ O backfill precisa vir DEPOIS do restart, não antes

O ramo de update do `sync_exact_leads` reescreve as duas colunas com o valor parseado:

```python
for key, value in lead_data.items():
    setattr(existing, key, value)
```

Com o parser antigo em memória, isso grava `None` — ou seja, **o sync apaga o backfill**. Foi
exatamente o que aconteceu: o backfill rodou, e o sync das 03:33 (processo antigo, ainda sem a
correção) devolveu `register_date` de 8.656 para **779** antes do restart das 03:38.

Sem dano permanente — o backfill foi reaplicado após o restart e o sync das **03:48**, já com o parser
corrigido, **preservou** os 99,95%. Mas a ordem correta é restart primeiro, backfill depois. A sprint
pedia backfill sem restart, o que teria durado no máximo 10 minutos.

**Estado final verificado em produção:** serviço ativo (PID 1293166), sync agendado a cada 10 min,
`register_date` em 99,95% após um ciclo completo de sync.

## Fora de escopo (frentes próprias)

- Autenticação em `/bulk-send-template` e `/send/*` — exposição real, ainda aberta.
- Código de erro da Meta e o incidente de entrega desde 23/07 (ver `INVESTIGACAO_ORIGEM_ENVIOS_20260726.md`).
- Realimentar `exact_leads.welcome_status` com o `failed`.
- Fluxo NAT, Blocos 5 em diante.
