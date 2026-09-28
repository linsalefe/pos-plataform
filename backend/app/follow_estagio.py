"""Follow automático dirigido pelo estágio da Exact. O lead entra em `Follow N`, o template sai.

    Gatilho:  uma linha nova em `exact_stage_events` com `funnel_id = 18535` e
              `stage_para` em um dos nove nomes de `follow_estagios.json`.
    Ação:     UM `bulk_send_template` com aquele lead só, com o template e os parâmetros
              do mapa.
    Garantia: uma vez por estágio por lead, PARA SEMPRE (a UNIQUE da tabela).

Contexto completo e todos os números citados aqui: `RECON_FOLLOW_AUTOMATICO_20260927.md`.
Molde do laço, do gate e do `_finalizar`: `app/rd_sender.py`, que por sua vez é uma cópia
reduzida de `app/nat_scheduler.py` — o cabeçalho de lá explica cada camada.

==========================================================================================
O QUE ISTO MUDA, EM NÚMERO
==========================================================================================
§1.4 do recon: das 1 255 entradas em estágio de follow do 18535 nos últimos 30 dias, só
**35 % a 51 %** foram seguidas de um template em 24 h, e o `" Follows 9"` — a despedida —
saiu em **2 % (1 de 63)**.

Automatizar não transfere trabalho: **mais que dobra** o volume de follows que sai do número
(de ~396 em 26 dias para ~1 062) e **multiplica por ~60** a despedida. No volume ATUAL a Meta
já devolveu 17 × `131049` ("not delivered to maintain healthy ecosystem") em 30 dias. É por
isso que o gate nasce fechado e o modo de teste por allowlist existe: a primeira medição
depois de ligar não pode ser feita no lead real.

==========================================================================================
DUAS DECISÕES DO ÁLEFE, EXPLÍCITAS (27/09)
==========================================================================================
**SEM JANELA DE HORÁRIO.** O template sai na hora, inclusive 21h e sábado. `nat_guard.
dentro_horario_comercial` (09h–18h30, seg–sex) existe e NÃO é chamada aqui, de propósito.
Medido: 95 % das entradas caem dentro da janela sozinhas (1 191 de 1 254); as outras 63 são
57 depois das 18h30 e 6 num sábado. O custo da decisão é conhecido e é esse.

**SEM TETO DE RAJADA.** Todos os eventos da passada são enviados em sequência, com
`asyncio.sleep(2)` entre eles. Medido: a maior rajada em 30 dias foi **45 leads entrando em
`" Follows 9"` numa única passada** (18/09, 18:18 SP) — com 2 s, são ~90 s de envio contínuo,
e o ciclo seguinte só começa depois. Se a nota de qualidade do número cair, é aqui que um teto
nasce, e `MAX_POR_CICLO` já é o lugar.

==========================================================================================
O QUE ESTE JOB **NÃO** REIMPLEMENTA
==========================================================================================
O envio é `exact_routes.bulk_send_template(payload, db)`, chamada como função Python — não
por HTTP. `main.py:238` já faz exatamente isso há meses (o consumidor de
`scheduled_messages`), e `app/autoria.py` existe para sustentar esse caminho:
`current_user` recebe o próprio objeto `Depends` e `quem_enviou()` devolve `None` porque não
houve humano logado, que é a informação certa.

Com isso vêm de graça, sem uma linha aqui:

  * a recusa de 30 dias e o novo `opt_out_meta` (`higiene_disparo.por_que_pular`);
  * ~~o pulo por conversa ativa do agente (`nat_ativa`)~~ — SAIU em 27/09: desde então o
    envio ENCERRA o agente do lead, e este job passa `motivo_agente="follow_estagio"`;
  * a canonização das duas grafias do telefone contra o eco da Meta, que é o que evita a
    `ForeignKeyViolation` dos 5 × HTTP 500 de 28/08;
  * a criação do `Contact` e o vínculo do SDR;
  * o `Message` com `template_name` e o texto renderizado (o que a tela de Conversas mostra);
  * o silenciamento do agente na thread (`_silenciar_agente_apos_envio_manual`);
  * a linha durável em `disparo_skip` quando pula;
  * a trava do template de boas-vindas.

São nove regras. Reimplementá-las é o caminho que produziu aqueles 5 × 500, quando metade de
uma correção foi trazida e a outra não.

==========================================================================================
A PERDA DE 1,5 % É ACEITA, E ESTÁ AQUI PARA QUEM FOR INVESTIGAR
==========================================================================================
`exact_spotter.py:531` compara ESTADO com ESTADO a cada 600 s. Quando o SDR move o lead duas
vezes dentro da mesma passada, o estágio do meio **nunca gera evento** — e portanto nunca
gera follow. Medido: **19 de 1 278 transições (1,5 %) em 30 dias, 10 delas no `Follow 1`**
(§1.3 do recon).

    lead 52050552  24/09 15:26
       EXACT : Follow 1->Follow 2@15:26, Follow 2->Follow 3@15:28
       NOSSO : Follow 1->Follow 3@15:36        <- o Follow 2 não existiu para nós

Aceito por decisão (27/09). O conserto, quando incomodar, é trocar o gatilho por
`GET /v3/LeadStages`, que tem o relógio da Exact, tem `cycle` e não perde o degrau do meio —
ver "Observações pra depois" no prompt da sprint. Não é um bug deste módulo: é uma propriedade
da fonte que ele lê.

==========================================================================================
FUSO: TUDO UTC
==========================================================================================
`exact_stage_events.observado_em`, `follow_estagio_envios.created_at` e `enviado_em` são todos
`now() AT TIME ZONE 'utc'`, e o Python aqui usa `datetime.utcnow()`. Mesma exceção deliberada
de `rd_conversoes` (ver a docstring de `RdConversao`), e pelo mesmo motivo: estes instantes são
o relógio do drenador, não hora de parede.

O único lugar com relógio de SP é o `mes` do `mensagem_follow7`, que é hora de parede de
verdade — resolvido por `follow_estagio_mapa.mes_corrente_sp()`. Um `utcnow()` ali erraria o
mês nas três primeiras horas do dia 1º.
"""
import asyncio
import json
import os
from datetime import datetime

