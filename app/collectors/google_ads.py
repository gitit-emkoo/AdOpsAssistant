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


def fetch_google_active_campaigns(metric_date: str, settings: Settings) -> list[dict]:
    """ENABLED 캠페인 + 해당일 성과."""
    customer_id = settings.google_ads_customer_id.replace("-", "")
    access_token = _access_token(settings)

    list_query = """
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.start_date_time,
          campaign.end_date_time
        FROM campaign
        WHERE campaign.status = 'ENABLED'
    """
    list_payload = _search(settings, access_token, customer_id, list_query)
    by_id: dict[str, dict] = {}
    for row in list_payload.get("results", []):
        campaign = row.get("campaign", {})
        cid = str(campaign.get("id") or "")
        if not cid:
            continue
        start_raw = campaign.get("startDateTime") or campaign.get("startDate") or ""
        end_raw = campaign.get("endDateTime") or campaign.get("endDate") or ""
        start_date = str(start_raw)[:10] or None
        end_date = str(end_raw)[:10] or None
        # Google은 종료 없음이 2037-12-30 등으로 오는 경우가 있음
        if end_date and end_date.startswith("2037"):
            end_date = None
        by_id[cid] = {
            "platform": "google_ads",
            "account_id": customer_id,
            "account_name": customer_id,
            "campaign_id": cid,
            "name": campaign.get("name") or f"Campaign {cid}",
            "status": campaign.get("status") or "ENABLED",
            "start_date": start_date,
            "end_date": end_date,
            "metric_date": metric_date,
            "spend": 0.0,
            "impressions": 0,
            "clicks": 0,
            "conversions": 0.0,
            "installs": 0.0,
        }

    base_query = f"""
        SELECT
          campaign.id,
          metrics.cost_micros,
          metrics.impressions,
          metrics.clicks,
          metrics.conversions
        FROM campaign
        WHERE campaign.status = 'ENABLED'
          AND segments.date = '{metric_date}'
    """
    payload = _search(settings, access_token, customer_id, base_query)
    for row in payload.get("results", []):
        campaign = row.get("campaign", {})
        metrics = row.get("metrics", {})
        cid = str(campaign.get("id") or "")
        if cid not in by_id:
            continue
        spend = float(metrics.get("costMicros", 0) or 0) / 1_000_000
        by_id[cid]["spend"] = round(spend, 2)
        by_id[cid]["impressions"] = int(metrics.get("impressions", 0) or 0)
        by_id[cid]["clicks"] = int(metrics.get("clicks", 0) or 0)
        by_id[cid]["conversions"] = float(metrics.get("conversions", 0) or 0)

    install_query = f"""
        SELECT
          campaign.id,
          segments.conversion_action_category,
          segments.conversion_action_name,
          metrics.conversions,
          metrics.all_conversions
        FROM campaign
        WHERE campaign.status = 'ENABLED'
          AND segments.date = '{metric_date}'
    """
    try:
        install_payload = _search(settings, access_token, customer_id, install_query)
        for row in install_payload.get("results", []):
            campaign = row.get("campaign", {})
            segments = row.get("segments", {})
            metrics = row.get("metrics", {})
            cid = str(campaign.get("id") or "")
            if cid not in by_id:
                continue
            if not _is_install_row(
                segments.get("conversionActionCategory", ""),
                segments.get("conversionActionName", ""),
            ):
                continue
            value = metrics.get("conversions")
            if value is None:
                value = metrics.get("allConversions", 0)
            by_id[cid]["installs"] = round(
                float(by_id[cid].get("installs") or 0) + float(value or 0),
                2,
            )
    except Exception:
        pass

    items = []
    for item in by_id.values():
        clicks = int(item.get("clicks") or 0)
        installs = float(item.get("installs") or 0)
        spend = float(item.get("spend") or 0)
        item["install_rate"] = round((installs / clicks * 100) if clicks else 0.0, 2)
        item["cpi"] = round((spend / installs) if installs else 0.0, 2)
        items.append(item)
    items.sort(key=lambda x: (-float(x.get("spend") or 0), x.get("name") or ""))
    return items


