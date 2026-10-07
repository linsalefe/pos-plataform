"""A reunião de cada contato, para os filtros do SDR na tela de conversas (07/10/2026).

Uma consulta só sobre `reuniao_status` (algumas centenas de linhas) e o casamento por
`telefone.chave_telefone` em Python. Não é `LEFT JOIN` no SQL de `GET /contacts`: a chave em SQL
(`relatorios.chave_sql`) é uma expressão regular por contato e levava a consulta de 165 ms para
1,2 s; assim custa cerca de 20 ms (RECON_DEVOLUTIVA_ISA_20261007 §4.2).

QUAL REUNIÃO REPRESENTA A PESSOA: a próxima Vigente ainda não começada (é a que o SDR precisa
ver); sem ela, a mais recente que começou há no máximo `JANELA_RECENTE`. Reunião mais velha que
isso não aparece: o card não pode carregar o "fora do padrão" de um mês atrás.

OS FILTROS, como o front recebe:
    marcada        Vigente, futura e não cortada (`cancelado_motivo` vazio)
    confirmada     marcada e `confirmado_em` preenchido
    fora_do_padrao a régua parou porque o lead respondeu algo fora dos botões e da lista
                   fechada (`regua_encerrada_motivo = 'humano'`, confirmação ou no-show)
    nao_confirmou  marcada, sem `confirmado_em`, régua de confirmação ainda viva: ligar
    cancelar_na_exact  meeting_id da reunião cortada (`sem_confirmacao`) que a Exact ainda
                   diz Vigente e o SDR não marcou como tratada; None se não há
    devolver_ao_funil  meeting_id da régua de no-show que acabou sem resposta
                   (`d8_sem_resposta`) e o SDR não marcou como tratada; None se não há

AS DUAS PENDÊNCIAS OLHAM TODAS AS REUNIÕES DA PESSOA, não só a que representa o card, e sem a
janela de 7 dias: o D8 cai 8 dias depois do corte, e "devolver ao funil" sumiria exatamente no
dia em que aparece. Somem quando o SDR clica "Tratado" (`sdr_tratado_em`) ou, no caso do corte,
quando o sync vê a reunião `Cancelada`.
"""
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.nat_guard import _agora_sp
from app.telefone import chave_telefone

JANELA_RECENTE = timedelta(days=7)
MOTIVO_FORA_DO_PADRAO = "humano"
MOTIVO_TELEFONE_INVALIDO = "telefone_invalido"     # = confirmacao.MOTIVO_TELEFONE_INVALIDO
MOTIVO_CORTE = "sem_confirmacao"                    # confirmacao.confirm_a_corte
MOTIVO_D8 = "d8_sem_resposta"                       # noshow.noshow_d8


def _resumo(r, agora: datetime) -> dict:
    futura = r.slot_inicio > agora
    marcada = r.exact_type == "Vigente" and futura and not r.cancelado_motivo
    return {
        "meeting_id": r.meeting_id,
        "inicio": r.slot_inicio.isoformat(),
        "marcada": marcada,
        "confirmada": marcada and r.confirmado_em is not None,
        "fora_do_padrao": r.regua_encerrada_motivo == MOTIVO_FORA_DO_PADRAO,
        # A Meta recusou o número (131026, `confirmacao.encerrar_por_telefone_invalido`). A
        # reunião segue Vigente na Exact, mas o card mostra "telefone inválido" no lugar dela.
        "telefone_invalido": r.regua_encerrada_motivo == MOTIVO_TELEFONE_INVALIDO,
        "nao_confirmou": marcada and r.confirmado_em is None and r.regua_encerrada_em is None,
        "cancelar_na_exact": None,      # preenchidos em `reunioes_por_chave`, sobre todas
        "devolver_ao_funil": None,
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
                   cancelado_motivo, regua_encerrada_em, regua_encerrada_motivo, sdr_tratado_em
            FROM reuniao_status
            WHERE telefone_chave <> ''
              AND (slot_inicio >= :desde
                   OR (sdr_tratado_em IS NULL
                       AND ((cancelado_motivo = :corte AND exact_type = 'Vigente')
                            OR regua_encerrada_motivo = :d8)))
            ORDER BY slot_inicio"""),
            {"desde": agora - JANELA_RECENTE, "corte": MOTIVO_CORTE, "d8": MOTIVO_D8})).all()
    except Exception as e:
        print(f"⚠️ reuniao_contato: espelho não lido ({type(e).__name__}: {e})")
        return {}
    escolhida: dict = {}
    pend_corte: dict = {}
    pend_d8: dict = {}
    for r in linhas:
        if r.sdr_tratado_em is None and r.confirmado_em is None \
                and r.cancelado_motivo == MOTIVO_CORTE and r.exact_type == "Vigente":
            pend_corte[r.telefone_chave] = r.meeting_id       # a mais recente vence (ordem)
        if r.sdr_tratado_em is None and r.regua_encerrada_motivo == MOTIVO_D8:
            pend_d8[r.telefone_chave] = r.meeting_id
        if r.slot_inicio < agora - JANELA_RECENTE:
            continue                                          # só entrou pelas pendências
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
    saida = {k: _resumo(r, agora) for k, r in escolhida.items()}
    for chave in set(pend_corte) | set(pend_d8):
        resumo = saida.get(chave)
        if resumo is None:
            # A pessoa só tem a reunião antiga da pendência: o card ainda precisa do badge.
            resumo = saida[chave] = {"meeting_id": None, "inicio": None, "marcada": False,
                                     "confirmada": False, "fora_do_padrao": False,
                                     "telefone_invalido": False, "nao_confirmou": False,
                                     "situacao": "pendente"}
        resumo["cancelar_na_exact"] = pend_corte.get(chave)
        resumo["devolver_ao_funil"] = pend_d8.get(chave)
    return saida


def reuniao_do_contato(mapa: dict, wa_ids: list[str]) -> dict | None:
    """O resumo de qualquer uma das grafias do contato (a chave é tolerante ao 9º dígito)."""
    for w in wa_ids:
        achado = mapa.get(chave_telefone(w))
        if achado is not None:
            return achado
    return None
