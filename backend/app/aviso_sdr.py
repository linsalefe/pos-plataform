"""Avisos por WhatsApp ao SDR e às consultoras (07/10/2026). FORA do agente.

Dois momentos têm pressa e não podem esperar alguém abrir o sino do Hub:

    corte (`confirmacao.confirm_a_corte`)   -> `nat_sdr_corte` para a consultora da reunião e
                                               os números de `SDR_AVISO_TELEFONES`
    "Posso falar agora" (`ligar_agora`)    -> `nat_sdr_ligar_agora` para as duas consultoras e
                                               os números de `SDR_AVISO_TELEFONES`

POR QUE NÃO `enviar_nat`. Ele manda para CONTATO (procura `Contact` por igualdade, aplica o
guard do agente, conta no teto por hora, carimba `nat_etapa` na conversa). Aqui o destino é um
número interno: vai direto por `whatsapp.send_template_message`, sem guard, sem teto e sem criar
contato na lista de conversas.

AUDITORIA SÓ NO LOG (`📣`). A sprint pedia gravar em `messages` com `nat_etapa='aviso_sdr'`,
mas `messages.contact_wa_id` é NOT NULL com FK para `contacts` (`models.Message`): não há como
gravar sem criar ou vincular um contato, que é o que a mesma decisão proíbe.

NUNCA LEVANTA. Cada destino tem try/except próprio: um número que falha não impede os outros,
e nada daqui desfaz o corte ou o clique, que já aconteceram.
"""
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import nat_copy

ENV_TELEFONES = "SDR_AVISO_TELEFONES"
DIAS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
IDIOMA = "pt_BR"


def telefones_sdr() -> list[str]:
    """`SDR_AVISO_TELEFONES`, normalizados, sem repetição. Vazio = só a Notification do Hub."""
    from app.agendamento.consultoras import normalizar_telefone
    vistos: list[str] = []
    for p in (os.getenv(ENV_TELEFONES, "") or "").split(","):
        t = normalizar_telefone(p)
        if t and t not in vistos:
            vistos.append(t)
    return vistos


def _unicos(numeros) -> list[str]:
    saida: list[str] = []
    for n in numeros:
        if n and n not in saida:
            saida.append(n)
    return saida


def destinatarios_corte(reuniao) -> list[str]:
    """A consultora da reunião e os SDRs. Sem telefone cadastrado, a consultora fica de fora."""
    from app.agendamento.consultoras import telefone_de
    return _unicos([telefone_de(reuniao.sales_rep_email or ""), *telefones_sdr()])


def destinatarios_ligar_agora() -> list[str]:
    """As duas consultoras e os SDRs: quem pegar, assume (decisão Álefe 07/10)."""
    from app.agendamento.consultoras import consultoras, normalizar_telefone
    return _unicos([*(normalizar_telefone(c.telefone) for c in consultoras()), *telefones_sdr()])


def quando(slot) -> str:
    """'qui 09/10 10:00'."""
    return f"{DIAS[slot.weekday()]} {slot:%d/%m %H:%M}"


def telefone_legivel(bruto: str | None) -> str:
    """'5583988046720' -> '(83) 98804-6720'. Sem formato reconhecível, devolve os dígitos."""
    d = "".join(ch for ch in (bruto or "") if ch.isdigit())
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return d


async def _canal(db: AsyncSession):
    from app.models import AutoWelcomeConfig, Channel
    cfg = (await db.execute(select(AutoWelcomeConfig).where(
        AutoWelcomeConfig.id == 1))).scalar_one_or_none()
    cid = cfg.channel_id if cfg and cfg.channel_id else 1
    return (await db.execute(select(Channel).where(Channel.id == cid))).scalar_one_or_none()


async def enviar_aviso(template: str, parametros: list, destinos: list[str],
                       db: AsyncSession) -> int:
    """Manda `template` para cada destino. Devolve quantos a Meta aceitou. Nunca levanta."""
    from app.whatsapp import send_template_message
    if not destinos:
        print(f"📣 aviso {template}: nenhum destino (consultora sem telefone e "
              f"{ENV_TELEFONES} vazio) — fica só a Notification do Hub")
        return 0
    try:
        canal = await _canal(db)
    except Exception as e:
        print(f"⚠️ aviso {template}: canal não resolvido ({type(e).__name__}: {e})")
        return 0
    if canal is None:
        print(f"⚠️ aviso {template}: sem canal configurado — nada enviado")
        return 0
    limpos = [" ".join(str(p or "").split()) or "-" for p in parametros]
    ok = 0
    for destino in destinos:
        try:
            r = await send_template_message(
                to=destino, template_name=template, language=IDIOMA,
                phone_number_id=canal.phone_number_id, token=canal.whatsapp_token,
                parameters=limpos)
            if "messages" in r:
                ok += 1
                print(f"📣 aviso {template} -> …{destino[-4:]}: enviado "
                      f"({r['messages'][0].get('id')})")
            else:
                print(f"⚠️ aviso {template} -> …{destino[-4:]}: Meta recusou {r}")
        except Exception as e:
            print(f"⚠️ aviso {template} -> …{destino[-4:]}: {type(e).__name__}: {e}")
    return ok


async def avisar_corte(reuniao, nome: str, pos: str, db: AsyncSession) -> int:
    try:
        return await enviar_aviso(nat_copy.NAT_SDR_CORTE,
                                  [nome, pos or "Pós-Graduação", quando(reuniao.slot_inicio)],
                                  destinatarios_corte(reuniao), db)
    except Exception as e:
        print(f"⚠️ aviso de corte da reunião {reuniao.meeting_id} falhou: "
              f"{type(e).__name__}: {e}")
        return 0


async def avisar_ligar_agora(reuniao, nome: str, pos: str, db: AsyncSession) -> int:
    try:
        return await enviar_aviso(nat_copy.NAT_SDR_LIGAR_AGORA,
                                  [nome, telefone_legivel(reuniao.telefone_bruto),
                                   pos or "Pós-Graduação"],
                                  destinatarios_ligar_agora(), db)
    except Exception as e:
        print(f"⚠️ aviso de ligar agora da reunião {reuniao.meeting_id} falhou: "
              f"{type(e).__name__}: {e}")
        return 0
