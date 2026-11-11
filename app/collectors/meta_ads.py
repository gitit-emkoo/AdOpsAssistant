"""Meta Marketing API collector."""

from __future__ import annotations

import httpx

from app.collectors.types import AdMetrics
from app.config import Settings


INSTALL_ACTION_TYPES = {
    "mobile_app_install",
    "omni_app_install",
    "app_install",
    "install",
}


def _account_id(settings: Settings) -> str:
    account_id = settings.meta_ad_account_id
    return account_id if account_id.startswith("act_") else f"act_{account_id}"


def fetch_meta_ads_metrics(metric_date: str, settings: Settings) -> AdMetrics:
    account_id = _account_id(settings)
    url = (
        f"https://graph.facebook.com/{settings.meta_api_version}/"
        f"{account_id}/insights"
    )

    with httpx.Client(timeout=60) as client:
        resp = client.get(
            url,
            params={
                "access_token": settings.meta_access_token,
                "time_range": f'{{"since":"{metric_date}","until":"{metric_date}"}}',
                "fields": "spend,impressions,clicks,actions,action_values",
                "level": "account",
            },
        )
        if resp.status_code >= 400:
            detail = resp.text[:300].replace(settings.meta_access_token, "***")
            raise RuntimeError(f"Meta API {resp.status_code}: {detail}")
        data = resp.json().get("data", [])

    if not data:
        return AdMetrics(
            platform="meta",
            metric_date=metric_date,
            spend=0,
            impressions=0,
            clicks=0,
            conversions=0,
            conversion_value=0,
            installs=0,
            source="live",
        )

    row = data[0]
    conversions = 0.0
    conversion_value = 0.0
    installs = 0.0
    purchase_types = {
        "purchase",
        "omni_purchase",
        "offsite_conversion.fb_pixel_purchase",
    }
    for action in row.get("actions") or []:
        action_type = action.get("action_type")
        value = float(action.get("value", 0) or 0)
        if action_type in purchase_types:
            conversions += value
        if action_type in INSTALL_ACTION_TYPES:
            installs += value
    for action in row.get("action_values") or []:
        if action.get("action_type") in purchase_types:
            conversion_value += float(action.get("value", 0) or 0)

    # 앱 광고면 설치를 주 전환으로도 참고할 수 있게 둠
    if installs and not conversions:
        conversions = installs

    return AdMetrics(
        platform="meta",
        metric_date=metric_date,
        spend=float(row.get("spend", 0) or 0),
        impressions=int(row.get("impressions", 0) or 0),
        clicks=int(row.get("clicks", 0) or 0),
        conversions=conversions,
        conversion_value=conversion_value,
        installs=installs,
        source="live",
    )
