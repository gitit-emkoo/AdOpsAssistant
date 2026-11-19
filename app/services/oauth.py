"""OAuth helpers for Meta (ads_read) and Google Ads (readonly via adwords scope)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings, get_settings
from app.services.connections import upsert_connection

META_AUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"
META_TOKEN_URL = "https://graph.facebook.com/v21.0/oauth/access_token"
META_GRAPH = "https://graph.facebook.com/v21.0"

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ADS_SCOPE = (
    "https://www.googleapis.com/auth/adwords openid email profile"
)
GOOGLE_ADS_SEARCH_URL = (
    "https://googleads.googleapis.com/v26/customers:listAccessibleCustomers"
)


def _base_url(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return (settings.app_base_url or "http://localhost:8000").rstrip("/")


def meta_redirect_uri(settings: Settings | None = None) -> str:
    return f"{_base_url(settings)}/oauth/meta/callback"


def google_redirect_uri(settings: Settings | None = None) -> str:
    return f"{_base_url(settings)}/oauth/google/callback"


def meta_authorize_url(state: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if not settings.meta_app_id:
        raise RuntimeError("META_APP_ID 가 없습니다.")
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": meta_redirect_uri(settings),
        "state": state,
        "response_type": "code",
        "scope": "ads_read,business_management",
    }
    return f"{META_AUTH_URL}?{urlencode(params)}"


def google_authorize_url(state: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if not settings.google_ads_client_id:
        raise RuntimeError("GOOGLE_ADS_CLIENT_ID 가 없습니다.")
    params = {
        "client_id": settings.google_ads_client_id,
        "redirect_uri": google_redirect_uri(settings),
        "response_type": "code",
        "scope": GOOGLE_ADS_SCOPE,
        "access_type": "offline",
        # 다른 Google 계정 추가 시 계정 선택 화면 노출
        "prompt": "select_account consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_meta_code(code: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    with httpx.Client(timeout=30) as client:
        short = client.get(
            META_TOKEN_URL,
            params={
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "redirect_uri": meta_redirect_uri(settings),
                "code": code,
            },
        )
        short.raise_for_status()
        short_data = short.json()
        access = short_data.get("access_token")
        if not access:
            raise RuntimeError(f"Meta 토큰 응답 오류: {short_data}")

        # long-lived (~60d)
        long = client.get(
            META_TOKEN_URL,
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "fb_exchange_token": access,
            },
        )
        long.raise_for_status()
        long_data = long.json()
        token = long_data.get("access_token") or access
        expires_in = int(long_data.get("expires_in") or short_data.get("expires_in") or 0)
        expires_at = None
        if expires_in:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()

        accounts = _list_meta_ad_accounts(client, token, settings.meta_api_version)
        identity = {"id": "", "name": ""}
        try:
            me = client.get(
                f"{META_GRAPH}/me",
                params={"access_token": token, "fields": "id,name"},
            )
            if me.status_code < 400:
                identity = {
                    "id": str(me.json().get("id") or ""),
                    "name": str(me.json().get("name") or ""),
                }
        except Exception:  # noqa: BLE001
            pass
    return {
        "access_token": token,
        "expires_at": expires_at,
        "available_accounts": accounts,
        "connection_key": identity.get("id") or "default",
        "label": identity.get("name") or identity.get("id") or "Meta",
    }


def _list_meta_ad_accounts(
    client: httpx.Client, token: str, api_version: str
) -> list[dict[str, str]]:
    accounts: list[dict[str, str]] = []
    seen: set[str] = set()
    url = f"https://graph.facebook.com/{api_version}/me/adaccounts"
    params: dict[str, Any] = {
        "access_token": token,
        "fields": "id,account_id,name,account_status",
        "limit": 50,
    }
    while url:
        resp = client.get(url, params=params)
        if resp.status_code >= 400:
            break
        data = resp.json()
        for row in data.get("data") or []:
            aid = str(row.get("id") or "").strip()
            if not aid or aid in seen:
                continue
            seen.add(aid)
            accounts.append(
                {
                    "id": aid,
                    "account_id": str(row.get("account_id") or ""),
                    "name": str(row.get("name") or aid),
                }
            )
        next_url = (data.get("paging") or {}).get("next")
        url = next_url or ""
        params = {}
    return accounts


def refresh_meta_available_accounts(
    user_id: int, *, connection_id: int | None = None
) -> list[dict[str, str]]:
    """Re-fetch ad account id/name catalog for an existing Meta connection."""
    from app.services.connections import get_connection, list_connections

    if connection_id is not None:
        conn = get_connection(user_id, "meta", connection_id=connection_id)
        targets = [conn] if conn else []
    else:
        targets = list_connections(user_id, "meta")
    settings = get_settings()
    last: list[dict[str, str]] = []
    for conn in targets:
        if not conn or not conn.get("access_token"):
            continue
        with httpx.Client(timeout=30) as client:
            accounts = _list_meta_ad_accounts(
                client, conn["access_token"], settings.meta_api_version
            )
        if not accounts:
            continue
        extra = dict(conn.get("meta") or {})
        extra["available_accounts"] = accounts
        extra["available_count"] = len(accounts)
        selected = list(conn.get("account_ids_list") or [])
        upsert_connection(
            user_id,
            "meta",
            connection_key=str(conn.get("connection_key") or "default"),
            label=str(conn.get("label") or ""),
            access_token=conn.get("access_token"),
            expires_at=conn.get("expires_at"),
            account_ids=selected,
            status=conn.get("status") or "connected",
            meta_json=extra,
        )
        last = accounts
    return last


def save_meta_connection(
    user_id: int,
    payload: dict[str, Any],
    *,
    selected_account_ids: list[str] | None = None,
    status: str | None = None,
    connection_key: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    available_raw = payload.get("available_accounts")
    if available_raw is None and payload.get("account_ids"):
        # backward compat: plain id list
        available_raw = [{"id": a, "name": a} for a in (payload.get("account_ids") or [])]
    available: list[dict[str, str]] = []
    for row in available_raw or []:
        if isinstance(row, str):
            available.append({"id": row, "name": row, "account_id": ""})
            continue
        aid = str(row.get("id") or "").strip()
        if not aid:
            continue
        available.append(
            {
                "id": aid,
                "account_id": str(row.get("account_id") or ""),
                "name": str(row.get("name") or aid),
            }
        )
    available_ids = {a["id"] for a in available}

    if selected_account_ids is not None:
        selected = []
        for raw in selected_account_ids:
            aid = str(raw or "").strip()
            if not aid:
                continue
            if not aid.startswith("act_"):
                aid = f"act_{aid}"
            if available_ids and aid not in available_ids:
                # allow act_123 vs 123 mismatch against available
                alt = aid.replace("act_", "", 1)
                match = next(
                    (
                        a["id"]
                        for a in available
                        if a["id"] == aid
                        or a["id"].endswith(alt)
                        or a.get("account_id") == alt
                    ),
                    None,
                )
                if match:
                    aid = match
                else:
                    continue
            if aid not in selected:
                selected.append(aid)
        if not selected:
            raise RuntimeError("수집할 Meta 광고 계정을 하나 이상 선택하세요.")
        final_status = status or "connected"
        account_ids = selected
    else:
        all_ids = [a["id"] for a in available]
        if len(all_ids) == 1:
            account_ids = all_ids
            final_status = status or "connected"
        else:
            account_ids = []
            final_status = status or ("pending_select" if all_ids else "connected")

    key = connection_key or payload.get("connection_key") or "default"
    display = label if label is not None else payload.get("label") or key
    return upsert_connection(
        user_id,
        "meta",
        connection_key=str(key),
        label=str(display or ""),
        access_token=payload.get("access_token"),
        refresh_token=None,
        expires_at=payload.get("expires_at"),
        account_ids=account_ids,
        status=final_status,
        meta_json={
            "account_count": len(account_ids),
            "available_accounts": available,
            "available_count": len(available),
        },
    )


def exchange_google_code(code: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_ads_client_id,
                "client_secret": settings.google_ads_client_secret,
                "redirect_uri": google_redirect_uri(settings),
                "grant_type": "authorization_code",
            },
        )
        data = resp.json()
        if resp.status_code >= 400:
            raise RuntimeError(f"Google 토큰 교환 실패: {data}")
        refresh = data.get("refresh_token")
        access = data.get("access_token")
        if not refresh:
            raise RuntimeError(
                "refresh_token이 없습니다. Google 동의 화면에서 다시 허용해 주세요."
            )
        customers = list_google_accessible_customers(refresh, settings)
        identity = {"id": "", "email": "", "name": ""}
        if access:
            try:
                with httpx.Client(timeout=20) as client:
                    info = client.get(
                        "https://openidconnect.googleapis.com/v1/userinfo",
                        headers={"Authorization": f"Bearer {access}"},
                    )
                    if info.status_code < 400:
                        data = info.json()
                        identity = {
                            "id": str(data.get("sub") or ""),
                            "email": str(data.get("email") or ""),
                            "name": str(data.get("name") or data.get("email") or ""),
                        }
            except Exception:  # noqa: BLE001
                pass
    return {
        "refresh_token": refresh,
        "access_token": access,
        "account_ids": customers,
        "available_customers": customers,
        "connection_key": identity.get("id")
        or identity.get("email")
        or "default",
        "label": identity.get("email")
        or identity.get("name")
        or identity.get("id")
        or "Google",
    }


def _google_access_token(refresh_token: str, settings: Settings) -> str:
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_ads_client_id,
                "client_secret": settings.google_ads_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        data = resp.json()
        if resp.status_code >= 400:
            raise RuntimeError(f"Google access token 갱신 실패: {data}")
        return data["access_token"]


def list_google_accessible_customers(
    refresh_token: str, settings: Settings | None = None
) -> list[str]:
    settings = settings or get_settings()
    access = _google_access_token(refresh_token, settings)
    headers = {
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json",
    }
    if settings.google_ads_developer_token:
        headers["developer-token"] = settings.google_ads_developer_token
    with httpx.Client(timeout=30) as client:
        resp = client.get(GOOGLE_ADS_SEARCH_URL, headers=headers)
        data = resp.json()
        if resp.status_code >= 400:
            raise RuntimeError(f"Google Ads 계정 목록 실패: {json.dumps(data)[:400]}")
    names = data.get("resourceNames") or []
    # customers/1234567890
    out: list[str] = []
    for name in names:
        cid = str(name).split("/")[-1]
        if cid and cid not in out:
            out.append(cid)
    return out


def save_google_connection(
    user_id: int,
    payload: dict[str, Any],
    *,
    selected_customer_id: str | None = None,
    selected_customer_ids: list[str] | None = None,
    login_customer_id: str | None = None,
    status: str | None = None,
    connection_key: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    available = [
        str(a).strip().replace("-", "")
        for a in (payload.get("available_customers") or payload.get("account_ids") or [])
        if str(a).strip()
    ]
    seen: set[str] = set()
    available_unique: list[str] = []
    for cid in available:
        if cid not in seen:
            seen.add(cid)
            available_unique.append(cid)
    available = available_unique

    if selected_customer_ids is not None:
        selected = []
        for raw in selected_customer_ids:
            cid = str(raw or "").strip().replace("-", "")
            if not cid:
                continue
            if available and cid not in available:
                continue
            if cid not in selected:
                selected.append(cid)
        if not selected:
            raise RuntimeError("수집할 Google Ads 고객을 하나 이상 선택하세요.")
        accounts = selected
        final_status = status or "connected"
    elif selected_customer_id:
        cid = selected_customer_id.strip().replace("-", "")
        accounts = [cid] if cid else []
        final_status = status or "connected"
    else:
        if len(available) == 1:
            accounts = available
            final_status = status or "connected"
        else:
            accounts = []
            final_status = status or ("pending_select" if available else "connected")

    key = connection_key or payload.get("connection_key") or "default"
    display = label if label is not None else payload.get("label") or key
    return upsert_connection(
        user_id,
        "google_ads",
        connection_key=str(key),
        label=str(display or ""),
        access_token=payload.get("access_token"),
        refresh_token=payload.get("refresh_token"),
        expires_at=None,
        account_ids=accounts,
        login_customer_id=login_customer_id or "",
        status=final_status,
        meta_json={
            "account_count": len(accounts),
            "available_customers": available,
            "available_count": len(available),
        },
    )
