"""De onde o agente tira a formação do lead — e por que são duas fontes.

------------------------------------------------------------------------------------------
FONTE PRIMÁRIA: agendamentos.extras (leads da LP, ~9,4/dia)
------------------------------------------------------------------------------------------
O formulário da landing page coleta Profissão, Ensino Superior, Como conheceu e Faixa de
investimento, e o backend grava em `agendamentos.extras` (JSONB) na linha de
`passo='lead_criado'`. Cobertura MEDIDA em 24/08: 80 de 81 leads da LP, 100% dos que
passaram pelo formulário. A junção com o lead da Exact é por `lead_id`, validada em 54 pares.

Nada de rede: o dado é nosso e está no banco no instante do gatilho. É por isso que a
maioria dos leads nunca chega à segunda fonte.

------------------------------------------------------------------------------------------
FONTE SECUNDÁRIA: description da Exact, ON-DEMAND (leads não-LP, ~6,1/dia)
------------------------------------------------------------------------------------------
Lead que entrou pelo sync não tem linha em `agendamentos`. A formação dele, quando existe,
está no `description` do lead na Exact — que o `GET /Leads` devolve, mas que o sync
descarta (`exact_spotter.py:378-388` monta lead_data com 10 campos e `description` não é um).

A escolha foi ler ON-DEMAND, uma chamada por lead novo, em vez de trazer o campo para o
sync. Números medidos em 24/08 que sustentam isso:

    exact_leads ............... 9 133 linhas, 5,7 MB, e o sync faz setattr em TODAS a
                                cada 600s
    chamadas do sync/dia ...... 19 páginas x 144 syncs = ~2 736
    leads não-LP/dia .......... 6,1

Trazer `description` para o sync custaria uma coluna de até 8 000 caracteres reescrita em
9 133 linhas a cada 10 minutos — num campo que MUDA sozinho, porque SDR cola anotação nele.
Ler on-demand custa +6 chamadas sobre 2 736, ou +0,2%.

Exact fora do ar no gatilho não é erro: devolve None, e o fluxo cai na abertura T3, que
pergunta a formação em vez de afirmá-la. Timeout curto pelo mesmo motivo do
`add_timeline_comment` do nat_flow — isto roda dentro de um handler agendado, e a Exact
lenta não pode segurar a fila.

------------------------------------------------------------------------------------------
O PARSER LÊ SÓ O NOSSO FORMATO
------------------------------------------------------------------------------------------
O `description` tem pelo menos três formatos convivendo no mesmo campo:

    NOSSO   E-mail: x@y.com | Profissão: Psicologia | Ensino Superior: Sim | ...
    RD      Profissão escolha:\\nProfessor(a)\\n\\nNível de escolaridade:\\nSim\\n\\n...
    SDR     texto livre, colado no fim de qualquer um dos dois

Só o nosso é lido. Tentar interpretar o do RD significaria adivinhar entre rótulos que
variam ("Profissão escolha" / "Profissão", "investimento pós graduação online" /
"Disponibilidade financeira opções") e, pior, correr o risco de capturar como profissão um
pedaço da anotação do SDR. Não parseou → lead sem formação → T3. Perder a formação de 6
leads por dia é barato; afirmar a formação errada para um deles não é.
"""
import re
import unicodedata

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agendamento, PASSO_FALHOU

# Timeout contra a Exact. 5s pelo mesmo motivo do nat_flow.TIMEOUT_TIMELINE_SEGUNDOS: roda
# dentro de um handler do agendador, e a fila não pode ficar presa num CRM lento.
TIMEOUT_EXACT_SEGUNDOS = 5.0

# Chaves que NÓS escrevemos (agendamento/extras.montar_descricao). A comparação é feita
# sobre a forma normalizada — ver _normalizar_chave — para tolerar o `profissao` em
# snake_case que 1 dos 81 leads medidos trouxe.
CHAVE_PROFISSAO = "profissao"
CHAVE_SUPERIOR = "ensino superior"
CHAVE_CONHECEU = "como conheceu"
CHAVE_INVESTIMENTO = "faixa de investimento"
CHAVE_EMAIL = "e-mail"

