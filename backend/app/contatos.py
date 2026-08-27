"""Um humano, uma conversa. Agrupa as duas grafias do mesmo telefone.

------------------------------------------------------------------------------------------
O PROBLEMA QUE ESTE MÓDULO RESOLVE
------------------------------------------------------------------------------------------
`contacts.wa_id` guarda o telefone como ele chegou, e o mesmo humano chega de dois jeitos:

    554192680313    12 dígitos — o `wa_id` que a Meta entrega no webhook (inbound)
    5541992680313   13 dígitos — o telefone do lead na Exact, com o 9º dígito

Medido em 27/08/2026 (`RECON_THREADS_DIVIDIDAS_20260827.md`): **406 pares, 812 contatos,
10% do Hub**, crescendo ~8 pares/dia. Em 257 deles a pessoa falou de um lado e nós do outro —
o SDR abre a thread e vê meia conversa, como se mensagens tivessem sumido. Não sumiram: a
conversa da Mikaelle alterna perfeitamente por timestamp entre as duas threads.

`app/telefone.py` já resolveu isso nas buscas do AGENTE. Este módulo leva a mesma regra para
a TELA e para a escrita.

------------------------------------------------------------------------------------------
POR QUE `variantes_wa_id` E NÃO `chave_telefone`
------------------------------------------------------------------------------------------
`chave_telefone` (DDD + últimos 8) é mais curta e daria uma chave de GROUP BY em SQL puro.
**Não use para agrupar contato.** Ela ignora o teste de "isto parece celular?" que
`variantes_wa_id` faz, e por isso funde um FIXO com um celular alheio:

    fixo   558622345678   -> chave '8622345678'
    outro  5586922345678  -> chave '8622345678'   <- MESMA chave, humanos DIFERENTES

`variantes_wa_id("558622345678")` devolve um elemento só (local começa em `2`, não é celular)
e o par nunca se forma. É essa recusa que protege contra entregar a conversa de alguém a
outro alguém — o mesmo motivo pelo qual `telefone.py` não sai somando 9 em tudo.

Consequência prática: o agrupamento acontece em Python, sobre a lista já carregada, e não em
SQL. `GET /contacts` já lê a tabela inteira sem paginar, então o custo é O(n) sobre o que já
estava na memória — e a regra continua morando num lugar só.

------------------------------------------------------------------------------------------
QUEM SOBREVIVE COMO REPRESENTANTE DO PAR
------------------------------------------------------------------------------------------
`principal_do_par` escolhe a grafia que **recebeu inbound**. Não é estética: é onde a pessoa
escreve, é o que a Meta considera canônico e é a forma que o SDR precisa ver para responder.
Dentro dos 406 pares, 817 dos 821 inbounds chegaram na grafia de 12 dígitos — o lado de 13 é,
na prática, um monólogo nosso.

Sem inbound em lado nenhum, cai para a mensagem mais recente; sem mensagem nenhuma, para a
ordem estável de `variantes_wa_id`. Nunca devolve None quando há membro.
"""
from app.telefone import variantes_wa_id


def chave_par(wa_id: str | None) -> str:
    """Chave de agrupamento. Os DOIS membros do par devolvem exatamente a mesma string.

        chave_par("5541992680313") == chave_par("554192680313")   # True

    Quem não forma par (estrangeiro, fixo, ilegível) vira chave de si mesmo e nunca se funde
    com ninguém.
    """
    v = variantes_wa_id(wa_id)
    return v[0] if v else (wa_id or "")


def principal_do_par(membros: list[str], *, tem_inbound=None, ultimo_ts=None) -> str:
    """A grafia que representa o par na tela. Ver o cabeçalho para o porquê da ordem.

    `tem_inbound` e `ultimo_ts` são funções `wa_id -> bool` / `wa_id -> datetime|None`.
    Quem chama já tem esses dados em mão (a query da lista devolve os dois), e passá-los
    evita que este módulo precise de sessão de banco.
    """
    if not membros:
        return ""
    if len(membros) == 1:
        return membros[0]

    def _posicao(w: str) -> int:
        # `variantes_wa_id` promete ordem estável (13 dígitos primeiro). Um wa_id que não
        # apareça na própria tupla (veio sem DDI, ou é formato que não sabemos ler) vai para
        # o fim em vez de levantar — esta função decide layout de tela, não pode quebrar.
        vs = variantes_wa_id(w)
        return vs.index(w) if w in vs else len(vs)

    ordem = sorted(membros, key=_posicao)

    if tem_inbound is not None:
        com_inbound = [w for w in ordem if tem_inbound(w)]
        if len(com_inbound) == 1:
            return com_inbound[0]
        if len(com_inbound) > 1 and ultimo_ts is not None:
            return max(com_inbound, key=lambda w: (ultimo_ts(w) is not None, ultimo_ts(w)))
        if len(com_inbound) > 1:
            return com_inbound[-1]

    if ultimo_ts is not None:
        com_msg = [w for w in ordem if ultimo_ts(w) is not None]
        if com_msg:
            return max(com_msg, key=ultimo_ts)

    # Nada para desempatar: a forma de 12 dígitos, que é para onde o inbound viria.
    return ordem[-1]


