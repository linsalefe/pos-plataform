"""Bloco 3 — Fluxo B enxuto e reagendamento pelos botões.

    cd backend && venv/bin/python test_fluxo_b.py

NADA sai daqui: envio, LLM, Exact e banco são dublês. Escrito e NÃO executado na sprint de
07/10.

O QUE ESTE TESTE PROVA
  1. gates: flag desligada = nada; allowlist pela chave tolerante; marca do estado
  2. oferta: hoje e amanhã pela data de SP; sem os dois, 2 próximos dias úteis; vazio = [];
     linha do D+1 só com horários que estão no contexto
  3. missão: estado antigo lê `MISSOES` (igual); estado do Fluxo B lê `MISSOES_B`
  4. abertura: flag desligada = etapa e template antigos; ligada = `aguardando_motivacao` +
     `nat_b_abertura` + marca; ligada mas fora da allowlist = antigo
  5. reativações: calendário (janela 8h–20h30, D+1 9h); armadas a cada pergunta no Fluxo B e
     follow de 20h no antigo; `_cancelar_follow` cancela as quatro
  6. handlers: fora da janela = skipped; lead respondeu = skipped; D+1 manda horários e arma
     o encerramento de 24h com `reativacao_esgotada`; o encerramento grava esse motivo
  7. prefere ligação: transferido com motivo, notificação `prefere_ligacao`, nota na Exact;
     no caminho antigo o mesmo rótulo é transferência comum
  8. `reabrir_para_oferta`: sem estado e em `concluido`; reunião antiga ignorada; sem horário
     não tenta
  9. `confirmacao.remarcar`: flag ligada chama a oferta e não manda a resposta fixa; desligada
     manda a resposta fixa e não chama a oferta
"""
import asyncio
import io
import json
import os
from contextlib import asynccontextmanager, redirect_stdout
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import confirmacao as cf
from app import fluxo_b
from app import qualificacao_fluxo as qf
from app import qualificacao_guard as guard
from app import qualificacao_llm as llm
from app.models import (ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_AGUARDANDO_FORMACAO,
                        ETAPA_Q_AGUARDANDO_MOTIVACAO, ETAPA_Q_CONCLUIDO, ETAPA_Q_ENCERRADO,
                        ETAPA_Q_ESCOLHENDO_SLOT, ETAPA_Q_OFERTANDO_AGENDA, ETAPA_Q_TRANSFERIDO,
                        KIND_ENCERRAR_INATIVO, KIND_FOLLOW_20H, KIND_REATIV_B_2H,
                        KIND_REATIV_B_30M, KIND_REATIV_B_4H, KIND_REATIV_B_D1, KINDS_REATIV_B,
                        TIPO_NOTIF_PREFERE_LIGACAO)
from app.nat_scheduler import AcaoAdiada, AcaoIgnorada

falhas = []
WA = "5583988046720"


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def D(*a):
    return datetime(*a)


def roda(coro):
    saida = io.StringIO()
    with redirect_stdout(saida):
        try:
            return asyncio.run(coro), saida.getvalue()
        except (AcaoIgnorada, AcaoAdiada) as e:
            return e, saida.getvalue()


def env(**kw):
    """Liga/desliga as flags do Fluxo B (sem cache, lidas a cada uso)."""
    base = {"FLUXO_B_ENXUTO": "", "FLUXO_B_SOMENTE_TELEFONES": ""}
    base.update(kw)
    return patch.dict(os.environ, base)


def estado(etapa=ETAPA_Q_AGUARDANDO_MOTIVACAO, b=True, **kw):
    base = dict(contact_wa_id=WA, exact_lead_id=52500000, etapa=etapa, origem="lp",
                formacao=None, ano_conclusao=None, atuacao=None, motivacao=None,
                agendamento_id=None, ultimo_wa_message_id=None, encerrado_em=None,
                encerrado_motivo=None, transferido_em=None, transferido_motivo=None,
                dados_extras={"fluxo": "b"} if b else None)
    base.update(kw)
    return SimpleNamespace(**base)


