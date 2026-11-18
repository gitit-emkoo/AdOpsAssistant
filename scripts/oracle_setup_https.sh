#!/usr/bin/env bash
set -euo pipefail

DOMAIN="kwccadops.duckdns.org"
ENV_FILE=/home/ubuntu/AdOpsAssistant/.env

# Prefer EMAIL_FROM / EMAIL_TO for Let's Encrypt notices
LE_EMAIL=$(grep -E '^EMAIL_FROM=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r' | cut -d',' -f1)
if [[ -z "${LE_EMAIL}" ]]; then
  LE_EMAIL=$(grep -E '^EMAIL_TO=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r' | cut -d',' -f1)
fi
if [[ -z "${LE_EMAIL}" ]]; then
  echo "EMAIL_FROM/EMAIL_TO missing for certbot"
  exit 1
fi

sudo DEBIAN_FRONTEND=noninteractive apt-get install -y certbot python3-certbot-nginx

# Ensure 443 is open in iptables
sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null \
  || sudo iptables -I INPUT 5 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save || true

sudo certbot --nginx \
  -d "$DOMAIN" \
  --non-interactive \
  --agree-tos \
  --email "$LE_EMAIL" \
  --redirect

if grep -q '^APP_BASE_URL=' "$ENV_FILE"; then
  sed -i "s|^APP_BASE_URL=.*|APP_BASE_URL=https://${DOMAIN}|" "$ENV_FILE"
else
  echo "APP_BASE_URL=https://${DOMAIN}" >> "$ENV_FILE"
fi

sudo systemctl restart adops
sleep 2
grep '^APP_BASE_URL=' "$ENV_FILE"
curl -s -o /dev/null -w "https_local_%{http_code}\n" --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/api/health" || true
echo "HTTPS_OK"
