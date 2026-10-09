"""Submete à Meta o template de alerta do sistema `alerta_cenat_hub` (09/10/2026).

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python submit_template_alerta.py           # dry-run
    cd /home/ubuntu/pos-plataform/backend && venv/bin/python submit_template_alerta.py --apply   # submete

Cópia de `submit_templates_sdr.py`. Texto em `saude_sistema.CORPO_ALERTA`: o pedido era
"Alerta do Cenat Hub: {{1}}", mas a Meta recusa variável no fim (subcode 2388299, 07/10), por
isso a frase fixa depois. UTILITY, `allow_category_change=True`, sem botões. Não envia nada.
"""
import argparse
import asyncio
import json
import sys

from app import saude_sistema
from app.database import async_session
from app.whatsapp import create_template
from submit_templates_fluxo_a import IDIOMA, _canal, _gravar, _status_na_meta, validar

TEMPLATES = [{"name": saude_sistema.TEMPLATE_ALERTA, "category": "UTILITY", "components": [
    {"type": "BODY", "text": saude_sistema.CORPO_ALERTA,
     "example": {"body_text": [saude_sistema.EXEMPLO_ALERTA]}}]}]


async def main(aplicar: bool, somente: list[str] | None) -> int:
    nomes = {t["name"] for t in TEMPLATES}
    if somente and set(somente) - nomes:
        raise SystemExit(f"--somente com nome desconhecido: {sorted(set(somente) - nomes)}")
    escolhidos = [t for t in TEMPLATES if not somente or t["name"] in somente]
    for t in TEMPLATES:
        validar(t)
    print(f"✅ validação local: {len(TEMPLATES)} templates OK\n")
    for t in escolhidos:
        print(f"===== {t['name']} ({t['category']})")
        print(json.dumps({"name": t["name"], "language": IDIOMA, "category": t["category"],
                          "allow_category_change": True, "components": t["components"]},
                         ensure_ascii=False, indent=2))
        print()
    if not aplicar:
        print("DRY-RUN: nada foi enviado à Meta nem gravado. Use --apply para submeter.")
        return 0
    falhas = 0
    async with async_session() as db:
        canal = await _canal(db)
        print(f"Canal {canal.id} (WABA …{canal.waba_id[-4:]})\n")
        for t in escolhidos:
            resp = await create_template(canal.waba_id, canal.whatsapp_token, t["name"],
                                         IDIOMA, t["category"], t["components"],
                                         allow_category_change=True)
            print(f"→ {t['name']}: {json.dumps(resp, ensure_ascii=False)}")
            if resp.get("error") and not resp.get("id"):
                e = resp["error"]
                print(f"   ⚠️ a Meta recusou a criação: {e.get('error_user_msg') or e.get('message')}")
            meta = await _status_na_meta(canal, t["name"]) or {}
            if not meta:
                falhas += 1
                print(f"   ❌ {t['name']} não existe na Meta depois da submissão")
                continue
            meta.setdefault("id", resp.get("id"))
            await _gravar(db, canal, t, meta)
            print(f"   status={meta.get('status')} pedida={t['category']} "
                  f"devolvida={meta.get('category')} id={meta.get('id')}")
            if meta.get("status") not in ("PENDING", "APPROVED"):
                falhas += 1
        await db.commit()
    print(f"\n{'✅' if not falhas else '❌'} {len(escolhidos) - falhas}/{len(escolhidos)} "
          "em PENDING ou APPROVED")
    return 1 if falhas else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--somente", nargs="+", metavar="NOME")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.apply, a.somente)))
