import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings

get_settings.cache_clear()
s = get_settings()

models = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.8-flash",
]

with httpx.Client(timeout=httpx.Timeout(25.0, connect=10.0)) as client:
    for model in models:
        print(f"try {model}...", flush=True)
        try:
            resp = client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": s.gemini_api_key},
                json={
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": "한국어로 짧게 인사해줘."}],
                        }
                    ]
                },
            )
            print("status=", resp.status_code, flush=True)
            data = resp.json()
            if resp.status_code >= 400:
                print(json.dumps(data, ensure_ascii=False)[:250], flush=True)
                continue
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            print("OK=", text, flush=True)
            print("USE_MODEL=", model, flush=True)
            break
        except Exception as exc:
            print("error=", type(exc).__name__, exc, flush=True)
