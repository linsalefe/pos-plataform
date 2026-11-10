"""Testes das funções puras de case_participacao.py. Escritos em 10/11/2026, NÃO executados.

    cd backend && venv/bin/python -m pytest test_case_participacao.py -q
"""
from datetime import date, datetime

import case_participacao as cp


def test_thr_usa_chave_tolerante_e_cai_no_numero_cru():
    assert cp.thr("5551999297391") == cp.thr("555199297391")
    assert cp.thr("447834239129") == "447834239129"      # estrangeiro: não reduz


def test_ultimo_respeita_o_dia_da_venda():
    ds = [datetime(2026, 10, 1, 9), datetime(2026, 10, 5, 23), datetime(2026, 10, 6, 1)]
    assert cp.ultimo(ds, date(2026, 10, 5)) == datetime(2026, 10, 5, 23)
    assert cp.ultimo(ds, date(2026, 9, 30)) is None
    assert cp.ultimo([None], date(2026, 10, 5)) is None


def test_faixas_da_distancia():
    assert cp.faixa(0) == "mesmo dia"
    assert cp.faixa(3) == "1 a 3 dias"
    assert cp.faixa(7) == "4 a 7 dias"
    assert cp.faixa(8) == "8 a 30 dias"
    assert cp.faixa(31) == "mais de 30 dias"


def test_soma_deixa_valor_zero_fora_e_nao_devolve_zero():
    assert cp.soma([{"valor": None}]) == (1, None, 1)
    assert cp.soma([{"valor": 100.0}, {"valor": None}]) == (2, 100.0, 1)


def test_grupos_de_flag_nao_se_misturam():
    assert not set(cp.CONVERSA) & set(cp.POS_MARCACAO)
    assert "confirmou" not in cp.TOQUES_IA          # resposta da pessoa, não toque da IA
    assert set(cp.CONVERSA) | set(cp.POS_MARCACAO) <= set(cp.FLAGS)


def test_toda_flag_tem_descricao():
    assert set(cp.FLAGS) <= set(cp.O_QUE_FAZ)
    assert {"lembrete_antigo", "lembrete_novo"} <= set(cp.O_QUE_FAZ)


def test_flags_de_reuniao_incluem_as_duas_metades_do_lembrete():
    assert {"lembrete_antigo", "lembrete_novo", "lembrete_t30"} <= set(cp.l_flags_reuniao())


def test_reguas_comecam_em_07_10():
    assert cp.INICIO_REGUAS == date(2026, 10, 7)
