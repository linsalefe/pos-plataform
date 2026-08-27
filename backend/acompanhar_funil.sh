#!/usr/bin/env bash
# Acompanhamento em tempo real de UM lead atravessando o funil do agente.
#
#   ./acompanhar_funil.sh 11987654321            # tail do journald, filtrado
#   ./acompanhar_funil.sh 11987654321 --estado   # foto do banco, uma vez
#   ./acompanhar_funil.sh 11987654321 --watch    # foto do banco a cada 10s
#   ./acompanhar_funil.sh 11987654321 --preflight # o número está limpo? dá para abrir?
#
# Filtra pelas DUAS grafias do telefone (12 e 13 dígitos), porque a abertura pode nascer
# numa e o inbound chegar na outra — ver app/contatos.py.
set -uo pipefail
cd "$(dirname "$0")"

TEL="${1:-}"
MODO="${2:---tail}"
[ -z "$TEL" ] && { echo "uso: $0 <telefone> [--tail|--estado|--watch|--preflight]"; exit 1; }

set -a; . ./.env; set +a
export PGPASSWORD=$(grep DATABASE_URL .env | sed -E 's#.*://[^:]+:([^@]+)@.*#\1#')

# As duas grafias, pela mesma função que o backend usa.
VARIANTES=$(PYTHONPATH="$PWD" venv/bin/python -c "
from app.qualificacao_gatilho import wa_id_de
from app.telefone import variantes_wa_id
w = wa_id_de('$TEL')
print(' '.join(variantes_wa_id(w) or [w]))
" 2>/dev/null)
[ -z "$VARIANTES" ] && { echo "telefone ilegível: $TEL"; exit 1; }
GREP_RE=$(echo "$VARIANTES" | tr ' ' '|')
IN_SQL=$(echo "$VARIANTES" | sed "s/[^ ]*/'&'/g" | tr ' ' ',')

echo "telefone $TEL  ->  grafias: $VARIANTES"

psql_() { psql -h localhost -U cenat -d cenat_whatsapp "$@"; }

estado() {
  echo "──────────────────────────────────────────── $(TZ=America/Sao_Paulo date '+%H:%M:%S') (SP)"
  psql_ -c "
    SELECT etapa, formacao, ano_conclusao, atuacao, left(motivacao,28) AS motivacao,
           agendamento_id AS ag
      FROM nat_qualificacao_state WHERE contact_wa_id IN ($IN_SQL);"
  psql_ -c "
    SELECT kind, status, to_char(run_at,'DD/MM HH24:MI:SS') AS run_at_sp,
           attempts, left(coalesce(motivo,''),34) AS motivo
      FROM nat_scheduled_actions WHERE contact_wa_id IN ($IN_SQL)
     ORDER BY id;"
  psql_ -c "
    SELECT direction AS dir, to_char(timestamp,'DD/MM HH24:MI:SS') AS hora_sp, status,
           coalesce(nat_etapa,'') AS etapa, left(replace(content,chr(10),' '),58) AS msg
      FROM messages WHERE contact_wa_id IN ($IN_SQL) ORDER BY timestamp;"
  psql_ -c "
    SELECT id, passo, lead_id, sub_source, to_char(slot_inicio,'DD/MM HH24:MI') AS slot,
           sales_rep_email
      FROM agendamentos WHERE regexp_replace(telefone,'\D','','g')
           LIKE '%'||right(regexp_replace('$TEL','\D','','g'),8) ORDER BY id;"
}

preflight() {
  echo "── PRÉ-VOO para $TEL ─────────────────────────────────────────────"
  psql_ -t -c "
    SELECT 'contato já existe: '||wa_id||' ('||coalesce(name,'sem nome')||')'
      FROM contacts WHERE wa_id IN ($IN_SQL);"
  psql_ -t -c "
    SELECT 'ESTADO DO AGENTE JÁ EXISTE: '||contact_wa_id||' etapa='||etapa
      FROM nat_qualificacao_state WHERE contact_wa_id IN ($IN_SQL);"
  psql_ -t -c "
    SELECT 'ação pendente: '||kind||' em '||to_char(run_at,'DD/MM HH24:MI')
      FROM nat_scheduled_actions
     WHERE contact_wa_id IN ($IN_SQL) AND status='pendente';"
  echo "(nenhuma linha acima = número limpo, o gatilho vai abrir)"
  echo
  psql_ -c "
    SELECT qualificacao_enabled AS agente_ligado, max_envios_hora AS teto,
           to_char(qualificacao_start_at,'DD/MM HH24:MI') AS corte_utc
      FROM nat_config WHERE id=1;"
  echo -n "hora (SP): $(TZ=America/Sao_Paulo date '+%H:%M %a')  ·  janela da abertura 09:00-18:30 seg-sex  ·  "
  TZ=America/Sao_Paulo python3 -c "
import datetime; a=datetime.datetime.now()
print('DENTRO' if a.weekday()<5 and datetime.time(9,0)<=a.time()<=datetime.time(18,30) else 'FORA — a abertura seria EMPURRADA')"
  curl -s https://hub.cenatdata.online/api/agendamento/slots \
    | python3 -c "
import json,sys
d=json.load(sys.stdin)
n=sum(len(v) for v in d['dias'].values())
print(f'slots livres na grade: {n}' + ('  ⚠️ POUCOS — a oferta precisa de pelo menos 1' if n<3 else ''))
for dia,l in d['dias'].items():
    print('   ', dia, ' '.join(x['hora'] for x in l))"
}

case "$MODO" in
  --preflight) preflight ;;
  --estado) estado ;;
  --watch)  while true; do clear; estado; sleep 10; done ;;
  --tail)
    echo "tail do cenat-backend — Ctrl-C para sair"
    echo "marcadores: 👤 contato · 🚀 abriu · 🧠 turno do LLM · 📅 ofertou · ✅ concluiu"
    echo "            ⏰ agendou ação · 🤝 silenciou · 🔒 bloqueado · ⚠️ ❌ problema"
    echo "───────────────────────────────────────────────────────────────────────────"
    # O `grep -v` do access log do uvicorn NÃO é cosmético: o Hub faz polling de
    # `/api/contacts/<wa>/messages` a cada 3s enquanto um SDR tiver a conversa aberta, e
    # essas linhas carregam o wa_id — afogariam a narração do funil no ruído.
    stdbuf -oL sudo journalctl -u cenat-backend -f -n 0 --output=short-iso \
      | stdbuf -oL grep --line-buffered -vE '\- "(GET|POST|OPTIONS|HEAD) /api/(contacts|nat|auth|notifications)' \
      | stdbuf -oL grep --line-buffered -E "$GREP_RE|🚀 Agente|📅 Agente|✅ Agente|🤝 Agente|🧠 LLM|NAT scheduler|🔒 Agente|❌ Meta recusou|⏳→✅|POST /webhook"
    ;;
  *) echo "modo desconhecido: $MODO"; exit 1 ;;
esac
