import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings

get_settings.cache_clear()
s = get_settings()
env_path = Path(".env")
print("--- .env keys present ---")
for line in env_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    value = value.strip().strip('"').strip("'")
    print(f"{key}: set={bool(value)} len={len(value)}")

print("--- runtime ---")
print("demo_mode=", s.demo_mode)
print("llm_configured=", s.llm_configured)
print("email_configured=", s.email_configured)
print("smtp_user_set=", bool(s.smtp_user))
print("smtp_password_set=", bool(s.smtp_password))
print("email_from_set=", bool(s.email_from))
print("email_to_set=", bool(s.email_to))
print("recipients_count=", len(s.email_recipients))
print("gemini_set=", bool(s.gemini_api_key))
