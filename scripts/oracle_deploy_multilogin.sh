#!/usr/bin/env bash
set -euo pipefail
APP=/home/ubuntu/AdOpsAssistant
SRC=/tmp/adops_multilogin
sudo systemctl stop adops || true
cp "$SRC/db.py" "$APP/app/"
cp "$SRC/main.py" "$APP/app/"
cp "$SRC/base.py" "$APP/app/collectors/"
cp "$SRC/connections.py" "$APP/app/services/"
cp "$SRC/oauth.py" "$APP/app/services/"
cp "$SRC/active_ads.py" "$APP/app/services/"
cp "$SRC/connections.html" "$APP/app/templates/"
cp "$SRC/style.css" "$APP/app/static/"
cd "$APP"
.venv/bin/python -c "from app.db import init_db; init_db(); print('db_ok')"
sudo systemctl start adops
sleep 2
systemctl is-active adops
curl -s -o /dev/null -w "login_%{http_code}\n" http://127.0.0.1:8000/login
echo DEPLOY_MULTILOGIN_OK
