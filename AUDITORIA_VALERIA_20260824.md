# Auditoria — referências à Valéria (user id=4) — 24/08/2026

A Valéria foi desligada. Este documento levanta **onde o sistema ainda depende dela**.
Nada foi alterado: é insumo de decisão.

## O achado principal

**Desativar a Valéria em `users` não redireciona uma única notificação.**

`nat_flow.usuario_existe` (`nat_flow.py:224`) responde *"a linha existe?"*, nunca *"o
usuário está ativo?"*:

```python
res = await db.execute(select(User.id).where(User.id == user_id))
return res.first() is not None
```

Os dois pontos que decidem destinatário de aviso — `qualificacao_fluxo._notificar:264` e
`nat_flow._destinatario_do_aviso:238` — usam essa função para saber se caem no fallback
para a gestão. Com `is_active=false`, a linha continua existindo, a função continua
devolvendo `True`, e o aviso continua indo para ela.

O login, esse sim, respeita: `auth.py:57` e `auth_routes.py:34` barram inativo.

**Consequência:** a tranca de acesso e a de roteamento são independentes, e só uma existe.
Corrigir `usuario_existe` para exigir `is_active` conserta os dois fluxos numa função — mais
barato e mais seguro que caçar o literal `4` em constantes espalhadas.

## Estado medido (24/08)

| | |
|---|---|
| `users` id=4 | `is_active = **true**`, role `admin`, login funcionando |
| Contatos com `assigned_to=4` | **1 245** |
| Mensagens nesses contatos (7 d) | 42 |
| Leads na Exact com `sdr_name='Valéria'` | 2 022 |
| …destes, criados nos últimos 7 d | **11** |
| Distribuição da Exact (7 d) | Thobias 94 · **Valéria 11** |

**A Exact ainda distribui para ela.** ~10% dos leads novos.

## Ponto → efeito → recomendação

| # | Ponto | Efeito HOJE | Efeito se NAT/agente ligar | Recomendação |
|---|---|---|---|---|
| 1 | `nat_guard.py:50` `SDR_IDS_PERMITIDOS = {4,5}` | Inerte (`nat_enabled=false`) | Leads dela **passam** no gate e são transferidos para ela | Remover o `4` — **mas ver o #2 antes** |
| 2 | `nat_sla.py:89-92` `restantes = SDR_IDS_PERMITIDOS - {dono}` | Inerte | ⚠️ Com só o `5` no conjunto, `restantes` fica **vazio** e a função devolve `None`: o nível 1 do escalonamento não avisa ninguém e a escada pula para a gestão | Remover o `4` **exige** rever a escada, senão o SLA perde um degrau em silêncio |
| 3 | `sdr_mapping.py:4` `"Valéria": 4` | **Ativo agora** — 11 leads/7 d viram `assigned_to=4` | idem | Mapear para quem assumir a carteira, ou `None` |
| 4 | `qualificacao_fluxo.py:264` `_notificar` | Inerte (agente off) | Aviso vai para ela; `is_active=false` **não** muda isso | Corrigir `usuario_existe` |
| 5 | `nat_flow.py:238` `_destinatario_do_aviso` | Inerte | Mesmo defeito, fluxo velho | Mesma correção |
| 6 | `users.is_active = true` | Ela faz login | — | Decisão de acesso, fora do código |
| 7 | `nat_guard.py:44` e `nat_sla.py:86,217` | Comentários citam "Valéria(4)" | — | Atualizar junto com a mudança, senão o próximo leitor confia no comentário |

## Ordem sugerida

1. `usuario_existe` passa a exigir `is_active` — conserta #4 e #5 de uma vez, e sem ela
   qualquer desativação é meia-verdade.
2. `users.is_active = false` para o id 4 — a partir daí o roteamento cai na gestão sozinho.
3. `sdr_mapping` — parar de atribuir leads novos a ela.
4. `SDR_IDS_PERMITIDOS` **junto com** a decisão sobre o nível 1 do SLA (#2). Não mexer num
   sem o outro.

O passo 1 é o único que muda comportamento com as flags desligadas — porque
`_destinatario_do_aviso` também é usado pelo fluxo velho. Vale rodar `test_nat_flow` e
`test_nat_recuperacao` depois.
