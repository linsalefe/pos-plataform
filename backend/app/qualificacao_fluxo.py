"""A máquina de etapas do agente. Só este módulo muda `etapa`.

------------------------------------------------------------------------------------------
O CONTRATO COM O LLM, DO LADO DE CÁ
------------------------------------------------------------------------------------------
`qualificacao_llm.conversar` PROPÕE `etapa_cumprida` e `acao`. Aqui a proposta é lida,
validada contra a etapa em que o lead realmente está, e só então vira escrita. Um
`acao="agendar_slot"` chegando em `aguardando_motivacao` não agenda nada: cai em ação
impossível → humano.

------------------------------------------------------------------------------------------
FLUXO
------------------------------------------------------------------------------------------
    abertura T3 --> aguardando_formacao --+
    abertura T1/T2 --------------------> aguardando_ano
                                             |
                                         aguardando_atuacao
                                             |
                                         aguardando_motivacao
                                             |
                              +--------------+--------------+
                    já tem reunião?                    não tem
                              |                             |
                         concluido                   ofertando_agenda
                      (+ lembrete)                          |
                                                     escolhendo_slot
                                                            |
                                                       concluido
                                                      (+ lembrete)

E de QUALQUER etapa: `transferido_humano`, que é terminal para o agente.

------------------------------------------------------------------------------------------
ONDE ELE CALA
------------------------------------------------------------------------------------------
`concluido`, `transferido_humano` e `encerrado` não estão em ETAPAS_QUALIFICACAO_ATIVAS.
Fora delas o agente não escuta (precedência do webhook) e não fala
(`qualificacao_pode_atuar`) — a mesma constante governa os dois lados, então "o agente fala"
e "o agente escuta" não podem divergir.
"""
import json
import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import qualificacao_llm as llm
from app import qualificacao_guard as guard
from app.models import (ETAPA_Q_AGUARDANDO_ANO, ETAPA_Q_AGUARDANDO_ATUACAO,
                        ETAPA_Q_AGUARDANDO_FORMACAO, ETAPA_Q_AGUARDANDO_MOTIVACAO,
                        ETAPA_Q_CONCLUIDO, ETAPA_Q_ESCOLHENDO_SLOT, ETAPA_Q_OFERTANDO_AGENDA,
                        ETAPA_Q_TRANSFERIDO, ETAPAS_QUALIFICACAO_ATIVAS,
                        ETAPA_Q_ENCERRADO, KIND_ENCERRAR_INATIVO, KIND_FOLLOW_20H,
                        KIND_LEMBRETE_REUNIAO,
                        KIND_RESPONDER_PENDENTE, KIND_VIGIAR_RESPOSTA,
                        ACAO_PENDENTE, Agendamento, Contact, Message, Notification,
                        NatQualificacaoState, NatScheduledAction, PASSO_AGENDADO)
from app.nat_guard import (GESTOR_USER_ID, _agora_sp, dentro_horario_comercial,
                           proximo_horario_util)
from app.nat_scheduler import (AcaoAdiada, AcaoIgnorada, agendar as nat_agendar,
                               cancelar as nat_cancelar, registrar_handler)
from app.nat_sender import enviar_nat, send_nat_message
from app.telefone import variantes_wa_id
from app.contatos import contato_existente
from app.nomes import primeiro_nome

# Quantas mensagens da conversa vão para o modelo. 10 cobre o vaivém das 4 perguntas com
# folga para uma digressão, e mantém o custo previsível.
MAX_HISTORICO = 10

# Quanto antes da reunião o lembrete sai.
ANTECEDENCIA_LEMBRETE = timedelta(minutes=30)

# De quanto em quanto tempo uma abertura barrada pelo TETO por hora volta a tentar.
#
# O teto é uma contagem MÓVEL de 1h (qualificacao_guard.contar_envios_ultima_hora), então ele
# se resolve sozinho conforme os envios antigos saem da janela — não há um instante exato para
# esperar, e mirar "a hora cheia" seria pior: concentraria de novo todo mundo no mesmo minuto.
# 10 min é o passo que espalha a fila sem fazer o lead esperar.
#
# MEDIDO em 24/08: ~7 aberturas caem juntas no pico das 09h, contra teto de 20/h. Isto é uma
# rede, não um caminho quente.
ATRASO_POR_TETO = timedelta(minutes=10)

# Silêncio do lead que encerra a qualificação. Constante nomeada porque é número de produto,
# não de engenharia: mudar a régua é mudar esta linha.
#
# 72h e não 24h: o lead é abordado logo depois de se candidatar, e "não respondeu no mesmo
# dia" é rotina — muita gente aplica de madrugada e volta no fim de semana. Encerrar cedo
# demais joga fora quem só demorou a ver o WhatsApp.
INATIVIDADE_ENCERRA = timedelta(hours=72)

# S6-4 (Sprint D) — quando o agente volta a falar com quem calou. Ver KIND_FOLLOW_20H para a
# medição que fixou o 20. Fica ABAIXO do encerramento de 72h de propósito: o follow é a
# última tentativa DENTRO da janela em que a conversa ainda está viva, não um adeus.
FOLLOW_APOS = timedelta(hours=20)

# Quanto tempo para trás o handler olha atrás de um toque humano. É o MESMO 20h, e não um
# número novo: a pergunta é "alguém falou com essa pessoa desde que o agente perguntou?".
FOLLOW_JANELA_HUMANO = FOLLOW_APOS

# ==========================================================================================
# O VIGIA — P3-A, 26/08/2026
# ==========================================================================================
# 10 MINUTOS. Um turno saudável leva 3–5s (medido nos prints de 25/08: 17:27:47→17:27:51,
# 17:28:26→17:28:29, e 5s no turno com agendamento). 10 min não gera falso positivo por
# lentidão e ainda cabe com folga dentro da janela de 24h para alguém agir.
PRAZO_VIGIA = timedelta(minutes=10)

# ------------------------------------------------------------------------------------------
# O VIGIA E A FALA ADIADA PELO TETO — por que a régua é a ESPERA e não o `run_at`
# ------------------------------------------------------------------------------------------
# Quando o teto adia uma fala (P0-B), existe pendência legítima e o agente ainda não falou.
# Duas medições decidiram o desenho:
#
#   1. `ATRASO_POR_TETO` é 10 min e o vigia vence em inbound+10 min. OS DOIS RELÓGIOS
#      COINCIDEM. Sem supressão, todo adiamento por teto geraria um "AGENTE MUDO" no minuto
#      exato em que a resposta ia sair — e alarme que erra é alarme que ninguém lê, que é
#      precisamente o diagnóstico da auditoria sobre os `window_*`.
#
#   2. `AcaoAdiada` NÃO consome tentativa (está na docstring dela), e `responder_pendente`
#      readia sempre para +10 min. Logo o `run_at` da pendência está SEMPRE a menos de 10
#      min no futuro, para sempre. Uma supressão medida no `run_at` — "não dispara se a
#      pendência está agendada para menos de 30 min" — nunca deixaria o vigia disparar.
#      Seria supressão permanente, justo no caso em que o lead mais precisa do alarme.
#
# Por isso a régua é a ESPERA DO LEAD, que só cresce: suprime enquanto houver pendência E a
# espera for menor que 30 minutos; a partir daí NOTIFICA, mesmo com pendência viva. 30 min
# são três readiamentos seguidos — três falhas do "esperar resolve" —, e ainda sobram 23h30
# de janela para agir.
ESPERA_MAXIMA_COM_PENDENCIA = timedelta(minutes=30)

# Tipo próprio na `notifications`. NÃO reusa `agente_transferiu`: transferência é desfecho
# tratado, agente mudo é falha de sistema, e misturar os dois na mesma consulta apagaria a
# distinção que este item existe para criar. Sem migração — `notifications.type` não tem
# CHECK.
TIPO_NOTIF_MUDO = "agente_mudo"

# ------------------------------------------------------------------------------------------
# OS DOIS MOTIVOS DE ENCERRAMENTO — quem calou? (S4-2, 27/08/2026)
# ------------------------------------------------------------------------------------------
# `encerrado_motivo` existe para preservar POR QUE o lead saiu (docstring de
# NatQualificacaoState). Até aqui ela só sabia dizer uma coisa, `inatividade`, e a dizia
# sempre — inclusive quando a inatividade era NOSSA.
#
# Medido em 26/08: a Erica e a Amanda Pavão escreveram, foram engolidas por um bug da janela
# de 24 h, e o `encerrar_inativo` de 29/08 as gravaria como "o lead calou". Elas não calaram.
# Um rótulo errado aqui contamina toda régua de follow-up que vier a ler `encerrado`: quem
# nós ignoramos é exatamente quem MAIS merece uma segunda abordagem, e ia para o mesmo balde
# de quem perdeu o interesse.
#
# A distinção é a mesma pergunta da varredura (`agente_parado.encalhada`), e por isso é ELA
# que responde — não uma segunda cópia do critério que divergiria no primeiro ajuste.
#
# `encerrado_motivo` é TEXT sem CHECK (verificado no banco em 27/08) — motivo novo não pede
# migração.
MOTIVO_INATIVIDADE = "inatividade"          # o LEAD calou: falamos por último e ele sumiu
MOTIVO_SEM_RESPOSTA_AGENTE = "sem_resposta_do_agente"   # NÓS calamos: ele falou por último

TIPO_NOTIF_AGENTE = "agente_transferiu"

# Mensagem determinística do fallback. NÃO passa pelo LLM: é justamente o caminho de quando
# o LLM não é confiável. Texto único, sem variação — a pessoa precisa entender que alguém
# vai assumir, não receber uma desculpa criativa.
TEXTO_FALLBACK = ("Deixa eu te conectar com uma pessoa da nossa equipe para seguir daqui, "
                  "tá? 🙂 Em breve alguém fala com você por aqui.")

# A missão de cada etapa. É o único lugar onde o roteiro vira texto para o modelo — mudar o
# roteiro é mudar estas linhas, não caçar prompt espalhado pelo módulo.
# A missão de cada etapa diz DUAS coisas, e a segunda é tão importante quanto a primeira:
# o que extrair, e QUAL PERGUNTA FAZER EM SEGUIDA quando a etapa se cumpre.
#
# Sem a segunda, o teste manual de 24/08 mostrou o que acontece: com `etapa_cumprida=true`
# o modelo inventava um fecho ("quer que eu te envie as próximas etapas da inscrição?"),
# `_avancar` mandava essa mensagem E movia a etapa, e o lead respondia uma pergunta que a
# etapa seguinte ia interpretar como outra coisa. A pergunta seguinte não é criatividade do
# modelo — é o roteiro.
MISSOES = {
    ETAPA_Q_AGUARDANDO_FORMACAO: (
        'Descubra QUAL É a formação (graduação) da pessoa. '
        'dado_extraido = {"formacao": "<o que ela disse>"}. '
        'SE ELA RESPONDER: valide em uma frase e TERMINE perguntando em que ano ela '
        'concluiu essa graduação.'),
    # ------------------------------------------------------------------------------------
    # S6-5 — O ANO DE CONCLUSÃO VIROU OPCIONAL (01/09/2026)
    # ------------------------------------------------------------------------------------
    # É O MAIOR DEGRAU DO FUNIL, e sozinho ele derruba mais gente que todos os outros
    # passos somados. Medido na janela 24/08-01/09 (RECON_FOLLOWS_HUMANO_IA_20260901, §4.5):
    #
    #     respondeu alguma vez   77
    #     deu a formação         72        -5
    #     deu o ANO              45       -27   (-37,5%)   <- aqui
    #     deu a atuação          40        -5
    #     deu a motivação        35        -5
    #
    # Perder alguém no ano de conclusão não custa o ano: custa a atuação, a motivação e o
    # agendamento que vinham depois. O dado mais barato do roteiro estava cobrando o preço
    # mais caro.
    #
    # POR QUE ELE TRAVA. "Em que ano você concluiu?" é uma pergunta de MEMÓRIA, e é a única
    # do roteiro que a pessoa pode não saber responder. Formação, atuação e motivação ela
    # sabe de cor; o ano de uma graduação de 2004 exige parar e contar. Quem não lembra na
    # hora não escreve "não lembro" — some.
    #
    # A SAÍDA É EXPLÍCITA, E NÃO UMA TOLERÂNCIA CALADA. "não lembro" passa a ser resposta
    # VÁLIDA (`etapa_cumprida`), e o que ela disse é gravado literalmente: `ano_conclusao =
    # "não lembra"` diz uma coisa, e NULL diz outra (que ninguém perguntou). A consultora lê
    # os dois no contexto — ver `_fatos`.
    #
    # E O AGENTE NÃO INSISTE. A segunda cobrança é o que transforma uma pergunta difícil em
    # motivo para sair da conversa.
    #
    # ONDE A SAÍDA APARECE, e onde NÃO aparece: quem faz a primeira pergunta é o template de
    # abertura (aprovado na Meta, imutável daqui) ou o fecho da missão de `aguardando_
    # formacao`, e os dois seguem perguntando o ano direto. A oferta entra quando o agente
    # VOLTA a falar nesta etapa — que é exatamente o momento em que a pessoa travou. Levar a
    # oferta para a primeira pergunta é decisão de produto (mais conversa concluída, menos
    # ano preenchido) e está isolada numa linha da missão de `aguardando_formacao`.
    ETAPA_Q_AGUARDANDO_ANO: (
        'Descubra em QUE ANO ela concluiu a graduação. '
        'dado_extraido = {"ano_conclusao": "<o que ela disse, literalmente>"}. '
        'ESTA PERGUNTA É OPCIONAL e você NUNCA insiste nela. '
        'CONTAM COMO RESPOSTA, e todas cumprem a etapa: um ano; "ainda estou cursando"; '
        '"não lembro", "não sei", "faz muito tempo", "preciso ver o diploma" ou qualquer '
        'jeito de dizer que ela não tem o ano na cabeça; e também uma aproximação '
        '("por volta de 2010"). '
        'SE ELA RESPONDER QUALQUER UMA DESSAS: valide em uma frase, sem cobrar precisão e '
        'sem pedir para ela conferir depois, e TERMINE perguntando como e onde ela atua '
        'profissionalmente hoje. '
        'SE ELA FALAR DE OUTRA COISA (perguntou o preço, desconversou, mudou de assunto): '
        'responda o que ela trouxe e, ao retomar, ofereça a saída com estas palavras ou '
        'equivalentes — "se não lembrar de cabeça, sem problema, seguimos". '
        'NUNCA peça o ano duas vezes na mesma conversa.'),
    ETAPA_Q_AGUARDANDO_ATUACAO: (
        'Descubra COMO E ONDE ela atua profissionalmente hoje. Se estiver fora da área ou '
        'sem atuar, isso também é resposta. dado_extraido = {"atuacao": "<o que ela disse>"}. '
        'SE ELA RESPONDER: valide em uma frase e TERMINE perguntando, de forma aberta, o que '
        'despertou o interesse dela nesta pós-graduação.'),
    ETAPA_Q_AGUARDANDO_MOTIVACAO: (
        'Pergunta ABERTA: o que despertou o interesse dela nesta pós-graduação. '
        'dado_extraido = {"motivacao": "<o que ela disse>"}. '
        'SE ELA RESPONDER: sua mensagem VALIDA o que ela de fato disse — comente o conteúdo '
        'real, com as palavras dela; nada de "que interessante". E NÃO FAÇA NENHUMA '
        'PERGUNTA: esta é a última etapa de qualificação, e quem fala em seguida é o '
        'sistema, com os horários. Termine dizendo que vai ver os horários disponíveis.'),
    # ------------------------------------------------------------------------------------
    # S5-4 — A OFERTA PAROU DE PROMETER O QUE A GRADE NÃO TEM (28/08/2026)
    # ------------------------------------------------------------------------------------
    # Três defeitos medidos nas 4 ofertas reais de 27-28/08, todos aqui:
    #
    # (a) A ESCAPATÓRIA PROMETIA A NOITE. "que dia e PERÍODO prefere" é convite aberto, e o
    #     modelo o preenchia com "manhã, tarde ou noite" — enquanto `consultoras.json` é
    #     09:00-18:30, seg-sex. 3 das 4 ofertas bateram nisso (2 pediram noite, 1 pediu
    #     sábado), e nas 3 o agente não tinha para onde procurar: repetiu a mesma lista.
    #
    # (b) O MODELO INVENTAVA DATA. Caso Marcio, 27/08: "manhã de sábado 27/08 às 12:00" —
    #     27/08 era quinta, 12:00 não é manhã, e aquele horário nunca foi ofertado. Três
    #     erros numa frase. O guard de `_agendar` protege o `slot_id` da AÇÃO; o texto da
    #     MENSAGEM não tem guard nenhum, e é ele que o lead lê. A regra explícita
    #     ("nem como exemplo") é a única defesa que existe nesse caminho.
    #
    # (c) NÃO HAVIA SAÍDA para quem só pode fora da grade. Agora há, e é a que já existia
    #     no contrato: `transferir_humano`. É a ÚNICA etapa em que a Nat oferece
    #     transferência por iniciativa própria — o PROMPT_BASE proíbe isso em geral, e a
    #     ressalva "salvo instrução em contrário na missão" está lá para este caso.
    #
    #     EFEITO COLATERAL CONHECIDO, dito aqui para não virar susto: a transferência passa
    #     por `_fallback`, que loga `🛟`. O RECON usa `grep -cE "🛟|LLM indisponível"` como
    #     medida de FALHA DE CONTRATO — e a partir daqui um `🛟` pode ser um desfecho
    #     correto. Quem separa os dois é `transferido_motivo`, não o emoji.
    ETAPA_Q_OFERTANDO_AGENDA: (
        'Ofereça NO MÁXIMO 5 horários, escolhidos entre os do contexto e espalhados entre '
        'os dias e entre manhã e tarde. NÃO liste todos. Escreva cada horário como data e '
        'hora, e NUNCA o id entre parênteses: ele é instrução interna e não pode aparecer '
        'na mensagem. Depois dos 5, TERMINE convidando: '
        'se nenhum servir, que ela diga que dia e período prefere — manhã ou tarde, de '
        'segunda a sexta — que você procura. '
        'Use SOMENTE os horários listados, e NUNCA escreva data, hora ou dia da semana que '
        'não esteja no contexto, nem como exemplo. '
        'Quando ela escolher um deles, use acao="agendar_slot" e dado_extraido = '
        '{"slot_id": "<o id exato do horário escolhido, copiado do contexto>"}. '
        'A agenda é de SEGUNDA A SEXTA, das 09h às 18h30: se ela JÁ TIVER PEDIDO noite ou '
        'fim de semana, não ofereça horário nenhum e não faça pergunta — diga que para '
        'esse horário quem combina é a consultora, avise que vai passar o contato para ela '
        'e use acao="transferir_humano". '
        'Em qualquer outro caso, a ÚLTIMA FRASE da sua mensagem é o convite descrito '
        'acima: se nenhum dos 5 servir, que ela diga o dia e o período que prefere.'),
    ETAPA_Q_ESCOLHENDO_SLOT: (
        'A pessoa está confirmando qual horário quer. Use SOMENTE os horários do contexto. '
        'Ao ter certeza de qual é, use acao="agendar_slot" e '
        'dado_extraido = {"slot_id": "<o id exato copiado do contexto>"}. '
        'NUNCA escreva data, hora ou dia da semana que não esteja no contexto, e não '
        'deduza o dia da semana de uma data: se não está escrito na lista, você não sabe '
        'qual é. '
        'A agenda é de SEGUNDA A SEXTA, das 09h às 18h30: se ela pedir noite, fim de '
        'semana ou um dia/horário fora da lista, não repita a lista, não invente e não '
        'faça pergunta — diga que para esse horário quem combina é a consultora, avise que '
        'vai passar o contato para ela e use acao="transferir_humano".'),
}

