"""Minimal email/password auth with session cookies."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from app.db import get_conn, now_iso, row_to_dict

SESSION_COOKIE = "adops_session"
SESSION_DAYS = 30
PBKDF2_ITERATIONS = 120_000


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt, digest = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iters,
    ).hex()
    return hmac.compare_digest(check, digest)


def create_user(email: str, password: str) -> dict[str, Any]:
    email_norm = email.strip().lower()
    if not email_norm or "@" not in email_norm:
        raise ValueError("이메일 형식이 올바르지 않습니다.")
    if len(password) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 합니다.")
    now = now_iso()
    password_hash = _hash_password(password)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email_norm,)
        ).fetchone()
        if existing:
            raise ValueError("이미 가입된 이메일입니다.")
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email_norm, password_hash, now),
        )
        user_id = int(cur.lastrowid)
    return {"id": user_id, "email": email_norm}


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    email_norm = email.strip().lower()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email_norm,)
        ).fetchone()
    user = row_to_dict(row)
    if not user:
        return None
    if not _verify_password(password, user["password_hash"]):
        return None
    return {"id": user["id"], "email": user["email"]}


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires = (now + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sessions (token, user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, expires, now.isoformat(timespec="seconds")),
        )
    return token


def destroy_session(token: str | None) -> None:
    if not token:
        return
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def get_user_by_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    now = datetime.utcnow().isoformat(timespec="seconds")
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email, s.expires_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        if not row:
            return None
        if str(row["expires_at"]) < now:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
    return {"id": int(row["id"]), "email": row["email"]}


def current_user(request: Request) -> dict[str, Any] | None:
    return get_user_by_session(request.cookies.get(SESSION_COOKIE))


def require_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if user:
        return user
    accept = request.headers.get("accept", "")
    if "text/html" in accept or request.url.path.startswith("/ui"):
        raise HTTPException(
            status_code=303,
            detail="login required",
            headers={"Location": "/login"},
        )
    raise HTTPException(status_code=401, detail="로그인이 필요합니다.")


def login_redirect_if_anonymous(request: Request) -> RedirectResponse | None:
    if current_user(request):
        return None
    return RedirectResponse("/login", status_code=303)


def set_session_cookie(response: RedirectResponse | Any, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_DAYS * 24 * 3600,
        path="/",
    )


def clear_session_cookie(response: RedirectResponse | Any) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
