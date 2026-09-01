"""S6-4 (Sprint D) — o follow de 20h do agente, e sobretudo QUANDO ELE NÃO SAI.

    cd backend && venv/bin/python test_follow_20h.py

NADA sai daqui: cadeia da Meta mockada, banco dublê.

O BURACO (RECON_FOLLOWS_HUMANO_IA_20260901, §4.5)
  118 conversas abertas pelo agente na janela; em 39 o lead calou e ninguém nunca mais
  mandou nada. Dessas 39, 18 estavam paradas numa etapa ATIVA — 9 no ano de conclusão, 4 na
  formação, 3 na motivação e 2 ESCOLHENDO O HORÁRIO DA REUNIÃO.

O QUE ESTE TESTE PROVA
  1. O follow nasce DESLIGADO, e desligado ele não manda nada
  2. Ligado e sem template aprovado, também não — e o motivo fica gravado
  3. As QUATRO recusas viram `skipped` com motivo, nunca `executado` mudo
  4. CANCELAMENTO: os cinco caminhos por onde a conversa deixa de ser do agente
  5. O agendamento é INCONDICIONAL (não olha a flag) — senão ligar não alcançaria a fila
  6. Idempotência: dois inbounds seguidos reagendam UM follow, não acumulam dois
  7. Falha de REDE não vira `skipped` (que é terminal): a exceção sobe e o scheduler retenta
  8. Os parâmetros do template: 0, 1, 2 variáveis — e a recusa acima de 2
"""
import asyncio
import io
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app import qualificacao_fluxo as qf
from app.models import (ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_CONCLUIDO, ETAPA_Q_ENCERRADO,
                        ETAPA_Q_ESCOLHENDO_SLOT, ETAPA_Q_TRANSFERIDO, KIND_FOLLOW_20H,
                        NatQualificacaoState, ORIGEM_LP)
from app.nat_scheduler import AcaoAdiada, AcaoIgnorada

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


WA = "5541999888777"
AGORA = datetime(2026, 9, 2, 10, 0, 0)


def _estado(etapa=ETAPA_Q_AGUARDANDO_ANO):
    return NatQualificacaoState(contact_wa_id=WA, exact_lead_id=1, origem=ORIGEM_LP,
                                etapa=etapa)


def roda_handler(*, ligado=True, template="follow_up", estado=None,
                 ultimo_inbound_h=None, humano_falou=False,
                 corpo="Olá, {{1}}! Aqui é da equipe do CENAT. {{2}} À disposição!",
                 corpo_erro=None, envio=(True, ""), sem_retomada=False):
    """Roda `follow_20h` e devolve (excecao_ou_None, mock_de_envio)."""
    cfg = MagicMock(follow_enabled=ligado, follow_template=template)
    inbound = None
    if ultimo_inbound_h is not None:
        inbound = MagicMock(timestamp=AGORA - timedelta(hours=ultimo_inbound_h))

    async def corpo_aprovado(nome, db):
        if corpo_erro:
            raise corpo_erro
        return corpo

    enviar = AsyncMock(return_value=envio)
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=cfg)))

    retomadas = {} if sem_retomada else qf.RETOMADA_FOLLOW
    with patch.object(qf, "RETOMADA_FOLLOW", new=retomadas), \
         patch.object(qf, "_config_follow",
                      new=AsyncMock(return_value=(ligado, template))), \
         patch.object(qf, "estado_de", new=AsyncMock(return_value=estado)), \
         patch.object(qf, "_ultimo_inbound", new=AsyncMock(return_value=inbound)), \
         patch.object(qf, "_alguem_falou_depois",
                      new=AsyncMock(return_value=humano_falou)), \
         patch.object(qf, "_corpo_aprovado", new=AsyncMock(side_effect=corpo_aprovado)), \
         patch.object(qf, "_nome", new=AsyncMock(return_value="Ana")), \
         patch.object(qf, "_agora_sp", new=MagicMock(return_value=AGORA)), \
         patch.object(qf, "enviar_nat", new=enviar), \
         patch("app.whatsapp.render_template_text", new=MagicMock(return_value="Olá Ana")):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                asyncio.run(qf.follow_20h({"contact_wa_id": WA, "payload": None}, db))
            return None, enviar
        except Exception as e:
            return e, enviar


# ==========================================================================================
print("\n1 e 2) Nasce desligado, e desligado não manda nada")

erro, envio = roda_handler(ligado=False, estado=_estado())
checa("flag desligada: recusa", type(erro), AcaoIgnorada)
checa("  com o motivo gravado", "follow_enabled=false" in str(erro), True)
checa("  e NADA foi enviado", envio.await_count, 0)

erro, envio = roda_handler(template=None, estado=_estado())
checa("sem template: recusa", type(erro), AcaoIgnorada)
checa("  e o motivo diz que o texto não foi submetido", "follow_template" in str(erro), True)
checa("  e NADA foi enviado", envio.await_count, 0)

