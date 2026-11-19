# AdOps Assistant

광고 성과 조회 · 질의 · 할 일 · 일/월간 리포트를 위한 웹앱입니다.

## 기능

- Google Ads / Meta 읽기 전용 연동 (OAuth)
- 대시보드 · 채팅 질의 · 진행 중 광고
- 일간/월간 성과 리포트 (이메일)
- 할 일 · 납부 리마인드 · 간단 지출 기록

## 로컬 실행

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

브라우저: `http://localhost:8000`  
환경 변수는 `.env.example`을 참고하세요.

## 라이선스

Private / 내부용.
