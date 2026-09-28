# DEPLOY_EXPEDIENTE_10_19_20260928 — grade das consultoras passa a 10:00–19:00

Segue o `RECON_CONSULTORAS_20260928.md` §4: o expediente da Amorim na Exact
(`/MeetingSettings.usersBusinessHours`) era 10:00–19:00, e o Hub oferecia 09:00–18:30.

## O que mudou

`backend/consultoras.json`: as duas consultoras (Amorim `comercial@`, Rodrigues
`processoseletivo@`) com `janelas` `"0"`–`"4"` = `[["10:00","19:00"]]`. Sábado e domingo
seguem sem grade. Duração de 45 min: 12 horários por dia, de 10:00 a 18:15 (o último
termina 19:00).

⚠️ A Rodrigues está com **09:00–18:30** na Exact. A mudança dela para 10:00–19:00 foi decisão
do Álefe, e a Exact não foi alterada. Se o expediente real dela for o da Exact, o arquivo é
que diverge agora.

## Antes do restart: reuniões já marcadas fora do expediente novo

- **Hub**: `agendamentos` com `passo='agendado'`, `slot_inicio` futuro (28/09 16:02 SP) e
  hora entre 09:00 e 10:00 SP: **0 linhas.**
- **Exact** (checagem extra): `/Meetings` com `startTime` ≥ 28/09 16:02, fora de
  `Cancelada`, começando antes de 10:00 ou terminando depois de 19:00: **0.**

**Não há nada para o comercial remarcar.**

## Restart (28/09 19:03 UTC)

`sudo systemctl restart cenat-backend`, PID 1873130. Boot:

    ✅ agendamento: 2 consultora(s) em rotação — Victória Amorim <comercial@cenatcursos.com.br>, Victória Rodrigues <processoseletivo@cenatcursos.com.br>

## `/api/agendamento/slots` depois do restart (16:03 SP)

| dia | horários | primeiro | último | antes das 10h |
|---|---|---|---|---|
| seg 28/09 (hoje) | 1 | 18:15 | 18:15 | 0 |
| ter 29/09 | 8 | 11:30 | 18:15 | 0 |
| qua 30/09 | 12 | **10:00** | 18:15 | 0 |
| qui 01/10 | 12 | **10:00** | 18:15 | 0 |

- **Hoje** só sobra 18:15, por causa da antecedência mínima de 2h (16:03 + 2h). Não dá para
  ver o início às 10:00 no dia de hoje; ele aparece em 30/09 e 01/10.
- **18:15–19:00** é horário novo: antes a grade acabava às 17:15.
- **Em 29/09**, 10:00 e 10:45 não aparecem porque já estão ocupados nas duas consultoras.
