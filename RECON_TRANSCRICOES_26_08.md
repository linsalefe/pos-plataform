# Transcrições de 26/08 SP + confirmação do encerramento + proposta da varredura

**Somente leitura.** Nenhuma escrita, nenhum envio.

Perímetro: **19 conversas do agente** com ≥1 inbound em 26/08 SP. Ficam de fora **16 threads
puramente humanas** (contatos sem estado do agente) que também tiveram inbound no dia.

Legenda: `LEAD` · `AGENTE` (tem `nat_etapa`) · `SDR` (envio manual, `sent_by_ai=false`) ·
`AI-OLD` (assistente antigo). Horários em SP.

---

## 1. As 19 transcrições

### 06:33 — Rita Andrade (`5548996012065`) · `transferido_humano`
```
06:33:06 LEAD    Olá! Tudo bem? Fiz minha aplicação na turma da Pós-Graduação Online em
                 Psicologia Escolar e gostaria de mais informações.
09:00:43 AGENTE  Olá, Rita! Que bom te ver por aqui ✨
                 Vi que você se interessou pela nossa Pós-Graduação em PsicologiaEscolar.
                 Antes de te mostrar os próximos passos, gostaria de conhecer um pouco da
                 sua trajetória.
                 Me conta: qual é a sua formação?
14:46:52 SDR     Olá Rita, tudo bem? 🌻
                 Fiz uma nova tentativa de contato, mas ainda sem sucesso, essa ligação é a
                 primeira etapa do seu processo seletivo da PsicologiaEscolar.
                 Qual o melhor horário para te retornar?
```
> Curso sai como `PsicologiaEscolar`, sem espaços — o alias cru, não o nome legível.

### 09:00 — Hosmana da Rosa Cezar de Moura (`5555996028910`) · `transferido_humano`
```
09:00:35 AGENTE  Olá, Hosmana! Que bom te ver por aqui ✨
                 Vi que você se interessou pela nossa Pós-Graduação em Transtorno do
                 Espectro Autista (TEA). Antes de te mostrar os próximos passos, gostaria
                 de conhecer um pouco da sua trajetória.
                 Me conta: qual é a sua formação?
09:00:37 LEAD    Agradecemos sua mensagem. Não estamos disponíveis no momento, mas
                 responderemos assim que possível.
09:21:05 LEAD    Ciências Biológicas
14:47:40 SDR     Olá Hosmana, tudo bem? 🌻
                 Fiz uma nova tentativa de contato, mas ainda sem sucesso, essa ligação é a
                 primeira etapa do seu processo seletivo da Transtorno do Espectro Autista
                 (TEA).
                 Qual o melhor horário para te retornar?
```
> Ela respondeu "Ciências Biológicas" às 09:21 e o agente nunca respondeu. A primeira
> mensagem dela é a auto-resposta do WhatsApp Business dela, consumida como inbound.

### 09:00 — "Eve 🍒🦖🤞" / Evelyn Renata Begliomini Manfrim (`5511940718388`) · `concluido`
```
09:00:40 AGENTE  Olá, Eve! Que bom te ver por aqui ✨
                 Recebi sua aplicação para a Pós-Graduação em Grupos e Oficinas em Saúde
                 Mental e sua reunião com nossa consultora Victória Amorim já está
                 confirmada para 28/08 às 10:30 📅
                 Enquanto isso, quero te conhecer um pouco melhor. Vi que sua formação é em
                 Terapia Ocupacional — em que ano você concluiu?
09:01:13 LEAD    Olá, bom diaaaaa!!!
09:01:16 AGENTE  Bom dia, Eve! Por aqui só consigo ler texto — você pode me dizer em que ano
                 concluiu a graduação (ou se ainda está cursando)?
09:01:20 LEAD    Conclui em 2013
09:01:23 AGENTE  Perfeito — você concluiu a graduação em 2013. Me conta: como e onde você
                 atua profissionalmente hoje?
09:01:47 LEAD    Estou mudando de área, hoje atuo em ambulatório de psiquiatria infanto
                 juvenil
09:01:50 AGENTE  Entendi — você está mudando de área e hoje atua em ambulatório de
                 psiquiatria infantojuvenil. O que despertou seu interesse nesta
                 pós-graduação em Grupos e Oficinas em Saúde Mental?
09:01:58 LEAD    Exatamente isso
09:02:01 AGENTE  Perfeito — você se interessou pela pós exatamente por estar mudando de área
                 e por atuar em ambulatório de psiquiatria infantojuvenil, buscando formação
                 em Grupos e Oficinas em Saúde Mental para essa transição. Vou ver os
                 horários disponíveis para a sua reunião com a Victória Amorim e te retorno
                 em seguida.
09:02:14 LEAD    Obrigada 😃
```
> O caso que originou o P0-D. "Vou ver os horários… e te retorno" — e nunca retornou. O
> "Obrigada 😃" já não foi escutado: `concluido` está fora das etapas ativas.
> `09:01:58 "Exatamente isso"` era resposta à pergunta anterior, e virou a motivação.

