# 📞 Guia: Sistema de Gravação de Ligações — CENAT HUB

## Visão Geral

As gravações de ligações via Twilio são salvas **localmente no servidor** (disco) e servidas pelo próprio backend FastAPI. Não utilizamos Google Drive ou qualquer storage externo para gravações.

---

## Arquitetura

```
Twilio (ligação finalizada)
    └── POST /api/twilio/recording-status (webhook)
        ├── Baixa o MP3 da API Twilio
        ├── Salva em /home/ubuntu/pos-plataform/recordings/{call_sid}.mp3
        └── Atualiza CallLog no banco (local_recording_path, transcription_status)

Frontend
    └── GET /api/twilio/recording/{call_sid}
        └── Serve o arquivo MP3 via FileResponse
```

---

## Banco de Dados

### Campos relevantes na tabela `call_logs`

| Campo | Tipo | Descrição |
|---|---|---|
| `call_sid` | VARCHAR(100) | SID principal da ligação |
| `recording_sid` | VARCHAR(100) | SID da gravação no Twilio |
| `recording_url` | TEXT | URL original da gravação no Twilio |
| `local_recording_path` | VARCHAR(500) | Caminho do arquivo no disco |
| `transcription` | TEXT | Transcrição gerada pelo Whisper |
| `transcription_insights` | TEXT | Insights gerados pelo GPT-4o |
| `transcription_status` | VARCHAR(30) | `pending`, `processing`, `done`, `error` |

### Migration

```python
ALTER TABLE call_logs 
ADD COLUMN IF NOT EXISTS local_recording_path VARCHAR(500),
ADD COLUMN IF NOT EXISTS transcription TEXT,
ADD COLUMN IF NOT EXISTS transcription_insights TEXT,
ADD COLUMN IF NOT EXISTS transcription_status VARCHAR(30);
```

---

## Problema: Parent vs Child Call SID

### Contexto
O Twilio gera múltiplos SIDs para uma mesma ligação (legs separados). O webhook de gravação pode chegar com um SID diferente do SID salvo no banco pelo webhook de status.

### Solução implementada: Match por tempo

Quando o `call_sid` do webhook de gravação não é encontrado no banco, buscamos o CallLog mais próximo pela data de criação (janela de ±60 segundos):

```python
# Busca o timestamp da call na API do Twilio
call_resp = await client.get(
    f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls/{call_sid}.json",
    auth=(account_sid, auth_token),
)
call_data = call_resp.json()
date_created = call_data.get("date_created", "")
dt = datetime.strptime(date_created, "%a, %d %b %Y %H:%M:%S +0000")

# Match por tempo no banco
result = await db.execute(
    select(CallLog).where(
        CallLog.created_at.between(dt - 30s, dt + 60s)
    ).order_by(CallLog.created_at.desc()).limit(1)
)
```

> ⚠️ **Importante:** Não usar `parent_call_sid` da API do Twilio — em ligações WebRTC (browser), esse campo retorna `None`.

---

## Endpoints

### `GET /api/twilio/recording/{call_sid}`
Serve o arquivo de áudio MP3 salvo localmente.

- Busca o `local_recording_path` no banco pelo `call_sid`
- Fallback: tenta `/recordings/{call_sid}.mp3` diretamente no disco
- Retorna 404 se não encontrado

### `DELETE /api/twilio/recording/{call_sid}`
Apaga o arquivo do disco e limpa os campos no banco.

- Requer autenticação
- Remove o arquivo físico
- Seta `local_recording_path = NULL` e `transcription_status = NULL`

---

## Backfill de gravações existentes

Se houver arquivos no disco sem vínculo no banco, usar o script:

```bash
cd ~/pos-plataform/backend
source venv/bin/activate
set -a && source .env && set +a
python backfill_recordings.py
```

O script:
1. Lista todos os `.mp3` em `/recordings/`
2. Tenta achar o CallLog pelo `call_sid` direto
3. Fallback: busca o CallLog mais próximo por timestamp via API Twilio
4. Atualiza `local_recording_path` e `transcription_status = 'pending'`

---

## Deploy

```bash
# Backend
cd ~/pos-plataform
git pull
sudo systemctl restart cenat-backend

# Frontend
cd ~/pos-plataform/frontend
git pull
npm run build
sudo systemctl restart cenat-frontend
```

---

## Lições aprendidas

1. **Nunca usar o cliente Twilio síncrono dentro de funções async** — trava o event loop. Usar `httpx.AsyncClient` para todas as chamadas à API Twilio.
2. **`parent_call_sid` não é confiável** em chamadas WebRTC — retorna `None`. Usar match por tempo como fallback.
3. **Variáveis de ambiente** não são carregadas automaticamente ao rodar scripts Python diretamente. Usar `set -a && source .env && set +a` antes de executar.
4. **Áudio em banco é má prática** — sempre salvar arquivos no disco e guardar apenas o caminho no banco.
