"""O mapa `estágio da Exact -> template da Meta -> parâmetros`, e como montá-los.

Módulo NEUTRO de propósito: só stdlib + `json`. Não importa `models`, não importa
`exact_routes`, não abre sessão de banco. É o que permite o teste travar o mapa contra a
lista de estágios sem subir a cadeia de envio do WhatsApp — mesma política de
`app/nomes.py` e `app/telefone.py`.

Contexto completo: `RECON_FOLLOW_AUTOMATICO_20260927.md`.

==========================================================================================
POR QUE O JSON É CHAVEADO PELO ID E A BUSCA É PELO NOME
==========================================================================================
O id do estágio na Exact (`GET /v3/stages`) é estável e legível: `174516` é o sétimo follow
do funil 18535, hoje e depois de alguém renomear a etapa. O nome NÃO é estável — e é pior
que instável, é traiçoeiro:

    Follow 1 · Follow 2 · Follow 3 · Follow 4 · Follows 5 · Follows 6 · " Follows 7" ·
    Follows 8 · " Follows 9"

Singular até o 4, plural do 5 em diante, e **espaço à ESQUERDA no 7 e no 9**. Ninguém
digita essa lista certo duas vezes. Por isso ela é COPIADA de `/v3/stages` para o JSON, e
`test_follow_estagio.py` a trava contra os nove nomes que os eventos dos últimos 30 dias
realmente têm (§1.1 do recon).

**CONTRADIZ o desenho da sprint (parcialmente):** `exact_stage_events` NÃO guarda o id do
estágio — só `stage_de` e `stage_para`, dois `varchar(50)` com o NOME
(`app/models.py:893`, INSERT em `exact_spotter.py:469`). A Exact devolve `lead["stage"]`
como string e o sync grava a string. Então o id do JSON é a chave de REGISTRO (o que um
humano confere contra `/v3/stages`), e o casamento em tempo de execução é pelo **nome, byte
a byte**. `_POR_NOME` é esse índice, construído — nunca digitado.

Consequência operacional: se alguém renomear " Follows 7" na Exact, o follow daquele degrau
para de sair EM SILÊNCIO. O teste do mapa contra o banco é a única defesa, e por isso ele
existe.

==========================================================================================
OS PARÂMETROS NÃO SÃO "{{1}} = PRIMEIRO NOME"
==========================================================================================
Este foi o achado que mais muda o desenho (§3.2 do recon). Os nove corpos aprovados na Meta
pedem quatro coisas diferentes, e **só o degrau 4 e o 9 têm uma variável só**:

    nome, sdr, curso   mensagem_flow      "Ola {{1}}, é o {{2}} do CENAT ... Pós {{3}}"
    nome, curso        mensagens_flows2, mensagem_follow3/5/8, mansagem_follows6
    nome               mensagem_follow4, mensagem_follow9
    nome, MÊS          mensagem_follow7   "Os candidatos inscritos neste mês de {{2}}"

O `{{2}}` do `mensagem_follow7` é o **MÊS**. Medido em 27/09: dos 40 envios manuais, 15
saíram com o nome do CURSO ali — "Os candidatos inscritos neste mês de Autolesão, Suicídio
e Luto estão tendo isenção da taxa de matrícula". A causa é a heurística da tela
(`frontend/src/app/automacoes/page.tsx:404`, `i <= 2 -> 'lead_course'`), e é o mesmo defeito
que o S6-3 consertou no `tentativa_contato` — num template que aquele conserto não cobria.

**Este mapa existe para que a automação não repita o erro.** `mes` nunca vira curso: é uma
lista literal de doze nomes, indexada pelo mês de SP.

==========================================================================================
QUEM RESOLVE O VALOR É O `bulk_send_template`, NÃO ESTE MÓDULO
==========================================================================================
`nome`, `curso` e `sdr` viram `param_mappings` com os tipos que a rota já sabe resolver
(`exact_routes.py:466-488`) — `lead_name`, `lead_course`, `sdr_name`. Só `mes` vira
`fixed_text`, porque a rota não tem o conceito.

É deliberado NÃO calcular aqui. `lead_course` chama `resolve_course_name(sub_source, db)`,
que consulta `course_aliases`; duplicar isso num segundo lugar criaria duas verdades sobre
o nome do curso, e a que divergisse sairia para o lead. Mesmo raciocínio do `lead_name`.

`sdr` usa **`sdr_name`** (o DONO do lead em `exact_leads.sdr_name`) e NÃO `sdr_logado`. Os
dois existem e respondem perguntas diferentes (`app/autoria.py`): `sdr_logado` é "quem
apertou enviar agora", e num job automático não há ninguém — cairia sempre no
`SDR_PADRAO = "Thobias"`, assinando com o nome dele o follow de um lead da Victória. O dono
do lead é quem de fato tentou o contato, que é o que `mensagem_flow` afirma.
"""
import json
import os
from datetime import datetime, timedelta, timezone

