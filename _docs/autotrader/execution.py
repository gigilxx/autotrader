"""주문 실행 파이프라인.

안전 게이트(중복방지 → 리스크 게이트)를 통과한 주문만 브로커로 전송한다.
브로커(KIS)는 추상화 — 실제 구현은 한투 공식 샘플 기반으로 작성.
⚠️ 공식 문서 확인 필요: 모의/실전 tr_id, 엔드포인트, 주문 파라미터, 토큰/호출제한.
"""
from __future__ import annotations

from typing import Protocol

from .kill_switch import KillSwitch
from .models import AccountSnapshot, OrderRequest, Side
from .reconciliation import IdempotencyGuard
from .risk_gate import Decision, RiskGate


class Broker(Protocol):
    """KIS 연동 추상화. 실제 구현에서 모의/실전을 분리할 것."""
    def get_account(self) -> AccountSnapshot: ...
    def send_order(self, order: OrderRequest) -> bool: ...


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

    def place(self, order: OrderRequest) -> Decision:
        """주문 전송 시도. 통과 못 하면 사유와 함께 거부."""
        # 0) 전역 정지 시 신규 진입 차단(청산은 계속 허용)
        if self.kill.halted and order.side == Side.BUY:
            return Decision(False, f"정지 상태 — 신규 진입 차단: {self.kill.reason}")

        # 1) 중복 주문 방지
        if not self.idem.is_new(order.client_order_id):
            return Decision(False, "중복 주문 — 이미 전송됨(멱등성 차단)")

        # 2) 최신 잔고 조회
        account = self.broker.get_account()

        # 3) 리스크 게이트
        decision = self.gate.evaluate(order, account)
        if not decision.approved:
            return decision

        # 4) 브로커 전송
        ok = self.broker.send_order(order)
        if not ok:
            return Decision(False, "브로커 전송 실패")

        # 5) 전송 성공 처리
        self.idem.mark_sent(order.client_order_id)
        if order.side == Side.BUY:
            self.gate.register_entry_fill()
        return Decision(True, "전송 완료")
