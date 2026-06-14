"""한국 증시 거래일 판정.

is_market_day(d) → bool
  - 토·일 제외
  - 한국 공휴일 제외 (holidays 라이브러리)
  - 임시 휴장일은 add_closure()로 수동 추가 가능

사용:
    from autotrader.calendar import is_market_day

    if not is_market_day():
        sys.exit(0)
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import holidays

_KR_HOLIDAYS = holidays.KR()
_EXTRA_CLOSURES: set[date] = set()


def add_closure(d: date) -> None:
    """임시 휴장일 수동 추가 (선물만기일 단축장 등)."""
    _EXTRA_CLOSURES.add(d)


def is_market_day(d: Optional[date] = None) -> bool:
    """한국 증시 정규 거래일이면 True."""
    target = d or date.today()
    if target.weekday() >= 5:
        return False
    if target in _KR_HOLIDAYS:
        return False
    if target in _EXTRA_CLOSURES:
        return False
    return True


def next_market_day(from_date: Optional[date] = None) -> date:
    """다음 거래일 반환 (from_date 다음날부터 탐색)."""
    candidate = (from_date or date.today()) + timedelta(days=1)
    while not is_market_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def prev_market_day(from_date: Optional[date] = None) -> date:
    """직전 거래일 반환 (from_date 전날부터 탐색)."""
    candidate = (from_date or date.today()) - timedelta(days=1)
    while not is_market_day(candidate):
        candidate -= timedelta(days=1)
    return candidate
