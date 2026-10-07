"""Rastro das tentativas recusadas: nenhuma submissão da LP some sem deixar nome e telefone.

------------------------------------------------------------------------------------------
POR QUE EXISTE
------------------------------------------------------------------------------------------
Em 16–29/09/2026, 11 pessoas da LP de Direitos Humanos T4 foram recusadas por origem e
sumiram: o 400 era levantado ANTES da linha em `agendamentos`, e o journal só guardava a
origem e o IP. Seis delas nunca foram achadas (INVESTIGACAO_LEADS_LP_SPOTTER_20260930.md).
O 422 era pior: morre no Pydantic, antes do handler, e não deixava rastro nenhum.

Agora toda recusa nossa grava uma linha `passo='recusado'` com o que veio no request,
mesmo inválido, e escreve UMA linha grepável no journal. O próximo "lead não aparece no
Spotter" se resolve com um SELECT (AGENDAMENTO.md §3.5).

------------------------------------------------------------------------------------------
AS INVARIANTES DA LINHA `recusado`
------------------------------------------------------------------------------------------
  * **Nunca tem `lead_id`.** Vários leitores chaveiam `agendamentos` por `lead_id` sem olhar
    `passo` (o nome e a origem do agente em qualificacao_fluxo.py, os extras em
    qualificacao_dados.py). Uma linha recusada com `lead_id` emprestaria a esses leitores uma
    origem que a allowlist recusou. O `leadId` que veio no corpo vai no texto de `erro`.
  * **Nunca tem `box_id` nem consultora** (`sales_rep_email = ''`), e `slot_inicio =
    slot_fim = agora`, como a linha do `/lead`. Assim ela não cai na faxina, na subtração de
    slots em voo nem na carga das consultoras (que exclui `recusado` explicitamente). O slot
    pedido também vai no `erro`.
  * **Nunca vai para a fila do RD** nem para a Exact. Recusa é recusa: o comportamento para o
    visitante e para o CRM é o mesmo de antes.
  * `sub_source` guarda a origem COMO VEIO, sem validação. Numa linha recusada ela é
    exatamente o que se quer ver (`'Pos DH T4'`), e nenhum leitor a alcança sem `lead_id`.

------------------------------------------------------------------------------------------
FALHAR AO GRAVAR O RASTRO NUNCA MUDA A RESPOSTA
------------------------------------------------------------------------------------------
`registrar` não levanta. O visitante recebe o mesmo 400/404/409/422 de sempre, e o rastro
que não gravou vira um warning no journal, que continua tendo a linha `agendamento recusa:`
com o telefone.
"""
from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.agendamento.horarios import agora_sp
from app.models import PASSO_RECUSADO, Agendamento

# Os motivos padronizados. Texto curto, estável e grepável: é o que vai em
# `agendamentos.motivo_recusa` e no `motivo=` do journal. A validação vira
# `validacao_<campo>` (ver `motivo_de_validacao`).
ORIGEM_NAO_PERMITIDA = "origem_nao_permitida"
DUPLO_CLIQUE = "duplo_clique"
SLOT_INVALIDO = "slot_invalido"
SLOT_OCUPADO = "slot_ocupado"
LEAD_NAO_ENCONTRADO = "lead_nao_encontrado"
RATE_LIMIT = "rate_limit"
VALIDACAO_CORPO = "validacao_corpo"

# Cortes do que veio no request. O nome e o telefone seguem a decisão de arquitetura
# (120/30); o resto obedece às colunas.
MAX_NOME = 120
MAX_TELEFONE = 30
MAX_EMAIL = 200
MAX_ORIGEM = 100
MAX_ERRO = 1000

# Prefixo estável do journal. `grep "agendamento recusa:"` é o contrato.
PREFIXO_LOG = "agendamento recusa:"


def _texto(valor, limite: int) -> str | None:
    """O que veio no request, como texto e cortado. None continua None."""
    if valor is None:
        return None
    return str(valor)[:limite]


def _extras(valor) -> dict | None:
    """Extras só se vier um dicionário, e cortado: o 422 pode ter sido justamente por eles."""
    if not isinstance(valor, dict) or not valor:
        return None
    return {str(k)[:60]: str(v)[:200] for k, v in list(valor.items())[:10]}


def motivo_de_validacao(erros) -> str:
    """`validacao_<campo>` do PRIMEIRO erro do corpo; `validacao_corpo` se não houver campo.

    O campo é normalizado para `[a-z_]` porque vira chave de `GROUP BY` e de grep: `leadId`
    vira `validacao_leadid`, e um nome de campo estranho não quebra o padrão.
    """
    for erro in erros or []:
        loc = list(erro.get("loc") or [])
        if loc and loc[0] == "body":
            loc = loc[1:]
        if loc and isinstance(loc[0], str):
            campo = re.sub(r"[^a-z_]", "", loc[0].lower())
            if campo:
                return f"validacao_{campo}"[:40]
    return VALIDACAO_CORPO


def detalhe_de_validacao(erros) -> str:
    """`telefone: telefone deve ter DDD...; nome: ...` — o motivo legível do 422."""
    partes = []
    for erro in erros or []:
        loc = [str(p) for p in (erro.get("loc") or []) if p != "body"]
        partes.append(f"{'.'.join(loc) or 'corpo'}: {erro.get('msg', '')}")
    return "; ".join(partes)[:300]


def logar(*, rota: str, motivo: str, telefone, nome=None, origem=None, ip=None,
          detalhe: str = "") -> None:
    """UMA linha no journal, sempre com o mesmo prefixo e os mesmos campos.

    `!r` em tudo que veio do visitante: escapa quebra de linha, então um nome com `\\n` não
    parte a linha em duas nem forja uma linha falsa no journal. O telefone vai COMPLETO de
    propósito, porque é o dado que permite achar a pessoa.
    """
    print(f"⚠️ {PREFIXO_LOG} rota={rota} motivo={motivo} "
          f"tel={_texto(telefone, MAX_TELEFONE)!r} nome={_texto(nome, MAX_NOME)!r} "
          f"origem={_texto(origem, MAX_ORIGEM)!r} ip={ip} detalhe={detalhe!r}")


async def registrar(db: AsyncSession, *, rota: str, motivo: str, nome, telefone,
                    email=None, origem=None, extras=None, detalhe: str = "",
                    origem_ip: str | None = None) -> int | None:
    """Grava a linha `recusado` e devolve o id. NUNCA levanta: devolve None e avisa no log."""
    try:
        agora = agora_sp()
        ag = Agendamento(
            nome=_texto(nome, MAX_NOME) or "",
            email=_texto(email, MAX_EMAIL),
            telefone=_texto(telefone, MAX_TELEFONE) or "",
            slot_inicio=agora, slot_fim=agora,
            sales_rep_email="",
            sub_source=_texto(origem, MAX_ORIGEM),
            lead_id=None, box_id=None, lead_externo=False,
            extras=_extras(extras),
            passo=PASSO_RECUSADO, motivo_recusa=motivo[:40],
            erro=f"{rota} · {detalhe}"[:MAX_ERRO],
            origem_ip=_texto(origem_ip, 45),
            created_at=agora, updated_at=agora,
        )
        db.add(ag)
        await db.commit()
        return ag.id
    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass
        print(f"⚠️ agendamento: rastro da recusa NÃO gravado (rota={rota} motivo={motivo} "
              f"tel={_texto(telefone, MAX_TELEFONE)!r}) — {type(e).__name__}: {e}")
        return None