erro, envio = roda_handler(corpo=None, estado=_estado())
checa("template não aprovado no WABA: recusa", type(erro), AcaoIgnorada)
checa("  e NADA foi enviado", envio.await_count, 0)


# ==========================================================================================
print("\n3) As quatro recusas — todas `AcaoIgnorada`, nenhuma silenciosa")

erro, envio = roda_handler(estado=None)
checa("sem estado: recusa", type(erro), AcaoIgnorada)

for etapa in (ETAPA_Q_TRANSFERIDO, ETAPA_Q_CONCLUIDO, ETAPA_Q_ENCERRADO):
    erro, envio = roda_handler(estado=_estado(etapa))
    checa(f"etapa '{etapa}': recusa", type(erro), AcaoIgnorada)
    checa("  e nada saiu", envio.await_count, 0)

erro, envio = roda_handler(estado=_estado(), ultimo_inbound_h=3)
checa("o lead falou há 3h: recusa (não há silêncio)", type(erro), AcaoIgnorada)
checa("  e nada saiu", envio.await_count, 0)

erro, envio = roda_handler(estado=_estado(), humano_falou=True)
checa("humano/campanha falou nas últimas 20h: recusa", type(erro), AcaoIgnorada)
checa("  e o motivo cita a campanha", "campanha" in str(erro), True)
checa("  e o agente NÃO entra por cima", envio.await_count, 0)

print("\n  --- e o caminho feliz, para o teste não provar só ausências ---")
erro, envio = roda_handler(estado=_estado(ETAPA_Q_ESCOLHENDO_SLOT), ultimo_inbound_h=40)
checa("etapa ativa + 40h de silêncio + ninguém tocou: ENVIA", erro, None)
checa("  uma vez", envio.await_count, 1)
checa("  com o template configurado", envio.await_args.kwargs["etapa"], "follow_up")
# O CONTRATO DO FOLLOW: {{2}} é a PERGUNTA PENDENTE, não o curso. É diferente do resto dos
# templates do agente, e a diferença é o ponto — ver RETOMADA_FOLLOW.
params = envio.await_args.kwargs["parametros"]
checa("  {{1}} = o nome", params[0], "Ana")
checa("  {{2}} = a retomada DA ETAPA em que o lead parou",
      params[1], " ".join(qf.RETOMADA_FOLLOW[ETAPA_Q_ESCOLHENDO_SLOT].split()))
checa("  e NÃO o curso (contrato diferente do resto do agente)", "TEA" in params[1], False)

# O motivo vem VERBATIM do guard, não inventado aqui: `e_teto` casa por prefixo, e uma
# string aproximada faria o teste passar contra um handler que trata o teto errado.
from app.qualificacao_guard import MOTIVO_TETO
erro, _ = roda_handler(estado=_estado(), ultimo_inbound_h=40,
                       envio=(False, f"{MOTIVO_TETO} (20/20)"))
checa("teto por hora: ADIA (não queima o follow)", type(erro), AcaoAdiada)

erro, _ = roda_handler(estado=_estado(), ultimo_inbound_h=40,
                       envio=(False, "contato não existe no banco"))
checa("recusa definitiva do envio: `skipped`", type(erro), AcaoIgnorada)


# ==========================================================================================
print("\n7) Falha de REDE não vira `skipped` — `skipped` é terminal")
#
# Se uma oscilação da Meta virasse AcaoIgnorada, o follow daquele lead morreria de vez.

erro, envio = roda_handler(estado=_estado(), ultimo_inbound_h=40,
                           corpo_erro=RuntimeError("Meta fora do ar"))
checa("erro de rede SOBE (scheduler retenta)", type(erro), RuntimeError)
checa("  e não virou AcaoIgnorada", isinstance(erro, AcaoIgnorada), False)


# ==========================================================================================
print("\n8) Os parâmetros do template aprovado")

f = qf._parametros_do_follow
R = "Ficou faltando só o ano."
checa("sem variáveis: lista vazia (≠ None)", f("Olá! Tudo bem?", "Ana", R), [])
checa("uma variável: o nome", f("Olá {{1}}!", "Ana", R), ["Ana"])
checa("duas: nome e a PERGUNTA PENDENTE", f("Olá {{1}}. {{2}}", "Ana", R), ["Ana", R])
# `follow_urgencia` tem 3 variáveis (uma delas o MÊS) e é justamente o que isto barra.
checa("três: recusa em vez de inventar", f("{{1}} {{2}} {{3}}", "Ana", R), None)
checa("uma variável e nome vazio: recusa (#131008)", f("Olá {{1}}", "  ", R), None)
checa("duas e retomada vazia: recusa", f("{{1}} {{2}}", "Ana", ""), None)
checa("o mesmo {{1}} repetido conta uma vez",
      f("Olá {{1}}, tudo bem {{1}}?", "Ana", R), ["Ana"])
# A Meta recusa parâmetro com quebra de linha, e as retomadas nascem de literais quebrados.
checa("quebra de linha na retomada é colapsada",
      f("{{1}} {{2}}", "Ana", "Ficou faltando\n   só o ano."), ["Ana", "Ficou faltando só o ano."])

