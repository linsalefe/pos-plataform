"""A página de Relatórios do Hub. Somente leitura, uma rota por seção.

Quem lê é a gestora comercial e o diretor, sozinhos, sem ninguém do lado para explicar.
Isso governa cada decisão deste módulo, e é por isso que ele carrega texto: `definicao` e
`limitacao` VÃO PARA A TELA. O relatório circula sem tradutor.

TRÊS REGRAS DE LEITURA, e nenhuma é estética
------------------------------------------------------------------------------------------
1. **N ao lado de todo percentual.** As amostras são de dezenas. Percentual sem denominador
   é mentira arredondada.
2. **Métrica não medível aparece como "não medível", com o motivo — nunca como zero.** Há
   quatro estados de confiança e nenhum deles é 0.
3. **Taxa por ator só com N ≥ 30** (`N_MINIMO_TAXA`). A IA tem 9 reuniões; "22% converteu"
   sobre 9 é ruído com dois dígitos, e o diretor vai ler como número.

O BUG DE PÁGINA QUE ESTE MÓDULO EXISTE PARA NÃO TER
------------------------------------------------------------------------------------------
Os "46 agendamentos" do RECON_JORNADA_LEAD não reproduziam com o corte que o cabeçalho
declarava (01/09, 20h SP). Reproduziam com corte em ~01/09 17:00 UTC: as consultas rodaram
no meio da sessão e o documento foi escrito às 20h. **O período era carimbado depois, não
usado como corte da query.**

Aqui `:ini` e `:fim` entram em TODA query como parâmetro, e o `periodo` devolvido no JSON é
EXATAMENTE o par usado no `WHERE` — é o mesmo objeto, não uma segunda formatação.
`test_relatorios.py` quebra se os dois divergirem.

O RELÓGIO, QUE É DE ONDE VÊM OS ERROS SILENCIOSOS
------------------------------------------------------------------------------------------
O servidor não tem TZ configurado: `datetime.now()` devolve UTC. E o banco mistura os dois
fusos NA MESMA LINHA de código — `routes.py:118` compara `datetime.now()` com
`messages.timestamp` (que é SP) e com `Contact.created_at` (que é UTC). Efeito medido: das
21h às 23h59 SP, todo dia, o painel antigo lê `0 mensagens hoje`.

Neste módulo o relógio é SP em todo lugar, e `para_utc` é o ÚNICO ponto que soma 3 h — usado
no bind, nunca dentro do SQL, para a conversão aparecer no código.

  SP  (naive):  messages.timestamp, agendamentos.slot_inicio,
                nat_qualificacao_state.transferido_em / encerrado_em,
                nat_scheduled_actions.run_at
  UTC (naive):  *.created_at, exact_stage_events.observado_em, exact_leads.register_date

CACHE: UM SÓ, E NÃO É DE AGREGAÇÃO
------------------------------------------------------------------------------------------
O E7 do recon recusou cache de agregação e continua valendo: o painel inteiro roda em ~76 ms
e cachear o NÚMERO QUE A GESTORA LÊ seria pagar complexidade para piorar a confiança numa
página que já tem o problema do "número que muda sozinho".

O que é cacheado aqui é outra coisa: o conjunto das chaves de telefone dos leads de teste —
19 strings que ninguém lê, insumo de um `NOT IN`. Custa ~75 ms e a página faz 5 chamadas em
paralelo. TTL de 600 s, alinhado ao passo do sync: o conjunto só muda quando o sync traz um
lead novo, e um TTL menor gastaria os 75 ms sem chance de ver nada diferente.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_admin
from app.database import get_db

# Gate no ROUTER, não na assinatura de cada rota: as funções continuam chamáveis de dentro
# do processo (teste, script) sem que a dependência vaze para os argumentos. Não existe role
# `gestor` — 7 dos 8 usuários são admin, e "admin" hoje exclui exatamente uma pessoa.
# Criar uma role para separar uma pessoa que o gate existente já separa é cerimônia (E4).
router = APIRouter(prefix="/api/relatorios", tags=["relatorios"],
                   dependencies=[Depends(get_current_admin)])
log = logging.getLogger(__name__)


# ==========================================================================================
# O RELÓGIO
# ==========================================================================================
SP = timezone(timedelta(hours=-3))


def agora_sp() -> datetime:
    """Agora em SP, naive — o mesmo relógio de `messages.timestamp`."""
    return datetime.now(SP).replace(tzinfo=None)


def para_utc(ts_sp: datetime) -> datetime:
    """Fronteira SP -> UTC. O ÚNICO lugar deste módulo que soma 3 h.

    Usar ao cruzar `*.created_at`, `exact_stage_events.observado_em` e
    `exact_leads.register_date`. Chamado no BIND, nunca dentro do SQL: uma conversão de fuso
    escondida numa string é a que ninguém revisa.
    """
    return ts_sp + timedelta(hours=3)


PERIODOS_FIXOS = {"hoje": 0, "7d": 7, "30d": 30}


@dataclass(frozen=True)
class Periodo:
    """O par que foi para o `WHERE`. O JSON serializa ESTE objeto, não uma segunda leitura."""
    de: datetime
    ate: datetime
    dias: int
    rotulo: str

    def json(self) -> dict:
        return {"de": self.de.isoformat(), "ate": self.ate.isoformat(),
                "dias": self.dias, "rotulo": self.rotulo,
                "relogio": "America/Sao_Paulo"}


def janela(periodo: str) -> Periodo:
    """'hoje' | '7d' | '30d' | 'AAAA-MM-DD:AAAA-MM-DD' | 'ISO..ISO' -> (ini, fim) naive-SP.

    O fim é SEMPRE `agora` nos períodos fixos, e não o fim do dia: um período que termina no
    futuro faria a métrica de silêncio contar como "sem resposta" quem escreveu há um minuto.

    A forma `..` aceita hora (`2026-08-24T20:16..2026-09-01T14:00`) e existe por um motivo
    concreto: as coortes congeladas dos recons têm corte no MINUTO, não no dia, e sem ela
    nenhuma reprodução passaria pelo caminho real do código — o teste teria de reimplementar
    a janela, que é exatamente como um teste passa a concordar com um bug.
    """
    periodo = (periodo or "30d").strip()
    agora = agora_sp()
    if periodo in PERIODOS_FIXOS:
        dias = PERIODOS_FIXOS[periodo]
        ini = (agora - timedelta(days=dias)).replace(hour=0, minute=0, second=0, microsecond=0)
        return Periodo(ini, agora, max(dias, 1), periodo)

    sep = ".." if ".." in periodo else (":" if ":" in periodo and "T" not in periodo else None)
    if sep:
        a, b = (x.strip() for x in periodo.split(sep, 1))
        try:
            ini = (datetime.fromisoformat(a) if ("T" in a or " " in a)
                   else datetime.combine(date.fromisoformat(a), datetime.min.time()))
            fim = (datetime.fromisoformat(b) if ("T" in b or " " in b)
                   else datetime.combine(date.fromisoformat(b), datetime.max.time()))
        except ValueError:
            raise HTTPException(400, "Período personalizado deve ser AAAA-MM-DD:AAAA-MM-DD.")
        if fim < ini:
            raise HTTPException(400, "A data final é anterior à inicial.")
        return Periodo(ini, min(fim, agora), max((fim - ini).days + 1, 1), periodo)
    raise HTTPException(400, "Período inválido. Use hoje, 7d, 30d ou AAAA-MM-DD:AAAA-MM-DD.")


# ==========================================================================================
# AS CONSTANTES QUE JÁ MORDERAM
# ==========================================================================================
# Duas etapas HOMÔNIMAS no funil 18535 — uma com ponto final. Medido: 14 eventos de
# `Reagendamento` e 4 de `Reagendamento.`; 17 leads estão hoje na grafia COM ponto. Elas já
# inflaram uma conversão de 6 para 18, e o último tropeço foi o `-1` que compensou o `+1` na
# tabela do §3 do recon da jornada — dois erros opostos que fecharam o total e por isso
# ninguém viu. A guarda é uma constante nomeada, não um literal recopiado.
ETAPAS_REAGENDAMENTO = ("Reagendamento", "Reagendamento.")

# `stage_de` que NÃO conta como entrada nova em Agendados: quem já estava agendado e voltou.
_GUARDA_REAGENDAMENTO = ("NOT (coalesce(e.stage_de,'') ILIKE '%Agendad%' "
                         "     OR coalesce(e.stage_de,'') ILIKE '%Reagendament%')")

FUNIL_POS = 18535                      # Pos Graduacao (prospecção)
FUNIS_VENDAS = (18537, 21007)          # Pós Graduação - Vendas · Vagas Afirmativas

# `INGEST_FUNNEL_IDS` está VAZIO: `exact_leads` tem os 9 299 leads de TODOS os funis da
# Exact, incluindo Intercâmbio (2 493) e Congresso (97). Toda query de funil aqui filtra
# `funnel_id` EXPLICITAMENTE — uma que esquecer conta 9 300 em vez de 3 800, sem erro
# visível. `test_relatorios.py` trava isso.

# Etapas em que o agente DEVE a próxima fala. Importada, não recopiada: é a mesma constante
# que governa escutar e falar.
from app.models import ETAPAS_QUALIFICACAO_ATIVAS  # noqa: E402

KIND_VIGIAR_RESPOSTA = "vigiar_resposta"   # nat_scheduled_actions.kind do vigia

# MARGEM do invariante de silêncio. O p99 de resposta do agente é 14,3 min (N=206) e
# `ATRASO_POR_TETO` é 10 min — quando o teto por hora adia uma fala, o agente legitimamente
# demora 10 min MAIS o ciclo de 60 s do scheduler. Os 10 min do vigia `agente_mudo` são para
# DETECTAR agente travado, e um falso positivo lá gera um aviso que alguém lê; aqui é um
# invariante de painel que pisca vermelho para a gestora. Errar para o lado do alarme é pior.
MARGEM_SILENCIO = timedelta(minutes=15)

# `messages.sent_by` nasceu no deploy do S6-1. Antes disso o dado NÃO EXISTE — não é zero,
# não é "sem atividade": nunca foi gravado.
CORTE_SENT_BY = datetime(2026, 9, 1, 16, 0)

# `agendamentos` começou a existir aqui. Antes, uma venda não tem como ser ligada à origem.
COBERTURA_AGENDAMENTOS = date(2026, 8, 17)

# Abaixo disto, contagem absoluta e lista nominal — nunca taxa (J-P5).
N_MINIMO_TAXA = 30

# Prefixos do botão da landing page, desacentuados. ⚠️ PARÊNTESES no OR quando isto entra
# num WHERE: sem eles o predicado vira `(direction AND A) OR B` e captura outbound — foi o
# erro que devolveu 908 em vez de 38 na primeira tentativa do recon.
PREFIXOS_BOTAO_LP = ("ola! tudo bem? fiz minha aplicacao%",
                     "ola! tudo bem? manifestei interesse%")

# Aberturas do agente, por roteiro. `messages.nat_etapa` carimba QUAL abertura saiu, e é a
# única marca histórica de coorte que existe: `nat_qualificacao_state.etapa` é SOBRESCRITA
# (uma linha por contato, sem log de transição), então "em que etapa o lead estava em 25/08"
# não é recuperável. Ver `nat_etapa_events`, proposta e fora desta sprint.
ABERTURA_T1 = "nat_abertura_qualificacao"    # formação conhecida, vai perguntar o ano
ABERTURA_T2 = "nat_abertura_agendado"        # formação conhecida, já tem reunião marcada
ABERTURA_T3 = "nat_abertura_sem_formacao"    # PRECISA perguntar a formação
ABERTURAS = (ABERTURA_T1, ABERTURA_T2, ABERTURA_T3)

ACENTOS_DE = "áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ"
ACENTOS_PARA = "aaaaeeiooouucaaaaeeiooouuc"

# ⚠️ ÂNCORA no `zz`. Sem ela, 48 leads REAIS casam — Pozzebon, Pezzi, Lanzzarin, Rizzato,
# Garbazza, Gavazza, Azzi, mezzomo, andrezza, Mazzeo. Medido contra os 9 299 leads em
# 01/09/2026. QUEM MEXER, MEÇA DE NOVO: um lead de teste que escapa polui um número de leve
# e de forma visível; um lead real excluído some de tudo, para sempre, sem sintoma.
PREDICADO_TESTE = r"(^\s*zz|smoke|teste|\mtest|john doe|fafaf|alefe|thobias justino)"


def chave_sql(col: str) -> str:
    """`app/telefone.chave_telefone` em SQL: DDD + últimos 8 dígitos.

    Existe porque 379 pessoas têm as DUAS grafias do telefone (com e sem o 9º dígito): a
    Exact guarda com, o WhatsApp entrega sem para DDD fora de 11–28. Agrupar por igualdade
    conta o mesmo humano duas vezes — e o achado da Josiane (escrita `555199297391` no
    WhatsApp e `5551999297391` na Exact) só existiu por causa desta chave.

    A implementação canônica é a de Python; esta é o espelho, e `test_relatorios.py` compara
    as duas sobre a base inteira. Duas implementações sem teste de igualdade divergem.
    """
    d = rf"regexp_replace(coalesce({col},''),'\D','','g')"
    dd = f"(CASE WHEN {d} LIKE '55%' AND length({d}) IN (12,13) THEN substr({d},3) ELSE {d} END)"
    return f"(CASE WHEN length({dd}) IN (10,11) THEN substr({dd},1,2)||right({dd},8) ELSE '' END)"


def thread_sql(col: str) -> str:
    """A chave de AGRUPAMENTO: a chave tolerante, ou o número cru quando ela não reduz.

    `chave_telefone` devolve `''` para o que não dá para reduzir — número estrangeiro
    (`447834239129`, `245956444415`, os dois existem na base) ou lixo de digitação. A
    docstring dela é explícita: **`''` NUNCA casa**, porque quem usa a chave para decidir
    precisa que o ilegível caia FORA, não que caia dentro.

    Num `GROUP BY` ou num `JOIN`, porém, `''` casa com `''`: todos os ilegíveis viram UMA
    conversa só. Medido aqui, e os dois defeitos eram visíveis: o invariante de silêncio
    acusava 1 conversa parada que era a soma de vários números distintos, e o funil
    contava 334 pessoas onde havia 127. É a mesma armadilha que o §A.4 do recon já
    resolvia com `coalesce(nullif(...), contact_wa_id)`.

    `chave_sql` continua sendo o espelho EXATO de `chave_telefone` — é ele que o teste
    compara contra a base inteira. Este é o derivado para agrupar.
    """
    d = rf"regexp_replace(coalesce({col},''),'\D','','g')"
    return f"coalesce(nullif({chave_sql(col)},''), {d})"


CHAVE_MSG = thread_sql("m.contact_wa_id")


# ==========================================================================================
# AS DUAS CESTAS DE LEAD DE TESTE
# ==========================================================================================
@dataclass(frozen=True)
class ConjuntoTeste:
    """O que sai do relatório, o que fica, e a lista de quem ficou em dúvida.

    NENHUMA REGRA MECÂNICA SEPARA SOZINHA — três foram testadas e nenhuma fecha:

      "zero inbound"                    deixa 15 duvidosos; 14 são testes legítimos feitos
                                        dos telefones do próprio time (217, 12 e 10 inbounds)
      "telefone com >= 2 leads de teste" pega 7 telefones, deixa 12 avulsos de fora —
                                        incluindo `John Doe`, `fafaf` e um `Álefe…teste`
      só o nome                         apaga a Ana Cristina

    `ANA CRISTINA JEFFRES PEREIRA - TESTE` (lead 51507231) É UMA PESSOA REAL: Landing Page,
    sub_source PosMulheridades, SDR Thobias, Follow 4, telefone de Manaus único na base, 8
    mensagens sendo 4 inbound dela. O sufixo " - TESTE" está no nome dela na Exact. O
    predicado a apagaria de todo relatório, em silêncio — é o defeito do `zz` um nível abaixo.

    Por isso DUAS cestas. `excluir` some das contas; `duvidosos` viaja no JSON para alguém
    decidir UMA vez, em vez de o código decidir todo dia em silêncio.

    Medido em 02/09/2026: 52 excluídos (18 chaves), 1 duvidoso — a Ana Cristina.
    """
    excluir: frozenset[str]
    duvidosos: tuple[dict, ...]
    nomes_que_casaram: int

    @property
    def array(self) -> list[str]:
        """Para o bind `= ANY(:teste)`. Nunca vazio: `ANY('{}')` é falso e não filtra nada,
        mas um array vazio em asyncpg precisa de tipo — o sentinela resolve os dois."""
        return sorted(self.excluir) or ["__nenhum__"]


_TESTE_CACHE: tuple[float, ConjuntoTeste] | None = None
TTL_TESTE = 600


async def chaves_de_teste(db: AsyncSession) -> ConjuntoTeste:
    """As chaves de telefone dos leads de teste. Cache em processo, TTL 600 s.

    NÃO É CACHE DE AGREGAÇÃO (o E7 do recon continua recusado). O que se guarda aqui é um
    conjunto de strings que ninguém lê — insumo de um `NOT IN`. O pior caso é quantificado:
    um lead de teste criado dentro da janela do TTL, com 1 ou 2 mensagens, sobre as ~4 400
    de uma janela de 30 dias — ≈ 0,05%, e some sozinho no ciclo seguinte.

    Custo evitado, medido: ~75 ms por chamada, e a página faz 5 chamadas em paralelo.

    Com um único processo `uvicorn`, um dicionário de módulo basta. Se um dia houver mais de
    um worker, cada um terá o seu — inofensivo, porque o conteúdo é idêntico.
    """
    global _TESTE_CACHE
    if _TESTE_CACHE and (time.monotonic() - _TESTE_CACHE[0]) < TTL_TESTE:
        return _TESTE_CACHE[1]

    from app.telefone import chave_telefone

    nomes = (await db.execute(text(
        "SELECT exact_id, name, phone1 FROM exact_leads "
        "WHERE lower(translate(name, :de, :para)) ~ :pred"),
        {"de": ACENTOS_DE, "para": ACENTOS_PARA, "pred": PREDICADO_TESTE})).all()

    # UMA varredura de `messages`, não uma por lead: a versão correlacionada custa 1,9 s.
    com_inbound = {chave_telefone(w) for w in (await db.execute(text(
        "SELECT DISTINCT contact_wa_id FROM messages WHERE direction='inbound'"
    ))).scalars().all()} - {""}

    por_chave: dict[str, list] = {}
    for exact_id, nome, telefone in nomes:
        por_chave.setdefault(chave_telefone(telefone), []).append((exact_id, nome))

    # "Bloco conhecido de teste", DERIVADO e não digitado: uma chave que carrega dois ou mais
    # leads de nome-de-teste é telefone do time. Uma lista fixa cobria 29% e envelhecia.
    bloco = {k for k, leads in por_chave.items() if k and len(leads) >= 2}

    excluir, duvidosos = set(), []
    for chave, leads in por_chave.items():
        if not chave or chave not in com_inbound or chave in bloco:
            if chave:
                excluir.add(chave)
            continue
        duvidosos.extend({"exact_id": e, "nome": n, "chave": chave} for e, n in leads)

    conj = ConjuntoTeste(frozenset(excluir), tuple(duvidosos), len(nomes))
    _TESTE_CACHE = (time.monotonic(), conj)
    return conj


# ==========================================================================================
# O CONTRATO DA RESPOSTA
# ==========================================================================================
CONFIANCAS = ("alta", "media", "baixa", "indisponivel", "nao_medivel")


def metrica(id: str, rotulo: str, valor, *, n=None, relogio: str, confianca: str,
            definicao: str, limitacao: str | None = None, **extra) -> dict:
    """Nenhuma métrica devolve número solto.

    `definicao` e `limitacao` VÃO PARA A TELA — a primeira no tooltip do ⓘ, a segunda como
    texto visível. Uma fonte: o front não reescreve nenhuma das duas.

    `confianca` nunca é `0`. São cinco estados e cada um tem tratamento visual próprio:
      alta         o número é o número
      media        tem ressalva, e a ressalva aparece na tela
      baixa        serve de indício, não de medida
      indisponivel o dado começa DEPOIS de parte do período pedido
      nao_medivel  o dado não existe — e `valor` é None, nunca 0, nunca barra
    """
    assert confianca in CONFIANCAS, confianca
    return {"id": id, "rotulo": rotulo, "valor": valor, "n": n, "relogio": relogio,
            "confianca": confianca, "definicao": definicao, "limitacao": limitacao, **extra}


def envelope(secao: str, p: Periodo, metricas: list[dict], teste: ConjuntoTeste,
             **extra) -> dict:
    """O `periodo` do JSON é o MESMO objeto que foi para o `WHERE`. Ver o cabeçalho."""
    return {"secao": secao, "periodo": p.json(), "apurado_em": agora_sp().isoformat(),
            "metricas": metricas,
            "leads_de_teste": {"excluidos": len(teste.excluir),
                               "duvidosos": list(teste.duvidosos)},
            **extra}


# ==========================================================================================
# AS QUERIES. Todas parametrizadas por :ini/:fim naive-SP; onde a tabela é UTC, o bind já
# vem convertido por `para_utc` e o nome do parâmetro diz isso (`:ini_utc`).
# ==========================================================================================
SQL_ATENDIMENTO = f"""
-- RELÓGIO: SP (messages.timestamp).
-- Conta PESSOAS, não mensagens: uma abertura pode sair em duas linhas (template + texto,
-- pela divisão de threads) e o mesmo humano pode ter duas grafias de telefone.
WITH ab AS (
  SELECT {CHAVE_MSG} AS thr,
         min(m.timestamp) FILTER (WHERE m.status IN ('delivered','read')) AS entregue_em,
         max(m.nat_etapa) AS abertura
  FROM messages m
  WHERE m.direction = 'outbound' AND m.nat_etapa = ANY(:aberturas)
    AND m.timestamp >= :ini AND m.timestamp <= :fim
  GROUP BY 1
), lim AS (SELECT * FROM ab WHERE NOT (thr = ANY(:teste))),
inb AS (
  SELECT {CHAVE_MSG} AS thr, m.timestamp AS ts
  FROM messages m
  WHERE m.direction = 'inbound' AND m.timestamp >= :ini AND m.timestamp <= :fim
)
-- ⚠️ count(DISTINCT thr) e NÃO count(*): depois do LEFT JOIN com `inb`, cada pessoa vira
-- uma linha por mensagem recebida. Com count(*) isto devolveu 334 pessoas onde havia 127.
SELECT count(DISTINCT lim.thr) AS pessoas,
       count(DISTINCT lim.thr) FILTER (WHERE entregue_em IS NOT NULL) AS entregues,
       count(DISTINCT lim.thr) FILTER (
         WHERE entregue_em IS NOT NULL AND inb.ts IS NOT NULL) AS responderam
