#!/usr/bin/env bash
set -euo pipefail
APP=/home/ubuntu/AdOpsAssistant
sudo systemctl stop adops || true
# files synced via scp into /tmp/adops_deploy
rsync -a --delete /tmp/adops_deploy/app/ "$APP/app/"
if [[ -f /tmp/adops_deploy/requirements.txt ]]; then
  cp /tmp/adops_deploy/requirements.txt "$APP/requirements.txt"
fi
cd "$APP"
source .venv/bin/activate
pip install -q -r requirements.txt
# ensure APP_BASE_URL is https duckdns
if grep -q '^APP_BASE_URL=' .env; then
  sed -i 's|^APP_BASE_URL=.*|APP_BASE_URL=https://kwccadops.duckdns.org|' .env
else
  echo 'APP_BASE_URL=https://kwccadops.duckdns.org' >> .env
fi
sudo systemctl start adops
sleep 3
sudo systemctl is-active adops
curl -s --max-time 10 http://127.0.0.1:8000/api/health || true
echo
curl -s -o /dev/null -w "login_%{http_code}\n" http://127.0.0.1:8000/login
curl -s -o /dev/null -w "home_redir_%{http_code}\n" http://127.0.0.1:8000/
echo DEPLOY_OK
