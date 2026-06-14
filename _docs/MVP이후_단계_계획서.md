# 자동매매 봇 — MVP 이후 단계 계획서
## Claude Code 실행용

---

너는 파이썬 시니어 엔지니어야.
MVP 골격(`autotrader` 패키지)은 이미 완성돼 있어.
이 문서의 태스크를 **순서대로** 구현해줘.

---

## 핵심 제약: 지금 KIS 모의 계좌가 없음

아래 두 가지로 작업을 분리한다:

| 구분 | 해당 단계 |
|---|---|
| ✅ **지금 가능** (KIS 계좌 불필요) | Phase 1·2·3·4 |
| ⏳ **계좌 생기면** (KIS 모의 계좌 필요) | Phase 5·6 |

---

## ✅ Phase 1 — 안전장치 보강 (KIS 불필요)

> `autotrader/` 패키지 내부 완성. 테스트는 mock으로 가능.

### 1-1. 상태 영속화 (SQLite)

파일: `autotrader/state_store.py` 신규 생성

저장 대상:
- `gate._trades_today`, `gate._realized_pnl_today`
- `idem._sent` (전송된 주문 ID 집합)
- `engine.local` (보유 포지션 추정)
- 기준 날짜 (`today`)

요구사항:
- SQLite (`state.db`), 테이블 3개: `daily_state`, `orders_sent`, `positions`
- `save_state(gate, idem, engine)` / `load_state(gate, idem, engine, today)` 인터페이스
- `today`가 다르면 일일 카운터만 초기화, 주문 ID는 유지
- `engine.prepare_day()` 진입 전에 `load_state()` 호출하도록 `run.py` 수정

### 1-2. 부분 체결 처리

파일: `autotrader/kis_broker.py` 수정

- `send_order()` 반환값을 `bool` → `OrderResult(ok, filled_qty, filled_price, order_no)` 로 변경
- `get_order_status(order_no)` 메서드 추가
  - ⚠️ 공식 저장소 `examples_llm/domestic_stock/inquire_ccnl/` 기반으로 구현
  - **KIS 공식 저장소 코드 반드시 확인 후 작성. 기억으로 단정 금지.**
- `engine._watch_entry()`, `engine._exit()` 에서 `filled_qty`로 `engine.local` 갱신

### 1-3. 강제청산 실패 재시도

파일: `autotrader/engine.py` 수정

- `engine._exit()` 실패 시 1초 간격으로 최대 3회 재시도
- 3회 모두 실패 시:
  - 텔레그램 긴급 알림 전송
  - 킬스위치 작동
- `force_close()` 는 특히 재시도를 철저히 — 이 실패는 오버나이트 보유로 이어짐

### 1-4. 매 사이클 잔고 대조

파일: `autotrader/run.py` 수정

- 10분마다 `reconcile(local_snapshot, broker.get_account(), kill)` 호출
- 불일치 시 킬스위치 + 텔레그램 긴급 알림

### 1-5. 이월 포지션 처리

파일: `autotrader/engine.py` 수정

- `prepare_day()` 시작 시 브로커 잔고 조회
- 보유 종목 있으면 → 즉시 강제청산 후 진행
  (당일청산 전략이므로 전일 이월 포지션은 존재하면 안 됨)

### Phase 1 완료 기준
```bash
python -m autotrader.run_tests   # 기존 18개 + 신규 테스트 모두 통과
# state.db 생성 → 프로세스 재시작 → 상태 복원 확인 (mock으로)
# 강제청산 3회 실패 시나리오 → 킬스위치 작동 확인 (mock으로)
```

---

## ✅ Phase 2 — 메인 루프 정식화 (KIS 불필요)

### 2-1. APScheduler 전환

파일: `autotrader/run.py` 전면 재작성

```python
# 스케줄 구조
08:55  →  engine.prepare_day()       # 목표가 계산
09:00  →  on_tick 루프 시작 (N초 간격)
14:30  →  신규 진입 금지 (engine 내부 시간 필터로 처리)
15:15  →  engine.force_close()
15:30  →  일일 리포트 생성 + 텔레그램 전송 + 루프 종료
```

요구사항:
- `APScheduler BackgroundScheduler` 사용
- 폴링 간격: 환경변수 `POLL_SEC`(기본 3초)로 조정 가능
- 예외가 스케줄러를 죽이지 않도록 — 모든 잡에 try/except

### 2-2. 휴장일 캘린더

파일: `autotrader/calendar.py` 신규 생성

- `is_market_day(date) → bool`
- 토·일 + 한국 공휴일 + 임시 휴장 처리
- 공휴일 데이터: `holidays` 라이브러리 (`pip install holidays`) 사용
  - `holidays.KR()`로 한국 공휴일 자동 처리
- `run.py` 시작 시 오늘이 휴장일이면 즉시 종료

### 2-3. 일일 리포트

