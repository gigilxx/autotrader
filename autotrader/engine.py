"""메인 트레이딩 엔진 — 변동성 돌파 당일청산.

하루 생애주기를 한 곳에서 조율한다:
  prepare_day()  : 거래일 초기화 + 목표가 계산 + 포지션 동기화
  on_tick(now)   : 현재가 수신 → 진입 감시 | 손절 감시
  force_close()  : 마감 직전 미청산분 강제 청산 (최대 3회 재시도)
  reconcile_now(): 브로커 잔고 대조 (10분 주기)
"""
from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional

from .alerts import AlertSender
from .auto_halt import HealthMonitor
from .config import AppConfig
from .costs import net_pnl
from .execution import OrderRouter
from .kill_switch import KillSwitch
from .market_data import MarketData
from .models import AccountSnapshot, OrderRequest, Position, Side
from .reconciliation import IdempotencyGuard, reconcile
from .report import ReportCollector, TradeRecord
from .risk_gate import RiskGate
from .state import StateManager
from .market_filter import MarketFilterResult, check_market
from .volatility_breakout import (
    BreakoutDetector,
    compute_target_price,
    entry_allowed_by_time,
    should_force_close,
    stop_price_of,
)
from .position_sizing import calc_position_size

logger = logging.getLogger("autotrader.engine")

_MAX_EXIT_RETRY = 3


