"""CORS por sufixo de domínio, aplicado SÓ em /api/agendamento/*.

------------------------------------------------------------------------------------------
POR QUE NÃO DÁ PARA USAR O CORSMiddleware GLOBAL
------------------------------------------------------------------------------------------
O `CORSMiddleware` do Starlette é da aplicação inteira: `allow_origin_regex` ali valeria
também para `/api/messages`, `/api/nat/config` e todo o resto do Hub — que roda com
`allow_credentials=True` e responde a token. Afrouxar a origem dessas rotas para "qualquer
subdomínio .netlify.app" é exatamente o que não se quer: bastaria um site nesse domínio para
fazer o navegador de um usuário logado disparar requisição autenticada.

A LP precisa de origem larga porque o domínio dela muda (preview do Netlify gera um
subdomínio por deploy). O Hub não precisa de nada disso. São políticas diferentes, e por isso
são middlewares diferentes.

------------------------------------------------------------------------------------------
POR QUE ESTE MIDDLEWARE PRECISA SER O MAIS EXTERNO
------------------------------------------------------------------------------------------
O `CORSMiddleware` global **responde o preflight ele mesmo**: se a origem não estiver na
lista dele, devolve `400 Disallowed CORS origin` e a requisição nunca chega ao router
(`starlette/middleware/cors.py:88` e `:138`). Um sub-app montado em /api/agendamento com CORS
próprio não resolveria — o middleware global responderia antes.

Como `add_middleware` insere na posição 0 e `build_middleware_stack` embrulha em ordem
reversa (`starlette/applications.py:126` e `:92`), **o último `add_middleware` é o mais
externo**. Este precisa ser registrado DEPOIS do `CORSMiddleware` do Hub para conseguir
interceptar o preflight da LP antes dele.

------------------------------------------------------------------------------------------
O QUE ELE NÃO FAZ
------------------------------------------------------------------------------------------
Não manda `Access-Control-Allow-Credentials`. A LP é anônima e não envia cookie nem token;
permitir credenciais em cima de uma faixa larga de origens seria juntar as duas metades do
problema que este arquivo existe para separar.

Caminho que não casa com o prefixo passa direto, sem tocar em header nenhum — o Hub continua
exatamente como estava.
"""
import os
import re

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PREFIXO = "/api/agendamento"

# Sufixos de hospedagem compartilhada: o ápice não é nosso e não pode ser liberado. Um site
# em `netlify.app` (o ápice) é da Netlify, não da CENAT — só os subdomínios interessam.
# Para um domínio próprio vale o contrário: o ápice é justamente o site principal.
SUFIXOS_COMPARTILHADOS = {
    "netlify.app", "vercel.app", "pages.dev", "github.io", "web.app",
    "firebaseapp.com", "onrender.com",
}

PADRAO_ENV = ".cenatsaudemental.com,.netlify.app"


def _regex_do_sufixo(sufixo: str) -> str:
    """`.netlify.app` -> `^https://[a-z0-9-]+\\.netlify\\.app$`

    Sempre `https`: a LP é servida por HTTPS e aceitar `http://` abriria a porta para uma
    origem forjada em rede insegura.

    `[a-z0-9-]+` cobre um rótulo de DNS, que é o que os previews da Netlify usam
    (`deploy-preview-42--site.netlify.app` é UM rótulo, com dois hifens no meio). Não cobre
    subdomínio de subdomínio de propósito — quanto mais estreito, melhor.
    """
    limpo = sufixo.strip().lstrip(".").lower()
    escapado = re.escape(limpo)
    if limpo in SUFIXOS_COMPARTILHADOS:
        return rf"^https://[a-z0-9-]+\.{escapado}$"
    # Domínio próprio: o ápice e um nível de subdomínio.
    return rf"^https://([a-z0-9-]+\.)?{escapado}$"


def compilar_padroes(bruto: str | None = None) -> list[re.Pattern]:
    if bruto is None:
        bruto = os.getenv("AGENDAMENTO_CORS_ORIGIN_SUFFIXES", PADRAO_ENV)
    padroes = []
    for sufixo in (bruto or "").split(","):
        if sufixo.strip():
            padroes.append(re.compile(_regex_do_sufixo(sufixo)))
    return padroes


def origens_exatas(bruto: str | None = None) -> set[str]:
    """`AGENDAMENTO_CORS_ORIGINS` — escape para origens que não casam com sufixo.

    Serve para desenvolvimento (`http://localhost:5500` servindo o obrigado.html) e para
    algum domínio avulso. **Não vai mais para a lista global**: na primeira versão deste
    módulo ele ia, e isso liberava a origem para as rotas autenticadas do Hub também.
    """
    if bruto is None:
        bruto = os.getenv("AGENDAMENTO_CORS_ORIGINS", "")
    return {o.strip() for o in (bruto or "").split(",") if o.strip()}


class AgendamentoCORSMiddleware:
    """CORS por sufixo, restrito ao prefixo do agendamento. ASGI puro."""

    def __init__(self, app: ASGIApp, *, prefixo: str = PREFIXO,
                 padroes: list[re.Pattern] | None = None,
                 exatas: set[str] | None = None,
                 metodos: str = "GET, POST, OPTIONS",
                 max_age: int = 600):
        self.app = app
        self.prefixo = prefixo
        self.padroes = compilar_padroes() if padroes is None else padroes
        self.exatas = origens_exatas() if exatas is None else exatas
        self.metodos = metodos
        self.max_age = max_age

    def origem_permitida(self, origem: str) -> bool:
        if origem in self.exatas:
            return True
        return any(p.match(origem) for p in self.padroes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(self.prefixo):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        origem = headers.get("origin")
        if not origem or not self.origem_permitida(origem):
            # Origem que não reconhecemos segue o caminho normal: o CORSMiddleware global
            # decide. Na prática ele nega, que é o desfecho certo.
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
            await self._preflight(origem, headers, send)
            return

        async def send_com_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                cabecalhos = MutableHeaders(scope=message)
                cabecalhos["Access-Control-Allow-Origin"] = origem
                # `Vary: Origin` é obrigatório com origem variável: sem ele, um cache
                # intermediário serviria a uma origem a resposta liberada para outra.
                cabecalhos.append("Vary", "Origin")
            await send(message)

        await self.app(scope, receive, send_com_cors)

    async def _preflight(self, origem: str, headers: Headers, send: Send) -> None:
        pedidos = headers.get("access-control-request-headers")
        resposta = [
            (b"access-control-allow-origin", origem.encode("latin-1")),
            (b"access-control-allow-methods", self.metodos.encode("latin-1")),
            (b"access-control-max-age", str(self.max_age).encode("latin-1")),
            (b"vary", b"Origin"),
            (b"content-length", b"0"),
        ]
        if pedidos:
            resposta.append(
                (b"access-control-allow-headers", pedidos.encode("latin-1")))
        await send({"type": "http.response.start", "status": 204, "headers": resposta})
        await send({"type": "http.response.body", "body": b""})
