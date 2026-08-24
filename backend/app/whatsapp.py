import httpx

GRAPH_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"


async def send_text_message(to: str, text: str, phone_number_id: str, token: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/{phone_number_id}/messages",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
        )
        return response.json()


async def send_interactive_buttons(to: str, body: str, buttons: list, phone_number_id: str, token: str) -> dict:
    """Mensagem de texto com botões de resposta rápida (fora de template).

    Só vale dentro da janela de 24h — fora dela a Meta recusa e só template passa.

    `buttons` é [{"payload": "...", "title": "..."}]; o payload vira o `id` da reply e é o
    que volta em interactive.button_reply.id no webhook. Máximo 3 botões, título de até 20
    caracteres (quem chama já entrega truncado — ver nat_copy.BOTOES_LIVRES).
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/{phone_number_id}/messages",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body},
                    "action": {
                        "buttons": [
                            {"type": "reply",
                             "reply": {"id": b["payload"], "title": b["titulo"]}}
                            for b in buttons
                        ]
                    },
                },
            },
        )
        return response.json()


async def send_template_message(to: str, template_name: str, language: str, phone_number_id: str, token: str, parameters: list = None, button_payloads: list = None) -> dict:
    """Envia um template aprovado.

    `button_payloads` fixa o payload de cada quick reply, por índice: o item 0 vai para o
    botão 0, o 1 para o botão 1. É o único momento em que dá para definir esse valor — a
    DEFINIÇÃO do template não carrega payload, só o envio. O payload não é visível para o
    lead e volta em `button.payload` no webhook quando ele clica, que é o que permite rotear
    sem depender do texto do botão (dois templates têm "Prefiro outro horário" idêntico).

    Use None numa posição para deixar aquele botão com o payload padrão da Meta (o texto).

    NÃO REGRESSÃO: sem `button_payloads`, o corpo enviado é byte a byte o mesmo de antes —
    a boas-vindas em produção passa por aqui e não pode mudar.
    """
    template_data = {
        "name": template_name,
        "language": {"code": language},
    }

    components = []
    if parameters:
        components.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in parameters],
            }
        )

    for indice, payload in enumerate(button_payloads or []):
        if payload is None:
            continue
        components.append({
            "type": "button",
            "sub_type": "quick_reply",
            "index": str(indice),
            "parameters": [{"type": "payload", "payload": payload}],
        })

    if components:
        template_data["components"] = components

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/{phone_number_id}/messages",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": template_data,
            },
        )
        return response.json()


async def upload_media(file_bytes: bytes, mime_type: str, filename: str, phone_number_id: str, token: str) -> str:
    """Faz upload de mídia para Meta e retorna o media_id."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{BASE_URL}/{phone_number_id}/media",
            headers={"Authorization": f"Bearer {token}"},
            data={"messaging_product": "whatsapp", "type": mime_type},
            files={"file": (filename, file_bytes, mime_type)},
        )
        data = response.json()
        if "id" not in data:
            raise Exception(f"Erro ao fazer upload: {data}")
        return data["id"]


async def send_media_message(to: str, media_id: str, media_type: str, phone_number_id: str, token: str, caption: str = None) -> dict:
    """Envia mensagem de mídia (image, document, audio, video)."""
    media_object: dict = {"id": media_id}
    if caption and media_type in ("image", "video", "document"):
        if media_type == "document":
            media_object["caption"] = caption
            media_object["filename"] = caption
        else:
            media_object["caption"] = caption

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/{phone_number_id}/messages",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": media_type,
                media_type: media_object,
            },
        )
        return response.json()


async def fetch_template_body(waba_id: str, token: str, template_name: str, language: str = None) -> str:
    """Busca no Meta o texto do corpo (BODY) de um template aprovado."""
    if not waba_id or not template_name:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{BASE_URL}/{waba_id}/message_templates",
                headers={"Authorization": f"Bearer {token}"},
                params={"name": template_name, "limit": 50},
            )
            data = response.json()
    except Exception:
        return None
    candidates = [t for t in data.get("data", []) if t.get("name") == template_name]
    if language:
        exact = [t for t in candidates if t.get("language") == language]
        if exact:
            candidates = exact
    for t in candidates:
        for comp in t.get("components", []):
            if comp.get("type") == "BODY":
                return comp.get("text", "") or None
    return None


def render_template_text(body: str, params: list = None) -> str:
    """Preenche {{1}}, {{2}}... do corpo com os valores de params."""
    if not body:
        return None
    text = body
    for i, p in enumerate(params or []):
        placeholder = "{{" + str(i + 1) + "}}"
        text = text.replace(placeholder, str(p) if p is not None else "")
    return text


async def create_template(waba_id: str, token: str, name: str, language: str,
                          category: str, components: list, *,
                          allow_category_change: bool = False) -> dict:
    """Cria (submete pra aprovação) um template no WABA. Retorna o JSON do Meta.

    Não levanta exceção: quem chama decide o que fazer com o corpo de erro do Meta
    (precisamos repassar o erro verbatim pra tela).

    `allow_category_change` autoriza a Meta a CORRIGIR a categoria em vez de recusar o
    template quando ela discorda da que pedimos. Sem ele, um corpo que a Meta leia como
    marketing enviado como UTILITY pode voltar rejeitado, e a correção custa uma nova
    submissão — dias de espera.

    Fica DESLIGADO por padrão, e keyword-only: a tela de templates (routes.py:694) manda a
    categoria que o admin escolheu, e ali "a Meta trocou sozinha" é surpresa, não conveniência.
    Ligado nas submissões por script, onde o combinado é aceitar a categoria que vier.
    """
    corpo = {"name": name, "language": language, "category": category,
             "components": components}
    if allow_category_change:
        corpo["allow_category_change"] = True
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{BASE_URL}/{waba_id}/message_templates",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=corpo,
        )
        return response.json()