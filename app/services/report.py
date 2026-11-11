from __future__ import annotations

import html
from datetime import date, timedelta
from typing import Any

from app.collectors import collect_all_metrics
from app.collectors.types import AdMetrics
from app.config import get_settings
from app.services.emailer import send_email
from app.services.llm import generate_daily_insights, strip_markdown
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


def metrics_to_html(metrics: list[AdMetrics]) -> str:
    rows = []
    for m in metrics:
        label = "Google" if m.platform == "google_ads" else "Meta"
        rows.append(
            "<tr>"
            f"<td>{label}</td>"
            f"<td>{_krw(m.spend)}</td>"
            f"<td>{m.clicks:,}</td>"
            f"<td>{m.installs:,.0f}</td>"
            f"<td>{m.install_rate:.1f}%</td>"
            f"<td>{_krw(m.cpi) if m.installs else '-'}</td>"
            "</tr>"
        )
    return (
        "<table border='0' cellpadding='8' cellspacing='0' "
        "style='border-collapse:collapse;font-family:sans-serif;font-size:14px;"
        "width:100%;max-width:640px'>"
        "<thead><tr style='background:#f3f4f6;text-align:left'>"
        "<th>채널</th><th>지출</th><th>클릭</th><th>설치</th><th>설치율</th><th>CPI</th>"
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
    return f"""
    <html><body style="font-family:Segoe UI,Apple SD Gothic Neo,sans-serif;line-height:1.5;color:#1a1a1a">
      <h2 style="margin:0 0 4px">광고 성과 리포트</h2>
      <p style="margin:0 0 16px;color:#666">기준일 {metric_date}</p>
      {metrics_to_html(metrics)}
      <h3 style="margin:22px 0 8px">요약 / 할 일</h3>
      {insights_to_html(insights)}
      <h3 style="margin:22px 0 8px">임박 일정</h3>
      {tasks_to_html(context.get('due_soon') or [])}
      <p style="margin:22px 0 0;color:#666;font-size:13px">
        이번 달 지출 {_krw(float(expense.get('total') or 0))} · {expense.get('count', 0)}건
      </p>
    </body></html>
    """


def run_daily_report(send: bool = True, metric_date: date | None = None) -> dict[str, Any]:
    day = metric_date or (date.today() - timedelta(days=1))
    metrics = collect_all_metrics(day)
    context = build_context(metrics)
    insights = strip_markdown(generate_daily_insights(context))
    html = build_email_html(context, insights, metrics)
    text = insights

    email_result = {"ok": False, "skipped": True, "reason": "send=false"}
    if send:
        subject = f"[AdOps] {day.isoformat()} 광고 성과"
        email_result = send_email(subject, html, text)

    return {
        "metric_date": day.isoformat(),
        "metrics": [m.to_dict() for m in metrics],
        "insights": insights,
        "email": email_result,
        "due_soon": context["due_soon"],
        "expenses_month": context["expenses_month"],
    }