# ==========================================================================================
# S6-4b — O QUE O FOLLOW DE 20h DIZ, POR ETAPA
# ==========================================================================================
# Vai inteiro no `{{2}}` do template `follow_up`, que é um slot de TEXTO LIVRE no meio da
# mensagem aprovada:
#
#     "Olá, {{1}}! Tudo bem? 😊
#      Aqui é da equipe do CENAT. {{2}}
#      Ficamos à disposição para tirar suas dúvidas! 💬"
#
# POR QUE ESTE TEMPLATE, E NÃO OS OUTROS DOIS APROVADOS. `nat_reativacao_09h` abre com "Bom
# dia" (o follow também dispara à tarde) e afirma "Conforme combinado", que não foi
# combinado; `follow_urgencia` diz "Estamos tentando contato há alguns dias", falso em 20h.
# Um template que afirma o que não aconteceu é o defeito que o S6-3 acabou de consertar —
# não faz sentido reintroduzi-lo pela porta do lado.
#
# ⚠️ O CONTRATO DE PARÂMETROS DO FOLLOW É DIFERENTE DO RESTO DO AGENTE.
#
#     nat_abertura_*, nat_lembrete_reuniao   {{1}} = nome   {{2}} = CURSO
#     follow (este)                          {{1}} = nome   {{2}} = A PERGUNTA PENDENTE
#
# Quem configurar `nat_config.follow_template` com um template feito para receber o CURSO no
# `{{2}}` vai mandar a frase no slot errado — a mesma classe de erro do `tentativa_contato`.
# O template do follow tem que ter o `{{2}}` como texto livre. Ver o §5.3 do
# RECON_FOLLOWS_HUMANO_IA_20260901 e o SPRINT6.
#
# A FRASE RETOMA A PERGUNTA QUE FICOU, e é por isso que ela é por ETAPA e não uma só: o lead
# que sumiu no ano de conclusão e o que sumiu escolhendo horário pararam em lugares
# diferentes, e um "ainda tem interesse?" genérico faria os dois recomeçarem do zero.
#
# `aguardando_ano` carrega a saída do S6-5 dentro da própria retomada — é a etapa onde 37,5%
# das conversas morriam, e a razão é que a pergunta exige memória.
RETOMADA_FOLLOW = {
    ETAPA_Q_AGUARDANDO_FORMACAO: (
        "Ficou faltando só uma informação para eu separar os horários com a nossa "
        "consultoria: qual é a sua formação?"),
    ETAPA_Q_AGUARDANDO_ANO: (
        "Ficou faltando só o ano em que você concluiu a graduação — e se não lembrar de "
        "cabeça, sem problema, seguimos."),
    ETAPA_Q_AGUARDANDO_ATUACAO: (
        "Ficou faltando só uma informação para eu separar os horários: como e onde você "
        "atua profissionalmente hoje?"),
    ETAPA_Q_AGUARDANDO_MOTIVACAO: (
        "Ficou faltando só uma coisa: o que despertou o seu interesse nesta pós-graduação?"),
    ETAPA_Q_OFERTANDO_AGENDA: (
        "Separei horários com a nossa consultoria para conversar com você — me diz qual "
        "fica melhor e eu já reservo."),
    ETAPA_Q_ESCOLHENDO_SLOT: (
        "Ficou faltando só confirmar o horário da conversa com a nossa consultoria — qual "
        "deles fica melhor para você?"),
}


# Para onde cada etapa vai quando cumprida. `aguardando_motivacao` não está aqui: o destino
# dela depende de o lead já ter reunião, e isso é decidido em código.
PROXIMA = {
    ETAPA_Q_AGUARDANDO_FORMACAO: ETAPA_Q_AGUARDANDO_ANO,
    ETAPA_Q_AGUARDANDO_ANO: ETAPA_Q_AGUARDANDO_ATUACAO,
    ETAPA_Q_AGUARDANDO_ATUACAO: ETAPA_Q_AGUARDANDO_MOTIVACAO,
}

# Onde cada dado do LLM é gravado. Chave fora daqui vai para `dados_extras` (JSONB), que
# existe para não exigir ALTER a cada pergunta nova do roteiro.
CAMPOS = {"formacao", "ano_conclusao", "atuacao", "motivacao"}


# ==========================================================================================
# LEITURA
# ==========================================================================================

def _mais_relevante(linhas, variantes: tuple[str, ...], de):
    """Escolhe UMA linha quando o mesmo humano tem duas. Determinístico.

    A ordem de `variantes_wa_id` manda (a forma de 13 dígitos primeiro) e o `id` desempata.
    Sem isto, `scalar_one_or_none()` levantaria `MultipleResultsFound` no dia em que as duas
    threads existirem — e elas já existem para 340 pessoas.
    """
    if not linhas:
        return None
    ordem = {v: i for i, v in enumerate(variantes)}
    return sorted(linhas, key=lambda o: (ordem.get(de(o), 99), o.id))[0]


async def _contato_de(wa_id: str, db: AsyncSession) -> Contact | None:
    """O contato, achando também a thread gêmea sem o 9º dígito. Ver `app/telefone.py`."""
    vs = variantes_wa_id(wa_id)
    if not vs:
        return None
    res = await db.execute(select(Contact).where(Contact.wa_id.in_(vs)))
    return _mais_relevante(list(res.scalars()), vs, lambda c: c.wa_id)


async def _identidade_do_lead(lead_id: int | None, db: AsyncSession) -> tuple[str, str | None]:
    """`(nome, sdr_name)` do lead, de onde houver. `("", None)` quando não há nada.

    Duas fontes na ordem em que ficam prontas: `exact_leads` é a boa (traz o SDR), mas o lead
    da LP pode ainda não ter sido sincronizado — MEDIDO, o sync leva até 10 min e a abertura
    dispara em 5. `agendamentos` tem o nome desde o instante do formulário, e é o que salva o
    caso comum de quem acabou de se candidatar.
    """
    if not lead_id:
        return "", None
    from app.models import ExactLead
    lead = (await db.execute(
        select(ExactLead).where(ExactLead.exact_id == lead_id))).scalar_one_or_none()
    if lead is not None:
        return (lead.name or ""), lead.sdr_name
    nome = (await db.execute(
        select(Agendamento.nome).where(Agendamento.lead_id == lead_id)
        .order_by(Agendamento.id.desc()).limit(1))).scalar_one_or_none()
    return (nome or ""), None


async def _contato_ou_criar(wa_id: str, *, lead_id: int | None,
                            db: AsyncSession) -> Contact | None:
    """O `Contact` para quem a abertura vai sair — CRIANDO-O se ele ainda não existe.

    ------------------------------------------------------------------------------------
    POR QUE CRIAR, E POR QUE ISTO ERA O BUG DE 25/08
    ------------------------------------------------------------------------------------
    `contacts` só nascia de dois jeitos: mensagem inbound do lead, ou efeito colateral do
    envio da BOAS-VINDAS (`send_welcome_to_new_lead` cria o Contact junto com a Message do
    template). O passo 4.5 cede a abertura ao agente e sai ANTES disso, e nada passou a criar
    o contato no lugar.

    Quem se candidata pela landing page e nunca mandou mensagem simplesmente não existe em
    `contacts`. MEDIDO nos 45 leads de 25/08: 33 sem linha, 11 com. Três de cada quatro leads
    não podiam receber abertura nenhuma — com a fila cheia, o agendador drenando e o agente
    ligado. O agente herdou a dependência da boas-vindas sem herdar quem a satisfazia.

    ------------------------------------------------------------------------------------
    POR QUE A BUSCA AQUI É ESTRITA, E NÃO TOLERANTE AO 9º DÍGITO
    ------------------------------------------------------------------------------------
    Este contato existe para UMA coisa: ser encontrado por `nat_sender`, que faz
    `Contact.wa_id == contact_wa_id`, igualdade crua. Um porteiro tolerante aqui não ajuda o
    envio — ele só decide se a função segue adiante — e em 25/08 fez pior que não ajudar:

        wa_id do lead   5582998307979  (Ronaldo Cesar, formulário da LP)
        variante de 12  558298307979   -> já existia em contacts como **Pablo Valente**

    A variante sem o 9º dígito do número de um é o número de OUTRA PESSOA (`app/telefone.py`
    documenta por que a tolerância é ambígua justamente para local de 8 dígitos começando em
    9). O porteiro abriu, o estado nasceu na linha de um estranho, e só não houve envio para
    a pessoa errada porque o sender é estrito e não achou os 13 dígitos. A inconsistência
    entre os dois foi o que impediu o estrago.

    Então a regra passa a ser UMA: o contato da abertura é o da grafia para a qual vamos
    mandar a mensagem. É exatamente o que a boas-vindas sempre fez
    (`select(Contact).where(Contact.wa_id == phone)` e cria se não achar) — o comportamento
    que o agente deveria ter herdado.

    A tolerância continua onde ela é certa e não pode escrever nada: `estado_de` (o mesmo
    humano não pode ganhar dois estados) e o histórico da conversa.

    Devolve None só se não houver canal — sem canal o envio não sairia de qualquer forma, e
    um Contact órfão sem `channel_id` seria lixo.
    """
    # CANONIZAÇÃO (b): procura nas DUAS grafias. A abertura nasce com o telefone do lead
    # (13 dígitos, via `qualificacao_gatilho.wa_id_de`) e o inbound dessa pessoa chega com
    # 12 — era exatamente aqui que a segunda thread nascia. Ver `app/contatos.py`.
    achado = await contato_existente(wa_id, db)
    if achado is not None:
        # Contato que existe SEM nome recebe o nome do lead — exatamente o que a boas-vindas
        # faz no passo 7 (`if not contact.name: contact.name = name`). Sem isto, um contato
        # criado por outro caminho (disparo em massa, inbound de perfil sem nome) mantém o
        # nome vazio para sempre, e o `{{1}}` vazio faz a Meta recusar a abertura inteira.
        if not (achado.name or "").strip():
            nome_do_lead, _ = await _identidade_do_lead(lead_id, db)
            if nome_do_lead:
                achado.name = nome_do_lead
                print(f"👤 Agente: nome de {wa_id} preenchido do lead ({nome_do_lead})")
        return achado

    from app.models import AutoWelcomeConfig
    from app.sdr_mapping import resolve_sdr_user_id

    # Mesmo canal que a boas-vindas usa, pela mesma leitura que `nat_sender._resolver_canal`
    # já faz — uma fonte de verdade para a credencial do WABA, não duas.
    cfg = (await db.execute(
        select(AutoWelcomeConfig).where(AutoWelcomeConfig.id == 1))).scalar_one_or_none()
    channel_id = cfg.channel_id if cfg else None
    if channel_id is None:
        return None

    nome, sdr_name = await _identidade_do_lead(lead_id, db)
    contato = Contact(
        wa_id=wa_id,
        name=nome or None,
        channel_id=channel_id,
        # ai_active=False, e aqui a boas-vindas NÃO é o modelo a seguir. Lá o True entrega a
        # conversa ao `ai_engine`; aqui quem conduz é o agente, e marcar o lead como "a IA
        # genérica responde" seria pedir dois robôs na mesma thread no dia em que aquele
        # trecho do webhook (hoje comentado) voltar.
        ai_active=False,
        lead_status="novo",
        assigned_to=resolve_sdr_user_id(sdr_name),
    )
    db.add(contato)
    await db.flush()
    print(f"👤 Agente: contato {wa_id} criado para a abertura "
          f"({nome or 'sem nome'}, canal {channel_id})")
    return contato


async def estado_de(contact_wa_id: str, db: AsyncSession) -> NatQualificacaoState | None:
    """O estado do agente para este humano — nas DUAS grafias do telefone dele.

    Era `== contact_wa_id`. Com igualdade, o estado nascido da chave montada a partir do
    telefone do lead (13 dígitos, via `qualificacao_gatilho.wa_id_de`) nunca era encontrado
    pelo inbound, que chega com 12 para todo DDD fora de 11–28 — 59% das threads do Hub.
    O agente calava sem erro nenhum. Ver `app/telefone.py`.
    """
    vs = variantes_wa_id(contact_wa_id)
    if not vs:
        return None
    res = await db.execute(select(NatQualificacaoState).where(
        NatQualificacaoState.contact_wa_id.in_(vs)))
    return _mais_relevante(list(res.scalars()), vs, lambda e: e.contact_wa_id)


async def agente_e_dono(contact_wa_id: str, db: AsyncSession) -> bool:
    """O agente é o dono do inbound deste contato? É a PRECEDÊNCIA do webhook.

    Uma pergunta, um lugar. `main.py` chama isto e, se for True, não roda o
    `processar_clique`/`processar_texto` do fluxo de botões para esta mensagem.
    """
    estado = await estado_de(contact_wa_id, db)
    return estado is not None and estado.etapa in ETAPAS_QUALIFICACAO_ATIVAS


def _ja_processado(estado: NatQualificacaoState, wa_message_id: str) -> bool:
    """Trava de reentrega: mesmo wa_message_id que o último processado (padrão nat_flow)."""
    return bool(wa_message_id) and estado.ultimo_wa_message_id == wa_message_id


