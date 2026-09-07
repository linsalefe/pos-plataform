"""O que o RD Station precisa receber, e como transformar uma linha nossa nisso.

Este módulo é PURO: mapa, normalização e uma chamada HTTP. Não conhece o banco, não decide
quando enviar e não guarda estado. Quem decide é `rd_outbox` (o que entra na fila) e
`rd_sender` (quando a fila drena). A separação é a mesma de `agendamento/origens.py` (regra)
e `agendamento/agendar.py` (fluxo), e existe pela mesma razão: a regra tem de ser testável
sem banco e sem rede.

------------------------------------------------------------------------------------------
POR QUE ESTA INTEGRAÇÃO EXISTE
------------------------------------------------------------------------------------------
Até 18/08/2026 a landing page usava o formulário do próprio RD Station, e era ele que
disparava a conversão que acorda os fluxos de automação de e-mail de cada pós. Naquele dia o
formulário nativo (`docs/form-nativo-snippet.html`) substituiu o do RD: o lead passou a ir
direto para o nosso backend e para a Exact, e o RD deixou de saber que a pessoa existe. Os
fluxos de e-mail das pós pararam de disparar — em silêncio, porque nada quebrou.

Medido no RECON de 07/09: **363 submissões com e-mail desde 18/08** que o RD nunca viu.

------------------------------------------------------------------------------------------
O MAPA NÃO É DERIVÁVEL DO NOME DO CURSO
------------------------------------------------------------------------------------------
`conversion_identifier` é a string LITERAL que o gatilho de cada fluxo escuta lá dentro. Ela
foi criada à mão, uma por formulário, e não segue regra:

    Pos Saude do Trabalhador  ->  formulario-pos-sm-trabalhador-7c1bffb18b   (hash no fim)
    PosMulheridades           ->  formulario-pos-mulheridades-2              (sufixo -2)
    Pos Direitos Humanos T4   ->  formulario-pos-sm-e-dh                     (nome comercial outro)

Inventar o identifier por slug do `sub_source` produziria strings que NENHUM fluxo escuta, e
o sintoma seria o pior possível: `201 Created` do RD, evento gravado, e nenhum e-mail saindo.
Por isso o mapa é dado de configuração, digitado a partir do que está no RD, e um `sub_source`
ausente do mapa vira `skipped` explícito em vez de um palpite.

------------------------------------------------------------------------------------------
ARQUIVO, E NÃO `.env` NEM TABELA
------------------------------------------------------------------------------------------
São 14 pares com espaço e acento na chave — um CSV em variável de ambiente seria hostil (ver
o aviso das aspas em `agendamento/origens.py:28-31`). E não vai para `course_aliases` pela
mesma lição de `migrate_agendamentos_subsource.py:26-27`: valor que vive em configuração não
deve exigir migração a cada curso novo.

O mecanismo é o de `agendamento/consultoras.py`: `RD_CONVERSOES_PATH` aponta o arquivo, e um
arquivo ausente ou inválido **não levanta** — devolve mapa vazio com log ❌. A consequência de
falhar aqui é `skipped/sem_mapa`, que é recuperável relendo a fila; a consequência de levantar
seria derrubar um agendamento real, que não é.

Sem cache: são 14 linhas lidas no máximo uma vez por submissão. Um cache com invalidação seria
mais código que o problema.
"""
import json
import os
import re

import httpx

# O endpoint de eventos de conversão da CDP do RD. `api_key` vai na query string — é o que a
# autenticação por API Key aceita nesta rota (a alternativa é OAuth, que é a Fase 2).
URL_CONVERSOES = "https://api.rd.services/platform/conversions"

# Mesmo teto de `agendamento/client.py:28`, e pela mesma razão: 15s é mais que o suficiente
# para uma API que responde em centenas de ms, e curto o bastante para o ciclo de 60s do
# drenador não empilhar chamadas penduradas.
TIMEOUT_PADRAO = 15.0

CAMINHO_PADRAO = "rd_conversoes.json"

# A tag que marca, dentro do RD, o contato que nasceu por esta integração. Serve para o
# marketing separar "veio do formulário nativo" de "veio de um formulário do RD" enquanto os
# dois convivem.
TAG_ORIGEM = "cenat-hub"

