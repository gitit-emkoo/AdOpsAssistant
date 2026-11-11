"""광고 API 연결 스모크 테스트. 비밀값은 출력하지 않습니다."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.collectors.base import collect_platform_metrics
from app.config import get_settings
from app.services.integrations import debug_meta_token, ensure_integration_table


def main() -> int:
    get_settings.cache_clear()
    settings = get_settings()
    ensure_integration_table()
    day = date.today() - timedelta(days=1)
    failed = False

    print("DEMO_MODE=", settings.demo_mode)
    print("google_configured=", settings.google_ads_configured)
    print("meta_configured=", settings.meta_configured)
    print("meta_app_credentials=", settings.meta_app_credentials_ready)

    if settings.demo_mode:
        print("주의: DEMO_MODE=true 이면 실API 대신 demo 데이터를 씁니다.")

    for platform in ("meta", "google_ads"):
        print(f"\n--- {platform} ---")
        try:
            metrics = collect_platform_metrics(platform, day, settings)
            d = metrics.to_dict()
            print(
                "ok",
                "source=",
                d["source"],
                "date=",
                d["metric_date"],
                "spend=",
                d["spend"],
                "clicks=",
                d["clicks"],
                "roas=",
                d["roas"],
            )
        except Exception as exc:  # noqa: BLE001
            failed = True
            msg = str(exc)
            if settings.meta_access_token:
                msg = msg.replace(settings.meta_access_token, "***")
            print("FAIL:", type(exc).__name__, msg[:300])

    print("\n--- meta token status ---")
    status = debug_meta_token(settings)
    print(
        "status=",
        status.get("status"),
        "level=",
        status.get("level"),
        "days_left=",
        status.get("days_left"),
        "title=",
        status.get("title"),
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
