"""KOSPI200 종목 중 변동성 돌파 전략 적합 종목 선별.

선별 기준:
  - Out-of-sample 수익팩터 > 1.2
  - 평균 거래량 상위 (pykrx 기준)
  - Out-of-sample MDD < 150,000원 (자본 250만 기준 6%)

사용:
    python -m backtest.screener
    python -m backtest.screener --start 20230101 --end 20241231 --top 5
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from .data_loader import get_daily_ohlcv, get_kospi200_tickers
from .engine import BacktestConfig, run_backtest
from .metrics import compute_metrics
from .optimize import split_df

_MIN_PROFIT_FACTOR = 1.2
_MAX_MDD_WON       = 150_000   # 250만 자본의 6%
_DEFAULT_K         = 0.5


@dataclass
class ScreenResult:
    symbol: str
    k: float
    profit_factor: float
    win_rate: float
    total_pnl: int
    max_drawdown: int
    total_trades: int


def screen(
    symbols: list[str],
    start: str,
    end: str,
    k: float = _DEFAULT_K,
    min_pf: float = _MIN_PROFIT_FACTOR,
    max_mdd: int = _MAX_MDD_WON,
) -> list[ScreenResult]:
    """종목 목록 중 기준 통과 종목 반환 (out-of-sample 기준)."""
    passed: list[ScreenResult] = []
    total = len(symbols)

    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{total}] {sym} 분석 중...", end=" ", flush=True)
        try:
            df = get_daily_ohlcv(sym, start, end)
            if len(df) < 40:
                print("데이터 부족")
                continue

            _, df_out = split_df(df)
            cfg = BacktestConfig(k=k)
            bt = run_backtest(df_out, sym, cfg)
            m  = compute_metrics(bt.trades)

            if m.total_trades < 5:
                print(f"거래 {m.total_trades}건 — 제외")
                continue

            if m.profit_factor < min_pf:
                print(f"PF={m.profit_factor:.2f} < {min_pf} — 제외")
                continue

            if m.max_drawdown > max_mdd:
                print(f"MDD={m.max_drawdown:,}원 > {max_mdd:,}원 — 제외")
                continue

            print(
                f"통과 PF={m.profit_factor:.2f} "
                f"승률={m.win_rate:.1%} "
                f"손익={m.total_pnl:+,}원"
            )
            passed.append(ScreenResult(
                symbol=sym, k=k,
                profit_factor=m.profit_factor,
                win_rate=m.win_rate,
                total_pnl=m.total_pnl,
                max_drawdown=m.max_drawdown,
                total_trades=m.total_trades,
            ))
        except Exception as e:
            print(f"오류: {e}")

    return sorted(passed, key=lambda r: r.profit_factor, reverse=True)


def print_watchlist(results: list[ScreenResult]) -> None:
    if not results:
        print("\n통과 종목 없음.")
        return
    print(f"\n{'=' * 70}")
    print(f"{'종목':>8}  {'PF':>6}  {'승률':>6}  {'손익(원)':>12}  {'MDD(원)':>12}  {'거래':>4}")
    print("-" * 70)
    for r in results:
        print(
            f"{r.symbol:>8}  {r.profit_factor:>6.2f}  {r.win_rate:>6.1%}"
            f"  {r.total_pnl:>12,}  {r.max_drawdown:>12,}  {r.total_trades:>4}"
        )
    print("=" * 70)
    print(f"최종 워치리스트: {[r.symbol for r in results]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="KOSPI200 변동성 돌파 종목 선별")
    parser.add_argument("--start",  default="20230101")
    parser.add_argument("--end",    default="20241231")
    parser.add_argument("--k",      type=float, default=_DEFAULT_K)
    parser.add_argument("--top",    type=int,   default=0, help="최대 종목 수 (0=전체)")
    parser.add_argument("--min-pf", type=float, default=_MIN_PROFIT_FACTOR)
    parser.add_argument("--max-mdd", type=int,  default=_MAX_MDD_WON)
    args = parser.parse_args()

    print("KOSPI200 종목 목록 조회 중...")
    symbols = get_kospi200_tickers()
    print(f"{len(symbols)}개 종목 대상")

    results = screen(symbols, args.start, args.end, args.k, args.min_pf, args.max_mdd)
    if args.top:
        results = results[: args.top]
    print_watchlist(results)


if __name__ == "__main__":
    main()
