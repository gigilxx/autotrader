"""공용 데이터 타입 정의.

봇 전체가 주고받는 기본 단위(주문/포지션/계좌)를 정의한다.
가격은 원(KRW) 정수, 수량은 정수(소수 주식 없음)로 가정한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Environment(str, Enum):
    """실행 환경. 기본은 모의투자."""
    MOCK = "mock"   # 모의투자(페이퍼)
    REAL = "real"   # 실전투자


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Market(str, Enum):
    KOSPI = "kospi"
    KOSDAQ = "kosdaq"


@dataclass(frozen=True)
class OrderRequest:
    """주문 요청. price가 None이면 시장가."""
    symbol: str
    side: Side
    qty: int
    price: Optional[int]
    client_order_id: str
    reason: str = ""  # 'breakout_entry' | 'stop_loss' | 'force_close' 등


@dataclass(frozen=True)
class DailyBar:
    """일봉 한 개."""
    date: str    # YYYYMMDD
    open: int
    high: int
    low: int
    close: int
    volume: int = 0   # 누적 거래량 (주) — KIS acml_vol 필드


@dataclass(frozen=True)
class Quote:
    """현재가 스냅샷(당일 시가·고저 포함)."""
    price: int
    open: int
    high: int
    low: int


@dataclass
class Position:
    symbol: str
    qty: int
    avg_price: float


@dataclass
class AccountSnapshot:
    """특정 시점의 계좌 스냅샷."""
    cash: int
    positions: dict[str, Position] = field(default_factory=dict)

    def position_count(self) -> int:
        """보유 수량이 1 이상인 종목 수."""
        return sum(1 for p in self.positions.values() if p.qty > 0)


@dataclass
class FilledOrder:
    """주문 체결 결과. send_order 후 체결 조회로 확정."""
    odno: str          # KIS 주문번호
    filled_qty: int    # 실제 체결수량 (0이면 미체결)
    avg_price: float   # 체결평균가
    status: str        # "filled" | "partial" | "pending" | "rejected"
