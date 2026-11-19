from __future__ import annotations

import calendar
import html
import json
from datetime import date, timedelta
from typing import Any

from app.collectors import collect_all_metrics, collect_metrics_range, get_metrics_between
from app.collectors.types import AdMetrics
from app.config import get_settings
from app.db import get_conn, now_iso
from app.services.emailer import send_email
from app.services.llm import (
    generate_daily_insights,
    generate_monthly_insights,
    strip_markdown,
)
from app.services.tasks import due_soon_tasks, list_tasks, monthly_expense_summary


def _krw(value: float) -> str:
    return f"{value:,.0f}원"


def build_context(metrics: list[AdMetrics]) -> dict[str, Any]:
    return {
        "metrics": [m.to_dict() for m in metrics],
        "tasks": list_tasks("open"),
        "due_soon": due_soon_tasks(7),
        "expenses_month": monthly_expense_summary(),
        "demo_mode": get_settings().demo_mode,
    }


def _active_metrics(metrics: list[AdMetrics]) -> list[AdMetrics]:
    """메일/요약용: 실제 집행(노출·클릭·지출) 있는 행만."""
    return [
        m
        for m in metrics
        if (m.spend or 0) > 0 or (m.impressions or 0) > 0 or (m.clicks or 0) > 0
    ]


