"""CORS por sufixo do agendamento — e a prova de que o Hub NÃO foi relaxado junto.

Rodar: cd backend && venv/bin/python test_agendamento_cors.py

Sem rede e sem banco: as requisições vão direto ao app ASGI, e as rotas usadas são dublês.

  1. os regexes gerados são exatamente os pedidos
  2. preflight da LP em /api/agendamento -> 204 com Allow-Origin e sem Allow-Credentials
  3. preflight da MESMA origem numa rota do Hub -> 400 Disallowed (o Hub segue fechado)
  4. GET simples da LP recebe Allow-Origin e Vary: Origin
  5. origens que NÃO podem: http://, ápice do netlify.app, domínio parecido, subdomínio duplo
  6. o Hub continua funcionando para a origem dele, com credenciais
  7. na aplicação real, o middleware do agendamento é o MAIS EXTERNO
"""
import asyncio

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agendamento.cors import (AgendamentoCORSMiddleware, PREFIXO, _regex_do_sufixo,
                                  compilar_padroes)

LP = "https://obrigado.cenatsaudemental.com"
LP_PREVIEW = "https://deploy-preview-42--cenat.netlify.app"
HUB = "https://hub.cenatdata.online"


def _app():
    """Mesma ordem de registro do main.py: CORS do Hub primeiro, agendamento depois."""
    app = FastAPI()

    @app.get("/api/agendamento/slots")
    async def slots():
        return {"dias": {}}

    @app.post("/api/agendamento/agendar")
    async def agendar():
        return {"ok": True}

    @app.get("/api/nat/config")
    async def hub():
        return {"segredo": "do Hub"}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:3001", HUB],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AgendamentoCORSMiddleware)
    return app


def _cliente(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://teste")


async def _preflight(cli, caminho, origem, metodo="POST"):
    return await cli.options(caminho, headers={
        "Origin": origem,
        "Access-Control-Request-Method": metodo,
        "Access-Control-Request-Headers": "content-type",
    })


# ==========================================================================================


async def caso_1_regexes():
    assert _regex_do_sufixo(".cenatsaudemental.com") == \
        r"^https://([a-z0-9-]+\.)?cenatsaudemental\.com$", _regex_do_sufixo(".cenatsaudemental.com")
    assert _regex_do_sufixo(".netlify.app") == \
        r"^https://[a-z0-9-]+\.netlify\.app$", _regex_do_sufixo(".netlify.app")
    padroes = compilar_padroes(".cenatsaudemental.com,.netlify.app")
    assert len(padroes) == 2
    print("  1. regexes iguais aos pedidos (ápice liberado só no domínio próprio)")


async def caso_2_preflight_lp():
    app = _app()
    async with _cliente(app) as cli:
        for origem in (LP, LP_PREVIEW, "https://cenatsaudemental.com"):
            r = await _preflight(cli, "/api/agendamento/agendar", origem)
            assert r.status_code == 204, (origem, r.status_code, r.text)
            assert r.headers["access-control-allow-origin"] == origem, r.headers
            assert "POST" in r.headers["access-control-allow-methods"]
            assert r.headers.get("vary") == "Origin", r.headers
            # Faixa larga de origens + credenciais seria juntar as duas metades do problema.
            assert "access-control-allow-credentials" not in r.headers, r.headers
    print("  2. preflight da LP (subdomínio, preview e ápice próprio) -> 204, sem credentials")


async def caso_3_hub_segue_fechado():
    """O teste que importa: a mesma origem da LP não pode falar com as rotas do Hub."""
    app = _app()
    async with _cliente(app) as cli:
        for origem in (LP, LP_PREVIEW):
            r = await _preflight(cli, "/api/nat/config", origem, metodo="GET")
            assert r.status_code == 400, \
                f"FALHOU: o Hub aceitou preflight de {origem} — CORS foi relaxado junto"
            assert "Disallowed" in r.text, r.text

            r = await cli.get("/api/nat/config", headers={"Origin": origem})
            assert "access-control-allow-origin" not in r.headers, \
                f"FALHOU: rota do Hub devolveu Allow-Origin para {origem}"
    print("  3. mesma origem numa rota do Hub -> 400 Disallowed, e sem Allow-Origin no GET")


async def caso_4_get_simples():
    app = _app()
    async with _cliente(app) as cli:
        r = await cli.get("/api/agendamento/slots", headers={"Origin": LP_PREVIEW})
        assert r.status_code == 200, r.status_code
        assert r.headers["access-control-allow-origin"] == LP_PREVIEW, r.headers
        assert "Origin" in r.headers.get("vary", ""), r.headers
    print("  4. GET da LP -> 200 com Allow-Origin e Vary: Origin")


async def caso_5_origens_recusadas():
    app = _app()
    proibidas = [
        "http://obrigado.cenatsaudemental.com",   # http puro
        "https://netlify.app",                    # ápice de hospedagem compartilhada
        "https://cenatsaudemental.com.br",        # domínio parecido
        "https://mal.cenatsaudemental.com.evil.com",
        "https://a.b.netlify.app",                # subdomínio de subdomínio
        "https://evil.com",
    ]
    async with _cliente(app) as cli:
        for origem in proibidas:
            r = await _preflight(cli, "/api/agendamento/agendar", origem)
            assert r.status_code == 400, \
                f"FALHOU: aceitou origem proibida {origem} ({r.status_code})"
            r = await cli.get("/api/agendamento/slots", headers={"Origin": origem})
            assert "access-control-allow-origin" not in r.headers, \
                f"FALHOU: devolveu Allow-Origin para {origem}"
    print(f"  5. {len(proibidas)} origens recusadas (http, ápice compartilhado, "
          "domínio parecido, sufixo colado, subdomínio duplo)")


async def caso_6_hub_continua_funcionando():
    app = _app()
    async with _cliente(app) as cli:
        r = await _preflight(cli, "/api/nat/config", HUB, metodo="GET")
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.headers["access-control-allow-origin"] == HUB
        assert r.headers.get("access-control-allow-credentials") == "true", r.headers

        r = await cli.get("/api/nat/config", headers={"Origin": HUB})
        assert r.headers["access-control-allow-origin"] == HUB
    print("  6. Hub continua respondendo à origem dele, com credentials")


async def caso_7_ordem_no_app_real():
    """Sem ser o mais externo, o middleware do Hub responderia o preflight da LP com 400."""
    import app.main as m
    externo = m.app.user_middleware[0].cls
    assert externo is AgendamentoCORSMiddleware, \
        f"FALHOU: o mais externo é {externo.__name__}, não o do agendamento"
    classes = [mw.cls.__name__ for mw in m.app.user_middleware]
    assert "CORSMiddleware" in classes, classes
    rotas = [r.path for r in m.app.routes if getattr(r, "path", "").startswith(PREFIXO)]
    assert len(rotas) == 3, rotas
    print(f"  7. no app real a ordem é {classes} — agendamento por fora")


async def main():
    print("\nCORS do agendamento — sem rede, sem banco\n")
    await caso_1_regexes()
    await caso_2_preflight_lp()
    await caso_3_hub_segue_fechado()
    await caso_4_get_simples()
    await caso_5_origens_recusadas()
    await caso_6_hub_continua_funcionando()
    await caso_7_ordem_no_app_real()
    print("\nOK: 7/7 passaram. A LP abriu; o Hub continua fechado.\n")


if __name__ == "__main__":
    asyncio.run(main())
