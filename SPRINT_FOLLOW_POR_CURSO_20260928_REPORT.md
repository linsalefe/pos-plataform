# SPRINT_FOLLOW_POR_CURSO_20260928 — Follow 3 e Follow 4 com template por pós

Branch `follow-por-curso`. **Aprovado no checkpoint com três ajustes (§6), mergeado e no ar.**
**Em produção (§7): 18 Follow 4 por variante, 12 entregues, 0 erro de template; F3 ainda sem entrada.**
As seções 1 a 5 descrevem o estado do checkpoint. **O que vale em produção é o §6**: Enfermagem
voltou ao F4 com `pt_PT`, o F4 de Trabalhador é `f4_audioorgtrabalho`, e há aliases e três
cursos a mais.
Os testes foram escritos e não executados (critério 6). O que rodou: `py_compile` e uma carga
do JSON por `follow_estagio_mapa.carregar()`, que é só leitura.

## TL;DR

- **Os 20 nomes do mapa existem no WABA**, todos `APPROVED`, com um `{{1}}` só e botão URL
  estático. O pedido fala em "18 nomes", mas o mapa tem 10 + 10 = 20.
- **CONTRADIZ (1): `f4_audiosmenfermagem` está em `pt_PT`.** O envio usa `pt_BR` fixo
  (`follow_estagio.IDIOMA`). Ficou **fora do mapa**: Enfermagem em Saúde Mental cai no
  `mensagem_follow4` no degrau 4. O F3 dela (`f3_guiaenfermagemsm`, pt_BR) está no mapa.
- **CONTRADIZ (2): nenhum dos quatro corpos de Trabalhador cita "Saúde Mental do Trabalhador"
  nem a turma.** Os corpos são genéricos; só o link do botão muda. Mantive a escolha do mapa
  (`f3_guiatrabalhot3`, `f4_audiosmtrabalho`) pelo conteúdo do link (§2).
- **CONTRADIZ (3), sobre o alcance:** o mapa casa pelo `sub_source` **da LP** ("Pos X"). As
  grafias legadas do mesmo curso (`posinfantoead`, `PosPsicologiaEscolar`, `PosGraduacaoTEA`…)
  caem no genérico. Dos 34 leads hoje em Follow 3/4, 30 casam e 4 não.

---

## 1. Critério 3: os templates no WABA (ao vivo, 28/09)

`GET /{waba}/message_templates` no WABA `1360246076143727`, com os mesmos `fields` e a mesma
paginação de `routes.py:750-775`: **90 templates**. Leitura apenas.

| degrau | sub_source | template | status | idioma | vars do corpo | botão | no mapa? |
|---|---|---|---|---|---|---|---|
| F3 | Pos Enfermagem em Saude Mental | f3_guiaenfermagemsm | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F3 | Pos Infantojuvenil EAD | f3_siteinfantoead | APPROVED | pt_BR | `{{1}}` | URL estática (site) | ✅ |
| F3 | Pos Psicologia Escolar | f3_guiaescolar | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F3 | Pos Psicologia na RAPS T3 | f3_guiarapst3 | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F3 | PosMulheridades | f3_guiamulheridades | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F3 | Pos Grupos e Oficinas T2 | f3_guiagrupot2 | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F3 | Pos TEA V3 | f3_guiatea | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F3 | Pos Gestao Psicossocial T5 | f3_guiagestaot5 | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F3 | Pos Suicidio e Luto T3 | f3_guiasuicidiot3 | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F3 | Pos Saude do Trabalhador | f3_guiatrabalhot3 | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F4 | Pos Enfermagem em Saude Mental | f4_audiosmenfermagem | APPROVED | **pt_PT** | `{{1}}` | URL estática (Drive) | ❌ **CONTRADIZ** |
| F4 | Pos Infantojuvenil EAD | f4_audioinfantoead | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F4 | Pos Psicologia Escolar | f4_audiopsiescolar | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F4 | Pos Psicologia na RAPS T3 | f4_audioraps | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F4 | PosMulheridades | f4_audiomulheridades | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F4 | Pos Grupos e Oficinas T2 | f4_audiogrupot2 | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F4 | Pos TEA V3 | f4_audiotea | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F4 | Pos Gestao Psicossocial T5 | f4_audiogestaot5 | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F4 | Pos Suicidio e Luto T3 | f4_audiosuicidiot3 | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| F4 | Pos Saude do Trabalhador | f4_audiosmtrabalho | APPROVED | pt_BR | `{{1}}` | URL estática (Drive) | ✅ |
| genérico F3 | — | mensagem_follow3 | APPROVED | pt_BR | `{{1}}`, `{{2}}` | nenhum | fallback |
| genérico F4 | — | mensagem_follow4 | APPROVED | pt_BR | `{{1}}` | nenhum | fallback |

