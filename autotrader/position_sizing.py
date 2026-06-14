"""포지션 사이징: '자본의 고정 %를 리스크로' 방식.

수량 = (자본 × 리스크%) ÷ (진입가 − 손절가),  내림(floor).
그리고 매수금액이 보유현금을 넘지 않도록 추가로 제한한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import RiskConfig


@dataclass
class SizingResult:
    qty: int
    risk_won: int    # 손절 시 예상 손실(원, 비용 제외 개략치)
    notional: int    # 매수 금액(원)
    reason: str = ""


def calc_position_size(
    entry_price: int,
    stop_price: int,
    available_cash: int,
    cfg: RiskConfig,
) -> SizingResult:
    """손절폭과 리스크 비율로 매수 수량을 계산한다."""
    if entry_price <= 0:
        return SizingResult(0, 0, 0, "진입가 비정상")
    if stop_price >= entry_price:
        return SizingResult(0, 0, 0, "손절가가 진입가 이상 — 매수 불가")

    per_share_risk = entry_price - stop_price
    qty_by_risk = cfg.risk_per_trade_won // per_share_risk
    qty_by_cash = available_cash // entry_price
    qty = int(min(qty_by_risk, qty_by_cash))

    if qty <= 0:
        return SizingResult(0, 0, 0, "수량 0 — 현금 부족 또는 손절폭 과대")

    return SizingResult(
        qty=qty,
        risk_won=qty * per_share_risk,
        notional=qty * entry_price,
        reason="ok",
    )
