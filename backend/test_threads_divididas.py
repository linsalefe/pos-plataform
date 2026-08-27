"""Threads divididas: agrupamento na leitura (a) e canonização na escrita (b).

    cd backend && venv/bin/python test_threads_divididas.py

NADA sai daqui: o banco é dublê em memória, no mesmo padrão de `test_vigia_agente_mudo.py`.
Nenhuma chamada à Meta, nenhuma escrita em produção.

O QUE ESTE ARQUIVO GUARDA:

  1. `chave_par` funde as duas grafias do mesmo humano — e RECUSA fundir um fixo com o
     celular alheio que só difere pelo 9 (o motivo de não agrupar por `chave_telefone`)
  2. `principal_do_par`: vence a grafia que RECEBEU inbound, com os desempates abaixo
  3. caso Mikaelle — as duas metades voltam mescladas por timestamp, num GET só, e abrir
     por qualquer uma das pontas devolve a MESMA conversa
  4. envio pela thread agrupada resolve para a grafia de que a pessoa nos escreve
  5. abertura com contato pré-existente em 12d NÃO cria o de 13d
  6. lead 100% novo cria UM contato só
  7. a lista: N contatos viram M conversas, e quem não tem par não se funde com ninguém
"""
import asyncio
from datetime import datetime
from unittest.mock import MagicMock

from app.contatos import agrupar, chave_par, contato_existente, destinatario, principal_do_par
from app.models import Contact, Message
from app.telefone import variantes_wa_id

falhas = []

MIKA_12 = "554192680313"      # a grafia em que os inbounds dela chegam
MIKA_13 = "5541992680313"     # a grafia em que o agente respondeu


def checa(cond, rotulo):
    print(("  ✅ " if cond else "  ❌ ") + rotulo)
    if not cond:
        falhas.append(rotulo)


class Sessao:
    """Dublê de sessão. Responde `select(...)` a partir de listas em memória.

    Reconhece as duas formas que `contatos.py` usa: `select(Contact).where(...in_)` e
    `select(Message.contact_wa_id).where(...).group_by(...)`. O filtro é aplicado de
    verdade — um dublê que devolvesse tudo não provaria nada sobre o `IN (variantes)`.
    """

    def __init__(self, contatos=(), mensagens=()):
        self.contatos = list(contatos)
        self.mensagens = list(mensagens)
        self.adicionados = []
        self.consultas = 0

    def add(self, obj):
        self.adicionados.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def execute(self, stmt, *a, **kw):
        self.consultas += 1
        sql = str(stmt)
        alvo = _wa_ids_do_filtro(stmt)
        r = MagicMock()
        if "FROM contacts" in sql:
            achados = [c for c in self.contatos if c.wa_id in alvo]
            r.scalars.return_value = achados
            r.scalar_one_or_none.return_value = achados[0] if achados else None
        else:
            msgs = [m for m in self.mensagens if m.contact_wa_id in alvo]
            if "inbound" in sql or any(m.direction == "inbound" for m in msgs):
                msgs = [m for m in msgs if m.direction == "inbound"]
            r.scalars.return_value = sorted({m.contact_wa_id for m in msgs})
        return r


def _wa_ids_do_filtro(stmt):
    """Os valores do `IN (...)` compilado — é o que prova que a busca virou variantes.

    `in_()` compila para um bindparam EXPANSIVO: o valor do parâmetro é a lista inteira,
    não um valor por chave. Achatar aqui é o que faz o dublê filtrar de verdade.
    """
    alvo = set()
    for v in stmt.compile().params.values():
        if isinstance(v, str):
            alvo.add(v)
        elif isinstance(v, (list, tuple)):
            alvo.update(x for x in v if isinstance(x, str))
    return alvo


def _msg(wa, direcao, hhmm, texto, i):
    return Message(wa_message_id=f"wamid.{i}", contact_wa_id=wa, direction=direcao,
                   message_type="text", content=texto,
                   timestamp=datetime.fromisoformat(f"2026-08-26T{hhmm}:00"),
                   status="received" if direcao == "inbound" else "sent")