Nenhum dos 20 tem `HEADER` (mídia). O botão é `URL` sem `{{`, ou seja, está na definição do
template e não pede componente no envio (RECON_FOLLOW_AUTOMATICO §3.3).

### CONTRADIZ: `f4_audiosmenfermagem` é `pt_PT`

Na Meta, o template é identificado por **nome + idioma**. Enviado com `language.code=pt_BR`,
um template que só existe em `pt_PT` é recusado com #132001 ("template name does not exist in
the translation"). O `IDIOMA = "pt_BR"` de `follow_estagio.py:134` é fixo para todo degrau.
Ficou fora do mapa, até decisão, por uma destas duas saídas:

- **(a)** recriar o template em `pt_BR` no Gerenciador (sem código; entra no mapa depois);
- **(b)** o mapa ganhar idioma por variante (`"por_curso": {"X": {"template": …, "idioma": "pt_PT"}}`)
  e o payload passar a usá-lo. É mudança de código pequena, fora do escopo desta sprint.

### Pós sem variante no mapa: o que o WABA tem

Psicologia Clínica T2, Psicologia Hospitalar, Álcool e Drogas T4 e Direitos Humanos T4: **nenhum
`f3_`/`f4_` para elas.** O WABA tem outros quatro pares, de cursos fora dessa lista e fora do
mapa por não terem sido pedidos. Reporto e não incluo:

| par | curso (pelo link) | leads no 18535 com sub_source da família |
|---|---|---|
| `f3_guiabpead` / `f4_audiobpead` | Boas Práticas EAD | `PosBoasPraticasEAD` 111 (1 hoje em F3/F4) |
| `f3_guiaeconomia` / `f4_audioeconomia` | Economia Solidária | `PosGraduacaoEconomiaSolidariaTurma1` 113 |
| `f3_guiapraticadialogica` / `f4_audiopraticadialogica` | Práticas Dialógicas | `PosPraticasDialogicasTurma1` 37 |
| `f3_sitetrabalhadort1` / `f4_audioorgtrabalho` | Trabalhador (ver §2) | — |

---

## 2. Critério 4: Saúde do Trabalhador

Os quatro corpos, verbatim:

**`f3_guiatrabalhot3`** (pt_BR), botão "Ementa da Pós" →
`drive.google.com/file/d/1WJYrT6ehn6w8yWTPSDI24W6jW4xuhJf3`
> Olá {{1}}, tudo bem? ✨
> Segue abaixo o link de acesso à ementa da Pós-Graduação para você conferir os detalhes do curso 🙏
>
> Me conta o melhor horário para conversarmos? Assim daremos sequência ao seu processo seletivo!

**`f3_sitetrabalhadort1`** (pt_BR), botão "Ementa da Pós" →
`posmdotrabalhadort3.cenatsaudemental.com/#curriculum`
> Olá {{1}}, tudo bem? 🌻
> Segue abaixo o link de acesso à ementa da Pós-Graduação para você conferir os detalhes do curso 🙏
>
> Me conta o melhor horário para conversarmos? Assim daremos sequência ao seu processo seletivo!

**`f4_audiosmtrabalho`** (pt_BR), botão "Àudio do Coordenador" →
`drive.google.com/file/d/1Jr0GY3B5q3dVZTzlHcN2OJBSy4IRDrVX`
> Olá {{1}}, ☺️Realizei mais uma tentativa de contato, porém não tive sucesso.
>
> Segue o áudio do coordenador com informações importantes sobre a Pós ! é só clicar no botão abaixo para ouvir! 🎧
> Fico no aguardo do seu retorno 🌻

