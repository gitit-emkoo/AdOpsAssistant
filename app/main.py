from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.collectors import (
    collect_all_metrics,
    enrich_metrics_rows,
    get_metrics_between,
    get_metrics_by_date,
    get_recent_metrics,
)
from app.config import get_settings
from app.db import init_db
from app.services.active_ads import get_active_ads, get_campaign_adsets
from app.services.auth import (
    authenticate,
    clear_session_cookie,
    create_session,
    create_user,
    current_user,
    set_session_cookie,
)
from app.services.chat import ask, recent_chat
from app.services.connections import (
    connection_status_summary,
    delete_connection,
    get_connection,
    list_connections,
    save_oauth_state,
    consume_oauth_state,
    settings_for_user,
)
from app.services.integrations import (
    ensure_integration_table,
    extend_meta_token,
    integration_overview,
)
from app.services.oauth import (
    exchange_google_code,
    exchange_meta_code,
    google_authorize_url,
    meta_authorize_url,
    refresh_meta_available_accounts,
    save_google_connection,
    save_meta_connection,
)
from app.services.report import (
    build_monthly_report,
    list_monthly_report_records,
    previous_month,
    run_daily_report,
    run_monthly_report,
)
from app.services.tasks import (
    add_expense,
    calendar_month,
    complete_task,
    create_task,
    delete_task,
    ensure_recurring_defaults,
    get_task,
    list_expenses,
    list_tasks,
    monthly_expense_summary,
    seed_default_tasks_if_empty,
    update_task,
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="AdOps Assistant")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return templates.TemplateResponse(
            request,
            "404.html",
            {"app_name": get_settings().app_name},
            status_code=404,
        )
    if exc.status_code == 401 and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/login", status_code=303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    ensure_integration_table()
    seed_default_tasks_if_empty()
    ensure_recurring_defaults()
    # Ensure at least one demo snapshot exists for the UI.
    # Collection failures must not prevent the web app from starting.
    if not get_recent_metrics(1):
        try:
            collect_all_metrics()
        except Exception as exc:  # noqa: BLE001
            print(f"[startup] metrics collect skipped: {exc}")


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


def _require_user(request: Request) -> dict:
    user = current_user(request)
    if user:
        return user
    raise HTTPException(status_code=401, detail="로그인이 필요합니다.")


def _html_user_or_redirect(request: Request):
    user = current_user(request)
    if user:
        return user
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str | None = None) -> HTMLResponse:
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "auth.html",
        {
            "app_name": settings.app_name,
            "title": "로그인",
            "mode": "login",
            "form_action": "/login",
            "submit_label": "로그인",
            "error": error,
            "email": "",
        },
    )


@app.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    user = authenticate(email, password)
    if not user:
        return templates.TemplateResponse(
            request,
            "auth.html",
            {
                "app_name": get_settings().app_name,
                "title": "로그인",
                "mode": "login",
                "form_action": "/login",
                "submit_label": "로그인",
                "error": "이메일 또는 비밀번호가 올바르지 않습니다.",
                "email": email,
            },
            status_code=400,
        )
    token = create_session(int(user["id"]))
    resp = RedirectResponse("/", status_code=303)
    set_session_cookie(resp, token)
    return resp


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "auth.html",
        {
            "app_name": settings.app_name,
            "title": "회원가입",
            "mode": "register",
            "form_action": "/register",
            "submit_label": "가입하기",
            "error": None,
            "email": "",
        },
    )


@app.post("/register")
def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    try:
        user = create_user(email, password)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "auth.html",
            {
                "app_name": get_settings().app_name,
                "title": "회원가입",
                "mode": "register",
                "form_action": "/register",
                "submit_label": "가입하기",
                "error": str(exc),
                "email": email,
            },
            status_code=400,
        )
    token = create_session(int(user["id"]))
    resp = RedirectResponse("/connections", status_code=303)
    set_session_cookie(resp, token)
    return resp