async def _historico(contact_wa_id: str, db: AsyncSession) -> list:
    """As últimas mensagens da conversa, em ordem cronológica, no formato do chat.

    Template outbound vira um marcador: o corpo renderizado já está em `content`, mas
    reapresentá-lo cru faria o modelo repetir a saudação. Mídia idem — o modelo não a vê.
    """
    # `in_` e não `==`: as duas grafias do telefone são a MESMA conversa, e ler só uma
    # delas daria ao modelo metade do diálogo — inclusive sem o template que ele mesmo
    # mandou, que sai para a grafia de 13 dígitos.
    res = await db.execute(
        select(Message.direction, Message.content, Message.message_type)
        .where(Message.contact_wa_id.in_(variantes_wa_id(contact_wa_id) or ("",)))
        .order_by(Message.timestamp.desc()).limit(MAX_HISTORICO))
    linhas = list(res.all())[::-1]
    saida = []
    for direcao, conteudo, tipo in linhas:
        texto = (conteudo or "").strip()
        if not texto:
            continue
        if texto.startswith("media:"):
            texto = "[a pessoa enviou um arquivo]"
        saida.append({"role": "assistant" if direcao == "outbound" else "user",
                      "content": texto})
    return saida


async def _reuniao(estado: NatQualificacaoState, db: AsyncSession):
    """O agendamento CONFIRMADO deste lead, ou None. Nunca inventa.

    Procura pelo `agendamento_id` quando o agente mesmo marcou; senão pelo `lead_id`, que é
    o caso do lead que agendou sozinho no obrigado.html.
    """
    if estado.agendamento_id:
        res = await db.execute(select(Agendamento).where(
            Agendamento.id == estado.agendamento_id))
        achado = res.scalar_one_or_none()
        if achado is not None:
            return achado
    if not estado.exact_lead_id:
        return None
    res = await db.execute(
        select(Agendamento)
        .where(Agendamento.lead_id == estado.exact_lead_id,
               Agendamento.passo == PASSO_AGENDADO)
        .order_by(Agendamento.id.desc()).limit(1))
    return res.scalar_one_or_none()


async def _curso(estado: NatQualificacaoState, db: AsyncSession) -> str:
    """Nome legível do curso. DUAS fontes, pelo mesmo motivo de `_nome`. (S3-3, 27/08/2026)

    `exact_leads` é a fonte boa, e era a única. O problema é QUANDO ela fica pronta: o lead
    da LP nasce na Exact e só entra em `exact_leads` no sync seguinte, enquanto a abertura
    dispara em 5 minutos. MEDIDO no RECON de 27/08 — a Sônia (`5566997112651`):

        abertura enviada     26/08 14:55 UTC
        exact_leads.synced_at 27/08 00:19 UTC     -> 9h de atraso

    E o que saiu no WhatsApp dela foi, literalmente:

        "Vi que você aplicou para a nossa Pós-Graduação em . Antes de te mostrar..."

    **2 de 2 leads da LP do período (100%)** receberam a abertura com o buraco. Mais duas
    aberturas foram RECUSADAS por causa do mesmo campo, com o guard de parâmetro em branco
    do `nat_sender` — `template ... com parâmetro(s) [2] em branco`, o `#131008` local.

    A segunda fonte é `agendamentos.sub_source`, que tem o dado **desde o instante do
    formulário** — a mesma tabela e a mesma ordem (`id DESC`) que `_identidade_do_lead` já
    usa para salvar o NOME no mesmo cenário. Não é fonte nova no módulo: é a fonte que já
    estava resolvendo metade do problema.

    ------------------------------------------------------------------------------------
    O QUE ESTE FIX **NÃO** RESOLVE — dito aqui para não parecer descuido
    ------------------------------------------------------------------------------------
    Com as duas fontes vazias, ainda se devolve `""`, e `""` tem dois destinos diferentes
    dependendo da janela de 24h:

        janela FECHADA -> `nat_sender` confere `vazios` e RECUSA o envio inteiro. Correto.
        janela ABERTA  -> vai como texto livre, e o buraco chega ao lead. Errado.

    A assimetria mora em `nat_sender.send_nat_message` (a checagem de parâmetro em branco só
    existe no ramo do template), não aqui, e consertá-la mexe no ÚNICO ponto por onde todo
    envio da NAT passa — fora do escopo deste item, e de risco diferente. Fica registrado.
    """
    from app.course_names import resolve_course_name
    sub = await _sub_source_do_lead(estado, db)
    return await resolve_course_name(sub, db) if sub else ""


async def _sub_source_do_lead(estado: NatQualificacaoState, db: AsyncSession) -> str:
    """O `subSource` CRU do lead — a origem dele, antes de virar nome legível.

    Extraído de `_curso` em 28/08/2026 (S5-1) sem mudar uma vírgula da consulta: as duas
    fontes e a ordem entre elas são as mesmas, pela mesma razão descrita ali. O que mudou é
    que agora existem DOIS consumidores do mesmo dado, e o segundo precisa do valor cru:

        `_curso`                -> resolve_course_name(sub)  -> "Pós-Graduação em TEA"
        `_origem_do_agendamento`-> allowlist de origens.py   -> "Pos TEA V3"

    Ter uma função só é o que impede os dois de divergirem no dia em que a ordem das fontes
    mudar de novo — e foi exatamente a divergência entre "o curso que a abertura fala" e "o
    curso que o CRM registra" que o S5-1 veio consertar.
    """
    from app.models import ExactLead
    if not estado.exact_lead_id:
        return ""
    res = await db.execute(select(ExactLead.sub_source).where(
        ExactLead.exact_id == estado.exact_lead_id))
    sub = res.scalar_one_or_none()
    if not sub:
        res = await db.execute(
            select(Agendamento.sub_source)
            .where(Agendamento.lead_id == estado.exact_lead_id)
            .order_by(Agendamento.id.desc()).limit(1))
        sub = res.scalar_one_or_none()
    return sub or ""


async def _origem_do_agendamento(estado: NatQualificacaoState, db: AsyncSession) -> str | None:
    """A `origem` a passar para `agendamento.agendar` — ou None, que significa "use o padrão".

    ------------------------------------------------------------------------------------
    S5-1 — A REUNIÃO DO AGENTE ENTRAVA COM O CURSO ERRADO (28/08/2026)
    ------------------------------------------------------------------------------------
    `_agendar` chamava `fluxo.agendar(..., origem=None)`, e `origens.resolver(None)` devolve
    `AGENDAMENTO_SUBSOURCE_PADRAO` — que em produção é `PosMulheridades`. O padrão existe
    para a LP ANTIGA, que ainda não manda o campo (está na docstring de `origens.resolver`);
    o agente herdou-o sem ser o caso de uso dele.

    MEDIDO em 28/08: **4 de 4** agendamentos que o agente já criou em toda a base saíram
    `PosMulheridades`, incluindo o da Kaylla (`agendamentos` id 251), que aplicou para TEA,
    conversou sobre TEA e teve a abertura falando de TEA — porque a abertura lê o sub_source
    certo e o agendamento não lia nada.

    NÃO É ALLOWLIST NOVA: é a MESMA de `origens.permitidas()`, conferida aqui antes da
    chamada em vez de dentro dela. A diferença é o que acontece no miss:

        `origens.resolver(fora_da_lista)` -> levanta OrigemInvalida -> agendamento MORRE
        esta função                       -> devolve None + LOG     -> agendamento SEGUE

    FAIL-CLOSED SOBRE O DADO, NÃO SOBRE A REUNIÃO. Um sub_source fora da allowlist é erro de
    cadastro (curso novo que ninguém acrescentou ao `.env`), e recusar a reunião por causa
    dele trocaria um relatório torto por um lead perdido — o pior dos dois. O que não pode
    acontecer em silêncio é a troca: por isso o log nomeia o valor recusado.

    A comparação é case-insensitive e o valor devolvido é o da allowlist, não o do banco —
    a mesma regra de `origens.resolver`, e pela mesma razão: `posmulheridades` criaria um
    SEGUNDO cadastro na Exact com o mesmo nome em caixa diferente.
    """
    from app.agendamento import origens

    sub = (await _sub_source_do_lead(estado, db)).strip()
    if not sub:
        print(f"⚠️  Agente: lead {estado.exact_lead_id} sem sub_source — agendamento vai "
              f"com a origem padrão ({origens.padrao_configurado()!r})")
        return None
    for permitida in origens.permitidas():
        if permitida.lower() == sub.lower():
            return permitida
    print(f"⚠️  Agente: sub_source {sub!r} (lead {estado.exact_lead_id}) NÃO está em "
          f"AGENDAMENTO_SUBSOURCES — agendamento vai com a origem padrão "
          f"({origens.padrao_configurado()!r}). Confira a grafia contra GET /Sources.")
    return None


async def _nome(estado: NatQualificacaoState, db: AsyncSession) -> str:
    """Primeiro nome do lead. DUAS fontes — o CADASTRO primeiro. (ordem invertida em S3-4)

    `contacts.name` nasce do perfil do WhatsApp e está VAZIO em 4 490 linhas do Hub — quem
    nunca mandou mensagem e quem tem o perfil sem nome público. Ele já foi a única fonte, e
    um nome vazio aqui vira `{{1}}` vazio no template, que a Meta recusa inteiro:

        (#131008) Required parameter is missing
        details: 'Parameter of type text is missing text value'

    Não é degradação elegante: a mensagem simplesmente não sai. Em 25/08 derrubou 3 das 18
    aberturas do backfill (Karen, Marlen, Beatriz) — e as três tinham nome em `exact_leads` o
    tempo todo. A Beatriz é a prova do mecanismo: o perfil dela chegou às 20:18 e a recusa
    dela foi às 19:46, com o mesmo número e o mesmo template. Foi por isso que o cadastro
    entrou como segunda fonte (`80358e5`).

    ------------------------------------------------------------------------------------
    POR QUE A ORDEM INVERTEU (S3-4, 27/08/2026)
    ------------------------------------------------------------------------------------
    O cadastro cobria a AUSÊNCIA do perfil. Não cobria o perfil PRESENTE e errado — e o
    perfil do WhatsApp é apelido, não nome. RECON de 27/08, `5511940718388`:

        contacts.name                  "Eve 🍒🦖🤞"
        exact_leads.name / agendamentos.nome  "Evelyn Renata Begliomini Manfrim"

    e a abertura saiu **"Olá, Eve!"** — para alguém que se inscreveu como Evelyn e vai
    aparecer como Evelyn na reunião com a consultora. O cadastro é o nome com que a pessoa se
    candidatou; o perfil é como ela se apresenta para os amigos dela.

    O CONJUNTO DE FONTES NÃO MUDOU — só a preferência. Isso é o que garante que o `#131008`
    não volta: o caso "vazio" continua sendo exatamente o mesmo, os DOIS lugares vazios, e
    aí a recusa local de `nat_sender` (parâmetro em branco) pega antes da Meta. Trocar a
    ordem não pode criar um vazio novo, porque nenhuma fonte foi removida — e é isso que o
    grupo 2 de `test_nome_cadastro_primeiro.py` trava.

    Custo: 1–2 SELECTs a mais por abertura (`_identidade_do_lead`), contra 1 que já havia.
    `_nome` roda uma vez por abertura e uma vez por montagem de contexto do LLM.

    ------------------------------------------------------------------------------------
    `.strip()` NA ESCOLHA — o que a inversão obrigou a arrumar
    ------------------------------------------------------------------------------------
    `primeiro_nome` devolve a entrada INTACTA quando nenhum token tem letra (está na
    docstring dela, e é a decisão certa lá: `"Olá, 123!"` é ruim, `"Olá, !"` é pior). Então
    `primeiro_nome("   ")` é `"   "` — que é *truthy*, e passaria como se fosse nome.

    Com a ordem antiga isso quase não aparecia: a primeira fonte era o perfil do WhatsApp,
    que o próprio WhatsApp normaliza. A primeira fonte agora é `agendamentos.nome`, que é
    campo livre de formulário e `nullable=False` — só-espaço é plausível ali. Sem o `strip`,
    um cadastro em branco venceria um perfil perfeitamente bom, o parâmetro sairia vazio, e
    a recusa local de `nat_sender` mataria a abertura de um lead que tinha nome.

    Trocar a ordem não podia introduzir um modo de falha novo; o `strip` é o que garante
    isso. Travado no grupo 5 de `test_identidade_abertura.py`.
    """
    do_lead, _ = await _identidade_do_lead(estado.exact_lead_id, db)
    nome = primeiro_nome(do_lead or "").strip()
    if nome:
        return nome
    contato = await _contato_de(estado.contact_wa_id, db)
    return primeiro_nome((contato.name if contato else "") or "").strip()


def _espalhados(horarios: list[dict], n: int) -> list[dict]:
    """Até `n` horários do dia, ESPALHADOS da manhã à tarde, em ordem.

    Isto era um `[:6]` — os seis primeiros — e funcionava enquanto a grade tinha 5 horários
    por dia: cortar os seis primeiros de cinco não corta nada. Em 25/08/2026 a grade virou o
    comercial inteiro (09:00–18:30, 12 horários/dia) e o corte passou a devolver
    `09:00 09:45 10:30 11:15 12:00 12:45` — **o agente nunca mais ofereceria uma tarde**,
    em silêncio, e quem só pode à tarde ouviria "não tenho horário" com a tarde inteira
    livre.

    Espalhar em vez de aumentar o `n`: o limite existe porque a lista vai inteira para o
    prompt e uma parede de 12 horários por dia empurra o modelo a despejar tudo no
    WhatsApp. Seis pontos cobrindo 09:00–17:15 dizem mais sobre o dia do que doze.

    ISTO NÃO É O QUE A PESSOA VÊ. Este `n` corta o que vai para o CONTEXTO — a lista da qual
    o modelo pode escolher, e a garantia de que ele não inventa horário. Quantos deles são
    APRESENTADOS é regra da missão de `ofertando_agenda`, hoje no máximo 5. Os dois números
    são diferentes de propósito: 3 dias × 6 dão ao modelo margem para atender "prefiro de
    manhã" sem uma segunda consulta à grade; 5 é o que cabe numa mensagem de WhatsApp sem
    virar parede. A Fabiana recebeu 14 numa mensagem só, em 25/08.

    Extremos sempre entram — o primeiro e o último horário do dia são justamente os que
    resolvem quem só pode cedo ou só pode tarde.
    """
    if len(horarios) <= n or n < 2:
        return horarios[:n] if n < 2 else horarios
    passo = (len(horarios) - 1) / (n - 1)
    indices = sorted({round(i * passo) for i in range(n)})
    return [horarios[i] for i in indices]


async def _fatos(estado: NatQualificacaoState, db: AsyncSession, *,
                 com_slots: bool = False) -> tuple[str, dict]:
    """(contexto para o prompt, mapa slot_id → slot oferecido).

    Os slots entram SÓ quando `com_slots` — é o que garante que o modelo não tem horário
    nenhum para oferecer nas etapas de qualificação, mesmo que a pessoa peça.
    """
    from app.agendamento import consultoras as equipe

    reuniao = await _reuniao(estado, db)
    fatos = {
        "Primeiro nome da pessoa": await _nome(estado, db),
        "Curso a que ela se candidatou": await _curso(estado, db),
        "Formação dela": estado.formacao,
        "Ano de conclusão": estado.ano_conclusao,
        "Atuação profissional": estado.atuacao,
        "Motivação declarada": estado.motivacao,
    }
    if reuniao is not None:
        fatos["Reunião já marcada para"] = reuniao.slot_inicio.strftime("%d/%m às %H:%M")
        fatos["Consultora que vai atender"] = equipe.nome_de(reuniao.sales_rep_email or "")

    ofertados = {}
    if com_slots:
        from app.agendamento import disponibilidade
        try:
            por_dia = await disponibilidade.resumo_por_dia(db)
        except Exception as e:
            print(f"⚠️  Agente: grade não carregada ({type(e).__name__}: {e})")
            por_dia = {}
        linhas = []
        for dia in sorted(por_dia)[:3]:          # 3 dias bastam para uma escolha
            for h in _espalhados(por_dia[dia], 6):
                rotulo = f"{dia} {h['hora']} (id: {h['id']})"
                linhas.append(rotulo)
                ofertados[h["id"]] = rotulo
        fatos["Horários disponíveis (use SÓ estes)"] = linhas

    return llm.montar_contexto(fatos), ofertados


# ==========================================================================================
# ESCRITA
# ==========================================================================================

async def _enviar(estado: NatQualificacaoState, texto: str,
                  db: AsyncSession) -> tuple[bool, str]:
    """Fala livre do agente, dentro da janela de 24h. `(saiu, motivo)`."""
    return await enviar_nat(
        estado.contact_wa_id, guard.ETAPA_CONVERSA, db,
        guard=guard.qualificacao_pode_atuar, corpo_livre=texto)


