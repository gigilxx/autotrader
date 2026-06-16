"""일일 거래 리포트.

당일 체결 거래를 실시간 수집해 마감 후 집계·전송한다.
TradingEngine이 _exit() 시 ReportCollector.record()를 호출하고,
daily_report() 시 build()로 최종 리포트를 만든다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")


@dataclass
class TradeRecord:
    symbol: str
    entry_price: int
    exit_price: int
    qty: int
    pnl: int
    reason: str
    exit_time: str = field(default_factory=lambda: datetime.now(_KST).strftime("%H:%M:%S"))


@dataclass
class DailyReport:
    report_date: date
    trades: list[TradeRecord] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.pnl <= 0)

    @property
    def total_pnl(self) -> int:
        return sum(t.pnl for t in self.trades)

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def avg_profit(self) -> float:
        profits = [t.pnl for t in self.trades if t.pnl > 0]
        return sum(profits) / len(profits) if profits else 0.0

    @property
    def avg_loss(self) -> float:
        losses = [t.pnl for t in self.trades if t.pnl <= 0]
        return sum(losses) / len(losses) if losses else 0.0

    def format(self) -> str:
        if not self.trades:
            return f"[일일 리포트] {self.report_date}\n  거래 없음"

        lines = [
            f"[일일 리포트] {self.report_date}",
            f"  거래: {self.total_trades}건 (승 {self.wins} / 패 {self.losses})",
            f"  승률: {self.win_rate:.1%}",
            f"  실현 손익: {self.total_pnl:+,}원",
        ]
        if self.avg_profit:
            lines.append(f"  평균 이익: {self.avg_profit:+,.0f}원")
        if self.avg_loss:
            lines.append(f"  평균 손실: {self.avg_loss:+,.0f}원")
        lines.append("  ─────────────────────")
        for t in self.trades:
            sign = "+" if t.pnl > 0 else ""
            lines.append(
                f"  [{t.exit_time}] {t.symbol} {t.qty}주"
                f"  {t.entry_price:,}→{t.exit_price:,}"
                f"  {sign}{t.pnl:,}원 ({t.reason})"
            )
        return "\n".join(lines)


class ReportCollector:
    """당일 거래 내역을 메모리에 수집하고 DailyReport를 생성한다."""

    def __init__(self) -> None:
        self._trades: list[TradeRecord] = []
        self._date: Optional[date] = None

    def reset(self, report_date: date) -> None:
        self._trades.clear()
        self._date = report_date

    def record(self, trade: TradeRecord) -> None:
        self._trades.append(trade)

    def build(self) -> DailyReport:
        return DailyReport(
            report_date=self._date or datetime.now(_KST).date(),
            trades=list(self._trades),
        )