class DB:
    """Sessão de mentira: guarda o que foi `add`ado; flush/commit não fazem nada."""
    def __init__(self):
        self.adicionados = []

    def add(self, obj):
        self.adicionados.append(obj)

    async def flush(self):
        pass

    @asynccontextmanager
    async def begin_nested(self):
        yield


# ==========================================================================================
print("\n1. gates")
with env():
    checa("flag vazia = desligada", fluxo_b.flag_ligada(), False)
    checa("  ativo_para = False", fluxo_b.ativo_para(WA), False)
with env(FLUXO_B_ENXUTO="true", FLUXO_B_SOMENTE_TELEFONES="83988046720"):
    checa("flag ligada", fluxo_b.flag_ligada(), True)
    checa("allowlist casa a grafia de 13 dígitos", fluxo_b.telefone_permitido(WA), True)
    checa("allowlist casa a grafia de 12 dígitos", fluxo_b.telefone_permitido("558388046720"),
          True)
    checa("outro telefone fora", fluxo_b.ativo_para("5511999998888"), False)
with env(FLUXO_B_ENXUTO="true"):
    checa("allowlist vazia = todos", fluxo_b.ativo_para("5511999998888"), True)
e = estado(b=False, dados_extras={"como_conheceu": "Instagram"})
checa("estado antigo não é Fluxo B", fluxo_b.e_fluxo_b(e), False)
fluxo_b.marcar(e)
checa("marcar preserva o resto dos extras", e.dados_extras,
      {"como_conheceu": "Instagram", "fluxo": "b"})
checa("e passa a ser Fluxo B", fluxo_b.e_fluxo_b(e), True)


# ==========================================================================================
print("\n2. oferta hoje e amanhã")
qua = D(2026, 10, 7, 10, 0)                       # quarta
dias = ["2026-10-07", "2026-10-08", "2026-10-09"]
checa("hoje e amanhã, nesta ordem", qf.dias_da_oferta(dias, qua),
      [("2026-10-07", "hoje (07/10)"), ("2026-10-08", "amanhã (08/10)")])
checa("só amanhã tem horário", qf.dias_da_oferta(["2026-10-08", "2026-10-09"], qua),
      [("2026-10-08", "amanhã (08/10)")])
sex = D(2026, 10, 9, 19, 0)                       # sexta à noite: hoje e sábado vazios
checa("sem hoje/amanhã: 2 próximos dias úteis",
      qf.dias_da_oferta(["2026-10-12", "2026-10-13", "2026-10-14"], sex),
      [("2026-10-12", "segunda-feira (12/10)"), ("2026-10-13", "terça-feira (13/10)")])
checa("fim de semana na grade não conta como dia útil",
      qf.dias_da_oferta(["2026-10-11", "2026-10-12"], sex),
      [("2026-10-12", "segunda-feira (12/10)")])
checa("grade vazia = []", qf.dias_da_oferta([], qua), [])
checa("chave ilegível é ignorada", qf.dias_da_oferta(["lixo", "2026-10-07"], qua),
      [("2026-10-07", "hoje (07/10)")])

h = lambda hora: {"id": f"2026-10-07T{hora}:00", "hora": hora}    # noqa: E731
oferta = [("hoje (07/10)", [h("11:30"), h("14:30"), h("18:15")]),
          ("amanhã (08/10)", [h("10:00"), h("13:45"), h("18:15")])]
checa("linha do D+1: primeiro e último de cada dia", qf.linha_do_d1(oferta),
      "hoje 11h30, 18h15 ou amanhã 10h00, 18h15")
checa("linha do D+1 vazia = None", qf.linha_do_d1([]), None)
contexto = {x["hora"] for _, hs in oferta for x in hs}
checa("todo horário da linha está no contexto",
      all(p in {c.replace(":", "h") for c in contexto}
          for p in "11h30 18h15 10h00".split()), True)