def agrupar(linhas: list[dict], *, wa: str = "wa_id") -> dict[str, list[dict]]:
    """`[{wa_id: ...}, ...]` -> `{chave_par: [linhas do mesmo humano]}`, ordem preservada."""
    grupos: dict[str, list[dict]] = {}
    for linha in linhas:
        grupos.setdefault(chave_par(linha.get(wa)), []).append(linha)
    return grupos


async def contato_existente(wa_id: str, db):
    """O `Contact` já gravado para este humano, em QUALQUER das duas grafias, ou None.

    É o coração da canonização na escrita: antes de criar contato, pergunte aqui. Se já
    existe um sob a outra grafia, escreva nele — é isso que impede o par de nascer.

    Ordem de preferência quando os DOIS existem (os 406 pares de hoje): o que já tem inbound,
    pela mesma razão de `principal_do_par`. Assim uma escrita nova nunca engorda o lado mudo.
    """
    from sqlalchemy import select, func
    from app.models import Contact, Message

    vs = variantes_wa_id(wa_id)
    if not vs:
        return None
    achados = list((await db.execute(
        select(Contact).where(Contact.wa_id.in_(vs)))).scalars())
    if not achados:
        return None
    if len(achados) == 1:
        return achados[0]

    com_inbound = set((await db.execute(
        select(Message.contact_wa_id)
        .where(Message.contact_wa_id.in_([c.wa_id for c in achados]),
               Message.direction == "inbound")
        .group_by(Message.contact_wa_id))).scalars())
    for c in achados:
        if c.wa_id in com_inbound:
            return c
    # Nenhum recebeu inbound: ordem estável, para dois processos concorrentes escolherem igual.
    ordem = {w: i for i, w in enumerate(vs)}
    return sorted(achados, key=lambda c: ordem.get(c.wa_id, 99))[-1]


async def canonizar(wa_id: str, db) -> str:
    """Sob qual `wa_id` GRAVAR. O do contato que já existe no par, ou o próprio se não há.

    É a peça que **para de criar divisão nova**. Chamada em todo ponto que escreve contato ou
    mensagem, ela faz o segundo caminho a chegar escrever no contato que o primeiro criou —
    em vez de abrir uma thread paralela com a outra grafia.

    ⚠️ **ISTO NÃO MUDA PARA ONDE A MENSAGEM É ENVIADA.** Só decide a chave de gravação. Quem
    resolve destinatário é `destinatario`, e só quando há inbound comprovando o endereço.
    A distinção importa: `telefone.py` avisa que eleger uma forma canônica poderia quebrar o
    ENVIO, porque não se sabe qual forma a Meta entrega. Continua verdade — e é por isso que
    a canonização fica do lado de cá, na escrita, onde errar não deixa ninguém sem receber.

    QUEM CHEGA PRIMEIRO DEFINE A GRAFIA, e isso é de propósito. Os dois sentidos acontecem:

        agente abre (13d) -> pessoa responde (12d)   -> o inbound grava no contato de 13d
        pessoa escreve (12d) -> agente responde      -> a abertura grava no contato de 12d

    Nos dois casos sai **uma** thread. Qual das duas grafias sobrou importa menos do que não
    haver duas — e a leitura já trata as duas como a mesma conversa de qualquer forma.
    """
    achado = await contato_existente(wa_id, db)
    return achado.wa_id if achado is not None else wa_id


async def destinatario(wa_id: str, db) -> str:
    """Para qual grafia ENVIAR. Devolve `wa_id` inalterado se não houver motivo para trocar.

    ⚠️ ESTA É A ÚNICA FUNÇÃO DESTE MÓDULO QUE MUDA O NÚMERO DISCADO — e ela só troca por uma
    grafia que **comprovadamente recebeu mensagem daquele humano**, nunca por uma inventada.

    `telefone.py` avisa que escolher uma forma canônica poderia quebrar o envio, e o aviso
    continua de pé: o envio para 13 dígitos funciona (a Mikaelle recebeu a abertura e
    respondeu). O que esta função faz é diferente de canonizar no escuro — se existe uma
    grafia da qual a pessoa JÁ NOS ESCREVEU, ela é o endereço vivo e comprovado, e é para lá
    que a resposta do SDR deve ir. Sem inbound em lado nenhum, nada muda.
    """
    from sqlalchemy import select
    from app.models import Message

    vs = variantes_wa_id(wa_id)
    if len(vs) < 2:
        return wa_id
    com_inbound = list((await db.execute(
        select(Message.contact_wa_id)
        .where(Message.contact_wa_id.in_(vs), Message.direction == "inbound")
        .group_by(Message.contact_wa_id))).scalars())
    if len(com_inbound) == 1:
        return com_inbound[0]
    return wa_id
