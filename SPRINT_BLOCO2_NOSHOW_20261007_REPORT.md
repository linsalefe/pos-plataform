# SPRINT Bloco 2: régua de no-show D0 a D8, 07/10/2026

Branch `feat/noshow`, a partir da `main` em `2bf40ba`. Base: spec da Isa (`Otimização IA - No
show (validar).pdf`, "Régua de no-show" e "Regras de parada", págs. 8 a 10), RECON §3, §4, §6.1,
§9 e o Bloco 1 (`confirmacao.py`).

**Estado em produção (07/10 ~08:30 SP):** `NOSHOW_ENABLED=true` com
`NOSHOW_SOMENTE_TELEFONES=83988046720`. Só um corte do Álefe arma a régua; ninguém mais é
afetado. Abrir para todos depende de aprovação explícita, depois do teste dele e com o
`conteudos_noshow.json` preenchido pela Isa.

## 1. Templates (Parte A)

8 templates, e não 7: a decisão 5 lista 8 degraus (o D0 do corte, `nat_ns_d0_corte`, já existia).
Todos submetidos em 07/10 com `allow_category_change=True`, **todos APPROVED** na mesma manhã,
categoria pedida = devolvida = MARKETING:

| template | id na Meta | botões |
|---|---|---|
| `nat_ns_d0_1h` | 2192624884650388 | Posso falar agora · Escolher horário |
| `nat_ns_d0_8h` | 1849583856220573 | Posso falar agora · Escolher horário |
| `nat_ns_d1` | 1115710774284226 | Escolher horário |
| `nat_ns_d2_audio` | 1936886920659410 | Reagendar · Posso falar agora · URL "Ouvir o áudio" |
| `nat_ns_d3_seminario` | 2099722863982154 | Quero participar |
| `nat_ns_d5_conteudo` | 1095929953224687 | URL "Ver conteúdo" |
| `nat_ns_d7_condicao` | 1052898764449222 | Reagendar |
| `nat_ns_d8_encerramento` | 2620642091731109 | Falar agora · Reagendar |

Corpos submetidos (fonte única: `nat_copy.CORPO_SUBMETIDO_NOSHOW`):

- **D0+1h:** Oi, {{1}}! Seu horário foi liberado, mas ainda dá tempo de conversar com a consultora. Como a agenda está apertada e restam poucas vagas, quer remarcar?
- **D0+8h:** Oi, {{1}}! Sua aplicação no processo seletivo da Pós em {{2}} ainda está em aberto, e logo ela se encerra. Quer que a consultora te ligue agora ou prefere escolher um novo horário?
- **D1:** Bom dia, {{1}}! Separei alguns horários para sua conversa com a consultora sobre a Pós em {{2}}: {{3}}. São só 15 minutos, e participando você garante a isenção da matrícula. Qual fica melhor para você?
- **D2:** Oi, {{1}}! O coordenador da Pós em {{2}} gravou um recado para você 👇 É só tocar no botão abaixo para ouvir.
- **D3:** Oi, {{1}}! Quero te fazer um convite especial: no dia {{2}}, às {{3}}, vamos ter o seminário gratuito {{4}}. Tenho uma vaga garantida para você, é só responder QUERO aqui que eu confirmo sua participação!
- **D5:** Oi, {{1}}! Separei um conteúdo que tem tudo a ver com a área da Pós em {{2}}: {{3}}. Acho que você vai gostar!
- **D7:** Oi, {{1}}! Esta semana temos uma condição especial para a turma da Pós em {{2}}: {{3}}. As vagas estão acabando e essa condição vale só até {{4}}. Quer que eu reserve um horário com a consultora para você garantir?
- **D8:** Oi, {{1}}! Como não tive seu retorno, vou encerrar por aqui seu agendamento no processo seletivo da Pós em {{2}}. Se quiser retomar, é só me chamar.

### Ajustes de texto em relação ao PDF (para levar à Isa)