from sqlalchemy import select, text, update

from app.database import async_session
from app.follow_estagio_mapa import (MapaInvalido, estagio_para, estagios_do_mapa,
                                     funil_alvo, montar_mappings, resolver)
from app.models import (FE_ENVIADO, FE_FALHOU, FE_PENDENTE, FE_SKIPPED, ExactLead,
                        FollowEstagioEnvio)
from app.telefone import chave_telefone

# Mesmo passo dos outros jobs do main.py. Um follow esperar até 60s é irrelevante contra a
# latência de 4,8 min (p50) do próprio sync que produz o evento.
INTERVALO_SEGUNDOS = 60

# Teto de eventos LIDOS por passada. Não é teto de rajada (a sprint decidiu não ter): é a
# trava contra o acidente de o cursor ser zerado à mão, quando 1 255 eventos de histórico
# passariam a caber numa só leitura. Com 400, um cursor zerado leva 4 passadas para chegar ao
# presente em vez de uma — e 4 minutos é tempo de alguém ver no journald e desligar o gate.
MAX_EVENTOS_POR_CICLO = 400

# Envios por passada. ~42 entradas/dia é a média; 100 cobre a maior rajada medida (45) com
# folga de mais que o dobro. O que sobrar fica `pendente` e sai no ciclo seguinte.
MAX_POR_CICLO = 100

# Entre envios. `bulk_send_template` já tem `asyncio.sleep(1)` interno por lead
# (`exact_routes.py:601`), então o intervalo real é ~3 s. 2 s aqui é a decisão da sprint, e
# some junto se um dia o envio virar lote de verdade.
ESPERA_ENTRE_ENVIOS_SEGUNDOS = 2

# Corpo da resposta guardado para diagnóstico, não para auditoria. 2000 chars cobrem o retorno
# do bulk com a lista de pulados; um traceback longo não acrescenta.
LIMITE_RESPOSTA = 2000

# O canal. Há um só (`channels.id = 1`, "Pós-Graduação (SDR)"), e a rota já usa 1 como default.
# Explícito aqui porque este payload é montado à mão e não passa pela tela.
CANAL_ID = 1
IDIOMA = "pt_BR"

MOTIVO_SEM_TELEFONE = ("o lead não tem phone1 na Exact — preencha o telefone e mova de novo")


def _agora_sp() -> datetime:
    """Hora de parede de São Paulo, naive — só para o texto da observação que o SDR lê."""
    from app.nat_guard import _agora_sp as agora_sp
    return agora_sp()


def texto_nota_follow(estagio_nome: str | None, template: str, quando: datetime) -> str:
    """A observação do follow na Exact. `quando` é SP naive.

    O nome do estágio JÁ traz a palavra ("Follow 3", " Follows 9" — com o espaço à esquerda
    da Exact, que sai no `strip`). Por isso não se escreve "Follow <nome>", que daria
    "Follow Follow 3".
    """
    nome = (estagio_nome or "").strip() or "?"
    return (f"[NAT] {nome} enviado pela IA em {quando:%d/%m %H:%M} "
            f"(template {template}).")


def _agora_utc() -> datetime:
    return datetime.utcnow()


def _ligado() -> bool:
    """`FOLLOW_ESTAGIO_ENABLED` lido a cada ciclo, sem cache.

    Sem cache de propósito, mesma regra de `rd_sender._envio_ligado`: o operador tem de
    conseguir desligar editando o `.env` e reiniciando, sem depender de o processo ter subido
    no momento certo.

    Aceita `true`, `1`, `sim`, `yes` — **qualquer outra coisa, inclusive vazio, é DESLIGADO**.
    A falha é fechada por escolha: uma variável escrita errada resulta em nenhum follow, não
    em 1 255 templates saindo sem ninguém ter conferido o mapa.
    """
    return (os.getenv("FOLLOW_ESTAGIO_ENABLED", "") or "").strip().lower() in (
        "true", "1", "sim", "yes")


