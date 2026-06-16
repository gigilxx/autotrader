# AutoTrader — Claude 작업 가이드

## 프로젝트 개요

한국투자증권(KIS) Open API를 사용하는 변동성 돌파 전략 자동매매 봇.
모의투자(`KIS_ENV=mock`) 기본, 환경변수 하나로 실전 전환.

---

## 프로세스 구조 (3개 별도 프로세스)

```
autotrader/run.py          — 메인 봇 (APScheduler BlockingScheduler, 단일 스레드)
ui/api/main.py             — FastAPI 백엔드 (uvicorn)
autotrader/telegram_control.py — 텔레그램 제어 봇 (별도 실행)
```

세 프로세스는 **`state.db` (SQLite WAL)** 를 공유하며 통신한다.
- `control_flags` 테이블: 봇에 보내는 신호 (kill, resume, watchlist_override, k_value, force_entry_{sym}, force_close_{sym} 등)
- `positions`, `daily_state`, `trades`, `sent_orders` 테이블: 봇이 기록, API가 읽음

---

## 핵심 실행 흐름

```
08:55  prepare_day()     목표가 계산, 포지션 동기화, 시장 필터
09:00  on_tick() 2초마다  현재가 폴링 → 돌파 감지 → 진입
15:15  force_close()     미청산 강제 청산
15:30  daily_report()    일일 리포트 후 종료
```

`on_tick()` 내부 순서:
1. `apply_runtime_flags()` — DB에서 제어 신호 읽어 상태 갱신
2. 병렬 현재가 조회 (`ThreadPoolExecutor(max_workers=min(N,2))`)
3. 각 종목 `_watch_entry()` / `_manage_position()`

---

## 핵심 제약 (수정 시 반드시 고려)

| 항목 | 값 | 이유 |
|---|---|---|
| KIS 모의 rate limit | 0.5초/콜 | `_throttle()` lock 안에서 sleep → 사실상 직렬 |
| KIS 실전 rate limit | 0.05초/콜 | |
| `POLL_INTERVAL_SEC` | 기본 2초 | `run.py:46` `os.getenv("POLL_SEC","2")` |
| 모의 종목 상한 | **4개** | 2초 ÷ 0.5초/콜 = 4콜 |
| `max_workers` | `min(N,2)` | rate limit 대비 |
| `BlockingScheduler` | 단일 스레드 | 잡 간 race condition 없음 |

---

## 주요 파일 맵

```
autotrader/
  run.py              진입점, 스케줄러, build_engine()
  engine.py           TradingEngine — on_tick, prepare_day, apply_runtime_flags
  config.py           AppConfig / RiskConfig / CostConfig / StrategyConfig
  kis_broker.py       KIS API 래퍼, credentials_from_env(), _throttle()
  market_data.py      get_quote(), get_prev_day_bar(), get_daily_bars()
  market_filter.py    KODEX200 이동평균 시장 필터
  execution.py        OrderRouter.place() — 리스크 게이트 + 주문 전송
  risk_gate.py        RiskGate — 한도/킬스위치 체크
  state.py            StateManager — SQLite 읽기/쓰기
  volatility_breakout.py  BreakoutDetector, compute_target_price()
  telegram_control.py 텔레그램 명령어 처리
  alerts.py           텔레그램/콘솔 알림 전송
  reconciliation.py   잔고 대조, IdempotencyGuard

ui/
  api/main.py         FastAPI 엔드포인트
  dashboard/
    lib/api.ts        프론트 API 클라이언트
    app/              Next.js 페이지 (page.tsx, watchlist/, logs/, trades/, events/, backtest/)
    components/       재사용 컴포넌트 (KillSwitchButton, MarketFilterCard, KValuePanel 등)
```

---

## 실행 명령

```bash
# 봇
python -m autotrader.run

# FastAPI (별도 터미널)
uvicorn ui.api.main:app --host 0.0.0.0 --port 8000 --reload

# 텔레그램 봇 (별도 터미널)
python -m autotrader.telegram_control

# 테스트
python -m pytest autotrader/tests.py -v

# 프론트엔드
cd ui/dashboard && npm run dev

# 종목 마스터 생성 (pykrx 필요, 로컬 실행)
pip install pykrx
python scripts/build_stock_master.py
```

---

## 환경변수 (`.env`)

```ini
KIS_APPKEY=
KIS_APPSECRET=
KIS_CANO=
KIS_ACNT_PRDT_CD=01
KIS_ENV=mock              # mock | real
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
POLL_SEC=2
STATE_DB=state.db
LOG_FILE=logs/autotrader.log
IMPORTANT_LOG=logs/important.log
UI_SECRET_KEY=            # 비우면 인증 생략 (개발용)
# WATCHLIST= 은 UI/텔레그램으로 관리 — .env에 두지 않음
```

---

## 코딩 규칙