### 09:00 — amanda matana / Amanda Pavão Matana (`5544998336280`) · `aguardando_atuacao` **ATIVO**
```
09:00:38 AGENTE  Olá, Amanda! Que bom te ver por aqui ✨
                 Recebi sua aplicação para a Pós-Graduação em Saúde Mental e Mulheridades e
                 sua reunião com nossa consultora Victória Rodrigues já está confirmada para
                 27/08 às 09:00 📅
                 Enquanto isso, quero te conhecer um pouco melhor. Vi que sua formação é em
                 Serviço Social — em que ano você concluiu?
09:01:53 LEAD    Bom dia! Conclui a graduação em 2022
```
> Silêncio desde então. Reunião **hoje 09:00**.

### 09:00 — Marina prestação de serviços (`5581982397261`) · `transferido_humano`
```
09:00:42 AGENTE  Olá, Marina! Que bom te ver por aqui ✨
                 Recebi sua aplicação para a Pós-Graduação em Grupos e Oficinas em Saúde
                 Mental e sua reunião com nossa consultora Victória Rodrigues já está
                 confirmada para 26/08 às 14:15 📅
                 Enquanto isso, quero te conhecer um pouco melhor. Vi que sua formação é em
                 Fisioterapia — em que ano você concluiu?
09:02:57 LEAD    (reaction, sem texto)
13:45:50 AGENTE  Olá, Marina! Passando para lembrar da sua reunião de hoje às 14:15 📅
                 Nossa consultora, Victória Rodrigues, vai te ligar aqui mesmo pelo
                 WhatsApp, por este mesmo número.
                 Fique de olho no celular no horário combinado! 😊
14:30:22 LEAD    (reaction, sem texto)
14:30:25 AGENTE  Marina, você concluiu a graduação em que ano?
14:34:00 LEAD    (reaction, sem texto)
14:34:04 AGENTE  Oi Marina! Em que ano você concluiu a graduação (ou está cursando)?
15:33:34 LEAD    Formanda em 2023
15:33:38 AGENTE  Perfeito, Marina — anotado que você formou em 2023. Como e onde você atua
                 profissionalmente hoje?
15:33:57 LEAD    (reaction, sem texto)
15:34:00 AGENTE  Entendido — você atua como formanda em 2023. Me conta: como e onde você
                 atua profissionalmente hoje?
15:34:20 LEAD    Empreendimento.
                 Atendo a domiciliar
15:34:23 AGENTE  Entendi: você atua em um empreendimento e faz atendimentos domiciliares. O
                 que despertou seu interesse pela pós em Grupos e Oficinas em Saúde Mental?
15:34:31 LEAD    E em locais
15:34:36 AGENTE  Você mencionou que atende em domicílio e em locais — ótimo contexto. O que
                 despertou seu interesse pela pós em Grupos e Oficinas em Saúde Mental?
15:34:59 LEAD    A necessidade do parcialmente
15:35:01 AGENTE  Entendi que o que despertou seu interesse foi “a necessidade do
                 parcialmente”. Vou ver os horários disponíveis para a sua reunião com a
                 Victória Rodrigues no dia 26/08 às 14:15 😊
15:35:02 AGENTE  Deixa eu te conectar com uma pessoa da nossa equipe para seguir daqui, tá?
                 🙂 Em breve alguém fala com você por aqui.
15:35:20 LEAD    E hoje e um dos emprédimentos investir
15:35:24 LEAD    Na saúde mental
15:35:32 LEAD    Da polução
15:35:35 LEAD    (reaction, sem texto)
```
> Quatro `reaction` viram turno do LLM. Às 15:35:01 o agente promete "ver os horários" de uma
> reunião que **já tinha acontecido às 14:15**, e 1 segundo depois vem a despedida do bug do
> S3-1. As três últimas mensagens dela caíram no vazio: já era `transferido_humano`.

### 09:36 — Erica Q. C. (`5598984703419`) · `aguardando_ano` **ATIVO**
```
09:36:21 LEAD    Bom dia!
09:36:26 LEAD    Formação em Psicologia
```
> A abertura dela é de 25/08 16:59. No dia 26 ela escreveu duas vezes e **não houve uma única
> resposta** — nem do agente, nem de humano. Vítima da janela de 24 h sem tolerância ao
> 9º dígito (`61fa16f`, 17 h 40 sem deploy).

### 09:30 — Bruna Dal-Bó Fernandes (`5548998009934`) · `transferido_humano`
```
09:30:50 AGENTE  Olá, Bruna! Que bom te ver por aqui ✨
                 Vi que você aplicou para a nossa Pós-Graduação em Transtorno do Espectro
                 Autista (TEA). Antes de te mostrar os horários com a nossa consultoria,
                 gostaria de entender um pouco melhor a sua trajetória até aqui.
                 Vi que sua formação é em Pedagogia. Em que ano você concluiu?
09:36:46 LEAD    2014
14:47:33 SDR     Olá Bruna, tudo bem? 🌻
                 Fiz uma nova tentativa de contato, mas ainda sem sucesso, essa ligação é a
                 primeira etapa do seu processo seletivo da Transtorno do Espectro Autista
                 (TEA).
                 Qual o melhor horário para te retornar?
```

