import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("EXACT_SPOTTER_TOKEN")
BASE_URL = "https://api.exactspotter.com/v3"

headers = {
    "Content-Type": "application/json",
    "token_exact": TOKEN
}

# Pegar um lead ID para testar
res = requests.get(f"{BASE_URL}/Leads", headers=headers, params={"$top": 1, "$orderby": "Id desc"})
lead = res.json()["value"][0]
lead_id = lead["id"]
print(f"=== LEAD: {lead['lead']} (ID: {lead_id}) ===\n")

# Testar endpoints de detalhes
endpoints = [
    f"/Leads({lead_id})",
    f"/QualificationHistories?$filter=leadId eq {lead_id}&$orderby=Id desc&$top=10",
    f"/Persons?$filter=leadId eq {lead_id}",
]

for ep in endpoints:
    print(f"--- {ep} ---")
    r = requests.get(f"{BASE_URL}{ep}", headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(json.dumps(data, indent=2, ensure_ascii=False)[:1500])
    else:
        print(r.text[:500])
    print()