async def _descartar_fala_adiada(estado: NatQualificacaoState, porque: str,
                                 db: AsyncSession) -> None:
    """Joga fora a fala que o teto adiou. Nunca levanta — higiene não derruba turno.

    ------------------------------------------------------------------------------------
    A ARESTA DAS DUAS FALAS FORA DE ORDEM
    ------------------------------------------------------------------------------------
    O adiamento por teto (P0-B) guarda o texto do turno e tenta de novo em 10 min. Entre
    agendar e disparar, a pessoa pode escrever DE NOVO — e escreve, justamente porque não
    recebeu resposta. O turno novo roda na etapa que já avançou (o `_avancar` move a etapa
    mesmo quando a fala foi só adiada: o dado extraído não pode se perder) e produz a fala
    da etapa seguinte. Dois desfechos:

        o turno novo TAMBÉM é recusado pelo teto -> `nat_agendar` cancela o pendente do
            mesmo (kind, contato) antes de inserir. Só o texto mais novo sobrevive. Já
            estava certo, por construção do agendador.

        o turno novo CONSEGUE falar (o teto é contagem MÓVEL de 1h — ele libera sozinho
            dentro dos 10 min) -> sem este cancelamento, a fala velha dispara depois e a
            pessoa recebe a pergunta do passo ANTERIOR depois da do passo seguinte. Duas
            falas fora de ordem, e a segunda perguntando o que ela já respondeu.

    NADA SE PERDE AO DESCARTAR. A fala adiada era o reconhecimento + a pergunta da etapa em
    que o lead já está; como ela nunca chegou a sair, o turno novo faz a mesma pergunta com
    contexto mais fresco. O que se descarta é uma duplicata velha, não informação.

    Chamado nos dois pontos em que o agente EFETIVAMENTE fala com o lead: quando a fala sai
    (`_falar`) e quando ele se despede (`_fallback`). Depois de qualquer um dos dois, uma
    fala velha na fila só pode piorar a conversa.
    """
    try:
        await nat_cancelar(KIND_RESPONDER_PENDENTE, estado.contact_wa_id, db)
    except Exception as e:
        print(f"⚠️  Agente: fala adiada de {estado.contact_wa_id} não cancelada "
              f"({porque}): {type(e).__name__}: {e}")


async def _falar(estado: NatQualificacaoState, texto: str, db: AsyncSession) -> bool:
    """Fala — e trata a RECUSA, que até 26/08 era jogada fora. Devolve se o turno segue.

    ------------------------------------------------------------------------------------
    O BURACO MAIS LARGO DOS SEIS (P0-B)
    ------------------------------------------------------------------------------------
    `_enviar` sempre soube dizer se a mensagem saiu. Ninguém lia. `processar_texto`,
    `_avancar` e `_ofertar_agenda` chamavam `await _enviar(...)` e descartavam o retorno,
    devolviam True ("tratei") e o turno terminava normalmente — sem mensagem, sem fallback,
    sem notificação e SEM EXCEÇÃO. Silêncio perfeito, invisível em qualquer tabela.

    MEDIDO em 25/08: matou 4 mensagens do 5583988046720 e 2 do 5582998307979. As duas
    conversas morreram sem deixar um único rastro ligado ao lead — só uma linha de `print`
    no journald que nem sempre chegava a sair do buffer.

    A RECUSA TEM DUAS NATUREZAS, E TRATÁ-LAS IGUAL É O ERRO:

        teto por hora   -> passa sozinho. REENFILEIRA a fala e tenta de novo em 10 min.
                           É a mesma lógica que `iniciar_qualificacao` já usa com AcaoAdiada:
                           o teto é contagem MÓVEL, esperar resolve. Transferir o lead para
                           humano por causa de uma janela cheia seria queimar lead por
                           congestionamento.
        qualquer outra  -> não passa sozinha (janela fechada, chave desligada, template não
                           montável, Meta recusou). `_fallback`: despedida + notificação.

    A fala reenfileirada é a MESMA que o LLM gerou agora. Ela pode chegar até 10 min depois
    do inbound e soar um pouco atrasada — e isso é aceitável de propósito: a alternativa
    medida é o lead nunca receber nada. Se o lead escrever nesse intervalo, o cancelamento
    de `_descartar_fala_adiada` impede que as duas falas cheguem fora de ordem.

    DORMENTE DESDE O P1-B (26/08). O teto por hora saiu de `qualificacao_pode_atuar`, então
    a CONVERSA não é mais recusada por ele e este ramo não deve disparar em produção. Fica
    inteiro de propósito: ele é a rede se o teto voltar a valer para a conversa (a auditoria
    previu essa hipótese como "opção B"), e `enviar_nat` repassa o motivo do guard tal e
    qual — qualquer trava futura que se chame teto cai aqui e é ADIADA, não descartada.
    """
    saiu, motivo = await _enviar(estado, texto, db)
    if saiu:
        await _descartar_fala_adiada(estado, "o agente acabou de falar", db)
        return True

    if guard.e_teto(motivo):
        await nat_agendar(KIND_RESPONDER_PENDENTE, estado.contact_wa_id,
                          _agora_sp() + ATRASO_POR_TETO, {"texto": texto}, db)
        print(f"⏳ Agente: fala para {estado.contact_wa_id} adiada ({motivo}) — "
              f"reenfileirada para daqui a {int(ATRASO_POR_TETO.total_seconds() // 60)} min")
        return False

    await _fallback(estado, f"envio recusado: {motivo}", db)
    return False


async def _notificar(estado: NatQualificacaoState, titulo: str, corpo: str,
                     db: AsyncSession) -> None:
    """Avisa o SDR dono; sem dono, a gestão. Nunca levanta — aviso não derruba fluxo."""
    from app.nat_flow import telefone_legivel, usuario_existe
    try:
        contato = await _contato_de(estado.contact_wa_id, db)
        dono = contato.assigned_to if contato else None
        destinatario = dono if await usuario_existe(dono, db) else GESTOR_USER_ID
        if not await usuario_existe(destinatario, db):
            print(f"❌ Agente: sem destinatário para avisar sobre {estado.contact_wa_id}")
            return
        db.add(Notification(
            user_id=destinatario, contact_wa_id=estado.contact_wa_id,
            type=TIPO_NOTIF_AGENTE, ref=estado.ultimo_wa_message_id,
            title=titulo,
            body=f"{corpo} — {telefone_legivel(estado.contact_wa_id)}"))
        print(f"🔔 Agente notificou user {destinatario}: {titulo}")
    except Exception as e:
        print(f"⚠️  Agente: notificação falhou ({type(e).__name__}: {e})")


async def _fallback(estado: NatQualificacaoState, motivo: str, db: AsyncSession) -> None:
    """LLM caiu, fugiu do contrato, ou pediu o impossível. Encerra o agente para o contato.

    A ORDEM IMPORTA: muda a etapa ANTES de enviar. `transferido_humano` está fora de
    ETAPAS_QUALIFICACAO_ATIVAS, então a partir daqui o agente nem escuta nem fala — e é
    justamente isso que impede um loop de "falhou → tenta de novo → falhou".

    Por isso o envio usa `guard_de_despedida` e não `qualificacao_pode_atuar`: a etapa já não
    é ativa, e o guard de envio recusaria a própria mensagem de despedida. Era
    `guard_de_abertura` até 26/08 (P1-B) — e com ele vinha o teto por hora, que podia calar
    exatamente a mensagem cuja razão de existir é não deixar o lead no silêncio.
    """
    print(f"🛟 Agente transferiu {estado.contact_wa_id} para humano: {motivo}")
    await _descartar_fala_adiada(estado, "o lead foi transferido", db)
    estado.etapa = ETAPA_Q_TRANSFERIDO
    estado.transferido_em = _agora_sp()
    estado.transferido_motivo = motivo
    await db.flush()
    # S6-4: transferida é transferida. Ver `_cancelar_follow`.
    await _cancelar_follow(estado.contact_wa_id, "a conversa foi transferida", db)

    # S5-3 (varredura): o retorno era descartado aqui também. Levantar NÃO serve — o estado
    # já é `transferido_humano` e uma exceção desfaria a transferência, que é o desfecho
    # correto. O que faltava era CONTAR: sem a despedida, o lead ficou sem nenhum aviso de
    # que alguém ia assumir, e quem precisa saber disso é justamente o SDR que a notificação
    # abaixo acorda. Então o aviso vai NA notificação, não só no `🔒` do log.
    saiu, motivo_envio = await enviar_nat(estado.contact_wa_id, guard.ETAPA_CONVERSA, db,
                                          guard=guard.guard_de_despedida,
                                          corpo_livre=TEXTO_FALLBACK)
    aviso = ("" if saiu else
             f" ⚠️ A despedida NÃO saiu ({motivo_envio}) — o lead não foi avisado de que "
             f"alguém assumiria.")
    await _notificar(estado, "Agente passou um lead para você",
                     f"Motivo: {motivo}.{aviso}", db)


# ==========================================================================================
# HUMANO ASSUME, AGENTE SILENCIA
# ==========================================================================================

MOTIVO_ASSUMIDO_SDR = "assumido_sdr"
MOTIVO_OUTBOUND_MANUAL = "outbound_manual_sdr"


async def silenciar(contact_wa_id: str, motivo: str, db: AsyncSession, *,
                    quem_id: int | None = None, quem_nome: str | None = None) -> str | None:
    """Tira o agente da conversa AGORA. Devolve a etapa que ele deixou, ou None.

    Duas portas chamam isto:
      * o botão "Assumir conversa" (`nat_routes.assumir_conversa`), quando o SDR decide;
      * a trava automática (`routes._silenciar_agente_apos_envio_manual`), quando o SDR
        simplesmente digita — que é como a maioria vai acontecer, porque ninguém lembra de
        clicar num botão antes de responder.

    É PARENTE DE `_fallback`, MAS NÃO É ELE, e a diferença é o ponto da sprint:

        _fallback   o agente desistiu -> manda uma despedida ao lead e avisa o SDR
        silenciar   o humano chegou   -> NÃO manda NADA e NÃO avisa NINGUÉM

    Mandar a despedida aqui seria o defeito que esta sprint existe para impedir: o SDR digita
    "oi, sou o Thobias" e o lead recebe, logo depois, "vou te passar para um humano". Duas
    vozes na mesma thread, uma delas dizendo que vai fazer o que a outra acabou de fazer.
    E notificar tampouco: quem seria notificado é justamente quem acabou de agir.

    IDEMPOTENTE e SILENCIOSA no caso comum: sem estado, ou em etapa que já não é ativa,
    devolve None sem tocar em nada. É o que permite chamá-la de dentro de todo envio manual
    sem transformar cada mensagem de SDR numa escrita no banco.

    Tolerante ao 9º dígito por vir de `estado_de` — o wa_id da tela e o do estado podem estar
    em grafias diferentes (ver `app/telefone.py`).

    QUEM assumiu vai para `dados_extras`, não para coluna nova. `transferido_motivo` guarda o
    motivo literal e parseável que o produto pediu (`assumido_sdr`), e enfiar o nome junto
    ("assumido_sdr por Fulano") tornaria a coluna impossível de agrupar em relatório. Coluna
    nova exigiria migração numa tabela que ESTÁ EM PRODUÇÃO com o agente no ar — atrito
    desproporcional para um campo de auditoria. Se virar consulta frequente, promove-se a
    coluna depois.
    """
    estado = await estado_de(contact_wa_id, db)
    if estado is None or estado.etapa not in ETAPAS_QUALIFICACAO_ATIVAS:
        return None

    anterior = estado.etapa
    estado.etapa = ETAPA_Q_TRANSFERIDO
    estado.transferido_em = _agora_sp()
    estado.transferido_motivo = motivo
    if quem_id is not None or quem_nome:
        extras = dict(estado.dados_extras or {})
        extras["assumido_por"] = {"id": quem_id, "nome": quem_nome}
        estado.dados_extras = extras
    await db.flush()

    # S6-4: o humano assumiu — o follow do agente não tem mais o que perguntar, e mandá-lo
    # seria a segunda voz na thread que `silenciar` existe para impedir.
    await _cancelar_follow(estado.contact_wa_id, "o SDR assumiu a conversa", db)

    print(f"🤝 Agente silenciado em {estado.contact_wa_id}: {anterior} → "
          f"{ETAPA_Q_TRANSFERIDO} (motivo={motivo}"
          + (f", por {quem_nome}" if quem_nome else "") + ")")
    return anterior


def _guardar_dado(estado: NatQualificacaoState, extraido: dict | None) -> None:
    """Grava o que o LLM extraiu. Campo conhecido vira coluna; o resto vira JSONB."""
    if not extraido:
        return
    extras = dict(estado.dados_extras or {})
    for chave, valor in extraido.items():
        if chave in CAMPOS:
            setattr(estado, chave, valor)
        elif chave != "slot_id":     # slot_id é instrução, não dado do lead
            extras[chave] = valor
    if extras:
        estado.dados_extras = extras


# ==========================================================================================
# ENTRADA: A ABERTURA (handler do KIND_INICIAR_QUALIFICACAO)
# ==========================================================================================

