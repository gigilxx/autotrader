# AWS EC2 Windows Server 배포 가이드

> **환경**: AWS EC2 Windows Server 2022 / 서울 리전(ap-northeast-2)  
> **예상 비용**: t3.small Windows ≈ **월 $35~40** (On-Demand 기준, 24시간 상시 가동)  
> **GitHub 저장소**: https://github.com/gigilxx/autotrader

---

## 0. 사전 준비

- AWS 계정 (없으면 아래 1단계에서 생성)
- GitHub 저장소 접근 권한 (`gigilxx/autotrader`)
- `.env` 파일 (KIS API 키, 텔레그램 토큰 등 — 로컬 PC에 있는 파일)
- RDP 클라이언트 (Windows 기본 제공: `mstsc`)

---

## 1. AWS 계정 생성

1. https://aws.amazon.com/ko/ → **무료로 시작하기**
2. 이메일, 비밀번호, 계정 이름 입력
3. 개인 계정 선택 → 카드 등록 (1달러 임시 청구 후 환불)
4. 이메일 인증 완료
5. 콘솔 로그인 → **루트 계정 MFA 설정 권장** (보안 → IAM → MFA 추가)

> **비용 알림 설정**: Billing → Budgets → 월 $50 초과 시 이메일 알림 설정 권장

---

## 2. EC2 인스턴스 생성

### 2-1. 리전 선택

AWS 콘솔 우측 상단 → **아시아 태평양(서울) ap-northeast-2** 선택

### 2-2. EC2 → 인스턴스 시작

1. 서비스 검색 → EC2 → **인스턴스 시작**

2. **이름**: `autotrader`

3. **AMI 선택**:
   - "Windows" 검색 → **Windows Server 2022 Base** 선택
   - (2022 없으면 2019 Base도 가능)

4. **인스턴스 유형**: `t3.small` (vCPU 2, RAM 2GB)
   - t3.micro(1GB)는 Next.js 빌드 시 메모리 부족 → 비추천

5. **키 페어**: 새 키 페어 생성
   - 이름: `autotrader-key`
   - 유형: RSA
   - 형식: .pem
   - **생성 후 `.pem` 파일을 안전한 곳에 보관** (RDP 암호 복구에 필요)

6. **네트워크 설정** → 보안 그룹 생성:

   | 유형 | 프로토콜 | 포트 | 소스 | 설명 |
   |------|---------|------|------|------|
   | RDP | TCP | 3389 | 내 IP | 원격 접속 |
   | 사용자 지정 TCP | TCP | 8000 | 내 IP | FastAPI |
   | 사용자 지정 TCP | TCP | 3000 | 내 IP | Next.js 대시보드 |

   > **소스를 "내 IP"로 설정** — 0.0.0.0/0(전체 공개) 하면 봇 API가 외부에 노출됨

7. **스토리지**: 30GB gp3 (기본값 유지)

8. **인스턴스 시작** 클릭

### 2-3. Elastic IP 할당 (IP 고정)

인스턴스를 재시작해도 IP가 바뀌지 않도록 고정 IP 할당.

1. EC2 → **탄력적 IP** → 탄력적 IP 주소 할당 → 할당
2. 할당된 IP 선택 → **탄력적 IP 주소 연결** → 인스턴스 선택 → 연결

---

## 3. RDP 접속

### 3-1. Windows 암호 확인

1. EC2 → 인스턴스 선택 → **연결** → **RDP 클라이언트** 탭
2. **암호 가져오기** → `.pem` 파일 업로드 → 암호 해독
3. 암호 메모 (Administrator 계정 비밀번호)

> 인스턴스 시작 후 암호 생성에 최대 **4분** 소요됨

### 3-2. RDP 연결

```
Windows + R → mstsc 실행
컴퓨터: <Elastic IP>:3389
사용자 이름: Administrator
암호: (3-1에서 해독한 암호)
```

---

## 4. 타임존 설정 (필수)

**AWS EC2 Windows Server는 기본 타임존이 UTC** — 한국 시간(KST, UTC+9)과 9시간 차이남.  
Task Scheduler 트리거가 시스템 시간 기준이므로 반드시 변경해야 함.

```powershell
# 한국 표준시로 변경
Set-TimeZone -Id "Korea Standard Time"

# 확인 (KST 현재 시각 출력되면 정상)
Get-Date
Get-TimeZone
```

