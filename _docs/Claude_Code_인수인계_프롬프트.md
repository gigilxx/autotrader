# Claude Code 인수인계 프롬프트
## 한국 주식 자동매매 봇 — 골격 기반 완성 요청

---

너는 파이썬 시니어 엔지니어야.
첨부된 `autotrader` 패키지는 검증된 골격이다.
**이 골격을 토대로 무인 실거래 가능한 수준으로 완성**해줘.

---

## 프로젝트 맥락

- 용도: 개인용 한국 주식 자동매매 봇 (모의투자 먼저, 실전은 나중)
- 전략: **변동성 돌파 당일청산**
  - 목표가 = 당일 시가 + k × (전일 고가 − 전일 저가), k=0.5
  - 현재가가 목표가를 위로 돌파하는 첫 순간 매수
  - 손절(-2%) 도달 시 즉시 매도, 15:15 미청산분 강제청산
- 증권사: 한국투자증권(KIS) Open API — 모의투자 기본
- 운용: **완전 무인(장중에 아무도 못 봄)** — 서버에서 24시간 실행
- 자금: 200~300만원

---

## 이미 완성된 것 (건드리지 마)

`CLAUDE_CODE_HANDOFF.md` 에 전체 목록 있음. 요약:
- 리스크 게이트 / 포지션 사이징 / 변동성 돌파 감지 / 킬스위치 / 자동정지
- 잔고 대조 + 멱등성(중복주문 방지)
- 주문 파이프라인 (`OrderRouter`)
- KIS 실연동 (`KISBroker`): 토큰·현재가·일봉·잔고·현금주문
- 시세 인터페이스 (`MarketData`) + 메인 엔진 (`TradingEngine`) + 실행 골격 (`run.py`)
- 단위 테스트 18개, 엔진 통합 시뮬레이션 통과

---

## 네가 채울 것 — 우선순위 순

### A. 데이터 견고화 (먼저)

1. **`# VERIFY` 응답 필드 확정**
   - `kis_broker.py`의 `get_quote`, `get_daily_bars`, `get_account` 안에
     `# VERIFY` 주석이 붙은 응답 필드명을 실제 API 응답 구조로 확인·수정
   - 필드: `stck_prpr` / `stck_oprc` / `stck_hgpr` / `stck_lwpr` (현재가)
   - 필드: `stck_bsop_date` / `stck_clpr` 등 (일봉)
   - 필드: `dnca_tot_amt` / `hldg_qty` / `pchs_avg_pric` (잔고)
   - 일봉 정렬 방향(최신 우선 여부) 확인해서 `get_prev_day_bar` 인덱스 확정
   - `ORD_DVSN` 시장가 코드 확인 (지금 `"01"` 가정)

2. **KIS WebSocket 실시간 체결가 구독**
   - 공식 저장소 `examples_llm/auth/auth_ws_token/` 기반
   - `market_data.py`에 `WebSocketMarketData` 클래스 추가
   - `engine.on_tick`을 폴링 → 콜백 기반으로 전환
   - 연결 끊김 자동 재연결 + `HealthMonitor.record_api_error()` 연결

### B. 메인 루프 정식화

3. **`run.py` APScheduler 전환**
   - 단순 sleep 루프 → `APScheduler`(BackgroundScheduler)로 교체
   - 스케줄:
     - 08:55 → `engine.prepare_day()` (목표가 계산)
     - 09:00~14:30 매 N초 → `engine.on_tick()` (N=실시간이면 콜백으로)
     - 15:15 → `engine.force_close()`
     - 15:30 → 일일 리포트 + 종료
   - **휴장일 캘린더** 반영 (공휴일·토·일은 실행 안 함)
   - 장 시간 밖에서 on_tick 호출 방지

### C. 안전장치 보강 (실전 전 필수)

4. **부분 체결 처리**
   - `send_order` 후 실제 체결수량/체결가를 조회해 `engine.local` 갱신
   - 체결 조회: `inquire-ccnl` 또는 주문번호(`ODNO`) 기반 조회
   - 미체결·거부 시 처리 로직

5. **상태 영속화** (프로세스 재시작 복원)
   - 저장 대상: `gate._trades_today` / `gate._realized_pnl_today` / `idem._sent` / `engine.local`
   - SQLite로 저장 (`state.db`), 시작 시 오늘 날짜 기준 로드
   - `engine.prepare_day()` 진입 전에 이월 포지션 복원