CHAVES_CONHECIDAS = {CHAVE_PROFISSAO, CHAVE_SUPERIOR, CHAVE_CONHECEU,
                     CHAVE_INVESTIMENTO, CHAVE_EMAIL}

SEPARADOR = "|"

# Valores de Profissão que NÃO são uma formação: mandar "sua formação é em Outra profissão"
# é pior que não afirmar nada. Vira ausência, e o lead cai no ramo que pergunta.
NAO_SAO_FORMACAO = {"outra profissao", "outra", "outro", "nenhuma", "n/a", "na", "-"}


def _normalizar_chave(bruta: str) -> str:
    """Minúscula, sem acento, `_` vira espaço, espaços colapsados.

    `Profissão`, `profissao` e `PROFISSAO` são a mesma chave. Sem isto, a LP mandar a chave
    em snake_case (aconteceu) faria a formação sumir sem ninguém perceber.
    """
    texto = unicodedata.normalize("NFD", bruta or "")
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.replace("_", " ").lower()
    return re.sub(r"\s+", " ", texto).strip()


def _limpar_valor(bruto: str) -> str:
    """Uma linha. Corta no primeiro fim de linha — é onde o SDR começa a escrever.

    Nós gravamos os extras já colapsados (`extras.limpar_texto`), então uma quebra de linha
    dentro do `description` só pode ter vindo de alguém digitando no CRM depois. O último
    par do formato é o que sofre: sem o corte, `Faixa de investimento` viria com o parecer
    inteiro do SDR grudado.
    """
    return (bruto or "").split("\n")[0].strip()


def parse_description(texto: str | None) -> dict:
    """`description` da Exact no NOSSO formato → dict de chaves normalizadas. Nunca levanta.

    Devolve `{}` para None, vazio, formato do RD, ou qualquer coisa que não tenha ao menos
    um par `chave: valor` conhecido.
    """
    if not isinstance(texto, str) or not texto.strip():
        return {}

    achados = {}
    for parte in texto.split(SEPARADOR):
        if ":" not in parte:
            continue
        chave_bruta, _, valor_bruto = parte.partition(":")
        chave = _normalizar_chave(chave_bruta)
        if chave not in CHAVES_CONHECIDAS:
            continue
        valor = _limpar_valor(valor_bruto)
        if valor:
            achados[chave] = valor
    return achados


def _formacao_de(dados: dict) -> str | None:
    """A profissão, se ela de fato nomeia uma formação. Senão None."""
    valor = (dados.get(CHAVE_PROFISSAO) or "").strip()
    if not valor:
        return None
    if _normalizar_chave(valor) in NAO_SAO_FORMACAO:
        return None
    return valor


def _de_extras(extras) -> dict:
    """`agendamentos.extras` (JSONB) → mesmo dict de chaves normalizadas do parser."""
    if not isinstance(extras, dict):
        return {}
    saida = {}
    for chave_bruta, valor in extras.items():
        chave = _normalizar_chave(chave_bruta)
        if chave in CHAVES_CONHECIDAS and isinstance(valor, str) and valor.strip():
            saida[chave] = valor.strip()
    return saida


async def dados_da_lp(lead_id: int | None, db: AsyncSession) -> dict:
    """Extras do formulário, pelo `lead_id` da Exact. `{}` se não houver.

    Lê a linha de `passo='lead_criado'`, que é a única que carrega `extras` — a de
    `passo='agendado'` vem do obrigado.html, que não reenvia o que o index já mandou
    (MEDIDO: 81 linhas com objeto, todas lead_criado; 54 com JSON null, todas agendado).

    Ordena por id DESC e pega a primeira: se a pessoa preencheu o formulário duas vezes,
    vale o que ela disse por último.
    """
    return _de_extras(await extras_brutos_da_lp(lead_id, db))


