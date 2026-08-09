# Busca de template no Hub — páginas de Templates e Automações

**Data:** 09/08/2026
**Motivo:** com 72 templates aprovados no WABA, achar um significava rolar a lista inteira.
Complementa o [FIX_TEMPLATES_PAGINACAO_20260809.md](FIX_TEMPLATES_PAGINACAO_20260809.md), que fez
os 72 aparecerem — sem busca, aparecer todos só piorou a rolagem.

## O que foi feito

### Página de Templates (`/templates`)

- Campo de busca na barra de controles, ao lado do seletor de canal e do botão *Atualizar*.
- Filtra por **nome, texto do corpo, categoria, idioma e status** (em português: buscar
  `rejeitado` acha os REJECTED).
- Botão “×” para limpar; contador ao lado dos controles (`12 de 72 templates`).
- Estado vazio próprio quando a busca não acha nada, com atalho para limpar.

### Página de Automações (`/automacoes`)

Dois seletores de template, os dois ganharam busca:

1. **Boas-vindas automática** — campo de busca acima do `<select>`, filtrando as opções.
   O template **salvo na configuração entra sempre na lista**, mesmo que não bata com o
   filtro: filtrar a tela não pode, em hipótese alguma, trocar o que está configurado.
2. **Disparo em massa** (coluna esquerda) — campo de busca acima da lista de cartões,
   com “×” para limpar e contador `X de Y`. Trocar de canal limpa a busca junto com a lista.

### Regras da busca (as duas páginas)

- Ignora acento e maiúscula/minúscula.
- `_` no nome conta como espaço: buscar `boas vindas` acha `nat_boasvindas`.
- Vários termos = **E** (todos precisam bater), em qualquer ordem.
- Filtro é só de exibição — roda no cliente, sobre a lista já carregada do Meta. Não altera
  envio, não altera configuração salva, não faz chamada nova à Graph API.
- Templates bloqueados (boas-vindas automática) continuam aparecendo bloqueados no
  disparo em massa; a busca não muda esse comportamento.

## Arquivos

- `frontend/src/app/templates/page.tsx`
- `frontend/src/app/automacoes/page.tsx`

## Verificação

- `npx tsc --noEmit` — sem erros.
- `npm run build` — build completo, 16 rotas.
- `cenat-frontend.service` reiniciado; `/templates` e `/automacoes` respondendo 200.
