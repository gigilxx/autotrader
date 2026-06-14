"""커스텀 모듈 검증 테스트.

리스크 게이트는 '손실/한도 시나리오에서 실제로 차단되는가'를 중점 검증한다.
pytest 없이도 돌도록 작성: `python -m autotrader.run_tests`
"""
from __future__ import annotations

from datetime import date, time

from .config import CostConfig, RiskConfig, StrategyConfig
from .costs import net_pnl, round_trip_cost, sell_cost
from .kill_switch import KillSwitch
from .models import AccountSnapshot, OrderRequest, Position, Side
from .position_sizing import calc_position_size
from .reconciliation import IdempotencyGuard, reconcile
from .risk_gate import RiskGate
from .volatility_breakout import (
    BreakoutDetector,
    compute_target_price,
    should_force_close,
    should_stop_loss,
)


def _buy(symbol="005930", qty=10, price=70_000, oid="o1") -> OrderRequest:
    return OrderRequest(symbol, Side.BUY, qty, price, oid, "breakout_entry")


def _sell(symbol="005930", qty=10, price=70_000, oid="s1") -> OrderRequest:
    return OrderRequest(symbol, Side.SELL, qty, price, oid, "stop_loss")


def _gate(**kw) -> tuple[RiskGate, KillSwitch]:
    kill = KillSwitch()
    gate = RiskGate(RiskConfig(**kw), kill)
    gate.roll_day(date(2026, 6, 12))
    return gate, kill


# ---------- 포지션 사이징 ----------
def test_sizing_basic():
    cfg = RiskConfig(capital=2_500_000, risk_per_trade_pct=0.01)  # 리스크 25,000원
    r = calc_position_size(entry_price=10_000, stop_price=9_800, available_cash=2_500_000, cfg=cfg)
    # 주당 리스크 200원 → 25,000/200 = 125주, 현금으로도 충분
    assert r.qty == 125, r
    assert r.reason == "ok"


def test_sizing_capped_by_cash():
    cfg = RiskConfig(capital=2_500_000, risk_per_trade_pct=0.5)  # 비현실적으로 큰 리스크
    r = calc_position_size(entry_price=10_000, stop_price=9_900, available_cash=300_000, cfg=cfg)
    assert r.qty == 30  # 현금 300,000 / 10,000 = 30주로 제한


def test_sizing_invalid_stop():
    cfg = RiskConfig()
    r = calc_position_size(entry_price=10_000, stop_price=10_000, available_cash=1_000_000, cfg=cfg)
    assert r.qty == 0


# ---------- 리스크 게이트: 차단 시나리오 ----------
def test_gate_blocks_when_daily_loss_hit():
    gate, kill = _gate(capital=2_500_000, daily_max_loss_pct=0.03)  # 한도 -75,000
    gate.register_realized_pnl(-80_000)  # 한도 초과 손실
    assert kill.halted is True
    d = gate.evaluate(_buy(), AccountSnapshot(cash=2_500_000))
    assert d.approved is False
    assert "정지" in d.reason or "손실" in d.reason


def test_gate_blocks_when_max_trades_reached():
    gate, _ = _gate(max_trades_per_day=3)
    for _ in range(3):
        gate.register_entry_fill()
    d = gate.evaluate(_buy(), AccountSnapshot(cash=2_500_000))
    assert d.approved is False
    assert "최대 거래" in d.reason


def test_gate_blocks_when_max_positions_reached():
    gate, _ = _gate(max_concurrent_positions=1)
    acct = AccountSnapshot(cash=2_500_000, positions={"000660": Position("000660", 5, 100_000)})
    d = gate.evaluate(_buy(symbol="005930"), acct)
    assert d.approved is False
    assert "동시 보유" in d.reason


def test_gate_blocks_insufficient_cash():
    gate, _ = _gate()
    d = gate.evaluate(_buy(qty=100, price=70_000), AccountSnapshot(cash=1_000_000))
    assert d.approved is False
    assert "현금 부족" in d.reason


def test_gate_blocks_market_order_entry():
    gate, _ = _gate()
    market_order = OrderRequest("005930", Side.BUY, 10, None, "o9", "breakout_entry")
    d = gate.evaluate(market_order, AccountSnapshot(cash=2_500_000))
    assert d.approved is False


# ---------- 리스크 게이트: 청산은 절대 막지 않음 ----------
def test_gate_always_allows_sell_even_when_halted():
    gate, kill = _gate(daily_max_loss_pct=0.03)
    gate.register_realized_pnl(-999_999)  # 강제 정지
    assert kill.halted is True
    d = gate.evaluate(_sell(), AccountSnapshot(cash=0))
    assert d.approved is True  # 손절/청산은 통과해야 함


