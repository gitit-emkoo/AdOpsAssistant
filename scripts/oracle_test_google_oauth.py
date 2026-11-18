#!/usr/bin/env python3
from __future__ import annotations

import httpx

from app.config import get_settings

get_settings.cache_clear()
s = get_settings()
with httpx.Client(timeout=30) as client:
    resp = client.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": s.google_ads_client_id,
            "client_secret": s.google_ads_client_secret,
            "refresh_token": s.google_ads_refresh_token,
            "grant_type": "refresh_token",
        },
    )
print("status", resp.status_code)
# Avoid printing secrets; only error payload
print("body", resp.text[:500])
