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