# Mesmo offset fixo do resto do projeto (`main.py:23`, `nat_guard.py:37`). Sem DST, de
# propósito: é o que os timestamps gravados já usam.
SP_TZ = timezone(timedelta(hours=-3))

# Em português e capitalizado, porque é isso que o corpo do `mensagem_follow7` pede:
# "neste mês de {{2}}". `locale` não entra aqui — depende de o sistema ter pt_BR instalado,
# e um `locale` faltando no servidor viraria "September" na mensagem do lead.
MESES = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")

# Tradução `nome do parâmetro no mapa` -> `type` que `bulk_send_template` aceita.
# `mes` NÃO está aqui: é o único que este módulo resolve, e resolve como `fixed_text`.
TIPOS = {
    "nome": "lead_name",     # exact_routes.py:469 — lead.name.split()[0], fallback "Aluno(a)"
    "curso": "lead_course",  # exact_routes.py:471 — resolve_course_name(sub_source, db)
    "sdr": "sdr_name",       # exact_routes.py:474 — lead.sdr_name, fallback "Equipe CENAT"
}

# Todos os nomes de parâmetro que o mapa pode usar. Um `params` com algo fora daqui é erro
# de digitação no JSON, e tem de estourar no CARREGAMENTO — não no meio de um envio.
PARAMS_VALIDOS = frozenset(TIPOS) | {"mes"}

# Motivo do pulo quando o lead não tem SDR e o template pede o nome dele. Curto porque vai
# para `follow_estagio_envios.motivo`, e diz o CAMINHO, não só o impedimento — mesma regra
# do `MOTIVO_RECUSA` de `higiene_disparo.py`.
MOTIVO_SEM_SDR = ("o template assina com o nome do SDR e o lead não tem sdr_name na Exact — "
                  "atribua o lead a alguém na Exact e mova de novo")

_PADRAO_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "follow_estagios.json")


def caminho_do_mapa() -> str:
    """`FOLLOW_ESTAGIOS_PATH`, ou `backend/follow_estagios.json`.

    Lido a cada chamada, sem cache do caminho: é o que permite um teste apontar para um
    JSON de fixture sem reimportar o módulo.
    """
    return (os.getenv("FOLLOW_ESTAGIOS_PATH", "") or "").strip() or _PADRAO_JSON


class MapaInvalido(Exception):
    """O JSON existe mas não serve. Levanta no CARREGAMENTO, nunca no envio.

    Falhar aqui é barato: o job loga e não envia nada nesta passada. Falhar no meio do laço
    de envio deixaria metade dos leads com template e metade sem, e o motivo só no stdout.
    """