TURNOS = [
    (MIKA_12, "inbound",  "13:11", "Olá! Fiz minha aplicação na turma 3"),
    (MIKA_13, "outbound", "13:20", "Olá, Mikaelle! Recebi sua aplicação"),
    (MIKA_12, "inbound",  "13:22", "Oi! Conclui no final de 2023"),
    (MIKA_13, "outbound", "13:22", "Perfeito, Mikaelle"),
    (MIKA_12, "inbound",  "13:25", "Certo, obrigada."),
    (MIKA_12, "inbound",  "13:26", "gostaria de confirmar o horário"),
]
MENSAGENS = [_msg(*t, i) for i, t in enumerate(TURNOS)]


# ---------------------------------------------------------------------------------------
def teste_chave():
    print("\n=== 1. chave_par — funde o mesmo humano, recusa humanos diferentes ===")
    checa(chave_par(MIKA_12) == chave_par(MIKA_13),
          "as duas grafias da Mikaelle caem na mesma chave")
    checa(chave_par("8694169303") == chave_par("5586994169303"),
          "sem DDI e com DDI+9 caem na mesma chave")
    checa(chave_par("86994169303") == chave_par("558694169303"),
          "as quatro formas do mesmo humano convergem")

    # É por isto que o agrupamento NÃO usa `chave_telefone` (DDD + últimos 8): ela fundiria
    # estes dois, que são pessoas diferentes.
    from app.telefone import chave_telefone
    fixo, celular_alheio = "558622345678", "5586922345678"
    checa(chave_telefone(fixo) == chave_telefone(celular_alheio),
          "(premissa) chave_telefone FUNDE o fixo com o celular alheio")
    checa(chave_par(fixo) != chave_par(celular_alheio),
          "chave_par NÃO funde — fixo começa em 2, nunca ganha o 9")
    checa(chave_par("447834239129") != chave_par("4478342391290"),
          "número estrangeiro não ganha par")
    checa(chave_par("") == "" and chave_par(None) == "", "vazio não explode")


def teste_principal():
    print("\n=== 2. principal_do_par — vence quem RECEBEU inbound ===")
    membros = [MIKA_13, MIKA_12]
    checa(principal_do_par(membros, tem_inbound=lambda w: w == MIKA_12,
                           ultimo_ts=lambda w: 1 if w == MIKA_13 else 0) == MIKA_12,
          "12d vence mesmo com a mensagem mais recente na de 13d")
    checa(principal_do_par(membros, tem_inbound=lambda w: False,
                           ultimo_ts=lambda w: 2 if w == MIKA_13 else 1) == MIKA_13,
          "sem inbound em lado nenhum, vence a mensagem mais recente")
    checa(principal_do_par(membros, tem_inbound=lambda w: False,
                           ultimo_ts=lambda w: None) == MIKA_12,
          "sem nada para desempatar, cai na grafia de 12d (a que recebe)")
    checa(principal_do_par([MIKA_12]) == MIKA_12, "membro único devolve ele mesmo")
    checa(principal_do_par([]) == "", "lista vazia não explode")


def teste_mikaelle():
    print("\n=== 3. caso Mikaelle — a conversa volta INTEIRA e na ordem do relógio ===")
    vs = variantes_wa_id(MIKA_12)
    checa(set(vs) == {MIKA_12, MIKA_13}, "as variantes cobrem as duas metades")

    msgs = sorted([m for m in MENSAGENS if m.contact_wa_id in vs], key=lambda m: m.timestamp)
    checa(len(msgs) == 6, f"as 6 mensagens num GET só (vieram {len(msgs)})")
    checa([m.direction for m in msgs] ==
          ["inbound", "outbound", "inbound", "outbound", "inbound", "inbound"],
          "os turnos alternam — a conversa faz sentido lida em sequência")
    checa(len({m.contact_wa_id for m in msgs}) == 2, "e vieram das DUAS grafias")

    msgs13 = sorted([m for m in MENSAGENS if m.contact_wa_id in variantes_wa_id(MIKA_13)],
                    key=lambda m: m.timestamp)
    checa([m.wa_message_id for m in msgs13] == [m.wa_message_id for m in msgs],
          "abrir pela grafia de 13d devolve a MESMA conversa")

    # o que a tela mostrava ANTES: metade, e sem sentido
    so_uma = [m for m in MENSAGENS if m.contact_wa_id == MIKA_12]
    checa(len(so_uma) == 4 and all(m.direction == "inbound" for m in so_uma),
          "(antes) a thread de 12d sozinha eram 4 mensagens, todas dela, sem resposta")


