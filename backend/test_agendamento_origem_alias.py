"""Alias de origem — "Pos DH T4" vira "Pos Direitos Humanos T4" antes da validação.

    cd backend && venv/bin/python test_agendamento_origem_alias.py

Nenhuma conexão: a Exact é mockada e o banco é o dublê de `test_agendamento.py`. Nada é
criado na Exact, nada entra na fila do RD.

O QUE ESTE TESTE PROVA
  1. alias resolve para o nome CANÔNICO, com a caixa da allowlist, em qualquer caixa
  2. o nome canônico continua aceito; origem fora de allowlist+aliases continua recusada
  3. falha fechada: destino fora da allowlist, JSON inválido, não-objeto e alias que colide
     com nome da allowlist são descartados — e a origem segue recusada
  4. cada resolução por alias é logada com contador
  5. /lead e /agendar: o canônico chega ao LeadsAdd, à nossa tabela e à fila do RD
  6. o mapa do RD só acha o identifier pelo canônico — é por isso que o alias não pode vazar
  7. validar_aliases() resume ativos e descartados para o log de boot
"""
import asyncio
import io
import os
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

# Importar a suíte principal limpa o .env de produção (ver o cabeçalho de lá) e traz os dublês.
from test_agendamento import TELEFONE, _DbFalso, _slot_valido

from app import rd_station
from app.agendamento import agendar as fluxo
from app.agendamento import client, origens

CANONICO = "Pos Direitos Humanos T4"
ALIAS = "Pos DH T4"
LISTA = f"PosMulheridades,Pos TEA V3,{CANONICO}"

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def _env(aliases: str | None, lista: str = LISTA):
    os.environ["AGENDAMENTO_SUBSOURCES"] = lista
    os.environ["AGENDAMENTO_SUBSOURCE_PADRAO"] = "PosMulheridades"
    if aliases is None:
        os.environ.pop("AGENDAMENTO_ORIGEM_ALIASES", None)
    else:
        os.environ["AGENDAMENTO_ORIGEM_ALIASES"] = aliases
    origens._usos_alias.clear()


def _recusa(origem) -> bool:
    try:
        origens.resolver(origem)
    except origens.OrigemInvalida:
        return True
    return False


def caso_1_alias_resolve_para_canonico():
    print("1. alias -> canônico")
    _env(f'{{"{ALIAS}": "{CANONICO}"}}')
    checa("alias exato", origens.resolver(ALIAS), CANONICO)
    checa("alias em minúsculas", origens.resolver("pos dh t4"), CANONICO)
    checa("alias com espaço em volta", origens.resolver("  POS DH T4 "), CANONICO)
    # destino no env com caixa diferente: sai a caixa da ALLOWLIST
    _env(f'{{"{ALIAS}": "pos direitos humanos t4"}}')
    checa("destino na caixa da allowlist", origens.resolver(ALIAS), CANONICO)


def caso_2_canonico_e_recusa_intactos():
    print("2. canônico aceito, resto recusado")
    _env(f'{{"{ALIAS}": "{CANONICO}"}}')
    checa("canônico aceito", origens.resolver(CANONICO), CANONICO)
    checa("sem origem -> padrão", origens.resolver(None), "PosMulheridades")
    checa("origem desconhecida recusada", _recusa("Pos Qualquer Coisa"), True)
    checa("alias parcial recusado", _recusa("Pos DH"), True)
    _env(None)
    checa("sem env de alias, 'Pos DH T4' é recusado como antes", _recusa(ALIAS), True)


def caso_3_falha_fechada():
    print("3. falha fechada por entrada")
    saida = io.StringIO()
    with redirect_stdout(saida):
        _env(f'{{"{ALIAS}": "Pos Direitos Humanos T5"}}')
        recusou_destino = _recusa(ALIAS)
    checa("destino fora da allowlist -> alias descartado", recusou_destino, True)
    checa("... e o log diz por quê", "não está em AGENDAMENTO_SUBSOURCES" in saida.getvalue(), True)

    with redirect_stdout(io.StringIO()):
        _env('{"Pos DH T4": ')
        checa("JSON inválido -> nenhum alias", _recusa(ALIAS), True)
        _env(f'["{ALIAS}", "{CANONICO}"]')
        checa("JSON que não é objeto -> nenhum alias", _recusa(ALIAS), True)
        _env(f'{{"{ALIAS}": 7}}')
        checa("destino não-texto -> descartado", _recusa(ALIAS), True)
        # alias que colide com nome da allowlist: o nome canônico vence, não é redirecionado
        _env(f'{{"Pos TEA V3": "{CANONICO}", "{ALIAS}": "{CANONICO}"}}')
        checa("alias = nome da allowlist não redireciona", origens.resolver("Pos TEA V3"),
              "Pos TEA V3")
        checa("... e o alias bom do mesmo JSON continua valendo", origens.resolver(ALIAS),
              CANONICO)
        # destino só é válido enquanto estiver NA allowlist: tirar o canônico desliga o alias
        _env(f'{{"{ALIAS}": "{CANONICO}"}}', lista="PosMulheridades,Pos TEA V3")
        checa("canônico removido da allowlist -> alias descartado", _recusa(ALIAS), True)


