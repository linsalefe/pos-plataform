"""Lead espontâneo — token, rotas públicas e o elo com o chat.

    cd backend && venv/bin/python test_espontaneo.py

A Exact é MOCKADA (nenhum lead, nenhum box, nenhuma reunião real) e o WhatsApp também.
Mas o BANCO é o de verdade, e isso é decisão, não descuido:

  * a claim de uso único é um `UPDATE ... WHERE usado_em IS NULL` e vale pelo `rowcount`;
  * "um token vivo por contato" é um ÍNDICE ÚNICO PARCIAL.

Um dublê em memória diria "passou" para as duas coisas mesmo se elas tivessem sido removidas
do schema — que é exatamente o defeito que elas existem para impedir. Testar contra o banco
é o único jeito de a asserção significar alguma coisa.

TODA linha criada aqui usa wa_id `55000000XXXX` (inexistente, formato válido) e é apagada no
`finally`. O teste falha se as tabelas não voltarem à contagem inicial.
"""
import asyncio
import os
import sys
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from dotenv import load_dotenv

load_dotenv()

# A allowlist precisa conter o subSource do espontâneo ANTES de importar as rotas, que leem
# o env no import. Em produção isto é o CHECKPOINT da Exact; aqui é só o teste.
os.environ["AGENDAMENTO_SUBSOURCES"] = (
    os.getenv("AGENDAMENTO_SUBSOURCES", "PosMulheridades") + ",Espontaneo WhatsApp")

from sqlalchemy import text                                          # noqa: E402

from app.agendamento import client, routes as ag_routes              # noqa: E402
from app.agendamento import token as tokens                          # noqa: E402
from app.agendamento.horarios import agora_sp                        # noqa: E402
from app.database import async_session                               # noqa: E402
from app.models import (ETAPA_ESP_LINK_ENVIADO, ETAPA_Q_CONCLUIDO,   # noqa: E402
                        ORIGEM_ESPONTANEO, Agendamento,
                        NatAgendamentoToken, NatQualificacaoState)

WA = "550000009901"
WA2 = "550000009902"
PREFIXO = "55000000990"

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def _req(ip="203.0.113.50"):
    r = MagicMock()
    r.headers.get.return_value = ip
    r.client.host = "127.0.0.1"
    return r


async def _limpar(db):
    await db.execute(text("DELETE FROM nat_agendamento_token "
                          "WHERE contact_wa_id LIKE :p"), {"p": PREFIXO + "%"})
    await db.execute(text("DELETE FROM nat_qualificacao_state "
                          "WHERE contact_wa_id LIKE :p"), {"p": PREFIXO + "%"})
    await db.execute(text("DELETE FROM agendamentos WHERE telefone LIKE :p"),
                     {"p": PREFIXO + "%"})
    await db.commit()


async def main():
    async with async_session() as db:
        antes = {
            "token": (await db.execute(text("SELECT count(*) FROM nat_agendamento_token"))).scalar(),
            "estado": (await db.execute(text("SELECT count(*) FROM nat_qualificacao_state"))).scalar(),
            "agend": (await db.execute(text("SELECT count(*) FROM agendamentos"))).scalar(),
        }
        await _limpar(db)
        try:
            await roteiro(db)
        finally:
            await _limpar(db)
            depois = {
                "token": (await db.execute(text("SELECT count(*) FROM nat_agendamento_token"))).scalar(),
                "estado": (await db.execute(text("SELECT count(*) FROM nat_qualificacao_state"))).scalar(),
                "agend": (await db.execute(text("SELECT count(*) FROM agendamentos"))).scalar(),
            }
            print()
            checa("limpeza: as 3 tabelas voltaram à contagem inicial", depois, antes)

    print()
    if falhas:
        print(f"❌ {len(falhas)} teste(s) falharam:")
        for f in falhas:
            print(f"   - {f}")
        return 1
    print("✅ Todos os testes passaram. Nada criado na Exact, nada enviado no WhatsApp.")
    return 0


