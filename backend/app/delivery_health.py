"""Alerta de saúde de entrega — Fase 4 da sprint de observabilidade.

O sistema passou 4 dias mandando template que a Meta recusava (`131042`) sem que ninguém
soubesse. As Fases 1 a 3 fizeram o banco contar a verdade; esta faz alguém ser AVISADO da
verdade, sem precisar abrir o painel nem rodar consulta.

Duas notificações, uma por transição:

  QUEBROU  na última hora, ≥ 5 templates saíram e ≥ 50% falharam
  VOLTOU   estava em alerta e a taxa caiu para < 10% (com volume suficiente para afirmar isso)

------------------------------------------------------------------------------------------
POR QUE JOB PRÓPRIO E NÃO UM HANDLER DO nat_scheduler
------------------------------------------------------------------------------------------
O `nat_scheduler` é ótimo e não serve aqui, por três razões — a terceira é decisiva:

1. Ele é por CONTATO: "rode isto para este contato a esta hora", com índice único parcial em
   (kind, contact_wa_id, pendente). Esta varredura é global e não tem contato nenhum; entrar
   lá exigiria um `contact_wa_id` sentinela inventado só para satisfazer o modelo.

2. Ele é one-shot. Uma varredura recorrente viraria uma ação que se reagenda, e aí o
   intervalo de 15 min passaria a depender de a execução anterior ter conseguido reagendar.

3. **Ele desiste.** Handler que falha 3 vezes vira `falhou` e sai de circulação para sempre
   (MAX_TENTATIVAS_ACAO). Num monitor isso é fatal: três indisponibilidades transitórias do
   banco, espaçadas de 60s, e o vigia deixa de existir em silêncio — exatamente o tipo de
   falha invisível que esta sprint inteira existe para eliminar. O `while True` com try/except
   largo não tem como morrer: um ciclo ruim é um ciclo perdido, não o fim do job.

Além disso o scheduler é infraestrutura da NAT, que está desligada. A saúde de entrega
precisa ser vigiada independentemente disso — ela cobre TODO template que sai (boas-vindas,
disparo em massa, resposta de atendente), não só o que a NAT manda.

------------------------------------------------------------------------------------------
ONDE O ESTADO DO ALERTA MORA
------------------------------------------------------------------------------------------
Na própria tabela `notifications`: o estado é "qual das duas notificações foi a última". Sem
tabela nova, sem migração, e — o que importa — **sobrevive a restart**. Estado em memória
seria pior que não ter: um deploy no meio de um incidente zeraria o alerta e a gestão
receberia a mesma notificação de novo, que é precisamente o que o requisito proíbe.

O modo de falhar também está do lado certo: se alguém apagar as notificações, o estado lido
volta a "normal" e um incidente em curso é ANUNCIADO DE NOVO. Barulho a mais, nunca silêncio.

É o mesmo padrão do `window_alerts_job`, que já usa `notifications` como o próprio registro
do que já foi avisado.

------------------------------------------------------------------------------------------
POR QUE A RECUPERAÇÃO TAMBÉM EXIGE VOLUME MÍNIMO
------------------------------------------------------------------------------------------
Decisão desta fase, e vale explicitar porque não estava no enunciado: "voltou ao normal" só é
anunciado com pelo menos MINIMO_ENVIOS templates na janela, o mesmo piso da quebra.

Sem esse piso, uma hora sem NENHUM envio daria taxa 0% e dispararia "a entrega voltou ao
normal" — uma afirmação sem nenhuma evidência por trás. E é o cenário atual, não hipotético:
com `auto_welcome_config` desligada, o volume de template é praticamente zero, então o alerta
"normalizou" chegaria por ausência de dado, no dia seguinte ao incidente, sem nada ter sido
resolvido. Seria a mesma classe de mentira que os 68 carimbos falsos — um sucesso reportado
sem entrega por trás.

Com o piso, o comportamento é o desejado: o alerta fica de pé, silencioso, até que a fatura
seja quitada e os envios voltem a acontecer DE VERDADE. Aí sim, com volume real e taxa baixa,
a notificação de normalização chega — que é o que ela deveria significar.

------------------------------------------------------------------------------------------
POR QUE A RECUPERAÇÃO EXIGE ZERO FALHAS, E NÃO SÓ TAXA < 10%
------------------------------------------------------------------------------------------
Este é o desvio consciente do enunciado da sprint, e a razão está nos dados do próprio
incidente. O enunciado pedia "voltou = taxa < 10%". Rodando essa regra hora a hora sobre
23/07 a 26/07, é isto que teria acontecido:

    23/07 08h  QUEBROU  total=6    falhas=6   taxa=100%
    23/07 15h  voltou   total=49   falhas=4   taxa=  8%   ← FALSO
    24/07 11h  QUEBROU  total=7    falhas=4   taxa= 57%
    24/07 16h  voltou   total=128  falhas=3   taxa=  2%   ← FALSO
    estado ao final de 26/07: NORMAL

Duas normalizações anunciadas no meio de um incidente que não tinha acabado, e o estado final
dizendo "normal" enquanto 100% das boas-vindas ainda falhava.

A causa é DILUIÇÃO. `messages` não guarda o nome do template, só o texto renderizado, então a
taxa é global — e nas horas de campanha em massa o denominador explode. Às 16h de 24/07 saíram
128 templates: 125 de uma campanha ("Obrigada por se inscrever…"), que a Meta aceitou, e 3 da
boas-vindas da Nat, que falharam. A boas-vindas estava em 100% de falha e a taxa global marcou
2%. Uma campanha saudável estava escondendo um fluxo morto.

Exigir `falhas == 0` para anunciar recuperação mata o falso positivo sem inventar
segmentação que os dados de hoje não sustentam. Com a regra corrigida, o mesmo replay dá:

    23/07 08h  QUEBROU  total=6    falhas=6   taxa=100%
    estado ao final de 26/07: ALERTA          ← uma notificação, e a verdade

Durante os 4 dias do incidente NÃO houve uma única hora com ≥5 templates e zero falhas — ou
seja, a regra corrigida não teria dado nenhum alarme falso de volta, e o alerta teria ficado
de pé exatamente enquanto o problema existiu.

LIMITAÇÃO CONHECIDA, do outro lado: a mesma diluição pode ESCONDER uma quebra. Se a campanha
das 16h tivesse rodado às 08h, a taxa global de 23/07 08h teria sido baixa e o alerta não
dispararia naquele momento. Neste incidente ele disparou, mas isso foi sorte de ordenação, não
projeto. A correção de verdade é `messages.template_name`, para medir a saúde POR TEMPLATE em
vez de no agregado — migração, portanto fora do escopo desta sprint, e registrada como frente
própria no doc.
"""
import asyncio
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import Notification, User
# Reaproveitados de nat_guard para não existirem duas definições de "quem é a gestão" nem de
# "que horas são". nat_guard não importa nada além de models — não arrasta a NAT junto, e a
# NAT estar desligada não afeta este módulo.
from app.nat_guard import GESTOR_USER_ID, _agora_sp

