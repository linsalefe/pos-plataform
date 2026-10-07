"""Grade: reunião cancelada na Exact não bloqueia mais o horário no site (07/10/2026).

    cd backend && venv/bin/python test_grade_cancelada.py

Escrito e NÃO executado na sprint de 07/10.

O QUE ESTE TESTE PROVA
  1. a consulta de `_ocupados_por_nos` exclui a linha cuja reunião no espelho está Cancelada
     ou tem `cancelado_motivo` (SQL compilado, sem banco)
  2. no banco real, dentro de uma transação desfeita no fim: agendamento com reunião Vigente
     bloqueia; Cancelada não bloqueia; Vigente com cancelado_motivo='sem_confirmacao' não
     bloqueia; sem linha no espelho bloqueia (o caso "em voo", que é a razão da consulta)
"""
import asyncio
from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.dialects import postgresql

from app.agendamento import disponibilidade as d
from app.database import async_session
from app.models import Agendamento, ReuniaoStatus

falhas = []
EMAIL = "comercial@cenatcursos.com.br"


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


# ==========================================================================================
print("\n1. SQL compilado")


class Captura:
    stmt = None

    async def execute(self, stmt):
        Captura.stmt = stmt

        class R:
            def all(self):
                return []
        return R()


asyncio.run(d._ocupados_por_nos(Captura(), datetime(2026, 10, 7), datetime(2026, 10, 8), EMAIL))
sql = str(Captura.stmt.compile(dialect=postgresql.dialect(),
                               compile_kwargs={"literal_binds": True}))
checa("NOT EXISTS sobre reuniao_status", "NOT (EXISTS" in sql and "reuniao_status" in sql, True)
checa("casa pelo agendamento_id", "reuniao_status.agendamento_id = agendamentos.id" in sql, True)
checa("Cancelada ou cancelado_motivo", "'Cancelada'" in sql and
      "reuniao_status.cancelado_motivo IS NOT NULL" in sql, True)


# ==========================================================================================
print("\n2. banco real, transação desfeita")
SLOT = datetime(2031, 1, 6, 10, 0)          # segunda-feira longe no futuro: não colide


async def cenario(exact_type, cancelado_motivo, com_espelho=True):
    async with async_session() as db:
        async with db.begin():
            agora = datetime(2026, 10, 7, 12, 0)
            ag = Agendamento(nome="zz teste grade", telefone="83900000000", slot_inicio=SLOT,
                             slot_fim=SLOT.replace(minute=45), sales_rep_email=EMAIL,
                             passo="agendado", created_at=agora, updated_at=agora)
            db.add(ag)
            await db.flush()
            if com_espelho:
                db.add(ReuniaoStatus(meeting_id=999000000 + ag.id, telefone_chave="8300000000",
                                     slot_inicio=SLOT, origem="hub", agendamento_id=ag.id,
                                     exact_type=exact_type, exact_type_visto_em=agora,
                                     cancelado_motivo=cancelado_motivo))
                await db.flush()
            ocup = await d._ocupados_por_nos(db, SLOT.replace(hour=0), SLOT.replace(hour=23),
                                             EMAIL)
            await db.execute(delete(ReuniaoStatus).where(ReuniaoStatus.agendamento_id == ag.id))
            await db.rollback()
            return SLOT in [i for i, _ in ocup]

checa("Vigente bloqueia", asyncio.run(cenario("Vigente", None)), True)
checa("Cancelada NÃO bloqueia", asyncio.run(cenario("Cancelada", None)), False)
checa("Vigente cortada (sem_confirmacao) NÃO bloqueia",
      asyncio.run(cenario("Vigente", "sem_confirmacao")), False)
checa("sem espelho (em voo) bloqueia", asyncio.run(cenario(None, None, com_espelho=False)), True)

print()
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ todos os casos passaram")