async def extras_brutos_da_lp(lead_id: int | None, db: AsyncSession) -> dict:
    """O JSONB de `agendamentos.extras` COMO ELE ESTÁ, sem normalizar chave nenhuma.

    Mesma consulta de `dados_da_lp` (que agora chama esta) — a diferença é só o que sai:
    lá as chaves viram a forma canônica do parser, aqui saem com a caixa e o acento que a
    LP mandou (`"Profissão"`, `"Faixa de investimento"`).

    O consumidor cru é o S5-1: `qualificacao_fluxo._agendar` reescreve esse dicionário em
    `agendamentos.extras` da linha nova, e normalizar no caminho faria a linha do agente
    guardar chaves diferentes das que a mesma LP gravou na linha anterior — duas grafias do
    mesmo formulário na mesma coluna, e todo relatório que agrupar por chave partido em dois.

    `{}` e None são a mesma coisa para quem chama: `agendar(extras=...)` grava `extras or
    None`, então formulário ausente continua virando NULL, como sempre foi.
    """
    if not lead_id:
        return {}
    res = await db.execute(
        select(Agendamento.extras)
        .where(Agendamento.lead_id == lead_id,
               Agendamento.extras.isnot(None),
               Agendamento.passo != PASSO_FALHOU)
        .order_by(Agendamento.id.desc())
        .limit(1))
    bruto = res.scalar_one_or_none()
    return bruto if isinstance(bruto, dict) else {}


async def dados_do_exact(lead_id: int | None) -> dict:
    """`GET /Leads?$filter=id eq {lead_id}` → parse do description. `{}` em qualquer falha.

    Import de `exact_spotter` DENTRO da função: aquele módulo carrega `send_template_message`
    no topo, e este aqui é chamado de caminhos que não devem ter a cadeia de envio junto.
    """
    if not lead_id:
        return {}
    from app.exact_spotter import BASE_URL, get_headers
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_EXACT_SEGUNDOS) as client:
            resp = await client.get(f"{BASE_URL}/Leads", headers=get_headers(),
                                    params={"$filter": f"id eq {int(lead_id)}"})
            resp.raise_for_status()
            valores = resp.json().get("value") or []
    except Exception as e:
        # Exact fora do ar não é erro deste fluxo: é ausência de formação, e ausência tem
        # caminho próprio (T3). Loga porque some em silêncio seria pior.
        print(f"⚠️  Agente: description do lead {lead_id} não lido "
              f"({type(e).__name__}: {e}) — segue sem formação")
        return {}
    if not valores:
        return {}
    return parse_description(valores[0].get("description"))


async def resolver_dados(*, lead_id: int | None, origem: str, db: AsyncSession) -> dict:
    """Os dados do formulário para este lead, venham de onde vierem.

    Devolve sempre as MESMAS chaves, para quem chama não precisar saber a origem:
        {"formacao": str|None, "ensino_superior": str|None,
         "faixa_investimento": str|None, "como_conheceu": str|None}

    Tenta a LP primeiro mesmo quando `origem='exact'`: um lead pode ter preenchido o
    formulário e só depois ter sido ingerido pelo sync, e nesse caso o dado local é melhor
    que o remoto — é o mesmo dado, sem chamada de rede.
    """
    from app.models import ORIGEM_LP  # local: evita ciclo em tempo de import

    dados = await dados_da_lp(lead_id, db)
    if not dados and origem != ORIGEM_LP:
        dados = await dados_do_exact(lead_id)

    return {
        "formacao": _formacao_de(dados),
        "ensino_superior": dados.get(CHAVE_SUPERIOR),
        "faixa_investimento": dados.get(CHAVE_INVESTIMENTO),
        "como_conheceu": dados.get(CHAVE_CONHECEU),
    }
