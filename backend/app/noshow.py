"""Régua de NO-SHOW D0+1h a D8 (spec da Isa, 28/09; Bloco 2, 07/10/2026).

==========================================================================================
O QUE É
==========================================================================================
Quem cai no corte da régua de confirmação (não confirmou até o corte) recebe 8 mensagens em
8 dias: D0+1h, D0+8h, D1 (horários), D2 (áudio do coordenador), D3 (seminário), D5 (conteúdo),
D7 (condição) e D8 (encerramento). Qualquer clique ou resposta do lead encerra a régua e passa
para humano. Depois do D8, o lead segue no funil do SDR (nada a mover: estágio intra-funil
não se move pela API).

GATILHO ÚNICO: O CORTE (`confirmacao.confirm_a_corte`). Não há gatilho por `Cancelada` na
Exact (ambíguo: cancelamento prévio, remarcação e falta são o mesmo valor, RECON §5.2) nem por
"consultora marcou falta" (não existe na API). "Não vou conseguir" não é no-show (spec).

D0 = o instante do corte, gravado em `reuniao_status.noshow_em`. A régua vive enquanto
`noshow_em` não é nulo e `regua_encerrada_em` é nulo. O corte encerra a régua de CONFIRMAÇÃO
(`regua_encerrada_motivo='corte'`); `armar` reabre a coluna para a régua de no-show. É a mesma
coluna de propósito: uma régua por pessoa, e "viva" significa uma coisa só.

==========================================================================================
REGRAS COMUNS
==========================================================================================
Determinístico, um kind por degrau (`models.KINDS_NOSHOW`), payload `{"meeting_id": ...}`,
handler relê tudo. Janela 8h–20h30 em todos os degraus (`nat_guard.dentro_janela_envio`); um
degrau adiado que passaria do próximo é `AcaoIgnorada("colidiu com o próximo degrau")`.

Conteúdo mensal (seminário, condição, conteúdo, áudio) vem de `backend/conteudos_noshow.json`,
RELIDO a cada execução: a Isa atualiza sem restart. Degrau sem conteúdo é pulado com motivo
(`"conteúdo do mês não cadastrado"`) e a régua segue; nunca texto inventado.

Gates `NOSHOW_ENABLED` e `NOSHOW_SOMENTE_TELEFONES`, sem cache.
"""
import json
import os
from datetime import date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import confirmacao as cf
from app import nat_copy
from app.models import (ACAO_EXECUTADO, KIND_CONFIRM_A_CORTE, KIND_NOSHOW_D0_1H,
                        KIND_NOSHOW_D0_8H, KIND_NOSHOW_D1, KIND_NOSHOW_D2, KIND_NOSHOW_D3,
                        KIND_NOSHOW_D5, KIND_NOSHOW_D7, KIND_NOSHOW_D8, KINDS_NOSHOW,
                        TIPO_NOTIF_CONFIRMACAO, TIPO_NOTIF_SEMINARIO, Message,
                        NatScheduledAction, ReuniaoStatus)
from app.nat_guard import _agora_sp, dentro_janela_envio, proxima_janela_envio
from app.nat_scheduler import AcaoAdiada, AcaoIgnorada, registrar_handler
from app.telefone import chave_telefone, variantes_wa_id

# ==========================================================================================
# GATES
# ==========================================================================================

def flag_ligada() -> bool:
    return (os.getenv("NOSHOW_ENABLED", "") or "").strip().lower() in ("true", "1", "sim", "yes")


def allowlist() -> frozenset[str]:
    cru = os.getenv("NOSHOW_SOMENTE_TELEFONES", "") or ""
    return frozenset(c for c in (chave_telefone(p) for p in cru.split(",")) if c)


def telefone_permitido(telefone: str | None) -> bool:
    lista = allowlist()
    return not lista or chave_telefone(telefone) in lista


