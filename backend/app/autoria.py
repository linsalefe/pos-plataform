"""Quem apertou enviar. Uma pergunta, um lugar.

Existe por causa de uma armadilha concreta, e não para embrulhar um `getattr`.

A ARMADILHA
------------------------------------------------------------------------------------------
`exact_routes.bulk_send_template` declara `current_user: User = Depends(get_current_user)`
na ASSINATURA, e é chamada de dois jeitos:

    HTTP (o Hub)                 -> o FastAPI resolve a dependência: `current_user` é User
    main.py:238 (job agendado)   -> chamada Python direta, 2 argumentos: `current_user`
                                    recebe o PRÓPRIO objeto `Depends`, não um User

O segundo caso não estoura: `Depends` é um objeto qualquer, e `getattr(x, "id", None)`
devolve None sem reclamar. Foi assim que `_silenciar_agente_apos_envio_manual` sempre
funcionou — por acidente feliz, não por decisão.

`sent_by` é FK para `users(id)`. Um dia alguém escreve `current_user.id` direto e o disparo
agendado morre em AttributeError no meio do lote, ou — pior — um objeto errado vira um id
que existe. `isinstance` fecha as duas portas: só um `User` de verdade vira autoria.

NULL É RESPOSTA, NÃO LACUNA. `sent_by IS NULL` quer dizer "não foi humano logado" e cobre
três casos legítimos: o agente (`nat_sender`), a boas-vindas automática (`exact_spotter`) e
o disparo agendado (que roda sem sessão). Quem ler o dado precisa dessa distinção — inventar
um usuário "sistema" para preencher a coluna apagaria justamente o que ela informa.
"""
from app.models import User


def quem_enviou(current_user) -> int | None:
    """id do humano logado que disparou este envio, ou None se não houve um.

    Tolerante de propósito: recebe o que a rota tiver na mão, incluindo o objeto `Depends`
    da chamada interna e `None`.
    """
    return current_user.id if isinstance(current_user, User) else None


# ------------------------------------------------------------------------------------------
# S6-3 — O NOME DE QUEM ASSINA O TEMPLATE
# ------------------------------------------------------------------------------------------
# 43 dos 82 envios de `tentativa_contato` na janela 24/08-01/09 (52%) saíram assinados com o
# NOME DO CURSO no lugar do nome de quem fala. 42 pessoas leram, literalmente:
#
#     "Ola Daiane, é o PsicologiaEscolar do CENAT ✨"
#     "Ola Vitória, é o Transtorno do Espectro Autista (TEA) do CENAT ✨"
#
# A causa está no default posicional da tela (`automacoes/page.tsx:selectTemplate`), que
# chutava `lead_course` para o segundo `{{n}}` de QUALQUER template. Este mapeamento é a
# outra metade do conserto: um tipo que diz "quem está mandando", em vez de o operador ter
# que lembrar de trocar o dropdown.
#
# POR QUE NÃO `sdr_name` (que já existia). Aquele resolve `exact_leads.sdr_name` — o DONO do
# lead na Exact, que é outra pessoa: 4 496 leads são da Victória e 2 091 do Thobias. Um
# template que diz "tentei falar com você" assinado pelo dono do lead mente quando quem
# tentou foi outro. Os dois tipos convivem porque respondem a perguntas diferentes:
# `sdr_name` = de quem é o lead; `sdr_logado` = quem está mandando esta mensagem agora.
SDR_PADRAO = "Thobias"


def nome_de_quem_enviou(current_user) -> str:
    """Nome para assinar o template. NUNCA vazio.

    O disparo AGENDADO roda sem sessão (ver a armadilha do `Depends` acima) e mesmo assim
    precisa de um nome: `{{n}}` em branco faz a Meta recusar a mensagem INTEIRA com #131008,
    e o lead não recebe nada. `SDR_PADRAO` é o operador de plantão da tela de Automações —
    trocar de pessoa é trocar esta constante, e é de propósito que isso seja uma linha
    visível no código e não uma configuração escondida.
    """
    if isinstance(current_user, User) and (current_user.name or "").strip():
        return current_user.name.strip()
    return SDR_PADRAO