# Deliberadamente frouxo. Não é validação de RFC — é peneira para o que NÃO É e-mail e faria o
# RD recusar o payload inteiro: string vazia, "-", "nao tem", nome sem arroba. Um endereço
# malformado que passe daqui é recusado pelo RD com 4xx, que a fila registra como `falhou`
# com o corpo da resposta. Um endereço válido recusado aqui sumiria em silêncio — por isso a
# peneira erra para o lado de deixar passar.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ==========================================================================================
# O MAPA
# ==========================================================================================
def carregar_mapa() -> dict[str, str]:
    """`sub_source` em minúsculas -> `conversion_identifier` intacto. `{}` se não deu.

    A CHAVE É NORMALIZADA, O VALOR NÃO. Mesma regra de `origens.resolver`: a comparação é
    case-insensitive porque os `sub_source` reais misturam convenções (`PosMulheridades` e
    `posgenerot2` convivem na Exact), mas o valor tem de sair byte por byte como está no RD —
    um identifier em caixa diferente não casa com gatilho nenhum.

    NUNCA LEVANTA. Arquivo ausente, JSON inválido, JSON que não é objeto de strings: log ❌ e
    mapa vazio. Este módulo é chamado de dentro do fluxo de agendamento, e uma exceção aqui
    custaria a reunião de alguém para consertar um problema de configuração nosso.
    """
    caminho = os.getenv("RD_CONVERSOES_PATH") or CAMINHO_PADRAO
    try:
        with open(caminho, encoding="utf-8") as fh:
            dados = json.load(fh)
    except OSError as e:
        print(f"❌ rd: não consegui ler o mapa de conversões em {caminho} ({e}). "
              f"Nenhuma conversão será enfileirada até isto ser resolvido.")
        return {}
    except (json.JSONDecodeError, ValueError) as e:
        print(f"❌ rd: {caminho} não é JSON válido ({e}). Nenhuma conversão será enfileirada.")
        return {}

    if not isinstance(dados, dict) or not dados:
        print(f"❌ rd: {caminho} não é um objeto não-vazio. Nenhuma conversão será enfileirada.")
        return {}

    mapa: dict[str, str] = {}
    for chave, valor in dados.items():
        if not isinstance(chave, str) or not isinstance(valor, str) or not valor.strip():
            print(f"⚠️ rd: entrada inválida no mapa ({chave!r}: {valor!r}) — ignorada.")
            continue
        mapa[chave.strip().lower()] = valor.strip()
    return mapa


def identifier_para(sub_source: str | None) -> str | None:
    """O `conversion_identifier` desta origem, ou None quando ela não está no mapa.

    None NÃO é erro: é a resposta certa para um curso que ainda não tem fluxo no RD, e o
    chamador transforma isso em `skipped/sem_mapa`. Chutar um identifier seria pior — ver o
    cabeçalho do módulo.
    """
    if not sub_source or not sub_source.strip():
        return None
    return carregar_mapa().get(sub_source.strip().lower())


# ==========================================================================================
# NORMALIZAÇÃO — o banco de origem não normaliza nada (RECON, achados 3 e 4)
# ==========================================================================================
def normalizar_email(bruto: str | None) -> str | None:
    """`strip().lower()` e a peneira do `_EMAIL_RE`. None quando não é e-mail.

    NÃO EXISTE VALIDADOR DE E-MAIL NO SERVIDOR. `DadosLead` (agendamento/routes.py:97-110)
    valida `nome`, `telefone` e `extras`, e não `email` — o único `trim` do fluxo é o
    `.value.trim()` do JavaScript da landing page. A base está limpa por sorte, não por
    contrato: medido em 07/09, 1 das 389 linhas com e-mail tem maiúscula.

    A caixa importa porque o e-mail é METADE DA CHAVE DE IDEMPOTÊNCIA: `Maria@x.com` e
    `maria@x.com` são a mesma pessoa e a mesma conversão, e sem o `lower()` a UNIQUE deixaria
    as duas passarem.
    """
    if not bruto or not isinstance(bruto, str):
        return None
    limpo = bruto.strip().lower()
    if not limpo or not _EMAIL_RE.match(limpo):
        return None
    return limpo


def normalizar_telefone_rd(bruto: str | None) -> str | None:
    """Dígitos -> `+55DDDNÚMERO`. None quando não dá para afirmar o formato.

    ------------------------------------------------------------------------------------
    POR COMPRIMENTO, NUNCA POR PREFIXO
    ------------------------------------------------------------------------------------
    `agendamentos.telefone` guarda DUAS grafias, e isto está medido:

        LP      10 ou 11 dígitos, SEM DDI   (routes.py:88-94 corta o 55 na entrada)
        agente  12 ou 13 dígitos, COM DDI   (qualificacao_fluxo.py:1480 passa o wa_id cru,
                                             que não atravessa o validador do Pydantic)

    A tentação é decidir por "começa com 55". **É errado, e o erro tem nome**: DDD 55 é Santa
    Maria/RS, e 4 linhas de 11 dígitos da base começam com 55 por causa do DDD. Tratá-las como
    DDI produziria `+55 9985-8xxxx` — um número de 9 dígitos sem DDD, que o RD aceita e
    ninguém consegue ligar.

    O comprimento decide sem ambiguidade: 10 = fixo com DDD, 11 = celular com DDD, 12/13 = os
    mesmos dois já com o DDI na frente.

    Qualquer outro comprimento devolve None, e None NÃO é motivo de skip — `mobile_phone` é
    campo opcional do payload, e uma conversão sem telefone continua acordando o fluxo de
    e-mail, que é o objetivo. Perder a conversão inteira por causa de um telefone ilegível
    seria trocar o essencial pelo acessório.
    """
    if not bruto or not isinstance(bruto, str):
        return None
    digitos = "".join(c for c in bruto if c.isdigit())
    if len(digitos) in (10, 11):
        return f"+55{digitos}"
    if len(digitos) in (12, 13):
        return f"+{digitos}"
    return None