# De quanto em quanto tempo a varredura roda.
INTERVALO_SEGUNDOS = 900  # 15 min

# Janela de observação. Uma hora é curta o bastante para o alerta chegar enquanto o incidente
# ainda importa, e longa o bastante para o denominador não virar ruído estatístico.
JANELA_MINUTOS = 60

# Piso de volume, para quebra E para recuperação. Abaixo disto a taxa não afirma nada: 2 de 2
# falhas é 100% e pode ser dois números inválidos digitados errado.
MINIMO_ENVIOS = 5

# Dois limiares, não um — a distância entre eles é histerese de propósito. Com um limiar só,
# uma taxa oscilando em volta dele geraria alerta/normalização/alerta a cada 15 min. Entre 10%
# e 50% nada acontece: quem está em alerta continua em alerta, quem está normal continua
# normal.
LIMIAR_QUEBROU = 0.50
LIMIAR_VOLTOU = 0.10

# Teto ABSOLUTO de falhas para anunciar recuperação — ver a seção sobre diluição na docstring.
# Zero é a única resposta defensável hoje: com a taxa medida no agregado de todos os templates,
# qualquer número > 0 permite que uma campanha grande e saudável declare "normalizou" com um
# fluxo inteiro ainda morto por baixo. Foi o que aconteceria em 23/07 e 24/07.
# Para voltar ao comportamento literal do enunciado, basta subir este número.
MAX_FALHAS_PARA_VOLTAR = 0

