# Deploy (a)+(b) no ar — restart, e as 5 validações

**27/08/2026 · 14:04–14:15 (SP) · `cenat-backend` + `cenat-frontend`**
Commits no ar: `31223bb` (a) leitura agrupada · `05cea3f` (b) canonização na escrita.

---

## 0. A sequência, e por que ela

O backend sozinho primeiro; o frontend com **build e restart colados**, na mesma janela.

A separação não é cerimônia: (a) e (b) só tocam `frontend/src/app/conversations/page.tsx`
do lado do cliente, e esse arquivo estava **mais novo que o `BUILD_ID` em disco** —
exatamente o estado que produziu o `ChunkLoadError` de 25/08
(`FIX_FRONTEND_CHUNK_404_20260825.md`). Naquele incidente o `.next/` foi reconstruído sem
restart e o processo ficou 5 dias servindo um manifest que o disco já não tinha. Build e
restart juntos fecham essa janela: o processo nasce sabendo do build que acabou de sair.

```
17:04:13 UTC  import de app.main/routes/contatos/qualificacao_fluxo/exact_* — preflight OK
17:04:20 UTC  systemctl restart cenat-backend    -> MainPID 1620115
17:05:0x UTC  NODE_ENV=production npm run build  -> 16 páginas, compilado em 23,2s
17:05:22 UTC  systemctl restart cenat-frontend   -> MainPID 1620271, ready em 926ms
```

---

## 1. Boot dos dois, e zero erro de chunk

**Backend** — `active (running)`, `NRestarts=0`, os 7 agendadores subiram:

```
✅ Sync Exact Spotter (10 min)          ✅ Agendador NAT (60s)
✅ Alertas de janela 24h (5 min)        ✅ Alerta de saúde de entrega (15 min)
✅ Agendamento de templates (60s)       ✅ Faxina de agendamento (0:15:00)
✅ Varredura de agente parado (15 min, régua de 60 min — só notifica)
✅ agendamento: 2 consultora(s) em rotação · source 'Landing Page' (140648), 14 origens
INFO: Application startup complete.
```

Nenhum ERROR, nenhum traceback. O único aviso é o `FutureWarning` do `google.api_core`
sobre Python 3.10, que é preexistente e não vem deste sprint.

**Frontend** — `BUILD_ID` `NiYDeWvvz7xjYxN25mFi6` → **`pjIpNDNBz1fh68EcmuuPo`**, processo e
disco no mesmo build. `Ready in 926ms`, sem warning de compilação.

**Chunks — o teste que pegou o incidente de 25/08.** Para cada página, baixei o HTML servido
pelo domínio público e pedi **todos** os assets que ele referencia:

| página | assets | 404 | | página | assets | 404 |
|---|---|---|---|---|---|---|
| `/` | 12 | 0 | | `/templates` | 13 | 0 |
| `/login` | 12 | 0 | | `/leads-pos` | 13 | 0 |
| `/dashboard` | 13 | 0 | | `/automacoes` | 14 | 0 |
| `/conversations` | 14 | 0 | | `/users` | 13 | 0 |
| `/agenda` | 13 | 0 | | `/calls` | 13 | 0 |
| `/kanban` | 13 | 0 | | `/ai-config` | 13 | 0 |

**156 assets checados, 0 falhas.** `/health` → `{"status":"online"}`.

E o código de (a) está mesmo no bundle que o navegador recebe — o casamento por `wa_ids`
aparece em `/_next/static/chunks/15cde51345997b3e.js`, servido pelo processo novo.

---

## 2. Caso Mikaelle na tela

**Uma conversa.** `GET /contacts` devolve **7 729 conversas** para **8 136 contatos** —
407 pares agrupados (era 406 ontem; nasceu mais um antes do deploy de (b)). Mikaelle aparece
**uma vez só**:

```json
{ "wa_id": "554192680313", "name": "Mikaelle Juliani (Psicóloga)", "assigned_to": 5,
  "wa_ids": ["554192680313", "5541992680313"],
  "last_message": "Oi… gostaria de confirmar o horário da conversa com a consultora",
  "unread": 0, "assigned_to_conflito": null }
```

O `name` veio do lado de 12 dígitos e o `assigned_to` do lado de 13 — fusão por regra, como
o commit descreve, não COALESCE cego.

**11 mensagens alternando, por qualquer das duas pontas.** Abrindo por `554192680313` e por
`5541992680313`, o resultado é byte a byte o mesmo:

```
mensagens: 11 | ordenadas por timestamp: True
turnos:    I O I O I O I O O I I
```

O `O O` no meio não é defeito: são as duas saídas de 26/08 13:25:04 — o fecho da
qualificação e o "deixa eu te conectar com uma pessoa da nossa equipe".

**Badge, e o `read` cruzando a grafia.** Hoje nenhum par real tem inbound não lida dos dois
lados (0 pares; 1 par tem de um lado só), então o cruzamento foi provado no caso mais duro
que existe: as 6 inbound da Mikaelle vivem **todas** na grafia de 12 dígitos, e o `read` foi
disparado pela de **13**, que não tem inbound nenhuma. Se o `IN(variantes)` não estivesse lá,
não zeraria nada.

```
1) 6 inbound marcadas como 'received'
2) card na lista agrupada  -> unread = 6
3) POST /contacts/5541992680313/read   (a grafia SEM inbound)
4) card na lista agrupada  -> unread = 0
5) diff do banco contra o snapshot     -> IDÊNTICO ao estado inicial
```

