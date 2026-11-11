from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from app.db import get_conn, now_iso, today_iso


def list_tasks(status: str | None = "open") -> list[dict[str, Any]]:
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = ?
                ORDER BY
                  CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
                  due_date ASC,
                  id DESC
                """,
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY id DESC LIMIT 100"
            ).fetchall()
    return [dict(r) for r in rows]


def create_task(
    title: str,
    category: str = "general",
    due_date: str | None = None,
    amount: float | None = None,
    notes: str | None = None,
    recurrence: str = "none",
    recur_day: int | None = None,
) -> dict[str, Any]:
    recurrence = (recurrence or "none").lower()
    if recurrence not in {"none", "monthly"}:
        raise ValueError("recurrence must be none or monthly")

    if recurrence == "monthly":
        if not recur_day or not (1 <= int(recur_day) <= 31):
            raise ValueError("monthly 반복은 recur_day(1-31)가 필요합니다.")
        due_date = None
        recur_day = int(recur_day)
    else:
        recur_day = None

    ts = now_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks (
                title, category, due_date, amount, notes, status,
                recurrence, recur_day, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
            """,
            (title, category, due_date, amount, notes, recurrence, recur_day, ts, ts),
        )
        task_id = cur.lastrowid
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row)


def _occurrence_date(year: int, month: int, recur_day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(int(recur_day), last_day))


def _completed_set(conn, task_ids: list[int], start: str, end: str) -> set[tuple[int, str]]:
    if not task_ids:
        return set()
    placeholders = ",".join("?" for _ in task_ids)
    rows = conn.execute(
        f"""
        SELECT task_id, occurrence_date
        FROM task_completions
        WHERE task_id IN ({placeholders})
          AND occurrence_date >= ?
          AND occurrence_date <= ?
        """,
        (*task_ids, start, end),
    ).fetchall()
    return {(int(r["task_id"]), r["occurrence_date"]) for r in rows}


def calendar_month(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    today = date.today()
    year = year or today.year
    month = month or today.month
    first = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = date(year, month, last_day)
    start_pad = first.weekday()  # Monday-start grid

    with get_conn() as conn:
        one_time = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'open'
              AND COALESCE(recurrence, 'none') = 'none'
              AND due_date IS NOT NULL
              AND due_date >= ?
              AND due_date <= ?
            ORDER BY due_date ASC, id ASC
            """,
            (first.isoformat(), last.isoformat()),
        ).fetchall()
        recurring = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'open'
              AND recurrence = 'monthly'
              AND recur_day IS NOT NULL
            ORDER BY recur_day ASC, id ASC
            """,
        ).fetchall()

        events: list[dict[str, Any]] = []
        for row in one_time:
            item = dict(row)
            item["occurrence_date"] = item["due_date"]
            item["is_recurring"] = False
            item["completed"] = False
            events.append(item)

        recurring_dicts = [dict(r) for r in recurring]
        completed = _completed_set(
            conn,
            [int(r["id"]) for r in recurring_dicts],
            first.isoformat(),
            last.isoformat(),
        )
        for row in recurring_dicts:
            occ = _occurrence_date(year, month, int(row["recur_day"]))
            item = dict(row)
            item["occurrence_date"] = occ.isoformat()
            item["is_recurring"] = True
            item["completed"] = (int(row["id"]), occ.isoformat()) in completed
            events.append(item)

    by_date: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_date.setdefault(event["occurrence_date"], []).append(event)

    cells: list[dict[str, Any]] = []
    # leading blanks
    for _ in range(start_pad):
        cells.append({"date": None, "events": []})
    for day in range(1, last_day + 1):
        d = date(year, month, day).isoformat()
        cells.append(
            {
                "date": d,
                "day": day,
                "is_today": d == today.isoformat(),
                "events": by_date.get(d, []),
            }
        )
    while len(cells) % 7 != 0:
        cells.append({"date": None, "events": []})

    prev_month = month - 1 or 12
    prev_year = year - 1 if month == 1 else year
    next_month = month + 1 if month < 12 else 1
    next_year = year + 1 if month == 12 else year

    return {
        "year": year,
        "month": month,
        "label": f"{year}년 {month}월",
        "cells": cells,
        "events": sorted(events, key=lambda e: (e["occurrence_date"], e["id"])),
        "prev": {"year": prev_year, "month": prev_month},
        "next": {"year": next_year, "month": next_month},
    }


