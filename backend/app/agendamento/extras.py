"""Campos livres da landing page: sanitização, limites e o `description` do lead.

------------------------------------------------------------------------------------------
O QUE SÃO OS EXTRAS
------------------------------------------------------------------------------------------
Perguntas que cada LP faz além de nome/e-mail/telefone: profissão, se tem ensino superior,
como conheceu a CENAT, faixa de investimento. Variam por página e por campanha, e por isso
NÃO viram coluna: virariam uma migração por pergunta nova.

Eles têm dois destinos, e os dois importam:

  1. **`agendamentos.extras`** (JSONB nosso) — o dado estruturado, para relatório.
  2. **`description` do lead na Exact** — o texto que o SDR lê antes de ligar.

O segundo é o que muda a conversa: um SDR que sabe que a pessoa é psicóloga e conheceu pelo
Instagram liga diferente de quem só tem um nome e um telefone.

------------------------------------------------------------------------------------------
O LIMITE DE `description` É 8000 — E A EXACT NÃO AVISA QUANDO ESTOURA
------------------------------------------------------------------------------------------
Medido em 18/08/2026, criando e apagando leads reais (AGENDAMENTO_FINDINGS.md §13):

    enviado 200 / 4000 / 7999 / 8000  ->  guardado idêntico
    enviado 8001                      ->  guardado 7999   (TRUNCADO)
    enviado 10000                     ->  guardado 7999   (TRUNCADO)

**Nenhuma das tentativas devolveu erro.** O `LeadsAdd` responde 201 e corta o texto em
silêncio — o dado some sem nada em log nenhum. Note ainda que estourar por 1 caractere custa
2: 8001 vira 7999, não 8000.

Por isso este módulo trabalha com um ORÇAMENTO próprio bem abaixo do teto (4000) e, se algum
dia o texto passar disso, **corta ele mesmo e deixa a marca `…`**. Truncar é ruim; truncar
sem ninguém saber é pior.

Com os limites de campo abaixo o pior caso real é ~2850 caracteres, então o orçamento nunca
deveria ser atingido. Ele existe para o dia em que alguém afrouxar um limite sem perceber
que existe um teto do outro lado.

------------------------------------------------------------------------------------------
POR QUE SANITIZAR
------------------------------------------------------------------------------------------
O conteúdo vem de formulário público e vai para um campo de texto que um humano lê no CRM.
Três coisas quebram esse texto:

  * **A barra vertical `|`** é o separador do formato. Um valor que a contenha parte o campo
    em dois pares falsos aos olhos de quem lê. Vira `/`.
  * **Quebra de linha e tabulação** desmontam o layout do CRM. Viram espaço.
  * **Caracteres de controle** (`\\x00`-`\\x1f`) não têm representação visível e já
    corromperam exportação de CSV em outros sistemas. Somem.

Sanitizar não é o mesmo que validar: o que estoura CONTRATO (mais de 10 chaves, valor longo
demais) é recusado com 422 lá em `routes.py`, porque é a LP mandando errado. O que é só
sujeira de digitação é limpo aqui, em silêncio.
"""
import re
import unicodedata

# Contrato com o front. Recusar é melhor que truncar em silêncio num campo que alimenta
# relatório: 10 perguntas já é uma LP longa, e uma 11ª é sinal de que alguém mudou o
# formulário sem olhar o backend.
MAX_CHAVES = 10
MAX_VALOR = 200
MAX_CHAVE = 60

# Teto MEDIDO da Exact, para referência de quem for ler este arquivo. Não usar direto.
LIMITE_EXACT = 8000
# O nosso, com folga deliberada. Ver o cabeçalho.
ORCAMENTO_DESCRICAO = 4000

SEPARADOR = " | "

_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")
_ESPACOS = re.compile(r"\s+")


class ExtrasInvalidos(ValueError):
    """Contrato violado: chaves demais, ou chave/valor longo demais. -> 422"""


