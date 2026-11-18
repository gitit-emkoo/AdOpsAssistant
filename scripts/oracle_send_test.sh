#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/AdOpsAssistant
.venv/bin/python scripts/send_daily_report.py > /tmp/report_out.json
python3 <<'PY'
import json
d = json.load(open("/tmp/report_out.json"))
e = d.get("email") or {}
print("email_ok", e.get("ok"))
print("skipped", e.get("skipped"))
print("error", e.get("error"))
print("recipients", e.get("recipients"))
print("message", (e.get("message") or "")[:200])
PY
