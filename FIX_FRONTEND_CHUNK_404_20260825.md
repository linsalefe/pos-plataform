# Fix: ChunkLoadError 404 no hub — processo Next dessincronizado do disco (reincidência)

**Data:** 2026-08-25
**Serviço afetado:** `cenat-frontend` (hub.cenatdata.online)
**Sintoma reportado:** console do navegador com 404 em CSS e JS + `ChunkLoadError`

## Sintoma

```
2205ec623a6bfa71.css:1   Failed to load resource: 404 (Not Found)
cedd993c6e911824.js:1    Failed to load resource: 404 (Not Found)
turbopack-78697e86690b0c7d.js:1  Uncaught ChunkLoadError:
    Failed to load chunk /_next/static/chunks/cedd993c6e911824.js from module 64893
favicon.ico:1            Failed to load resource: 404 (Not Found)
```

## Diagnóstico

Mesma causa raiz do incidente de 17/08 (`FIX_FRONTEND_CSS_500_20260817.md`),
com os papéis invertidos: agora o **disco estava à frente do processo**.

| Item | Estado antes do fix |
|---|---|
| `cenat-frontend` ativo desde | 03:06 UTC |
| `.next/` reconstruído em | 03:40 UTC |
| `BUILD_ID` no disco | `7dcEYkRJaHE33M3FvIsS1` |
| CSS que o processo servia no HTML | `6d56f8743cefb471.css` (build de 17/08) |
| CSS que o navegador pedia | `2205ec623a6bfa71.css` (build de 03:40) |

O `.next/` foi reconstruído às 03:40 (Bloco B do espontâneo, rota
`/agendar/[token]`) **sem restart do serviço**. O processo de 03:06 continuou
com o manifest antigo em memória.

Confirmado direto na porta 3001, sem nginx no caminho:

```
200  http://127.0.0.1:3001/login
404  http://127.0.0.1:3001/_next/static/chunks/cedd993c6e911824.js
HTML servido apontava para: _next/static/chunks/6d56f8743cefb471.css
```

O navegador tinha HTML em cache do build novo e pedia chunks que o processo
em memória não conhecia → 404 → `ChunkLoadError` → página não montava.

Não era nginx, TLS, rede nem backend (`/health` → 200 o tempo todo).
Era processo desatualizado em relação ao disco.

### Erros benignos no mesmo console

- `favicon.ico → 404`: não há favicon no projeto. Cosmético.
- `Web Data Assistant load: "tma_vars"`: extensão do navegador, não é a aplicação.

## Correção aplicada

Working tree limpo, nenhum fonte mais novo que o `BUILD_ID` — um restart puro
resolveria. Optou-se por rebuild + restart para deixar processo e disco no
mesmo `BUILD_ID` e fechar a janela de dessincronia.

```bash
cd /home/ubuntu/pos-plataform/frontend
NODE_ENV=production npm run build     # 16 páginas, inclui ƒ /agendar/[token]
sudo systemctl restart cenat-frontend.service
```

`BUILD_ID`: `7dcEYkRJaHE33M3FvIsS1` -> `NiYDeWvvz7xjYxN25mFi6`
Serviço ativo desde 12:43:47 UTC, MainPID 1583226.

## Validação (via domínio público)

```
12 assets do /login (1 CSS + 11 JS)          -> todos 200
_next/static/chunks/2205ec623a6bfa71.css     -> 200  (era 404)
_next/static/chunks/cedd993c6e911824.js      -> 200  (era 404)
/ /login /dashboard /conversations /agenda   -> 200
/kanban /templates /leads-pos /automacoes    -> 200
/agendar/tokeninvalido  (Bloco B, público)   -> 200
/health                                      -> {"status":"online"}
/api/auth/me                                 -> 401 (esperado, sem login)
```

Usuário deve dar hard refresh (Ctrl+Shift+R) para descartar o HTML em cache.

## Prevenção — reincidência confirmada

Segunda ocorrência do mesmo modo de falha em 8 dias. A regra já estava escrita
no doc de 17/08 e foi violada de novo: **`npm run build` sem restart**.

Regra, sempre como um comando só:

```bash
cd /home/ubuntu/pos-plataform/frontend && \
  NODE_ENV=production npm run build && \
  sudo systemctl restart cenat-frontend.service
```

Fumaça depois de qualquer deploy de frontend:

```bash
ASSETS=$(curl -s https://hub.cenatdata.online/login | grep -o '_next/static/[^"]*\.\(css\|js\)' | sort -u)
for a in $ASSETS; do curl -s -o /dev/null -w "%{http_code} $a\n" "https://hub.cenatdata.online/$a"; done
```

Qualquer código diferente de 200 = processo dessincronizado do disco.

## Referência de infraestrutura

- frontend: `cenat-frontend.service`, `next start -p 3001`, WorkingDirectory `/home/ubuntu/pos-plataform/frontend`
- backend: `cenat-backend.service`, porta 8001
- nginx `/etc/nginx/sites-enabled/cenat-hub`: `/api/` e `/health` -> 8001, restante -> 3001