async def _resumo(db):
    return {"2026-10-07": [h(f"{x:02d}:00") for x in range(9, 18)]}

with patch("app.agendamento.disponibilidade.resumo_por_dia", _resumo):
    r, _ = roda(qf.horarios_da_oferta(None, qua))
    checa("horarios_da_oferta: 3 por dia, espalhados",
          [x["hora"] for x in r[0][1]], ["09:00", "13:00", "17:00"])


# ==========================================================================================
print("\n3. missão por caminho")
for etapa in (ETAPA_Q_AGUARDANDO_MOTIVACAO, ETAPA_Q_OFERTANDO_AGENDA, ETAPA_Q_ESCOLHENDO_SLOT):
    checa(f"antigo/{etapa} = MISSOES", qf._missao(etapa, estado(etapa, b=False)),
          qf.MISSOES[etapa])
    checa(f"Fluxo B/{etapa} = MISSOES_B", qf._missao(etapa, estado(etapa)), qf.MISSOES_B[etapa])
checa("Fluxo B sem versão própria cai em MISSOES",
      qf._missao(ETAPA_Q_AGUARDANDO_ANO, estado(ETAPA_Q_AGUARDANDO_ANO)),
      qf.MISSOES[ETAPA_Q_AGUARDANDO_ANO])
checa("a missão nova traz o texto da venda",
      "A próxima etapa do processo seletivo" in qf.MISSOES_B[ETAPA_Q_AGUARDANDO_MOTIVACAO],
      True)
checa("e o marcador prefere_ligacao", "prefere_ligacao" in
      qf.MISSOES_B[ETAPA_Q_AGUARDANDO_MOTIVACAO], True)
checa("a missão antiga NÃO fala de prefere_ligacao",
      any("prefere_ligacao" in m for m in qf.MISSOES.values()), False)
checa("validador aceita prefere_ligacao com transferência",
      llm._validar(json.dumps({"mensagem": "ok", "etapa_cumprida": False,
                               "dado_extraido": None, "acao": "transferir_humano",
                               "motivo": "prefere_ligacao"}))[0]["motivo"],
      "prefere_ligacao")


# ==========================================================================================
print("\n4. abertura")


def abrir(*, formacao=None, ligada=False, permitidos="83988046720"):
    enviados, follows = [], []

    async def _enviar(wa, etapa, db, **kw):
        enviados.append((etapa, kw.get("parametros")))
        return True, "ok"

    async def _follow(e, db):
        follows.append(fluxo_b.e_fluxo_b(e))

    db = DB()
    acao = {"contact_wa_id": WA, "agora": qua,
            "payload": json.dumps({"lead_id": 52500000, "origem": "lp",
                                   "referencia_utc": "2026-10-07T13:00:00"})}
    with env(FLUXO_B_ENXUTO="true" if ligada else "",
             FLUXO_B_SOMENTE_TELEFONES=permitidos), \
         patch.object(qf, "estado_de", AsyncMock(return_value=None)), \
         patch.object(guard, "qualificacao_pode_iniciar", AsyncMock(return_value=(True, "ok"))), \
         patch.object(qf, "reuniao_de", AsyncMock(return_value=None)), \
         patch.object(qf, "_reuniao", AsyncMock(return_value=None)), \
         patch.object(qf, "_contato_ou_criar", AsyncMock(return_value=SimpleNamespace(wa_id=WA))), \
         patch("app.qualificacao_dados.resolver_dados", AsyncMock(return_value={
             "formacao": formacao, "faixa_investimento": None, "como_conheceu": None})), \
         patch.object(qf, "_nome", AsyncMock(return_value="Álefe")), \
         patch.object(qf, "_curso", AsyncMock(return_value="Saúde Mental")), \
         patch.object(qf, "_corpo_do_template", AsyncMock(return_value="corpo")), \
         patch.object(qf, "enviar_nat", _enviar), \
         patch.object(qf, "_agendar_encerramento", AsyncMock()), \
         patch.object(qf, "_agendar_follow", _follow):
        roda(qf.iniciar_qualificacao(acao, db))
    novo = db.adicionados[0] if db.adicionados else None
    return novo, enviados, follows

