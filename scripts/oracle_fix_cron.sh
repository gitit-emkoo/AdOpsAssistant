#!/usr/bin/env bash
set -euo pipefail
# Daily: 00:00 UTC = 09:00 KST
DAILY='0 0 * * * cd /home/ubuntu/AdOpsAssistant && /home/ubuntu/AdOpsAssistant/.venv/bin/python /home/ubuntu/AdOpsAssistant/scripts/send_daily_report.py >> /home/ubuntu/AdOpsAssistant/cron-report.log 2>&1'
# Monthly: 01:00 UTC on 1st = 10:00 KST, previous calendar month
MONTHLY='0 1 1 * * cd /home/ubuntu/AdOpsAssistant && /home/ubuntu/AdOpsAssistant/.venv/bin/python /home/ubuntu/AdOpsAssistant/scripts/send_monthly_report.py >> /home/ubuntu/AdOpsAssistant/cron-report.log 2>&1'
(
  crontab -l 2>/dev/null | grep -v 'send_daily_report.py' | grep -v 'send_monthly_report.py' || true
  echo "$DAILY"
  echo "$MONTHLY"
) | crontab -
echo "=== crontab ==="
crontab -l
