# Sprint curto — o carimbo do lead para de mentir

**29/08/2026.** Item 3 do §4.2 do `RECON_VAO_ESPONTANEO_20260829.md`. Commit único, com teste.
Escopo: **um** defeito. Nada de reenfileiramento — isso continua sendo decisão humana.

---

## O defeito, em uma frase

`exact_spotter.py:266` carimba o lead como atendido no instante em que a abertura é
**enfileirada**; a abertura pode morrer 5 minutos ou 2 dias depois, e até hoje ninguém
voltava no carimbo.

O comentário que já existe ali trata o caso de o gatilho recusar **na hora** — *"Carimbar 'o
agente assumiu' em cima de um gatilho que NÃO enfileirou fecha a porta do lead pelos dois
lados"*. O que faltava é o caso simétrico, e maior: o gatilho enfileira, o carimbo é posto, e
a **ação** falha depois.

## Por que isso some com o lead

Não é uma trava, são três, e é a conjunção que mata:

| Camada | Por que não devolve o lead |
|---|---|
| sync da Exact | o lead já é `existing`; nunca volta a `new_leads_to_contact` |
| `reprocessar_leads_perdidos.py:163` | filtra `welcome_status IS NULL` — e o carimbo não é NULL |
| agendador | a ação está em estado final (`skipped` / `falhou`); não há o que repescar |

**Medido em 29/08:** 7 leads carimbados como atendidos sem uma única abertura — 3 pela saída
muda de 25/08 (Adriana Palhana, Josiqueila, Elidilza) e 4 pela grafia do telefone (Fernanda,
Claudia, Sandra Diell, Dyenifer). Os dois defeitos de origem já estavam consertados (`b428ae1`
e `cd7507e`); o que não existia era o caminho de volta.

## O que mudou

`app/nat_scheduler.py` — uma função nova, `_desmentir_carimbo_do_lead`, chamada nos **dois
desfechos terminais** de `_executar_acao`:

```python
except AcaoIgnorada as e:
    await _finalizar(db, acao_id, ACAO_SKIPPED, agora, motivo=e.motivo)
    await _desmentir_carimbo_do_lead(db, dados, e.motivo)      # <—
...
if tentativas >= MAX_TENTATIVAS_ACAO:
    await _finalizar(db, acao_id, ACAO_FALHOU, agora, attempts=tentativas)
    await _desmentir_carimbo_do_lead(db, dados, f"{type(e).__name__}: {e}"[:200])   # <—
```

O `welcome_error` passa a dizer `agente NÃO abriu: <motivo real>`.

**`falhou` entrou junto com `skipped`, e isso é uma decisão a registrar.** A autorização
falava em `skipped`. Incluí `falhou` porque é o mesmo desaparecimento: 3 tentativas gastas, a
ação sai de circulação, o lead fica exatamente igual de invisível. Tratar só metade deixaria a
próxima Josiqueila sumindo pela outra porta. **Se a preferência for reverter para só
`skipped`, é apagar duas linhas.**

### Três coisas que ela deliberadamente NÃO faz

1. **Não toca em `welcome_status`.** Ele é a trava de idempotência que o passo 3 de
   `send_welcome_to_new_lead` consulta (`is not null`). Devolvê-lo a NULL faria o lead voltar
   a ser candidato à **boas-vindas** — o fluxo velho, não o agente. O que estava errado nunca
   foi o status; era o texto ao lado dele.
2. **Não reenfileira.** Só grava a verdade, para que a varredura de reconciliação consiga
   **enxergar** o lead. Quem entra na fila é triagem humana — a mesma que o dict `EXCLUIDOS`
   do script irmão registra.
3. **Só reescreve o carimbo que mente.** O `WHERE` exige `welcome_error ILIKE '%assumiu a
   abertura%'` **e** `welcome_status = 'skipped'`. Um lead marcado "funil fora do escopo" ou
   "backfill 25/08" tem carimbo verdadeiro, e sobrescrevê-lo apagaria a decisão de quem o pôs.

### Onde ela roda, e por que ali

**Depois do `_finalizar`, fora do savepoint do handler.** O savepoint acabou de ser revertido
pela exceção — escrever antes seria escrever no que some. E ela abre um savepoint **próprio**,
pelo mesmo motivo de `_registrar_transicao`: um erro aqui não pode abortar a transação que
acabou de registrar o desfecho da ação. O desfecho é o que importa; este UPDATE é o acréscimo.
Falha fechada e silenciosa-com-log: nunca levanta.

Reusa `payload_de` em vez de repetir o `json.loads` — uma definição só de "payload ilegível
não derruba nada".

## O teste

`backend/test_carimbo_desmentido.py` — banco falso, nada enviado, nada gravado.

```
cd backend && venv/bin/python test_carimbo_desmentido.py
```

Prova oito coisas, e as três que valem por si:

* **o `SET` tem `welcome_error` e não tem `welcome_status`** — lido do SQL compilado, não da
  intenção. É a regressão que custaria caro (lead de volta para a boas-vindas velha).
* **`executado` e `adiado` NÃO desmentem.** Um lead adiado para segunda 09:00 tem carimbo
  verdadeiro: a abertura ainda vai sair. Desmentir ali encheria o banco de falso alarme e
  poria os 5 leads legítimos do §1.2 do recon na lista de reconciliação.
* **erro no UPDATE não propaga** — o registro do desfecho da ação sobrevive ao acréscimo.

Rodei também as 12 suítes que tocam `nat_scheduler`, mais `test_abertura_grafia`,
`test_nat_duplicata`, `test_welcome_guardrail` e `test_espontaneo`: **todas verdes**.

## O que este commit NÃO resolve

Os **7 leads que já estão carimbados** não se corrigem sozinhos — a função só age quando a
ação termina, e as deles já terminaram. Eles dependem da varredura de reconciliação (§5 do
recon), que está levantada e **aguardando aprovação da lista**.

Daqui para a frente, o próximo caso nasce visível.
