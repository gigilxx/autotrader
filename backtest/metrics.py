"""백테스트 성과 지표 계산.

비용 포함/제외 두 가지로 출력해 비용 영향을 명확히 한다.

사용:
    from backtest.metrics import compute_metrics, MetricsReport

    report = compute_metrics(trades_df)
    print(report.format())
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class MetricsReport:
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_profit: float           # 이긴 거래 평균 손익
    avg_loss: float             # 진 거래 평균 손익 (음수)
    expected_value: float       # 기대값 = 승률×평균이익 + 패율×평균손실
    profit_factor: float        # 총이익 / 총손실 (1 이상 = 합격선)
    total_pnl: int              # 순손익 합계
    max_drawdown: int           # MDD (양수 값으로 표현, 원)
    # 비용 제외 버전 (전략 자체 성과)
    total_pnl_gross: Optional[int] = None
    profit_factor_gross: Optional[float] = None

    def format(self, *, with_gross: bool = True) -> str:
        lines = [
            f"  거래: {self.total_trades}건 (승 {self.wins} / 패 {self.losses})",
            f"  승률: {self.win_rate:.1%}",
            f"  기대값: {self.expected_value:+,.0f}원/거래",
            f"  손익비(비용포함): {self.profit_factor:.2f}",
            f"  순손익: {self.total_pnl:+,}원",
            f"  MDD: {self.max_drawdown:,}원",
        ]
        if with_gross and self.total_pnl_gross is not None:
            lines.append(
                f"  순손익(비용제외): {self.total_pnl_gross:+,}원"
                f"  손익비(비용제외): {self.profit_factor_gross:.2f}"
            )
        return "\n".join(lines)


def compute_metrics(
    trades: pd.DataFrame,
    pnl_col: str = "pnl",
    gross_col: Optional[str] = "gross_pnl",
) -> MetricsReport:
    """거래 DataFrame → MetricsReport.

    trades 컬럼 필수: pnl (비용 포함 손익), 선택: gross_pnl (비용 제외)
    """
    if trades.empty:
        return MetricsReport(
            total_trades=0, wins=0, losses=0, win_rate=0.0,
            avg_profit=0.0, avg_loss=0.0, expected_value=0.0,
            profit_factor=float("inf"), total_pnl=0, max_drawdown=0,
        )

    pnl = trades[pnl_col]
    wins_mask = pnl > 0
    loss_mask = pnl <= 0

    total = len(pnl)
    wins = wins_mask.sum()
    losses = loss_mask.sum()
    win_rate = wins / total if total > 0 else 0.0

    avg_profit = float(pnl[wins_mask].mean()) if wins > 0 else 0.0
    avg_loss   = float(pnl[loss_mask].mean()) if losses > 0 else 0.0

    loss_rate = 1 - win_rate
    expected_value = win_rate * avg_profit + loss_rate * avg_loss

    total_gain = float(pnl[wins_mask].sum())
    total_loss = abs(float(pnl[loss_mask].sum()))
    profit_factor = total_gain / total_loss if total_loss > 0 else float("inf")

    total_pnl = int(pnl.sum())

    # MDD 계산
    cumulative = pnl.cumsum()
    rolling_max = cumulative.cummax()
    drawdown = rolling_max - cumulative
    max_dd = int(drawdown.max()) if not drawdown.empty else 0

    # 비용 제외 버전
    total_pnl_gross = None
    profit_factor_gross = None
    if gross_col and gross_col in trades.columns:
        gpnl = trades[gross_col]
        total_pnl_gross = int(gpnl.sum())
        g_gain = float(gpnl[gpnl > 0].sum())
        g_loss = abs(float(gpnl[gpnl <= 0].sum()))
        profit_factor_gross = g_gain / g_loss if g_loss > 0 else float("inf")

    return MetricsReport(
        total_trades=total,
        wins=int(wins),
        losses=int(losses),
        win_rate=win_rate,
        avg_profit=avg_profit,
        avg_loss=avg_loss,
        expected_value=expected_value,
        profit_factor=profit_factor,
        total_pnl=total_pnl,
        max_drawdown=max_dd,
        total_pnl_gross=total_pnl_gross,
        profit_factor_gross=profit_factor_gross,
    )
