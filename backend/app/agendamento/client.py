"""Cliente HTTP da Exact para o módulo de agendamento. Traduz os 400 conhecidos em exceções.

Reaproveita `exact_spotter.BASE_URL` e `exact_spotter.get_headers()` — o token e a base são os
mesmos do resto do projeto, e duplicá-los aqui criaria dois lugares para trocar credencial.

------------------------------------------------------------------------------------------
POR QUE TRADUZIR ERRO EM EXCEÇÃO TIPADA
------------------------------------------------------------------------------------------
A Exact devolve 400 com uma mensagem em inglês dentro de `{"error": {"message": ...}}`, e as
mensagens têm significados MUITO diferentes: uma quer dizer "o visitante perdeu a corrida"
(resposta 409 e recarrega a grade), outra quer dizer "nossa configuração está errada" (alerta
interno, e o visitante não pode ver isso). Comparar string no meio do fluxo de agendamento
espalharia essa decisão por todo lado.

As mensagens exatas estão em AGENDAMENTO_FINDINGS.md §2 e §8, todas observadas na API real.

------------------------------------------------------------------------------------------
O QUE ESTE MÓDULO NÃO FAZ
------------------------------------------------------------------------------------------
Não tem retentativa. Um `BoxesAdd` repetido depois de timeout pode criar DOIS boxes (o
primeiro pode ter chegado), e box sobrando na agenda de uma consultora é pior que uma falha
visível na LP. Quem decide repetir é o visitante, clicando de novo.
"""
import httpx

from app.agendamento.horarios import para_exact
from app.exact_spotter import BASE_URL, get_headers

TIMEOUT_PADRAO = 15.0


class ExactErro(Exception):
    """Base. Qualquer coisa que a Exact recusou ou que não deu para falar com ela."""


class ExactIndisponivel(ExactErro):
    """Rede, timeout ou 5xx. Não sabemos se a escrita aconteceu — tratar como talvez."""


class SlotOcupado(ExactErro):
    """`BoxesAdd`: já existe box sobrepondo o horário. O visitante perdeu a corrida."""


class BoxIndisponivel(ExactErro):
    """`scheduleAdd`: o box não está `available`. No nosso fluxo, indica corrida ou bug."""


class IntervaloInvalido(ExactErro):
    """`end` não é posterior ao `start`. Bug nosso — nunca deveria chegar à API."""


class SdrNaoEncontrado(ExactErro):
    """`salesRepEmail` não existe na Exact. Erro de configuração, não do visitante."""


class BoxInexistente(ExactErro):
    """`BoxesRemove` num id que a Exact não conhece."""


class BoxComReuniao(ExactErro):
    """`BoxesRemove` num box que já tem reunião. É definitivo — ver FINDINGS §6."""


# Mensagem crua da Exact -> exceção. Casamento por prefixo porque o texto é estável mas o
# ponto final e maiúsculas já variaram entre endpoints.
_ERROS = (
    ("boxes are occupied", SlotOcupado),
    ("box is already occupied", BoxIndisponivel),
    ("start time must precede", IntervaloInvalido),
    ("sdr not found", SdrNaoEncontrado),
    ("the informed box does not exist", BoxInexistente),
    ("it is not possible to change a box", BoxComReuniao),
)


def _levantar(resp: httpx.Response) -> None:
    """Converte um 4xx da Exact em exceção tipada. 2xx passa direto."""
    if resp.status_code < 400:
        return
    try:
        msg = (resp.json().get("error") or {}).get("message") or resp.text
    except ValueError:
        msg = resp.text
    baixa = (msg or "").strip().lower()
    for prefixo, excecao in _ERROS:
        if baixa.startswith(prefixo):
            raise excecao(msg)
    if resp.status_code >= 500:
        raise ExactIndisponivel(f"HTTP {resp.status_code}: {msg}")
    raise ExactErro(f"HTTP {resp.status_code}: {msg}")


async def _req(metodo: str, caminho: str, *, timeout: float = TIMEOUT_PADRAO, **kw):
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(metodo, f"{BASE_URL}{caminho}",
                                        headers=get_headers(), **kw)
    except httpx.HTTPError as e:
        raise ExactIndisponivel(str(e)) from e
    _levantar(resp)
    return resp


async def listar_boxes(inicio, fim, sales_rep_email: str) -> list[dict]:
    """Boxes do consultor que COMEÇAM na janela pedida.

    O `$filter` é obrigatório e não é preciosismo: `GET /Boxes` sem filtro aplica uma janela
    implícita que corta ~4 semanas de passado (FINDINGS §5) — 276 linhas contra 1472 com
    filtro de status. Disponibilidade calculada em cima da versão sem filtro erra calada.

    Filtra por `start`, não por sobreposição real: um box que comece ANTES da janela e termine
    dentro dela não aparece. Na prática os blocos duram no máximo ~1h10 e a janela é o dia
    inteiro, então o caso não ocorre. Quem garante de verdade é o `BoxesAdd`, que enxerga a
    agenda inteira — esta consulta é para EXIBIR, não para decidir.
    """
    filtro = (f"salesRepEmail eq '{sales_rep_email}'"
              f" and start ge {para_exact(inicio)} and start le {para_exact(fim)}")
    resp = await _req("GET", "/Boxes", params={"$filter": filtro, "$top": 500})
    return resp.json().get("value", [])