**`f4_audioorgtrabalho`** (pt_BR), botão "Áudio do Coordenador" →
`drive.google.com/file/d/1Jr0GY3B5q3dVZTzlHcN2OJBSy4IRDrVX` (**o mesmo arquivo**)
> Olá {{1}} ☺️  Realizei mais uma tentativa de contato, porém não tive sucesso.
> Segue o áudio do coordenador com informações importantes sobre a Pós ! é só clicar no botão abaixo para ouvir! 🎧
> Fico no aguardo do seu retorno 🌻

**CONTRADIZ o critério 4 como escrito:** nenhum corpo cita "Saúde Mental do Trabalhador" nem a
turma. Não dá para escolher pelo corpo. Olhei o que o botão abre (título público da página,
GET simples):

| link | título |
|---|---|
| Drive `1WJYrT…` (f3_guiatrabalhot3) | `2026_SM nas Organizações e no Trabalho.pdf` |
| site `posmdotrabalhadort3…` (f3_sitetrabalhadort1) | `Pós-Graduação em Boas Práticas em Saúde Mental nas Organizações e no Trabalho — CENAT` |
| Drive `1Jr0GY…` (os dois F4) | `Pós Saúde Mental nas Organizações - Áudio da Coordenação - Thiago Ramos.MP3` |

**Escolha: a do mapa, `f3_guiatrabalhot3` e `f4_audiosmtrabalho`.**

- **F4:** os dois abrem o mesmo áudio, então a escolha não muda o que o lead ouve.
  `f4_audiosmtrabalho` tem "Àudio" com crase no botão; `f4_audioorgtrabalho` tem a grafia
  certa. Trocar é só mudar uma string no JSON.
- **F3:** os dois são do curso atual. O Drive é o PDF "2026_", o site é a página da turma
  (`…t3`, apesar do nome `…t1` do template). Fiquei com o PDF porque é o mesmo formato (guia no
  Drive) dos outros nove F3 do mapa.

Todos os três links falam em **"Saúde Mental nas Organizações e no Trabalho"**. O
`course_aliases` chama `Pos Saude do Trabalhador` de "Saúde Mental do Trabalhador". Se o curso
foi renomeado, o `{{2}}` do genérico `mensagem_follow3` já usa o nome antigo: é uma observação,
não algo desta sprint.

---

## 3. CONTRADIZ: o mapa só casa a grafia da LP

`por_curso` é chaveado por `sub_source` (sem caixa, sem espaço nas pontas), como pede o
critério 2. Mas o mesmo curso tem várias grafias em `exact_leads` (funil 18535, 28/09):

| curso | casa com o mapa | grafias legadas (caem no genérico) |
|---|---|---|
| Infantojuvenil EAD | `Pos Infantojuvenil EAD` (8) | `posinfantoead` (23, **3 hoje em F3/F4**) |
| Psicologia Escolar | `Pos Psicologia Escolar` (26) | `PosPsicologiaEscolar` (53) |
| TEA | `Pos TEA V3` (44) | `PosGraduacaoTEA` (86) |
| Enfermagem SM | `Pos Enfermagem em Saude Mental` (26) | `posenfermagemsm` (19) |
| RAPS | `Pos Psicologia na RAPS T3` (11) | `PosPsicologianaRAPST3` (24) |
| Trabalhador | `Pos Saude do Trabalhador` (51) | `PosSMTrabalhadorT3` (46), `possmdotrabalhador` (124), `SMtrabalhador` (170) |
| Suicídio e Luto T3 | `Pos Suicidio e Luto T3` (6) | `PosAutolesaoComportamentoSuicidaeLutoTurma3` (327) |
| Gestão T5 | `Pos Gestao Psicossocial T5` (9) | `PosGestaoAvaliacaoePlanejamentoTurma5` (77) |
| Grupos e Oficinas T2 | `Pos Grupos e Oficinas T2` (95) | `posgruposeoficinasturma2` (73) |

**Hoje em Follow 3/4: 34 leads, 30 casam e 4 vão para o genérico** (3 `posinfantoead`, 1
`PosBoasPraticasEAD`). Como a entrada nova vem da LP, a cobertura tende a subir. Incluir as
grafias legadas é só acrescentar chaves ao `por_curso`. Não fiz, porque decidir que
`possmdotrabalhador` é a mesma turma de `Pos Saude do Trabalhador` é decisão de produto.

---

## 4. O que mudou

