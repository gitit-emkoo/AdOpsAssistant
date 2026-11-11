"""Google Ads collector.

실연동: OAuth refresh token + Customer ID.
앱 광고(안드로이드 설치 등)는 conversion category DOWNLOAD / install 액션을 집계합니다.
"""

from __future__ import annotations

import httpx

from app.collectors.types import AdMetrics
from app.config import Settings


TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ADS_API_VERSION = "v26"
GOOGLE_ADS_SEARCH_URL = (
    "https://googleads.googleapis.com/"
    f"{GOOGLE_ADS_API_VERSION}/customers/{{customer_id}}/googleAds:search"
)


def _access_token(settings: Settings) -> str:
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "client_id": settings.google_ads_client_id,
                "client_secret": settings.google_ads_client_secret,
                "refresh_token": settings.google_ads_refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


def _headers(settings: Settings, access_token: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if settings.google_ads_developer_token:
        headers["developer-token"] = settings.google_ads_developer_token
    if settings.google_ads_login_customer_id:
        headers["login-customer-id"] = settings.google_ads_login_customer_id.replace(
            "-", ""
        )
    return headers


def _search(settings: Settings, access_token: str, customer_id: str, query: str) -> dict:
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            GOOGLE_ADS_SEARCH_URL.format(customer_id=customer_id),
            headers=_headers(settings, access_token),
            json={"query": query},
        )
        if resp.status_code >= 400:
            detail = resp.text[:800]
            raise RuntimeError(f"Google Ads API {resp.status_code}: {detail}")
        return resp.json()


def _is_install_row(category: str, name: str) -> bool:
    cat = (category or "").upper()
    lower_name = (name or "").lower()
    if cat in {"DOWNLOAD"}:
        return True
    keywords = (
        "install",
        "설치",
        "앱 설치",
        "app install",
        "android install",
        "first_open",
        "first open",
    )
    return any(k in lower_name for k in keywords)


def fetch_google_ads_metrics(metric_date: str, settings: Settings) -> AdMetrics:
    customer_id = settings.google_ads_customer_id.replace("-", "")
    access_token = _access_token(settings)

    base_query = f"""
        SELECT
          metrics.cost_micros,
          metrics.impressions,
          metrics.clicks,
          metrics.conversions,
          metrics.conversions_value
        FROM customer
        WHERE segments.date = '{metric_date}'
    """
    base_payload = _search(settings, access_token, customer_id, base_query)

    spend = impressions = clicks = 0
    conversions = conversion_value = 0.0
    for row in base_payload.get("results", []):
        metrics = row.get("metrics", {})
        spend += float(metrics.get("costMicros", 0)) / 1_000_000
        impressions += int(metrics.get("impressions", 0))
        clicks += int(metrics.get("clicks", 0))
        conversions += float(metrics.get("conversions", 0))
        conversion_value += float(metrics.get("conversionsValue", 0))

    installs = 0.0
    install_query = f"""
        SELECT
          segments.conversion_action_category,
          segments.conversion_action_name,
          metrics.conversions,
          metrics.all_conversions
        FROM customer
        WHERE segments.date = '{metric_date}'
    """
    try:
        install_payload = _search(settings, access_token, customer_id, install_query)
        for row in install_payload.get("results", []):
            segments = row.get("segments", {})
            metrics = row.get("metrics", {})
            category = segments.get("conversionActionCategory", "")
            name = segments.get("conversionActionName", "")
            if not _is_install_row(category, name):
                continue
            value = metrics.get("conversions")
            if value is None:
                value = metrics.get("allConversions", 0)
            installs += float(value or 0)
    except Exception:
        # 전환 세그먼트 권한이 없는 경우에도 기본 지표는 반환
        installs = 0.0

    return AdMetrics(
        platform="google_ads",
        metric_date=metric_date,
        spend=round(spend, 2),
        impressions=impressions,
        clicks=clicks,
        conversions=round(conversions, 2),
        conversion_value=round(conversion_value, 2),
        installs=round(installs, 2),
        source="live",
    )
