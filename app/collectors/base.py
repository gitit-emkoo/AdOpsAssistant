from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.collectors.google_ads import fetch_google_ads_metrics
from app.collectors.meta_ads import fetch_meta_ads_metrics
from app.collectors.types import AdMetrics
from app.config import Settings, get_settings
from app.db import get_conn, now_iso


def _demo_metrics(platform: str, metric_date: str) -> AdMetrics:
    seed = sum(ord(c) for c in f"{platform}-{metric_date}")
    spend = 120_000 + (seed % 80_000)
    impressions = 18_000 + (seed % 12_000)
    clicks = 420 + (seed % 260)
    installs = 35 + (seed % 40)
    conversions = float(installs)
    value = spend * (1.4 + (seed % 90) / 100)
    return AdMetrics(
        platform=platform,
        metric_date=metric_date,
        spend=float(spend),
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        conversion_value=float(round(value, 0)),
        installs=float(installs),
        source="demo",
    )


def collect_platform_metrics(
    platform: str,
    metric_date: date | None = None,
    settings: Settings | None = None,
    user_id: int | None = None,
) -> AdMetrics:
    if settings is None:
        if user_id is not None:
            from app.services.connections import settings_for_user

            settings = settings_for_user(user_id)
        else:
            settings = get_settings()
    day = (metric_date or date.today() - timedelta(days=1)).isoformat()

    if settings.demo_mode:
        return _demo_metrics(platform, day)

    if platform == "google_ads":
        if not settings.google_ads_configured:
            return _demo_metrics(platform, day)
        return fetch_google_ads_metrics(day, settings)

    if platform == "meta":
        if not settings.meta_configured:
            return _demo_metrics(platform, day)
        return fetch_meta_ads_metrics(day, settings)

    raise ValueError(f"Unsupported platform: {platform}")


def save_metrics(metrics: AdMetrics) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO metric_snapshots (
                platform, metric_date, spend, impressions, clicks, installs,
                conversions, conversion_value, raw_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, metric_date) DO UPDATE SET
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
    """플랫폼별 수집. 한쪽 실패해도 다른 쪽 결과는 저장합니다."""
    results: list[AdMetrics] = []
    errors: list[str] = []
    for platform in ("google_ads", "meta"):
        try:
            item = collect_platform_metrics(
                platform, metric_date, user_id=user_id
            )
            save_metrics(item)
            results.append(item)
        except Exception as exc:  # noqa: BLE001 — 채널 독립 수집
            errors.append(f"{platform}: {exc}")
    return CollectResult(results, errors)


def get_recent_metrics(days: int = 7) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM metric_snapshots
            ORDER BY metric_date DESC, platform ASC
            LIMIT ?
            """,
            (days * 2,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_metrics_by_date(metric_date: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM metric_snapshots
            WHERE metric_date = ?
            ORDER BY platform ASC
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
            ORDER BY metric_date ASC, platform ASC
            """,
            (start_date, end_date),
        ).fetchall()
    return [dict(r) for r in rows]


def collect_metrics_range(
    start: date,
    end: date,
    *,
    fill_missing_only: bool = True,
    user_id: int | None = None,
    platforms: tuple[str, ...] = ("google_ads", "meta"),
) -> CollectResult:
    """기간 성과를 일별로 수집. 기본은 플랫폼별로 DB에 없는 날짜만 채웁니다."""
    if end < start:
        start, end = end, start
    # 한 번에 너무 많이 치지 않도록 최대 31일
    if (end - start).days > 30:
        start = end - timedelta(days=30)

    existing: set[tuple[str, str]] = set()
    if fill_missing_only:
        for row in get_metrics_between(start.isoformat(), end.isoformat()):
            existing.add((str(row.get("metric_date")), str(row.get("platform"))))

    results: list[AdMetrics] = []
    errors: list[str] = []
    cursor = start
    while cursor <= end:
        day = cursor.isoformat()
        day_date = date.fromisoformat(day)
        cursor += timedelta(days=1)
        for platform in platforms:
            if fill_missing_only and (day, platform) in existing:
                continue
            try:
                item = collect_platform_metrics(
                    platform, day_date, user_id=user_id
                )
                save_metrics(item)
                results.append(item)
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
        item["ctr"] = round((clicks / impressions * 100) if impressions else 0.0, 2)
        item["cpc"] = round((spend / clicks) if clicks else 0.0, 2)
        item["cpi"] = round((spend / installs) if installs else 0.0, 2)
        item["install_rate"] = round((installs / clicks * 100) if clicks else 0.0, 2)
        item["cpa"] = round((spend / conversions) if conversions else 0.0, 2)
        item["roas"] = round((conversion_value / spend) if spend else 0.0, 2)
        enriched.append(item)
    return enriched