novo, env_, fol = abrir(formacao=None, ligada=False)
checa("flag desligada, sem formação: aguardando_formacao", novo.etapa,
      ETAPA_Q_AGUARDANDO_FORMACAO)
checa("  template nat_abertura_sem_formacao", env_[0][0], guard.ETAPA_ABERTURA_SEM_FORMACAO)
checa("  sem marca", fluxo_b.e_fluxo_b(novo), False)
novo, env_, _ = abrir(formacao="Psicologia", ligada=False)
checa("flag desligada, com formação: aguardando_ano", novo.etapa, ETAPA_Q_AGUARDANDO_ANO)
checa("  template nat_abertura_qualificacao", env_[0][0], guard.ETAPA_ABERTURA_QUALIFICACAO)
novo, env_, fol = abrir(formacao="Psicologia", ligada=True)
checa("flag ligada: aguardando_motivacao", novo.etapa, ETAPA_Q_AGUARDANDO_MOTIVACAO)
checa("  template nat_b_abertura com nome e pós", env_[0],
      (guard.ETAPA_ABERTURA_FLUXO_B, ["Álefe", "Saúde Mental"]))
checa("  formação da LP continua gravada", novo.formacao, "Psicologia")
checa("  marca do Fluxo B", fluxo_b.e_fluxo_b(novo), True)
checa("  reativações armadas na abertura (via _agendar_follow)", fol, [True])
novo, env_, _ = abrir(formacao=None, ligada=True, permitidos="11999998888")
checa("flag ligada, fora da allowlist: caminho antigo", novo.etapa,
      ETAPA_Q_AGUARDANDO_FORMACAO)
checa("nat_b_abertura conta no teto", guard.ETAPA_ABERTURA_FLUXO_B in
      guard.ETAPAS_DE_ENVIO_DO_AGENTE, True)


# ==========================================================================================
print("\n5. reativações: calendário, armar, cancelar")
cal = dict(qf.calendario_reativacao(D(2026, 10, 7, 10, 0)))
checa("pergunta às 10h: 30m, 2h, 4h e D+1", list(cal), list(KINDS_REATIV_B))
checa("  +30 min 10h30", cal[KIND_REATIV_B_30M], D(2026, 10, 7, 10, 30))
checa("  +4h 14h", cal[KIND_REATIV_B_4H], D(2026, 10, 7, 14, 0))
checa("  D+1 9h", cal[KIND_REATIV_B_D1], D(2026, 10, 8, 9, 0))
cal = dict(qf.calendario_reativacao(D(2026, 10, 7, 19, 0)))
checa("pergunta às 19h: só +30 min e D+1", list(cal), [KIND_REATIV_B_30M, KIND_REATIV_B_D1])
cal = dict(qf.calendario_reativacao(D(2026, 10, 7, 20, 15)))
checa("pergunta às 20h15: só o D+1 (20h45 fora da janela)", list(cal), [KIND_REATIV_B_D1])
cal = dict(qf.calendario_reativacao(D(2026, 10, 7, 23, 0)))
checa("clique às 23h: D+1 é o dia seguinte 9h", cal, {KIND_REATIV_B_D1: D(2026, 10, 8, 9, 0)})

agendados, cancelados = [], []


async def _ag(kind, wa, quando, payload, db):
    agendados.append((kind, quando, payload))
    return 1


async def _canc(kind, wa, db, **kw):
    cancelados.append(kind)
    return 0