| degrau | PDF | submetido | por quê |
|---|---|---|---|
| **D0+1h** | "Você acabou não participando da reunião do processo seletivo." | "Oi, {{1}}! Seu horário foi liberado, mas ainda dá tempo de conversar com a consultora." | **O gatilho é o CORTE, não a falta.** O corte é antes da reunião (manhã: 9h; tarde: 4h antes), então o D0+1h sai na hora da reunião ou até 3h ANTES dela. O texto da Isa diria a quem ainda não teve a reunião que ela faltou. Texto escolhido pelo Álefe. |
| todos menos D1 | "[nome], …" | "Oi, {{1}}! …" | corpo não pode começar com variável |
| D1 | "Separei alguns horários **de hoje** …" + horários depois do corpo | horários no meio ("…sobre a Pós em {{2}}: {{3}}.") e sem "de hoje" | variável no fim é recusada; e a linha pode trazer amanhã ou os 2 próximos dias úteis (fallback decidido em 07/10) |
| D2 | só a frase do 👇 | + "É só tocar no botão abaixo para ouvir." | 12 palavras para 2 variáveis é o perfil recusado por proporção. O 👇 foi aceito pela Meta |
| D5 | "… gostar! [link]" | link em botão URL "Ver conteúdo" | decisão 5 |
| D8 | "… Pós em [pós]." | + "Se quiser retomar, é só me chamar." | variável no fim é recusada (pontuação não conta: recusa do `nat_a_ementa`, 07/10) |

## 2. Critérios de aceite

| # | critério | estado | evidência |
|---|---|---|---|
| 1 | script com dry-run, checkpoint antes do `--apply`, status gravado | ✅ | `submit_templates_noshow.py`; 8 linhas em `whatsapp_templates` |
| 2 | `NOSHOW_ENABLED=false` = nada muda; o corte segue mandando o D0 e avisando | ✅ | `noshow.armar` devolve 0; inbound só delega com a flag; deploy desligado com ciclo do sync limpo |
| 3 | corte do Álefe arma 8 ações `pendente` | ⏳ | código pronto; **aguardando o teste** (seção 4) |
| 4 | clique/texto encerra com motivo, nota, notificação, e nada mais da régua | ✅ código | `noshow.inbound` + `encerrar` (cancela os pendentes da reunião) |
| 5 | follow por estágio não envia com a régua viva; arrasto do SDR encerra | ✅ código | `follow_estagio._enviar_uma` (fica pendente); `exact_spotter` → `noshow.encerrar_por_arrasto` |
| 6 | janela 8h–20h30 em todos os degraus; D0+8h às 22h sai 8h, antes do D1 | ✅ | `noshow._espinha`; seção 3 |
| 7 | conteúdo mensal de `conteudos_noshow.json`; vazio = skipped e segue | ✅ | `conteudos()` relido a cada envio; `AcaoIgnorada("conteúdo do mês não cadastrado: …")` |
| 8 | testes escritos, não executados; import passa | ✅ | `backend/test_noshow.py` (só `py_compile`); `import app.main, app.noshow` ok |

## 3. Relógio

| degrau | corte ter 13/10 às 9h | corte sex 16/10 às 15h | corte qua 14/10 às 14h15 |
|---|---|---|---|
| D0+1h | ter 10:00 | sex 16:00 | qua 15:15 |
| D0+8h | ter 17:00 | 23:00 → sáb 08:00 | 22:15 → qui 08:00 |
| D1 (9h) | qua 09:00 | sáb 09:00 | qui 09:00 |
| D2 (10h) | qui 10:00 | dom 10:00 | sex 10:00 |
| D3 | sex 10:00 | seg 10:00 | sáb 10:00 |
| D5 | dom 10:00 | qua 10:00 | seg 10:00 |
| D7 | ter 20/10 10:00 | sex 23/10 10:00 | qua 21/10 10:00 |
| D8 | qua 21/10 10:00 | sáb 24/10 10:00 | qui 22/10 10:00 |

Corte de sexta: D0+8h e D1 com 1h de diferença no sábado, e o D1 oferece horários de segunda
(a grade não tem fim de semana; fallback dos 2 próximos dias úteis).

## 4. Teste do Álefe

**Pendente.** Roteiro: agendar pela LP para amanhã de manhã e NÃO confirmar. O corte das 9h manda
o D0 e arma a régua:

```sql
SELECT kind, status, run_at, left(motivo,60) FROM nat_scheduled_actions
 WHERE contact_wa_id LIKE '%88046720' AND kind LIKE 'noshow%' ORDER BY run_at;
SELECT meeting_id, noshow_em, regua_encerrada_em, regua_encerrada_motivo
  FROM reuniao_status WHERE telefone_chave = '8388046720' ORDER BY registrado_em DESC LIMIT 3;
```

