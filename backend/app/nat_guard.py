"""Trava central do fluxo NAT. Nada da NAT atua sem passar por aqui.

Princípio único: FALHA FECHADA. Qualquer dúvida, qualquer ausência de dado, qualquer exceção
inesperada → (False, motivo). Nunca (True) por omissão.

Esta fase só CRIA a função. Ela NÃO está plugada em send_welcome_to_new_lead nem em lugar
nenhum — plugar muda comportamento de produção e é decisão separada.

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
SDR_IDS_PERMITIDOS = frozenset({4, 5})

# ---------------------------------------------------------------------------------------
# MARCADOR DE ENVIO DA NAT — verificação 5
#
# O teto tem que contar SÓ o que a NAT enviou. Contar `direction='outbound'` seria errado:
# incluiria resposta manual de SDR (routes.py:218,263,321), a boas-vindas
# (exact_spotter.py:272) e o disparo em massa da tela de Automações (exact_routes.py:379).
# Uma campanha de 500 templates estouraria o teto da NAT sem a NAT ter mandado nada — e a
# reação natural seria subir o teto, evaporando a proteção.
#
# Hoje NÃO EXISTE marcador confiável. Auditado em 2026-07-25:
#   - `messages.sent_by_ai` é coluna MORTA: nenhum código a escreve (só é lida em
#     routes.py:534 para saída de API). 0 de 26.766 linhas com true, 0 nulas.
#   - Nenhum dos 5 pontos que criam Message outbound a preenche.
#
# Conforme decidido: não se chuta um proxy. Enquanto a NAT não tem caminho de envio, nenhuma
# mensagem lhe é atribuível e 0 é a resposta CERTA — não um fallback. Quando o envio existir
# (Bloco 2+), define-se a coluna própria aqui e a contagem passa a valer sem tocar no resto.
COLUNA_MARCADOR_ENVIO_NAT = None  # ← definir junto com o primeiro envio real da NAT


def _agora_sp() -> datetime:
    """Naive no fuso de SP — igual ao que é gravado em messages.timestamp.

    Não usar `now()` do Postgres aqui: o banco está em Etc/UTC (verificado) e os timestamps
    são gravados naive em SP (-3h). Um recorte com `now() - interval '1 hour'` ficaria 3h
    adiantado e NUNCA casaria com nada — o teto passaria sempre, silenciosamente.
    """
    return datetime.now(SP_TZ).replace(tzinfo=None)


async def contar_envios_nat_ultima_hora(db: AsyncSession) -> int:
    """Envios ATRIBUÍVEIS À NAT na última hora.

    Enquanto COLUNA_MARCADOR_ENVIO_NAT for None, a NAT não tem caminho de envio e nada lhe
    é atribuível: retorna 0 por ser verdade, não por desistência.
    """
    if COLUNA_MARCADOR_ENVIO_NAT is None:
        return 0

    corte = _agora_sp() - timedelta(hours=1)
    marcador = getattr(Message, COLUNA_MARCADOR_ENVIO_NAT)
    res = await db.execute(
        select(func.count()).select_from(Message).where(
            Message.direction == "outbound",
            Message.timestamp > corte,
            marcador.is_(True),
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

        if COLUNA_MARCADOR_ENVIO_NAT is None:
            print("⚠️  NAT: teto não é exigível ainda — não há marcador de envio da NAT "
                  "(COLUNA_MARCADOR_ENVIO_NAT is None). Contador vale 0 por construção.")

        print(f"✅ NAT liberada para {wa_id} (funil {funnel_id}, SDR {assigned_to}, "
              f"{enviados}/{teto} na última hora)")
        return True, "ok"

    except Exception as e:
        # FALHA FECHADA — exceção inesperada nunca libera.
        return bloqueia(f"erro inesperado na verificação: {type(e).__name__}: {e}")