with patch.object(qf, "_agora_sp", lambda: D(2026, 10, 7, 10, 0)), \
     patch.object(qf, "nat_agendar", _ag), patch.object(qf, "nat_cancelar", _canc), \
     patch("app.nat_scheduler.agendar", _ag), patch("app.nat_scheduler.cancelar", _canc):
    roda(qf._agendar_follow(estado(), None))
    checa("Fluxo B: arma as quatro", [k for k, _, _ in agendados], list(KINDS_REATIV_B))
    checa("  com armado_em no payload", agendados[0][2], {"armado_em": "2026-10-07T10:00:00"})
    checa("  cancela as quatro antes", cancelados[:4], list(KINDS_REATIV_B))
    checa("  e NÃO arma o follow de 20h", KIND_FOLLOW_20H in [k for k, _, _ in agendados],
          False)
    agendados.clear(); cancelados.clear()
    roda(qf._agendar_follow(estado(b=False), None))
    checa("caminho antigo: só o follow de 20h", [k for k, _, _ in agendados], [KIND_FOLLOW_20H])
    agendados.clear(); cancelados.clear()
    roda(qf._cancelar_follow(WA, "teste", None))
    checa("_cancelar_follow cancela o follow e as quatro", cancelados,
          [KIND_FOLLOW_20H] + list(KINDS_REATIV_B))
checa("KINDS_DA_CONVERSA inclui as quatro (agendou no meio)",
      set(KINDS_REATIV_B) <= set(qf.KINDS_DA_CONVERSA), True)


# ==========================================================================================
print("\n6. handlers das reativações e o encerramento")


def reativar(kind, *, agora=D(2026, 10, 8, 9, 0), e=None, ultimo=None, humano=False,
             ligada=True, linha_oferta=oferta, saiu=True):
    enviados, agend = [], []

    async def _enviar(wa, etapa, db, **kw):
        enviados.append((etapa, kw.get("parametros")))
        return (saiu, "ok" if saiu else "Meta recusou")

    async def _ag(kind, wa, quando, payload, db):
        agend.append((kind, quando, payload))
        return 1

    acao = {"id": 1, "contact_wa_id": WA,
            "payload": json.dumps({"armado_em": "2026-10-07T10:00:00"})}
    with env(FLUXO_B_ENXUTO="true" if ligada else "",
             FLUXO_B_SOMENTE_TELEFONES="83988046720"), \
         patch.object(qf, "_agora_sp", lambda: agora), \
         patch.object(qf, "estado_de", AsyncMock(return_value=e or estado())), \
         patch.object(qf, "_ultimo_inbound", AsyncMock(return_value=ultimo)), \
         patch.object(qf, "_alguem_falou_depois", AsyncMock(return_value=humano)), \
         patch("app.higiene_disparo._opt_out_meta", AsyncMock(return_value=None)), \
         patch.object(qf, "_nome", AsyncMock(return_value="Álefe")), \
         patch.object(qf, "horarios_da_oferta", AsyncMock(return_value=linha_oferta)), \
         patch.object(qf, "enviar_nat", _enviar), patch.object(qf, "nat_agendar", _ag):
        r, _ = roda(qf._reativar(acao, None, kind))
    return r, enviados, agend

r, env_, ag = reativar(KIND_REATIV_B_30M, agora=D(2026, 10, 7, 10, 30))
checa("+30 min: nat_b_reativ_30m com o nome", env_, [("nat_b_reativ_30m", ["Álefe"])])
r, env_, ag = reativar(KIND_REATIV_B_D1)
checa("D+1: nat_b_reativ_d1 com nome e horários", env_,
      [("nat_b_reativ_d1", ["Álefe", "hoje 11h30, 18h15 ou amanhã 10h00, 18h15"])])
checa("  arma encerrar_inativo em 24h com reativacao_esgotada", ag,
      [(KIND_ENCERRAR_INATIVO, D(2026, 10, 9, 9, 0), {"motivo": "reativacao_esgotada"})])
r, env_, _ = reativar(KIND_REATIV_B_2H, agora=D(2026, 10, 7, 21, 0))
checa("curta fora da janela = skipped, nada enviado",
      (isinstance(r, AcaoIgnorada), env_), (True, []))