@dataclass
class _Local:
    """엔진이 추정하는 보유 상태."""
    entry_price: int
    qty: int
    highest_px: int = 0  # 진입 후 최고가 (트레일링 스톱용)

    def __post_init__(self) -> None:
        if self.highest_px == 0:
            self.highest_px = self.entry_price


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
        state: Optional[StateManager] = None,
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
        self.state = state or StateManager()

        self.detector = BreakoutDetector()
        self.targets: dict[str, float] = {}
        self.local: dict[str, _Local] = {}
        self._today: Optional[date] = None
        self.reporter = ReportCollector()
        self._market_ok: bool = True
        self._market_filter: Optional[MarketFilterResult] = None

    # ---------------- 거래일 시작 ----------------
    def prepare_day(self, today: Optional[date] = None) -> None:
        self._today = today or date.today()
        today_d = self._today

        # 1) state.db에서 일일 카운터 복원
        ds = self.state.load_daily_state(today_d)
        self.gate.roll_day(today_d)
        self.gate._trades_today = ds.trades_today
        self.gate._realized_pnl_today = ds.realized_pnl_today

        # 2) 전송된 주문 ID 복원
        sent = self.state.load_sent_orders(today_d)
        self.idem._sent.update(sent)

        # 3) state.db에서 포지션 복원
        for pos in self.state.load_positions(today_d):
            self.local[pos.symbol] = _Local(entry_price=pos.entry_price, qty=pos.qty)

        # 4) 브로커 잔고로 동기화 (이월 포지션 즉시 청산)
        try:
            broker_acct = self.router.broker.get_account()
            self._sync_local_with_broker(broker_acct)
            self.health.record_api_success()
        except Exception as e:  # noqa: BLE001
            logger.error("시작 잔고 조회 실패: %s", e)
            self.health.record_api_error()

        # 4.5) 리포트 수집기 초기화
        self.reporter.reset(today_d)

        # 4.6) 시장 필터
        if self.cfg.strategy.use_market_filter:
            try:
                result = check_market(
                    self.router.broker,
                    ma_days=self.cfg.strategy.market_filter_ma_days,
                    symbol=self.cfg.strategy.market_filter_symbol,
                )
                self._market_ok = result.ok
                self._market_filter = result
                self.state.set_control_flag("market_filter_summary", result.summary())
                self.health.record_api_success()
                if not result.ok:
                    self.alert.send(f"⚠️ 시장 필터 차단 — 오늘 신규 진입 없음\n{result.summary()}")
            except Exception as e:  # noqa: BLE001
                logger.error("시장 필터 조회 실패: %s — 거래 허용으로 처리", e)
                self._market_ok = True
                self.health.record_api_error()
        else:
            self._market_ok = True

        # 5) 목표가 계산
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

        self.state.cleanup_old_data()

    def _sync_local_with_broker(self, broker_acct: AccountSnapshot) -> None:
        """브로커 실잔고로 engine.local 보정. 이월 포지션은 즉시 청산."""
        for sym, bpos in broker_acct.positions.items():
            if sym in self.watchlist and bpos.qty > 0:
                if sym not in self.local:
                    logger.warning("이월 포지션 감지 %s %d주 — 즉시 청산", sym, bpos.qty)
                    self.local[sym] = _Local(entry_price=int(bpos.avg_price), qty=bpos.qty)
                    try:
                        px = self.data.get_current_price(sym)
                    except Exception:
                        px = int(bpos.avg_price)
                    self._exit(sym, px, "carryover_close")

        for sym in list(self.local.keys()):
            bpos = broker_acct.positions.get(sym)
            if bpos is None or bpos.qty <= 0:
                logger.warning("local 포지션 %s 브로커 미확인 — local 제거", sym)
                del self.local[sym]

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
        if not self._market_ok:
            return
        if not entry_allowed_by_time(now, self.cfg.strategy):
            return
        target = self.targets.get(sym)
        if target is None:
            return
        if not self.detector.update(sym, px, target):
            return

        stop = stop_price_of(px, self.cfg.risk.stop_loss_pct)
        try:
            available_cash = self.router.broker.get_account().cash
        except Exception:
            available_cash = self.cfg.risk.capital

        sizing = calc_position_size(px, stop, available_cash, self.cfg.risk)
        if sizing.qty <= 0:
            logger.info("사이징 0 — 진입 보류 %s (%s)", sym, sizing.reason)
            return

        oid = IdempotencyGuard.make_order_id(sym, "buy", _bar_ts(), "entry")
        order = OrderRequest(sym, Side.BUY, sizing.qty, px, oid, "breakout_entry")
        d = self.router.place(order)
        logger.info("진입 시도 %s qty=%d → %s (%s)", sym, sizing.qty, d.approved, d.reason)

        if not d.approved:
            return

        # 부분 체결 대응
        filled_qty = sizing.qty
        fill_price = float(px)
        if d.odno:
            try:
                fill = self.router.broker.wait_for_fill(d.odno, sym, sizing.qty)
                if fill.filled_qty > 0:
                    filled_qty = fill.filled_qty
                    fill_price = fill.avg_price if fill.avg_price > 0 else float(px)
                    if fill.status == "partial":
                        logger.warning("부분 체결 %s: %d/%d주 — 잔량 취소", sym, filled_qty, sizing.qty)
                        try:
                            self.router.broker.cancel_order(d.odno, sym, sizing.qty)
                        except Exception as ce:  # noqa: BLE001
                            logger.warning("잔량 취소 실패 %s: %s", sym, ce)
                else:
                    try:
                        ok = self.router.broker.cancel_order(d.odno, sym, sizing.qty)
                        logger.info("미체결 주문 취소 %s ODNO=%s → %s", sym, d.odno, "성공" if ok else "실패")
                    except Exception as ce:  # noqa: BLE001
                        logger.warning("미체결 취소 실패 %s ODNO=%s: %s", sym, d.odno, ce)
            except Exception as e:  # noqa: BLE001
                logger.warning("체결 조회 실패 %s: %s — 요청 수량으로 가정", sym, e)

        if filled_qty <= 0:
            logger.warning("체결 수량 0 — 진입 취소 %s", sym)
            return

        self.local[sym] = _Local(entry_price=int(fill_price), qty=filled_qty)

        today_d = self._today or date.today()
        self.state.save_position(today_d, sym, int(fill_price), filled_qty)
        self.state.add_sent_order(oid, today_d)
        self.state.save_daily_state(today_d, self.gate.trades_today, self.gate.realized_pnl_today)

        self.alert.send(
            f"진입 {sym} {filled_qty}주 @ {int(fill_price):,}원 "
            f"(목표가 {target:.0f}, 손절 {stop:,})"
        )

    def _manage_position(self, sym: str, px: int) -> None:
        pos = self.local[sym]
        pos.highest_px = max(pos.highest_px, px)
        trail_stop = int(pos.highest_px * (1 - self.cfg.risk.stop_loss_pct))
        if px <= trail_stop:
            self._exit(sym, px, "trailing_stop")

    def _exit(self, sym: str, px: int, reason: str) -> None:
        pos = self.local.get(sym)
        if not pos:
            return

        oid = IdempotencyGuard.make_order_id(sym, "sell", _bar_ts(), reason)
        order = OrderRequest(sym, Side.SELL, pos.qty, None, oid, reason)  # 시장가 — 청산은 체결 보장 우선

        for attempt in range(1, _MAX_EXIT_RETRY + 1):
            d = self.router.place(order)
            logger.info("청산(%s) %s qty=%d 시도%d → %s", reason, sym, pos.qty, attempt, d.approved)
            if d.approved:
                pnl = net_pnl(pos.entry_price, px, pos.qty, self.cfg.cost)
                self.gate.register_realized_pnl(pnl)

                today_d = self._today or date.today()
                exit_time = _now_hms()
                self.state.delete_position(today_d, sym)
                self.state.save_daily_state(
                    today_d, self.gate.trades_today, self.gate.realized_pnl_today
                )
                self.state.record_trade(
                    today_d, exit_time, sym,
                    pos.entry_price, px, pos.qty, pnl, reason,
                )
                self.reporter.record(TradeRecord(
                    symbol=sym,
                    entry_price=pos.entry_price,
                    exit_price=px,
                    qty=pos.qty,
                    pnl=pnl,
                    reason=reason,
                    exit_time=exit_time,
                ))
                del self.local[sym]
                self.alert.send(f"청산 {sym} {pos.qty}주 @ {px:,}원 ({reason}) 손익 {pnl:,}원")
                return

            if attempt < _MAX_EXIT_RETRY:
                logger.warning("청산 실패 %s — 1초 후 재시도 (%d/%d)", sym, attempt, _MAX_EXIT_RETRY)
                _time.sleep(1)

        msg = f"{sym} 청산 {_MAX_EXIT_RETRY}회 실패 ({reason})"
        logger.error("긴급: %s", msg)
        self.alert.send_urgent(f"긴급: {msg} — 즉시 확인 필요")
        self.kill.trip(f"강제청산 {_MAX_EXIT_RETRY}회 실패 — {sym}")

    # ---------------- 외부 제어 ----------------
    def close_position_by_symbol(self, symbol: str) -> None:
        """UI/텔레그램 수동 청산 요청."""
        if symbol not in self.local:
            logger.warning("수동 청산 요청: %s 포지션 없음", symbol)
            return
        try:
            px = self.data.get_current_price(symbol)
        except Exception:
            px = self.local[symbol].entry_price
        self._exit(symbol, px, "manual_close")

    def apply_runtime_flags(self) -> None:
        """control_flags에서 런타임 설정 변경을 5초마다 반영."""
        sm = self.state

        # 수동 청산
        for sym in list(self.local.keys()):
            if sm.get_control_flag(f"force_close_{sym}"):
                sm.clear_control_flag(f"force_close_{sym}")
                self.close_position_by_symbol(sym)

        # watchlist 변경 — 제거 종목 보유 시 즉시 청산, 추가 종목 목표가 계산 시도
        watchlist_str = sm.get_control_flag("watchlist_override")
        if watchlist_str is not None:
            new_wl = [s.strip() for s in watchlist_str.split(",") if s.strip()]
            if set(new_wl) != set(self.watchlist):
                for sym in set(self.watchlist) - set(new_wl):
                    if sym in self.local:
                        self.close_position_by_symbol(sym)
                    self.targets.pop(sym, None)
                for sym in set(new_wl) - set(self.watchlist):
                    if sym not in self.targets:
                        try:
                            prev = self.data.get_prev_day_bar(sym)
                            q = self.data.get_quote(sym)
                            self.targets[sym] = compute_target_price(
                                prev.high, prev.low, q.open, self.cfg.strategy.k
                            )
                            logger.info("신규 종목 목표가 %s = %.0f", sym, self.targets[sym])
                        except Exception as e:  # noqa: BLE001
                            logger.warning("목표가 계산 실패 %s: %s", sym, e)
                self.watchlist = new_wl
                logger.info("watchlist 업데이트: %s", self.watchlist)

        # k값 변경 — 즉시 반영(다음 prepare_day부터 목표가에 적용)
        k_str = sm.get_control_flag("k_value")
        if k_str is not None:
            try:
                new_k = float(k_str)
                if 0.1 <= new_k <= 1.0 and self.cfg.strategy.k != new_k:
                    logger.info("k값 변경: %.2f → %.2f", self.cfg.strategy.k, new_k)
                    self.cfg.strategy.k = new_k
                    self.alert.send(f"k값 변경됨: {new_k}")
            except ValueError:
                pass
            sm.clear_control_flag("k_value")

    # ---------------- 마감 강제청산 ----------------
    def force_close(self, now: time) -> None:
        if not should_force_close(now, self.cfg.strategy):
            return
        for sym in list(self.local.keys()):
            try:
                px = self.data.get_current_price(sym)
            except Exception:  # noqa: BLE001
                px = self.local[sym].entry_price
            self._exit(sym, px, "force_close")

    # ---------------- 잔고 대조 ----------------
    def reconcile_now(self) -> None:
        """브로커 잔고와 local 추정 대조. 불일치 시 킬스위치."""
        try:
            broker_acct = self.router.broker.get_account()
        except Exception as e:  # noqa: BLE001
            logger.error("잔고 대조 조회 실패: %s", e)
            return

        local_positions = {
            sym: Position(sym, pos.qty, float(pos.entry_price))
            for sym, pos in self.local.items()
        }
        local_acct = AccountSnapshot(cash=0, positions=local_positions)
        result = reconcile(local_acct, broker_acct, self.kill, cash_tolerance=999_999_999)
        if not result.ok:
            logger.error("잔고 대조 불일치: %s", result.detail)
            self.alert.send_urgent(f"잔고 불일치: {result.detail}")

    # ---------------- 일일 리포트 ----------------
    def daily_report(self) -> str:
        daily = self.reporter.build()
        body = daily.format()
        suffix = (
            f"\n  잔여 포지션: {list(self.local.keys()) or '없음'}"
            f"\n  킬스위치: {'ON — ' + self.kill.reason if self.kill.halted else 'OFF'}"
        )
        report = body + suffix
        self.alert.send(report)
        return report


def _bar_ts() -> str:
    """멱등 주문 ID용 봉 타임스탬프(분 단위)."""
    return datetime.now().strftime("%Y%m%dT%H%M")


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")