### 10:09 — Álefe Lins (`5583988046720`) · `transferido_humano` — **número de teste do time**
```
10:09:56 LEAD    Olá
10:10:04 AGENTE  Álefe, em que área e onde você atua profissionalmente hoje? Pode ser se está
                 em clínica, hospital, empresa, saúde pública, desempregado, fora da área,
                 etc.
10:10:25 LEAD    Atuo como psicólogo
10:10:28 AGENTE  Perfeito, Álefe — você atua como psicólogo. O que despertou seu interesse
                 pela pós-graduação em Saúde Mental do Trabalhador?
10:10:52 LEAD    Me especializar como profissional
10:10:55 AGENTE  Ótimo — você quer se especializar como profissional, buscando aprofundamento
                 na área de Saúde Mental do Trabalhador. Vou ver os horários disponíveis com
                 a consultoria.
10:11:05 LEAD    Ok
10:11:05 AGENTE  Deixa eu te conectar com uma pessoa da nossa equipe para seguir daqui, tá?
                 🙂 Em breve alguém fala com você por aqui.
10:11:14 LEAD    Obrigado
```
> A falha de contrato das 10:11 que ficou sem nome na auditoria — 2 tentativas do LLM fora do
> contrato ao ofertar a agenda. Único caso do dia de transferência legítima por falha do LLM.

### 11:50 — Sônia Castro (`5566997112651`) · `transferido_humano`
```
11:50:21 LEAD    Olá! Tudo bem? Fiz minha aplicação na turma da Pós-Graduação Online:
                 Transtorno do Espectro Autista (TEA): Subjetividade, Atenção Psicossocial e
                 Novas Práticas Profissionais e gostaria de mais informações.
                  Subjetividade e Atenção Psicossocial e gostaria de mais informações.
11:55:45 AGENTE  Olá, Sônia! Que bom te ver por aqui ✨
                 Vi que você aplicou para a nossa Pós-Graduação em . Antes de te mostrar os
                 horários com a nossa consultoria, gostaria de entender um pouco melhor a
                 sua trajetória até aqui.
                 Vi que sua formação é em Pedagogia. Em que ano você concluiu?
14:46:56 SDR     Olá Sônia, tudo bem? 🌻
                 Fiz uma nova tentativa de contato, mas ainda sem sucesso, essa ligação é a
                 primeira etapa do seu processo seletivo da Transtorno do Espectro Autista
                 (TEA).
                 Qual o melhor horário para te retornar?
15:52:59 LEAD    Estou no trabalho
```
> **"Pós-Graduação em ."** — o caso que o S3-3 conserta.

### 13:11 — Mikaelle Juliani (`5541992680313`) · `transferido_humano` — **vítima do bug S3-1**
```
13:11:50 LEAD    Olá! Tudo bem? Fiz minha aplicação na turma 3 da Pós-Graduação Online em
                 Psicologia na atenção psicossocial: Elementos para o trabalho na RAPS e
                 gostaria de mais informações.
13:20:48 AGENTE  Olá, Mikaelle! Que bom te ver por aqui ✨
                 Recebi sua aplicação para a Pós-Graduação em Psicologia na RAPS e sua
                 reunião com nossa consultora Victória Rodrigues já está confirmada para
                 27/08 às 09:45 📅
                 Enquanto isso, quero te conhecer um pouco melhor. Vi que sua formação é em
                 Psicologia — em que ano você concluiu?
13:22:12 LEAD    Oi! Conclui no final de 2023
13:22:17 AGENTE  Perfeito, Mikaelle — você concluiu a graduação no final de 2023. Me conta:
                 como e onde você atua profissionalmente hoje?
13:24:00 LEAD    Atuo de forma autônoma com psicologia clínica. Mas estou aguardando ser
                 chamada para um concurso da prefeitura para trabalhar nos equipamentos do
                 SUS.
13:24:04 AGENTE  Entendi — você atua como psicóloga clínica autônoma e está na espera do
                 concurso da prefeitura para atuar nos equipamentos do SUS. O que despertou
                 seu interesse por esta pós-graduação em Psicologia na RAPS?
13:25:00 LEAD    Ao longo da graduação me interessei por saúde pública, fiz estágio no CAPS e
                 a monografia sobre políticas públicas e  equipamentos de saúde.
13:25:04 AGENTE  Que bacana, Mikaelle — você se interessou por saúde pública durante a
                 graduação, fez estágio no CAPS e escreveu a monografia sobre políticas
                 públicas e equipamentos de saúde. Vou ver os horários disponíveis para a sua
                 reunião com a Victória Rodrigues e já te aviso 👍
13:25:04 AGENTE  Deixa eu te conectar com uma pessoa da nossa equipe para seguir daqui, tá?
                 🙂 Em breve alguém fala com você por aqui.
13:25:27 LEAD    Certo, obrigada.
```
> A melhor conversa do dia — validação específica, ritmo bom — e termina com a despedida do
> bug. Reunião **hoje 09:45**, e ela nunca foi confirmada por escrito.

