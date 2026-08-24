"""O LLM do agente: conversa dentro da etapa, mas NUNCA decide a etapa.

------------------------------------------------------------------------------------------
A DIVISÃO DE TRABALHO
------------------------------------------------------------------------------------------
    código  -> em que etapa o lead está, para onde ele vai, o que foi coletado, o que é
               enviado, e se é template ou texto livre
    LLM     -> como a frase é dita, e o que a resposta do lead significa

O LLM PROPÕE (`etapa_cumprida`, `acao`); quem dispõe é `qualificacao_fluxo`. Nenhuma etapa
muda por o modelo ter dito que mudou — muda porque o código leu a proposta, validou e
escreveu no banco.

------------------------------------------------------------------------------------------
FALHA FECHADA, NO PADRÃO DO PROJETO
------------------------------------------------------------------------------------------
Mesma regra de `nat_copy.parametros_template`: quando não dá para agir com honestidade,
devolve None e quem chama trata como "não envio". Aqui, `conversar` devolve None para:
timeout depois do retry, erro de rede, JSON inválido, campo faltando, tipo errado, `acao`
fora do enum, ou mensagem vazia.

None NÃO significa "tente de novo com outro prompt". Significa transferir para humano.

------------------------------------------------------------------------------------------
FATOS SÓ DE FORA
------------------------------------------------------------------------------------------
Tudo que o LLM pode AFIRMAR entra pelo contexto, montado por código: curso, formação,
data/hora da reunião e consultora vêm do banco; os slots vêm de `disponibilidade` e SÓ
quando a etapa é de agendamento; o conteúdo dos cursos vem dos chunks de
`knowledge_documents`.

E o que ele não pode afirmar está dito no prompt, explicitamente: VALOR NÃO EXISTE NA BASE.
Conferido — 0 de 18 chunks contêm "R$", não há tabela de preço no banco nem no código, e a
régua R$100/200/300 é critério humano (RECON §1.11). Sem essa linha o modelo inventa um
valor plausível, que é o pior desfecho possível numa conversa de venda.
"""
import json
import os

from openai import AsyncOpenAI

MODELO = "gpt-5-mini"

# Curto de propósito: isto roda DENTRO do processamento do webhook da Meta. Um modelo lento
# não pode segurar o lote de mensagens de todos os outros leads.
TIMEOUT_SEGUNDOS = 10.0
MAX_TENTATIVAS = 2          # a primeira e UMA repetição; depois, fallback
MAX_TOKENS = 400

ACOES_VALIDAS = frozenset({"nenhuma", "ofertar_agenda", "agendar_slot", "transferir_humano"})

# Cliente PREGUIÇOSO. Construir no import exigiria OPENAI_API_KEY presente para o módulo
# sequer carregar — e isso impediria `test_qualificacao.py` de exercitar o validador do
# contrato sem credencial, que é justamente o teste que mais importa. Também evita que uma
# variável ausente derrube o boot do backend inteiro por causa de um fluxo desligado.
_cliente = None


def _obter_cliente():
    global _cliente
    if _cliente is None:
        _cliente = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"),
                               timeout=TIMEOUT_SEGUNDOS)
    return _cliente

