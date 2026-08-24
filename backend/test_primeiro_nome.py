"""Guardrail do primeiro nome nas mensagens automáticas.

Roda sem banco, sem rede e sem token: só exercita `app.nomes.primeiro_nome`.

    cd /home/ubuntu/pos-plataform/backend && venv/bin/python test_primeiro_nome.py

O problema: o `{{1}}` dos templates recebia o cadastro inteiro, e o lead lia
"Olá, Marina leite Guimaraes serra! 😊" — mensagem real, enviada em 24/08/2026.
"""
from app.nomes import primeiro_nome

falhas = []


def checa(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'ok' if ok else 'FALHOU'}] {rotulo}\n      obtido={obtido!r} esperado={esperado!r}")
    if not ok:
        falhas.append(rotulo)


print("\n1) Os casos exigidos pela sprint")
checa("nome completo minúsculo", primeiro_nome("marina leite guimaraes serra"), "Marina")
checa("tudo maiúsculo com acento", primeiro_nome("JOÃO"), "João")
checa("string vazia", primeiro_nome(""), "")
checa("espaços múltiplos", primeiro_nome("  ana    maria   souza  "), "Ana")
checa("nome de uma palavra", primeiro_nome("Ana"), "Ana")

print("\n2) Casos reais da base (medidos em messages/exact_leads)")
# Colhidos de mensagens que já saíram — ver o RECON de 24/08.
checa("Marina leite Guimaraes serra", primeiro_nome("Marina leite Guimaraes serra"), "Marina")
checa("Bruna Da Rosa Gonçalves", primeiro_nome("Bruna Da Rosa Gonçalves"), "Bruna")
checa("Diana Sales Lima de Araújo", primeiro_nome("Diana Sales Lima de Araújo"), "Diana")
checa("Valeriana Jesus Santos", primeiro_nome("Valeriana Jesus Santos"), "Valeriana")

print("\n3) Capitalização por pedaço (hífen e apóstrofo)")
checa("hifenizado minúsculo", primeiro_nome("maria-clara souza"), "Maria-Clara")
checa("hifenizado maiúsculo", primeiro_nome("ANA-LUÍZA DA SILVA"), "Ana-Luíza")
checa("apóstrofo reto", primeiro_nome("d'ávila neto"), "D'Ávila")
checa("apóstrofo tipográfico", primeiro_nome("d’ávila neto"), "D’Ávila")

print("\n4) Entrada suja — o token cego (split()[0]) erraria aqui")
checa("número antes do nome", primeiro_nome("123 Ana"), "Ana")
checa("traço solto antes do nome", primeiro_nome("- Maria"), "Maria")
checa("só pontuação e número", primeiro_nome("123"), "123")
checa("só espaços", primeiro_nome("   "), "   ")

print("\n5) Tipos inesperados — nunca levanta, nunca devolve não-string")
checa("None", primeiro_nome(None), "")
checa("int", primeiro_nome(12345), "")
checa("lista", primeiro_nome(["Ana"]), "")

print("\n6) Idempotência: aplicar duas vezes não muda o resultado")
for bruto in ["marina leite guimaraes serra", "JOÃO", "maria-clara souza", "Ana", "123", ""]:
    uma = primeiro_nome(bruto)
    checa(f"idempotente para {bruto!r}", primeiro_nome(uma), uma)

print("\n7) Sanidade: a saída nunca tem espaço e nunca é mais longa que a entrada")
for bruto in ["marina leite guimaraes serra", "Bruna Da Rosa Gonçalves", "ANA-LUÍZA DA SILVA",
              "d'ávila neto", "Ana", "123 Ana"]:
    saida = primeiro_nome(bruto)
    checa(f"sem espaço em {bruto!r}", " " in saida, False)
    checa(f"não cresce em {bruto!r}", len(saida) <= len(bruto), True)

print("\n" + "=" * 70)
if falhas:
    print(f"❌ {len(falhas)} teste(s) falharam:")
    for f in falhas:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ Todos os testes passaram.")
