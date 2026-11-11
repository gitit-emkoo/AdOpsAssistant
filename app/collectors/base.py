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
) -> AdMetrics:
    settings = settings or get_settings()
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


def collect_all_metrics(metric_date: date | None = None) -> list[AdMetrics]:
    results = [
        collect_platform_metrics("google_ads", metric_date),
        collect_platform_metrics("meta", metric_date),
    ]
    for item in results:
        save_metrics(item)
    return results


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
