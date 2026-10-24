# SPRINT: grade de horários subtrai o Google Agenda das consultoras (livre/ocupado) (24/10/2026)

Item 1 dos quatro pedidos do comercial. Base: `RECON_4_PEDIDOS_COMERCIAL_20261024_REPORT.md` §1.

**Resultado:** **ligado** desde 24/10 às 15:48 SP (`GOOGLE_GRADE_ENABLED=true`, `GOOGLE_GRADE_LOG_ONLY=false`). Antes disso, a comparação em log reproduziu o §1.3 do RECON horário por horário, e o Álefe aprovou ligar no mesmo dia, sem esperar as 24 h de comparação. A grade servida pela LP, pelo agente, pelo no-show e pela remarcação agora tira, de cada consultora, o que o Google dela diz ocupado, com a folga de 15 min em volta.

## 1. O que mudou

| arquivo | mudança |
|---|---|
| `backend/app/agendamento/google_ocupado.py` (novo) | `ocupados_google(ids, inicio, fim)`: uma `freebusy.query` para todos os calendários, com escopo `calendar.readonly`, `asyncio.to_thread`, timeout de 5 s e fuso via `zoneinfo`. Devolve `{id: [(ini, fim)]}` em hora de parede de SP ou `{id: GoogleIndisponivel}`, e nunca levanta. Também tem `habilitado()`, `so_log()` e `ativo()`, lidos do `.env` a cada chamada |
| `backend/app/agendamento/disponibilidade.py` | `slots_livres` soma os blocos do Google aos de antes (Exact, nossos agendamentos e remarcação pendente) antes de aplicar a folga. Se o Google falha para uma consultora, ela sai da rodada. O log `📊 google_grade` diz quais horários saem (`sairiam=` em comparação, `tirados=` com o Google ativo) e só repete quando o resultado muda. `filtrar_pelo_google` atende o `agendar` |
| `backend/app/agendamento/agendar.py` | **Desvio aprovado.** Antes do `BoxesAdd`, as candidatas passam por `filtrar_pelo_google`. Motivo: o `agendar` escolhe a consultora pela carga, não pela grade. Às 13:30 de 27/10 o horário aparecia porque a Rodrigues estava livre, mas a Amorim, ocupada no Google, podia ganhar o box. Se não sobra nenhuma, o visitante recebe o mesmo 409 de "horário preenchido" |
| `backend/app/agendamento/consultoras.py`, `backend/consultoras.json` | campo `google_calendar_id` nas duas consultoras (= o e-mail). Sem o campo, o Google não é consultado para ela e o log avisa |
| `backend/.env` (fora do git) | `GOOGLE_GRADE_ENABLED`, `GOOGLE_GRADE_LOG_ONLY` e o comentário do paliativo atualizado. Cópias: `.env.bak_20261024_google` (antes de tudo) e `.env.bak_20261024_logonly` (modo comparação) |
| `backend/test_google_ocupado.py` (novo) | 11 casos, **escritos e não executados** |

Sem DDL. Expediente provisório `10:00–12:00 + 13:30–19:00` seg–sex, em `consultoras.json`, com o almoço fixo mantido.

## 2. Chave desligada: `/slots` idêntico

`/slots` capturado antes do restart e depois do restart com `GOOGLE_GRADE_ENABLED=false`: `cmp` sem diferença ("IDENTICO byte a byte"). Na hora, a janela tinha só o dia 27/10: `13:30, 14:15, 15:00, 15:45, 16:30`.

## 3. Comparação (LOG_ONLY), 24/10 15:44 SP

O `/slots` servido continuou igual ao antigo (`cmp` sem diferença). Log:
```
🗓️ google_ocupado: freebusy 2 calendário(s) 26/10 09:45–27/10 19:00 em 421 ms
📊 google_grade dia=2026-10-27 consultora=comercial@cenatcursos.com.br sairiam=['13:30']
📊 google_grade dia=2026-10-27 consultora=processoseletivo@cenatcursos.com.br sairiam=['13:30']
```
O 28/10 só entra na janela no domingo. Para conferir o dia agora, rodei a mesma função só em leitura com `AGENDAMENTO_JANELA_DIAS=5`:
```
📊 google_grade dia=2026-10-28 consultora=comercial@...       sairiam=['10:00', '10:45', '13:30', '14:15']
📊 google_grade dia=2026-10-28 consultora=processoseletivo@... sairiam=['10:00', '10:45', '13:30', '18:00']
```