def metrics_to_html(metrics: list[AdMetrics]) -> str:
    rows = []
    for m in _active_metrics(metrics):
        label = "Google" if m.platform == "google_ads" else "Meta"
        name = html.escape(m.entity_name or m.entity_id or "-")
        rows.append(
            "<tr>"
            f"<td>{label}</td>"
            f"<td>{name}</td>"
            f"<td>{_krw(m.spend)}</td>"
            f"<td>{m.clicks:,}</td>"
            f"<td>{m.installs:,.0f}</td>"
            f"<td>{m.install_rate:.1f}%</td>"
            f"<td>{_krw(m.cpi) if m.installs else '-'}</td>"
            "</tr>"
        )
    if not rows:
        rows.append(
            "<tr><td colspan='7' style='color:#666'>해당일 집행된 광고가 없습니다.</td></tr>"
        )
    return (
        "<table border='0' cellpadding='8' cellspacing='0' "
        "style='border-collapse:collapse;font-family:sans-serif;font-size:14px;"
        "width:100%;max-width:720px'>"
        "<thead><tr style='background:#f3f4f6;text-align:left'>"
        "<th>채널</th><th>광고</th><th>지출</th><th>클릭</th><th>설치</th><th>설치율</th><th>CPI</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def tasks_to_html(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "<p style='margin:0'>임박한 할 일이 없습니다.</p>"
    items: list[str] = []
    for t in tasks[:7]:
        due = t.get("due_date") or t.get("occurrence_date") or "없음"
        items.append(
            f"<li>{html.escape(str(t.get('title')))} "
            f"<span style='color:#666'>({html.escape(str(due))})</span></li>"
        )
    return "<ul style='margin:8px 0 0 18px;padding:0'>" + "".join(items) + "</ul>"


def insights_to_html(insights: str) -> str:
    plain = strip_markdown(insights)
    escaped = html.escape(plain)
    return (
        "<div style='white-space:pre-wrap;line-height:1.55;"
        "background:#f8faf9;padding:12px 14px;border-radius:8px'>"
        f"{escaped}</div>"
    )


def build_email_html(context: dict[str, Any], insights: str, metrics: list[AdMetrics]) -> str:
    expense = context.get("expenses_month") or {}
    metric_date = metrics[0].metric_date if metrics else ""
    site_url = (get_settings().app_base_url or "").rstrip("/") or "http://localhost:8000"
    safe_url = html.escape(site_url, quote=True)
    return f"""
    <html><body style="font-family:Segoe UI,Apple SD Gothic Neo,sans-serif;line-height:1.5;color:#1a1a1a">
      <h2 style="margin:0 0 4px">광고 성과 리포트</h2>
      <p style="margin:0 0 16px;color:#666">기준일 {metric_date}</p>
      <p style="margin:0 0 18px">
        <a href="{safe_url}"
           style="display:inline-block;background:#0a2540;color:#fff;text-decoration:none;
                  padding:10px 16px;border-radius:8px;font-weight:600;font-size:14px">
          대시보드 열기
        </a>
      </p>
      {metrics_to_html(metrics)}
      <h3 style="margin:22px 0 8px">요약 / 할 일</h3>
      {insights_to_html(insights)}
      <h3 style="margin:22px 0 8px">임박 일정</h3>
      {tasks_to_html(context.get('due_soon') or [])}
      <p style="margin:22px 0 0;color:#666;font-size:13px">
        이번 달 지출 {_krw(float(expense.get('total') or 0))} · {expense.get('count', 0)}건
      </p>
      <p style="margin:16px 0 0;color:#666;font-size:13px">
        앱 바로가기: <a href="{safe_url}" style="color:#0a2540">{safe_url}</a>
      </p>
    </body></html>
    """


def run_daily_report(send: bool = True, metric_date: date | None = None) -> dict[str, Any]:
    day = metric_date or (date.today() - timedelta(days=1))
    metrics = _active_metrics(list(collect_all_metrics(day)))
    context = build_context(metrics)
    if metrics:
        insights = strip_markdown(generate_daily_insights(context))
    else:
        insights = (
            "요약:\n"
            f"- {day.isoformat()}에는 집행(노출·지출)된 광고가 없습니다.\n"
            "이상 징후:\n"
            "- 없음\n"
            "오늘 할 일:\n"
            "1. 진행 예정이면 캠페인 상태를 확인하세요."
        )
    html_body = build_email_html(context, insights, metrics)
    site_url = (get_settings().app_base_url or "").rstrip("/") or "http://localhost:8000"
    text = f"{insights}\n\n대시보드: {site_url}"

    email_result = {"ok": False, "skipped": True, "reason": "send=false"}
    if send:
        subject = f"[AdOps] {day.isoformat()} 광고 성과"
        email_result = send_email(subject, html_body, text)

    return {
        "metric_date": day.isoformat(),
        "metrics": [m.to_dict() for m in metrics],
        "insights": insights,
        "email": email_result,
        "due_soon": context["due_soon"],
        "expenses_month": context["expenses_month"],
    }


def previous_month(today: date | None = None) -> tuple[int, int]:
    day = today or date.today()
    first = day.replace(day=1)
    last_prev = first - timedelta(days=1)
    return last_prev.year, last_prev.month


def month_bounds(year: int, month: int, *, clamp_to_yesterday: bool = True) -> tuple[date, date]:
    start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = date(year, month, last_day)
    if clamp_to_yesterday:
        yesterday = date.today() - timedelta(days=1)
        if end > yesterday:
            end = yesterday
        if start > end:
            end = start
    return start, end


def _empty_totals() -> dict[str, float | int]:
    return {
        "spend": 0.0,
        "impressions": 0,
        "clicks": 0,
        "installs": 0.0,
        "conversions": 0.0,
    }


def _add_row(bucket: dict[str, float | int], row: dict[str, Any]) -> None:
    bucket["spend"] = float(bucket["spend"]) + float(row.get("spend") or 0)
    bucket["impressions"] = int(bucket["impressions"]) + int(row.get("impressions") or 0)
    bucket["clicks"] = int(bucket["clicks"]) + int(row.get("clicks") or 0)
    bucket["installs"] = float(bucket["installs"]) + float(row.get("installs") or 0)
    bucket["conversions"] = float(bucket["conversions"]) + float(row.get("conversions") or 0)


def _with_rates(bucket: dict[str, float | int]) -> dict[str, Any]:
    spend = float(bucket["spend"])
    impressions = int(bucket["impressions"])
    clicks = int(bucket["clicks"])
    installs = float(bucket["installs"])
    return {
        **bucket,
        "spend": round(spend, 2),
        "impressions": impressions,
        "clicks": clicks,
        "installs": round(installs, 2),
        "conversions": round(float(bucket["conversions"]), 2),
        "ctr": round((clicks / impressions * 100) if impressions else 0.0, 2),
        "cpi": round((spend / installs) if installs else 0.0, 2),
        "install_rate": round((installs / clicks * 100) if clicks else 0.0, 2),
    }


def aggregate_month_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = _empty_totals()
    by_platform: dict[str, dict[str, float | int]] = {}
    by_day: dict[str, dict[str, float | int]] = {}
    by_campaign: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        _add_row(totals, row)
        platform = str(row.get("platform") or "unknown")
        by_platform.setdefault(platform, _empty_totals())
        _add_row(by_platform[platform], row)
        day = str(row.get("metric_date") or "")
        if day:
            by_day.setdefault(day, _empty_totals())
            _add_row(by_day[day], row)
        entity_id = str(row.get("entity_id") or "")
        entity_name = str(row.get("entity_name") or entity_id or "(이름 없음)")
        key = (platform, entity_id, entity_name)
        if key not in by_campaign:
            by_campaign[key] = {
                **_empty_totals(),
                "platform": platform,
                "entity_id": entity_id,
                "entity_name": entity_name,
            }
        _add_row(by_campaign[key], row)
    platforms = [
        {"platform": key, **_with_rates(val)}
        for key, val in sorted(by_platform.items())
    ]
    days = [
        {"metric_date": key, **_with_rates(val)}
        for key, val in sorted(by_day.items())
    ]
    campaigns = [
        {
            "platform": val["platform"],
            "entity_id": val["entity_id"],
            "entity_name": val["entity_name"],
            **_with_rates(val),
        }
        for val in sorted(
            by_campaign.values(),
            key=lambda x: (-float(x.get("spend") or 0), str(x.get("entity_name") or "")),
        )
    ]
    return {
        "totals": _with_rates(totals),
        "platforms": platforms,
        "campaigns": campaigns,
        "days": days,
        "day_count": len(days),
        "row_count": len(rows),
    }


def _platform_label(platform: str) -> str:
    if platform == "google_ads":
        return "Google"
    if platform == "meta":
        return "Meta"
    return platform


def monthly_platforms_to_html(platforms: list[dict[str, Any]]) -> str:
    rows = []
    for p in platforms:
        rows.append(
            "<tr>"
            f"<td>{html.escape(_platform_label(str(p.get('platform'))))}</td>"
            f"<td>{_krw(float(p.get('spend') or 0))}</td>"
            f"<td>{int(p.get('clicks') or 0):,}</td>"
            f"<td>{float(p.get('installs') or 0):,.0f}</td>"
            f"<td>{float(p.get('install_rate') or 0):.1f}%</td>"
            f"<td>{_krw(float(p.get('cpi') or 0)) if float(p.get('installs') or 0) else '-'}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='6'>데이터 없음</td></tr>")
    return (
        "<table border='0' cellpadding='8' cellspacing='0' "
        "style='border-collapse:collapse;font-family:sans-serif;font-size:14px;"
        "width:100%;max-width:640px'>"
        "<thead><tr style='background:#f3f4f6;text-align:left'>"
        "<th>채널</th><th>지출</th><th>클릭</th><th>설치</th><th>설치율</th><th>CPI</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def monthly_campaigns_to_html(campaigns: list[dict[str, Any]], *, limit: int = 20) -> str:
    rows = []
    for p in campaigns[:limit]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(_platform_label(str(p.get('platform'))))}</td>"
            f"<td>{html.escape(str(p.get('entity_name') or '-'))}</td>"
            f"<td>{_krw(float(p.get('spend') or 0))}</td>"
            f"<td>{int(p.get('clicks') or 0):,}</td>"
            f"<td>{float(p.get('installs') or 0):,.0f}</td>"
            f"<td>{_krw(float(p.get('cpi') or 0)) if float(p.get('installs') or 0) else '-'}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='6'>데이터 없음</td></tr>")
    return (
        "<table border='0' cellpadding='8' cellspacing='0' "
        "style='border-collapse:collapse;font-family:sans-serif;font-size:14px;"
        "width:100%;max-width:720px'>"
        "<thead><tr style='background:#f3f4f6;text-align:left'>"
        "<th>채널</th><th>광고</th><th>지출</th><th>클릭</th><th>설치</th><th>CPI</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def build_monthly_email_html(report: dict[str, Any]) -> str:
    site_url = (get_settings().app_base_url or "").rstrip("/") or "http://localhost:8000"
    reports_url = f"{site_url}/reports?year={report['year']}&month={report['month']}"
    safe_url = html.escape(reports_url, quote=True)
    totals = report.get("totals") or {}
    return f"""
    <html><body style="font-family:Segoe UI,Apple SD Gothic Neo,sans-serif;line-height:1.5;color:#1a1a1a">
      <h2 style="margin:0 0 4px">월간 광고 성과 리포트</h2>
      <p style="margin:0 0 16px;color:#666">
        {html.escape(report.get('label') or '')}
        ({html.escape(report.get('start_date') or '')} ~ {html.escape(report.get('end_date') or '')})
      </p>
      <p style="margin:0 0 18px">
        <a href="{safe_url}"
           style="display:inline-block;background:#0a2540;color:#fff;text-decoration:none;
                  padding:10px 16px;border-radius:8px;font-weight:600;font-size:14px">
          월간 리포트 열기
        </a>
      </p>
      <p style="margin:0 0 12px">
        총 지출 <strong>{_krw(float(totals.get('spend') or 0))}</strong> ·
        클릭 <strong>{int(totals.get('clicks') or 0):,}</strong> ·
        설치 <strong>{float(totals.get('installs') or 0):,.0f}</strong> ·
        CPI <strong>{_krw(float(totals.get('cpi') or 0)) if float(totals.get('installs') or 0) else '-'}</strong>
      </p>
      {monthly_platforms_to_html(report.get('platforms') or [])}
      <h3 style="margin:22px 0 8px">광고별 (상위)</h3>
      {monthly_campaigns_to_html(report.get('campaigns') or [])}
      <h3 style="margin:22px 0 8px">월간 요약</h3>
      {insights_to_html(str(report.get('insights') or ''))}
      <p style="margin:16px 0 0;color:#666;font-size:13px">
        앱 바로가기: <a href="{safe_url}" style="color:#0a2540">{safe_url}</a>
      </p>
    </body></html>
    """


def save_monthly_report_record(
    year_month: str,
    *,
    start_date: str,
    end_date: str,
    summary: dict[str, Any],
    insights: str,
    emailed: bool = False,
) -> None:
    now = now_iso()
    payload = json.dumps(summary, ensure_ascii=False)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, emailed_at FROM monthly_reports WHERE year_month = ?",
            (year_month,),
        ).fetchone()
        if existing:
            emailed_at = now if emailed else existing["emailed_at"]
            conn.execute(
                """
                UPDATE monthly_reports
                SET start_date = ?, end_date = ?, summary_json = ?, insights = ?,
                    emailed_at = ?, updated_at = ?
                WHERE year_month = ?
                """,
                (
                    start_date,
                    end_date,
                    payload,
                    insights,
                    emailed_at,
                    now,
                    year_month,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO monthly_reports (
                    year_month, start_date, end_date, summary_json, insights,
                    emailed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    year_month,
                    start_date,
                    end_date,
                    payload,
                    insights,
                    now if emailed else None,
                    now,
                    now,
                ),
            )


def get_monthly_report_record(year_month: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM monthly_reports WHERE year_month = ?",
            (year_month,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["summary"] = json.loads(item.get("summary_json") or "{}")
    except Exception:  # noqa: BLE001
        item["summary"] = {}
    return item


def list_monthly_report_records(limit: int = 12) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT year_month, start_date, end_date, emailed_at, updated_at
            FROM monthly_reports
            ORDER BY year_month DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def build_monthly_report(
    year: int,
    month: int,
    *,
    ensure_data: bool = False,
    force_insights: bool = False,
    user_id: int | None = None,
) -> dict[str, Any]:
    start, end = month_bounds(year, month)
    year_month = f"{year:04d}-{month:02d}"
    label = f"{year}년 {month}월"
    collect_errors: list[str] = []
    if ensure_data and end >= start:
        collected = collect_metrics_range(
            start, end, fill_missing_only=True, user_id=user_id
        )
        collect_errors = list(collected.errors)

    rows = get_metrics_between(start.isoformat(), end.isoformat())
    agg = aggregate_month_rows(rows)
    cached = get_monthly_report_record(year_month)
    insights = (cached or {}).get("insights") or ""
    if force_insights or (not insights and agg["day_count"] > 0):
        context = {
            "year_month": label,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "totals": agg["totals"],
            "platforms": agg["platforms"],
            "campaigns": agg["campaigns"][:15],
            "days": agg["days"][-10:],
            "demo_mode": get_settings().demo_mode,
        }
        insights = strip_markdown(generate_monthly_insights(context))
    elif not insights:
        insights = "이 달 데이터가 없습니다. ‘데이터 채우기’로 수집한 뒤 요약을 만들어 주세요."

    report = {
        "year": year,
        "month": month,
        "year_month": year_month,
        "label": label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "totals": agg["totals"],
        "platforms": agg["platforms"],
        "campaigns": agg["campaigns"],
        "days": agg["days"],
        "day_count": agg["day_count"],
        "insights": insights,
        "emailed_at": (cached or {}).get("emailed_at"),
        "collect_errors": collect_errors,
    }
    save_monthly_report_record(
        year_month,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        summary={
            "totals": agg["totals"],
            "platforms": agg["platforms"],
            "campaigns": agg["campaigns"][:30],
            "day_count": agg["day_count"],
        },
        insights=insights,
        emailed=False,
    )
    return report


def run_monthly_report(
    *,
    year: int | None = None,
    month: int | None = None,
    send: bool = True,
    ensure_data: bool = True,
    user_id: int | None = None,
) -> dict[str, Any]:
    if year is None or month is None:
        year, month = previous_month()
    report = build_monthly_report(
        year,
        month,
        ensure_data=ensure_data,
        force_insights=True,
        user_id=user_id,
    )
    site_url = (get_settings().app_base_url or "").rstrip("/") or "http://localhost:8000"
    reports_url = f"{site_url}/reports?year={year}&month={month}"
    text = f"{report.get('insights') or ''}\n\n월간 리포트: {reports_url}"
    html_body = build_monthly_email_html(report)

    email_result = {"ok": False, "skipped": True, "reason": "send=false"}
    if send:
        subject = f"[AdOps] {report['label']} 월간 광고 성과"
        email_result = send_email(subject, html_body, text)
        if email_result.get("ok"):
            save_monthly_report_record(
                report["year_month"],
                start_date=report["start_date"],
                end_date=report["end_date"],
                summary={
                    "totals": report["totals"],
                    "platforms": report["platforms"],
                    "day_count": report["day_count"],
                },
                insights=report.get("insights") or "",
                emailed=True,
            )
            report["emailed_at"] = now_iso()

    return {
        **report,
        "email": email_result,
    }
