"""S6-2 — o disparo não alcança quem pediu para parar.

    cd backend && venv/bin/python test_higiene_disparo.py

NADA sai daqui: banco é dublê, cadeia da Meta mockada. Nenhuma chamada de rede.

O DEFEITO (RECON_FOLLOWS_HUMANO_IA_20260901, §4.2)
  8 dos 9 leads que disseram "não" continuaram recebendo — até 6 toques depois. Michele
  respondeu, em 31/08: "Eu NÃO TENHO INTERESSE! Já é a quarta mensagem que me mandam sobre
  e eu sempre digo que nao tenho". 21 pessoas receberam ≥5 templates em 8 dias sem nunca
  responder. E 4 envios voltaram com `131049 — not delivered to maintain healthy ecosystem`.

O TETO SAIU EM 21/09/2026 (SPRINT_DISPARO_SEM_TETO_20260921): o processo prevê 9 follows
por lead e a regra de 3 templates/7 dias bloqueava o time. As seções 3 e 4 provam agora o
CONTRÁRIO do que provavam: 9 templates na semana NÃO pulam, em nenhum modo.

O QUE ESTE TESTE PROVA
  1. O PADRÃO DE RECUSA, contra frases REAIS do banco — as que devem casar e as que não
  2. recusa dentro de 30 dias pula; fora de 30 dias, não
  3. NÃO existe mais teto: 3, 9 templates/7 dias — envia; e nem CONTA os templates
  4. individual: a RECUSA continua valendo (e `aplicar_teto` não existe mais)
  5. a recusa é achada nas DUAS grafias do telefone
  6. higiene NUNCA derruba disparo: banco quebrado => envia
  7. a rota registra o pulo com a regra, e `skipped_nat` NÃO muda de significado
  8. (27/09) o opt-out da META pula — `131050` sim, `131049` NÃO
"""
import asyncio
import inspect
import io
import re
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app import exact_routes, higiene_disparo
from app.higiene_disparo import (CODIGO_OPT_OUT_META, CODIGOS_OPT_OUT_META,
                                 PADRAO_RECUSA, por_que_pular)

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


AGORA = datetime(2026, 9, 1, 15, 0, 0)
RE = re.compile(PADRAO_RECUSA, re.IGNORECASE)


# ==========================================================================================
print("\n1) O padrão de recusa, contra frases REAIS do banco")
#
# Todas verbatim de `messages`. A lista de baixo é a que importa: cada uma dessas custou
# uma decisão, e a medição sobre 6 meses de inbound é o que as pôs aqui.

DEVE_CASAR = [
    "Não tenho mais interesse",
    "Oi, eu nao tenho mais interesse. Obrigada",
    "Eu NÃO TENHO INTERESSE! Já é a quarta mensagem que me mandam sobre",
    "No momento não tenho interesse. Estou me preparando para o início do ano q vem.",
    "Boa tarde, não desejo iniciar a pós graduação no momento, obrigada",
    "Não irei fazer no momento",
    "Olá, não vou fazer a pós no momento",
    "No momento não tenho condições financeiras",
    "Sou grata; deixo para outro momento. Sem condições financeiras",
    "Olá. Por enquanto eu desisti da especialização.",
    "Boa tarde. Vou desistir no momento.",
    "eu não quero dar continuidade no momento, obrigada",
    "Não quero pós graduação",
    "Agradeço os contatos, mas não quero mais receber contato",
    "não seguir com essa formação",
    "Obrigado pelo convite, mas por enquanto não pretendo fazer.",
    # A mais forte do corpus inteiro — e a que mais custa deixar passar.
    "estou informando que NÃO DESEJO prosseguir com atendimento ou receber QUALQUER TIPO "
    "de ligação, contato, notificação ou informação da parte da instituição",
]
for frase in DEVE_CASAR:
    checa(f'casa: "{frase[:52]}…"', bool(RE.search(frase)), True)