r, env_, _ = reativar(KIND_REATIV_B_D1, agora=D(2026, 10, 8, 21, 0))
checa("D+1 fora da janela = adiada para 8h", (isinstance(r, AcaoAdiada), env_), (True, []))
r, env_, _ = reativar(KIND_REATIV_B_4H, ultimo=D(2026, 10, 7, 11, 0))
checa("lead respondeu depois da pergunta = skipped", (isinstance(r, AcaoIgnorada), env_),
      (True, []))
r, env_, _ = reativar(KIND_REATIV_B_4H, humano=True)
checa("humano falou depois = skipped", (isinstance(r, AcaoIgnorada), env_), (True, []))
r, env_, _ = reativar(KIND_REATIV_B_30M, ligada=False)
checa("flag desligada = skipped", (isinstance(r, AcaoIgnorada), env_), (True, []))
r, env_, _ = reativar(KIND_REATIV_B_30M, e=estado(ETAPA_Q_CONCLUIDO))
checa("etapa terminal = skipped", (isinstance(r, AcaoIgnorada), env_), (True, []))
r, env_, _ = reativar(KIND_REATIV_B_30M, e=estado(b=False))
checa("estado do caminho antigo = skipped", (isinstance(r, AcaoIgnorada), env_), (True, []))
r, env_, ag = reativar(KIND_REATIV_B_D1, linha_oferta=[])
checa("D+1 sem horário = skipped, sem encerramento", (isinstance(r, AcaoIgnorada), env_, ag),
      (True, [], []))
r, _, ag = reativar(KIND_REATIV_B_D1, saiu=False)
checa("D+1 recusado = skipped, sem encerramento", (isinstance(r, AcaoIgnorada), ag),
      (True, []))


def encerrar(payload):
    e = estado(ETAPA_Q_ESCOLHENDO_SLOT)
    with patch.object(qf, "estado_de", AsyncMock(return_value=e)), \
         patch("app.agente_parado.encalhada", AsyncMock(return_value=None)), \
         patch.object(qf, "_cancelar_follow", AsyncMock()):
        roda(qf.encerrar_inativo({"contact_wa_id": WA, "payload": payload}, DB()))
    return e

e = encerrar(json.dumps({"motivo": "reativacao_esgotada"}))
checa("encerramento depois do D+1: reativacao_esgotada", (e.etapa, e.encerrado_motivo),
      (ETAPA_Q_ENCERRADO, "reativacao_esgotada"))
e = encerrar("{}")
checa("encerramento de sempre (payload vazio): inatividade", e.encerrado_motivo, "inatividade")
e = encerrar(None)
checa("payload NULL: inatividade", e.encerrado_motivo, "inatividade")


# ==========================================================================================
print("\n7. prefere ligação")


def turno(e, resposta):
    notifs, notas, falas = [], [], []

    async def _notificar(est, titulo, corpo, db, *, tipo=qf.TIPO_NOTIF_AGENTE):
        notifs.append(tipo)

    async def _nota(lead_id, texto):
        notas.append(texto)
        return True

    async def _enviar(wa, etapa, db, **kw):
        falas.append(kw.get("corpo_livre"))
        return True, "ok"

    with patch.object(qf, "estado_de", AsyncMock(return_value=e)), \
         patch.object(qf, "_reuniao", AsyncMock(return_value=None)), \
         patch.object(qf, "_agendar_encerramento", AsyncMock()), \
         patch.object(qf, "_agendar_follow", AsyncMock()), \
         patch.object(qf, "_armar_vigia", AsyncMock()), \
         patch.object(qf, "_fatos", AsyncMock(return_value=("ctx", {"s1": "hoje 10:00"}))), \
         patch.object(qf, "_historico", AsyncMock(return_value=[])), \
         patch.object(llm, "conversar", AsyncMock(return_value=resposta)), \
         patch.object(qf, "_descartar_fala_adiada", AsyncMock()), \
         patch.object(qf, "_cancelar_follow", AsyncMock()), \
         patch.object(qf, "enviar_nat", _enviar), \
         patch.object(qf, "_notificar", _notificar), \
         patch("app.exact_notes.registrar_observacao", _nota):
        roda(qf.processar_texto(WA, "prefiro que me liguem", "wamid.X", DB()))
    return notifs, notas, falas