def allowlist() -> frozenset[str]:
    """As chaves de telefone do modo de teste. Vazio = todos os leads entram.

    `FOLLOW_ESTAGIO_SOMENTE_TELEFONES` é lista separada por vírgula, em qualquer grafia:
    `83988046720`, `5583988046720`, `558388046720` e `8388046720` viram a MESMA chave.

    Casa pela **chave tolerante** (`telefone.chave_telefone`, DDD + últimos 8 dígitos) e não
    por igualdade, porque o mesmo humano está gravado de duas formas: a Exact guarda o 9º
    dígito, o WhatsApp entrega sem ele para DDD fora de 11–28. O número de teste do Álefe é
    exatamente esse caso — `5583988046720` em `exact_leads`, `558388046720` nos inbounds, duas
    threads em `contacts`. Igualdade crua deixaria o teste passar por acaso ou falhar por
    acaso, dependendo de qual grafia o operador digitasse no `.env`.

    Chave ilegível (`''`) é DESCARTADA da allowlist: `''` casa com `''`, e uma entrada torta no
    `.env` ligaria o follow para todo lead de telefone ilegível — o oposto de uma allowlist.
    """
    cru = os.getenv("FOLLOW_ESTAGIO_SOMENTE_TELEFONES", "") or ""
    return frozenset(c for c in (chave_telefone(p) for p in cru.split(",")) if c)


async def _cursor(db) -> int | None:
    """O `ultimo_evento_id`, com a linha TRAVADA para esta transação. None se não há linha.

    `FOR UPDATE` e não leitura solta: o cursor é lido, usado para filtrar e reescrito na mesma
    transação. Sem o lock, dois processos (um segundo worker, um restart com sobreposição,
    alguém rodando o drenador num shell) leriam o mesmo valor e enfileirariam os mesmos
    eventos — a UNIQUE salvaria do duplo envio, mas o índice é a rede, não o mecanismo.

    **None é FALHA FECHADA, não zero.** Linha ausente significa migração não rodada (ou
    `create_tables.py` tendo criado a tabela vazia, que é o caminho que não inicializa o
    `MAX(id)`). Tratar como 0 varreria o histórico inteiro — os 1 255 follows que o cabeçalho
    de `FollowEstagioCursor` descreve. Na dúvida, não processa.
    """
    linha = (await db.execute(text(
        "SELECT ultimo_evento_id FROM follow_estagio_cursor WHERE id = 1 FOR UPDATE"))).first()
    return None if linha is None else int(linha[0])


async def _eventos_novos(db, cursor: int, estagios: tuple[str, ...]) -> list:
    """Os eventos ainda não olhados que interessam. Já com os dados do lead.

    **O FILTRO INTEIRO MORA NA QUERY** (critério 2 da sprint), e não num `if` depois:

      * `funnel_id = :funil` — quatro funis têm etapa chamada `Follow 1`, e o **18285 é
        Intercâmbio**, com 703 entradas em 30 dias (§1.1 do recon). Um `if` em Python leria
        essas 703 linhas a cada passada só para descartá-las, e um `continue` esquecido
        mandaria template de pós para Intercâmbio.
      * `stage_para = ANY(:estagios)` — os nove nomes do mapa, byte a byte, com o espaço à
        esquerda de `" Follows 7"` e `" Follows 9"`. Comparação exata, sem `ILIKE` e sem
        `trim()`: `Follow 2 - Vi` (funil 20647) e `Ultimo follow (Descarte)` (18285) não podem
        entrar por semelhança.
      * `id > :cursor ORDER BY id LIMIT` — a marca d'água.

    O LEFT JOIN traz o lead na MESMA consulta. `LEFT` e não `INNER` de propósito: um evento de
    lead que já não está no espelho (há 10 assim, §1.3) tem de ser CONSUMIDO — avançar o
    cursor por cima dele —, não ficar preso para sempre bloqueando os seguintes. Ele sai com
    `lead_id IS NULL` e é marcado como olhado sem virar linha.

    `el.id` é o **PK local**, que é o que `bulk_send_template` recebe em `lead_ids`;
    `e.exact_lead_id` é o id na Exact, que é o que vai para a UNIQUE. As duas viajam juntas
    justamente para o chamador não ter que escolher errado.
    """
    return (await db.execute(text("""
        SELECT e.id            AS evento_id,
               e.exact_lead_id AS lead_exact_id,
               e.stage_de      AS stage_de,
               e.stage_para    AS stage_para,
               e.funnel_id     AS funnel_id,
               e.observado_em  AS observado_em,
               el.id           AS lead_id,
               el.name         AS lead_nome,
               el.phone1       AS telefone,
               el.sdr_name     AS sdr_name,
               el.sub_source   AS sub_source
          FROM exact_stage_events e
          LEFT JOIN exact_leads el ON el.exact_id = e.exact_lead_id
         WHERE e.id > :cursor
           AND e.funnel_id = :funil
           AND e.stage_para = ANY(:estagios)
         ORDER BY e.id
         LIMIT :limite
    """), {"cursor": cursor, "funil": funil_alvo(), "estagios": list(estagios),
           "limite": MAX_EVENTOS_POR_CICLO})).mappings().all()


