import asyncio
import os
import httpx
from datetime import datetime
from sqlalchemy import text
from app.database import async_session
from dotenv import load_dotenv
load_dotenv()

RECORDINGS_DIR = "/home/ubuntu/pos-plataform/recordings"
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

async def get_call_info(call_sid: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Calls/{call_sid}.json",
            auth=(ACCOUNT_SID, AUTH_TOKEN),
        )
        return resp.json()

async def backfill():
    files = [f for f in os.listdir(RECORDINGS_DIR) if f.endswith(".mp3")]
    print(f"📁 {len(files)} arquivos encontrados")

    async with async_session() as db:
        for fname in files:
            call_sid = fname.replace(".mp3", "")
            local_path = f"{RECORDINGS_DIR}/{fname}"

            # Tenta achar direto
            result = await db.execute(
                text("SELECT id FROM call_logs WHERE call_sid = :sid"),
                {"sid": call_sid}
            )
            row = result.fetchone()

            # Fallback: busca pelo call mais próximo no tempo
            if not row:
                call_info = await get_call_info(call_sid)
                date_created = call_info.get("date_created", "")
                try:
                    dt = datetime.strptime(date_created, "%a, %d %b %Y %H:%M:%S +0000")
                    result2 = await db.execute(
                        text("""
                            SELECT id, call_sid FROM call_logs
                            WHERE ABS(EXTRACT(EPOCH FROM (created_at - :dt))) < 60
                            ORDER BY ABS(EXTRACT(EPOCH FROM (created_at - :dt)))
                            LIMIT 1
                        """),
                        {"dt": dt}
                    )
                    row2 = result2.fetchone()
                    if row2:
                        print(f"🔁 Match por tempo: {call_sid} -> {row2[1]}")
                        row = row2
                except Exception as e:
                    print(f"❌ Erro parse data: {e}")

            if row:
                await db.execute(
                    text("UPDATE call_logs SET local_recording_path = :path, transcription_status = 'pending' WHERE id = :id"),
                    {"path": local_path, "id": row[0]}
                )
                print(f"✅ Linkado: {fname} -> id {row[0]}")
            else:
                print(f"⚠️ Não encontrado: {call_sid}")

        await db.commit()
        print("✅ Backfill concluído")

asyncio.run(backfill())