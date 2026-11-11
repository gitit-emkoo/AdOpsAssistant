import json
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.collectors.google_ads import GOOGLE_ADS_SEARCH_URL, _access_token
from app.config import get_settings

get_settings.cache_clear()
s = get_settings()
day = (date.today() - timedelta(days=1)).isoformat()
customer_id = s.google_ads_customer_id.replace("-", "")
headers = {
    "Authorization": f"Bearer {_access_token(s)}",
    "Content-Type": "application/json",
}
if s.google_ads_developer_token:
    headers["developer-token"] = s.google_ads_developer_token
if s.google_ads_login_customer_id:
    headers["login-customer-id"] = s.google_ads_login_customer_id.replace("-", "")

query = f"""
SELECT metrics.cost_micros, metrics.impressions, metrics.clicks
FROM customer
WHERE segments.date = '{day}'
"""
resp = httpx.post(
    GOOGLE_ADS_SEARCH_URL.format(customer_id=customer_id),
    headers=headers,
    json={"query": query},
    timeout=60,
)
print("status=", resp.status_code)
print(json.dumps(resp.json(), ensure_ascii=False, indent=2)[:2000])
