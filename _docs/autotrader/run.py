"""실행 진입점 (스케줄러 골격).

이 파일은 '뼈대'다. 실제 무인 운용에 맞게 Claude Code가 채운다.

흐름:
  09:00 직전  prepare_day()      — 목표가 계산
  장중 주기   on_tick()          — 진입/손절 감시 (N초마다)
  15:15       force_close()      — 강제청산
  종료        리포트/정리

🟡 Claude Code TODO:
- APScheduler로 위 스케줄을 정식 등록(장 운영시간·휴장일 캘린더 반영).
- 현재는 단순 sleep 루프(개념 시연용).
- 실시간 시세(WebSocket) 사용 시 on_tick을 콜백 기반으로 전환.
- 상태 영속화 로드/저장 연결(재시작 복원).
"""
from __future__ import annotations

import logging
import time as _time
from datetime import datetime

from .alerts import ConsoleAlertSender, TelegramAlertSender  # noqa: F401
from .auto_halt import HealthMonitor
from .config import AppConfig
from .engine import TradingEngine
from .execution import OrderRouter
from .kill_switch import KillSwitch
from .market_data import KISMarketData
from .reconciliation import IdempotencyGuard
from .risk_gate import RiskGate
from .kis_broker import KISBroker, credentials_from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def build_engine(watchlist: list[str]) -> TradingEngine:
    cfg = AppConfig()  # 기본 모의 + 보수적 리스크

    broker = KISBroker(credentials_from_env())  # 🟡 모의 앱키를 환경변수로
    data = KISMarketData(broker)

    kill = KillSwitch()
    alert = ConsoleAlertSender()  # 🟡 TODO: TelegramAlertSender(send_fn)로 교체
    kill.set_alert(lambda reason: alert.send(f"🛑 킬스위치: {reason}"))

    gate = RiskGate(cfg.risk, kill)
    health = HealthMonitor(kill)
    idem = IdempotencyGuard()
    router = OrderRouter(broker, gate, kill, idem)

    return TradingEngine(cfg, data, router, gate, kill, health, idem, alert, watchlist)


def main() -> None:
    watchlist = ["005930"]  # 🟡 TODO: 대상 종목(유동성 큰 종목)으로 교체/백테스트로 선정
    engine = build_engine(watchlist)

    # --- 개념 시연용 단순 루프 (실제론 APScheduler로 대체) ---
    engine.prepare_day()
    POLL_SEC = 2  # 🟡 모의 호출제한(0.5초) 고려해 여유 있게
    while True:
        now = datetime.now()
        engine.on_tick(now.time(), _time.time())
        engine.force_close(now.time())
        if engine.kill.halted:
            logging.info("정지 상태 — 루프 종료")
            break
        # 🟡 TODO: 장 마감 시각 도달 시 종료 조건
        _time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
