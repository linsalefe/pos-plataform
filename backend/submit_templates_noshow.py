"""Submete à Meta os templates da régua de no-show D0+1h a D8 (Bloco 2, 07/10/2026).

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python submit_templates_noshow.py           # dry-run
    cd /home/ubuntu/pos-plataform/backend && venv/bin/python submit_templates_noshow.py --apply   # submete
    ... --apply --somente nat_ns_d1                                                               # ressubmete um

Mesmo molde de `submit_templates_fluxo_a.py`, e reaproveita dele a validação, a leitura do
canal, a gravação em `whatsapp_templates` e a releitura de status (uma regra, um lugar: a
recusa de 07/10 por "variável no fim" já está corrigida lá).

DE ONDE VEM O TEXTO: `nat_copy.CORPO_SUBMETIDO_NOSHOW`, copiado da spec da Isa ("Régua de
no-show", págs. 8 a 10). Ajustes em relação ao PDF: SPRINT_BLOCO2_NOSHOW_20261007_REPORT.md.

Todos MARKETING, com `allow_category_change=True`. Nunca imprime o token. Não envia nada a lead.
"""
import argparse
import asyncio
import json
import sys

from app import nat_copy
from app.database import async_session
from app.whatsapp import create_template
from submit_templates_fluxo_a import (IDIOMA, TemplateInvalido, _canal, _gravar,
                                      _status_na_meta, validar)

# Exemplos de URL: ids REAIS dos botões aprovados na Meta (lidos em 07/10). O áudio é o do
# `f4_audiotea`; o conteúdo usa o mesmo formato de link do Drive.
EXEMPLO_URL_AUDIO = "https://drive.google.com/file/d/1ZhOIf5MOMWQRSKcmT4bFgEdDK4a1B73I/view"
EXEMPLO_URL_CONTEUDO = "https://drive.google.com/file/d/1tv9smwk9AHcj9TefufQVL1SweoMbhvCj/view"
EXEMPLO_URL = {nat_copy.NAT_NS_D2_AUDIO: EXEMPLO_URL_AUDIO,
               nat_copy.NAT_NS_D5_CONTEUDO: EXEMPLO_URL_CONTEUDO}

EXEMPLOS = {
    nat_copy.NAT_NS_D0_1H: ["Ana"],
    nat_copy.NAT_NS_D0_8H: ["Ana", "Saúde Mental"],
    nat_copy.NAT_NS_D1: ["Ana", "Saúde Mental", "hoje 14h15, 16h30 ou amanhã 10h00"],
    nat_copy.NAT_NS_D2_AUDIO: ["Ana", "Saúde Mental"],
    nat_copy.NAT_NS_D3_SEMINARIO: ["Ana", "21/10", "19h", "Saúde Mental e Território"],
    nat_copy.NAT_NS_D5_CONTEUDO: ["Ana", "Saúde Mental", "O cuidado em liberdade na RAPS"],
    nat_copy.NAT_NS_D7_CONDICAO: ["Ana", "Saúde Mental", "isenção da matrícula e 10% de "
                                  "desconto na primeira mensalidade", "sexta-feira, 24/10"],
    nat_copy.NAT_NS_D8_ENCERRAMENTO: ["Ana", "Saúde Mental"],
}


def _template(nome: str) -> dict:
    """BODY com exemplo + BUTTONS (quick replies primeiro, botão URL depois, se houver)."""
    comps = [{"type": "BODY", "text": nat_copy.CORPO_SUBMETIDO_NOSHOW[nome],
              "example": {"body_text": [EXEMPLOS[nome]]}}]
    botoes = [{"type": "QUICK_REPLY", "text": b["titulo"]}
              for b in nat_copy.BOTOES_NOSHOW.get(nome, [])]
    if nome in nat_copy.BOTAO_URL_NOSHOW:
        botoes.append({"type": "URL", "text": nat_copy.BOTAO_URL_NOSHOW[nome],
                       "url": "https://drive.google.com/file/d/{{1}}",
                       "example": [EXEMPLO_URL[nome]]})
    if botoes:
        comps.append({"type": "BUTTONS", "buttons": botoes})
    return {"name": nome, "category": "MARKETING", "components": comps}


TEMPLATES = [_template(n) for n in nat_copy.CORPO_SUBMETIDO_NOSHOW]
PAYLOADS = {n: [b["payload"] for b in bs] for n, bs in nat_copy.BOTOES_NOSHOW.items()}


def validar_noshow(t: dict) -> None:
    validar(t)
    quick = [b for c in t["components"] if c["type"] == "BUTTONS"
             for b in c["buttons"] if b["type"] == "QUICK_REPLY"]
    if len(PAYLOADS.get(t["name"], [])) != len(quick):
        raise TemplateInvalido(f"{t['name']}: {len(PAYLOADS.get(t['name'], []))} payload(s) "
                               f"para {len(quick)} quick reply")


async def main(aplicar: bool, somente: list[str] | None) -> int:
    if somente and set(somente) - {t["name"] for t in TEMPLATES}:
        raise SystemExit(f"--somente com nome desconhecido: "
                         f"{sorted(set(somente) - {t['name'] for t in TEMPLATES})}")
    escolhidos = [t for t in TEMPLATES if not somente or t["name"] in somente]
    for t in TEMPLATES:
        validar_noshow(t)
    print(f"✅ validação local: {len(TEMPLATES)} templates OK\n")
    for t in escolhidos:
        print(f"===== {t['name']} ({t['category']})"
              f"{'  payloads=' + str(PAYLOADS[t['name']]) if t['name'] in PAYLOADS else ''}")
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