def test_gate_allows_valid_buy():
    gate, _ = _gate()
    d = gate.evaluate(_buy(qty=10, price=70_000), AccountSnapshot(cash=2_500_000))
    assert d.approved is True


# ---------- 변동성 돌파 ----------
def test_target_price():
    # 전일 변동폭 1000, k=0.5, 시가 10,000 → 목표가 10,500
    assert compute_target_price(prev_high=10_500, prev_low=9_500, today_open=10_000, k=0.5) == 10_500


def test_breakout_fires_once_on_transition():
    d = BreakoutDetector()
    target = 10_500
    assert d.update("A", 10_400, target) is False  # 아래
    assert d.update("A", 10_500, target) is True   # 돌파 순간
    assert d.update("A", 10_600, target) is False  # 이미 발화 → 재신호 없음
    assert d.update("A", 10_400, target) is False  # 다시 내려와도 그대로
    assert d.update("A", 10_700, target) is False  # 재돌파해도 하루 1회


def test_stop_and_force_close():
    assert should_stop_loss(entry_price=10_000, current_price=9_800, stop_loss_pct=0.02) is True
    assert should_stop_loss(entry_price=10_000, current_price=9_900, stop_loss_pct=0.02) is False
    cfg = StrategyConfig(force_close_time=time(15, 15))
    assert should_force_close(time(15, 16), cfg) is True
    assert should_force_close(time(15, 0), cfg) is False


# ---------- 잔고 대조 / 멱등성 ----------
def test_reconcile_trips_on_mismatch():
    kill = KillSwitch()
    local = AccountSnapshot(cash=1_000_000, positions={"005930": Position("005930", 10, 70_000)})
    broker = AccountSnapshot(cash=1_000_000, positions={"005930": Position("005930", 5, 70_000)})
    r = reconcile(local, broker, kill)
    assert r.ok is False
    assert kill.halted is True


def test_reconcile_ok_within_tolerance():
    kill = KillSwitch()
    local = AccountSnapshot(cash=1_000_500)
    broker = AccountSnapshot(cash=1_000_000)
    r = reconcile(local, broker, kill, cash_tolerance=1000)
    assert r.ok is True
    assert kill.halted is False


def test_idempotency_blocks_duplicate():
    g = IdempotencyGuard()
    oid = IdempotencyGuard.make_order_id("005930", "buy", "2026-06-12T09:05", "entry")
    assert g.is_new(oid) is True
    g.mark_sent(oid)
    assert g.is_new(oid) is False  # 재전송 차단


# ---------- 비용 ----------
def test_sell_cost_includes_tax():
    cfg = CostConfig(sell_tax_rate=0.0020, brokerage_fee_rate=0.00015)
    # 매도 1,000,000원 → (0.0020+0.00015)*1,000,000 = 2,150원
    assert sell_cost(1_000_000, cfg) == 2_150


def test_net_pnl_can_be_negative_due_to_cost():
    cfg = CostConfig()
    # 가격 변화 없음 → 비용만큼 손실
    pnl = net_pnl(entry_price=10_000, exit_price=10_000, qty=100, cfg=cfg)
    assert pnl < 0


# ---------- 상태 영속화 ----------
def test_state_manager_daily_state():
    import tempfile
    from pathlib import Path
    from datetime import date
    from .state import StateManager

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        sm = StateManager(db_path=db_path)
        today = date(2026, 6, 14)

        sm.save_daily_state(today, trades=2, pnl=-15_000)
        ds = sm.load_daily_state(today)
        assert ds.trades_today == 2
        assert ds.realized_pnl_today == -15_000

        other = sm.load_daily_state(date(2026, 6, 13))
        assert other.trades_today == 0
    finally:
        db_path.unlink(missing_ok=True)


def test_state_manager_sent_orders():
    import tempfile
    from pathlib import Path
    from datetime import date
    from .state import StateManager

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        sm = StateManager(db_path=db_path)
        today = date(2026, 6, 14)

        sm.add_sent_order("005930:buy:T0900:entry", today)
        sm.add_sent_order("000660:buy:T0910:entry", today)
        loaded = sm.load_sent_orders(today)
        assert "005930:buy:T0900:entry" in loaded
        assert "000660:buy:T0910:entry" in loaded
        assert len(loaded) == 2
    finally:
        db_path.unlink(missing_ok=True)