@registrar_handler("iniciar_qualificacao")
async def iniciar_qualificacao(acao: dict, db: AsyncSession) -> None:
    """+5 min depois da aplicação: escolhe a abertura e cria o estado.

    O ESTADO É RELIDO AQUI, nunca vem do payload — entre agendar e executar passam 5 minutos,
    e é exatamente nesse intervalo que a pessoa termina (ou não) o agendamento no
    obrigado.html. Medido: mediana 28s, máximo 3min14s entre o formulário e o agendamento;
    aos 5 minutos a ramificação é definitiva.

    NENHUMA SAÍDA DAQUI É SILENCIOSA (Risco 3). Até 25/08 este handler tinha cinco `return`
    mudos, e os cinco viravam `executado` — a mesma marca de quem abriu a conversa. Foi assim
    que 4 ações executadas produziram ZERO estados sem nada quebrar. Agora:

        não dá para agir AGORA  -> AcaoAdiada  (fora do horário, teto por hora) — volta a
                                   `pendente` com run_at empurrado, SEM consumir tentativa
        não há o que fazer      -> AcaoIgnorada (já tem estado, anterior ao corte, sem
                                   contato possível) — vira `skipped` com o motivo no banco
        abriu                   -> `executado`, e agora isso significa uma coisa só

    Levantar em vez de `return` também reverte o savepoint do handler, o que apaga de graça
    o Contact e o estado criados antes de se descobrir que a abertura não sairia — a limpeza
    que o `db.delete(estado)` fazia à mão, e que não cobria o contato.
    """
    from app.qualificacao_dados import resolver_dados
    from app.models import ORIGEM_LP

    payload = json.loads(acao.get("payload") or "{}")
    wa_id = acao["contact_wa_id"]
    lead_id = payload.get("lead_id")
    origem = payload.get("origem") or ORIGEM_LP

    # HORÁRIO COMERCIAL (09h00–18h30, seg-sex). Só a ABERTURA respeita — ela é
    # business-initiated, e é a única mensagem que a pessoa não pediu.
    #
    # Fora da janela EMPURRA, não recusa: recusar deixaria sem abertura para sempre o lead
    # que se candidatou às 22h — e 22h é uma das horas de maior movimento da LP (8 dos 81
    # formulários medidos).
    #
    # É a MESMA linha que continua pendente, com o run_at empurrado — e não uma linha nova
    # como antes. A versão anterior chamava `agendar`, que começa cancelando o pendente do
    # par (kind, contato): ou seja, cancelava a própria ação em execução e só não estragava
    # nada porque o `_finalizar` logo depois a reescrevia para `executado`. Adiar a linha no
    # lugar tira esse cruzamento, não gasta id, e mantém o histórico da espera num lugar só.
    agora = acao.get("agora") or _agora_sp()
    if not dentro_horario_comercial(agora):
        raise AcaoAdiada(proximo_horario_util(agora),
                         f"fora do horário comercial ({agora:%H:%M})")

    ja = await estado_de(wa_id, db)
    if ja is not None:
        # NÃO é lead perdido: é lead já atendido. Vira `skipped` justamente para o §2b do
        # monitor parar de confundir os dois — ele procura ação EXECUTADA sem estado, e um
        # booking espontâneo caía aqui e produzia essa assinatura como falso positivo.
        raise AcaoIgnorada(f"já tem estado ({ja.etapa}) — abertura desnecessária")

    # ADMISSÃO. A data de referência vem de quem agendou a ação: para a LP é
    # agendamentos.created_at (o lead pode nem estar em exact_leads ainda), para o sync é
    # register_date. Já em UTC naive — ver o cabeçalho de qualificacao_guard.
    referencia = payload.get("referencia_utc")
    if isinstance(referencia, str):
        from datetime import datetime as _dt
        try:
            referencia = _dt.fromisoformat(referencia)
        except ValueError:
            referencia = None
    pode, motivo = await guard.qualificacao_pode_iniciar(referencia, db)
    if not pode:
        # O TETO É O ÚNICO "NÃO" QUE VIRA "SIM" SOZINHO. Corte de data e chave desligada não
        # mudam de ideia em dez minutos; o teto por hora muda, porque a contagem é móvel.
        # Tratar os dois igual era descartar lead por causa de uma janela cheia.
        if guard.e_teto(motivo):
            raise AcaoAdiada(agora + ATRASO_POR_TETO, motivo)
        raise AcaoIgnorada(f"não admitido: {motivo}")

    contato = await _contato_ou_criar(wa_id, lead_id=lead_id, db=db)
    if contato is None:
        raise AcaoIgnorada("não foi possível resolver nem criar o contato "
                           "(sem canal configurado?)")

    # ------------------------------------------------------------------------------------
    # S5-2 — A GRAFIA DAQUI PARA BAIXO É A DO CONTATO, NÃO A DA AÇÃO (28/08/2026)
    # ------------------------------------------------------------------------------------
    # `_contato_ou_criar` resolve nas DUAS grafias desde `05cea3f`: com o contato já
    # existindo como 12 dígitos, ele acha, decide corretamente NÃO criar o de 13 — e o
    # objeto resolvido era jogado fora, porque este ponto só testava `is None`. O estado
    # nascia com a grafia da ação e `nat_sender` procurava `Contact.wa_id == <13 dígitos>`
    # com igualdade crua, não achava, e recusava com "contato não existe no banco". O
    # savepoint então revertia o estado junto: o lead não recebia nada, não virava estado e
    # não entrava em fila nenhuma — sumia.
    #
    # MEDIDO em 27-28/08: 6 ações, 4 pessoas (Fernanda `554999333881`, `558588719031`,
    # Sandra Diell `555596238065`, `555198557793`). 19% das aberturas da janela.
    #
    # NÃO SE MEXE NA IGUALDADE CRUA DO SENDER. A docstring de `_contato_ou_criar` explica
    # por que o porteiro precisa ser estrito: em 25/08 a variante de 12 dígitos de um lead
    # era o número de OUTRA PESSOA, e só a igualdade do sender impediu o envio para o
    # estranho. A regra continua sendo UMA — "o contato da abertura é o da grafia para a
    # qual vamos mandar" —, e a forma de cumpri-la é ALINHAR a grafia ao contato que existe,
    # não afrouxar quem envia.
    if contato.wa_id != wa_id:
        print(f"🔤 Agente: {wa_id} já existe como {contato.wa_id} — abertura segue nessa "
              f"grafia (estado e envio)")
        wa_id = contato.wa_id

    dados = await resolver_dados(lead_id=lead_id, origem=origem, db=db)
    formacao = dados["formacao"]

    estado = NatQualificacaoState(
        contact_wa_id=wa_id, exact_lead_id=lead_id, origem=origem,
        etapa=ETAPA_Q_AGUARDANDO_ANO if formacao else ETAPA_Q_AGUARDANDO_FORMACAO,
        formacao=formacao,
        faixa_investimento=dados["faixa_investimento"],
        dados_extras={"como_conheceu": dados["como_conheceu"]} if dados["como_conheceu"] else None,
    )
    db.add(estado)
    await db.flush()

    reuniao = await _reuniao(estado, db)
    nome, curso = await _nome(estado, db), await _curso(estado, db)

    # T1 / T2 / T3 — a escolha é código, não modelo.
    if reuniao is not None and formacao:
        from app.agendamento import consultoras as equipe
        etapa_msg = guard.ETAPA_ABERTURA_AGENDADO
        parametros = [nome, curso, equipe.nome_de(reuniao.sales_rep_email or ""),
                      reuniao.slot_inicio.strftime("%d/%m"),
                      reuniao.slot_inicio.strftime("%H:%M"), formacao]
        estado.agendamento_id = reuniao.id
    elif formacao:
        etapa_msg = guard.ETAPA_ABERTURA_QUALIFICACAO
        parametros = [nome, curso, formacao]
    else:
        etapa_msg = guard.ETAPA_ABERTURA_SEM_FORMACAO
        parametros = [nome, curso]

    corpo = await _corpo_do_template(etapa_msg, parametros, db)
    enviado, motivo_envio = await enviar_nat(wa_id, etapa_msg, db,
                                             guard=guard.guard_de_abertura,
                                             parametros=parametros, corpo_livre=corpo)
    if not enviado:
        # Sem abertura não há conversa — e o savepoint do handler leva embora o estado E o
        # contato recém-criados, sem `db.delete` à mão (que só cobria o estado).
        #
        # O teto pode estourar AQUI mesmo tendo passado na admissão: entre uma coisa e outra
        # o `_corpo_do_template` faz uma chamada à Meta, e outras aberturas do mesmo ciclo
        # podem ter enchido a janela nesse intervalo. Adiar em vez de descartar é o que faz a
        # segunda linha de defesa não custar o lead.
        if guard.e_teto(motivo_envio):
            raise AcaoAdiada(agora + ATRASO_POR_TETO, motivo_envio)
        raise AcaoIgnorada(f"abertura não saiu: {motivo_envio}")

    # Arma o relógio da inatividade já na abertura. Sem isto, quem NUNCA responde nunca
    # encerraria — e é justamente esse lead que a régua de follow-up quer receber.
    await _agendar_encerramento(estado, db)
    # S6-4: e o follow de 20h, no MESMO ponto. É aqui que ele mais importa — dos 39 leads
    # que calaram e ninguém tocou na janela do RECON, a maior parte calou logo depois da
    # abertura, ainda em `aguardando_ano` ou `aguardando_formacao`.
    await _agendar_follow(estado, db)
    print(f"🚀 Agente abriu com {wa_id}: {etapa_msg} → {estado.etapa}")


async def _corpo_do_template(nome_template: str, parametros: list,
                             db: AsyncSession) -> str | None:
    """O texto renderizado do template, para a Message local não ficar vazia na tela do SDR.

    Vem da Meta, que é a única fonte da verdade do corpo aprovado — copiá-lo para cá criaria
    a mesma cópia que apodrece que o `nat_copy` já precisa vigiar com teste de drift.
    Falhar aqui é inofensivo: o envio usa template + parâmetros e independe disto.
    """
    try:
        from app.models import Channel
        from app.whatsapp import fetch_template_body, render_template_text
        canal = (await db.execute(select(Channel).where(Channel.id == 1))).scalar_one_or_none()
        if canal is None:
            return None
        corpo = await fetch_template_body(canal.waba_id, canal.whatsapp_token,
                                          nome_template, "pt_BR")
        return render_template_text(corpo, parametros) if corpo else None
    except Exception as e:
        print(f"⚠️  Agente: corpo de '{nome_template}' não renderizado ({type(e).__name__})")
        return None


# ==========================================================================================
# O NÚCLEO: UMA MENSAGEM DO LEAD
# ==========================================================================================

async def processar_texto(contact_wa_id: str, texto: str, wa_message_id: str,
                          db: AsyncSession) -> bool:
    """Uma mensagem recebida. True se o agente tratou; False se não é dele.

    False significa "não sou o dono desta mensagem" — o webhook então segue para o fluxo
    velho, como sempre fez.
    """
    estado = await estado_de(contact_wa_id, db)
    if estado is None or estado.etapa not in ETAPAS_QUALIFICACAO_ATIVAS:
        return False
    if _ja_processado(estado, wa_message_id):
        print(f"↩️  Agente: {wa_message_id} já processado para {contact_wa_id}")
        return True

    estado.ultimo_wa_message_id = wa_message_id
    await db.flush()

    # O relógio da inatividade reinicia a cada mensagem DELA. `agendar` cancela o pendente
    # anterior antes de inserir, então isto reagenda em vez de acumular — e o índice único
    # parcial do banco é a rede da mesma regra.
    await _agendar_encerramento(estado, db)

    # S6-4: o follow segue o mesmo relógio — cada mensagem DELA empurra os 20h para frente.
    # `agendar` cancela o pendente antes de inserir, então isto reagenda em vez de acumular.
    await _agendar_follow(estado, db)

    # E o vigia do P3-A, pela mesma mecânica e no mesmo ponto: dois inbounds seguidos
    # reagendam um vigia só, porque `agendar` cancela o pendente do mesmo (kind, contato)
    # antes de inserir. Os dois kinds convivem — o índice é sobre (kind, contact_wa_id).
    await _armar_vigia(estado, db)

    etapa = estado.etapa
    com_slots = etapa in (ETAPA_Q_OFERTANDO_AGENDA, ETAPA_Q_ESCOLHENDO_SLOT)
    contexto, ofertados = await _fatos(estado, db, com_slots=com_slots)

    resposta = await llm.conversar(missao=MISSOES[etapa], contexto=contexto,
                                   historico=await _historico(contact_wa_id, db),
                                   # S5-7: o wa_id do ESTADO, não o do inbound. `estado_de`
                                   # é tolerante às duas grafias, então `contact_wa_id` aqui
                                   # é a grafia de quem escreveu (12 dígitos para 59% das
                                   # threads) enquanto o estado vive na outra. Rotular pelo
                                   # estado é rotular pela CHAVE — a mesma em todo turno da
                                   # mesma pessoa, e a mesma que `_ofertar_agenda` usa.
                                   rotulo=f"{estado.contact_wa_id}/{etapa}")
    if resposta is None:
        await _fallback(estado, "LLM indisponível ou fora do contrato", db)
        return True

    if resposta["acao"] == "transferir_humano":
        await _fallback(estado, "o LLM pediu transferência (lead quer falar com uma pessoa, "
                                "remarcar, ou saiu do roteiro)", db)
        return True

    _guardar_dado(estado, resposta["dado_extraido"])

    # AÇÃO IMPOSSÍVEL NA ETAPA. O modelo propôs agendar numa etapa de qualificação: não
    # improvisa, não ignora — transfere. Ignorar seria seguir conversando como se nada
    # tivesse acontecido, e o lead acabou de ouvir uma promessa que não vai ser cumprida.
    if resposta["acao"] == "agendar_slot" and not com_slots:
        await _fallback(estado, f"ação 'agendar_slot' pedida em '{etapa}', onde não há "
                                "agenda oferecida", db)
        return True

    if resposta["acao"] == "agendar_slot":
        await _agendar(estado, resposta, ofertados, db)
        return True

    if not resposta["etapa_cumprida"]:
        # A pessoa desconversou ou perguntou outra coisa. O LLM acolhe e retoma; a etapa NÃO
        # anda. É o caminho normal de uma digressão, não uma falha.
        await _falar(estado, resposta["mensagem"], db)
        return True

    await _avancar(estado, resposta["mensagem"], db)
    return True


async def _avancar(estado: NatQualificacaoState, mensagem: str, db: AsyncSession) -> None:
    """Etapa cumprida: envia a fala e move o estado. ÚNICO lugar que faz as duas coisas."""
    etapa = estado.etapa

    if etapa in PROXIMA:
        # A etapa anda mesmo se a fala foi só ADIADA pelo teto: o dado do lead já foi
        # extraído e regravar a etapa depois exigiria guardar o turno inteiro. O que não
        # pode acontecer — e não acontece — é a etapa andar depois de um `_fallback`, que
        # já move o estado para `transferido_humano` antes de voltar.
        if not await _falar(estado, mensagem, db) and estado.etapa == ETAPA_Q_TRANSFERIDO:
            return
        estado.etapa = PROXIMA[etapa]
        print(f"➡️  Agente: {estado.contact_wa_id} {etapa} → {estado.etapa}")
        return

    if etapa == ETAPA_Q_AGUARDANDO_MOTIVACAO:
        # A bifurcação do roteiro. Releitura, não memória: a reunião pode ter nascido no
        # obrigado.html DEPOIS da abertura.
        reuniao = await _reuniao(estado, db)
        if not await _falar(estado, mensagem, db) and estado.etapa == ETAPA_Q_TRANSFERIDO:
            return
        if reuniao is not None:
            estado.agendamento_id = reuniao.id
            await _concluir(estado, reuniao, db, confirmar=True)
        else:
            estado.etapa = ETAPA_Q_OFERTANDO_AGENDA
            await _ofertar_agenda(estado, db)
        return

    # ofertando_agenda / escolhendo_slot com etapa_cumprida e sem acao=agendar_slot é
    # contradição do modelo: disse que cumpriu sem escolher horário nenhum.
    await _fallback(estado, f"etapa '{etapa}' dada como cumprida sem slot escolhido", db)


async def _ofertar_agenda(estado: NatQualificacaoState, db: AsyncSession) -> None:
    """Apresenta a grade. Os horários vêm de `disponibilidade`; o LLM só os veste."""
    contexto, ofertados = await _fatos(estado, db, com_slots=True)
    if not ofertados:
        await _fallback(estado, "não há horário livre na grade para oferecer", db)
        return
    resposta = await llm.conversar(missao=MISSOES[ETAPA_Q_OFERTANDO_AGENDA],
                                   contexto=contexto,
                                   historico=await _historico(estado.contact_wa_id, db),
                                   # S5-7: era `ofertar_agenda` — nome de etapa que NÃO
                                   # existe no banco (a real é `ofertando_agenda`). Com o
                                   # rótulo do turno normal usando o wa_id do INBOUND (12
                                   # dígitos) e este o do ESTADO (13), a Clarice aparecia
                                   # como 553199818666 em 5 turnos e 5531999818666 em 1: um
                                   # `grep` pelo telefone perdia metade dos turnos da mesma
                                   # pessoa. Uma grafia só (a do estado, que é a chave) e o
                                   # nome real da etapa.
                                   rotulo=f"{estado.contact_wa_id}/{ETAPA_Q_OFERTANDO_AGENDA}"
                                          f"[{len(ofertados)} slots]")
    if resposta is None:
        await _fallback(estado, "LLM indisponível ao oferecer a agenda", db)
        return
    if not await _falar(estado, resposta["mensagem"], db) \
            and estado.etapa == ETAPA_Q_TRANSFERIDO:
        return
    estado.etapa = ETAPA_Q_ESCOLHENDO_SLOT
    print(f"📅 Agente ofereceu {len(ofertados)} horário(s) a {estado.contact_wa_id}")


