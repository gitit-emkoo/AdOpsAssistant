from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.collectors.google_ads import fetch_google_ads_metrics
from app.collectors.meta_ads import fetch_meta_ads_metrics
from app.collectors.types import AdMetrics
from app.config import Settings, get_settings
from app.db import get_conn, now_iso


def _demo_metrics(platform: str, metric_date: str) -> list[AdMetrics]:
    items: list[AdMetrics] = []
    for idx, name in enumerate((f"{platform} 캠페인 A", f"{platform} 캠페인 B"), start=1):
        seed = sum(ord(c) for c in f"{platform}-{metric_date}-{idx}")
        spend = 60_000 + (seed % 40_000)
        impressions = 9_000 + (seed % 6_000)
        clicks = 210 + (seed % 130)
        installs = 18 + (seed % 20)
        conversions = float(installs)
        value = spend * (1.4 + (seed % 90) / 100)
        items.append(
            AdMetrics(
                platform=platform,
                metric_date=metric_date,
                spend=float(spend),
                impressions=impressions,
                clicks=clicks,
                conversions=conversions,
                conversion_value=float(round(value, 0)),
                installs=float(installs),
                source="demo",
                entity_id=f"demo-{platform}-{idx}",
                entity_name=name,
                entity_type="campaign",
                account_id="demo",
            )
        )
    return items


def collect_platform_metrics(
    platform: str,
    metric_date: date | None = None,
    settings: Settings | None = None,
    user_id: int | None = None,
) -> list[AdMetrics]:
    day = (metric_date or date.today() - timedelta(days=1)).isoformat()
    overlays: list[Settings]
    if user_id is not None:
        from app.services.connections import settings_overlays_for_platform

        overlays = settings_overlays_for_platform(user_id, platform)
    elif settings is not None:
        overlays = [settings]
    else:
        overlays = [get_settings()]

    # demo: 첫 오버레이 기준
    if overlays and overlays[0].demo_mode:
        return _demo_metrics(platform, day)

    items: list[AdMetrics] = []
    errors: list[str] = []
    for overlay in overlays:
        try:
            if platform == "google_ads":
                if not overlay.google_ads_configured:
                    if len(overlays) == 1:
                        return _demo_metrics(platform, day)
                    continue
                items.extend(fetch_google_ads_metrics(day, overlay))
            elif platform == "meta":
                if not overlay.meta_configured:
                    if len(overlays) == 1:
                        return _demo_metrics(platform, day)
                    continue
                items.extend(fetch_meta_ads_metrics(day, overlay))
            else:
                raise ValueError(f"Unsupported platform: {platform}")
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    if errors and not items:
        raise RuntimeError(" / ".join(errors))
    items.sort(key=lambda m: (-m.spend, m.entity_name or ""))
    return items


def save_metrics(metrics: AdMetrics) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO metric_snapshots (
                platform, metric_date, entity_id, entity_name, entity_type, account_id,
                spend, impressions, clicks, installs,
                conversions, conversion_value, raw_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, metric_date, entity_id) DO UPDATE SET
                entity_name=excluded.entity_name,
                entity_type=excluded.entity_type,
                account_id=excluded.account_id,
                spend=excluded.spend,
                impressions=excluded.impressions,
                clicks=excluded.clicks,
                installs=excluded.installs,
                conversions=excluded.conversions,
                conversion_value=excluded.conversion_value,
                raw_json=excluded.raw_json,
                created_at=excluded.created_at
            """,
            (
                metrics.platform,
                metrics.metric_date,
                metrics.entity_id or "",
                metrics.entity_name or "",
                metrics.entity_type or "campaign",
                metrics.account_id or "",
                metrics.spend,
                metrics.impressions,
                metrics.clicks,
                metrics.installs,
                metrics.conversions,
                metrics.conversion_value,
                str(metrics.to_dict()),
                now_iso(),
            ),
        )


def replace_platform_day_metrics(
    platform: str, metric_date: str, items: list[AdMetrics]
) -> None:
    """Replace all rows for a platform/day with campaign-level items."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM metric_snapshots WHERE platform = ? AND metric_date = ?",
            (platform, metric_date),
        )
    if not items:
        # Keep a marker so fill_missing_only won't retry forever.
        save_metrics(
            AdMetrics(
                platform=platform,
                metric_date=metric_date,
                spend=0,
                impressions=0,
                clicks=0,
                conversions=0,
                conversion_value=0,
                installs=0,
                source="live",
                entity_id="__empty__",
                entity_name="(캠페인 없음)",
                entity_type="campaign",
                account_id="",
            )
        )
        return
    for item in items:
        save_metrics(item)