FROM lim LEFT JOIN inb ON inb.thr = lim.thr AND inb.ts > lim.entregue_em
"""

SQL_QUALIFICACOES = f"""
-- RELÓGIO: nat_qualificacao_state.created_at = UTC (bind convertido).
SELECT count(*) AS estados,
       count(*) FILTER (WHERE formacao IS NOT NULL AND ano_conclusao IS NOT NULL
                          AND atuacao IS NOT NULL AND motivacao IS NOT NULL) AS completas
FROM nat_qualificacao_state s
WHERE s.created_at >= :ini_utc AND s.created_at <= :fim_utc
  AND NOT ({thread_sql('s.contact_wa_id')} = ANY(:teste))
"""

SQL_REUNIOES = f"""
-- RELÓGIO: exact_stage_events.observado_em = UTC (bind convertido).
-- PRECEDÊNCIA DE 5 VIAS. A regra antiga ("entrou em Agendados sem linha em agendamentos =
-- indeterminado") empilhava quatro casos distintos: `agendamentos.passo` tem estados
-- intermediários e um lead pode ter várias linhas. As duas categorias do meio são
-- acionáveis — o visitante começou o fluxo e não fechou lá.
--   ia             linha com passo='agendado' e SEM origem_ip
--   landing_page   linha com passo='agendado'
--   ia_incompleta  linha sem origem_ip que nunca chegou a 'agendado'  (hoje 0; o caso
--                  SlotIndisponivel existe, e sem esta via o rótulo mentiria em silêncio)
--   lp_incompleta  linha que nunca chegou a 'agendado'
--   indeterminada  nenhuma linha
WITH ev AS (
  SELECT DISTINCT e.exact_lead_id
  FROM exact_stage_events e
  WHERE e.observado_em >= :ini_utc AND e.observado_em <= :fim_utc
    AND e.stage_para = 'Agendados' AND e.funnel_id = :funil
    AND {_GUARDA_REAGENDAMENTO}
), lim AS (
  SELECT ev.exact_lead_id
  FROM ev JOIN exact_leads el ON el.exact_id = ev.exact_lead_id
  WHERE NOT ({thread_sql('el.phone1')} = ANY(:teste))
)
SELECT CASE
  WHEN EXISTS (SELECT 1 FROM agendamentos a WHERE a.lead_id = lim.exact_lead_id
                 AND a.passo = 'agendado' AND a.origem_ip IS NULL) THEN 'ia'
  WHEN EXISTS (SELECT 1 FROM agendamentos a WHERE a.lead_id = lim.exact_lead_id
                 AND a.passo = 'agendado')                         THEN 'landing_page'
  WHEN EXISTS (SELECT 1 FROM agendamentos a WHERE a.lead_id = lim.exact_lead_id
                 AND a.origem_ip IS NULL)                          THEN 'ia_incompleta'
  WHEN EXISTS (SELECT 1 FROM agendamentos a WHERE a.lead_id = lim.exact_lead_id)
                                                                   THEN 'lp_incompleta'
  ELSE 'indeterminada' END AS origem, count(*) AS n
FROM lim GROUP BY 1
"""

SQL_FUNIL_COORTE = f"""
-- RELÓGIO: SP (messages.timestamp) para a abertura; o estado é lido AGORA.
-- POR COORTE, NÃO SOMADO, e o degrau "deu formação" está FORA de propósito: em 121 estados,
-- 102 já nasciam com a formação preenchida, vinda do lead da Exact — não da conversa. Somar
-- as duas coortes escondia que o T3 (precisa perguntar a formação) converte ZERO.
--
-- A coorte vem de `messages.nat_etapa`, que carimba QUAL abertura saiu. É a única marca
-- histórica que existe: `nat_qualificacao_state.etapa` é sobrescrita.
WITH ab AS (
  SELECT {CHAVE_MSG} AS thr,
         min(m.timestamp) FILTER (WHERE m.status IN ('delivered','read')) AS entregue_em,
         CASE WHEN bool_or(m.nat_etapa = :t3) THEN 't3' ELSE 't1_t2' END AS coorte
  FROM messages m
  WHERE m.direction = 'outbound' AND m.nat_etapa = ANY(:aberturas)
    AND m.timestamp >= :ini AND m.timestamp <= :fim
  GROUP BY 1
), lim AS (SELECT * FROM ab WHERE NOT (thr = ANY(:teste)) AND entregue_em IS NOT NULL),
inb AS (
  -- ⚠️ ÚLTIMO inbound, não o primeiro. Cinco das seis pessoas do roteiro T3 já tinham
  -- escrito ANTES de a abertura chegar (o texto do botão da landing page); com `min` elas
  -- contavam como "não respondeu" e o degrau ficava MENOR que o degrau de baixo.
  SELECT {CHAVE_MSG} AS thr, max(m.timestamp) AS ultima
  FROM messages m WHERE m.direction = 'inbound' AND m.timestamp <= :fim GROUP BY 1
), est AS (
  -- Agregado por thr: as duas grafias do mesmo telefone podem ter duas linhas de estado, e
  -- um join 1:N aqui multiplicaria a pessoa dentro do count.
  SELECT {thread_sql('s.contact_wa_id')} AS thr,
         max(s.ano_conclusao) AS ano_conclusao, max(s.atuacao) AS atuacao,
         max(s.motivacao) AS motivacao, max(s.agendamento_id) AS agendamento_id
  FROM nat_qualificacao_state s GROUP BY 1
)
SELECT lim.coorte,
       count(*) AS abertas,
       count(*) FILTER (WHERE inb.ultima > lim.entregue_em)        AS responderam,
       count(*) FILTER (WHERE est.ano_conclusao IS NOT NULL)       AS deu_ano,
       count(*) FILTER (WHERE est.atuacao       IS NOT NULL)       AS deu_atuacao,
       count(*) FILTER (WHERE est.motivacao     IS NOT NULL)       AS deu_motivacao,
       count(*) FILTER (WHERE est.agendamento_id IS NOT NULL)      AS agendou
FROM lim LEFT JOIN inb ON inb.thr = lim.thr
         LEFT JOIN est ON est.thr = lim.thr
GROUP BY 1
"""

SQL_SILENCIO = f"""
-- RELÓGIO: SP. Invariante: DEVE ser 0.
-- Conta CONVERSAS (o lead que ficou sem resposta), não mensagens.
-- A margem de 15 min protege contra o falso positivo em janela aberta: sem ela, quem
-- escreveu há 30 s aparece como "agente calou".
-- ⚠️ `est` lê a etapa ATUAL, sem recorte de tempo — este card declara "situação agora" na
-- tela, e não obedece ao seletor de período. Reconstruir a etapa no instante da mensagem é
-- IMPOSSÍVEL com o dado de hoje (sem log de transição), não caro.
WITH mk AS (
  SELECT m.direction, m.timestamp AS ts, {CHAVE_MSG} AS thr
  FROM messages m WHERE m.timestamp >= :ini AND m.timestamp <= :fim
), est AS (
  SELECT DISTINCT {thread_sql('s.contact_wa_id')} AS thr FROM nat_qualificacao_state s
  WHERE s.etapa = ANY(:etapas_ativas)
)
SELECT count(DISTINCT i.thr) AS conversas
FROM mk i JOIN est e ON e.thr = i.thr
WHERE i.direction = 'inbound' AND i.ts <= :corte_margem
  AND NOT (i.thr = ANY(:teste))
  AND NOT EXISTS (SELECT 1 FROM mk o
                  WHERE o.thr = i.thr AND o.direction = 'outbound' AND o.ts > i.ts)
"""

SQL_SAUDE_MOTIVOS = f"""
-- RELÓGIO: SP (transferido_em, encerrado_em).
-- O motivo é texto livre e carrega IDENTIFICADORES: "envio recusado: 5537999965494 está em
-- 'concluido'" e "o LLM escolheu um horário que não foi oferecido ('2026-09-01 09:00')".
-- Sem normalizar, quatro ocorrências do MESMO motivo viram quatro linhas de n=1 e a tela
-- mostra doze motivos onde há sete. Normaliza para AGRUPAR; o motivo cru continua no banco.
SELECT CASE WHEN s.transferido_em IS NOT NULL THEN 'transferido' ELSE 'encerrado' END AS tipo,
       regexp_replace(
-- ⚠️ CHAVES DUPLICADAS nos quantificadores: esta string é f-string, e `{{10,13}}` sem
-- escapar é lido como campo de formatação — vira `(10, 13)` e o quantificador
-- desaparece SEM ERRO. Foi o que aconteceu na primeira escrita disto.
         regexp_replace(coalesce(s.transferido_motivo, s.encerrado_motivo, '(sem motivo)'),
                        '\y\d{{10,13}}\y', 'um lead', 'g'),
         '\(''?(\d{{4}}-\d{{2}}-\d{{2}}[^'')]*|None)''?\)', '(um horário)', 'g') AS motivo,
       count(*) AS n
FROM nat_qualificacao_state s
WHERE coalesce(s.transferido_em, s.encerrado_em) BETWEEN :ini AND :fim
  AND NOT ({thread_sql('s.contact_wa_id')} = ANY(:teste))
GROUP BY 1, 2 ORDER BY 3 DESC
"""

SQL_VIGIAS = """
-- RELÓGIO: SP (run_at). Vigia DISPARADO = ação executada, não agendada.
SELECT a.kind, a.status, count(*) AS n
FROM nat_scheduled_actions a
WHERE a.run_at >= :ini AND a.run_at <= :fim
GROUP BY 1, 2 ORDER BY 3 DESC
"""

SQL_MEDIANA = f"""
-- RELÓGIO: SP (messages.timestamp). UMA passada, sem LATERAL correlacionado: a versão dos
-- recons custava 679 ms (1 213 loops de sort), esta custa 39 ms e devolve o mesmo resultado.
--
-- ⚠️ O ALGORITMO PASSA A SER ESTE. A definição publicada em 29/08 era PROSA, e a prosa
-- admite pelo menos três leituras (o que conta como pergunta, se interactive/button contam
-- como outbound, se a abertura entra) — cada uma com um N diferente. Não tente reproduzir
-- os 3,7 s publicados: não há como saber qual leitura os produziu. A ordem de grandeza é
-- que é robusta: IA em segundos, humano em dezenas de minutos.
WITH mk AS (
  SELECT m.id, m.direction, m.message_type, m.timestamp AS ts, m.nat_etapa,
         {CHAVE_MSG} AS thr
  FROM messages m WHERE m.timestamp >= :ini AND m.timestamp <= :fim
), w AS (
  SELECT thr, ts, direction, id,
    lag(direction) OVER p AS dir_ant,
    min(ts) FILTER (WHERE direction = 'outbound' AND message_type <> 'template')
            OVER (PARTITION BY thr ORDER BY ts, id
                  ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING) AS ts_resp,
    (array_agg(nat_etapa) FILTER (WHERE direction = 'outbound' AND message_type <> 'template')
            OVER (PARTITION BY thr ORDER BY ts, id
                  ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING))[1] AS etapa_resp
  FROM mk WINDOW p AS (PARTITION BY thr ORDER BY ts, id)
)
SELECT CASE WHEN etapa_resp IS NOT NULL THEN 'ia' ELSE 'humano' END AS quem,
       count(*) AS n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM (ts_resp - ts))) AS mediana