def carregar(caminho: str | None = None) -> dict:
    """Lê e VALIDA o mapa. Devolve `{"funnel_id": int, "estagios": {id: entrada}}`.

    Cada `entrada` ganha duas chaves derivadas, para o resto do código não precisar do dict
    externo: `estagio_id` (int, a chave do JSON) e `params` já validado.

    A validação é grosseira de propósito — ela só cobre o que quebraria em silêncio: nome
    vazio, nome repetido (dois ids apontando para a MESMA etapa fariam a busca por nome ser
    ambígua), template vazio, e parâmetro que `bulk_send_template` não sabe resolver.
    """
    caminho = caminho or caminho_do_mapa()
    with open(caminho, encoding="utf-8") as fh:
        cru = json.load(fh)

    funil = cru.get("funnel_id")
    if not isinstance(funil, int):
        raise MapaInvalido(f"{caminho}: 'funnel_id' ausente ou não-inteiro ({funil!r})")

    estagios_crus = cru.get("estagios")
    if not isinstance(estagios_crus, dict) or not estagios_crus:
        raise MapaInvalido(f"{caminho}: 'estagios' ausente ou vazio")

    estagios: dict[int, dict] = {}
    vistos: dict[str, int] = {}
    for chave, entrada in estagios_crus.items():
        try:
            estagio_id = int(chave)
        except (TypeError, ValueError):
            raise MapaInvalido(f"{caminho}: chave de estágio não-numérica {chave!r}")

        nome = entrada.get("nome") if isinstance(entrada, dict) else None
        template = entrada.get("template") if isinstance(entrada, dict) else None
        params = entrada.get("params") if isinstance(entrada, dict) else None

        # `nome` NÃO passa por strip: o espaço à esquerda de " Follows 7" é o nome.
        if not isinstance(nome, str) or not nome.strip():
            raise MapaInvalido(f"{caminho}: estágio {estagio_id} sem 'nome'")
        if not isinstance(template, str) or not template.strip():
            raise MapaInvalido(f"{caminho}: estágio {estagio_id} ({nome!r}) sem 'template'")
        if not isinstance(params, list) or not params:
            raise MapaInvalido(f"{caminho}: estágio {estagio_id} ({nome!r}) sem 'params'")
        fora = [p for p in params if p not in PARAMS_VALIDOS]
        if fora:
            raise MapaInvalido(
                f"{caminho}: estágio {estagio_id} ({nome!r}) usa parâmetro que "
                f"bulk_send_template não resolve: {fora} — válidos: {sorted(PARAMS_VALIDOS)}")
        if nome in vistos:
            raise MapaInvalido(
                f"{caminho}: o nome {nome!r} aparece em dois estágios ({vistos[nome]} e "
                f"{estagio_id}) — a busca em tempo de execução é pelo NOME e ficaria ambígua")
        vistos[nome] = estagio_id

        por_curso, params_por_curso = _validar_por_curso(caminho, estagio_id, nome, entrada)

        estagios[estagio_id] = {"estagio_id": estagio_id, "nome": nome,
                                "template": template.strip(), "params": list(params),
                                "por_curso": por_curso, "params_por_curso": params_por_curso}

    return {"funnel_id": funil, "estagios": estagios,
            "por_nome": {e["nome"]: e for e in estagios.values()}}


def _validar_por_curso(caminho: str, estagio_id: int, nome: str,
                       entrada: dict) -> tuple[dict[str, str], list[str] | None]:
    """O bloco opcional `por_curso` de um estágio: `(índice, params_por_curso)`.

    O índice é chaveado por `sub_source.strip().lower()`: mesma comparação de
    `agendamento/origens.resolver` (`origens.py:180-182`). A Exact devolve o subSource com a
    caixa que a LP mandou, e a LP já mandou os dois jeitos.

    Duas chaves que só diferem na caixa (`"Pos TEA V3"` e `"pos tea v3"`) são erro de
    CARREGAMENTO: com o índice em minúsculas, uma apagaria a outra em silêncio, e o lead
    receberia o template da que sobrou.

    `params_por_curso` é OBRIGATÓRIO quando há `por_curso`, e não é inferido de `params`: os
    genéricos pedem `nome`+`curso` e as variantes só `nome` (sprint de 28/09, decisão 3).
    Herdar `params` mandaria dois parâmetros para um corpo com um `{{1}}`, e a Meta recusa a
    mensagem inteira com #132000.
    """
    bruto = entrada.get("por_curso")
    if bruto is None:
        if "params_por_curso" in entrada:
            raise MapaInvalido(f"{caminho}: estágio {estagio_id} ({nome!r}) tem "
                               f"'params_por_curso' sem 'por_curso'")
        return {}, None
    if not isinstance(bruto, dict) or not bruto:
        raise MapaInvalido(f"{caminho}: estágio {estagio_id} ({nome!r}) com 'por_curso' "
                           f"vazio ou que não é objeto")

    indice: dict[str, str] = {}
    for sub_source, tpl in bruto.items():
        chave = (sub_source or "").strip().lower()
        if not chave or not isinstance(tpl, str) or not tpl.strip():
            raise MapaInvalido(f"{caminho}: estágio {estagio_id} ({nome!r}) tem entrada "
                               f"vazia em 'por_curso': {sub_source!r} -> {tpl!r}")
        if chave in indice:
            raise MapaInvalido(f"{caminho}: estágio {estagio_id} ({nome!r}) repete o "
                               f"sub_source {sub_source!r} em 'por_curso' (a comparação "
                               f"ignora caixa)")
        indice[chave] = tpl.strip()

    params = entrada.get("params_por_curso")
    if not isinstance(params, list) or not params:
        raise MapaInvalido(f"{caminho}: estágio {estagio_id} ({nome!r}) tem 'por_curso' "
                           f"sem 'params_por_curso'")
    fora = [p for p in params if p not in PARAMS_VALIDOS]
    if fora:
        raise MapaInvalido(
            f"{caminho}: estágio {estagio_id} ({nome!r}) usa em 'params_por_curso' parâmetro "
            f"que bulk_send_template não resolve: {fora} — válidos: {sorted(PARAMS_VALIDOS)}")
    return indice, list(params)


