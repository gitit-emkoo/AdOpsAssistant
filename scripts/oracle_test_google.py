#!/usr/bin/env python3
from __future__ import annotations

from datetime import date, timedelta

from app.config import get_settings
from app.collectors.base import collect_all_metrics, collect_platform_metrics

get_settings.cache_clear()
s = get_settings()
print("demo_mode", s.demo_mode)
print("google_configured", s.google_ads_configured)
print("customer_id_set", bool(s.google_ads_customer_id))
print("login_customer_set", bool(s.google_ads_login_customer_id))
print("refresh_set", bool(s.google_ads_refresh_token))
print("dev_token_set", bool(s.google_ads_developer_token))

day = date.today() - timedelta(days=1)
try:
    g = collect_platform_metrics("google_ads", day)
    print("google_source", g.source)
    print("google_spend", g.spend, "clicks", g.clicks, "installs", g.installs)
except Exception as exc:  # noqa: BLE001
    print("google_error", type(exc).__name__, str(exc)[:500])

all_r = collect_all_metrics(day)
print("collect_errors", all_r.errors)
for item in all_r:
    print(item.platform, item.source, item.spend, item.clicks)
