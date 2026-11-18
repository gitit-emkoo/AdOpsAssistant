#!/usr/bin/env bash
set -euo pipefail
ENV_FILE=/home/ubuntu/AdOpsAssistant/.env
if grep -q '^APP_BASE_URL=' "$ENV_FILE"; then
  sed -i 's|^APP_BASE_URL=.*|APP_BASE_URL=http://161.33.43.244:8000|' "$ENV_FILE"
else
  echo 'APP_BASE_URL=http://161.33.43.244:8000' >> "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"
sudo systemctl restart adops
sleep 3
cd /home/ubuntu/AdOpsAssistant
PYTHONPATH=/home/ubuntu/AdOpsAssistant .venv/bin/python scripts/oracle_test_google.py