파일: `autotrader/report.py` 신규 생성

- 당일 거래 내역(진입·청산 시각·가격·수량·손익) 집계
- 총 실현손익, 거래횟수, 승률 계산
- 텔레그램으로 전송 (마감 후 15:30)

### Phase 2 완료 기준
```bash
# FakeMarketData + FakeBroker로 하루 시뮬레이션 전체 실행
# 08:55~15:30 스케줄이 정확히 작동하는지 로그로 확인
# 토요일/공휴일에 실행 시 즉시 종료되는지 확인
```

---

## ✅ Phase 3 — 백테스트 (KIS 불필요)

> KIS 대신 **무료 데이터 소스**로 과거 일봉 수집.

파일: `backtest/` 디렉터리 신규 생성

### 3-1. 데이터 수집

`backtest/data_loader.py`

- `pykrx` 라이브러리 사용 (`pip install pykrx`)
  - 한국거래소 공식 데이터, 무료, KIS 계좌 불필요
- `get_daily_ohlcv(symbol, start, end) → pd.DataFrame`
- 컬럼: `date, open, high, low, close, volume`

### 3-2. 백테스트 엔진

`backtest/engine.py`

- 변동성 돌파 전략 (`compute_target_price` — 기존 코드 재사용)
- `costs.net_pnl` 연결 — **수수료·세금 포함 손익 계산 필수**
- 파라미터: k값, 손절%, 기간
- 출력: 거래 내역 DataFrame + 성과 지표

### 3-3. 성과 지표

`backtest/metrics.py`

- 승률, 평균이익, 평균손실, 손익비
- 기대값 = 승률 × 평균이익 − 패율 × 평균손실
- MDD (최대낙폭)
- 수익팩터 (총이익 / 총손실, 1 이상이면 합격선)
- **비용 포함/제외 두 가지로 출력** (비용 영향 확인용)

### 3-4. k값 최적화

`backtest/optimize.py`

- k = 0.3, 0.4, 0.5, 0.6, 0.7 그리드 탐색
- 종목별·기간별 성과 비교 테이블 출력
- ⚠️ 과최적화 주의 — in-sample/out-of-sample 분리 필수
  (예: 2023~2024 학습, 2025 검증)

### 3-5. 대상 종목 선정

`backtest/screener.py`

- 코스피200 종목 중 백테스트 성과 기준 선별
- 기준: 수익팩터 > 1.2, 평균 거래량 상위, MDD < 15%
- 최종 watchlist 출력

### Phase 3 완료 기준
```
# 삼성전자(005930) 2023~2025 백테스트 리포트 출력
# 비용 포함 기대값이 + 인 k값 확인
# watchlist 종목 3~5개 선정
```

---

## ✅ Phase 4 — UI (KIS 불필요)

### 4-1. FastAPI 백엔드

파일: `ui/api/main.py`

SQLite(`state.db`)를 읽어 아래 엔드포인트 제공:

```
GET  /status          → 봇 상태(실행중·정지·킬스위치 여부)
GET  /positions       → 현재 보유 포지션
GET  /pnl/today       → 오늘 실현손익·거래횟수·남은 한도
GET  /trades          → 오늘 거래 내역 리스트
GET  /logs?n=50       → 최근 로그 N개
POST /kill            → 킬스위치 작동 (인증 필요)
POST /resume          → 킬스위치 해제 (인증 필요)
WS   /ws/status       → 상태 실시간 스트림 (10초 간격 push)
```

요구사항:
- `FastAPI` + `uvicorn`
- `/kill`, `/resume` 는 `Authorization: Bearer {SECRET_KEY}` 헤더 인증
- `SECRET_KEY` 는 환경변수로 관리
- 봇 프로세스와 **별도 프로세스**로 실행 (SQLite 공유)
- CORS 설정 (Next.js 개발 서버 허용)

### 4-2. Telegram 제어 봇

파일: `autotrader/telegram_control.py`

기존 `TelegramAlertSender`에 명령어 수신 기능 추가:

```
/status   → 현재 상태·포지션·손익 요약
/kill     → 킬스위치 작동
/resume   → 킬스위치 해제
/trades   → 오늘 거래 내역
/help     → 명령어 목록
```

요구사항:
- `python-telegram-bot` 라이브러리
- 등록된 `TELEGRAM_CHAT_ID` 외 다른 사용자 명령 무시
- `/kill` 은 확인 메시지("정말 킬스위치를 작동할까요? /confirm_kill") 후 실행

### 4-3. Next.js 대시보드

디렉터리: `ui/dashboard/` (Next.js 15 + TypeScript + Tailwind)

화면 구성:

**메인 대시보드 (`/`)**
- 봇 상태 배지 (실행중 🟢 / 정지 🔴 / 킬스위치 ⛔)
- 오늘 손익 (원, %)
- 거래 횟수 / 남은 한도
- 현재 포지션 카드 (종목·수량·진입가·평가손익)
- 킬스위치 / 재개 버튼 (확인 다이얼로그)

