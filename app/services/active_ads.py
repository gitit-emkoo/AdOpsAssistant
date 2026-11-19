"""진행 중 광고(캠페인) + 오늘 성과 보드."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.collectors.google_ads import fetch_google_active_campaigns, fetch_google_ad_groups
from app.collectors.meta_ads import fetch_meta_active_campaigns, fetch_meta_adsets
from app.config import Settings, get_settings
from app.db import get_conn, now_iso


CACHE_KEY = "active_ads_today"
CACHE_TTL_MINUTES = 10


def _is_running_on(item: dict[str, Any], metric_date: str) -> bool:
    """광고기간 종료일이 기준일보다 이전이면 진행 중 목록에서 제외."""
    end = item.get("end_date")
    if not end:
        return True
    return str(end)[:10] >= metric_date


def _ensure_cache_table() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_cache (
                cache_key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def _today(settings: Settings) -> date:
    try:
        return datetime.now(ZoneInfo(settings.timezone)).date()
    except Exception:  # noqa: BLE001
        return date.today()


def _demo_campaigns(metric_date: str) -> list[dict[str, Any]]:
    return [
        {
            "platform": "google_ads",
            "campaign_id": "demo-g-1",
            "name": "Demo Android Installs",
            "status": "ENABLED",
            "start_date": metric_date[:8] + "01",
            "end_date": None,
            "metric_date": metric_date,
            "spend": 18420.0,
            "impressions": 9200,
            "clicks": 146,
            "installs": 38.0,
            "install_rate": 26.03,
            "cpi": 484.74,
        },
        {
            "platform": "meta",
            "account_id": "act_demo_1",
            "account_name": "Demo Account A",
            "campaign_id": "demo-m-1",
            "name": "Demo Meta App Traffic",
            "status": "ACTIVE",
            "start_date": metric_date[:8] + "01",
            "end_date": None,
            "metric_date": metric_date,
            "spend": 9720.0,
            "impressions": 15400,
            "clicks": 88,
            "installs": 12.0,
            "install_rate": 13.64,
            "cpi": 810.0,
        },
        {
            "platform": "meta",
            "account_id": "act_demo_2",
            "account_name": "Demo Account B",
            "campaign_id": "demo-m-2",
            "name": "Demo Meta Brand",
            "status": "ACTIVE",
            "start_date": metric_date[:8] + "01",
            "end_date": None,
            "metric_date": metric_date,
            "spend": 4200.0,
            "impressions": 8000,
            "clicks": 40,
            "installs": 5.0,
            "install_rate": 12.5,
            "cpi": 840.0,
        },
    ]


def _cache_key(user_id: int | None = None) -> str:
    if user_id is None:
        return CACHE_KEY
    return f"{CACHE_KEY}:u{user_id}"


def _read_cache(user_id: int | None = None) -> dict[str, Any] | None:
    _ensure_cache_table()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT payload_json, updated_at FROM kv_cache WHERE cache_key = ?",
            (_cache_key(user_id),),
        ).fetchone()
    if not row:
        return None
    try:
        updated = datetime.fromisoformat(row["updated_at"])
    except ValueError:
        return None
    if datetime.now() - updated.replace(tzinfo=None) > timedelta(minutes=CACHE_TTL_MINUTES):
        return None
    try:
        return json.loads(row["payload_json"])
    except json.JSONDecodeError:
        return None


def _write_cache(payload: dict[str, Any], user_id: int | None = None) -> None:
    _ensure_cache_table()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO kv_cache (cache_key, payload_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (_cache_key(user_id), json.dumps(payload, ensure_ascii=False), now_iso()),
        )


def _fetch_active_for_overlays(
    metric_date: str,
    google_overlays: list[Settings],
    meta_overlays: list[Settings],
) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for settings in google_overlays:
        if not settings.google_ads_configured:
            continue
        try:
            items.extend(fetch_google_active_campaigns(metric_date, settings))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"google_ads: {exc}")
    for settings in meta_overlays:
        if not settings.meta_configured:
            continue
        try:
            meta_items = fetch_meta_active_campaigns(metric_date, settings)
            items.extend(meta_items)
            errors.extend([f"meta: {e}" for e in (meta_items.errors or [])])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"meta: {exc}")
    return items, errors


def get_active_ads(
    *,
    force_refresh: bool = False,
    settings: Settings | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    from app.services.connections import settings_overlays_for_platform, settings_for_user

    if settings is None:
        settings = settings_for_user(user_id) if user_id is not None else get_settings()
    google_overlays = (
        settings_overlays_for_platform(user_id, "google_ads")
        if user_id is not None
        else [settings]
    )
    meta_overlays = (
        settings_overlays_for_platform(user_id, "meta")
        if user_id is not None
        else [settings]
    )

    if not force_refresh:
        cached = _read_cache(user_id)
        if cached:
            cached_errors = " ".join(str(e) for e in (cached.get("errors") or []))
            if "expired" in cached_errors.lower() or "access token" in cached_errors.lower():
                pass
            else:
                cached["source"] = "cache"
                return cached

    metric_date = _today(settings).isoformat()
    items: list[dict[str, Any]] = []
    errors: list[str] = []

    if settings.demo_mode:
        items = _demo_campaigns(metric_date)
    else:
        items, errors = _fetch_active_for_overlays(
            metric_date, google_overlays, meta_overlays
        )

    if not settings.demo_mode and not items and not errors:
        yesterday = (_today(settings) - timedelta(days=1)).isoformat()
        metric_date = yesterday
        items, errors = _fetch_active_for_overlays(
            yesterday, google_overlays, meta_overlays
        )

    items = [i for i in items if _is_running_on(i, metric_date)]
    items.sort(key=lambda x: (-float(x.get("spend") or 0), x.get("name") or ""))
    payload = {
        "metric_date": metric_date,
        "items": items,
        "errors": errors,
        "updated_at": now_iso(),
        "source": "live",
    }
    if items:
        _write_cache(payload, user_id)
        return payload

    # 전부 실패하면 이전 캐시라도 보여 줌
    if errors:
        _ensure_cache_table()
        with get_conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM kv_cache WHERE cache_key = ?",
                (_cache_key(user_id),),
            ).fetchone()
        if row:
            try:
                stale = json.loads(row["payload_json"])
                stale["source"] = "stale_cache"
                stale["errors"] = errors + list(stale.get("errors") or [])
                return stale
            except json.JSONDecodeError:
                pass
    _write_cache(payload, user_id)
    return payload


def get_campaign_adsets(
    *,
    platform: str,
    campaign_id: str,
    account_id: str | None = None,
    metric_date: str | None = None,
    settings: Settings | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    if settings is None:
        if user_id is not None:
            from app.services.connections import settings_for_user

            settings = settings_for_user(user_id)
        else:
            settings = get_settings()
    day = metric_date or _today(settings).isoformat()
    platform = (platform or "").strip().lower()
    campaign_id = str(campaign_id or "").strip()
    if not campaign_id:
        return {"ok": False, "error": "campaign_id 가 필요합니다.", "items": []}

    try:
        if settings.demo_mode:
            items = [
                {
                    "platform": platform or "meta",
                    "account_id": account_id or "act_demo",
                    "campaign_id": campaign_id,
                    "adset_id": "demo-set-1",
                    "name": "Demo Ad Set A",
                    "status": "ACTIVE",
                    "metric_date": day,
                    "spend": 5200.0,
                    "clicks": 40,
                    "installs": 8.0,
                    "install_rate": 20.0,
                    "cpi": 650.0,
                },
                {
                    "platform": platform or "meta",
                    "account_id": account_id or "act_demo",
                    "campaign_id": campaign_id,
                    "adset_id": "demo-set-2",
                    "name": "Demo Ad Set B",
                    "status": "ACTIVE",
                    "metric_date": day,
                    "spend": 3100.0,
                    "clicks": 22,
                    "installs": 4.0,
                    "install_rate": 18.18,
                    "cpi": 775.0,
                },
            ]
        elif platform in {"google_ads", "google"}:
            items = fetch_google_ad_groups(
                campaign_id, day, settings, account_id=account_id or None
            )
        elif platform in {"meta", "facebook"}:
            if not account_id:
                return {
                    "ok": False,
                    "error": "Meta는 account_id 가 필요합니다.",
                    "items": [],
                }
            items = fetch_meta_adsets(account_id, campaign_id, day, settings)
        else:
            return {"ok": False, "error": f"지원하지 않는 platform: {platform}", "items": []}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300], "items": [], "metric_date": day}

    return {
        "ok": True,
        "platform": platform,
        "campaign_id": campaign_id,
        "account_id": account_id,
        "metric_date": day,
        "items": items,
    }
