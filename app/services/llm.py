from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings, get_settings


SYSTEM_PROMPT = """당신은 광고 성과와 업무 리마인드를 돕는 한국어 AI 비서입니다.
주어진 숫자/일정 데이터만 근거로 답하세요. 없는 수치는 추측하지 마세요.
앱 광고에서는 클릭과 설치(installs)를 구분해서 보세요. 클릭 대비 설치율, CPI를 우선 언급하세요.
답변은 짧고 실행 가능하게: 요약 → 이상 징후 → 오늘 할 일 순으로 작성하세요.
금액은 원 단위, 비율은 %로 표기하세요.
"""

# 일부 최신 모델은 일시 과부하(503)가 잦아서 폴백 체인을 둡니다.
MODEL_FALLBACKS = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
)


def _rule_based_answer(question: str, context: dict[str, Any]) -> str:
    metrics = context.get("metrics") or []
    tasks = context.get("tasks") or []
    lines = ["[데모/오프라인 응답]", ""]

    if metrics:
        lines.append("최근 광고 성과:")
        for m in metrics[:4]:
            spend = m.get("spend", 0)
            clicks = m.get("clicks", 0)
            roas = 0.0
            if spend:
                roas = float(m.get("conversion_value", 0) or 0) / float(spend)
            installs = float(m.get("installs") or 0)
            cpi = (spend / installs) if installs else 0.0
            lines.append(
                f"- {m.get('platform')} {m.get('metric_date')}: "
                f"지출 {spend:,.0f}원 / 클릭 {clicks} / 설치 {installs:,.0f} "
                f"/ CPI {cpi:,.0f}원 / ROAS {roas:.2f}"
            )
        lines.append("")

    open_tasks = [t for t in tasks if t.get("status") == "open"]
    if open_tasks:
        lines.append("열린 할 일:")
        for t in open_tasks[:5]:
            due = t.get("due_date") or "기한 없음"
            lines.append(f"- [{t.get('category')}] {t.get('title')} (기한: {due})")
        lines.append("")

    lines.append(f"질문: {question}")
    lines.append("Gemini API 키를 연결하면 더 자연스러운 분석을 제공합니다.")
    return "\n".join(lines)


def _candidate_models(settings: Settings) -> list[str]:
    models = [settings.gemini_model, *MODEL_FALLBACKS]
    seen: set[str] = set()
    ordered: list[str] = []
    for model in models:
        if model and model not in seen:
            seen.add(model)
            ordered.append(model)
    return ordered


def _call_gemini(question: str, context: dict[str, Any], settings: Settings) -> str:
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"컨텍스트(JSON):\n{context}\n\n"
        f"사용자 질문: {question}\n\n"
        "위 데이터만 사용해서 답하세요."
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ]
    }
    errors: list[str] = []

    with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        for model in _candidate_models(settings):
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent"
            )
            try:
                resp = client.post(
                    url,
                    params={"key": settings.gemini_api_key},
                    json=payload,
                )
                data = resp.json()
                if resp.status_code >= 400:
                    message = data.get("error", {}).get("message", resp.text[:200])
                    errors.append(f"{model}: {message}")
                    continue
                text = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text")
                )
                if text and text.strip():
                    return text.strip()
                errors.append(f"{model}: empty response")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{model}: {exc}")

    raise RuntimeError(" / ".join(errors) or "Gemini 호출 실패")


def generate_answer(
    question: str,
    context: dict[str, Any],
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    if not settings.llm_configured:
        return _rule_based_answer(question, context)

    try:
        return _call_gemini(question, context, settings)
    except Exception as exc:  # noqa: BLE001 — fallback for free-tier/network issues
        return (
            _rule_based_answer(question, context)
            + f"\n\n(LLM 호출 실패: {exc})"
        )


def generate_daily_insights(context: dict[str, Any], settings: Settings | None = None) -> str:
    question = (
        "어제 광고 성과를 요약하고, 이상 징후와 오늘 할 일 3가지를 제안해줘. "
        "납부/세무 일정이 있으면 함께 리마인드해줘."
    )
    return generate_answer(question, context, settings)
