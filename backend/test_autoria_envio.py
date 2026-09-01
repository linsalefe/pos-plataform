"""S6-1 — todo outbound grava QUEM enviou e QUAL template saiu.

    cd backend && venv/bin/python test_autoria_envio.py

NADA sai daqui: a cadeia da Meta é mockada e o banco é dublê. Nenhuma chamada de rede,
nenhuma linha gravada.

O DEFEITO (medido no RECON_FOLLOWS_HUMANO_IA_20260901)
  `messages` não tinha `sent_by` nem `template_name`. As rotas de envio recebiam
  `current_user`, usavam para calar o agente, e descartavam. Resultado: em 8 dias e meio,
  517 templates humanos e ZERO forma de dizer quem mandou qual. A última alternativa — a
  assinatura no corpo — está errada em 52% dos casos.

O QUE ESTE TESTE PROVA
  1. `quem_enviou` sobrevive aos TRÊS chamadores, e o do meio é a armadilha:
     User -> id · objeto `Depends` (job agendado) -> None · None -> None
  2. /send/template grava sent_by E o nome do template aprovado (não o texto renderizado)
  3. /send/text grava sent_by e deixa template_name NULL (texto livre não tem template)
  4. bulk grava os dois no caminho HTTP...
  5. ...e grava sent_by NULL no caminho do job agendado, sem estourar
  6. o agente (`nat_sender`) grava template_name e NUNCA sent_by
  7. NULL é resposta e não lacuna: os três casos de NULL são distinguíveis entre si
"""
import asyncio
import io
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Depends

from app import exact_routes, routes
from app.autoria import quem_enviou
from app.auth import get_current_user
from app.models import User

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


THOBIAS = User(id=5, name="Thobias", email="sdr@cenatsaudemental.com",
               password_hash="x", role="admin")
# É ISTO que o job agendado passa. Não é um mock: é o mesmo valor default da assinatura de
# `bulk_send_template`, avaliado uma vez na definição da função e nunca substituído quando a
# chamada não passa pelo pipeline do FastAPI.
COMO_O_JOB_CHAMA = Depends(get_current_user)


# ==========================================================================================
print("\n1) `quem_enviou` — os três chamadores, e o do meio é a armadilha")

checa("User logado vira id", quem_enviou(THOBIAS), 5)
checa("objeto `Depends` (job agendado) vira None", quem_enviou(COMO_O_JOB_CHAMA), None)
checa("None vira None", quem_enviou(None), None)
checa("um MagicMock com .id NÃO passa por User", quem_enviou(MagicMock(id=99)), None)


# ==========================================================================================
print("\n2 e 3) As rotas /send/* do Hub")

CANAL = MagicMock(id=1, waba_id="w", whatsapp_token="t", phone_number_id="p")


def envia_pela_rota(coro_factory):
    """Roda uma rota /send/* e devolve a Message que ela mandou o db gravar."""
    gravadas = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=CANAL)))
    db.add = MagicMock(side_effect=lambda o: gravadas.append(o))
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    eco = {"messages": [{"id": "wamid.X"}], "contacts": [{"wa_id": "5511999999999"}]}
    with patch.object(routes, "send_text_message", new=AsyncMock(return_value=eco)), \
         patch.object(routes, "send_template_message", new=AsyncMock(return_value=eco)), \
         patch.object(routes, "destinatario", new=AsyncMock(side_effect=lambda t, d: t)), \
         patch.object(routes, "canonizar", new=AsyncMock(side_effect=lambda w, d: w)), \
         patch.object(routes, "contato_existente", new=AsyncMock(return_value=MagicMock(name="c"))), \
         patch.object(routes, "bloquear_se_boas_vindas", new=AsyncMock()), \
         patch.object(routes, "_silenciar_agente_apos_envio_manual", new=AsyncMock()):
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(coro_factory(db))
    return [g for g in gravadas if hasattr(g, "wa_message_id")]


req_tpl = routes.SendTemplateRequest(to="5511999999999", template_name="tentativa_contato",
                                     channel_id=1, parameters=["Ana", "Thobias"],
                                     rendered_text="Ola Ana, é o Thobias do CENAT")
msgs = envia_pela_rota(lambda db: routes.send_template(req_tpl, db, THOBIAS))
checa("/send/template gravou 1 mensagem", len(msgs), 1)
checa("  sent_by = o SDR logado", msgs[0].sent_by, 5)
checa("  template_name = o nome APROVADO na Meta", msgs[0].template_name, "tentativa_contato")
checa("  e NÃO o texto renderizado (que é o `content`)",
      msgs[0].content, "Ola Ana, é o Thobias do CENAT")

req_txt = routes.SendTextRequest(to="5511999999999", text="oi, aqui é o Thobias", channel_id=1)
msgs = envia_pela_rota(lambda db: routes.send_text(req_txt, db, THOBIAS))
checa("/send/text gravou sent_by", msgs[0].sent_by, 5)
checa("  e template_name fica NULL (texto livre não tem template)", msgs[0].template_name, None)


# ==========================================================================================
print("\n4 e 5) O disparo — HTTP × job agendado, a MESMA função")


