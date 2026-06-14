# Claude Code 인수인계 — 무엇이 됐고, 무엇을 채울까

이 패키지는 **검증된 골격**이다. 핵심 로직·안전장치·KIS 연동·메인 루프의 뼈대가
서로 맞물려 있고, 모의 시뮬레이션으로 동작을 확인했다.
Claude Code는 아래 `🟡 TODO`를 채워 **무인 실거래용**으로 완성하면 된다.

## ✅ 이미 된 것 (골격, 테스트 통과)
- 리스크 게이트 / 포지션 사이징 / 변동성 돌파(전환감지) / 자동정지·킬스위치 / 알림 인터페이스
- 잔고 대조 + 멱등성(중복주문 방지)
- 주문 파이프라인(`OrderRouter`): 멱등성 → 리스크게이트 → 브로커
- **KIS 실연동**(`kis_broker.py`): 토큰·현재가·일봉·잔고·현금주문 (공식 저장소 기준, mock 검증)
- 시세 인터페이스(`market_data.py`) + 메인 엔진(`engine.py`) + 실행 골격(`run.py`)
- 단위 테스트 18개 + 엔진 통합 시뮬레이션 통과

## 🟡 Claude Code가 채울 것 (우선순위)

### A. 데이터(#2) 견고화
- [ ] KIS 실시간(WebSocket) 체결가 구독으로 `on_tick`을 콜백 기반 전환
      (공식 샘플: `examples_llm/auth/auth_ws_token`, 실시간 체결가)
- [ ] `# VERIFY` 응답 필드 확정: `stck_prpr/oprc/hgpr/lwpr`, 일봉 정렬,
      잔고 `dnca_tot_amt/hldg_qty/pchs_avg_pric`
- [ ] 일봉 `prev_day_bar` 인덱싱(정렬 순서) 확정

### B. 메인 루프(#3) 정식화
- [ ] `run.py` 단순 루프 → **APScheduler**(장 운영시간·휴장일 캘린더)
- [ ] 장 마감 종료 조건, prepare_day 시각(09:00 직전) 트리거

### C. 안전장치 보강(#4)
- [ ] **부분 체결**: `send_order` 후 실제 체결수량/체결가로 `engine.local` 갱신
- [ ] **상태 영속화**: `gate` 일일카운터·`idem` 주문id·`engine.local`을 디스크/DB 저장→재시작 복원
- [ ] **강제청산 실패 재시도/에스컬레이션**(`engine._exit`의 TODO)
- [ ] 실제 **텔레그램** 전송(`TelegramAlertSender(send_fn)`) 연결
- [ ] 매 사이클 **잔고 대조** 호출(`reconciliation.reconcile`)
- [ ] 시작 시 브로커 잔고로 `engine.local` 동기화(이월 포지션)

### D. 검증·운영(#5,#6)
- [ ] 백테스트: 변동성 돌파 + `costs.net_pnl`로 비용 포함 기대값, k 튜닝
- [ ] 대상 종목 선정(유동성)
- [ ] 서버/VPS 배포, 토큰 파일 캐시, 로깅 영속화, 자동 재시작(systemd)

## 진입점
- 모의 검증: 환경변수(`KIS_*`) 세팅 후 `python -m autotrader.run`
- 테스트: `python -m autotrader.run_tests`

## ⚠️ 게이트
모의에서 4주+ 무사고로 돌고 리스크 규칙이 한 번도 안 뚫린 뒤에만 실전(극소액).
