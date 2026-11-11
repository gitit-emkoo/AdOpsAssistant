"""Google Ads OAuth Refresh Token 발급 도우미.

사전 준비:
1) Google Cloud에서 OAuth 클라이언트(데스크톱 앱) 생성
2) Client ID / Client Secret 확보

사용:
  .\\.venv\\Scripts\\python.exe scripts\\google_ads_oauth.py
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings

SCOPE = "https://www.googleapis.com/auth/adwords"
REDIRECT_URI = "http://127.0.0.1:8080/oauth2callback"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class _Handler(BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/oauth2callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.parse_qs(parsed.query)
        _Handler.code = (qs.get("code") or [None])[0]
        _Handler.error = (qs.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            "<h2>인증 완료</h2><p>이 창을 닫고 터미널로 돌아가세요.</p>".encode(
                "utf-8"
            )
        )

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def main() -> int:
    get_settings.cache_clear()
    settings = get_settings()

    client_id = settings.google_ads_client_id.strip()
    client_secret = settings.google_ads_client_secret.strip()
    if not client_id or not client_secret:
        print("먼저 .env에 GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET 을 넣으세요.")
        print("OAuth 클라이언트 유형은 '데스크톱 앱' 이어야 합니다.")
        return 1

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print("브라우저에서 Google 로그인/동의를 진행합니다...")
    print(url)
    webbrowser.open(url)

    server = HTTPServer(("127.0.0.1", 8080), _Handler)
    print("콜백 대기 중: http://127.0.0.1:8080/oauth2callback")
    while _Handler.code is None and _Handler.error is None:
        server.handle_request()
    server.server_close()

    if _Handler.error:
        print("인증 실패:", _Handler.error)
        return 1
    if not _Handler.code:
        print("authorization code를 받지 못했습니다.")
        return 1

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "code": _Handler.code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    data = resp.json()
    if resp.status_code >= 400:
        print("토큰 교환 실패:", json.dumps(data, ensure_ascii=False))
        return 1

    refresh = data.get("refresh_token")
    if not refresh:
        print("refresh_token이 없습니다. prompt=consent 로 다시 시도하세요.")
        print(json.dumps({k: ("***" if "token" in k else v) for k, v in data.items()}, ensure_ascii=False))
        return 1

    print("\n성공. 아래 값을 .env의 GOOGLE_ADS_REFRESH_TOKEN 에 넣으세요.\n")
    print(refresh)
    print("\n다음은 Developer Token + Customer ID 입력 후:")
    print("  .\\.venv\\Scripts\\python.exe scripts\\test_ads_connection.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
