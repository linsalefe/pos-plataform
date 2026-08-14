"""Texto das mensagens da NAT e payloads dos botões. Só dados — sem banco, sem rede.

Os corpos em CORPO_APROVADO são cópia VERBATIM do que está aprovado no WABA (lido da Meta em
2026-07-26). Isso serve a duas coisas:

  1. quando a janela de 24h está aberta, a NAT manda texto livre — e o texto livre tem que ser
     o MESMO que o lead receberia por template, senão a conversa muda de voz dependendo de um
     detalhe técnico que ele não vê;
  2. o teste de drift (test_nat_flow.py, caso 13) compara isto com a Meta e avisa quando
     alguém editar o template lá sem mexer aqui — que é como a cópia apodrece em silêncio.

Editar o texto aqui NÃO muda o template aprovado. Se o template mudar na Meta, o certo é
trazer a mudança para cá, não o contrário.

--------------------------------------------------------------------------------------------
PAYLOAD DE BOTÃO

O roteamento é por payload, nunca por texto: "Prefiro outro horário" é o MESMO rótulo em
nat_boasvindas e em nat_reativacao_09h (Cenário 2). O payload é fixado no ENVIO
(send_template_message(button_payloads=...)) e volta em button.payload no webhook.

Quando o Cenário 2 entrar, ele ganha payloads próprios (ex.: NAT_REATIV_SIM) — é justamente
por isso que estes aqui não podem ser genéricos tipo "SIM".
"""

# Payloads dos botões do Cenário 1. Valores literais: é isto que chega no webhook.
NAT_SIM = "NAT_SIM"
NAT_OUTRO_HORARIO = "NAT_OUTRO_HORARIO"

# Payloads da recuperação (Bloco 6), disparada quando o SDR marca "não consegui contato".
# Separados de NAT_SIM/NAT_OUTRO_HORARIO embora o SENTIDO seja parecido ("falo agora" x "falo
# depois"): o que o roteamento precisa saber não é a intenção, é DE QUAL MENSAGEM o clique
# veio. Um NAT_SIM chegando em sem_contato seria indistinguível de um clique atrasado no botão
# da boas-vindas, e o fluxo trataria um lead que acabou de pedir nova ligação como quem está
# respondendo a uma pergunta de dez etapas atrás.
NAT_TENTAR_AGORA = "NAT_TENTAR_AGORA"
NAT_AGENDAR_OUTRO = "NAT_AGENDAR_OUTRO"

# Limite de caracteres do TÍTULO de botão em mensagem interativa (não-template) da Cloud API.
LIMITE_TITULO_BOTAO = 20

# Chaves das mensagens = nome do template que as respalda.
NAT_BOASVINDAS = "nat_boasvindas"
NAT_MSG_SIM = "nat_sim"
NAT_CONFIRMA_TRANSFERENCIA = "nat_confirma_transferencia"
NAT_MSG_OUTRO_HORARIO = "nat_outro_horario"
NAT_MSG_RECUPERACAO = "nat_recuperacao_sdr"

IDIOMA = "pt_BR"

# --------------------------------------------------------------------------------------------
# CORPOS APROVADOS — verbatim da Meta. Não "melhorar" o texto aqui.
CORPO_APROVADO = {
    NAT_BOASVINDAS: (
        "Olá, {{1}}! 😊\n"
        "Sou a Nat, assistente virtual do CENAT.\n"
        "Recebi sua aplicação para a Pós-Graduação em {{2}} e gostaria de agradecer pelo seu "
        "interesse!\n\n"
        "Nossa equipe está disponível neste momento e um dos nossos consultores pode falar com "
        "você nos próximos minutos.\n\n"
        "Essa conversa dura em torno de 10 minutos por ligação e tem como objetivo conhecer "
        "seus objetivos profissionais e apresentar os próximos passos da sua jornada "
        "acadêmica.\n\n"
        "Você tem alguns minutos disponíveis para conversar?"
    ),
    NAT_MSG_SIM: (
        "Perfeito, {{1}} 🌻\n"
        "Fico feliz em falar com você!\n"
        "Verifiquei em sua aplicação que sua formação é em {{2}}. Gostaria de entender melhor: "
        "o que despertou seu interesse na Pós-Graduação em {{3}}? Me conta um pouco mais 🙏"
    ),
    NAT_CONFIRMA_TRANSFERENCIA: (
        "Muito obrigada pelas informações, {{1}}😊\n"
        "Vou solicitar agora mesmo que um dos nossos consultores entre em contato com você!"
    ),
    NAT_MSG_OUTRO_HORARIO: (
        "Sem problemas 🙏\n"
        "Qual período costuma ser melhor para você?"
    ),
    # ⚠️ EXISTEM DOIS nat_recuperacao_sdr APROVADOS NO WABA, com corpos DIFERENTES: um em
    # `en` e este, em `pt_BR`. O envio pede language=IDIOMA (nat_sender), então o que o lead
    # recebe é o pt_BR — e é ele que está copiado aqui, verbatim, lido da Meta em 2026-08-14.
    # Quem for conferir drift precisa filtrar por idioma antes de indexar por nome; sem o
    # filtro, a comparação depende da ordem em que a Graph API devolve a lista.
    NAT_MSG_RECUPERACAO: (
        "Olá {{1}}! Tentamos falar com você há alguns minutos, mas não conseguimos concluir "
        "o contato. 🥺\n\n"
        "Ainda tenho muito interesse em ajudar você com sua aplicação para a Pós-Graduação "
        "em {{2}}. Gostaria de tentar novamente agora ou prefere agendar para outro período?"
    ),
}

