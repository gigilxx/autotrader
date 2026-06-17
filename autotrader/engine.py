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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")
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
    round_up_to_tick,
    should_force_close,
    stop_price_of,
)
from .position_sizing import calc_position_size

logger = logging.getLogger("autotrader.engine")

_MAX_EXIT_RETRY = 3
_CASH_TOLERANCE_DISABLED = 999_999_999  # 로컬은 현금을 추적하지 않으므로 현금 대조 비활성화


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
        self._target_bases: dict[str, tuple[int, int, int]] = {}  # sym → (prev_high, prev_low, today_open)
        self.local: dict[str, _Local] = {}
        self._today: Optional[date] = None
        self.reporter = ReportCollector()
        self._market_ok: bool = True
        self._market_filter: Optional[MarketFilterResult] = None

    # ---------------- 거래일 시작 ----------------
    def prepare_day(self, today: Optional[date] = None) -> None:
        """08:55 실행 — DB 복원·브로커 동기화·시장 필터. 목표가는 compute_targets()에서 09:05에 계산."""
        self._today = today or datetime.now(_KST).date()
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

        # 4.6) 시장 필터 (전날 종가 기반 — 장 시작 전 조회 가능)
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
                self.state.set_control_flag("market_filter_ok", "1" if result.ok else "0")
                self.health.record_api_success()
                if not result.ok:
                    self.alert.send(f"⚠️ 시장 필터 차단 — 오늘 신규 진입 없음\n{result.summary()}")
            except Exception as e:  # noqa: BLE001
                logger.error("시장 필터 조회 실패: %s — 거래 허용으로 처리", e)
                self._market_ok = True
                self.health.record_api_error()
        else:
            self._market_ok = True

        self.detector.reset_day()
        self.targets.clear()
        self._target_bases.clear()
        self.state.cleanup_old_data()

    def compute_targets(self) -> None:
        """09:05 실행 — 장 시작 후 실제 시가로 목표가 계산 (종목당 API 1콜)."""
        for sym in self.watchlist:
            try:
                prev, today_open = self.data.get_prev_bar_and_today_open(sym)
                self._target_bases[sym] = (prev.high, prev.low, today_open)
                self.targets[sym] = compute_target_price(
                    prev.high, prev.low, today_open, self.cfg.strategy.k
                )
                logger.info("목표가 %s = %.0f", sym, self.targets[sym])
                self.health.record_api_success()
            except Exception as e:  # noqa: BLE001
                logger.error("목표가 계산 실패 %s: %s", sym, e)
                self.health.record_api_error()

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
    def _fetch_price(self, sym: str) -> tuple[str, int | None]:
        try:
            return sym, self.data.get_current_price(sym)
        except Exception as e:  # noqa: BLE001
            logger.warning("시세 실패 %s: %s", sym, e)
            return sym, None

    def on_tick(self, now: time, now_ts: float) -> None:
        if self.kill.halted:
            return
        self.health.check_feed(now_ts)

        symbols = list(self.watchlist)
        # 현재가 병렬 조회 (max_workers=2: rate limit 대비 2개씩 묶음)
        with ThreadPoolExecutor(max_workers=min(len(symbols), 2)) as ex:
            results = list(ex.map(self._fetch_price, symbols))

        for sym, px in results:
            if px is None:
                self.health.record_api_error()
                continue
            self.health.record_quote(now_ts)
            self.health.record_api_success()
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
        # marketable limit — 돌파 감지 가격 그대로 지정가를 걸면 그 사이 가격이 더 올라가
        # 체결이 잘 안 됨(2026-06-17 실측). 약간의 버퍼를 더해 체결률을 높이되 상한은 유지.
        limit_price = round_up_to_tick(int(px * (1 + self.cfg.strategy.entry_price_buffer_pct)))
        try:
            account = self.router.broker.get_account()
            available_cash = account.cash
        except Exception:
            account = None
            available_cash = self.cfg.risk.capital

        sizing = calc_position_size(limit_price, stop, available_cash, self.cfg.risk)
        if sizing.qty <= 0:
            logger.info("사이징 0 — 진입 보류 %s (%s)", sym, sizing.reason)
            return

        oid = IdempotencyGuard.make_order_id(sym, "buy", _bar_ts(), "entry")
        order = OrderRequest(sym, Side.BUY, sizing.qty, limit_price, oid, "breakout_entry")
        d = self.router.place(order, prefetched_account=account)
        logger.info("진입 시도 %s qty=%d @ %d → %s (%s)", sym, sizing.qty, limit_price, d.approved, d.reason)

        if not d.approved:
            return

        filled_qty, fill_price = self._resolve_buy_fill(d.odno, sym, sizing.qty, limit_price)
        if filled_qty <= 0:
            logger.warning("체결 수량 0 — 진입 취소 %s", sym)
            return

        self._record_entry(sym, oid, int(fill_price), filled_qty, target, stop)

    def _resolve_buy_fill(
        self, odno: str | None, sym: str, req_qty: int, fallback_px: int
    ) -> tuple[int, float]:
        """주문 ODNO의 체결 결과를 조회하고 (filled_qty, avg_price) 반환. 부분 체결 시 잔량 취소."""
        filled_qty = req_qty
        fill_price = float(fallback_px)
        if not odno:
            return filled_qty, fill_price
        try:
            fill = self.router.broker.wait_for_fill(odno, sym, req_qty)
            if fill.filled_qty > 0:
                filled_qty = fill.filled_qty
                fill_price = fill.avg_price if fill.avg_price > 0 else float(fallback_px)
                if fill.status == "partial":
                    logger.warning("부분 체결 %s: %d/%d주 — 잔량 취소", sym, filled_qty, req_qty)
                    try:
                        self.router.broker.cancel_order(odno, sym, req_qty)
                    except Exception as ce:  # noqa: BLE001
                        logger.warning("잔량 취소 실패 %s: %s", sym, ce)
            else:
                try:
                    ok = self.router.broker.cancel_order(odno, sym, req_qty)
                    logger.info("미체결 주문 취소 %s ODNO=%s → %s", sym, odno, "성공" if ok else "실패")
                except Exception as ce:  # noqa: BLE001
                    logger.warning("미체결 취소 실패 %s ODNO=%s: %s", sym, odno, ce)
                    ok = False

                if ok:
                    filled_qty = 0
                else:
                    # 취소 실패 — 그 사이 체결됐을 수 있으니 재조회로 확정 (추정만으로 0 단정 금지)
                    try:
                        recheck = self.router.broker.get_order_fill(odno, sym)
                    except Exception as re_:  # noqa: BLE001
                        logger.warning("취소 실패 후 재조회 실패 %s: %s — 요청 수량으로 가정", sym, re_)
                        recheck = None
                    if recheck is None:
                        pass  # filled_qty는 기본값(req_qty) 유지 — 미추적 포지션 방지
                    elif recheck.filled_qty > 0:
                        filled_qty = recheck.filled_qty
                        fill_price = recheck.avg_price if recheck.avg_price > 0 else float(fallback_px)
                        logger.warning("취소 실패했으나 체결 확인됨 %s: %d주 @ %s", sym, filled_qty, fill_price)
                    else:
                        filled_qty = 0
        except Exception as e:  # noqa: BLE001
            logger.warning("체결 조회 실패 %s: %s — 요청 수량으로 가정", sym, e)
        return filled_qty, fill_price

    def _persist_entry(self, sym: str, oid: str, fill_price: int, filled_qty: int) -> None:
        """체결 완료된 진입 정보를 local/state에 기록 (알림 제외)."""
        self.local[sym] = _Local(entry_price=fill_price, qty=filled_qty)
        today_d = self._today or datetime.now(_KST).date()
        self.state.save_position(today_d, sym, fill_price, filled_qty)
        self.state.add_sent_order(oid, today_d)
        self.state.save_daily_state(today_d, self.gate.trades_today, self.gate.realized_pnl_today)

    def _record_entry(
        self, sym: str, oid: str, fill_price: int, filled_qty: int, target: float, stop: int
    ) -> None:
        """체결 완료된 진입 정보를 local/state에 기록하고 알림 전송."""
        self._persist_entry(sym, oid, fill_price, filled_qty)
        self.alert.send(
            f"진입 {sym} {filled_qty}주 @ {fill_price:,}원 "
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
                actual_px = px
                filled_qty = pos.qty  # ODNO 없는 극단적 경우엔 확인 불가 — 요청 수량 그대로 가정
                if d.odno:
                    try:
                        fill = self.router.broker.wait_for_fill(d.odno, sym, pos.qty)
                        filled_qty = fill.filled_qty
                        if fill.avg_price > 0:
                            actual_px = int(fill.avg_price)
                    except Exception as e:
                        # 체결 여부를 확인 못 했으면 "성공"으로 단정하지 않는다 — 미체결 포지션이
                        # local에서 사라지는 게 가장 위험함(재시도 루프가 멱등성 차단으로 자연스럽게
                        # 빠져나가 결국 킬스위치 트립 + 긴급 알림으로 이어짐).
                        logger.warning("청산 체결 조회 실패 %s — 재시도: %s", sym, e)
                        filled_qty = 0

                if filled_qty <= 0:
                    logger.warning("청산 미체결 확인 %s — 재시도 (%d/%d)", sym, attempt, _MAX_EXIT_RETRY)
                    if attempt < _MAX_EXIT_RETRY:
                        _time.sleep(1)
                    continue

                pnl = net_pnl(pos.entry_price, actual_px, filled_qty, self.cfg.cost)
                self.gate.register_realized_pnl(pnl)

                today_d = self._today or datetime.now(_KST).date()
                exit_time = _now_hms()
                remaining = pos.qty - filled_qty
                if remaining > 0:
                    logger.warning("청산 부분 체결 %s: %d/%d주 — 잔량 local 유지", sym, filled_qty, pos.qty)
                    pos.qty = remaining
                    self.state.save_position(today_d, sym, pos.entry_price, remaining)
                else:
                    self.state.delete_position(today_d, sym)
                    del self.local[sym]
                self.state.save_daily_state(
                    today_d, self.gate.trades_today, self.gate.realized_pnl_today
                )
                self.state.record_trade(
                    today_d, exit_time, sym,
                    pos.entry_price, actual_px, filled_qty, pnl, reason,
                )
                self.reporter.record(TradeRecord(
                    symbol=sym,
                    entry_price=pos.entry_price,
                    exit_price=actual_px,
                    qty=filled_qty,
                    pnl=pnl,
                    reason=reason,
                    exit_time=exit_time,
                ))
                self.alert.send(f"청산 {sym} {filled_qty}주 @ {actual_px:,}원 ({reason}) 손익 {pnl:,}원")
                return

            if attempt < _MAX_EXIT_RETRY:
                logger.warning("청산 실패 %s — 1초 후 재시도 (%d/%d)", sym, attempt, _MAX_EXIT_RETRY)
                _time.sleep(1)

        # 재시도를 다 소진했어도 "체결 확인에 실패한 것"과 "실제로 안 팔린 것"은 다르다.
        # 브로커 잔고를 직접 한 번 더 봐서, 사실은 이미 체결됐는데 우리 쪽 조회만 실패한
        # 경우(레이트리밋 등)라면 local을 그대로 둬서 잔고대조가 영원히 같은 불일치를
        # 재보고하는 사고(2026-06-17 000660)를 막는다.
        try:
            broker_acct = self.router.broker.get_account()
            broker_qty = broker_acct.positions.get(sym, Position(sym, 0, 0)).qty
        except Exception as e:  # noqa: BLE001
            logger.error("청산 실패 후 잔고 재확인도 실패 %s: %s", sym, e)
            broker_qty = pos.qty  # 확인 불가 — 기존처럼 안전하게 "아직 있다"고 가정

        if broker_qty < pos.qty:
            sold_qty = pos.qty - broker_qty
            logger.warning("청산 재확인: 브로커 기준 %d주 실제로는 체결됨 %s — local 보정", sold_qty, sym)
            pnl = net_pnl(pos.entry_price, px, sold_qty, self.cfg.cost)
            self.gate.register_realized_pnl(pnl)
            today_d = self._today or datetime.now(_KST).date()
            exit_time = _now_hms()
            if broker_qty > 0:
                pos.qty = broker_qty
                self.state.save_position(today_d, sym, pos.entry_price, broker_qty)
            else:
                self.state.delete_position(today_d, sym)
                del self.local[sym]
            self.state.save_daily_state(today_d, self.gate.trades_today, self.gate.realized_pnl_today)
            self.state.record_trade(today_d, exit_time, sym, pos.entry_price, px, sold_qty, pnl, reason)
            self.reporter.record(TradeRecord(
                symbol=sym, entry_price=pos.entry_price, exit_price=px,
                qty=sold_qty, pnl=pnl, reason=reason, exit_time=exit_time,
            ))
            self.alert.send(f"청산 {sym} {sold_qty}주 @ {px:,}원 ({reason}, 체결조회 실패 후 잔고로 확정) 손익 {pnl:,}원")
            return

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

    def _force_entry(self, sym: str) -> None:
        """UI 수동 진입 — 브레이크아웃 조건 무시하고 현재가로 즉시 매수."""
        now_t = datetime.now(_KST).time()
        if not entry_allowed_by_time(now_t, self.cfg.strategy):
            logger.warning("강제 진입 %s — 진입 마감 시간(%s) 이후, 무시", sym, self.cfg.strategy.entry_cutoff_time)
            return

        try:
            px = self.data.get_current_price(sym)
        except Exception as e:
            logger.error("강제 진입 현재가 조회 실패 %s: %s", sym, e)
            return

        stop = stop_price_of(px, self.cfg.risk.stop_loss_pct)
        limit_price = round_up_to_tick(int(px * (1 + self.cfg.strategy.entry_price_buffer_pct)))
        try:
            account = self.router.broker.get_account()
            available_cash = account.cash
        except Exception:
            account = None
            available_cash = self.cfg.risk.capital

        sizing = calc_position_size(limit_price, stop, available_cash, self.cfg.risk)
        if sizing.qty <= 0:
            logger.warning("강제 진입 사이징 0 — %s (%s)", sym, sizing.reason)
            return

        oid = IdempotencyGuard.make_order_id(sym, "buy", _bar_ts(), "force_entry")
        order = OrderRequest(sym, Side.BUY, sizing.qty, limit_price, oid, "force_entry")
        d = self.router.place(order, prefetched_account=account)
        logger.info("강제 진입 시도 %s qty=%d @ %d → %s", sym, sizing.qty, limit_price, d.approved)

        if not d.approved:
            logger.warning("강제 진입 거부 %s: %s", sym, d.reason)
            return

        # B-1: 체결 확인 후 포지션 기록
        filled_qty, fill_price = self._resolve_buy_fill(d.odno, sym, sizing.qty, limit_price)
        if filled_qty <= 0:
            logger.warning("강제 진입 체결 수량 0 — %s", sym)
            return

        self._persist_entry(sym, oid, int(fill_price), filled_qty)
        self.alert.send(f"강제 진입 {sym} {filled_qty}주 @ {int(fill_price):,}원 (UI 수동)")

    def apply_runtime_flags(self) -> None:
        """control_flags에서 런타임 설정 변경을 5초마다 반영."""
        self._apply_force_close_flags()
        self._apply_watchlist_change()
        self._apply_k_change()
        self._apply_force_entry_flags()

    def _apply_force_close_flags(self) -> None:
        sm = self.state
        for sym in list(self.local.keys()):
            if sm.get_control_flag(f"force_close_{sym}"):
                sm.clear_control_flag(f"force_close_{sym}")
                self.close_position_by_symbol(sym)

    def _apply_watchlist_change(self) -> None:
        sm = self.state
        watchlist_str = sm.get_control_flag("watchlist_override")
        if watchlist_str is None:
            return
        new_wl = [s.strip() for s in watchlist_str.split(",") if s.strip()]
        if set(new_wl) == set(self.watchlist):
            return

        for sym in set(self.watchlist) - set(new_wl):
            if sym in self.local:
                self.close_position_by_symbol(sym)
            self.targets.pop(sym, None)

        for sym in set(new_wl) - set(self.watchlist):
            if sym not in self.targets:
                self._compute_target_for_new_symbol(sym)

        self.watchlist = new_wl
        logger.info("watchlist 업데이트: %s", self.watchlist)

    def _compute_target_for_new_symbol(self, sym: str) -> None:
        """장중 추가된 종목의 목표가 계산. 이미 돌파 상태면 진입 스킵 플래그 설정."""
        try:
            prev, today_open = self.data.get_prev_bar_and_today_open(sym)
            self._target_bases[sym] = (prev.high, prev.low, today_open)
            target = compute_target_price(prev.high, prev.low, today_open, self.cfg.strategy.k)
            self.targets[sym] = target
            try:
                px_now = self.data.get_current_price(sym)
                if px_now >= target:
                    self.detector.mark_already_above(sym)
                    logger.info(
                        "신규 종목 %s 현재가(%d) 이미 목표가(%.0f) 초과 — 장중 추격 진입 방지",
                        sym, px_now, target,
                    )
                else:
                    logger.info("신규 종목 목표가 %s = %.0f", sym, target)
            except Exception:
                logger.info("신규 종목 목표가 %s = %.0f", sym, target)
        except Exception as e:  # noqa: BLE001
            logger.warning("목표가 계산 실패 %s: %s", sym, e)

    def _apply_k_change(self) -> None:
        sm = self.state
        k_str = sm.get_control_flag("k_value")
        if k_str is None:
            return
        try:
            new_k = float(k_str)
            if 0.1 <= new_k <= 1.0 and self.cfg.strategy.k != new_k:
                logger.info("k값 변경: %.2f → %.2f", self.cfg.strategy.k, new_k)
                self.cfg.strategy.k = new_k
                sm.set_control_flag("current_k", str(new_k))
                for sym, (ph, pl, op) in self._target_bases.items():
                    if sym not in self.local:
                        new_target = compute_target_price(ph, pl, op, new_k)
                        old_target = self.targets.get(sym, 0)
                        self.targets[sym] = new_target
                        logger.info(
                            "목표가 재계산 %s: %.0f → %.0f (k=%.2f)",
                            sym, old_target, new_target, new_k,
                        )
                self.alert.send(f"k값 변경됨: {new_k} (미진입 종목 목표가 즉시 반영)")
        except ValueError:
            pass
        sm.clear_control_flag("k_value")

    def _apply_force_entry_flags(self) -> None:
        sm = self.state
        for sym in list(self.watchlist):
            if sm.get_control_flag(f"force_entry_{sym}"):
                sm.clear_control_flag(f"force_entry_{sym}")
                if sym not in self.local:
                    self._force_entry(sym)
                else:
                    logger.warning("강제 진입 요청 %s — 이미 보유 중, 무시", sym)

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
        result = reconcile(local_acct, broker_acct, self.kill, cash_tolerance=_CASH_TOLERANCE_DISABLED)
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
    return datetime.now(_KST).strftime("%Y%m%dT%H%M")


def _now_hms() -> str:
    return datetime.now(_KST).strftime("%H:%M:%S")
