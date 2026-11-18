#!/usr/bin/env bash
set -euo pipefail
ENV_FILE=/home/ubuntu/AdOpsAssistant/.env
if grep -q '^APP_BASE_URL=' "$ENV_FILE"; then
  sed -i 's|^APP_BASE_URL=.*|APP_BASE_URL=http://161.33.43.244:8000|' "$ENV_FILE"
else
  echo 'APP_BASE_URL=http://161.33.43.244:8000' >> "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"
grep '^EMAIL_TO=' "$ENV_FILE" || echo 'EMAIL_TO MISSING'
bash /home/ubuntu/oracle_send_test.sh
