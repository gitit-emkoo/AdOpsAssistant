"""Per-user ad platform connections (OAuth tokens). Supports multiple logins per platform."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from typing import Any

from app.config import Settings, get_settings
from app.db import get_conn, now_iso, row_to_dict


def _split_accounts(raw: str) -> list[str]:
    ids: list[str] = []
    for part in (raw or "").replace(";", ",").split(","):
        value = part.strip()
        if value:
            ids.append(value)
    return ids


def _parse_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _enrich(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    item["account_ids_list"] = _split_accounts(item.get("account_ids") or "")
    item["meta"] = _parse_json(item.get("meta_json"))
    item["has_access_token"] = bool(item.get("access_token"))
    item["has_refresh_token"] = bool(item.get("refresh_token"))
    return item


def list_connections(user_id: int, platform: str | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if platform:
            rows = conn.execute(
                """
                SELECT * FROM ad_connections
                WHERE user_id = ? AND platform = ?
                ORDER BY id ASC
                """,
                (user_id, platform),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM ad_connections
                WHERE user_id = ?
                ORDER BY platform, id ASC
                """,
                (user_id,),
            ).fetchall()
    return [_enrich(dict(r)) for r in rows if r]  # type: ignore[misc]


def get_connection(
    user_id: int,
    platform: str,
    *,
    connection_id: int | None = None,
    connection_key: str | None = None,
) -> dict[str, Any] | None:
    with get_conn() as conn:
        if connection_id is not None:
            row = conn.execute(
                """
                SELECT * FROM ad_connections
                WHERE id = ? AND user_id = ? AND platform = ?
                """,
                (connection_id, user_id, platform),
            ).fetchone()
        elif connection_key is not None:
            row = conn.execute(
                """
                SELECT * FROM ad_connections
                WHERE user_id = ? AND platform = ? AND connection_key = ?
                """,
                (user_id, platform, connection_key),
            ).fetchone()
        else:
            # 하위 호환: 첫 번째(가장 오래된) 연결
            row = conn.execute(
                """
                SELECT * FROM ad_connections
                WHERE user_id = ? AND platform = ?
                ORDER BY id ASC LIMIT 1
                """,
                (user_id, platform),
            ).fetchone()
    return _enrich(row_to_dict(row))


def upsert_connection(
    user_id: int,
    platform: str,
    *,
    connection_key: str = "default",
    label: str = "",
    access_token: str | None = None,
    refresh_token: str | None = None,
    expires_at: str | None = None,
    account_ids: str | list[str] | None = None,
    login_customer_id: str | None = None,
    status: str = "connected",
    meta_json: dict | None = None,
) -> dict[str, Any]:
    connection_key = (connection_key or "default").strip() or "default"
    label = label or ""
    if isinstance(account_ids, list):
        account_ids = ",".join(account_ids)
    account_ids = account_ids or ""
    login_customer_id = login_customer_id or ""
    now = now_iso()
    payload = json.dumps(meta_json or {}, ensure_ascii=False)
    with get_conn() as conn:
        existing = conn.execute(
            """
            SELECT id FROM ad_connections
            WHERE user_id = ? AND platform = ? AND connection_key = ?
            """,
            (user_id, platform, connection_key),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE ad_connections SET
                    label = CASE WHEN ? != '' THEN ? ELSE label END,
                    access_token = COALESCE(?, access_token),
                    refresh_token = COALESCE(?, refresh_token),
                    expires_at = ?,
                    account_ids = ?,
                    login_customer_id = ?,
                    status = ?,
                    meta_json = ?,
                    updated_at = ?
                WHERE user_id = ? AND platform = ? AND connection_key = ?
                """,
                (
                    label,
                    label,
                    access_token,
                    refresh_token,
                    expires_at,
                    account_ids,
                    login_customer_id,
                    status,
                    payload,
                    now,
                    user_id,
                    platform,
                    connection_key,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO ad_connections (
                    user_id, platform, connection_key, label,
                    access_token, refresh_token, expires_at,
                    account_ids, login_customer_id, status, meta_json,
                    updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    platform,
                    connection_key,
                    label,
                    access_token,
                    refresh_token,
                    expires_at,
                    account_ids,
                    login_customer_id,
                    status,
                    payload,
                    now,
                    now,
                ),
            )
    return get_connection(user_id, platform, connection_key=connection_key) or {}


def delete_connection(
    user_id: int,
    platform: str,
    *,
    connection_id: int | None = None,
) -> bool:
    with get_conn() as conn:
        if connection_id is not None:
            cur = conn.execute(
                "DELETE FROM ad_connections WHERE id = ? AND user_id = ? AND platform = ?",
                (connection_id, user_id, platform),
            )
        else:
            cur = conn.execute(
                "DELETE FROM ad_connections WHERE user_id = ? AND platform = ?",
                (user_id, platform),
            )
        return cur.rowcount > 0


def save_oauth_state(
    user_id: int, platform: str, payload: dict[str, Any] | None = None
) -> str:
    state = secrets.token_urlsafe(24)
    expires = (datetime.utcnow() + timedelta(minutes=20)).isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO oauth_states (state, user_id, platform, payload, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                state,
                user_id,
                platform,
                json.dumps(payload or {}, ensure_ascii=False),
                expires,
                now_iso(),
            ),
        )
    return state


def consume_oauth_state(state: str, platform: str) -> tuple[int, dict[str, Any]] | None:
    now = datetime.utcnow().isoformat(timespec="seconds")
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT user_id, expires_at, payload FROM oauth_states
            WHERE state = ? AND platform = ?
            """,
            (state, platform),
        ).fetchone()
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        if not row:
            return None
        if str(row["expires_at"]) < now:
            return None
        return int(row["user_id"]), _parse_json(row["payload"] if "payload" in row.keys() else "{}")


