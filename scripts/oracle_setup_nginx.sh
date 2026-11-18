#!/usr/bin/env bash
set -euo pipefail

DOMAIN="kwccadops.duckdns.org"
APP_UPSTREAM="127.0.0.1:8000"

sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nginx

# Open HTTP (and HTTPS later) before the REJECT rule
sudo iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null \
  || sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null \
  || sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save || true

sudo tee /etc/nginx/sites-available/adops >/dev/null <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    client_max_body_size 20m;

    location / {
        proxy_pass http://${APP_UPSTREAM};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 120s;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/adops /etc/nginx/sites-enabled/adops
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx

# Update app base URL (no :8000)
ENV_FILE=/home/ubuntu/AdOpsAssistant/.env
if grep -q '^APP_BASE_URL=' "$ENV_FILE"; then
  sed -i "s|^APP_BASE_URL=.*|APP_BASE_URL=http://${DOMAIN}|" "$ENV_FILE"
else
  echo "APP_BASE_URL=http://${DOMAIN}" >> "$ENV_FILE"
fi
sudo systemctl restart adops
sleep 2

echo "=== local checks ==="
curl -s -o /dev/null -w "uvicorn_%{http_code}\n" http://127.0.0.1:8000/api/health || true
curl -s -o /dev/null -w "nginx_host_%{http_code}\n" -H "Host: ${DOMAIN}" http://127.0.0.1/api/health || true
grep '^APP_BASE_URL=' "$ENV_FILE"
sudo iptables -L INPUT -n --line-numbers | head -12
echo "NGINX_OK"
