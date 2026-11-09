"""Testes das funções puras de case_faturamento.py. Escritos em 09/11/2026, NÃO executados.

    cd backend && venv/bin/python -m pytest test_case_faturamento.py -q
"""
from datetime import datetime

import case_faturamento as cf


def _c(origem="ia", em=datetime(2026, 10, 1, 10), venda=None, motivo=None, concluida=False,
       remarcacoes=0, espelho=True):
    return dict(lead_id=1, origem=origem, em=em, consultora="x@y", remarcacoes=remarcacoes,
                stage="Vendidos" if venda or motivo else "Agendados", funil=18537,
                concluida=concluida, espelho=espelho, aplicou_lp_antes=False, roteiro=None,
                fluxo=None, venda=venda, motivo_sem_venda=motivo)


def test_sp_converte_utc_para_sao_paulo():
    assert cf.sp("2026-08-25T15:00:51.6547185Z") == datetime(2026, 8, 25, 12, 0, 51)


def test_saledate_digitado_a_mao_cai_na_meia_noite_de_sp():
    # 03:00Z é a data informada à mão na Exact, sem hora.
    assert cf.sp("2026-09-09T03:00:00Z") == datetime(2026, 9, 9, 0, 0)


def test_brl_formata_e_nunca_devolve_zero_para_ausente():
    assert cf.brl(6500) == "R$ 6.500,00"
    assert cf.brl(None) == "não medível"


def test_pct_abaixo_do_minimo_devolve_contagem():
    assert "sem taxa" in cf.pct(8, 20)
    assert cf.pct(8, 40) == "20.0% (8/40)"


def test_venda_apos_pega_a_primeira_venda_posterior():
    vendas = [{"saleDate": "2026-08-01T12:00:00Z", "totalDealValue": 1},
              {"saleDate": "2026-10-05T12:00:00Z", "totalDealValue": 2},
              {"saleDate": "2026-10-03T12:00:00Z", "totalDealValue": 3}]
    assert cf.venda_apos(vendas, datetime(2026, 10, 1, 9))["totalDealValue"] == 3


def test_venda_no_mesmo_dia_da_marcacao_conta():
    # saleDate às vezes é só a data (00:00 SP): no mesmo dia, mesmo "antes" na hora, conta.
    vendas = [{"saleDate": "2026-10-01T03:00:00Z", "totalDealValue": 5}]
    assert cf.venda_apos(vendas, datetime(2026, 10, 1, 15)) is not None


def test_venda_anterior_a_marcacao_nao_conta():
    vendas = [{"saleDate": "2026-09-01T12:00:00Z", "totalDealValue": 5}]
    assert cf.venda_apos(vendas, datetime(2026, 10, 1, 9)) is None


def test_resumo_vendido_sem_leadssold_conta_como_sem_valor():
    v = dict(data=datetime(2026, 10, 3), valor=6000.0, closer="x@y", ciclo=1)
    r = cf.resumo([_c(venda=v, concluida=True),
                   _c(motivo="Vendidos sem linha em LeadsSold"),
                   _c(motivo="venda antes da marcação"),
                   _c()])
    assert r["n"] == 4
    assert r["vendidos"] == 2           # a venda anterior à marcação fica fora
    assert r["com_valor"] == 1 and r["sem_valor"] == 1
    assert r["faturamento"] == 6000.0 and r["ticket"] == 6000.0
    assert r["antes"] == 1 and r["sem_sold"] == 1
    assert r["vend_conc"] == 1


def test_resumo_sem_venda_devolve_none_e_nao_zero():
    r = cf.resumo([_c()])
    assert r["faturamento"] is None and r["ticket"] is None and r["mediana_dias"] is None


def test_valor_zero_na_exact_fica_fora_da_soma():
    v = dict(data=datetime(2026, 10, 3), valor=None, closer=None, ciclo=1)
    r = cf.resumo([_c(venda=v)])
    assert r["vendidos"] == 1 and r["com_valor"] == 0 and r["faturamento"] is None


def test_toque_do_agente_nao_inclui_confirmacao_nem_noshow():
    # Confirmação e no-show saem DEPOIS de uma reunião; não levam ninguém até ela.
    assert not any(e.startswith(("nat_a_", "nat_ns_")) for e in cf.ETAPAS_AGENTE)


def test_intercambio_fora_dos_funis_de_pos():
    assert 18285 not in cf.FUNIS_POS
