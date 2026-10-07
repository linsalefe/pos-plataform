# Sprint: sinalização para o SDR (07/10/2026)

Branch `feat/sinalizacao-sdr`, no ar desde 07/10. Merge na `main` só depois de o Álefe confirmar
que recebeu o aviso de teste.

## 1. Templates

| template | id Meta | categoria | status |
|---|---|---|---|
| `nat_sdr_corte` | 1285456514199002 | UTILITY (pedida e devolvida) | PENDING |
| `nat_sdr_ligar_agora` | 2103094596998334 | UTILITY (pedida e devolvida) | **APPROVED** |

Os corpos estão em `nat_copy.CORPO_SUBMETIDO_SDR`. Diferença em relação ao texto combinado: o
`nat_sdr_ligar_agora` ganhou o fecho "Quem estiver livre, assume a ligação.". O texto combinado
terminava em variável (`Pós em {{3}}.`), o que o validador recusa e a Meta também recusaria.

## 2. Avisos por WhatsApp (`app/aviso_sdr.py`)

| momento | template | destinatários |
|---|---|---|
| corte (`confirmacao.confirm_a_corte`, depois da Notification) | `nat_sdr_corte` (nome, pós, "sex 09/10 10:00") | consultora da reunião (`consultoras.telefone_de`) + `SDR_AVISO_TELEFONES` |
| "Posso falar agora", da confirmação e do no-show (`confirmacao.ligar_agora`) | `nat_sdr_ligar_agora` (nome, telefone do lead, pós) | as duas consultoras + `SDR_AVISO_TELEFONES` |

- Os avisos vão direto por `whatsapp.send_template_message`. Não passam pelo guard do agente nem
  pelo teto por hora, e não criam contato.
- Cada destino tem o seu próprio tratamento de erro. `avisar_*` nunca levanta, então nada desfaz
  o corte ou o clique.
- `consultoras.normalizar_telefone`: `(21) 97007-5652` vira `5521970075652`. As duas consultoras
  resolvem.
- `SDR_AVISO_TELEFONES` está **vazio** por decisão do Álefe; até ser preenchido, o SDR recebe só
  a Notification do Hub.
- **Desvio da decisão 2:** o aviso **não** é gravado em `messages`. `messages.contact_wa_id` é
  NOT NULL com FK para `contacts`, e não dá para gravar sem criar ou vincular um contato, que a
  mesma decisão proíbe. A auditoria fica no log (`📣 aviso <template> -> …<4 dígitos>: enviado
  (<wamid>)`).

**Teste no número do Álefe** (07/10): `nat_sdr_ligar_agora` com dados de exemplo ("Ana Souza
(TESTE)") para `5583988046720`. A Meta aceitou (`wamid.HBgMNTU4Mzg4MDQ2NzIw...`) e não houve erro
de entrega no log. **A confirmação do recebimento é do Álefe.** O `nat_sdr_corte` fica para quando
o template for aprovado.

## 3. Filtros e "Tratado"

Três filtros rápidos novos no painel, além dos três de `7232fe9`, com badge no card:

| filtro | regra (`app/reuniao_contato.py`) | badge |
|---|---|---|
| Não confirmou | Vigente futura, sem `confirmado_em`, régua viva | "não confirmou", cinza |
| Cancelar na Exact | `cancelado_motivo='sem_confirmacao'`, `exact_type='Vigente'`, sem confirmação e sem `sdr_tratado_em` | "cancelar na Exact", vermelho |
| Devolver ao funil | `regua_encerrada_motivo='d8_sem_resposta'`, sem `sdr_tratado_em` | "devolver ao funil", roxo |

- Os três entram no contador de filtros e no "Limpar filtros". "Não confirmou" ordena pela
  reunião mais próxima.
- **"Cancelar na Exact" e "Devolver ao funil" olham todas as reuniões da pessoa, sem a janela de
  7 dias**, porque o D8 cai 8 dias depois do corte.
- **Botão "Tratado"**: aparece no card quando um desses dois filtros está ativo. Chama
  `POST /api/reunioes/{meeting_id}/tratado`, que grava `sdr_tratado_em` e `sdr_tratado_por` e
  responde 401 sem login. A regra de dono é a das conversas. O card sai do filtro.
- "Cancelar na Exact" também sai sozinho quando o sync vê a reunião `Cancelada`.

**DDL (aprovada no checkpoint 2):** `migrate_sdr_tratado.py`, idempotente.

```
ALTER TABLE reuniao_status ADD COLUMN IF NOT EXISTS sdr_tratado_em TIMESTAMP
ALTER TABLE reuniao_status ADD COLUMN IF NOT EXISTS sdr_tratado_por INTEGER
```

A migração rodou antes do restart, como exigido: o modelo já pede a coluna.

**Consulta:**

```
Seq Scan on reuniao_status (actual time=0.090..0.156 rows=71) ; Rows Removed by Filter: 179
Execution Time: 0.213 ms
```

O casamento com os contatos em Python custa cerca de 21 ms, o mesmo de antes. Hoje: não
confirmou 1 (por conversa), cancelar 0, devolver 0. As réguas começaram hoje, então ainda não
houve corte nem D8.

## 4. ChangeFunnel com a reunião já Cancelada: não medido

Ainda não há nenhum corte (`cancelado_motivo='sem_confirmacao'`: 0 linhas). O primeiro está
agendado para 08/10 às 10:30 (reunião 4774374), e o segundo para 09/10 às 12:00 (4774926).
Nenhuma escrita foi feita na Exact. A medição fica para quando a consultora cancelar uma reunião
cortada.

O passo a passo continua o da sprint:
1. `GET /Meetings?$filter=id eq <id>` mostrando `type` = `Cancelada`;
2. `mudar_funil(lead_id, 197254)`;
3. o mesmo `GET` de novo e a etapa do lead.

Até lá, **nenhum `ChangeFunnel` automático**.

## 5. Testes

Escritos e não executados (só `py_compile`):

- `backend/test_aviso_sdr.py`: normalização, destinatários, `SDR_AVISO_TELEFONES` vazio, falha
  num destino.
- `backend/test_filtros_sdr.py`: os três filtros, com os casos de borda. Inclui quem confirmou
  depois do corte, o sync que viu `Cancelada`, o "Tratado" e o D8 com reunião de mais de 7 dias.

O frontend passou no `tsc --noEmit` e no build.

## 6. O que falta

1. O Álefe confirmar o recebimento do aviso de teste. Depois disso, o merge na `main`.
2. Aprovação do `nat_sdr_corte` na Meta (estava PENDING no deploy). Se o primeiro corte de 08/10
   10:30 chegar antes da aprovação, o aviso falha no log e o corte segue normalmente.
3. O número do SDR em `SDR_AVISO_TELEFONES`.
4. A Fase 4, quando houver uma reunião cortada e já cancelada pela consultora.
