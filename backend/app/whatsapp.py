import httpx

BASE_URL = "https://graph.facebook.com/v22.0"


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


async def send_template_message(to: str, template_name: str, language: str, phone_number_id: str, token: str, parameters: list = None) -> dict:
    template_data = {
        "name": template_name,
        "language": {"code": language},
    }

    if parameters:
        template_data["components"] = [
            {
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in parameters],
            }
        ]

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