pede = {"mensagem": "ok", "etapa_cumprida": False, "dado_extraido": None,
        "acao": "transferir_humano", "motivo": "prefere_ligacao"}
e = estado(ETAPA_Q_AGUARDANDO_MOTIVACAO)
notifs, notas, falas = turno(e, pede)
checa("Fluxo B: transferido com motivo prefere_ligacao", (e.etapa, e.transferido_motivo),
      (ETAPA_Q_TRANSFERIDO, "prefere_ligacao"))
checa("  notificação do tipo prefere_ligacao", notifs, [TIPO_NOTIF_PREFERE_LIGACAO])
checa("  nota [NAT] Prefere ligação", len(notas) == 1 and
      notas[0].startswith("[NAT] Prefere ligação"), True)
checa("  despedida fixa, não o 'ok' do modelo", falas[0].startswith("Combinado!"), True)
e = estado(ETAPA_Q_AGUARDANDO_MOTIVACAO, b=False)
notifs, notas, falas = turno(e, pede)
checa("caminho antigo: o mesmo rótulo é transferência comum",
      (e.transferido_motivo.startswith("o LLM pediu transferência"), notifs, notas),
      (True, [qf.TIPO_NOTIF_AGENTE], []))

# Motivação cumprida no Fluxo B vai direto para escolhendo_slot (a oferta foi na mesma fala)
e = estado(ETAPA_Q_AGUARDANDO_MOTIVACAO)
with patch.object(qf, "_falar", AsyncMock(return_value=True)), \
     patch.object(qf, "_ofertar_agenda", AsyncMock()) as oferta_separada:
    roda(qf._avancar(e, "venda + horários", DB(), ofertados={"s1": "hoje 10:00"}))
checa("motivação cumprida (B) → escolhendo_slot", e.etapa, ETAPA_Q_ESCOLHENDO_SLOT)
checa("  sem o turno separado de _ofertar_agenda", oferta_separada.await_count, 0)
e = estado(ETAPA_Q_AGUARDANDO_MOTIVACAO)
with patch.object(qf, "_falar", AsyncMock(return_value=True)) as falar, \
     patch.object(qf, "_fallback", AsyncMock()) as fb:
    roda(qf._avancar(e, "venda sem horários", DB(), ofertados={}))
checa("motivação cumprida (B) sem horário → _fallback, nada falado",
      (fb.await_count, falar.await_count), (1, 0))


# ==========================================================================================
print("\n8. reabrir_para_oferta")


def reabrir(e, *, horarios=oferta, ligado=True):
    db = DB()

    async def _ofertar(est, db):
        est.etapa = ETAPA_Q_ESCOLHENDO_SLOT

    with patch.object(guard, "_carregar_config",
                      AsyncMock(return_value=SimpleNamespace(qualificacao_enabled=ligado))), \
         patch.object(qf, "horarios_da_oferta", AsyncMock(return_value=horarios)), \
         patch.object(qf, "estado_de", AsyncMock(return_value=e)), \
         patch.object(qf, "_contato_ou_criar",
                      AsyncMock(return_value=SimpleNamespace(wa_id=WA))), \
         patch.object(qf, "_agendar_encerramento", AsyncMock()), \
         patch.object(qf, "_ofertar_agenda", _ofertar), \
         patch.object(qf, "_agendar_follow", AsyncMock()) as follow:
        r, _ = roda(qf.reabrir_para_oferta("558388046720", 52500000, db,
                                           agendamento_antigo=971))
    novo = e if e is not None else (db.adicionados[0] if db.adicionados else None)
    return r, novo, follow.await_count