async def _enfileirar(db, evento, entrada, permitidos: frozenset[str]) -> str:
    """Cria (ou não) a linha `pendente` deste evento. Devolve um rótulo para o resumo.

    ==========================================================================================
    O MODO DE TESTE NÃO PODE CRIAR LINHA — NEM COMO `skipped`
    ==========================================================================================
    Critério 4 da sprint, e a razão é a UNIQUE. Ela é `(lead_exact_id, estagio_id)` e **não é
    parcial**: uma linha `skipped` bloqueia aquele par para sempre. Se os eventos de fora da
    allowlist virassem `skipped`, o dia em que o Álefe apagasse
    `FOLLOW_ESTAGIO_SOMENTE_TELEFONES` do `.env`, **todo lead que tivesse passado por um
    estágio durante o teste ficaria permanentemente bloqueado** para o follow real — e de
    forma invisível, porque a linha existe e diz "skipped".

    Então o evento é apenas CONSUMIDO: o cursor avança por cima dele e nada é gravado. O
    preço é conhecido e é o certo: os follows que teriam saído durante a janela de teste não
    saem, e é exatamente o que "modo de teste" significa.

    ==========================================================================================
    `ON CONFLICT DO NOTHING` É A REENTRADA
    ==========================================================================================
    Segundo evento do mesmo lead para o mesmo estágio (o `Follows 9 -> Follows 8 -> Follows 9`
    de §4.3) bate no índice e não faz nada. Nenhuma linha nova, nenhum envio, nenhum erro.

    `ON CONFLICT` e não `SELECT` antes: entre o SELECT e o INSERT cabe outro processo, e o que
    garante a regra tem de ser o banco. O `RETURNING id` é como sabemos qual dos dois
    aconteceu — vazio significa que já existia.

    `sem_telefone` e `sem_sdr` SÃO gravados como `skipped`, ao contrário da allowlist, e a
    diferença é de fato: ali o lead está fora do TESTE (condição nossa, temporária); aqui
    falta dado DELE (condição dele, e que só muda se alguém consertar o cadastro). Bloquear o
    par é a resposta certa — reenviar em loop um follow que não pode ser montado seria pior.
    """
    lead_exact_id = evento["lead_exact_id"]
    telefone = evento["telefone"]

    # Lead que já não está no espelho (10 casos, §1.3). Consome o evento sem gravar: não há
    # `lead_ids` para mandar ao bulk, e uma linha `skipped` bloquearia o par por um lead que
    # pode voltar num re-sync.
    if evento["lead_id"] is None:
        print(f"⚠️  follow: evento #{evento['evento_id']} lead {lead_exact_id} não está em "
              f"exact_leads — evento consumido, nenhuma linha criada")
        return "lead_ausente"

    if permitidos:
        chave = chave_telefone(telefone)
        if not chave or chave not in permitidos:
            # Silencioso no nível de linha, contado no resumo: com a allowlist ligada isto é
            # o caso NORMAL (todo lead menos o de teste), e um print por evento afogaria o
            # journald justamente quando alguém está olhando o teste.
            return "fora_da_allowlist"

    if not (telefone or "").strip():
        motivo = MOTIVO_SEM_TELEFONE
    else:
        _, motivo = montar_mappings(entrada, evento)

    status = FE_SKIPPED if motivo else FE_PENDENTE
    # O template EFETIVO deste lead (variante da pós ou genérico), não o genérico do degrau.
    # `_enviar_uma` resolve de novo com o lead relido e regrava se o `sub_source` mudou.
    template, _ = resolver(entrada, evento.get("sub_source"))

    # `ON CONFLICT (lead_exact_id, estagio_id) DO NOTHING` — a UNIQUE é quem decide. Ver a
    # seção acima sobre por que não há SELECT antes.
    criado = (await db.execute(text("""
        INSERT INTO follow_estagio_envios
               (lead_exact_id, telefone, estagio_id, estagio_nome, template, evento_id,
                status, motivo)
        VALUES (:lead_exact_id, :telefone, :estagio_id, :estagio_nome, :template, :evento_id,
                :status, :motivo)
        ON CONFLICT (lead_exact_id, estagio_id) DO NOTHING
        RETURNING id
    """), {"lead_exact_id": lead_exact_id, "telefone": telefone,
           "estagio_id": entrada["estagio_id"], "estagio_nome": entrada["nome"],
           "template": template, "evento_id": evento["evento_id"],
           "status": status, "motivo": motivo})).first()

    if criado is None:
        print(f"↩️  follow: lead {lead_exact_id} já tem linha para "
              f"{entrada['nome']!r} — reentrada, nada a fazer (evento #{evento['evento_id']})")
        return "reentrada"

    if motivo:
        print(f"⏭️  follow #{criado[0]}: lead {lead_exact_id} ({evento['lead_nome']!r}) em "
              f"{entrada['nome']!r} PULADO antes do envio: {motivo}")
        return FE_SKIPPED

    print(f"➕ follow #{criado[0]}: lead {lead_exact_id} ({evento['lead_nome']!r}) entrou em "
          f"{entrada['nome']!r} — '{template}' enfileirado")
    return FE_PENDENTE