# `notifications.type` é VARCHAR(30) — os dois cabem com folga.
TIPO_QUEBROU = "delivery_health_down"
TIPO_VOLTOU = "delivery_health_up"

ESTADO_ALERTA = "alerta"
ESTADO_NORMAL = "normal"


async def medir(db: AsyncSession, *, agora=None) -> dict:
    """Total, falhas, taxa e erro mais frequente dos templates da última hora.

    SÓ `direction='outbound'` e `message_type='template'`. Mensagem recebida não tem entrega
    para medir, e texto de atendente vive dentro da janela de 24h (regra diferente, falha por
    motivo diferente) — misturar os dois diluiria a taxa justamente quando ela precisa gritar.
    """
    agora = agora if agora is not None else _agora_sp()
    inicio = agora - timedelta(minutes=JANELA_MINUTOS)

    linha = (await db.execute(text("""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE status = 'failed') AS falhas
        FROM messages
        WHERE direction = 'outbound'
          AND message_type = 'template'
          AND timestamp >= :inicio
          AND timestamp <= :agora
    """), {"inicio": inicio, "agora": agora})).first()

    total, falhas = (linha.total or 0), (linha.falhas or 0)

    # Erro mais frequente. NULL vira '(sem código)' porque falha sem código é o caso comum de
    # tudo que precede a persistência de statuses[].errors[] — e continuar mostrando "None"
    # esconderia que existem falhas ali.
    erro_top = None
    if falhas:
        r = (await db.execute(text("""
            SELECT coalesce(error_code::text, '(sem código)') AS codigo, count(*) AS n
            FROM messages
            WHERE direction = 'outbound'
              AND message_type = 'template'
              AND status = 'failed'
              AND timestamp >= :inicio
              AND timestamp <= :agora
            GROUP BY 1 ORDER BY n DESC, codigo LIMIT 1
        """), {"inicio": inicio, "agora": agora})).first()
        if r is not None:
            erro_top = {"codigo": r.codigo, "ocorrencias": r.n}

    return {
        "total": total,
        "falhas": falhas,
        "taxa": (falhas / total) if total else 0.0,
        "erro_top": erro_top,
        "inicio": inicio,
        "agora": agora,
    }


async def estado_atual(db: AsyncSession) -> str:
    """`alerta` ou `normal`, lido da última notificação de saúde de entrega.

    ORDER BY id, não created_at: o id é BIGSERIAL e a ordem dele é exata. `created_at` vem de
    `server_default=func.now()`, que é o relógio do banco (UTC) enquanto o resto do projeto
    grava horário de SP — ordenar por ele funcionaria, mas seria depender de um relógio que
    não é o nosso para responder uma pergunta de ordem.

    Sem nenhuma das duas → `normal`. É a resposta certa no primeiro boot e depois de uma
    limpeza de notificações (ver docstring do módulo: erra para o lado do barulho).
    """
    r = (await db.execute(text("""
        SELECT type FROM notifications
        WHERE user_id = :uid AND type IN (:down, :up)
        ORDER BY id DESC LIMIT 1
    """), {"uid": GESTOR_USER_ID, "down": TIPO_QUEBROU, "up": TIPO_VOLTOU})).first()

    return ESTADO_ALERTA if (r is not None and r.type == TIPO_QUEBROU) else ESTADO_NORMAL


