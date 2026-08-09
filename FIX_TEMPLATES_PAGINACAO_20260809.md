# Templates do Meta sumindo no Hub — paginação não seguida

**Data:** 09/08/2026
**Sintoma:** o Hub não mostrava todos os templates do WhatsApp que existem no Gerenciador do Meta.

## Diagnóstico

Consulta ao vivo na Graph API, seguindo `paging.next` até o fim:

```
canal 1 — Pós-Graduação (SDR) — waba=1360246076143727
  páginas=2   total=72   por_status={'APPROVED': 72}
```

Resposta do endpoint do Hub, no mesmo momento:

```
GET /api/channels/1/templates?status=all  ->  50 itens
```

O WABA tem **72 templates aprovados**; o Hub entregava **50**. Faltavam 22.

## Causa

`backend/app/routes.py`, `list_templates()`: a chamada pedia `limit: 50` e lia
apenas `data["data"]` da **primeira página**. A Graph API pagina a resposta e
devolve o ponteiro da próxima página em `paging.next` — que o código ignorava.

Ou seja: nunca foi filtro de status nem cache do front. Era teto de página fixo.
O bug ficou dormente enquanto o WABA tinha menos de 50 templates e apareceu
sozinho quando o catálogo cresceu.

Afetava as três telas que consomem o endpoint:

- `frontend/src/app/templates/page.tsx` (`?status=all`)
- `frontend/src/app/automacoes/page.tsx` (`?status=APPROVED`)
- `frontend/src/app/conversations/page.tsx` (seletor de template na conversa)

## Correção

`list_templates()` agora percorre a paginação:

- `limit` de 50 → 100 por página;
- laço que segue `paging.next` até acabar, com teto de 20 páginas (2.000 templates)
  para não girar indefinidamente se o Meta devolver ponteiro circular;
- o header `Authorization` é reenviado em cada página;
- erro do Meta (`data["error"]`) agora vira **502** com a mensagem original, em vez
  de virar silenciosamente uma lista vazia.

`fetch_template_body()` em `whatsapp.py` não foi alterado: ele consulta com filtro
`name=<template>`, então o resultado nunca passa de uma página.

## Verificação

Instância de teste na porta 8009 (a produção na 8001 não foi tocada):

```
GET /api/channels/1/templates?status=all       ->  72 itens
GET /api/channels/1/templates?status=APPROVED  ->  72 itens
```

Bate com os 72 contados direto no Meta.

## Pendência

O backend em produção (uvicorn na porta **8001**) roda **sem `--reload`**: a correção
só passa a valer depois de reiniciar o serviço.