def resolver(entrada: dict, sub_source) -> tuple[str, list[str]]:
    """`(template, params)` deste lead neste estágio.

    `por_curso[sub_source]` (sem caixa e sem espaço nas pontas) e, se não houver, o genérico
    `template` + `params`. Lead sem `sub_source` fica com o genérico. Estágio sem `por_curso`
    (sete dos nove) devolve sempre o genérico.

    Nunca devolve "nada": o fallback é o genérico por decisão do Álefe (sprint de 28/09,
    decisão 2). Uma pós sem variante NÃO é motivo de `skipped`.

    É a ÚNICA regra de escolha. `montar_mappings` e o job chamam esta função, e as duas
    chamadas com o mesmo lead dão a mesma resposta, porque ela é pura.
    """
    chave = (sub_source or "").strip().lower() if isinstance(sub_source, str) else ""
    variante = entrada.get("por_curso", {}).get(chave) if chave else None
    if variante:
        return variante, list(entrada["params_por_curso"])
    return entrada["template"], list(entrada["params"])


def _sub_source_de(lead):
    if isinstance(lead, dict):
        return lead.get("sub_source")
    return getattr(lead, "sub_source", None)


# Cache em processo. O mapa é um arquivo do deploy: ele não muda sem restart, e reler um
# JSON de 700 bytes a cada evento seria I/O por nada. `recarregar()` existe para o teste.
_CACHE: dict | None = None


def mapa() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = carregar()
    return _CACHE


def recarregar(caminho: str | None = None) -> dict:
    """Descarta o cache e lê de novo. Para teste, e para um shell de operação."""
    global _CACHE
    _CACHE = carregar(caminho)
    return _CACHE


def funil_alvo() -> int:
    return mapa()["funnel_id"]


def estagios_do_mapa() -> tuple[str, ...]:
    """Os nomes, na ordem do degrau (pela ordem dos ids no JSON, que é a da escada).

    É o que vai para o `IN (...)` da query do job — ver `follow_estagio._eventos_novos`. O
    filtro por estágio mora na QUERY e não num `if` depois (critério 2 da sprint): um
    `if` deixaria o job ler os 703 eventos de follow do Intercâmbio a cada passada para
    depois jogá-los fora.
    """
    return tuple(e["nome"] for e in mapa()["estagios"].values())


def estagio_para(evento) -> dict | None:
    """A entrada do mapa para este evento, ou None.

    `evento` é qualquer objeto com `funnel_id` e `stage_para` — uma `Row` do SELECT do job,
    um `ExactStageEvent`, ou um dict (aceito por `.get` para os testes).

    Confere o funil TAMBÉM aqui, mesmo a query já filtrando. Não é paranoia gratuita: esta
    função é a única porta do mapa, e quatro funis têm estágio chamado `Follow 1` — 18535
    (pós), 18285 (Intercâmbio, 703 entradas em 30 dias), 20647 e 20776 (§1.1 do recon). Um
    chamador futuro que esqueça o `WHERE funnel_id` mandaria template de pós para
    Intercâmbio, e o pior lugar para descobrir isso é o WhatsApp do lead.
    """
    if isinstance(evento, dict):
        funil, destino = evento.get("funnel_id"), evento.get("stage_para")
    else:
        funil, destino = getattr(evento, "funnel_id", None), getattr(evento, "stage_para", None)

    if funil != funil_alvo() or not isinstance(destino, str):
        return None
    return mapa()["por_nome"].get(destino)