print()
NAO_PODE_CASAR = [
    # O ACHADO. Está DENTRO do nosso próprio template `ainda_ha_interesse`; todo lead que
    # reencaminha ou cita a nossa mensagem viraria "recusa" para sempre.
    ("Ainda há interesse em seguir com a sua inscrição na Pós-Graduação? *IMPORTANTE:* Na "
     "ausência de retorno considerarei que não há mais interesse e encerrarei",
     "eco do NOSSO template"),
    # Lead comprando.
    ("Bom dia. Podem enviar o link? Não quero perder as aulas. Obrigada",
     "'não quero' de quem QUER"),
    # Preferência de CANAL: bloquear WhatsApp para eles é o avesso do que pediram.
    ("nao quero falar por telefone", "preferência de canal"),
    ("Não quero informação por ligação. Quero pelo WhatsApp", "preferência de canal"),
    ("Irei ser direto, não quero fazer amizade tampouco perder tempo. Quero saber o valor "
     "da pós graduação", "lead impaciente, não recusa"),
    # O contrário de desistir.
    ("não desisti, só demorei para responder", "'não desisti' é o oposto"),
]
for frase, porque in NAO_PODE_CASAR:
    checa(f'NÃO casa ({porque}): "{frase[:44]}…"', bool(RE.search(frase)), False)


# ==========================================================================================
print("\n2, 3 e 4) A janela da recusa — e o teto que NÃO existe mais")


def pergunta(recusa_texto=None, n_templates=0, wa="5541999888777", opt_out=None):
    """Roda `por_que_pular` com um banco que responde exatamente essas coisas.

    São DUAS consultas desde 27/09, nesta ordem: `_recusou` e `_opt_out_meta`.

    `n_templates` continua aqui de propósito: o dublê está PRONTO para responder a
    contagem, e a prova é que ninguém pergunta (o teto saiu em 21/09).

    `opt_out` nasce em None — "a Meta nunca registrou opt-out para este contato". Sem esse
    default explícito, o `MagicMock` devolveria um mock TRUTHY em vez de None e TODO caso de
    "sem recusa" viraria `opt_out_meta`. O dublê que responde por omissão mente para o lado
    perigoso, e é justamente o que esta linha impede.
    """
    chamadas = []

    async def execute(stmt):
        chamadas.append(stmt)
        r = MagicMock()
        if len(chamadas) == 1:                      # _recusou
            r.scalar_one_or_none = MagicMock(return_value=recusa_texto)
        elif len(chamadas) == 2:                    # _opt_out_meta
            r.scalar_one_or_none = MagicMock(return_value=opt_out)
        else:                                       # (era _quantos_templates; não existe mais)
            r.scalar_one = MagicMock(return_value=n_templates)
        return r

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = asyncio.run(por_que_pular(wa, db, agora=AGORA))
    return r, len(chamadas)


r, _ = pergunta(recusa_texto="Não tenho mais interesse")
checa("recusa na janela: pula", r[0], "recusa")
checa("  e o motivo CITA o que o lead disse", "Não tenho mais interesse" in r[1], True)
checa("  e diz o caminho (tela de Conversas)", "tela de Conversas" in r[1], True)

r, n = pergunta(recusa_texto=None, n_templates=0)
checa("sem recusa e sem toques: envia", r, None)
# DUAS desde 27/09 (recusa + opt-out da Meta). A contagem de templates continua não
# existindo — se ela voltasse, seriam três.
checa("  e só DUAS consultas rodaram (recusa + opt-out) — o teto não existe mais", n, 2)

print("\n3) O teto NÃO existe mais (21/09): 3, 9 templates na semana — envia")
r, n = pergunta(n_templates=3)
checa("3 templates em 7 dias: ENVIA", r, None)
checa("  e nem contou os templates", n, 2)

r, n = pergunta(n_templates=9)
checa("9 templates (o processo prevê 9 follows): ENVIA", r, None)
checa("  e nem contou os templates", n, 2)

r, n = pergunta(recusa_texto="não desejo", n_templates=9)
checa("recusa com 9 toques: o motivo é a RECUSA, não um teto", r[0], "recusa")
checa("  e a recusa curto-circuita: o opt-out nem é consultado", n, 1)

# `regra` nunca pode voltar a ser 'teto': a tela não tem mais rótulo para isso, e
# `disparo_skips` não deve ganhar linha nova com essa regra a partir do deploy.
for n_t in (0, 3, 9, 30):
    r, _ = pergunta(recusa_texto=None, n_templates=n_t)
    checa(f"{n_t} templates: a regra 'teto' não sobe", r is None or r[0] != "teto", True)