### `backend/follow_estagios.json`
`129983` ganhou `por_curso` (10) + `params_por_curso: ["nome"]`; `129955` ganhou `por_curso`
(**9**, sem Enfermagem) + `params_por_curso: ["nome"]`. `template`/`params` genéricos
intactos. Os outros sete: sem mudança.

### `backend/app/follow_estagio_mapa.py`
- `_validar_por_curso`: valida no **carregamento**. Recusa `por_curso` vazio, variante vazia,
  chave repetida que só difere na caixa, `por_curso` sem `params_por_curso` (e o inverso) e
  parâmetro inválido.
- `resolver(entrada, sub_source) -> (template, params)`: `por_curso[sub_source.strip().lower()]`,
  senão o genérico. `None`, vazio ou não-string vão para o genérico. É a única regra de escolha.
- `montar_mappings` passa a usar os `params` de `resolver` (variante: só `nome`), inclusive na
  checagem de `sdr`.

### `backend/app/follow_estagio.py` (critério 5)
- `_enfileirar`: a linha nasce com o template **resolvido** para o `sub_source` do evento.
- `_enviar_uma`: resolve de novo com o lead **relido** e manda esse `template_name`.
  `_finalizar` ganhou `template=`, e a linha é **regravada com o template efetivo** em todo
  desfecho a partir daí: enviado, skipped da rota e falhou. O `print` e a **observação na
  Exact** (`texto_nota_follow`) citam esse nome.

### Testes
- `test_follow_por_curso.py` (novo, **não executado**) cobre: variante encontrada; fora do
  mapa → genérico; grafia legada → genérico; caixa e espaço; `None`, vazio e não-string;
  `montar_mappings` com 1 e 2 params; os sete degraus inalterados; o carregamento recusando
  JSON torto; `_enfileirar` e `_enviar_uma` gravando o template efetivo, com o payload, a
  linha e a nota.
- `test_follow_estagio.py` §2: o laço de parâmetros passou a usar
  `Lead(sub_source="Pos Psicologia Clinica T2")`. Com o `Lead()` padrão (`PosMulheridades`),
  o Follow 3 agora resolveria a variante e a asserção de `nome`+`curso` quebraria. Continua
  provando o genérico.

### `py_compile`
```
venv/bin/python -m py_compile app/follow_estagio_mapa.py app/follow_estagio.py \
    test_follow_por_curso.py test_follow_estagio.py        -> OK
```
Carga do JSON por `carregar()`: `129983` com 10 variantes, `129955` com 9, ambos com
`params_por_curso=['nome']`; `resolver(F3, 'pos tea v3') = ('f3_guiatea', ['nome'])`.