Ver D0+1h e D0+8h chegarem e testar um clique (deve encerrar a régua com o payload como motivo).

## 5. `conteudos_noshow.json`: o que a Isa precisa preencher antes de abrir para todos

| bloco | estado | sem ele |
|---|---|---|
| `audio_por_curso` (D2) | **preenchido, 16 cursos** (Follow 4 do `follow_estagios.json` × botões dos `f4_audio*`) | curso fora da lista: D2 pulado |
| `seminario` (D3): nome, data, hora, valido_ate | **vazio** | D3 pulado |
| `conteudo_por_curso` (D5): titulo, drive_id por curso | **vazio** | D5 pulado |
| `condicao` (D7): texto, valido_ate | **vazio** | D7 pulado |

`valido_ate` em AAAA-MM-DD; vencido = pulado. Relido a cada envio (sem restart).

## 6. Contador de envios da régua (acompanhamento do número)

Por lead: corte + 8 degraus = até 9 templates MARKETING em 8 dias (aceito, decisão 21/09).
Consulta diária:

```sql
SELECT date(processed_at) dia, kind, status, count(*) FROM nat_scheduled_actions
 WHERE kind LIKE 'noshow%' OR kind = 'confirm_a_corte'
 GROUP BY 1,2,3 ORDER BY 1 DESC, 2;
```

Ainda zero envios (allowlist só com o Álefe, sem corte dele).

## 7. Desvios do plano, com evidência

1. **8 templates**, não 7 (seção 1).
2. **A volta automática `Agendados → Entrada` não conta como arrasto.** MEDIDO: das 65 reuniões do
   Hub canceladas desde 20/09, 28 têm `Agendados → Entrada` logo depois: é o efeito de a
   consultora cancelar a reunião na Exact, que é o que o corte pede. Sem a exceção, a régua morreria
   minutos depois de nascer. `Entrada → Follow 1`, `→ Descartado` etc. encerram (`sdr_assumiu`).
3. **No follow por estágio a linha fica `pendente`, não `FE_SKIPPED`**, com
   `motivo='aguardando: regua_noshow_ativa'`. A UNIQUE `(lead, estágio)` não é parcial: um
   `skipped` bloquearia o par para sempre. Pendente, o follow sai quando a régua encerrar.
4. **Mesmas colunas `regua_encerrada_*`.** O corte encerra a régua de confirmação (`'corte'`) e o
   `noshow.armar` reabre a coluna: uma régua viva por pessoa.
5. **D1:** até 2 horários por dia em 2 dias; sem horário nenhum, `AcaoIgnorada`.
6. **Cliques do D0 do corte** (`NS_D0_*`) passam a ser do no-show quando a régua está viva; com a
   flag desligada, seguem com o tratamento do Bloco 1.
7. **"Sem interesse"** no no-show encerra a régua e avisa o dono, sem mexer em `cancelado_*` (a
   reunião já está cancelada para nós desde o corte).

## 8. Arquivos

`app/noshow.py` (novo), `app/confirmacao.py` (corte arma; inbound delega), `app/models.py`
(`KIND_NOSHOW_*`, `TIPO_NOTIF_SEMINARIO`), `app/nat_copy.py` (corpos, payloads, botões, textos),
`app/nat_scheduler.py` (`app.noshow` nos handlers), `app/qualificacao_guard.py` (teto conta a
régua), `app/follow_estagio.py` (trava), `app/exact_spotter.py` (arrasto), `app/routes.py` (SDR
manual), `app/reuniao_sync.py` (reunião nova = `reagendou`), `app/main.py` (linha de boot),
`backend/submit_templates_noshow.py`, `backend/conteudos_noshow.json`, `backend/test_noshow.py`.
`.env` (fora do git): `NOSHOW_ENABLED=true`, `NOSHOW_SOMENTE_TELEFONES=83988046720`.

## 9. Para o Bloco 3

- "Escolher horário"/"Reagendar" mostrando hoje+amanhã e agendando sozinho; responder "14h15" ao
  D1 virar agendamento.
- Fluxo B enxuto.
- Tela para a Isa editar `conteudos_noshow.json`.
