# 📞 Guia Completo: Implementação Twilio VoIP no Cenat Hub

**Documento técnico** com o passo a passo para implementar ligações VoIP via Twilio em uma aplicação FastAPI + Next.js, incluindo problemas encontrados e soluções aplicadas.

---

## Índice

1. [Visão Geral](#1-visão-geral)
2. [Pré-requisitos](#2-pré-requisitos)
3. [Configuração da Conta Twilio](#3-configuração-da-conta-twilio)
4. [Backend — FastAPI](#4-backend--fastapi)
5. [Frontend — Next.js](#5-frontend--nextjs)
6. [Deploy em Produção](#6-deploy-em-produção)
7. [Configuração do Número Twilio](#7-configuração-do-número-twilio)
8. [Google Drive — Upload de Gravações](#8-google-drive--upload-de-gravações)
9. [Problemas Encontrados e Soluções](#9-problemas-encontrados-e-soluções)
10. [Checklist de Verificação](#10-checklist-de-verificação)
11. [Referência de Endpoints](#11-referência-de-endpoints)
12. [Custos Estimados](#12-custos-estimados)

---

## 1. Visão Geral

### Arquitetura

```
┌──────────────────┐         ┌──────────────────────────┐
│   Browser        │         │   Twilio Cloud           │
│   (Next.js)      │         │                          │
│                  │         │  - Sinalização WebRTC    │
│  @twilio/voice-  │◄───────►│  - PSTN Gateway          │
│  sdk (npm)       │  WSS    │  - Gravação              │
│                  │         │  - TwiML Engine          │
└────────┬─────────┘         └────────────┬─────────────┘
         │ HTTPS                          │ Webhooks
         ▼                                ▼
┌──────────────────────────────────────────────────────┐
│                FastAPI Backend                        │
│                                                      │
│  /twilio/token          → Gera Access Token JWT      │
│  /twilio/voice          → TwiML para saída (browser) │
│  /twilio/voice-incoming → TwiML para entrada (PSTN)  │
│  /twilio/call-status    → Webhook status da chamada  │
│  /twilio/recording-status → Webhook da gravação      │
│  /twilio/recording/{sid}  → Proxy para ouvir áudio   │
│  /twilio/call-logs      → Histórico de ligações      │
└──────────────────────────────────────────────────────┘
```

### Funcionalidades

- Ligações de saída: browser → celular (PSTN)
- Ligações de entrada: celular → browser (WebRTC)
- Gravação automática de todas as chamadas
- Upload automático das gravações ao Google Drive
- Proxy de áudio (ouvir gravações sem login no Twilio)
- Histórico completo com duração, status e links
- Webphone flutuante + página dedicada de ligações

---

## 2. Pré-requisitos

| Requisito | Detalhes |
|-----------|----------|
| Conta Twilio | Com créditos (trial ou paga) |
| Número Twilio | Brasileiro (+55) com Voice habilitado |
| Regulatory Bundle | Obrigatório para números BR (documento + endereço) |
| Python 3.10+ | Backend FastAPI |
| Node.js 20+ | Frontend Next.js |
| HTTPS | Obrigatório para WebRTC e webhooks |

### Pacotes Python

```
twilio>=9.0.0
httpx
```

### Pacote NPM

```
@twilio/voice-sdk
```

> **IMPORTANTE:** NÃO use o SDK JS antigo via CDN (`twilio.min.js` v1.14). Ele usa Capability Tokens e é incompatível com Access Tokens modernos. Use SEMPRE o pacote npm `@twilio/voice-sdk` v2.x+.

---

## 3. Configuração da Conta Twilio

### 3.1 — Regulatory Bundle (Obrigatório para BR)

Números brasileiros exigem um Regulatory Bundle aprovado:

1. Acesse: **Console → Phone Numbers → Regulatory Compliance**
2. Crie um bundle do tipo **Individual** ou **Business**
3. Envie:
   - Documento de identidade (RG ou CNH)
   - Comprovante de endereço
4. Aguarde aprovação (pode levar de horas a dias)
5. Com bundle aprovado, compre o número em **Buy a Number**

### 3.2 — Comprar Número Brasileiro

1. **Console → Phone Numbers → Buy a Number**
2. País: Brazil
3. Capabilities: ✅ Voice (SMS opcional)
4. Selecione o DDD desejado
5. Vincule ao Regulatory Bundle aprovado

### 3.3 — Criar TwiML App

O TwiML App é necessário para ligações de saída (browser → PSTN):

1. **Console → Develop → Voice → TwiML Apps**
2. Clique **Create**
3. Nome: `cenat-hub-voice`
4. Voice Request URL: `https://seu-dominio.com/api/twilio/voice`
5. Método: `POST`
6. Salve e copie o **Application SID** (`APxxxxxxxx`)

### 3.4 — Criar API Key

A API Key é usada para gerar Access Tokens:

1. **Console → Account → API Keys & Tokens**
2. Clique **Create API Key**
3. Nome: `cenat-hub-voice`
4. Tipo: **Standard**
5. Copie o **SID** (`SKxxxxxxxx`) e o **Secret**

> **⚠️ ATENÇÃO:** O Secret só é mostrado uma vez! Se perder, crie uma nova key.

> **⚠️ PROBLEMA COMUM:** API Keys criadas pelo Console podem falhar com erro "JWT is invalid". Se isso acontecer, crie via API REST:
> ```bash
> curl -X POST "https://api.twilio.com/2010-04-01/Accounts/ACCOUNT_SID/Keys.json" \
>   -u "ACCOUNT_SID:AUTH_TOKEN" \
>   -d "FriendlyName=cenat-hub-voice"
> ```

### 3.5 — Variáveis de Ambiente

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_KEY_SID=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_TWIML_APP_SID=APxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+553123916801
```

---

## 4. Backend — FastAPI

### 4.1 — Modelo de Dados (SQLAlchemy)

```python
class CallLog(Base):
    __tablename__ = "call_logs"

    id = Column(Integer, primary_key=True, index=True)
    call_sid = Column(String, index=True)
    from_number = Column(String)
    to_number = Column(String)
    direction = Column(String)          # outbound | inbound
    status = Column(String)             # initiated | ringing | answered | completed | no-answer | busy | failed
    duration = Column(Integer, default=0)
    recording_url = Column(String, nullable=True)
    recording_sid = Column(String, nullable=True)
    drive_file_url = Column(String, nullable=True)
    user_id = Column(Integer, nullable=True)
    user_name = Column(String, nullable=True)
    contact_wa_id = Column(String, nullable=True)
    contact_name = Column(String, nullable=True)
    channel_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

### 4.2 — Rota: Gerar Token (`/twilio/token`)

```python
import unicodedata
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant

@router.get("/token")
async def get_voice_token(current_user=Depends(get_current_user)):
    # IMPORTANTE: Remover acentos do identity para evitar problemas no JWT
    clean_name = unicodedata.normalize('NFKD', current_user.name)\
        .encode('ascii', 'ignore').decode('ascii')
    identity = f"user_{current_user.id}_{clean_name.replace(' ', '_')}"

    token = AccessToken(
        TWILIO_ACCOUNT_SID,
        TWILIO_API_KEY_SID,
        TWILIO_API_KEY_SECRET,
        identity=identity,
        ttl=3600,
    )

    grant = VoiceGrant(
        outgoing_application_sid=TWILIO_TWIML_APP_SID,
        incoming_allow=True,
    )
    token.add_grant(grant)

    jwt_token = token.to_jwt()
    if isinstance(jwt_token, bytes):
        jwt_token = jwt_token.decode("utf-8")

    return {"token": jwt_token, "identity": identity}
```

### 4.3 — Rota: TwiML para Saída (`/twilio/voice`)

Chamada pelo TwiML App quando o browser inicia uma ligação:

```python
@router.post("/voice")
async def voice_twiml(request: Request):
    from twilio.twiml.voice_response import VoiceResponse, Dial

    form = await request.form()
    to = form.get("To", "")
    response = VoiceResponse()

    if to and to.startswith("+"):
        # Browser → Telefone
        dial = Dial(
            caller_id=TWILIO_PHONE_NUMBER,
            record="record-from-answer",
            recording_status_callback="https://seu-dominio.com/api/twilio/recording-status",
        )
        dial.number(
            to,
            status_callback="https://seu-dominio.com/api/twilio/call-status",
            status_callback_event="initiated ringing answered completed",
        )
        response.append(dial)
    elif to:
        # Browser → Browser (client)
        dial = Dial()
        dial.client(to)
        response.append(dial)
    else:
        response.say("Nenhum destino informado.", language="pt-BR")

    return Response(content=str(response), media_type="application/xml")
```

### 4.4 — Rota: TwiML para Entrada (`/twilio/voice-incoming`)

Chamada quando alguém liga para o número Twilio:

```python
@router.post("/voice-incoming")
async def voice_incoming_twiml(request: Request):
    from twilio.twiml.voice_response import VoiceResponse, Dial

    response = VoiceResponse()
    response.say("Aguarde enquanto conectamos sua ligação.", language="pt-BR")

    dial = Dial(
        record="record-from-answer",
        recording_status_callback="https://seu-dominio.com/api/twilio/recording-status",
        timeout=30,
    )
    # Identity do usuário que deve receber (mesmo nome usado no token)
    dial.client("user_1_Alefe_Lins")
    response.append(dial)

    # Se ninguém atender
    response.say("Desculpe, ninguém está disponível no momento.", language="pt-BR")

    return Response(content=str(response), media_type="application/xml")
```

### 4.5 — Webhook: Status da Chamada (`/twilio/call-status`)

```python
@router.post("/call-status")
async def call_status_webhook(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    status = form.get("CallStatus", "")
    duration = int(form.get("CallDuration", 0) or 0)

    async with async_session() as db:
        result = await db.execute(select(CallLog).where(CallLog.call_sid == call_sid))
        call_log = result.scalar_one_or_none()

        if call_log:
            call_log.status = status
            if duration > 0:
                call_log.duration = duration
        else:
            call_log = CallLog(
                call_sid=call_sid,
                from_number=form.get("From", ""),
                to_number=form.get("To", ""),
                direction="outbound" if form.get("Direction") == "outbound-dial" else "inbound",
                status=status,
                duration=duration,
            )
            db.add(call_log)
        await db.commit()

    return Response(content="OK", status_code=200)
```

### 4.6 — Webhook: Gravação (`/twilio/recording-status`)

> **NOTA IMPORTANTE:** O webhook de gravação envia o **Parent Call SID** (chamada do browser), mas o `call-status` salva o **Child Call SID** (chamada PSTN). A busca precisa considerar ambos.

```python
@router.post("/recording-status")
async def recording_status_webhook(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    recording_sid = form.get("RecordingSid", "")
    recording_url = form.get("RecordingUrl", "")
    recording_status = form.get("RecordingStatus", "")

    if recording_status == "completed" and recording_url:
        mp3_url = f"{recording_url}.mp3"
        async with async_session() as db:
            # Tentar buscar pelo call_sid direto
            result = await db.execute(select(CallLog).where(CallLog.call_sid == call_sid))
            call_log = result.scalar_one_or_none()

            if not call_log:
                # Fallback: buscar a chamada mais recente
                result = await db.execute(
                    select(CallLog).order_by(CallLog.id.desc()).limit(1)
                )
                call_log = result.scalar_one_or_none()

            if call_log:
                call_log.recording_sid = recording_sid
                call_log.recording_url = mp3_url
                # Upload ao Google Drive (opcional)
                try:
                    from app.google_drive import upload_recording_to_drive
                    drive_link = await upload_recording_to_drive(
                        recording_url=mp3_url,
                        call_sid=call_sid,
                        from_number=call_log.from_number,
                        to_number=call_log.to_number,
                        user_name=call_log.user_name or "Geral",
                        duration=call_log.duration or 0,
                    )
                    if drive_link:
                        call_log.drive_file_url = drive_link
                except Exception as e:
                    print(f"❌ Erro upload Drive: {e}")
                await db.commit()

    return Response(content="OK", status_code=200)
```

### 4.7 — Proxy de Gravação (`/twilio/recording/{sid}`)

As gravações Twilio exigem autenticação. Este proxy permite que o frontend acesse sem credenciais:

```python
@router.get("/recording/{recording_sid}")
async def stream_recording(recording_sid: str):
    """Proxy para servir gravações sem expor credenciais Twilio."""
    import httpx
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Recordings/{recording_sid}.mp3"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, auth=(account_sid, auth_token), follow_redirects=True)
        if resp.status_code != 200:
            return Response(content="Gravação não encontrada", status_code=404)
        return Response(
            content=resp.content,
            media_type="audio/mpeg",
            headers={"Content-Disposition": f"inline; filename={recording_sid}.mp3"}
        )
```

> **NOTA:** Esta rota NÃO tem autenticação (`Depends(get_current_user)`) porque o elemento `<audio>` do HTML não envia headers Authorization. Para segurança adicional, considere adicionar um token temporário na URL.

---

## 5. Frontend — Next.js

### 5.1 — Instalar SDK

```bash
npm install @twilio/voice-sdk
```

> **⚠️ NÃO use o CDN antigo** (`https://sdk.twilio.com/js/client/v1.14/twilio.min.js`). O SDK v1.14 usa Capability Tokens e é incompatível com Access Tokens.

### 5.2 — Webphone Component (Resumo)

```tsx
import { Device, Call } from '@twilio/voice-sdk';

// Inicializar Device
const device = new Device(twilioToken, {
  codecPreferences: [Call.Codec.Opus, Call.Codec.PCMU],
  closeProtection: true,
  logLevel: 1,
});

// Registrar para receber chamadas
await device.register();

// Eventos
device.on('registered', () => { /* pronto */ });
device.on('error', (err) => { /* erro */ });
device.on('incoming', (call) => { /* chamada recebida */ });

// Fazer chamada
const call = await device.connect({ params: { To: '+5531999999999' } });

// Eventos da chamada
call.on('ringing', () => { /* chamando */ });
call.on('accept', () => { /* em chamada */ });
call.on('disconnect', () => { /* desligou */ });

// Controles
call.mute(true/false);
call.disconnect();
```

### 5.3 — Reproduzir Gravações

Use o proxy do backend ao invés da URL direta do Twilio:

```tsx
// ❌ ERRADO: Exige login no Twilio
<source src={call.recording_url} type="audio/mpeg" />

// ✅ CERTO: Proxy sem autenticação
<source src={`https://seu-dominio.com/api/twilio/recording/${recordingSid}`} type="audio/mpeg" />

// Extrair recording_sid da URL:
const sid = recording_url.match(/Recordings\/(RE[^.]+)/)?.[1] || '';
```

### 5.4 — Inicialização Lazy

O AudioContext do browser só pode ser criado após interação do usuário. Inicialize o Device apenas quando o usuário clicar no botão do telefone:

```tsx
const handleDialerToggle = () => {
  setShowDialer(!showDialer);
  if (!deviceReady && !initStarted) {
    initDevice(); // Só inicializa no primeiro clique
  }
};
```

---

## 6. Deploy em Produção

### 6.1 — Variáveis de Ambiente no Servidor

```bash
# Adicionar ao backend/.env
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_API_KEY_SID=SKxxxxxxxx
TWILIO_API_KEY_SECRET=xxxxxxxx
TWILIO_TWIML_APP_SID=APxxxxxxxx
TWILIO_PHONE_NUMBER=+553123916801
```

### 6.2 — Criar Tabela no Banco

```python
from app.database import Base, engine
from app.models import *
import asyncio

async def create():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

asyncio.run(create())
```

### 6.3 — Instalar Dependências

```bash
# Backend
pip install twilio httpx

# Frontend
npm install @twilio/voice-sdk
```

### 6.4 — Rebuild e Restart

```bash
# Backend
sudo systemctl restart cenat-backend

# Frontend
cd frontend && npm run build && sudo systemctl restart cenat-frontend
```

---

## 7. Configuração do Número Twilio

### 7.1 — Chamadas de Entrada

No console Twilio (**Phone Numbers → seu número → Configure**):

| Campo | Valor |
|-------|-------|
| A call comes in | Webhook |
| URL | `https://seu-dominio.com/api/twilio/voice-incoming` |
| HTTP | POST |

### 7.2 — Status Callbacks

| Campo | Valor |
|-------|-------|
| Call status changes | `https://seu-dominio.com/api/twilio/call-status` |
| HTTP | POST |

### 7.3 — TwiML App (Chamadas de Saída)

No console (**Develop → Voice → TwiML Apps → seu app**):

| Campo | Valor |
|-------|-------|
| Voice Request URL | `https://seu-dominio.com/api/twilio/voice` |
| HTTP | POST |

---

## 8. Google Drive — Upload de Gravações

### 8.1 — Problema: Service Account sem Storage

Service Accounts não têm espaço no Google Drive. Solução:

1. Crie uma pasta no seu Google Drive pessoal (ex: `Gravações CENAT`)
2. Compartilhe com o email da Service Account (permissão: Editor)
3. Use o **ID da pasta** no código (hardcoded ou variável de ambiente)

### 8.2 — Scope Correto

```python
# ❌ ERRADO: Só acessa arquivos criados pelo app
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# ✅ CERTO: Acessa pastas compartilhadas
SCOPES = ["https://www.googleapis.com/auth/drive"]
```

### 8.3 — Folder ID Fixo

```python
# Ao invés de criar pasta dinâmica, use o ID da pasta compartilhada:
_folder_id = "1-xXfqt_pgwqSZwXCQO3LpTeAtXd_hmMl"  # ID da pasta no Drive
```

---

## 9. Problemas Encontrados e Soluções

### 9.1 — "JWT is invalid" (Código 31204)

**Causa:** API Key criada pelo Console pode ter problemas de ativação.

**Solução:** Criar API Key via REST API:
```bash
curl -X POST "https://api.twilio.com/2010-04-01/Accounts/AC.../Keys.json" \
  -u "AC...:AUTH_TOKEN" \
  -d "FriendlyName=nome-da-key"
```

### 9.2 — "JWT is invalid" com SDK v1.14

**Causa:** O SDK JavaScript v1.14 (via CDN) usa Capability Tokens, incompatíveis com Access Tokens gerados pelo Python SDK moderno.

**Solução:** Usar `@twilio/voice-sdk` via npm (v2.x+):
```bash
npm install @twilio/voice-sdk
```

### 9.3 — Acentos no Identity causam erro

**Causa:** Nomes como "Álefe" geram caracteres unicode no JWT que o Twilio não aceita.

**Solução:** Normalizar o nome removendo acentos:
```python
import unicodedata
clean_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
```

### 9.4 — AudioContext não inicia automaticamente

**Causa:** Navegadores modernos bloqueiam AudioContext sem interação do usuário.

**Solução:** Inicializar o Device apenas após clique (lazy init).

### 9.5 — Gravações não chegam ao webhook

**Causa:** O `recording_status_callback` envia o Parent Call SID, mas o banco armazena o Child Call SID.

**Solução:** Buscar pelo call_sid e, se não encontrar, usar fallback para o registro mais recente.

### 9.6 — Gravações pedem login do Twilio

**Causa:** URLs do formato `api.twilio.com/.../Recordings/RE...` exigem Basic Auth.

**Solução:** Criar proxy no backend que baixa o áudio e serve diretamente.

### 9.7 — Service Account sem quota no Drive

**Causa:** Service Accounts não têm espaço de armazenamento próprio.

**Solução:** Compartilhar pasta do Google Drive pessoal com a Service Account e usar scope `drive` (não `drive.file`).

### 9.8 — Chamadas de entrada tocam mensagem em inglês

**Causa:** Número Twilio configurado com URL padrão `https://demo.twilio.com/welcome/voice/`.

**Solução:** Alterar para `https://seu-dominio.com/api/twilio/voice-incoming`.

### 9.9 — numpy incompatível no servidor

**Causa:** `numpy==2.4.2` no requirements.txt não instala no Python 3.10.

**Solução:** Usar versão sem pin: `sed -i 's/numpy==2.4.2/numpy/' requirements.txt`

---

## 10. Checklist de Verificação

### Twilio Console

- [ ] Regulatory Bundle aprovado
- [ ] Número comprado com Voice habilitado
- [ ] TwiML App criado com URL correta
- [ ] API Key ativa (testar via REST)
- [ ] Número configurado: "A call comes in" → URL do voice-incoming
- [ ] Call status changes → URL do call-status

### Backend

- [ ] Variáveis de ambiente no `.env`
- [ ] Tabela `call_logs` criada
- [ ] Rota `/twilio/token` funcionando
- [ ] Rota `/twilio/voice` retornando TwiML
- [ ] Rota `/twilio/voice-incoming` retornando TwiML
- [ ] Rota `/twilio/call-status` recebendo webhooks
- [ ] Rota `/twilio/recording-status` recebendo webhooks
- [ ] Rota `/twilio/recording/{sid}` servindo áudio
- [ ] Identity sem acentos no token

### Frontend

- [ ] `@twilio/voice-sdk` instalado via npm
- [ ] Webphone com inicialização lazy
- [ ] Discador funcional
- [ ] Indicador de status (bolinha verde/cinza)
- [ ] Notificação de chamada recebida
- [ ] Player de gravação usando proxy

### Google Drive

- [ ] Pasta compartilhada com Service Account
- [ ] Scope `drive` (não `drive.file`)
- [ ] Folder ID fixo configurado
- [ ] `google-credentials.json` no servidor

---

## 11. Referência de Endpoints

| Método | Rota | Auth | Descrição |
|--------|------|------|-----------|
| GET | `/twilio/token` | JWT | Gera Access Token para o browser |
| POST | `/twilio/voice` | — | TwiML para chamadas de saída |
| POST | `/twilio/voice-incoming` | — | TwiML para chamadas de entrada |
| POST | `/twilio/call-status` | — | Webhook: status da chamada |
| POST | `/twilio/recording-status` | — | Webhook: gravação finalizada |
| GET | `/twilio/recording/{sid}` | — | Proxy para reproduzir gravação |
| GET | `/twilio/call-logs` | JWT | Listar histórico de ligações |

---

## 12. Custos Estimados

| Item | Custo |
|------|-------|
| Número brasileiro (mensal) | ~US$ 6,00 |
| Ligação de saída (por minuto) | ~US$ 0,04 |
| Ligação de entrada (por minuto) | ~US$ 0,01 |
| Gravação (por minuto) | ~US$ 0,0025 |
| Armazenamento gravação (por mês, por GB) | Grátis (30 dias no Twilio) |

> Valores aproximados. Consulte [twilio.com/pricing](https://www.twilio.com/pricing) para valores atualizados.

---

**Última atualização:** 12/02/2026
**Autor:** Equipe CENAT Hub