def settings_from_connection(conn: dict[str, Any], base: Settings | None = None) -> Settings:
    """한 OAuth 연결 → Settings 오버레이."""
    settings = base or get_settings()
    updates: dict[str, Any] = {}
    platform = conn.get("platform")
    if platform == "meta" and conn.get("access_token"):
        updates["meta_access_token"] = conn["access_token"]
        if conn.get("account_ids"):
            updates["meta_ad_account_id"] = conn["account_ids"]
        if conn.get("expires_at"):
            updates["meta_token_expires_at"] = conn["expires_at"]
    if platform == "google_ads" and conn.get("refresh_token"):
        updates["google_ads_refresh_token"] = conn["refresh_token"]
        accounts = _split_accounts(conn.get("account_ids") or "")
        if accounts:
            updates["google_ads_customer_id"] = ",".join(accounts)
        if conn.get("login_customer_id"):
            updates["google_ads_login_customer_id"] = conn["login_customer_id"]
    if not updates:
        return settings
    return settings.model_copy(update=updates)


def settings_overlays_for_platform(user_id: int | None, platform: str) -> list[Settings]:
    """수집용: 연결된 모든 로그인 Settings. 없으면 .env 한 장."""
    base = get_settings()
    if not user_id:
        return [base]
    connected = [
        c
        for c in list_connections(user_id, platform)
        if c
        and c.get("status") == "connected"
        and (
            (platform == "meta" and c.get("access_token") and c.get("account_ids_list"))
            or (
                platform == "google_ads"
                and c.get("refresh_token")
                and c.get("account_ids_list")
            )
        )
    ]
    if not connected:
        return [base]
    return [settings_from_connection(c, base) for c in connected]


def settings_for_user(user_id: int | None) -> Settings:
    """대시보드 등 단일 Settings가 필요할 때 — 연결 계정 ID를 합치고 토큰은 첫 연결."""
    settings = get_settings()
    if not user_id:
        return settings
    updates: dict[str, Any] = {}
    meta_conns = [
        c
        for c in list_connections(user_id, "meta")
        if c and c.get("status") == "connected" and c.get("access_token")
    ]
    if meta_conns:
        updates["meta_access_token"] = meta_conns[0]["access_token"]
        all_accounts: list[str] = []
        for c in meta_conns:
            all_accounts.extend(c.get("account_ids_list") or [])
        if all_accounts:
            # de-dupe
            seen: set[str] = set()
            uniq = []
            for a in all_accounts:
                if a not in seen:
                    seen.add(a)
                    uniq.append(a)
            updates["meta_ad_account_id"] = ",".join(uniq)
        if meta_conns[0].get("expires_at"):
            updates["meta_token_expires_at"] = meta_conns[0]["expires_at"]

    google_conns = [
        c
        for c in list_connections(user_id, "google_ads")
        if c and c.get("status") == "connected" and c.get("refresh_token")
    ]
    if google_conns:
        updates["google_ads_refresh_token"] = google_conns[0]["refresh_token"]
        all_cust: list[str] = []
        for c in google_conns:
            all_cust.extend(c.get("account_ids_list") or [])
        if all_cust:
            seen_c: set[str] = set()
            uniq_c = []
            for a in all_cust:
                if a not in seen_c:
                    seen_c.add(a)
                    uniq_c.append(a)
            updates["google_ads_customer_id"] = ",".join(uniq_c)
        if google_conns[0].get("login_customer_id"):
            updates["google_ads_login_customer_id"] = google_conns[0]["login_customer_id"]
    if not updates:
        return settings
    return settings.model_copy(update=updates)