### Diff de `follow_estagio.py`
```diff
diff --git a/backend/app/follow_estagio.py b/backend/app/follow_estagio.py
index 3a8d674..750e2a8 100644
--- a/backend/app/follow_estagio.py
+++ b/backend/app/follow_estagio.py
@@ -100,7 +100,7 @@ from sqlalchemy import select, text, update
 
 from app.database import async_session
 from app.follow_estagio_mapa import (MapaInvalido, estagio_para, estagios_do_mapa,
-                                     funil_alvo, montar_mappings)
+                                     funil_alvo, montar_mappings, resolver)
 from app.models import (FE_ENVIADO, FE_FALHOU, FE_PENDENTE, FE_SKIPPED, ExactLead,
                         FollowEstagioEnvio)
 from app.telefone import chave_telefone
@@ -315,6 +315,9 @@ async def _enfileirar(db, evento, entrada, permitidos: frozenset[str]) -> str:
         _, motivo = montar_mappings(entrada, evento)
 
     status = FE_SKIPPED if motivo else FE_PENDENTE
+    # O template EFETIVO deste lead (variante da pós ou genérico), não o genérico do degrau.
+    # `_enviar_uma` resolve de novo com o lead relido e regrava se o `sub_source` mudou.
+    template, _ = resolver(entrada, evento.get("sub_source"))
 
     # `ON CONFLICT (lead_exact_id, estagio_id) DO NOTHING` — a UNIQUE é quem decide. Ver a
     # seção acima sobre por que não há SELECT antes.
@@ -328,7 +331,7 @@ async def _enfileirar(db, evento, entrada, permitidos: frozenset[str]) -> str:
         RETURNING id
     """), {"lead_exact_id": lead_exact_id, "telefone": telefone,
            "estagio_id": entrada["estagio_id"], "estagio_nome": entrada["nome"],
-           "template": entrada["template"], "evento_id": evento["evento_id"],
+           "template": template, "evento_id": evento["evento_id"],
            "status": status, "motivo": motivo})).first()
 
     if criado is None:
@@ -342,7 +345,7 @@ async def _enfileirar(db, evento, entrada, permitidos: frozenset[str]) -> str:
         return FE_SKIPPED
 
     print(f"➕ follow #{criado[0]}: lead {lead_exact_id} ({evento['lead_nome']!r}) entrou em "
-          f"{entrada['nome']!r} — '{entrada['template']}' enfileirado")
+          f"{entrada['nome']!r} — '{template}' enfileirado")
     return FE_PENDENTE
 
 
@@ -416,7 +419,8 @@ async def _pendentes(db, limite: int) -> list:
 
 
 async def _finalizar(db, linha_id: int, *, status: str, motivo: str | None = None,
-                     resposta: str | None = None, enviado_em: datetime | None = None) -> None:
+                     resposta: str | None = None, enviado_em: datetime | None = None,
+                     template: str | None = None) -> None:
     """Grava o desfecho por UPDATE explícito, não por atributo do ORM.
 
     Mesma razão de `rd_sender._finalizar` e `nat_scheduler._finalizar`: este código roda depois
@@ -437,6 +441,8 @@ async def _finalizar(db, linha_id: int, *, status: str, motivo: str | None = Non
         valores["resposta"] = resposta[:LIMITE_RESPOSTA]
     if enviado_em is not None:
         valores["enviado_em"] = enviado_em
+    if template is not None:
+        valores["template"] = template
     await db.execute(update(FollowEstagioEnvio)
                      .where(FollowEstagioEnvio.id == linha_id).values(**valores))
 
@@ -492,7 +498,7 @@ async def _enviar_uma(db, linha) -> str:
     ==========================================================================================
     O PAYLOAD, CAMPO POR CAMPO
     ==========================================================================================
-        template_name   do mapa
+        template_name   `resolver(entrada, lead.sub_source)`: variante da pós ou genérico
         language        "pt_BR"
         channel_id      1 (o único canal)
         lead_ids        [lead.id]  <- PK LOCAL de exact_leads, NÃO o exact_id
@@ -546,13 +552,18 @@ async def _enviar_uma(db, linha) -> str:
                          motivo="o lead saiu de exact_leads entre o enfileiramento e o envio")
         return FE_SKIPPED
 
+    # Variante da pós (Follow 3 e 4) ou genérico, pelo `sub_source` de AGORA. É gravado na
+    # linha em todo desfecho a partir daqui: a coluna tem de dizer o que foi (ou teria sido)
+    # enviado, não o que se previa no enfileiramento.
+    template, _ = resolver(entrada, lead.sub_source)
+
     mappings, motivo = montar_mappings(entrada, lead)
     if motivo:
-        await _finalizar(db, linha.id, status=FE_SKIPPED, motivo=motivo)
+        await _finalizar(db, linha.id, status=FE_SKIPPED, motivo=motivo, template=template)
         return FE_SKIPPED
 
     payload = {
-        "template_name": entrada["template"],
+        "template_name": template,
         "language": IDIOMA,
         "channel_id": CANAL_ID,
         "lead_ids": [lead.id],
@@ -571,7 +582,7 @@ async def _enviar_uma(db, linha) -> str:
         # horas depois do arrasto do card já não é o follow daquele momento. O motivo fica
         # gravado, que é o que permite decidir se vale um retry numa próxima sprint.
         await _finalizar(db, linha.id, status=FE_FALHOU,
-                         motivo=f"{type(e).__name__}: {e}")
+                         motivo=f"{type(e).__name__}: {e}", template=template)
         print(f"❌ follow #{linha.id}: lead {linha.lead_exact_id} em {linha.estagio_nome!r} — "
               f"{type(e).__name__}: {e}")
         return FE_FALHOU
@@ -579,10 +590,11 @@ async def _enviar_uma(db, linha) -> str:
     status, motivo = _desfecho_do_bulk(resultado)
     await _finalizar(db, linha.id, status=status, motivo=motivo,
                      resposta=json.dumps(resultado, ensure_ascii=False, default=str),
-                     enviado_em=_agora_utc() if status == FE_ENVIADO else None)
+                     enviado_em=_agora_utc() if status == FE_ENVIADO else None,
+                     template=template)
 
     if status == FE_ENVIADO:
-        print(f"✅ follow #{linha.id}: '{entrada['template']}' enviado para lead "
+        print(f"✅ follow #{linha.id}: '{template}' enviado para lead "
               f"{linha.lead_exact_id} ({lead.name!r}) em {linha.estagio_nome!r}")
         # 27/09: a observação na timeline do lead na Exact, onde o SDR trabalha. DEPOIS do
         # `_finalizar`: o UPDATE para `enviado` já está na transação, e `drenar` faz o commit
@@ -591,7 +603,7 @@ async def _enviar_uma(db, linha) -> str:
         from app.exact_notes import registrar_observacao
         await registrar_observacao(
             linha.lead_exact_id,
-            texto_nota_follow(linha.estagio_nome, entrada["template"], _agora_sp()))
+            texto_nota_follow(linha.estagio_nome, template, _agora_sp()))
     elif status == FE_SKIPPED:
         print(f"⏭️  follow #{linha.id}: lead {linha.lead_exact_id} em "
               f"{linha.estagio_nome!r} PULADO pelo disparo — {motivo}")
```
(`follow_estagio_mapa.py` e o JSON: ver o commit.)