@app.post("/logout")
def logout(request: Request):
    from app.services.auth import SESSION_COOKIE, destroy_session

    destroy_session(request.cookies.get(SESSION_COOKIE))
    resp = RedirectResponse("/login", status_code=303)
    clear_session_cookie(resp)
    return resp


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    settings = settings_for_user(int(user["id"]))
    integrations = integration_overview()
    selected_date = date.today() - timedelta(days=1)
    metrics_end = selected_date
    metrics_start = metrics_end - timedelta(days=2)
    selected_metrics = enrich_metrics_rows(
        get_metrics_between(metrics_start.isoformat(), metrics_end.isoformat())
    )
    if not selected_metrics:
        selected_metrics = enrich_metrics_rows(get_recent_metrics(3))
    metrics_kpi = {
        "spend": sum(float(m.get("spend") or 0) for m in selected_metrics),
        "clicks": sum(int(m.get("clicks") or 0) for m in selected_metrics),
        "installs": sum(float(m.get("installs") or 0) for m in selected_metrics),
    }
    installs = metrics_kpi["installs"]
    metrics_kpi["cpi"] = (
        metrics_kpi["spend"] / installs if installs else None
    )
    today = date.today()
    task_calendar = calendar_month(today.year, today.month)
    active_ads = get_active_ads(user_id=int(user["id"]))
    conn_status = connection_status_summary(int(user["id"]))
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_name": get_settings().app_name,
            "user": user,
            "demo_mode": settings.demo_mode,
            "metrics": selected_metrics,
            "metrics_kpi": metrics_kpi,
            "selected_metric_date": selected_date.isoformat(),
            "metrics_start": metrics_start.isoformat(),
            "metrics_end": metrics_end.isoformat(),
            "active_ads": active_ads,
            "tasks": list_tasks("open"),
            "task_calendar": task_calendar,
            "expenses": monthly_expense_summary(),
            "chat": recent_chat(12),
            "llm_ready": get_settings().llm_configured,
            "email_ready": get_settings().email_configured,
            "google_ready": settings.google_ads_configured,
            "meta_ready": settings.meta_configured,
            "integrations": integrations,
            "meta_status": integrations["meta"],
            "meta_app_ready": get_settings().meta_app_credentials_ready,
            "connections": conn_status,
        },
    )


@app.get("/api/active-ads")
def api_active_ads(
    request: Request,
    refresh: bool = False,
    user: dict = Depends(_require_user),
) -> dict:
    return get_active_ads(force_refresh=refresh, user_id=int(user["id"]))


