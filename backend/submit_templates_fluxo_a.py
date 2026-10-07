"""Submete à Meta os 7 templates do Fluxo A (confirmação de reunião) e o D0 do no-show.

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python submit_templates_fluxo_a.py           # dry-run
    cd /home/ubuntu/pos-plataform/backend && venv/bin/python submit_templates_fluxo_a.py --apply   # submete

DRY-RUN POR PADRÃO: valida e imprime os 7 JSONs, sem chamar a Meta e sem gravar nada. Só
`--apply` submete, grava em `whatsapp_templates` e relê o status na Meta.

==========================================================================================
DE ONDE VEM O TEXTO
==========================================================================================
Spec da Isa, "IA de Confirmação e No-show" (28/09/2026), seção "Textos", páginas 7 e 8
(`Otimização IA - No show (validar).pdf`, na raiz do repo). Ajustes permitidos e feitos, e só
estes (SPRINT_TEMPLATES_FLUXO_A_20261007_REPORT.md lista um a um):

  * "Oi, " na frente quando o corpo começaria com `{{1}}`: a Meta recusa body que começa ou
    termina com variável (RECON_CONFIRMACAO_NOSHOW_20261007 §3.3);
  * `{dia}, {data}` da confirmação viram UM parâmetro ("quinta-feira, 09/10"): menos variável,
    menos recusa por proporção de variável por palavra;
  * `{saudação}` do pedido cai (o corpo não pode começar com variável);
  * `{link}` da ementa sai do corpo e vira botão URL com sufixo dinâmico, padrão dos `f3_guia*`;
  * "Escolher novo horário" (21 caracteres) vira "Escolher horário" (16);
  * `nat_ns_d0_corte` ganha "Oi, {{1}}." (a spec não tinha nome; corpo 100% fixo com botão de
    marketing é o perfil mais recusado).

==========================================================================================
CATEGORIA
==========================================================================================
UTILITY para confirmação, pedido, último aviso e 30 min antes; MARKETING para ementa,
benefício e corte. Todos com `allow_category_change=True` (`whatsapp.create_template`): a Meta
pode reclassificar em vez de recusar, e a categoria final é a que ela devolver. O script
registra a pedida e a devolvida.

==========================================================================================
O QUE ESTE SCRIPT NÃO FAZ
==========================================================================================
Não envia mensagem a ninguém, não toca `nat_lembrete_reuniao` (que segue aprovado e em uso
até o Bloco 1), e não muda fluxo. O payload dos botões NÃO entra na definição do template: ele
é fixado no envio (`send_template_message(button_payloads=...)`), e está em `PAYLOADS` aqui e
em `nat_copy.py` só para o Bloco 1 usar.

Nunca imprime o token.
"""
import argparse
import asyncio
import json
import re
import sys

import httpx
from sqlalchemy import select

from app import nat_copy
from app.database import async_session
from app.models import AutoWelcomeConfig, Channel, WhatsappTemplate
from app.whatsapp import BASE_URL, create_template

IDIOMA = "pt_BR"
LIMITE_BODY = 1024
LIMITE_BOTAO = 20

# Id real de ementa, do botão URL do template `f3_guiatea` aprovado na Meta (lido em 07/10).
EXEMPLO_URL_EMENTA = "https://drive.google.com/file/d/1tv9smwk9AHcj9TefufQVL1SweoMbhvCj/view"


def _body(texto: str, exemplo: list[str]) -> dict:
    comp = {"type": "BODY", "text": texto}
    if exemplo:
        comp["example"] = {"body_text": [exemplo]}
    return comp


def _quick(nome: str) -> dict:
    """Os quick replies do template, na ordem de `nat_copy.BOTOES_FLUXO_A`."""
    return {"type": "BUTTONS",
            "buttons": [{"type": "QUICK_REPLY", "text": b["titulo"]}
                        for b in nat_copy.BOTOES_FLUXO_A[nome]]}


C = nat_copy.CORPO_SUBMETIDO_FLUXO_A

