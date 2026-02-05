# 🟢 Cenat Hub — Central de Atendimento Integrado

**Plataforma de multiatendimento via WhatsApp Business API** desenvolvida para o CENAT (Centro Educacional Novas Abordagens em Saúde Mental).

Permite que a equipe comercial gerencie leads, responda conversas em tempo real, envie templates personalizados e acompanhe métricas — tudo em um único painel web acessível de qualquer navegador.

---

## 📋 Índice

1. [Visão Geral](#-visão-geral)
2. [Arquitetura do Sistema](#-arquitetura-do-sistema)
3. [Tecnologias Utilizadas](#-tecnologias-utilizadas)
4. [Pré-requisitos](#-pré-requisitos)
5. [ETAPA 1 — Configuração do Meta Business](#-etapa-1--configuração-do-meta-business)
6. [ETAPA 2 — Configuração do Ambiente Local](#-etapa-2--configuração-do-ambiente-local)
7. [ETAPA 3 — Backend (FastAPI)](#-etapa-3--backend-fastapi)
8. [ETAPA 4 — Banco de Dados (PostgreSQL)](#-etapa-4--banco-de-dados-postgresql)
9. [ETAPA 5 — Frontend (Next.js)](#-etapa-5--frontend-nextjs)
10. [ETAPA 6 — Webhook (Receber Mensagens)](#-etapa-6--webhook-receber-mensagens)
11. [ETAPA 7 — Deploy em Produção (AWS Lightsail)](#-etapa-7--deploy-em-produção-aws-lightsail)
12. [ETAPA 8 — Configurar Templates do WhatsApp](#-etapa-8--configurar-templates-do-whatsapp)
13. [Funcionalidades](#-funcionalidades)
14. [Estrutura de Pastas](#-estrutura-de-pastas)
15. [Banco de Dados — Tabelas](#-banco-de-dados--tabelas)
16. [API — Endpoints](#-api--endpoints)
17. [Variáveis de Ambiente](#-variáveis-de-ambiente)
18. [Comandos Úteis](#-comandos-úteis)
19. [Solução de Problemas](#-solução-de-problemas)
20. [Licença](#-licença)

---

## 🔍 Visão Geral

O **Cenat Hub** é uma plataforma web completa de CRM e atendimento via WhatsApp Business API Cloud. A equipe comercial utiliza o painel para:

- Receber e responder mensagens de leads em tempo real
- Iniciar novas conversas enviando templates aprovados pelo Meta
- Gerenciar status de cada lead (Novo → Contato → Qualificado → Matriculado → Perdido)
- Organizar leads com tags e notas
- Operar múltiplos números de WhatsApp em um único painel
- Visualizar métricas no dashboard (total de conversas, leads novos, etc.)
- Receber e visualizar mídias (fotos, áudios, vídeos, documentos)

**URL de Produção:** `https://hub.cenatdata.online`

---

## 🏗 Arquitetura do Sistema

```
┌─────────────────────────────────────────────────────────┐
│                     NAVEGADOR                           │
│              (hub.cenatdata.online)                      │
│                  Next.js (React)                        │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTPS
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  NGINX (Reverse Proxy)                  │
│              SSL via Let's Encrypt                       │
│                                                         │
│  /           → Frontend (porta 3001)                    │
│  /api/       → Backend  (porta 8001)                    │
│  /webhook    → Backend  (porta 8001)                    │
└──────────┬──────────────────────┬───────────────────────┘
           │                      │
           ▼                      ▼
┌──────────────────┐   ┌──────────────────────────────────┐
│   Next.js App    │   │      FastAPI Backend              │
│   Porta 3001     │   │      Porta 8001                   │
│                  │   │                                    │
│  - Login         │   │  - REST API (/api/*)              │
│  - Dashboard     │   │  - Webhook WhatsApp (/webhook)    │
│  - Conversas     │   │  - Autenticação JWT               │
│  - Usuários      │   │  - Proxy de mídia                 │
└──────────────────┘   └──────────┬───────────────────────┘
                                  │
                                  ▼
                       ┌──────────────────┐
                       │   PostgreSQL     │
                       │   Porta 5432     │
                       │                  │
                       │  - contacts      │
                       │  - messages      │
                       │  - channels      │
                       │  - users         │
                       │  - tags          │
                       │  - contact_tags  │
                       └──────────────────┘

                    ┌──────────────────────┐
                    │  Meta / WhatsApp     │
                    │  Cloud API           │
                    │                      │
                    │  - Enviar mensagens  │
                    │  - Receber webhook   │
                    │  - Baixar mídias     │
                    │  - Templates         │
                    └──────────────────────┘
```

**Fluxo de uma mensagem recebida:**
1. Lead envia mensagem pelo WhatsApp
2. Meta envia POST para `https://hub.cenatdata.online/webhook`
3. Nginx encaminha para FastAPI (porta 8001)
4. Backend salva no PostgreSQL (contato + mensagem)
5. Frontend faz polling a cada 3 segundos e exibe no chat

**Fluxo de uma mensagem enviada:**
1. Atendente digita mensagem no chat
2. Frontend faz POST para `/api/send/text`
3. Backend envia via WhatsApp Cloud API
4. Meta entrega ao lead no WhatsApp
5. Backend salva mensagem no PostgreSQL

---

## 🛠 Tecnologias Utilizadas

| Camada | Tecnologia | Versão |
|--------|-----------|--------|
| **Frontend** | Next.js (React) | 15.x |
| **Estilização** | Tailwind CSS | 3.x |
| **Ícones** | Lucide React | latest |
| **HTTP Client** | Axios | latest |
| **Backend** | FastAPI (Python) | 0.100+ |
| **ORM** | SQLAlchemy (async) | 2.x |
| **DB Driver** | asyncpg | latest |
| **Banco de Dados** | PostgreSQL | 14+ |
| **Autenticação** | JWT (PyJWT) + bcrypt | — |
| **HTTP (backend)** | httpx | latest |
| **WhatsApp API** | Meta Cloud API | v22.0 |
| **Servidor Web** | Nginx | 1.18 |
| **SSL** | Certbot (Let's Encrypt) | auto |
| **Hospedagem** | AWS Lightsail | Ubuntu 22.04 |
| **Controle de versão** | Git + GitHub | — |

---

## ✅ Pré-requisitos

Antes de começar, você precisa ter:

- **Conta Meta Business** verificada (business.facebook.com)
- **App Meta Developers** com produto WhatsApp configurado
- **Número de telefone** vinculado ao WhatsApp Business API
- **Conta AWS** (para hospedagem em produção)
- **Domínio** apontando para o IP do servidor
- **Git e GitHub** configurados na máquina local
- **Node.js 20+** instalado localmente
- **Python 3.10+** instalado localmente
- **PostgreSQL 14+** instalado localmente (para desenvolvimento)

---

## 📱 ETAPA 1 — Configuração do Meta Business

Esta é a etapa mais importante. Sem ela, nada funciona.

### 1.1 — Criar App no Meta Developers

1. Acesse **https://developers.facebook.com**
2. Clique em **Criar App**
3. Selecione **Negócio** como tipo
4. Preencha:
   - Nome do App: `Cenat Hub` (ou o nome que preferir)
   - E-mail: seu e-mail de contato
   - Portfólio de negócios: selecione seu negócio verificado
5. Clique em **Criar App**

### 1.2 — Adicionar Produto WhatsApp

1. No painel do app, clique em **Adicionar Produto**
2. Encontre **WhatsApp** e clique em **Configurar**
3. Selecione o portfólio de negócios associado
4. O Meta vai criar automaticamente:
   - Um **WABA** (WhatsApp Business Account)
   - Um **número de teste** (para desenvolvimento)

### 1.3 — Vincular Número de Produção

> ⚠️ **Importante:** O número de teste tem limitações (só envia para números cadastrados). Para uso real, vincule um número de produção.

1. Vá em **WhatsApp → Configuração da API**
2. Clique em **Adicionar número de telefone**
3. Insira o número (formato internacional, ex: `+55 83 98804-6720`)
4. Verifique via SMS ou ligação
5. Defina o **nome de exibição** (aparece no WhatsApp do lead)
6. Configure o **PIN de verificação em duas etapas** (guarde esse PIN!)

### 1.4 — Obter Credenciais

Após configurar, anote as seguintes informações (você vai precisar delas):

| Informação | Onde encontrar | Exemplo |
|-----------|---------------|---------|
| **Token de Acesso** | API Setup → Token permanente | `EAAM...QWZDZD` |
| **Phone Number ID** | API Setup → Número selecionado | `978293125363835` |
| **WABA ID** | Business Settings → WhatsApp Accounts | `1360246076143727` |
| **App ID** | Dashboard do App | `1234567890` |
| **Webhook Verify Token** | Você define (string qualquer) | `cenat_webhook_2024` |

#### Como gerar o Token Permanente:

1. Vá em **business.facebook.com → Configurações → Usuários do sistema**
2. Crie um **Usuário do sistema** (tipo Admin)
3. Clique no usuário → **Gerar Token**
4. Selecione o app
5. Marque as permissões:
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
6. Clique em **Gerar Token**
7. **Copie e salve o token** — ele não aparece novamente!

### 1.5 — Configurar Webhook (depois do deploy)

> Esta etapa só pode ser feita depois que o servidor estiver rodando. Volte aqui na ETAPA 7.

1. Vá em **Meta Developers → Seu App → WhatsApp → Configuração**
2. Em "Webhook", clique em **Editar**
3. Preencha:
   - **URL do Callback:** `https://hub.cenatdata.online/webhook`
   - **Token de Verificação:** `cenat_webhook_2024`
4. Clique em **Verificar e Salvar**
5. Em **Campos do Webhook**, ative:
   - ✅ `messages` — para receber mensagens
   - ✅ `message_status` — para receber status (enviado, entregue, lido)

---

## 💻 ETAPA 2 — Configuração do Ambiente Local

### 2.1 — Clonar o Repositório

```bash
git clone git@github.com:linsalefe/pos-plataform.git
cd pos-plataform
```

### 2.2 — Estrutura do Projeto

```
pos-plataform/
├── backend/              # API FastAPI (Python)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py       # App principal + webhook
│   │   ├── models.py     # Modelos SQLAlchemy
│   │   ├── database.py   # Conexão com PostgreSQL
│   │   ├── routes.py     # Rotas da API
│   │   ├── auth.py       # Autenticação JWT
│   │   ├── auth_routes.py # Rotas de login/registro
│   │   └── whatsapp.py   # Funções de envio WhatsApp
│   ├── requirements.txt
│   └── .env
├── frontend/             # Interface Next.js (React)
│   ├── src/
│   │   ├── app/
│   │   │   ├── login/page.tsx
│   │   │   ├── dashboard/page.tsx
│   │   │   ├── conversations/page.tsx
│   │   │   ├── users/page.tsx
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── components/
│   │   │   ├── Sidebar.tsx
│   │   │   └── AppLayout.tsx
│   │   ├── contexts/
│   │   │   └── auth-context.tsx
│   │   └── lib/
│   │       └── api.ts
│   ├── public/
│   │   ├── logo-icon-white.png
│   │   ├── logo-icon-color.png
│   │   ├── logo-principal-cor.png
│   │   └── logo-principal-negativo.png
│   ├── package.json
│   └── .env.production
└── README.md
```

---

## ⚙️ ETAPA 3 — Backend (FastAPI)

### 3.1 — Criar ambiente virtual e instalar dependências

```bash
cd backend
python3 -m venv venv
source venv/bin/activate   # No Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install bcrypt==4.0.1
```

### 3.2 — Arquivo `requirements.txt`

```
fastapi
uvicorn[standard]
sqlalchemy[asyncio]
asyncpg
python-dotenv
httpx
pyjwt
bcrypt==4.0.1
```

### 3.3 — Criar arquivo `.env`

Crie o arquivo `backend/.env` com suas credenciais:

```env
WHATSAPP_TOKEN=SEU_TOKEN_PERMANENTE_AQUI
WHATSAPP_PHONE_ID=SEU_PHONE_NUMBER_ID_AQUI
WEBHOOK_VERIFY_TOKEN=cenat_webhook_2024
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/cenat_whatsapp
JWT_SECRET=sua-chave-secreta-jwt-aqui
```

> ⚠️ **Nunca commite o `.env`!** Adicione ao `.gitignore`.

### 3.4 — Rodar o Backend

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

O backend estará acessível em `http://localhost:8001`.

Teste: `curl http://localhost:8001/health` → deve retornar `{"status": "ok"}`

---

## 🗄 ETAPA 4 — Banco de Dados (PostgreSQL)

### 4.1 — Criar Banco de Dados (Desenvolvimento Local)

```bash
# No Mac/Linux
psql -U postgres -c "CREATE DATABASE cenat_whatsapp;"

# Ou, se usar sudo:
sudo -u postgres psql -c "CREATE DATABASE cenat_whatsapp;"
```

### 4.2 — Criar Tabelas Automaticamente

Ao rodar o backend pela primeira vez, as tabelas base são criadas automaticamente via SQLAlchemy. Mas algumas colunas extras precisam ser adicionadas manualmente:

```bash
psql -U postgres cenat_whatsapp -c "
-- Colunas extras na tabela contacts
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS lead_status VARCHAR(30) DEFAULT 'novo';
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS channel_id INTEGER REFERENCES channels(id);

-- Coluna extra na tabela messages
ALTER TABLE messages ADD COLUMN IF NOT EXISTS channel_id INTEGER REFERENCES channels(id);

-- Tabela de tags (se não existir)
CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    color VARCHAR(20) NOT NULL DEFAULT 'blue',
    created_at TIMESTAMP DEFAULT now()
);

-- Tabela de relação contato-tags
CREATE TABLE IF NOT EXISTS contact_tags (
    contact_wa_id VARCHAR(20) REFERENCES contacts(wa_id),
    tag_id INTEGER REFERENCES tags(id),
    PRIMARY KEY (contact_wa_id, tag_id)
);
"
```

### 4.3 — Inserir Canal (Número de WhatsApp)

```bash
psql -U postgres cenat_whatsapp -c "
INSERT INTO channels (name, phone_number, phone_number_id, whatsapp_token, waba_id, is_active)
VALUES (
    'Pós-Graduação (SDR)',
    '5511952137432',
    '978293125363835',
    'SEU_TOKEN_AQUI',
    '1360246076143727',
    true
);
"
```

> 📌 Para adicionar mais números, basta inserir mais linhas nesta tabela com os dados de cada número.

### 4.4 — Criar Usuário Admin

```bash
# Gerar hash da senha com Python
cd backend && source venv/bin/activate
HASH=$(python3 -c "
import bcrypt
h = bcrypt.hashpw('SuaSenhaAqui'.encode(), bcrypt.gensalt()).decode()
print(h)
")

# Inserir no banco
psql -U postgres cenat_whatsapp -c "
INSERT INTO users (name, email, password_hash, role, is_active)
VALUES ('Seu Nome', 'seu@email.com', '$HASH', 'admin', true);
"
```

---

## 🎨 ETAPA 5 — Frontend (Next.js)

### 5.1 — Instalar dependências

```bash
cd frontend
npm install
```

### 5.2 — Configurar variáveis de ambiente

Crie `frontend/.env.local` para desenvolvimento:

```env
NEXT_PUBLIC_API_URL=http://localhost:8001/api
```

Crie `frontend/.env.production` para produção:

```env
NEXT_PUBLIC_API_URL=https://hub.cenatdata.online/api
```

### 5.3 — Arquivo `src/lib/api.ts`

```typescript
import axios from 'axios';

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001/api',
});

export default api;
```

### 5.4 — Rodar o Frontend (Desenvolvimento)

```bash
cd frontend
npm run dev
```

O frontend estará acessível em `http://localhost:3000`.

### 5.5 — Build para Produção

```bash
cd frontend
npm run build
npm start -- -p 3001
```

---

## 🔗 ETAPA 6 — Webhook (Receber Mensagens)

### 6.1 — Como funciona

O webhook é o mecanismo pelo qual o Meta envia mensagens recebidas para o seu servidor. Toda vez que alguém manda uma mensagem para o seu número de WhatsApp Business, o Meta faz um POST para a URL configurada.

### 6.2 — Desenvolvimento Local (ngrok)

Para receber webhooks localmente, use o **ngrok**:

```bash
# Instalar ngrok (Mac)
brew install ngrok

# Ou baixar de https://ngrok.com/download

# Expor o backend local
ngrok http 8001
```

O ngrok gera uma URL como `https://abc123.ngrok-free.app`. Use essa URL no Meta:

1. Meta Developers → Seu App → WhatsApp → Configuração
2. Webhook URL: `https://abc123.ngrok-free.app/webhook`
3. Verify Token: `cenat_webhook_2024`
4. Ative os campos: `messages`, `message_status`

> ⚠️ A URL do ngrok muda toda vez que reinicia. Atualize no Meta.

### 6.3 — Produção

Em produção, o webhook aponta para o domínio real:

- **URL:** `https://hub.cenatdata.online/webhook`
- **Verify Token:** `cenat_webhook_2024`

---

## 🚀 ETAPA 7 — Deploy em Produção (AWS Lightsail)

### 7.1 — Criar Instância no Lightsail

1. Acesse **https://lightsail.aws.amazon.com**
2. Clique em **Create Instance**
3. Configure:
   - **Plataforma:** Linux/Unix
   - **Blueprint:** Ubuntu 22.04
   - **Plano:** $12/mês (2 GB RAM, 2 vCPUs, 60 GB SSD)
   - **Nome:** `cenat-hub`
4. Clique em **Create Instance**

### 7.2 — IP Estático

1. Na página da instância, vá em **Networking**
2. Clique em **Attach static IP**
3. Crie e anexe (é grátis enquanto vinculado)
4. Anote o IP estático (ex: `18.208.110.141`)

### 7.3 — Firewall

Na mesma página de Networking, adicione regras:

| Aplicativo | Protocolo | Porta |
|-----------|-----------|-------|
| SSH | TCP | 22 |
| HTTP | TCP | 80 |
| HTTPS | TCP | 443 |
| Personalizar | TCP | 8001 |

### 7.4 — Configurar DNS

No painel do seu provedor de domínio, crie:

| Tipo | Nome | Valor |
|------|------|-------|
| A | hub | IP estático da instância |

Após configurar, `hub.cenatdata.online` vai apontar para o servidor.

### 7.5 — Acessar o Servidor via SSH

Você pode acessar pelo terminal do Lightsail (botão "Connect using SSH") ou configurar no VSCode via SSH.

### 7.6 — Instalar Dependências no Servidor

```bash
# Atualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar pacotes essenciais
sudo apt install -y python3 python3-pip python3-venv postgresql postgresql-contrib nginx certbot python3-certbot-nginx git curl

# Instalar Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Verificar versões
node -v    # v20.x.x
npm -v     # 10.x.x
python3 --version  # 3.10+
```

### 7.7 — Configurar PostgreSQL

```bash
sudo -u postgres psql -c "CREATE USER cenat WITH PASSWORD 'CenatHub2024#';"
sudo -u postgres psql -c "CREATE DATABASE cenat_whatsapp OWNER cenat;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE cenat_whatsapp TO cenat;"
```

### 7.8 — Configurar Chave SSH para GitHub

```bash
ssh-keygen -t ed25519 -C "cenat-hub" -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

Copie a chave pública e adicione no GitHub: **Settings → SSH and GPG Keys → New SSH Key**.

### 7.9 — Clonar o Projeto

```bash
cd /home/ubuntu
git clone git@github.com:linsalefe/pos-plataform.git
```

### 7.10 — Configurar Backend no Servidor

```bash
cd /home/ubuntu/pos-plataform/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install bcrypt==4.0.1 pyjwt httpx
```

Criar `.env` de produção:

```bash
cat > /home/ubuntu/pos-plataform/backend/.env << 'EOF'
WHATSAPP_TOKEN=SEU_TOKEN_AQUI
WHATSAPP_PHONE_ID=978293125363835
WEBHOOK_VERIFY_TOKEN=cenat_webhook_2024
DATABASE_URL=postgresql+asyncpg://cenat:CenatHub2024#@localhost:5432/cenat_whatsapp
JWT_SECRET=cenat-hub-prod-secret-2024-x7k9m
EOF
```

Criar tabelas:

```bash
source venv/bin/activate
python3 -c "
import asyncio
from app.database import engine
from app.models import Base

async def create():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('Tabelas criadas!')

asyncio.run(create())
"
```

Executar alterações extras no banco (colunas, canal, usuário admin):

```bash
sudo -u postgres psql cenat_whatsapp -c "
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS lead_status VARCHAR(30) DEFAULT 'novo';
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS channel_id INTEGER REFERENCES channels(id);
ALTER TABLE messages ADD COLUMN IF NOT EXISTS channel_id INTEGER REFERENCES channels(id);

INSERT INTO channels (name, phone_number, phone_number_id, whatsapp_token, waba_id, is_active)
VALUES ('Pós-Graduação (SDR)', '5511952137432', '978293125363835',
'SEU_TOKEN_AQUI', '1360246076143727', true);
"
```

Criar usuário admin:

```bash
source venv/bin/activate
python3 -c "
import bcrypt
h = bcrypt.hashpw('SuaSenhaAqui'.encode(), bcrypt.gensalt()).decode()
print(h)
" | xargs -I{} sudo -u postgres psql cenat_whatsapp -c \
"INSERT INTO users (name, email, password_hash, role, is_active) VALUES ('Seu Nome', 'seu@email.com', '{}', 'admin', true);"
```

### 7.11 — Criar Serviço do Backend (systemd)

```bash
sudo tee /etc/systemd/system/cenat-backend.service << 'EOF'
[Unit]
Description=Cenat Hub Backend
After=network.target postgresql.service

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/pos-plataform/backend
ExecStart=/home/ubuntu/pos-plataform/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=3
EnvironmentFile=/home/ubuntu/pos-plataform/backend/.env

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable cenat-backend
sudo systemctl start cenat-backend
```

Verificar:

```bash
sudo systemctl status cenat-backend
# Deve mostrar "active (running)"
```

### 7.12 — Configurar Frontend no Servidor

```bash
cd /home/ubuntu/pos-plataform/frontend

# Configurar API URL de produção
cat > .env.production << 'EOF'
NEXT_PUBLIC_API_URL=https://hub.cenatdata.online/api
EOF

# Configurar api.ts
cat > src/lib/api.ts << 'EOF'
import axios from 'axios';

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001/api',
});

export default api;
EOF

# Instalar dependências e buildar
npm install
npm run build
```

### 7.13 — Criar Serviço do Frontend (systemd)

```bash
sudo tee /etc/systemd/system/cenat-frontend.service << 'EOF'
[Unit]
Description=Cenat Hub Frontend
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/pos-plataform/frontend
ExecStart=/usr/bin/npm start -- -p 3001
Restart=always
RestartSec=3
Environment=NODE_ENV=production
Environment=NEXT_PUBLIC_API_URL=https://hub.cenatdata.online/api

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable cenat-frontend
sudo systemctl start cenat-frontend
```

Verificar:

```bash
sudo systemctl status cenat-frontend
# Deve mostrar "active (running)"
```

### 7.14 — Configurar Nginx (Reverse Proxy)

```bash
sudo tee /etc/nginx/sites-available/cenat-hub << 'EOF'
server {
    listen 80;
    server_name hub.cenatdata.online;

    location /api/ {
        proxy_pass http://127.0.0.1:8001/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /webhook {
        proxy_pass http://127.0.0.1:8001/webhook;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:8001/health;
    }

    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/cenat-hub /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

### 7.15 — Instalar SSL (HTTPS)

```bash
sudo certbot --nginx -d hub.cenatdata.online --non-interactive --agree-tos -m seu@email.com
```

O Certbot configura automaticamente o Nginx para redirecionar HTTP → HTTPS.

A renovação é automática (via cron do Certbot). Para verificar:

```bash
sudo certbot renew --dry-run
```

### 7.16 — Testar Tudo

```bash
# Testar backend
curl https://hub.cenatdata.online/health

# Testar API
curl https://hub.cenatdata.online/api/channels

# Acessar no navegador
# https://hub.cenatdata.online
```

### 7.17 — Configurar Webhook no Meta (Agora sim!)

Volte para a **ETAPA 1.5** e configure o webhook com a URL de produção:

- **URL:** `https://hub.cenatdata.online/webhook`
- **Token:** `cenat_webhook_2024`

---

## 📝 ETAPA 8 — Configurar Templates do WhatsApp

Templates são mensagens pré-aprovadas pelo Meta, obrigatórias para **iniciar** uma conversa com um lead que não mandou mensagem primeiro.

### 8.1 — Acessar Gerenciador de Templates

1. Acesse **https://business.facebook.com/latest/whatsapp_manager/message_templates**
2. Clique em **Criar modelo**

### 8.2 — Criar Template de Primeiro Contato

| Campo | Valor |
|-------|-------|
| **Categoria** | Marketing |
| **Tipo** | Padrão |
| **Nome** | `primeiro_contato_pos` |
| **Idioma** | Portuguese (BR) |

**Corpo da mensagem:**

```
Olá, {{1}}, tudo bem?
👋 Seja bem-vindo(a) ao CENAT! 🎓 É um prazer saber do seu interesse em nossa Pós-Graduação {{2}}.
Estamos aqui para ajudá-lo(a) a dar o próximo passo em sua carreira com uma formação de excelência.
💡 Ficamos à disposição para esclarecer qualquer dúvida! 😊
Posso explicar mais sobre a Pós?
```

**Exemplos de variáveis (obrigatório):**
- `{{1}}` → `Maria`
- `{{2}}` → `Boas práticas: Como trabalhar com pessoas que ouvem vozes`

Clique em **Enviar para análise**. A aprovação leva de **alguns minutos até 24 horas**.

### 8.3 — Como os Templates Funcionam na Plataforma

1. Na página de **Conversas**, clique em **+ Nova conversa**
2. Preencha o telefone e nome do lead
3. Clique em **Carregar templates disponíveis**
4. Selecione o template desejado
5. Preencha as variáveis (nome, curso, etc.)
6. Veja a **prévia** da mensagem
7. Clique em **Enviar template**

O sistema busca automaticamente todos os templates **aprovados** da sua conta Meta.

### 8.4 — Regras Importantes dos Templates

- Só podem ser enviados para **iniciar** uma conversa
- Cada envio tem um **custo** (~R$0,25 a R$0,80 por conversa)
- Depois que o lead responde, a **janela de 24 horas** abre
- Dentro da janela, você pode enviar **texto livre** sem custo adicional
- Se a janela fechar (24h sem resposta do lead), precisa enviar novo template

---

## 🎯 Funcionalidades

### Dashboard
- Total de conversas ativas
- Leads novos (últimas 24h)
- Mensagens enviadas/recebidas
- Gráfico de atividade

### Conversas
- Chat em tempo real com polling (3 segundos)
- Envio e recebimento de texto
- Visualização de imagens, áudios, vídeos e documentos
- Busca de contatos
- Filtro por status (Todos, Novo, Contato, Qualificado, etc.)
- Seletor de canal (múltiplos números)

### CRM (Painel lateral)
- Status do lead: Novo → Contato → Qualificado → Matriculado → Perdido
- Tags coloridas personalizáveis
- Notas internas por contato
- Informações do contato (telefone, data de criação)

### Nova Conversa
- Seletor dinâmico de templates aprovados
- Preenchimento de variáveis com prévia em tempo real
- Criação automática do contato no sistema

### Gerenciar Usuários (Admin)
- Lista de todos os usuários
- Criar novos usuários (atendentes ou admins)
- Ativar/desativar usuários
- Controle de acesso por função

### Autenticação
- Login com email e senha
- JWT com expiração de 24 horas
- Proteção de todas as rotas
- Logout seguro

### Multi-número
- Suporte a múltiplos números de WhatsApp
- Cada número é um "canal" independente
- Contatos e mensagens vinculados ao canal correto
- Seletor de canal no topo das conversas

---

## 🗃 Estrutura de Pastas

```
pos-plataform/
├── backend/
│   ├── app/
│   │   ├── __init__.py          # Inicialização do módulo
│   │   ├── main.py              # FastAPI app, CORS, webhook, health
│   │   ├── models.py            # Modelos: Contact, Message, Channel, User, Tag
│   │   ├── database.py          # Engine + SessionLocal async
│   │   ├── routes.py            # Rotas: contacts, messages, send, tags, channels, media, templates
│   │   ├── auth.py              # hash_password, verify_password, create_access_token, get_current_user
│   │   ├── auth_routes.py       # login, register, me, users, toggle_user
│   │   └── whatsapp.py          # send_text_message, send_template_message
│   ├── requirements.txt
│   ├── .env                     # Variáveis (NÃO commitar)
│   └── venv/                    # Ambiente virtual (NÃO commitar)
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx       # Layout raiz (metadata, fontes, AuthProvider)
│   │   │   ├── page.tsx         # Redirect: / → /dashboard ou /login
│   │   │   ├── login/
│   │   │   │   └── page.tsx     # Página de login com branding Cenat Hub
│   │   │   ├── dashboard/
│   │   │   │   └── page.tsx     # Dashboard com métricas e gráficos
│   │   │   ├── conversations/
│   │   │   │   └── page.tsx     # Chat + CRM + templates + mídia
│   │   │   └── users/
│   │   │       └── page.tsx     # Gerenciar usuários (admin)
│   │   ├── components/
│   │   │   ├── Sidebar.tsx      # Menu lateral com logo, navegação, logout
│   │   │   └── AppLayout.tsx    # Wrapper com proteção de rota
│   │   ├── contexts/
│   │   │   └── auth-context.tsx # Provider de autenticação (JWT + localStorage)
│   │   └── lib/
│   │       └── api.ts           # Instância Axios configurada
│   ├── public/
│   │   ├── logo-icon-white.png  # Logo ícone branca (sidebar)
│   │   ├── logo-icon-color.png  # Logo ícone colorida (favicon, login)
│   │   ├── logo-principal-cor.png
│   │   └── logo-principal-negativo.png
│   ├── package.json
│   ├── .env.production
│   └── tailwind.config.ts
│
└── README.md
```

---

## 🗂 Banco de Dados — Tabelas

### `contacts`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| wa_id | VARCHAR(20) PK | ID WhatsApp (DDD+número) |
| name | VARCHAR(255) | Nome do contato |
| lead_status | VARCHAR(30) | Status: novo, contato, qualificado, matriculado, perdido |
| notes | TEXT | Notas internas |
| channel_id | INTEGER FK | Canal (número) vinculado |
| created_at | TIMESTAMP | Data de criação |

### `messages`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | SERIAL PK | ID interno |
| wa_message_id | VARCHAR(100) UNIQUE | ID da mensagem no WhatsApp |
| contact_wa_id | VARCHAR(20) FK | Contato vinculado |
| channel_id | INTEGER FK | Canal vinculado |
| direction | VARCHAR(10) | inbound ou outbound |
| message_type | VARCHAR(20) | text, image, audio, video, document, template, sticker |
| content | TEXT | Conteúdo (texto ou media:ID\|mime\|caption) |
| timestamp | TIMESTAMP | Hora da mensagem |
| status | VARCHAR(20) | sent, delivered, read, received |

### `channels`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | SERIAL PK | ID interno |
| name | VARCHAR(100) | Nome do canal (ex: "Pós-Graduação SDR") |
| phone_number | VARCHAR(20) | Número no formato 55XXXXXXXXXXX |
| phone_number_id | VARCHAR(50) | ID do número na API do Meta |
| whatsapp_token | TEXT | Token de acesso para este número |
| waba_id | VARCHAR(50) | ID da conta WhatsApp Business |
| is_active | BOOLEAN | Se o canal está ativo |
| created_at | TIMESTAMP | Data de criação |

### `users`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | SERIAL PK | ID interno |
| name | VARCHAR(255) | Nome do usuário |
| email | VARCHAR(255) UNIQUE | Email (usado no login) |
| password_hash | VARCHAR(255) | Senha hasheada (bcrypt) |
| role | VARCHAR(20) | admin ou atendente |
| is_active | BOOLEAN | Se pode fazer login |
| created_at | TIMESTAMP | Data de criação |

### `tags`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | SERIAL PK | ID interno |
| name | VARCHAR(50) UNIQUE | Nome da tag |
| color | VARCHAR(20) | Cor (blue, red, green, etc.) |
| created_at | TIMESTAMP | Data de criação |

### `contact_tags`
| Coluna | Tipo | Descrição |
|--------|------|-----------|
| contact_wa_id | VARCHAR(20) PK, FK | Contato |
| tag_id | INTEGER PK, FK | Tag |

---

## 🔌 API — Endpoints

### Autenticação
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/auth/login` | Login (retorna JWT) |
| GET | `/api/auth/me` | Dados do usuário logado |
| POST | `/api/auth/register` | Criar usuário (admin) |
| GET | `/api/auth/users` | Listar usuários (admin) |
| PATCH | `/api/auth/users/{id}` | Ativar/desativar usuário |

### Contatos
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/contacts` | Listar contatos (filtro por channel_id) |
| GET | `/api/contacts/{wa_id}` | Detalhes do contato |
| PATCH | `/api/contacts/{wa_id}/status` | Atualizar status do lead |
| PATCH | `/api/contacts/{wa_id}/notes` | Atualizar notas |

### Mensagens
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/messages/{wa_id}` | Histórico de mensagens |
| POST | `/api/send/text` | Enviar texto livre |
| POST | `/api/send/template` | Enviar template |

### Tags
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/tags` | Listar todas as tags |
| POST | `/api/tags` | Criar nova tag |
| POST | `/api/contacts/{wa_id}/tags/{tag_id}` | Adicionar tag ao contato |
| DELETE | `/api/contacts/{wa_id}/tags/{tag_id}` | Remover tag do contato |

### Canais
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/channels` | Listar canais ativos |
| POST | `/api/channels` | Criar novo canal |
| GET | `/api/channels/{id}/templates` | Listar templates aprovados |

### Mídia
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/media/{media_id}` | Proxy para baixar mídia do WhatsApp |

### Dashboard
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/dashboard/stats` | Métricas gerais |

### Webhook
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/webhook` | Verificação do Meta |
| POST | `/webhook` | Receber mensagens e status |

---

## 🔐 Variáveis de Ambiente

### Backend (`backend/.env`)

```env
# WhatsApp API (obrigatório)
WHATSAPP_TOKEN=token_permanente_do_meta
WHATSAPP_PHONE_ID=phone_number_id_principal
WEBHOOK_VERIFY_TOKEN=string_secreta_para_webhook

# Banco de Dados (obrigatório)
DATABASE_URL=postgresql+asyncpg://usuario:senha@host:5432/cenat_whatsapp

# Autenticação (obrigatório)
JWT_SECRET=chave_secreta_para_tokens_jwt
```

### Frontend (`frontend/.env.production`)

```env
NEXT_PUBLIC_API_URL=https://seu-dominio.com/api
```

---

## 🧰 Comandos Úteis

### Servidor de Produção

```bash
# ═══════════════════════════════════════
# VERIFICAR STATUS DOS SERVIÇOS
# ═══════════════════════════════════════
sudo systemctl status cenat-backend
sudo systemctl status cenat-frontend
sudo systemctl status nginx
sudo systemctl status postgresql

# ═══════════════════════════════════════
# REINICIAR SERVIÇOS
# ═══════════════════════════════════════
sudo systemctl restart cenat-backend
sudo systemctl restart cenat-frontend
sudo systemctl restart nginx

# ═══════════════════════════════════════
# VER LOGS (últimas 50 linhas)
# ═══════════════════════════════════════
sudo journalctl -u cenat-backend -n 50 --no-pager
sudo journalctl -u cenat-frontend -n 50 --no-pager
sudo tail -50 /var/log/nginx/error.log

# ═══════════════════════════════════════
# ATUALIZAR CÓDIGO (deploy)
# ═══════════════════════════════════════
cd /home/ubuntu/pos-plataform
git pull

# Backend
sudo systemctl restart cenat-backend

# Frontend (precisa rebuildar)
cd frontend
npm run build
sudo systemctl restart cenat-frontend

# ═══════════════════════════════════════
# ACESSAR BANCO DE DADOS
# ═══════════════════════════════════════
sudo -u postgres psql cenat_whatsapp

# Consultas úteis:
# SELECT * FROM contacts ORDER BY created_at DESC LIMIT 10;
# SELECT * FROM messages WHERE contact_wa_id = '5583988001234' ORDER BY timestamp DESC;
# SELECT * FROM channels;
# SELECT id, name, email, role, is_active FROM users;
# UPDATE users SET is_active = true WHERE email = 'email@exemplo.com';

# ═══════════════════════════════════════
# RENOVAR SSL
# ═══════════════════════════════════════
sudo certbot renew --dry-run   # Testar
sudo certbot renew              # Renovar
```

### Desenvolvimento Local

```bash
# Rodar backend
cd backend && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# Rodar frontend
cd frontend && npm run dev

# Expor para webhook (ngrok)
ngrok http 8001
```

### Git (Fluxo de Deploy)

```bash
# No Mac (desenvolvimento)
cd ~/Documents/pos-plataform
git add -A
git commit -m "feat: descrição da mudança"
git push

# No servidor (produção)
cd /home/ubuntu/pos-plataform
git pull
sudo systemctl restart cenat-backend
cd frontend && npm run build && sudo systemctl restart cenat-frontend
```

---

## ❗ Solução de Problemas

### Backend não inicia

```bash
# Ver erro detalhado
sudo journalctl -u cenat-backend -n 50 --no-pager

# Erro comum: módulo não encontrado
cd /home/ubuntu/pos-plataform/backend
source venv/bin/activate
pip install pyjwt bcrypt==4.0.1 httpx
sudo systemctl restart cenat-backend
```

### Frontend dá 502 Bad Gateway

```bash
# Verificar se está rodando
sudo systemctl status cenat-frontend

# Geralmente é erro de Node.js
node -v   # Precisa ser >= 20.x

# Se precisar atualizar:
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
cd /home/ubuntu/pos-plataform/frontend
rm -rf .next node_modules
npm install
npm run build
sudo systemctl restart cenat-frontend
```

### Webhook não recebe mensagens

1. Verifique a URL no Meta Developers: deve ser `https://hub.cenatdata.online/webhook`
2. Teste: `curl https://hub.cenatdata.online/webhook?hub.mode=subscribe&hub.verify_token=cenat_webhook_2024&hub.challenge=test`
3. Deve retornar: `test`
4. Verifique se os campos `messages` e `message_status` estão ativados

### Canal não aparece no dropdown

```bash
# Verificar se is_active está true
sudo -u postgres psql cenat_whatsapp -c "SELECT id, name, is_active FROM channels;"

# Corrigir se necessário
sudo -u postgres psql cenat_whatsapp -c "UPDATE channels SET is_active = true;"
```

### Login dá "Usuário inativo"

```bash
sudo -u postgres psql cenat_whatsapp -c "UPDATE users SET is_active = true WHERE email = 'seu@email.com';"
```

### Mídia não carrega (imagem/áudio)

- Mídias antigas (antes da implementação) não carregam — são IDs sem formato
- Envie uma nova mensagem de mídia para testar
- Verifique se o token do canal está válido

### CORS Error no navegador

Verifique se o domínio está na lista de origens permitidas no `main.py`:

```python
allow_origins=["http://localhost:3000", "http://localhost:3001", "https://hub.cenatdata.online"]
```

---

## 📄 Licença

Projeto proprietário — CENAT © 2026. Todos os direitos reservados.