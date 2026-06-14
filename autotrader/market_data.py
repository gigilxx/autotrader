"""시세 데이터 인터페이스 (#2).

전략에 필요한 입력을 공급한다:
- 전일 일봉(고가·저가)  → 변동성 돌파 목표가 계산용
- 현재가 스냅샷(시가 포함) → 목표가 비교 / 진입 판정

설계 의도: 엔진은 이 Protocol에만 의존한다. 실제 소스(KIS REST/실시간)는 갈아끼울 수 있다.

🟡 Claude Code TODO:
- 현재 KISMarketData는 'REST 폴링' 방식. 무인 단타엔 KIS 실시간(WebSocket) 체결가
  구독으로 교체/보강 권장. (공식 샘플: examples_llm/.../auth_ws_token, 실시간 체결가)
- 일봉 정렬·필드명은 실응답으로 VERIFY 후 prev_day_bar 인덱싱 확정.
"""
from __future__ import annotations

from datetime import date
from typing import Protocol

from .kis_broker import KISBroker
from .models import DailyBar, Quote


class MarketData(Protocol):
    def get_prev_day_bar(self, symbol: str) -> DailyBar: ...
    def get_quote(self, symbol: str) -> Quote: ...
    def get_current_price(self, symbol: str) -> int: ...


class KISMarketData:
    """KIS REST 기반 시세 공급(폴링). KISBroker를 재사용."""

    def __init__(self, broker: KISBroker) -> None:
        self.broker = broker

    def get_prev_day_bar(self, symbol: str, today: str | None = None) -> DailyBar:
        """오늘 이전의 가장 최근 일봉(=전일).

        🟡 TODO(VERIFY): get_daily_bars 정렬 순서 확인.
        여기서는 '오늘 날짜가 아닌 첫 봉'을 전일로 본다.
        """
        today = today or date.today().strftime("%Y%m%d")
        bars = self.broker.get_daily_bars(symbol)
        for b in bars:
            if b.date and b.date != today:
                return b
        if bars:
            return bars[0]
        raise ValueError(f"{symbol}: 일봉 데이터 없음")

    def get_quote(self, symbol: str) -> Quote:
        return self.broker.get_quote(symbol)

    def get_current_price(self, symbol: str) -> int:
        return self.broker.get_current_price(symbol)


class FakeMarketData:
    """테스트/시연용. 미리 정한 전일봉과, 틱 단위 현재가 시퀀스를 흘려준다."""

    def __init__(self, prev_bar: DailyBar, today_open: int, tick_prices: list[int]) -> None:
        self._prev = prev_bar
        self._open = today_open
        self._ticks = list(tick_prices)
        self._i = -1

    def advance(self) -> bool:
        """다음 틱으로 진행. 더 없으면 False."""
        if self._i + 1 >= len(self._ticks):
            return False
        self._i += 1
        return True

    def get_prev_day_bar(self, symbol: str) -> DailyBar:
        return self._prev

    def get_quote(self, symbol: str) -> Quote:
        px = self._ticks[max(self._i, 0)]
        return Quote(price=px, open=self._open, high=px, low=self._open)

    def get_current_price(self, symbol: str) -> int:
        return self._ticks[max(self._i, 0)]
