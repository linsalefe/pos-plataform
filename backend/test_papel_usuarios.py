"""Papel de usuário, tag `Vagas afirmativas` e destinos de SDR (24/10/2026).

    cd backend && venv/bin/python test_papel_usuarios.py

Escrito e NÃO executado na sprint de 24/10. Offline: o banco é dublê.

O QUE ESTE TESTE PROVA
  1. `sdr_ids` lê `users.papel='sdr'` ativos do banco
  2. banco vazio -> reserva `SDR_USER_IDS`; sem ela, `SDR_PADRAO` (Thobias)
  3. falha na consulta -> reserva, sem levantar e sem rollback na sessão de quem chamou
  4. `remarcacao.destinatarios` sem dono = SDRs do papel + gestão; com dono = só o dono
  5. conta 3 inativa não aparece: o filtro da consulta exige `is_active`
  6. `e_template_de_vagas`: casa os 4 templates da régua, ignora o resto
  7. `marcar_vagas` aplica a tag em savepoint e nunca levanta
  8. regra do filtro da tela (espelho em Python de `passaNoPapel`, conversations/page.tsx):
     sdr esconde a rajada da consultora e mostra quem respondeu; consultora vê vagas e os dela
  9. papel inválido na rota de usuários vira 400
"""
import asyncio
import io
import os
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app import remarcacao, tags_auto, usuarios
from app.auth_routes import _papel_valido

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


class _Db:
    def __init__(self, ids=(), falhar=False):
        self.ids = list(ids)
        self.falhar = falhar
        self.statements = []
        self.rollbacks = 0

    async def execute(self, stmt, *a, **k):
        self.statements.append(stmt)
        if self.falhar:
            raise RuntimeError("coluna papel não existe")
        res = MagicMock()
        res.scalars.return_value.all.return_value = self.ids
        return res

    async def rollback(self):
        self.rollbacks += 1

    def begin_nested(self):
        db = self

        class _Sp:
            async def __aenter__(self_):
                return db

            async def __aexit__(self_, *exc):
                return False
        return _Sp()


async def caso_1_do_banco():
    db = _Db(ids=[5])
    checa("SDRs do banco", await usuarios.sdr_ids(db), [5])
    sql = str(db.statements[0].compile(compile_kwargs={"literal_binds": True}))
    checa("filtra papel", "users.papel = 'sdr'" in sql, True)


async def caso_2_reserva():
    os.environ["SDR_USER_IDS"] = "5,4"
    with redirect_stdout(io.StringIO()):
        checa("reserva do .env", await usuarios.sdr_ids(_Db(ids=[])), [5, 4])
    os.environ.pop("SDR_USER_IDS")
    with redirect_stdout(io.StringIO()):
        checa("reserva padrão", await usuarios.sdr_ids(_Db(ids=[])), list(usuarios.SDR_PADRAO))


async def caso_3_falha():
    db = _Db(falhar=True)
    saida = io.StringIO()
    with redirect_stdout(saida):
        r = await usuarios.sdr_ids(db)
    checa("falha cai na reserva", r, list(usuarios.SDR_PADRAO))
    checa("sem rollback na sessão alheia", db.rollbacks, 0)
    checa("log da falha", "não consegui ler papel=sdr" in saida.getvalue(), True)


async def caso_4_destinatarios():
    existe = AsyncMock(return_value=True)
    with patch("app.nat_flow.usuario_existe", existe), \
         patch.object(usuarios, "sdr_ids", AsyncMock(return_value=[5])):
        sem_dono = await remarcacao.destinatarios("5583988046720", _Db(), dono=None,
                                                  consultar_dono=False)
        com_dono = await remarcacao.destinatarios("5583988046720", _Db(), dono=6,
                                                  consultar_dono=False)
    checa("sem dono: SDR + gestão", sem_dono, [5, remarcacao.GESTOR_USER_ID])
    checa("com dono: só ele", com_dono, [6])


async def caso_5_inativo():
    db = _Db(ids=[5])
    await usuarios.ids_do_papel(db, usuarios.PAPEL_SDR)
    sql = str(db.statements[0].compile(compile_kwargs={"literal_binds": True}))
    checa("exige is_active", "users.is_active IS true" in sql, True)


