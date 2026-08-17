"""Allowlist de `subSource` — de qual curso veio o lead da landing page.

------------------------------------------------------------------------------------------
POR QUE ALLOWLIST, E NÃO TEXTO LIVRE
------------------------------------------------------------------------------------------
`LeadsAdd` **cria** o subSource quando o valor não existe. Isso foi medido, não suposto: o
primeiro teste da investigação mandou `"DialogicasTurma"`, um nome que eu inventei, e ele
virou o subSource **id 176793 — o id mais alto de toda a base**, acima de qualquer curso real.
Ficou lá depois que o lead de teste foi excluído.

(AGENDAMENTO_FINDINGS.md §3 afirmava o contrário — "a API não criou origem nova". Estava
errado: o valor voltar resolvido com um id não prova que o id já existia. Corrigido em §11.)

O cadastro de origens é **global e usado em relatório de marketing**. Um campo de texto livre
vindo de página pública significa que qualquer visitante — ou qualquer erro de digitação numa
LP nova — cria uma linha nova lá dentro, e ninguém percebe até o relatório sair torto.

Por isso o `origem` do corpo do POST é conferido contra esta lista antes de chegar à Exact. O
que não estiver nela é 400, e nada é criado.

------------------------------------------------------------------------------------------
COMO CONFIGURAR
------------------------------------------------------------------------------------------
    AGENDAMENTO_SUBSOURCES=PosMulheridades,posgenerot2,PosPraticasDialogicasTurma1
    AGENDAMENTO_SUBSOURCE_PADRAO=PosPraticasDialogicasTurma1

O padrão é usado quando o corpo não manda `origem` — LP antiga que ainda não passa o campo
continua funcionando. O padrão TAMBÉM precisa estar na allowlist; se não estiver, ele é
acrescentado e o log avisa, porque recusar todo agendamento por causa de um env mal preenchido
seria pior que aceitar o valor que o operador claramente quis.

A comparação é **case-insensitive**, mas o valor enviado à Exact é o da allowlist, com a caixa
exata. Os nomes reais misturam convenções (`posgenerot2` e `PosMulheridades` convivem), e um
`PosMulheridades` enviado como `posmulheridades` criaria um SEGUNDO cadastro com o mesmo nome
em caixa diferente — exatamente o problema que este módulo existe para evitar.
"""
import os

# Valores conferidos em GET /Sources e no volume real de `exact_leads` (17/08/2026).
# Cada um existe hoje na Exact, sob o source "Rd Marketing" (id 106847).
#
#   PosMulheridades              id 173358   120 leads   pós de Mulheridades
#   posgenerot2                  id 168707   325 leads   pós de Gênero, turma 2 (a viva)
#   PosPraticasDialogicasTurma1  id 170904    90 leads   pós de Práticas Dialógicas
#
# NÃO incluir `posgenero` (id 137321): é a turma 1 de Gênero, sem lead novo desde 31/10/2025.
# NÃO incluir `DialogicasTurma` (id 176793): é lixo criado por um teste desta investigação.
SUBSOURCES_PADRAO = "PosMulheridades,posgenerot2,PosPraticasDialogicasTurma1"
SUBSOURCE_PADRAO = "PosPraticasDialogicasTurma1"


class OrigemInvalida(Exception):
    """`origem` fora da allowlist. -> 400, e nada é criado na Exact."""


def _lista() -> list[str]:
    bruto = os.getenv("AGENDAMENTO_SUBSOURCES", SUBSOURCES_PADRAO)
    valores = [v.strip() for v in (bruto or "").split(",") if v.strip()]
    padrao = padrao_configurado()
    if padrao and not any(v.lower() == padrao.lower() for v in valores):
        print(f"⚠️ agendamento: AGENDAMENTO_SUBSOURCE_PADRAO={padrao!r} não está em "
              f"AGENDAMENTO_SUBSOURCES. Acrescentando — corrija o .env.")
        valores.append(padrao)
    return valores


def padrao_configurado() -> str:
    return (os.getenv("AGENDAMENTO_SUBSOURCE_PADRAO", SUBSOURCE_PADRAO) or "").strip()


def permitidas() -> list[str]:
    """A allowlist, na caixa exata que vai para a Exact. Serve também ao GET /slots."""
    return _lista()


def resolver(origem: str | None) -> str:
    """`origem` do corpo -> subSource válido. Levanta OrigemInvalida se não estiver na lista.

    Sem `origem`, devolve o padrão — a LP que ainda não manda o campo segue funcionando.
    """
    valores = _lista()
    if not valores:
        # Não deveria acontecer: só com AGENDAMENTO_SUBSOURCES e _PADRAO ambos vazios.
        raise OrigemInvalida("nenhum subSource configurado")

    if origem is None or not origem.strip():
        padrao = padrao_configurado()
        for v in valores:
            if v.lower() == padrao.lower():
                return v
        return valores[0]

    procurado = origem.strip().lower()
    for v in valores:
        if v.lower() == procurado:
            return v          # devolve a caixa da allowlist, não a que o visitante mandou
    raise OrigemInvalida(f"origem não permitida: {origem!r}")
