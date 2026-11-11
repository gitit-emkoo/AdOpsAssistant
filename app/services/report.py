from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.collectors import collect_all_metrics
from app.collectors.types import AdMetrics
from app.config import get_settings
from app.services.emailer import send_email
from app.services.llm import generate_daily_insights
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
        rows.append(
            "<tr>"
            f"<td>{m.platform}</td>"
            f"<td>{m.metric_date}</td>"
            f"<td>{_krw(m.spend)}</td>"
            f"<td>{m.impressions:,}</td>"
            f"<td>{m.clicks:,}</td>"
            f"<td>{m.installs:,.0f}</td>"
            f"<td>{m.install_rate:.1f}%</td>"
            f"<td>{_krw(m.cpi) if m.installs else '-'}</td>"
            f"<td>{m.ctr:.2f}%</td>"
            f"<td>{m.source}</td>"
            "</tr>"
        )
    return (
        "<table border='1' cellpadding='8' cellspacing='0' "
        "style='border-collapse:collapse;font-family:sans-serif;font-size:14px'>"
        "<thead><tr>"
        "<th>채널</th><th>일자</th><th>지출</th><th>노출</th><th>클릭</th>"
        "<th>설치</th><th>설치율</th><th>CPI</th><th>CTR</th><th>소스</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def tasks_to_html(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "<p>임박한 할 일이 없습니다.</p>"
    items: list[str] = []
    for t in tasks:
        amount = f" / {_krw(float(t['amount']))}" if t.get("amount") is not None else ""
        items.append(
            f"<li><strong>[{t.get('category')}]</strong> {t.get('title')} "
            f"(기한: {t.get('due_date') or '없음'}{amount})</li>"
        )
    return "<ul>" + "".join(items) + "</ul>"


def build_email_html(context: dict[str, Any], insights: str, metrics: list[AdMetrics]) -> str:
    expense = context.get("expenses_month") or {}
    return f"""
    <html><body style="font-family:Segoe UI,Apple SD Gothic Neo,sans-serif;line-height:1.5;color:#1a1a1a">
      <h2>매일 광고 성과 리포트</h2>
      <p>데모 모드: <strong>{'ON' if context.get('demo_mode') else 'OFF'}</strong></p>
      {metrics_to_html(metrics)}
      <h3>AI 인사이트 / 오늘 할 일</h3>
      <pre style="white-space:pre-wrap;background:#f6f7f9;padding:12px;border-radius:8px">{insights}</pre>
      <h3>임박 일정 (7일)</h3>
      {tasks_to_html(context.get('due_soon') or [])}
      <h3>이번 달 지출 요약</h3>
      <p>총 {_krw(float(expense.get('total') or 0))} / {expense.get('count', 0)}건</p>
      <p style="color:#666;font-size:12px">웹앱에서 실시간 질의: 로컬 또는 배포된 앱 URL</p>
    </body></html>
    """


def run_daily_report(send: bool = True, metric_date: date | None = None) -> dict[str, Any]:
    day = metric_date or (date.today() - timedelta(days=1))
    metrics = collect_all_metrics(day)
    context = build_context(metrics)
    insights = generate_daily_insights(context)
    html = build_email_html(context, insights, metrics)
    text = insights

    email_result = {"ok": False, "skipped": True, "reason": "send=false"}
    if send:
        subject = f"[AdOps] {day.isoformat()} 광고 성과 & 할 일"
        email_result = send_email(subject, html, text)

    return {
        "metric_date": day.isoformat(),
        "metrics": [m.to_dict() for m in metrics],
        "insights": insights,
        "email": email_result,
        "due_soon": context["due_soon"],
        "expenses_month": context["expenses_month"],
    }