O passo 5 importa: `POST /read` devolve as linhas a `status='read'`, que era o valor original
das 11. O teste não deixou resíduo — conferido com `diff`, não no olho.

---

## 3. Envio: nada disparado, e o que observar

Nenhum envio de teste, conforme combinado. Duas coisas no lugar disso.

**A canonização está viva no processo novo**, exercitada em leitura pura contra o banco real:

| chegaria como | `canonizar` grava em | `destinatario` envia para |
|---|---|---|
| `5541992680313` | **`554192680313`** ← desviado para a thread que já existe | `554192680313` |
| `554192680313` | `554192680313` | `554192680313` |
| `5583988046720` | **`558388046720`** ← idem | `558388046720` |
| `5511999999123` (desconhecido) | `5511999999123` | `5511999999123` |

Número que ninguém conhece continua sendo ele mesmo — a canonização não inventa contato.

**Já saiu um envio real depois do restart**, às 14:11 SP (msg `32130`, `sent`), para
`5585986911107` — Quezia, abertura do agente. É contato **novo**: não existe `558586911107`
no banco, então `canonizar` manteve a grafia dela e criou **uma** thread. É o caso limpo para
observar. Quando ela responder, a Meta entrega o inbound em 12 dígitos e (b) tem que gravar
**dentro deste mesmo contato**. A consulta que responde isso:

```sql
SELECT contact_wa_id, direction, to_char(timestamp,'DD/MM HH24:MI') AS ts_sp, left(content,40)
FROM messages WHERE contact_wa_id IN ('5585986911107','558586911107') ORDER BY timestamp;
-- esperado: TODAS as linhas em 5585986911107. Se aparecer 558586911107, (b) não pegou.
```

---

## 4. Notificação antiga do agente (13 dígitos)

O sino empurra `/conversations?wa=<contact_wa_id>`, e a página resolve com
`c.wa_id === wa || c.wa_ids?.includes(wa)` (`conversations/page.tsx:253`). Rodei o predicado
**antigo e o novo** contra as notificações reais e a lista agrupada de agora:

| | |
|---|---|
| notificações com grafia de 13 dígitos | **2 130** |
| abriam a conversa ANTES (`== wa_id`) | 2 123 |
| abrem a conversa AGORA (`\|\| wa_ids`) | **2 130** |
| **consertadas por este deploy** | **7** |
| ainda sem destino | **0** |

São exatamente os 7 casos que o commit (a) previu. Ponta a ponta, a notificação `4421`:

```
notif 4421 · 26/08 16:25 · agente_transferiu · "Agente passou um lead para você"
  wa = 5541992680313   ->  /conversations?wa=5541992680313
  cards que casam: 1   ->  abre 554192680313 · Mikaelle Juliani (Psicóloga)
  conversa: 11 mensagens · I O I O I O I O O I I
  última: "Oi… gostaria de confirmar o horário da conversa com a consultora"
```

Antes, esse clique abria a lista e não selecionava nada — em silêncio.

---

## 5. Deep-link `?wa=` nas duas grafias

**407 de 407 pares**: as duas grafias caem no **mesmo card**. Amostra conferindo também que a
conversa carregada é idêntica (hash do corpo da resposta):

```
?wa=5541996596171  e  ?wa=554196596171   -> card 5541996596171    2 msgs  ✅ igual
?wa=558185088547   e  ?wa=5581985088547  -> card 558185088547     7 msgs  ✅ igual
?wa=5581995345775  e  ?wa=558195345775   -> card 5581995345775    2 msgs  ✅ igual
?wa=558196326394   e  ?wa=5581996326394  -> card 558196326394     8 msgs  ✅ igual
?wa=559891804665   e  ?wa=5598991804665  -> card 559891804665     8 msgs  ✅ igual
```

Note que o card representante nem sempre é o de 12 dígitos (`5541996596171` é o de 13). É o
`principal_do_par` funcionando: vence quem recebeu inbound, e onde ninguém recebeu, a mensagem
mais recente decide. O SDR não precisa saber disso — as duas grafias levam ao mesmo lugar.

---

## Achado colateral: as idades da triagem estavam 3h infladas

Ao regerar a fila, confirmei o fuso das duas colunas de tempo:

```
agora UTC: 27/08 17:11        messages.timestamp:  27/08 14:11:23   <- SP, naive
agora SP : 27/08 14:11        messages.created_at: 27/08 17:11:21   <- UTC
```

`TRIAGEM_SEM_RESPOSTA_20260827.md` calculou idade com o relógio **UTC** contra um timestamp
que é de **SP** — toda idade daquele doc saiu **3 horas maior** do que a real. Em linha de
`44d` não muda nada; no topo da fila muda: a Mikaelle estava marcada `4h` quando tinha `1h44`.
Corrigido na regeração de hoje.

---

## Estado final

| | |
|---|---|
| `cenat-backend` | ativo desde 17:04:20 UTC · MainPID 1620115 · 0 restarts |
| `cenat-frontend` | ativo desde 17:05:22 UTC · MainPID 1620271 · `pjIpNDNBz1fh68EcmuuPo` |
| contatos / conversas | 8 136 → **7 729** (407 pares agrupados) |
| assets checados | 156, **0** falhas |
| dados alterados no teste | **nenhum** — o único write foi revertido pelo próprio `POST /read` |

**(c) — migração dos 407 pares — segue fora deste deploy**, para o planejamento, como
combinado. Nada aqui migra, apaga ou funde linha no banco: (a) é leitura e (b) escolhe chave
de gravação para o que ainda vai nascer.
