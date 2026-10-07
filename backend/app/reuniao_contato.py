"""A reunião de cada contato, para os filtros do SDR na tela de conversas (07/10/2026).

Uma consulta só sobre `reuniao_status` (algumas centenas de linhas) e o casamento por
`telefone.chave_telefone` em Python. Não é `LEFT JOIN` no SQL de `GET /contacts`: a chave em SQL
(`relatorios.chave_sql`) é uma expressão regular por contato e levava a consulta de 165 ms para
1,2 s; assim custa cerca de 20 ms (RECON_DEVOLUTIVA_ISA_20261007 §4.2).

QUAL REUNIÃO REPRESENTA A PESSOA: a próxima Vigente ainda não começada (é a que o SDR precisa
ver); sem ela, a mais recente que começou há no máximo `JANELA_RECENTE`. Reunião mais velha que
isso não aparece: o card não pode carregar o "fora do padrão" de um mês atrás.

OS TRÊS FILTROS, como o front recebe:
    marcada        Vigente, futura e não cortada (`cancelado_motivo` vazio)
    confirmada     marcada e `confirmado_em` preenchido
    fora_do_padrao a régua parou porque o lead respondeu algo fora dos botões e da lista
                   fechada (`regua_encerrada_motivo = 'humano'`, confirmação ou no-show)
"""
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.nat_guard import _agora_sp
from app.telefone import chave_telefone

JANELA_RECENTE = timedelta(days=7)
MOTIVO_FORA_DO_PADRAO = "humano"


def _resumo(r, agora: datetime) -> dict:
    futura = r.slot_inicio > agora
    marcada = r.exact_type == "Vigente" and futura and not r.cancelado_motivo
    return {
        "meeting_id": r.meeting_id,
        "inicio": r.slot_inicio.isoformat(),
        "marcada": marcada,
        "confirmada": marcada and r.confirmado_em is not None,
        "fora_do_padrao": r.regua_encerrada_motivo == MOTIVO_FORA_DO_PADRAO,
        # Para o tooltip do badge: por que a reunião não está "marcada", quando não está.
        "situacao": ("marcada" if marcada else r.cancelado_motivo
                     or ("cancelada" if r.exact_type == "Cancelada"
                         else "concluida" if r.exact_type == "Concluido"
                         else "passada" if not futura else r.exact_type.lower())),
    }


async def reunioes_por_chave(db: AsyncSession, agora: datetime | None = None) -> dict:
    """`{chave_telefone: resumo}`. Nunca levanta: sem reunião, a tela segue sem os filtros."""
    agora = agora or _agora_sp()
    try:
        linhas = (await db.execute(text("""
            SELECT meeting_id, telefone_chave, slot_inicio, exact_type, confirmado_em,
                   cancelado_motivo, regua_encerrada_motivo
            FROM reuniao_status
            WHERE telefone_chave <> '' AND slot_inicio >= :desde
            ORDER BY slot_inicio"""), {"desde": agora - JANELA_RECENTE})).all()
    except Exception as e:
        print(f"⚠️ reuniao_contato: espelho não lido ({type(e).__name__}: {e})")
        return {}
    escolhida: dict = {}
    for r in linhas:
        atual = escolhida.get(r.telefone_chave)
        futura_vigente = r.exact_type == "Vigente" and r.slot_inicio > agora
        if atual is None:
            escolhida[r.telefone_chave] = r
        elif futura_vigente:
            # A próxima Vigente futura vence (a ordem é por horário, então a 1ª que aparece).
            if not (atual.exact_type == "Vigente" and atual.slot_inicio > agora):
                escolhida[r.telefone_chave] = r
        elif not (atual.exact_type == "Vigente" and atual.slot_inicio > agora):
            escolhida[r.telefone_chave] = r          # sem futura: a mais recente
    return {k: _resumo(r, agora) for k, r in escolhida.items()}


def reuniao_do_contato(mapa: dict, wa_ids: list[str]) -> dict | None:
    """O resumo de qualquer uma das grafias do contato (a chave é tolerante ao 9º dígito)."""
    for w in wa_ids:
        achado = mapa.get(chave_telefone(w))
        if achado is not None:
            return achado
    return None
