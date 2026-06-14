"""모듈이 어떻게 맞물리는지 보여주는 실행 예시 (가짜 브로커 사용).

실제 매매 아님 — 무인 파이프라인의 흐름과 안전장치 동작을 시연한다.
사용:  python -m autotrader.example
"""
from __future__ import annotations

from datetime import date, time

from .config import RiskConfig, StrategyConfig
from .alerts import ConsoleAlertSender
from .execution import OrderRouter
from .kill_switch import KillSwitch
from .models import AccountSnapshot, OrderRequest, Position, Side
from .position_sizing import calc_position_size
from .reconciliation import IdempotencyGuard
from .risk_gate import RiskGate
from .volatility_breakout import BreakoutDetector, compute_target_price, stop_price_of


class FakeBroker:
    """메모리상의 가짜 브로커. ⚠️ 실제 KIS 연동으로 교체 필요."""

    def __init__(self, cash: int) -> None:
        self.account = AccountSnapshot(cash=cash)

    def get_account(self) -> AccountSnapshot:
        return self.account

    def send_order(self, order: OrderRequest) -> bool:
        # 데모: 지정가로 즉시 체결된다고 가정
        if order.side == Side.BUY:
            self.account.cash -= order.qty * (order.price or 0)
            self.account.positions[order.symbol] = Position(
                order.symbol, order.qty, float(order.price or 0)
            )
        return True


def main() -> None:
    cfg_risk = RiskConfig(capital=2_500_000)
    cfg_strat = StrategyConfig(k=0.5, force_close_time=time(15, 15))

    kill = KillSwitch()
    alert = ConsoleAlertSender()
    kill.set_alert(lambda reason: alert.send(f"킬스위치 작동: {reason}"))

    gate = RiskGate(cfg_risk, kill)
    gate.roll_day(date(2026, 6, 12))
    idem = IdempotencyGuard()
    broker = FakeBroker(cash=2_500_000)
    router = OrderRouter(broker, gate, kill, idem)
    detector = BreakoutDetector()

    symbol = "005930"
    target = compute_target_price(prev_high=72_000, prev_low=70_000, today_open=70_000, k=cfg_strat.k)
    print(f"목표가: {target:,.0f}원")

    # 장중 틱이 들어온다고 가정
    ticks = [70_500, 70_900, 71_000, 71_050]  # 마지막에 목표가(71,000) 돌파
    entered = False
    for px in ticks:
        if not entered and detector.update(symbol, px, target):
            stop = stop_price_of(int(px), cfg_risk.stop_loss_pct)
            sizing = calc_position_size(int(px), stop, broker.get_account().cash, cfg_risk)
            print(f"돌파! 현재가 {px:,} / 손절가 {stop:,} / 수량 {sizing.qty}")
            oid = IdempotencyGuard.make_order_id(symbol, "buy", "2026-06-12T10:00", "entry")
            order = OrderRequest(symbol, Side.BUY, sizing.qty, int(px), oid, "breakout_entry")
            d = router.place(order)
            print(f"주문 결과: {d.approved} — {d.reason}")
            # 같은 주문 재전송 시도(멱등성 시연)
            d2 = router.place(order)
            print(f"중복 재전송: {d2.approved} — {d2.reason}")
            entered = True

    print(f"\n남은 현금: {broker.get_account().cash:,}원")
    print(f"보유: {broker.get_account().positions}")


if __name__ == "__main__":
    main()