async def ler_eventos() -> dict:
    """Passada de LEITURA: eventos novos -> linhas `pendente`. Devolve `{rótulo: n}`.

    Uma transação para o lote inteiro, e o cursor avança **por último, dentro dela**. Se o
    commit falhar, o cursor não anda e o lote volta na passada seguinte — o pior caso é um
    `ON CONFLICT DO NOTHING` a mais, que é inofensivo por construção.

    Avançar o cursor ANTES de enfileirar perderia eventos em silêncio; avançar depois do ENVIO
    faria um envio lento segurar a leitura e a passada seguinte reler os mesmos eventos.
    Aqui ele avança depois do ENFILEIRAMENTO, que é o único ponto em que "já vi" é verdade.
    """
    resumo: dict = {}
    async with async_session() as db:
        cursor = await _cursor(db)
        if cursor is None:
            print("❌ follow: follow_estagio_cursor está sem a linha id=1 — a migração "
                  "(migrate_follow_estagio.py) não rodou. NADA será processado: tratar "
                  "cursor ausente como 0 varreria o histórico inteiro.")
            return {"sem_cursor": True}

        estagios = estagios_do_mapa()
        eventos = await _eventos_novos(db, cursor, estagios)
        if not eventos:
            return {}

        for evento in eventos:
            entrada = estagio_para(evento)
            if entrada is None:
                # Inalcançável pela query (ela já filtra funil e nome). Se acontecer, o mapa
                # mudou entre o `estagios_do_mapa()` e este laço, ou alguém chamou
                # `_eventos_novos` com outra lista. Consome e conta — nunca envia por
                # semelhança.
                print(f"⚠️  follow: evento #{evento['evento_id']} passou a query mas não casa "
                      f"no mapa ({evento['funnel_id']}/{evento['stage_para']!r})")
                resumo["fora_do_mapa"] = resumo.get("fora_do_mapa", 0) + 1
                continue
            rotulo = await _enfileirar(db, evento, entrada, allowlist())
            resumo[rotulo] = resumo.get(rotulo, 0) + 1

        ultimo = eventos[-1]["evento_id"]
        await db.execute(text(
            "UPDATE follow_estagio_cursor SET ultimo_evento_id = :id, "
            "atualizado_em = (now() AT TIME ZONE 'utc') WHERE id = 1"), {"id": ultimo})
        await db.commit()
        resumo["cursor"] = ultimo
    return resumo


async def _pendentes(db, limite: int) -> list:
    """Os `pendente` mais antigos, TRAVADOS para esta transação.

    `FOR UPDATE SKIP LOCKED` com `ORDER BY id`: outro processo que rode o mesmo SELECT salta as
    linhas travadas em vez de esperar. Hoje há um worker só — isto protege contra o futuro, não
    contra o presente (mesma nota de `rd_sender._proxima`).

    O lote inteiro é travado de uma vez, e não uma linha por transação como no `rd_sender`. A
    diferença é que aqui cada envio é seguido de um `sleep(2)`: com uma transação por linha,
    manter 45 transações abertas em sequência custaria 45 × (envio + 2 s) de conexão. Cada
    linha é marcada e COMMITADA individualmente logo após o próprio envio — ver `drenar`.
    """
    return (await db.execute(
        select(FollowEstagioEnvio)
        .where(FollowEstagioEnvio.status == FE_PENDENTE)
        .order_by(FollowEstagioEnvio.id)
        .limit(limite)
        .with_for_update(skip_locked=True)
    )).scalars().all()


async def _finalizar(db, linha_id: int, *, status: str, motivo: str | None = None,
                     resposta: str | None = None, enviado_em: datetime | None = None,
                     template: str | None = None) -> None:
    """Grava o desfecho por UPDATE explícito, não por atributo do ORM.

    Mesma razão de `rd_sender._finalizar` e `nat_scheduler._finalizar`: este código roda depois
    de uma chamada externa que pode ter levantado, e um objeto ORM expirado recarregaria de
    forma lazy no meio do tratamento de erro.

    `motivo` é OBRIGATÓRIO em `falhou`. É o padrão da sprint de 18/09 — os 60 `follow_20h`
    quebrados ficaram um mês indiagnosticáveis porque `falhou` não exigia motivo. O
    `assert` é a trava: preferimos estourar aqui, no caminho de erro, a gravar um `falhou`
    mudo que ninguém consegue investigar.
    """
    assert status != FE_FALHOU or (motivo or "").strip(), \
        "falhou exige motivo (sprint de 18/09)"
    valores: dict = {"status": status}
    if motivo is not None:
        valores["motivo"] = motivo
    if resposta is not None:
        valores["resposta"] = resposta[:LIMITE_RESPOSTA]
    if enviado_em is not None:
        valores["enviado_em"] = enviado_em
    if template is not None:
        valores["template"] = template
    await db.execute(update(FollowEstagioEnvio)
                     .where(FollowEstagioEnvio.id == linha_id).values(**valores))


