"""Reconciliação dos `welcome_status='sent'` que na verdade falharam — Fase 3 da sprint.

    cd backend && venv/bin/python fix_welcome_status_falso.py            # dry-run (padrão)
    cd backend && venv/bin/python fix_welcome_status_falso.py --apply    # grava

------------------------------------------------------------------------------------------
O QUE ISTO CORRIGE
------------------------------------------------------------------------------------------
`send_welcome_to_new_lead` carimba 'sent' quando a Meta ACEITA a mensagem. Os `failed` que
chegaram depois pelo webhook de status nunca realimentaram `exact_leads` — a Fase 2 conserta
isso daqui para a frente, mas não alcança o passado: os leads carimbados antes da coluna
`welcome_wamid` existir não têm vínculo nenhum com a mensagem.

Este script reconstrói esse vínculo para o passado e só para ele.

------------------------------------------------------------------------------------------
POR QUE O PAREAMENTO É CONSERVADOR
------------------------------------------------------------------------------------------
Um lead pode ter recebido VÁRIAS templates (boas-vindas + campanha de follow-up): são 499
mensagens template para 254 leads 'sent'. Casar por telefone sem mais nada pegaria a mensagem
errada e carimbaria 'failed' num lead que na verdade recebeu.

A regra é: na dúvida, não mexe. Subestimar a correção é muito melhor do que carimbar 'failed'
em lead entregue — o primeiro erro deixa um lead a menos na lista, o segundo apaga uma entrega
real e alimenta a mesma desconfiança no dado que esta sprint existe para curar.

JANELA (--janela, padrão 10s): a Message e o carimbo do lead são gravados na MESMA transação
do envio, um logo após o outro. Medido nos 254 leads reais: o maior delta é de 33 MILISSEGUNDOS
e a janela de 1s já pareia 254 de 254 sem nenhuma ambiguidade. O padrão de 10s dá ~300x de
folga sobre o pior caso observado e ainda assim rende 0 ambíguos; ±2min renderia 1 ambíguo sem
parear nada a mais. A janela não é um chute: é o tempo de uma transação, não o de uma campanha.

NÃO importa app.whatsapp (nem app.exact_spotter, que o importa no nível de módulo, linha 7).
`format_phone` está reimplementada abaixo, idêntica ao original — um script de correção de
dados não pode ter no import um cliente HTTP capaz de enviar mensagem.

NÃO envia mensagem, NÃO altera auto_welcome_config nem nat_config, NÃO mexe em lead que não
esteja com welcome_status='sent'.
"""
import argparse
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select, and_

from app.database import async_session, engine
from app.models import ExactLead, Message

# `database.py` cria o engine com echo=True (global, e não vou mexer nisso por causa de um
# script). Sem isto, as ~500 queries do pareamento afogam o relatório em 200KB de SQL e o
# resultado — a única coisa que importa aqui — vira agulha em palheiro.
# Tem que ser `engine.echo`, não o nível do logger: com echo=True o SQLAlchemy usa um
# InstanceLogger que emite sem consultar o nível, então setLevel() não tem efeito nenhum.
# Afeta só este processo; o engine do servidor continua como está.
engine.echo = False


def format_phone(phone: str) -> str:
    """Cópia literal de exact_spotter.format_phone (linha 117).

    Duplicada de propósito: importar o original arrastaria app.whatsapp junto. Se o original
    mudar, esta precisa mudar — o pareamento tem que usar exatamente a mesma normalização que
    o envio usou para escrever `messages.contact_wa_id`, senão não casa nada.
    """
    if not phone:
        return ""
    digits = "".join(c for c in phone if c.isdigit())
    if not digits.startswith("55"):
        digits = "55" + digits
    return digits


# Quase toda falha histórica não tem motivo: a persistência de statuses[].errors[] entrou na
# Sprint 3, e só 1 das 2.313 templates falhadas tem error_code. Dizer "motivo não capturado" é
# a resposta honesta; inventar um código seria repetir, ao contrário, o erro que causou a sprint.
SEM_MOTIVO = ("recusada pela Meta — motivo não capturado "
              "(falha anterior à persistência de erro no webhook)")

CORRIGIDO, JA_CORRETO, AMBIGUO, SEM_MENSAGEM = "corrigidos", "ja_corretos", "ambiguos", "sem_mensagem"


def _erro_da_mensagem(msg: Message) -> str:
    partes = [str(msg.error_code) if msg.error_code is not None else None,
              msg.error_details or msg.error_title]
    return " — ".join(p for p in partes if p) or SEM_MOTIVO


