"""Sprint 3 itens 3 e 4 — o nome e o curso que vão na abertura. (27/08/2026)

    cd backend && venv/bin/python test_identidade_abertura.py

Os dois casos reais do RECON de 27/08:

    "Vi que você aplicou para a nossa Pós-Graduação em ."   -> 2 de 2 leads da LP (100%)
    "Olá, Eve!"  para Evelyn Renata Begliomini Manfrim      -> perfil do WhatsApp ganhando
                                                               do cadastro

O QUE ESTE ARQUIVO GUARDA:

  1. `_curso`: exact_leads é a primeira fonte, e continua sendo
  2. `_curso`: sem exact_leads (o lead da LP que ainda não sincronizou) -> agendamentos
  3. `_curso`: as duas vazias -> "" (e o porquê de NÃO inventar)
  4. `_nome`: o cadastro ganha do perfil do WhatsApp — o caso "Eve"
  5. `_nome`: sem cadastro, o perfil ainda salva — o #131008 NÃO volta
  6. `_nome`: os dois vazios -> "" (mesmo caso de antes da inversão; nenhuma fonte sumiu)
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app import qualificacao_fluxo as fluxo
from app.models import NatQualificacaoState, ORIGEM_LP

falhas = []
LEAD_ID = 51571878


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


class Sessao:
    """Responde `select` por tabela. `exact` e `agendamento` são o que cada fonte devolve."""
    def __init__(self, *, exact=None, agendamento=None):
        self.exact = exact
        self.agendamento = agendamento
        self.consultadas = []

    async def execute(self, stmt, *a, **kw):
        texto = str(stmt)
        r = MagicMock()
        if "exact_leads" in texto:
            self.consultadas.append("exact_leads")
            r.scalar_one_or_none.return_value = self.exact
        elif "agendamentos" in texto:
            self.consultadas.append("agendamentos")
            r.scalar_one_or_none.return_value = self.agendamento
        else:
            r.scalar_one_or_none.return_value = None
        return r


def _estado(lead_id=LEAD_ID, wa="5566997112651"):
    return NatQualificacaoState(contact_wa_id=wa, exact_lead_id=lead_id, origem=ORIGEM_LP,
                                etapa="aguardando_formacao")


def curso(*, exact=None, agendamento=None, lead_id=LEAD_ID):
    db = Sessao(exact=exact, agendamento=agendamento)
    with patch("app.course_names.resolve_course_name",
               new=AsyncMock(side_effect=lambda sub, _db: {
                   "Pos TEA V3": "Transtorno do Espectro Autista (TEA)",
                   "Pos Grupos e Oficinas T2": "Grupos e Oficinas em Saúde Mental",
               }.get(sub, sub))):
        return asyncio.run(fluxo._curso(_estado(lead_id), db)), db.consultadas


def nome(*, cadastro=None, perfil=None):
    """`cadastro` é o que `_identidade_do_lead` devolve; `perfil` é `contacts.name`."""
    contato = SimpleNamespace(name=perfil, wa_id="5511940718388") if perfil is not None else None
    with patch.object(fluxo, "_identidade_do_lead",
                      new=AsyncMock(return_value=(cadastro or "", None))), \
         patch.object(fluxo, "_contato_de", new=AsyncMock(return_value=contato)):
        return asyncio.run(fluxo._nome(_estado(wa="5511940718388"), Sessao()))


print("=" * 78)
print("Sprint 3 itens 3 e 4 — nome e curso da abertura")
print("=" * 78)

print("\n1) _curso: exact_leads continua sendo a primeira fonte")
c, consultadas = curso(exact="Pos TEA V3", agendamento="Pos Grupos e Oficinas T2")
checa("resolve pelo exact_leads", c, "Transtorno do Espectro Autista (TEA)")
checa("  e nem chega a consultar agendamentos", "agendamentos" in consultadas, False)

print("\n2) _curso: lead da LP ainda não sincronizado -> agendamentos salva a abertura")
# O caso da Sônia: abertura 26/08 14:55 UTC, exact_leads.synced_at 27/08 00:19 UTC.
c, consultadas = curso(exact=None, agendamento="Pos TEA V3")
checa("cai para agendamentos.sub_source", c, "Transtorno do Espectro Autista (TEA)")
checa("  consultou as duas, nessa ordem", consultadas, ["exact_leads", "agendamentos"])
checa("  e o texto da abertura deixa de ter buraco",
      f"Pós-Graduação em {c}." != "Pós-Graduação em .", True)

c, _ = curso(exact="", agendamento="Pos TEA V3")
checa("sub_source vazio (não só NULL) também cai para a segunda fonte",
      c, "Transtorno do Espectro Autista (TEA)")

print("\n3) _curso: as duas vazias -> \"\", e não um curso inventado")
# `resolve_course_name("")` devolveria "Pós-Graduação", e a abertura viraria
# "Pós-Graduação em Pós-Graduação". Vazio é honesto e é o que o guard de parâmetro em
# branco do nat_sender sabe recusar.
c, consultadas = curso(exact=None, agendamento=None)
checa("devolve vazio", c, "")
checa("  tendo tentado as duas fontes", consultadas, ["exact_leads", "agendamentos"])
c, consultadas = curso(exact=None, agendamento=None, lead_id=None)
checa("sem lead_id nenhum, nem consulta", consultadas, [])
checa("  e devolve vazio", c, "")

print("\n4) _nome: o cadastro ganha do perfil do WhatsApp (o caso \"Eve\")")
checa("perfil apelidado, cadastro completo -> vence o cadastro",
      nome(cadastro="Evelyn Renata Begliomini Manfrim", perfil="Eve 🍒🦖🤞"), "Evelyn")
checa("  e capitaliza como sempre fez",
      nome(cadastro="MIKAELLE BEATRIZ DE SOUZA JULIANI", perfil="Mika"), "Mikaelle")

print("\n5) _nome: sem cadastro, o perfil ainda salva — o #131008 NÃO volta")
# Era este o motivo de `_nome` existir (80358e5). Inverter a ordem não removeu fonte
# nenhuma, então o caso que a Meta recusava continua coberto — só que pelo outro lado.
checa("cadastro vazio, perfil presente -> usa o perfil", nome(cadastro="", perfil="Bruna"),
      "Bruna")
checa("cadastro None, perfil presente -> usa o perfil",
      nome(cadastro=None, perfil="Camilla Brito"), "Camilla")
checa("cadastro só com lixo sem letra -> não engole o perfil",
      nome(cadastro="   ", perfil="Talita"), "Talita")

print("\n6) _nome: os dois vazios -> \"\" (mesmo caso de antes da inversão)")
checa("sem cadastro e sem contato", nome(cadastro="", perfil=None), "")
checa("sem cadastro e com perfil vazio", nome(cadastro="", perfil=""), "")
# É aqui que o guard local de `nat_sender` (parâmetro em branco) assume, e é por isso que
# nenhuma abertura chega à Meta com {{1}} vazio.

print("\n" + "=" * 78)
if falhas:
    print(f"{len(falhas)} FALHA(S):")
    for f in falhas:
        print(f"  - {f}")
    raise SystemExit(1)
print("TUDO OK")
