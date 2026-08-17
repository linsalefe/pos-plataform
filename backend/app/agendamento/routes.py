"""Endpoints públicos do agendamento. Sem autenticação — a LP é uma página aberta.

------------------------------------------------------------------------------------------
ESTES ENDPOINTS SÃO A ÚNICA SUPERFÍCIE PÚBLICA DO BACKEND
------------------------------------------------------------------------------------------
Todo o resto da API exige token. Aqui não dá: quem chama é o `obrigado.html` no navegador de
um visitante anônimo. Isso muda o que precisa de cuidado:

  * **Rate limit por IP**, em memória. Sem ele, um laço de `curl` cria leads e boxes na
    agenda real de uma consultora até o rate limit da própria Exact estourar — e aí derruba
    junto o `sync_job`, que divide o mesmo token.

  * **A grade valida a entrada.** `slot_id` vai a `grade.slot_por_id`, que só devolve slot da
    grade e dentro da antecedência. Sem isso, um POST forjado agenda 03:00 de domingo: o
    `BoxesAdd` aceitaria numa boa, porque a Exact não conhece a nossa grade.

  * **Mensagem de erro não vaza detalhe da Exact.** `SDR not found` significa que a NOSSA
    configuração está errada, e o visitante não tem o que fazer com isso. O log guarda o
    original.

------------------------------------------------------------------------------------------
O RATE LIMIT É EM MEMÓRIA, E ISSO BASTA HOJE
------------------------------------------------------------------------------------------
Um processo, um contador. Se um dia houver dois workers, cada um terá o próprio balde e o
limite efetivo dobra — momento de trocar por Redis. Não usei `slowapi` porque o projeto não
tem a dependência e o problema cabe em 20 linhas.
"""
import time as _time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agendamento import agendar as fluxo
from app.agendamento import disponibilidade
from app.agendamento.grade import grade
from app.database import get_db

router = APIRouter(prefix="/api/agendamento", tags=["agendamento"])

# (requisições, janela em segundos) por IP. Leitura é barata e o front recarrega a grade a
# cada agendamento perdido; escrita fala com a Exact três vezes e por isso é bem mais apertada.
LIMITE_LEITURA = (60, 60)
LIMITE_ESCRITA = (5, 300)

_baldes: dict[str, deque] = defaultdict(deque)


def _ip(request: Request) -> str:
    """IP do visitante, respeitando o proxy.

    O backend roda atrás de nginx, então `request.client.host` é sempre 127.0.0.1 — sem ler o
    `X-Forwarded-For`, o rate limit trataria o mundo inteiro como um único visitante e
    bloquearia todo mundo junto. Pega o PRIMEIRO da lista, que é o cliente original.
    """
    encaminhado = request.headers.get("x-forwarded-for")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.client.host if request.client else "desconhecido"


def _limitar(request: Request, limite: tuple[int, int], escopo: str) -> None:
    maximo, janela = limite
    chave = f"{escopo}:{_ip(request)}"
    agora = _time.monotonic()
    balde = _baldes[chave]
    while balde and agora - balde[0] > janela:
        balde.popleft()
    if len(balde) >= maximo:
        raise HTTPException(status_code=429,
                            detail="Muitas tentativas. Aguarde alguns minutos.")
    balde.append(agora)
    # Higiene do dicionário: sem isto, um IP por visitante vira vazamento lento de memória
    # num processo que fica meses de pé.
    if len(_baldes) > 10_000:
        for k in [k for k, v in _baldes.items() if not v]:
            del _baldes[k]


def _normalizar_telefone(bruto: str) -> str:
    """Só dígitos, sem o DDI. A Exact quer `ddiPhone` e `phone` separados (FINDINGS §3).

    O visitante digita `(11) 99999-8888`, `+55 11 99999-8888` ou `5511999998888`. Os três
    viram `11999998888`.
    """
    digitos = "".join(c for c in bruto if c.isdigit())
    if len(digitos) > 11 and digitos.startswith("55"):
        digitos = digitos[2:]
    return digitos