# ==========================================================================================
# O RELÓGIO (decisão 4) — função pura
# ==========================================================================================
TEMPLATE_DO_KIND = {
    KIND_NOSHOW_D0_1H: nat_copy.NAT_NS_D0_1H,
    KIND_NOSHOW_D0_8H: nat_copy.NAT_NS_D0_8H,
    KIND_NOSHOW_D1: nat_copy.NAT_NS_D1,
    KIND_NOSHOW_D2: nat_copy.NAT_NS_D2_AUDIO,
    KIND_NOSHOW_D3: nat_copy.NAT_NS_D3_SEMINARIO,
    KIND_NOSHOW_D5: nat_copy.NAT_NS_D5_CONTEUDO,
    KIND_NOSHOW_D7: nat_copy.NAT_NS_D7_CONDICAO,
    KIND_NOSHOW_D8: nat_copy.NAT_NS_D8_ENCERRAMENTO,
}


def _dia(d0: datetime, n: int, hora: int) -> datetime:
    return (d0 + timedelta(days=n)).replace(hour=hora, minute=0, second=0, microsecond=0)


def calcular_degraus(d0: datetime) -> list[tuple[str, datetime]]:
    """Os 8 degraus em ordem. D1 às 9h ("Bom dia" no texto); D2 em diante às 10h."""
    return [(KIND_NOSHOW_D0_1H, d0 + timedelta(hours=1)),
            (KIND_NOSHOW_D0_8H, d0 + timedelta(hours=8)),
            (KIND_NOSHOW_D1, _dia(d0, 1, 9)),
            (KIND_NOSHOW_D2, _dia(d0, 2, 10)),
            (KIND_NOSHOW_D3, _dia(d0, 3, 10)),
            (KIND_NOSHOW_D5, _dia(d0, 5, 10)),
            (KIND_NOSHOW_D7, _dia(d0, 7, 10)),
            (KIND_NOSHOW_D8, _dia(d0, 8, 10))]


def proximo_degrau(d0: datetime, kind: str) -> datetime | None:
    """O `run_at` do degrau seguinte a `kind`, ou None para o D8."""
    degraus = calcular_degraus(d0)
    for i, (k, _) in enumerate(degraus):
        if k == kind:
            return degraus[i + 1][1] if i + 1 < len(degraus) else None
    return None


# ==========================================================================================
# CONTEÚDOS DO MÊS — relidos a cada execução
# ==========================================================================================
CAMINHO_CONTEUDOS = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 "conteudos_noshow.json")
SEM_CONTEUDO = "conteúdo do mês não cadastrado"


def conteudos() -> dict:
    """O JSON inteiro, relido do disco. Ilegível = vazio (todo degrau mensal é pulado)."""
    try:
        with open(CAMINHO_CONTEUDOS, encoding="utf-8") as fh:
            dados = json.load(fh)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError) as e:
        print(f"⚠️ noshow: conteudos_noshow.json ilegível ({e}) — degraus mensais pulados")
        return {}


def _vigente(bloco: dict, hoje: date, campos: tuple[str, ...]) -> dict | None:
    """O bloco se todos os `campos` estão preenchidos e `valido_ate` (AAAA-MM-DD) não venceu."""
    if not isinstance(bloco, dict) or any(not str(bloco.get(c) or "").strip() for c in campos):
        return None
    try:
        if date.fromisoformat(str(bloco["valido_ate"]).strip()) < hoje:
            return None
    except (KeyError, ValueError):
        return None
    return bloco


def _por_curso(mapa: dict, sub_source: str):
    alvo = (sub_source or "").strip().lower()
    for k, v in (mapa or {}).items():
        if k.strip().lower() == alvo:
            return v
    return None


# ==========================================================================================
# LEITURAS E EFEITOS
# ==========================================================================================

async def reuniao_em_regua(wa_id: str, db: AsyncSession) -> ReuniaoStatus | None:
    """A reunião desta pessoa com régua de no-show VIVA, ou None."""
    chave = chave_telefone(wa_id)
    if not chave:
        return None
    return (await db.execute(select(ReuniaoStatus).where(
        ReuniaoStatus.telefone_chave == chave, ReuniaoStatus.noshow_em.isnot(None),
        ReuniaoStatus.regua_encerrada_em.is_(None))
        .order_by(ReuniaoStatus.noshow_em.desc()).limit(1))).scalar_one_or_none()


