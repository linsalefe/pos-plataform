# Triagem — conversas com pergunta sem resposta

**27/08/2026 · regerado às 14:15 (SP), depois do deploy de (a)+(b) · fila de trabalho do time.**

> **Esta versão substitui a lista das 71 gerada às 10:57.** Duas correções, ambas materiais:
>
> 1. **As idades estavam 3 horas infladas.** A geração anterior comparou o relógio **UTC** com
>    `messages.timestamp`, que é **naive de São Paulo** (`created_at` é que é UTC). Toda idade
>    saiu 3h maior. No fim da fila não muda nada; no topo muda — a Mikaelle constava `4h`
>    quando tinha `1h44`.
> 2. **São 69, não 71.** `558196326394` (Maria clara lins) e `559891804665` (Angela Maria)
>    foram respondidas entre as duas gerações. Nenhuma entrou. Total de pendentes no Hub
>    segue 1 490 — 69 em thread dividida, 1 421 em thread inteira.

Estas são as conversas em que **a última mensagem da conversa unificada é do lead** e ninguém
respondeu. "Unificada" = as duas metades da thread dividida (12 e 13 dígitos) lidas juntas por
timestamp — ver `RECON_THREADS_DIVIDIDAS_20260827.md`.

Os falsos-pendentes ficaram **fora**: naqueles, o Hub mostrava a conversa como não respondida
mas a resposta existia na outra metade. Aqui só o que está realmente em aberto.

## Como usar

* **A tela do Hub já junta as duas metades** desde o deploy de hoje (14:05). Abrir por
  qualquer das duas grafias devolve a conversa inteira, e o `?wa=` da notificação do sino
  também. A coluna `wa_id` abaixo é onde a mensagem **dela** está — é só a referência do banco,
  não uma instrução de navegação. Para achar na busca, cole os **8 últimos dígitos**
  (ex.: `92680313`).
* **`⚠ SDR só na outra metade` / `⚠ dividido c/`**: o dono do lead está registrado no outro
  contato — **56 das 69** (44 + 12). O card mostra o dono que existe, mas combine quem responde
  antes de escrever.
* **`etapa agente`**: `transferido_humano` = a Nat já entregou para gente e parou de propósito
  (é com você). `—` = não há estado do agente; a conversa é 100% humana.
* Não crie contato novo e não apague nenhum dos dois lados. A migração dos pares — (c) — ainda
  está no planejamento.

## Ordem: idade crescente (a mais recente primeiro)