async def roteiro(db):
    ag = agora_sp()

    # =====================================================================================
    print("\n1) Máscara do telefone — confirma sem expor")
    for formato in ("5585999995219", "558599995219", "85999995219", "8599995219"):
        checa(f"{formato} mascarado", tokens.mascarar(formato), "(85) 9****-5219")
    checa("estrangeiro não vira máscara falsa", tokens.mascarar("447834239129"), "")
    checa("vazio devolve vazio", tokens.mascarar(""), "")

    # =====================================================================================
    print("\n2) Emissão — um token vivo por contato")
    t1 = await tokens.emitir(db, contact_wa_id=WA, nome="Maria", curso="Pos TEA V3")
    await db.commit()
    checa("token tem 43 chars (token_urlsafe(32))", len(t1.token), 43)
    checa("nasce vivo", (t1.usado_em, t1.revogado_em), (None, None))
    checa("expira em 7 dias", (t1.expira_em.date() - ag.date()).days, 7)

    t2 = await tokens.emitir(db, contact_wa_id=WA)
    await db.commit()
    checa("pedir de novo devolve O MESMO token", t2.token, t1.token)
    checa("e não apaga o que já tinha sido coletado", (t2.nome, t2.curso),
          ("Maria", "Pos TEA V3"))

    t3 = await tokens.emitir(db, contact_wa_id=WA, formacao="Psicologia")
    await db.commit()
    checa("dado novo entra sem trocar o token", (t3.token, t3.formacao),
          (t1.token, "Psicologia"))

    n = (await db.execute(text("SELECT count(*) FROM nat_agendamento_token "
                               "WHERE contact_wa_id = :w"), {"w": WA})).scalar()
    checa("três emissões, UMA linha", n, 1)

    # =====================================================================================
    print("\n3) Resolução — os quatro estados que a página desenha")
    checa("válido", (await tokens.resolver(db, t1.token)).status, tokens.OK)
    checa("inexistente", (await tokens.resolver(db, "nao-existe")).status, tokens.INEXISTENTE)
    checa("vazio", (await tokens.resolver(db, "")).status, tokens.INEXISTENTE)

    t1.expira_em = ag - timedelta(minutes=1)
    await db.commit()
    checa("expirado", (await tokens.resolver(db, t1.token)).status, tokens.EXPIRADO)

    # Vencido sem uso: emitir REVOGA e cria outro. É o furo que `revogado_em` fechou —
    # sem ela o índice único trancaria o contato para sempre.
    t4 = await tokens.emitir(db, contact_wa_id=WA, nome="Maria")
    await db.commit()
    checa("vencido sem uso -> token NOVO", t4.token != t1.token, True)
    velho = (await db.execute(text("SELECT revogado_em IS NOT NULL, usado_em IS NULL "
                                   "FROM nat_agendamento_token WHERE token = :t"),
                              {"t": t1.token})).first()
    checa("o velho foi REVOGADO, não marcado como usado", tuple(velho), (True, True))
    checa("token revogado não resolve", (await tokens.resolver(db, t1.token)).status,
          tokens.INEXISTENTE)

    # =====================================================================================
    print("\n4) Claim de uso único — atômica")
    checa("primeira claim ganha", await tokens.consumir(db, t4.token), True)
    await db.commit()
    checa("segunda claim PERDE (sem isto seriam dois leads na Exact)",
          await tokens.consumir(db, t4.token), False)
    checa("depois de usado, resolve como 'usado'",
          (await tokens.resolver(db, t4.token)).status, tokens.USADO)
    await tokens.liberar(db, t4.token)
    await db.commit()
    checa("liberar devolve a claim", (await tokens.resolver(db, t4.token)).status, tokens.OK)

    # =====================================================================================
    print("\n5) Rotas públicas — o telefone NUNCA vem do corpo")
    r = await ag_routes.ler_token(t4.token, _req(), db)
    checa("GET devolve o que a tela precisa",
          (r["status"], r["nome"], r["telefone_mascarado"]),
          ("ok", "Maria", tokens.mascarar(WA)))
    checa("GET NÃO devolve o wa_id cru", WA in str(r), False)

    for ruim, esperado in [("nao-existe", 404), (None, 404)]:
        try:
            await ag_routes.ler_token(ruim or "", _req(), db)
            checa(f"GET {ruim!r} deveria recusar", "passou", esperado)
        except Exception as e:
            checa(f"GET {ruim!r} -> {esperado}", getattr(e, "status_code", None), esperado)

    # =====================================================================================
    print("\n6) Booking — cria lead+box+schedule e usa o telefone do TOKEN")
    estado = NatQualificacaoState(contact_wa_id=WA, origem=ORIGEM_ESPONTANEO,
                                  etapa=ETAPA_ESP_LINK_ENVIADO)
    db.add(estado)
    await db.commit()

    slot = None
    from app.agendamento import consultoras as equipe_mod
    for c in equipe_mod.consultoras():
        cand = c.grade.slots_candidatos()
        if cand:
            slot = cand[-1]
            break
    if slot is None:
        print("  (sem slot na grade agora — janela seca; pulando o booking)")
        return

    visto = {}

    async def _lead(**k):
        visto.update(k)
        return 4242

    with patch.object(client, "criar_box", AsyncMock(return_value=777)), \
         patch.object(client, "criar_lead", _lead), \
         patch.object(client, "agendar_reuniao", AsyncMock(return_value=True)), \
         patch.object(client, "meeting_por_lead", AsyncMock(return_value={"id": 999})), \
         patch.object(client, "listar_boxes", AsyncMock(return_value=[])), \
         patch("app.qualificacao_fluxo.send_nat_message",
               AsyncMock(return_value=True)) as envio:
        corpo = ag_routes.PedidoEspontaneo(nome="Maria Silva", email="m@x.com",
                                           slot=slot.id)
        resp = await ag_routes.agendar_por_token(t4.token, corpo, _req(), db)

    checa("booking respondeu ok", resp["ok"], True)
    checa("lead criado com o telefone DO TOKEN", visto.get("telefone"), WA)
    checa("subSource dedicado chegou ao LeadsAdd", visto.get("sub_source"),
          "Espontaneo WhatsApp")
    checa("token marcado como usado",
          (await tokens.resolver(db, t4.token)).status, tokens.USADO)
    marcado = (await db.execute(text("SELECT agendamento_id FROM nat_agendamento_token "
                                     "WHERE token = :t"), {"t": t4.token})).scalar()
    checa("token aponta para a reunião", marcado, resp["agendamento_id"])

    # ---- o elo com o chat -------------------------------------------------------------
    await db.refresh(estado)
    checa("estado do agente foi para concluido", estado.etapa, ETAPA_Q_CONCLUIDO)
    checa("e guarda qual reunião", estado.agendamento_id, resp["agendamento_id"])
    checa("a Nat confirmou no chat", envio.await_count, 1)
    texto = envio.await_args.kwargs.get("corpo_livre", "") if envio.await_args else ""
    checa("a confirmação traz a hora REAL do banco",
          slot.inicio.strftime("%H:%M") in texto, True)
    checa("e diz que é horário de Brasília", "Brasília" in texto, True)

    lembrete = (await db.execute(text(
        "SELECT count(*) FROM nat_scheduled_actions WHERE kind = 'lembrete_reuniao' "
        "AND contact_wa_id = :w AND status = 'pendente'"), {"w": WA})).scalar()
    checa("lembrete T-30 agendado pelo caminho que já existia", lembrete, 1)

    abertura = (await db.execute(text(
        "SELECT count(*) FROM nat_scheduled_actions WHERE kind = 'iniciar_qualificacao' "
        "AND contact_wa_id = :w"), {"w": WA})).scalar()
    checa("e NENHUMA abertura inútil foi enfileirada (o contato já tinha estado)",
          abertura, 0)

    await db.execute(text("DELETE FROM nat_scheduled_actions WHERE contact_wa_id LIKE :p"),
                     {"p": PREFIXO + "%"})
    await db.commit()

    # =====================================================================================
    print("\n7) Link já usado não agenda de novo")
    try:
        corpo = ag_routes.PedidoEspontaneo(nome="Maria Silva", slot=slot.id)
        await ag_routes.agendar_por_token(t4.token, corpo, _req("203.0.113.51"), db)
        checa("segundo booking deveria dar 409", "passou", 409)
    except Exception as e:
        checa("segundo booking -> 409", getattr(e, "status_code", None), 409)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
