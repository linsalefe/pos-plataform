# Rotas sem login: levantamento e correção (07/10/2026)

**Achado:** `GET /api/contacts/{id}/messages` respondia sem login, e o levantamento completo achou
**56 rotas abertas**, várias delas de escrita. **41 foram protegidas**; as 15 restantes são
webhook, API pública da LP, login e health.

## Como foi levantado

Leitura do AST de `routes.py`, `nat_routes.py`, `exact_routes.py`, `kanban_routes.py`,
`calendar_routes.py`, `twilio_routes.py`, `agendamento/routes.py`, e também de `ai_routes.py`,
`auth_routes.py`, `auto_welcome_routes.py`, `relatorios.py` e `main.py`.

Uma rota conta como protegida quando há `Depends(get_current_user)` ou `Depends(get_current_admin)`
em algum destes lugares: nos parâmetros, no `dependencies=` do decorator, no `APIRouter`, ou numa
dependência que exige login por sua vez.

`nat_routes.py` e `relatorios.py` já estavam 100% protegidos.

## Antes: 56 rotas abertas

| arquivo | rotas abertas |
|---|---|
| `routes.py` | `GET /channels` · `POST /channels` · `GET /dashboard/stats` · `GET /contacts/{wa_id}` · **`PATCH /contacts/{wa_id}`** · `POST /contacts/{wa_id}/tags/{tag_id}` · `DELETE /contacts/{wa_id}/tags/{tag_id}` · `POST /contacts/{wa_id}/read` · **`GET /contacts/{wa_id}/messages`** · `GET /tags` · `POST /tags` · `DELETE /tags/{tag_id}` · `GET /channels/{id}/templates` · **`GET /media/{media_id}`** · `GET /course-aliases` · `GET /course-aliases/resolve/{alias}` |
| `exact_routes.py` | `GET /exact-leads` · `POST /exact-leads/sync` · `GET /exact-leads/stats` · `GET /exact-leads/funnels` · `GET /exact-leads/{id}/details` |
| `kanban_routes.py` | `GET /cards` · `GET /stats` · `PATCH /cards/{id}/move` · `PATCH /cards/{id}` · `POST /cards/{id}/generate-summary` |
| `calendar_routes.py` | `GET /consultants` · `GET /available-dates/{c}` · `GET /available-slots/{c}/{d}` · `POST /book` |
| `ai_routes.py` | `GET /config/{ch}` · `PUT /config/{ch}` · `PATCH /contacts/{wa_id}/toggle` · `GET /documents/{ch}` · `POST /documents/{ch}` · `DELETE /documents/{ch}/{t}` · `POST /test-chat` |
| `auto_welcome_routes.py` | `GET /config` · `GET /blocked-templates` · `GET /preview` |
| `twilio_routes.py` | **`GET /recording/{call_sid}`** (áudio das ligações) · 5 webhooks |
| `agendamento/routes.py` | 6 rotas públicas da LP |
| `auth_routes.py`, `main.py` | `POST /login` · `GET /webhook` · `POST /webhook` · `GET /health` |

**Houve acesso indevido?** Nos 3 dias de log disponíveis, todo IP que chamou
`/contacts/{id}/messages` também tinha login válido no mesmo período. Não há sinal de acesso de
fora. O log não vai além de 3 dias, então isso não vale para antes.

## Depois: 15 rotas abertas, todas de propósito

| rota | por que fica aberta |
|---|---|
| `POST /api/twilio/voice`, `/voice-outbound`, `/call-status`, `/recording-status`, `/voice-incoming` | webhooks chamados pelo Twilio |
| `GET /api/agendamento/slots`, `POST /agendar`, `POST /lead`, `GET /espontaneo/{segredo}`, `POST /espontaneo/{segredo}/agendar`, `POST /espontaneo/{segredo}/lead` | API pública da LP (o "espontâneo" é protegido pelo segredo do link) |
| `POST /api/auth/login` | login |
| `GET /webhook`, `POST /webhook` | webhook da Meta (o GET confere o `verify_token`: 403 com token errado) |
| `GET /health` | health check |

## Como foi protegido

- **39 rotas do Hub:** `dependencies=[Depends(get_current_user)]` no decorator. Nenhuma assinatura
  de função mudou. É o mesmo `get_current_user` das outras rotas, então devolve o mesmo 401
  "Not authenticated".
- **`/media/{id}` e `/twilio/recording/{call_sid}`:** usam o novo
  `auth.get_current_user_header_ou_url`, o mesmo login com o token aceito também em `?token=`.
  `<img>`, `<audio>`, `<video>` e `window.open` não mandam header, e sem isso essas rotas teriam
  de continuar abertas. O frontend anexa o token nas 6 URLs de mídia (`conversations/page.tsx`)
  e na da gravação (`calls/page.tsx`).
- **`/agenda`:** usava `fetch` cru para `/calendar`; passou para o cliente `api`, que manda o
  login.

## Verificação (curl, depois do restart)

```
41 rotas recém-protegidas, SEM token ......... 41 × 401
/media/123?token=xyz, /twilio/recording/CAx?token=xyz ... 401, 401
com token válido no header: /contacts/{id}/messages 200 · /contacts 200 · /exact-leads/stats 200
/media/<id real>?channel_id=1&token=<válido> ... 200 audio/ogg 14395B ; sem token ... 401
públicas: /api/agendamento/slots 200 · /health 200 · /webhook (verify_token errado) 403
```

Tráfego real depois do deploy (15:01 UTC): os 3 navegadores do time com 200 em `/contacts`,
`/contacts/{id}/messages`, `/nat/{id}/estado` e `/notifications`, e nenhum 401.

## Riscos que continuam (não corrigidos aqui)

1. **Webhooks do Twilio sem verificação de assinatura** (`X-Twilio-Signature`). Qualquer um que
   conheça a URL pode chamar `/call-status` e `/recording-status`.
2. **Login sem checagem de dono.** Um SDR logado lê as mensagens de qualquer contato pela URL. A
   lista (`GET /contacts`) filtra por `assigned_to` para quem não é admin, mas
   `/contacts/{id}/messages` não filtra.
3. **Token na URL** da mídia e da gravação: fica no histórico do navegador e no log do nginx. O
   token expira em 24h. A alternativa sem esse custo é baixar a mídia com o `api` e exibir por
   `blob:`, o que dá mais trabalho no frontend.
4. **Kanban IA e `/api/ai`** são do motor de IA antigo, que está desligado. Agora estão protegidos,
   mas candidatos a sair do código.