async def encerrar(r: ReuniaoStatus, motivo: str, db: AsyncSession, *,
                   nota: str | None = None) -> int:
    """Cancela os degraus pendentes DESTA reunião e grava o encerramento. Nunca levanta."""
    try:
        n = await cf._cancelar_da_reuniao(r, KINDS_NOSHOW, motivo, db)
        if r.regua_encerrada_em is None:
            r.regua_encerrada_em = _agora_sp()
            r.regua_encerrada_motivo = motivo[:60]
        if nota:
            await cf._nota(r, nota)
        print(f"🚫 noshow: régua da reunião {r.meeting_id} encerrada ({motivo}), "
              f"{n} degrau(s) cancelado(s)")
        return n
    except Exception as e:
        print(f"⚠️ noshow: régua da reunião {r.meeting_id} não encerrada ({motivo}): "
              f"{type(e).__name__}: {e}")
        return 0


async def encerrar_da_pessoa(wa_id: str, motivo: str, db: AsyncSession) -> int:
    r = await reuniao_em_regua(wa_id, db)
    return await encerrar(r, motivo, db) if r is not None else 0


# A volta AUTOMÁTICA que a Exact faz quando a reunião é cancelada. MEDIDO em 07/10: das 65
# reuniões do Hub canceladas desde 20/09, 28 têm `Agendados -> Entrada` logo depois. É o
# efeito de a consultora cancelar a reunião (que é o que o corte pede a ela), não o SDR
# assumindo; tratar como arrasto mataria a régua minutos depois de ela nascer.
TRANSICOES_AUTOMATICAS = frozenset({("Agendados", "Entrada")})


async def encerrar_por_arrasto(transicoes: list[tuple], db: AsyncSession) -> int:
    """O SDR moveu o card de um lead com régua viva → `sdr_assumiu` (decisão 7).

    `transicoes` = [(exact_lead_id, telefone, de, para)] que o sync viu mudar de estágio. Uma
    consulta só para as réguas vivas; casamento pela chave do telefone (a pessoa), não pelo
    lead. A volta automática `Agendados -> Entrada` (cancelamento da reunião) não conta.
    """
    transicoes = [t for t in transicoes
                  if ((t[2] or "").strip(), (t[3] or "").strip()) not in TRANSICOES_AUTOMATICAS]
    if not transicoes:
        return 0
    vivas = (await db.execute(select(ReuniaoStatus).where(
        ReuniaoStatus.noshow_em.isnot(None),
        ReuniaoStatus.regua_encerrada_em.is_(None)))).scalars().all()
    if not vivas:
        return 0
    por_chave = {r.telefone_chave: r for r in vivas if r.telefone_chave}
    total = 0
    for lead_id, telefone, *_ in transicoes:
        r = por_chave.get(chave_telefone(telefone))
        if r is not None and r.regua_encerrada_em is None:
            total += 1
            await encerrar(r, "sdr_assumiu", db,
                           nota="Régua de no-show encerrada: SDR moveu o lead de estágio")
    return total


# ==========================================================================================
# ARMAR (chamado no fim do corte)
# ==========================================================================================

async def armar(r: ReuniaoStatus, wa_id: str, db: AsyncSession, *,
                agora: datetime | None = None) -> int:
    """Grava `noshow_em` e cria os 8 degraus. Idempotente. Devolve quantos inseriu."""
    from app.nat_scheduler import agendar
    if not flag_ligada() or not telefone_permitido(r.telefone_bruto):
        return 0
    if r.noshow_em is not None:
        return 0                                   # já armada: idempotente
    agora = agora or _agora_sp()
    r.noshow_em = agora
    # A régua de confirmação acabou no corte; a de no-show começa. Mesma coluna, ver cabeçalho.
    r.regua_encerrada_em = None
    r.regua_encerrada_motivo = None
    degraus = calcular_degraus(agora)
    for kind, quando in degraus:
        await agendar(kind, wa_id, quando, {"meeting_id": r.meeting_id}, db)
    print(f"📅 noshow: régua armada para a reunião {r.meeting_id} ({wa_id}), D0 "
          f"{agora:%d/%m %H:%M}: {len(degraus)} degraus")
    return len(degraus)


# ==========================================================================================
# GUARD E ENVIO
# ==========================================================================================

