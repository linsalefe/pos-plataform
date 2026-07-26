"""Envio unificado da NAT: uma função decide sozinha entre template e texto livre.

Módulo separado de nat_flow.py de propósito. Aqui mora "COMO a NAT fala"; lá mora "QUANDO
ela fala e para onde o lead vai depois". Misturar os dois faria a máquina de estados carregar
credencial de canal, janela de 24h e formato de payload da Meta — e qualquer mudança na Cloud
API viraria mudança no fluxo.

A regra da janela de 24h é da Meta, não nossa: fora dela só template aprovado passa; dentro
dela texto livre é permitido — e é melhor, porque template com variável ausente (a formação
em nat_sim, que falta em ~49% dos leads) não tem como ser montado com honestidade.

NADA sai daqui sem passar por nat_pode_atuar. Com a NAT desligada, toda chamada é no-op.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import nat_copy
from app.models import AutoWelcomeConfig, Channel, Contact, Message
from app.nat_guard import _agora_sp, nat_pode_atuar
from app.whatsapp import (send_interactive_buttons, send_template_message,
                          send_text_message)

# A Meta fecha a janela de atendimento 24h depois da ÚLTIMA mensagem do lead.
JANELA_ATENDIMENTO = timedelta(hours=24)


async def janela_aberta(contact_wa_id: str, db: AsyncSession) -> bool:
    """Houve mensagem DO LEAD nas últimas 24h?

    Considera só inbound: mensagem nossa não reabre janela nenhuma. Sem inbound algum, a
    janela está fechada — é o caso do lead novo, que por isso recebe a boas-vindas por
    template.

    Comparação em horário naive de SP, igual ao que messages.timestamp guarda (ver
    nat_guard._agora_sp: o banco está em UTC e um now() do Postgres ficaria 3h à frente).
    """
    res = await db.execute(
        select(Message.timestamp)
        .where(Message.contact_wa_id == contact_wa_id, Message.direction == "inbound")
        .order_by(Message.timestamp.desc())
        .limit(1)
    )
    ultimo = res.scalar_one_or_none()
    if ultimo is None:
        return False
    return (_agora_sp() - ultimo) < JANELA_ATENDIMENTO


async def _resolver_canal(contact: Contact, db: AsyncSession):
    """Canal do contato; sem ele, o mesmo canal que a boas-vindas usa.

    A leitura de auto_welcome_config aqui é SÓ leitura — a config não é alterada. O canal
    mora lá porque é onde o WABA do projeto está configurado; duplicar isso em nat_config
    criaria duas fontes de verdade para a mesma credencial.
    """
    channel_id = contact.channel_id
    if channel_id is None:
        cfg = await db.execute(select(AutoWelcomeConfig).where(AutoWelcomeConfig.id == 1))
        config = cfg.scalar_one_or_none()
        channel_id = config.channel_id if config else None
    if channel_id is None:
        return None
    ch = await db.execute(select(Channel).where(Channel.id == channel_id))
    return ch.scalar_one_or_none()


async def send_nat_message(contact_wa_id: str, etapa: str, db: AsyncSession, **vars) -> bool:
    """Envia a mensagem da NAT correspondente a `etapa`. True se saiu, False se não.

    `etapa` é a chave da mensagem em nat_copy (= nome do template que a respalda):
    nat_boasvindas, nat_sim, nat_confirma_transferencia, nat_outro_horario.

    `vars` aceita nome, curso e formacao.

    Decide sozinho o formato:
      janela ABERTA  -> texto livre (com botões interactive, se a etapa tiver botões)
      janela FECHADA -> template aprovado (com button_payloads, se tiver botões)

    Nunca envia sem nat_pode_atuar liberar. Falha fechada: qualquer erro devolve False.
    """
    def recusa(motivo: str) -> bool:
        print(f"🔒 NAT não enviou ({etapa} → {contact_wa_id}): {motivo}")
        return False

    try:
        res = await db.execute(select(Contact).where(Contact.wa_id == contact_wa_id))
        contact = res.scalar_one_or_none()
        if contact is None:
            return recusa("contato não existe no banco")

        # TRAVA CENTRAL — antes de qualquer coisa que custe rede.
        pode, motivo = await nat_pode_atuar(contact, db)
        if not pode:
            return recusa(motivo)

        canal = await _resolver_canal(contact, db)
        if canal is None:
            return recusa("canal não resolvido (contato sem channel_id e config sem canal)")

        nome = vars.get("nome") or contact.name or ""
        curso = vars.get("curso") or ""
        formacao = vars.get("formacao") or ""

        botoes = nat_copy.BOTOES_LIVRES.get(etapa)
        aberta = await janela_aberta(contact_wa_id, db)

        if aberta:
            corpo = nat_copy.texto_livre(etapa, nome=nome, curso=curso, formacao=formacao)
            if not corpo:
                return recusa(f"sem texto para a etapa '{etapa}'")
            if botoes:
                resultado = await send_interactive_buttons(
                    to=contact_wa_id, body=corpo, buttons=botoes,
                    phone_number_id=canal.phone_number_id, token=canal.whatsapp_token)
                tipo_msg = "interactive"
            else:
                resultado = await send_text_message(
                    to=contact_wa_id, text=corpo,
                    phone_number_id=canal.phone_number_id, token=canal.whatsapp_token)
                tipo_msg = "text"
        else:
            parametros = nat_copy.parametros_template(
                etapa, nome=nome, curso=curso, formacao=formacao)
            if parametros is None:
                # Hoje só nat_sim sem formação cai aqui. Ver nat_copy.parametros_template:
                # preferimos não enviar a afirmar algo sobre a formação do lead sem saber.
                return recusa(
                    f"template '{etapa}' não pode ser montado sem inventar dado do lead "
                    "(formação ausente e janela de 24h fechada)")
            corpo = nat_copy.texto_livre(etapa, nome=nome, curso=curso, formacao=formacao)
            resultado = await send_template_message(
                to=contact_wa_id, template_name=etapa, language=nat_copy.IDIOMA,
                phone_number_id=canal.phone_number_id, token=canal.whatsapp_token,
                parameters=parametros or None,
                button_payloads=nat_copy.payloads_dos_botoes(etapa))
            tipo_msg = "template"

        if "messages" not in resultado:
            return recusa(f"Meta recusou: {resultado}")

        # Registra o outbound para a conversa não ficar com buraco na tela do SDR.
        #
        # nat_etapa é o MARCADOR DE ENVIO DA NAT, e é gravado aqui porque este é o único
        # ponto do código por onde envio da NAT passa. Guarda a etapa (nat_boasvindas,
        # nat_sim, ...) e não um booleano: "quantos a NAT mandou na última hora" e "de qual
        # passo do fluxo" ficam sendo a mesma pergunta com granularidades diferentes.
        # É o que o teto por hora de nat_pode_atuar conta — ver contar_envios_nat_ultima_hora.
        db.add(Message(
            wa_message_id=resultado["messages"][0]["id"],
            contact_wa_id=contact_wa_id,
            channel_id=canal.id,
            direction="outbound",
            message_type=tipo_msg,
            content=corpo,
            timestamp=_agora_sp(),
            status="sent",
            nat_etapa=etapa,
        ))
        print(f"📤 NAT enviou '{etapa}' para {contact_wa_id} "
              f"({'texto livre' if aberta else 'template'}, janela "
              f"{'aberta' if aberta else 'fechada'})")
        return True

    except Exception as e:
        return recusa(f"erro inesperado: {type(e).__name__}: {e}")