async def _agendar(estado: NatQualificacaoState, resposta: dict, ofertados: dict,
                   db: AsyncSession) -> None:
    """Escreve a reunião. O slot é VALIDADO duas vezes antes de qualquer escrita.

    Primeiro contra o que foi realmente oferecido nesta rodada (o modelo não pode inventar
    um id), depois contra `slots_livres(usar_cache=False)` — porque entre oferecer e escolher
    passaram minutos e a grade é cacheada por 60s.
    """
    from app.agendamento import agendar as fluxo, disponibilidade

    slot_id = (resposta.get("dado_extraido") or {}).get("slot_id")
    if not slot_id or slot_id not in ofertados:
        await _fallback(estado, f"o LLM escolheu um horário que não foi oferecido "
                                f"({slot_id!r})", db)
        return

    livres = {d.id for d in await disponibilidade.slots_livres(db, usar_cache=False)}
    if slot_id not in livres:
        # Corrida: alguém pegou o horário. Não é falha — reapresenta a grade.
        print(f"↩️  Agente: slot {slot_id} não está mais livre; reofertando")
        estado.etapa = ETAPA_Q_OFERTANDO_AGENDA
        await _ofertar_agenda(estado, db)
        return

    contato = await _contato_de(estado.contact_wa_id, db)
    nome = (contato.name if contato else "") or "Lead"

    # S5-1 — os dois dados que faltavam na chamada, lidos ANTES de abrir a sessão própria
    # do agendamento: são consultas de leitura na sessão do webhook, e fazê-las lá dentro
    # esticaria a segunda conexão sem necessidade (ver o bloco P0-A logo abaixo).
    from app.qualificacao_dados import extras_brutos_da_lp
    origem = await _origem_do_agendamento(estado, db)
    extras = await extras_brutos_da_lp(estado.exact_lead_id, db)
    try:
        # ----------------------------------------------------------------------------------
        # P0-A — `agendar` PRECISA DE UMA TRANSAÇÃO QUE ELE POSSUA (26/08/2026)
        # ----------------------------------------------------------------------------------
        # Era `fluxo.agendar(db, ...)`, com a sessão DO WEBHOOK, de dentro do
        # `async with db.begin_nested()` de `main.py`. E `agendar._marcar` faz `db.commit()`
        # a cada passo — de propósito, e a razão está no docstring dele: sem o commit por
        # passo, um processo morto no meio do fluxo perderia a linha inteira, e a FAXINA
        # nunca saberia que existe um box nosso pendurado na agenda real da consultora.
        #
        # O commit é certo. O que estava errado era a transação que ele recebia: commitar
        # fecha o savepoint do webhook, e a instrução seguinte levanta
        # `InvalidRequestError: Can't operate on closed transaction inside context manager`.
        # Aí o `_fallback` morre no MESMO erro e o savepoint reverte até a etapa
        # `transferido_humano` que ele acabou de escrever.
        #
        # MEDIDO em 25/08 com a Fabiana (5517997379129): 3 mensagens, 3 exceções, 3
        # rollbacks, ZERO notificações, ZERO mensagens. E não era bug raro — era bug de
        # 100% dos agendamentos feitos pelo agente; teve uma vítima só porque só uma pessoa
        # chegou até aqui.
        #
        # A SESSÃO PRÓPRIA é a opção que NÃO TOCA no `_marcar`: o caminho da LP — que é o de
        # maior volume e o que traz dinheiro — continua byte por byte o que era, e o agente
        # passa a rodar o mesmo fluxo com a mesma durabilidade por passo. As alternativas
        # custavam mais: tornar o commit condicional apagaria a durabilidade justo no
        # caminho do agente (box órfão INVISÍVEL para a faxina), e enfileirar no scheduler
        # poria o lead esperando até 60s logo depois de escolher o horário.
        #
        # ABERTA SÓ AQUI, e não no começo do turno: o turno já segura uma conexão do webhook
        # durante `llm.conversar` (3–5s), e abrir a segunda cedo dobraria a retenção num
        # pool que acabou de ser dimensionado (P1-A). Ela vive o tempo do agendamento e
        # fecha antes de qualquer outra coisa acontecer no turno.
        #
        # `read committed` é o que faz isto funcionar: o `_reuniao()` logo abaixo roda na
        # sessão do webhook — cuja transação começou ANTES — e ainda assim enxerga a linha
        # que esta sessão commitou. Conferido em produção
        # (`default_transaction_isolation = read committed`).
        from app.database import async_session
        async with async_session() as db_agendamento:
            r = await fluxo.agendar(
                db_agendamento, nome=nome, email=None,
                telefone=estado.contact_wa_id, slot_id=slot_id,
                # S5-1: era `origem=None`, e None quer dizer "use o padrão do .env" —
                # `PosMulheridades` para TODA reunião do agente. Ver
                # `_origem_do_agendamento`: ela devolve o sub_source real do lead quando ele
                # está na allowlist, e None (com log) quando não está, para que um cadastro
                # incompleto nunca custe a reunião.
                origem=origem,
                # SEMPRE com lead_id: é o que impede a pessoa de virar um segundo lead no
                # funil.
                lead_id=estado.exact_lead_id,
                # S5-1: era `extras=None`. O formulário da LP (profissão, faixa de
                # investimento, "como conheceu") existe na linha `lead_criado` do mesmo lead
                # e virava NULL aqui — a linha do agendamento REAL ficava sem o dado que a
                # tentativa anterior tinha. Com `lead_externo=True` o `LeadsAdd` é pulado e
                # os extras não vão para a Exact (`agendar.py:402-408`); eles ficam na nossa
                # tabela, que é justamente onde o relatório os lê.
                extras=extras or None, origem_ip=None)
    except Exception as e:
        await _fallback(estado, f"agendamento falhou ({type(e).__name__}: {e})", db)
        return

    estado.agendamento_id = r.agendamento_id
    reuniao = await _reuniao(estado, db)
    # A reunião JÁ EXISTE na Exact neste ponto. Se a confirmação não sai, o estado ainda
    # tem de fechar — senão o agente continua "escutando" um lead cuja reunião está marcada.
    await _falar(estado, resposta["mensagem"], db)
    if estado.etapa != ETAPA_Q_TRANSFERIDO:
        await _concluir(estado, reuniao, db)


async def _concluir(estado: NatQualificacaoState, reuniao, db: AsyncSession, *,
                    confirmar: bool = False) -> None:
    """Missão cumprida: etapa `concluido` e lembrete agendado.

    ------------------------------------------------------------------------------------
    `confirmar` — A PROMESSA QUE O AGENTE FAZIA E NÃO CUMPRIA
    ------------------------------------------------------------------------------------
    A MISSAO de `aguardando_motivacao` manda, sem condição: "Termine dizendo que vai ver os
    horários disponíveis". Ela não pode ser condicional — o modelo não sabe se a pessoa já
    tem reunião, e essa é justamente a informação que só o código tem.

    A bifurcação em `_avancar` tem dois ramos e, até 26/08, só um falava depois:

        sem reunião -> _ofertar_agenda -> manda os horários          ✅
        com reunião -> _concluir       -> CALAVA                     ❌

    MEDIDO em 26/08 09h02 com a Evelyn (`nat_abertura_agendado`, reunião 205 já marcada):

        09:02:01 agente: "...Vou ver os horários disponíveis para a sua reunião com a
                          Victória Amorim e te retorno em seguida."
        09:02:14 ela:    "Obrigada 😃"
        (nada, nunca)

    E o silêncio era definitivo: `concluido` está fora de ETAPAS_QUALIFICACAO_ATIVAS, então
    o "Obrigada" seguinte já nem foi escutado. Não é um caso de borda — é TODO lead que
    chega com reunião marcada, a faixa inteira da abertura T1.

    O fecho é determinístico e não passa pelo LLM: ele afirma data, hora e consultora, que
    são fatos do banco. Uma promessa quebrada não se conserta com criatividade.

    Só `_avancar` pede `confirmar=True`. Vindo de `_agendar`, a fala do modelo ACABOU de
    confirmar o horário escolhido — um segundo texto aqui seria a mesma notícia duas vezes.

    ------------------------------------------------------------------------------------
    POR QUE A CONFIRMAÇÃO NÃO PASSA POR `_falar` — o bug de 26/08, e a forma escolhida
    ------------------------------------------------------------------------------------
    Este bloco nasceu no P0-D (`defa955`) chamando `_enviar`, que devolve `(saiu, motivo)` e
    não faz nada com a recusa. Seis minutos depois o P0-B (`b25d233`) trocou por `_falar` no
    varrimento "recusa nunca mais é silêncio" — certo em todos os outros pontos do módulo,
    e AQUI um lead perdido:

        estado.etapa = 'concluido'  ->  db.flush()
        _falar -> qualificacao_pode_atuar RELÊ o estado -> vê 'concluido' -> recusa
               -> _fallback -> etapa='transferido_humano' + TEXTO_FALLBACK + notificação

    A pessoa acabava de contar a trajetória inteira e recebia "Deixa eu te conectar com uma
    pessoa da nossa equipe" no lugar da data da própria reunião. MEDIDO em 26/08: 4 de 4
    (100%) dos leads T1 que completaram o roteiro depois das 13:32 UTC — Marina (207),
    Mikaelle (216), Amanda (220) e Natália (222) —, e 4 dos 6 avisos `agente_transferiu`
    que chegaram à gestão no período eram este falso alarme.

    DUAS FORMAS EXISTIAM. A escolhida é a segunda:

    (a) CONFIRMAR ANTES de gravar `concluido`, com a etapa ainda ativa. Recusada por três
        razões, e a segunda é decisiva:
          1. exigiria uma terceira cópia do idioma `if not await _falar(...) and
             estado.etapa == ETAPA_Q_TRANSFERIDO: return` só para preservar a invariante;
          2. uma confirmação que não sai levaria o estado a `transferido_humano` pelo
             `_fallback` — que é EXATAMENTE o desfecho que este fix existe para remover. A
             reunião já está de pé na Exact; falhar em anunciá-la não pode desfazer a
             conclusão. `_agendar` já diz a mesma regra com outras palavras;
          3. no ramo do teto (`_falar` devolve False sem transferir) a etapa viraria
             `concluido` com um `responder_pendente` vivo — e o bug reapareceria 10 min
             depois, só que mais raro e mais difícil de achar.

    (b) GRAVAR a etapa e enviar com um guard que NÃO exige etapa ativa. É o que
        `lembrete_reuniao` e `concluir_por_agendamento_externo` já fazem, pelo mesmo motivo.

    O GUARD É `guard_de_despedida`, NÃO `guard_de_abertura`. Os dois dispensam etapa ativa,
    mas `guard_de_abertura` carrega o TETO POR HORA, e o P1-B já decidiu essa questão: o
    teto é para business-initiated (abertura), não para a resposta a quem acabou de
    escrever. O lembrete fica com `guard_de_abertura` de propósito — ele É business-initiated
    e sai dias depois. Esta confirmação é a última fala de um turno que o lead começou.

    RECUSA AQUI NÃO É `_fallback` — E NÃO É SILÊNCIO. Sobrou pouco que possa recusar
    (`guard_de_despedida` checa só a chave geral), e o que sobra significa "o agente está
    desligado" ou "a Meta não aceitou". Nenhum desses casos justifica desfazer uma conclusão
    correta nem acordar a gestão: a reunião existe, o SDR a vê na Exact e o lembrete T-30
    continua agendado logo abaixo. Fica o `print`, que a partir do item 2 deste sprint
    aparece de fato no journald. Mesmo tratamento (e mesmo texto) de
    `concluir_por_agendamento_externo`.

    A fala adiada eventualmente pendente não precisa ser cancelada aqui: o handler
    `responder_pendente` já recusa agir sobre etapa fora de ETAPAS_QUALIFICACAO_ATIVAS com
    `AcaoIgnorada` — ele NÃO cai em `_fallback` nesse caminho.
    """
    estado.etapa = ETAPA_Q_CONCLUIDO
    await db.flush()
    # S6-4: reunião marcada — não há pergunta pendente para o follow retomar.
    await _cancelar_follow(estado.contact_wa_id, "a reunião foi marcada", db)

    if confirmar and reuniao is not None:
        from app.agendamento import consultoras as equipe
        quem = equipe.nome_de(reuniao.sales_rep_email or "")
        enviado, motivo = await enviar_nat(
            estado.contact_wa_id, guard.ETAPA_CONVERSA, db,
            guard=guard.guard_de_despedida,
            corpo_livre=(
                f"Na verdade você já tem horário reservado: "
                f"{reuniao.slot_inicio.strftime('%d/%m às %H:%M')}"
                f"{f' com {quem}' if quem else ''}. "
                f"Te espero lá! Se precisar remarcar, é só me dizer. 🙂"))
        if not enviado:
            print(f"⚠️  Agente: confirmação de reunião NÃO saiu para "
                  f"{estado.contact_wa_id} ({motivo}) — a reunião {reuniao.id} está de pé "
                  f"e o estado segue em '{ETAPA_Q_CONCLUIDO}'")

    if reuniao is not None:
        await agendar_lembrete(reuniao, db)
    print(f"✅ Agente concluiu {estado.contact_wa_id}"
          f"{f' (reunião {reuniao.id})' if reuniao is not None else ''}")


async def concluir_por_agendamento_externo(contact_wa_id: str, reuniao,
                                           db: AsyncSession) -> bool:
    """A pessoa agendou pela PÁGINA do token. Fecha o estado e confirma no chat.

    Devolve True se o agente falou. Nunca levanta: o agendamento já existe na Exact quando
    chegamos aqui, e falhar em confirmar não pode desfazer uma reunião real.

    ------------------------------------------------------------------------------------
    POR QUE NÃO DEU PARA REUSAR `_concluir`
    ------------------------------------------------------------------------------------
    `_concluir` fecha o estado e agenda o lembrete, mas NÃO manda mensagem — no fluxo dele a
    confirmação é a própria resposta do LLM naquele turno da conversa. Aqui não existe turno:
    o booking aconteceu numa aba do navegador, e do lado do WhatsApp o silêncio seria a
    última coisa que a pessoa veria depois de clicar no link que a Nat mandou.

    O lembrete T-30 NÃO é agendado aqui: `agendamento/agendar.py::_gatilho_do_agente` já o
    enfileira para todo agendamento que chega a `PASSO_AGENDADO`, venha de onde vier. Chamar
    de novo seria inofensivo (`nat_scheduler.agendar` cancela o pendente antes de inserir),
    mas duas fontes para a mesma ação é o tipo de coisa que diverge quando uma delas muda.

    ------------------------------------------------------------------------------------
    O TEXTO SAI DO BANCO, NUNCA DO MODELO
    ------------------------------------------------------------------------------------
    Data, hora e consultora vêm da linha de `agendamentos` que acabou de ser gravada. Um LLM
    escrevendo "sua reunião é quinta às 15h" a partir do contexto erraria em silêncio, e o
    erro só apareceria quando ninguém aparecesse na reunião.

    O guard é `guard_de_abertura`, não `qualificacao_pode_atuar`: a etapa já é `concluido`,
    que está fora das ativas, e o guard de envio recusaria a própria confirmação. Mesmo
    motivo e mesma solução de `_fallback`.
    """
    try:
        estado = await estado_de(contact_wa_id, db)
        if estado is None:
            return False
        if estado.etapa == ETAPA_Q_CONCLUIDO and estado.agendamento_id == reuniao.id:
            return False                      # reentrega: já fechamos este mesmo booking

        estado.etapa = ETAPA_Q_CONCLUIDO
        estado.agendamento_id = reuniao.id
        await db.flush()
        # S6-4: marcou sozinho pela página — mesmo caso do `_concluir`.
        await _cancelar_follow(estado.contact_wa_id, "a reunião foi marcada na página", db)

        from app.agendamento import consultoras as equipe
        consultora = equipe.nome_de(reuniao.sales_rep_email or "")
        quando = reuniao.slot_inicio
        texto = (f"Prontinho! ✅ Sua conversa está marcada para "
                 f"{quando:%d/%m} às {quando:%H:%M} (horário de Brasília)"
                 + (f", com {consultora}" if consultora else "") + ".\n\n"
                 "Vou te lembrar 30 minutos antes. Se precisar remarcar, é só me falar "
                 "por aqui.")
        enviado = await send_nat_message(estado.contact_wa_id, guard.ETAPA_CONVERSA, db,
                                         guard=guard.guard_de_abertura, corpo_livre=texto)
        print(f"✅ Agente: {estado.contact_wa_id} agendou pela página "
              f"(reunião {reuniao.id}, {quando:%d/%m %H:%M})"
              f"{'' if enviado else ' — confirmação NÃO saiu'}")
        return enviado
    except Exception as e:
        print(f"⚠️  Agente: falha ao confirmar no chat o agendamento externo de "
              f"{contact_wa_id} ({type(e).__name__}: {e}). A reunião está de pé.")
        return False


# ==========================================================================================
# BLOCO F — LEMBRETE T-30MIN
# ==========================================================================================

async def agendar_lembrete(reuniao, db: AsyncSession) -> bool:
    """Agenda o lembrete para `slot_inicio - 30min`. Idempotente por (kind, contato).

    Devolve True só quando insere. Mesmo motivo de `agendar_abertura`: as saídas silenciosas
    (sem reunião, reunião no passado, sem telefone) não deixam nada para o chamador commitar.

    Chamada dos DOIS nascimentos possíveis de uma reunião: o agente marcando (`_concluir`) e
    o obrigado.html marcando sozinho (`agendamento/agendar.py`). `nat_scheduler.agendar`
    cancela o pendente anterior antes de inserir, então chamar duas vezes reagenda em vez de
    duplicar — e o índice único parcial do banco é a rede da mesma regra.

    Reunião no passado não agenda nada: um `run_at` vencido dispararia no ciclo seguinte e
    mandaria "sua reunião é hoje às X" depois de X.
    """
    from app.exact_spotter import format_phone
    from app.nat_scheduler import agendar as agendar_acao

    if reuniao is None or not reuniao.slot_inicio:
        return False
    quando = reuniao.slot_inicio - ANTECEDENCIA_LEMBRETE
    if quando <= _agora_sp():
        print(f"↩️  Agente: reunião {reuniao.id} é cedo demais para lembrete "
              f"({reuniao.slot_inicio:%d/%m %H:%M})")
        return False
    wa_id = format_phone(reuniao.telefone or "")
    if not wa_id:
        return False
    await agendar_acao(KIND_LEMBRETE_REUNIAO, wa_id, quando,
                       {"agendamento_id": reuniao.id}, db)
    return True