def guard_de_noshow(meeting_id: int, kind: str):
    async def _guard(contact, db: AsyncSession) -> tuple[bool, str]:
        from app import qualificacao_guard as qg
        from app.higiene_disparo import _opt_out_meta

        def bloqueia(motivo: str) -> tuple[bool, str]:
            print(f"🔒 No-show não enviou {kind} ({getattr(contact, 'wa_id', '?')}): {motivo}")
            return False, motivo
        try:
            r = await cf._reuniao(meeting_id, db)
            if r is None or r.noshow_em is None:
                return bloqueia(f"reunião {meeting_id} sem régua de no-show")
            if r.regua_encerrada_em is not None:
                return bloqueia(f"régua encerrada: {r.regua_encerrada_motivo}")
            if await _opt_out_meta(variantes_wa_id(contact.wa_id) or (contact.wa_id,), db):
                return bloqueia("opt-out registrado pela Meta (131050)")
            if await cf._acoes(meeting_id, db, kinds=(kind,), status=ACAO_EXECUTADO):
                return bloqueia(f"{kind} já enviado para a reunião {meeting_id}")
            config = await qg._carregar_config(db)
            if config is not None:
                ok, motivo = await qg._teto_ok(config, db)
                if not ok:
                    return bloqueia(motivo)
            return True, "ok"
        except Exception as e:
            return bloqueia(f"erro inesperado no guard do no-show: {type(e).__name__}: {e}")
    return _guard


async def _espinha(acao: dict, db: AsyncSession, kind: str):
    """Relê tudo. Devolve (reuniao, wa_id, agora, prazo do próximo degrau ou None)."""
    from app.nat_scheduler import payload_de
    agora = acao.get("agora") or _agora_sp()
    mid = payload_de(acao).get("meeting_id")
    r = await cf._reuniao(mid, db)
    if r is None:
        raise AcaoIgnorada(f"reunião {mid!r} não existe em reuniao_status")
    if not flag_ligada():
        raise AcaoIgnorada("NOSHOW_ENABLED desligado")
    if not telefone_permitido(r.telefone_bruto):
        raise AcaoIgnorada("telefone fora de NOSHOW_SOMENTE_TELEFONES")
    if r.noshow_em is None:
        raise AcaoIgnorada("reunião sem régua de no-show (noshow_em nulo)")
    if r.regua_encerrada_em is not None:
        raise AcaoIgnorada(f"régua encerrada: {r.regua_encerrada_motivo}")
    prazo = proximo_degrau(r.noshow_em, kind)
    if prazo is not None and agora >= prazo:
        raise AcaoIgnorada("colidiu com o próximo degrau")
    if not dentro_janela_envio(agora):
        prox = proxima_janela_envio(agora)
        if prazo is not None and prox >= prazo:
            raise AcaoIgnorada("colidiu com o próximo degrau "
                               f"(a janela só abre {prox:%d/%m %H:%M})")
        raise AcaoAdiada(prox, f"fora da janela 8h–20h30 ({agora:%H:%M})")
    return r, acao["contact_wa_id"], agora, prazo


async def _enviar(acao: dict, db: AsyncSession, r: ReuniaoStatus, kind: str, parametros: list,
                  corpo: str, agora: datetime, prazo: datetime | None, *,
                  url_sufixo: str | None = None) -> None:
    """Envia; teto vira AcaoAdiada (dentro do prazo); outra recusa vira AcaoIgnorada."""
    from app import qualificacao_guard as qg
    from app.nat_sender import enviar_nat
    from app.nat_scheduler import payload_de
    template = TEMPLATE_DO_KIND[kind]
    url_suffixes = None
    if url_sufixo:
        # O botão URL vem DEPOIS dos quick replies no template: o índice é a contagem deles.
        url_suffixes = [None] * len(nat_copy.BOTOES_NOSHOW.get(template, [])) + [url_sufixo]
    wa = acao["contact_wa_id"]
    ok, motivo = await enviar_nat(wa, template, db, guard=guard_de_noshow(r.meeting_id, kind),
                                  parametros=parametros, corpo_livre=corpo,
                                  url_suffixes=url_suffixes)
    if not ok:
        if qg.e_teto(motivo):
            prox = agora + cf.ATRASO_POR_TETO
            if prazo is None or prox < prazo:
                raise AcaoAdiada(prox, motivo)
            raise AcaoIgnorada(f"{motivo} — e readiar colidiria com o próximo degrau")
        raise AcaoIgnorada(f"{kind} não saiu: {motivo}")
    wamid = (await db.execute(
        select(Message.wa_message_id).where(Message.contact_wa_id == wa,
                                            Message.nat_etapa == template)
        .order_by(Message.id.desc()).limit(1))).scalar_one_or_none()
    await db.execute(update(NatScheduledAction).where(NatScheduledAction.id == acao["id"])
                     .values(payload=json.dumps({**payload_de(acao), "wa_message_id": wamid},
                                                ensure_ascii=False)))