---

## 5. Primeiros envios reais

Ver §7.

---

## 6. Ajustes do checkpoint (Álefe, 28/09)

1. **`language` opcional por template.**
   - No mapa, uma variante pode ser `"template"` (pt_BR) ou `{"template": …, "language": …}`.
     O estágio também aceita `language` para o genérico.
   - O formato é validado no carregamento (`^[a-z]{2,3}(_[A-Z]{2})?$`); `pt-BR` é recusado.
   - `resolver` devolve `(template, params, idioma)`, e o payload usa esse idioma. O
     `IDIOMA` fixo de `follow_estagio.py` saiu e o padrão ficou em
     `follow_estagio_mapa.IDIOMA_PADRAO = "pt_BR"`.
   - **`f4_audiosmenfermagem` voltou ao mapa com `pt_PT`.** A rota repassa `language` para o
     envio e para a leitura do corpo (`exact_routes.py:309,340`).
2. **Trabalhador no F4 = `f4_audioorgtrabalho`** (mesmo áudio, botão "Áudio" com a grafia certa).
3. **Aliases e cursos a mais.** As seis grafias existem em `exact_leads` do 18535:

   | sub_source | leads | F3 | F4 | por quê |
   |---|---|---|---|---|
   | `posinfantoead` | 23 | f3_siteinfantoead | f4_audioinfantoead | alias de Infantojuvenil EAD |
   | `PosGraduacaoTEA` | 86 | f3_guiatea | f4_audiotea | alias de TEA |
   | `possmdotrabalhador` | 124 | f3_guiatrabalhot3 | f4_audioorgtrabalho | alias de Trabalhador |
   | `PosBoasPraticasEAD` | 111 | f3_guiabpead | f4_audiobpead | curso próprio |
   | `PosGraduacaoEconomiaSolidariaTurma1` | 113 | f3_guiaeconomia | f4_audioeconomia | existe → incluído |
   | `PosPraticasDialogicasTurma1` | 37 | f3_guiapraticadialogica | f4_audiopraticadialogica | existe → incluído |

   Os seis templates novos são APPROVED, pt_BR, com um `{{1}}` e URL estática. Os títulos
   dos links conferem com o curso: "Guia_Pós TEA.pdf", "Boas Praticas - EAD 2026", "Guia
   Economia Solidária Arte e Cultura.pdf", "Guia_Práticas Dialógicas e Diálogo Aberto.pdf",
   e os áudios de coordenação de cada um.

**Mapa final: 16 chaves no F3 e 16 no F4.** Com ele, **34 de 34** leads hoje em Follow 3/4
resolvem uma variante. Esses leads já passaram pelo evento de entrada, então isto só mede
cobertura; o follow sai quando um lead ENTRA no estágio.

Continuam no genérico, fora do pedido: as outras grafias legadas (`PosPsicologiaEscolar`,
`PosSMTrabalhadorT3`, `SMtrabalhador`, `PosAutolesaoComportamentoSuicidaeLutoTurma3`…) e as
quatro pós sem template próprio.