def _desfecho_do_bulk(resultado: dict) -> tuple[str, str | None]:
    """Traduz o retorno de `bulk_send_template` em `(status, motivo)`.

    O retorno é sempre um dict com as seis chaves de `exact_routes.py:647-650`: `sent`,
    `failed`, `errors`, `skipped_nat`, `skipped_total`, `skipped_por_regra` e **`skipped`**.
    Com UM lead, exatamente um dos três caminhos aconteceu:

        sent == 1                 -> `enviado`. A Meta aceitou.
        skipped                   -> `skipped`, com a regra e o motivo que o bulk já escreveu
                                     (`recusa`, `nat_ativa`, `opt_out_meta`). O mesmo motivo
                                     já está em `disparo_skip`; copiar para cá é para quem
                                     olha o follow não precisar cruzar duas tabelas.
        resto (failed, ou sent=0) -> `falhou`, com o erro da Meta. `errors[0]['error']` é o
                                     que a Meta devolveu.

    **A lista de pulos chama-se `skipped`, não `pulados`.** Dentro da rota a variável local é
    `pulados`, mas a chave do JSON é `skipped` — e ler a chave errada não daria erro: daria
    `[]`, e todo pulo (recusa, opt-out, conversa ativa) cairia no ramo de `falhou` com "sem
    `sent` e sem erro". A linha diria "falhou" para um lead que foi CORRETAMENTE poupado, e
    ninguém investigaria um `falhou` de motivo genérico. `skipped_total` é o cinto de
    segurança: se um dia a chave mudar de nome, o total ainda acusa que houve pulo.

    A ordem importa: `sent` primeiro. Um lote de um não pode ter enviado E pulado, mas se a
    rota mudar um dia, "saiu mensagem" é o fato que domina — marcar `skipped` uma linha cuja
    mensagem chegou ao lead seria a pior das inconsistências.
    """
    if (resultado.get("sent") or 0) >= 1:
        return FE_ENVIADO, None

    pulos = resultado.get("skipped") or []
    if pulos:
        p = pulos[0]
        regra = p.get("regra") or "?"
        return FE_SKIPPED, f"{regra}: {p.get('motivo') or '(sem motivo)'}"
    if (resultado.get("skipped_total") or 0) >= 1:
        # Defensivo: `skipped_total` sem a lista `skipped` não deveria existir, mas um
        # `skipped` mudo é melhor que um `falhou` mudo, e a regra vem do dicionário agregado.
        regras = ", ".join((resultado.get("skipped_por_regra") or {}).keys()) or "?"
        return FE_SKIPPED, f"pulado pelo disparo ({regras})"

    erros = resultado.get("errors") or []
    detalhe = (erros[0].get("error") if erros else None) or "sem `sent` e sem erro no retorno"
    return FE_FALHOU, f"a Meta/rota não confirmou o envio: {detalhe}"


