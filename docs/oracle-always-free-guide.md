# Oracle Always Free 배포 가이드 (초보용)

목표: **무료 VM 1대**에 지금 AdOps Assistant(프론트+백+SQLite)를 그대로 올리고, 폰에서도 접속하기.

구성

| 역할 | 어디서 |
|------|--------|
| 웹앱(할 일·대화·DB) | Oracle Always Free VM |
| 매일 메일 | **같은 VM의 cron** (권장) / 또는 기존 GitHub Actions |
| 도메인·HTTPS | 나중에 Cloudflare (선택) |

> GitHub Actions와 Oracle VM은 **DB를 공유하지 않습니다.**  
> 웹에서 입력한 할 일이 메일에도 나오게 하려면, 매일 메일은 **Oracle VM에서** 돌리는 편이 맞습니다.

---

## 0. 준비물

- 신용카드 (가입 시 등록, Always Free만 쓰면 보통 과금 없음)
- GitHub에 올린 이 저장소 URL
- 로컬 `.env` 내용 (비밀키 — 채팅/메일에 붙여넣지 말 것)
- Windows면 PowerShell 또는 Windows Terminal

---

## 1. Oracle Cloud 계정 만들기

1. [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/) 접속
2. **Start for free** → 국가/이메일/비밀번호 입력
3. 집주소·전화·카드 등록 (본인 확인용)
4. Home Region은 **나중에 바꾸기 어렵습니다.**  
   아시아면 `Japan Central (Osaka)` / `Japan East (Tokyo)` / `South Korea Central (Seoul)` 중 **용량 여유 있는 곳**을 고르세요.  
   (Seoul이 꽉 차 있으면 Osaka/Tokyo 추천)

