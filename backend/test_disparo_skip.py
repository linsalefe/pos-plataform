"""BLOCO 1 da sprint de Relatórios — o pulo do disparo deixa rastro.

    cd backend && venv/bin/python test_disparo_skip.py

NADA sai daqui: banco é dublê, cadeia da Meta mockada. Nenhuma chamada de rede,
nenhuma linha gravada em produção.

O DEFEITO (RECON_RELATORIOS_20260901 §4.1)
  `skipped_total` / `skipped_por_regra` / `skipped` só existiam no corpo da resposta HTTP.
  O único ponto que persistia era `main.py:240`, no caminho AGENDADO — e o agendado tem 4
  linhas, todas de junho. 100% dos disparos recentes saíram pela porta HTTP, cujo retorno
  ninguém guarda: o filtro de recusa do S6-2 rodava sem deixar como provar que rodou.

O QUE ESTE TESTE PROVA
  1. cada pulo vira uma linha de `disparo_skip`, com regra, motivo, template e horário
  2. a chave gravada é a TOLERANTE (DDD + últimos 8), igual a app/telefone.chave_telefone
  3. `origem_envio` separa campanha de individual, e `sent_by` só é id de User de verdade
  4. o caminho AGENDADO (chamada Python, `current_user` = objeto Depends) grava sent_by NULL
  5. FALHA DE LOG É LOG DE FALHA: se a gravação estoura, o disparo segue e o contrato
     da resposta HTTP não muda
  6. `pulados` continua serializável por json.dumps — é o que o main.py:240 faz com ele
  7. quem não foi pulado não vira linha
"""
import asyncio
import io
import json
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

from app import exact_routes
from app.models import DisparoSkip, User
from app.telefone import chave_telefone

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


CANAL = MagicMock(id=1, waba_id="w", whatsapp_token="t", phone_number_id="p")


def _lead(id, exact_id, nome, telefone):
    l = MagicMock()
    l.id, l.exact_id, l.name, l.phone1 = id, exact_id, nome, telefone
    l.sub_source, l.sdr_name, l.funnel_id = "Pos TEA V3", "Thobias", 18535
    return l


class _Savepoint:
    """Dublê de `AsyncSession.begin_nested()`.

    `explode` reproduz o INSERT falhando no flush de saída do bloco — a tabela ausente é o
    caso concreto (código no ar antes da migração). E reproduz o que o Postgres faz em
    seguida: `ROLLBACK TO SAVEPOINT` DESCARTA o que foi adicionado dentro. Um dublê que
    guardasse as linhas mesmo assim provaria o contrário do que acontece.
    """

    def __init__(self, gravadas, explode=False):
        self.gravadas, self.explode = gravadas, explode

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        if self.explode:
            self.gravadas.clear()            # ROLLBACK TO SAVEPOINT
            raise RuntimeError('relation "disparo_skip" does not exist')
        return False


def dispara(leads, higiene, origem_envio="campanha", current_user=None,
            explode_log=False, estado_nat=None):
    """Roda a rota inteira com a sessão dublada. Devolve (resposta, linhas, log)."""
    gravadas = []
    passo = {"n": 0}

    async def execute(stmt):
        passo["n"] += 1
        r = MagicMock()
        if passo["n"] == 1:
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=leads)))
        else:
            r.scalar_one_or_none = MagicMock(return_value=CANAL)
        return r

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    db.add, db.flush, db.commit = MagicMock(), AsyncMock(), AsyncMock()
    db.begin_nested = MagicMock(return_value=_Savepoint(gravadas, explode_log))
    db.add_all = MagicMock(side_effect=gravadas.extend)
    envio = AsyncMock(return_value={"messages": [{"id": "wamid.Y"}],
                                    "contacts": [{"wa_id": "IGNORADO"}]})
    pedido = {"template_name": "f5_ligacao", "channel_id": 1, "origem_envio": origem_envio,
              "lead_ids": [l.id for l in leads], "param_mappings": [{"type": "lead_name"}]}
    with patch("app.higiene_disparo.por_que_pular", new=AsyncMock(side_effect=higiene)), \
         patch("app.qualificacao_fluxo.estado_de",
               new=AsyncMock(return_value=estado_nat)), \
         patch("app.whatsapp.send_template_message", new=envio), \
         patch("app.whatsapp.fetch_template_body", new=AsyncMock(return_value="Olá {{1}}")), \
         patch("app.whatsapp.render_template_text", new=MagicMock(return_value="Olá X")), \
         patch("app.contatos.contato_existente", new=AsyncMock(return_value=None)), \
         patch.object(exact_routes, "bloquear_se_boas_vindas", new=AsyncMock()), \
         patch("app.sdr_mapping.resolve_sdr_user_id", new=MagicMock(return_value=5)), \
         patch("asyncio.sleep", new=AsyncMock()), \
         patch.object(exact_routes, "_silenciar_agente_apos_envio_manual", new=AsyncMock()):
        buf = io.StringIO()
        with redirect_stdout(buf):
            r = asyncio.run(exact_routes.bulk_send_template(
                pedido, db, MagicMock() if current_user is None else current_user))
    return r, gravadas, buf.getvalue()


async def ninguem_pula(*a, **k):
    return None


async def michele_recusou(wa, db, *, agora, aplicar_teto=True):
    return ("recusa", 'o lead pediu para parar — ele disse: "Não tenho mais interesse"') \
        if wa == "5541999888777" else None


# ==========================================================================================
print("\n1) Cada pulo vira uma linha, com a regra e o motivo")

MICHELE = _lead(1, 51600001, "Michele", "5541999888777")
ROBERTO = _lead(2, 51600002, "Roberto", "5511988887777")
r, linhas, log = dispara([MICHELE, ROBERTO], michele_recusou)

