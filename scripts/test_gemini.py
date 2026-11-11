import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.services.llm import generate_answer

get_settings.cache_clear()
settings = get_settings()
print("model=", settings.gemini_model)
print("key_set=", bool(settings.gemini_api_key))
answer = generate_answer(
    "한 줄로 인사해줘. 테스트야.",
    {"metrics": [], "tasks": []},
    settings,
)
print("--- answer ---")
print(answer[:1000])
