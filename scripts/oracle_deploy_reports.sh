#!/usr/bin/env bash
set -euo pipefail
APP=/home/ubuntu/AdOpsAssistant
SRC=/tmp/adops_reports
sudo systemctl stop adops || true
cp "$SRC/db.py" "$APP/app/"
cp "$SRC/main.py" "$APP/app/"
cp "$SRC/report.py" "$APP/app/services/"
cp "$SRC/llm.py" "$APP/app/services/"
cp "$SRC/reports.html" "$APP/app/templates/"
cp "$SRC/index.html" "$APP/app/templates/"
cp "$SRC/connections.html" "$APP/app/templates/"
cp "$SRC/style.css" "$APP/app/static/"
cp "$SRC/send_monthly_report.py" "$APP/scripts/"
cp "$SRC/oracle_fix_cron.sh" "$APP/scripts/"
sed -i 's/\r$//' "$APP/scripts/oracle_fix_cron.sh" "$APP/scripts/send_monthly_report.py" "$APP/scripts/oracle_deploy_reports.sh" || true
chmod +x "$APP/scripts/oracle_fix_cron.sh"
bash "$APP/scripts/oracle_fix_cron.sh"
cd "$APP"
.venv/bin/python -c "from app.db import init_db; init_db(); print('db_ok')"
sudo systemctl start adops
sleep 2
systemctl is-active adops
curl -s -o /dev/null -w "reports_%{http_code}\n" http://127.0.0.1:8000/reports
curl -s -o /dev/null -w "login_%{http_code}\n" http://127.0.0.1:8000/login
echo DEPLOY_REPORTS_OK
