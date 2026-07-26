"""Travas da NAT (nat_guard) + captura de clique de botão (nat_buttons).

Rodar: cd backend && venv/bin/python test_nat_guard.py

NADA REAL ACONTECE: o banco é falso (MagicMock, nenhuma conexão aberta, nenhuma linha
gravada), nenhuma mensagem é enviada, nenhum template é chamado. Os casos 8 e 9 são REPLAY
de payload sintético do webhook — que é a única validação possível hoje, já que nada está
sendo entregue desde 23/07 e não há clique real chegando para esperar.

O que estes testes provam:

  Travas (nat_guard.nat_pode_atuar) — todas FALHAM FECHADAS:
   1. nat_enabled=false, todo o resto correto        -> BLOQUEIA (kill switch manda)
   2. register_date anterior ao nat_start_at         -> BLOQUEIA (corte por data)
   3. register_date IS NULL                          -> BLOQUEIA (ausência não libera)
   4. funil 18537 e 25588                            -> BLOQUEIA (só 18535 é alvo)
   5. assigned_to fora de (4,5) ou nulo              -> BLOQUEIA (id literal, não role)
   6. teto de envios/hora estourado                  -> BLOQUEIA
   7. lead válido, tudo ligado                       -> LIBERA

  Captura de clique (nat_buttons.extrair_evento_botao):
   8. replay type="button" (quick reply de template) -> payload, texto e context extraídos
   9. replay type="interactive" (button_reply)       -> idem, com source correto

O caso 7 é o que dá sentido aos outros seis: sem ele, uma função que retornasse False sempre
passaria em 1-6 e a NAT nunca atuaria depois de ligada.
"""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.models import NatConfig, ExactLead
from app.nat_buttons import extrair_evento_botao, conteudo_legivel
from app.nat_guard import nat_pode_atuar, FUNIL_NAT, SDR_IDS_PERMITIDOS

CORTE = datetime(2026, 7, 25, 0, 0, 0)
DEPOIS_DO_CORTE = datetime(2026, 7, 26, 10, 0, 0)
ANTES_DO_CORTE = datetime(2026, 7, 20, 10, 0, 0)


def _cfg(enabled=True, start_at=CORTE, teto=20):
    return NatConfig(id=1, nat_enabled=enabled, nat_start_at=start_at, max_envios_hora=teto)


def _lead(funnel_id=FUNIL_NAT, register_date=DEPOIS_DO_CORTE):
    """ExactLead em memória. phone1 vira wa_id 5583999998888 via format_phone."""
    lead = ExactLead(exact_id=999, name="Fulano", phone1="5583999998888",
                     funnel_id=funnel_id)
    lead.register_date = register_date
    return lead


def _res_scalar(valor):
    """Resultado falso para db.execute().scalar_one_or_none() — leitura do nat_config."""
    m = MagicMock()
    m.scalar_one_or_none.return_value = valor
    return m


def _res_first(valor):
    """Resultado falso para db.execute().first() — leitura de Contact.assigned_to."""
    m = MagicMock()
    m.first.return_value = valor
    return m


def _db(config, contato_row=(4,)):
    """Banco FALSO. Nenhuma conexão é aberta.

    Devolve, em ordem: o nat_config (scalar_one_or_none) e depois a linha do Contact
    (first). Se a trava bloquear antes, a segunda simplesmente não é consumida — o que
    por si só já prova que a verificação parou onde devia.
    """
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_res_scalar(config), _res_first(contato_row)])
    return db


# Contador injetado: em produção é contar_envios_nat_ultima_hora. Aqui nunca toca o banco.
def _contador(n):
    return AsyncMock(return_value=n)


async def caso_1_kill_switch():
    """O mais importante: com nat_enabled=false, NADA mais importa."""
    db = _db(_cfg(enabled=False))
    pode, motivo = await nat_pode_atuar(_lead(), db, contar_envios=_contador(0))
    assert pode is False, "FALHOU: NAT atuou com o kill switch DESLIGADO!"
    assert "nat_enabled" in motivo, motivo
    print(f"  1. nat_enabled=false (tudo o mais ok) -> BLOQUEADO  {motivo}")