PROMPT_BASE = """Você é a Nat, assistente do CENAT (Centro Educacional Novas Abordagens em \
Saúde Mental). Conversa por WhatsApp com uma pessoa que acabou de se candidatar a uma \
pós-graduação.

COMO VOCÊ FALA
- Português do Brasil, calorosa e direta. Mensagens curtas, de conversa — não de e-mail.
- No máximo um emoji por mensagem, e só quando couber.
- Uma pergunta por mensagem. Nunca duas — e nada de confirmação no fim ("certo?", "né?"), que conta como segunda pergunta.
- NUNCA PEÇA PERMISSÃO PARA AGIR. Nada de "quer que eu...?", "posso...?", "você gostaria que eu...?", "posso seguir?". Você AVISA o que vai fazer; não pergunta se pode. Isso vale inclusive para passar o contato à consultora: você diz que vai passar, e pronto.
- Trate a pessoa pelo primeiro nome.

O QUE VOCÊ NUNCA FAZ
- NUNCA invente fato sobre o curso, a instituição ou a pessoa. Se não está no contexto \
abaixo, você não sabe.
- VALORES, PREÇOS, MENSALIDADES E DESCONTOS NÃO EXISTEM NA SUA BASE. Se perguntarem, \
responda que quem passa os valores e as condições é a consultora, na conversa — e siga com \
a sua pergunta da etapa. Não estime, não dê faixa, não diga "a partir de".
- NUNCA ofereça, confirme ou invente horário de reunião. Os horários disponíveis, quando \
existirem, estarão no contexto. Se não estiverem, você não tem nenhum.
- NUNCA prometa remarcar ou cancelar.

QUANDO PASSAR PARA UMA PESSOA (acao="transferir_humano")
Existem exatamente TRÊS motivos, e nenhum outro:
1. a pessoa pede para remarcar ou cancelar uma reunião QUE JÁ EXISTE — e ela só existe se estiver no contexto acima, como "Reunião já marcada para". Sem reunião no contexto, pedido de horário NÃO é remarcação: é assunto da consultora, motivo nenhum de transferência;
2. a pessoa pede para falar com um humano, um atendente ou a consultora AGORA;
3. a pessoa pede para parar de receber mensagens, se descadastrar, ou diz que não quer mais — respeite na hora, agradeça com educação e NÃO tente reverter.

EM QUALQUER OUTRO CASO, acao="nenhuma". Pedir um horário, querer agendar, perguntar quando será a reunião: NADA disso é motivo de transferência. A agenda tem um momento próprio mais adiante; agora a sua missão é outra.

VOCÊ NUNCA OFERECE TRANSFERÊNCIA. Transferir acontece quando a PESSOA pede — nunca por iniciativa sua, e nunca como pergunta.

NÃO SABER RESPONDER ALGO NÃO É MOTIVO DE TRANSFERÊNCIA. Preço, desconto, carga horária, reconhecimento, matrícula, documentos, horário: responda em UMA frase que quem passa esses detalhes é a consultora na conversa, e então TERMINE A MENSAGEM COM A PERGUNTA DA SUA MISSÃO. A última frase da sua mensagem é a pergunta da missão. acao="nenhuma".

QUANDO A AÇÃO FOR "transferir_humano", NÃO FAÇA PERGUNTA NENHUMA. Você está se despedindo: uma pergunta ali fica sem resposta para sempre, porque você não vai mais falar com essa pessoa.

SE A PESSOA MANDAR ÁUDIO, IMAGEM, FIGURINHA OU ARQUIVO (o histórico mostra "[a pessoa enviou um arquivo]"): diga com naturalidade que por aqui você só consegue ler texto, peça que ela escreva, e repita a pergunta da sua missão.

A AÇÃO TEM QUE CASAR COM A SUA MENSAGEM. Se você retomou a pergunta da etapa, a ação é "nenhuma". Se você se despediu ou encaminhou para uma pessoa, a ação é "transferir_humano". Mensagem que retoma a conversa com ação de transferência é contradição: o lead lê uma pergunta que nunca mais vai receber resposta.
- NUNCA repita uma pergunta que o contexto mostra já respondida.
- Se perguntarem se você é uma pessoa, um robô ou um bot: diga com naturalidade que é a assistente virtual do CENAT, sem constrangimento e sem se desculpar, e siga com a sua pergunta. NUNCA se passe por uma pessoa.

SUA MISSÃO NESTA MENSAGEM
{missao}

CONTEXTO VERIFICADO (tudo aqui é fato; o que não está aqui, você não sabe)
{contexto}

RESPONDA SOMENTE COM UM OBJETO JSON, sem markdown, exatamente com estas chaves:
{{"mensagem": "o que enviar à pessoa, em texto puro",
  "etapa_cumprida": true ou false,
  "dado_extraido": {{"campo": "valor"}} ou null,
  "acao": "nenhuma" | "ofertar_agenda" | "agendar_slot" | "transferir_humano"}}

Regras do JSON:
- "etapa_cumprida" é true SÓ quando a pessoa respondeu de fato o que a missão pedia. \
Desconversou, perguntou outra coisa, ou respondeu outra coisa? false, e a sua "mensagem" \
acolhe o que ela disse e retoma a pergunta.
- "dado_extraido" traz o que você entendeu da resposta DELA, com o nome de campo que a \
missão indicar. Nada inferido: só o que ela disse.
- "acao" é "nenhuma" salvo instrução em contrário na missão."""


