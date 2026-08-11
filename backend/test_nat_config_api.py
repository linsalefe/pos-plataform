"""Fase 4 do sprint de ativação: o kill switch da NAT por HTTP.

Rodar: cd backend && venv/bin/python test_nat_config_api.py

App REAL (rotas, dependências e validação de verdade), banco trocado por um dublê. Sem
lifespan — o TestClient fora do `with` não dispara startup, então nenhum job de background
sobe e nada é enviado.

  1. GET  /config sem token          -> 401, e sem token não-admin -> 403
  2. PATCH /config sem token         -> 401, com token não-admin   -> 403, nada gravado
  3. LIGAR sem nat_start_at          -> 422 (ligada sem corte não atua, e parece que atua)
  4. "agora" grava UTC, não SP       -> o corte NÃO fica 3h no passado
  5. data ISO sem fuso               -> 422 (é a armadilha que criaria lead retroativo)
  6. campo desconhecido              -> 422 ({"nat_enable": false} não pode dar 200)
  7. max_envios_hora inválido        -> 422; e 0 é aceito (estrangulamento deliberado)
  8. DESLIGAR sempre passa           -> o caminho de emergência não tem validação no meio
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.models import NatConfig
from app.nat_guard import SP_TZ

falhas = []


def check(nome, condicao, detalhe=""):
    print(f"  {'✅' if condicao else '❌'} {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


def _config(enabled=False, start_at=None, teto=20):
    cfg = NatConfig(id=1, nat_enabled=enabled, nat_start_at=start_at, max_envios_hora=teto)
    cfg.updated_at = datetime(2026, 7, 25, 21, 49, 42)
    return cfg


class _DbFalso:
    def __init__(self, cfg):
        self.cfg = cfg
        self.commits = 0

    async def execute(self, *a, **k):
        res = MagicMock()
        res.scalar_one_or_none.return_value = self.cfg
        return res

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


def _client(cfg, *, usuario=None):
    """App real com o banco dublado. `usuario=None` = anônimo (nenhum login injetado)."""
    from app.main import app
    from app.auth import get_current_user
    from app.database import get_db

    db = _DbFalso(cfg)

    async def _db_override():
        yield db

    app.dependency_overrides[get_db] = _db_override
    if usuario is not None:
        app.dependency_overrides[get_current_user] = lambda: usuario
    return app, TestClient(app), db


def _usuario(role="admin", uid=1, nome="Álefe Lins"):
    return MagicMock(id=uid, name=nome, role=role, is_active=True)


def _limpar(app):
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------------------
async def caso_1_get_exige_admin():
    cfg = _config()
    app, client, _ = _client(cfg)                      # anônimo
    r_anon = client.get("/api/nat/config")
    _limpar(app)

    app, client, _ = _client(cfg, usuario=_usuario(role="atendente", uid=8, nome="Ana"))
    r_atendente = client.get("/api/nat/config")
    _limpar(app)

    app, client, _ = _client(cfg, usuario=_usuario())
    r_admin = client.get("/api/nat/config")
    _limpar(app)

    check("GET sem token -> 401", r_anon.status_code == 401, f"HTTP {r_anon.status_code}")
    check("GET com não-admin -> 403", r_atendente.status_code == 403,
          f"HTTP {r_atendente.status_code}")
    check("GET com admin -> 200", r_admin.status_code == 200, f"HTTP {r_admin.status_code}")
    corpo = r_admin.json()
    check("resposta traz os 3 campos + atuando",
          {"nat_enabled", "nat_start_at", "max_envios_hora", "atuando"} <= set(corpo),
          f"{sorted(corpo)}")
    check("NAT desligada e sem corte -> atuando=False", corpo["atuando"] is False)


async def caso_2_patch_exige_admin():
    cfg = _config()
    app, client, db = _client(cfg)                     # anônimo
    r_anon = client.patch("/api/nat/config", json={"nat_enabled": True})
    _limpar(app)
    check("PATCH sem token -> 401", r_anon.status_code == 401, f"HTTP {r_anon.status_code}")
    check("anônimo não gravou nada", db.commits == 0 and cfg.nat_enabled is False)

    app, client, db = _client(cfg, usuario=_usuario(role="atendente", uid=8, nome="Ana"))
    r_ana = client.patch("/api/nat/config", json={"nat_enabled": True})
    _limpar(app)
    check("PATCH com não-admin -> 403", r_ana.status_code == 403, f"HTTP {r_ana.status_code}")
    check("não-admin não ligou a NAT", db.commits == 0 and cfg.nat_enabled is False,
          f"nat_enabled={cfg.nat_enabled}")


async def caso_3_ligar_sem_corte_e_recusado():
    """nat_enabled=true com nat_start_at nulo: o painel diria LIGADA e o guard bloquearia
    100% dos leads em "nat_start_at não definido". É o pior desfecho: parece que funciona."""
    cfg = _config(enabled=False, start_at=None)
    app, client, db = _client(cfg, usuario=_usuario())
    r = client.patch("/api/nat/config", json={"nat_enabled": True})
    _limpar(app)

    check("ligar sem corte -> 422", r.status_code == 422, f"HTTP {r.status_code}")
    check("nada foi gravado", db.commits == 0 and cfg.nat_enabled is False)
    check("a mensagem explica o que fazer", "nat_start_at" in r.json()["detail"],
          r.json()["detail"][:80])

    # Os dois juntos passam.
    app, client, db = _client(cfg, usuario=_usuario())
    r2 = client.patch("/api/nat/config",
                      json={"nat_enabled": True, "nat_start_at": "agora"})
    _limpar(app)
    check("ligar COM corte no mesmo PATCH -> 200", r2.status_code == 200,
          f"HTTP {r2.status_code}")
    check("atuando=True só agora", r2.json()["atuando"] is True)


async def caso_4_agora_grava_utc():
    """A trava compara nat_start_at com register_date, que é UTC (date_parse.parse_datetime).
    Gravar o relógio de São Paulo poria o corte 3h no passado e deixaria entrar todo lead
    registrado nas 3 horas anteriores — retroativo, contra a decisão nº 2 do sprint."""
    cfg = _config()
    app, client, _ = _client(cfg, usuario=_usuario())
    antes_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    r = client.patch("/api/nat/config",
                     json={"nat_enabled": True, "nat_start_at": "agora"})
    depois_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    _limpar(app)

    gravado = cfg.nat_start_at
    check("gravou entre o antes e o depois em UTC", antes_utc <= gravado <= depois_utc,
          f"gravado={gravado} utc_agora={depois_utc}")

    agora_sp = datetime.now(SP_TZ).replace(tzinfo=None)
    check("NÃO gravou o relógio de São Paulo (evita 3h de leads retroativos)",
          abs((gravado - agora_sp).total_seconds()) > 3000,
          f"gravado={gravado} sp={agora_sp} diferença={(gravado - agora_sp)}")

    corpo = r.json()
    check("resposta mostra o corte nos dois fusos, para conferência",
          corpo["nat_start_at"] and corpo["nat_start_at_sp"],
          f"UTC={corpo['nat_start_at']} SP={corpo['nat_start_at_sp']}")

    # ISO com fuso explícito também é aceito e convertido.
    app, client, _ = _client(cfg, usuario=_usuario())
    client.patch("/api/nat/config", json={"nat_start_at": "2026-08-11T12:00:00-03:00"})
    _limpar(app)
    check("'-03:00' vira 15:00 UTC", cfg.nat_start_at == datetime(2026, 8, 11, 15, 0),
          f"{cfg.nat_start_at}")


async def caso_5_data_sem_fuso_recusada():
    cfg = _config(enabled=False, start_at=datetime(2026, 8, 1))
    app, client, db = _client(cfg, usuario=_usuario())
    r = client.patch("/api/nat/config", json={"nat_start_at": "2026-08-11T12:00:00"})
    _limpar(app)

    check("ISO sem fuso -> 422", r.status_code == 422, f"HTTP {r.status_code}")
    check("corte antigo intacto", cfg.nat_start_at == datetime(2026, 8, 1) and db.commits == 0)
    check("a mensagem explica a ambiguidade", "fuso" in r.json()["detail"].lower(),
          r.json()["detail"][:100])


async def caso_6_campo_desconhecido():
    """Num endpoint feito para desligar coisas às pressas, um typo aceito em silêncio
    devolveria 200 com a NAT ainda ligada."""
    cfg = _config(enabled=True, start_at=datetime(2026, 8, 1))
    app, client, db = _client(cfg, usuario=_usuario())
    r = client.patch("/api/nat/config", json={"nat_enable": False})     # falta o 'd'
    _limpar(app)

    check("campo desconhecido -> 422", r.status_code == 422, f"HTTP {r.status_code}")
    check("a NAT NÃO foi silenciosamente deixada ligada com 200",
          cfg.nat_enabled is True and db.commits == 0)
    check("a mensagem diz quais campos valem", "nat_enabled" in r.json()["detail"],
          r.json()["detail"][:90])

    app, client, _ = _client(cfg, usuario=_usuario())
    r_vazio = client.patch("/api/nat/config", json={})
    _limpar(app)
    check("corpo vazio -> 422", r_vazio.status_code == 422, f"HTTP {r_vazio.status_code}")


async def caso_7_teto():
    cfg = _config(enabled=False, start_at=datetime(2026, 8, 1), teto=20)

    for valor in (-1, "20", 3.5, True):
        app, client, db = _client(cfg, usuario=_usuario())
        r = client.patch("/api/nat/config", json={"max_envios_hora": valor})
        _limpar(app)
        check(f"max_envios_hora={valor!r} -> 422", r.status_code == 422,
              f"HTTP {r.status_code}")
    check("teto intacto depois das recusas", cfg.max_envios_hora == 20,
          f"{cfg.max_envios_hora}")

    app, client, _ = _client(cfg, usuario=_usuario())
    r = client.patch("/api/nat/config", json={"max_envios_hora": 0})
    _limpar(app)
    check("teto 0 é aceito (estrangulamento deliberado, sem desligar)",
          r.status_code == 200 and cfg.max_envios_hora == 0, f"HTTP {r.status_code}")


async def caso_8_desligar_sempre_passa():
    """O caminho de emergência. Nenhuma validação pode ficar entre o operador e o desligar."""
    cfg = _config(enabled=True, start_at=datetime(2026, 8, 1), teto=20)
    app, client, db = _client(cfg, usuario=_usuario())
    r = client.patch("/api/nat/config", json={"nat_enabled": False})
    _limpar(app)

    check("desligar -> 200", r.status_code == 200, f"HTTP {r.status_code}")
    check("nat_enabled virou False", cfg.nat_enabled is False)
    check("atuando=False", r.json()["atuando"] is False)
    check("o corte NÃO foi apagado junto (religar não perde o histórico)",
          cfg.nat_start_at == datetime(2026, 8, 1), f"{cfg.nat_start_at}")

    # Desligar de novo é inofensivo.
    app, client, _ = _client(cfg, usuario=_usuario())
    r2 = client.patch("/api/nat/config", json={"nat_enabled": False})
    _limpar(app)
    check("desligar duas vezes -> 200, idempotente", r2.status_code == 200,
          f"HTTP {r2.status_code}")


async def main():
    print("\nFase 4 — kill switch por HTTP (app real, banco falso, nenhum job de background)\n")
    print("1) GET /config exige admin");            await caso_1_get_exige_admin()
    print("2) PATCH /config exige admin");          await caso_2_patch_exige_admin()
    print("3) ligar sem corte de data");            await caso_3_ligar_sem_corte_e_recusado()
    print("4) 'agora' grava UTC, não SP");          await caso_4_agora_grava_utc()
    print("5) data sem fuso é recusada");           await caso_5_data_sem_fuso_recusada()
    print("6) campo desconhecido não passa");       await caso_6_campo_desconhecido()
    print("7) max_envios_hora");                    await caso_7_teto()
    print("8) DESLIGAR sempre passa");              await caso_8_desligar_sempre_passa()

    print()
    if falhas:
        print(f"❌ {len(falhas)} falha(s): {falhas}")
        raise SystemExit(1)
    print("OK: o kill switch exige admin, recusa o que é ambíguo e nunca barra o desligar.\n")


if __name__ == "__main__":
    asyncio.run(main())