async def _mensagem_do_lead(lead: ExactLead, janela: int, db):
    """Devolve (categoria, mensagem|None, candidatas).

    Dois caminhos, nesta ordem de confiança:
      1. welcome_wamid — vínculo exato, escrito pelo próprio envio. Não existe ambiguidade.
      2. telefone + janela em torno de welcome_sent_at — reconstrução, e o único caminho
         possível para os leads anteriores à coluna.
    """
    if lead.welcome_wamid:
        msg = (await db.execute(select(Message).where(
            Message.wa_message_id == lead.welcome_wamid))).scalar_one_or_none()
        return (SEM_MENSAGEM, None, []) if msg is None else (None, msg, [msg])

    # Sem wamid E sem horário não há janela para construir — nada a fazer, e adivinhar por
    # telefone sozinho é exatamente o que a regra proíbe.
    if not lead.welcome_sent_at or not lead.phone1:
        return (SEM_MENSAGEM, None, [])

    phone = format_phone(lead.phone1)
    if not phone:
        return (SEM_MENSAGEM, None, [])

    delta = timedelta(seconds=janela)
    candidatas = (await db.execute(select(Message).where(and_(
        Message.contact_wa_id == phone,
        Message.message_type == "template",
        Message.direction == "outbound",
        Message.timestamp >= lead.welcome_sent_at - delta,
        Message.timestamp <= lead.welcome_sent_at + delta,
    )))).scalars().all()

    if not candidatas:
        return (SEM_MENSAGEM, None, [])
    if len(candidatas) > 1:
        # NÃO desempata por proximidade: se duas templates saíram para o mesmo número dentro
        # da janela, qualquer critério de escolha seria um palpite com cara de precisão.
        return (AMBIGUO, None, candidatas)
    return (None, candidatas[0], candidatas)


async def main(aplicar: bool, janela: int, amostra: int):
    contagem = {CORRIGIDO: 0, JA_CORRETO: 0, AMBIGUO: 0, SEM_MENSAGEM: 0}
    exemplos = {k: [] for k in contagem}

    async with async_session() as db:
        leads = (await db.execute(
            select(ExactLead).where(ExactLead.welcome_status == "sent")
                             .order_by(ExactLead.welcome_sent_at.desc())
        )).scalars().all()

        print(f"Leads com welcome_status='sent': {len(leads)}")
        print(f"Janela de pareamento: ±{janela}s | modo: "
              f"{'APLICAR (grava)' if aplicar else 'DRY-RUN (não grava)'}\n")

        for lead in leads:
            categoria, msg, candidatas = await _mensagem_do_lead(lead, janela, db)

            if categoria is None:
                if msg.status == "failed":
                    categoria = CORRIGIDO
                    erro = _erro_da_mensagem(msg)
                    if aplicar:
                        lead.welcome_status = "failed"
                        lead.welcome_error = erro
                else:
                    categoria = JA_CORRETO

            contagem[categoria] += 1
            if len(exemplos[categoria]) < amostra:
                exemplos[categoria].append({
                    "exact_id": lead.exact_id,
                    "nome": (lead.name or "")[:28],
                    "enviado_em": str(lead.welcome_sent_at),
                    "status_msg": msg.status if msg else f"{len(candidatas)} candidatas",
                    "erro": (_erro_da_mensagem(msg)[:70]
                             if (msg and msg.status == "failed") else ""),
                })

        if aplicar:
            await db.commit()

    rotulos = {
        CORRIGIDO:    "CORRIGIDOS   ('sent' -> 'failed', a mensagem falhou)",
        JA_CORRETO:   "JÁ CORRETOS  (mensagem entregue/lida/a caminho — 'sent' não mente)",
        AMBIGUO:      "AMBÍGUOS     (>1 template na janela — NÃO tocados, de propósito)",
        SEM_MENSAGEM: "SEM MENSAGEM (nenhuma template casou — NÃO tocados)",
    }
    print("=" * 90)
    for chave in (CORRIGIDO, JA_CORRETO, AMBIGUO, SEM_MENSAGEM):
        print(f"{rotulos[chave]:<62} {contagem[chave]:>5}")
    print("=" * 90)
    print(f"{'TOTAL':<62} {sum(contagem.values()):>5}\n")

    for chave in (CORRIGIDO, AMBIGUO, SEM_MENSAGEM):
        if not exemplos[chave]:
            continue
        print(f"--- amostra: {rotulos[chave]} ---")
        for e in exemplos[chave]:
            print(f"  exact_id={e['exact_id']:<8} {e['nome']:<30} {e['enviado_em']:<28} "
                  f"{e['status_msg']:<16} {e['erro']}")
        print()

    if aplicar:
        print(f"APLICADO: {contagem[CORRIGIDO]} leads passaram de 'sent' para 'failed'.")
        print("Rodar de novo é seguro: o script só olha welcome_status='sent', e estes já não estão.")
    else:
        print("DRY-RUN — nada gravado. Use --apply para gravar.")
    print("Nenhuma mensagem enviada. auto_welcome_config e nat_config intactas.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Corrige welcome_status='sent' que na verdade falhou.")
    p.add_argument("--apply", action="store_true",
                   help="grava as correções. Sem esta flag o script é dry-run.")
    p.add_argument("--janela", type=int, default=10,
                   help="janela em segundos em torno de welcome_sent_at (padrão: 10)")
    p.add_argument("--amostra", type=int, default=10, help="itens por categoria no relatório")
    a = p.parse_args()
    asyncio.run(main(a.apply, a.janela, a.amostra))