@registrar_handler("lembrete_reuniao")
async def lembrete_reuniao(acao: dict, db: AsyncSession) -> None:
    """T-30min. RELÊ tudo: entre agendar e executar passaram horas ou dias.

    NENHUMA SAÍDA DAQUI É SILENCIOSA (Risco 3, S4-1). As quatro saídas de "nada a fazer"
    — sem `agendamento_id`, reunião desmarcada, reunião que já começou, consultora que sumiu
    — eram `return` mudo e viravam `executado` com motivo NULL, a mesma marca de quem enviou
    o lembrete. Agora são `AcaoIgnorada`: `skipped` com o motivo GRAVADO, e "o lembrete saiu"
    volta a significar uma coisa só.
    """
    from app.agendamento import consultoras as equipe

    payload = json.loads(acao.get("payload") or "{}")
    wa_id = acao["contact_wa_id"]
    reuniao_id = payload.get("agendamento_id")
    if not reuniao_id:
        raise AcaoIgnorada("sem agendamento_id no payload")

    reuniao = (await db.execute(select(Agendamento).where(
        Agendamento.id == reuniao_id))).scalar_one_or_none()
    if reuniao is None or reuniao.passo != PASSO_AGENDADO:
        raise AcaoIgnorada(f"reunião {reuniao_id} não está mais agendada "
                           f"(passo={reuniao.passo if reuniao else 'inexistente'})")
    if reuniao.slot_inicio <= _agora_sp():
        raise AcaoIgnorada(f"reunião {reuniao_id} já começou "
                           f"({reuniao.slot_inicio:%d/%m %H:%M}) — não envia lembrete atrasado")

    consultora = equipe.nome_de(reuniao.sales_rep_email or "")
    if not consultora:
        raise AcaoIgnorada(f"reunião {reuniao_id} sem consultora resolvível "
                           f"(sales_rep_email={reuniao.sales_rep_email!r})")

    nome = primeiro_nome(reuniao.nome or "")
    hora = reuniao.slot_inicio.strftime("%H:%M")
    parametros = [nome, hora, consultora]
    corpo = await _corpo_do_template(guard.ETAPA_LEMBRETE_REUNIAO, parametros, db)

    # `guard_de_abertura` e não `qualificacao_pode_atuar`: nesta altura a etapa é `concluido`,
    # em que o agente cala de propósito. O lembrete é a exceção combinada — e continua
    # sujeito à chave geral e ao teto por hora.
    #
    # ------------------------------------------------------------------------------------
    # S5-3 — O ENVIO TAMBÉM PRESTA CONTAS (28/08/2026)
    # ------------------------------------------------------------------------------------
    # Era `await send_nat_message(...)` com o `bool` DESCARTADO. As quatro pré-checagens
    # acima já viraram `AcaoIgnorada` no S4-1 — e a docstring desta função comemora
    # exatamente isso — mas o envio, o único passo que de fato manda a mensagem, continuava
    # mudo: recusa dele virava `executado` com motivo NULL, a mesma marca de quem enviou.
    #
    # MEDIDO em 27-28/08: 15 lembretes `executado`, 13 enviados. Os 2 fantasmas:
    #   ação 226, Mikaelle, 27/08 09:15 — `teto de envios/hora estourado (22/20)`
    #   ação  64, Josiqueila, 28/08 08:30 — `contato não existe no banco`
    # A Mikaelle tinha escrito "gostaria de confirmar o horário" ÀS 09:13. A reunião era às
    # 09:45. Ninguém soube que o lembrete não saiu.
    #
    # O TETO ADIA, NÃO DESCARTA — e aqui isso é mais do que simetria com a abertura. O teto
    # é contagem MÓVEL de 1h: em 10 minutos ele passa sozinho. No caso da Mikaelle, +10 min
    # ainda eram 20 minutos antes da reunião: o lembrete teria saído. Descartar por
    # congestionamento seria perder a mensagem justamente na hora em que ela vale mais.
    #
    # SÓ QUE ADIAR TEM PRAZO. `run_at` empurrado para depois do início da reunião mandaria
    # "sua reunião é hoje às X" depois de X — é a mesma regra da pré-checagem lá em cima, e
    # por isso a decisão é a mesma: passou da hora, é `AcaoIgnorada`.
    enviado, motivo_envio = await enviar_nat(wa_id, guard.ETAPA_LEMBRETE_REUNIAO, db,
                                             guard=guard.guard_de_abertura,
                                             parametros=parametros, corpo_livre=corpo)
    if not enviado:
        if guard.e_teto(motivo_envio):
            proxima = _agora_sp() + ATRASO_POR_TETO
            if proxima < reuniao.slot_inicio:
                raise AcaoAdiada(proxima, f"lembrete não saiu: {motivo_envio}")
            raise AcaoIgnorada(f"lembrete não saiu: {motivo_envio} — e readiar passaria do "
                               f"início da reunião ({reuniao.slot_inicio:%d/%m %H:%M})")
        raise AcaoIgnorada(f"lembrete não saiu: {motivo_envio}")


# ==========================================================================================
# ITEM 3 — ENCERRAMENTO POR INATIVIDADE
# ==========================================================================================
#
# `ETAPA_Q_ENCERRADO` existia no CHECK e nas constantes e NENHUM código a atribuía — o mesmo
# defeito que o ESTADO_NAT_20260809 apontou no fluxo velho, onde `sem_contato` e `encerrado`
# eram constantes mortas. Aqui ela ganha um caminho.
#
# O QUE MUDA QUANDO UM LEAD É ENCERRADO
#   * `encerrado` está FORA de ETAPAS_QUALIFICACAO_ATIVAS: o agente deixa de ser dono do
#     inbound (precedência do webhook) e deixa de poder enviar (qualificacao_pode_atuar);
#   * se o lead responder DEPOIS, `processar_texto` devolve False e a mensagem segue para o
#     caminho de sempre — o fluxo humano. O agente NÃO reabre a conversa sozinho: ele já
#     desistiu uma vez, e reabrir com base numa resposta tardia faria a pessoa receber uma
#     pergunta de três dias atrás como se nada tivesse acontecido;
#   * o lead vira candidato limpo à régua de follow-up, quando ela existir.


async def _agendar_encerramento(estado: NatQualificacaoState, db: AsyncSession) -> None:
    """(Re)agenda o encerramento por inatividade. Nunca levanta — é higiene, não fluxo."""
    try:
        from app.nat_scheduler import agendar as agendar_acao
        await agendar_acao(KIND_ENCERRAR_INATIVO, estado.contact_wa_id,
                           _agora_sp() + INATIVIDADE_ENCERRA, {}, db)
    except Exception as e:
        print(f"⚠️  Agente: encerramento não agendado para {estado.contact_wa_id} "
              f"({type(e).__name__}: {e})")


async def _agendar_follow(estado: NatQualificacaoState, db: AsyncSession) -> None:
    """(Re)agenda o follow de 20h. Nunca levanta — é higiene, não fluxo.

    AGENDA NA MESMA TRANSAÇÃO DA PERGUNTA, e é por isso que fica colado no
    `_agendar_encerramento`: os dois pontos de chamada são os mesmos dois — a abertura
    (`iniciar_qualificacao`, depois do envio confirmado) e cada inbound (`processar_texto`).
    Um turno que estoura reverte os dois juntos, e é o comportamento certo: se a pergunta não
    aconteceu, o follow àquela pergunta também não deve existir.

    O AGENDAMENTO É INCONDICIONAL — não olha `follow_enabled`. Quem decide é o HANDLER, na
    hora de executar. A diferença importa: com a decisão aqui, ligar a flag só começaria a
    valer para conversas NOVAS, e as que já estivessem esperando ficariam sem follow para
    sempre. Com a decisão lá, ligar a flag alcança quem já está na fila. O custo é uma linha
    `pendente` por conversa ativa, que é o que a tabela já carrega para o encerramento.

    IDEMPOTÊNCIA POR CONSTRAINT, e ela já existe: `agendar` cancela o pendente do mesmo
    (kind, contato) antes de inserir, e `uq_nat_sched_pendente_por_contato` é a rede da mesma
    regra no banco. Dois inbounds seguidos reagendam UM follow, não acumulam dois. Era este o
    risco que adiou o Sprint D, e ele estava resolvido antes de a sprint começar.
    """
    try:
        from app.nat_scheduler import agendar as agendar_acao
        await agendar_acao(KIND_FOLLOW_20H, estado.contact_wa_id,
                           _agora_sp() + FOLLOW_APOS, {}, db)
    except Exception as e:
        print(f"⚠️  Agente: follow não agendado para {estado.contact_wa_id} "
              f"({type(e).__name__}: {e})")


async def _cancelar_follow(contact_wa_id: str, porque: str, db: AsyncSession) -> None:
    """A conversa saiu das etapas ativas: o follow não tem mais o que perguntar.

    CINCO saídas chamam isto, e são as cinco por onde uma conversa deixa de ser do agente:
    `silenciar` (o SDR assumiu), `_concluir` (reunião marcada), `_fallback` (transferida) e
    `encerrar_inativo` (72h). A quinta é o inbound, e essa não aparece como chamada: em
    `processar_texto` o `_agendar_follow` REAGENDA, e `agendar` cancela antes de inserir.

    Cancelar não é a única defesa, e não deve ser: o handler relê o estado e recusa sozinho
    se a etapa já não for ativa. Um cancelamento esquecido vira `skipped` com motivo, nunca
    uma mensagem indevida. Isto aqui é higiene da FILA — para `nat_scheduled_actions` não
    virar um cemitério de pendentes que nunca vão rodar.

    Nunca levanta, pelo mesmo motivo de sempre: higiene não derruba fluxo.
    """
    try:
        from app.nat_scheduler import cancelar as cancelar_acao
        quantos = await cancelar_acao(KIND_FOLLOW_20H, contact_wa_id, db)
        if quantos:
            print(f"🚫 Agente: follow cancelado para {contact_wa_id} — {porque}")
    except Exception as e:
        print(f"⚠️  Agente: follow não cancelado para {contact_wa_id} "
              f"({type(e).__name__}: {e})")


@registrar_handler("responder_pendente")
async def responder_pendente(acao: dict, db: AsyncSession) -> None:
    """A fala que o TETO por hora adiou. Tenta de novo; adia outra vez se ainda não couber.

    Existe pelo mesmo motivo que `AcaoAdiada` existe na abertura: o teto é contagem MÓVEL de
    1h, então ele passa sozinho — e recusar por causa dele é perder o lead por
    congestionamento, não por regra de negócio.

    O ESTADO É RELIDO, nunca vem do payload: entre agendar e executar passam 10 minutos, e
    nesse intervalo a pessoa pode ter escrito de novo (a etapa andou), um humano pode ter
    assumido, ou o encerramento por inatividade pode ter corrido. Só o texto vem do payload,
    porque é a única coisa que o banco não sabe reconstruir.
    """
    wa_id = acao["contact_wa_id"]
    texto = (json.loads(acao.get("payload") or "{}")).get("texto") or ""
    if not texto.strip():
        raise AcaoIgnorada("sem texto para reenviar")

    estado = await estado_de(wa_id, db)
    if estado is None or estado.etapa not in ETAPAS_QUALIFICACAO_ATIVAS:
        # Não é falha: humano assumiu, lead concluiu ou o silêncio encerrou. Falar agora
        # seria o agente reaparecendo numa conversa que já não é dele.
        raise AcaoIgnorada(f"etapa não é mais ativa "
                           f"({estado.etapa if estado else 'sem estado'})")

    saiu, motivo = await _enviar(estado, texto, db)
    if saiu:
        print(f"⏳→✅ Agente: fala adiada entregue a {wa_id}")
        return
    if guard.e_teto(motivo):
        raise AcaoAdiada(_agora_sp() + ATRASO_POR_TETO, motivo)
    # Não é mais o teto: virou recusa definitiva enquanto esperávamos. Fecha com humano em
    # vez de tentar para sempre.
    await _fallback(estado, f"envio recusado ao reenviar fala adiada: {motivo}", db)


async def _armar_vigia(estado: NatQualificacaoState, db: AsyncSession) -> None:
    """(Re)arma o vigia de resposta. Nunca levanta — vigia que derruba turno é pior que nada.

    ------------------------------------------------------------------------------------
    A FRONTEIRA DE COBERTURA — quem cobre o quê, dito na cara
    ------------------------------------------------------------------------------------
    Isto roda DENTRO do savepoint do webhook (`main.py`, `async with db.begin_nested()`),
    igual ao `_agendar_encerramento`. Consequência: um turno que ESTOURA reverte este INSERT
    junto. Não é descuido, é divisão de trabalho, e cada classe tem um dono:

        turno termina "com sucesso" e não fala  ->  o savepoint COMMITA, o vigia sobrevive
                                                    e dispara.  ESTA É A CLASSE-ALVO — é a
                                                    falha de contrato de 26/08 10:11, que
                                                    segue sem nome, e qualquer outra ainda
                                                    desconhecida com a mesma assinatura.
        turno ESTOURA no meio                  ->  rollback leva o vigia junto, e não faz
                                                    falta: a rede do P0-C
                                                    (`_rede_de_ultima_instancia`) já notifica
                                                    o MESMO GESTOR_USER_ID, em sessão nova,
                                                    com traceback, e ainda se despede do lead.
        webhook morre ANTES do roteamento      ->  fora de alcance de qualquer detector que
                                                    viva no banco: nada chegou a ser escrito,
                                                    nem a Message do inbound. É o caso do
                                                    pool esgotado batendo em `main.py:370`,
                                                    e quem o cobre é o P1-A, não este vigia.

    Armar em sessão própria cobriria também a segunda linha — ao custo de uma conexão a mais
    POR MENSAGEM DE LEAD, num pool dimensionado para a retenção de uma só, e para duplicar um
    aviso que o P0-C já manda. Não vale o preço.
    """
    try:
        from app.nat_scheduler import agendar as agendar_acao
        await agendar_acao(KIND_VIGIAR_RESPOSTA, estado.contact_wa_id,
                           _agora_sp() + PRAZO_VIGIA, {"etapa": estado.etapa}, db)
    except Exception as e:
        print(f"⚠️  Agente: vigia não armado para {estado.contact_wa_id} "
              f"({type(e).__name__}: {e})")


async def _ultimo_inbound(contact_wa_id: str, db: AsyncSession):
    """Quando o lead falou pela última vez — nas DUAS grafias do telefone dele.

    Mesma tolerância ao 9º dígito de `estado_de` e `janela_aberta`: o agente envia para 13
    dígitos e o WhatsApp entrega o inbound com 12 em 59% das threads. Um vigia estrito não
    veria a mensagem do próprio lead que ele está vigiando e calaria — repetindo, dentro do
    detector de silêncio, exatamente o bug que ele existe para detectar.
    """
    vs = variantes_wa_id(contact_wa_id) or (contact_wa_id,)
    res = await db.execute(
        select(Message.timestamp)
        .where(Message.contact_wa_id.in_(vs), Message.direction == "inbound")
        .order_by(Message.timestamp.desc()).limit(1))
    return res.scalar_one_or_none()


async def _fala_adiada_pendente(contact_wa_id: str, db: AsyncSession) -> bool:
    """Existe fala adiada pelo teto esperando a vez deste contato? (P0-B)"""
    vs = variantes_wa_id(contact_wa_id) or (contact_wa_id,)
    res = await db.execute(
        select(func.count()).select_from(NatScheduledAction).where(
            NatScheduledAction.kind == KIND_RESPONDER_PENDENTE,
            NatScheduledAction.contact_wa_id.in_(vs),
            NatScheduledAction.status == ACAO_PENDENTE))
    return bool(res.scalar() or 0)


