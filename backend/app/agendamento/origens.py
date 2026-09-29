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
    AGENDAMENTO_SOURCE="Landing Page"

**ASPAS são obrigatórias em valor com espaço.** Não por causa do systemd nem do dotenv — os
dois leem bem sem elas — mas do bash: um operador que faça `set -a && . .env` recebe
`AGENDAMENTO_SOURCE=Landing` e o shell tenta executar `Page` como comando. A variável fica
pela metade, o código cai no padrão, e nada avisa (FINDINGS §16).

**Valor com espaço é seguro no CSV.** Testado nos dois parsers que leem este `.env`: o
`EnvironmentFile` do systemd e o `python-dotenv`. Os dois preservam `Pos Saude do Trabalhador`
inteiro, e o separador é a vírgula — só um valor que CONTENHA vírgula quebraria, e aí a saída
é `AGENDAMENTO_SUBSOURCES_JSON`, que não existe porque nunca foi preciso.

`AGENDAMENTO_SOURCE` é o `source` do lead, o nível acima do `subSource`. Muda junto com a
allowlist: uma subSource pertence a UM source, e apontar para o par errado cria cadastro novo
do mesmo jeito.

O padrão é usado quando o corpo não manda `origem` — LP antiga que ainda não passa o campo
continua funcionando. O padrão TAMBÉM precisa estar na allowlist; se não estiver, ele é
acrescentado e o log avisa, porque recusar todo agendamento por causa de um env mal preenchido
seria pior que aceitar o valor que o operador claramente quis.

A comparação é **case-insensitive**, mas o valor enviado à Exact é o da allowlist, com a caixa
exata. Os nomes reais misturam convenções (`posgenerot2` e `PosMulheridades` convivem), e um
`PosMulheridades` enviado como `posmulheridades` criaria um SEGUNDO cadastro com o mesmo nome
em caixa diferente — exatamente o problema que este módulo existe para evitar.

------------------------------------------------------------------------------------------
ALIASES — quando a LP publicada manda um nome fora do padrão
------------------------------------------------------------------------------------------
    AGENDAMENTO_ORIGEM_ALIASES='{"Pos DH T4": "Pos Direitos Humanos T4"}'

Incidente de 27/08 a 29/09/2026: a LP de Direitos Humanos T4 foi publicada com
`ORIGEM = "Pos DH T4"`, enquanto a allowlist, a Exact (177142) e o mapa do RD tinham
`Pos Direitos Humanos T4`. Toda chamada da página era 400: 158 recusas de 49 IPs no journal.

O alias é traduzido ANTES da validação, e o que sai daqui é sempre o nome CANÔNICO — é ele
que vai para a Exact, para `agendamentos.sub_source` e, por consequência, para o mapa do RD.
Por isso o alias nunca cria cadastro: não existe caminho em que o nome do alias chegue ao
`LeadsAdd`.

JSON e não CSV porque o par tem direção, e nomes de pós têm espaço. ASPAS SIMPLES em volta
no `.env` (o JSON tem aspas duplas). Validado ao carregar, FALHA FECHADA por entrada:
  - JSON inválido ou que não seja objeto  -> nenhum alias vale
  - destino fora da allowlist             -> aquele alias é descartado
  - alias igual a um nome da allowlist    -> descartado (o nome canônico tem precedência)
Descartado = continua 400, como antes. Aceitar um destino fora da lista seria texto livre
por outra porta. O motivo vai para o log uma vez por valor do env, e o boot repete o resumo.