@app.get("/api/active-ads/adsets")
def api_active_adsets(
    request: Request,
    platform: str = Query(...),
    campaign_id: str = Query(...),
    account_id: str | None = Query(default=None),
    metric_date: str | None = Query(default=None, alias="date"),
    user: dict = Depends(_require_user),
) -> dict:
    return get_campaign_adsets(
        platform=platform,
        campaign_id=campaign_id,
        account_id=account_id,
        metric_date=metric_date,
        user_id=int(user["id"]),
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
def api_integrations_status(user: dict = Depends(_require_user)) -> dict:
    overview = integration_overview()
    overview["connections"] = connection_status_summary(int(user["id"]))
    return overview


@app.post("/api/integrations/meta/extend")
def api_meta_extend(
    payload: MetaExtendRequest | None = None,
    user: dict = Depends(_require_user),
) -> dict:
    short = payload.short_token if payload else None
    return extend_meta_token(short)


@app.post("/api/chat")
def api_chat(
    payload: ChatRequest,
    user: dict = Depends(_require_user),
) -> dict:
    return ask(
        payload.question,
        refresh_metrics=payload.refresh_metrics,
        user_id=int(user["id"]),
    )


@app.post("/api/report/run")
def api_run_report(send: bool = False) -> dict:
    return run_daily_report(send=send)


@app.get("/reports", response_class=HTMLResponse)
def reports_page(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    flash: str | None = None,
    level: str | None = None,
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if year is None or month is None:
        year, month = previous_month()
    month = max(1, min(12, int(month)))
    year = int(year)
    report = build_monthly_report(
        year, month, ensure_data=False, user_id=int(user["id"])
    )
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    return templates.TemplateResponse(
        request,
        "reports.html",
        {
            "app_name": get_settings().app_name,
            "user": user,
            "report": report,
            "history": list_monthly_report_records(12),
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
            "flash": flash,
            "flash_level": level or "ok",
        },
    )


@app.post("/reports/refresh")
def reports_refresh(
    request: Request,
    year: int = Form(...),
    month: int = Form(...),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    report = build_monthly_report(
        int(year),
        int(month),
        ensure_data=True,
        force_insights=False,
        user_id=int(user["id"]),
    )
    err_n = len(report.get("collect_errors") or [])
    msg = f"{year}-{month:02d} 데이터 채움"
    if err_n:
        msg += f" (경고 {err_n}건)"
    return RedirectResponse(
        f"/reports?year={year}&month={month}&flash={quote(msg)}&level=ok",
        status_code=303,
    )


@app.post("/reports/insights")
def reports_insights(
    request: Request,
    year: int = Form(...),
    month: int = Form(...),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    build_monthly_report(
        int(year),
        int(month),
        ensure_data=False,
        force_insights=True,
        user_id=int(user["id"]),
    )
    return RedirectResponse(
        f"/reports?year={year}&month={month}&flash={quote('AI 요약을 갱신했습니다')}&level=ok",
        status_code=303,
    )


@app.post("/reports/email")
def reports_email(
    request: Request,
    year: int = Form(...),
    month: int = Form(...),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    result = run_monthly_report(
        year=int(year),
        month=int(month),
        send=True,
        ensure_data=True,
        user_id=int(user["id"]),
    )
    email = result.get("email") or {}
    if email.get("ok"):
        msg = "월간 리포트 메일을 보냈습니다"
        level = "ok"
    else:
        msg = f"메일 실패: {email.get('reason') or email.get('error') or 'unknown'}"[:120]
        level = "danger"
    return RedirectResponse(
        f"/reports?year={year}&month={month}&flash={quote(msg)}&level={level}",
        status_code=303,
    )


@app.post("/api/report/monthly")
def api_run_monthly_report(
    year: int | None = None,
    month: int | None = None,
    send: bool = False,
    user: dict = Depends(_require_user),
) -> dict:
    return run_monthly_report(
        year=year,
        month=month,
        send=send,
        ensure_data=True,
        user_id=int(user["id"]),
    )


@app.get("/api/metrics")
def api_metrics(
    metric_date: str | None = Query(default=None, alias="date"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    days: int = Query(default=3, ge=1, le=90),
    user: dict = Depends(_require_user),
) -> dict:
    if start and end:
        start_day = _parse_metric_date(start)
        end_day = _parse_metric_date(end)
        if end_day < start_day:
            start_day, end_day = end_day, start_day
        items = enrich_metrics_rows(
            get_metrics_between(start_day.isoformat(), end_day.isoformat())
        )
        return {
            "mode": "range",
            "start": start_day.isoformat(),
            "end": end_day.isoformat(),
            "metric_date": f"{start_day.isoformat()} ~ {end_day.isoformat()}",
            "items": items,
            "source": "cache",
        }
    if metric_date:
        day = _parse_metric_date(metric_date)
        items = enrich_metrics_rows(get_metrics_by_date(day.isoformat()))
        return {
            "mode": "day",
            "metric_date": day.isoformat(),
            "start": day.isoformat(),
            "end": day.isoformat(),
            "items": items,
            "source": "cache",
        }
    end_day = date.today() - timedelta(days=1)
    start_day = end_day - timedelta(days=days - 1)
    items = enrich_metrics_rows(
        get_metrics_between(start_day.isoformat(), end_day.isoformat())
    )
    return {
        "mode": "recent",
        "days": days,
        "start": start_day.isoformat(),
        "end": end_day.isoformat(),
        "metric_date": f"최근 {days}일 ({start_day.isoformat()} ~ {end_day.isoformat()})",
        "items": items,
        "source": "cache",
    }


@app.post("/api/metrics/refresh")
def api_metrics_refresh(
    metric_date: str | None = Query(default=None, alias="date"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    user: dict = Depends(_require_user),
) -> dict:
    uid = int(user["id"])
    if start and end:
        start_day = _parse_metric_date(start)
        end_day = _parse_metric_date(end)
        if end_day < start_day:
            start_day, end_day = end_day, start_day
        if (end_day - start_day).days > 30:
            end_day = start_day + timedelta(days=30)
        errors: list[str] = []
        cursor = start_day
        any_ok = False
        while cursor <= end_day:
            collected = collect_all_metrics(cursor, user_id=uid)
            errs = list(getattr(collected, "errors", []) or [])
            if errs:
                errors.extend([f"{cursor.isoformat()}: {e}" for e in errs])
            if collected:
                any_ok = True
            cursor += timedelta(days=1)
        cached = enrich_metrics_rows(
            get_metrics_between(start_day.isoformat(), end_day.isoformat())
        )
        return {
            "mode": "range",
            "start": start_day.isoformat(),
            "end": end_day.isoformat(),
            "metric_date": f"{start_day.isoformat()} ~ {end_day.isoformat()}",
            "items": cached,
            "source": "live" if any_ok else "cache",
            "errors": errors,
            "ok": not errors or bool(cached),
        }

    day = _parse_metric_date(metric_date)
    items = collect_all_metrics(day, user_id=uid)
    errors = list(getattr(items, "errors", []) or [])
    cached = enrich_metrics_rows(get_metrics_by_date(day.isoformat()))
    return {
        "mode": "day",
        "metric_date": day.isoformat(),
        "start": day.isoformat(),
        "end": day.isoformat(),
        "items": cached or [m.to_dict() for m in items],
        "source": "live" if items else "cache",
        "errors": errors,
        "ok": not errors or bool(items),
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


@app.get("/api/tasks/{task_id}")
def api_get_task(task_id: int) -> dict:
    task = get_task(task_id)
    if not task:
        return {"ok": False, "error": "할 일을 찾을 수 없습니다."}
    return {"ok": True, "item": task}


@app.put("/api/tasks/{task_id}")
def api_update_task(task_id: int, payload: TaskRequest) -> dict:
    try:
        task = update_task(
            task_id,
            title=payload.title,
            category=payload.category,
            due_date=payload.due_date,
            amount=payload.amount,
            notes=payload.notes,
            recurrence=payload.recurrence,
            recur_day=payload.recur_day,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not task:
        return {"ok": False, "error": "할 일을 찾을 수 없습니다."}
    return {"ok": True, "item": task}


@app.delete("/api/tasks/{task_id}")
def api_delete_task(task_id: int) -> dict:
    ok = delete_task(task_id)
    return {"ok": ok}


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
    request: Request,
    title: str = Form(...),
    category: str = Form("general"),
    due_date: str | None = Form(None),
    recurrence: str = Form("none"),
    recur_day: str | None = Form(None),
):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
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
    request: Request,
    amount: float = Form(...),
    category: str = Form("misc"),
    vendor: str | None = Form(None),
    notes: str | None = Form(None),
):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    add_expense(amount=amount, category=category, vendor=vendor, notes=notes)
    return RedirectResponse("/", status_code=303)


@app.get("/connections", response_class=HTMLResponse)
def connections_page(request: Request, flash: str | None = None, level: str | None = None):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    uid = int(user["id"])
    try:
        refresh_meta_available_accounts(uid)
    except Exception:  # noqa: BLE001
        pass
    status = connection_status_summary(uid)
    return templates.TemplateResponse(
        request,
        "connections.html",
        {
            "app_name": get_settings().app_name,
            "user": user,
            "status": status,
            "flash": flash,
            "flash_level": level or "ok",
        },
    )


@app.post("/connections/meta/disconnect")
async def disconnect_meta(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    cid = form.get("connection_id")
    connection_id = int(cid) if cid else None
    delete_connection(int(user["id"]), "meta", connection_id=connection_id)
    return RedirectResponse(
        "/connections?flash=Meta%20로그인을%20해제했습니다.&level=ok",
        status_code=303,
    )


@app.post("/connections/google/disconnect")
async def disconnect_google(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    cid = form.get("connection_id")
    connection_id = int(cid) if cid else None
    delete_connection(int(user["id"]), "google_ads", connection_id=connection_id)
    return RedirectResponse(
        "/connections?flash=Google%20로그인을%20해제했습니다.&level=ok",
        status_code=303,
    )


@app.get("/oauth/meta/start")
def oauth_meta_start(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    settings = get_settings()
    if not settings.meta_app_credentials_ready:
        return RedirectResponse(
            "/connections?flash=META_APP_ID/SECRET%20필요&level=danger",
            status_code=303,
        )
    state = save_oauth_state(int(user["id"]), "meta", {"mode": "add"})
    try:
        url = meta_authorize_url(state, settings)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            f"/connections?flash={quote(str(exc)[:120])}&level=danger",
            status_code=303,
        )
    return RedirectResponse(url, status_code=302)


@app.get("/oauth/meta/callback")
def oauth_meta_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        return RedirectResponse(
            "/connections?flash=Meta%20동의%20취소&level=warn",
            status_code=303,
        )
    if not code or not state:
        return RedirectResponse(
            "/connections?flash=Meta%20콜백%20파라미터%20없음&level=danger",
            status_code=303,
        )
    consumed = consume_oauth_state(state, "meta")
    if not consumed:
        return RedirectResponse(
            "/connections?flash=OAuth%20state%20만료&level=danger",
            status_code=303,
        )
    user_id, _payload = consumed
    try:
        payload = exchange_meta_code(code)
        conn = save_meta_connection(user_id, payload)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            f"/connections?flash={quote('Meta 연동 실패: ' + str(exc)[:100])}&level=danger",
            status_code=303,
        )
    if (conn or {}).get("status") == "pending_select":
        return RedirectResponse(
            "/connections?flash="
            + quote("Meta 로그인 추가됨. 광고계정을 선택하세요.")
            + "&level=ok",
            status_code=303,
        )
    return RedirectResponse(
        "/connections?flash=" + quote("Meta 연결 완료") + "&level=ok",
        status_code=303,
    )


@app.post("/oauth/meta/select")
async def oauth_meta_select(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    selected = [str(v) for v in form.getlist("account_ids") if str(v).strip()]
    cid_raw = form.get("connection_id")
    connection_id = int(cid_raw) if cid_raw else None
    conn = get_connection(int(user["id"]), "meta", connection_id=connection_id)
    if not conn or not conn.get("access_token"):
        return RedirectResponse(
            "/connections?flash=" + quote("먼저 Meta 연결을 하세요") + "&level=danger",
            status_code=303,
        )
    try:
        extra = conn.get("meta") or {}
        save_meta_connection(
            int(user["id"]),
            {
                "access_token": conn.get("access_token"),
                "expires_at": conn.get("expires_at"),
                "available_accounts": extra.get("available_accounts") or [],
                "connection_key": conn.get("connection_key"),
                "label": conn.get("label"),
            },
            selected_account_ids=selected,
            status="connected",
            connection_key=str(conn.get("connection_key") or "default"),
            label=str(conn.get("label") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            f"/connections?flash={quote(str(exc)[:120])}&level=danger",
            status_code=303,
        )
    return RedirectResponse(
        "/connections?flash=" + quote("Meta 광고계정 선택 완료") + "&level=ok",
        status_code=303,
    )


@app.get("/oauth/google/start")
def oauth_google_start(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    settings = get_settings()
    if not (settings.google_ads_client_id and settings.google_ads_client_secret):
        return RedirectResponse(
            "/connections?flash=GOOGLE_ADS_CLIENT_ID/SECRET%20필요&level=danger",
            status_code=303,
        )
    state = save_oauth_state(int(user["id"]), "google_ads", {"mode": "add"})
    try:
        url = google_authorize_url(state, settings)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            f"/connections?flash={quote(str(exc)[:120])}&level=danger",
            status_code=303,
        )
    return RedirectResponse(url, status_code=302)


@app.get("/oauth/google/callback")
def oauth_google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        return RedirectResponse(
            "/connections?flash=Google%20동의%20취소&level=warn",
            status_code=303,
        )
    if not code or not state:
        return RedirectResponse(
            "/connections?flash=Google%20콜백%20파라미터%20없음&level=danger",
            status_code=303,
        )
    consumed = consume_oauth_state(state, "google_ads")
    if not consumed:
        return RedirectResponse(
            "/connections?flash=OAuth%20state%20만료&level=danger",
            status_code=303,
        )
    user_id, _payload = consumed
    try:
        payload = exchange_google_code(code)
        save_google_connection(user_id, payload)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            f"/connections?flash={quote('Google 연동 실패: ' + str(exc)[:100])}&level=danger",
            status_code=303,
        )
    return RedirectResponse(
        "/connections?flash="
        + quote("Google 로그인 추가됨. Ads 고객을 선택하세요.")
        + "&level=ok",
        status_code=303,
    )


@app.post("/oauth/google/select")
async def oauth_google_select(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    selected = [str(v) for v in form.getlist("customer_ids") if str(v).strip()]
    if not selected and form.get("customer_id"):
        selected = [str(form.get("customer_id"))]
    login_customer_id = str(form.get("login_customer_id") or "").strip()
    cid_raw = form.get("connection_id")
    connection_id = int(cid_raw) if cid_raw else None
    conn = get_connection(int(user["id"]), "google_ads", connection_id=connection_id)
    if not conn or not conn.get("refresh_token"):
        return RedirectResponse(
            "/connections?flash=" + quote("먼저 Google 연결을 하세요") + "&level=danger",
            status_code=303,
        )
    try:
        extra = conn.get("meta") or {}
        available = extra.get("available_customers") or list(
            conn.get("account_ids_list") or []
        )
        save_google_connection(
            int(user["id"]),
            {
                "refresh_token": conn["refresh_token"],
                "access_token": conn.get("access_token"),
                "available_customers": available,
                "connection_key": conn.get("connection_key"),
                "label": conn.get("label"),
            },
            selected_customer_ids=selected,
            login_customer_id=login_customer_id,
            status="connected",
            connection_key=str(conn.get("connection_key") or "default"),
            label=str(conn.get("label") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            f"/connections?flash={quote(str(exc)[:120])}&level=danger",
            status_code=303,
        )
    return RedirectResponse(
        "/connections?flash=" + quote("Google Ads 계정 선택 완료") + "&level=ok",
        status_code=303,
    )
