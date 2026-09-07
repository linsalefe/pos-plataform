# RD Station — abertura do gate e drenagem da fila (07/09/2026)

Encerra o item que ficou aberto na Fase 1: o envio estava implantado e a fila enchendo, com
`RD_ENVIO_ENABLED` desligado à espera da conferência dos fluxos no painel do RD. Os fluxos
foram conferidos pelo operador em 07/09/2026 e o gate foi aberto no mesmo dia.

## O que mudou

`backend/.env` (fora do git):

```
RD_API_KEY=<chave da API de conversão do RD>
RD_ENVIO_ENABLED=true
```

Sem aspas de propósito. O valor é alfanumérico puro, e três coisas leem este arquivo — o
`EnvironmentFile` do systemd guardaria as aspas dentro da chave, e a chamada sairia com um
`api_key` inválido.

Nenhuma mudança de código foi para o repositório. `MAX_POR_CICLO` foi baixado para 1 e
devolvido para 50 dentro da janela de operação; `git diff` fecha limpo contra o HEAD.

## Como foi aberto

O gate não foi aberto de uma vez. `MAX_POR_CICLO = 1`, restart, e o primeiro envio real ficou
sozinho no ciclo para ser conferido no painel do RD antes de os outros 118 saírem.

**Primeiro envio — 07/09 18:52:54 UTC**

| | |
|---|---|
| Linha | `rd_conversoes` #2 |
| Evento | `formulario-pos-grupos-t2` |
| HTTP | 200 |
| Corpo | `{"event_uuid":"db536b7b-d0e6-4a2a-8fbd-05781c603655"}` |

Conferido no painel do RD: o contato registrou a conversão no evento e entrou no fluxo. Só
então `MAX_POR_CICLO` voltou a 50 e o serviço foi reiniciado (19:05:30 UTC).

## Resultado

| | |
|---|---|
| Enviado | **119** |
| Falhou | **0** |
| Retentativas | **0** (nenhuma linha com `tentativas > 1`) |
| Skipped | 132, todos anteriores — 117 do corte do histórico agendado, 15 `sem_email` |
| Janela | 18:52:54 → 19:08:53 UTC |

Fila **zerada**: não há mais nenhuma linha `pendente`.

Distribuição por evento:

| Evento | Enviados |
|---|---:|
| `formulario-pos-grupos-t2` | 39 |
| `formulario-pos-mulheridades-2` | 18 |
| `formulario-pos-tea` | 17 |
| `formulario-pos-sm-trabalhador-7c1bffb18b` | 11 |
| `formulario-pos-enfermagem` | 9 |
| `formulario-pos-infanto-ead` | 7 |
| `formulario-pos-suicidio-t3` | 5 |
| `formulario-pos-psi-na-raps-t3` | 4 |
| `formulario-pos-psicologia-escolar` | 4 |
| `formulario-pos-ad-t4` | 2 |
| `formulario-pos-sm-e-dh` | 1 |
| `formulario-pos-gestao-t5` | 1 |
| `formulario-pos-psicologia-clinica` | 1 |

## Estado a partir daqui

A integração passa a operar em regime: cada conversão nova entra na fila e sai no ciclo
seguinte, em até 60s. O drenador imprime `⏱️ rd fila: {...}` a cada passada com trabalho, e
some do log quando a fila está vazia — a ausência da linha é fila limpa, não job morto.

O que continua valendo do desenho da Fase 1, e não foi exercitado porque nada falhou: 429 e
5xx voltam em 5 minutos até três tentativas; os demais 4xx marcam `falhou` na hora, com o
corpo da resposta gravado em `resposta`, que é onde olhar quando acontecer.

Para fechar o gate de novo basta `RD_ENVIO_ENABLED=false` e restart — a fila volta a
acumular como `pendente`, sem perda.