def _connection_card(conn: dict[str, Any], platform: str) -> dict[str, Any]:
    extra = conn.get("meta") or {}
    if platform == "meta":
        available = extra.get("available_accounts") or []
        if not available and conn.get("account_ids_list"):
            available = [{"id": a, "name": a} for a in conn["account_ids_list"]]
        normalized = []
        for row in available:
            if isinstance(row, str):
                normalized.append({"id": row, "name": row, "account_id": ""})
                continue
            aid = str((row or {}).get("id") or "").strip()
            if not aid:
                continue
            normalized.append(
                {
                    "id": aid,
                    "account_id": str((row or {}).get("account_id") or ""),
                    "name": str((row or {}).get("name") or aid),
                }
            )
        selected = conn.get("account_ids_list") or []
        name_by_id = {a["id"]: a.get("name") or a["id"] for a in normalized}
        return {
            "id": conn.get("id"),
            "connection_key": conn.get("connection_key") or "default",
            "label": conn.get("label") or conn.get("connection_key") or "Meta",
            "status": conn.get("status") or "disconnected",
            "expires_at": conn.get("expires_at"),
            "account_ids": selected,
            "selected_accounts": [
                {"id": aid, "name": name_by_id.get(aid, aid)} for aid in selected
            ],
            "available_accounts": normalized,
            "needs_select": bool(
                conn.get("access_token")
                and (
                    conn.get("status") == "pending_select"
                    or normalized
                )
            ),
        }

    available = extra.get("available_customers") or []
    if not available and conn.get("account_ids_list"):
        available = list(conn.get("account_ids_list") or [])
    selected = conn.get("account_ids_list") or []
    return {
        "id": conn.get("id"),
        "connection_key": conn.get("connection_key") or "default",
        "label": conn.get("label") or conn.get("connection_key") or "Google",
        "status": conn.get("status") or "disconnected",
        "account_ids": selected,
        "available_customers": available,
        "login_customer_id": conn.get("login_customer_id") or "",
        "needs_select": bool(
            conn.get("refresh_token")
            and (conn.get("status") == "pending_select" or available)
        ),
    }


def connection_status_summary(user_id: int) -> dict[str, Any]:
    settings = get_settings()
    meta_list = list_connections(user_id, "meta")
    google_list = list_connections(user_id, "google_ads")
    meta_cards = [_connection_card(c, "meta") for c in meta_list if c]
    google_cards = [_connection_card(c, "google_ads") for c in google_list if c]
    meta_ready = any(c.get("status") == "connected" and c.get("account_ids") for c in meta_cards)
    google_ready = any(
        c.get("status") == "connected" and c.get("account_ids") for c in google_cards
    )
    return {
        "meta": {
            "connected": meta_ready,
            "connections": meta_cards,
            "account_ids": [a for c in meta_cards for a in (c.get("account_ids") or [])],
            "status": "connected" if meta_ready else (
                "pending_select"
                if any(c.get("status") == "pending_select" for c in meta_cards)
                else "disconnected"
            ),
            "env_fallback": settings.meta_configured and not meta_ready,
        },
        "google_ads": {
            "connected": google_ready,
            "connections": google_cards,
            "account_ids": [a for c in google_cards for a in (c.get("account_ids") or [])],
            "status": "connected" if google_ready else (
                "pending_select"
                if any(c.get("status") == "pending_select" for c in google_cards)
                else "disconnected"
            ),
            "env_fallback": settings.google_ads_configured and not google_ready,
        },
        "meta_app_ready": settings.meta_app_credentials_ready,
        "google_oauth_ready": bool(
            settings.google_ads_client_id and settings.google_ads_client_secret
        ),
    }
