# Agenda: folga de 30 min entre ocupações e almoço fixo 12:00–13:30 (14/10/2026)

Pedido da Isa (13/10): reuniões caindo coladas em almoço, follow e outras reuniões. Ela quer 30 min de folga.

## O que mudou

1. **Folga** (`app/agendamento/disponibilidade.py`). Em `slots_livres`, toda ocupação (box da Exact **ou** agendamento nosso) bloqueia `[inicio - folga, fim + folga]`. A folga vem de `AGENDAMENTO_FOLGA_MIN`, com padrão 30 (valor inválido ou negativo também cai em 30). `_sobrepoe` continua meio-aberto: um slot que termina exatamente onde a folga começa ainda é oferecido.
2. **Almoço** (`backend/consultoras.json`). As duas consultoras passam a ter `[["10:00","12:00"],["13:30","19:00"]]` de segunda a sexta. `Grade.slots_do_dia` já percorria várias faixas por dia, e não precisou mexer.
3. **Só a oferta muda.** Reunião já marcada continua onde está. O `BoxesAdd` não sabe da folga e aceitaria um box colado. A folga vale porque a gente não oferece o horário.

Com passo de 45 min, a grade nova por dia útil fica assim: `10:00 10:45 | 13:30 14:15 15:00 15:45 16:30 17:15 18:00`. São 9 horários; antes eram 12. A faixa 11:30–12:00 não vira slot, porque 11:30–12:15 passaria do 12:00.

## Antes × depois (medido em 14/10 contra a Exact real, antes do deploy)

Slots livres por consultora. "Antes" = janela 10–19 sem folga. "Depois" = janela com almoço e folga de 30.

| Consultora | Dia | Antes | Só janela nova | Depois |
|---|---|---|---|---|
| Amorim | qui 15/10 | 10 | 7 | **5** |
| Amorim | sex 16/10 | 11 | 8 | **7** |
| Rodrigues | qui 15/10 | 11 | 7 | **6** |
| Rodrigues | sex 16/10 | 11 | 8 | **7** |
| **Total** | | **43** | **30** | **25** |

Ocupações nesses dias: só reuniões, sem bloco de almoço ou de follow na Exact.
- Amorim 15/10: 10:00, 18:15. Amorim 16/10: 18:15.
- Rodrigues 15/10: 16:45. Rodrigues 16/10: 10:00.

O almoço tira 13 dos 18 horários que somem e a folga tira 5. Cada reunião marcada passa a custar até 3 horários da consultora: o dela e um vizinho de cada lado.

## Pontos de atenção

- **Bloco de almoço na Exact + folga.** Se uma consultora criar um bloco 12:00–13:30 na agenda, a folga derruba o 13:30, e a tarde dela passa a começar às 14:15. Hoje nenhuma das duas tem esse bloco.
- **Teste escrito, não rodado:** `backend/test_folga_agenda.py`, além do caso 4 de `test_agendamento.py`, que agora testa o "encostar" com folga 0 e com folga 30.
