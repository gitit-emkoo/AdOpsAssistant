#!/usr/bin/env bash
set -euo pipefail
echo "=== time ==="
date -u
date
timedatectl | sed -n '1,8p' || true
echo "=== crontab ==="
crontab -l || true
echo "=== cron log file ==="
if [[ -f /home/ubuntu/AdOpsAssistant/cron-report.log ]]; then
  wc -l /home/ubuntu/AdOpsAssistant/cron-report.log
  echo "--- last 80 lines ---"
  tail -n 80 /home/ubuntu/AdOpsAssistant/cron-report.log
else
  echo "cron-report.log missing"
fi
echo "=== syslog cron (if any) ==="
sudo grep -E "CRON|send_daily_report" /var/log/syslog 2>/dev/null | tail -n 30 || true
echo "=== adops service ==="
sudo systemctl is-active adops || true