FROM w
WHERE direction = 'inbound' AND dir_ant IS DISTINCT FROM 'inbound' AND ts_resp IS NOT NULL
  AND NOT (thr = ANY(:teste))
GROUP BY 1
"""

SQL_POR_SDR = f"""
-- RELÓGIO: SP. Só existe a partir de CORTE_SENT_BY — antes disso o dado NUNCA foi gravado.
SELECT u.name AS sdr, count(*) AS enviadas,
       count(DISTINCT {CHAVE_MSG}) AS pessoas
FROM messages m JOIN users u ON u.id = m.sent_by
WHERE m.timestamp >= :ini AND m.timestamp <= :fim AND m.sent_by IS NOT NULL
  AND NOT ({CHAVE_MSG} = ANY(:teste))
GROUP BY 1 ORDER BY 2 DESC
"""

SQL_VAO_ESPONTANEO = f"""
-- RELÓGIO: SP. ⚠️ PARÊNTESES no OR: sem eles o predicado vira `(direction AND A) OR B` e
-- captura outbound — foi o erro que devolveu 908 em vez de 38 na primeira tentativa.
WITH bot AS (
  SELECT {CHAVE_MSG} AS thr, min(m.contact_wa_id) AS wa_id, min(m.timestamp) AS escreveu
  FROM messages m
  WHERE m.direction = 'inbound' AND m.timestamp >= :ini AND m.timestamp <= :fim
    AND ( lower(translate(m.content, :de, :para)) LIKE :p1
       OR lower(translate(m.content, :de, :para)) LIKE :p2 )
  GROUP BY 1
), lim AS (SELECT * FROM bot WHERE NOT (thr = ANY(:teste))),
saida AS (
  SELECT {CHAVE_MSG} AS thr, m.timestamp AS ts
  FROM messages m WHERE m.direction = 'outbound' AND m.timestamp >= :ini
), leads AS (
  -- UMA passada sobre exact_leads, não uma por pessoa. Três subqueries escalares
  -- correlacionadas aqui custavam 3,4 s — cada uma recalculava a chave sobre os 9 299
  -- nomes. O lead mais RECENTE é o que vale: o mesmo telefone pode carregar vários.
  SELECT DISTINCT ON (thr) thr, name, funnel_id, stage FROM (
    SELECT {thread_sql('el.phone1')} AS thr, el.exact_id, el.name, el.funnel_id, el.stage
    FROM exact_leads el) x
  ORDER BY thr, exact_id DESC
)
SELECT lim.thr, lim.wa_id, lim.escreveu,
       leads.name AS nome, leads.funnel_id AS funil, leads.stage AS etapa
