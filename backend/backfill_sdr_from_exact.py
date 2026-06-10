import asyncio
import re
from sqlalchemy import select
from app.database import async_session
from app.models import Contact, ExactLead
from app.sdr_mapping import resolve_sdr_user_id


def canon(num):
    d = re.sub(r"\D", "", num or "")
    if d.startswith("55"):
        d = d[2:]
    if len(d) == 11 and d[2] == "9":
        d = d[:2] + d[3:]
    return d if len(d) == 10 else None


async def main():
    async with async_session() as db:
        leads = (await db.execute(select(ExactLead.phone1, ExactLead.phone2, ExactLead.sdr_name))).all()
        canon_users = {}
        for phone1, phone2, sdr in leads:
            uid = resolve_sdr_user_id(sdr)
            if uid is None:
                continue
            for ph in (phone1, phone2):
                k = canon(ph)
                if k:
                    canon_users.setdefault(k, set()).add(uid)
        safe_map = {k: next(iter(v)) for k, v in canon_users.items() if len(v) == 1}

        contacts = (await db.execute(select(Contact).where(Contact.assigned_to.is_(None)))).scalars().all()
        assigned = 0
        ambiguos = 0
        sem_match = 0
        for c in contacts:
            k = canon(c.wa_id)
            if k and k in safe_map:
                c.assigned_to = safe_map[k]
                assigned += 1
            elif k and k in canon_users:
                ambiguos += 1
            else:
                sem_match += 1
        await db.commit()
        print(f"Backfill -> atribuidos={assigned} | ambiguos_pulados={ambiguos} | sem_match={sem_match} | total_sem_sdr={len(contacts)}")


if __name__ == "__main__":
    asyncio.run(main())
