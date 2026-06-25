import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from app import exact_spotter
from app import whatsapp

async def main():
    # NEGATIVO: funil não-pós (Intercambio 18285) -> welcome NÃO pode enviar (guardrail no topo, db nem é tocado)
    with patch.object(exact_spotter, "send_template_message", new=AsyncMock(return_value={})) as spy:
        await exact_spotter.send_welcome_to_new_lead(
            {"name": "X", "phone1": "5583999999999", "funnel_id": 18285, "sub_source": "interuk"}, db=None)
        assert spy.call_count == 0, "FALHOU: welcome disparou pra funil NÃO-pós!"

    # POSITIVO: funil pós (18535) -> guardrail passa e TENTA enviar (send mockado retorna {} sem 'messages',
    # então a função retorna antes de escrever no banco). Prova que pós continua recebendo welcome.
    fake_channel = MagicMock(waba_id="w", whatsapp_token="t", phone_number_id="p")
    exec_res = MagicMock(); exec_res.scalar_one_or_none.return_value = fake_channel
    fake_db = MagicMock(); fake_db.execute = AsyncMock(return_value=exec_res)
    with patch.object(exact_spotter, "send_template_message", new=AsyncMock(return_value={})) as spy, \
         patch.object(whatsapp, "fetch_template_body", new=AsyncMock(return_value="Olá {{1}}")):
        await exact_spotter.send_welcome_to_new_lead(
            {"name": "Y", "phone1": "5583988888888", "funnel_id": 18535, "sub_source": "pospsi"}, fake_db)
        assert spy.call_count == 1, "FALHOU: welcome NÃO tentou enviar pra pós"

    print("OK guardrail: não-pós bloqueado (0 envios), pós passou (1 tentativa) — sem envio real, sem escrita.")

asyncio.run(main())
