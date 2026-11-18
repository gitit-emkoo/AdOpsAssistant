# AdOps Assistant

매일 광고 성과 메일 + 모바일 웹 질의 + 할 일/납부 리마인드 MVP입니다.

## 1차 범위

- Google Ads / Meta 성과 수집 (미설정 시 DEMO 데이터)
- 매일 메일 리포트 (본인 + 협업자)
- 스마트폰용 웹앱에서 실시간 질의
- 할 일·세무/납부 일정 리마인드
- 간단 지출 기록 + 월 요약 (장부 확장용 뼈대)
- Gemini 무료 티어 LLM (`gemini-3.6-flash`, 키 없으면 규칙 기반 응답)

## 빠른 시작

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

브라우저에서 `http://localhost:8000` 접속.

같은 Wi-Fi의 스마트폰에서는 PC IP로 접속하면 됩니다.  
예: `http://192.168.0.12:8000`

## 매일 메일 테스트

```bash
python scripts/send_daily_report.py --no-send
python scripts/send_daily_report.py
```

Gmail을 쓸 경우 Google 계정에서 **앱 비밀번호**를 발급해 `SMTP_PASSWORD`에 넣으세요.

## 클라우드 매일 실행 (무료)

GitHub Actions 워크플로: `.github/workflows/daily_report.yml`

Repository Secrets에 `.env.example`과 같은 키들을 등록한 뒤  
Actions에서 `Daily Ad Report`를 수동 실행해 보세요.

## API 연동

1. `.env`에서 `DEMO_MODE=false`
2. Google Ads / Meta 자격증명 입력
3. `GEMINI_API_KEY` 입력 (권장)
4. 메일 SMTP 설정

### Google Ads 준비물

- Developer Token
- OAuth Client ID / Secret
- Refresh Token
- Customer ID (필요 시 Login Customer ID)

### Meta 준비물

- Marketing API Access Token
- Ad Account ID (`act_...`) — 여러 계정이면 쉼표로: `act_111,act_222`
- 장기 토큰용 App ID / App Secret (`META_APP_ID`, `META_APP_SECRET`)

짧은 토큰을 장기 토큰(약 60일)으로 바꾸려면:

```bash
.\.venv\Scripts\python.exe scripts\extend_meta_token.py
```

웹앱의 **토큰 안내** 모달에서도 교환할 수 있습니다. 만료 임박 시 상단 알림이 뜹니다.

## 무료 상시 배포 (Oracle Always Free)

프론트+백+SQLite를 VM 한 대에 그대로 올리는 초보용 가이드:

→ [`docs/oracle-always-free-guide.md`](docs/oracle-always-free-guide.md)

매일 메일은 같은 VM의 cron을 쓰면 웹에서 넣은 할 일과 DB가 맞습니다. (GitHub Actions와는 DB를 공유하지 않음)

## 다음 확장

- 지출 CSV 업로드
- 월별 세무/비용 보고서 메일
- 카드/오픈뱅킹 연동 검토
- 도메인 + HTTPS (Cloudflare)