def _validar(bruto) -> dict | None:
    """O JSON do modelo, validado contra o contrato. None se qualquer coisa estiver fora.

    Rígido de propósito: um campo faltando ou um tipo errado significa que o modelo saiu do
    contrato, e um agente que "dá um jeito" quando o contrato quebra é um agente que vai
    improvisar em produção. Fora do contrato → humano.
    """
    if not bruto or not isinstance(bruto, str):
        return None
    texto = bruto.strip()
    # Cinto e suspensório: o modelo às vezes embrulha em cerca de markdown mesmo com
    # response_format json_object.
    if texto.startswith("```"):
        texto = texto.strip("`").strip()
        if texto.lower().startswith("json"):
            texto = texto[4:].strip()
    try:
        dados = json.loads(texto)
    except (ValueError, TypeError):
        return None
    if not isinstance(dados, dict):
        return None

    mensagem = dados.get("mensagem")
    if not isinstance(mensagem, str) or not mensagem.strip():
        return None
    if not isinstance(dados.get("etapa_cumprida"), bool):
        return None
    acao = dados.get("acao")
    if acao not in ACOES_VALIDAS:
        return None
    extraido = dados.get("dado_extraido")
    if extraido is not None and not isinstance(extraido, dict):
        return None
    if isinstance(extraido, dict):
        # Só texto. Um dict aninhado viraria str() feio dentro de uma coluna TEXT.
        extraido = {str(k): str(v) for k, v in extraido.items()
                    if v is not None and not isinstance(v, (dict, list))}

    return {
        "mensagem": mensagem.strip(),
        "etapa_cumprida": dados["etapa_cumprida"],
        "dado_extraido": extraido or None,
        "acao": acao,
    }


def montar_contexto(fatos: dict) -> str:
    """Os fatos verificados, um por linha. Chave vazia é OMITIDA, nunca vira "não informado".

    Omitir é diferente de dizer "desconhecido": o modelo trata "Curso: não informado" como um
    fato sobre o qual pode comentar. O que não está no contexto, ele não sabe.
    """
    linhas = []
    for rotulo, valor in fatos.items():
        if valor is None or valor == "" or valor == []:
            continue
        if isinstance(valor, (list, tuple)):
            linhas.append(f"{rotulo}:")
            linhas.extend(f"  - {v}" for v in valor)
        else:
            linhas.append(f"{rotulo}: {valor}")
    return "\n".join(linhas) if linhas else "(sem fatos adicionais)"


async def conversar(*, missao: str, contexto: str, historico: list) -> dict | None:
    """Uma rodada de conversa. Devolve o dict do contrato, ou None (→ transferir humano).

    `historico` é [{"role": "user"|"assistant", "content": str}], já recortado por quem
    chama. Vem do banco, não da memória do modelo: cada chamada é independente.
    """
    mensagens = [{"role": "system",
                  "content": PROMPT_BASE.format(missao=missao, contexto=contexto)}]
    mensagens.extend(historico or [])

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            extra = {"reasoning_effort": "minimal"} if MODELO.startswith("gpt-5") else {}
            resposta = await _obter_cliente().chat.completions.create(
                model=MODELO,
                messages=mensagens,
                max_completion_tokens=MAX_TOKENS,
                response_format={"type": "json_object"},
                **extra,
            )
            validado = _validar(resposta.choices[0].message.content)
            if validado is not None:
                return validado
            print(f"⚠️  Agente/LLM: resposta fora do contrato "
                  f"(tentativa {tentativa}/{MAX_TENTATIVAS})")
        except Exception as e:
            print(f"⚠️  Agente/LLM: {type(e).__name__}: {e} "
                  f"(tentativa {tentativa}/{MAX_TENTATIVAS})")

    # Esgotou. Não improvisa: quem chama transfere para humano.
    return None
