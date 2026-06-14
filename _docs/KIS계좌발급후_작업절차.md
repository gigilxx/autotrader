# KIS 모의 계좌 발급 후 작업 절차

> 이 문서는 KIS(한국투자증권) 모의투자 계좌를 발급받은 직후부터  
> 실전 전환 전까지 해야 할 모든 작업을 순서대로 기술한다.  
> 각 단계를 **완료 후 다음 단계로 진행**하고, 체크박스를 채운다.

---

## 0단계: 사전 준비 (발급 직후)

### 0-1. 앱키 발급

1. [KIS Developers](https://apiportal.koreainvestment.com/) 접속
2. **모의투자** 앱 등록 → AppKey / AppSecret 발급
   - 실전 앱키와 **별도**로 모의 앱키를 발급해야 함
3. 계좌번호 확인
   - `CANO`: 종합계좌번호 앞 8자리
   - `ACNT_PRDT_CD`: 뒤 2자리 (보통 `01`)

### 0-2. `.env` 파일 작성

프로젝트 루트 `D:\source\autotrader\` 에서:

```bash
copy .env.example .env
```

`.env` 파일 열어 아래 항목 채우기:

```env
KIS_APPKEY=발급받은_모의_AppKey
KIS_APPSECRET=발급받은_모의_AppSecret
KIS_CANO=12345678          # 계좌번호 앞 8자리
KIS_ACNT_PRDT_CD=01        # 계좌상품코드 (보통 01)
KIS_ENV=mock               # 반드시 mock으로 시작
WATCHLIST=005930           # 삼성전자로 먼저 테스트
POLL_SEC=3
TELEGRAM_TOKEN=            # 선택 (없으면 콘솔 출력)
TELEGRAM_CHAT_ID=          # 선택
```

> ⚠️ `.env` 파일은 절대 Git에 커밋하지 않는다 (`.gitignore`에 포함돼 있음).

---

## 1단계: KIS API 응답 필드 검증 (Phase 5-1)

### 목적

`kis_broker.py` 곳곳에 `# VERIFY` / `# ⚠️` 주석이 달린 필드들을 실제 모의 계좌 응답으로 확인한다.  
KIS는 사양을 예고 없이 바꾸므로, **운용 전 반드시 직접 확인**해야 한다.

### 1-1. 검증 스크립트 실행

프로젝트 루트에서:

```bash
python -m autotrader.run_tests
```

결과: `31 passed, 0 failed` 확인 ← 아직 KIS 호출 없음, mock 테스트만

### 1-2. KIS API 실응답 직접 확인

아래 임시 스크립트를 `verify_kis.py`로 작성해 실행한다 (확인 후 삭제):

```python
# verify_kis.py — 확인 후 삭제
import json
from dotenv import load_dotenv
load_dotenv()

from autotrader.kis_broker import KISBroker, credentials_from_env

broker = KISBroker(credentials_from_env())

# ── 1) 현재가 조회
print("=== 현재가 (005930 삼성전자) ===")
q = broker.get_quote("005930")
print(f"  현재가: {q.price:,}원")
print(f"  시가: {q.open:,}  고가: {q.high:,}  저가: {q.low:,}")

# ── 2) 일봉 조회
print("\n=== 일봉 (최근 3개) ===")
bars = broker.get_daily_bars("005930")[:3]
for b in bars:
    print(f"  {b.date}  O={b.open:,}  H={b.high:,}  L={b.low:,}  C={b.close:,}  V={b.volume:,}")

# ── 3) 잔고 조회
print("\n=== 계좌 잔고 ===")
acct = broker.get_account()
print(f"  예수금: {acct.cash:,}원")
print(f"  보유 종목 수: {acct.position_count()}")
for sym, pos in acct.positions.items():
    print(f"    [{sym}] {pos.qty}주 @ {pos.avg_price:,}원")

print("\n모든 필드 정상이면 Phase 5-1 완료.")
```

```bash
python verify_kis.py
```

### 1-3. 검증 항목 체크리스트

| 항목 | 확인 방법 | 체크 |
|---|---|---|
| `stck_prpr` (현재가) | `q.price` 값이 실제 주가와 일치 | [ ] |
| `stck_oprc / hgpr / lwpr` (시가·고가·저가) | `q.open / high / low` 합리적 값 | [ ] |
| `stck_bsop_date` (일봉 날짜) | `bars[0].date`가 가장 최근 거래일 | [ ] |
| `stck_clpr` (종가) | `bars[0].close`가 실제 종가와 일치 | [ ] |
| `acml_vol` (거래량) | `bars[0].volume > 0` | [ ] |
| `dnca_tot_amt` (예수금) | `acct.cash`가 실제 모의 예수금과 일치 | [ ] |
| 일봉 정렬 방향 | `bars[0].date` > `bars[1].date` (최신 우선) | [ ] |

### 1-4. 체결 조회 필드 검증 (`tot_ccld_qty`, `avg_prvs`)

실제 모의 주문을 한 건 넣은 후 `get_order_fill()`이 정상 동작하는지 확인한다.  
이 항목은 **2단계(수동 주문 테스트)** 이후에 확인 가능하다.

---

## 2단계: 수동 주문 테스트

### 목적

`kis_broker.send_order()`가 실제로 모의 주문을 넣고 ODNO를 반환하는지 확인한다.

### 2-1. 수동 주문 스크립트

```python
# test_order.py — 확인 후 삭제
from dotenv import load_dotenv
load_dotenv()

from autotrader.kis_broker import KISBroker, credentials_from_env
from autotrader.models import OrderRequest, Side

broker = KISBroker(credentials_from_env())

# 삼성전자 1주 지정가 매수 (낮은 가격으로 미체결 상태 유지)
order = OrderRequest(
    symbol="005930",
    side=Side.BUY,
    qty=1,
    price=10_000,       # 매우 낮은 가격 → 미체결 예상
    client_order_id="test:buy:20260101T0900:manual",
    reason="test",
)

odno = broker.send_order(order)
print(f"주문번호(ODNO): {odno!r}")

if odno:
    fill = broker.get_order_fill(odno, "005930")
    print(f"체결수량: {fill.filled_qty}  평균가: {fill.avg_price}  상태: {fill.status}")
    print("✓ get_order_fill 정상 동작")
else:
    print("⚠️ ODNO 비어 있음 — send_order 응답 필드 확인 필요")
```

```bash
python test_order.py
```

### 2-2. 확인 사항

| 항목 | 기대값 | 체크 |
|---|---|---|
| `odno` | 빈 문자열이 아닌 숫자 문자열 | [ ] |
| `fill.status` | `"pending"` (낮은 가격 → 미체결) | [ ] |
| `kis_broker.py` 의 `data["output"]["ODNO"]` 키 | 실제 응답 JSON으로 확인 | [ ] |

> 만약 ODNO가 비어 있으면 `kis_broker.py`의 `send_order()` 마지막 줄  
> `return data.get("output", {}).get("ODNO", "")` 에서 키 이름을 실제 응답 JSON으로 수정한다.

### 2-3. 주문 취소 (잔류 주문 제거)

테스트 후 KIS 모의투자 앱/웹에서 미체결 주문을 수동으로 취소한다.

---

## 3단계: 봇 엔진 모의 실행

### 목적

실제 스케줄러가 장중에 정상 작동하는지 하루 동안 관찰한다.

### 3-1. 로그 설정 확인

`logs/` 폴더가 자동 생성되고 `logs/autotrader.log`에 기록되는지 확인한다.

### 3-2. 수동 실행 (처음 1~2일은 터미널에서 직접)

```bash
# 터미널에서 직접 실행 (장중 08:50~15:35)
python -m autotrader.run
```

### 3-3. 장중 모니터링 로그 확인 사항

| 시각 | 기대 로그 | 체크 |
|---|---|---|
| 08:55 | `=== 거래일 시작 ===`, 목표가 계산 로그 | [ ] |
| 09:00~ | `시세 실패` 없이 틱 폴링 진행 | [ ] |
| 돌파 시 | `진입 시도 005930 qty=N → True` | [ ] |
| 체결 후 | `진입 005930 N주 @ X,XXX원` 알림 | [ ] |
| 손절 or 15:15 | `청산 005930 N주 @ X,XXX원` 알림 | [ ] |
| 15:30 | `=== 일일 리포트 ===`, 스케줄러 종료 | [ ] |

### 3-4. 체결 조회 VERIFY 완료

진입/청산이 한 번이라도 발생하면:

- `logs/autotrader.log`에서 `부분 체결` 경고 없는지 확인
- `state.db`의 `trades` 테이블에 거래 기록이 쌓이는지 확인:

```bash
python -c "
import sqlite3
cx = sqlite3.connect('state.db')
for r in cx.execute('SELECT * FROM trades'): print(dict(r))
"
```

### 3-5. `# VERIFY` 주석 제거

`kis_broker.py` 실응답으로 모든 필드가 확인되면 해당 `# VERIFY` 주석을 삭제한다.

---

## 4단계: WebSocket 실시간 시세 (Phase 5-2, 선택)

> REST 폴링(현행 3초)으로도 충분하면 이 단계를 건너뛰어도 된다.  
> 폴링으로 4주 무사고를 달성하는 것이 우선이다.

### 4-1. KIS WebSocket 공식 문서 확인

KIS Developers → WebSocket 인증 가이드 → `ws_approval_key` 발급 방법 확인  
공식 저장소: `examples_llm/auth/auth_ws_token/` 참고

### 4-2. `market_data.py`에 `WebSocketMarketData` 추가

```python
# market_data.py 에 추가할 클래스 골격 (실제 구현은 공식 문서 기준으로)
class WebSocketMarketData:
    """WebSocket 실시간 체결가. 연결 끊김 시 자동 재연결."""
    # VERIFY: ws_url, subscribe message 형식, 종목 구독 방식
    # 공식 저장소 examples_llm/auth/auth_ws_token/ 참고
    ...
```

### 4-3. `run.py` 전환

`KISMarketData` → `WebSocketMarketData`로 교체 후 `tick_job`의 `interval` 제거  
(콜백 기반이 되면 폴링 잡 불필요)

---

## 5단계: Task Scheduler 등록 (무인 자동 실행)

### 목적

매일 아침 08:50에 자동으로 봇이 시작되도록 Windows에 등록한다.

### 5-1. 등록

관리자 권한 없이 실행 가능:

```bash
setup_task.bat
```

### 5-2. 등록 확인

```bash
schtasks /query /tn "AutoTrader" /fo LIST
```

### 5-3. 수동 트리거 테스트

```bash
schtasks /run /tn "AutoTrader"
```

`logs/autotrader.log` 에 로그가 찍히는지 확인한다.

### 5-4. 주의 사항

- PC가 꺼져 있으면 스케줄이 실행되지 않는다 → 장중 PC가 켜져 있어야 함
- 슬립/절전 방지: 제어판 → 전원 관리 → 절전 안 함 설정

---

## 6단계: UI 서버 실행 (선택)

### 6-1. FastAPI 백엔드

```bash
# 봇 프로세스와 별도 터미널에서
pip install fastapi uvicorn
uvicorn ui.api.main:app --host 0.0.0.0 --port 8000
```

`.env`에 추가:
```env
UI_SECRET_KEY=임의의강한비밀키   # POST /kill /resume 보호
```

### 6-2. Next.js 대시보드

```bash
cd ui/dashboard
cp .env.local.example .env.local
# .env.local 편집: NEXT_PUBLIC_API_URL, NEXT_PUBLIC_API_SECRET 설정
npm install
npm run dev    # 개발: http://localhost:3000
npm run build && npm start  # 배포
```

### 6-3. Telegram 제어 봇 (선택)

```bash
pip install python-telegram-bot
# .env에 TELEGRAM_TOKEN, TELEGRAM_CHAT_ID 설정 후
python -m autotrader.telegram_control
```

지원 명령어: `/status`, `/kill` (확인 단계 포함), `/resume`, `/trades`, `/help`

---

## 7단계: 4주 모의 운용 (Phase 6) — 실전 전환 게이트

> 이 체크리스트를 **전부 통과해야만** 실전 전환이 가능하다.  
> 하나라도 실패하면 원인을 찾아 수정 후 카운터를 0으로 리셋한다.

### 운용 기간: 최소 4주 (20 거래일)

시작일: ____________  
목표 완료일: ____________

### 일별 점검 체크리스트 (매일 15:35 이후 확인)

```
날짜: ____-__-__
[ ] 봇이 08:55~15:30 정상 실행됨
[ ] 치명 버그 없음 (잘못된 주문, 손절 미작동)
[ ] 강제청산 (15:15) 정상 작동
[ ] 재시작 후 카운터 정상 복원 (state.db 확인)
[ ] 잔고 대조 불일치 없음 (로그에 "잔고 불일치" 없음)
[ ] 일일 리포트 수신 확인
메모:
```

### 4주 완료 기준

| 기준 | 달성 여부 |
|---|---|
| 치명 버그 0건 (잘못된 주문, 손절 미작동) | [ ] |
| 강제청산 매일 정상 작동 (20/20 거래일) | [ ] |
| 리스크 규칙 단 한 번도 뚫리지 않음 | [ ] |
| 재시작 후 상태 복원 정상 (최소 3회 검증) | [ ] |
| 잔고 대조 불일치 0건 | [ ] |
| 슬리피지가 백테스트 대비 ±0.3% 이내 | [ ] |

---

## 8단계: 실전 전환

> **7단계 체크리스트 전부 통과 후에만 진행**

### 8-1. 실전 앱키 발급

KIS Developers → **실전투자** 앱 등록 → 별도 AppKey / AppSecret 발급

### 8-2. `.env` 수정 (단 2줄만 바꾼다)

```env
KIS_APPKEY=실전_AppKey       # 모의 앱키에서 교체
KIS_APPSECRET=실전_AppSecret  # 모의 시크릿에서 교체
KIS_ENV=real                  # mock → real 변경
```

> ✅ 코드는 **한 줄도 바꾸지 않는다.** `KIS_ENV=real` 하나로만 전환된다.

### 8-3. 실전 주의 사항

- 첫 1~2주는 **극소액**으로 시작 (WATCHLIST=005930, 자본 50만원 이하 권장)
- `RiskConfig` 재확인:
  ```python
  # config.py 기본값 — 필요 시 .env 또는 코드로 조정
  daily_max_loss_pct=0.03   # 일일 최대손실 -3%
  max_trades_per_day=3       # 1일 최대 진입 3회
  max_concurrent_positions=1 # 동시 보유 1종목
  ```
- 실전 수수료/세금 재확인:
  ```python
  # config.py CostConfig
  sell_tax_rate=0.0020       # 2026년 기준 0.20% (변동 가능)
  brokerage_fee_rate=0.00015  # 계좌별 상이 — 실제 수수료 확인
  ```
- **킬스위치를 언제든 수동으로 누를 준비**가 돼 있어야 함
  - Telegram: `/kill` → `/confirm_kill`
  - 대시보드: ⛔ 킬스위치 버튼

---

## 빠른 참조: 주요 명령어

```bash
# 테스트 실행
python -m autotrader.run_tests

# 봇 수동 실행
python -m autotrader.run

# 백테스트 (pykrx, KIS 불필요)
python -m backtest.optimize --symbol 005930 --start 20230101 --end 20241231

# KOSPI200 종목 선별
python -m backtest.screener --start 20230101 --end 20241231 --top 5

# KIS 기반 백테스트 (계좌 필요)
python -m autotrader.backtest --symbol 005930 --k 0.3,0.5,0.7

# FastAPI 서버
uvicorn ui.api.main:app --host 0.0.0.0 --port 8000

# Telegram 봇
python -m autotrader.telegram_control

# Task Scheduler 등록
setup_task.bat

# state.db 빠른 조회
python -c "import sqlite3; cx=sqlite3.connect('state.db'); [print(dict(r)) for r in cx.execute('SELECT * FROM trades ORDER BY id DESC LIMIT 5')]"
```

---

## 트러블슈팅

### "KISError: 환경변수 누락"
→ `.env` 파일이 프로젝트 루트에 있는지, `KIS_APPKEY` 등 4개 필드가 채워져 있는지 확인

### "토큰 발급 실패: 401"
→ AppKey/AppSecret이 **모의** 계좌용인지 확인 (실전 키로 모의 서버 접근 불가)

### "체결 수량 0 — 진입 취소"
→ `wait_for_fill()` 3초 이내 미체결. 정상 동작.  
모의 체결이 느릴 수 있음 — `kis_broker.py`의 `wait_for_fill(max_wait=5.0)` 으로 늘릴 수 있음

### "잔고 대조 불일치"
→ 즉시 킬스위치 → 로그 확인 → `state.db positions` 테이블과 실제 잔고 비교  
원인 파악 후 `positions` 테이블 수동 보정 가능:
```bash
python -c "import sqlite3; cx=sqlite3.connect('state.db'); cx.execute('DELETE FROM positions WHERE date=?', ('20260115',)); cx.commit()"
```

### "ODNO 비어 있음"
→ `kis_broker.py`의 `send_order()` 마지막 줄 키 이름 확인  
응답 JSON을 출력해 실제 ODNO 필드명 확인:
```python
data = broker._post("/uapi/domestic-stock/v1/trading/order-cash", tr_id, body)
print(json.dumps(data, ensure_ascii=False, indent=2))
```

---

> 작성일: 2026-06-14  
> 관련 코드: `D:\source\autotrader\` (GitHub: gigilxx/autotrader)