print("\n4) individual: a RECUSA vale — e `aplicar_teto` já não é aceito")
r, _ = pergunta(recusa_texto="Não quero pós graduação")
checa("individual para quem recusou: PULA", r[0], "recusa")

try:
    asyncio.run(por_que_pular("5541999888777", MagicMock(), agora=AGORA, aplicar_teto=False))
    aceitou_flag = True
except TypeError:
    aceitou_flag = False
checa("`aplicar_teto` foi embora com a regra (TypeError se alguém ainda passar)",
      aceitou_flag, False)


# ==========================================================================================
print("\n5) A recusa é achada nas DUAS grafias — 59% das threads chegam sem o 9º dígito")

vistos = {}


async def execute_variantes(stmt):
    # `in_(variantes)` — o que importa é QUAIS grafias foram procuradas.
    vistos["sql"] = str(stmt)
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=None)
    r.scalar_one = MagicMock(return_value=0)
    return r


db = MagicMock()
db.execute = AsyncMock(side_effect=execute_variantes)
buf = io.StringIO()
with redirect_stdout(buf):
    asyncio.run(por_que_pular("5541999888777", db, agora=AGORA))
params = db.execute.await_args_list[0].args[0].compile().params
# `in_` compila como parâmetro EXPANDIDO: um nome, uma lista de valores.
grafias = {x for v in params.values() if isinstance(v, (list, tuple)) for x in v}
checa("procura as duas grafias do mesmo humano",
      grafias, {"5541999888777", "554199888777"})

r, _ = pergunta(wa="nao-e-telefone")
checa("wa_id ilegível não pula (e não estoura)", r, None)


# ==========================================================================================
print("\n6) Higiene NUNCA derruba disparo")

db = MagicMock()
db.execute = AsyncMock(side_effect=RuntimeError("banco caiu no meio do lote"))
buf = io.StringIO()
with redirect_stdout(buf):
    r = asyncio.run(por_que_pular("5541999888777", db, agora=AGORA))
checa("banco quebrado => NÃO pula (a mensagem sai)", r, None)
checa("  e o erro fica no log, não engolido", "Higiene do disparo falhou" in buf.getvalue(), True)


# ==========================================================================================
print("\n7) A rota: o pulo aparece com a regra, e `skipped_nat` não muda de significado")

CANAL = MagicMock(id=1, waba_id="w", whatsapp_token="t", phone_number_id="p")


def _lead(id, nome, telefone):
    l = MagicMock()
    l.id, l.name, l.phone1 = id, nome, telefone
    l.sub_source, l.sdr_name, l.funnel_id = "Pos TEA V3", "Thobias", 18535
    return l


def dispara(leads, higiene, origem_envio="campanha"):
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
    envio = AsyncMock(return_value={"messages": [{"id": "wamid.Y"}],
                                    "contacts": [{"wa_id": "IGNORADO"}]})
    pedido = {"template_name": "f5_ligacao", "channel_id": 1, "origem_envio": origem_envio,
              "lead_ids": [l.id for l in leads], "param_mappings": [{"type": "lead_name"}]}
    with patch("app.higiene_disparo.por_que_pular", new=AsyncMock(side_effect=higiene)), \
         patch("app.qualificacao_fluxo.estado_de", new=AsyncMock(return_value=None)), \
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
            r = asyncio.run(exact_routes.bulk_send_template(pedido, db, MagicMock()))
    return r, envio, buf.getvalue()


async def michele_recusou(wa, db, *, agora):
    return ("recusa", "o lead pediu para parar — ele disse: \"Não tenho mais interesse\"") \
        if wa == "5541999888777" else None

r, envio, log = dispara([_lead(1, "Michele", "5541999888777"),
                         _lead(2, "Roberto", "5511988887777")], michele_recusou)
checa("só o Roberto recebeu", envio.await_count, 1)
checa("  e foi ele mesmo", envio.await_args.args[0], "5511988887777")
checa("Michele entrou em `skipped`", r["skipped"][0]["name"], "Michele")
checa("  com a regra nomeada", r["skipped"][0]["regra"], "recusa")
checa("  e o motivo citando a fala dela",
      "Não tenho mais interesse" in r["skipped"][0]["motivo"], True)
