"""매일 광고 성과 메일 발송 스크립트.

사용:
  python scripts/send_daily_report.py
  python scripts/send_daily_report.py --no-send
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import init_db
from app.services.report import run_daily_report
from app.services.tasks import seed_default_tasks_if_empty


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="메일은 보내지 않고 리포트만 생성",
    )
    args = parser.parse_args()

    init_db()
    seed_default_tasks_if_empty()
    result = run_daily_report(send=not args.no_send)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    email = result.get("email") or {}
    if email.get("ok") or email.get("skipped"):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