| # | idade | wa_id (com inbound) | telefone | nome | SDR | etapa agente | última mensagem do lead |
|---|---|---|---|---|---|---|---|
| 1 | **43min** | `558185088547` | (81) 8508-8547 | Cintia Pessoa | Thobias | transferido_humano | Estou me organizando com relação a tempo |
| 2 | **5h** | `554192680313` | (41) 9268-0313 | Mikaelle Beatriz de Souza Juliani | Thobias (⚠ SDR só na outra metade) | transferido_humano | Oi… gostaria de confirmar o horário da conversa com a consultora |
| 3 | **22h** | `556697112651` | (66) 9711-2651 | Sônia Castro | Thobias | transferido_humano | Estou no trabalho |
| 4 | **22h** | `558182397261` | (81) 8239-7261 | Marina Soares de Souza | Thobias (⚠ SDR só na outra metade) | transferido_humano | [reaction] |
| 5 | **26h** | `553172666778` | (31) 7266-6778 | Alexandre | Thobias (⚠ dividido c/ Valéria) | — | Maravilha |
| 6 | **28h** | `558388046720` | (83) 8804-6720 | Álefe Guimel Lins Barbosa | Vi Amorim (⚠ dividido c/ Thobias) | transferido_humano | Obrigado |
| 7 | **28h** | `559884703419` | (98) 8470-3419 | Erica Q. C. | Thobias | aguardando_ano | Formação em Psicologia |
| 8 | **29h** | `559284118443` | (92) 8411-8443 | Ana Jeffres. Psicóloga Clínica & Organizacional | Thobias (⚠ SDR só na outra metade) | — | Olá! Tudo bem? Fiz minha aplicação na turma da Pós-Graduação Online em Saúde M… |
| 9 | **45h** | `559192312177` | (91) 9231-2177 | 🎯📓🧠 ✡Psi Rosana  🦋🩺 | Thobias (⚠ dividido c/ Valéria) | — | A noite! As 21h , se puder |
| 10 | **46h** | `555185440615` | (51) 8544-0615 | Juliana Mattos | Valéria | — | Oi sim |
| 11 | **2d** | `558688761858` | (86) 8876-1858 | maria da conceicao melo ferreira melo ferreira | Valéria (⚠ SDR só na outra metade) | — | estou entrando agora no curso |
| 12 | **2d** | `556299799505` | (62) 9979-9505 | Anna | Thobias (⚠ SDR só na outra metade) | — | Bom dia, como será feita a conversa? |
| 13 | **3d** | `558388041204` | (83) 8804-1204 | Diana | Thobias (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 14 | **3d** | `553498332553` | (34) 9833-2553 | Marja Almeida | Thobias (⚠ SDR só na outra metade) | — | Olá! Tudo bem? Fiz minha aplicação na turma 2 da Pós-Graduação Online Grupos e… |
| 15 | **4d** | `558694143294` | (86) 9414-3294 | DANIELLA DE CARVALHO COSTA | Thobias (⚠ SDR só na outra metade) | — | botao:Sim, Posso conversar agora |
| 16 | **4d** | `553192299281` | (31) 9229-9281 | Adriana | Thobias (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 17 | **5d** | `554792148590` | (47) 9214-8590 | Fernanda Prada | Thobias (⚠ SDR só na outra metade) | — | botao:Sim, Posso conversar agora |
| 18 | **5d** | `556281727120` | (62) 8172-7120 | Pricilla Peixoto | Thobias (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 19 | **6d** | `559187528743` | (91) 8752-8743 | Prof Heloiza Benjamin | Valéria (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 20 | **6d** | `559188517368` | (91) 8851-7368 | Laide Cunha Psicóloga e Neuropsicopedagoga Clinica CRP 10/05536 | Valéria (⚠ SDR só na outra metade) | — | botao:Sim, Posso conversar agora |
| 21 | **7d** | `554899842160` | (48) 9984-2160 | Jocelia Cavalcante | Thobias (⚠ SDR só na outra metade) | — | botao:Sim, Posso conversar agora |
| 22 | **7d** | `556792977590` | (67) 9297-7590 | Jacqueline  | Valéria (⚠ SDR só na outra metade) | — | Prefiro via WhatsApp |
| 23 | **8d** | `557191483014` | (71) 9148-3014 | Elder dos Reis Almeida | Thobias (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 24 | **8d** | `558681555714` | (86) 8155-5714 | Antoniana Teixeira de Siqueira Frota | Thobias | — | botao:Sim, Posso conversar agora |
| 25 | **8d** | `558597054973` | (85) 9705-4973 | Yara feitosa vieira | Valéria (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 26 | **9d** | `556191438878` | (61) 9143-8878 | Matilde | Valéria (⚠ SDR só na outra metade) | — | media:1985891808738214\|image/jpeg\| |
| 27 | **9d** | `554398392280` | (43) 9839-2280 | Antonio Augusto Baldi Martins  | Thobias (⚠ SDR só na outra metade) | — | botao:Sim, Posso conversar agora |
| 28 | **10d** | `556199863010` | (61) 9986-3010 | Liana  | Thobias (⚠ SDR só na outra metade) | — | botao:Sim, Posso conversar agora |
| 29 | **10d** | `559996519506` | (99) 9651-9506 | Samara de Jesus de Sousa Kaiper | Thobias (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 30 | **11d** | `558299448224` | (82) 9944-8224 | Lidiane de Oliveira Goes | Valéria (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 31 | **11d** | `554896171139` | (48) 9617-1139 | Gabriela Psicóloga | Thobias (⚠ SDR só na outra metade) | — | botao:Sim, Posso conversar agora |
| 32 | **11d** | `558896623026` | (88) 9662-3026 | Rachel Cardoso ✨️ | Vi Amorim (⚠ dividido c/ Valéria) | — | Olá! Tudo bem? Fiz minha aplicação na turma da Pós-Graduação Online em Saúde M… |
| 33 | **12d** | `554298734345` | (42) 9873-4345 | Franciely Cristina Costa | Thobias (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 34 | **12d** | `556696966240` | (66) 9696-6240 | Célia Márcia | Thobias (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 35 | **12d** | `553193317024` | (31) 9331-7024 | Barbbara campos da Silva | Thobias | — | botao:Prefiro outro horário |
| 36 | **12d** | `556195106513` | (61) 9510-6513 | Adrielle de Matos Borges Teixeira  | Valéria (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 37 | **12d** | `555596375992` | (55) 9637-5992 | Paola Jacobuk | Valéria (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 38 | **13d** | `554298436782` | (42) 9843-6782 | Gilberto Gomes | Thobias | — | Olá, eu sou ‎Gilberto Gomes, e agradeço seu contato. Como posso te ajudar? |
| 39 | **13d** | `554187753666` | (41) 8775-3666 | Andrea Cristina Elias | Valéria (⚠ SDR só na outra metade) | — | botao:Sim, Posso conversar agora |
| 40 | **14d** | `553484230223` | (34) 8423-0223 | Jonathan Moreira e Silva  | Valéria (⚠ SDR só na outra metade) | — | Olá |
| 41 | **15d** | `554896345524` | (48) 9634-5524 | Raiane Angeli | Valéria (⚠ SDR só na outra metade) | — | botao:Sim, Posso conversar agora |
| 42 | **15d** | `554199521748` | (41) 9952-1748 | André | Valéria (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 43 | **15d** | `554898363891` | (48) 9836-3891 | Isa | Thobias (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 44 | **15d** | `557991616093` | (79) 9161-6093 | Fabiola Andrade | Valéria | — | Disponibilidade de tempo e recursos financeiros |
| 45 | **16d** | `556293145787` | (62) 9314-5787 | Isabelle Cirqueira Rodrigues | Valéria (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 46 | **16d** | `558589585400` | (85) 8958-5400 | Davi Cartaxo Rodrigues  | Vi Amorim (⚠ dividido c/ Valéria) | — | Perdão |
| 47 | **16d** | `558199043236` | (81) 9904-3236 | Paulo Vasconcelos  | Valéria (⚠ SDR só na outra metade) | — | Aguardando |
| 48 | **16d** | `557781533673` | (77) 8153-3673 | Daniel Cavalcante de Albuquerque | Vi Amorim | — | Não consegui |
| 49 | **17d** | `559691872193` | (96) 9187-2193 | Thaís | Thobias | — | Olá, só gostaria de saber se é possível iniciar módulos isolados, ou apenas o … |
| 50 | **20d** | `555397099717` | (53) 9709-9717 | Bruna Medeiros | Valéria (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 51 | **21d** | `553488894519` | (34) 8889-4519 | Juliana Rodrigues | Thobias (⚠ SDR só na outra metade) | — | botao:Sim, Posso conversar agora |
| 52 | **22d** | `554198025019` | (41) 9802-5019 | Gabriela | Valéria (⚠ SDR só na outra metade) | — | botao:Prefiro outro horário |
| 53 | **23d** | `559681408675` | (96) 8140-8675 | 🌹Nana Cabral🌹 | Thobias | — | Tá bem |
| 54 | **23d** | `558896632544` | (88) 9663-2544 | Francisca Jeanne Farias Matos  | Vi Amorim (⚠ dividido c/ Valéria) | — | Boa noite! |
| 55 | **23d** | `556182876193` | (61) 8287-6193 | Adriano Carneiro Silva  | Vi Amorim (⚠ dividido c/ Thobias) | — | A  vaga de psicoterapia? |
| 56 | **23d** | `558788599781` | (87) 8859-9781 | Valdirene Rocha | Vi Amorim (⚠ dividido c/ Valéria) | — | Oii |
| 57 | **24d** | `559384175730` | (93) 8417-5730 | LUCIANA AIRES ROSA DE LIMA | Valéria (⚠ SDR só na outra metade) | — | Oi |
| 58 | **26d** | `559181777470` | (91) 8177-7470 | Marinete | Vi Amorim (⚠ dividido c/ Valéria) | — | No momento não consigo pagar uma mensalidade para fazer a pós,sendo que ainda … |
| 59 | **26d** | `554396281669` | (43) 9628-1669 | Carla Leal De Carvalho  | Valéria | — | Boa tarde, tudo bem  e vc ?   Não enviei, porque não tenho laudo medico |
| 60 | **27d** | `555481313151` | (54) 8131-3151 | Xxxxxxxx | Valéria (⚠ SDR só na outra metade) | — | botao:Sim, Posso conversar agora |
| 61 | **27d** | `559391683840` | (93) 9168-3840 | Thereza Christina | Vi Amorim (⚠ dividido c/ Thobias) | — | Olá! Tudo bem? Fiz minha aplicação na turma da Pós-Graduação EAD: Novas Aborda… |
| 62 | **29d** | `553484452303` | (34) 8445-2303 | Lilian Naves | Vi Amorim (⚠ dividido c/ Valéria) | — | Bom dia! |
| 63 | **35d** | `553284293461` | (32) 8429-3461 | Camis | Valéria (⚠ SDR só na outra metade) | — | [button] |
| 64 | **36d** | `558599865219` | (85) 9986-5219 | Paulo | Thobias | — | [reaction] |
| 65 | **41d** | `559581299091` | (95) 8129-9091 | Fabrício Bezerra de Deus | Thobias (⚠ SDR só na outra metade) | — | [button] |
| 66 | **41d** | `557192274267` | (71) 9227-4267 | Andrezza di Paula Souza Leite | Thobias (⚠ SDR só na outra metade) | — | [button] |
| 67 | **42d** | `553299827513` | (32) 9982-7513 | Viviane soares | Vi Amorim (⚠ dividido c/ Valéria) | — | Olá! Tudo bem? Fiz minha inscrição da Pós-Graduação EAD: Novas Abordagens em S… |
| 68 | **42d** | `555186022759` | (51) 8602-2759 | Mariana VA | Valéria (⚠ SDR só na outra metade) | — | [button] |
| 69 | **44d** | `558888389779` | (88) 8838-9779 | João Batista Moreira Gonçalves | Valéria (⚠ SDR só na outra metade) | — | [button] |

## Leitura dos números

| corte | conversas |     | SDR | conversas |
|---|---|---|---|---|
| menos de 24h | 4 | | Thobias | 33 |
| 1 a 7 dias | 16 | | Valéria | 25 |
| 7 a 30 dias | 42 | | Vi Amorim | 11 |
| mais de 30 dias | 7 | | | |

As 4 de menos de 24h são as urgentes. A **nº 1 (Cintia Pessoa)** respondeu **há 43 minutos** —
ontem ela tinha dito "no momento não tenho interesse" e hoje voltou com "estou me organizando
com relação a tempo", o que é uma reabertura, não uma recusa. A **nº 2 (Mikaelle)** está
pedindo **confirmação de um horário já agendado com a consultora**, e o agente já a transferiu
para humano.

## Metade da fila é clique de botão sem resposta: 35 de 69

**35 das 69 (51%)** têm como última mensagem um clique de botão que levou silêncio:

| último clique | conversas |
|---|---|
| `Prefiro outro horário` | 18 |
| `Sim, Posso conversar agora` | 12 |
| `[button]` (payload não registrado) | 5 |

A concentração não é coincidência:

| população | paradas em inbound | dessas, clique de botão |
|---|---|---|
| threads **divididas** | 69 | **35 (51%)** |
| threads **inteiras** | 1 421 | 22 (1,5%) |

**33× mais concentrado nas threads divididas — mas a divisão NÃO é a causa.** As duas coisas
têm a **mesma origem**: a boas-vindas antiga (`exact_spotter.py:326/358/373`) gravava na grafia
de 13 dígitos, o que **criava** a divisão; e é ela que manda os botões que **o backend não
trata** — a pendência já registrada em `AUDITORIA_NAT_20260725.md`. Quem recebeu aquela
boas-vindas herdou os dois problemas de uma vez.

Os 35 têm `nat_etapa` NULL — **não é o agente atual**, é o fluxo antigo. E **29 dos 35**
aconteceram em agosto: está vivo, não é resíduo.

**O deploy de hoje não conserta isto.** (a) e (b) juntam as metades na tela e param de criar
divisão nova; os cliques continuarão chegando sem tratamento até a pendência da NAT ser
fechada. Continua sendo item próprio.

## Nota de manuseio

Gerado em sessão de leitura. A única escrita da sessão de validação foi no caso Mikaelle, e foi
revertida pelo próprio `POST /read` — conferido por `diff` contra o snapshot anterior. Ver
`DEPLOY_THREADS_DIVIDIDAS_20260827.md`.