r, novo, follows = reabrir(None)
checa("sem estado: True e estado novo", (r, novo.etapa), (True, ETAPA_Q_ESCOLHENDO_SLOT))
checa("  origem exact, com a marca", (novo.origem, fluxo_b.e_fluxo_b(novo)), ("exact", True))
checa("  reunião antiga ignorada", qf._reunioes_ignoradas(novo), frozenset({971}))
checa("  reativações armadas depois da oferta", follows, 1)
e = estado(ETAPA_Q_CONCLUIDO, b=False, agendamento_id=971, encerrado_motivo=None)
r, novo, _ = reabrir(e)
checa("concluido: renasce e oferta", (r, novo.etapa), (True, ETAPA_Q_ESCOLHENDO_SLOT))
checa("  agendamento_id limpo", novo.agendamento_id, None)
checa("  histórico em dados_extras", novo.dados_extras["reaberturas"][0]["de"],
      ETAPA_Q_CONCLUIDO)
e = estado(ETAPA_Q_ENCERRADO, b=False, encerrado_motivo="inatividade",
           encerrado_em=D(2026, 10, 5, 9, 0))
r, novo, _ = reabrir(e)
checa("encerrado: encerrado_motivo preservado em dados_extras",
      (novo.encerrado_motivo, novo.dados_extras["reaberturas"][0]["encerrado_motivo"]),
      (None, "inatividade"))
e = estado(ETAPA_Q_CONCLUIDO, b=False)
r, novo, _ = reabrir(e, horarios=[])
checa("sem horário: False e estado intocado", (r, novo.etapa), (False, ETAPA_Q_CONCLUIDO))
r, novo, _ = reabrir(estado(ETAPA_Q_CONCLUIDO, b=False), ligado=False)
checa("agente desligado: False", r, False)


# ==========================================================================================
print("\n9. confirmacao.remarcar")


def remarcar(*, ligada, reabriu=True):
    respostas, notifs = [], []

    async def _responder(wa, texto, db):
        respostas.append(texto)
        return True

    async def _notificar(r, wa, tipo, titulo, corpo, db, **kw):
        notifs.append(corpo)

    r = SimpleNamespace(meeting_id=4774374, lead_id=52500000, agendamento_id=971,
                        slot_inicio=D(2026, 10, 9, 14, 30), cancelado_em=None,
                        cancelado_motivo=None, nome="Álefe Teste")
    with env(FLUXO_B_ENXUTO="true" if ligada else "",
             FLUXO_B_SOMENTE_TELEFONES="83988046720"), \
         patch.object(cf, "cancelar_regua", AsyncMock(return_value=0)), \
         patch.object(cf, "_nota", AsyncMock()), \
         patch.object(cf, "_notificar", _notificar), \
         patch.object(cf, "_responder", _responder), \
         patch.object(cf, "_nome", AsyncMock(return_value="Álefe")), \
         patch.object(qf, "reabrir_para_oferta", AsyncMock(return_value=reabriu)) as reab:
        roda(cf.remarcar(r, WA, DB()))
    return r, respostas, notifs, reab

r, resp, notifs, reab = remarcar(ligada=False)
checa("flag desligada: resposta fixa", resp, [cf.nat_copy.TEXTO_A_REMARCAR.format(nome="Álefe")])
checa("  oferta NÃO chamada", reab.await_count, 0)
checa("  reunião marcada como remarcar", r.cancelado_motivo, "remarcar")
r, resp, notifs, reab = remarcar(ligada=True)
checa("flag ligada: oferta chamada com a reunião antiga",
      (reab.await_count, reab.await_args.kwargs.get("agendamento_antigo")), (1, 971))
checa("  sem resposta fixa", resp, [])
checa("  SDR/consultora avisados de que os horários já foram", len(notifs) == 1 and
      "já mandou os horários" in notifs[0], True)
r, resp, notifs, reab = remarcar(ligada=True, reabriu=False)
checa("flag ligada mas a oferta não foi tentada: resposta fixa", len(resp), 1)

print()
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ todos os casos passaram")
