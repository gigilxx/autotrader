"""주문 실행 파이프라인.

안전 게이트(중복방지 → 리스크 게이트)를 통과한 주문만 브로커로 전송한다.
"""
from __future__ import annotations

from typing import Optional, Protocol

from .kill_switch import KillSwitch
from .models import AccountSnapshot, OrderRequest, Side
from .reconciliation import IdempotencyGuard
from .risk_gate import RiskGate


class Broker(Protocol):
    """KIS 연동 추상화."""
    def get_account(self) -> AccountSnapshot: ...
    def send_order(self, order: OrderRequest) -> str: ...  # ODNO 반환
    def cancel_order(self, odno: str, symbol: str, qty: int) -> bool: ...
    def wait_for_fill(self, odno: str, symbol: str, expected_qty: int, max_wait: float = ...) -> object: ...


class PlaceResult:
    """place() 반환값 — 승인 여부 + KIS 주문번호."""
    __slots__ = ("approved", "reason", "odno")

    def __init__(self, approved: bool, reason: str, odno: str = "") -> None:
        self.approved = approved
        self.reason = reason
        self.odno = odno


class OrderRouter:
    def __init__(
        self,
        broker: Broker,
        gate: RiskGate,
        kill: KillSwitch,
        idem: IdempotencyGuard,
    ) -> None:
        self.broker = broker
        self.gate = gate
        self.kill = kill
        self.idem = idem

    def place(self, order: OrderRequest, prefetched_account: Optional[AccountSnapshot] = None) -> PlaceResult:
        """주문 전송 시도. 통과 못 하면 사유와 함께 거부."""
        if self.kill.halted and order.side == Side.BUY:
            return PlaceResult(False, f"정지 상태 — 신규 진입 차단: {self.kill.reason}")

        if not self.idem.is_new(order.client_order_id):
            return PlaceResult(False, "중복 주문 — 이미 전송됨(멱등성 차단)")

        account = prefetched_account or self.broker.get_account()

        decision = self.gate.evaluate(order, account)
        if not decision.approved:
            return PlaceResult(False, decision.reason)

        try:
            odno = self.broker.send_order(order)
        except Exception as e:  # noqa: BLE001
            return PlaceResult(False, f"브로커 전송 실패: {e}")

        self.idem.mark_sent(order.client_order_id)
        if order.side == Side.BUY:
            self.gate.register_entry_fill()
        return PlaceResult(True, "전송 완료", odno=odno)
