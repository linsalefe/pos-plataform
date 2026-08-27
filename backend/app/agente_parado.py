"""A VARREDURA POR ESTADO — o complemento do vigia por evento (S4-2, 27/08/2026).

------------------------------------------------------------------------------------------
POR QUE UM SEGUNDO DETECTOR, SE O P3-A JÁ EXISTE
------------------------------------------------------------------------------------------
O vigia do P3-A (`qualificacao_fluxo.vigiar_resposta`) é ARMADO NO INBOUND: quando o lead
escreve, uma ação vence em +10 min e pergunta "o agente respondeu?". Isso cobre a falha que
ele foi feito para cobrir — o turno que termina "com sucesso" e não fala — e nada mais.

Quem já estava preso ANTES de o vigia existir não tem vigia. Quem cair num buraco cujo
inbound nem chegou a ser processado (pool esgotado batendo no webhook, P1-A) não tem vigia.
E ninguém varre o banco à procura de conversa encalhada. Medido em 26/08: a Erica
(5598984703419) e a Amanda Pavão (5544998336280) escreveram às 09:36 e 09:01, ficaram em
etapa ativa sem resposta por ~36 h, e o único mecanismo que ia tocar nelas era o
`encerrar_inativo` de 72 h — que as gravaria como `inatividade`, isto é, "o lead calou".

    vigia (P3-A)      por EVENTO   arma no inbound, vence em 10 min, alarme rápido
    varredura (S4-2)  por ESTADO   varre a cada 15 min, régua de 60 min, rede de fundo

São falhas diferentes e por isso são TIPOS diferentes de notificação:
`agente_mudo` é "este turno não falou"; `agente_parado` é "esta conversa está encalhada".
Reusar o mesmo tipo apagaria a distinção que os dois existem para criar — o mesmo erro que
a auditoria apontou nos `window_*`, onde tudo virava "Lead aguardando há 1h".

------------------------------------------------------------------------------------------
SÓ NOTIFICA. NUNCA ACORDA O AGENTE.
------------------------------------------------------------------------------------------
Decisão fechada, e a mais importante do módulo. Um varredor que reinjetasse a mensagem no
agente responderia uma pergunta de uma hora atrás como se nada tivesse acontecido, e faria
isso justamente nos casos em que o agente já demonstrou que não sabe lidar com aquela
conversa. Pior: um bug que faça o turno morrer viraria um LOOP de turnos mortos, a cada 15
minutos, sem ninguém sabendo. O varredor é um alarme; quem decide o que fazer é gente.

Não há uma única chamada de envio neste arquivo, e o teste trava isso lendo a fonte.

------------------------------------------------------------------------------------------
A RÉGUA: 60 MINUTOS
------------------------------------------------------------------------------------------
Seis vezes o prazo do vigia (10 min), de propósito. Este detector é a REDE, não o alarme
rápido: se o vigia funcionou, ele já avisou aos 10 min e a gestão já sabe há 50 minutos
quando esta varredura olha. Chegar antes disso só produziria dois avisos do mesmo caso.

60 min também passa por cima da supressão pela fala adiada do vigia
(`ESPERA_MAXIMA_COM_PENDENCIA` = 30 min) sem precisar repeti-la: um lead com fala adiada
pelo teto que ainda esteja esperando aos 60 minutos já é caso de alarme pela régua do
próprio vigia. Não há supressão aqui, e a ausência é deliberada.

------------------------------------------------------------------------------------------
O TETO DE 20, E POR QUE ELE É RUIDOSO QUANDO CORTA
------------------------------------------------------------------------------------------
Um incidente largo (a NAT muda para todo mundo) encheria a sineta da gestão com centenas de
avisos e o efeito prático seria o mesmo dos `window_*`: ninguém lê. O teto protege a leitura.
Mas teto que corta em silêncio é pior que teto nenhum — 20 avisos numa sineta com 300 casos
por baixo LÊ-SE como "são 20 casos". Por isso a varredura ordena pela espera (o mais preso
primeiro), corta em 20, e IMPRIME quantos ficaram de fora. Nenhum corte é silencioso.

------------------------------------------------------------------------------------------
ANTI-REPETIÇÃO: (contato, wa_message_id do último inbound)
------------------------------------------------------------------------------------------
A varredura roda a cada 15 min e a régua é de 60: sem anti-repetição, um lead encalhado
geraria 4 avisos por hora até alguém agir. A chave é o `wa_message_id` do inbound que está
sem resposta — enquanto for a MESMA mensagem sem resposta, é o MESMO caso e o aviso é um só.
Se o lead escrever de novo, o wa_message_id muda e um aviso novo sai, que é o certo: um lead
que insistiu é um caso diferente de um lead que desistiu.

Vai em `notifications.ref`, e a checagem em massa antes do INSERT usa o índice
`idx_notifications_dedup` (contact_wa_id, type, ref) — a mesma mecânica do
`window_alerts_job`.

E ATRÁS DELA HÁ CONSTRAINT (27/08, `migrate_agente_parado_dedup.py`):

    CREATE UNIQUE INDEX uq_notif_agente_parado
        ON notifications (contact_wa_id, ref) WHERE type = 'agente_parado';

Único e PARCIAL. Parcial porque a tripla global não pode virar única: `nat_sla` e
`nat_recuperacao` gravam `ref = '<kind>:<acao_id>'` de propósito, para que dois
escalonamentos do mesmo lead apareçam como dois avisos.

O SELECT continua sendo o caminho normal — é ele que evita o erro. O índice é a rede: numa
corrida (um segundo processo, um restart sobreposto), o INSERT duplicado levanta
IntegrityError, o `commit` do ciclo falha inteiro e o job imprime ❌. É perda de UM ciclo, é
RUIDOSA, e se cura sozinha: 15 min depois o SELECT já enxerga a linha vencedora e o ciclo
passa limpo. Perder um ciclo com barulho é melhor que duplicar aviso em silêncio.

------------------------------------------------------------------------------------------
FAIL-CLOSED
------------------------------------------------------------------------------------------
Um detector que morre em silêncio devolve o sistema exatamente ao estado de onde esta sprint
veio. Portanto:
  * `varrer()` LEVANTA se o GESTOR_USER_ID não existir — sem destinatário não há detecção,
    e fingir que varreu seria a falha silenciosa dentro do detector de falha silenciosa;
  * o job imprime BATIMENTO A CADA CICLO, inclusive quando não achou nada. "Nada no log"
    não pode significar ao mesmo tempo "está tudo bem" e "o loop caiu há três dias";
  * o try/except abraça o ciclo inteiro para o loop não morrer, e o erro sai com ❌.
"""
import asyncio
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import (ETAPAS_QUALIFICACAO_ATIVAS, Message, NatQualificacaoState,
                        Notification)