가입 메일이 오면 콘솔 로그인: [https://cloud.oracle.com](https://cloud.oracle.com)

---

## 2. Always Free VM 만들기

메뉴(☰) → **Compute** → **Instances** → **Create instance**

### 기본

- **Name**: `adops-assistant` (아무 이름)
- **Compartment**: 기본값(root) 유지

### Image (OS)

1. **Change image**
2. **Canonical Ubuntu 24.04** (또는 22.04) 선택  
   - Oracle Linux도 가능하지만, 이 가이드는 Ubuntu 기준입니다.

### Shape (중요 — 무료 한도)

1. **Change shape**
2. **Ampere** 계열
3. Shape: `VM.Standard.A1.Flex`
4. **OCPU = 2**, **Memory = 12 GB**  
   → 화면에 **Always Free-eligible** 표시가 있는지 확인
5. 이 값을 넘기면 유료가 될 수 있으니 **2 / 12를 넘기지 마세요.**

> `Out of capacity` 나오면: 다른 Availability Domain 시도, 몇 시간 뒤 재시도, 또는 Home Region을 바꿔 새로 가입하는 수밖에 없는 경우도 있습니다.

### Networking

- **Assign a public IPv4 address** = **Yes** (꼭)
- VCN/Subnet은 기본 생성값 그대로 OK

### SSH 키

1. **Generate a key pair for me** 선택
2. **Save Private Key** / **Save Public Key** 둘 다 PC에 저장  
   예: `C:\Users\당신\.ssh\oracle-adops.key`
3. 개인키(`.key`)는 **절대 공개/업로드 금지**

**Create** 클릭 → 상태가 **Running** 될 때까지 대기  
인스턴스 상세에서 **Public IP** 복사해 두세요. (아래에서는 `YOUR_IP`)

Ubuntu 기본 사용자 이름: `ubuntu`

---

## 3. 방화벽 열기 (웹 접속용)

Oracle은 **보안 목록(Security List)** 과 **OS 방화벽** 둘 다 열어야 합니다.

### 3-1. OCI Security List

1. 인스턴스 → **Subnet** 클릭
2. **Security Lists** → Default Security List
3. **Add Ingress Rules**

| 항목 | 값 |
|------|-----|
| Source CIDR | `0.0.0.0/0` (처음엔 편하게, 나중에 좁혀도 됨) |
| IP Protocol | TCP |
| Destination Port Range | `8000` |

저장.

(SSH 22번은 기본에 있는 경우가 많습니다. 없으면 22도 같은 방식으로 추가.)

### 3-2. Ubuntu iptables (자주 막히는 지점)

SSH 접속 후 아래 실행:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || sudo apt-get install -y iptables-persistent
sudo netfilter-persistent save
```

`iptables-persistent` 설치 중 질문이 나오면 **Yes**로 현재 규칙 저장.

---

## 4. Windows에서 SSH 접속

PowerShell:

```powershell
ssh -i $env:USERPROFILE\.ssh\oracle-adops.key ubuntu@YOUR_IP
```

- 키 경로/파일명은 실제 저장한 이름으로
- 처음이면 `yes` 입력
- 프롬프트가 `ubuntu@...$` 이면 성공

접속이 안 되면

- Public IP가 맞는지
- 인스턴스가 Running인지
- Security List에 22 열려 있는지
- 키 파일 권한이 이상한 경우: 키를 `.ssh` 폴더로 옮기고 다시 시도

---

## 5. 서버에 앱 설치

SSH 들어간 상태에서 순서대로:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git
```

### 저장소 clone

```bash
cd ~
git clone https://github.com/gitit-emkoo/AdOpsAssistant.git
cd AdOpsAssistant
```

비공개 저장소면 GitHub Personal Access Token이 필요하거나, `scp`로 파일을 올려도 됩니다.

### 가상환경 + 패키지

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### .env 만들기

```bash
nano .env
```

로컬 `.env` 내용을 붙여넣되, 아래만 서버용으로 바꿉니다.

```env
APP_BASE_URL=http://YOUR_IP:8000
DEMO_MODE=false
```

저장: `Ctrl+O` → Enter → `Ctrl+X`

> `.env`에는 API 키·SMTP 비밀번호가 들어 있습니다. 절대 Git에 커밋하지 마세요. (이미 `.gitignore`에 있는 것이 정상)

### 한 번 실행 테스트

```bash
source ~/AdOpsAssistant/.venv/bin/activate
cd ~/AdOpsAssistant
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

폰/PC 브라우저에서:

```text
http://YOUR_IP:8000
```

화면이 보이면 성공. 터미널에서 `Ctrl+C`로 끄고, 아래 systemd로 상시 실행합니다.

---

## 6. 재부팅 후에도 자동 실행 (systemd)

```bash
sudo nano /etc/systemd/system/adops.service
```

내용:

```ini
[Unit]
Description=AdOps Assistant
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/AdOpsAssistant
Environment=PATH=/home/ubuntu/AdOpsAssistant/.venv/bin
ExecStart=/home/ubuntu/AdOpsAssistant/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

적용:

```bash
sudo systemctl daemon-reload
sudo systemctl enable adops
sudo systemctl start adops
sudo systemctl status adops
```

로그 보기:

```bash
journalctl -u adops -f
```

---

## 7. 매일 메일 (VM cron 권장)

웹과 같은 DB를 쓰려면 VM에서 보냅니다.

```bash
crontab -e
```

처음이면 `nano` 선택. 맨 아래에 (한국시간 아침 9시 예시):

```cron
0 0 * * * /home/ubuntu/AdOpsAssistant/.venv/bin/python /home/ubuntu/AdOpsAssistant/scripts/send_daily_report.py >> /home/ubuntu/AdOpsAssistant/cron-report.log 2>&1
```

> 서버 시간이 UTC인 경우가 많습니다.  
> 한국 09:00 = UTC 00:00 이라서 위처럼 `0 0 * * *` 입니다.  
> 확인: `timedatectl`

GitHub Actions는 **끄거나**, API만 모아 메일 보내는 백업으로 남겨도 됩니다.  
할 일 연동까지 맞추려면 **VM cron만** 쓰는 게 단순합니다.

---

## 8. 코드 업데이트할 때

로컬에서 push한 뒤, 서버에서:

```bash
cd ~/AdOpsAssistant
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart adops
```

`.env`는 pull로 덮어쓰지 않습니다.

---

## 9. (선택) 도메인 + HTTPS — Cloudflare

1. 도메인을 Cloudflare에 연결
2. DNS A 레코드 → Oracle Public IP
3. 나중에 Nginx + Let’s Encrypt, 또는 Cloudflare Tunnel/프록시로 443 연결

처음엔 `http://IP:8000` 만으로도 모바일 사용 가능합니다.

---

## 10. 자주 막히는 문제

| 증상 | 확인 |
|------|------|
| VM 생성 Out of capacity | 다른 AD/시간/리전 재시도 |
| SSH 타임아웃 | Public IP, Security List 22, 인스턴스 Running |
| 브라우저는 안 열림 | Security List **8000** + Ubuntu iptables 8000 |
| 페이지는 뜨는데 연동 실패 | 서버 `.env` 키, `DEMO_MODE=false` |
| 메일은 오는데 할 일 없음 | 메일을 Actions가 아니라 **VM cron**으로 보내는지 |
| 과금 걱정 | Compute shape이 Always Free인지, 추가 유료 DB/로드밸런서를 안 만들었는지 과금 알림 켜기 |

과금 알림: 콘솔 → Billing → Budgets / 이메일 알림에서 **$1** 같은 낮은 임계값 알림을 켜 두세요.

---

## 한 줄 요약

1. Always Free Ampere(2 OCPU / 12GB) Ubuntu VM 생성  
2. 포트 8000 열기  
3. git clone → `.env` → uvicorn  
4. systemd로 상시 실행  
5. cron으로 매일 메일  
6. 폰에서 `http://공인IP:8000`
