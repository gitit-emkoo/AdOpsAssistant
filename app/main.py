from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.collectors import (
    collect_all_metrics,
    enrich_metrics_rows,
    get_metrics_by_date,
    get_recent_metrics,
)
from app.config import get_settings
from app.db import init_db
from app.services.chat import ask, recent_chat
from app.services.integrations import (
    ensure_integration_table,
    extend_meta_token,
    integration_overview,
)
from app.services.report import run_daily_report
from app.services.tasks import (
    add_expense,
    calendar_month,
    complete_task,
    create_task,
    ensure_recurring_defaults,
    list_expenses,
    list_tasks,
    monthly_expense_summary,
    seed_default_tasks_if_empty,
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="AdOps Assistant")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    ensure_integration_table()
    seed_default_tasks_if_empty()
    ensure_recurring_defaults()
    # Ensure at least one demo snapshot exists for the UI.
    if not get_recent_metrics(1):
        collect_all_metrics()


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    refresh_metrics: bool = False


class TaskRequest(BaseModel):
    title: str
    category: str = "general"
    due_date: str | None = None
    amount: float | None = None
    notes: str | None = None
    recurrence: str = "none"
    recur_day: int | None = None


class TaskCompleteRequest(BaseModel):
    occurrence_date: str | None = None


class ExpenseRequest(BaseModel):
    amount: float
    category: str = "misc"
    vendor: str | None = None
    notes: str | None = None
    spent_on: str | None = None


class MetaExtendRequest(BaseModel):
    short_token: str | None = None


def _parse_metric_date(value: str | None) -> date:
    if not value:
        return date.today() - timedelta(days=1)
    return datetime.strptime(value, "%Y-%m-%d").date()


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    settings = get_settings()
    integrations = integration_overview()
    selected_date = date.today() - timedelta(days=1)
    selected_metrics = enrich_metrics_rows(
        get_metrics_by_date(selected_date.isoformat())
    )
    if not selected_metrics:
        selected_metrics = enrich_metrics_rows(get_recent_metrics(7))
    today = date.today()
    task_calendar = calendar_month(today.year, today.month)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_name": settings.app_name,
            "demo_mode": settings.demo_mode,
            "metrics": selected_metrics,
            "selected_metric_date": selected_date.isoformat(),
            "tasks": list_tasks("open"),
            "task_calendar": task_calendar,
            "expenses": monthly_expense_summary(),
            "chat": recent_chat(12),
            "llm_ready": settings.llm_configured,
            "email_ready": settings.email_configured,
            "google_ready": settings.google_ads_configured,
            "meta_ready": settings.meta_configured,
            "integrations": integrations,
            "meta_status": integrations["meta"],
            "meta_app_ready": settings.meta_app_credentials_ready,
        },
    )


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    return {
        "ok": True,
        "demo_mode": settings.demo_mode,
        "llm": settings.llm_configured,
        "email": settings.email_configured,
        "google_ads": settings.google_ads_configured,
        "meta": settings.meta_configured,
    }


@app.get("/api/integrations/status")
def api_integrations_status() -> dict:
    return integration_overview()


@app.post("/api/integrations/meta/extend")
def api_meta_extend(payload: MetaExtendRequest | None = None) -> dict:
    short = payload.short_token if payload else None
    return extend_meta_token(short)


@app.post("/api/chat")
def api_chat(payload: ChatRequest) -> dict:
    return ask(payload.question, refresh_metrics=payload.refresh_metrics)


@app.post("/api/report/run")
def api_run_report(send: bool = False) -> dict:
    return run_daily_report(send=send)


@app.get("/api/metrics")
def api_metrics(
    metric_date: str | None = Query(default=None, alias="date"),
    days: int = Query(default=14, ge=1, le=90),
) -> dict:
    if metric_date:
        day = _parse_metric_date(metric_date)
        items = enrich_metrics_rows(get_metrics_by_date(day.isoformat()))
        return {
            "metric_date": day.isoformat(),
            "items": items,
            "source": "cache",
        }
    return {"items": enrich_metrics_rows(get_recent_metrics(days))}


@app.post("/api/metrics/refresh")
def api_metrics_refresh(
    metric_date: str | None = Query(default=None, alias="date"),
) -> dict:
    day = _parse_metric_date(metric_date)
    items = collect_all_metrics(day)
    return {
        "metric_date": day.isoformat(),
        "items": [m.to_dict() for m in items],
        "source": "live",
    }


@app.get("/api/tasks")
def api_tasks() -> dict:
    return {"items": list_tasks("open")}


@app.get("/api/tasks/calendar")
def api_tasks_calendar(
    year: int | None = None,
    month: int | None = None,
) -> dict:
    return calendar_month(year, month)


@app.post("/api/tasks")
def api_create_task(payload: TaskRequest) -> dict:
    return create_task(
        title=payload.title,
        category=payload.category,
        due_date=payload.due_date,
        amount=payload.amount,
        notes=payload.notes,
        recurrence=payload.recurrence,
        recur_day=payload.recur_day,
    )


@app.post("/api/tasks/{task_id}/done")
def api_complete_task(task_id: int, payload: TaskCompleteRequest | None = None) -> dict:
    occurrence = payload.occurrence_date if payload else None
    task = complete_task(task_id, occurrence_date=occurrence)
    return {"item": task}


@app.get("/api/expenses")
def api_expenses(year_month: str | None = None) -> dict:
    return {
        "summary": monthly_expense_summary(year_month),
        "items": list_expenses(year_month),
    }


@app.post("/api/expenses")
def api_add_expense(payload: ExpenseRequest) -> dict:
    return add_expense(
        amount=payload.amount,
        category=payload.category,
        vendor=payload.vendor,
        notes=payload.notes,
        spent_on=payload.spent_on,
    )


@app.post("/ui/tasks")
def ui_create_task(
    title: str = Form(...),
    category: str = Form("general"),
    due_date: str | None = Form(None),
    recurrence: str = Form("none"),
    recur_day: str | None = Form(None),
) -> RedirectResponse:
    day_val = None
    if recur_day and str(recur_day).strip():
        day_val = int(recur_day)
    create_task(
        title=title,
        category=category,
        due_date=due_date or None,
        recurrence=recurrence or "none",
        recur_day=day_val,
    )
    return RedirectResponse("/", status_code=303)


@app.post("/ui/expenses")
def ui_add_expense(
    amount: float = Form(...),
    category: str = Form("misc"),
    vendor: str | None = Form(None),
    notes: str | None = Form(None),
) -> RedirectResponse:
    add_expense(amount=amount, category=category, vendor=vendor, notes=notes)
    return RedirectResponse("/", status_code=303)
