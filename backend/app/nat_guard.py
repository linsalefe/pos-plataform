"""Trava central do fluxo NAT. Nada da NAT atua sem passar por aqui.

Princípio único: FALHA FECHADA. Qualquer dúvida, qualquer ausência de dado, qualquer exceção
inesperada → (False, motivo). Nunca (True) por omissão.

ONDE ESTÁ PLUGADA (reconferido em 2026-08-24):
  * nat_flow.iniciar_fluxo_nat  (nat_flow.py:481) — entrada do lead no fluxo;
  * nat_sender.send_nat_message (nat_sender.py:95) — TODO envio da NAT.

O NOME DA FUNÇÃO É A REFERÊNCIA; o número da linha é cortesia e envelhece sozinho. As duas
linhas acima já estavam erradas: a docstring dizia `nat_flow.py:340` desde 11/08, quando a
chamada nunca esteve ali — hoje a linha 340 é um comentário dentro de `transferir_para_sdr`.
Quem for conferir, use `grep -n nat_pode_atuar backend/app/nat_*.py`.

Ou seja: a função governa produção desde o sprint dos Blocos 2-3-4. O texto anterior deste
cabeçalho ("só CRIA a função, não está plugada em lugar nenhum") era herdado do sprint dos
Blocos 0-1 e ficou mentindo — quem lia o módulo para decidir se era seguro ligar a chave lia
que ela não valia nada. Foi corrigido em 11/08 (commit 39ac2cf); o RECON de 24/08 reportou o
problema como aberto por ter copiado o achado do ESTADO_NAT de 09/08 sem reconferir o arquivo.

As 5 verificações, nesta ordem:
  1. nat_config.nat_enabled é true?
  2. nat_start_at definido E register_date >= nat_start_at? (register_date NULL bloqueia)
  3. Funil do lead é 18535?
  4. assigned_to do contato está em (4, 5)?
  5. Teto de max_envios_hora não estourado na última hora?
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NatConfig, ExactLead, Contact, Message

# Mesmo offset fixo usado no resto do projeto (main.py:18). Sem DST, de propósito:
# é o que os timestamps gravados já usam.
SP_TZ = timezone(timedelta(hours=-3))

# Funil alvo da NAT. Apenas este. 18537 e 25588 são bloqueados de propósito — a
# auto_welcome_config em produção está mais ampla (18535,18537,25588), e é o guard que
# restringe, não aquela config (que NÃO deve ser alterada).
FUNIL_NAT = 18535

# SDRs elegíveis, por id literal. NÃO usar `role`: Valéria(4), Thobias(5) e Isa(2) estão
# todos como 'admin' no banco, então role não distingue SDR de gestor.
#
# Auditado de novo em 2026-07-26: `users` não tem CHECK em role, e os 7 gates do código são
# todos o literal `role != "admin"`. Não existe valor 'gestor' a que recorrer — por isso a
# gestora também entra por id, e o item "role gestor" saiu da migração desta sprint.
SDR_IDS_PERMITIDOS = frozenset({4, 5})

# Gestora (Isa). Último degrau do escalonamento do SLA, e destinatário de fallback quando um
# lead chega na transferência sem SDR atribuído. Mesma escolha por id literal, mesma razão.
GESTOR_USER_ID = 2

# ---------------------------------------------------------------------------------------
# MARCADOR DE ENVIO DA NAT — verificação 5
#
# O teto tem que contar SÓ o que a NAT enviou. Contar `direction='outbound'` seria errado:
# incluiria resposta manual de SDR (routes.py:218,263,321), a boas-vindas
# (exact_spotter.py:272) e o disparo em massa da tela de Automações (exact_routes.py:379).
# Uma campanha de 500 templates estouraria o teto da NAT sem a NAT ter mandado nada — e a
# reação natural seria subir o teto, evaporando a proteção.
#
# O marcador é `messages.nat_etapa` (TEXT nullable, criada em migrate_nat_sprint3.py), escrita
# num único ponto: nat_sender.send_nat_message, que é por onde TODO envio da NAT passa.
#
# `nat_etapa IS NOT NULL` é o predicado, e não `= True`, porque a coluna guarda a ETAPA que
# originou o envio (nat_boasvindas, nat_sim, ...). NULL é a resposta certa para todo o resto:
# boas-vindas (exact_spotter.py), resposta manual de SDR (routes.py), disparo em massa
# (exact_routes.py). Uma campanha de 500 templates não move este contador — que era o problema
# de contar `direction='outbound'`: estouraria o teto da NAT sem a NAT ter mandado nada, e a
# reação natural seria subir o teto, evaporando a proteção.
#
# A alternativa descartada foi `sent_by_ai`, que é coluna MORTA: nenhum código a escreve (só é
# lida em routes.py:534), 0 de 26.767 linhas com true. Escolher booleano foi o que a matou.
COLUNA_MARCADOR_ENVIO_NAT = "nat_etapa"


def _agora_sp() -> datetime:
    """Naive no fuso de SP — igual ao que é gravado em messages.timestamp.

    Não usar `now()` do Postgres aqui: o banco está em Etc/UTC (verificado) e os timestamps
    são gravados naive em SP (-3h). Um recorte com `now() - interval '1 hour'` ficaria 3h
    adiantado e NUNCA casaria com nada — o teto passaria sempre, silenciosamente.
    """
    return datetime.now(SP_TZ).replace(tzinfo=None)


# ---------------------------------------------------------------------------------------
# HORÁRIO COMERCIAL
#
# Mora aqui, e não em módulo próprio, porque é uma TRAVA: a pergunta que responde é a mesma
# que nat_pode_atuar responde — "a NAT pode agir agora?". Separar em outro módulo espalharia
# "quando a NAT pode atuar" por dois arquivos, e quem fosse auditar a segurança do fluxo
# teria que descobrir que existe um segundo lugar. Um módulo só, uma auditoria só.
#
# NÃO é chamada de dentro de nat_pode_atuar de propósito: o horário decide o CAMINHO (envia
# agora vs. enfileira em aguardando_horario), enquanto nat_pode_atuar decide se pode ou não
# haver ação. Fundi-las faria "fora do horário" virar bloqueio, e o lead que chega 20h seria
# descartado em vez de enfileirado para as 09h.
HORA_ABERTURA = 9    # 09:00 inclusive
HORA_FECHAMENTO = 19  # 19:00 exclusive — às 19:00 em ponto já está fechado


def dentro_horario_comercial(quando: datetime | None = None) -> bool:
    """09h–19h no fuso de São Paulo, segunda a sexta. Sem `quando`, usa agora.

    `quando` explícito é o que torna a função testável sem mock de relógio.

    Aceita datetime aware ou naive:
      * aware  -> convertido para SP_TZ. É o que faz 12:00 UTC valer como 09:00 SP.
      * naive  -> assumido JÁ em SP, que é como messages.timestamp é gravado no banco.
        Assumir UTC aqui jogaria toda decisão 3h para frente e a janela de fato viraria
        06h-16h SP, sem nenhum erro visível.

    LIMITAÇÃO CONHECIDA: feriado não é tratado. Em feriado nacional a NAT vai considerar
    horário comercial normal e disparar. Fora do escopo desta sprint — precisa de calendário
    de feriados, que não existe no projeto.
    """
    momento = quando if quando is not None else datetime.now(SP_TZ)

    if momento.tzinfo is not None:
        momento = momento.astimezone(SP_TZ)

    # weekday(): 0=segunda ... 5=sábado, 6=domingo. Fim de semana é fora em qualquer hora.
    if momento.weekday() >= 5:
        return False

    return HORA_ABERTURA <= momento.hour < HORA_FECHAMENTO


async def contar_envios_nat_ultima_hora(db: AsyncSession) -> int:
    """Envios ATRIBUÍVEIS À NAT na última hora.

    A query final é:

        SELECT count(*) FROM messages
         WHERE direction = 'outbound'
           AND timestamp > (agora_sp - 1h)
           AND nat_etapa IS NOT NULL

    Coberta pelo índice parcial idx_messages_nat_etapa_ts, que indexa só as linhas da NAT em
    vez de varrer as 26.767 (e crescendo) de messages — isto roda ANTES DE CADA ENVIO.

    O corte vem de _agora_sp(), nunca de now() do Postgres: o banco está em UTC e os
    timestamps são naive em SP, então um corte do banco ficaria 3h à frente e a contagem
    daria 0 para sempre — teto que nunca segura nada, sem erro visível.
    """
    corte = _agora_sp() - timedelta(hours=1)
    marcador = getattr(Message, COLUNA_MARCADOR_ENVIO_NAT)
    res = await db.execute(
        select(func.count()).select_from(Message).where(
            Message.direction == "outbound",
            Message.timestamp > corte,
            marcador.isnot(None),
        )
    )
    return int(res.scalar() or 0)


async def _carregar_config(db: AsyncSession):
    """Singleton id=1 de nat_config. Ausência = desligado."""
    res = await db.execute(select(NatConfig).where(NatConfig.id == 1))
    return res.scalar_one_or_none()


async def _resolver_lead_e_wa_id(lead_ou_contato, db: AsyncSession):
    """Normaliza a entrada em (funnel_id, register_date, wa_id).

    Aceita ExactLead, Contact, ou o dict `lead_data` que sync_exact_leads monta.
    Qualquer coisa que não dê para resolver devolve None nos campos — e quem chama bloqueia.
    """
    from app.exact_spotter import format_phone

    # Contact: não carrega funil nem register_date. Volta ao ExactLead pelo telefone.
    if isinstance(lead_ou_contato, Contact):
        wa_id = lead_ou_contato.wa_id
        res = await db.execute(select(ExactLead).where(ExactLead.phone1.isnot(None)))
        for lead in res.scalars():
            if format_phone(lead.phone1) == wa_id:
                return lead.funnel_id, lead.register_date, wa_id
        return None, None, wa_id

    if isinstance(lead_ou_contato, ExactLead):
        return (lead_ou_contato.funnel_id,
                lead_ou_contato.register_date,
                format_phone(lead_ou_contato.phone1 or ""))

    if isinstance(lead_ou_contato, dict):
        return (lead_ou_contato.get("funnel_id"),
                lead_ou_contato.get("register_date"),
                format_phone(lead_ou_contato.get("phone1", "") or ""))

    return None, None, None


async def nat_pode_atuar(lead_ou_contato, db: AsyncSession, *,
                         contar_envios=None) -> tuple[bool, str]:
    """Retorna (pode, motivo). Falha fechada: qualquer erro → (False, motivo).

    `contar_envios` é ponto de injeção para teste — em produção fica None e usa
    contar_envios_nat_ultima_hora.
    """
    def bloqueia(motivo: str) -> tuple[bool, str]:
        print(f"🔒 NAT bloqueada: {motivo}")
        return False, motivo

    try:
        # 1) KILL SWITCH
        config = await _carregar_config(db)
        if config is None:
            return bloqueia("nat_config inexistente (id=1) — sem config, NAT não atua")
        if not config.nat_enabled:
            return bloqueia("nat_enabled=false")

        funnel_id, register_date, wa_id = await _resolver_lead_e_wa_id(lead_ou_contato, db)

        # 2) CORTE POR DATA — por register_date, imune a backfill e a falha de sync.
        if config.nat_start_at is None:
            return bloqueia("nat_start_at não definido — corte de data ausente")
        if register_date is None:
            return bloqueia("register_date ausente no lead")
        if register_date < config.nat_start_at:
            return bloqueia(
                f"register_date {register_date} anterior ao corte {config.nat_start_at}")

        # 3) FUNIL
        if funnel_id != FUNIL_NAT:
            return bloqueia(f"funil {funnel_id} fora do alvo da NAT ({FUNIL_NAT})")

        # 4) SDR ATRIBUÍDO — ids literais, nunca `role`.
        if not wa_id:
            return bloqueia("sem telefone resolvível — não dá para achar o contato")
        res = await db.execute(select(Contact.assigned_to).where(Contact.wa_id == wa_id))
        row = res.first()
        if row is None:
            return bloqueia(f"contato {wa_id} não existe no banco")
        assigned_to = row[0]
        if assigned_to not in SDR_IDS_PERMITIDOS:
            return bloqueia(
                f"assigned_to={assigned_to} fora dos SDRs permitidos {sorted(SDR_IDS_PERMITIDOS)}")

        # 5) TETO POR HORA — só envios atribuíveis à NAT (ver COLUNA_MARCADOR_ENVIO_NAT).
        contador = contar_envios or contar_envios_nat_ultima_hora
        enviados = await contador(db)
        teto = config.max_envios_hora
        if teto is None:
            return bloqueia("max_envios_hora não definido")
        if enviados >= teto:
            return bloqueia(f"teto de envios/hora estourado ({enviados}/{teto})")

        print(f"✅ NAT liberada para {wa_id} (funil {funnel_id}, SDR {assigned_to}, "
              f"{enviados}/{teto} na última hora)")
        return True, "ok"

    except Exception as e:
        # FALHA FECHADA — exceção inesperada nunca libera.
        return bloqueia(f"erro inesperado na verificação: {type(e).__name__}: {e}")