### 13:13 — Flávia Ruschel (`5547996069022`) · `transferido_humano`
```
13:13:47 LEAD    Olá! Tudo bem? Fiz minha aplicação na turma da Pós-Graduação Online:
                 Transtorno do Espectro Autista (TEA): Subjetividade, Atenção Psicossocial e
                 Novas Práticas Profissionais e gostaria de mais informações.
                  Subjetividade e Atenção Psicossocial e gostaria de mais informações.
13:20:47 AGENTE  Olá, Flávia! Que bom te ver por aqui ✨
                 Recebi sua aplicação para a Pós-Graduação em Transtorno do Espectro Autista
                 (TEA) e sua reunião com nossa consultora Victória Amorim já está confirmada
                 para 27/08 às 17:15 📅
                 Enquanto isso, quero te conhecer um pouco melhor. Vi que sua formação é em
                 Psicologia — em que ano você concluiu?
13:22:38 SDR     Flávia, muito obrigado por compartilhar um pouco do seu momento profissional
                 e do que te trouxe até essa Pós.:sparkles:
                 O próximo passo é uma conversa por ligação de voz com a nossa consultora,
                 que vai te ajudar a entender como essa formação se encaixa exatamente no que
                 você busca.
                 Sua reunião está marcada para o dia 27/08 às 17:15  :date:
13:34:55 LEAD    Vou concluir julho 2027
```
> Dois defeitos no envio do SDR: **`:sparkles:` e `:date:` não renderizados**, e o texto
> agradece por ela ter "compartilhado seu momento profissional" — ela ainda não tinha dito
> nada. Depois disso ela respondeu a pergunta do agente e ninguém voltou.

### 13:52 — Amanda Cristina Gontijo Silva (`5537999965494`) · `transferido_humano` — **vítima S3-1**
```
13:52:51 AGENTE  Olá, Amanda! Que bom te ver por aqui ✨
                 Recebi sua aplicação para a Pós-Graduação em Transtorno do Espectro Autista
                 (TEA) e sua reunião com nossa consultora Victória Rodrigues já está
                 confirmada para 28/08 às 14:15 📅
                 Enquanto isso, quero te conhecer um pouco melhor. Vi que sua formação é em
                 Psicologia — em que ano você concluiu?
14:06:13 LEAD    Ola, boa tarde
14:06:18 LEAD    Conclui em 2021
14:06:19 AGENTE  Oi Amanda, boa tarde 😊 Em que ano você concluiu a graduação em Psicologia
                 (ou ainda está cursando)?
14:06:21 AGENTE  Perfeito, Amanda — anotado: conclusão em 2021. Me conta como e onde você
                 atua profissionalmente hoje?
14:07:35 LEAD    Atuo como psicoterapeuta desde 2021, sou mestra em psicologia social pela
                 UFMG e especialista em clínica pelo IFEN.
                 Atuo também no cuidado de mulheres vítimas de violência de gênero e com
                 minorias de gênero
14:07:38 AGENTE  Perfeito — você atua como psicoterapeuta desde 2021, é mestre em Psicologia
                 Social pela UFMG, especialista em clínica pelo IFEN e trabalha com cuidado
                 de mulheres vítimas de violência de gênero e com minorias de gênero. O que
                 despertou seu interesse pela pós em Transtorno do Espectro Autista (TEA)?
14:08:59 LEAD    A necessidade de ampliar conhecimento sobre o tema e ampliar minha atividade
                 clínica para o psicodiagnóstico de maneira crítica
14:09:02 AGENTE  Perfeito — entendi que você busca ampliar conhecimento sobre TEA e expandir
                 sua atuação clínica para o psicodiagnóstico de maneira crítica; é uma
                 motivação super pertinente ao curso. Vou ver os horários disponíveis para
                 sua reunião com a Victória Rodrigues.
14:09:03 AGENTE  Deixa eu te conectar com uma pessoa da nossa equipe para seguir daqui, tá?
                 🙂 Em breve alguém fala com você por aqui.
```
> `14:06:19` e `14:06:21`: rajada de duas mensagens dela virou dois turnos concorrentes — o
> agente pergunta o ano e, 2 s depois, já responde o ano. Fecha com a despedida do bug.

