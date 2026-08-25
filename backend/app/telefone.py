"""Chave tolerante de telefone. Casa o MESMO humano escrito de quatro jeitos.

------------------------------------------------------------------------------------------
O PROBLEMA, MEDIDO EM 25/08/2026
------------------------------------------------------------------------------------------
A Exact guarda o telefone com o 9º dígito; o WhatsApp entrega o `wa_id` SEM ele para DDD
fora da região 11–28. Os dois nunca se encontram:

    exact_leads.phone1        13 dígitos: 8 348   ·  12 dígitos: 209
    messages.contact_wa_id    13 dígitos: 2 625   ·  12 dígitos: 3 780

Provado em produção, no mesmo humano, no mesmo dia:

    24/08 16:37  558694169303   inbound   "Fiz minha aplicação na turma…"
    24/08 16:48  5586994169303  outbound  template "Sou a Nat…"
    24/08 17:20  558694169303   inbound   botao:"Sim, Posso conversar agora"

**340 pessoas (5% do Hub) já existem com duas threads por causa disso.**

`exact_spotter.format_phone` só prefixa `55` — ele normaliza o DDI e ignora o 9º dígito, que
é justamente onde está a divergência. Para o agente de qualificação isso é fatal: o estado
nasce com a chave montada a partir do telefone do LEAD (13 dígitos) e o inbound chega com 12.
Comparação por igualdade → o agente não reconhece a própria conversa, e cala.

------------------------------------------------------------------------------------------
POR QUE VARIANTES, E NÃO UMA FORMA CANÔNICA
------------------------------------------------------------------------------------------
A tentação é escolher um formato e converter tudo. Não dá, por dois motivos:

  * **O que já está gravado não se move.** Reescrever `contact_wa_id` de `messages`,
    `contacts` e das tabelas de estado é migração de dados sobre 6 451 threads vivas, com
    UNIQUE no caminho — risco desproporcional para um problema de LEITURA.
  * **Não se sabe qual forma entrega.** O envio para `5586994169303` funcionou (a pessoa
    recebeu e clicou). Escolher a outra forma como canônica poderia quebrar o envio, que
    hoje funciona.

Então nada muda na ESCRITA. O que muda é a BUSCA: em vez de `== wa_id`, `IN (variantes)`.
Reversível, sem migração, e o pior caso é achar o que antes não achava.

------------------------------------------------------------------------------------------
POR QUE NÃO SAI ADICIONANDO 9 EM TUDO
------------------------------------------------------------------------------------------
Celular brasileiro pré-2012 começava em 6–9; fixo começa em 2–5. Um fixo `86 2234-5678`
com um 9 na frente vira `86 9223-4567 8` — que é um celular **de outra pessoa**. Por isso a
variante só nasce quando o número local tem cara de celular. Uma colisão silenciosa aqui
entregaria a conversa de alguém a outro alguém.

Número que não é brasileiro (`447834239129`, `245956444415` — os dois existem na base) passa
inteiro, sem variante nenhuma. Não sabemos ler o plano de numeração deles, e chutar seria pior
que não casar.

------------------------------------------------------------------------------------------
ONDE ISTO É USADO
------------------------------------------------------------------------------------------
`variantes_wa_id` nas BUSCAS do agente de qualificação (estado, histórico, contato, guard).
`chave_telefone` para casar conjuntos — a admissão do lead espontâneo contra `exact_leads`.

Módulo sem import nenhum, de propósito: ele é chamado do caminho da landing page, e
`qualificacao_gatilho` já documenta a regra de não arrastar a cadeia de envio do WhatsApp
para dentro do request do visitante.
"""

# Números locais de celular começam aqui. Fixo (2–5) nunca ganha um 9.
INICIO_CELULAR = "6789"


def digitos(bruto: str | None) -> str:
    return "".join(c for c in (bruto or "") if c.isdigit())


def variantes_wa_id(bruto: str | None) -> tuple[str, ...]:
    """Todas as formas em que este número pode estar gravado. Determinística.

    Sempre com DDI e sempre com a forma de 13 dígitos primeiro, quando as duas existem —
    quem usa isto para ESCOLHER (e não só para buscar) precisa de uma ordem estável.

        variantes_wa_id("5586994169303") -> ("5586994169303", "558694169303")
        variantes_wa_id("558694169303")  -> ("5586994169303", "558694169303")
        variantes_wa_id("86994169303")   -> ("5586994169303", "558694169303")
        variantes_wa_id("8694169303")    -> ("5586994169303", "558694169303")

    Os quatro formatos do mesmo humano devolvem exatamente o mesmo par. É essa igualdade
    que o teste trava.
    """
    d = digitos(bruto)
    if not d:
        return ()
    # Sem DDI: 10 (DDD + 8) ou 11 (DDD + 9). Mesma suposição que `format_phone` sempre fez.
    if len(d) in (10, 11):
        d = "55" + d
    if not (d.startswith("55") and len(d) in (12, 13)):
        return (d,)                       # estrangeiro, ou formato que não sabemos ler
    ddd, local = d[2:4], d[4:]
    if len(local) == 9 and local[0] == "9":
        return (d, "55" + ddd + local[1:])
    if len(local) == 8 and local[0] in INICIO_CELULAR:
        return ("55" + ddd + "9" + local, d)
    return (d,)                            # fixo, ou celular que já não bate o padrão


def chave_telefone(bruto: str | None) -> str:
    """DDD + últimos 8 dígitos. Para casar CONJUNTOS (um lado nosso, outro da Exact).

    Imune ao 9º dígito e ao DDI de uma vez só, e é o que permite perguntar "este wa_id tem
    lead?" com um `in` de custo constante em vez de varrer 8 636 telefones.

    Devolve `""` para o que não dá para reduzir — e `""` NUNCA casa: quem usa isto para
    decidir admissão precisa que o ilegível caia fora, não que caia dentro.
    """
    d = digitos(bruto)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    return d[:2] + d[-8:] if len(d) in (10, 11) else ""
