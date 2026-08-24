"""Primeiro nome do lead, para as mensagens automáticas.

O cadastro guarda o nome COMPLETO, como a pessoa digitou no formulário — e era ele que ia
para o `{{1}}` dos templates:

    "Olá, Marina leite Guimaraes serra! 😊"

Ninguém é chamado assim numa conversa de WhatsApp. Esta função devolve o primeiro nome,
com a capitalização arrumada.

------------------------------------------------------------------------------------------
AS REGRAS, E POR QUE CADA UMA
------------------------------------------------------------------------------------------
  * **Primeiro token que CONTÉM letra**, não `split()[0]` cego. O cadastro vem de campo
    livre: `"  ana"`, `"123 Ana"` e `"- Maria"` existem, e o token cego devolveria espaço,
    número ou traço no lugar do nome.

  * **Capitalização por pedaço**, separando em `-` e apóstrofo: `"maria-clara"` vira
    `"Maria-Clara"` e `"d'ávila"` vira `"D'Ávila"`. `str.capitalize()` sozinho devolveria
    `"Maria-clara"`.

  * **Normaliza SEMPRE**, inclusive nome já bem escrito. O que se perde é o caso raro do
    `"McDonald"` (vira `"Mcdonald"`); o que se ganha é `"JOÃO"` e `"joão"` virarem
    `"João"` — e é isso que a base tem de verdade, porque o campo é digitado no celular.

  * **Sem nenhum token com letra, devolve o que entrou, intacto.** Melhor mandar o
    cadastro cru do que mandar vazio: `"Olá, 123!"` é ruim, `"Olá, !"` é pior.

------------------------------------------------------------------------------------------
MÓDULO NEUTRO
------------------------------------------------------------------------------------------
Só stdlib; não importa NADA do projeto. É o que permite chamá-lo tanto de `exact_spotter`
(boas-vindas) quanto de `nat_sender` sem recriar o import circular que `course_names.py`
existe para quebrar.
"""
import re

# Separadores internos de um nome. Ficam no resultado do split (grupo capturado), então
# juntar os pedaços de volta reconstrói o token original, com ou sem separador.
_SEPARADORES = re.compile(r"([-'’])")


def _capitalizar(pedaco: str) -> str:
    """Primeira letra maiúscula, resto minúsculo. `""` continua `""`."""
    return pedaco[:1].upper() + pedaco[1:].lower() if pedaco else pedaco


def primeiro_nome(nome) -> str:
    """Primeiro nome, capitalizado. NUNCA levanta — está no caminho de cada envio.

        "marina leite guimaraes serra"  ->  "Marina"
        "JOÃO"                          ->  "João"
        "maria-clara souza"             ->  "Maria-Clara"
        ""                              ->  ""
        None                            ->  ""
    """
    if not isinstance(nome, str):
        return ""
    for token in nome.split():
        if any(c.isalpha() for c in token):
            return "".join(
                pedaco if _SEPARADORES.fullmatch(pedaco) else _capitalizar(pedaco)
                for pedaco in _SEPARADORES.split(token)
            )
    return nome