async def caso_2_register_date_antes_do_corte():
    db = _db(_cfg())
    pode, motivo = await nat_pode_atuar(_lead(register_date=ANTES_DO_CORTE), db,
                                        contar_envios=_contador(0))
    assert pode is False, "FALHOU: atuou sobre lead anterior ao corte de data!"
    assert "anterior ao corte" in motivo, motivo
    print(f"  2. register_date < nat_start_at       -> BLOQUEADO  {motivo}")


async def caso_3_register_date_nulo():
    """Ausência de dado não libera: a trava falha fechada."""
    db = _db(_cfg())
    pode, motivo = await nat_pode_atuar(_lead(register_date=None), db,
                                        contar_envios=_contador(0))
    assert pode is False, "FALHOU: register_date NULL passou pela trava de data!"
    assert "register_date ausente" in motivo, motivo
    print(f"  3. register_date IS NULL              -> BLOQUEADO  {motivo}")

    # E o outro eixo: nat_start_at NULL (como está em produção agora) também bloqueia,
    # mesmo com o nat_enabled ligado. A NAT nasce desligada em DOIS eixos.
    db = _db(_cfg(start_at=None))
    pode, motivo = await nat_pode_atuar(_lead(), db, contar_envios=_contador(0))
    assert pode is False, "FALHOU: atuou sem corte de data definido!"
    assert "nat_start_at" in motivo, motivo
    print(f"     nat_start_at IS NULL (2o eixo)     -> BLOQUEADO  {motivo}")


async def caso_4_funil_fora_do_alvo():
    for funil in (18537, 25588):
        db = _db(_cfg())
        pode, motivo = await nat_pode_atuar(_lead(funnel_id=funil), db,
                                            contar_envios=_contador(0))
        assert pode is False, f"FALHOU: atuou no funil {funil}, fora do alvo!"
        assert "fora do alvo" in motivo, motivo
        print(f"  4. funil {funil} (auto_welcome cobre)   -> BLOQUEADO  {motivo}")


async def caso_5_sdr_nao_permitido():
    """assigned_to é verificado por id literal — Valéria(4), Thobias(5). Isa(2) é gestora
    e os três estão como 'admin' no banco, então `role` não distinguiria."""
    db = _db(_cfg(), contato_row=(2,))                 # Isa, gestora
    pode, motivo = await nat_pode_atuar(_lead(), db, contar_envios=_contador(0))
    assert pode is False, "FALHOU: atuou em lead de quem nao e SDR alvo!"
    assert "assigned_to=2" in motivo, motivo
    print(f"  5. assigned_to=2 (gestora, nao SDR)   -> BLOQUEADO  {motivo}")

    db = _db(_cfg(), contato_row=(None,))              # contato sem dono
    pode, motivo = await nat_pode_atuar(_lead(), db, contar_envios=_contador(0))
    assert pode is False, "FALHOU: atuou em contato sem dono!"
    print(f"     assigned_to IS NULL                -> BLOQUEADO  {motivo}")

    db = _db(_cfg(), contato_row=None)                 # contato nem existe
    pode, motivo = await nat_pode_atuar(_lead(), db, contar_envios=_contador(0))
    assert pode is False, "FALHOU: atuou em contato inexistente!"
    assert "não existe" in motivo, motivo
    print(f"     contato inexistente no banco       -> BLOQUEADO  {motivo}")


async def caso_6_teto_estourado():
    db = _db(_cfg(teto=20))
    pode, motivo = await nat_pode_atuar(_lead(), db, contar_envios=_contador(20))
    assert pode is False, "FALHOU: estourou o teto de envios/hora!"
    assert "teto de envios/hora" in motivo, motivo
    print(f"  6. teto estourado (20/20)             -> BLOQUEADO  {motivo}")


async def caso_7_lead_valido_libera():
    """Sem este caso, uma funcao que so retorna False passaria em 1-6."""
    db = _db(_cfg(), contato_row=(5,))                 # Thobias
    pode, motivo = await nat_pode_atuar(_lead(), db, contar_envios=_contador(3))
    assert pode is True, f"FALHOU: bloqueou lead valido! motivo={motivo}"
    assert motivo == "ok", motivo
    print(f"  7. lead valido, tudo ligado           -> LIBERADO   funil={FUNIL_NAT} "
          f"SDR=5 {sorted(SDR_IDS_PERMITIDOS)}")


