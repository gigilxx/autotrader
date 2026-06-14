"""변동성 돌파 백테스트 엔진 (pykrx 데이터 기반).

기존 autotrader.volatility_breakout + autotrader.costs 로직을 재사용하며,
pykrx로 수집한 과거 일봉 DataFrame을 입력으로 받는다.

사용:
    from backtest.data_loader import get_daily_ohlcv
    from backtest.engine import run_backtest

    df = get_daily_ohlcv("005930", "20230101", "20241231")
    result = run_backtest(df, symbol="005930", k=0.5)
    print(result.metrics.format())
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from autotrader.config import CostConfig
from autotrader.costs import net_pnl
from autotrader.volatility_breakout import compute_target_price, stop_price_of


@dataclass
class BacktestConfig:
    k: float = 0.5
    stop_loss_pct: float = 0.02
    capital: int = 2_500_000
    risk_per_trade_pct: float = 0.01
    cost: CostConfig = field(default_factory=CostConfig)


@dataclass
class BacktestResult:
    symbol: str
    k: float
    trades: pd.DataFrame    # 컬럼: date, entry, exit, qty, pnl, gross_pnl, reason
    config: BacktestConfig = field(default_factory=BacktestConfig)

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def net_pnl_total(self) -> int:
        return int(self.trades["pnl"].sum()) if not self.trades.empty else 0


def run_backtest(
    df: pd.DataFrame,
    symbol: str,
    cfg: Optional[BacktestConfig] = None,
) -> BacktestResult:
    """일봉 DataFrame으로 변동성 돌파 백테스트 실행.

    df 컬럼 필수: date(YYYYMMDD), open, high, low, close
    날짜 오름차순 정렬 가정.
    """
    if cfg is None:
        cfg = BacktestConfig()

    df = df.sort_values("date").reset_index(drop=True)
    risk_won = int(cfg.capital * cfg.risk_per_trade_pct)

    records = []

    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        today = df.iloc[i]

        ph, pl = int(prev["high"]), int(prev["low"])
        if ph == 0 or pl == 0 or int(today["open"]) == 0:
            continue

        target = compute_target_price(ph, pl, int(today["open"]), cfg.k)
        stop   = stop_price_of(int(target), cfg.stop_loss_pct)

        if int(today["high"]) < target:
            continue  # 목표가 미달

        entry_price   = int(target)
        per_share_risk = entry_price - stop
        if per_share_risk <= 0:
            continue

        qty = min(risk_won // per_share_risk, cfg.capital // entry_price)
        if qty <= 0:
            continue

        # 손절 vs 종가 청산
        if int(today["low"]) <= stop:
            exit_price = stop
            reason = "stop_loss"
        else:
            exit_price = int(today["close"])
            reason = "eod_close"

        gross = (exit_price - entry_price) * qty
        cost_net = net_pnl(entry_price, exit_price, qty, cfg.cost)

        records.append({
            "date":      str(today["date"]),
            "entry":     entry_price,
            "exit":      exit_price,
            "qty":       qty,
            "pnl":       cost_net,
            "gross_pnl": gross,
            "reason":    reason,
        })

    trades_df = pd.DataFrame(
        records,
        columns=["date", "entry", "exit", "qty", "pnl", "gross_pnl", "reason"],
    ) if records else pd.DataFrame(
        columns=["date", "entry", "exit", "qty", "pnl", "gross_pnl", "reason"]
    )

    return BacktestResult(symbol=symbol, k=cfg.k, trades=trades_df, config=cfg)
