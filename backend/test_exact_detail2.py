import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("EXACT_SPOTTER_TOKEN")
BASE_URL = "https://api.exactspotter.com/v3"
headers = {"Content-Type": "application/json", "token_exact": TOKEN}

lead_id = 47250457

endpoints = [
    f"/QualificationHistories?$filter=leadId eq {lead_id}&$orderby=id desc&$top=10",
    f"/LeadHistories?$filter=leadId eq {lead_id}&$orderby=id desc&$top=10",
    f"/Leads?$filter=id eq {lead_id}",
]

for ep in endpoints:
    print(f"--- {ep} ---")
    r = requests.get(f"{BASE_URL}{ep}", headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
    else:
        print(r.text[:500])
    print()