---

## 5. 소프트웨어 설치

RDP로 접속한 Windows Server 내에서 실행.  
모든 명령은 **PowerShell(관리자 권한)** 에서 실행.

### 4-1. Chocolatey 패키지 매니저 설치

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
```

### 4-2. Python 3.12 설치

```powershell
choco install python312 -y
# 설치 확인
python --version  # Python 3.12.x
```

### 4-3. Node.js 20 LTS 설치

```powershell
choco install nodejs-lts -y
# 설치 확인
node --version   # v20.x.x
npm --version
```

### 4-4. Git 설치

```powershell
choco install git -y
# 설치 확인
git --version
```

### 4-5. NSSM 설치 (서비스 관리자)

FastAPI·Next.js를 Windows 서비스로 등록하기 위해 사용.

```powershell
choco install nssm -y
```

> 설치 후 PowerShell 재시작 필요 (`exit` 후 다시 열기)

---

## 6. 코드 배포

### 5-1. 저장소 클론

```powershell
mkdir C:\repo
cd C:\repo
git clone https://github.com/gigilxx/autotrader.git
cd C:\repo\autotrader
```

### 5-2. .env 파일 업로드

로컬 PC의 `.env` 파일을 서버에 복사.

**방법 A — RDP 클립보드 붙여넣기:**
1. 로컬 PC에서 `.env` 파일 내용을 복사
2. 서버에서 메모장 열기 → 붙여넣기
3. `C:\repo\autotrader\.env` 로 저장

**방법 B — PowerShell Secure Copy (로컬에서 실행):**
```powershell
# 로컬 PC PowerShell에서 실행
scp -i autotrader-key.pem .env Administrator@<Elastic IP>:C:\repo\autotrader\.env
```

### 5-3. Python 의존성 설치

```powershell
cd C:\repo\autotrader
pip install -r requirements.txt
```

### 5-4. Next.js 의존성 설치 및 빌드

```powershell
cd C:\repo\autotrader\ui\dashboard
npm install
npm run build
```

> 빌드에 1~2분 소요. `t3.micro`는 메모리 부족으로 실패할 수 있음.

---

## 7. 봇 자동 시작 — Task Scheduler 등록

### 6-1. XML 파일 경로 확인

`autotrader_task.xml` 이 이미 `C:\repo\autotrader\autotrader_task.xml`에 있음.  
동작 경로가 `C:\repo\autotrader\run.bat`으로 설정되어 있어 그대로 사용 가능.

### 6-2. 작업 등록

```powershell
schtasks /Create /XML "C:\repo\autotrader\autotrader_task.xml" /TN "AutoTraderBot" /F
```

### 6-3. 등록 확인

```powershell
schtasks /Query /TN "AutoTraderBot" /FO LIST
```

> 평일 08:50에 자동 시작, 15:30 장 마감 후 자동 종료.  
> 수동 테스트: `schtasks /Run /TN "AutoTraderBot"`

---

## 8. FastAPI 서비스 등록 (NSSM)

서버 재부팅 후에도 FastAPI가 자동으로 켜지도록 Windows 서비스로 등록.

```powershell
# 서비스 등록
nssm install AutoTraderAPI python
nssm set AutoTraderAPI AppDirectory C:\repo\autotrader
nssm set AutoTraderAPI AppParameters "-m uvicorn ui.api.main:app --host 0.0.0.0 --port 8000"
nssm set AutoTraderAPI AppEnvironmentExtra PYTHONUTF8=1
nssm set AutoTraderAPI DisplayName "AutoTrader FastAPI"
nssm set AutoTraderAPI Description "AutoTrader 봇 상태 API"
nssm set AutoTraderAPI Start SERVICE_AUTO_START

# 서비스 시작
nssm start AutoTraderAPI

# 상태 확인
nssm status AutoTraderAPI
```

---

## 9. Next.js 대시보드 서비스 등록 (NSSM)

```powershell
# npm 경로 확인 (보통 C:\Program Files\nodejs\npm.cmd)
where npm