def chave_de(email_norm: str | None, telefone: str | None) -> str:
    """A identidade da PESSOA para a UNIQUE. `email:<...>` ou `tel:<dígitos>`.

    POR QUE NÃO `agendamento_id` (RECON, achado 2): o fluxo de duas etapas da landing page
    grava DUAS linhas em `agendamentos` para a mesma submissão — uma no `POST /lead`
    (`lead_criado`) e outra no `POST /agendar` (`agendado`), com ids diferentes. Medido: 101
    dos 124 e-mails repetidos desde 18/08 são exatamente esse par, 107 deles em menos de 30
    minutos. Uma UNIQUE por `agendamento_id` aceitaria as duas e a pessoa apareceria no RD
    como duas conversões.

    O PREFIXO É PARTE DA CHAVE, não enfeite: sem ele, um e-mail e um telefone não têm como
    colidir, mas a leitura de `SELECT chave FROM rd_conversoes` deixaria de dizer qual dos
    dois caminhos gerou a linha — e é exatamente essa a pergunta ao investigar um `skipped`.

    A linha sem e-mail é sempre `skipped` (o RD exige `email` no payload), então a chave
    `tel:` nunca chega a virar envio. Ela existe para que a fila continue tendo UMA linha por
    pessoa por evento: sem ela, cada tentativa do agente para o mesmo lead criaria um
    `skipped` novo, e a fila viraria log em vez de fila.
    """
    if email_norm:
        return f"email:{email_norm}"
    digitos = "".join(c for c in (telefone or "") if c.isdigit())
    return f"tel:{digitos}"


# ==========================================================================================
# O PAYLOAD E A CHAMADA
# ==========================================================================================
def montar_payload(*, identifier: str, email: str, nome: str | None,
                   telefone: str | None) -> dict:
    """O corpo do POST. Mínimo por decisão de sprint.

    O QUE FICOU DE FORA, E NÃO POR ESQUECIMENTO:

      `cf_*`                   as quatro perguntas do formulário existem em `agendamentos.extras`
                               (`Profissão`, `Como conheceu`, `Ensino Superior`, `Faixa de
                               investimento`), mas 129 de 396 linhas guardam o escalar JSON
                               `null` e quebram `jsonb_object_keys`. Entra quando os
                               identificadores dos campos personalizados do RD forem conferidos.
      `legal_bases`            depende de saber se a LP coleta consentimento explícito (LGPD).
      `available_for_mailing`  mesma pendência.
      UTM                      a landing page não captura nada disso — conferido no RECON, não
                               há uma única ocorrência de `utm` em `docs/` nem em `app/`.

    `mobile_phone` é OMITIDO quando não há telefone legível, em vez de ir como `None` ou "":
    campo ausente o RD ignora; campo presente e vazio ele pode gravar por cima de um telefone
    bom que já tenha no contato.
    """
    payload = {
        "conversion_identifier": identifier,
        "email": email,
        "tags": [TAG_ORIGEM],
    }
    if nome and nome.strip():
        payload["name"] = nome.strip()
    if telefone:
        payload["mobile_phone"] = telefone
    return {"event_type": "CONVERSION", "event_family": "CDP", "payload": payload}


async def enviar_conversao(corpo: dict) -> tuple[int, str]:
    """POST no RD. Devolve `(status, corpo_da_resposta)`. Só levanta em erro de REDE.

    SEM RETENTATIVA AQUI. O `agendamento/client.py` também não tem, mas pela razão oposta:
    lá um `BoxesAdd` repetido cria dois boxes, então repetir é perigoso. Aqui repetir é
    seguro — o RD casa a conversão pelo e-mail e o mesmo evento duas vezes não duplica
    contato — e a retentativa mora no drenador, onde ela sobrevive a restart porque vive no
    `run_at` da linha e não em memória (mesma lição de `nat_scheduler.py:38-47`).

    4xx e 5xx VOLTAM COMO VALOR, não como exceção: o drenador precisa do status para decidir
    entre retry (429, 5xx) e desistência (demais 4xx), e do corpo para gravar em `resposta`.
    Só o que impede saber o status — timeout, DNS, conexão recusada — vira `httpx.HTTPError`.

    A `api_key` vai na query string porque é o que esta rota aceita com API Key. Ela NUNCA é
    impressa, nem parcialmente: quem loga é o chamador, e loga status e corpo, não a URL.
    """
    api_key = os.getenv("RD_API_KEY", "")
    async with httpx.AsyncClient(timeout=TIMEOUT_PADRAO) as client:
        resp = await client.post(URL_CONVERSOES, params={"api_key": api_key}, json=corpo)
    return resp.status_code, (resp.text or "")
