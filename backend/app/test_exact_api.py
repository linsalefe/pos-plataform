import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("EXACT_SPOTTER_TOKEN")
BASE_URL = "https://api.exactspotter.com/v3"

headers = {
    "Content-Type": "application/json",
    "token_exact": TOKEN
}

# Buscar leads do funil 18537
response = requests.get(
    f"{BASE_URL}/Leads",
    headers=headers,
    params={
        "$filter": "funnelId eq 18537",
        "$top": 10,
        "$orderby": "Id desc"
    }
)

data = response.json()
leads = data.get("value", [])

print(f"=== FUNIL 18537 ({len(leads)} leads) ===")
for lead in leads:
    ss = lead.get("subSource", {})
    print(f"  Lead: {lead['lead']} | SubSource: {ss.get('value', 'N/A')} | Stage: {lead['stage']}")