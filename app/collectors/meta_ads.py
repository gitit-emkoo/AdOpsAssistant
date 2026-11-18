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


def _normalize_account_id(account_id: str) -> str:
    value = (account_id or "").strip()
    if not value:
        return ""
    return value if value.startswith("act_") else f"act_{value}"


def _account_ids(settings: Settings) -> list[str]:
    ids = list(settings.meta_ad_account_ids)
    if ids:
        return ids
    # 하위 호환: 단일 문자열만 있는 경우
    single = _normalize_account_id(settings.meta_ad_account_id)
    return [single] if single else []


def _parse_insights_row(row: dict) -> tuple[float, int, int, float, float, float]:
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
    if installs and not conversions:
        conversions = installs
    spend = float(row.get("spend", 0) or 0)
    impressions = int(row.get("impressions", 0) or 0)
    clicks = int(row.get("clicks", 0) or 0)
    return spend, impressions, clicks, conversions, installs, conversion_value


def _fetch_account_metrics(
    account_id: str,
    metric_date: str,
    settings: Settings,
    client: httpx.Client,
) -> AdMetrics:
    url = (
        f"https://graph.facebook.com/{settings.meta_api_version}/"
        f"{account_id}/insights"
    )
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
        raise RuntimeError(f"{account_id}: Meta API {resp.status_code}: {detail}")
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
    spend, impressions, clicks, conversions, installs, conversion_value = (
        _parse_insights_row(data[0])
    )
    return AdMetrics(
        platform="meta",
        metric_date=metric_date,
        spend=spend,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        conversion_value=conversion_value,
        installs=installs,
        source="live",
    )


