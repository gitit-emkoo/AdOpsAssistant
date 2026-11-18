"""Per-user ad platform connections (OAuth tokens)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from app.config import Settings, get_settings
from app.db import get_conn, now_iso, row_to_dict


def list_connections(user_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, user_id, platform, expires_at, account_ids, login_customer_id,
                   status, updated_at, created_at,
                   CASE WHEN access_token IS NOT NULL AND access_token != '' THEN 1 ELSE 0 END AS has_access_token,
                   CASE WHEN refresh_token IS NOT NULL AND refresh_token != '' THEN 1 ELSE 0 END AS has_refresh_token
            FROM ad_connections
            WHERE user_id = ?
            ORDER BY platform
            """,
            (user_id,),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["account_ids_list"] = _split_accounts(item.get("account_ids") or "")
        items.append(item)
    return items


def get_connection(user_id: int, platform: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM ad_connections
            WHERE user_id = ? AND platform = ?
            """,
            (user_id, platform),
        ).fetchone()
    return row_to_dict(row)


def upsert_connection(
    user_id: int,
    platform: str,
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    expires_at: str | None = None,
    account_ids: str | list[str] | None = None,
    login_customer_id: str | None = None,
    status: str = "connected",
    meta_json: dict | None = None,
) -> dict[str, Any]:
    if isinstance(account_ids, list):
        account_ids = ",".join(account_ids)
    account_ids = account_ids or ""
    login_customer_id = login_customer_id or ""
    now = now_iso()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM ad_connections WHERE user_id = ? AND platform = ?",
            (user_id, platform),
        ).fetchone()
        payload = json.dumps(meta_json or {}, ensure_ascii=False)
        if existing:
            conn.execute(
                """
                UPDATE ad_connections SET
                    access_token = COALESCE(?, access_token),
                    refresh_token = COALESCE(?, refresh_token),
                    expires_at = ?,
                    account_ids = ?,
                    login_customer_id = ?,
                    status = ?,
                    meta_json = ?,
                    updated_at = ?
                WHERE user_id = ? AND platform = ?
                """,
                (
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
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO ad_connections (
                    user_id, platform, access_token, refresh_token, expires_at,
                    account_ids, login_customer_id, status, meta_json, updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    platform,
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
    return get_connection(user_id, platform) or {}


def delete_connection(user_id: int, platform: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM ad_connections WHERE user_id = ? AND platform = ?",
            (user_id, platform),
        )
        return cur.rowcount > 0


def save_oauth_state(user_id: int, platform: str) -> str:
    import secrets

    state = secrets.token_urlsafe(24)
    expires = (datetime.utcnow() + timedelta(minutes=20)).isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO oauth_states (state, user_id, platform, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (state, user_id, platform, expires, now_iso()),
        )
    return state


def consume_oauth_state(state: str, platform: str) -> int | None:
    now = datetime.utcnow().isoformat(timespec="seconds")
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT user_id, expires_at FROM oauth_states
            WHERE state = ? AND platform = ?
            """,
            (state, platform),
        ).fetchone()
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        if not row:
            return None
        if str(row["expires_at"]) < now:
            return None
        return int(row["user_id"])


def _split_accounts(raw: str) -> list[str]:
    ids: list[str] = []
    for part in (raw or "").replace(";", ",").split(","):
        value = part.strip()
        if value:
            ids.append(value)
    return ids


def settings_for_user(user_id: int | None) -> Settings:
    """Merge .env defaults with per-user OAuth connections when present."""
    settings = get_settings()
    if not user_id:
        return settings
    updates: dict[str, Any] = {}
    meta = get_connection(user_id, "meta")
    if meta and meta.get("status") == "connected" and meta.get("access_token"):
        updates["meta_access_token"] = meta["access_token"]
        if meta.get("account_ids"):
            updates["meta_ad_account_id"] = meta["account_ids"]
        if meta.get("expires_at"):
            updates["meta_token_expires_at"] = meta["expires_at"]
    google = get_connection(user_id, "google_ads")
    if (
        google
        and google.get("status") == "connected"
        and google.get("refresh_token")
    ):
        updates["google_ads_refresh_token"] = google["refresh_token"]
        if google.get("account_ids"):
            accounts = _split_accounts(google["account_ids"])
            if accounts:
                updates["google_ads_customer_id"] = accounts[0]
        if google.get("login_customer_id"):
            updates["google_ads_login_customer_id"] = google["login_customer_id"]
    if not updates:
        return settings
    return settings.model_copy(update=updates)


def _parse_meta_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def connection_status_summary(user_id: int) -> dict[str, Any]:
    settings = get_settings()
    items = {c["platform"]: c for c in list_connections(user_id)}
    meta = items.get("meta")
    google = items.get("google_ads")
    meta_full = get_connection(user_id, "meta") if meta else None
    meta_extra = _parse_meta_json((meta_full or {}).get("meta_json"))
    available = meta_extra.get("available_accounts") or []
    if not available and meta and meta.get("account_ids_list"):
        available = [{"id": a, "name": a} for a in meta["account_ids_list"]]
    # Ensure dict shape for template (id/name)
    normalized_available: list[dict[str, str]] = []
    for row in available:
        if isinstance(row, str):
            normalized_available.append({"id": row, "name": row, "account_id": ""})
            continue
        aid = str((row or {}).get("id") or "").strip()
        if not aid:
            continue
        normalized_available.append(
            {
                "id": aid,
                "account_id": str((row or {}).get("account_id") or ""),
                "name": str((row or {}).get("name") or aid),
            }
        )
    available = normalized_available
    name_by_id = {a["id"]: a.get("name") or a["id"] for a in available}
    selected_ids = (meta or {}).get("account_ids_list") or []
    selected_labels = [
        {"id": aid, "name": name_by_id.get(aid, aid)} for aid in selected_ids
    ]
    meta_token = bool(meta and meta.get("has_access_token"))
    meta_ready = meta_token and (meta or {}).get("status") == "connected"
    return {
        "meta": {
            "connected": meta_ready,
            "account_ids": selected_ids,
            "selected_accounts": selected_labels,
            "available_accounts": available,
            "expires_at": (meta or {}).get("expires_at"),
            "status": (meta or {}).get("status") or "disconnected",
            "needs_select": bool(
                meta_token
                and (
                    (meta or {}).get("status") == "pending_select"
                    or available
                )
            ),
            "env_fallback": settings.meta_configured and not meta_ready,
        },
        "google_ads": {
            "connected": bool(
                google
                and google.get("has_refresh_token")
                and google.get("status") == "connected"
            ),
            "account_ids": (google or {}).get("account_ids_list") or [],
            "login_customer_id": (google or {}).get("login_customer_id") or "",
            "status": (google or {}).get("status") or "disconnected",
            "env_fallback": settings.google_ads_configured
            and not (
                google
                and google.get("has_refresh_token")
                and google.get("status") == "connected"
            ),
        },
        "meta_app_ready": settings.meta_app_credentials_ready,
        "google_oauth_ready": bool(
            settings.google_ads_client_id and settings.google_ads_client_secret
        ),
    }
