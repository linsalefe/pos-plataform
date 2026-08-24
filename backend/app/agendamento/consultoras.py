"""Quem atende a reunião. Uma ou várias consultoras, cada uma com a própria grade.

------------------------------------------------------------------------------------------
POR QUE ISTO DEIXOU DE SER UMA CONSTANTE
------------------------------------------------------------------------------------------
O módulo nasceu com `sales_rep_email` fixo em `comercial@cenatcursos.com.br` — que é a
**pré-venda** (SDR). As reuniões da landing page são de **venda**, e vão para as consultoras.
Como são mais de uma, o horário deixa de ser "livre ou ocupado" e passa a ser "livre para
quem".

Isso muda três coisas, e as três estão implementadas aqui e em `disponibilidade.py`:

  * `/slots` mostra a **união** das grades. Um horário aparece se ao menos uma consultora
    pode atendê-lo.
  * `/agendar` **escolhe** entre as que estão livres naquele horário, pela menor carga do
    dia (`escolher`).
  * `Boxes are occupied` numa consultora deixa de ser 409 imediato: o fluxo tenta a próxima
    antes de desistir. Ver `agendar.py`.

------------------------------------------------------------------------------------------
COMO CONFIGURAR
------------------------------------------------------------------------------------------
    AGENDAMENTO_CONSULTORAS='[{"email":"fulana@cenatcursos.com.br",
                               "nome_exibicao":"Fulana",
                               "grade":{"janelas":{"0":[["09:30","12:00"]]}}}]'
    AGENDAMENTO_CONSULTORAS_PATH=/etc/cenat/consultoras.json

A `grade` de cada uma aceita as mesmas chaves de `grade.GRADE_PADRAO` e herda o que não
vier — na prática só `janelas` costuma variar, porque duração e antecedência são política do
produto, não da pessoa.

**Sem o env, o módulo se comporta exatamente como antes**: uma única consultora, montada a
partir de `grade()`, com o `sales_rep_email` que já estava lá. É o que mantém a LP de
Mulheridades no ar sem tocar em nada.

O `sales_rep_email` de dentro da grade de uma consultora é IGNORADO e sobrescrito pelo
`email` dela. Duas fontes para o mesmo dado é convite para divergirem.

------------------------------------------------------------------------------------------
A VALIDAÇÃO DE STARTUP NÃO DERRUBA O PROCESSO
------------------------------------------------------------------------------------------
`validar_contra_exact()` confere cada e-mail em `GET /Sellers`. Um e-mail errado faria todo
`BoxesAdd` falhar com `SDR not found` (FINDINGS §2) — erro que o visitante veria como "não
consegui agendar", sem ninguém entender por quê. Melhor descobrir no boot.

Mas o backend serve o Hub, o webhook da Meta e a NAT. Derrubar tudo isso porque o CRM
respondeu estranho seria trocar um problema por um bem maior. Então:

  * e-mail que a Exact diz **não existir ou estar inativo** -> consultora sai de rotação,
    log em ERRO;
  * **Exact inacessível** -> ninguém sai de rotação. Não dá para distinguir "inválida" de
    "não consegui perguntar", e chutar aqui tiraria a LP do ar por causa de um timeout;
  * **nenhuma sobrou válida** -> log CRÍTICO. `/slots` passa a devolver `fallback:true` e a
    LP cai no "deixe seu contato", que é o degrade correto.
"""
import json
import os
from dataclasses import dataclass

from app.agendamento.grade import GRADE_PADRAO, Grade, grade


@dataclass(frozen=True)
class Consultora:
    """Uma consultora e a grade dela. `email` é a chave em tudo: log, banco e Exact."""
    email: str
    nome_exibicao: str
    grade: Grade


def _cfg_bruta() -> list[dict] | None:
    bruto = os.getenv("AGENDAMENTO_CONSULTORAS")
    origem = "AGENDAMENTO_CONSULTORAS"
    if not bruto:
        caminho = os.getenv("AGENDAMENTO_CONSULTORAS_PATH")
        if not caminho:
            return None
        origem = f"AGENDAMENTO_CONSULTORAS_PATH={caminho}"
        try:
            with open(caminho, encoding="utf-8") as fh:
                bruto = fh.read()
        except OSError as e:
            print(f"⚠️ agendamento: não consegui ler {caminho} ({e}). Usando consultora única.")
            return None
    try:
        dados = json.loads(bruto)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        # Mesma política da grade: config inválida não derruba o backend inteiro.
        print(f"⚠️ agendamento: {origem} inválido ({e}). Usando consultora única.")
        return None
    if not isinstance(dados, list) or not dados:
        print(f"⚠️ agendamento: {origem} não é uma lista não-vazia. Usando consultora única.")
        return None
    return dados