from app.nat_guard import GESTOR_USER_ID, _agora_sp
from app.telefone import variantes_wa_id

INTERVALO_SEGUNDOS = 900          # 15 min

# Quanto tempo o lead precisa estar sem resposta para virar caso. Ver a seção A RÉGUA.
ESPERA_MINIMA = timedelta(minutes=60)

# Teto de notificações por ciclo. Ver a seção O TETO DE 20 — quando corta, ele grita.
MAX_NOTIFICACOES_POR_CICLO = 20

# Tipo próprio na `notifications`. NÃO reusa `agente_mudo`: turno que não falou e conversa
# encalhada são falhas diferentes. `notifications.type` é VARCHAR(30) e não tem CHECK — os 14
# caracteres cabem, e não há migração.
TIPO_NOTIF_PARADO = "agente_parado"


async def _ultima_mensagem(contact_wa_id: str, direcao: str, db: AsyncSession):
    """A última mensagem naquela direção, nas DUAS grafias do telefone. Ou None.

    A tolerância ao 9º dígito não é detalhe: o agente envia para 13 dígitos e a Meta entrega
    o inbound com 12 em 59% das threads (medido em 26/08). Uma varredura estrita não veria o
    inbound do lead que ela está varrendo e o julgaria "sem inbound" — ou, pior, não veria o
    outbound do agente e acusaria conversa encalhada onde o agente respondeu. As duas
    metades do critério dependem disto.
    """
    vs = variantes_wa_id(contact_wa_id) or (contact_wa_id,)
    res = await db.execute(
        select(Message.timestamp, Message.wa_message_id)
        .where(Message.contact_wa_id.in_(vs), Message.direction == direcao)
        .order_by(Message.timestamp.desc()).limit(1))
    return res.first()


async def encalhada(contact_wa_id: str, db: AsyncSession, *, agora=None):
    """(ultimo_inbound_ts, wa_message_id, espera) se a conversa está parada; senão None.

    O critério, inteiro, num lugar só — é a mesma pergunta que a varredura faz em massa e que
    o `encerrar_inativo` faz para UM contato na hora de escolher o rótulo do encerramento.
    Duplicá-lo em dois lugares faria os dois divergirem no primeiro ajuste da régua.

    "Outbound" aqui é QUALQUER outbound, não só o do agente, e isso é de propósito: se um
    humano respondeu, o lead não está esperando — e a etapa já teria saído das ativas pela
    trava de envio manual (`qualificacao_fluxo.silenciar`). Contar só o outbound do agente
    acusaria conversa encalhada numa thread onde alguém acabou de falar com a pessoa.
    """
    agora = agora or _agora_sp()
    entrada = await _ultima_mensagem(contact_wa_id, "inbound", db)
    if entrada is None:
        return None                       # nunca escreveu: não há pergunta sem resposta
    saida = await _ultima_mensagem(contact_wa_id, "outbound", db)
    if saida is not None and saida.timestamp > entrada.timestamp:
        return None                       # respondemos depois da última fala dele
    espera = agora - entrada.timestamp
    if espera <= ESPERA_MINIMA:
        return None
    return entrada.timestamp, entrada.wa_message_id, espera


