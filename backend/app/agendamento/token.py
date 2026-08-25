"""O link personalizado do lead espontâneo: emitir, resolver e consumir.

------------------------------------------------------------------------------------------
POR QUE O TOKEN EXISTE
------------------------------------------------------------------------------------------
`hub.cenatdata.online/agendar/<token>` é página PÚBLICA e sem login — quem abre é alguém
que recebeu o link no WhatsApp. Toda a identificação da pessoa vive DESTE lado: o browser
não manda telefone nenhum, e nem poderia. Se o telefone viesse do corpo do POST, qualquer um
agendaria no nome de qualquer número.

`secrets.token_urlsafe(32)` = 256 bits. Id sequencial na URL seria enumerável em minutos.

------------------------------------------------------------------------------------------
UM TOKEN VIVO POR CONTATO
------------------------------------------------------------------------------------------
`emitir` é IDEMPOTENTE por contato: pedir o link de novo devolve **o mesmo** token enquanto
ele estiver vivo. É o que dá sentido à regra de produto "a Nat não repete o link mais de 1x"
— repetir a mensagem não pode criar um link novo e invalidar o que a pessoa já tem aberto.

Quando o token venceu sem uso, `emitir` o REVOGA e emite outro. Revogar em vez de marcar
usado: as duas colunas guardam fatos diferentes, e misturá-las faria o relatório contar link
abandonado como link usado. O índice único parcial `uq_token_vivo` é a rede da mesma regra —
se dois pedidos simultâneos escaparem daqui, o banco recusa o segundo.

------------------------------------------------------------------------------------------
A CLAIM VEM ANTES DA ESCRITA NA EXACT, E ISSO É DELIBERADO
------------------------------------------------------------------------------------------
Dois cliques simultâneos no mesmo link são um caso real (a pessoa toca duas vezes, ou abre
em duas abas). A ordem importa e não há escolha boa dos dois lados:

    agendar → consumir   os dois cliques passam pelo agendamento e nascem DOIS LEADS na
                         Exact. `LeadsAdd` não tem idempotência e não há endpoint para
                         desfazer (FINDINGS §11). Irreversível.
    consumir → agendar   um clique ganha a claim, o outro vê "já usado". Se o agendamento
                         falhar depois, o token fica queimado — mas isso é REVERSÍVEL:
                         `liberar()` devolve a claim.

Escolhi o segundo. Sujeira reversível é melhor que lead duplicado permanente, e é a mesma
lógica que `agendar.py` já aplica ao compensar o box.

`consumir` é um UPDATE condicional (`WHERE usado_em IS NULL`) que devolve quantas linhas
mudou: é o check-and-set atômico: ler-depois-escrever deixaria a janela entre as duas.
"""
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agendamento.horarios import agora_sp
from app.models import NatAgendamentoToken

DIAS_DE_VIDA = 7

# Estados possíveis de um token pedido pela URL. `INEXISTENTE` e `EXPIRADO` são coisas
# diferentes para a TELA (uma oferece recomeçar a conversa, a outra também, mas com texto
# distinto) e iguais para a segurança — nenhuma das duas deixa agendar.
OK = "ok"
USADO = "usado"
EXPIRADO = "expirado"
INEXISTENTE = "inexistente"


@dataclass(frozen=True)
class Resolucao:
    """O que a rota precisa saber. `token` é None quando não há o que mostrar."""
    status: str
    token: NatAgendamentoToken | None = None

    @property
    def ok(self) -> bool:
        return self.status == OK


def _novo_segredo() -> str:
    return secrets.token_urlsafe(32)


async def vivo_de(db: AsyncSession, contact_wa_id: str) -> NatAgendamentoToken | None:
    """O token vivo deste contato, se houver. Vivo = não usado e não revogado."""
    res = await db.execute(
        select(NatAgendamentoToken)
        .where(NatAgendamentoToken.contact_wa_id == contact_wa_id,
               NatAgendamentoToken.usado_em.is_(None),
               NatAgendamentoToken.revogado_em.is_(None))
        .order_by(NatAgendamentoToken.id.desc()))
    return res.scalars().first()