def fetch_google_ad_groups(
    campaign_id: str,
    metric_date: str,
    settings: Settings,
) -> list[dict]:
    """캠페인 아래 광고그룹(광고세트에 해당) + 해당일 성과."""
    customer_id = settings.google_ads_customer_id.replace("-", "")
    access_token = _access_token(settings)
    cid = str(campaign_id).strip()

    list_query = f"""
        SELECT
          ad_group.id,
          ad_group.name,
          ad_group.status,
          campaign.id
        FROM ad_group
        WHERE campaign.id = {cid}
          AND ad_group.status != 'REMOVED'
    """
    list_payload = _search(settings, access_token, customer_id, list_query)
    by_id: dict[str, dict] = {}
    for row in list_payload.get("results", []):
        ad_group = row.get("adGroup", {})
        aid = str(ad_group.get("id") or "")
        if not aid:
            continue
        by_id[aid] = {
            "platform": "google_ads",
            "account_id": customer_id,
            "campaign_id": cid,
            "adset_id": aid,
            "name": ad_group.get("name") or f"Ad group {aid}",
            "status": ad_group.get("status") or "",
            "metric_date": metric_date,
            "spend": 0.0,
            "impressions": 0,
            "clicks": 0,
            "installs": 0.0,
        }

    metrics_query = f"""
        SELECT
          ad_group.id,
          metrics.cost_micros,
          metrics.impressions,
          metrics.clicks,
          metrics.conversions
        FROM ad_group
        WHERE campaign.id = {cid}
          AND segments.date = '{metric_date}'
    """
    metrics_payload = _search(settings, access_token, customer_id, metrics_query)
    for row in metrics_payload.get("results", []):
        ad_group = row.get("adGroup", {})
        metrics = row.get("metrics", {})
        aid = str(ad_group.get("id") or "")
        if aid not in by_id:
            continue
        spend = float(metrics.get("costMicros", 0) or 0) / 1_000_000
        by_id[aid]["spend"] = round(spend, 2)
        by_id[aid]["impressions"] = int(metrics.get("impressions", 0) or 0)
        by_id[aid]["clicks"] = int(metrics.get("clicks", 0) or 0)

    install_query = f"""
        SELECT
          ad_group.id,
          segments.conversion_action_category,
          segments.conversion_action_name,
          metrics.conversions,
          metrics.all_conversions
        FROM ad_group
        WHERE campaign.id = {cid}
          AND segments.date = '{metric_date}'
    """
    try:
        install_payload = _search(settings, access_token, customer_id, install_query)
        for row in install_payload.get("results", []):
            ad_group = row.get("adGroup", {})
            segments = row.get("segments", {})
            metrics = row.get("metrics", {})
            aid = str(ad_group.get("id") or "")
            if aid not in by_id:
                continue
            if not _is_install_row(
                segments.get("conversionActionCategory", ""),
                segments.get("conversionActionName", ""),
            ):
                continue
            value = metrics.get("conversions")
            if value is None:
                value = metrics.get("allConversions", 0)
            by_id[aid]["installs"] = round(
                float(by_id[aid].get("installs") or 0) + float(value or 0),
                2,
            )
    except Exception:
        pass

    items = []
    for item in by_id.values():
        clicks = int(item.get("clicks") or 0)
        installs = float(item.get("installs") or 0)
        spend = float(item.get("spend") or 0)
        item["install_rate"] = round((installs / clicks * 100) if clicks else 0.0, 2)
        item["cpi"] = round((spend / installs) if installs else 0.0, 2)
        items.append(item)
    items.sort(key=lambda x: (-float(x.get("spend") or 0), x.get("name") or ""))
    return items
