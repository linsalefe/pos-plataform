"""Extração do clique de botão do payload do webhook da Meta.

Módulo separado de propósito: é função pura, sem banco e sem FastAPI, para poder ser testada
por replay de payload sintético — que é a única validação possível hoje, já que nada está
sendo entregue desde 23/07 e não há clique real chegando.

Dois formatos, e os dois importam:

  * type="button"      -> quick reply de TEMPLATE. É o que os 6 templates nat_* produzem hoje.
                          {"type":"button","button":{"payload":"...","text":"..."},
                           "context":{"id":"wamid.ORIGINAL"}}

  * type="interactive" -> botão de mensagem livre. Ainda não ocorre (0 linhas no banco), será
                          usado no Bloco 3.
                          {"type":"interactive","interactive":{"type":"button_reply",
                           "button_reply":{"id":"...","title":"..."}}}

O `context.id` é o campo que dá sentido ao evento: é o wamid da mensagem que o botão
respondeu. "Prefiro outro horário" é o MESMO texto em nat_boasvindas e em nat_reativacao_09h —
sem ele, os dois cliques são indistinguíveis. Nunca descartar.
"""

FONTE_TEMPLATE = "template"
FONTE_INTERACTIVE = "interactive"


def extrair_evento_botao(msg: dict, wa_message_id: str = None) -> dict | None:
    """Devolve o evento de clique, ou None se a mensagem não for clique de botão.

    As chaves do retorno espelham as colunas de nat_button_events.
    """
    if not isinstance(msg, dict):
        return None

    tipo = msg.get("type")

    if tipo == "button":
        botao = msg.get("button") or {}
        payload = botao.get("payload")
        texto = botao.get("text")
        fonte = FONTE_TEMPLATE

    elif tipo == "interactive":
        interativo = msg.get("interactive") or {}
        # list_reply e outros subtipos não são clique de botão — fora de escopo.
        if interativo.get("type") != "button_reply":
            return None
        resposta = interativo.get("button_reply") or {}
        # No formato interativo o payload estável é o `id`; `title` é só o rótulo visível.
        payload = resposta.get("id")
        texto = resposta.get("title")
        fonte = FONTE_INTERACTIVE

    else:
        return None

    return {
        "contact_wa_id": msg.get("from"),
        "wa_message_id": wa_message_id or msg.get("id"),
        "context_message_id": (msg.get("context") or {}).get("id"),
        "button_payload": payload,
        "button_text": texto,
        "source": fonte,
    }


def conteudo_legivel(evento: dict) -> str:
    """Texto que vai para Message.content.

    Antes ficava "" — o que também deixava a notificação do SDR sem corpo (main.py:294).
    """
    return f"botao:{evento.get('button_text') or ''}"