C = nat_copy.CORPO_SUBMETIDO_NOSHOW


async def _base(r: ReuniaoStatus, wa: str, db: AsyncSession) -> tuple[str, str]:
    return await cf._nome(r, wa, db), await cf._pos(r, db)


# ==========================================================================================
# OS 8 HANDLERS
# ==========================================================================================

@registrar_handler(KIND_NOSHOW_D0_1H)
async def noshow_d0_1h(acao: dict, db: AsyncSession):
    r, wa, agora, prazo = await _espinha(acao, db, KIND_NOSHOW_D0_1H)
    nome, _ = await _base(r, wa, db)
    p = [nome]
    await _enviar(acao, db, r, KIND_NOSHOW_D0_1H, p, cf._render(C[nat_copy.NAT_NS_D0_1H], p),
                  agora, prazo)


@registrar_handler(KIND_NOSHOW_D0_8H)
async def noshow_d0_8h(acao: dict, db: AsyncSession):
    r, wa, agora, prazo = await _espinha(acao, db, KIND_NOSHOW_D0_8H)
    p = list(await _base(r, wa, db))
    await _enviar(acao, db, r, KIND_NOSHOW_D0_8H, p, cf._render(C[nat_copy.NAT_NS_D0_8H], p),
                  agora, prazo)


def _hora(dt: datetime) -> str:
    return f"{dt:%H}h{dt:%M}"


def linha_de_horarios(slots: list[datetime], agora: datetime, *, por_dia: int = 2,
                      dias: int = 2) -> str | None:
    """'hoje 14h15, 16h30 ou amanhã 10h00'. Hoje e amanhã; sem nada neles, os 2 próximos dias
    com horário (a grade só tem dia útil, então são os 2 próximos dias úteis). None se vazio.
    """
    por_data: dict = {}
    for s in sorted(slots):
        if s > agora:
            por_data.setdefault(s.date(), []).append(s)
    if not por_data:
        return None
    alvo = [d for d in (agora.date(), agora.date() + timedelta(days=1)) if d in por_data]
    if not alvo:
        alvo = sorted(por_data)[:dias]
    partes = []
    for d in alvo[:dias]:
        horas = por_data[d][:por_dia]
        if d == agora.date():
            rotulo = "hoje"
        elif d == agora.date() + timedelta(days=1):
            rotulo = "amanhã"
        else:
            rotulo = cf.dia_extenso(horas[0])
        partes.append(f"{rotulo} " + ", ".join(_hora(h) for h in horas))
    return " ou ".join(partes)


@registrar_handler(KIND_NOSHOW_D1)
async def noshow_d1(acao: dict, db: AsyncSession):
    from app.agendamento import disponibilidade
    r, wa, agora, prazo = await _espinha(acao, db, KIND_NOSHOW_D1)
    livres = await disponibilidade.slots_livres(db, usar_cache=False)
    linha = linha_de_horarios([d.slot.inicio for d in livres], agora)
    if not linha:
        raise AcaoIgnorada("sem horário livre hoje, amanhã nem nos 2 próximos dias úteis")
    nome, pos = await _base(r, wa, db)
    p = [nome, pos, linha]
    await _enviar(acao, db, r, KIND_NOSHOW_D1, p, cf._render(C[nat_copy.NAT_NS_D1], p),
                  agora, prazo)


@registrar_handler(KIND_NOSHOW_D2)
async def noshow_d2(acao: dict, db: AsyncSession):
    r, wa, agora, prazo = await _espinha(acao, db, KIND_NOSHOW_D2)
    sub = await cf._sub_source(r, db)
    sufixo = _por_curso(conteudos().get("audio_por_curso"), sub)
    if not sufixo:
        raise AcaoIgnorada(f"{SEM_CONTEUDO}: áudio do coordenador para {sub!r}")
    nome, pos = await _base(r, wa, db)
    livre = nat_copy.TEXTO_NS_D2_LIVRE.format(nome=nome, pos=pos,
                                              link=f"https://drive.google.com/file/d/{sufixo}")
    await _enviar(acao, db, r, KIND_NOSHOW_D2, [nome, pos], livre, agora, prazo,
                  url_sufixo=sufixo)