### 09:00 — Waldeneza (`5598981519379`) · `transferido_humano`
```
09:00:36 AGENTE  Olá, Waldeneza! Que bom te ver por aqui ✨
                 Vi que você aplicou para a nossa Pós-Graduação em Grupos e Oficinas em Saúde
                 Mental. Antes de te mostrar os horários com a nossa consultoria, gostaria de
                 entender um pouco melhor a sua trajetória até aqui.
                 Vi que sua formação é em Terapia Ocupacional. Em que ano você concluiu?
14:47:42 SDR     Olá Waldeneza, tudo bem? 🌻
                 Fiz uma nova tentativa de contato, mas ainda sem sucesso, essa ligação é a
                 primeira etapa do seu processo seletivo da Grupos e Oficinas em Saúde Mental.
                 Qual o melhor horário para te retornar?
14:52:01 LEAD    Ainda não vou fazer. Mandei msg para gravar o contato.
14:52:03 LEAD    Obrigada
14:54:28 SDR     Entendo, Waldeneza! 😊
14:54:52 SDR     Só fiquei na dúvida porque você chegou a fazer a aplicação e pediu para
                 manter o contato. O que fez você decidir deixar a pós para outro momento?
14:55:29 SDR     Te pergunto porque, caso seja uma questão de tempo, investimento ou até por a
                 turma já estar mais para frente, posso te explicar melhor as condições
                 atuais e estamos com 15% de desconto até 31/08, além das condições especiais
                 da campanha.
14:55:40 SDR     Existe algum ponto específico que está fazendo você adiar? Assim vejo se
                 consigo te ajudar antes de você deixar essa oportunidade para depois. 🌻
```

### 14:47 — Maria clara lins (`5581996326394`) · `transferido_humano`
```
14:47:17 SDR     Olá Maria, tudo bem? 🌻
                 Fiz uma nova tentativa de contato, mas ainda sem sucesso, essa ligação é a
                 primeira etapa do seu processo seletivo da Saúde Mental e Mulheridades.
                 Qual o melhor horário para te retornar?
15:04:00 LEAD    Boa tarde, não desejo iniciar a pós graduação no momento, obrigada
15:10:16 SDR     Sem problemas, Maria! 😊 Obrigado por me avisar.
15:10:41 SDR     Só para eu registrar certinho sua aplicação: você pretende deixar a pós para
                 um momento mais adiante ou decidiu não seguir com essa formação? Assim
                 consigo acompanhar seu interesse da melhor forma. 🌻
15:11:07 LEAD    não seguir com essa formação
```
> A abertura do agente foi em 25/08 18:05; no dia 26 só houve SDR.

### 10:00 — Angela Ramos (`5598991804665`) · `transferido_humano`
```
10:00:34 AGENTE  Olá, Angela! Que bom te ver por aqui ✨
                 Vi que você aplicou para a nossa Pós-Graduação em Autolesão, Suicídio e
                 Luto. Antes de te mostrar os horários com a nossa consultoria, gostaria de
                 entender um pouco melhor a sua trajetória até aqui.
                 Vi que sua formação é em Psicologia. Em que ano você concluiu?
14:47:22 SDR     Olá Angela, tudo bem? 🌻
                 Fiz uma nova tentativa de contato, mas ainda sem sucesso, essa ligação é a
                 primeira etapa do seu processo seletivo da Autolesão, Suicídio e Luto.
                 Qual o melhor horário para te retornar?
15:07:06 LEAD    oi
15:07:09 LEAD    desculpa
15:07:22 LEAD    mnesse momento fica caro pra mim
```
> Objeção de preço explícita, sem resposta de ninguém até o fim do dia.

### 14:47 — Michele Veronica Bravo de Miranda (`5541995901498`) · `transferido_humano`
```
14:47:05 SDR     Olá Michele, tudo bem? 🌻
                 Fiz uma nova tentativa de contato, mas ainda sem sucesso, essa ligação é a
                 primeira etapa do seu processo seletivo da Saúde Mental e Mulheridades.
                 Qual o melhor horário para te retornar?
15:08:15 LEAD    Oi, eu nao tenho mais interesse. Obrigada
15:09:32 SDR     Sem problemas, Michele! 😊 Obrigado por me avisar.
15:09:39 SDR     Só para eu registrar corretamente sua aplicação: o que fez você decidir não
                 seguir com a pós neste momento? Foi uma questão de investimento, tempo,
                 momento profissional ou outro motivo?
15:09:48 SDR     Seu retorno me ajuda a entender melhor o seu momento. 🌻
```

### 14:47 — Cintia Pessôa (`5581985088547`) · `transferido_humano`
```
14:47:38 SDR     Olá Cintia, tudo bem? 🌻
                 Fiz uma nova tentativa de contato, mas ainda sem sucesso, essa ligação é a
                 primeira etapa do seu processo seletivo da Saúde Mental e Mulheridades.
                 Qual o melhor horário para te retornar?
15:12:02 LEAD    No momento não tenho interesse. Estou me preparando para o início do ano q
                 vem. Agradeço o contato
```