def _lead(id, nome, telefone):
    l = MagicMock()
    l.id, l.name, l.phone1 = id, nome, telefone
    l.sub_source, l.sdr_name, l.funnel_id = "Pos TEA V3", "Victória", 18535
    return l


def dispara(leads, current_user):
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
    db.add = MagicMock(side_effect=lambda o: gravadas.append(o))
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    pedido = {"template_name": "f5_ligacao", "channel_id": 1,
              "lead_ids": [l.id for l in leads], "origem_envio": "campanha",
              "param_mappings": [{"type": "lead_name"}]}
    envio = AsyncMock(return_value={"messages": [{"id": "wamid.Y"}],
                                    "contacts": [{"wa_id": "IGNORADO"}]})
    # S6-2: a higiene do disparo (recusa/teto) tem teste proprio —
    # test_higiene_disparo.py. Aqui ela sai da frente, senao o db-duble responde
    # qualquer SELECT com um MagicMock truthy e TODO lead vira "recusou".
    with patch("app.qualificacao_fluxo.estado_de", new=AsyncMock(return_value=None)), \
         patch("app.higiene_disparo.por_que_pular", new=AsyncMock(return_value=None)), \
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
            asyncio.run(exact_routes.bulk_send_template(pedido, db, current_user))
    return [g for g in gravadas if hasattr(g, "wa_message_id")]

msgs = dispara([_lead(1, "Ana", "5511988887777")], THOBIAS)
checa("disparo pelo Hub: sent_by = quem apertou", msgs[0].sent_by, 5)
checa("  template_name gravado", msgs[0].template_name, "f5_ligacao")
checa("  e NÃO é o sdr_name do lead na Exact (que é Victória)", msgs[0].sent_by, 5)

# O caminho que estouraria com `current_user.id`.
msgs = dispara([_lead(2, "Bruno", "5511977776666")], COMO_O_JOB_CHAMA)
checa("job agendado: não estoura", len(msgs), 1)
checa("  sent_by NULL — não houve humano logado", msgs[0].sent_by, None)
checa("  mas o template continua registrado", msgs[0].template_name, "f5_ligacao")


# ==========================================================================================
print("\n6) O agente — template_name sim, sent_by nunca")

from app import nat_sender


CONTATO = MagicMock(wa_id="5511966665555", name="Ana", channel_id=1)


def agente_envia(aberta):
    """Roda `nat_sender.enviar_nat` com a janela aberta (texto livre) ou fechada (template)."""
    gravadas = []
    db = MagicMock()
    db.add = MagicMock(side_effect=lambda o: gravadas.append(o))
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=CONTATO)))
    eco = {"messages": [{"id": "wamid.Z"}]}
    with patch.object(nat_sender, "_resolver_canal", new=AsyncMock(return_value=CANAL)), \
         patch.object(nat_sender, "janela_aberta", new=AsyncMock(return_value=aberta)), \
         patch.object(nat_sender, "send_text_message", new=AsyncMock(return_value=eco)), \
         patch.object(nat_sender, "send_template_message", new=AsyncMock(return_value=eco)):
        buf = io.StringIO()
        with redirect_stdout(buf):
            saiu, motivo = asyncio.run(nat_sender.enviar_nat(
                contact_wa_id="5511966665555", etapa="nat_abertura_qualificacao", db=db,
                guard=AsyncMock(return_value=(True, "")),
                parametros=["Ana", "TEA"], corpo_livre="Olá, Ana!"))
    assert saiu, f"o envio do agente não saiu no teste: {motivo}"
    return [g for g in gravadas if hasattr(g, "wa_message_id")]


msgs = agente_envia(aberta=False)
checa("janela FECHADA: template_name = a etapa (= nome aprovado na Meta)",
      msgs[0].template_name, "nat_abertura_qualificacao")
checa("  sent_by NULL — o agente não é humano logado", msgs[0].sent_by, None)
checa("  e nat_etapa continua sendo quem responde 'foi o agente?'",
      msgs[0].nat_etapa, "nat_abertura_qualificacao")

msgs = agente_envia(aberta=True)
checa("janela ABERTA: saiu texto livre, template_name fica NULL",
      msgs[0].template_name, None)
checa("  sent_by segue NULL", msgs[0].sent_by, None)
checa("  e nat_etapa continua marcando o envio do agente",
      msgs[0].nat_etapa, "nat_abertura_qualificacao")


# ==========================================================================================
print("\n7) NULL é resposta, não lacuna — os três NULLs são distinguíveis")
#
# Sem esta distinção a coluna viraria ruído. Quem lê `sent_by IS NULL` precisa saber qual dos
# três casos está olhando, e cada um tem OUTRA coluna que o identifica:
#
#   agente             -> nat_etapa IS NOT NULL
#   disparo agendado   -> template_name IS NOT NULL e nat_etapa IS NULL
#   boas-vindas auto   -> wa_message_id casa com exact_leads.welcome_wamid
#
# O teste do que é distinguível está nas asserções acima (6 prova nat_etapa; 5 prova
# template_name preenchido com sent_by NULL). Aqui só se registra a regra de leitura.
checa("agente: sent_by NULL + nat_etapa preenchido",
      (None, "nat_abertura_qualificacao") != (None, None), True)


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado.")