class CollectResult(list):
    """list처럼 쓰되, 실패한 채널 메시지를 errors에 담습니다."""

    errors: list[str]

    def __init__(self, items: list[AdMetrics] | None = None, errors: list[str] | None = None):
        super().__init__(items or [])
        self.errors = list(errors or [])


def collect_all_metrics(
    metric_date: date | None = None,
    user_id: int | None = None,
) -> CollectResult:
    """플랫폼별 캠페인 단위 수집. 한쪽 실패해도 다른 쪽 결과는 저장합니다."""
    results: list[AdMetrics] = []
    errors: list[str] = []
    day = (metric_date or date.today() - timedelta(days=1)).isoformat()
    for platform in ("google_ads", "meta"):
        try:
            items = collect_platform_metrics(
                platform, metric_date, user_id=user_id
            )
            replace_platform_day_metrics(platform, day, items)
            results.extend(items)
        except Exception as exc:  # noqa: BLE001 — 채널 독립 수집
            errors.append(f"{platform}: {exc}")
    return CollectResult(results, errors)


def get_recent_metrics(days: int = 7) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM metric_snapshots
            WHERE COALESCE(entity_id, '') != '__empty__'
            ORDER BY metric_date DESC, platform ASC, spend DESC
            LIMIT ?
            """,
            (max(days * 40, 40),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_metrics_by_date(metric_date: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM metric_snapshots
            WHERE metric_date = ?
              AND COALESCE(entity_id, '') != '__empty__'
            ORDER BY platform ASC, spend DESC, entity_name ASC
            """,
            (metric_date,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_metrics_between(start_date: str, end_date: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM metric_snapshots
            WHERE metric_date >= ?
              AND metric_date <= ?
              AND COALESCE(entity_id, '') != '__empty__'
            ORDER BY metric_date ASC, platform ASC, spend DESC, entity_name ASC
            """,
            (start_date, end_date),
        ).fetchall()
    return [dict(r) for r in rows]


def _has_campaign_rows(platform: str, metric_date: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM metric_snapshots
            WHERE platform = ? AND metric_date = ?
              AND COALESCE(entity_type, 'campaign') = 'campaign'
            LIMIT 1
            """,
            (platform, metric_date),
        ).fetchone()
    return row is not None


def collect_metrics_range(
    start: date,
    end: date,
    *,
    fill_missing_only: bool = True,
    user_id: int | None = None,
    platforms: tuple[str, ...] = ("google_ads", "meta"),
) -> CollectResult:
    """기간 성과를 일별·캠페인별로 수집."""
    if end < start:
        start, end = end, start
    if (end - start).days > 30:
        start = end - timedelta(days=30)

    results: list[AdMetrics] = []
    errors: list[str] = []
    cursor = start
    while cursor <= end:
        day = cursor.isoformat()
        day_date = date.fromisoformat(day)
        cursor += timedelta(days=1)
        for platform in platforms:
            if fill_missing_only and _has_campaign_rows(platform, day):
                continue
            try:
                items = collect_platform_metrics(
                    platform, day_date, user_id=user_id
                )
                replace_platform_day_metrics(platform, day, items)
                results.extend(items)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{day} {platform}: {exc}")
    return CollectResult(results, errors)


def enrich_metrics_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        spend = float(row.get("spend") or 0)
        impressions = int(row.get("impressions") or 0)
        clicks = int(row.get("clicks") or 0)
        installs = float(row.get("installs") or 0)
        conversions = float(row.get("conversions") or 0)
        conversion_value = float(row.get("conversion_value") or 0)
        item = dict(row)
        item["installs"] = installs
        item["entity_name"] = item.get("entity_name") or item.get("entity_id") or ""
        item["ctr"] = round((clicks / impressions * 100) if impressions else 0.0, 2)
        item["cpc"] = round((spend / clicks) if clicks else 0.0, 2)
        item["cpi"] = round((spend / installs) if installs else 0.0, 2)
        item["install_rate"] = round((installs / clicks * 100) if clicks else 0.0, 2)
        item["cpa"] = round((spend / conversions) if conversions else 0.0, 2)
        item["roas"] = round((conversion_value / spend) if spend else 0.0, 2)
        enriched.append(item)
    return enriched