@registrar_handler(KIND_NOSHOW_D3)
async def noshow_d3(acao: dict, db: AsyncSession):
    r, wa, agora, prazo = await _espinha(acao, db, KIND_NOSHOW_D3)
    sem = _vigente(conteudos().get("seminario"), agora.date(),
                   ("nome", "data", "hora", "valido_ate"))
    if not sem:
        raise AcaoIgnorada(f"{SEM_CONTEUDO}: seminário vazio ou vencido")
    nome, _ = await _base(r, wa, db)
    p = [nome, sem["data"], sem["hora"], sem["nome"]]
    await _enviar(acao, db, r, KIND_NOSHOW_D3, p,
                  cf._render(C[nat_copy.NAT_NS_D3_SEMINARIO], p), agora, prazo)


@registrar_handler(KIND_NOSHOW_D5)
async def noshow_d5(acao: dict, db: AsyncSession):
    r, wa, agora, prazo = await _espinha(acao, db, KIND_NOSHOW_D5)
    sub = await cf._sub_source(r, db)
    item = _por_curso(conteudos().get("conteudo_por_curso"), sub)
    if not isinstance(item, dict) or not (item.get("titulo") or "").strip() \
            or not (item.get("drive_id") or "").strip():
        raise AcaoIgnorada(f"{SEM_CONTEUDO}: conteúdo para {sub!r}")
    nome, pos = await _base(r, wa, db)
    sufixo = item["drive_id"].strip()
    livre = nat_copy.TEXTO_NS_D5_LIVRE.format(
        nome=nome, pos=pos, titulo=item["titulo"].strip(),
        link=f"https://drive.google.com/file/d/{sufixo}")
    await _enviar(acao, db, r, KIND_NOSHOW_D5, [nome, pos, item["titulo"].strip()], livre,
                  agora, prazo, url_sufixo=sufixo)


@registrar_handler(KIND_NOSHOW_D7)
async def noshow_d7(acao: dict, db: AsyncSession):
    r, wa, agora, prazo = await _espinha(acao, db, KIND_NOSHOW_D7)
    cond = _vigente(conteudos().get("condicao"), agora.date(), ("texto", "valido_ate"))
    if not cond:
        raise AcaoIgnorada(f"{SEM_CONTEUDO}: condição vazia ou vencida")
    nome, pos = await _base(r, wa, db)
    limite = date.fromisoformat(cond["valido_ate"].strip())
    p = [nome, pos, cond["texto"].strip(), f"{limite:%d/%m}"]
    await _enviar(acao, db, r, KIND_NOSHOW_D7, p,
                  cf._render(C[nat_copy.NAT_NS_D7_CONDICAO], p), agora, prazo)


@registrar_handler(KIND_NOSHOW_D8)
async def noshow_d8(acao: dict, db: AsyncSession):
    r, wa, agora, prazo = await _espinha(acao, db, KIND_NOSHOW_D8)
    p = list(await _base(r, wa, db))
    await _enviar(acao, db, r, KIND_NOSHOW_D8, p,
                  cf._render(C[nat_copy.NAT_NS_D8_ENCERRAMENTO], p), agora, prazo)
    # Decisão 8: a régua termina aqui. O lead já está no funil do SDR.
    r.regua_encerrada_em = agora
    r.regua_encerrada_motivo = "d8_sem_resposta"
    await cf._nota(r, "Régua de no-show encerrada sem resposta")


# ==========================================================================================
# INBOUND (decisão 6) — chamado por `confirmacao.inbound`
# ==========================================================================================
PAYLOADS_AGORA = frozenset({nat_copy.NS_D0_AGORA, nat_copy.NS_1H_AGORA, nat_copy.NS_8H_AGORA,
                            nat_copy.NS_D2_AGORA, nat_copy.NS_D8_AGORA})