**거래 내역 (`/trades`)**
- 오늘 거래 테이블 (시각·종목·진입가·청산가·손익·사유)

**로그 (`/logs`)**
- 실시간 로그 뷰어 (WebSocket 연결)

**백테스트 결과 (`/backtest`)**
- 성과 지표 테이블
- k값별 비교 차트 (recharts)

요구사항:
- FastAPI `/ws/status` WebSocket으로 상태 실시간 갱신
- 모바일 반응형 (폰에서도 킬스위치 버튼 누를 수 있게)
- 킬스위치 버튼 — 실수 방지 확인 다이얼로그 필수
- Vercel 배포 가능한 구조 (`NEXT_PUBLIC_API_URL` 환경변수)

---

## ⏳ Phase 5 — KIS 연결 검증 (모의 계좌 생기면)

> 이 단계는 모의 계좌 발급 후 진행.

### 5-1. `# VERIFY` 응답 필드 확정

`kis_broker.py` 내 `# VERIFY` 주석 항목들:
- `get_quote()`: `stck_prpr / stck_oprc / stck_hgpr / stck_lwpr`
- `get_daily_bars()`: `stck_bsop_date / stck_clpr`, 정렬 방향
- `get_account()`: `dnca_tot_amt / hldg_qty / pchs_avg_pric`
- `ORD_DVSN` 시장가 코드 확인

방법: 모의 계좌로 각 API 한 번씩 호출 → 실제 응답 JSON 출력 → 필드 확정

### 5-2. WebSocket 실시간 체결가

`market_data.py`에 `WebSocketMarketData` 클래스 추가
- 공식 저장소 `examples_llm/auth/auth_ws_token/` 기반
- 연결 끊김 자동 재연결
- `engine.on_tick`을 폴링 → 콜백 기반 전환

---

## ⏳ Phase 6 — 모의투자 장기 검증

> 실전 진입 전 게이트. 통과 못 하면 실전 절대 금지.

- 최소 **4주** 모의 가동
- 매일 로그 리뷰
- 체크리스트:
  - [ ] 치명 버그 0건 (잘못된 주문, 손절 미작동)
  - [ ] 강제청산 매일 정상 작동
  - [ ] 리스크 규칙 단 한 번도 안 뚫림
  - [ ] 상태 영속화 — 재시작 후 카운터 정상 복원
  - [ ] 잔고 대조 불일치 0건
  - [ ] 백테스트 대비 실제 슬리피지 허용 범위 내

---

## 작업 규칙

- **KIS API 관련 코드는 공식 저장소 기준으로. 기억 단정 금지.**
- **확신 없는 부분은 `# VERIFY` / `# TODO` 명시.**
- **매 Phase 완료 후 `python -m autotrader.run_tests` 통과 유지.**
- **모든 외부 호출에 try/except — 예외가 봇을 죽이면 안 됨.**
- **모의→실전 전환은 `KIS_ENV=real` 환경변수 하나로만.**
- **UI의 킬스위치 버튼은 반드시 확인 다이얼로그 포함.**

---

## 환경변수 전체 목록

```bash
# KIS
KIS_APPKEY=...
KIS_APPSECRET=...
KIS_CANO=12345678
KIS_ACNT_PRDT_CD=01
KIS_ENV=mock              # 모의(mock) | 실전(real)

# Telegram
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...

# UI
UI_SECRET_KEY=...         # FastAPI 인증 키
NEXT_PUBLIC_API_URL=...   # Next.js → FastAPI URL

# 봇 설정
POLL_SEC=3                # 시세 폴링 간격(초)
```

---

## 디렉터리 구조 (최종 목표)

```
autotrader/          ← 봇 엔진 (기존)
  state_store.py     ← Phase 1 신규
  telegram_control.py← Phase 4 신규
  calendar.py        ← Phase 2 신규
  report.py          ← Phase 2 신규

backtest/            ← Phase 3 신규
  data_loader.py
  engine.py
  metrics.py
  optimize.py
  screener.py

ui/
  api/               ← Phase 4 신규 (FastAPI)
    main.py
  dashboard/         ← Phase 4 신규 (Next.js)
    app/
    components/

state.db             ← 런타임 생성
```

---

## 모델 전략

세션 시작 직후 실행:
```
/model opusplan
```

Phase 1(안전장치)·Phase 5(KIS 검증)는 **plan mode에서 설계 먼저**, 그다음 실행.
나머지는 Sonnet이 자동 처리.

---

## 우선순위 요약

```
지금 바로:  Phase 1 → Phase 2 → Phase 3 → Phase 4
계좌 생기면: Phase 5 → Phase 6
Phase 6 통과 후에만: 실전 (극소액부터)
```
