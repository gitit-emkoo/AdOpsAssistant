"""광고 연동 상태 / Meta 장기 토큰 관리."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import ROOT_DIR, Settings, get_settings
from app.db import get_conn, now_iso


def ensure_integration_table() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS integration_status (
                provider TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                expires_at TEXT,
                token_type TEXT,
                message TEXT,
                checked_at TEXT NOT NULL
            )
            """
        )


def _save_status(
    provider: str,
    status: str,
    *,
    expires_at: str | None = None,
    token_type: str | None = None,
    message: str | None = None,
) -> None:
    ensure_integration_table()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO integration_status (
                provider, status, expires_at, token_type, message, checked_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                status=excluded.status,
                expires_at=excluded.expires_at,
                token_type=excluded.token_type,
                message=excluded.message,
                checked_at=excluded.checked_at
            """,
            (provider, status, expires_at, token_type, message, now_iso()),
        )


def _update_env_value(key: str, value: str) -> None:
    env_path = ROOT_DIR / ".env"
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    line = f"{key}={value}"
    if pattern.search(text):
        text = pattern.sub(line, text)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    env_path.write_text(text, encoding="utf-8")
    get_settings.cache_clear()


def debug_meta_token(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    ensure_integration_table()

    if not settings.meta_access_token:
        result = {
            "provider": "meta",
            "configured": False,
            "status": "missing",
            "level": "danger",
            "title": "Meta 토큰 없음",
            "message": "META_ACCESS_TOKEN 이 비어 있습니다.",
            "expires_at": None,
            "days_left": None,
            "token_type": None,
            "can_extend": bool(settings.meta_app_id and settings.meta_app_secret),
        }
        _save_status("meta", "missing", message=result["message"])
        return result

    if not settings.meta_app_id or not settings.meta_app_secret:
        # App ID/Secret 없어도 토큰 자체 유효성은 Graph 호출로 확인
        return _probe_meta_token_without_app(settings)

    app_token = f"{settings.meta_app_id}|{settings.meta_app_secret}"
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"https://graph.facebook.com/{settings.meta_api_version}/debug_token",
                params={
                    "input_token": settings.meta_access_token,
                    "access_token": app_token,
                },
            )
            data = resp.json()
            if resp.status_code >= 400:
                raise RuntimeError(data.get("error", {}).get("message", resp.text[:200]))
            info = data.get("data") or {}
    except Exception as exc:  # noqa: BLE001
        result = {
            "provider": "meta",
            "configured": True,
            "status": "error",
            "level": "danger",
            "title": "Meta 토큰 확인 실패",
            "message": str(exc)[:300],
            "expires_at": None,
            "days_left": None,
            "token_type": None,
            "can_extend": True,
        }
        _save_status("meta", "error", message=result["message"])
        return result

    if not info.get("is_valid", False):
        result = {
            "provider": "meta",
            "configured": True,
            "status": "expired",
            "level": "danger",
            "title": "Meta 토큰 만료/무효",
            "message": "토큰이 만료되었거나 권한이 없습니다. 새 토큰을 발급하세요.",
            "expires_at": None,
            "days_left": 0,
            "token_type": "invalid",
            "can_extend": True,
        }
        _save_status("meta", "expired", token_type="invalid", message=result["message"])
        return result

    expires_at = None
    days_left = None
    data_access_expires = info.get("data_access_expires_at")
    expires_epoch = info.get("expires_at") or 0
    if expires_epoch and int(expires_epoch) > 0:
        expires_at = datetime.fromtimestamp(int(expires_epoch), tz=timezone.utc).isoformat()
        days_left = _days_left(expires_at)
        token_type = "short" if days_left is not None and days_left <= 2 else "long"
    else:
        # expires_at=0 이면 만료 없음(시스템 사용자 등)으로 보는 경우가 많음
        token_type = "non_expiring"
        days_left = None
        expires_at = None

    status, level, title, message = _classify(days_left, has_token=True, token_type=token_type)
    if data_access_expires:
        da = datetime.fromtimestamp(int(data_access_expires), tz=timezone.utc)
        message = f"{message} 데이터 액세스 만료: {da.date().isoformat()}"

    result = {
        "provider": "meta",
        "configured": True,
        "status": status,
        "level": level,
        "title": title,
        "message": message,
        "expires_at": expires_at,
        "days_left": days_left,
        "token_type": token_type,
        "can_extend": True,
        "scopes": info.get("scopes") or [],
    }
    _save_status(
        "meta",
        status,
        expires_at=expires_at,
        token_type=token_type,
        message=message,
    )
    if expires_at:
        _update_env_value("META_TOKEN_EXPIRES_AT", expires_at)
    return result


def extend_meta_token(short_token: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    if not settings.meta_app_id or not settings.meta_app_secret:
        return {
            "ok": False,
            "error": "META_APP_ID / META_APP_SECRET 을 .env에 먼저 넣으세요. Meta 앱 설정 > 기본에서 확인합니다.",
        }

    token = (short_token or settings.meta_access_token or "").strip()
    if not token:
        return {"ok": False, "error": "교환할 Meta 토큰이 없습니다."}

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"https://graph.facebook.com/{settings.meta_api_version}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.meta_app_id,
                    "client_secret": settings.meta_app_secret,
                    "fb_exchange_token": token,
                },
            )
            data = resp.json()
            if resp.status_code >= 400 or "access_token" not in data:
                err = str(data.get("error", {}).get("message") or data)[:400]
                lower = err.lower()
                if "expired" in lower or "session has expired" in lower:
                    return {
                        "ok": False,
                        "error": (
                            "지금 .env에 있는 토큰이 이미 만료돼서 교환할 수 없습니다. "
                            "Graph API Explorer에서 새 짧은 토큰을 받은 뒤, "
                            "입력칸에 붙여넣고 다시 '장기 토큰으로 교환'을 눌러주세요."
                        ),
                        "raw_error": err,
                    }
                return {"ok": False, "error": err}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:400]}

    long_token = data["access_token"]
    expires_in = int(data.get("expires_in") or 0)
    expires_at = None
    if expires_in > 0:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()

    _update_env_value("META_ACCESS_TOKEN", long_token)
    if expires_at:
        _update_env_value("META_TOKEN_EXPIRES_AT", expires_at)

    status = debug_meta_token()
    return {
        "ok": True,
        "expires_in_days": round(expires_in / 86400, 1) if expires_in else None,
        "expires_at": expires_at,
        "status": status,
        "message": "장기 토큰으로 교환해 .env에 저장했습니다. (보통 약 60일)",
    }


def google_status(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    if not settings.google_ads_configured:
        return {
            "provider": "google_ads",
            "configured": False,
            "status": "missing",
            "level": "warn",
            "title": "Google Ads 미연동",
            "message": "OAuth / Customer ID 설정을 확인하세요.",
        }
    return {
        "provider": "google_ads",
        "configured": True,
        "status": "ok",
        "level": "ok",
        "title": "Google Ads 연결됨",
        "message": "Refresh Token 기반이라 보통 장기 유지됩니다. 권한 오류 시 OAuth를 다시 실행하세요.",
    }


def integration_overview() -> dict[str, Any]:
    meta = debug_meta_token()
    google = google_status()
    alerts = []
    for item in (meta, google):
        # 상단 알림은 실제 장애/만료 임박만 표시
        if item.get("status") in {"missing", "expired", "error", "expiring_soon"}:
            alerts.append(item)
        elif item.get("level") == "danger":
            alerts.append(item)
    return {
        "meta": meta,
        "google_ads": google,
        "alerts": alerts,
        "guide": token_guide(),
    }


def token_guide() -> dict[str, Any]:
    return {
        "meta_short": [
            "Meta for Developers → Graph API Explorer 접속",
            "앱 선택(광고운영 보조 / AdOps Assistant)",
            "권한: ads_read, ads_management 추가",
            "액세스 토큰 생성 → 복사",
            ".env의 META_ACCESS_TOKEN에 붙여넣기 또는 아래 교환 버튼 사용",
        ],
        "meta_long": [
            "Meta 앱 설정 → 기본에서 앱 ID / 앱 시크릿 복사",
            ".env에 META_APP_ID, META_APP_SECRET 저장",
            "짧은 토큰이 META_ACCESS_TOKEN에 있는 상태에서 '장기 토큰으로 교환' 클릭",
            "성공 시 약 60일짜리 토큰으로 .env가 자동 갱신됩니다",
            "더 오래 쓰려면 나중에 Business Manager 시스템 사용자 토큰으로 업그레이드",
        ],
        "google": [
            "Google 쪽 오류는 Meta 장기토큰과 무관합니다. Refresh Token을 다시 발급하세요.",
            "로컬에서 scripts/google_ads_oauth.py 를 실행해 Google 로그인·동의를 완료하세요.",
            "발급된 GOOGLE_ADS_REFRESH_TOKEN 을 로컬 .env와 Oracle 서버 .env에 넣으세요.",
            "웹에서 'API 새로고침' 또는 진행 중 광고 '새로고침'을 누르세요.",
            "참고: 비밀번호를 바꾸거나 동의를 취소하면 refresh token이 즉시 무효가 됩니다.",
        ],
        "links": {
            "graph_explorer": "https://developers.facebook.com/tools/explorer/",
            "meta_apps": "https://developers.facebook.com/apps/",
        },
    }


def _probe_meta_token_without_app(settings: Settings) -> dict[str, Any]:
    """App 자격증명 없이 토큰이 실제로 살아 있는지 확인합니다."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM integration_status WHERE provider='meta'"
        ).fetchone()
    expires_at = (row["expires_at"] if row else None) or settings.meta_token_expires_at or None
    days_left = _days_left(expires_at)
    accounts = list(settings.meta_ad_account_ids)
    account = accounts[0] if accounts else ""

    try:
        with httpx.Client(timeout=20) as client:
            target = account or "me"
            fields = "id,name" if account else "id,name"
            resp = client.get(
                f"https://graph.facebook.com/{settings.meta_api_version}/{target}",
                params={
                    "fields": fields,
                    "access_token": settings.meta_access_token,
                },
            )
            data = resp.json()
            err = data.get("error") or {}
            message = str(err.get("message") or "")
            if resp.status_code >= 400 or err:
                expired_like = any(
                    key in message.lower()
                    for key in ("expired", "session has expired", "validating access token")
                ) or err.get("code") in {190, 102}
                if expired_like:
                    result = {
                        "provider": "meta",
                        "configured": True,
                        "status": "expired",
                        "level": "danger",
                        "title": "Meta 토큰 만료",
                        "message": "토큰이 만료됐습니다. Graph API Explorer에서 새 토큰을 받아 장기 토큰으로 교환하세요.",
                        "expires_at": expires_at,
                        "days_left": 0,
                        "token_type": "invalid",
                        "can_extend": False,
                        "needs_app_credentials": True,
                    }
                    _save_status(
                        "meta",
                        "expired",
                        expires_at=expires_at,
                        token_type="invalid",
                        message=result["message"],
                    )
                    return result
                result = {
                    "provider": "meta",
                    "configured": True,
                    "status": "error",
                    "level": "danger",
                    "title": "Meta 토큰 확인 실패",
                    "message": message[:300] or f"HTTP {resp.status_code}",
                    "expires_at": expires_at,
                    "days_left": days_left,
                    "token_type": (row["token_type"] if row else None) or "unknown",
                    "can_extend": False,
                    "needs_app_credentials": True,
                }
                _save_status("meta", "error", expires_at=expires_at, message=result["message"])
                return result
    except Exception as exc:  # noqa: BLE001
        result = {
            "provider": "meta",
            "configured": True,
            "status": "error",
            "level": "danger",
            "title": "Meta 토큰 확인 실패",
            "message": str(exc)[:300],
            "expires_at": expires_at,
            "days_left": days_left,
            "token_type": (row["token_type"] if row else None) or "unknown",
            "can_extend": False,
            "needs_app_credentials": True,
        }
        _save_status("meta", "error", expires_at=expires_at, message=result["message"])
        return result

    # 토큰은 유효. 만료일 정확 확인은 App ID/Secret 필요 → 노란불
    if days_left is not None and days_left <= 0:
        status, level, title, message = _classify(days_left, has_token=True)
    elif days_left is not None:
        status, level, title, message = _classify(days_left, has_token=True)
    else:
        status, level, title, message = (
            "ok",
            "warn",
            "Meta 토큰 유효(만료일 미확인)",
            "토큰은 살아 있습니다. 정확한 만료일/장기교환은 App ID·Secret 설정 후 가능합니다.",
        )
    result = {
        "provider": "meta",
        "configured": True,
        "status": status,
        "level": level,
        "title": title,
        "message": message,
        "expires_at": expires_at,
        "days_left": days_left,
        "token_type": (row["token_type"] if row else None) or "unknown",
        "can_extend": False,
        "needs_app_credentials": True,
    }
    _save_status(
        "meta",
        status,
        expires_at=expires_at,
        token_type=result["token_type"],
        message=message,
    )
    return result


