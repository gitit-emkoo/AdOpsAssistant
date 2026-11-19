#!/usr/bin/env bash
set -euo pipefail
APP=/home/ubuntu/AdOpsAssistant
SRC=/tmp/adops_campaign
sudo systemctl stop adops || true
cp "$SRC/db.py" "$APP/app/"
cp "$SRC/main.py" "$APP/app/"
cp "$SRC/types.py" "$APP/app/collectors/"
cp "$SRC/base.py" "$APP/app/collectors/"
cp "$SRC/meta_ads.py" "$APP/app/collectors/"
cp "$SRC/google_ads.py" "$APP/app/collectors/"
cp "$SRC/report.py" "$APP/app/services/"
cp "$SRC/llm.py" "$APP/app/services/"
cp "$SRC/index.html" "$APP/app/templates/"
cp "$SRC/reports.html" "$APP/app/templates/"
cp "$SRC/404.html" "$APP/app/templates/"
cp "$SRC/app.js" "$APP/app/static/"
cd "$APP"
.venv/bin/python -c "from app.db import init_db; init_db(); print('db_ok')"
sudo systemctl start adops
sleep 2
systemctl is-active adops
curl -s -o /dev/null -w "notfound_%{http_code}\n" http://127.0.0.1:8000/this-page-does-not-exist
curl -s -o /dev/null -w "login_%{http_code}\n" http://127.0.0.1:8000/login
echo DEPLOY_CAMPAIGN_OK
