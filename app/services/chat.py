from __future__ import annotations

from datetime import date
from typing import Any

from app.collectors import (
    collect_all_metrics,
    collect_metrics_range,
    enrich_metrics_rows,
    get_metrics_between,
    get_recent_metrics,
)
from app.db import get_conn, now_iso
from app.services.active_ads import get_active_ads, get_campaign_adsets
from app.services.llm import generate_answer, strip_markdown
from app.services.period import parse_metric_period
from app.services.tasks import due_soon_tasks, list_tasks, monthly_expense_summary


def _save_message(role: str, content: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chat_messages (role, content, created_at) VALUES (?, ?, ?)",
            (role, content, now_iso()),
        )


def recent_chat(limit: int = 20) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT role, content, created_at
            FROM chat_messages
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in reversed(rows):
        item = dict(row)
        if item.get("role") == "assistant":
            item["content"] = strip_markdown(item.get("content") or "")
        items.append(item)
    return items


def _hint_from_collect_notes(notes: list[str]) -> list[str]:
    hints: list[str] = []
    for note in notes:
        if "Session has expired" in note or "access token" in note.lower():
            hints.append("Meta 토큰이 만료됐습니다. 웹의 토큰 안내에서 장기 토큰으로 갱신하세요.")
        elif "google" in note.lower():
            hints.append(f"Google 수집 참고: {note[:180]}")
        else:
            hints.append(f"수집 참고: {note[:180]}")
    return list(dict.fromkeys(hints))


def _is_metrics_question(question: str) -> bool:
    keys = (
        "광고", "성과", "ROAS", "roas", "CPI", "cpi", "클릭", "설치",
        "지출", "비용", "캠페인", "광고세트", "광고 세트", "세트",
        "구글", "메타", "Meta", "Google",
        "이번주", "지난주", "이번달", "지난달", "최근",
    )
    return any(k in question for k in keys)


def _wants_adset_detail(question: str) -> bool:
    keys = ("광고세트", "광고 세트", "세트별", "ad set", "adset", "광고그룹", "광고 그룹")
    return any(k.lower() in question.lower() for k in keys)


def ask(
    question: str,
    refresh_metrics: bool = False,
    user_id: int | None = None,
) -> dict[str, Any]:
    collect_notes: list[str] = []
    period = parse_metric_period(question)
    start = date.fromisoformat(period["start"])
    end = date.fromisoformat(period["end"])
    wants_metrics = refresh_metrics or _is_metrics_question(question)

    if wants_metrics:
        try:
            collected = collect_metrics_range(
                start,
                end,
                fill_missing_only=not refresh_metrics,
                user_id=user_id,
            )
            collect_notes.extend(collected.errors)
        except Exception as exc:  # noqa: BLE001
            collect_notes.append(str(exc))

    metrics = enrich_metrics_rows(get_metrics_between(period["start"], period["end"]))
    if wants_metrics and not metrics:
        # 폴백: 최근 저장분
        try:
            collected = collect_all_metrics(user_id=user_id)
            collect_notes.extend(getattr(collected, "errors", []) or [])
        except Exception as exc:  # noqa: BLE001
            collect_notes.append(str(exc))
        metrics = enrich_metrics_rows(get_recent_metrics(7))

    active = get_active_ads(user_id=user_id)
    active_campaigns = [
        {
            "platform": c.get("platform"),
            "account": c.get("account_name") or c.get("account_id"),
            "campaign_id": c.get("campaign_id"),
            "name": c.get("name"),
            "period": f"{c.get('start_date') or '?'} ~ {c.get('end_date') or '진행중'}",
            "spend": c.get("spend"),
            "clicks": c.get("clicks"),
            "installs": c.get("installs"),
            "install_rate": c.get("install_rate"),
            "cpi": c.get("cpi"),
            "metric_date": c.get("metric_date") or active.get("metric_date"),
        }
        for c in (active.get("items") or [])[:12]
    ]

    adsets_by_campaign: list[dict[str, Any]] = []
    if wants_metrics and _wants_adset_detail(question):
        for camp in (active.get("items") or [])[:5]:
            detail = get_campaign_adsets(
                platform=str(camp.get("platform") or ""),
                campaign_id=str(camp.get("campaign_id") or ""),
                account_id=str(camp.get("account_id") or "") or None,
                metric_date=str(active.get("metric_date") or "") or None,
                user_id=user_id,
            )
            if detail.get("ok"):
                adsets_by_campaign.append(
                    {
                        "campaign": camp.get("name"),
                        "platform": camp.get("platform"),
                        "adsets": [
                            {
                                "name": a.get("name"),
                                "spend": a.get("spend"),
                                "clicks": a.get("clicks"),
                                "installs": a.get("installs"),
                                "install_rate": a.get("install_rate"),
                                "cpi": a.get("cpi"),
                            }
                            for a in (detail.get("items") or [])[:10]
                        ],
                    }
                )

    context = {
        "period": period,
        "metrics": metrics,
        "active_campaigns": active_campaigns,
        "adsets_by_campaign": adsets_by_campaign,
        "tasks": list_tasks("open"),
        "due_soon": due_soon_tasks(7),
        "expenses_month": {
            k: v
            for k, v in monthly_expense_summary().items()
            if k != "items"
        },
        "instruction": (
            f"사용자가 물은 광고 기간은 '{period['label']}' "
            f"({period['start']} ~ {period['end']}) 입니다. "
            "계정 일별 성과는 metrics, 진행 중 캠페인은 active_campaigns 를 우선 사용하세요. "
            "광고세트 질문이면서 adsets_by_campaign 이 있으면 그 데이터를 사용하세요. "
            "없는 수치는 추측하지 마세요."
        ),
    }
    answer = generate_answer(question, context)
    hints = _hint_from_collect_notes(collect_notes)
    if hints:
        answer = answer + "\n\n" + "\n".join(hints)
    _save_message("user", question)
    _save_message("assistant", answer)
    return {
        "question": question,
        "answer": answer,
        "period": period,
        "context_preview": {
            "period": period,
            "metrics_count": len(metrics),
            "tasks": context["tasks"][:5],
        },
    }
