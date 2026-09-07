"""Quem entra na fila do RD, e com que desfecho. Uma linha por pessoa, por evento.

Este módulo é o ÚNICO ponto que decide o que vai para `rd_conversoes`. `rd_station.py` diz
como transformar dados (mapa, normalização, payload); aqui se decide se há o que transformar,
e o resultado é sempre uma linha — nunca silêncio.

------------------------------------------------------------------------------------------
SILÊNCIO É O DEFEITO QUE ESTA TABELA EXISTE PARA NÃO REPETIR
------------------------------------------------------------------------------------------
A integração antiga morreu sem sintoma: o formulário do RD saiu da landing page em 18/08 e os
fluxos de e-mail pararam, mas nada errou, nada logou, e a descoberta veio semanas depois. Por
isso todo caminho de decisão termina em INSERT:

    sub_source fora do mapa   -> skipped, motivo='sem_mapa'
    sem e-mail                -> skipped, motivo='sem_email'
    e-mail que não é e-mail   -> skipped, motivo='email_invalido'
    tudo certo                -> pendente, com payload pronto

`SELECT motivo, count(*) FROM rd_conversoes WHERE status='skipped' GROUP BY 1` passa a ser a
resposta para "por que fulano não recebeu o e-mail do fluxo". Sem as linhas de `skipped`, a
pergunta não teria resposta nenhuma — que é onde estávamos.

`sem_email` NÃO é caso de borda: é 100% do caminho do agente. Medido em 07/09 — das 21 linhas
de `agendamentos` criadas pelo agente desde 18/08, ZERO têm e-mail, porque
`qualificacao_fluxo.py:1478` passa `email=None` fixo e o e-mail não é coletado em ponto nenhum
da conversa. Essas linhas vão acumular em `skipped/sem_email` até alguém decidir se o agente
passa a perguntar e-mail. A fila torna a decisão visível; ela não a toma.

------------------------------------------------------------------------------------------
NUNCA LEVANTA, E O SAVEPOINT É PARTE DISSO
------------------------------------------------------------------------------------------
`enfileirar` é chamado no meio do fluxo de agendamento, com a sessão DELE, entre o commit que
materializa o `Agendamento` e o `BoxesAdd` que reserva o horário na agenda real de uma
consultora. Um erro aqui não pode custar a reunião de ninguém.

Duas camadas garantem isso, e as duas importam:

  1. `try/except Exception` devolvendo `'erro'` — nada sai daqui como exceção.
  2. O INSERT roda dentro de `db.begin_nested()`. Sem o savepoint, um INSERT que falhasse
     deixaria a transação da sessão ABORTADA, e o `_marcar` seguinte — que é quem grava
     `box_criado` depois do BoxesAdd — falharia no commit com
     `InFailedSQLTransactionError`. O agendamento morreria por causa da fila, que é
     exatamente o inverso da prioridade. Com o savepoint, só o INSERT volta atrás.

É a mesma lição do P0-A (`qualificacao_fluxo.py:1440-1460`), onde uma transação emprestada
derrubou 100% dos agendamentos do agente por três dias.

------------------------------------------------------------------------------------------
QUEM COMMITA
------------------------------------------------------------------------------------------
Não é este módulo. `enfileirar` grava e devolve; o commit vem do `_marcar` seguinte, no mesmo
fluxo (`agendamento/agendar.py:231-241`, que commita a cada passo). É a mesma primitiva de
`nat_scheduler.agendar`, e pela mesma razão escrita lá: quem chama é dono da fronteira da
transação.

O risco desse desenho é conhecido e está medido no relatório da sprint: um caminho que morra
entre o INSERT da fila e o primeiro `_marcar` perde a linha do outbox — mas nesse caminho o
`Agendamento` também não avança de `iniciado`, então a fila e a tabela de origem contam a
mesma história. O backfill repesca.
"""
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import rd_station
from app.models import RD_PENDENTE, RD_SKIPPED, Agendamento, RdConversao

# Devolvidos por `enfileirar`. `duplicado` e `erro` NÃO são status de banco: o primeiro quer
# dizer que a UNIQUE já tinha a linha (o caso normal do segundo passo da landing page), e o
# segundo que nada foi gravado. Separá-los de `pendente`/`skipped` é o que faz o resumo do
# backfill distinguir "enfileirei 3" de "3 já estavam lá".
DUPLICADO = "duplicado"
ERRO = "erro"

MOTIVO_SEM_MAPA = "sem_mapa"
MOTIVO_SEM_EMAIL = "sem_email"
MOTIVO_EMAIL_INVALIDO = "email_invalido"