async def varrer(db: AsyncSession, *, agora=None) -> dict:
    """Um ciclo da varredura. Devolve o resumo; NÃO dá commit (quem chama commita).

    LEVANTA se o GESTOR_USER_ID não existir — ver FAIL-CLOSED no cabeçalho.
    """
    from app.nat_flow import telefone_legivel, usuario_existe

    agora = agora or _agora_sp()
    if not await usuario_existe(GESTOR_USER_ID, db):
        raise RuntimeError(f"GESTOR_USER_ID={GESTOR_USER_ID} não existe — a varredura de "
                           f"agente parado não tem para quem avisar")

    estados = (await db.execute(
        select(NatQualificacaoState).where(
            NatQualificacaoState.etapa.in_(ETAPAS_QUALIFICACAO_ATIVAS)))).scalars().all()

    casos = []
    for estado in estados:
        achado = await encalhada(estado.contact_wa_id, db, agora=agora)
        if achado is not None:
            ts, wa_message_id, espera = achado
            casos.append((espera, estado, ts, wa_message_id))

    # O mais preso primeiro: se o teto cortar, ele corta os casos MAIS NOVOS, não uma fatia
    # arbitrária da lista.
    casos.sort(key=lambda c: c[0], reverse=True)
    cortados = max(0, len(casos) - MAX_NOTIFICACOES_POR_CICLO)
    do_ciclo = casos[:MAX_NOTIFICACOES_POR_CICLO]

    # Anti-repetição em UMA consulta, não uma por caso.
    refs = [c[3] for c in do_ciclo if c[3]]
    ja_avisados = set()
    if refs:
        ja_avisados = set((await db.execute(
            select(Notification.ref).where(
                Notification.type == TIPO_NOTIF_PARADO,
                Notification.ref.in_(refs)))).scalars().all())

    criadas = 0
    for espera, estado, ts, wa_message_id in do_ciclo:
        if wa_message_id and wa_message_id in ja_avisados:
            continue
        minutos = int(espera.total_seconds() // 60)
        db.add(Notification(
            user_id=GESTOR_USER_ID, contact_wa_id=estado.contact_wa_id,
            type=TIPO_NOTIF_PARADO, ref=wa_message_id,
            title=f"AGENTE PARADO — conversa encalhada há {minutos} min",
            body=(f"{telefone_legivel(estado.contact_wa_id)} escreveu {ts:%d/%m %H:%M} e "
                  f"segue sem resposta. Etapa: '{estado.etapa}'. O agente NÃO será acordado "
                  f"— alguém precisa assumir a conversa.")))
        criadas += 1
        print(f"🧊 AGENTE PARADO: {estado.contact_wa_id} em '{estado.etapa}' há {minutos} "
              f"min — gestão (user {GESTOR_USER_ID}) avisada")

    return {"ativos": len(estados), "encalhados": len(casos), "notificados": criadas,
            "repetidos": len(do_ciclo) - criadas, "cortados_pelo_teto": cortados}


async def agente_parado_job():
    """Loop de 15 min. Registrado no lifespan de main.py, junto dos outros jobs.

    Dorme ANTES de trabalhar, como todos os outros jobs do main.py. Ver FAIL-CLOSED.
    """
    while True:
        await asyncio.sleep(INTERVALO_SEGUNDOS)
        try:
            async with async_session() as db:
                r = await varrer(db)
                await db.commit()
            print(f"⏱️  Varredura de agente parado: {r['ativos']} em etapa ativa, "
                  f"{r['encalhados']} encalhado(s), {r['notificados']} aviso(s) novo(s), "
                  f"{r['repetidos']} já avisado(s)")
            if r["cortados_pelo_teto"]:
                print(f"⚠️  Varredura de agente parado: {r['cortados_pelo_teto']} caso(s) "
                      f"NÃO notificado(s) neste ciclo pelo teto de "
                      f"{MAX_NOTIFICACOES_POR_CICLO} — os mais antigos vieram primeiro, e "
                      f"os cortados voltam no próximo ciclo")
        except Exception as e:
            print(f"❌ Erro no agente_parado_job: {type(e).__name__}: {e}")