PAYLOADS_HORARIO = frozenset({nat_copy.NS_D0_HORARIO, nat_copy.NS_1H_HORARIO,
                              nat_copy.NS_8H_HORARIO, nat_copy.NS_D1_HORARIO,
                              nat_copy.NS_D2_REAGENDAR, nat_copy.NS_D7_REAGENDAR,
                              nat_copy.NS_D8_REAGENDAR})
PAYLOADS_NOSHOW = PAYLOADS_AGORA | PAYLOADS_HORARIO | {nat_copy.NS_D3_QUERO}


async def _payload_pelo_contexto(r: ReuniaoStatus, evento: dict, db: AsyncSession) -> str | None:
    """Clique sem payload: só pelo rótulo se o `context.id` é uma mensagem desta régua (ou o
    D0 do corte) para esta reunião. Senão None."""
    ctx = evento.get("context_message_id")
    rotulo = (evento.get("button_text") or "").strip().lower()
    if not ctx or not rotulo:
        return None
    from app.nat_scheduler import payload_de
    templates = {**TEMPLATE_DO_KIND, KIND_CONFIRM_A_CORTE: nat_copy.NAT_NS_D0_CORTE}
    botoes = {**nat_copy.BOTOES_NOSHOW,
              nat_copy.NAT_NS_D0_CORTE: nat_copy.BOTOES_FLUXO_A[nat_copy.NAT_NS_D0_CORTE]}
    for a in await cf._acoes(r.meeting_id, db, kinds=tuple(templates), status=ACAO_EXECUTADO):
        if payload_de({"payload": a.payload}).get("wa_message_id") != ctx:
            continue
        for b in botoes.get(templates[a.kind], []):
            if b["titulo"].strip().lower() == rotulo:
                return b["payload"]
    return None


async def _d3_ja_saiu(r: ReuniaoStatus, db: AsyncSession) -> bool:
    return bool(await cf._acoes(r.meeting_id, db, kinds=(KIND_NOSHOW_D3,),
                                status=ACAO_EXECUTADO))


async def inbound(r: ReuniaoStatus, wa_id: str, evento: dict | None, content: str,
                  db: AsyncSession) -> bool:
    """Qualquer clique ou resposta encerra a régua. Sempre True (a mensagem é da régua)."""
    payload = None
    if evento:
        payload = (evento.get("button_payload") or "").strip() or None
        if payload not in PAYLOADS_NOSHOW:
            payload = await _payload_pelo_contexto(r, evento, db)
    if payload is None and not evento and cf.normalizar(content) == "quero" \
            and await _d3_ja_saiu(r, db):
        payload = nat_copy.NS_D3_QUERO

    if payload in PAYLOADS_AGORA:
        await encerrar(r, payload, db)
        await cf.ligar_agora(r, wa_id, db)
    elif payload in PAYLOADS_HORARIO:
        await encerrar(r, payload, db)
        await cf.remarcar(r, wa_id, db, ja_cortada=True)
    elif payload == nat_copy.NS_D3_QUERO:
        sem = conteudos().get("seminario") or {}
        nome_sem = (sem.get("nome") or "").strip() or "do mês"
        await encerrar(r, payload, db, nota=f"Quer participar do seminário {nome_sem}")
        await cf._notificar(r, wa_id, TIPO_NOTIF_SEMINARIO, "Lead quer participar do seminário",
                            f"Seminário {nome_sem}. Mande o link por aqui e tente o "
                            f"reagendamento da reunião.", db)
        await cf._responder(wa_id, nat_copy.TEXTO_NS_SEMINARIO_QUERO.format(
            nome=await cf._nome(r, wa_id, db)), db)
    elif payload is None and not evento and cf._recusa(content):
        await encerrar(r, "sem_interesse", db, nota="Sem interesse agora")
        await cf._notificar(r, wa_id, TIPO_NOTIF_CONFIRMACAO, "Lead disse que não tem interesse",
                            "Régua de no-show encerrada.", db)
    else:
        await encerrar(r, "humano", db, nota="Aguardando humano")
        previa = "[mídia]" if (content or "").startswith("media:") else (content or "")[:120]
        await cf._notificar(r, wa_id, TIPO_NOTIF_CONFIRMACAO,
                            "Lead respondeu a régua de no-show: assuma",
                            f"Mensagem: {previa}", db)
    return True