class DadosLead(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    telefone: str = Field(min_length=8, max_length=25)

    @field_validator("nome")
    @classmethod
    def _nome_limpo(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("nome vazio")
        return v.strip()

    @field_validator("telefone")
    @classmethod
    def _telefone_valido(cls, v: str) -> str:
        digitos = _normalizar_telefone(v)
        # 10 = fixo com DDD, 11 = celular com DDD. Fora disso não é telefone brasileiro, e
        # deixar passar significa criar lead que ninguém consegue ligar.
        if len(digitos) not in (10, 11):
            raise ValueError("telefone deve ter DDD + número (10 ou 11 dígitos)")
        return digitos


class PedidoAgendamento(DadosLead):
    slot: str = Field(min_length=10, max_length=40)


@router.get("/slots")
async def listar_slots(request: Request, db: AsyncSession = Depends(get_db)):
    """Horários livres, agrupados por dia. Resposta cacheada por 60s.

    O cache é do processo inteiro, não por visitante: a grade é a mesma para todo mundo.
    """
    _limitar(request, LIMITE_LEITURA, "slots")
    try:
        dias = await disponibilidade.resumo_por_dia(db)
    except Exception as e:
        # A LP não pode quebrar porque a Exact caiu. Devolve grade vazia e o front cai no
        # fallback de "deixe seu contato".
        print(f"❌ /agendamento/slots: {type(e).__name__}: {e}")
        return {"dias": {}, "fallback": True,
                "mensagem": "Não consegui carregar os horários agora."}
    g = grade()
    return {
        "dias": dias,
        "fallback": False,
        "duracao_min": int(g.duracao.total_seconds() // 60),
        "fuso": "America/Sao_Paulo",
    }


@router.post("/agendar")
async def criar_agendamento(pedido: PedidoAgendamento, request: Request,
                            db: AsyncSession = Depends(get_db)):
    """Cria o lead e agenda numa chamada. 409 = o horário foi tomado, recarregue a grade."""
    _limitar(request, LIMITE_ESCRITA, "agendar")
    try:
        r = await fluxo.agendar(db, nome=pedido.nome, email=pedido.email,
                                telefone=pedido.telefone, slot_id=pedido.slot,
                                origem_ip=_ip(request))
    except fluxo.SlotInvalido as e:
        raise HTTPException(status_code=400, detail="Horário inválido ou expirado.") from e
    except fluxo.SlotIndisponivel as e:
        raise HTTPException(
            status_code=409,
            detail="Esse horário acabou de ser preenchido. Escolha outro, por favor.") from e
    except fluxo.AgendamentoFalhou as e:
        # O lead pode ter sobrevivido (falha no passo 3). Dizer isso ao visitante muda a
        # mensagem: "vamos entrar em contato" é verdade, e "tente de novo" não seria.
        if e.lead_id:
            raise HTTPException(
                status_code=502,
                detail="Recebemos seus dados, mas não consegui confirmar o horário. "
                       "Nossa equipe entra em contato pelo WhatsApp.") from e
        raise HTTPException(status_code=502,
                            detail="Não consegui concluir o agendamento. Tente de novo.") from e

    return {
        "ok": True,
        "agendamento_id": r.agendamento_id,
        "lead_id": r.lead_id,
        "inicio": r.slot.inicio.strftime("%Y-%m-%dT%H:%M:%S"),
        "fim": r.slot.fim.strftime("%Y-%m-%dT%H:%M:%S"),
        "fuso": "America/Sao_Paulo",
        "aviso": "Para remarcar ou cancelar, fale com a gente pelo WhatsApp.",
    }


@router.post("/lead")
async def criar_lead_sem_agendar(pedido: DadosLead, request: Request,
                                 db: AsyncSession = Depends(get_db)):
    """Fallback: cadastra sem agendar. O lead cai em `Entrada` e um SDR liga.

    É o que salva o contato quando não há horário na grade ou o visitante não quer escolher.
    """
    _limitar(request, LIMITE_ESCRITA, "lead")
    try:
        lead_id = await fluxo.cadastrar_lead_sem_agendar(
            db, nome=pedido.nome, email=pedido.email,
            telefone=pedido.telefone, origem_ip=_ip(request))
    except fluxo.AgendamentoFalhou as e:
        raise HTTPException(status_code=502,
                            detail="Não consegui registrar seu contato. Tente de novo.") from e
    return {"ok": True, "lead_id": lead_id,
            "aviso": "Recebemos seu contato. Nossa equipe fala com você em breve."}
