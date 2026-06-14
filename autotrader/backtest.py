"""변동성 돌파 전략 백테스트.

KIS REST API로 일봉 데이터를 가져와 전략 성과를 계산한다.
비용(수수료+세금)을 반드시 반영한다.

사용:
  # 단일 종목, k 그리드
  python -m autotrader.backtest --symbol 005930 --k 0.3,0.5,0.7

  # 다종목 동시 비교 (쉼표 구분)
  python -m autotrader.backtest --symbol 005930,000660,005380 --k 0.5

  # 기간·자본 지정 + CSV 저장
  python -m autotrader.backtest --symbol 005930 --k 0.5 --days 120 --csv result.csv

체결 가정: 당일 고가 >= 목표가이면 목표가에 체결 (최선 가정).
실제 슬리피지는 다를 수 있으므로 모의 검증 필수.
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from typing import Optional

from .config import CostConfig
from .costs import net_pnl
from .models import DailyBar
from .volatility_breakout import compute_target_price, stop_price_of


@dataclass
class Trade:
    date: str
    symbol: str
    entry: float
    exit: float
    qty: int
    pnl: int
    reason: str  # "stop_loss" | "eod_close"


@dataclass
class BacktestResult:
    symbol: str
    k: float
    total_trades: int
    wins: int
    losses: int
    gross_pnl: int
    net_pnl_total: int
    max_drawdown: int
    win_rate: float
    profit_factor: float
    trades: list[Trade] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"[{self.symbol}] k={self.k}\n"
            f"  거래 횟수: {self.total_trades} (승 {self.wins} / 패 {self.losses})\n"
            f"  승률: {self.win_rate:.1%}\n"
            f"  순손익(비용포함): {self.net_pnl_total:,}원\n"
            f"  최대 낙폭(MDD): {self.max_drawdown:,}원\n"
            f"  손익비: {self.profit_factor:.2f}\n"
        )


def run_backtest(
    bars: list[DailyBar],
    symbol: str,
    k: float,
    capital: int = 2_500_000,
    stop_loss_pct: float = 0.02,
    risk_per_trade_pct: float = 0.01,
    cost_cfg: Optional[CostConfig] = None,
) -> BacktestResult:
    """일봉 리스트로 백테스트 실행.

    bars: 최신 우선 정렬 (get_daily_bars 기본값). 내부에서 날짜 오름차순으로 뒤집음.
    """
    if cost_cfg is None:
        cost_cfg = CostConfig()

    # 날짜 오름차순 정렬
    sorted_bars = sorted(bars, key=lambda b: b.date)

    trades: list[Trade] = []
    cumulative_pnl = 0
    peak_pnl = 0
    max_dd = 0
    gross_wins = 0
    gross_losses = 0

    risk_won = int(capital * risk_per_trade_pct)

    for i in range(1, len(sorted_bars)):
        prev = sorted_bars[i - 1]
        today = sorted_bars[i]

        if prev.high == 0 or prev.low == 0 or today.open == 0:
            continue

        target = compute_target_price(prev.high, prev.low, today.open, k)
        stop = stop_price_of(int(target), stop_loss_pct)

        # 목표가에 체결 가능한지 확인 (당일 고가 >= 목표가)
        if today.high < target:
            continue  # 돌파 없음

        entry_price = int(target)
        per_share_risk = entry_price - stop
        if per_share_risk <= 0:
            continue

        qty = min(risk_won // per_share_risk, capital // entry_price)
        if qty <= 0:
            continue

        # 손절 vs 종가 청산
        if today.low <= stop:
            exit_price = stop
            reason = "stop_loss"
        else:
            exit_price = today.close
            reason = "eod_close"

        pnl = net_pnl(entry_price, exit_price, qty, cost_cfg)
        trades.append(Trade(
            date=today.date,
            symbol=symbol,
            entry=float(entry_price),
            exit=float(exit_price),
            qty=qty,
            pnl=pnl,
            reason=reason,
        ))

        cumulative_pnl += pnl
        peak_pnl = max(peak_pnl, cumulative_pnl)
        dd = peak_pnl - cumulative_pnl
        max_dd = max(max_dd, dd)

        if pnl > 0:
            gross_wins += 1
        else:
            gross_losses += 1

    total = len(trades)
    win_rate = gross_wins / total if total > 0 else 0.0
    total_gain = sum(t.pnl for t in trades if t.pnl > 0)
    total_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    profit_factor = total_gain / total_loss if total_loss > 0 else float("inf")
    gross_pnl = sum(t.pnl for t in trades)

    return BacktestResult(
        symbol=symbol,
        k=k,
        total_trades=total,
        wins=gross_wins,
        losses=gross_losses,
        gross_pnl=gross_pnl,
        net_pnl_total=gross_pnl,
        max_drawdown=max_dd,
        win_rate=win_rate,
        profit_factor=profit_factor,
        trades=trades,
    )


def save_csv(results: list[BacktestResult], path: str) -> None:
    """거래 내역 전체를 CSV로 저장."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["날짜", "종목", "k", "진입가", "청산가", "수량", "손익(원)", "사유"])
        for r in results:
            for t in r.trades:
                writer.writerow([
                    t.date, t.symbol, r.k,
                    int(t.entry), int(t.exit), t.qty, t.pnl, t.reason,
                ])
    print(f"CSV 저장: {path}")