def _corpo(m: dict) -> str:
    pct = f"{m['taxa'] * 100:.0f}%"
    partes = [f"{m['falhas']} de {m['total']} templates falharam na última hora ({pct})."]
    if m["erro_top"]:
        partes.append(f"Erro mais frequente: {m['erro_top']['codigo']} "
                      f"({m['erro_top']['ocorrencias']}x).")
    partes.append(f"Janela: {m['inicio']:%d/%m %H:%M} a {m['agora']:%d/%m %H:%M}.")
    return " ".join(partes)


async def _notificar(db: AsyncSession, tipo: str, titulo: str, corpo: str) -> bool:
    """Cria a notificação para a gestão. False se o usuário não existir.

    A conferência não é zelo excessivo: `notifications.user_id` tem FK para `users`, e apontar
    para um id inexistente estoura IntegrityError. Melhor descobrir com um SELECT do que com
    um rollback que derruba o ciclo inteiro — e, pior, sem registrar o alerta em lugar nenhum.
    """
    if (await db.execute(select(User.id).where(User.id == GESTOR_USER_ID))).first() is None:
        print(f"⚠️  Saúde de entrega: usuário da gestão (id={GESTOR_USER_ID}) não existe — "
              f"alerta {tipo} NÃO registrado. Corpo: {corpo}")
        return False

    db.add(Notification(user_id=GESTOR_USER_ID, contact_wa_id=None, type=tipo,
                        ref=None, title=titulo, body=corpo))
    return True


async def avaliar(db: AsyncSession, *, agora=None) -> dict:
    """Um ciclo: mede, compara com o estado guardado e notifica SÓ na transição.

    NÃO dá commit — quem chama decide a fronteira da transação. É o que deixa o teste rodar
    isto contra uma sessão e desfazer tudo no fim.

    `agora` explícito permite testar sem mock de relógio, mesmo padrão de
    `nat_scheduler.processar_pendentes` e de `dentro_horario_comercial(quando=...)`.

    Devolve as métricas + `estado_anterior`, `estado`, `transicao` (None quando nada mudou).
    """
    m = await medir(db, agora=agora)
    anterior = await estado_atual(db)

    volume_suficiente = m["total"] >= MINIMO_ENVIOS
    quebrou = volume_suficiente and m["taxa"] >= LIMIAR_QUEBROU
    voltou = (volume_suficiente and m["taxa"] < LIMIAR_VOLTOU
              and m["falhas"] <= MAX_FALHAS_PARA_VOLTAR)

    transicao, estado = None, anterior

    if anterior == ESTADO_NORMAL and quebrou:
        if await _notificar(db, TIPO_QUEBROU, "Entrega de mensagens quebrou", _corpo(m)):
            transicao, estado = TIPO_QUEBROU, ESTADO_ALERTA
            print(f"🚨 Saúde de entrega: QUEBROU — {_corpo(m)}")

    elif anterior == ESTADO_ALERTA and voltou:
        if await _notificar(db, TIPO_VOLTOU, "Entrega de mensagens normalizada", _corpo(m)):
            transicao, estado = TIPO_VOLTOU, ESTADO_NORMAL
            print(f"✅ Saúde de entrega: NORMALIZOU — {_corpo(m)}")

    return {**m, "estado_anterior": anterior, "estado": estado, "transicao": transicao}


async def delivery_health_job():
    """Loop de 15 min. Registrado no lifespan de main.py, junto dos outros jobs.

    Dorme ANTES de trabalhar, como todos os outros jobs do main.py.

    O try/except abraça o ciclo inteiro porque este loop não pode morrer: se morrer, o sistema
    volta a não saber que está falhando — que é o estado de onde esta sprint veio.
    """
    while True:
        await asyncio.sleep(INTERVALO_SEGUNDOS)
        try:
            async with async_session() as db:
                r = await avaliar(db)
                await db.commit()
            if r["transicao"]:
                print(f"🔔 Saúde de entrega: notificação {r['transicao']} enviada para a "
                      f"gestão (id={GESTOR_USER_ID})")
        except Exception as e:
            print(f"❌ Erro no delivery_health_job: {type(e).__name__}: {e}")
