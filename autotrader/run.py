"""실행 진입점 — APScheduler 기반 장중 스케줄러.

스케줄:
  08:55  prepare_day()  — 목표가 계산, 포지션 동기화
  09:00~14:30  tick_job()  — 2초마다 현재가 폴링 (REST 방식)
  15:15  force_close()  — 미청산분 강제청산
  15:30  daily_report() — 일일 리포트 후 스케줄러 종료

한국 공휴일·토요일·일요일은 자동 스킵 (holidays 라이브러리 사용).
모의→실전 전환: 환경변수 KIS_ENV=real 하나로만.
"""
from __future__ import annotations

import logging
import logging.handlers

from dotenv import load_dotenv
load_dotenv()
import os
import time as _time
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import holidays
from apscheduler.schedulers.blocking import BlockingScheduler

from .alerts import build_alert_sender
from .auto_halt import HealthMonitor
from .config import AppConfig
from .engine import TradingEngine
from .execution import OrderRouter
from .kill_switch import KillSwitch
from .market_data import KISMarketData
from .reconciliation import IdempotencyGuard
from .risk_gate import RiskGate
from .state import StateManager
from .kis_broker import KISBroker, credentials_from_env

KST = ZoneInfo("Asia/Seoul")
_KR_HOLIDAYS = holidays.KR()

MARKET_OPEN  = time(9, 0)
MARKET_CLOSE = time(15, 30)

POLL_INTERVAL_SEC = int(os.getenv("POLL_SEC", "2"))  # REST 폴링 간격 (모의: 0.5초/콜 × 종목수 고려)


class _ImportantFilter(logging.Filter):
    """WARNING 이상 + 주요 비즈니스 이벤트를 important.log로 보내는 필터."""
    _KEYWORDS = (
        "진입", "청산", "부분 체결", "미체결",
        "킬스위치", "trailing_stop", "force_close", "manual_close",
        "거래일 시작", "일일 리포트", "리포트 내용",
        "시장 필터", "watchlist", "k값",
        "스케줄러 시작", "스케줄러 종료",
        "이월 포지션", "관심종목",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        msg = record.getMessage()
        return any(kw in msg for kw in self._KEYWORDS)


def _setup_logging() -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    # 전체 로그 (INFO+)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "autotrader.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(fmt)

    # 중요 이벤트 전용 (WARNING+ 또는 비즈니스 키워드 포함 INFO)
    important = logging.handlers.RotatingFileHandler(
        log_dir / "important.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=30,
        encoding="utf-8",
    )
    important.setFormatter(fmt)
    important.addFilter(_ImportantFilter())

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addHandler(important)
    root.addHandler(logging.StreamHandler())


def _is_trading_day(d: datetime | None = None) -> bool:
    """장 운영일(월~금, 한국 공휴일 제외) 여부."""
    today = (d or datetime.now(KST)).date()
    return today.weekday() < 5 and today not in _KR_HOLIDAYS


def build_engine(watchlist: list[str]) -> TradingEngine:
    cfg = AppConfig()

    broker = KISBroker(credentials_from_env())
    data = KISMarketData(broker)

    kill = KillSwitch()
    alert = build_alert_sender()
    kill.set_alert(lambda reason: alert.send_urgent(f"킬스위치: {reason}"))

    gate = RiskGate(cfg.risk, kill)
    health = HealthMonitor(kill)
    idem = IdempotencyGuard()
    router = OrderRouter(broker, gate, kill, idem)
    state = StateManager()

    return TradingEngine(cfg, data, router, gate, kill, health, idem, alert, watchlist, state)


def main() -> None:
    _setup_logging()
    logger = logging.getLogger("autotrader.run")

    watchlist_env = os.getenv("WATCHLIST", "005930")
    watchlist = [s.strip() for s in watchlist_env.split(",") if s.strip()]
    logger.info("관심종목: %s", watchlist)

    engine = build_engine(watchlist)
    scheduler = BlockingScheduler(timezone=KST)

    def _guard(fn):
        """예외가 스케줄러를 죽이지 않도록 감싼다."""
        def wrapped(*args, **kwargs):
            try:
                fn(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                logger.exception("스케줄 작업 예외: %s", e)
        wrapped.__name__ = fn.__name__
        return wrapped

    @_guard
    def prepare_day_job():
        if not _is_trading_day():
            logger.info("휴장일 — prepare_day 스킵")
            return
        logger.info("=== 거래일 시작 ===")
        engine.prepare_day()

    @_guard
    def tick_job():
        if engine.kill.halted:
            return
        if not _is_trading_day():
            return
        now = datetime.now(KST)
        t = now.time()
        if not (MARKET_OPEN <= t <= MARKET_CLOSE):
            return
        engine.on_tick(t, _time.time())

    @_guard
    def force_close_job():
        if not _is_trading_day():
            return
        logger.info("=== 강제청산 시작 ===")
        engine.force_close(time(15, 15))

    @_guard
    def reconcile_job():
        if not _is_trading_day():
            return
        now_t = datetime.now(KST).time()
        if not (MARKET_OPEN <= now_t <= MARKET_CLOSE):
            return
        engine.reconcile_now()

    @_guard
    def daily_report_job():
        if not _is_trading_day():
            return
        logger.info("=== 일일 리포트 ===")
        report = engine.daily_report()
        logger.info("리포트 내용:\n%s", report)
        scheduler.shutdown(wait=False)

    @_guard
    def control_check_job():
        """UI/텔레그램에서 설정한 kill/resume 플래그를 5초마다 확인."""
        sm = engine.state
        if sm.get_control_flag("kill_requested") and not engine.kill.halted:
            sm.clear_control_flag("kill_requested")
            logger.warning("킬스위치 트립 — UI/Telegram 요청")
            engine.kill.trip("UI/Telegram 킬스위치 요청")
        if sm.get_control_flag("resume_requested") and engine.kill.halted:
            sm.clear_control_flag("resume_requested")
            engine.kill.reset()
            logger.warning("킬스위치 해제 — UI/Telegram 요청")
            engine.alert.send("킬스위치 해제 (UI/Telegram 요청)")
        engine.apply_runtime_flags()

    scheduler.add_job(prepare_day_job,  "cron", day_of_week="mon-fri", hour=8,  minute=55, id="prepare_day")
    scheduler.add_job(tick_job,         "interval", seconds=POLL_INTERVAL_SEC,  id="tick")
    scheduler.add_job(force_close_job,  "cron", day_of_week="mon-fri", hour=15, minute=15, id="force_close")
    scheduler.add_job(reconcile_job,    "interval", minutes=10,                 id="reconcile")
    scheduler.add_job(daily_report_job, "cron", day_of_week="mon-fri", hour=15, minute=30, id="daily_report")
    scheduler.add_job(control_check_job, "interval", seconds=5,                 id="control_check")

    # 08:55~15:30 사이에 재시작된 경우 prepare_day를 즉시 실행
    now_t = datetime.now(KST).time()
    if _is_trading_day() and time(8, 55) <= now_t <= MARKET_CLOSE and not engine.targets:
        logger.info("장중 재시작 감지 — prepare_day 즉시 실행")
        prepare_day_job()

    logger.info("스케줄러 시작 (KIS_ENV=%s)", os.getenv("KIS_ENV", "mock"))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("스케줄러 종료")


if __name__ == "__main__":
    main()