async def _enviar_uma(db, linha) -> str:
    """Envia UMA linha e grava o desfecho. Devolve o rótulo para o resumo.

    ==========================================================================================
    O PAYLOAD, CAMPO POR CAMPO
    ==========================================================================================
        template_name   `resolver(entrada, lead.sub_source)`: variante da pós ou genérico
        language        "pt_BR"
        channel_id      1 (o único canal)
        lead_ids        [lead.id]  <- PK LOCAL de exact_leads, NÃO o exact_id
        param_mappings  do mapa (a chave é `param_mappings`, NÃO `mappings`)
        origem_envio    "campanha"

    **`lead_ids` é o PK local.** A rota faz `WHERE ExactLead.id.in_(lead_ids)`. Mandar o
    `exact_id` ali não dá erro: não encontra nada, o laço não roda e o retorno é
    `sent=0, failed=0` — que este módulo marcaria como `falhou` com "sem `sent` e sem erro",
    e o lead nunca receberia nada. Por isso o SELECT de `_eventos_novos` traz `el.id` e a
    linha guarda `lead_exact_id` separado.

    **`param_mappings` e não `mappings`** (`exact_routes.py:316`). O nome errado não daria
    erro: a rota cairia no modo legado (`parameters`), que monta `[nome, curso]` por POSIÇÃO —
    exatamente o chute que põe o nome do curso no `{{2}}` do `mensagem_follow7`, onde vai o
    mês. Silencioso e errado, que é o pior par.

    **`origem_envio="campanha"`** e não `"individual"`: é o que faz o filtro `nat_ativa` valer
    (`exact_routes.py:447`). Um follow automático não é um SDR escolhendo uma pessoa; se a Nat
    está conversando com o lead agora, o template "não tive sucesso em falar com você" é falso.
    `"campanha"` também é o default fail-safe da rota, mas vai explícito porque este payload é
    montado à mão.

    **`current_user` não é passado.** A rota o declara como `Depends(get_current_user)` e, na
    chamada Python, recebe o próprio objeto `Depends`. `app/autoria.py` sustenta isso de
    propósito: `quem_enviou()` devolve `None` (não houve humano logado, e essa é a informação)
    e `nome_de_quem_enviou()` cairia em `SDR_PADRAO` — que aqui não é usado, porque o `sdr`
    vem de `sdr_name`, o dono do lead.

    O lead é RELIDO aqui, e não reaproveitado do evento: entre o enfileiramento e o envio pode
    ter passado uma passada do sync. O `sdr_name` e o `sub_source` que vão para a mensagem têm
    de ser os de agora.
    """
    from app.exact_routes import bulk_send_template
    from app.follow_estagio_mapa import mapa

    entrada = mapa()["estagios"].get(linha.estagio_id)
    if entrada is None:
        # O estágio saiu do JSON entre o enfileiramento e o envio. `falhou` com motivo, não
        # envio às cegas com o template gravado na linha: se alguém removeu o degrau do mapa,
        # foi de propósito.
        await _finalizar(db, linha.id, status=FE_FALHOU,
                         motivo=f"estágio {linha.estagio_id} ({linha.estagio_nome!r}) não "
                                f"está mais em follow_estagios.json")
        return FE_FALHOU

    lead = (await db.execute(
        select(ExactLead).where(ExactLead.exact_id == linha.lead_exact_id))).scalar_one_or_none()
    if lead is None:
        await _finalizar(db, linha.id, status=FE_SKIPPED,
                         motivo="o lead saiu de exact_leads entre o enfileiramento e o envio")
        return FE_SKIPPED

    # Variante da pós (Follow 3 e 4) ou genérico, pelo `sub_source` de AGORA. É gravado na
    # linha em todo desfecho a partir daqui: a coluna tem de dizer o que foi (ou teria sido)
    # enviado, não o que se previa no enfileiramento.
    template, _ = resolver(entrada, lead.sub_source)

    mappings, motivo = montar_mappings(entrada, lead)
    if motivo:
        await _finalizar(db, linha.id, status=FE_SKIPPED, motivo=motivo, template=template)
        return FE_SKIPPED

    payload = {
        "template_name": template,
        "language": IDIOMA,
        "channel_id": CANAL_ID,
        "lead_ids": [lead.id],
        "param_mappings": mappings,
        "origem_envio": "campanha",
        # 27/09: o envio ENCERRA o agente do lead antes de sair (mesma função do takeover
        # humano), com motivo próprio. Regra única: ação do SDR encerra o agente.
        "motivo_agente": "follow_estagio",
    }

    try:
        resultado = await bulk_send_template(payload, db)
    except Exception as e:
        # Inclui a `HTTPException` da trava de boas-vindas (400) e qualquer erro de rede.
        # `falhou` na hora, sem retentativa: a sprint não pediu retry, e um follow reenviado
        # horas depois do arrasto do card já não é o follow daquele momento. O motivo fica
        # gravado, que é o que permite decidir se vale um retry numa próxima sprint.
        await _finalizar(db, linha.id, status=FE_FALHOU,
                         motivo=f"{type(e).__name__}: {e}", template=template)
        print(f"❌ follow #{linha.id}: lead {linha.lead_exact_id} em {linha.estagio_nome!r} — "
              f"{type(e).__name__}: {e}")
        return FE_FALHOU

    status, motivo = _desfecho_do_bulk(resultado)
    await _finalizar(db, linha.id, status=status, motivo=motivo,
                     resposta=json.dumps(resultado, ensure_ascii=False, default=str),
                     enviado_em=_agora_utc() if status == FE_ENVIADO else None,
                     template=template)

    if status == FE_ENVIADO:
        print(f"✅ follow #{linha.id}: '{template}' enviado para lead "
              f"{linha.lead_exact_id} ({lead.name!r}) em {linha.estagio_nome!r}")
        # 27/09: a observação na timeline do lead na Exact, onde o SDR trabalha. DEPOIS do
        # `_finalizar`: o UPDATE para `enviado` já está na transação, e `drenar` faz o commit
        # logo que esta função volta. A nota é só HTTP — não toca na sessão e nunca levanta —,
        # então não tem como mudar o status. Custo: até 5 s a mais por linha se a Exact travar.
        from app.exact_notes import registrar_observacao
        await registrar_observacao(
            linha.lead_exact_id,
            texto_nota_follow(linha.estagio_nome, template, _agora_sp()))
    elif status == FE_SKIPPED:
        print(f"⏭️  follow #{linha.id}: lead {linha.lead_exact_id} em "
              f"{linha.estagio_nome!r} PULADO pelo disparo — {motivo}")
    else:
        print(f"❌ follow #{linha.id}: lead {linha.lead_exact_id} em "
              f"{linha.estagio_nome!r} FALHOU — {motivo}")
    return status