def teste_envio():
    print("\n=== 4. envio pela thread agrupada resolve para a grafia certa ===")
    db = Sessao(contatos=[Contact(wa_id=MIKA_12), Contact(wa_id=MIKA_13)],
                mensagens=MENSAGENS)
    checa(asyncio.run(destinatario(MIKA_13, db)) == MIKA_12,
          "pedir envio para 13d resolve para 12d (a grafia de que ela nos escreve)")
    checa(asyncio.run(destinatario(MIKA_12, db)) == MIKA_12, "pedir para 12d fica em 12d")

    vazio = Sessao()
    checa(asyncio.run(destinatario("5511999998888", vazio)) == "5511999998888",
          "número sem histórico nenhum passa inalterado — nada é inventado")
    estrangeiro = Sessao()
    checa(asyncio.run(destinatario("447834239129", estrangeiro)) == "447834239129",
          "estrangeiro passa inteiro, e nem consulta o banco")
    checa(estrangeiro.consultas == 0, "sem variante, sem consulta (curto-circuito)")


def teste_escrita():
    print("\n=== 5. contato pré-existente em 12d NÃO vira par ===")
    db = Sessao(contatos=[Contact(wa_id=MIKA_12, name="Mikaelle")], mensagens=MENSAGENS)
    achado = asyncio.run(contato_existente(MIKA_13, db))
    checa(achado is not None and achado.wa_id == MIKA_12,
          "abrir por 13d encontra o contato de 12d que já existia")
    checa(db.adicionados == [], "e não criou contato nenhum")

    print("\n=== 6. lead 100% novo cria UM contato só ===")
    zerado = Sessao()
    checa(asyncio.run(contato_existente("5511987654321", zerado)) is None,
          "número inédito não encontra nada — é aí, e só aí, que se cria")
    depois = Sessao(contatos=[Contact(wa_id="5511987654321")])
    c = asyncio.run(contato_existente("551187654321", depois))
    checa(c is not None and c.wa_id == "5511987654321",
          "criado uma vez, a OUTRA grafia do mesmo humano já acha esse contato")

    print("\n   os dois lados existem: ganha o que tem inbound")
    dois = Sessao(contatos=[Contact(wa_id=MIKA_13), Contact(wa_id=MIKA_12)],
                  mensagens=MENSAGENS)
    c2 = asyncio.run(contato_existente(MIKA_13, dois))
    checa(c2 is not None and c2.wa_id == MIKA_12,
          "com os dois gravados, escreve no que recebe inbound — o lado mudo não engorda")


def teste_lista():
    print("\n=== 7. a lista: contatos viram conversas ===")
    linhas = [{"wa_id": MIKA_12}, {"wa_id": MIKA_13},
              {"wa_id": "5511987654321"},
              {"wa_id": "558622345678"},        # fixo
              {"wa_id": "5586922345678"},       # celular alheio, difere só pelo 9
              {"wa_id": "447834239129"}]        # estrangeiro
    g = agrupar(linhas)
    checa(len(g) == 5, f"6 contatos -> 5 conversas (achei {len(g)})")
    checa(any(len(v) == 2 for v in g.values()), "exatamente o par da Mikaelle se fundiu")
    checa(all(len(v) == 1 for k, v in g.items() if k != chave_par(MIKA_12)),
          "fixo, celular alheio e estrangeiro ficaram cada um por si")


if __name__ == "__main__":
    teste_chave()
    teste_principal()
    teste_mikaelle()
    teste_envio()
    teste_escrita()
    teste_lista()
    print("\n" + "=" * 72)
    if falhas:
        print(f"❌ {len(falhas)} FALHA(S):")
        for f in falhas:
            print(f"   - {f}")
        raise SystemExit(1)
    print("✅ tudo passou")