async def caso_6_templates():
    for nome in ("vagasafirmativas_1", "follow1_vagasafirmativas_apresentacao",
                 "follow2_vagasafirmativas_acompanhamento", "follow3_vagasafirmativas_despedida"):
        checa(f"vagas: {nome}", tags_auto.e_template_de_vagas(nome), True)
    for nome in ("mensagem_follow7", "tentativa_contato", None, ""):
        checa(f"não vagas: {nome!r}", tags_auto.e_template_de_vagas(nome), False)


async def caso_7_marcar():
    db = _Db()
    checa("aplica", await tags_auto.marcar_vagas(db, "5583988046720", "vagasafirmativas_1"), True)
    checa("dois INSERTs", len(db.statements), 2)
    checa("template comum não toca", await tags_auto.marcar_vagas(_Db(), "558", "outro"), False)
    with redirect_stdout(io.StringIO()):
        checa("falha não levanta",
              await tags_auto.marcar_vagas(_Db(falhar=True), "558", "vagasafirmativas_1"), False)


def passa_no_papel(c, papel, uid, papel_de):
    """Espelho de `passaNoPapel` em frontend/src/app/conversations/page.tsx."""
    vagas = any(t["name"] == tags_auto.TAG_VAGAS for t in c["tags"])
    if papel == "sdr":
        return not (vagas and c["direction"] == "outbound"
                    and papel_de(c.get("last_sent_by")) == "consultora")
    if papel == "consultora":
        return vagas or c["assigned_to"] == uid
    return True


async def caso_8_filtro():
    papeis = {5: "sdr", 6: "consultora"}
    pd = papeis.get
    tag = [{"name": tags_auto.TAG_VAGAS}]
    rajada = {"tags": tag, "direction": "outbound", "last_sent_by": 6, "assigned_to": 5}
    respondeu = {"tags": tag, "direction": "inbound", "last_sent_by": None, "assigned_to": 5}
    abriu_sdr = {"tags": tag, "direction": "outbound", "last_sent_by": 5, "assigned_to": 5}
    comum = {"tags": [], "direction": "inbound", "last_sent_by": None, "assigned_to": 5}
    dela = {"tags": [], "direction": "outbound", "last_sent_by": None, "assigned_to": 6}
    checa("sdr esconde a rajada", passa_no_papel(rajada, "sdr", 5, pd), False)
    checa("sdr vê quem respondeu", passa_no_papel(respondeu, "sdr", 5, pd), True)
    checa("sdr vê o vagas_1 que ele mesmo mandou", passa_no_papel(abriu_sdr, "sdr", 5, pd), True)
    checa("sdr vê o resto", passa_no_papel(comum, "sdr", 5, pd), True)
    checa("consultora vê vagas", passa_no_papel(rajada, "consultora", 6, pd), True)
    checa("consultora vê os dela", passa_no_papel(dela, "consultora", 6, pd), True)
    checa("consultora não vê o comum do SDR", passa_no_papel(comum, "consultora", 6, pd), False)
    checa("gestão vê tudo", passa_no_papel(rajada, "gestao", 2, pd), True)


async def caso_9_papel_invalido():
    try:
        _papel_valido("chefe")
        levantou = False
    except HTTPException as e:
        levantou = e.status_code == 400
    checa("papel inválido = 400", levantou, True)
    _papel_valido("sdr")
    _papel_valido(None)


async def main():
    print("\nPapel de usuário, tag de vagas, destinos de SDR: banco dublê\n")
    for caso in (caso_1_do_banco, caso_2_reserva, caso_3_falha, caso_4_destinatarios,
                 caso_5_inativo, caso_6_templates, caso_7_marcar, caso_8_filtro,
                 caso_9_papel_invalido):
        print(caso.__name__)
        await caso()
    if falhas:
        print(f"\nFALHOU: {falhas}\n")
        raise SystemExit(1)
    print("\nOK: todos os casos passaram.\n")


if __name__ == "__main__":
    asyncio.run(main())
