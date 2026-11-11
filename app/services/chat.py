from __future__ import annotations

from typing import Any

from app.collectors import collect_all_metrics, get_recent_metrics
from app.db import get_conn, now_iso
from app.services.llm import generate_answer, strip_markdown
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


def ask(question: str, refresh_metrics: bool = False) -> dict[str, Any]:
    if refresh_metrics:
        collect_all_metrics()

    recent = get_recent_metrics(7)
    if not recent:
        collect_all_metrics()
        recent = get_recent_metrics(7)

    context = {
        "metrics": recent,
        "tasks": list_tasks("open"),
        "due_soon": due_soon_tasks(7),
        "expenses_month": {
            k: v
            for k, v in monthly_expense_summary().items()
            if k != "items"
        },
    }
    answer = generate_answer(question, context)
    _save_message("user", question)
    _save_message("assistant", answer)
    return {"question": question, "answer": answer, "context_preview": context}
