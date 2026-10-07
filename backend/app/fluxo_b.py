"""Gates do Fluxo B enxuto (Bloco 3, 07/10/2026). Módulo pequeno de propósito.

`FLUXO_B_ENXUTO` liga o caminho novo do agente (uma pergunta, oferta hoje+amanhã, reativações
30m/2h/4h/D+1 e remarcação pelos botões). `FLUXO_B_SOMENTE_TELEFONES` é a allowlist pela chave
tolerante do telefone; vazia = todos. Os dois lidos a cada chamada, sem cache, mesmo padrão de
`confirmacao.flag_ligada` e `noshow.flag_ligada`.

Com a flag desligada o agente de 4 perguntas segue byte a byte o que era, e os cliques de
remarcar dos Blocos 1 e 2 continuam com a resposta fixa.

O estado que nasce no caminho novo leva `dados_extras["fluxo"] = "b"` (`MARCA`). É a marca, e
não a flag, que decide a missão e o avanço daquela conversa: desligar a flag no meio de uma
conversa não pode trocar o roteiro de quem já está nela. As reativações, essas sim, olham a
flag na hora de sair (desligar = parar de mandar).
"""
import os

from app.telefone import chave_telefone

CHAVE_FLUXO = "fluxo"
MARCA = "b"


def flag_ligada() -> bool:
    """`FLUXO_B_ENXUTO`, sem cache. `true`/`1`/`sim`/`yes`; o resto é DESLIGADO."""
    return (os.getenv("FLUXO_B_ENXUTO", "") or "").strip().lower() in (
        "true", "1", "sim", "yes")


def allowlist() -> frozenset[str]:
    """`FLUXO_B_SOMENTE_TELEFONES` como chaves tolerantes. Vazia = todos entram."""
    cru = os.getenv("FLUXO_B_SOMENTE_TELEFONES", "") or ""
    return frozenset(c for c in (chave_telefone(p) for p in cru.split(",")) if c)


def telefone_permitido(telefone: str | None) -> bool:
    lista = allowlist()
    return not lista or chave_telefone(telefone) in lista


def ativo_para(telefone: str | None) -> bool:
    """Flag ligada E telefone na allowlist. É a pergunta que todo ponto de entrada faz."""
    return flag_ligada() and telefone_permitido(telefone)


def e_fluxo_b(estado) -> bool:
    """O estado nasceu (ou renasceu) no caminho novo?"""
    return (getattr(estado, "dados_extras", None) or {}).get(CHAVE_FLUXO) == MARCA


def marcar(estado) -> None:
    extras = dict(estado.dados_extras or {})
    extras[CHAVE_FLUXO] = MARCA
    estado.dados_extras = extras