async def drenar(*, limite: int = MAX_POR_CICLO) -> dict:
    """Envia os `pendente`, em sequência, com `sleep(2)` entre eles. `{rótulo: n}`.

    Uma transação para o lote (o lock do `_pendentes`), mas **um commit por linha**, logo
    depois do próprio envio. É o que garante que uma mensagem já entregue ao lead nunca fique
    com a linha `pendente`: se o processo morrer no meio da rajada, o que saiu está marcado e
    o resto continua `pendente` para a passada seguinte.

    O `sleep` fica DEPOIS do commit, e não antes: dormir com escrita pendente seguraria a
    transação por 2 s por lead sem necessidade.
    """
    resumo: dict = {}
    async with async_session() as db:
        linhas = await _pendentes(db, limite)
        if not linhas:
            return {}
        print(f"📨 follow: {len(linhas)} pendente(s) a enviar")
        for i, linha in enumerate(linhas):
            try:
                rotulo = await _enviar_uma(db, linha)
                await db.commit()
            except Exception as e:
                # Falha de infraestrutura (commit, lock, conexão), não do envio — aquele já
                # tem tratamento em `_enviar_uma`. A linha continua `pendente` e a passada
                # seguinte tenta de novo. Sem `break`: uma linha ruim não segura a fila.
                print(f"❌ follow: erro ao processar linha #{linha.id}: "
                      f"{type(e).__name__}: {e}")
                await db.rollback()
                resumo["erro"] = resumo.get("erro", 0) + 1
                continue
            resumo[rotulo] = resumo.get(rotulo, 0) + 1
            if i < len(linhas) - 1:
                await asyncio.sleep(ESPERA_ENTRE_ENVIOS_SEGUNDOS)
    return resumo


async def processar(*, limite_envios: int = MAX_POR_CICLO) -> dict:
    """Uma passada completa: ler eventos, depois drenar. Devolve o resumo das duas.

    O gate é conferido ANTES de abrir qualquer sessão: **com o follow desligado, este job não
    toca no banco**. Nem para ler eventos, nem para contar pendentes — critério 3 da sprint.

    Ler e drenar na MESMA passada (e não em jobs separados) é o que faz o follow sair em
    segundos depois do evento aparecer, em vez de esperar o ciclo seguinte.
    """
    if not _ligado():
        # Sai em toda passada de propósito: é a única prova, no journald, de que o gate está
        # fechado por escolha e não porque o job morreu. Mesma decisão do `rd_sender`.
        print("ℹ️  follow por estágio DESLIGADO (FOLLOW_ESTAGIO_ENABLED != true) — "
              "nenhum evento é lido e nada é enviado.")
        return {"desligado": True}

    try:
        estagios = estagios_do_mapa()
    except (MapaInvalido, OSError, ValueError) as e:
        # Mapa ausente ou inválido: ruidoso e sem tocar no banco. Ligar o gate com o JSON
        # torto é erro de operação, e enfileirar com mapa quebrado mandaria o template errado.
        print(f"❌ follow: mapa inválido ({type(e).__name__}: {e}) — nada será processado até "
              "follow_estagios.json ser corrigido.")
        return {"mapa_invalido": True}

    permitidos = allowlist()
    if permitidos:
        print(f"🧪 follow em MODO DE TESTE: só {len(permitidos)} telefone(s) da allowlist "
              f"entram. Os demais eventos são consumidos SEM criar linha.")

    resumo = dict(await ler_eventos())
    if resumo.get("sem_cursor") or resumo.get("mapa_invalido"):
        return resumo
    for rotulo, n in (await drenar(limite=limite_envios)).items():
        resumo[f"envio_{rotulo}"] = n
    resumo.setdefault("estagios_no_mapa", len(estagios))
    return resumo


async def follow_estagio_job():
    """Loop de 60s. Registrado no lifespan de `main.py`, ao lado do `rd_sender_job`.

    Dorme ANTES de trabalhar, como todos os outros jobs: no boot o processo tem coisa melhor a
    fazer (servir o webhook da Meta), e um follow esperar 60s a mais é irrelevante contra a
    latência de 4,8 min do sync que produz o evento.

    O try/except abraça o ciclo inteiro porque este loop não pode morrer: se ele morrer, os
    follows param de sair sem nada quebrar visivelmente — e um canal que para em silêncio é
    exatamente o modo de falha que esta automação existe para corrigir (o incidente 131042 de
    23-26/07, em que 100 % das boas-vindas falharam por quatro dias).
    """
    while True:
        await asyncio.sleep(INTERVALO_SEGUNDOS)
        try:
            resumo = await processar()
            if resumo:
                print(f"⏱️  follow por estágio: {resumo}")
        except Exception as e:
            print(f"❌ Erro no follow_estagio_job: {type(e).__name__}: {e}")