def fetch_meta_ads_metrics(metric_date: str, settings: Settings) -> AdMetrics:
    """모든 Meta 광고계정 성과를 합산합니다."""
    accounts = _account_ids(settings)
    if not accounts:
        raise RuntimeError("META_AD_ACCOUNT_ID 가 비어 있습니다.")

    total = AdMetrics(
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
    errors: list[str] = []
    with httpx.Client(timeout=60) as client:
        for account_id in accounts:
            try:
                item = _fetch_account_metrics(account_id, metric_date, settings, client)
                total.spend += item.spend
                total.impressions += item.impressions
                total.clicks += item.clicks
                total.conversions += item.conversions
                total.conversion_value += item.conversion_value
                total.installs += item.installs
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

    if errors and total.spend == 0 and total.clicks == 0 and total.installs == 0:
        raise RuntimeError(" / ".join(errors))
    if errors:
        # 일부 계정만 실패해도 합산 결과는 반환
        setattr(total, "account_errors", errors)
    return total


def _meta_installs_from_actions(actions: list | None) -> float:
    installs = 0.0
    for action in actions or []:
        if action.get("action_type") in INSTALL_ACTION_TYPES:
            installs += float(action.get("value", 0) or 0)
    return installs


def _fetch_account_campaigns(
    account_id: str,
    metric_date: str,
    settings: Settings,
    client: httpx.Client,
) -> list[dict]:
    base = f"https://graph.facebook.com/{settings.meta_api_version}"
    token = settings.meta_access_token

    camp_resp = client.get(
        f"{base}/{account_id}/campaigns",
        params={
            "access_token": token,
            "effective_status": '["ACTIVE"]',
            "fields": "id,name,status,effective_status,start_time,stop_time,account_id",
            "limit": 50,
        },
    )
    if camp_resp.status_code >= 400:
        detail = camp_resp.text[:300].replace(token, "***")
        raise RuntimeError(f"{account_id}: Meta API {camp_resp.status_code}: {detail}")
    campaigns = camp_resp.json().get("data", [])

    # 계정 표시 이름(가능하면)
    account_name = account_id
    try:
        acc_resp = client.get(
            f"{base}/{account_id}",
            params={"access_token": token, "fields": "id,name,account_id"},
        )
        if acc_resp.status_code < 400:
            account_name = acc_resp.json().get("name") or account_id
    except Exception:  # noqa: BLE001
        pass

    insights_resp = client.get(
        f"{base}/{account_id}/insights",
        params={
            "access_token": token,
            "level": "campaign",
            "time_range": f'{{"since":"{metric_date}","until":"{metric_date}"}}',
            "fields": "campaign_id,campaign_name,spend,impressions,clicks,actions",
            "limit": 50,
        },
    )
    if insights_resp.status_code >= 400:
        detail = insights_resp.text[:300].replace(token, "***")
        raise RuntimeError(f"{account_id}: Meta API {insights_resp.status_code}: {detail}")
    insights = insights_resp.json().get("data", [])

    metrics_by_id: dict[str, dict] = {}
    for row in insights:
        cid = str(row.get("campaign_id") or "")
        if not cid:
            continue
        spend = float(row.get("spend", 0) or 0)
        clicks = int(row.get("clicks", 0) or 0)
        installs = _meta_installs_from_actions(row.get("actions"))
        metrics_by_id[cid] = {
            "spend": spend,
            "impressions": int(row.get("impressions", 0) or 0),
            "clicks": clicks,
            "installs": installs,
            "name": row.get("campaign_name"),
        }

    items: list[dict] = []
    for camp in campaigns:
        cid = str(camp.get("id") or "")
        if not cid:
            continue
        start_raw = camp.get("start_time")
        end_raw = camp.get("stop_time")
        end_date = (end_raw or "")[:10] or None
        # Meta는 종료일이 지나도 effective_status=ACTIVE 로 남는 경우가 있음
        if end_date and end_date < metric_date:
            continue
        m = metrics_by_id.get(cid, {})
        spend = float(m.get("spend") or 0)
        clicks = int(m.get("clicks") or 0)
        installs = float(m.get("installs") or 0)
        items.append(
            {
                "platform": "meta",
                "account_id": account_id,
                "account_name": account_name,
                "campaign_id": cid,
                "name": camp.get("name") or m.get("name") or f"Campaign {cid}",
                "status": camp.get("effective_status") or camp.get("status") or "ACTIVE",
                "start_date": (start_raw or "")[:10] or None,
                "end_date": end_date,
                "metric_date": metric_date,
                "spend": round(spend, 2),
                "impressions": int(m.get("impressions") or 0),
                "clicks": clicks,
                "installs": round(installs, 2),
                "install_rate": round((installs / clicks * 100) if clicks else 0.0, 2),
                "cpi": round((spend / installs) if installs else 0.0, 2),
            }
        )

    known = {i["campaign_id"] for i in items}
    for cid, m in metrics_by_id.items():
        if cid in known:
            continue
        spend = float(m.get("spend") or 0)
        clicks = int(m.get("clicks") or 0)
        installs = float(m.get("installs") or 0)
        items.append(
            {
                "platform": "meta",
                "account_id": account_id,
                "account_name": account_name,
                "campaign_id": cid,
                "name": m.get("name") or f"Campaign {cid}",
                "status": "ACTIVE",
                "start_date": None,
                "end_date": None,
                "metric_date": metric_date,
                "spend": round(spend, 2),
                "impressions": int(m.get("impressions") or 0),
                "clicks": clicks,
                "installs": round(installs, 2),
                "install_rate": round((installs / clicks * 100) if clicks else 0.0, 2),
                "cpi": round((spend / installs) if installs else 0.0, 2),
            }
        )
    return items


class MetaCampaignResult(list):
    errors: list[str]

    def __init__(self, items: list[dict] | None = None, errors: list[str] | None = None):
        super().__init__(items or [])
        self.errors = list(errors or [])


def fetch_meta_active_campaigns(metric_date: str, settings: Settings) -> MetaCampaignResult:
    """모든 계정의 ACTIVE 캠페인 + 해당일 성과."""
    accounts = _account_ids(settings)
    if not accounts:
        return MetaCampaignResult()

    items: list[dict] = []
    errors: list[str] = []
    with httpx.Client(timeout=60) as client:
        for account_id in accounts:
            try:
                items.extend(
                    _fetch_account_campaigns(account_id, metric_date, settings, client)
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

    if errors and not items:
        raise RuntimeError(" / ".join(errors))
    items.sort(key=lambda x: (-float(x.get("spend") or 0), x.get("name") or ""))
    return MetaCampaignResult(items, errors)


def fetch_meta_adsets(
    account_id: str,
    campaign_id: str,
    metric_date: str,
    settings: Settings,
) -> list[dict]:
    """캠페인 아래 광고세트 + 해당일 성과."""
    account_id = _normalize_account_id(account_id)
    campaign_id = str(campaign_id).strip()
    if not account_id or not campaign_id:
        return []

    base = f"https://graph.facebook.com/{settings.meta_api_version}"
    token = settings.meta_access_token
    with httpx.Client(timeout=60) as client:
        sets_resp = client.get(
            f"{base}/{campaign_id}/adsets",
            params={
                "access_token": token,
                "fields": "id,name,status,effective_status,start_time,end_time",
                "limit": 50,
            },
        )
        if sets_resp.status_code >= 400:
            detail = sets_resp.text[:300].replace(token, "***")
            raise RuntimeError(f"Meta adsets {sets_resp.status_code}: {detail}")
        adsets = sets_resp.json().get("data", [])

        insights_resp = client.get(
            f"{base}/{account_id}/insights",
            params={
                "access_token": token,
                "level": "adset",
                "filtering": (
                    f'[{{"field":"campaign.id","operator":"IN",'
                    f'"value":["{campaign_id}"]}}]'
                ),
                "time_range": f'{{"since":"{metric_date}","until":"{metric_date}"}}',
                "fields": "adset_id,adset_name,spend,impressions,clicks,actions",
                "limit": 50,
            },
        )
        if insights_resp.status_code >= 400:
            detail = insights_resp.text[:300].replace(token, "***")
            raise RuntimeError(f"Meta adset insights {insights_resp.status_code}: {detail}")
        insights = insights_resp.json().get("data", [])

    metrics_by_id: dict[str, dict] = {}
    for row in insights:
        aid = str(row.get("adset_id") or "")
        if not aid:
            continue
        spend = float(row.get("spend", 0) or 0)
        clicks = int(row.get("clicks", 0) or 0)
        installs = _meta_installs_from_actions(row.get("actions"))
        metrics_by_id[aid] = {
            "spend": spend,
            "impressions": int(row.get("impressions", 0) or 0),
            "clicks": clicks,
            "installs": installs,
            "name": row.get("adset_name"),
        }

    items: list[dict] = []
    for adset in adsets:
        aid = str(adset.get("id") or "")
        if not aid:
            continue
        status = (adset.get("effective_status") or adset.get("status") or "").upper()
        if status in {"DELETED", "ARCHIVED"}:
            continue
        end_raw = adset.get("end_time")
        end_date = (end_raw or "")[:10] or None
        if end_date and end_date < metric_date:
            continue
        m = metrics_by_id.get(aid, {})
        spend = float(m.get("spend") or 0)
        clicks = int(m.get("clicks") or 0)
        installs = float(m.get("installs") or 0)
        items.append(
            {
                "platform": "meta",
                "account_id": account_id,
                "campaign_id": campaign_id,
                "adset_id": aid,
                "name": adset.get("name") or m.get("name") or f"Ad set {aid}",
                "status": status or "ACTIVE",
                "start_date": (adset.get("start_time") or "")[:10] or None,
                "end_date": end_date,
                "metric_date": metric_date,
                "spend": round(spend, 2),
                "impressions": int(m.get("impressions") or 0),
                "clicks": clicks,
                "installs": round(installs, 2),
                "install_rate": round((installs / clicks * 100) if clicks else 0.0, 2),
                "cpi": round((spend / installs) if installs else 0.0, 2),
            }
        )

    items.sort(key=lambda x: (-float(x.get("spend") or 0), x.get("name") or ""))
    return items