### 15:37 — Natália Nordin de Oliveira (`5551995304709`) · `transferido_humano` — **vítima S3-1**
```
15:37:54 AGENTE  Olá, Natália! Que bom te ver por aqui ✨
                 Recebi sua aplicação para a Pós-Graduação em Psicologia na RAPS e sua
                 reunião com nossa consultora Victória Amorim já está confirmada para 27/08
                 às 15:45 📅
                 Enquanto isso, quero te conhecer um pouco melhor. Vi que sua formação é em
                 Psicologia — em que ano você concluiu?
15:42:17 LEAD    2023
15:42:20 AGENTE  Perfeito, você concluiu em 2023 — obrigada por avisar! Como e onde você atua
                 profissionalmente hoje?
15:42:38 LEAD    Atuo online particular
15:42:42 AGENTE  Entendi que você atua online em atendimentos particulares — ótimo! O que
                 despertou seu interesse por essa pós-graduação em Psicologia na RAPS?
15:43:01 LEAD    Estou estudando para concursos na Raps
15:43:04 AGENTE  Entendi: você está estudando para concursos na Raps — faz sentido procurar
                 uma pós que alinhe com isso, especialmente vindo da prática online
                 particular. Vou ver os horários disponíveis para sua reunião com a Victória
                 Amorim.
15:43:04 AGENTE  Deixa eu te conectar com uma pessoa da nossa equipe para seguir daqui, tá?
                 🙂 Em breve alguém fala com você por aqui.
```
> Conversa de 5 minutos, sem um tropeço — e o mesmo desfecho errado. Reunião **hoje 15:45**.

### 18:04 — (sem nome) / Natália (`5512991814636`) · `aguardando_ano` **ATIVO**
```
18:04:52 LEAD    Olá! Tudo bem? Fiz minha aplicação na turma 3 da da Pós-Graduação Online
                 Novas Abordagens em Saúde Mental: Autolesão, Comportamento suicida e Luto e
                 gostaria de mais informações.
18:09:56 AGENTE  Olá, Natália! Que bom te ver por aqui ✨
                 Vi que você aplicou para a nossa Pós-Graduação em . Antes de te mostrar os
                 horários com a nossa consultoria, gostaria de entender um pouco melhor a sua
                 trajetória até aqui.
                 Vi que sua formação é em Psicologia. Em que ano você concluiu?
```
> Segunda ocorrência de **"Pós-Graduação em ."**, e a última abertura antes do deploy do S3-3.

---

## 2. Erica e Amanda Pavão — o desfecho é seguro, mas o RÓTULO da ação não é o que você espera

### Resposta curta

**Sim, `encerrar_inativo` NÃO vai gravar `'inatividade'`.** Não existe caminho no handler que
chegue à escrita com a etapa fora das ativas.

**Não, ele não vai dar `skipped` com motivo.** Vai dar **`executado`, com `motivo` NULL.**
Essa parte da expectativa está errada, e importa para a auditoria depois.

### A evidência

`qualificacao_fluxo.py:1649`:

```python
@registrar_handler("encerrar_inativo")
async def encerrar_inativo(acao: dict, db: AsyncSession) -> None:
    wa_id = acao["contact_wa_id"]
    estado = await estado_de(wa_id, db)
    if estado is None:
        print(f"↩️  Encerramento: {wa_id} não tem estado — nada a fazer")
        return                                    # <-- return simples
    if estado.etapa not in ETAPAS_QUALIFICACAO_ATIVAS:
        print(f"↩️  Encerramento: {wa_id} já está em '{estado.etapa}' — nada a fazer")
        return                                    # <-- return simples, NÃO AcaoIgnorada
    estado.etapa = ETAPA_Q_ENCERRADO
    estado.encerrado_em = _agora_sp()
    estado.encerrado_motivo = MOTIVO_INATIVIDADE
```

O guard existe e está correto. Mas ele usa `return`, e no despachante (`nat_scheduler.py`) só
`AcaoIgnorada` produz `skipped`:

```python
except AcaoIgnorada as e:
    await _finalizar(db, acao_id, ACAO_SKIPPED, agora, motivo=e.motivo)   # skipped + motivo
    return ACAO_SKIPPED
...
await _finalizar(db, acao_id, ACAO_EXECUTADO, agora)                      # motivo default None
return ACAO_EXECUTADO
```

**Consequência prática:** em 29/08 as linhas 195 e 185 de `nat_scheduled_actions` ficarão
`executado / motivo NULL` — **indistinguíveis de uma ação que de fato encerrou um lead**. Se
você for auditar "o encerramento rotulou alguém errado?" procurando `skipped`, não vai achar
nada e pode concluir que o handler nem rodou.

**A prova de que nada foi encerrado é no estado, não na ação:**

```sql
select contact_wa_id, etapa, encerrado_em, encerrado_motivo, transferido_motivo
  from nat_qualificacao_state where contact_wa_id in ('5598984703419','5544998336280');
-- o que se espera em 29/08: etapa='transferido_humano', encerrado_em NULL,
--                           encerrado_motivo NULL, transferido_motivo='outbound_manual_sdr'
```

E no log: `↩️  Encerramento: <wa> já está em 'transferido_humano' — nada a fazer`.

### É fail-closed? Sim, com dois caminhos nomeados em que a etapa pode continuar ativa

A trava depende de `silenciar()` ter rodado. Ela é chamada de:

| Porta | Arquivo | Cobre? |
|---|---|---|
| `/send/text` | `routes.py:278` | ✅ |
| `/send/template` | `routes.py:325` | ✅ |
| `/send/media` | `routes.py:385` | ✅ |
| disparo em massa | `exact_routes.py:410` | ✅ |
| botão "Assumir conversa" | `nat_routes.py:298` | ✅ |
| boas-vindas automática | `exact_spotter.py` | ❌ **não chama** |
| `scheduled_messages_job` | `main.py` | ❌ **não chama** |

**Dois riscos residuais, os dois de baixa probabilidade:**

1. **`silenciar` é best-effort e o erro é engolido.** `_silenciar_agente_apos_envio_manual`
   roda em savepoint com `except` largo, e a própria docstring diz: *"O pior caso é o agente
   continuar ativo, que é o estado de hoje."* Se a escrita falhar, a mensagem do SDR sai, a
   etapa fica ativa e o 29/08 grava `'inatividade'`.
2. **Se o SDR usar mensagem AGENDADA em vez de digitar**, o `scheduled_messages_job` não tem a
   trava e a etapa fica ativa.

**Recomendação operacional:** peça ao SDR para **digitar direto na conversa** (`/send/text`) —
não agendar. E confira depois do envio:

```sql
select contact_wa_id, etapa, transferido_motivo, transferido_em
  from nat_qualificacao_state where contact_wa_id in ('5598984703419','5544998336280');
-- tem de sair 'transferido_humano' / 'outbound_manual_sdr' em SEGUIDA ao envio
```

Se sair, o 29/08 está resolvido. Se por qualquer razão continuar ativo, aí sim há prazo até
29/08 09:01 e 09:36 para agir.

> Nota do 9º dígito: a Erica tem o estado gravado em `5598984703419` e os inbounds chegam em
> `559884703419`. `silenciar` → `estado_de` usa `variantes_wa_id`, então **funciona nas duas
> grafias** — não importa por qual thread o SDR responda.

---

## 3. Proposta — varredura por ESTADO, o complemento do vigia (§5.2). Não implementar.

### O buraco

O vigia do P3-A cobre *"o lead escreveu e o agente não respondeu em 10 min"*, mas ele é
**armado no inbound**. Quem ficou preso **antes de ele existir** — ou num turno que estourou
antes de armar — não tem vigia, e ninguém varre a tabela de estados procurando conversa
parada. Hoje: 2 leads há ~36 h, invisíveis até o `encerrar_inativo` de 72 h fechá-los com o
rótulo errado.

O vigia é orientado a **evento**; falta o orientado a **estado**.

### A forma: JOB, não `kind`

| | `kind` no `nat_scheduled_actions` | **job periódico** |
|---|---|---|
| Precisa de uma linha por lead | sim — e o problema é justamente o lead que **não tem** linha | não |
| Cobre lead preso por bug anterior ao agendamento | **não** | **sim** |
| Cobre lead cuja ação foi revertida por savepoint | **não** | **sim** |

O `kind` herda a falha que ele deveria detectar: se o INSERT do vigia caiu junto com o turno,
não há linha para vencer. **Um job que varre `nat_qualificacao_state` não depende de nada ter
sido escrito antes** — é essa independência que o torna a rede certa.

Modelo pronto no projeto: `window_alerts_job` (`main.py:154`, `asyncio.sleep(300)`).

### O desenho

```
frequência        a cada 15 min (job próprio, ou carona no window_alerts_job de 5 min)
critério          etapa ∈ ETAPAS_QUALIFICACAO_ATIVAS
              AND existe inbound
              AND não existe outbound com timestamp > o último inbound
              AND agora_sp() - último_inbound > LIMIAR
LIMIAR            60 min  (o dobro do vigia, para nunca competir com ele)
teto              N por ciclo (ex.: 20), para um bug largo não virar enxurrada de alerta
destino           notifications, type = 'agente_parado' (tipo PRÓPRIO)
anti-repetição    não notificar de novo o mesmo (contato, último_wa_message_id)
```

**Por que 60 min e não 30:** o vigia vence em 10 min e readia até 30 com pendência. Abaixo de
60 os dois disparariam sobre o mesmo caso e a gestão receberia dois alarmes para um problema —
que é exatamente o defeito dos `window_*` que a auditoria apontou. Acima de 60, o vigia já
falhou de vez e a varredura é a única voz.

**Por que tipo próprio (`agente_parado`) e não `agente_mudo`:** o mesmo argumento do P3-A ao
separar `agente_mudo` de `agente_transferiu`. `agente_mudo` = *um turno específico não falou*.
`agente_parado` = *uma conversa está encalhada e ninguém percebeu*. As duas causas e as duas
ações são diferentes; juntá-las apaga a distinção que o alerta existe para criar.
`notifications.type` não tem CHECK — sem migração.

**Destino: GESTÃO, não o SDR dono.** A varredura detecta falha de sistema, não lead para
trabalhar. Mesmo critério do vigia.

### Duas decisões a tomar antes de escrever a primeira linha

