# Fix: CSS 500 no hub — processo Next servindo build apagado

**Data:** 2026-08-17
**Serviço afetado:** `cenat-frontend` (hub.cenatdata.online)
**Sintoma reportado:** console do navegador com `e5aa01708428abad.css:1 Failed to load resource: 500`

## Sintoma

Console da página de login:

```
e5aa01708428abad.css:1  Failed to load resource: status 500 (Internal Server Error)
api/auth/me:1           Failed to load resource: status 401 (Unauthorized)
caa3a2e1cccd8315-s.p.3b6cae6d.woff2 was preloaded but not used...
```

## Diagnóstico

Só o **500 do CSS** era problema real.

| Serviço | Estado | Ativo desde |
|---|---|---|
| `cenat-backend` | OK, `/health` → 200 `{"status":"online"}` | 2026-08-17 20:01 UTC |
| `cenat-frontend` | ativo, **servindo build inexistente** | 2026-08-09 19:40 UTC |
| `nginx` | OK | — |
| `postgresql@14-main` | OK | — |

### Causa raiz

O processo `next-server` (pid 1415070) subiu em **09/ago 19:40** e carregou o
build-manifest daquele build em memória.

Em **14/ago 20:38** o diretório `.next/` foi reconstruído por baixo do processo
em execução. O rebuild apagou os assets do build antigo do disco.

O processo continuou entregando HTML apontando para
`_next/static/chunks/e5aa01708428abad.css` — arquivo que **não existia mais**.
O disco tinha `6d56f8743cefb471.css` (BUILD_ID `A9hwoYm9bYnvABXmLE9aQ`), que o
processo em memória desconhecia.

Confirmado direto na porta 3001, sem nginx no caminho:

```
3001 css antigo (e5aa...):   500   <- o que o HTML pedia
3001 css do disco (6d56...): 404   <- o que existia, mas o processo ignorava
```

Não era nginx, rede, TLS nem backend. Era processo desatualizado em relação ao disco.

### Erros benignos no mesmo console

- `api/auth/me → 401`: correto, sessão não autenticada. Backend respondendo bem.
- `woff2 preloaded but not used`: aviso de performance do Next, não quebra nada.

## Correção aplicada

`frontend/src/app/conversations/page.tsx` havia sido alterado **depois** do build
de 14/ago. Um restart puro resolveria o CSS mas serviria essa página desatualizada.
Optou-se por rebuild + restart.

```bash
cd /home/ubuntu/pos-plataform/frontend
NODE_ENV=production npm run build     # compilou em 28.5s, 16 páginas estáticas
sudo systemctl restart cenat-frontend.service
```

BUILD_ID: `A9hwoYm9bYnvABXmLE9aQ` -> `L67nlk9560S9hMgAiQO5J`

## Validação (via domínio público)

```
CSS referenciado pelo HTML: _next/static/chunks/6d56f8743cefb471.css -> 200
hash antigo e5aa01708428abad.css -> 404 (e removido do HTML)
11 chunks JS da página de login -> todos 200
rotas / /login /dashboard /conversations /agenda /kanban /templates -> todas 200
/health -> 200
/api/auth/me -> 401 (esperado, sem login)
```

Usuário deve dar hard refresh (Ctrl+Shift+R) para limpar o HTML em cache.

## Prevenção

O modo de falha é **rebuildar `.next/` sem reiniciar o serviço**. Enquanto o
processo vive, ele serve um manifest que aponta para arquivos já apagados —
e o sintoma só aparece para quem carrega a página depois do rebuild.

Regra: `npm run build` no frontend **sempre** seguido de
`sudo systemctl restart cenat-frontend.service`.

```bash
\
  NODE_ENV=production npm run build && \
  sudo systemctl restart cenat-frontend.service
```

Checagem rápida de fumaça depois de qualquer deploy:

```bash
CSS=$(curl -s https://hub.cenatdata.online/login | grep -o '_next/static/[^"]*\.css' | sort -u)
for c in $CSS; do curl -s -o /dev/null -w "%{http_code} $c\n" "https://hub.cenatdata.online/$c"; done
```

Se o CSS do HTML não der 200, o processo está dessincronizado do disco.

## Referência de infraestrutura

- frontend: `cenat-frontend.service`, `npm start -- -p 3001`, WorkingDirectory `/home/ubuntu/pos-plataform/frontend`
- backend: `cenat-backend.service`, porta 8001
- nginx `/etc/nginx/sites-enabled/cenat-hub`: `/api/` e `/health` -> 8001, restante -> 3001