def print_summary_table(results: list[BacktestResult]) -> None:
    """종목×k 교차 순손익 요약 테이블 출력."""
    symbols = sorted({r.symbol for r in results})
    k_vals  = sorted({r.k for r in results})

    col_w = 14
    header = f"{'종목':>8}" + "".join(f"  k={k:<{col_w-4}}" for k in k_vals)
    print("\n" + "=" * len(header))
    print("순손익(원) 요약")
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    best_overall: Optional[BacktestResult] = None
    for sym in symbols:
        row = f"{sym:>8}"
        for k in k_vals:
            match = next((r for r in results if r.symbol == sym and r.k == k), None)
            if match:
                row += f"  {match.net_pnl_total:>{col_w},}"
                if best_overall is None or match.net_pnl_total > best_overall.net_pnl_total:
                    best_overall = match
            else:
                row += f"  {'N/A':>{col_w}}"
        print(row)

    print("=" * len(header))
    if best_overall:
        print(
            f"최고 성과: {best_overall.symbol}  k={best_overall.k}"
            f"  순손익 {best_overall.net_pnl_total:,}원"
            f"  승률 {best_overall.win_rate:.1%}"
            f"  MDD {best_overall.max_drawdown:,}원"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="변동성 돌파 전략 백테스트")
    parser.add_argument("--symbol", default="005930",
                        help="종목코드, 쉼표 구분 가능 (예: 005930,000660)")
    parser.add_argument("--k", default="0.5",
                        help="돌파 계수, 쉼표 구분 가능 (예: 0.3,0.5,0.7)")
    parser.add_argument("--days", type=int, default=120,
                        help="백테스트 기간(거래일 수, 기본 120)")
    parser.add_argument("--capital", type=int, default=2_500_000,
                        help="운용 자본(원, 기본 250만)")
    parser.add_argument("--csv", default="",
                        help="거래 내역 CSV 저장 경로 (예: result.csv)")
    args = parser.parse_args()

    from .kis_broker import credentials_from_env, KISBroker, KISError

    try:
        creds = credentials_from_env()
    except KISError as e:
        print(f"환경변수 오류: {e}")
        print("  .env 파일을 확인하세요 (.env.example 참고)")
        sys.exit(1)

    broker = KISBroker(creds)
    symbols  = [s.strip() for s in args.symbol.split(",") if s.strip()]
    k_values = [float(k.strip()) for k in args.k.split(",") if k.strip()]

    all_results: list[BacktestResult] = []

    for sym in symbols:
        print(f"\n[{sym}] 일봉 데이터 조회 중...", end=" ", flush=True)
        try:
            bars = broker.get_daily_bars(sym)
        except KISError as e:
            print(f"실패: {e}")
            continue

        sorted_bars = sorted(bars, key=lambda b: b.date)[-args.days:]
        print(f"{sorted_bars[0].date} ~ {sorted_bars[-1].date} ({len(sorted_bars)}거래일)")

        for k in k_values:
            result = run_backtest(sorted_bars, sym, k, args.capital)
            all_results.append(result)
            print(result.summary())

    if not all_results:
        print("결과 없음.")
        sys.exit(1)

    if len(symbols) > 1 or len(k_values) > 1:
        print_summary_table(all_results)

    if args.csv:
        save_csv(all_results, args.csv)


if __name__ == "__main__":
    main()
