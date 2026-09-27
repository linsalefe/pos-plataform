"""Observação automática no lead da Exact — onde o SDR trabalha (sprint de religamento, 27/09/2026).

==========================================================================================
É O `TimelineAdd`, E NÃO UM CAMPO DO LEAD
==========================================================================================
O `$metadata` da Exact (lido em 27/09, 64 KB) declara seis EntitySets com nome de nota ou
histórico: `TimelineAdd`, `ListTimeline`, `QualificationHistories`, `CallsHistory`,
`TransferHistory`, `CustomFieldsHistories`. Só um aceita texto livre por lead:

    TimelineAdd     TimelineODataDTO     {leadId: Int32, userId: Int32, text: String}
    ListTimeline    ListTimelineODataDTO {id, leadId, text, createdAt, user}   <- a leitura

O `description` do `LeadsAdd` seria a outra porta, mas ele só existe na CRIAÇÃO — o
`LeadsUpdate` que o declara dá 404 (TESTE_FOLLOW_ESTAGIO_20260927_REPORT §3). E sobrescrever
a descrição apagaria o e-mail e os extras que a LP grava ali.

`exact_spotter.add_timeline_comment` já faz o mesmo POST desde julho (resumo do atendimento,
anotação do NAT). Esta função é a mesma chamada com o contrato que a sprint pediu — log
`❌ exact_note #<lead_id>` e prefixo `[NAT]` — e com timeout curto por padrão, porque o
chamador da recusa roda dentro do webhook da Meta.

A rota vai em `/timelineAdd` (t minúsculo), a grafia que `add_timeline_comment` usa em
produção desde julho — o `$metadata` escreve `TimelineAdd`. Não troco uma grafia provada por
outra que só o contrato declara.

==========================================================================================
BEST-EFFORT: NUNCA LEVANTA, NUNCA FAZ RETRY, SEMPRE LOGA
==========================================================================================
A nota é um aviso ao SDR, não parte do fluxo. Quando ela é chamada, o que importa já
aconteceu (a despedida saiu, o template foi entregue). Levantar aqui desfaria — ou marcaria
como falha — um desfecho que é verdadeiro. Retry também não: uma nota duplicada na timeline
é ruído que o SDR lê duas vezes, e a Exact fora do ar não volta em 2 segundos.

Nenhum chamador deve ler o retorno para decidir nada; ele existe para teste e log.
"""
import httpx

from app.exact_spotter import BASE_URL, EXACT_BOT_USER_ID, get_headers

# Prefixo de toda nota automática: o SDR distingue a nota do agente da nota de um colega.
PREFIXO = "[NAT]"

# 5 s, e não os 15 s do `add_timeline_comment`: a nota de recusa é gravada dentro do
# processamento do webhook da Meta — mesmo motivo do `timeout=5` do nat_flow.
TIMEOUT_PADRAO = 5.0


def com_prefixo(texto: str) -> str:
    """Garante o `[NAT]` na frente, sem duplicar se o chamador já pôs."""
    texto = (texto or "").strip()
    return texto if texto.startswith(PREFIXO) else f"{PREFIXO} {texto}"


async def registrar_observacao(lead_id: int | None, texto: str, *,
                               timeout: float = TIMEOUT_PADRAO) -> bool:
    """Grava `texto` na timeline do lead `lead_id` (o id NA EXACT). True se a Exact aceitou.

    Nunca levanta. Toda falha vira uma linha `❌ exact_note #<lead_id>: ...` e `False`.
    """
    if not lead_id:
        print(f"❌ exact_note #{lead_id}: sem lead_id da Exact — observação não gravada")
        return False
    try:
        corpo = {"leadId": int(lead_id), "userId": EXACT_BOT_USER_ID,
                 "text": com_prefixo(texto)}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{BASE_URL}/timelineAdd", headers=get_headers(),
                                     json=corpo)
        if resp.status_code in (200, 201, 204):
            print(f"📝 exact_note #{lead_id}: {corpo['text'][:80]!r}")
            return True
        print(f"❌ exact_note #{lead_id}: HTTP {resp.status_code} — {resp.text[:300]}")
        return False
    except Exception as e:
        print(f"❌ exact_note #{lead_id}: {type(e).__name__}: {e}")
        return False
