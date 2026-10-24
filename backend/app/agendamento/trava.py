"""Trava de reaplicação: quem já tem reunião marcada não cria lead nem reunião nova pela LP.

------------------------------------------------------------------------------------------
POR QUE EXISTE
------------------------------------------------------------------------------------------
Em 30 dias até 24/10/2026, 50 pessoas aplicaram 2+ vezes e geraram 63 leads a mais na Exact.
Duas reaplicaram com reunião Vigente e marcaram o MESMO horário com a outra consultora: a
grade é a união das agendas, e o `BoxesAdd` cai na próxima consultora livre
(RECON_4_PEDIDOS_COMERCIAL_20261024_REPORT.md §2.1.3). A única trava era `_duplo_clique`,
de 90 segundos.

------------------------------------------------------------------------------------------
AS DECISÕES, E POR QUE CADA UMA
------------------------------------------------------------------------------------------
  * **Pessoa = `chave_telefone`.** Nunca `lead_id` (a Exact cria um lead por aplicação, é
    justamente o problema) nem telefone bruto (com e sem 55, com e sem o 9º dígito).

  * **Fonte = `reuniao_status`, não `agendamentos`.** Só ele enxerga a reunião que a SDR
    marcou direto na Exact (atraso máximo de 10 min do sync). Predicado: Vigente e
    `slot_inicio > agora`. Vigente com horário passado NÃO trava: há reunião de 16/10 ainda
    Vigente porque ninguém fechou na Exact, e essa pessoa pode e deve marcar outra.

  * **Mora nas rotas públicas, não em `fluxo.agendar`.** O agente e a remarcação chamam
    `fluxo.agendar` com `lead_id`, e a remarcação cria a reunião nova enquanto a antiga ainda
    pode aparecer Vigente no espelho. Travar lá dentro bloquearia a remarcação.

  * **Resposta 200 no formato do `_duplo_clique`.** Os snippets publicados (Netlify,
    WordPress) tratam 409 e 4xx como erro, e republicar LP demora. Com 200, o snippet antigo
    mostra "Agendado! <data>" ou "Recebemos seu contato!" sem mudar nada.

  * **Privacidade.** As rotas da LP são públicas e o telefone é DIGITADO: devolver data e
    consultora para qualquer número diria a um estranho que outra pessoa tem reunião. Os
    detalhes só saem quando o primeiro nome ou o e-mail batem com os da reunião. Na dúvida,
    resposta genérica. Na página do token o telefone vem do link que a Nat mandou para
    aquele WhatsApp, então ali a identidade já está provada.

Nada aqui escreve. O registro da reaplicação é a linha `recusado/ja_agendado` do rastro,
gravada pela rota.
"""
from __future__ import annotations

import unicodedata

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agendamento import consultoras as equipe_mod
from app.agendamento.horarios import agora_sp
from app.models import EXACT_TYPE_VIGENTE, Agendamento, ReuniaoStatus
from app.nomes import primeiro_nome
from app.telefone import chave_telefone

MENSAGEM_COM_DADOS = "Você já tem uma conversa marcada com a nossa consultora."
MENSAGEM_GENERICA = ("Já recebemos seu contato e sua conversa com a consultora está marcada. "
                     "Para remarcar, fale com a gente pelo WhatsApp.")
AVISO = "Para remarcar ou cancelar, fale com a gente pelo WhatsApp."


async def reuniao_vigente_futura(db: AsyncSession, telefone: str | None) -> ReuniaoStatus | None:
    """A reunião Vigente e futura desta pessoa, a mais próxima. None se não houver.

    Mesmo predicado de `confirmacao.py` e `qualificacao_guard.py`. Telefone ilegível dá
    chave `""`, que nunca casa: na dúvida, não trava.
    """
    chave = chave_telefone(telefone)
    if not chave:
        return None
    return (await db.execute(
        select(ReuniaoStatus).where(
            ReuniaoStatus.telefone_chave == chave,
            ReuniaoStatus.exact_type == EXACT_TYPE_VIGENTE,
            ReuniaoStatus.slot_inicio > agora_sp())
        .order_by(ReuniaoStatus.slot_inicio.asc())
        .limit(1)
    )).scalar_one_or_none()


