# 📱 Cenat WhatsApp CRM

Plataforma de atendimento comercial via WhatsApp para a equipe do CENAT. Integra a API oficial do WhatsApp Business Cloud com um CRM completo para gestão de leads.

## 🚀 Stack

### Backend
- **Python 3.11** + **FastAPI** — API REST assíncrona
- **PostgreSQL** — Banco de dados relacional
- **SQLAlchemy** (async) — ORM
- **httpx** — Cliente HTTP para API do WhatsApp

### Frontend
- **Next.js 14** — Framework React (App Router)
- **TypeScript** — Tipagem estática
- **Tailwind CSS** — Estilização
- **Axios** — Cliente HTTP
- **Lucide React** — Ícones

## 📋 Funcionalidades

- ✅ Receber e enviar mensagens via WhatsApp Business API
- ✅ Webhook para recebimento em tempo real
- ✅ Dashboard com métricas (mensagens, contatos, funil de leads)
- ✅ Chat em tempo real com interface estilo WhatsApp
- ✅ CRM integrado (status do lead, tags, notas)
- ✅ Multi-número (suporte a múltiplos canais/números)
- ✅ Filtros por status de lead e busca de contatos
- 🔜 Autenticação (login da equipe comercial)
- 🔜 Deploy em produção (VPS, HTTPS, domínio)

## 📁 Estrutura do Projeto
```
pos-plataform/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app + webhook
│   │   ├── models.py        # Modelos SQLAlchemy
│   │   ├── database.py      # Configuração do banco
│   │   ├── routes.py        # Endpoints da API
│   │   ├── whatsapp.py      # Integração WhatsApp API
│   │   └── create_tables.py # Script de criação de tabelas
│   ├── .env                 # Variáveis de ambiente
│   └── requirements.txt     # Dependências Python
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── dashboard/page.tsx      # Dashboard
│   │   │   └── conversations/page.tsx  # Chat + CRM
│   │   ├── components/
│   │   │   ├── Sidebar.tsx    # Sidebar de navegação
│   │   │   └── AppLayout.tsx  # Layout principal
│   │   └── lib/
│   │       └── api.ts         # Cliente Axios
│   └── package.json
└── README.md
```

## ⚙️ Configuração Local

### Pré-requisitos
- Python 3.11+
- Node.js 18+
- PostgreSQL 15+

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Criar banco de dados
createdb cenat_whatsapp
python -m app.create_tables

# Rodar servidor
uvicorn app.main:app --reload --port 8001
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Variáveis de Ambiente (backend/.env)
```env
WHATSAPP_TOKEN=seu_token_aqui
WHATSAPP_PHONE_ID=seu_phone_id
WEBHOOK_VERIFY_TOKEN=seu_verify_token
DATABASE_URL=postgresql+asyncpg://localhost:5432/cenat_whatsapp
```

## 🔗 API Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Health check |
| GET | `/webhook` | Verificação do webhook |
| POST | `/webhook` | Receber mensagens do WhatsApp |
| GET | `/api/channels` | Listar canais |
| POST | `/api/channels` | Criar canal |
| GET | `/api/dashboard/stats` | Métricas do dashboard |
| GET | `/api/contacts` | Listar contatos |
| PATCH | `/api/contacts/{wa_id}` | Atualizar contato |
| GET | `/api/contacts/{wa_id}/messages` | Mensagens do contato |
| POST | `/api/send/text` | Enviar mensagem de texto |
| POST | `/api/send/template` | Enviar template |
| GET | `/api/tags` | Listar tags |
| POST | `/api/tags` | Criar tag |
| POST | `/api/contacts/{wa_id}/tags/{tag_id}` | Adicionar tag ao contato |
| DELETE | `/api/contacts/{wa_id}/tags/{tag_id}` | Remover tag do contato |

## 👥 Equipe

Desenvolvido para o **CENAT** — Centro Nacional de Educação e Tecnologia.