# 서비스 등록
nssm install AutoTraderDashboard "C:\Program Files\nodejs\node.exe"
nssm set AutoTraderDashboard AppDirectory C:\repo\autotrader\ui\dashboard
nssm set AutoTraderDashboard AppParameters "node_modules\.bin\next start -p 3000"
nssm set AutoTraderDashboard DisplayName "AutoTrader Dashboard"
nssm set AutoTraderDashboard Description "AutoTrader Next.js 대시보드"
nssm set AutoTraderDashboard Start SERVICE_AUTO_START

# 서비스 시작
nssm start AutoTraderDashboard

# 상태 확인
nssm status AutoTraderDashboard
```

---

## 10. Windows 방화벽 규칙 추가

EC2 보안 그룹 외에 Windows 방화벽도 허용 필요.

```powershell
# FastAPI 포트
netsh advfirewall firewall add rule name="AutoTrader FastAPI" dir=in action=allow protocol=TCP localport=8000

# Next.js 포트
netsh advfirewall firewall add rule name="AutoTrader Dashboard" dir=in action=allow protocol=TCP localport=3000
```

---

## 11. 동작 확인

### 10-1. 서비스 상태 확인

```powershell
Get-Service AutoTraderAPI, AutoTraderDashboard
```

### 10-2. 브라우저 접속

로컬 PC 브라우저에서:

| 주소 | 용도 |
|------|------|
| `http://<Elastic IP>:3000` | 대시보드 |
| `http://<Elastic IP>:8000/status` | API 상태 확인 |
| `http://<Elastic IP>:8000/docs` | FastAPI Swagger UI |

### 10-3. 로그 위치

| 파일 | 내용 |
|------|------|
| `C:\repo\autotrader\logs\autotrader.log` | 전체 로그 |
| `C:\repo\autotrader\logs\important.log` | 주요 이벤트 (대시보드 → 주요 이벤트 탭) |
| `C:\repo\autotrader\logs\restart.log` | 봇 재시작 기록 |

---

## 12. 코드 업데이트 방법

로컬에서 수정 후 GitHub에 push → 서버에서 pull:

```powershell
cd C:\repo\autotrader

# 코드 업데이트
git pull origin master

# Python 의존성 변경된 경우
pip install -r requirements.txt

# Next.js 변경된 경우 재빌드
cd ui\dashboard
npm install
npm run build
cd C:\repo\autotrader

# 서비스 재시작
nssm restart AutoTraderAPI
nssm restart AutoTraderDashboard

# 봇은 다음 날 08:50에 자동으로 새 코드 적용됨
# 즉시 재시작하려면:
schtasks /Run /TN "AutoTraderBot"
```

---

## 13. 비용 절약 팁

| 방법 | 절약 효과 |
|------|---------|
| Reserved Instance 1년 약정 | On-Demand 대비 약 40% 절감 |
| 주말 인스턴스 중지 | 월 ~8일 절약 → 약 26% 절감 |
| t3.micro 사용 (대시보드만 필요 없을 때) | t3.small 대비 50% 절감 |

**주말 자동 중지/시작** (Lambda + EventBridge로 설정 가능, 선택사항):
- 금요일 15:35 중지, 월요일 08:40 시작

---

## 14. 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| 대시보드 접속 안 됨 | 방화벽/보안 그룹 | 9단계, 10단계 재확인 |
| FastAPI 500 에러 | `.env` 경로 오류 | `C:\repo\autotrader\.env` 존재 확인 |
| 봇이 실행 안 됨 | Task Scheduler 오류 | 이벤트 뷰어 → Windows 로그 → 시스템 확인 |
| `ModuleNotFoundError` | pip install 미완료 | `pip install -r requirements.txt` 재실행 |
| Next.js 빌드 실패 | 메모리 부족 | t3.small 이상 사용 또는 스왑 설정 |
| 서비스가 NSSM에서 안 뜸 | 경로 오류 | `nssm edit <서비스명>` 으로 GUI에서 경로 확인 |

---

## 15. 보안 체크리스트

- [ ] 보안 그룹 인바운드 규칙이 "내 IP"로만 제한되어 있는가?
- [ ] `.env` 파일이 `.gitignore`에 포함되어 있는가?
- [ ] `UI_SECRET_KEY` 환경변수가 `.env`에 설정되어 있는가? (API 인증)
- [ ] AWS 루트 계정 MFA가 활성화되어 있는가?
- [ ] RDP 접속 후 Administrator 비밀번호를 변경했는가?
