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
import os
import time as _time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agendamento import agendar as fluxo
from app.agendamento import client, consultoras as equipe_mod, disponibilidade
from app.agendamento import extras as extras_mod, origens
from app.agendamento import token as tokens
from app.models import Agendamento
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
    # De qual curso veio. Conferido contra a allowlist em `origens.py`, NUNCA repassado como
    # texto livre: `LeadsAdd` cria o subSource quando o valor não existe. Ausente = padrão.
    origem: str | None = Field(default=None, max_length=100)
    # Respostas livres do formulário: profissão, como conheceu, faixa de investimento. Vão
    # para `agendamentos.extras` (JSONB) e para o `description` do lead, que é o que o SDR
    # lê antes de ligar. Declarado aqui no DadosLead de propósito: assim vale para /lead e
    # para /agendar sem duplicar nada, e as duas rotas têm o mesmo contrato.
    #
    # Os limites (10 chaves, 200 chars) são RECUSA, não corte — ver o validador abaixo.
    extras: dict[str, str] | None = Field(default=None)

    @field_validator("extras")
    @classmethod
    def _extras_limpos(cls, v):
        """Aplica contrato e sanitização de uma vez só.

        `ExtrasInvalidos` herda de `ValueError`, então o Pydantic já o transforma em 422 com
        a mensagem dentro — sem `except` aqui e sem tratamento no endpoint.

        Recusar em vez de truncar é decisão consciente, e vai contra o "visitante nunca fica
        preso" que rege o resto do módulo. A razão: extras alimentam relatório de marketing,
        e um valor cortado pela metade é pior que uma submissão recusada, porque ninguém
        descobre. Quem controla o formulário somos nós — 10 perguntas é uma LP longa, e uma
        11ª significa que alguém mexeu no form sem olhar o backend. O 422 aparece no console
        de quem publicou a página, que é exatamente quem pode consertar.
        """
        return extras_mod.sanitizar(v) or None

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
    # Lead que JÁ existe, criado antes pelo POST /lead. Presente = pula o LeadsAdd e agenda
    # este lead; ausente = cria um novo, como sempre. É o que impede a pessoa de virar dois
    # leads no fluxo de duas etapas da LP (form no index -> agendamento no obrigado).
    #
    # O nome é `leadId` porque é o que a query string do obrigado.html carrega (`?lead=`) e
    # o que o front monta. `lead_id` também é aceito, para quem chamar de dentro do projeto.
    #
    # `gt=0` porque id da Exact é sempre positivo, e um `0` vindo de string vazia mal
    # convertida no front viraria uma consulta inútil à Exact — melhor recusar como 422.
    lead_id: int | None = Field(default=None, alias="leadId", gt=0)

    model_config = {"populate_by_name": True}


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
    equipe = equipe_mod.consultoras()
    if not dias:
        # Sem horário nenhum a LP não tem o que mostrar. Pode ser feriado, agenda lotada, ou
        # todas as consultoras fora de rotação pela validação de startup. `fallback:true` é o
        # que faz o front cair no "deixe seu contato" em vez de exibir grade vazia.
        return {"dias": {}, "fallback": True,
                "mensagem": "Não há horários abertos no momento."}
    # A duração é política do produto e igual para todas; leio da primeira em rotação.
    return {
        "dias": dias,
        "fallback": False,
        "duracao_min": int(equipe[0].grade.duracao.total_seconds() // 60),
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
                                origem=pedido.origem, lead_id=pedido.lead_id,
                                extras=pedido.extras, origem_ip=_ip(request))
    except origens.OrigemInvalida as e:
        # 400 e não 422: o corpo está bem formado, o valor é que não é aceito. E a mensagem
        # não lista as origens permitidas — é endpoint público, e a lista é dado interno.
        print(f"⚠️ /agendamento/agendar: {e} (ip {_ip(request)})")
        raise HTTPException(status_code=400, detail="Origem inválida.") from e
    except fluxo.SlotInvalido as e:
        raise HTTPException(status_code=400, detail="Horário inválido ou expirado.") from e
    except fluxo.LeadNaoEncontrado as e:
        # 404 e não 400: o corpo está correto, o recurso é que não existe. O front trata
        # reenviando SEM `leadId` — aí o /agendar cria o lead e o visitante não fica preso
        # por causa de um `?lead=` velho na URL.
        raise HTTPException(
            status_code=404,
            detail="O cadastro informado não foi encontrado. "
                   "Recarregue a página e tente de novo.") from e
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
        # Quem vai atender. O e-mail NÃO vai junto de propósito: é endpoint público, e o
        # endereço interno da consultora não é dado do visitante.
        "consultora_nome": r.consultora_nome,
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
            db, nome=pedido.nome, email=pedido.email, telefone=pedido.telefone,
            origem=pedido.origem, extras=pedido.extras, origem_ip=_ip(request))
    except origens.OrigemInvalida as e:
        print(f"⚠️ /agendamento/lead: {e} (ip {_ip(request)})")
        raise HTTPException(status_code=400, detail="Origem inválida.") from e
    except fluxo.AgendamentoFalhou as e:
        # 503 quando a Exact não respondeu, 502 quando ela respondeu recusando. A diferença
        # importa para o FRONT, não para o visitante: o form nativo segue para o obrigado.html
        # de qualquer jeito (sem `lead=` na URL), e lá o POST /agendar cria o lead. Ninguém
        # fica preso numa página porque o CRM piscou.
        #
        # Nenhum dos dois é 500: 500 quer dizer "quebrou aqui dentro", e não é o caso — a
        # falha é de uma dependência externa, e o front tem o que fazer com essa informação.
        indisponivel = isinstance(e.__cause__, client.ExactIndisponivel)
        raise HTTPException(
            status_code=503 if indisponivel else 502,
            detail="Não consegui registrar seu contato agora. Tente de novo.") from e
    # `lead_id` (snake) é a chave canônica de RESPOSTA em todo o módulo — igual ao /agendar,
    # e igual ao resto do corpo (`agendamento_id`, `inicio`, `fim`). O `leadId` em camelCase é
    # aceito só na ENTRADA do /agendar, porque é o formato que o front tem em mãos. Devolver
    # as duas grafias aqui deixaria o contrato ambíguo sobre qual é a de verdade.
    return {"ok": True, "lead_id": lead_id,
            "aviso": "Recebemos seu contato. Nossa equipe fala com você em breve."}