Cada resolução por alias é logada com um contador (`🔁 agendamento: origem por alias`), para
medir quanto tráfego ainda vem do nome errado e saber quando aposentar o alias.
"""
import json
import os
from functools import lru_cache

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

# O `source` (nível acima do subSource). Sai daqui e não de `agendar.py` porque tem
# exatamente o mesmo risco: `LeadsAdd` CRIA source que não existe, igual faz com subSource.
# Valor de produção desde 18/08/2026: "Landing Page" (id 140648), criado via LeadsAdd —
# não existe SourcesAdd na API. O padrão abaixo é só a rede para env ausente, e aponta para
# o source ANTIGO de propósito: se a config sumir, é melhor cair onde o histórico está.
SOURCE_PADRAO = "Rd Marketing"


class OrigemInvalida(Exception):
    """`origem` fora da allowlist. -> 400, e nada é criado na Exact."""


# Resoluções por alias desde o boot, por alias. Só vai para o log — é o medidor do volume.
_usos_alias: dict[str, int] = {}


def _lista() -> list[str]:
    bruto = os.getenv("AGENDAMENTO_SUBSOURCES", SUBSOURCES_PADRAO)
    valores = [v.strip() for v in (bruto or "").split(",") if v.strip()]
    padrao = padrao_configurado()
    if padrao and not any(v.lower() == padrao.lower() for v in valores):
        print(f"⚠️ agendamento: AGENDAMENTO_SUBSOURCE_PADRAO={padrao!r} não está em "
              f"AGENDAMENTO_SUBSOURCES. Acrescentando — corrija o .env.")
        valores.append(padrao)
    return valores


@lru_cache(maxsize=8)
def _aliases_de(bruto: str, lista: tuple[str, ...]) -> tuple[dict[str, str], tuple[str, ...]]:
    """(aliases válidos {alias_minúsculo: canônico na caixa da allowlist}, motivos de descarte).

    Em cache pelo par (env, allowlist): o descarte é logado UMA vez, não a cada POST.
    """
    if not bruto.strip():
        return {}, ()
    try:
        dados = json.loads(bruto)
    except ValueError as e:
        return {}, (f"AGENDAMENTO_ORIGEM_ALIASES não é JSON válido ({e}); nenhum alias vale",)
    if not isinstance(dados, dict):
        return {}, ("AGENDAMENTO_ORIGEM_ALIASES precisa ser um objeto JSON "
                    "{alias: canônico}; nenhum alias vale",)

    canonicos = {v.lower(): v for v in lista}
    validos: dict[str, str] = {}
    motivos: list[str] = []
    for alias, destino in dados.items():
        if not isinstance(alias, str) or not isinstance(destino, str) \
                or not alias.strip() or not destino.strip():
            motivos.append(f"alias {alias!r} -> {destino!r} descartado: par vazio ou não-texto")
            continue
        chave = alias.strip().lower()
        canonico = canonicos.get(destino.strip().lower())
        if canonico is None:
            motivos.append(f"alias {alias!r} descartado: destino {destino!r} não está em "
                           f"AGENDAMENTO_SUBSOURCES")
            continue
        if chave in canonicos:
            motivos.append(f"alias {alias!r} descartado: já é um nome da allowlist")
            continue
        validos[chave] = canonico
    for m in motivos:
        print(f"❌ agendamento: {m}")
    return validos, tuple(motivos)


def aliases() -> dict[str, str]:
    """Aliases válidos agora: {alias em minúsculas: nome canônico da allowlist}."""
    bruto = os.getenv("AGENDAMENTO_ORIGEM_ALIASES", "") or ""
    return _aliases_de(bruto, tuple(_lista()))[0]


def validar_aliases() -> dict:
    """Resumo dos aliases para o log de boot. Nunca levanta — o descarte já é a falha fechada."""
    bruto = os.getenv("AGENDAMENTO_ORIGEM_ALIASES", "") or ""
    validos, motivos = _aliases_de(bruto, tuple(_lista()))
    if motivos:
        print(f"❌ agendamento: {len(motivos)} alias(es) de origem descartado(s) — "
              f"essas origens seguem recusadas com 400. Corrija AGENDAMENTO_ORIGEM_ALIASES.")
    if validos:
        pares = ", ".join(f"{a!r} -> {c!r}" for a, c in validos.items())
        print(f"✅ agendamento: {len(validos)} alias(es) de origem ativo(s): {pares}")
    return {"validos": validos, "descartados": list(motivos)}


def padrao_configurado() -> str:
    return (os.getenv("AGENDAMENTO_SUBSOURCE_PADRAO", SUBSOURCE_PADRAO) or "").strip()


def permitidas() -> list[str]:
    """A allowlist, na caixa exata que vai para a Exact. Serve também ao GET /slots."""
    return _lista()


def source_configurado() -> str:
    """O `source` que vai no `LeadsAdd`. Vazio no env = `Rd Marketing`."""
    return (os.getenv("AGENDAMENTO_SOURCE", SOURCE_PADRAO) or SOURCE_PADRAO).strip()


async def validar_contra_exact() -> dict:
    """Confere no startup que o source existe e que TODA a allowlist vive dentro dele.

    Esta função existe por causa de um incidente evitado em 18/08/2026: chegou um pedido para
    trocar a allowlist por 12 nomes legíveis (`Pos Psicologia Escolar`) e um source novo
    (`Landing Page`). Onze dos doze não existiam na Exact, e o source nenhum. Aplicar aquilo
    teria feito o primeiro lead de cada LP **criar** um cadastro paralelo ao que já existe
    (`PosPsicologiaEscolar`, com 71 leads), partindo o histórico de 2222 leads em dois nomes
    para os mesmos cursos — em silêncio, com 201 na resposta.

    A checagem é barata (uma chamada) e roda uma vez por boot. NUNCA levanta: o backend serve
    o Hub, o webhook da Meta e a NAT, e não pode cair porque o CRM respondeu estranho. O que
    ela faz é gritar no log com o nome exato do que está errado.

    Não desativa nada. Diferente das consultoras — onde um e-mail inválido faz todo agendamento
    falhar de imediato e tirar de rotação é o certo — aqui o valor errado ainda "funciona":
    cria o cadastro e segue. Bloquear automaticamente deixaria a LP fora do ar por um problema
    de nomenclatura; avisar alto deixa a decisão com quem pode consertar.
    """
    from app.agendamento import client

    source = source_configurado()
    lista = permitidas()
    resumo = {"source": source, "source_ok": False, "faltando": [], "checagem_falhou": False}
    try:
        sources = await client.listar_sources()
    except client.ExactErro as e:
        print(f"⚠️ agendamento: não consegui validar origens em /Sources "
              f"({type(e).__name__}: {e}). Seguindo sem verificar.")
        resumo["checagem_falhou"] = True
        return resumo

    achado = next((s for s in sources
                   if str(s.get("value", "")).strip().lower() == source.lower()), None)
    if achado is None:
        print(f"❌ agendamento: source {source!r} NÃO EXISTE em /Sources. O primeiro lead vai "
              f"CRIAR esse cadastro na Exact, e não há endpoint para desfazer.")
        return resumo
    if not achado.get("active", True):
        print(f"❌ agendamento: source {source!r} existe mas está INATIVO na Exact.")
    resumo["source_ok"] = True
    resumo["source_id"] = achado.get("id")

    dentro = {str(x.get("value", "")).strip().lower()
              for x in (achado.get("subSources") or [])}
    for valor in lista:
        if valor.strip().lower() not in dentro:
            resumo["faltando"].append(valor)

    if resumo["faltando"]:
        print(f"❌ agendamento: {len(resumo['faltando'])} de {len(lista)} origens da allowlist "
              f"NÃO existem sob o source {source!r}: {resumo['faltando']}. "
              "Cada uma vai ser CRIADA no primeiro lead da LP correspondente — cadastro "
              "duplicado e histórico partido. Confira a grafia contra GET /Sources.")
    else:
        print(f"✅ agendamento: source {source!r} (id {achado.get('id')}) com as "
              f"{len(lista)} origens da allowlist confirmadas.")
    return resumo


def resolver(origem: str | None) -> str:
    """`origem` do corpo -> subSource válido. Levanta OrigemInvalida se não estiver na lista
    nem for alias válido. Alias devolve o nome CANÔNICO, nunca o próprio alias.

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

    canonico = aliases().get(procurado)
    if canonico is not None:
        _usos_alias[procurado] = _usos_alias.get(procurado, 0) + 1
        print(f"🔁 agendamento: origem por alias {origem!r} -> {canonico!r} "
              f"(uso nº {_usos_alias[procurado]} desde o boot)")
        return canonico
    raise OrigemInvalida(f"origem não permitida: {origem!r}")