async def caso_8_replay_botao_de_template():
    """Payload real de quick reply de TEMPLATE — o formato que os 6 nat_* produzem."""
    msg = {
        "from": "5583999998888",
        "id": "wamid.CLIQUE",
        "timestamp": "1769385600",
        "type": "button",
        "button": {"payload": "Prefiro outro horário", "text": "Prefiro outro horário"},
        "context": {"id": "wamid.ORIGINAL_BOASVINDAS"},
    }
    ev = extrair_evento_botao(msg, msg["id"])
    assert ev is not None, "FALHOU: clique de template foi descartado (o bug original)!"
    assert ev["source"] == "template", ev
    assert ev["button_payload"] == "Prefiro outro horário", ev
    assert ev["button_text"] == "Prefiro outro horário", ev
    assert ev["context_message_id"] == "wamid.ORIGINAL_BOASVINDAS", \
        "FALHOU: context.id perdido — sem ele nat_boasvindas e nat_reativacao_09h ficam indistinguiveis!"
    assert ev["contact_wa_id"] == "5583999998888", ev
    assert ev["wa_message_id"] == "wamid.CLIQUE", ev
    conteudo = conteudo_legivel(ev)
    assert conteudo == "botao:Prefiro outro horário", conteudo
    assert conteudo != "", "FALHOU: content vazio -> notificacao do SDR sairia sem corpo!"
    print(f'  8. replay type="button"               -> source={ev["source"]} '
          f'payload={ev["button_payload"]!r} context={ev["context_message_id"]!r}')
    print(f'     Message.content                    -> {conteudo!r} (antes era "")')


async def caso_9_replay_botao_interativo():
    """Botão de mensagem livre. Ainda não ocorre; será usado no Bloco 3."""
    msg = {
        "from": "5583999997777",
        "id": "wamid.CLIQUE_INT",
        "timestamp": "1769385600",
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "button_reply": {"id": "nat_confirma_sim", "title": "Sim, pode ligar"},
        },
        "context": {"id": "wamid.ORIGINAL_LIVRE"},
    }
    ev = extrair_evento_botao(msg, msg["id"])
    assert ev is not None, "FALHOU: clique interativo descartado!"
    assert ev["source"] == "interactive", ev
    assert ev["button_payload"] == "nat_confirma_sim", ev
    assert ev["button_text"] == "Sim, pode ligar", ev
    assert ev["context_message_id"] == "wamid.ORIGINAL_LIVRE", ev
    print(f'  9. replay type="interactive"          -> source={ev["source"]} '
          f'payload={ev["button_payload"]!r} context={ev["context_message_id"]!r}')

    # Mensagem comum continua passando reto: a captura é ADITIVA, não intercepta texto.
    texto = {"from": "5583999997777", "id": "wamid.TXT", "type": "text",
             "text": {"body": "oi"}}
    assert extrair_evento_botao(texto, "wamid.TXT") is None, \
        "FALHOU: mensagem de texto virou evento de botao!"
    # list_reply não é clique de botão — fora de escopo, não pode virar evento.
    lista = {"from": "5583999997777", "id": "wamid.LST", "type": "interactive",
             "interactive": {"type": "list_reply", "list_reply": {"id": "x", "title": "y"}}}
    assert extrair_evento_botao(lista, "wamid.LST") is None, \
        "FALHOU: list_reply virou evento de botao!"
    print("     texto comum e list_reply           -> ignorados (captura e aditiva)")


async def main():
    print("\nTravas da NAT + captura de clique (banco falso, nenhum envio, nada gravado)\n")
    await caso_1_kill_switch()
    await caso_2_register_date_antes_do_corte()
    await caso_3_register_date_nulo()
    await caso_4_funil_fora_do_alvo()
    await caso_5_sdr_nao_permitido()
    await caso_6_teto_estourado()
    await caso_7_lead_valido_libera()
    print()
    await caso_8_replay_botao_de_template()
    await caso_9_replay_botao_interativo()
    print("\nOK: 9/9 passaram. Todas as travas falham fechadas; os dois formatos de clique "
          "sao capturados com context_message_id preservado.\n")


if __name__ == "__main__":
    asyncio.run(main())