Testes: `test_follow_por_curso.py` atualizado (idioma, aliases, cursos novos, `language`
inválido), **não executado**. `py_compile` OK nos quatro arquivos.

## 7. Deploy e primeiros envios reais

Merge `cda5180` em `main`, push, `cenat-backend` reiniciado em **28/09 20:08:34 UTC** (17:08 SP).
Janela observada: até 21:28 UTC (18:28 SP). Fontes: `follow_estagio_envios`, o journal
(`✅ follow #`, `📝 exact_note #`, `❌ Meta recusou`) e `messages`.

### Follow 4: 18 envios, todos por variante, nenhum no genérico

| # | lead | template | Meta | nota na Exact |
|---|---|---|---|---|
| 31 | 51968226 | f4_audiopsiescolar | delivered | ✅ |
| 32 | 51503724 | f4_audiogrupot2 | delivered | ✅ |
| 33 | 51429477 | f4_audioinfantoead | delivered | ✅ |
| 34 | 52013431 | f4_audioinfantoead | **failed 131026** | ✅ |
| 35 | 52008485 | f4_audiogrupot2 | delivered | ✅ |
| 36 | 52001613 | **f4_audiosmenfermagem (pt_PT)** | **delivered** | ✅ |
| 37 | 51991784 | **f4_audioorgtrabalho** | delivered | ✅ |
| 38 | 51970277 | f4_audiopsiescolar | **failed 131026** | ✅ |
| 39 | 51734704 | f4_audiopsiescolar | delivered | ✅ |
| 40 | 52034221 | f4_audiomulheridades | delivered | ✅ |
| 41 | 52013432 | f4_audiobpead | sent (sem retorno até 21:28) | ✅ |
| 42 | 52011405 | f4_audiopsiescolar | delivered | ✅ |
| 43 | 51972778 | f4_audiotea | delivered | ✅ |
| 44 | 52013425 | f4_audiotea | **failed 131050** (opt-out) | ✅ |
| 45 | 52004915 | f4_audiopsiescolar | **failed 131026** | ✅ |
| 46 | 51995974 | f4_audiopsiescolar | **failed 131026** | ✅ |
| 47 | 51980645 | f4_audiogrupot2 | delivered | ✅ |
| 49 | 51902367 | f4_audiopsiescolar | delivered | ✅ |

- **12 entregues, 1 aguardando, 5 falharam: 4 × 131026 (número não recebe) e 1 × 131050
  (opt-out).** São falhas do destinatário. Não houve nenhum erro de template (132xxx, parâmetro,
  idioma), e a Meta aceitou os 8 templates distintos.
- **O `pt_PT` funcionou:** o #36 (`f4_audiosmenfermagem`) foi `delivered`. O ajuste 1 do §6 está
  confirmado em produção.
- Cada observação na Exact cita o template efetivo, ex.:
  `[NAT] Follow 4 enviado pela IA em 28/09 18:02 (template f4_audiosmenfermagem).` (critério 5).
- Nos outros degraus nada mudou: Follow 1 (`mensagem_flow`), Follow 2 (`mensagens_flows2`) e
  Follows 5 (`mensagem_follow5`) saíram com o genérico de sempre.

### Follow 3: nenhum ainda

Nenhum lead entrou em Follow 3 desde o deploy. As 8 linhas de Follow 3 na tabela são de antes
das 20:08 e usaram o `mensagem_follow3`. **O primeiro F3 por variante ainda não foi observado.**

### CONTRADIZ: `messages` mostra `sent` para 4 das 5 falhas

O webhook `failed` chegou **antes** do commit da linha em `messages`, o que o log registra como
`[mensagem não encontrada no banco]`. A linha ficou `sent` para sempre. Isso atingiu os wamids do
#34, #45, #46 e também do #29 (Follow 1, **131049**). Nos quatro casos, a linha consta em
`messages` com `created_at` anterior ao webhook. `created_at` é a hora da transação, e o commit
só acontece depois do envio **e da nota na Exact** (até 5 s). A Meta devolve `failed` em ~1-2 s.

Não é defeito desta sprint: vale para todo envio de `follow_estagio` desde 27/09. **Quem ler
`messages.status` para medir o follow subconta as falhas.** A fonte confiável é o journal.
Não corrigido.