6. **강제청산 실패 재시도**
   - `engine._exit`에서 `d.approved is False` 또는 브로커 에러 시
   - 최대 3회 재시도 (1초 간격)
   - 3회 실패 시 텔레그램 긴급 알림 + 킬스위치

7. **텔레그램 알림 실제 연결**
   - `python-telegram-bot` 라이브러리 사용
   - `alerts.TelegramAlertSender`의 `send_fn`에 실제 전송 함수 주입
   - 환경변수: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
   - 메시지 타입 구분: 진입/청산/정지/에러

8. **매 사이클 잔고 대조**
   - `run.py` 루프에서 일정 주기(예: 10분)로 `reconcile()` 호출
   - 불일치 시 킬스위치 → 텔레그램 긴급 알림

9. **시작 시 보유 포지션 동기화**
   - `engine.prepare_day()` 진입 전 브로커 잔고로 `engine.local` 초기화
   - 전일 이월 포지션 있으면 즉시 강제청산 (당일청산 전략이므로)

### D. 검증·운영 (모의 통과 후)

10. **백테스트**
    - 변동성 돌파 전략을 과거 일봉 데이터로 검증
    - `costs.net_pnl` 연결해 **수수료·세금 포함** 기대값 계산
    - k값(0.3~0.7) 범위로 그리드 탐색, 승률·손익비·MDD 리포트

11. **대상 종목 선정**
    - 유동성 기준(평균 거래량 상위, 변동폭 적당한 종목)
    - 코스피200 내에서 선정 권장

12. **운영 인프라**
    - 서버(VPS/클라우드) 배포 가이드
    - 토큰 파일 캐시(재시작 시 재발급 최소화)
    - 로그 파일 영속화 (rotating file handler)
    - 자동 재시작 (systemd 또는 Docker)

---

## 모델 전략

세션 시작 직후 아래 명령을 먼저 실행해:

```
/model opusplan
```

이렇게 하면 **계획(plan) 모드에선 Opus, 실행(execution) 모드에선 Sonnet**이 자동으로 갈린다.
설계·추론은 Opus가, 코드 생성은 Sonnet이 맡는 최적 조합이다.

단, 아래 항목은 **plan mode에서 신중히 설계한 뒤 실행**해야 한다.
돈이 직접 오가는 부분이라 Opus의 추론이 특히 중요하다:
- **A (KIS 연동 `# VERIFY` 필드 확정)**: 응답 필드 하나가 틀리면 잔고·주문이 오작동
- **C (안전장치 전체)**: 부분체결·강제청산 재시도·잔고 대조·상태 영속화

이 항목들을 작업할 때는 코드부터 짜지 말고,
먼저 설계(어떤 흐름으로 처리할지)를 plan mode에서 정리한 뒤 실행으로 넘어가라.

---

## 작업 규칙 (중요)

- **KIS API 관련(엔드포인트·tr_id·필드명)은 반드시 공식 저장소 코드 기준으로**
  기억으로 단정 금지. 확신 없으면 "VERIFY 필요"로 명시.
- **확신 없는 모든 부분을 주석으로 표시** (`# VERIFY` / `# TODO`)
- **이 코드가 놓치는 엣지케이스를 작업 완료 후 정리**해줘.
- **A·C 완료 후 반드시 테스트** — `python -m autotrader.run_tests` 통과 유지.
- **모의→실전 전환은 환경변수 `KIS_ENV=real` 하나로만** (코드 분기 금지).
- 무인 운용이므로 **예외가 봇을 죽이면 안 됨** — 모든 외부 호출에 try/except.

---

## 실행 방법

```bash
# 환경변수 세팅 (.env 파일 또는 export)
KIS_APPKEY=...
KIS_APPSECRET=...
KIS_CANO=12345678
KIS_ACNT_PRDT_CD=01
KIS_ENV=mock          # 모의 (실전은 real)
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...

# 테스트
python -m autotrader.run_tests

# 실행
python -m autotrader.run
```

---

## 우선순위 정리

```
A (데이터 견고화) → C (안전장치) → B (스케줄러) → D (백테스트·운영)
A와 C가 끝나야 모의 장기 검증을 시작할 수 있다.
모의에서 4주+ 무사고 후에만 실전.
```