def mes_corrente_sp(agora: datetime | None = None) -> str:
    """O mês corrente em português, capitalizado, no relógio de SP.

    `agora` explícito é o que torna isto testável sem mock de relógio — mesma escolha de
    `nat_guard.dentro_horario_comercial(quando=...)`.

    Aceita aware (converte para SP) ou naive (assume JÁ em SP, como o resto do projeto
    grava). Assumir UTC num naive faria o dia 1º às 00h SP virar mês anterior.
    """
    momento = agora if agora is not None else datetime.now(SP_TZ)
    if momento.tzinfo is not None:
        momento = momento.astimezone(SP_TZ)
    return MESES[momento.month - 1]


def primeiro_nome(nome) -> str:
    """O primeiro nome COMO O BULK O CALCULA. Espelho de `exact_routes.py:469`.

    **Não é `app/nomes.primeiro_nome`, e a diferença é deliberada.** Aquele é melhor (pula
    token sem letra, capitaliza `maria-clara` e `d'ávila`), mas quem monta o `{{1}}` no
    envio é a rota, com `lead.name.split()[0] if lead.name else "Aluno(a)"`. O critério 7
    da sprint pede "mesma regra do bulk", e um espelho que MELHORA a regra é um espelho que
    mente: o log diria "Marina" e o lead leria outra coisa.

    Existe só para log e teste. O ENVIO nunca passa por aqui — usa o tipo `lead_name`, e é
    a rota que resolve. As duas não podem divergir porque só uma está no caminho.

    Unificar as duas regras é assunto de outra sprint: mexer em `lead_name` muda o `{{1}}`
    de TODO disparo manual, que não é o escopo daqui.
    """
    return nome.split()[0] if nome else "Aluno(a)"


def montar_mappings(entrada: dict, lead, *, agora: datetime | None = None):
    """`(param_mappings, motivo)` — a lista pronta para o payload, ou `(None, motivo)`.

    **CONTRADIZ o desenho da sprint em dois pontos, os dois de nomenclatura da rota:**

      1. A chave do payload é **`param_mappings`**, não `mappings` (`exact_routes.py:316`).
         Mandar `mappings` faz a rota cair no "modo legado" (`parameters`), que monta
         `[nome, curso]` por posição — exatamente o chute que o `mensagem_follow7` não
         suporta. O nome errado não daria erro: daria a mensagem errada.
      2. A sprint descreve `montar_mappings(...) -> payload.mappings`. Aqui ela devolve uma
         TUPLA, porque o critério 7 pede um `skipped`/`sem_sdr` quando o lead não tem SDR, e
         esse motivo tem de subir para a linha do banco. Devolver só a lista obrigaria o
         chamador a repetir a checagem — duas regras para a mesma coisa, e a que ficasse
         para trás mandaria "é o Equipe CENAT do CENAT" para o lead.

    Por que `sem_sdr` e não deixar o fallback da rota agir: `sdr_name` cai em
    `"Equipe CENAT"` quando `lead.sdr_name` é vazio, e o corpo do `mensagem_flow` é
    "Ola {{1}}, é o {{2}} do CENAT ✨". Com o fallback, o lead recebe "é o Equipe CENAT do
    CENAT". Preferimos NÃO mandar e deixar o motivo gravado — hoje os 4 125 leads do 18535
    têm `sdr_name` (0 nulos, medido em 27/09), então isto é uma trava para o caso que ainda
    não aconteceu, não um filtro de volume.

    `mes` é o único valor resolvido aqui (a rota não tem o conceito) e vai como `fixed_text`.
    Nunca vazio: um `{{n}}` em branco faz a Meta recusar a mensagem INTEIRA com #131008.

    Os parâmetros são os do template que `resolver` escolhe para o `sub_source` do lead
    (variante por pós: `params_por_curso`; genérico: `params`). O template em si o chamador
    pede a `resolver`, com o mesmo lead.
    """
    _, params = resolver(entrada, _sub_source_de(lead))
    sdr = getattr(lead, "sdr_name", None) if not isinstance(lead, dict) else lead.get("sdr_name")
    if "sdr" in params and not (sdr or "").strip():
        return None, MOTIVO_SEM_SDR

    mappings = []
    for param in params:
        if param == "mes":
            mappings.append({"type": "fixed_text", "value": mes_corrente_sp(agora)})
        else:
            # `PARAMS_VALIDOS` já foi conferido no carregamento; um KeyError aqui seria bug
            # de `carregar`, não dado ruim.
            mappings.append({"type": TIPOS[param]})
    return mappings, None
