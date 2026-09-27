# LIBERACAO_FOLLOW_ESTAGIO_20260927 — relatório

**Resultado: follow por estágio LIBERADO para todo o funil 18535 desde 17:24:40 UTC de 27/09.
Na hora monitorada NÃO houve nenhum envio — nenhum lead entrou em estágio de Follow.** Os
60 ciclos rodaram limpos, o desligamento automático não disparou e o gate continua aberto
(`FOLLOW_ESTAGIO_ENABLED=true`).

**Esta hora não prova o caminho de envio.** Era domingo e a Exact não teve movimento de card:
o único evento de estágio da janela foi o lead de teste que eu mesmo criei (§3). A primeira
linha real de `follow_estagio_envios` ainda está por vir, e vai para um lead de verdade, sem
que o caminho ponta a ponta tenha sido testado antes (TESTE_FOLLOW_ESTAGIO_20260927_REPORT: parou
na Fase 1).

---

## 1. A liberação

| passo | estado |
|---|---|
| Backup do `.env` | ✅ fora do repo (scratchpad da sessão) |
| `FOLLOW_ESTAGIO_SOMENTE_TELEFONES` | ✅ linha **removida** do `backend/.env` |
| `FOLLOW_ESTAGIO_ENABLED` | ✅ `true`, intocado |
| `nat_config.follow_enabled` | `false` (follow_20h do agente, outro assunto — intocado) |
| Restart | ✅ `sudo systemctl restart cenat-backend` às **17:24:40 UTC**, `active` |

Boot e primeiro ciclo **sem** allowlist — sem `MODO DE TESTE` no boot e sem a linha `🧪` no ciclo,
que eram as duas marcas da allowlist (compare com o §1 do relatório de teste):

```
17:24:42  ✅ Follow por estágio da Exact (checa a cada 60s, envio LIGADO)
17:25:43  ⏱️  follow por estágio: {'estagios_no_mapa': 9}
```

## 2. A hora monitorada (17:24:40 → 18:24:51 UTC)

Um script consultou `follow_estagio_envios` a cada 20 s, com o desligamento embutido: qualquer
`falhou`, ou `skipped` com motivo que não começasse por `recusa`/`opt_out_meta`, trocaria o
gate para `false` e reiniciaria o serviço na hora. Para cada linha nova ele registraria estágio,
template, texto renderizado (de `messages.content`), status da Meta (`messages.status`),
latência evento→envio e latência fila→envio.

| medida | valor |
|---|---|
| Ciclos do job na janela | **60** (um por minuto, 17:25:43 → 18:24:48), todos `{'estagios_no_mapa': 9}` |
| Linhas novas em `follow_estagio_envios` | **0** |
| `falhou` / `skipped` | 0 / 0 — **desligamento automático não disparou** |
| `❌` / `Traceback` / `MODO DE TESTE` no journald | 0 / 0 / 0 |
| `disparo_skip` na janela | 0 |
| Serviço ao fim | `active`, gate `true` |

Batimentos (a cada 15 min):

```
HB [17:26:55] servico=active ciclos=2  max_evento=4259 cursor=4259 linhas=0
HB [17:42:04] servico=active ciclos=17 max_evento=4259 cursor=4259 linhas=0
HB [17:57:00] servico=active ciclos=32 max_evento=4259 cursor=4259 linhas=0
HB [18:12:07] servico=active ciclos=47 max_evento=4259 cursor=4259 linhas=0
FIM [18:24:51] janela de 60 min encerrada
```

**Por linha (estágio, template, parâmetros, status Meta, latência): não há o que reportar —
nenhuma linha foi criada.**

## 3. O evento 4260, e por que o cursor ficou em 4259

O único evento de estágio da janela:

```
  id  | exact_lead_id | stage_de | stage_para | funnel_id |        observado_em
 4260 |      52262377 |          | Entrada    |     18535 | 2026-09-27 18:17:28
```

É o **lead de teste `TESTE NAT Alefe`**, que criei às 18:12 para a Fase 0 da
SPRINT_RELIGAR_AGENTE_20260927 (prova do `timelineAdd`). Entrou em `Entrada`, que não está no
mapa — nenhum follow devido.

O cursor continuar em **4259** com `MAX(id)=4260` **não é defeito**: `_eventos_novos` filtra
`stage_para = ANY(<9 estágios>)` na própria query, e o cursor só avança sobre o que ela
devolve. Eventos fora do mapa nunca são lidos, então não seguram nada — o cursor fica para
trás até o próximo evento de Follow e salta por cima de tudo de uma vez. Fica anotado porque
quem olhar `cursor < MAX(id)` vai achar que o job travou.

Antes do lead de teste, o último evento era das **03:10 UTC**: nenhum card mexido no domingo.

## 4. O que muda agora e o que observar

* Todo lead do funil 18535 que entrar num dos 9 estágios de Follow recebe o template **em até
  ~1 min**, **sem janela de horário** e **sem teto de rajada** — decisões de 27/09. A maior
  rajada medida (18/09) foi de 45 leads numa passada.
* **Segunda de manhã é o primeiro teste real.** Consultas prontas:

```sql
SELECT id, status, motivo, estagio_nome, template, created_at, enviado_em
  FROM follow_estagio_envios ORDER BY id;
SELECT status, left(motivo, 40), count(*) FROM follow_estagio_envios GROUP BY 1, 2;
```

* O primeiro sinal de que o teto faz falta é o erro `131049` da Meta (limite de frequência) —
  e ele NÃO é pulado pelo disparo.
* Para desligar: `FOLLOW_ESTAGIO_ENABLED=false` no `backend/.env` + restart. **Atenção ao
  religar:** desligado, o job não toca no banco e o cursor PARA (`follow_estagio.py:620`). Na
  volta, todo lead que entrou em Follow durante a pausa recebe o template de uma vez — é
  recuperação de queda, por desenho. Se a pausa for longa e isso não for desejado, avançar o
  cursor para o `MAX(id)` de `exact_stage_events` ANTES de religar.
* Os eventos de Follow que chegaram entre o deploy (14:03) e a liberação (17:24) foram **zero**,
  então a allowlist não comeu nenhum follow real.

## 5. Resíduo

* Nenhum lead alterado, nenhuma mensagem enviada por este trabalho.
* O lead de teste 52262377 é da outra sprint e será apagado no fim dela (`LeadsDelete`).
