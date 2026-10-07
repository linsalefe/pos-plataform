# Filtros do SDR: reunião marcada, confirmou, respondeu fora do padrão (07/10/2026)

Sprint 2 do `RECON_DEVOLUTIVA_ISA_20261007_REPORT.md` §5. O desenho do backend foi aprovado pelo
Álefe em 07/10, com "fora do padrão" contando só o motivo `humano`.

## Backend

`app/reuniao_contato.py` faz uma consulta em `reuniao_status` (reuniões dos últimos 7 dias em
diante) e casa com os contatos em Python pela `chave_telefone`, que é tolerante ao 9º dígito.
`GET /contacts` passa a devolver o campo `reuniao` em cada conversa:

```json
{"meeting_id": 4774914, "inicio": "2026-10-08T17:40:00", "marcada": true, "confirmada": true,
 "fora_do_padrao": false, "situacao": "marcada"}
```

- **Reunião que representa a pessoa:** a próxima Vigente ainda não começada; sem ela, a mais
  recente dos últimos 7 dias.
- **`marcada`:** Vigente, futura e sem `cancelado_motivo` (a reunião cortada não conta).
- **`confirmada`:** marcada e com `confirmado_em` preenchido.
- **`fora_do_padrao`:** `regua_encerrada_motivo = 'humano'`, ou seja, o lead respondeu fora dos
  botões e da lista fechada, na régua de confirmação ou na de no-show.

**Custo medido:** cerca de 24 ms por carga da lista (2 ms de consulta mais 21 ms de casamento).
O `LEFT JOIN` em SQL custava 1 s.

## Frontend (`conversations/page.tsx`)

- **Três filtros rápidos novos**, no painel Filtros: "Reunião marcada", "Confirmou" e "Respondeu
  fora do padrão". Entram no contador de filtros ativos e em "Limpar filtros".
- **Ordenação:** com "Reunião marcada" ou "Confirmou" ativos, a lista vem pela reunião mais
  próxima primeiro.
- **Badge no card:** "📅 hoje 14:30", "amanhã 10:00" ou "qui 08/10 17:40". Fica verde com ✓
  quando a pessoa confirmou. Um badge âmbar "fora do padrão" aparece quando é o caso.

## Testes

`backend/test_reuniao_contato.py`, escrito e não executado. O frontend passou no `tsc --noEmit`.

## Retrato de 07/10, depois do deploy

61 contatos com reunião: 8 marcadas, 3 confirmadas, 2 fora do padrão.
