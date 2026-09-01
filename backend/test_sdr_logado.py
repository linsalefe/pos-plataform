"""S6-3 — o template para de se apresentar com o nome do curso.

    cd backend && venv/bin/python test_sdr_logado.py

NADA sai daqui: cadeia da Meta mockada, banco dublê.

O DEFEITO (RECON_FOLLOWS_HUMANO_IA_20260901, §4.3)
  43 dos 82 envios de `tentativa_contato` (52%) na janela 24/08-01/09 saíram assinados com o
  nome do CURSO. 42 pessoas leram "Ola Daiane, é o PsicologiaEscolar do CENAT ✨".

  A causa foi CONFIRMADA no dado, não deduzida: em TODO envio quebrado o `{{2}}` e o `{{3}}`
  trazem a MESMA string —

      slot2                                 slot3                                  n
      Saúde Mental e Mulheridades           Saúde Mental e Mulheridades           11
      PsicologiaEscolar                     PsicologiaEscolar                      9
      Transtorno do Espectro Autista (TEA)  Transtorno do Espectro Autista (TEA)   7
      Thobias                               Grupos e Oficinas em Saúde Mental     14   <- certo

  Que é exatamente o default posicional de `automacoes/page.tsx:selectTemplate`:
  `i === 1 -> lead_course` e `i === 2 -> lead_course`.

O QUE ESTE TESTE PROVA
  1. `nome_de_quem_enviou` nunca devolve vazio — `{{n}}` em branco é #131008
  2. os TRÊS caminhos de envio assinam certo: campanha, individual e agendado
  3. `{{2}}` deixa de ser igual ao `{{3}}` — a assinatura exata do defeito
  4. `sdr_name` (dono do lead na Exact) continua existindo e continua diferente
  5. o default da TELA lê o corpo do template, e acerta o `tentativa_contato` sem
     estragar o `f5_ligacao` nem o `processo_seletivo_fase`
"""
import asyncio
import io
import pathlib
import re
import subprocess
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Depends

from app import exact_routes
from app.auth import get_current_user
from app.autoria import SDR_PADRAO, nome_de_quem_enviou
from app.models import User

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}")
    if not ok:
        print(f"      obtido={obtido!r} esperado={esperado!r}")
        falhas.append(rotulo)


def u(id, nome):
    return User(id=id, name=nome, email=f"{id}@x", password_hash="x", role="admin")


THOBIAS, VICTORIA = u(5, "Thobias"), u(6, "Victória")
COMO_O_JOB_CHAMA = Depends(get_current_user)


# ==========================================================================================
print("\n1) `nome_de_quem_enviou` — nunca vazio")

checa("usuário logado assina com o próprio nome", nome_de_quem_enviou(VICTORIA), "Victória")
checa("job agendado (objeto Depends) cai no padrão",
      nome_de_quem_enviou(COMO_O_JOB_CHAMA), SDR_PADRAO)
checa("None cai no padrão", nome_de_quem_enviou(None), SDR_PADRAO)
checa("usuário com nome em branco cai no padrão", nome_de_quem_enviou(u(9, "   ")), SDR_PADRAO)
checa("o padrão não é string vazia (#131008)", bool(SDR_PADRAO.strip()), True)


# ==========================================================================================
print("\n2 e 3) Os TRÊS caminhos de envio — e o `{{2}}` deixa de repetir o `{{3}}`")

CANAL = MagicMock(id=1, waba_id="w", whatsapp_token="t", phone_number_id="p")

# O mapeamento que a tela passa a montar sozinha para o `tentativa_contato`:
# {{1}} nome do lead · {{2}} quem está mandando · {{3}} o curso
MAPEAMENTO = [{"type": "lead_name"}, {"type": "sdr_logado"}, {"type": "lead_course"}]


def _lead():
    l = MagicMock()
    l.id, l.name, l.phone1 = 1, "Daiane Souza", "5541999888777"
    l.sub_source = "Pos Psicologia Escolar V3"
    l.sdr_name = "Victória"          # DONO na Exact — de propósito diferente de quem manda
    l.funnel_id = 18535
    return l


def dispara(current_user, mapeamento=MAPEAMENTO, origem_envio="campanha"):
    passo = {"n": 0}

    async def execute(stmt):
        passo["n"] += 1
        r = MagicMock()
        if passo["n"] == 1:
            r.scalars = MagicMock(return_value=MagicMock(
                all=MagicMock(return_value=[_lead()])))
        else:
            r.scalar_one_or_none = MagicMock(return_value=CANAL)
        return r

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    db.add, db.flush, db.commit = MagicMock(), AsyncMock(), AsyncMock()
    envio = AsyncMock(return_value={"messages": [{"id": "wamid.X"}],
                                    "contacts": [{"wa_id": "IGNORADO"}]})
    pedido = {"template_name": "tentativa_contato", "channel_id": 1, "lead_ids": [1],
              "param_mappings": mapeamento, "origem_envio": origem_envio}
    with patch("app.higiene_disparo.por_que_pular", new=AsyncMock(return_value=None)), \
         patch("app.qualificacao_fluxo.estado_de", new=AsyncMock(return_value=None)), \
         patch("app.whatsapp.send_template_message", new=envio), \
         patch("app.whatsapp.fetch_template_body", new=AsyncMock(return_value="Ola {{1}}")), \
         patch("app.whatsapp.render_template_text", new=MagicMock(return_value="Ola X")), \
         patch("app.contatos.contato_existente", new=AsyncMock(return_value=None)), \
         patch.object(exact_routes, "bloquear_se_boas_vindas", new=AsyncMock()), \
         patch("app.exact_routes.resolve_course_name",
               new=AsyncMock(return_value="Psicologia Escolar")), \
         patch("app.sdr_mapping.resolve_sdr_user_id", new=MagicMock(return_value=5)), \
         patch("asyncio.sleep", new=AsyncMock()), \
         patch.object(exact_routes, "_silenciar_agente_apos_envio_manual", new=AsyncMock()):
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(exact_routes.bulk_send_template(pedido, db, current_user))
    # send_template_message(phone, template_name, language, pnid, token, lead_params)
    return envio.await_args.args[5]