async def criar_box(*, inicio, fim, sales_rep_email: str, type_meeting: str,
                    description: str) -> int:
    """`POST /BoxesAdd` com `status="available"`. Devolve o `boxId`.

    Sempre `available`: é o único status que o `scheduleAdd` aceita depois (FINDINGS §8).

    ESTA CHAMADA É O LOCK do horário. Ela recusa qualquer sobreposição, então quem consegue
    criar ganhou o slot — não existe janela de check-then-act entre consultar e reservar.
    """
    corpo = {
        "start": para_exact(inicio),
        "end": para_exact(fim),
        "salesRepEmail": sales_rep_email,
        "status": "available",
        "typeMeeting": type_meeting,
        "description": description,
    }
    resp = await _req("POST", "/BoxesAdd", json=corpo)
    return int(resp.json()["value"])


async def remover_box(box_id: int) -> None:
    """`DELETE /BoxesRemove/{id}`. Só funciona em box SEM reunião.

    É idempotente para um box que já removemos (204 de novo), mas um box que recebeu
    `scheduleAdd` levanta `BoxComReuniao` para sempre — não há desfazer (FINDINGS §6).
    """
    await _req("DELETE", f"/BoxesRemove/{box_id}")


async def criar_lead(*, nome: str, telefone: str, email: str | None, source: str,
                     sub_source: str, funnel_id: int, ddi: str = "55") -> int:
    """`POST /LeadsAdd`. Devolve o `leadId`. O lead nasce em `Entrada` do funil.

    `duplicityValidation=False` porque a LP é pública e um bloqueio por duplicidade viraria
    erro na cara do visitante. A defesa contra duplicata é nossa, antes daqui.

    O payload é ANINHADO sob `lead` — diferente do `BoxesAdd`, que é flat.

    O E-MAIL VAI EM `description`, NÃO EM CAMPO PRÓPRIO. O `LeadsAdd` não tem campo de e-mail:
    não está no payload documentado, e `GET /Leads` não devolve nenhuma chave de e-mail (as de
    contato são `phone1`, `phone2` e `telephones`). Na Exact o e-mail pertence à *pessoa*, não
    ao lead — outra entidade (`LeadsAndPersons`), fora do escopo deste módulo. Mandar
    `"email"` no payload seria descartado em silêncio e a LP perderia o dado que pediu ao
    visitante. Em `description` o SDR enxerga, e o nosso banco guarda em coluna própria.
    """
    lead = {
        "name": nome,
        "source": source,
        "subSource": sub_source,
        "funnelId": funnel_id,
        "ddiPhone": ddi,
        "phone": telefone,
    }
    if email:
        lead["description"] = f"E-mail informado na LP: {email}"
    resp = await _req("POST", "/LeadsAdd", json={"duplicityValidation": False, "lead": lead})
    return int(resp.json()["value"])


async def agendar_reuniao(*, box_id: int, lead_id: int, stage_name: str,
                          sales_rep_email: str) -> bool:
    """`POST /scheduleAdd`. PONTO DE NÃO RETORNO.

    Faz três escritas de uma vez: move o lead de etapa, atribui o salesRep e cria a reunião.
    Devolve booleano, não o id da reunião — para o id é preciso `meeting_por_lead` depois.

    Não existe `ScheduleRemove` na API (conferido no `$metadata`). Depois disto, cancelar e
    remarcar são assunto do WhatsApp, e o box fica ocupado para sempre.
    """
    corpo = {
        "boxId": box_id,
        "leadId": lead_id,
        "stageName": stage_name,
        "salesRepEmail": sales_rep_email,
    }
    resp = await _req("POST", "/scheduleAdd", json=corpo)
    return bool(resp.json().get("value"))


async def meeting_por_lead(lead_id: int) -> dict | None:
    """A reunião do lead, para guardar o `meeting_id` que o `scheduleAdd` não devolve.

    Best-effort: falhar aqui não invalida o agendamento, que já aconteceu.
    """
    resp = await _req("GET", "/Meetings", params={"$filter": f"lead/id eq {lead_id}"})
    valores = resp.json().get("value", [])
    return valores[0] if valores else None


async def buscar_lead_por_telefone(telefone: str) -> dict | None:
    """Lead existente com este telefone, se houver. Usado para não duplicar na LP.

    `duplicityValidation=False` não protege ninguém numa página pública: o mesmo visitante
    preenchendo duas vezes vira dois leads.
    """
    filtro = f"phone1 eq '{telefone}'"
    resp = await _req("GET", "/Leads", params={"$filter": filtro, "$top": 1})
    valores = resp.json().get("value", [])
    return valores[0] if valores else None