def _montar(dados: list[dict]) -> list[Consultora]:
    saida: list[Consultora] = []
    for i, item in enumerate(dados):
        try:
            email = str(item["email"]).strip()
            if not email:
                raise KeyError("email")
            nome = str(item.get("nome_exibicao") or email.split("@")[0]).strip()
            cfg = dict(GRADE_PADRAO)
            cfg.update(item.get("grade") or {})
            # O email da consultora manda. Ver o cabeçalho.
            cfg["sales_rep_email"] = email
            saida.append(Consultora(email=email, nome_exibicao=nome, grade=Grade(cfg)))
        except (KeyError, TypeError, ValueError) as e:
            print(f"⚠️ agendamento: consultora #{i} ignorada, config inválida ({e})")
    return saida


_cache: list[Consultora] | None = None


def consultoras() -> list[Consultora]:
    """Singleton preguiçoso. Recarregar exige restart — é config de infra."""
    global _cache
    if _cache is None:
        dados = _cfg_bruta()
        montadas = _montar(dados) if dados else []
        if not montadas:
            # Fallback = o comportamento de antes deste módulo existir.
            g = grade()
            montadas = [Consultora(email=g.sales_rep_email,
                                   nome_exibicao=g.sales_rep_email.split("@")[0],
                                   grade=g)]
        _cache = montadas
    return _cache


def recarregar() -> list[Consultora]:
    """Só para os testes, que trocam a config sem reiniciar o processo."""
    global _cache
    _cache = None
    return consultoras()


def por_email(email: str) -> Consultora | None:
    for c in consultoras():
        if c.email.lower() == (email or "").lower():
            return c
    return None


def nome_de(email: str) -> str:
    """Nome de exibição, com o e-mail como reserva.

    A reserva importa para linha antiga: se uma consultora sair da config, os agendamentos
    dela continuam no banco e ainda precisam de um rótulo legível.
    """
    c = por_email(email)
    return c.nome_exibicao if c else (email or "").split("@")[0]


def desativar(email: str) -> None:
    """Tira uma consultora de rotação em tempo de execução. Usado só pela validação."""
    global _cache
    if _cache is None:
        consultoras()
    _cache = [c for c in (_cache or []) if c.email.lower() != (email or "").lower()]


async def validar_contra_exact() -> dict:
    """Confere cada e-mail em `GET /Sellers`. Chamado no startup. NUNCA levanta.

    Devolve um resumo para quem quiser logar ou expor num healthcheck.
    """
    from app.agendamento import client

    alvo = list(consultoras())
    resumo = {"verificadas": [], "invalidas": [], "checagem_falhou": False}
    try:
        sellers = await client.listar_sellers()
    except client.ExactErro as e:
        # Não dá para distinguir "e-mail inválido" de "não consegui perguntar". Ninguém sai.
        print(f"⚠️ agendamento: não consegui validar as consultoras em /Sellers "
              f"({type(e).__name__}: {e}). Seguindo com {len(alvo)} sem verificar.")
        resumo["checagem_falhou"] = True
        return resumo

    ativos = {str(s.get("email", "")).lower(): s for s in sellers if s.get("active")}
    conhecidos = {str(s.get("email", "")).lower() for s in sellers}

    for c in alvo:
        chave = c.email.lower()
        if chave in ativos:
            resumo["verificadas"].append(c.email)
            continue
        motivo = "inativa na Exact" if chave in conhecidos else "não existe em /Sellers"
        print(f"❌ agendamento: consultora {c.email} {motivo} — FORA DE ROTAÇÃO. "
              f"Todo BoxesAdd com ela falharia com 'SDR not found'.")
        resumo["invalidas"].append({"email": c.email, "motivo": motivo})
        desativar(c.email)

    if not consultoras():
        print("🚨 agendamento: NENHUMA consultora válida. /slots vai degradar para "
              "fallback e a LP cai no 'deixe seu contato'. Corrija AGENDAMENTO_CONSULTORAS.")
    else:
        print(f"✅ agendamento: {len(consultoras())} consultora(s) em rotação — "
              + ", ".join(f"{c.nome_exibicao} <{c.email}>" for c in consultoras()))
    return resumo
