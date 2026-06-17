"""설정값. 기본은 보수적이며 모의투자로 시작하도록 구성.

⚠️ 세율·수수료 등 일부 값은 시점/계좌마다 다르므로 반드시 본인 기준으로 확인할 것.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time

from .models import Environment


@dataclass
class RiskConfig:
    """리스크 한도."""
    capital: int = 30_000_000          # 운용 자본(원)
    risk_per_trade_pct: float = 0.01   # 1회 매매 리스크 = 자본의 1%
    stop_loss_pct: float = 0.02        # 손절 -2%
    daily_max_loss_pct: float = 0.03   # 일일 최대손실 -3% → 당일 중단
    max_concurrent_positions: int = 1  # 동시 보유 종목 수
    max_trades_per_day: int = 3        # 1일 최대 진입 횟수

    @property
    def daily_max_loss_won(self) -> int:
        return int(self.capital * self.daily_max_loss_pct)

    @property
    def risk_per_trade_won(self) -> int:
        return int(self.capital * self.risk_per_trade_pct)


@dataclass
class CostConfig:
    """거래 비용. ⚠️ 공식/계좌 기준 확인 필요.

    2026년 매도 증권거래세 ≈ 0.20%
    (코스피 0.05% + 농어촌특별세 0.15%, 코스닥 0.20%).
    위탁수수료는 계좌마다 다르며 0에 가까운 경우도 있음.
    """
    sell_tax_rate: float = 0.0020      # 매도 시 거래세(편도)
    brokerage_fee_rate: float = 0.00015  # 위탁수수료(편도)


@dataclass
class StrategyConfig:
    """변동성 돌파 전략 파라미터."""
    k: float = 0.5                        # 돌파 계수
    force_close_time: time = time(15, 15)  # 마감 전 강제청산 시각
    entry_cutoff_time: time = time(14, 30)  # 이 시각 이후 신규 진입 금지
    use_market_filter: bool = True         # 시장 필터 사용 여부
    market_filter_symbol: str = "069500"   # KODEX 200
    market_filter_ma_days: int = 20        # 이동평균 기간


@dataclass
class AppConfig:
    env: Environment = field(default_factory=lambda: (
        Environment.REAL if os.getenv("KIS_ENV", "mock").lower() == "real"
        else Environment.MOCK
    ))
    risk: RiskConfig = field(default_factory=RiskConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