def test_state_manager_positions():
    import tempfile
    from pathlib import Path
    from datetime import date
    from .state import StateManager

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        sm = StateManager(db_path=db_path)
        today = date(2026, 6, 14)

        sm.save_position(today, "005930", 70_000, 10)
        positions = sm.load_positions(today)
        assert len(positions) == 1
        assert positions[0].symbol == "005930"
        assert positions[0].entry_price == 70_000
        assert positions[0].qty == 10

        sm.delete_position(today, "005930")
        positions = sm.load_positions(today)
        assert len(positions) == 0
    finally:
        db_path.unlink(missing_ok=True)


# ---------- FilledOrder ----------
def test_filled_order_fields():
    from .models import FilledOrder
    f = FilledOrder(odno="12345", filled_qty=5, avg_price=70_100.0, status="partial")
    assert f.odno == "12345"
    assert f.filled_qty == 5
    assert f.status == "partial"


# ---------- PlaceResult (execution) ----------
def test_place_result_fields():
    from .execution import PlaceResult
    pr = PlaceResult(True, "전송 완료", odno="99999")
    assert pr.approved is True
    assert pr.odno == "99999"


# ---------- 휴장일 캘린더 ----------
def test_trading_day_check():
    from datetime import date
    import holidays
    kr = holidays.KR()
    # 2026-01-01 (신정 공휴일)
    assert date(2026, 1, 1) in kr
    # 2026-06-15 (월요일, 평일)
    mon = date(2026, 6, 15)
    assert mon.weekday() == 0 and mon not in kr  # 장 운영일
    # 2026-06-14 (일요일)
    assert date(2026, 6, 14).weekday() == 6  # 휴장


# ---------- calendar 모듈 ----------
def test_calendar_is_market_day():
    from datetime import date
    from .calendar import is_market_day, add_closure

    assert is_market_day(date(2026, 6, 15)) is True   # 월요일, 비공휴일
    assert is_market_day(date(2026, 6, 14)) is False  # 일요일
    assert is_market_day(date(2026, 1, 1))  is False  # 신정


def test_calendar_extra_closure():
    from datetime import date
    from .calendar import is_market_day, add_closure, _EXTRA_CLOSURES

    extra = date(2026, 7, 1)  # 원래 거래일
    assert is_market_day(extra) is True
    add_closure(extra)
    assert is_market_day(extra) is False
    _EXTRA_CLOSURES.discard(extra)  # 테스트 후 복원


def test_calendar_next_market_day():
    from datetime import date
    from .calendar import next_market_day

    # 금요일(2026-06-19)의 다음 거래일 = 월요일(2026-06-22)
    nxt = next_market_day(date(2026, 6, 19))
    assert nxt.weekday() < 5  # 평일


# ---------- report 모듈 ----------
def test_report_collector_empty():
    from datetime import date
    from .report import ReportCollector

    rc = ReportCollector()
    rc.reset(date(2026, 6, 15))
    report = rc.build()
    assert report.total_trades == 0
    assert report.total_pnl == 0
    assert "거래 없음" in report.format()


def test_report_collector_records():
    from datetime import date
    from .report import ReportCollector, TradeRecord

    rc = ReportCollector()
    rc.reset(date(2026, 6, 15))
    rc.record(TradeRecord("005930", 70_000, 72_000, 10, 19_790, "eod_close", exit_time="15:15:00"))
    rc.record(TradeRecord("000660", 130_000, 127_400, 5, -13_650, "stop_loss", exit_time="11:30:00"))

    r = rc.build()
    assert r.total_trades == 2
    assert r.wins == 1
    assert r.losses == 1
    assert r.win_rate == 0.5
    assert r.total_pnl == 19_790 - 13_650
    text = r.format()
    assert "005930" in text
    assert "stop_loss" in text


# ---------- state control_flags ----------
def test_state_control_flags():
    import tempfile
    from pathlib import Path
    from .state import StateManager

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        sm = StateManager(db_path=db_path)
        assert sm.get_control_flag("kill_requested") is None
        sm.set_control_flag("kill_requested", "1")
        assert sm.get_control_flag("kill_requested") == "1"
        sm.clear_control_flag("kill_requested")
        assert sm.get_control_flag("kill_requested") is None
    finally:
        db_path.unlink(missing_ok=True)


# ---------- state record_trade ----------
def test_state_record_trade():
    import tempfile
    from pathlib import Path
    from datetime import date
    from .state import StateManager

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        sm = StateManager(db_path=db_path)
        today = date(2026, 6, 15)
        sm.record_trade(today, "15:15:00", "005930", 70_000, 72_000, 10, 19_790, "eod_close")
        trades = sm.get_trades(today)
        assert len(trades) == 1
        assert trades[0]["symbol"] == "005930"
        assert trades[0]["pnl"] == 19_790
    finally:
        db_path.unlink(missing_ok=True)
