"""Endpoints do fluxo NAT.

Dois grupos, com públicos diferentes, todos autenticados:

  A TELA DE CONVERSAS (Bloco 5, Fase 7) — qualquer usuário logado:
  GET  /api/nat/{wa_id}/estado    o que a tela precisa para decidir o que mostrar
  POST /api/nat/{wa_id}/assumir   o botão "Assumir ligação"

  O PAINEL DE CONTROLE (sprint de ativação, Fase 4) — só admin:
  GET   /api/nat/config           lê o kill switch
  PATCH /api/nat/config           liga, desliga e ajusta o teto

`assumido_por` é O QUE PARA O RELÓGIO do SLA. É um clique explícito, e não a leitura da
notificação: o sino pode ser limpo sem intenção, e "vi o alerta" não é "vou ligar".

O mesmo clique é também a ÚNICA SAÍDA do fluxo: leva o lead para `encerrado`. Antes desta
sprint nenhum caminho atribuía essa etapa e o lead morria em `aguardando_ligacao`.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_admin, get_current_user
from app.database import get_db
from app.models import (ETAPA_AGUARDANDO_LIGACAO, ETAPA_ENCERRADO, KIND_SLA_CHECK,
                        NatConfig, NatFlowState, User)
from app.nat_guard import SP_TZ, _agora_sp

router = APIRouter(prefix="/api/nat", tags=["nat"])


async def _estado(wa_id: str, db: AsyncSession) -> NatFlowState | None:
    res = await db.execute(select(NatFlowState).where(NatFlowState.contact_wa_id == wa_id))
    return res.scalar_one_or_none()


async def _nome(user_id: int | None, db: AsyncSession) -> str | None:
    if user_id is None:
        return None
    res = await db.execute(select(User.name).where(User.id == user_id))
    row = res.first()
    return (row[0] if row else None) or f"usuário {user_id}"


async def _payload(state: NatFlowState, db: AsyncSession) -> dict:
    """A resposta que a tela consome.

    `pode_assumir` é calculado AQUI, não no TSX. A regra é "está em aguardando_ligacao e
    ninguém assumiu" — a mesma que o handler do sla_check aplica. Duplicá-la no frontend
    criaria dois lugares para ela divergir, e o frontend perderia primeiro.
    """
    return {
        "em_fluxo": True,
        "etapa": state.etapa,
        "transferido_em": state.transferido_em.isoformat() if state.transferido_em else None,
        "assumido_por": state.assumido_por,
        "assumido_por_nome": await _nome(state.assumido_por, db),
        "assumido_em": state.assumido_em.isoformat() if state.assumido_em else None,
        "escalonamento_nivel": state.escalonamento_nivel or 0,
        "pode_assumir": (state.etapa == ETAPA_AGUARDANDO_LIGACAO
                         and state.assumido_por is None),
    }


VAZIO = {
    "em_fluxo": False, "etapa": None, "transferido_em": None, "assumido_por": None,
    "assumido_por_nome": None, "assumido_em": None, "escalonamento_nivel": 0,
    "pode_assumir": False,
}


@router.get("/{wa_id}/estado")
async def estado_do_fluxo(wa_id: str, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    """Estado do fluxo NAT do contato. Contato fora do fluxo devolve em_fluxo=false, não 404.

    Não é 404 porque a tela pergunta isto para TODO contato que o atendente abre, e a
    esmagadora maioria não está no fluxo da NAT. 404 nesse caso encheria o console do
    navegador de erro para o comportamento mais normal que existe.
    """
    state = await _estado(wa_id, db)
    if state is None:
        return VAZIO
    return await _payload(state, db)


@router.post("/{wa_id}/assumir")
async def assumir_ligacao(wa_id: str, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    """Para o relógio do SLA, ENCERRA o fluxo e cancela o sla_check pendente.

    ENCERRAR É O QUE TIRA O LEAD DAS MÃOS DA NAT. Antes desta sprint, `assumir` gravava
    `assumido_por` e parava por aí: o lead ficava em `aguardando_ligacao` para sempre, porque
    nenhum caminho do código atribuía `encerrado` — a constante existia em models.py e nunca
    era usada. O efeito prático era o pior possível: depois de assumido, QUALQUER clique do
    lead caía em "clique fora da etapa esperada" e era descartado em silêncio
    (nat_flow.processar_clique), enquanto um SDR humano já estava conduzindo a conversa.

    Com `encerrado`, a NAT sai do caminho e não volta:
      * processar_clique  — a etapa não é aguardando_resposta, o clique é ignorado;
      * processar_texto   — a etapa não é aguardando_motivacao nem reagendado, sem transição.
    Nos dois casos a mensagem do lead segue o percurso normal (grava em `messages`, notifica o
    SDR dono), que é o atendimento humano que já assumiu. Ignorar aqui é a resposta CERTA, e
    não uma lacuna — o que estava errado era o lead nunca chegar a este estado.

    IDEMPOTENTE. Assumir duas vezes não é erro e não reabre nada: a segunda chamada devolve
    200 com quem já havia assumido e NÃO sobrescreve assumido_por/assumido_em. Sobrescrever
    seria pior que um erro — apagaria o registro de quem realmente pegou o lead primeiro, que
    é justamente o que a escada de escalonamento usa para saber quem responde por ele. Essa
    checagem vem ANTES da checagem de etapa, e tem que continuar vindo: depois desta mudança
    a própria etapa já não é mais `aguardando_ligacao` na segunda chamada, e inverter a ordem
    trocaria o 200 idempotente por um 409.

    Dois savepoints, na ordem da importância — mesmo raciocínio do Bloco 5:
      1. o carimbo + o encerramento, que é o que para o relógio e devolve o lead ao humano;
      2. o cancelamento do sla_check.
    Se o cancelamento falhar, o carimbo permanece e o SLA ainda não escalona: o handler relê
    o estado e encontra `assumido_por` preenchido — e agora também uma etapa que não é
    `aguardando_ligacao`, que é a PRIMEIRA das três saídas de "nada a fazer" do sla_check.
    Duas redes onde antes havia uma.

    O FRONTEND não lê `etapa` (conferido em conversations/page.tsx: usa só `pode_assumir`,
    `assumido_por`, `assumido_por_nome` e `assumido_em`). O botão "Assumir ligação" some, que
    é o desejado — já foi assumido —, e some pelo mesmo motivo de antes: `pode_assumir` exige
    `assumido_por is None`. No lugar dele aparece o selo verde com quem assumiu e a hora,
    ditado por `assumido_por`. Nada na tela muda por causa da etapa.
    """
    state = await _estado(wa_id, db)
    if state is None:
        raise HTTPException(404, "Este contato não está no fluxo da NAT.")

    if state.assumido_por is not None:
        # Idempotência. Inclui o caso de dois SDRs clicando quase juntos: o segundo vê quem
        # ficou com o lead em vez de tomá-lo.
        return {"ja_assumido": True, "cancelados": 0, **await _payload(state, db)}

    if state.etapa != ETAPA_AGUARDANDO_LIGACAO:
        raise HTTPException(
            409,
            f"O lead não está aguardando ligação (etapa atual: {state.etapa}). "
            "Não há SLA correndo para assumir.")

    async with db.begin_nested():
        state.assumido_por = current_user.id
        state.assumido_em = _agora_sp()
        # Mesma escrita lógica ("este lead é do humano agora"), mesmo savepoint: um estado
        # com assumido_por preenchido e etapa ainda em aguardando_ligacao seria exatamente o
        # meio-termo que esta fase existe para eliminar.
        state.etapa = ETAPA_ENCERRADO

    cancelados = 0
    try:
        async with db.begin_nested():
            from app.nat_scheduler import cancelar
            cancelados = await cancelar(KIND_SLA_CHECK, wa_id, db)
    except Exception as e:
        print(f"⚠️  NAT: {wa_id} assumido por {current_user.id}, mas o cancelamento do "
              f"sla_check falhou ({type(e).__name__}: {e}). O SLA não escalona: o handler "
              "relê o estado e vê assumido_por preenchido.")

    await db.commit()
    print(f"✋ NAT: {wa_id} assumido por {current_user.name} (id={current_user.id}) → "
          f"{ETAPA_ENCERRADO} — {cancelados} sla_check cancelado(s)")

    await db.refresh(state)
    return {"ja_assumido": False, "cancelados": cancelados, **await _payload(state, db)}


# ==========================================================================================
# PAINEL DE CONTROLE DO nat_config — o kill switch
# ==========================================================================================
#
# Antes desta sprint, ligar e desligar a NAT era UPDATE manual no Postgres. Um kill switch
# que exige acesso ao banco não é kill switch: na hora em que ele é necessário, quem está
# olhando o problema pode não ser quem tem a credencial.
#
# ---------------------------------------------------------------------------------------
# ⚠️  nat_start_at É UTC. Esta é a única armadilha real deste endpoint.
#
# A trava de data compara nat_start_at com exact_leads.register_date (nat_guard, verificação
# 2), e register_date é gravado NAIVE EM UTC — está no docstring de date_parse.parse_datetime
# e confere no banco: em 11/08/2026 o register_date mais recente era 14:53 com o UTC em 15:18
# e o horário de São Paulo em 12:18.
#
# Ou seja, o resto do fluxo NAT trabalha em horário de São Paulo (nat_guard._agora_sp, o
# horário comercial, messages.timestamp), mas ESTE campo não. Gravar aqui o relógio de SP na
# hora da ativação poria o corte 3 HORAS NO PASSADO, e todo lead registrado nas 3 horas
# anteriores entraria no fluxo retroativamente — exatamente o que a decisão nº 2 do sprint
# proíbe. O erro seria silencioso: nenhuma exceção, só leads a mais.
#
# Por isso o endpoint NÃO aceita data sem fuso. As três formas de escrever o campo são:
#   "agora"                      -> o servidor resolve, e é o caminho da ativação
#   ISO com fuso ("...Z", "-03:00") -> convertido para UTC aqui
#   null                         -> apaga o corte, o que BLOQUEIA tudo (desligamento duro)
# Uma string ISO sem fuso é recusada com 400, porque não há resposta certa para ela.
# ---------------------------------------------------------------------------------------

CAMPOS_CONFIG = {"nat_enabled", "nat_start_at", "max_envios_hora"}


async def _config_singleton(db: AsyncSession) -> NatConfig:
    res = await db.execute(select(NatConfig).where(NatConfig.id == 1))
    cfg = res.scalar_one_or_none()
    if cfg is None:
        # Falha fechada, como o guard: sem config a NAT não atua, e inventar uma linha aqui
        # criaria o singleton com defaults sem ninguém ter decidido nada.
        raise HTTPException(404, "nat_config (id=1) não existe. Rode migrate_nat_config.py.")
    return cfg


def _para_utc_naive(valor, campo: str) -> datetime | None:
    """Normaliza o que veio no JSON para datetime naive em UTC. Ver o aviso acima."""
    if valor is None:
        return None
    if isinstance(valor, str) and valor.strip().lower() in {"agora", "now"}:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if not isinstance(valor, str):
        raise HTTPException(422, f"{campo} deve ser 'agora', uma data ISO com fuso, ou null.")

    texto = valor.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(texto)
    except ValueError:
        raise HTTPException(422, f"{campo}: '{valor}' não é uma data ISO válida.")

    if dt.tzinfo is None:
        raise HTTPException(
            422,
            f"{campo}: '{valor}' está sem fuso horário e seria ambíguo. Este campo é "
            "comparado com register_date, que é UTC — uma data sem fuso interpretada como "
            "horário de São Paulo poria o corte 3h no passado e deixaria leads retroativos "
            "entrarem no fluxo. Use \"agora\", ou informe o fuso ('2026-08-11T15:00:00Z' "
            "para UTC, '2026-08-11T12:00:00-03:00' para horário de São Paulo).")
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _serializar_config(cfg: NatConfig) -> dict:
    """O estado do kill switch, com o corte mostrado nos DOIS fusos.

    `nat_start_at_sp` não é redundância: o campo é UTC e todo o resto do sistema (e a cabeça
    de quem opera) é São Paulo. Sem a tradução ao lado, ninguém consegue conferir de relance
    se o corte que acabou de gravar é o que queria — e conferir o corte é a única defesa
    contra uma ativação retroativa.
    """
    corte = cfg.nat_start_at
    corte_sp = (corte.replace(tzinfo=timezone.utc).astimezone(SP_TZ).replace(tzinfo=None)
                if corte else None)
    return {
        "nat_enabled": cfg.nat_enabled,
        "nat_start_at": corte.isoformat() if corte else None,
        "nat_start_at_sp": corte_sp.isoformat() if corte_sp else None,
        "max_envios_hora": cfg.max_envios_hora,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        # A NAT só atua com os DOIS eixos ligados. Um `nat_enabled=true` com corte nulo
        # parece ligado na tela e não envia nada — a resposta diz o que vale de fato.
        "atuando": bool(cfg.nat_enabled and cfg.nat_start_at is not None),
    }


@router.get("/config")
async def get_nat_config(db: AsyncSession = Depends(get_db),
                         current_admin: User = Depends(get_current_admin)):
    """Estado atual do kill switch da NAT. Só admin."""
    return _serializar_config(await _config_singleton(db))


@router.patch("/config")
async def patch_nat_config(req: dict, db: AsyncSession = Depends(get_db),
                           current_admin: User = Depends(get_current_admin)):
    """Liga, desliga e ajusta o teto da NAT. Só admin. PATCH: o que não vier não muda.

    DESLIGAR NUNCA É BARRADO. Nenhuma validação roda no caminho de `nat_enabled: false` —
    é o caminho de emergência, e um kill switch que pode recusar o desligamento por causa de
    um campo inválido no mesmo corpo não serve para nada.

    LIGAR EXIGE O CORTE DE DATA, e essa é a validação que existe aqui. `nat_enabled=true` com
    `nat_start_at` nulo é o pior desfecho possível: o painel diz LIGADA, o guard bloqueia
    100% dos leads em "nat_start_at não definido", e quem ligou vai procurar o defeito em
    outro lugar. Os dois campos podem vir no mesmo PATCH.

    Chave desconhecida é 422, não é ignorada. Num endpoint cujo objetivo é desligar coisas
    às pressas, `{"nat_enable": false}` aceito em silêncio devolveria 200 com a NAT ligada.
    """
    if not isinstance(req, dict) or not req:
        raise HTTPException(422, f"Informe ao menos um campo: {sorted(CAMPOS_CONFIG)}.")

    desconhecidos = set(req) - CAMPOS_CONFIG
    if desconhecidos:
        raise HTTPException(
            422, f"Campo(s) desconhecido(s): {sorted(desconhecidos)}. "
                 f"Aceitos: {sorted(CAMPOS_CONFIG)}.")

    cfg = await _config_singleton(db)
    antes = _serializar_config(cfg)

    # --- validação dos valores, antes de escrever qualquer coisa ---
    if "nat_enabled" in req and not isinstance(req["nat_enabled"], bool):
        raise HTTPException(422, "nat_enabled deve ser true ou false.")

    if "max_envios_hora" in req:
        teto = req["max_envios_hora"]
        if isinstance(teto, bool) or not isinstance(teto, int) or teto < 0:
            raise HTTPException(422, "max_envios_hora deve ser um inteiro >= 0.")

    novo_corte = (_para_utc_naive(req["nat_start_at"], "nat_start_at")
                  if "nat_start_at" in req else cfg.nat_start_at)

    vai_ligar = req.get("nat_enabled", cfg.nat_enabled)
    if vai_ligar and novo_corte is None:
        raise HTTPException(
            422,
            "Para LIGAR a NAT é preciso um nat_start_at. Sem corte de data o guard bloqueia "
            "todos os leads e a NAT fica ligada sem atuar. Mande os dois juntos: "
            '{"nat_enabled": true, "nat_start_at": "agora"}.')

    # --- escrita ---
    if "nat_enabled" in req:
        cfg.nat_enabled = req["nat_enabled"]
    if "nat_start_at" in req:
        cfg.nat_start_at = novo_corte
    if "max_envios_hora" in req:
        cfg.max_envios_hora = req["max_envios_hora"]

    await db.commit()
    await db.refresh(cfg)
    depois = _serializar_config(cfg)

    # QUEM E QUANDO. `updated_at` é a coluna (o "quando", e ela já existia); o "quem" vai
    # para o journal, porque nat_config não tem coluna de autor e criar uma exigiria migração
    # — que esta sprint não roda sem aprovação. Prefixo fixo e gritante para o grep valer:
    #   journalctl -u <servico> | grep 'NAT CONFIG'
    mudancas = {k: (antes[k], depois[k]) for k in CAMPOS_CONFIG if antes[k] != depois[k]}
    print(f"🎛️  NAT CONFIG alterado por {current_admin.name} (id={current_admin.id}) em "
          f"{_agora_sp():%d/%m/%Y %H:%M:%S} (SP): "
          + (", ".join(f"{k}: {v[0]!r} → {v[1]!r}" for k, v in mudancas.items())
             or "nenhum valor mudou")
          + f" | atuando={depois['atuando']}")

    return depois
