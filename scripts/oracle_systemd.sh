#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/ubuntu/AdOpsAssistant"

sudo tee /etc/systemd/system/adops.service >/dev/null <<'EOF'
[Unit]
Description=AdOps Assistant
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/AdOpsAssistant
Environment=PATH=/home/ubuntu/AdOpsAssistant/.venv/bin
ExecStart=/home/ubuntu/AdOpsAssistant/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable adops
sudo systemctl restart adops
sleep 2
sudo systemctl --no-pager --full status adops || true

# Daily mail at 00:00 UTC = 09:00 KST
DAILY='0 0 * * * cd /home/ubuntu/AdOpsAssistant && /home/ubuntu/AdOpsAssistant/.venv/bin/python /home/ubuntu/AdOpsAssistant/scripts/send_daily_report.py >> /home/ubuntu/AdOpsAssistant/cron-report.log 2>&1'
MONTHLY='0 1 1 * * cd /home/ubuntu/AdOpsAssistant && /home/ubuntu/AdOpsAssistant/.venv/bin/python /home/ubuntu/AdOpsAssistant/scripts/send_monthly_report.py >> /home/ubuntu/AdOpsAssistant/cron-report.log 2>&1'
(
  crontab -l 2>/dev/null | grep -v 'send_daily_report.py' | grep -v 'send_monthly_report.py' || true
  echo "$DAILY"
  echo "$MONTHLY"
) | crontab -
crontab -l

echo "SYSTEMD_CRON_OK"
curl -s -o /dev/null -w "LOCAL_HTTP_%{http_code}\n" http://127.0.0.1:8000/api/health || true