def limpar_texto(bruto: str) -> str:
    """Uma linha de texto seguro para o CRM. Nunca levanta; devolve "" se não sobrar nada.

    NFC antes de tudo: `Profissão` digitado com `~` combinante ocupa mais bytes e compara
    diferente de `Profissão` pré-composto. Normalizar evita duas chaves "iguais" no JSON.
    """
    if not isinstance(bruto, str):
        bruto = str(bruto)
    texto = unicodedata.normalize("NFC", bruto)
    texto = _CONTROLE.sub(" ", texto)     # controle vira espaço, não some: separa palavras
    texto = texto.replace("|", "/")       # o separador do formato não pode vir do conteúdo
    texto = _ESPACOS.sub(" ", texto)      # colapsa o que sobrou
    return texto.strip()


def sanitizar(bruto: dict | None) -> dict[str, str]:
    """Valida o contrato e devolve o dicionário limpo, na ordem em que veio.

    Levanta ExtrasInvalidos para violação de contrato (a LP mandou errado). Sujeira de
    conteúdo é limpa sem reclamar.

    A ordem é preservada de propósito: ela é a ordem das perguntas no formulário, e é como
    o SDR espera ler no CRM. `dict` mantém ordem de inserção desde o Python 3.7.
    """
    if not bruto:
        return {}
    if not isinstance(bruto, dict):
        raise ExtrasInvalidos("extras deve ser um objeto de texto para texto")
    if len(bruto) > MAX_CHAVES:
        raise ExtrasInvalidos(f"extras aceita no máximo {MAX_CHAVES} chaves, vieram {len(bruto)}")

    limpo: dict[str, str] = {}
    for chave_bruta, valor_bruto in bruto.items():
        if valor_bruto is None:
            continue
        if not isinstance(chave_bruta, str) or not isinstance(valor_bruto, str):
            raise ExtrasInvalidos("extras aceita apenas texto em chave e valor")
        if len(chave_bruta) > MAX_CHAVE:
            raise ExtrasInvalidos(f"chave longa demais (máx {MAX_CHAVE}): {chave_bruta[:40]!r}")
        if len(valor_bruto) > MAX_VALOR:
            raise ExtrasInvalidos(
                f"valor longo demais (máx {MAX_VALOR}) na chave {chave_bruta[:40]!r}")

        chave = limpar_texto(chave_bruta)
        valor = limpar_texto(valor_bruto)
        # Par que virou vazio depois da limpeza não vai para o CRM nem para o relatório:
        # "Profissão: " sozinho não informa nada e só ocupa espaço na linha que o SDR lê.
        if not chave or not valor:
            continue
        limpo[chave] = valor
    return limpo


def montar_descricao(email: str | None, extras: dict[str, str] | None) -> str | None:
    """O `description` do lead: e-mail primeiro, extras na ordem do formulário.

        E-mail: x@y.com | Profissão: Psicologia | Como conheceu: Instagram

    Devolve None quando não há nada a dizer — assim o `LeadsAdd` segue sem a chave
    `description`, exatamente como antes de os extras existirem.

    O e-mail vem primeiro porque é o dado que o SDR mais usa e o único que a Exact não tem
    campo próprio para guardar (ver `client.criar_lead`).
    """
    partes: list[str] = []
    if email:
        limpo = limpar_texto(email)
        if limpo:
            partes.append(f"E-mail: {limpo}")
    for chave, valor in (extras or {}).items():
        partes.append(f"{chave}: {valor}")

    if not partes:
        return None

    texto = SEPARADOR.join(partes)
    if len(texto) > ORCAMENTO_DESCRICAO:
        # Corte NOSSO, com marca visível. A alternativa é o corte da Exact, que é mudo e
        # come 2 caracteres a mais. Quem ler o CRM vê que faltou pedaço.
        texto = texto[:ORCAMENTO_DESCRICAO - 1].rstrip() + "…"
    return texto
