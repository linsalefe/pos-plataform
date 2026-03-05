import asyncio
import os
import httpx
from sqlalchemy import text
from app.database import async_session

RECORDINGS_DIR = "/home/ubuntu/pos-plataform/recordings"
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

async def get_parent_sid(call_sid: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Calls/{call_sid}.json",
            auth=(ACCOUNT_SID, AUTH_TOKEN),
        )
        data = resp.json()
        return data.get("parent_call_sid", "")

async def backfill():
    files = [f for f in os.listdir(RECORDINGS_DIR) if f.endswith(".mp3")]
    print(f"📁 {len(files)} arquivos encontrados")

    async with async_session() as db:
        for fname in files:
            call_sid = fname.replace(".mp3", "")
            local_path = f"{RECORDINGS_DIR}/{fname}"

            result = await db.execute(
                text("SELECT id FROM call_logs WHERE call_sid = :sid"),
                {"sid": call_sid}
            )
            row = result.fetchone()

            if not row:
                parent_sid = await get_parent_sid(call_sid)
                print(f"🔁 {call_sid} -> parent: {parent_sid}")
                if parent_sid:
                    result = await db.execute(
                        text("SELECT id FROM call_logs WHERE call_sid = :sid"),
                        {"sid": parent_sid}
                    )
                    row = result.fetchone()

            if row:
                await db.execute(
                    text("UPDATE call_logs SET local_recording_path = :path, transcription_status = 'pending' WHERE id = :id"),
                    {"path": local_path, "id": row[0]}
                )
                print(f"✅ Linkado: {fname} -> id {row[0]}")
            else:
                print(f"⚠️ Não encontrado no banco: {call_sid}")

        await db.commit()
        print("✅ Backfill concluído")

asyncio.run(backfill())