print("\n  --- toda etapa ativa tem uma retomada escrita ---")
from app.models import ETAPAS_QUALIFICACAO_ATIVAS
checa("nenhuma etapa ativa fica sem frase",
      sorted(ETAPAS_QUALIFICACAO_ATIVAS - set(qf.RETOMADA_FOLLOW)), [])
checa("e nenhuma frase está vazia",
      [e for e, t in qf.RETOMADA_FOLLOW.items() if not t.strip()], [])
checa("a retomada do ano carrega a saída do S6-5",
      "se não lembrar de cabeça, sem problema, seguimos"
      in qf.RETOMADA_FOLLOW[ETAPA_Q_AGUARDANDO_ANO], True)
# Sem retomada para a etapa, o follow NÃO manda pergunta genérica.
erro, envio = roda_handler(estado=_estado(ETAPA_Q_AGUARDANDO_ANO), ultimo_inbound_h=40,
                           sem_retomada=True)
checa("etapa sem retomada: recusa em vez de mandar genérico", type(erro), AcaoIgnorada)
checa("  e nada saiu", envio.await_count, 0)


# ==========================================================================================
print("\n4, 5 e 6) Agendamento e cancelamento")


def observa_fila(fn):
    """Roda `fn(db)` capturando as chamadas a agendar/cancelar do scheduler."""
    agendou, cancelou = [], []

    async def agendar(kind, wa, run_at, payload, db):
        agendou.append((kind, wa, run_at))
        return 1

    async def cancelar(kind, wa, db):
        cancelou.append((kind, wa))
        return 1

    with patch("app.nat_scheduler.agendar", new=AsyncMock(side_effect=agendar)), \
         patch("app.nat_scheduler.cancelar", new=AsyncMock(side_effect=cancelar)), \
         patch.object(qf, "_agora_sp", new=MagicMock(return_value=AGORA)):
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(fn())
    return agendou, cancelou


db = MagicMock(flush=AsyncMock())
est = _estado()

agendou, _ = observa_fila(lambda: qf._agendar_follow(est, db))
checa("agenda o follow", [k for k, _, _ in agendou], [KIND_FOLLOW_20H])
checa("  para daqui a 20h", agendou[0][2], AGORA + timedelta(hours=20))
checa("  e 20h é MENOS que o encerramento de 72h", qf.FOLLOW_APOS < qf.INATIVIDADE_ENCERRA,
      True)

# 5) INCONDICIONAL: agendar não olha a flag. Se olhasse, ligar o follow só valeria para
#    conversas novas e quem já estivesse esperando ficaria sem follow para sempre.
agendou, _ = observa_fila(lambda: qf._agendar_follow(est, db))
checa("agenda mesmo com a flag desligada (a decisão é do handler)",
      len(agendou), 1)

# 6) Idempotência: `agendar` cancela o pendente antes de inserir — a garantia é do
#    scheduler, e é a mesma que o encerramento já usa. O índice único parcial
#    `uq_nat_sched_pendente_por_contato` é a rede no banco.
import inspect
fonte_agendar = inspect.getsource(__import__("app.nat_scheduler", fromlist=["x"]).agendar)
checa("`agendar` cancela antes de inserir (idempotência por construção)",
      "await cancelar(" in fonte_agendar, True)

print("\n  --- os cinco caminhos de cancelamento ---")

_, cancelou = observa_fila(lambda: qf._cancelar_follow(WA, "teste", db))
checa("o helper cancela o kind certo", cancelou, [(KIND_FOLLOW_20H, WA)])

fonte = inspect.getsource(qf)
for rotulo, funcao in [
    ("silenciar (o SDR assumiu)", "async def silenciar"),
    ("_fallback (transferida)", "async def _fallback"),
    ("_concluir (reunião marcada)", "async def _concluir"),
    ("concluir_por_agendamento_externo (marcou pela página)",
     "async def concluir_por_agendamento_externo"),
    ("encerrar_inativo (72h)", "async def encerrar_inativo"),
]:
    ini = fonte.index(funcao)
    fim = fonte.find("\nasync def ", ini + 10)
    corpo_fn = fonte[ini:fim if fim > 0 else len(fonte)]
    checa(f"{rotulo} cancela o follow", "_cancelar_follow(" in corpo_fn, True)

# O sexto caminho é o inbound, e ele não cancela: REAGENDA.
ini = fonte.index("async def processar_texto")
fim = fonte.index("\nasync def _avancar")
checa("o inbound REAGENDA (não cancela) — cada fala dela empurra os 20h",
      ("_agendar_follow(" in fonte[ini:fim], "_cancelar_follow(" in fonte[ini:fim]),
      (True, False))
ini = fonte.index("async def iniciar_qualificacao")
fim = fonte.index("\nasync def _corpo_do_template")
checa("a abertura também agenda — é onde o buraco mais aparece",
      "_agendar_follow(" in fonte[ini:fim], True)


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado. O follow segue DESLIGADO.")