| | sai por colisão no Google | sai pela folga | grade nova | RECON §1.3 |
|---|---|---|---|---|
| Amorim 27/10 | 13:30 | | 16:30 | 16:30, 17:15, 18:00 (*) |
| Rodrigues 27/10 | | 13:30 | 14:15, 15:00, 15:45, 16:30 | igual |
| Amorim 28/10 | 10:00, 13:30, 14:15 | 10:45 | 15:00, 15:45, 16:30, 17:15, 18:00 | igual |
| Rodrigues 28/10 | 10:00, 18:00 | 10:45, 13:30 | 14:15, 15:00, 15:45, 16:30, 17:15 | igual |

São as 6 colisões e os 4 horários que caem pela folga do RECON, um por um. (*) O 17:15 e o 18:00 da Amorim em 27/10 já saíam pela Exact, por causa da reunião de teste 4789469 da sprint da trava, marcada para as 18:00.

## 4. Ligado, 24/10 15:48 SP

```
$ curl -s http://127.0.0.1:8001/api/agendamento/slots
{"dias": {"2026-10-27": [14:15, 15:00, 15:45, 16:30]}, "fallback": false, "duracao_min": 45}
🗓️ google_ocupado: freebusy 2 calendário(s) 26/10 09:45–27/10 19:00 em 317 ms
📊 google_grade dia=2026-10-27 consultora=comercial@cenatcursos.com.br tirados=['13:30']
📊 google_grade dia=2026-10-27 consultora=processoseletivo@cenatcursos.com.br tirados=['13:30']
```
O 13:30, que colidia com o Google da Amorim e caía pela folga na Rodrigues, deixou de ser oferecido.

**Latência da `freebusy.query`:** de 113 a 481 ms nas 4 medições. Ela roda uma vez por chamada não cacheada de `slots_livres`; o cache é de 60 s.

## 5. Primeiras 24 h ligado

**Pendente até 25/10 às 15:48 SP.** O resumo fica nesta seção e sai de duas consultas:

```bash
# horários tirados pelo Google, por dia e consultora (o log só repete quando muda)
sudo journalctl -u cenat-backend --since "2026-10-24 18:48 UTC" --no-pager | grep "📊 google_grade"
# falhas do Google (consultora fora da rodada)
sudo journalctl -u cenat-backend --since "2026-10-24 18:48 UTC" --no-pager | grep -E "❌ google_ocupado|Google de"
```
Para saber se algum agendamento (LP ou agente) caiu dentro de bloco do Google: pegar os `agendamentos` com `passo='agendado'` criados depois de 24/10 15:48 SP, consultar o freebusy dos dias deles e cruzar. Contar com a folga e sem ela; o esperado é zero nos dois casos.

## 6. Para a Isa

- **Bloquear no Google tudo o que não podem atender:** reunião interna, follow, almoço, compromisso pessoal. A grade agora é o expediente menos o que está ocupado no Google. Não existe mais "marcar LIVRE".
- **A cópia manual de bloqueios para a Exact pode parar** depois de uma semana ligado sem colisão. Até lá, não faz mal: a Exact continua sendo subtraída.
- **Confirmar o expediente de cada consultora** (hoje provisório: 10:00–12:00 + 13:30–19:00) e **o almoço da Amorim**, que não está bloqueado no Google em 27 e 28/10. O almoço fixo segue em `consultoras.json` até a resposta. Trocar é só editar esse arquivo, sem código.
- Se o Google de uma consultora ficar ilegível (permissão revogada, por exemplo), ela some da grade até voltar. O log `❌ google_ocupado` mostra quando isso acontece.

## 7. Testes

`backend/test_google_ocupado.py`, escrito e **não executado** (convenção da sprint). Casos:
- bloco 13:30–14:30 tira 13:30 e 14:15, e o log mostra `tirados=`;
- bloco 09:00–10:40 tira 10:00 e 10:45;
- dia inteiro ocupado tira o dia;
- 403 numa consultora tira só ela;
- chave desligada: grade idêntica e Google não consultado;
- `LOG_ONLY` serve a grade antiga e loga `sairiam=`;
- cache: uma consulta em 60 s;
- fuso com `-03:00` e com `Z`;
- `errors` por calendário;
- timeout;
- `filtrar_pelo_google`.

`import app.main` passa.
