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
from app.nomes import primeiro_nome
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


async def send_nat_message(contact_wa_id: str, etapa: str, db: AsyncSession, *,
                           guard=None, corpo_livre: str | None = None,
                           parametros: list | None = None, **vars) -> bool:
    """Envia a mensagem da NAT correspondente a `etapa`. True se saiu, False se não.

    `etapa` é a chave da mensagem em nat_copy (= nome do template que a respalda):
    nat_boasvindas, nat_sim, nat_confirma_transferencia, nat_outro_horario.

    `vars` aceita nome, curso e formacao.

    Decide sozinho o formato:
      janela ABERTA  -> texto livre (com botões interactive, se a etapa tiver botões)
      janela FECHADA -> template aprovado (com button_payloads, se tiver botões)

    Falha fechada: qualquer erro devolve False.

    --------------------------------------------------------------------------------------
    OS TRÊS PARÂMETROS DO AGENTE DE PRÉ-QUALIFICAÇÃO
    --------------------------------------------------------------------------------------
    Os três são keyword-only e nascem em None: sem eles, esta função se comporta EXATAMENTE
    como antes, e os chamadores do fluxo de botões não mudaram uma linha.

    `guard` — a trava a consultar, no lugar de nat_pode_atuar. Mesmo ponto de injeção que
    nat_pode_atuar já oferece para `contar_envios` (nat_guard.py:194). Existe porque
    nat_pode_atuar checa `nat_enabled`, funil 18535 e assigned_to ∈ {4,5}: reusá-la no agente
    faria ligar o agente exigir ligar o fluxo de botões junto, e barraria os leads da LP que
    já migraram de funil. Cada fluxo traz a sua trava; nenhum envia sem uma.

    `corpo_livre` — o texto EXATO a enviar quando a janela está aberta. É como a fala gerada
    pelo LLM entra aqui sem passar por nat_copy, que só conhece os corpos fixos do fluxo
    velho. Com a janela FECHADA ele não é enviado (só template aprovado passa) e serve
    apenas de conteúdo da Message local.

    `parametros` — as variáveis do template, quando a janela está fechada, para templates que
    nat_copy não conhece (nat_abertura_*, nat_lembrete_reuniao).

    O que NÃO muda com eles: o marcador `messages.nat_etapa` continua sendo gravado aqui, e
    continua sendo o único lugar. É o que permite ao teto por hora de cada fluxo contar os
    SEUS envios filtrando por nome de etapa.
    """
    def recusa(motivo: str) -> bool:
        print(f"🔒 NAT não enviou ({etapa} → {contact_wa_id}): {motivo}")
        return False

    try:
        res = await db.execute(select(Contact).where(Contact.wa_id == contact_wa_id))
        contact = res.scalar_one_or_none()
        if contact is None:
            return recusa("contato não existe no banco")

        # TRAVA CENTRAL — antes de qualquer coisa que custe rede. Injetável, mas NUNCA
        # ausente: `guard or nat_pode_atuar` garante que não existe caminho sem trava.
        pode, motivo = await (guard or nat_pode_atuar)(contact, db)
        if not pode:
            return recusa(motivo)

        canal = await _resolver_canal(contact, db)
        if canal is None:
            return recusa("canal não resolvido (contato sem channel_id e config sem canal)")

        # ÚNICO ponto por onde toda mensagem da NAT passa — por isso o primeiro nome é
        # aplicado aqui, e não em _dados_do_lead: aquele dicionário também alimenta a
        # notificação do SDR, que precisa do cadastro inteiro para achar o lead.
        nome = primeiro_nome(vars.get("nome") or contact.name or "")
        curso = vars.get("curso") or ""
        formacao = vars.get("formacao") or ""

        botoes = nat_copy.BOTOES_LIVRES.get(etapa)
        aberta = await janela_aberta(contact_wa_id, db)

        if aberta:
            corpo = corpo_livre or nat_copy.texto_livre(
                etapa, nome=nome, curso=curso, formacao=formacao)
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
            if parametros is None:
                parametros = nat_copy.parametros_template(
                    etapa, nome=nome, curso=curso, formacao=formacao)
            if parametros is None:
                # Hoje só nat_sim sem formação cai aqui. Ver nat_copy.parametros_template:
                # preferimos não enviar a afirmar algo sobre a formação do lead sem saber.
                return recusa(
                    f"template '{etapa}' não pode ser montado sem inventar dado do lead "
                    "(formação ausente e janela de 24h fechada)")
            # Só para a Message local — o que SAI é o template aprovado. Um template
            # que nat_copy não conhece (os do agente) vem com o texto já renderizado em
            # `corpo_livre`; sem ele a conversa ficaria com um balão vazio na tela do SDR.
            corpo = corpo_livre or nat_copy.texto_livre(
                etapa, nome=nome, curso=curso, formacao=formacao) or f"[{etapa}]"
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
