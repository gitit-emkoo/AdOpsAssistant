"""현재 META_ACCESS_TOKEN 을 장기 토큰으로 교환합니다.

필요:
  META_APP_ID
  META_APP_SECRET
  META_ACCESS_TOKEN (짧은 토큰)

사용:
  .\\.venv\\Scripts\\python.exe scripts\\extend_meta_token.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.services.integrations import ensure_integration_table, extend_meta_token


def main() -> int:
    get_settings.cache_clear()
    ensure_integration_table()
    result = extend_meta_token()
    # 토큰 원문은 출력하지 않음
    safe = {
        "ok": result.get("ok"),
        "message": result.get("message"),
        "error": result.get("error"),
        "expires_in_days": result.get("expires_in_days"),
        "expires_at": result.get("expires_at"),
        "status": {
            k: v
            for k, v in (result.get("status") or {}).items()
            if k not in {"scopes"}
        },
    }
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
