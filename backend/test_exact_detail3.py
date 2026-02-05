import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("EXACT_SPOTTER_TOKEN")
BASE_URL = "https://api.exactspotter.com/v3"
headers = {"Content-Type": "application/json", "token_exact": TOKEN}

# Pegar um lead mais antigo com mais dados
res = requests.get(f"{BASE_URL}/Leads", headers=headers, params={"$top": 1, "$filter": "stage eq 'Vendidos'"})
lead = res.json()["value"][0]
lead_id = lead["id"]
print(f"=== LEAD: {lead['lead']} (ID: {lead_id}) ===\n")

# Testar endpoints
endpoints = [
    ("Leads filtrado", f"/Leads?$filter=id eq {lead_id}"),
    ("Persons", f"/Persons?$filter=leadId eq {lead_id}"),
    ("LeadHistories", f"/LeadHistories?$filter=leadId eq {lead_id}"),
    ("QualificationHistories", f"/QualificationHistories?$filter=leadId eq {lead_id}"),
]

for name, ep in endpoints:
    print(f"--- {name} ---")
    r = requests.get(f"{BASE_URL}{ep}", headers=headers)
    print(f"Status: {r.status_code} | Tamanho: {len(r.text)}")
    if r.status_code == 200 and len(r.text) > 5:
        try:
            data = r.json()
            values = data.get("value", [])
            print(f"Registros: {len(values)}")
            if values:
                print(f"Campos: {list(values[0].keys())}")
        except:
            print(f"Resposta: {r.text[:300]}")
    print()