checa("uma linha para o único pulo", len(linhas), 1)
l = linhas[0]
checa("  é um DisparoSkip", isinstance(l, DisparoSkip), True)
checa("  com a regra nomeada", l.regra, "recusa")
checa("  com o motivo citando a fala dela",
      "Não tenho mais interesse" in (l.motivo or ""), True)
checa("  com o template que NÃO foi enviado", l.template_name, "f5_ligacao")
checa("  com o telefone como foi para a Meta", l.telefone, "5541999888777")
checa("  com o nome do lead", l.nome, "Michele")
checa("  com `lead_id` = exact_id (convenção de agendamentos.lead_id)", l.lead_id, 51600001)
checa("  sem etapa (a regra não é nat_ativa)", l.etapa, None)
checa("  com horário preenchido", l.quando is not None, True)
checa("quem recebeu não virou linha", [x.nome for x in linhas], ["Michele"])

# O SEGUNDO ponto de captura: conversa ativa da NAT. É a metade da métrica 6 que já era
# medível por `nat_qualificacao_state.transferido_em` — mas ali só quando o agente chegou a
# ser transferido. Aqui fica registrado o pulo que IMPEDIU o atropelo.
r_nat, linhas_nat, _ = dispara([_lead(9, 51600009, "Daniela", "5511955554444")],
                               ninguem_pula,
                               estado_nat=MagicMock(etapa="escolhendo_slot"))
checa("conversa ativa da NAT também vira linha", len(linhas_nat), 1)
checa("  com a regra nat_ativa", linhas_nat[0].regra, "nat_ativa")
checa("  e COM a etapa, que é o que a outra regra não tem",
      linhas_nat[0].etapa, "escolhendo_slot")


# ==========================================================================================
print("\n2) A chave gravada é a TOLERANTE — a mesma de app/telefone.py")
#
# 379 pessoas têm as duas grafias do telefone (com e sem o 9º dígito). Um log que grave só
# a grafia que a Exact tinha não cruza com `messages`, e o relatório perde a pessoa.

checa("chave = DDD + últimos 8", l.chave, "4199888777")
checa("  e é literalmente chave_telefone(telefone)",
      l.chave, chave_telefone("5541999888777"))

r2, linhas2, _ = dispara([_lead(3, 51600003, "Sem nono dígito", "554199888777")],
                         lambda *a, **k: ("recusa", "disse não"))
checa("a MESMA pessoa escrita sem o 9º dígito dá a MESMA chave",
      linhas2[0].chave, l.chave)


# ==========================================================================================
print("\n3) origem_envio e sent_by")

checa("campanha é campanha", l.origem_envio, "campanha")

usuario = User(); usuario.id = 7
r3, linhas3, _ = dispara([_lead(4, 51600004, "Ana", "5511977776666")],
                         lambda *a, **k: ("recusa", "disse não"),
                         origem_envio="individual", current_user=usuario)
checa("individual é individual", linhas3[0].origem_envio, "individual")
checa("sent_by é o id do humano logado", linhas3[0].sent_by, 7)


# ==========================================================================================
print("\n4) O caminho AGENDADO grava sent_by NULL — e não estoura")
#
# `main.py:233` chama esta rota como FUNÇÃO PYTHON: `current_user` recebe o próprio objeto
# `Depends`, não um User. `quem_enviou` (app/autoria.py) é quem fecha essa porta. Sem ele,
# `current_user.id` seria um AttributeError no meio do lote — ou, pior, um id que existe.

from fastapi import Depends  # noqa: E402  (o import é a demonstração)

r4, linhas4, _ = dispara([_lead(5, 51600005, "Lead agendado", "5511966665555")],
                         lambda *a, **k: ("teto", "já recebeu 3 templates"),
                         current_user=Depends(lambda: None))
checa("gravou a linha mesmo sem sessão", len(linhas4), 1)
checa("  com sent_by NULL — não houve humano logado", linhas4[0].sent_by, None)
checa("  e a regra do teto preservada", linhas4[0].regra, "teto")


# ==========================================================================================
print("\n5) FALHA DE LOG É LOG DE FALHA — o disparo segue")

r5, linhas5, log5 = dispara([MICHELE, ROBERTO], michele_recusou, explode_log=True)
checa("o envio de quem não foi pulado aconteceu igual", r5["sent"], 1)
checa("pular continua não sendo falhar", (r5["failed"], r5["errors"]), (0, []))
checa("o contrato da resposta HTTP não mudou", r5["skipped_total"], 1)
checa("  e a quebra por regra também não", r5["skipped_por_regra"], {"recusa": 1})
checa("nada foi gravado", linhas5, [])
checa("e o aviso saiu no log", "disparo_skip NÃO gravado" in log5, True)


# ==========================================================================================
print("\n6) `pulados` continua serializável — é o que main.py:240 faz com ele")
#
# Se `quando` (um datetime) entrasse no dict de `pulados`, o `json.dumps(result)` do job
# agendado estouraria em TypeError e mataria o ÚNICO caminho que já persistia alguma coisa.
# Duas listas, e é por isso.

try:
    json.dumps(r)
    serializavel = True
except TypeError as e:
    serializavel, erro = False, e
checa("json.dumps(resposta) passa", serializavel, True)
checa("  e `skipped` continua com as chaves de antes",
      sorted(r["skipped"][0].keys()), ["etapa", "motivo", "name", "phone", "regra"])


# ==========================================================================================
print("\n7) Sem pulo, sem linha — e sem savepoint")

r7, linhas7, _ = dispara([ROBERTO], ninguem_pula)
checa("ninguém pulado, nenhuma linha", linhas7, [])
checa("  e o disparo saiu", r7["sent"], 1)


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado em produção.")