- `state.py` 예외: `except Exception: pass` 금지 → `logger.error` (쓰기) / `logger.warning` (읽기)
- `control_flags` 쓰기: `StateManager.set_control_flag()` 사용 (직접 SQL 금지)
- `engine.py` 수정 시: `apply_runtime_flags()` 흐름과 `_target_bases` dict 영향 반드시 확인
- WAL: 세 프로세스 모두 `PRAGMA journal_mode=WAL` 필수 (현재 `state.py` 미적용 — T1 미완)
- 새 `control_flags` 플래그 추가 시: `apply_runtime_flags()` + FastAPI 엔드포인트 + 텔레그램 핸들러 세 곳 동시 처리

---

## 미완료 태스크 (작업 큐)

우선순위와 의존성은 `_docs/` 문서를 참조.

| ID | 내용 | 핵심 파일 | 우선순위 |
|---|---|---|---|
| ~~T1~~ | ~~`state.py` WAL + pass→log (R-3, O-6, 리팩②③)~~ | ~~`state.py`~~ | ✅ 완료 |
| ~~T2~~ | ~~`config.py` env MOCK 고정 + 타입 None (O-1, 리팩⑥)~~ | ~~`config.py`~~ | ✅ 완료 |
| ~~T3~~ | ~~일봉 정렬 방향 통일 (B-5, 리팩⑪)~~ | ~~`kis_broker.py`, `market_filter.py`~~ | ✅ 완료 |
| ~~T4~~ | ~~`engine.py` 버그 수정 (B-1 force_entry 미체결, B-2 pnl 체결가, 리팩① get_account 이중, S-4 시간제한)~~ | ~~`engine.py`, `execution.py`~~ | ✅ 완료 |
| ~~T5~~ | ~~BreakoutDetector 캡슐화 (S-1 직접접근→메서드, S-2 데드코드)~~ | ~~`volatility_breakout.py`, `engine.py`~~ | ✅ 완료 |
| ~~T6~~ | ~~`api/main.py` 정리 (U-2 빈watchlist, I-1 resume경쟁, 리팩④ SQL복사, 리팩⑫ 중복DB조회)~~ | ~~`ui/api/main.py`~~ | ✅ 완료 |
| ~~T7~~ | ~~기타 소항목 (B-3 cash_tolerance 상수화, O-5 토큰경로, 리팩⑤ force_close_time 하드코딩)~~ | ~~`engine.py`, `kis_broker.py`, `run.py`~~ | ✅ 완료 (E-2 체결실패는 T4에서 처리됨) |
| ~~T8~~ | ~~텔레그램 리팩 (리팩⑩ if-elif→dict, 리팩③ StateManager 전환)~~ | ~~`telegram_control.py`~~ | ✅ 완료 |
| T9 | 관심종목 Part1 — DB 우선 전환, 005930 fallback 제거 | `run.py`, `telegram_control.py`, `api/main.py`, `.env.example` | 🟠 중요 |
| T10 | 관심종목 기능A — 종목 수 제한 + 포지션 보유 확인 후 제거 | `api/main.py`, `api.ts`, `watchlist/page.tsx`, `telegram_control.py` | 🟠 중요 |
| T11 | 종목 마스터 JSON 생성 ⚠️로컬 pykrx 실행 필요 | `scripts/build_stock_master.py`, `data/stock_master.json` | 🟠 중요 |
| T12 | 관심종목 기능B — 자동완성 + 종목명 표시 | `api/main.py`, `StockAutocomplete.tsx`, `watchlist/page.tsx`, `api.ts` | 🟠 중요 |
| T13 | 목표가 계산 시점 분리 (S-3, 08:55→09:05) | `run.py`, `engine.py` | 🟡 보통 |
| T14 | U-3 SECRET 노출 — Next.js API Route 도입 | 구조 변경 필요, 별도 논의 | 🟡 보통 |
| T15 | `engine.py` 함수 분리 리팩 (리팩⑧ _watch_entry 68줄, 리팩⑨ apply_runtime_flags 80줄) | `engine.py` | 🟡 보통 |
| T16 | `prepare_day()` API 호출 최적화 (리팩⑦ 종목당 2번→1번) ⚠️KIS 응답 필드 확인 필요 | `engine.py`, `market_data.py`, `kis_broker.py` | 🟡 보통 |
| T17 | `_conn()/_db()` 통합 — `api/main.py` 에서도 StateManager 사용 (리팩③ 후속) | `ui/api/main.py`, `autotrader/state.py` | 🟡 보통 |

**병렬 수행 가능**: T1, T2, T5, T7, T8, T15, T16 (서로 다른 파일, 의존성 없음)  
**순서 의존**: T6 → T9 → T10 → (T11 병렬 가능) → T12  
**T4 이후 권장**: T15 (같은 파일 engine.py 충돌 방지)  
**T8 이후 권장**: T17 (telegram StateManager 전환이 T8에 포함)

---

## 참고 문서 (`_docs/`)

- `코드_전수조사_결과.md` — 버그/보안/전략 17개 항목
- `리팩토링_조사_결과.md` — 성능/구조 12개 항목
- `관심종목_UI개선_구현계획.md` — watchlist 전환 + 자동완성 구현 계획
- `KIS계좌발급후_작업절차.md` — 초기 설정 가이드