for rotulo, quem, esperado in [
    ("campanha (Hub, Thobias logado)", THOBIAS, "Thobias"),
    ("individual (Hub, Victória logada)", VICTORIA, "Victória"),
    ("agendado (sem sessão)", COMO_O_JOB_CHAMA, SDR_PADRAO),
]:
    params = dispara(quem, origem_envio="individual" if "individual" in rotulo else "campanha")
    checa(f"{rotulo}: {{{{1}}}} = primeiro nome do lead", params[0], "Daiane")
    checa(f"  {{{{2}}}} = quem está mandando", params[1], esperado)
    checa(f"  {{{{3}}}} = o curso", params[2], "Psicologia Escolar")
    checa("  e {{2}} NÃO é igual a {{3}} — a assinatura exata do defeito",
          params[1] == params[2], False)

print()
params = dispara(THOBIAS, mapeamento=[{"type": "lead_name"}, {"type": "sdr_name"},
                                      {"type": "lead_course"}])
checa("`sdr_name` continua sendo o DONO do lead na Exact", params[1], "Victória")
checa("  e é mesmo outra pessoa que a logada (Thobias)", params[1] != "Thobias", True)


# ==========================================================================================
print("\n5) O default da TELA lê o corpo do template")
#
# O regex vive em `automacoes/page.tsx`. Aqui ele é LIDO DE LÁ e conferido contra a cópia
# usada no teste: se alguém mexer no tsx e não vier aqui, isto quebra em vez de mentir.

TSX = pathlib.Path("../frontend/src/app/automacoes/page.tsx")
fonte = TSX.read_text()
m = re.search(r"const APRESENTACAO = (/.*/i);", fonte)
checa("o regex foi encontrado no page.tsx", m is not None, True)

REGEX_JS = m.group(1) if m else "/$^/"

# Corpos RECONSTRUÍDOS a partir do texto renderizado no banco (a Meta é quem guarda os
# originais com `{{n}}`; `messages.content` só tem o renderizado). As frases são verbatim.
CORPOS = {
    "tentativa_contato": (
        "Ola {{1}}, é o {{2}} do CENAT ✨\n"
        "Tentei realizar uma nova tentativa de contato referente a sua aplicação na "
        "Pós Graduação {{3}} mas até o momento não tive sucesso 🥺"),
    # ARMADILHA DE PROPÓSITO: o corpo CONTÉM "é a", mas longe do placeholder.
    "f5_ligacao": (
        "Olá {{1}}, tudo bem? 🌻\n"
        "Fiz uma nova tentativa de contato, mas ainda sem sucesso, essa ligação é a "
        "primeira etapa do seu processo seletivo da {{2}}"),
    "processo_seletivo_fase": (
        "Olá,{{1}} ! Tudo bem?  Aqui é Thobias , do CENAT ✨\n"
        "Você participou do processo seletivo para a {{2}}, estamos finalizando a campanha"),
    "f3_guia_ementa": (
        "Olá {{1}}, tudo bem? ✨\n"
        "Segue abaixo o link de acesso à ementa da Pós-Graduação {{2}}"),
}
ESPERADO = {
    "tentativa_contato": ["lead_name", "sdr_logado", "lead_course"],
    "f5_ligacao": ["lead_name", "lead_course"],
    "processo_seletivo_fase": ["lead_name", "lead_course"],
    "f3_guia_ementa": ["lead_name", "lead_course"],
}

script = """
const APRESENTACAO = %s;
const tipoPadrao = (body, i) => {
  if (i === 0) return 'lead_name';
  const antes = (body || '').split(`{{${i + 1}}}`)[0] || '';
  if (APRESENTACAO.test(antes.slice(-24))) return 'sdr_logado';
  return i <= 2 ? 'lead_course' : 'fixed_text';
};
const corpos = %s;
const out = {};
for (const [nome, body] of Object.entries(corpos)) {
  const n = (body.match(/\\{\\{\\d+\\}\\}/g) || []).length;
  out[nome] = Array.from({length: n}, (_, i) => tipoPadrao(body, i));
}
console.log(JSON.stringify(out));
""" % (REGEX_JS, __import__("json").dumps(CORPOS, ensure_ascii=False))

try:
    saida = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                           timeout=30, check=True).stdout
    obtido = __import__("json").loads(saida)
    for nome, esperado in ESPERADO.items():
        checa(f"{nome}: {esperado}", obtido.get(nome), esperado)
    checa("  o `tentativa_contato` deixou de mandar curso no slot de pessoa",
          obtido["tentativa_contato"][1], "sdr_logado")
    checa("  e o `f5_ligacao` NÃO foi contaminado pelo 'é a' distante do placeholder",
          obtido["f5_ligacao"][1], "lead_course")
except FileNotFoundError:
    print("  [pulado] node não disponível — o default da tela não foi exercitado")
except subprocess.CalledProcessError as e:
    print(f"  [FALHOU] node: {e.stderr[:300]}")
    falhas.append("default da tela")


# ==========================================================================================
print("\n" + "=" * 78)
if falhas:
    print(f"❌ {len(falhas)} falha(s): {falhas}")
    raise SystemExit(1)
print("✅ Todos passaram. Nada enviado, nada gravado.")
