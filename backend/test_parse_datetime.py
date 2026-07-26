"""Guardrail do parser de data da API do Exact.

Roda sem banco, sem rede e sem token: só exercita `app.date_parse.parse_datetime`.

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python test_parse_datetime.py

O bug: `datetime.fromisoformat` no Python 3.10 aceita fração de segundo de EXATAMENTE 3 ou 6
dígitos. A Exact devolve 4, 5, 6 e 7 dígitos. Tudo que não era 6 virava None, e `register_date`
ficou NULL em 91% da base — que é justamente o campo em que a verificação 2 do `nat_guard`
falha fechada.
"""
from datetime import datetime

from app.date_parse import parse_datetime

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}\n      obtido={obtido!r} esperado={esperado!r}")
    if not ok:
        falhas.append(rotulo)


print("\n1) Fração de 7 dígitos — o caso do bug (90% da base)")
# 7 dígitos: trunca no microssegundo, que é a maior precisão que datetime guarda.
checa("registerDate com 7 dígitos",
      parse_datetime("2026-07-25T16:45:14.2081828Z"),
      datetime(2026, 7, 25, 16, 45, 14, 208182))
checa("updateDate com 7 dígitos",
      parse_datetime("2026-07-25T16:50:24.0851085Z"),
      datetime(2026, 7, 25, 16, 50, 24, 85108))

print("\n2) Fração de 6 dígitos — não-regressão (o único caso que já funcionava)")
checa("6 dígitos com Z",
      parse_datetime("2026-07-25T00:05:19.929555Z"),
      datetime(2026, 7, 25, 0, 5, 19, 929555))
checa("6 dígitos sem timezone",
      parse_datetime("2026-07-25T14:48:20.636379"),
      datetime(2026, 7, 25, 14, 48, 20, 636379))

print("\n3) Frações curtas — 4, 5 e 3 dígitos (também quebravam antes)")
# .9519 são 951900µs, não 9519µs: completa com zero à DIREITA.
checa("4 dígitos",
      parse_datetime("2026-07-22T20:30:51.9519Z"),
      datetime(2026, 7, 22, 20, 30, 51, 951900))
checa("5 dígitos",
      parse_datetime("2026-07-07T01:51:20.11367Z"),
      datetime(2026, 7, 7, 1, 51, 20, 113670))
checa("3 dígitos",
      parse_datetime("2026-07-07T01:51:20.113Z"),
      datetime(2026, 7, 7, 1, 51, 20, 113000))

print("\n4) Sem fração de segundo")
checa("sem fração, com Z",
      parse_datetime("2026-07-14T11:16:15Z"),
      datetime(2026, 7, 14, 11, 16, 15))
checa("sem fração, sem timezone",
      parse_datetime("2026-07-14T11:16:15"),
      datetime(2026, 7, 14, 11, 16, 15))

print("\n5) Timezone: Z, offset explícito, sem timezone")
# Datas com offset são convertidas para UTC antes de virar naive — as colunas são
# TIMESTAMP WITHOUT TIME ZONE e o resto do sistema grava utcnow().
checa("Z equivale a +00:00",
      parse_datetime("2026-07-25T16:45:14.208182+00:00"),
      parse_datetime("2026-07-25T16:45:14.208182Z"))
checa("offset -03:00 vira UTC",
      parse_datetime("2026-07-25T13:45:14.208182-03:00"),
      datetime(2026, 7, 25, 16, 45, 14, 208182))
checa("offset +0300 sem dois-pontos vira UTC",
      parse_datetime("2026-07-25T19:45:14.208182+0300"),
      datetime(2026, 7, 25, 16, 45, 14, 208182))
checa("sem timezone é tratado como já-UTC",
      parse_datetime("2026-07-25T16:45:14.208182"),
      datetime(2026, 7, 25, 16, 45, 14, 208182))

print("\n6) Entrada inválida devolve None, sem exceção — nunca inventa data")
for rotulo, entrada in [
    ("None", None),
    ("string vazia", ""),
    ("só espaços", "   "),
    ("lixo", "banana"),
    ("data impossível", "2026-13-45T99:99:99Z"),
    ("número, não string", 20260725),
    ("dict", {"date": "2026-07-25"}),
]:
    checa(f"{rotulo} -> None", parse_datetime(entrada), None)

print("\n6b) Não-regressão: entradas estranhas que o parser ANTIGO já aceitava")
# Verificado contra a implementação antiga: os dois casos abaixo devolviam datetime, não None.
# São ISO válido (precisão de minuto) e ponto sem dígitos, que o fromisoformat tolera.
# Passar a devolver None aqui seria mudança de comportamento — a sprint pede correção aditiva.
checa("ISO com precisão de minuto (antigo também aceitava)",
      parse_datetime("2026-07-25T16:45"),
      datetime(2026, 7, 25, 16, 45))
checa("ponto sem dígitos (antigo também aceitava)",
      parse_datetime("2026-07-25T16:45:14.Z"),
      datetime(2026, 7, 25, 16, 45, 14))

print("\n7) Payload real capturado da API na Fase 1")
# Amostra literal de fetch_leads_from_exact, uma de cada formato observado em 3.000 leads.
reais = [
    ("2026-07-25T16:45:14.2081828Z", datetime(2026, 7, 25, 16, 45, 14, 208182)),
    ("2026-07-25T14:50:27.0169152Z", datetime(2026, 7, 25, 14, 50, 27, 16915)),
    ("2026-07-25T13:59:14.7695038Z", datetime(2026, 7, 25, 13, 59, 14, 769503)),
    ("2026-07-07T01:51:20.11367Z",   datetime(2026, 7, 7, 1, 51, 20, 113670)),
    ("2026-07-22T20:30:51.9519Z",    datetime(2026, 7, 22, 20, 30, 51, 951900)),
    ("2026-07-25T00:05:19.929555Z",  datetime(2026, 7, 25, 0, 5, 19, 929555)),
    ("2026-07-25T14:48:20.636379Z",  datetime(2026, 7, 25, 14, 48, 20, 636379)),
    ("2026-07-20T17:41:17.2397Z",    datetime(2026, 7, 20, 17, 41, 17, 239700)),
    ("2026-07-25T12:40:54.39789Z",   datetime(2026, 7, 25, 12, 40, 54, 397890)),
]
for bruto, esperado in reais:
    checa(f"real {bruto}", parse_datetime(bruto), esperado)

print("\n8) Sanidade: nenhuma data válida cai fora de faixa plausível")
for bruto, _ in reais:
    dt = parse_datetime(bruto)
    checa(f"faixa de {bruto}", datetime(2020, 1, 1) < dt < datetime(2030, 1, 1), True)

print("\n" + "=" * 70)
if falhas:
    print(f"❌ {len(falhas)} teste(s) falharam:")
    for f in falhas:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ Todos os testes passaram.")
