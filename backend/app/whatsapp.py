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
