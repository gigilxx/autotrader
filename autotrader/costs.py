"""거래 비용 계산.

매수는 수수료만, 매도는 수수료 + 증권거래세가 든다.
손익 계산에 반드시 비용을 반영해야 단타에서 본전 구간을 정확히 본다.
"""
from __future__ import annotations

from .config import CostConfig


def buy_cost(amount: int, cfg: CostConfig) -> int:
    """매수 금액에 대한 비용(원). 수수료만."""
    return round(amount * cfg.brokerage_fee_rate)


def sell_cost(amount: int, cfg: CostConfig) -> int:
    """매도 금액에 대한 비용(원). 수수료 + 증권거래세."""
    return round(amount * (cfg.brokerage_fee_rate + cfg.sell_tax_rate))


def round_trip_cost(amount: int, cfg: CostConfig) -> int:
    """동일 금액 매수→매도 1회전 총비용(원)."""
    return buy_cost(amount, cfg) + sell_cost(amount, cfg)


def net_pnl(entry_price: int, exit_price: int, qty: int, cfg: CostConfig) -> int:
    """비용 차감 후 실현손익(원).

    일일 손실 한도 추적에 이 값을 사용한다.
    """
    gross = (exit_price - entry_price) * qty
    costs = buy_cost(entry_price * qty, cfg) + sell_cost(exit_price * qty, cfg)
    return gross - costs
