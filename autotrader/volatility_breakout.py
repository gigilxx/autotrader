"""변동성 돌파 전략 로직 (신호 생성만, 실행은 하지 않음).

핵심: 진입은 '목표가를 위로 돌파하는 첫 순간'에만. (상태가 아니라 전환만)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time

from .config import StrategyConfig


def compute_target_price(prev_high: int, prev_low: int, today_open: int, k: float) -> float:
    """목표가 = 당일 시가 + k × (전일 고가 − 전일 저가)."""
    return today_open + k * (prev_high - prev_low)


@dataclass
class BreakoutDetector:
    """종목별로 목표가 상향 돌파의 '전환 순간'만 True로 반환.

    직전 상태(_above)를 기억해 거짓→참 전환만 잡고,
    하루 1회만 진입(_fired)하도록 한다.
    """
    _above: dict[str, bool] = field(default_factory=dict)
    _fired: dict[str, bool] = field(default_factory=dict)

    def update(self, symbol: str, current_price: float, target_price: float) -> bool:
        was_above = self._above.get(symbol, False)
        is_above = current_price >= target_price
        self._above[symbol] = is_above

        if is_above and not was_above and not self._fired.get(symbol, False):
            self._fired[symbol] = True
            return True
        return False

    def reset_day(self) -> None:
        """새 거래일 시작 시 호출."""
        self._above.clear()
        self._fired.clear()


def stop_price_of(entry_price: int, stop_loss_pct: float) -> int:
    """진입가 기준 손절가(원, 내림)."""
    return int(entry_price * (1 - stop_loss_pct))


def should_stop_loss(entry_price: int, current_price: int, stop_loss_pct: float) -> bool:
    """현재가가 손절선 이하인지."""
    return current_price <= stop_price_of(entry_price, stop_loss_pct)


def should_force_close(now: time, cfg: StrategyConfig) -> bool:
    """마감 전 강제청산 시각 도달 여부."""
    return now >= cfg.force_close_time


def entry_allowed_by_time(now: time, cfg: StrategyConfig) -> bool:
    """신규 진입 허용 시간대인지(너무 늦으면 진입 금지)."""
    return now < cfg.entry_cutoff_time
