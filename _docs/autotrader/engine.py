"""메인 트레이딩 엔진 (#3) — 변동성 돌파 당일청산.

하루 생애주기를 한 곳에서 조율한다:
  prepare_day()  : 거래일 초기화 + 종목별 목표가 계산
  on_tick(now)   : 현재가 수신 → (진입 감시 | 손절 감시)
  force_close()  : 마감 직전 미청산분 강제 청산

이미 만든 모듈을 '엮기만' 한다(리스크게이트·사이징·돌파감지·라우터·자동정지).
🟡 표시는 Claude Code가 채워야 할 자리.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional

from .alerts import AlertSender
from .auto_halt import HealthMonitor
from .config import AppConfig
from .execution import OrderRouter
from .kill_switch import KillSwitch
from .market_data import MarketData
from .models import OrderRequest, Side
from .reconciliation import IdempotencyGuard
from .risk_gate import RiskGate
from .volatility_breakout import (
    BreakoutDetector,
    compute_target_price,
    entry_allowed_by_time,
    should_force_close,
    should_stop_loss,
    stop_price_of,
)
from .position_sizing import calc_position_size

logger = logging.getLogger("autotrader.engine")


@dataclass
class _Local:
    """엔진이 추정하는 보유 상태(브로커 잔고와 주기적으로 대조 필요)."""
    entry_price: int
    qty: int


class TradingEngine:
    def __init__(
        self,
        cfg: AppConfig,
        data: MarketData,
        router: OrderRouter,
        gate: RiskGate,
        kill: KillSwitch,
        health: HealthMonitor,
        idem: IdempotencyGuard,
        alert: AlertSender,
        watchlist: list[str],
    ) -> None:
        self.cfg = cfg
        self.data = data
        self.router = router
        self.gate = gate
        self.kill = kill
        self.health = health
        self.idem = idem
        self.alert = alert
        self.watchlist = watchlist

        self.detector = BreakoutDetector()
        self.targets: dict[str, float] = {}
        self.local: dict[str, _Local] = {}  # symbol -> 보유 추정

    # ---------------- 거래일 시작 ----------------
    def prepare_day(self, today: Optional[date] = None) -> None:
        today = today or date.today()
        self.gate.roll_day(today)
        self.detector.reset_day()
        self.targets.clear()
        for sym in self.watchlist:
            try:
                prev = self.data.get_prev_day_bar(sym)
                q = self.data.get_quote(sym)
                self.targets[sym] = compute_target_price(
                    prev.high, prev.low, q.open, self.cfg.strategy.k
                )
                logger.info("목표가 %s = %.0f", sym, self.targets[sym])
                self.health.record_api_success()
            except Exception as e:  # noqa: BLE001
                logger.error("목표가 계산 실패 %s: %s", sym, e)
                self.health.record_api_error()
        # 🟡 TODO: 시작 시 브로커 잔고로 self.local 동기화(이월/잔여 포지션 확인)

    # ---------------- 장중 1틱 ----------------
    def on_tick(self, now: time, now_ts: float) -> None:
        if self.kill.halted:
            return
        self.health.check_feed(now_ts)

        for sym in self.watchlist:
            try:
                px = self.data.get_current_price(sym)
                self.health.record_quote(now_ts)
                self.health.record_api_success()
            except Exception as e:  # noqa: BLE001
                logger.warning("시세 실패 %s: %s", sym, e)
                self.health.record_api_error()
                continue

            if sym in self.local:
                self._manage_position(sym, px)
            else:
                self._watch_entry(sym, px, now)

    def _watch_entry(self, sym: str, px: int, now: time) -> None:
        if not entry_allowed_by_time(now, self.cfg.strategy):
            return
        target = self.targets.get(sym)
        if target is None:
            return
        if not self.detector.update(sym, px, target):
            return

        stop = stop_price_of(px, self.cfg.risk.stop_loss_pct)
        # 🟡 TODO: available_cash는 브로커 잔고에서 받는 게 정확(여기선 설정 자본 사용)
        sizing = calc_position_size(px, stop, self.cfg.risk.capital, self.cfg.risk)
        if sizing.qty <= 0:
            logger.info("사이징 0 — 진입 보류 %s (%s)", sym, sizing.reason)
            return

        oid = IdempotencyGuard.make_order_id(sym, "buy", _bar_ts(), "entry")
        order = OrderRequest(sym, Side.BUY, sizing.qty, px, oid, "breakout_entry")
        d = self.router.place(order)
        logger.info("진입 시도 %s qty=%d → %s (%s)", sym, sizing.qty, d.approved, d.reason)
        if d.approved:
            # 🟡 TODO: 실제 체결가/체결수량으로 갱신(부분체결 대응). 지금은 요청가=체결가 가정.
            self.local[sym] = _Local(entry_price=px, qty=sizing.qty)
            self.alert.send(f"진입 {sym} {sizing.qty}주 @ {px:,}")

    def _manage_position(self, sym: str, px: int) -> None:
        pos = self.local[sym]
        if should_stop_loss(pos.entry_price, px, self.cfg.risk.stop_loss_pct):
            self._exit(sym, px, "stop_loss")

    def _exit(self, sym: str, px: int, reason: str) -> None:
        pos = self.local.get(sym)
        if not pos:
            return
        oid = IdempotencyGuard.make_order_id(sym, "sell", _bar_ts(), reason)
        order = OrderRequest(sym, Side.SELL, pos.qty, px, oid, reason)
        d = self.router.place(order)  # 청산은 리스크게이트가 항상 허용
        logger.info("청산(%s) %s qty=%d → %s", reason, sym, pos.qty, d.approved)
        if d.approved:
            from .costs import net_pnl
            pnl = net_pnl(pos.entry_price, px, pos.qty, self.cfg.cost)
            self.gate.register_realized_pnl(pnl)  # 일일 손실 한도 반영
            self.alert.send(f"청산 {sym} {pos.qty}주 @ {px:,} ({reason}) 손익 {pnl:,}원")
            del self.local[sym]
        # 🟡 TODO: 청산 주문 실패 시 재시도/에스컬레이션(특히 강제청산). 미구현.

    # ---------------- 마감 강제청산 ----------------
    def force_close(self, now: time) -> None:
        if not should_force_close(now, self.cfg.strategy):
            return
        for sym in list(self.local.keys()):
            try:
                px = self.data.get_current_price(sym)
            except Exception:  # noqa: BLE001
                px = self.local[sym].entry_price  # 시세 실패 시 폴백(주의)
            self._exit(sym, px, "force_close")


def _bar_ts() -> str:
    """멱등 주문 ID용 봉 타임스탬프(분 단위). 🟡 TODO: 실제 봉 기준으로 정교화."""
    from datetime import datetime
    return datetime.now().strftime("%Y%m%dT%H%M")
