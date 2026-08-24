# Rascunhos de templates — Bloco 1 (submeter ao Meta)

Bloco 1 do `RECON_PREQUALIFICACAO_20260824.md` — o caminho crítico, porque aprovação da
Meta leva dias. Submeter em paralelo ao resto.

Decisões incorporadas: lembrete usa o número do canal (sem variável de telefone);
lead sem dado de formação recebe abertura que pergunta em vez de afirmar; a
ramificação de agendamento (confirmar reunião × ofertar agenda) acontece DEPOIS
das perguntas 1-3, já com janela de 24h aberta — logo não precisa de template.

São 4 submissões. Nomes seguem o padrão `nat_*` (decisão 5: continua sendo NAT).

---

## T1 — `nat_abertura_agendado` · UTILITY · pt_BR

Para quem preencheu o form E agendou na página de obrigado (67% hoje). Reconhece a
reunião logo de cara — corrige a contradição do §3.1 ("podemos falar agora?" para
quem acabou de marcar terça às 16h).

> Olá, {{1}}! Que bom te ver por aqui ✨
>
> Recebi sua aplicação para a Pós-Graduação em {{2}} e sua reunião com nossa
> consultora {{3}} já está confirmada para {{4}} às {{5}} 📅
>
> Enquanto isso, quero te conhecer um pouco melhor. Vi que sua formação é em
> {{6}} — em que ano você concluiu?

Variáveis: 1 primeiro nome · 2 curso · 3 consultora · 4 data · 5 hora · 6 formação
Sem botões (resposta é texto livre; abre a janela).

## T2 — `nat_abertura_qualificacao` · MARKETING · pt_BR

Para quem preencheu o form e NÃO agendou (33%). É o passo 1 do roteiro, verbatim
adaptado.

> Olá, {{1}}! Que bom te ver por aqui ✨
>
> Vi que você aplicou para a nossa Pós-Graduação em {{2}}. Antes de te mostrar os
> horários com a nossa consultoria, gostaria de entender um pouco melhor a sua
> trajetória até aqui.
>
> Vi que sua formação é em {{3}}. Em que ano você concluiu?

Variáveis: 1 primeiro nome · 2 curso · 3 formação

## T3 — `nat_abertura_sem_formacao` · MARKETING · pt_BR

Para lead sem dado de formação (chegou sem formulário — decisão 4: o agente
pergunta tudo).

> Olá, {{1}}! Que bom te ver por aqui ✨
>
> Vi que você se interessou pela nossa Pós-Graduação em {{2}}. Antes de te mostrar
> os próximos passos, gostaria de conhecer um pouco da sua trajetória.
>
> Me conta: qual é a sua formação?

Variáveis: 1 primeiro nome · 2 curso

## T4 — `nat_lembrete_reuniao` · UTILITY · pt_BR

T-30min. Roteiro adaptado à decisão 1: a consultora liga pelo WhatsApp, por este
mesmo número — sem variável de telefone.

> Olá, {{1}}! Passando para lembrar da sua reunião de hoje às {{2}} 📅
>
> Nossa consultora, {{3}}, vai te ligar aqui mesmo pelo WhatsApp, por este mesmo
> número.
>
> Fique de olho no celular no horário combinado! 😊

Variáveis: 1 primeiro nome · 2 hora · 3 consultora

---

## Notas de submissão

- Submeter T1 e T4 como UTILITY (lembrete/confirmação de compromisso é o caso
  canônico; se o Meta recategorizar T1 como MARKETING, aceitar — não muda o fluxo).
- Idioma: só `pt_BR`. Não criar variante `en` (lição do `nat_recuperacao_sdr`).
- Depois de aprovados, conferir por `hsm_id` + `language`, nunca só por nome.
- `nat_sim` (aprovado) continua disponível como resposta pós-clique; não conflita.
- O que já existe e NÃO será usado pelo agente novo: `nat_boasvindas` fica
  aposentado quando o agente ligar (decisão 3 — desligamento do auto_welcome é
  checkpoint coordenado com a Valéria, na ativação).

---

## Dependências deste bloco (do RECON)

| Variável | De onde vem hoje | Estado |
|---|---|---|
| 1 primeiro nome | `agendamentos.nome` / `exact_leads.name` | ✅ `app.nomes.primeiro_nome`, entregue na Sprint Higiene (24/08) |
| 2 curso | `resolve_course_name(sub_source)` | ✅ 10 de 13 entregues na Sprint Higiene (24/08). ⚠️ 3 ainda saem com o código cru — Infantojuvenil EAD, Psicologia Escolar, Enfermagem |
| 3 consultora | `consultoras.json` → `nome_exibicao`, via `agendamentos.sales_rep_email` | ✅ existe |
| 4 data · 5 hora | `agendamentos.slot_inicio` | ✅ existe |
| 6 formação | `agendamentos.extras['Profissão']` | ⚠️ existe no banco, ainda não ligado ao envio (Bloco 2 do RECON, G2) |