# nat_sim SEM a formação do lead — {{1}} nome, {{2}} curso (o {{3}} do aprovado vira {{2}}).
#
# A formação vem do Exact e falta em ~49% dos leads. A saída aqui é REMOVER a frase inteira,
# não substituí-la por texto genérico: qualquer preenchimento ("sua área", "uma área ligada
# a...") seria a NAT afirmando algo sobre a formação do lead sem saber, e o lead percebe.
# Sem a frase, a mensagem continua íntegra — "Fico feliz em falar com você!" já emenda
# naturalmente em "Gostaria de entender melhor:".
CORPO_SEM_FORMACAO = {
    NAT_MSG_SIM: (
        "Perfeito, {{1}} 🌻\n"
        "Fico feliz em falar com você!\n"
        "Gostaria de entender melhor: o que despertou seu interesse na Pós-Graduação em {{2}}? "
        "Me conta um pouco mais 🙏"
    ),
}

# --------------------------------------------------------------------------------------------
# BOTÕES
#
# Texto aprovado no TEMPLATE (o que o lead vê quando recebe por template). Fica aqui só para o
# teste de drift conferir contra a Meta — o envio por template usa o rótulo que já está lá.
BOTOES_APROVADOS = {
    NAT_BOASVINDAS: ["Sim, Posso conversar agora", "Prefiro outro horário"],
    # Ordem lida da Meta, não escolhida aqui: o índice do botão no webhook vem do template
    # aprovado, e inverter esta lista trocaria "quer falar agora" por "quer falar depois" em
    # todo clique que caia no fallback por texto.
    NAT_MSG_RECUPERACAO: ["Tentar novamente agora", "Agendar outro horário"],
}

# Título dos MESMOS botões em mensagem livre (interactive), onde o limite é 20 caracteres.
# Os aprovados têm 26 e 21 — não cabem. Truncar por corte cego ("Sim, Posso conversar" /
# "Prefiro outro horári") deixaria um rótulo mutilado na tela do lead, então os títulos são
# encurtados à mão, preservando o sentido:
#
#   'Sim, Posso conversar agora' (26) -> 'Sim, posso agora'  (16)
#   'Prefiro outro horário'      (21) -> 'Outro horário'     (13)
#
# A ordem da lista É o índice do botão e tem que casar com a ordem aprovada no template.
BOTOES_LIVRES = {
    NAT_BOASVINDAS: [
        {"payload": NAT_SIM, "titulo": "Sim, posso agora"},
        {"payload": NAT_OUTRO_HORARIO, "titulo": "Outro horário"},
    ],
    # Recuperação (Bloco 6). Os aprovados têm 22 e 21 caracteres — nenhum dos dois cabe no
    # limite de 20. Encurtados à mão pelo mesmo critério da boas-vindas (preservar o sentido
    # em vez de cortar cego, que deixaria 'Tentar novamente ago' na tela do lead):
    #
    #   'Tentar novamente agora' (22) -> 'Tentar agora'   (12)
    #   'Agendar outro horário'  (21) -> 'Outro horário'  (13)
    NAT_MSG_RECUPERACAO: [
        {"payload": NAT_TENTAR_AGORA, "titulo": "Tentar agora"},
        {"payload": NAT_AGENDAR_OUTRO, "titulo": "Outro horário"},
    ],
}


def payloads_dos_botoes(chave: str) -> list | None:
    """Payloads por índice, para send_template_message(button_payloads=...)."""
    botoes = BOTOES_LIVRES.get(chave)
    if not botoes:
        return None
    return [b["payload"] for b in botoes]


def _preencher(corpo: str, valores: list) -> str:
    """Troca {{1}}, {{2}}... pelos valores. Mesma regra de whatsapp.render_template_text."""
    texto = corpo
    for i, valor in enumerate(valores):
        texto = texto.replace("{{" + str(i + 1) + "}}", str(valor) if valor is not None else "")
    return texto


def parametros_template(chave: str, *, nome: str = "", curso: str = "",
                        formacao: str = "") -> list | None:
    """Parâmetros do template, na ordem das variáveis aprovadas.

    Devolve None quando o template NÃO PODE ser montado com honestidade — hoje só o caso de
    nat_sim sem formação, que tem a formação como {{2}} obrigatória. O template aprovado tem a
    frase fixa "sua formação é em {{2}}"; mandar vazio deixaria "sua formação é em ." e mandar
    um genérico seria inventar dado do lead. Quem chama trata o None como "não envio".
    (Na prática isso não ocorre: nat_sim só sai depois de um clique, e clique abre a janela de
    24h, então o caminho é sempre texto livre — onde a frase simplesmente some.)
    """
    if chave == NAT_BOASVINDAS:
        return [nome, curso]
    if chave == NAT_MSG_SIM:
        if not (formacao or "").strip():
            return None
        return [nome, formacao, curso]
    if chave == NAT_CONFIRMA_TRANSFERENCIA:
        return [nome]
    if chave == NAT_MSG_OUTRO_HORARIO:
        return []
    if chave == NAT_MSG_RECUPERACAO:
        # {{1}} nome, {{2}} curso — as duas variáveis que a boas-vindas já usa. Sem a
        # formação, então não existe aqui o caso "não dá para montar com honestidade" que
        # obriga o nat_sim a devolver None.
        return [nome, curso]
    return None


def texto_livre(chave: str, *, nome: str = "", curso: str = "", formacao: str = "") -> str | None:
    """Mesma mensagem do template, pronta para ir como texto livre."""
    if chave == NAT_MSG_SIM and not (formacao or "").strip():
        return _preencher(CORPO_SEM_FORMACAO[NAT_MSG_SIM], [nome, curso])

    corpo = CORPO_APROVADO.get(chave)
    if corpo is None:
        return None
    return _preencher(corpo, parametros_template(
        chave, nome=nome, curso=curso, formacao=formacao) or [])