def _primeiro_nome_norm(nome) -> str:
    """`"  JOÃO silva"` -> `"joao"`. Sem acento e minúsculo; `""` para o ilegível."""
    base = unicodedata.normalize("NFKD", primeiro_nome(nome) or "")
    return "".join(c for c in base if not unicodedata.combining(c)).lower()


def _email_norm(email) -> str:
    return (email or "").strip().lower() if isinstance(email, str) else ""


async def _emails_da_reuniao(db: AsyncSession, reuniao: ReuniaoStatus) -> set[str]:
    """E-mails que a pessoa digitou na LP para esta reunião ou para o lead dela.

    Vem de `agendamentos`, porque `exact_leads` não guarda e-mail. Reunião que a SDR marcou
    direto na Exact não tem linha aqui: aí só o nome vale.
    """
    filtros = []
    if reuniao.agendamento_id:
        filtros.append(Agendamento.id == reuniao.agendamento_id)
    if reuniao.lead_id:
        filtros.append(Agendamento.lead_id == reuniao.lead_id)
    if not filtros:
        return set()
    linhas = (await db.execute(
        select(Agendamento.email).where(or_(*filtros), Agendamento.email.isnot(None))
    )).scalars().all()
    return {e for e in (_email_norm(x) for x in linhas) if e}


async def identidade_bate(reuniao: ReuniaoStatus, nome, email, db: AsyncSession) -> bool:
    """Primeiro nome OU e-mail iguais aos da reunião existente. Qualquer dúvida -> False."""
    pn = _primeiro_nome_norm(nome)
    if pn and pn == _primeiro_nome_norm(reuniao.nome):
        return True
    em = _email_norm(email)
    if em and em in await _emails_da_reuniao(db, reuniao):
        return True
    return False


async def whatsapp_url(db: AsyncSession) -> str | None:
    """`wa.me` do canal do agente, o mesmo que atende a remarcação. None se não houver."""
    from app.models import AutoWelcomeConfig, Channel
    try:
        cfg = (await db.execute(select(AutoWelcomeConfig).where(
            AutoWelcomeConfig.id == 1))).scalar_one_or_none()
        cid = cfg.channel_id if cfg and cfg.channel_id else 1
        canal = (await db.execute(select(Channel).where(Channel.id == cid))).scalar_one_or_none()
    except Exception as e:
        print(f"⚠️ trava: canal do WhatsApp não lido ({type(e).__name__}: {e})")
        return None
    numero = "".join(c for c in (canal.phone_number or "") if c.isdigit()) if canal else ""
    return f"https://wa.me/{numero}" if numero else None


def resposta_ja_agendado(reuniao: ReuniaoStatus, bate: bool, url: str | None) -> dict:
    """O 200 da reaplicação travada, no formato do `_duplo_clique` mais `ja_agendado`.

    Sem identidade, `inicio`/`fim`/`consultora_nome` vão nulos: o snippet antigo cai no
    "Recebemos seu contato!", e o novo mostra a mensagem genérica.
    """
    def _iso(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S") if dt else None

    return {
        "ok": True,
        "ja_agendado": True,
        "agendamento_id": reuniao.agendamento_id,
        "lead_id": reuniao.lead_id,
        "inicio": _iso(reuniao.slot_inicio) if bate else None,
        "fim": _iso(reuniao.slot_fim) if bate else None,
        "fuso": "America/Sao_Paulo",
        "consultora_nome": equipe_mod.nome_de(reuniao.sales_rep_email or "") if bate else None,
        "mensagem": MENSAGEM_COM_DADOS if bate else MENSAGEM_GENERICA,
        "whatsapp_url": url,
        "aviso": AVISO,
    }


def logar(telefone, reuniao: ReuniaoStatus) -> None:
    print(f"🔁 reaplicação travada: {chave_telefone(telefone)} já tem reunião "
          f"{reuniao.meeting_id} em {reuniao.slot_inicio:%d/%m %H:%M}")