# O TEXTO VEM DE `nat_copy.CORPO_SUBMETIDO_FLUXO_A`, não é redigitado aqui: o que fica no
# código para o Bloco 1 usar é, por construção, o que foi submetido. Aqui só os exemplos e a
# forma de cada template.
TEMPLATES = [
    {"name": nat_copy.NAT_A_CONFIRMACAO, "category": "UTILITY", "components": [
        _body(C[nat_copy.NAT_A_CONFIRMACAO],
              ["Ana", "Saúde Mental", "quinta-feira, 09/10", "14:30", "Victória"]),
        _quick(nat_copy.NAT_A_CONFIRMACAO)]},
    {"name": nat_copy.NAT_A_EMENTA, "category": "MARKETING", "components": [
        _body(C[nat_copy.NAT_A_EMENTA], ["Ana", "Saúde Mental", "quinta-feira", "14:30"]),
        {"type": "BUTTONS", "buttons": [
            {"type": "URL", "text": "Ementa da Pós",
             "url": "https://drive.google.com/file/d/{{1}}",
             "example": [EXEMPLO_URL_EMENTA]}]}]},
    {"name": nat_copy.NAT_A_BENEFICIO, "category": "MARKETING", "components": [
        _body(C[nat_copy.NAT_A_BENEFICIO], ["Ana"])]},
    {"name": nat_copy.NAT_A_PEDIDO_CONFIRMACAO, "category": "UTILITY", "components": [
        _body(C[nat_copy.NAT_A_PEDIDO_CONFIRMACAO], ["Ana", "Victória", "amanhã", "10:00"]),
        _quick(nat_copy.NAT_A_PEDIDO_CONFIRMACAO)]},
    {"name": nat_copy.NAT_A_ULTIMO_AVISO, "category": "UTILITY", "components": [
        _body(C[nat_copy.NAT_A_ULTIMO_AVISO], ["Ana", "14:30", "10:30"]),
        _quick(nat_copy.NAT_A_ULTIMO_AVISO)]},
    {"name": nat_copy.NAT_A_30MIN, "category": "UTILITY", "components": [
        _body(C[nat_copy.NAT_A_30MIN], ["Ana", "Victória", "(11) 91234-5678"])]},
    {"name": nat_copy.NAT_NS_D0_CORTE, "category": "MARKETING", "components": [
        _body(C[nat_copy.NAT_NS_D0_CORTE], ["Ana"]),
        _quick(nat_copy.NAT_NS_D0_CORTE)]},
]

# Payload por MENSAGEM, não por intenção. Ordem = índice do botão. Usado só no envio (Bloco 1).
PAYLOADS = {nome: [b["payload"] for b in botoes]
            for nome, botoes in nat_copy.BOTOES_FLUXO_A.items()}

_VAR = re.compile(r"\{\{\s*(\d+)\s*\}\}")


class TemplateInvalido(Exception):
    pass


def validar(t: dict) -> None:
    """Os 5 checks da sprint, mais nome e coerência de payload. Levanta com mensagem clara."""
    nome = t["name"]
    if not re.fullmatch(r"[a-z0-9_]+", nome):
        raise TemplateInvalido(f"{nome}: nome fora de snake_case minúsculo")
    if t["category"] not in ("UTILITY", "MARKETING"):
        raise TemplateInvalido(f"{nome}: categoria {t['category']!r}")
    bodies = [c for c in t["components"] if c["type"] == "BODY"]
    if len(bodies) != 1:
        raise TemplateInvalido(f"{nome}: precisa de exatamente 1 BODY")
    body = bodies[0]["text"]
    if len(body) > LIMITE_BODY:
        raise TemplateInvalido(f"{nome}: body com {len(body)} caracteres (limite {LIMITE_BODY})")
    if _VAR.match(body.strip()):
        raise TemplateInvalido(f"{nome}: body começa com variável")
    # Pontuação final NÃO conta como texto para a Meta: "às {{4}}!" foi recusado em 07/10
    # (nat_a_ementa, subcode 2388299, "As variáveis não podem estar no início ou no fim").
    if re.search(r"\{\{\s*\d+\s*\}\}[\s!?.,;:)]*$", body):
        raise TemplateInvalido(f"{nome}: body termina com variável (pontuação não conta)")
    nums = sorted({int(n) for n in _VAR.findall(body)})
    if nums != list(range(1, len(nums) + 1)):
        raise TemplateInvalido(f"{nome}: variáveis fora de sequência {nums}")
    exemplo = (bodies[0].get("example") or {}).get("body_text") or [[]]
    if len(exemplo[0]) != len(nums) or any(not str(e).strip() for e in exemplo[0]):
        raise TemplateInvalido(f"{nome}: {len(nums)} variável(is) e {len(exemplo[0])} "
                               "exemplo(s) — precisa de 1 exemplo não vazio por variável")
    if "—" in body:
        raise TemplateInvalido(f"{nome}: travessão no corpo")
    botoes = [b for c in t["components"] if c["type"] == "BUTTONS" for b in c["buttons"]]
    for b in botoes:
        if len(b["text"]) > LIMITE_BOTAO:
            raise TemplateInvalido(f"{nome}: botão {b['text']!r} com {len(b['text'])} "
                                   f"caracteres (limite {LIMITE_BOTAO})")
        if b["type"] == "URL":
            vars_url = _VAR.findall(b["url"])
            if vars_url and (vars_url != ["1"] or not b["url"].endswith("{{1}}")):
                raise TemplateInvalido(f"{nome}: URL dinâmica só aceita {{{{1}}}} no fim")
            if vars_url and not b.get("example"):
                raise TemplateInvalido(f"{nome}: URL dinâmica sem example")
    quick = [b for b in botoes if b["type"] == "QUICK_REPLY"]
    if nome in PAYLOADS and len(PAYLOADS[nome]) != len(quick):
        raise TemplateInvalido(f"{nome}: {len(PAYLOADS[nome])} payload(s) para "
                               f"{len(quick)} quick reply")