def complete_task(task_id: int, occurrence_date: str | None = None) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        task = dict(row)
        if (task.get("recurrence") or "none") == "monthly":
            if not occurrence_date:
                raise ValueError("반복 할 일은 occurrence_date가 필요합니다.")
            conn.execute(
                """
                INSERT OR IGNORE INTO task_completions (task_id, occurrence_date, completed_at)
                VALUES (?, ?, ?)
                """,
                (task_id, occurrence_date, now_iso()),
            )
            task["occurrence_date"] = occurrence_date
            task["completed"] = True
            return task

        conn.execute(
            "UPDATE tasks SET status = 'done', updated_at = ? WHERE id = ?",
            (now_iso(), task_id),
        )
        updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(updated) if updated else None


def due_soon_tasks(within_days: int = 7) -> list[dict[str, Any]]:
    today = date.today()
    end = today + timedelta(days=within_days)
    items: list[dict[str, Any]] = []

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'open'
              AND COALESCE(recurrence, 'none') = 'none'
              AND due_date IS NOT NULL
              AND due_date <= ?
              AND due_date >= ?
            ORDER BY due_date ASC
            """,
            (end.isoformat(), today.isoformat()),
        ).fetchall()
        items.extend(dict(r) for r in rows)

        recurring = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'open'
              AND recurrence = 'monthly'
              AND recur_day IS NOT NULL
            """
        ).fetchall()
        recurring_dicts = [dict(r) for r in recurring]
        completed = _completed_set(
            conn,
            [int(r["id"]) for r in recurring_dicts],
            today.isoformat(),
            end.isoformat(),
        )

        cursor = today
        while cursor <= end:
            for row in recurring_dicts:
                occ = _occurrence_date(cursor.year, cursor.month, int(row["recur_day"]))
                if occ != cursor:
                    continue
                if (int(row["id"]), occ.isoformat()) in completed:
                    continue
                item = dict(row)
                item["due_date"] = occ.isoformat()
                item["occurrence_date"] = occ.isoformat()
                items.append(item)
            cursor += timedelta(days=1)

    items.sort(key=lambda x: x.get("due_date") or x.get("occurrence_date") or "")
    return items


def seed_default_tasks_if_empty() -> None:
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
        if count:
            return

    today = date.today()
    create_task("보험료 납부", category="finance", recurrence="monthly", recur_day=10)
    create_task("원천세 신고", category="tax", recurrence="monthly", recur_day=10)
    samples = [
        ("부가세 예정 자료 정리", "tax", (today + timedelta(days=5)).isoformat()),
        ("메타 소재 3종 교체 검토", "ads", today.isoformat()),
    ]
    for title, category, due in samples:
        create_task(title, category=category, due_date=due)


def list_expenses(year_month: str | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if year_month:
            rows = conn.execute(
                """
                SELECT * FROM expenses
                WHERE substr(spent_on, 1, 7) = ?
                ORDER BY spent_on DESC, id DESC
                """,
                (year_month,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM expenses ORDER BY spent_on DESC, id DESC LIMIT 200"
            ).fetchall()
    return [dict(r) for r in rows]


def add_expense(
    amount: float,
    category: str = "misc",
    vendor: str | None = None,
    notes: str | None = None,
    spent_on: str | None = None,
) -> dict[str, Any]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO expenses (spent_on, category, vendor, amount, notes, source, created_at)
            VALUES (?, ?, ?, ?, ?, 'manual', ?)
            """,
            (spent_on or today_iso(), category, vendor, amount, notes, now_iso()),
        )
        expense_id = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
    return dict(row)


def monthly_expense_summary(year_month: str | None = None) -> dict[str, Any]:
    ym = year_month or date.today().strftime("%Y-%m")
    rows = list_expenses(ym)
    total = sum(float(r["amount"]) for r in rows)
    by_category: dict[str, float] = {}
    for r in rows:
        by_category[r["category"]] = by_category.get(r["category"], 0) + float(r["amount"])
    return {
        "year_month": ym,
        "total": total,
        "count": len(rows),
        "by_category": by_category,
        "items": rows,
    }


def ensure_recurring_defaults() -> None:
    """기존 DB에도 고정 월 할 일이 없으면 추가."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT title FROM tasks
            WHERE recurrence = 'monthly' AND status = 'open'
            """
        ).fetchall()
        titles = {r["title"] for r in rows}
    if "보험료 납부" not in titles:
        create_task("보험료 납부", category="finance", recurrence="monthly", recur_day=10)
    if "원천세 신고" not in titles:
        create_task("원천세 신고", category="tax", recurrence="monthly", recur_day=10)