async def emitir(db: AsyncSession, *, contact_wa_id: str, nome: str | None = None,
                 curso: str | None = None, formacao: str | None = None,
                 atuacao: str | None = None) -> NatAgendamentoToken:
    """Devolve o token vivo do contato, ou cria um. NÃO faz commit — quem chama decide.

    Enquanto vivo, o token é REAPROVEITADO e os dados coletados depois são atualizados
    nele: a pessoa pode ter dito o curso só na mensagem seguinte ao envio do link, e a
    página tem que refletir a conversa inteira, não o instante da emissão.
    """
    agora = agora_sp()
    atual = await vivo_de(db, contact_wa_id)

    if atual is not None and atual.expira_em > agora:
        # Só sobrescreve o que veio preenchido: uma chamada sem `curso` não pode apagar o
        # curso que a conversa já tinha estabelecido.
        for campo, valor in (("nome", nome), ("curso", curso),
                             ("formacao", formacao), ("atuacao", atuacao)):
            if valor:
                setattr(atual, campo, valor)
        await db.flush()
        return atual

    if atual is not None:
        # Venceu sem uso. Aposenta para o índice único liberar a emissão nova — e para o
        # relatório continuar sabendo que este link foi abandonado, não usado.
        atual.revogado_em = agora
        await db.flush()

    novo = NatAgendamentoToken(
        token=_novo_segredo(), contact_wa_id=contact_wa_id,
        nome=nome, curso=curso, formacao=formacao, atuacao=atuacao,
        expira_em=agora + timedelta(days=DIAS_DE_VIDA))
    db.add(novo)
    await db.flush()
    return novo


async def resolver(db: AsyncSession, segredo: str) -> Resolucao:
    """Traduz o `<token>` da URL no que a página deve mostrar. NUNCA levanta.

    A ordem das checagens é a da tela: `usado` vence `expirado`, porque quem já agendou
    precisa ver o agendamento dele, não uma mensagem de link vencido — mesmo que o token
    tenha vencido depois do uso.
    """
    if not segredo or len(segredo) > 200:
        return Resolucao(INEXISTENTE)
    res = await db.execute(
        select(NatAgendamentoToken).where(NatAgendamentoToken.token == segredo))
    obj = res.scalar_one_or_none()
    if obj is None or obj.revogado_em is not None:
        return Resolucao(INEXISTENTE)
    if obj.usado_em is not None:
        return Resolucao(USADO, obj)
    if obj.expira_em <= agora_sp():
        return Resolucao(EXPIRADO, obj)
    return Resolucao(OK, obj)


async def consumir(db: AsyncSession, segredo: str) -> bool:
    """CLAIM atômica: marca usado e devolve se ESTA chamada foi quem ganhou.

    `WHERE usado_em IS NULL` no próprio UPDATE. Ler antes e escrever depois deixaria a
    janela em que dois cliques leem "livre" e os dois agendam — dois leads na Exact, sem
    desfazer.
    """
    res = await db.execute(
        update(NatAgendamentoToken)
        .where(NatAgendamentoToken.token == segredo,
               NatAgendamentoToken.usado_em.is_(None),
               NatAgendamentoToken.revogado_em.is_(None))
        .values(usado_em=agora_sp()))
    return res.rowcount == 1


async def liberar(db: AsyncSession, segredo: str) -> None:
    """Devolve a claim. Só para compensar agendamento que falhou DEPOIS de consumir.

    Sem isto, uma falha na Exact queimaria o link e a pessoa ficaria sem caminho — com o
    agravante de que a Nat já disse que era aquele o link. Mesma disciplina de
    `agendar._compensar_box`: a compensação nunca levanta.
    """
    try:
        await db.execute(
            update(NatAgendamentoToken)
            .where(NatAgendamentoToken.token == segredo)
            .values(usado_em=None, agendamento_id=None))
    except Exception as e:
        print(f"⚠️ token {segredo[:8]}…: não consegui liberar a claim "
              f"({type(e).__name__}: {e}). O link fica queimado.")


async def marcar_agendamento(db: AsyncSession, segredo: str, agendamento_id: int) -> None:
    """Fecha o círculo: qual reunião nasceu deste link."""
    await db.execute(
        update(NatAgendamentoToken)
        .where(NatAgendamentoToken.token == segredo)
        .values(agendamento_id=agendamento_id))


def mascarar(wa_id: str) -> str:
    """`5585999995219` -> `(85) 9****-5219`. Para a tela CONFIRMAR sem EXPOR.

    A pessoa precisa reconhecer o próprio número ("é o meu mesmo") sem que a página exponha
    um telefone completo numa URL que pode ser compartilhada, printada ou indexada.

    Devolve `""` para o que não dá para ler — e a tela omite a linha em vez de mostrar lixo.
    """
    d = "".join(c for c in (wa_id or "") if c.isdigit())
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) not in (10, 11):
        return ""
    ddd, resto = d[:2], d[2:]
    return f"({ddd}) {resto[0]}****-{resto[-4:]}"