async def _canal(db):
    """O canal da NAT: `auto_welcome_config.channel_id`, a mesma leitura de
    `nat_sender._resolver_canal`. (`nat_config` não tem coluna de canal.)"""
    cfg = (await db.execute(select(AutoWelcomeConfig).where(
        AutoWelcomeConfig.id == 1))).scalar_one_or_none()
    if cfg is None or cfg.channel_id is None:
        raise SystemExit("auto_welcome_config sem channel_id — não sei qual WABA usar")
    canal = (await db.execute(select(Channel).where(
        Channel.id == cfg.channel_id))).scalar_one_or_none()
    if canal is None or not canal.waba_id:
        raise SystemExit(f"canal {cfg.channel_id} sem waba_id")
    return canal


async def _status_na_meta(canal, nome: str) -> dict | None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{BASE_URL}/{canal.waba_id}/message_templates",
            headers={"Authorization": f"Bearer {canal.whatsapp_token}"},
            params={"name": nome, "fields": "id,name,language,status,category,"
                                            "rejected_reason", "limit": 50})
    for t in resp.json().get("data", []):
        if t.get("name") == nome and t.get("language") == IDIOMA:
            return t
    return None


async def _gravar(db, canal, t: dict, meta: dict) -> None:
    """Idempotente por (channel_id, name, language): atualiza se já existe."""
    linha = (await db.execute(select(WhatsappTemplate).where(
        WhatsappTemplate.channel_id == canal.id, WhatsappTemplate.name == t["name"],
        WhatsappTemplate.language == IDIOMA))).scalars().first()
    if linha is None:
        linha = WhatsappTemplate(channel_id=canal.id, name=t["name"], language=IDIOMA,
                                 created_by_name="submit_templates_fluxo_a.py")
        db.add(linha)
    linha.category = meta.get("category") or t["category"]
    linha.components = json.dumps(t["components"], ensure_ascii=False)
    if meta.get("id"):
        linha.meta_template_id = str(meta["id"])
    linha.status = meta.get("status") or linha.status or "PENDING"
    linha.rejected_reason = meta.get("rejected_reason")


async def main(aplicar: bool, somente: list[str] | None = None) -> int:
    if somente:
        desconhecidos = set(somente) - {t["name"] for t in TEMPLATES}
        if desconhecidos:
            raise SystemExit(f"--somente com nome(s) desconhecido(s): {sorted(desconhecidos)}")
    escolhidos = [t for t in TEMPLATES if not somente or t["name"] in somente]
    for t in TEMPLATES:
        validar(t)
    print(f"✅ validação local: {len(TEMPLATES)} templates OK\n")

    for t in escolhidos:
        corpo = {"name": t["name"], "language": IDIOMA, "category": t["category"],
                 "allow_category_change": True, "components": t["components"]}
        print(f"===== {t['name']} ({t['category']})"
              f"{'  payloads=' + str(PAYLOADS[t['name']]) if t['name'] in PAYLOADS else ''}")
        print(json.dumps(corpo, ensure_ascii=False, indent=2))
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
            erro = resp.get("error")
            if erro and not resp.get("id"):
                # Já existe na Meta (reexecução)? Então o status vem da leitura abaixo.
                print(f"   ⚠️ a Meta recusou a criação: "
                      f"{erro.get('error_user_msg') or erro.get('message')}")
            meta = await _status_na_meta(canal, t["name"]) or {}
            if not meta:
                falhas += 1
                print(f"   ❌ {t['name']} não existe na Meta depois da submissão")
                continue
            meta.setdefault("id", resp.get("id"))
            await _gravar(db, canal, t, meta)
            print(f"   status={meta.get('status')} categoria pedida={t['category']} "
                  f"devolvida={meta.get('category')} id={meta.get('id')}"
                  f"{' motivo=' + str(meta.get('rejected_reason')) if meta.get('rejected_reason') not in (None, 'NONE') else ''}")
            if meta.get("status") not in ("PENDING", "APPROVED"):
                falhas += 1
        await db.commit()
    print(f"\n{'✅' if not falhas else '❌'} {len(escolhidos) - falhas}/{len(escolhidos)} "
          "em PENDING ou APPROVED")
    return 1 if falhas else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="submete à Meta e grava")
    p.add_argument("--somente", nargs="+", metavar="NOME",
                   help="submete só estes templates (ressubmissão de um recusado)")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.apply, a.somente)))