1. **A varredura deve só notificar, ou também acordar o agente?** O vigia só notifica, de
   propósito. Fazer a varredura *responder* significaria o agente reaparecendo numa conversa
   parada há horas, com o lead já esfriado — e é a mesma discussão de reabrir conversa que o
   `encerrado` já resolveu por "não reabre". **Recomendo: só notificar.**
2. **O que fazer com o `encerrar_inativo` desses casos** (§5.1 do preflight). Uma varredura que
   avisa mas deixa o lead sair da base como `'inatividade'` conserta metade. A outra metade é
   `encerrar_inativo` distinguir "o lead calou" de "nós calamos" — provavelmente um
   `encerrado_motivo` novo (`sem_resposta_do_agente`), decidido junto com esta varredura.

### Custo

Uma query indexada a cada 15 min sobre 43 linhas (hoje). `idx_nat_qualif_etapa` já existe. O
`messages` por chave de telefone é o lado caro — mitigável restringindo a varredura aos
estados ativos primeiro (poucos) e só então buscando o último inbound de cada.

---

## 4. Backlog registrado

* **"fafaf"** (`5571985252525`, abertura hoje 09:00): **deixar sair.** Lixo de formulário é
  problema de admissão (`qualificacao_pode_iniciar`) ou do próprio formulário, não da
  formatação do nome. Prioridade baixa. Registrado aqui e no preflight §5.3.
* **`:sparkles:` / `:date:` cru** na mensagem do SDR para a Flávia: shortcode não renderizado
  saindo no texto do template manual do SDR. Fora do agente.

### E um achado NOVO que é maior do que backlog — 58% das aberturas com o curso mal formatado

`PsicologiaEscolar` (Rita, 09:00:43) não é "um alias faltando". São **duas convenções de
`sub_source` convivendo**, e a tabela de aliases só cobre uma delas:

```sql
select 'exact_leads' fonte,
       count(*) filter (where sub_source ~ ' ')  com_espaco,
       count(*) filter (where sub_source !~ ' ' and sub_source is not null) sem_espaco
  from exact_leads where register_date >= '2026-08-01'
union all select 'agendamentos', ... from agendamentos where created_at >= '2026-08-01';
--     fonte     | com_espaco | sem_espaco
--  exact_leads  |        106 |        309     <-- a fonte que `_curso` lê PRIMEIRO
--  agendamentos |        163 |         42
```

`course_aliases` é construída na convenção **com espaço** (`Pos Psicologia Escolar`,
`Pos TEA V3`). `exact_leads` é majoritariamente **sem espaço**. Quando não casa,
`resolve_course_name` cai no fallback, tira o prefixo "Pos" e devolve o resto cru:

```
PosPsicologiaEscolar  ->  "PsicologiaEscolar"
PosSMTrabalhadorT3    ->  "SMTrabalhadorT3"
PosBoasPraticasEAD    ->  "BoasPraticasEAD"
```

**Tamanho medido:**

```sql
select count(*) from exact_leads el
 left join course_aliases ca on lower(ca.alias)=lower(el.sub_source)
 where ca.id is null and el.sub_source is not null and el.register_date >= '2026-08-01';
-- 240   (de 415 leads de agosto = 58%)
```

Os 12 maiores buracos: `PosPsicologiaEscolar` (41), `PosSMTrabalhadorT3` (38),
`PosBoasPraticasEAD` (28), `interuruguai2026` (25), `posinfantoead` (17), `PosGraduacaoTEA`
(16), `PosPsicologianaRAPST3` (16), `PosAutolesaoComportamentoSuicidaeLutoTurma3` (14),
`PosGraduacaoEconomiaSolidariaTurma1` (13), `PosGestaoAvaliacaoePlanejamentoTurma5` (12),
`intercambiotrieste2026` (7), `posgruposeoficinasturma2` (6).

**Interação com o S3-3, e é desconfortável:** `_curso()` lê `exact_leads` primeiro e só cai
para `agendamentos` quando a primeira está vazia. Como `exact_leads` é a fonte da convenção
*ruim* e `agendamentos` a da convenção *boa*, existe o caso em que a fonte preferida entrega o
resultado pior — e o S3-3 não muda isso, porque ele só age quando a primeira está **ausente**,
não quando está feia. A Rita é exatamente esse caso (`exact_leads.sub_source =
'PosPsicologiaEscolar'`, sem alias).

**Não é código, é dado** — resolve-se preenchendo `course_aliases` com a convenção sem espaço.
Query para a gestora completar:

```sql
select el.sub_source, count(*) from exact_leads el
 left join course_aliases ca on lower(ca.alias)=lower(el.sub_source)
 where ca.id is null and el.sub_source is not null and el.register_date >= '2026-08-01'
 group by 1 order by 2 desc;
```

Não implementado, e a decisão de qual `short_name` cada alias recebe é comercial, não técnica.

---

## 5. Amanhã depois das 09:00

Rodar o checklist do §6 de `RECON_27_08_PREFLIGHT.md` e trazer junto o primeiro turno real
logado (linha `🧠 LLM`), que é a prova pendente do S3-2.