checa("`skipped_total` conta todos os pulos", r["skipped_total"], 1)
checa("`skipped_por_regra` quebra por regra", r["skipped_por_regra"], {"recusa": 1})
checa("`skipped_nat` NÃO mudou de significado (só conversa ativa)", r["skipped_nat"], 0)
checa("pular não é falhar", (r["failed"], r["errors"]), (0, []))
checa("o pulo está no log com a regra", "por 'recusa'" in log, True)

r, envio, _ = dispara([_lead(1, "Ana", "5511988887777")], lambda *a, **k: None)
checa("sem higiene a acionar, tudo sai", envio.await_count, 1)
checa("  e o contrato antigo continua", ("sent" in r, "skipped_nat" in r), (True, True))


# ==========================================================================================
print("\n8) O opt-out da META (27/09) — `131050` pula, `131049` NÃO")
#
# O WhatsApp tem um botão "parar promoções" que não manda mensagem nenhuma para nós: o que
# chega é o erro `131050` no envio SEGUINTE. O Hub já gravava em `messages.error_code`
# (main.py:698) e `delivery_health` já contava — ninguém lia para DECIDIR se pode enviar.
# Medido em 27/09: 1 lead com 131050 nos 30 dias, e ele seguia entrando em todo disparo.

r, n = pergunta(recusa_texto=None, opt_out=CODIGO_OPT_OUT_META)
checa("131050 registrado pela Meta: PULA", r[0], "opt_out_meta")
checa("  e o motivo cita o código", "131050" in r[1], True)
checa("  e diz o caminho (tela de Conversas)", "tela de Conversas" in r[1], True)
checa("  e as duas consultas rodaram", n, 2)

# A DISTINÇÃO QUE É O ACHADO. 131049 aparece 17× nos mesmos 30 dias — 17 vezes mais que o
# 131050 — e é a Meta LIMITANDO A FREQUÊNCIA, não o destinatário escolhendo sair. O mesmo
# lead volta a receber no dia seguinte. Tratar os dois igual apagaria de todas as campanhas
# gente que nunca pediu para sair.
#
# A prova é dupla, e as duas metades importam: o código não está na LISTA, e é a lista que a
# consulta usa no `in_` — então um 131049 no banco não é nem devolvido pelo dublê.
for codigo, rotulo in ((131049, "limite de frequência da Meta"),
                       (131026, "número indisponível"),
                       (131047, "janela de reengajamento"),
                       (131008, "parâmetro em branco")):
    checa(f"{codigo} ({rotulo}) NÃO está na lista de opt-out",
          codigo in CODIGOS_OPT_OUT_META, False)

checa("a lista de opt-out tem UM código só, e é o 131050",
      CODIGOS_OPT_OUT_META, (131050,))

# SEM JANELA, ao contrário da recusa: o opt-out da Meta não expira sozinho. A prova é que a
# consulta não leva corte de data — `_opt_out_meta` recebe (variantes, db), sem `desde`.
checa("`_opt_out_meta` não tem parâmetro de data (o opt-out não expira)",
      [p for p in inspect.signature(higiene_disparo._opt_out_meta).parameters
       if p not in ("variantes", "db")], [])
checa("`_recusou` TEM corte de data (a recusa expira em 30 dias)",
      "desde" in inspect.signature(higiene_disparo._recusou).parameters, True)

# A recusa vem PRIMEIRO quando as duas batem: a frase da pessoa é mais acionável que um
# código de erro.
r, _ = pergunta(recusa_texto="Não tenho mais interesse", opt_out=CODIGO_OPT_OUT_META)
checa("recusa + opt-out: o SDR lê a RECUSA (a frase da pessoa)", r[0], "recusa")

# E a regra nova viaja crua para a rota, sem a rota saber que ela existe.
async def bruna_optou_por_sair(wa, db, *, agora):
    return ("opt_out_meta", higiene_disparo.MOTIVO_OPT_OUT_META)

r, envio, log = dispara([_lead(1, "Bruna", "5541999888777")], bruna_optou_por_sair)
checa("a rota PULA o opt_out_meta sem ter sido mudada", envio.await_count, 0)
checa("  e o conta em skipped_por_regra com o nome da regra",
      r["skipped_por_regra"], {"opt_out_meta": 1})
checa("  e NÃO o conta em skipped_nat (o significado não muda)", r["skipped_nat"], 0)
checa("  e o conta em skipped_total", r["skipped_total"], 1)
checa("  e o log nomeia a regra", "opt_out_meta" in log, True)


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado.")
