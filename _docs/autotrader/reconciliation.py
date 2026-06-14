"""잔고 대조 + 중복주문 방지(멱등성).

- reconcile: 봇이 추정한 잔고와 증권사 실제 잔고를 대조, 불일치 시 정지.
- IdempotencyGuard: 네트워크 재시도 등으로 같은 주문이 두 번 나가는 것을 방지.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .kill_switch import KillSwitch
from .models import AccountSnapshot


@dataclass
class ReconResult:
    ok: bool
    detail: str


def reconcile(
    local: AccountSnapshot,
    broker: AccountSnapshot,
    kill: KillSwitch,
    cash_tolerance: int = 1000,  # 수수료/반올림 오차 허용(원)
) -> ReconResult:
    """추정 잔고(local)와 실제 잔고(broker)를 대조. 불일치 시 킬스위치."""
    problems: list[str] = []

    if abs(local.cash - broker.cash) > cash_tolerance:
        problems.append(f"현금 불일치: 추정 {local.cash:,} vs 실제 {broker.cash:,}")

    symbols = set(local.positions) | set(broker.positions)
    for s in sorted(symbols):
        lq = local.positions[s].qty if s in local.positions else 0
        bq = broker.positions[s].qty if s in broker.positions else 0
        if lq != bq:
            problems.append(f"[{s}] 수량 불일치: 추정 {lq} vs 실제 {bq}")

    if problems:
        detail = "; ".join(problems)
        kill.trip(f"잔고 대조 실패 — {detail}")
        return ReconResult(False, detail)
    return ReconResult(True, "일치")


@dataclass
class IdempotencyGuard:
    """동일 주문의 중복 전송 방지.

    같은 논리적 주문은 같은 client_order_id를 갖도록 생성하고(make_order_id),
    이미 '전송 완료'로 표시된 id의 재전송을 막는다.
    """
    _sent: set[str] = field(default_factory=set)

    @staticmethod
    def make_order_id(symbol: str, side: str, bar_ts: str, tag: str = "") -> str:
        """봉 타임스탬프 기준 결정적 ID — 같은 봉의 같은 신호는 같은 ID."""
        return f"{symbol}:{side}:{bar_ts}:{tag}"

    def is_new(self, client_order_id: str) -> bool:
        """아직 전송되지 않은 주문이면 True."""
        return client_order_id not in self._sent

    def mark_sent(self, client_order_id: str) -> None:
        """브로커 전송 성공 후 호출."""
        self._sent.add(client_order_id)