@registrar_handler("vigiar_resposta")
async def vigiar_resposta(acao: dict, db: AsyncSession) -> None:
    """O lead escreveu e o agente não respondeu. Avisa a GESTÃO. NUNCA fala com o lead.

    ------------------------------------------------------------------------------------
    POR QUE UM SINAL NOVO, E NÃO MAIS UM `window_*`
    ------------------------------------------------------------------------------------
    O alerta antigo JÁ EXISTIA e JÁ DISPAROU para os cinco casos mortos de 24–26/08: 27+26+
    25+9 notificações, e `is_read=false` em 100% delas. Ele falha em três eixos ao mesmo
    tempo — vai para o SDR dono (que não pode consertar um agente), o título "Lead
    aguardando há 1h" é indistinguível de um lead esperando um humano, e por isso ninguém
    lê. Este aqui vai para o GESTOR_USER_ID e diz AGENTE MUDO: é falha de sistema.

    RELÊ TUDO, nunca confia no payload: entre armar e vencer passam 10 minutos, e nesse
    intervalo o agente pode ter falado, um humano pode ter assumido, o lead pode ter
    concluído. O payload guarda só a etapa de quando foi armado, e serve para o corpo da
    notificação mostrar se ela mudou.

    SAÍDAS, e todas com motivo — nenhuma é silenciosa (Risco 3):
        AcaoIgnorada -> `skipped` com motivo na linha. Não é falha: é "não há o que vigiar".
        AcaoAdiada   -> volta a `pendente` com motivo gravado e run_at empurrado, sem gastar
                        tentativa. É a supressão pela fala adiada.
        notificação  -> `executado`.
    """
    wa_id = acao["contact_wa_id"]
    etapa_de_quando_armou = (json.loads(acao.get("payload") or "{}")).get("etapa")

    estado = await estado_de(wa_id, db)
    if estado is None or estado.etapa not in ETAPAS_QUALIFICACAO_ATIVAS:
        # `transferido_humano`, `concluido` e `encerrado` estão fora de
        # ETAPAS_QUALIFICACAO_ATIVAS — a MESMA constante que governa escutar e falar. Nenhum
        # caso especial novo: se o agente não é mais dono da conversa, não há agente mudo.
        raise AcaoIgnorada(f"etapa não é mais ativa "
                           f"({estado.etapa if estado else 'sem estado'})")

    ultimo = await _ultimo_inbound(wa_id, db)
    if ultimo is None:
        raise AcaoIgnorada("nenhum inbound deste contato — nada a vigiar")

    espera = _agora_sp() - ultimo
    if espera < PRAZO_VIGIA:
        # O lead escreveu de novo depois de o vigia ser armado e o cancelamento não pegou
        # (ou o relógio andou). Adiar é mais barato e mais honesto que notificar cedo.
        raise AcaoAdiada(ultimo + PRAZO_VIGIA, f"lead escreveu há {espera} — ainda no prazo")

    # A SUPRESSÃO PELA FALA ADIADA — ver ESPERA_MAXIMA_COM_PENDENCIA. A régua é a espera do
    # lead, que só cresce; NÃO o `run_at` da pendência, que fica para sempre a menos de 10
    # min de distância e nunca deixaria o vigia disparar.
    if espera < ESPERA_MAXIMA_COM_PENDENCIA and await _fala_adiada_pendente(wa_id, db):
        raise AcaoAdiada(_agora_sp() + PRAZO_VIGIA,
                         f"fala adiada pelo teto ainda pendente e o lead espera há "
                         f"{int(espera.total_seconds() // 60)} min "
                         f"(teto: {int(ESPERA_MAXIMA_COM_PENDENCIA.total_seconds() // 60)})")

    minutos = int(espera.total_seconds() // 60)
    from app.nat_flow import telefone_legivel, usuario_existe
    destinatario = GESTOR_USER_ID
    if not await usuario_existe(destinatario, db):
        # Falha ALTA: sem destinatário, o detector de silêncio não pode virar silêncio.
        raise RuntimeError(f"GESTOR_USER_ID={GESTOR_USER_ID} não existe — "
                           f"agente mudo para {wa_id} não pôde ser reportado")

    mudou = (f" (era '{etapa_de_quando_armou}' quando o vigia foi armado)"
             if etapa_de_quando_armou and etapa_de_quando_armou != estado.etapa else "")
    db.add(Notification(
        user_id=destinatario, contact_wa_id=wa_id, type=TIPO_NOTIF_MUDO,
        ref=estado.ultimo_wa_message_id,
        title=f"AGENTE MUDO — lead esperando há {minutos} min",
        body=(f"{telefone_legivel(wa_id)} escreveu {ultimo:%d/%m %H:%M} e o agente não "
              f"respondeu. Etapa: '{estado.etapa}'{mudou}.")))
    print(f"🔇 AGENTE MUDO: {wa_id} em '{estado.etapa}' há {minutos} min — "
          f"gestão (user {destinatario}) avisada")


# ==========================================================================================
# S6-4 (SPRINT D) — O FOLLOW DE 20 HORAS
# ==========================================================================================
#
# O BURACO QUE ELE TAPA (RECON_FOLLOWS_HUMANO_IA_20260901, §4.5)
# ------------------------------------------------------------------------------------------
# O agente abriu 118 conversas na janela 24/08-01/09. Em 39 delas o lead calou e NINGUÉM
# nunca mais mandou nada. Dessas 39, 18 estavam paradas numa etapa ATIVA — 9 esperando o ano
# de conclusão, 4 a formação, 3 a motivação e 2 ESCOLHENDO O HORÁRIO DA REUNIÃO. Duas pessoas
# foram deixadas no ar apontando para um slot na agenda. O agente não tinha cadência de
# follow: ele abre, conversa enquanto o lead responde, e para.
#
# QUATRO RECUSAS, cada uma por um motivo diferente
# ------------------------------------------------------------------------------------------
#   flag desligada     o follow é decisão de produto, não efeito colateral de deploy
#   sem template       `{{n}}` vazio é #131008 e a Meta recusa a mensagem INTEIRA; recusar
#                      aqui troca um erro remoto e opaco por um motivo local e gravado
#   etapa não ativa    a conversa já não é do agente (humano assumiu, concluiu, encerrou)
#   alguém já tocou    é a regra que falta em TODO o resto do sistema. A NAT sabe quando o
#                      SDR digitou (é o `silenciar`), mas NÃO sabe quando uma CAMPANHA passou
#                      por cima de uma thread que já saiu das etapas ativas. Sem esta
#                      checagem, o lead receberia o disparo e, horas depois, o follow do
#                      agente — dois remetentes sobre a mesma coisa.
#
# NENHUMA SAÍDA É SILENCIOSA (Risco 3, S4-1): toda recusa é `AcaoIgnorada`, que vira
# `skipped` com o motivo GRAVADO na ação. `return` mudo viraria `executado` sem motivo,
# indistinguível de um follow que de fato saiu.
#
# FALHA DE REDE NÃO É RECUSA. Se a Meta não responde, a exceção SOBE e o scheduler retenta;
# só um `fetch_template_body` que devolve None limpo — template ausente ou não aprovado —
# vira `AcaoIgnorada`. Confundir os dois faria uma oscilação de rede queimar o follow do lead
# de vez, porque `skipped` é terminal.


async def _config_follow(db: AsyncSession) -> tuple[bool, str | None]:
    """(follow_enabled, follow_template). Falha fechada: sem config, desligado."""
    from app.models import NatConfig
    cfg = (await db.execute(select(NatConfig).where(NatConfig.id == 1))).scalar_one_or_none()
    if cfg is None:
        return False, None
    return bool(cfg.follow_enabled), (cfg.follow_template or "").strip() or None


async def _corpo_aprovado(nome_template: str, db: AsyncSession) -> str | None:
    """O corpo BRUTO (com os `{{n}}`) do template aprovado na Meta. None se não existe.

    Diferente de `_corpo_do_template`, que renderiza e engole erro: aqui o corpo bruto é
    necessário para CONTAR as variáveis antes de preencher, e a exceção precisa subir para o
    scheduler poder retentar (ver o bloco acima).
    """
    from app.models import Channel
    from app.whatsapp import fetch_template_body
    canal = (await db.execute(select(Channel).where(Channel.id == 1))).scalar_one_or_none()
    if canal is None:
        return None
    return await fetch_template_body(canal.waba_id, canal.whatsapp_token,
                                     nome_template, "pt_BR")


async def _alguem_falou_depois(contact_wa_id: str, desde, db: AsyncSession) -> bool:
    """Houve outbound de HUMANO para este contato desde `desde`?

    `nat_etapa IS NULL` é o que separa humano de agente, e é o mesmo critério do RECON: todo
    envio do agente passa por `nat_sender` e carimba a etapa; nada mais carimba.

    Por VARIANTES do telefone (`app/telefone.py`): 59% das threads chegam sem o 9º dígito, e
    com igualdade crua o follow não enxergaria o disparo que caiu na outra grafia.
    """
    n = (await db.execute(
        select(func.count()).select_from(Message)
        .where(Message.contact_wa_id.in_(variantes_wa_id(contact_wa_id)),
               Message.direction == "outbound",
               Message.nat_etapa.is_(None),
               Message.status != "failed",
               Message.timestamp >= desde))).scalar_one()
    return (n or 0) > 0


def _parametros_do_follow(corpo: str, nome: str, retomada: str) -> list | None:
    """Preenche os `{{n}}` do template do follow. None se não dá para preencher com verdade.

    O CONTRATO DO FOLLOW É `{{1}}` = nome e `{{2}}` = A PERGUNTA PENDENTE — e não o curso,
    como nos outros templates do agente. Ver o bloco de `RETOMADA_FOLLOW`.

    Sem variável nenhuma devolve `[]`, que é diferente de None: `[]` quer dizer "não há o que
    preencher e está tudo certo"; None quer dizer "há, e eu não sei com o quê".

    Acima de 2 devolve None em vez de inventar. Um `{{3}}` em branco é #131008 e a Meta
    recusa a mensagem inteira; preenchido com um chute, é o agente afirmando algo que não
    sabe — que é exatamente o defeito do `{{2}}` do `tentativa_contato` (S6-3). É também o
    que impede `follow_urgencia` (3 variáveis, uma delas o MÊS) de ser usado por engano.

    ESPAÇO EM BRANCO É COLAPSADO porque a Meta recusa parâmetro com quebra de linha ou
    tabulação (#132000/#131008, dependendo do caso) — e as retomadas nascem de literais
    quebrados em várias linhas no código.
    """
    def limpo(v: str) -> str:
        return " ".join((v or "").split())

    quantas = len(set(re.findall(r"\{\{\s*(\d+)\s*\}\}", corpo or "")))
    nome, retomada = limpo(nome), limpo(retomada)
    if quantas == 0:
        return []
    if quantas == 1:
        return [nome] if nome else None
    if quantas == 2:
        return [nome, retomada] if (nome and retomada) else None
    return None


@registrar_handler(KIND_FOLLOW_20H)
async def follow_20h(acao: dict, db: AsyncSession) -> None:
    """20h de silêncio do lead sobre a NOSSA pergunta → o agente retoma, uma vez.

    RELÊ TUDO, nunca confia no payload (vazio de propósito): entre agendar e executar passam
    20 horas, e nesse intervalo o lead pode ter respondido — o que REAGENDA esta ação —, um
    humano pode ter assumido, uma campanha pode ter passado por cima, ou a reunião pode ter
    sido marcada pela página.
    """
    from app.whatsapp import render_template_text

    wa_id = acao["contact_wa_id"]
    agora = _agora_sp()

    ligado, nome_template = await _config_follow(db)
    if not ligado:
        raise AcaoIgnorada("follow_enabled=false — o follow do agente está desligado")
    if not nome_template:
        raise AcaoIgnorada("nat_config.follow_template está vazio — o texto do follow ainda "
                           "não foi submetido à Meta")

    estado = await estado_de(wa_id, db)
    if estado is None:
        raise AcaoIgnorada("não tem estado — nada a retomar")
    if estado.etapa not in ETAPAS_QUALIFICACAO_ATIVAS:
        raise AcaoIgnorada(f"já está em '{estado.etapa}' — fora das etapas ativas")

    # O caminho normal é o inbound ter REAGENDADO esta ação; isto cobre a corrida em que o
    # lead responde entre o vencimento e a execução.
    ultimo = await _ultimo_inbound(wa_id, db)
    if ultimo is not None and ultimo.timestamp >= agora - FOLLOW_APOS:
        raise AcaoIgnorada("o lead falou dentro da janela — não há silêncio a retomar")

    if await _alguem_falou_depois(wa_id, agora - FOLLOW_JANELA_HUMANO, db):
        raise AcaoIgnorada("um humano (ou uma campanha) falou com este contato nas últimas "
                           "20h — o agente não entra por cima")

    corpo = await _corpo_aprovado(nome_template, db)
    if not corpo:
        raise AcaoIgnorada(f"template '{nome_template}' não está aprovado no WABA — nada "
                           "foi enviado")

    nome = await _nome(estado, db)
    # A frase que RETOMA a pergunta onde ela ficou. Sem retomada para a etapa, o follow não
    # sai: mandar "ainda tem interesse?" genérico faria o lead recomeçar do zero, e é o
    # oposto do que o follow existe para fazer.
    retomada = RETOMADA_FOLLOW.get(estado.etapa)
    if not retomada:
        raise AcaoIgnorada(f"não há retomada escrita para a etapa '{estado.etapa}' — o "
                           "follow não manda pergunta genérica")
    parametros = _parametros_do_follow(corpo, nome, retomada)
    if parametros is None:
        quantas = len(set(re.findall(r"\{\{\s*(\d+)\s*\}\}", corpo)))
        raise AcaoIgnorada(
            f"template '{nome_template}' tem {quantas} variável(is) e o agente não sabe "
            f"preenchê-las sem inventar. O contrato do follow é {{{{1}}}}=nome e "
            f"{{{{2}}}}=a pergunta pendente (nome={nome!r})")

    saiu, motivo = await enviar_nat(
        contact_wa_id=estado.contact_wa_id, etapa=nome_template, db=db,
        guard=guard.qualificacao_pode_atuar, parametros=parametros or None,
        corpo_livre=render_template_text(corpo, parametros) or corpo)
    if not saiu:
        # Teto por hora passa sozinho; qualquer outra recusa é definitiva.
        if guard.e_teto(motivo):
            raise AcaoAdiada(agora + ATRASO_POR_TETO, motivo)
        raise AcaoIgnorada(f"envio recusado: {motivo}")

    horas = FOLLOW_APOS.total_seconds() / 3600
    print(f"🔁 Agente fez follow de {horas:.0f}h em {wa_id} "
          f"(etapa '{estado.etapa}', template '{nome_template}')")


@registrar_handler("encerrar_inativo")
async def encerrar_inativo(acao: dict, db: AsyncSession) -> None:
    """72h de silêncio numa etapa ativa → `encerrado`.

    RELÊ o estado, nunca confia no payload: entre agendar e executar passam três dias, e
    nesse intervalo o lead pode ter respondido (o que reagenda esta ação), sido transferido,
    ou concluído com reunião marcada.

    NENHUMA SAÍDA DAQUI É SILENCIOSA (Risco 3, S4-1). As duas saídas de "nada a fazer" eram
    `return` mudo e viravam `executado` com motivo NULL — indistinguíveis de um encerramento
    real. Um lead transferido a um humano e um lead de fato encerrado produziam a MESMA linha
    na fila, e a régua de follow-up que vier a ler `encerrado` não teria como separá-los.
    Agora as duas são `AcaoIgnorada`: `skipped` com o motivo GRAVADO.

    NÃO envia mensagem nenhuma ao lead: quem parou de responder não precisa de um aviso de
    que parou.

    O MOTIVO GRAVADO diz QUEM calou (S4-2): `inatividade` quando falamos por último e o lead
    sumiu, `sem_resposta_do_agente` quando o lead falou por último e nós é que não voltamos.
    Ver o bloco OS DOIS MOTIVOS DE ENCERRAMENTO no topo do módulo.
    """
    wa_id = acao["contact_wa_id"]
    estado = await estado_de(wa_id, db)
    if estado is None:
        raise AcaoIgnorada("não tem estado — nada a encerrar")
    if estado.etapa not in ETAPAS_QUALIFICACAO_ATIVAS:
        raise AcaoIgnorada(f"já está em '{estado.etapa}' — fora das etapas ativas")

    # QUEM CALOU? Ver MOTIVO_SEM_RESPOSTA_AGENTE. A pergunta é a mesma da varredura por
    # estado, e quem a responde é ela — um critério, um lugar.
    from app.agente_parado import encalhada
    agora = _agora_sp()
    nos_calamos = await encalhada(wa_id, db, agora=agora) is not None

    estado.etapa = ETAPA_Q_ENCERRADO
    estado.encerrado_em = agora
    estado.encerrado_motivo = (MOTIVO_SEM_RESPOSTA_AGENTE if nos_calamos
                               else MOTIVO_INATIVIDADE)
    await db.flush()
    # S6-4: 72h sem resposta. Se um follow ainda estivesse pendente aqui, ele já não teria
    # etapa ativa para agir — mas deixá-lo na fila é sujeira, e a fila é lida por humanos.
    await _cancelar_follow(wa_id, "a conversa foi encerrada por inatividade", db)
    horas = INATIVIDADE_ENCERRA.total_seconds() / 3600
    if nos_calamos:
        print(f"🌑 Agente encerrou {wa_id} com motivo '{MOTIVO_SEM_RESPOSTA_AGENTE}' — "
              f"o lead falou por último e ficou {horas:.0f}h sem resposta NOSSA")
    else:
        print(f"🌑 Agente encerrou {wa_id} por inatividade ({horas:.0f}h sem resposta)")