def caso_4_contador_no_log():
    print("4. cada resolução por alias vai para o log com contador")
    _env(f'{{"{ALIAS}": "{CANONICO}"}}')
    saida = io.StringIO()
    with redirect_stdout(saida):
        origens.resolver(ALIAS)
        origens.resolver("pos dh t4")
        origens.resolver(CANONICO)  # canônico NÃO conta
    log = saida.getvalue()
    checa("duas linhas de alias", log.count("origem por alias"), 2)
    checa("contador chega a 2", "uso nº 2" in log, True)
    checa("contador em memória", origens._usos_alias, {"pos dh t4": 2})


async def caso_5_canonico_chega_a_exact_tabela_e_rd():
    print("5. /lead e /agendar gravam e enviam o canônico")
    _env(f'{{"{ALIAS}": "{CANONICO}"}}')

    # --- /lead ---
    db = _DbFalso()
    criar = AsyncMock(return_value=999)
    fila = AsyncMock()
    with patch.object(client, "criar_lead", criar), \
         patch("app.agendamento.agendar.rd_outbox.enfileirar", fila), \
         redirect_stdout(io.StringIO()):
        await fluxo.cadastrar_lead_sem_agendar(db, nome="TESTE", email="a@b.com",
                                               telefone=TELEFONE, origem=ALIAS)
    checa("/lead: LeadsAdd com subSource canônico",
          criar.await_args.kwargs["sub_source"], CANONICO)
    checa("/lead: tabela com canônico", db.agendamentos()[0].sub_source, CANONICO)
    checa("/lead: fila do RD recebe o canônico", fila.await_args.args[1].sub_source, CANONICO)

    # --- /agendar ---
    slot = _slot_valido()
    db2 = _DbFalso()
    criar2 = AsyncMock(return_value=888)
    fila2 = AsyncMock()
    with patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", criar2), \
         patch.object(client, "agendar_reuniao", AsyncMock(return_value=True)), \
         patch.object(client, "meeting_por_lead", AsyncMock(return_value=None)), \
         patch("app.agendamento.agendar.rd_outbox.enfileirar", fila2), \
         redirect_stdout(io.StringIO()):
        await fluxo.agendar(db2, nome="TESTE", email="a@b.com", telefone=TELEFONE,
                            slot_id=slot.id, origem=ALIAS)
    checa("/agendar: LeadsAdd com subSource canônico",
          criar2.await_args.kwargs["sub_source"], CANONICO)
    checa("/agendar: tabela com canônico", db2.agendamentos()[0].sub_source, CANONICO)

    # --- origem desconhecida: nada é criado ---
    db3 = _DbFalso()
    criar3 = AsyncMock(return_value=1)
    with patch.object(client, "criar_lead", criar3):
        try:
            await fluxo.cadastrar_lead_sem_agendar(db3, nome="TESTE", email=None,
                                                   telefone=TELEFONE, origem="Pos XYZ")
            recusou = False
        except origens.OrigemInvalida:
            recusou = True
    checa("origem desconhecida -> OrigemInvalida", recusou, True)
    checa("... e LeadsAdd nem é chamado", criar3.called, False)


def caso_6_mapa_do_rd():
    print("6. o mapa do RD (rd_conversoes.json real) só conhece o canônico")
    checa("canônico -> formulario-pos-sm-e-dh", rd_station.identifier_para(CANONICO),
          "formulario-pos-sm-e-dh")
    checa("alias cru não está no mapa", rd_station.identifier_para(ALIAS), None)


def caso_7_resumo_de_boot():
    print("7. validar_aliases() para o log de boot")
    _env(f'{{"{ALIAS}": "{CANONICO}", "Pos X": "Nao Existe"}}')
    saida = io.StringIO()
    with redirect_stdout(saida):
        r = origens.validar_aliases()
    checa("um válido", r["validos"], {"pos dh t4": CANONICO})
    checa("um descartado", len(r["descartados"]), 1)
    checa("log de boot avisa o descarte", "descartado" in saida.getvalue(), True)
    _env(None)
    with redirect_stdout(io.StringIO()):
        checa("sem env: nada ativo, nada descartado", origens.validar_aliases(),
              {"validos": {}, "descartados": []})


async def main():
    caso_1_alias_resolve_para_canonico()
    caso_2_canonico_e_recusa_intactos()
    caso_3_falha_fechada()
    caso_4_contador_no_log()
    await caso_5_canonico_chega_a_exact_tabela_e_rd()
    caso_6_mapa_do_rd()
    caso_7_resumo_de_boot()
    if falhas:
        print(f"\nFALHOU: {len(falhas)} verificação(ões): {falhas}")
        raise SystemExit(1)
    print("\nOK: alias de origem. Nada criado na Exact, nada na fila do RD.\n")


if __name__ == "__main__":
    asyncio.run(main())