async def enfileirar(db: AsyncSession, ag: Agendamento) -> str:
    """Grava UMA linha em `rd_conversoes` para este agendamento. Nunca levanta.

    Devolve `'pendente'`, `'skipped'`, `'duplicado'` ou `'erro'`. O chamador não precisa fazer
    nada com o retorno — ele existe para o backfill somar e para os testes afirmarem.

    A ORDEM DAS DECISÕES IMPORTA. `sem_mapa` vem antes de `sem_email` porque o identifier faz
    parte da chave de idempotência: sem ele não há linha possível, nem sequer a de `skipped`.
    Um curso fora do mapa com e-mail e um curso fora do mapa sem e-mail são o mesmo problema —
    o mapa —, e reportar `sem_email` neles mandaria quem investiga para o lado errado.
    """
    try:
        identifier = rd_station.identifier_para(ag.sub_source)
        if identifier is None:
            # Sem identifier não há como sequer nomear o evento. A linha existe só para a
            # pergunta "quantos leads perdemos por falta de mapa?" ter resposta — e por isso
            # a chave usa o telefone, que sempre existe (`agendamentos.telefone` é NOT NULL).
            return await _gravar(
                db, ag, identifier=_identifier_orfao(ag),
                email=None, status=RD_SKIPPED, motivo=MOTIVO_SEM_MAPA)

        email = rd_station.normalizar_email(ag.email)
        if email is None:
            # Distinguir "não tem" de "tem e está errado" não é preciosismo: o primeiro é
            # decisão de produto (o agente não pergunta e-mail), o segundo é dado sujo de um
            # formulário. As contas de quem vai decidir o que fazer são diferentes.
            bruto = (ag.email or "").strip()
            motivo = MOTIVO_EMAIL_INVALIDO if bruto else MOTIVO_SEM_EMAIL
            return await _gravar(db, ag, identifier=identifier, email=None,
                                 status=RD_SKIPPED, motivo=motivo)

        telefone = rd_station.normalizar_telefone_rd(ag.telefone)
        payload = rd_station.montar_payload(
            identifier=identifier, email=email, nome=ag.nome, telefone=telefone)
        return await _gravar(db, ag, identifier=identifier, email=email,
                             status=RD_PENDENTE, motivo=None, payload=payload)
    except Exception as e:
        print(f"❌ rd #{getattr(ag, 'id', '?')}: não consegui enfileirar a conversão — "
              f"{type(e).__name__}: {e}")
        return ERRO


def _identifier_orfao(ag: Agendamento) -> str:
    """O `conversion_identifier` de uma linha que não tem um. NOT NULL exige alguma coisa.

    `sem-mapa:<sub_source>` e não uma string fixa: assim a UNIQUE continua valendo por curso,
    e dois cursos diferentes fora do mapa não colapsam numa linha só. O prefixo garante que
    isto nunca colida com um identifier de verdade — nenhum gatilho do RD começa com
    `sem-mapa:` — e que ninguém vá postá-lo por engano se repescar a fila.
    """
    return f"sem-mapa:{(ag.sub_source or '').strip().lower() or 'vazio'}"


async def _gravar(db: AsyncSession, ag: Agendamento, *, identifier: str,
                  email: str | None, status: str, motivo: str | None,
                  payload: dict | None = None) -> str:
    """`INSERT ... ON CONFLICT DO NOTHING` dentro de um savepoint. Devolve o desfecho.

    `ON CONFLICT DO NOTHING` E NÃO `DO UPDATE`: a primeira linha é a verdade. O segundo passo
    da landing page chega com exatamente os mesmos dados (mesma pessoa, mesmo curso), e o
    único campo que ele mudaria é `agendamento_id` — trocar a referência do `lead_criado` pela
    do `agendado` não informa nada e apagaria qual foi o primeiro contato. Já um `skipped` que
    depois ganhasse e-mail merece virar `pendente`, mas isso é repesca deliberada (um UPDATE
    explícito, feito por quem decidiu), não efeito colateral de um segundo formulário.

    `rowcount == 0` é o caminho NORMAL, não um aviso: acontece uma vez por submissão da LP,
    porque toda submissão que agenda passa por aqui duas vezes. Por isso o log é ℹ️ e não ⚠️.
    """
    valores = {
        "chave": rd_station.chave_de(email, ag.telefone),
        "conversion_identifier": identifier,
        "agendamento_id": ag.id,
        "sub_source": ag.sub_source,
        "payload": payload,
        "status": status,
        "motivo": motivo,
    }
    stmt = (insert(RdConversao)
            .values(**valores)
            .on_conflict_do_nothing(index_elements=["chave", "conversion_identifier"]))

    # O savepoint é o que impede um erro desta escrita de abortar a transação do agendamento.
    # Ver o cabeçalho do módulo.
    async with db.begin_nested():
        resultado = await db.execute(stmt)

    if resultado.rowcount == 0:
        print(f"ℹ️ rd #{ag.id}: conversão já enfileirada para {valores['chave']} "
              f"({identifier}) — nada a fazer")
        return DUPLICADO

    if status == RD_PENDENTE:
        print(f"✅ rd #{ag.id}: conversão enfileirada — {identifier}")
    else:
        print(f"⚠️ rd #{ag.id}: conversão PULADA ({motivo}) — {identifier}")
    return status
