from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any


def _week_bounds(day: date) -> tuple[date, date]:
    # 월~일
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)
    return start, end


def parse_metric_period(
    question: str,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """질문에서 광고 성과 조회 기간을 뽑습니다. 없으면 최근 7일."""
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    text = (question or "").strip()
    lower = text.lower()

    # 명시 날짜 범위: 2026-11-01 ~ 2026-11-10 / 11/1-11/10
    range_iso = re.search(
        r"(20\d{2}-\d{1,2}-\d{1,2})\s*(?:~|-|부터|~|–|—)\s*(20\d{2}-\d{1,2}-\d{1,2})",
        text,
    )
    if range_iso:
        start = date.fromisoformat(_norm_iso(range_iso.group(1)))
        end = date.fromisoformat(_norm_iso(range_iso.group(2)))
        return _pack(start, end, "지정 기간", today)

    range_slash = re.search(
        r"(\d{1,2})[./](\d{1,2})\s*(?:~|-|부터)\s*(\d{1,2})[./](\d{1,2})",
        text,
    )
    if range_slash:
        y = today.year
        start = date(y, int(range_slash.group(1)), int(range_slash.group(2)))
        end = date(y, int(range_slash.group(3)), int(range_slash.group(4)))
        return _pack(start, end, "지정 기간", today)

    single_iso = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", text)
    if single_iso and any(k in text for k in ("날", "일자", "하루", "당일")):
        day = date.fromisoformat(_norm_iso(single_iso.group(1)))
        return _pack(day, day, "지정일", today)

    if re.search(r"어제", text):
        return _pack(yesterday, yesterday, "어제", today)
    if re.search(r"그제|그저께", text):
        day = today - timedelta(days=2)
        return _pack(day, day, "그저께", today)
    if re.search(r"오늘", text) and re.search(r"광고|성과|지출|클릭|설치", text):
        return _pack(today, today, "오늘", today)

    if re.search(r"이번\s*주|금주", text):
        start, end = _week_bounds(today)
        end = min(end, yesterday)
        return _pack(start, end, "이번 주", today)
    if re.search(r"지난\s*주|저번\s*주", text):
        start, end = _week_bounds(today - timedelta(days=7))
        return _pack(start, end, "지난 주", today)
    if re.search(r"이번\s*달|금월", text):
        start = today.replace(day=1)
        end = yesterday
        return _pack(start, end, "이번 달", today)
    if re.search(r"지난\s*달|저번\s*달|전월", text):
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        start = end.replace(day=1)
        return _pack(start, end, "지난 달", today)

    days_match = re.search(r"최근\s*(\d{1,2})\s*일", text)
    if days_match:
        n = max(1, min(31, int(days_match.group(1))))
        end = yesterday
        start = end - timedelta(days=n - 1)
        return _pack(start, end, f"최근 {n}일", today)

    if re.search(r"이번\s*주말|주말", text) and re.search(r"광고|성과", text):
        # 직전 토~일
        weekday = today.weekday()
        last_sunday = today - timedelta(days=(weekday + 1) % 7 or 7)
        last_saturday = last_sunday - timedelta(days=1)
        return _pack(last_saturday, last_sunday, "지난 주말", today)

    # 기본: 최근 7일 (어제 기준)
    end = yesterday
    start = end - timedelta(days=6)
    label = "최근 7일"
    if re.search(r"이번주\s*모든|모든\s*광고|주간", text):
        start, week_end = _week_bounds(today)
        end = min(week_end, yesterday)
        label = "이번 주"
    return _pack(start, end, label, today)


def _norm_iso(value: str) -> str:
    y, m, d = value.split("-")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _pack(start: date, end: date, label: str, today: date) -> dict[str, Any]:
    if end > today:
        end = today
    if start > end:
        start = end
    # 미래만 물어본 경우 방어
    if start > today:
        start = today
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "label": label,
        "today": today.isoformat(),
        "days": (end - start).days + 1,
    }