FROM lim LEFT JOIN leads ON leads.thr = lim.thr
WHERE NOT EXISTS (SELECT 1 FROM saida o WHERE o.thr = lim.thr AND o.ts > lim.escreveu)
ORDER BY lim.escreveu DESC
"""

SQL_JORNADA_COORTE = f"""
-- RELÓGIO: agendamentos.created_at = UTC (bind convertido). slot_inicio é SP.
-- DISTINCT ON por lead: um lead pode ter várias linhas em `agendamentos`; a coorte é de
-- PESSOAS que agendaram, não de linhas.
-- `passo='agendado'` já faz metade da higiene sem ninguém ter pedido — isso é sorte, não
-- desenho, e por isso o predicado de teste roda de qualquer jeito.
WITH a AS (
  SELECT DISTINCT ON (ag.lead_id)
         ag.lead_id, ag.nome, ag.sales_rep_email, ag.origem_ip, ag.created_at, ag.slot_inicio,
         {thread_sql('ag.telefone')} AS thr
  FROM agendamentos ag
  WHERE ag.passo = 'agendado' AND ag.lead_id IS NOT NULL
    AND ag.created_at >= :ini_utc AND ag.created_at <= :fim_utc
  ORDER BY ag.lead_id, ag.created_at
), lim AS (SELECT * FROM a WHERE NOT (thr = ANY(:teste)))
SELECT lim.lead_id, lim.nome, lim.sales_rep_email, lim.slot_inicio,
       (lim.origem_ip IS NULL) AS da_ia,
       el.funnel_id, el.stage,
       (SELECT max(e.observado_em) FROM exact_stage_events e
         WHERE e.exact_lead_id = lim.lead_id) AS ultima_transicao
