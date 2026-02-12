# 🧰 Comandos Úteis — CENAT Hub

## Conectar ao servidor (VS Code / Terminal)
```bash
ssh -i ~/.ssh/lightsail-us-east-1.pem ubuntu@18.208.110.141
```

---

## Deploy (fluxo padrão)

```bash
# No Mac (commitar)
cd ~/Documents/pos-plataform
git add -A && git commit -m "mensagem" && git push

# No servidor (atualizar)
cd ~/pos-plataform && git pull
sudo systemctl restart cenat-backend
cd frontend && npm run build && sudo systemctl restart cenat-frontend
```

---

## Verificar serviços

```bash
sudo systemctl status cenat-backend
sudo systemctl status cenat-frontend
sudo systemctl status nginx
sudo systemctl status postgresql
```

---

## Reiniciar serviços

```bash
sudo systemctl restart cenat-backend
sudo systemctl restart cenat-frontend
sudo systemctl restart nginx
```

---

## Logs

```bash
# Backend (últimas 50 linhas)
sudo journalctl -u cenat-backend --no-pager -n 50

# Backend (tempo real)
sudo journalctl -u cenat-backend -f

# Backend (últimos 5 min)
sudo journalctl -u cenat-backend --no-pager --since "5 min ago"

# Frontend
sudo journalctl -u cenat-frontend --no-pager -n 30

# Nginx
sudo tail -50 /var/log/nginx/error.log
```

---

## Banco de dados

```bash
# Acessar
sudo -u postgres psql cenat_whatsapp

# Consultas rápidas
sudo -u postgres psql cenat_whatsapp -c "SELECT id, name, email, role, is_active FROM users;"
sudo -u postgres psql cenat_whatsapp -c "SELECT id, name, is_active FROM channels;"
sudo -u postgres psql cenat_whatsapp -c "SELECT * FROM call_logs ORDER BY id DESC LIMIT 10;"
sudo -u postgres psql cenat_whatsapp -c "SELECT COUNT(*) FROM contacts;"
sudo -u postgres psql cenat_whatsapp -c "SELECT COUNT(*), stage FROM exact_leads GROUP BY stage ORDER BY count DESC;"
```

---

## Twilio (debug)

```bash
# Filtrar logs de gravação
sudo journalctl -u cenat-backend --no-pager -n 50 | grep -i "recording\|drive\|☁️\|❌"

# Filtrar logs de chamada
sudo journalctl -u cenat-backend --no-pager -n 50 | grep -i "call\|📞"

# Testar proxy de gravação
curl -I https://hub.cenatdata.online/api/twilio/recording/RE_SID_AQUI
```

---

## Variáveis de ambiente

```bash
# Ver .env do backend
cat ~/pos-plataform/backend/.env

# Editar
nano ~/pos-plataform/backend/.env

# Após editar, sempre reiniciar
sudo systemctl restart cenat-backend
```

---

## SSL

```bash
sudo certbot renew --dry-run   # testar
sudo certbot renew              # renovar
```

---

## Sync Exact Spotter (manual)

```bash
curl -X POST https://hub.cenatdata.online/api/exact-leads/sync
```

---

## Espaço em disco

```bash
df -h
du -sh ~/pos-plataform
```

---

## Processos e portas

```bash
sudo lsof -i :8001   # backend
sudo lsof -i :3001   # frontend
sudo lsof -i :5432   # postgres
```

---

**Última atualização:** 12/02/2026