def _days_left(expires_at: str | None) -> int | None:
    if not expires_at:
        return None
    try:
        dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = (dt - datetime.now(timezone.utc)).total_seconds()
        if secs <= 0:
            return 0
        # 하루 미만 남아도 아직 유효하면 최소 1일로 표시
        return max(1, int((secs + 86399) // 86400))
    except ValueError:
        return None


def _classify(
    days_left: int | None,
    *,
    has_token: bool,
    token_type: str | None = None,
) -> tuple[str, str, str, str]:
    if not has_token:
        return "missing", "danger", "Meta 토큰 없음", "토큰을 발급해 주세요."
    if token_type == "non_expiring":
        return "ok", "ok", "Meta 토큰 정상", "만료 기한이 없는 토큰으로 보입니다."
    if days_left is None:
        return "unknown", "warn", "Meta 토큰 만료일 미확인", "App ID/Secret을 넣으면 만료일을 정확히 확인할 수 있습니다."
    if days_left <= 0:
        return "expired", "danger", "Meta 토큰 만료", "새 토큰을 발급하거나 장기 토큰으로 교환하세요."
    if token_type == "short" or days_left <= 7:
        label = "오늘 중" if days_left <= 1 else f"약 {days_left}일 후"
        return (
            "expiring_soon",
            "warn",
            f"Meta 짧은 토큰 {label} 만료" if token_type == "short" else f"Meta 토큰 {label} 만료",
            "아직 유효합니다. 지금 장기 토큰으로 교환하세요.",
        )
    return (
        "ok",
        "ok",
        f"Meta 토큰 정상 (약 {days_left}일 남음)",
        "장기 토큰이 유효합니다.",
    )