FROM lim LEFT JOIN exact_leads el ON el.exact_id = lim.lead_id
ORDER BY ultima_transicao DESC NULLS LAST
"""

SQL_VENDIDOS_RASTREAVEIS = """
-- RELÓGIO: UTC (exact_leads.stage é lido AGORA — é estado, não evento).
-- ⚠️ NÃO CALCULAR PERCENTUAL SOBRE 1 176. Os que faltam não são vendas sem origem: são
-- vendas ANTERIORES ao registro. `agendamentos` começou em 17/08/2026.
-- IGNORA o seletor de período de propósito: a pergunta é "de tudo que já foi vendido,
-- quanto dá para ligar a uma reunião nossa" — e ela não tem janela.
SELECT count(*) FILTER (WHERE el.stage = 'Vendidos') AS vendidos,
       count(*) FILTER (WHERE el.stage = 'Vendidos' AND ag.lead_id IS NOT NULL) AS rastreaveis
FROM exact_leads el
LEFT JOIN (SELECT DISTINCT lead_id FROM agendamentos WHERE lead_id IS NOT NULL) ag
       ON ag.lead_id = el.exact_id
WHERE el.funnel_id = :funil_vendas
"""


# ==========================================================================================
# AS ROTAS. Uma por seção, e não uma monolítica: a seção por SDR tem dado só desde 01/09, a
# métrica 6 tem metade cega e a das reuniões depende do sync da Exact. Numa rota só, um NULL
# inesperado em qualquer uma derruba a página inteira; separadas, a tela mostra as outras e
# um card "indisponível" na que falhou. O front dispara as chamadas em paralelo.
# ==========================================================================================
PERIODO_Q = Query("30d", description="hoje | 7d | 30d | AAAA-MM-DD:AAAA-MM-DD")


def tolerante(secao: str):
    """Uma seção que estoura não derruba as outras — e diz POR QUE estourou.

    As rotas já são independentes, então um 500 numa não impede as outras de carregar. O que
    este envelope acrescenta é a diferença entre "card vazio" e "card quebrado, com o
    motivo": sem ele o `axios` do front cai no `catch` genérico e a tela mostra o mesmo nada
    que mostraria se a métrica fosse zero — que é precisamente o que a regra 2 proíbe.

    Devolve 200 com `erro` preenchido, DE PROPÓSITO: um 5xx faz o axios lançar, e o front
    perderia o motivo no caminho. O traceback vai para o log do servidor, que é onde ele
    serve para alguma coisa. A página é somente leitura — não há ação para desfazer.
    """
    def deco(fn):
        @wraps(fn)
        async def wrapper(periodo: str = PERIODO_Q, db: AsyncSession = Depends(get_db)):
            try:
                return await fn(periodo, db)
            except HTTPException:
                raise                       # 400 de período inválido é do usuário, não nosso
            except Exception as e:
                log.exception("relatorios/%s falhou", secao)
                return {"secao": secao, "periodo": None, "apurado_em": agora_sp().isoformat(),
                        "metricas": [],
                        "erro": {"tipo": type(e).__name__, "mensagem": str(e)[:300]}}
        return wrapper
    return deco

_R_SP = "SP (messages.timestamp)"
_R_UTC = "UTC→SP (bind convertido)"

# A frase do "número que muda sozinho". Três métricas mudam de valor quando recalculadas
# sobre a MESMA janela, sem bug nenhum — são todas da forma "quantos ainda não foram
# atendidos", e o "ainda" se move. Sem esta frase, a página e o .md parecem se contradizer.
MOVEL = ("Este número conta quem ainda não foi atendido até agora. Se alguém do time "
         "responder essas pessoas hoje, o número cai — mesmo você escolhendo o mesmo período.")


async def _base(db: AsyncSession, periodo: str):
    p = janela(periodo)
    teste = await chaves_de_teste(db)
    comum = {"ini": p.de, "fim": p.ate, "ini_utc": para_utc(p.de), "fim_utc": para_utc(p.ate),
             "teste": teste.array}
    return p, teste, comum


@router.get("/resumo")
@tolerante("resumo")
async def resumo(periodo: str = PERIODO_Q, db: AsyncSession = Depends(get_db)):
    """Métricas 1 a 4 — os cards do topo."""
    p, teste, q = await _base(db, periodo)

    at = (await db.execute(text(SQL_ATENDIMENTO), {**q, "aberturas": list(ABERTURAS)})).one()
    ql = (await db.execute(text(SQL_QUALIFICACOES), q)).one()
    reu = {r.origem: r.n for r in (await db.execute(
        text(SQL_REUNIOES), {**q, "funil": FUNIL_POS})).all()}

    return envelope("resumo", p, [
        metrica("ia_aberturas", "Pessoas que a Nat abordou",
                at.entregues, n=at.pessoas, relogio=_R_SP, confianca="alta",
                definicao="Pessoas que receberam uma abertura da Nat com status entregue ou "
                          "lido. O denominador é quem recebeu a tentativa de abertura — a "
                          "diferença são falhas de entrega da Meta.",
                unidade="pessoas"),
        metrica("ia_conversas", "Responderam a Nat",
                at.responderam, n=at.entregues, relogio=_R_SP, confianca="alta",
                definicao="Pessoas que escreveram alguma coisa depois de a abertura ser "
                          "entregue. Base: quem recebeu a abertura.",
                unidade="pessoas"),
        metrica("ia_qualificacoes", "Qualificações completas",
                ql.completas, n=ql.estados, relogio=_R_UTC, confianca="alta",
                definicao="Conversas em que as quatro respostas foram coletadas: formação, "
                          "ano de conclusão, atuação e motivação.",
                unidade="conversas"),
        metrica("reunioes_ia", "Reuniões marcadas pela Nat",
                reu.get("ia", 0), n=sum(reu.values()), relogio=_R_UTC, confianca="alta",
                definicao="Leads que entraram na etapa Agendados do funil de pós e têm "
                          "agendamento fechado por nós SEM IP de visitante — ou seja, "
                          "marcado na conversa, não no site.",
                limitacao=None, quebra=reu,
                unidade="reuniões"),
        metrica("reunioes_lp", "Reuniões pela página de obrigado",
                reu.get("landing_page", 0), n=sum(reu.values()), relogio=_R_UTC,
                confianca="alta",
                definicao="Mesma entrada em Agendados, com agendamento fechado no site "
                          "(tem IP de visitante). É o auto-serviço.",
                limitacao=(f"{reu.get('lp_incompleta', 0)} pessoa(s) começaram o fluxo da "
                           "página, a linha nasceu e o agendamento não fechou lá — e mesmo "
                           "assim o lead entrou em Agendados. Elas aparecem como "
                           "'LP incompleta' na quebra, não somadas aqui.")
                          if reu.get("lp_incompleta") else None,
                quebra=reu, unidade="reuniões"),
        metrica("reunioes_realizadas", "Reuniões realizadas", None, relogio="—",
                confianca="nao_medivel",
                definicao="Quantas das reuniões marcadas aconteceram de fato.",
                limitacao="O status da reunião (Vigente/Concluído/Cancelada) vive só na API "
                          "da Exact e não é sincronizado. Pior: ele vira 'Concluído' no "
                          "instante em que o lead troca de funil, com data no futuro — ou "
                          "seja, exatamente os leads que avançam são os que têm o registro "
                          "corrompido. Medir 'reunião realizada' por aí mediria 'avançou de "
                          "funil', que é outra métrica."),
    ], teste)


@router.get("/ia")
@tolerante("ia")
async def ia(periodo: str = PERIODO_Q, db: AsyncSession = Depends(get_db)):
    """Métrica 8 (funil por coorte) e métrica 7 (saúde)."""
    p, teste, q = await _base(db, periodo)

    coortes = {r.coorte: dict(r._mapping) for r in (await db.execute(
        text(SQL_FUNIL_COORTE), {**q, "aberturas": list(ABERTURAS), "t3": ABERTURA_T3})).all()}

    # O card de saúde IGNORA o seletor: `nat_qualificacao_state.etapa` é o estado ATUAL, e
    # fingir que ele responde a uma janela seria mentir com um seletor.
    agora = agora_sp()
    silencio = (await db.execute(text(SQL_SILENCIO), {
        "ini": datetime(2000, 1, 1), "fim": agora,
        "corte_margem": agora - MARGEM_SILENCIO,
        "etapas_ativas": sorted(ETAPAS_QUALIFICACAO_ATIVAS), "teste": teste.array})).scalar()

    motivos = [dict(r._mapping) for r in (await db.execute(text(SQL_SAUDE_MOTIVOS), q)).all()]
    vigias = [dict(r._mapping) for r in (await db.execute(text(SQL_VIGIAS), q)).all()]
    # O vigia `vigiar_resposta` DISPARAR é o sintoma de agente travado. Ele ser cancelado é
    # o caso saudável: a conversa andou e a vigilância deixou de ser necessária.
    vigias_disparados = sum(v["n"] for v in vigias
                            if v["kind"] == KIND_VIGIAR_RESPOSTA and v["status"] == "executado")
    sem_resposta = sum(m["n"] for m in motivos if m["motivo"] == "sem_resposta_do_agente")

    def degraus(c: dict | None) -> list[dict]:
        if not c:
            return []
        return [{"rotulo": r, "n": c[k]} for r, k in (
            ("Abertura entregue", "abertas"), ("Respondeu", "responderam"),
            ("Deu o ano", "deu_ano"), ("Deu a atuação", "deu_atuacao"),
            ("Deu a motivação", "deu_motivacao"), ("Agendou", "agendou"))]

    t12, t3 = coortes.get("t1_t2"), coortes.get("t3")
    return envelope("ia", p, [
        metrica("funil_t1_t2", "Quem já tinha formação no cadastro",
                degraus(t12), n=(t12 or {}).get("abertas", 0), relogio=_R_SP,
                confianca="alta",
                definicao="O roteiro de quem chega com a formação conhecida: a Nat afirma a "
                          "formação e vai direto ao próximo passo.",
                limitacao="O degrau 'deu formação' não aparece de propósito: em 102 de 121 "
                          "conversas a formação já vinha do cadastro da Exact, não da "
                          "conversa. Ele mede dado que já tínhamos, não progresso.",
                coorte="t1_t2"),
        metrica("funil_t3", "Quem precisou ser perguntado sobre a formação",
                degraus(t3), n=(t3 or {}).get("abertas", 0), relogio=_R_SP,
                confianca="alta",
                definicao="O roteiro de quem chega sem formação no cadastro: a primeira "
                          "coisa que a Nat faz é perguntar.",
                limitacao="Este caminho é o único em que a primeira mensagem ao lead é uma "
                          "exigência, e ele converte pouco. Não leia como perda comercial: "
                          "parte dessas pessoas está em funil de vendas, atendida por outro "
                          "canal. Amostra pequena — conte as pessoas, não a taxa.",
                coorte="t3"),
        metrica("saude_silencio", "Conversas paradas esperando a Nat",
                silencio, n=None, relogio="SP · situação AGORA",
                confianca="alta" if silencio == 0 else "media",
                definicao="Lead que escreveu, está numa etapa em que a Nat deve a próxima "
                          "fala, e não recebeu resposta. Margem de 15 minutos, acima do "
                          "tempo de resposta mais lento observado no agente.",
                limitacao="Este card mostra a situação AGORA e não muda com o período "
                          "escolhido. A etapa do lead é sobrescrita a cada avanço e não há "
                          "histórico — em que etapa alguém estava semana passada não é "
                          "recuperável.",
                ignora_periodo=True),
        metrica("saude_sem_resposta_agente", "Encerradas por silêncio do agente",
                sem_resposta, n=None, relogio="SP (encerrado_em)",
                confianca="alta" if sem_resposta == 0 else "media",
                definicao="Conversas encerradas com o motivo 'sem_resposta_do_agente'.",
                limitacao=None),
        metrica("saude_motivos", "Como as conversas terminam",
                motivos, n=sum(m["n"] for m in motivos), relogio="SP",
                confianca="alta",
                definicao="Transferências ao humano e encerramentos, por motivo, no período.",
                limitacao=None),
        metrica("saude_vigias_disparados", "Vigias que precisaram disparar",
                vigias_disparados, n=None, relogio="SP (run_at)",
                confianca="alta" if vigias_disparados == 0 else "media",
                definicao="O vigia acorda quando o agente recebe uma mensagem e não "
                          "responde. Ele disparar significa que a Nat travou e alguém "
                          "precisou ser avisado. Zero é o número certo.",
                limitacao=None),
        metrica("saude_acoes", "Ações programadas do agente",
                vigias, n=sum(v["n"] for v in vigias), relogio="SP (run_at)",
                confianca="alta",
                definicao="Tudo que o agente agendou para si no período, por tipo e "
                          "situação: abrir conversa, lembrar da reunião, encerrar por "
                          "inatividade, vigiar a própria resposta. 'cancelado' é o caso "
                          "normal — a ação deixou de ser necessária porque a conversa "
                          "andou.",
                limitacao=None),
    ], teste)


@router.get("/humano")
@tolerante("humano")
async def humano(periodo: str = PERIODO_Q, db: AsyncSession = Depends(get_db)):
    """Métrica 2 (medianas) e métrica 5 (por SDR). A métrica 9 fica para a v2."""
    p, teste, q = await _base(db, periodo)

    med = {r.quem: dict(r._mapping) for r in (await db.execute(text(SQL_MEDIANA), q)).all()}
    ia_m, hu_m = med.get("ia", {}), med.get("humano", {})

    # A fronteira do `sent_by`. Gráfico vazio lê-se como "ninguém trabalhou" — por isso a
    # cobertura viaja no JSON e a seção some quando o período inteiro é anterior ao corte.
    cobre_desde = max(p.de, CORTE_SENT_BY)
    dias_cobertos = 0 if p.ate < CORTE_SENT_BY else max((p.ate - cobre_desde).days, 1)
    linhas_sdr = ([] if p.ate < CORTE_SENT_BY else
                  [dict(r._mapping) for r in (await db.execute(
                      text(SQL_POR_SDR), {**q, "ini": cobre_desde})).all()])

    if p.ate < CORTE_SENT_BY:
        conf_sdr, aviso = "nao_medivel", (
            "O período escolhido é inteiro anterior a 01/09/2026 16h, quando o sistema "
            "começou a gravar quem enviou cada mensagem. Não há o que mostrar: o dado não "
            "existe, e não é zero.")
    elif p.de < CORTE_SENT_BY:
        conf_sdr, aviso = "indisponivel", (
            "Só dá para atribuir mensagem a uma pessoa a partir de 01/09/2026, 16h. Antes "
            f"disso o sistema não gravava quem enviou — o dado não existe, e não é zero. "
            f"Você pediu {p.de:%d/%m} – {p.ate:%d/%m}; os números abaixo cobrem "
            f"{dias_cobertos} de {p.dias} dias do período.")
    else:
        conf_sdr, aviso = "alta", None

    return envelope("humano", p, [
        metrica("resposta_mediana", "Tempo até responder",
                {"ia": ia_m.get("mediana"), "humano": hu_m.get("mediana")},
                n={"ia": ia_m.get("n", 0), "humano": hu_m.get("n", 0)},
                relogio=_R_SP, confianca="media", unidade="segundos",
                definicao="Da primeira mensagem do lead até a primeira resposta que não é "
                          "template. Mediana, não média.",
                limitacao="Populações diferentes: a Nat responde lead novo que acabou de "
                          "escrever; o time responde base de follow, muitas vezes fria. A "
                          "comparação mostra velocidade, não eficácia — e é para ser lida "
                          "em ordem de grandeza, não no dígito.",
                comparacao_ressalvada=True),
        metrica("mensagens_por_sdr", "Mensagens por pessoa do time",
                linhas_sdr or None, n=sum(l["enviadas"] for l in linhas_sdr) or None,
                relogio=_R_SP, confianca=conf_sdr,
                definicao="Templates e mensagens enviados por cada pessoa logada no Hub.",
                limitacao=aviso,
                cobertura={"desde": CORTE_SENT_BY.isoformat(),
                           "dias_cobertos": dias_cobertos, "dias_pedidos": p.dias}),
        metrica("follow_humano", "Follow do time, por template", None, relogio="—",
                confianca="nao_medivel",
                definicao="Bulk × individual, resposta em 24 h, recusas e falhas da Meta.",
                limitacao="Fora desta versão — é a métrica mais cara do inventário e nada "
                          "nela é urgente. Quando entrar, virá com a nota de que só conta "
                          "mensagem de WhatsApp: ligação não fica registrada no sistema."),
    ], teste)


@router.get("/atritos")
@tolerante("atritos")
async def atritos(periodo: str = PERIODO_Q, db: AsyncSession = Depends(get_db)):
    """Métrica 6 (conversas cortadas) e métrica 10 (vão do espontâneo)."""
    p, teste, q = await _base(db, periodo)

    motivos = [dict(r._mapping) for r in (await db.execute(text(SQL_SAUDE_MOTIVOS), q)).all()]
    cortadas = sum(m["n"] for m in motivos
                   if m["tipo"] == "transferido" and "manual" in (m["motivo"] or ""))

    vao = [dict(r._mapping) for r in (await db.execute(text(SQL_VAO_ESPONTANEO), {
        **q, "de": ACENTOS_DE, "para": ACENTOS_PARA,
        "p1": PREFIXOS_BOTAO_LP[0], "p2": PREFIXOS_BOTAO_LP[1]})).all()]
    vendidos_no_vao = sum(1 for v in vao if (v.get("etapa") or "") == "Vendidos")

    return envelope("atritos", p, [
        metrica("conversas_cortadas", "Conversas da Nat cortadas por envio humano",
                cortadas, n=sum(m["n"] for m in motivos if m["tipo"] == "transferido"),
                relogio="SP (transferido_em)", confianca="alta",
                definicao="Conversas em que a Nat estava conduzindo e um envio humano ou de "
                          "campanha entrou na thread, transferindo o lead.",
                limitacao="São CONVERSAS, não vezes. O silenciamento é idempotente e há uma "
                          "linha de estado por contato: segundo e terceiro toque na mesma "
                          "conversa não deixam rastro, então reincidência não é contável."),
        metrica("disparos_pulados", "Disparos pulados pela higiene", None, relogio="—",
                confianca="indisponivel",
                definicao="Quem a régua de higiene tirou do disparo, por qual regra: pediu "
                          "para parar, já recebeu demais, ou está conversando com a Nat.",
                limitacao="O filtro roda e funciona, mas até 02/09/2026 o resultado só "
                          "existia na resposta do disparo e não era gravado. O registro "
                          "começou agora e este card entra quando houver dias suficientes "
                          "para dizer alguma coisa.",
                cobertura={"desde": "2026-09-02"}),
        metrica("vao_espontaneo", "Escreveram no WhatsApp e não receberam resposta",
                len(vao), n=None, relogio=_R_SP, confianca="alta",
                definicao="Pessoas que escreveram pelo botão da página de obrigado e não "
                          "receberam nenhuma mensagem nossa depois disso.",
                limitacao="Isto NÃO é lead perdido: parte dessas pessoas foi atendida por "
                          "outro canal — por telefone, pela página, ou com a consultora. "
                          f"Nesta janela, {vendidos_no_vao} dela(s) fechou(aram) matrícula. "
                          "A métrica mede falha de atendimento NESTE canal. " + MOVEL,
                lista=vao, vendidos=vendidos_no_vao),
    ], teste)


@router.get("/jornada")
@tolerante("jornada")
async def jornada(periodo: str = PERIODO_Q, db: AsyncSession = Depends(get_db)):
    """A jornada do lead, da reunião marcada à venda."""
    p, teste, q = await _base(db, periodo)

    linhas = [dict(r._mapping) for r in (await db.execute(text(SQL_JORNADA_COORTE), q)).all()]
    v = (await db.execute(text(SQL_VENDIDOS_RASTREAVEIS), {"funil_vendas": FUNIS_VENDAS[0]})).one()

    ia_n = sum(1 for l in linhas if l["da_ia"])
    atravessou = [l for l in linhas if l["funnel_id"] in FUNIS_VENDAS]
    atr_ia = sum(1 for l in atravessou if l["da_ia"])

    por_consultora: dict[str, dict] = {}
    for l in linhas:
        c = por_consultora.setdefault(l["sales_rep_email"] or "(sem consultora)",
                                      {"agendou": 0, "em_vendas": 0, "vendido": 0})
        c["agendou"] += 1
        if l["funnel_id"] in FUNIS_VENDAS:
            c["em_vendas"] += 1
        if l["stage"] == "Vendidos":
            c["vendido"] += 1

    tabela = [{"lead_id": l["lead_id"], "nome": l["nome"],
               "origem": "ia" if l["da_ia"] else "landing_page",
               "consultora": l["sales_rep_email"], "funil": l["funnel_id"],
               "etapa": l["stage"], "reuniao": l["slot_inicio"].isoformat()
               if l["slot_inicio"] else None,
               "ultima_transicao": l["ultima_transicao"].isoformat()
               if l["ultima_transicao"] else None} for l in linhas]

    return envelope("jornada", p, [
        metrica("agendaram", "Reuniões marcadas",
                {"ia": ia_n, "landing_page": len(linhas) - ia_n}, n=len(linhas),
                relogio=_R_UTC, confianca="alta",
                definicao="Leads com agendamento fechado por nós no período. Sem IP de "
                          "visitante = marcado pela Nat na conversa.",
                por_consultora=por_consultora),
        metrica("chegou_em_vendas", "Atravessaram para um funil de vendas",
                {"ia": atr_ia, "landing_page": len(atravessou) - atr_ia}, n=len(atravessou),
                relogio="UTC (funnel_id, no último sync)", confianca="alta",
                definicao="O funil do lead hoje é um funil de vendas. Conta a TRAVESSIA, "
                          "não a etapa: um lead em Agendados no funil de vendas já "
                          "atravessou.",
                limitacao="A troca de funil não aparece no nosso banco — ela é inferida da "
                          "mudança de funil entre dois syncs. Na Exact ela existe como "
                          "evento, com funil de origem e de destino. Quem executou a troca "
                          "não é registrado em lugar nenhum.",
                lista=[t for t in tabela if t["funil"] in FUNIS_VENDAS]),
        metrica("vendidos_rastreaveis", "Vendas ligadas a uma reunião nossa",
                v.rastreaveis, n=v.vendidos, relogio="UTC (stage, no último sync)",
                confianca="media",
                definicao="Leads vendidos no funil de vendas que têm agendamento nosso.",
                limitacao=(f"Só dá para ligar uma venda à sua origem desde "
                           f"{COBERTURA_AGENDAMENTOS:%d/%m/%Y}, quando o sistema de "
                           f"agendamento começou a gravar. Antes disso, "
                           f"{v.vendidos - v.rastreaveis} vendas sem rastro — não é ausência "
                           f"de venda, é ausência de registro. NÃO calcule percentual sobre "
                           f"{v.vendidos}."),
                cobertura={"desde": COBERTURA_AGENDAMENTOS.isoformat(),
                           "rastreaveis": v.rastreaveis,
                           "sem_rastro": v.vendidos - v.rastreaveis},
                ignora_periodo=True),
        metrica("compareceu", "Compareceu à reunião", None, relogio="—",
                confianca="nao_medivel",
                definicao="Quantas pessoas apareceram na reunião marcada.",
                limitacao="O status da reunião vive só na API da Exact e vira 'Concluído' no "
                          "instante da troca de funil, com data no futuro. Exatamente os "
                          "leads que avançam são os que têm o registro corrompido — medir "
                          "por aí mediria 'avançou de funil'."),
    ], teste, tabela=tabela,
        limiar_taxa={"n_minimo": N_MINIMO_TAXA,
                     "nota": (f"Abaixo de {N_MINIMO_TAXA} por ator a página mostra contagem "
                              "e lista nominal, nunca taxa: uma conversão em cima de nove "
                              "reuniões é ruído com dois dígitos.")})
