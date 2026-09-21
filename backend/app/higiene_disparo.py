"""S6-2 — quem NÃO entra num disparo. Extensão do filtro de 28/08.

Uma pergunta: `por_que_pular(wa_id, db)` devolve o motivo, ou None. Desde 21/09 só a
regra (a), a recusa, mora aqui; a (c), `nat_ativa`, continua em `exact_routes.py`.

O TETO DE 3 TEMPLATES / 7 DIAS FOI REMOVIDO EM 21/09/2026 (decisão do Álefe)
------------------------------------------------------------------------------------------
A regra (b) pulava quem tinha recebido 3 ou mais templates outbound (status <> 'failed',
contando os do agente junto) nos últimos 7 dias, em campanha e agendado; o individual já
não a aplicava. O processo comercial prevê ATÉ 9 FOLLOWS POR LEAD, e a regra bloqueava o
trabalho do time no meio da régua. Foi REMOVIDA, não configurada: sem `nat_config`, sem
override. O risco da nota de qualidade do número na Meta fica assumido pelo comercial.

O que ela media enquanto existiu (RECON_NAT_FOLLOWUPS_20260917, §1.3): entre 02/09 e
17/09, **44 pulos em 44 leads** — 43 no lote de 02/09 18h (111 selecionados, 47 enviados)
e 1 em 14/09. Linhas antigas de `disparo_skips` com `regra = 'teto'` são histórico e ficam;
nenhuma nova entra a partir do deploy. Se a Meta reduzir o limite diário de conversas
iniciadas, esse é o primeiro sinal de que o teto fazia falta.

O DEFEITO QUE ISTO FECHA (RECON_FOLLOWS_HUMANO_IA_20260901, §4.2)
------------------------------------------------------------------------------------------
8 dos 9 leads que disseram "não" na janela 24/08–01/09 continuaram recebendo — até 6 toques
depois da recusa. Michele disse "não tenho mais interesse" em 26/08, o SDR respondeu à mão
com educação exemplar no minuto seguinte, e a LISTA voltou a alcançá-la em 29/08 e 31/08,
até ela responder em caixa alta: "Já é a quarta mensagem que me mandam sobre e eu sempre
digo que nao tenho". Maria disse três vezes.

21 pessoas receberam 5 ou mais templates em 8 dias e nunca responderam uma vez. Nenhuma
recebeu a MESMA família 3×: o problema é a soma das réguas, cinco listas independentes
chegando na mesma pessoa.

E o custo já não é só de eficácia. Quatro envios da janela voltaram com
`131049 — "not delivered to maintain healthy ecosystem"`, que é a Meta protegendo o
destinatário de nós. O ativo em risco é o número, não a campanha.

A CAMPANHA NÃO LÊ A CONVERSA — e é isso, exatamente, que estas regras corrigem. O filtro de
28/08 (regra c) já perguntava "o agente está falando com essa pessoa agora?". Faltava
perguntar "essa pessoa já pediu para parar?" (e, até 21/09, "quantas vezes já batemos nela
esta semana?" — ver o registro da remoção acima).

O PADRÃO DE RECUSA FOI VALIDADO CONTRA O CORPUS INTEIRO, NÃO IMAGINADO
------------------------------------------------------------------------------------------
Rodado sobre todo o inbound do banco (6 meses): **72 mensagens casam, e as 72 são recusa de
verdade**. O que ficou de FORA foi decidido pelos falsos positivos que a medição mostrou:

  `não quero` sozinho          FORA. "Não quero perder as aulas" (seguido de "Podem enviar
                               o link?") é um lead comprando. "não quero falar por telefone"
                               e "Não quero informação por ligação | Quero pelo WhatsApp" são
                               preferência de CANAL — bloquear WhatsApp para eles é o avesso
                               do que pediram.
  `não há mais interesse`      FORA, e este é o achado. A frase está DENTRO do nosso próprio
                               template `ainda_ha_interesse` ("Na ausência de retorno
                               considerarei que não há mais interesse"). Todo lead que
                               reencaminha ou cita a nossa mensagem viraria "recusa". Custo
                               de tirar: uma recusa genuína em 6 meses ("não há interesse na
                               pós"). Custo de manter: um falso positivo por encaminhamento,
                               para sempre.
  `desisti`                    DENTRO, mas exigindo que não venha logo depois de "não" —
                               "não desisti" é o contrário de desistir.

Quem mexer neste padrão RODE A MEDIÇÃO DE NOVO antes de commitar. Falso positivo aqui não
faz barulho: some um lead real de todas as campanhas por 30 dias, e ninguém percebe.
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message
from app.telefone import variantes_wa_id

# --- (a) recusa explícita -----------------------------------------------------------------
JANELA_RECUSA = timedelta(days=30)
PADRAO_RECUSA = (
    r"n[ãa]o (tenho|tem|tinha|temos) (mais )?interesse"
    r"|sem interesse"
    r"|n[ãa]o (tenho|temos|terei) (mais )?condi[çc][õo]es"
    r"|sem condi[çc][õo]es financeiras"
    r"|n[ãa]o desejo"
    r"|n[ãa]o (irei|vou|pretendo) fazer"
    r"|(^|[^o] )desisti"
    r"|n[ãa]o quero (a |essa |esta |mais )?(p[óo]s|gradua|especializa|receber|dar continuidade)"
    r"|n[ãa]o (quero |vou )?dar continuidade"
    r"|n[ãa]o seguir com"
)

# Os motivos dizem o CAMINHO, não só o impedimento — mesma regra do MOTIVO_PULO_NAT: quem
# lê o retorno da rota precisa saber o que fazer com aquela pessoa, não só que ela ficou de
# fora.
MOTIVO_RECUSA = ("o lead pediu para parar nos últimos 30 dias — se precisar falar com ele, "
                 "responda pela tela de Conversas, onde dá para ler o que ele disse")


async def _recusou(variantes: tuple[str, ...], desde: datetime,
                   db: AsyncSession) -> str | None:
    """A recusa mais recente dentro da janela, ou None. Devolve o TEXTO, para o log."""
    r = await db.execute(
        select(Message.content)
        .where(Message.contact_wa_id.in_(variantes),
               Message.direction == "inbound",
               Message.timestamp >= desde,
               Message.content.op("~*")(PADRAO_RECUSA))
        .order_by(Message.timestamp.desc())
        .limit(1))
    return r.scalar_one_or_none()


async def por_que_pular(wa_id: str, db: AsyncSession, *,
                        agora: datetime) -> tuple[str, str] | None:
    """`(regra, motivo)` se este contato não deve receber o disparo. None se pode.

    Vale em TODOS os modos — campanha, agendado e individual. (Até 21/09 havia um
    `aplicar_teto` que desligava a regra (b) no individual; a regra foi embora e a flag com
    ela.)

    POR QUE (a) VALE TAMBÉM NO INDIVIDUAL
    --------------------------------------------------------------------------------------
    O filtro de 28/08 dispensa o individual porque "o SDR escolheu aquela pessoa e apertou
    enviar, e essa é decisão dele". Vale para o RITMO: quem olha a thread vê os toques.

    Não vale para a recusa, e a diferença é de fato, não de grau. Quem aperta enviar na tela
    de Automações está olhando uma LISTA DE LEADS DA EXACT — a recusa não está ali. Ele não
    está decidindo ignorar o "não"; ele não tem como saber que houve um. A regra (a) não
    tira decisão de ninguém: ela entrega a informação que a tela não mostra.

    E a saída continua existindo, na tela certa: quem precisa responder a alguém que recusou
    faz isso pela tela de Conversas (`/send/text`), onde o "não" está na frente dele. Foi
    exatamente o que o SDR fez com a Michele em 26/08, e aquilo estava certo — o que errou
    foi a lista voltar por cima três dias depois.

    ORDEM DAS REGRAS = ordem de importância: a recusa roda antes da `nat_ativa` (na rota)
    porque é a única que fala de um pedido explícito da pessoa. Se duas batem, o motivo que
    o SDR lê é o que mais importa que ele saiba.

    NUNCA LEVANTA. Higiene que derruba disparo é pior que disparo sem higiene: um erro aqui
    tem que deixar a mensagem sair, não segurar o lote. Falha => None (não pula) + log.
    """
    try:
        variantes = variantes_wa_id(wa_id)
        if not variantes:
            return None

        recusa = await _recusou(variantes, agora - JANELA_RECUSA, db)
        if recusa is not None:
            trecho = " ".join(recusa.split())[:80]
            return "recusa", f'{MOTIVO_RECUSA} — ele disse: "{trecho}"'

        return None
    except Exception as e:
        print(f"⚠️  Higiene do disparo falhou em {wa_id} ({type(e).__name__}: {e}). "
              "O envio segue — higiene não derruba disparo.")
        return None