# ==========================================================================================
# LEAD ESPONTÂNEO — a página do token
# ==========================================================================================
# `hub.cenatdata.online/agendar/<token>`. Página pública e sem login, servida pelo Next.js;
# estas rotas são o backend dela.
#
# A DIFERENÇA PARA AS ROTAS DE CIMA, E É A RAZÃO DE EXISTIREM SEPARADAS:
# no fluxo da LP o visitante DIGITA o telefone. Aqui ele não digita nada — o telefone vem do
# token, do lado do servidor. Se viesse do corpo do POST, qualquer um agendaria no nome de
# qualquer número, e a página é pública.

# O subSource dedicado. Fica em env porque `LeadsAdd` CRIA o que não existe e não há endpoint
# para remover (FINDINGS §11): enquanto o valor não estiver na allowlist, `origens.resolver`
# levanta `OrigemInvalida` e o booking devolve 400. É falha FECHADA de propósito — melhor a
# página recusar do que nascer cadastro errado e permanente na Exact.
SUBSOURCE_ESPONTANEO = os.getenv("AGENDAMENTO_SUBSOURCE_ESPONTANEO", "Espontaneo WhatsApp")


class PedidoEspontaneo(BaseModel):
    """Só o que a página tem para dar. Telefone NÃO entra — ver o cabeçalho da seção."""
    nome: str = Field(min_length=2, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    slot: str | None = Field(default=None, min_length=10, max_length=40)

    @field_validator("nome")
    @classmethod
    def _nome_limpo(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("nome vazio")
        return v.strip()


def _recusa_de(status: str) -> HTTPException:
    """404 para o que nunca existiu, 410 para o que existiu e morreu.

    A tela trata os dois igual (oferece retomar no WhatsApp), mas o código de status é
    informação para quem lê log e para o próximo dev — e um `Gone` diz exatamente o que houve.
    """
    if status == tokens.EXPIRADO:
        return HTTPException(410, "Este link expirou.")
    return HTTPException(404, "Link inválido.")


@router.get("/espontaneo/{segredo}")
async def ler_token(segredo: str, request: Request, db: AsyncSession = Depends(get_db)):
    """O que a página precisa para se desenhar. NUNCA devolve o wa_id cru.

    `usado` responde 200, e não 410, de propósito: quem já agendou tem que ver O SEU
    AGENDAMENTO, não uma mensagem de erro. É a diferença entre "o link morreu" e "você já
    fez isso, olha aí".
    """
    _limitar(request, LIMITE_LEITURA, "esp_ler")
    r = await tokens.resolver(db, segredo)
    if r.status in (tokens.INEXISTENTE, tokens.EXPIRADO):
        raise _recusa_de(r.status)

    t = r.token
    corpo = {"status": r.status, "nome": t.nome, "curso": t.curso,
             "telefone_mascarado": tokens.mascarar(t.contact_wa_id)}
    if r.status == tokens.USADO:
        ag = None
        if t.agendamento_id:
            ag = (await db.execute(select(Agendamento).where(
                Agendamento.id == t.agendamento_id))).scalar_one_or_none()
        corpo["agendamento"] = {
            "inicio": ag.slot_inicio.strftime("%Y-%m-%dT%H:%M:%S") if ag else None,
            "fim": ag.slot_fim.strftime("%Y-%m-%dT%H:%M:%S") if ag and ag.slot_fim else None,
            "consultora_nome": equipe_mod.nome_de(ag.sales_rep_email or "") if ag else "",
        }
    return corpo


@router.post("/espontaneo/{segredo}/agendar")
async def agendar_por_token(segredo: str, pedido: PedidoEspontaneo, request: Request,
                            db: AsyncSession = Depends(get_db)):
    """Agenda usando o telefone DO TOKEN. O corpo não carrega telefone nenhum.

    A CLAIM VEM ANTES DA EXACT. Dois cliques simultâneos no mesmo link são caso real (a
    pessoa toca duas vezes, ou abre em duas abas), e a ordem decide o estrago:

        agendar → consumir   os dois passam e nascem DOIS LEADS na Exact, sem desfazer
        consumir → agendar   um ganha, o outro vê 409; e se o agendamento falhar, a claim
                             é devolvida por `tokens.liberar`

    Sujeira reversível é melhor que lead duplicado permanente. Ver `token.py`.
    """
    _limitar(request, LIMITE_ESCRITA, "esp_agendar")
    if not pedido.slot:
        raise HTTPException(400, "Escolha um horário.")

    r = await tokens.resolver(db, segredo)
    if not r.ok:
        if r.status == tokens.USADO:
            raise HTTPException(409, "Este link já foi usado para agendar.")
        raise _recusa_de(r.status)

    telefone = r.token.contact_wa_id
    if not await tokens.consumir(db, segredo):
        # Perdeu a corrida para outro clique. Não é erro do visitante.
        raise HTTPException(409, "Este link já foi usado para agendar.")

    try:
        resultado = await fluxo.agendar(
            db, nome=pedido.nome, email=pedido.email, telefone=telefone,
            slot_id=pedido.slot, origem=SUBSOURCE_ESPONTANEO, origem_ip=_ip(request))
    except Exception:
        # Devolve a claim: sem isto, uma falha na Exact queimaria o link que a Nat acabou de
        # mandar e a pessoa ficaria sem caminho nenhum.
        await tokens.liberar(db, segredo)
        await db.commit()
        raise

    await tokens.marcar_agendamento(db, segredo, resultado.agendamento_id)
    await db.commit()

    # O ELO COM O CHAT. Depois do commit e em try próprio: a reunião já existe na Exact, e
    # falhar em confirmar não pode desfazê-la nem devolver erro para quem agendou.
    try:
        from app.qualificacao_fluxo import concluir_por_agendamento_externo
        reuniao = (await db.execute(select(Agendamento).where(
            Agendamento.id == resultado.agendamento_id))).scalar_one_or_none()
        if reuniao is not None:
            await concluir_por_agendamento_externo(telefone, reuniao, db)
            await db.commit()
    except Exception as e:
        print(f"⚠️ /espontaneo/agendar: reunião {resultado.agendamento_id} criada, mas o "
              f"fechamento do agente falhou ({type(e).__name__}: {e})")

    print(f"📅 espontâneo: {telefone} agendou {resultado.slot.id} com "
          f"{resultado.consultora_nome} (lead {resultado.lead_id}, "
          f"agendamento {resultado.agendamento_id})")
    return {
        "ok": True,
        "agendamento_id": resultado.agendamento_id,
        "lead_id": resultado.lead_id,
        "inicio": resultado.slot.inicio.strftime("%Y-%m-%dT%H:%M:%S"),
        "fim": resultado.slot.fim.strftime("%Y-%m-%dT%H:%M:%S"),
        "fuso": "America/Sao_Paulo",
        "consultora_nome": resultado.consultora_nome,
        "aviso": "Para remarcar ou cancelar, fale com a gente pelo WhatsApp.",
    }


@router.post("/espontaneo/{segredo}/lead")
async def lead_por_token(segredo: str, pedido: PedidoEspontaneo, request: Request,
                         db: AsyncSession = Depends(get_db)):
    """Fallback sem grade: cadastra e um SDR liga. Mesmo espírito do `/lead` da LP.

    Consome o token igual ao booking: o link é de uso único, e "deixei meu contato" também
    é um desfecho. Sem isso a pessoa poderia cadastrar-se várias vezes com o mesmo link.
    """
    _limitar(request, LIMITE_ESCRITA, "esp_lead")
    r = await tokens.resolver(db, segredo)
    if not r.ok:
        if r.status == tokens.USADO:
            raise HTTPException(409, "Este link já foi usado.")
        raise _recusa_de(r.status)

    telefone = r.token.contact_wa_id
    if not await tokens.consumir(db, segredo):
        raise HTTPException(409, "Este link já foi usado.")

    try:
        lead_id = await fluxo.cadastrar_lead_sem_agendar(
            db, nome=pedido.nome, email=pedido.email, telefone=telefone,
            origem=SUBSOURCE_ESPONTANEO, origem_ip=_ip(request))
    except Exception:
        await tokens.liberar(db, segredo)
        await db.commit()
        raise

    await db.commit()
    print(f"👤 espontâneo: {telefone} cadastrado sem agendar (lead {lead_id})")
    return {"ok": True, "lead_id": lead_id,
            "aviso": "Recebemos seu contato. Nossa equipe fala com você em breve."}
