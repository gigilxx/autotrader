"""k값 그리드 탐색 + in-sample / out-of-sample 검증.

사용:
    python -m backtest.optimize --symbol 005930 --start 20230101 --end 20241231
    python -m backtest.optimize --symbol 005930,000660 --start 20230101 --end 20241231 --csv result.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .data_loader import get_daily_ohlcv
from .engine import BacktestConfig, BacktestResult, run_backtest
from .metrics import MetricsReport, compute_metrics

K_GRID = [0.3, 0.4, 0.5, 0.6, 0.7]


@dataclass
class OptimizeResult:
    symbol: str
    k: float
    in_sample:  MetricsReport
    out_sample: MetricsReport
    backtest:   BacktestResult


def split_df(df: pd.DataFrame, ratio: float = 2 / 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """날짜 기준으로 in-sample / out-of-sample 분리."""
    n = int(len(df) * ratio)
    return df.iloc[:n].reset_index(drop=True), df.iloc[n:].reset_index(drop=True)


def optimize_symbol(
    symbol: str,
    start: str,
    end: str,
    k_grid: list[float] = K_GRID,
) -> list[OptimizeResult]:
    """단일 종목에 대해 k 그리드 탐색. 결과 리스트 반환."""
    print(f"\n[{symbol}] 데이터 로딩 {start}~{end} ...", end=" ", flush=True)
    df = get_daily_ohlcv(symbol, start, end)
    if df.empty:
        print("데이터 없음")
        return []
    print(f"{len(df)}일")

    df_in, df_out = split_df(df)
    in_period  = f"{df_in['date'].iloc[0]}~{df_in['date'].iloc[-1]}"
    out_period = f"{df_out['date'].iloc[0]}~{df_out['date'].iloc[-1]}"
    print(f"  In-sample: {in_period} ({len(df_in)}일)")
    print(f"  Out-sample: {out_period} ({len(df_out)}일)")

    results = []
    for k in k_grid:
        cfg = BacktestConfig(k=k)
        bt_in  = run_backtest(df_in,  symbol, cfg)
        bt_out = run_backtest(df_out, symbol, cfg)
        m_in   = compute_metrics(bt_in.trades)
        m_out  = compute_metrics(bt_out.trades)

        # out-of-sample 전체 결과도 유지
        bt_full = run_backtest(df, symbol, cfg)

        results.append(OptimizeResult(
            symbol=symbol, k=k,
            in_sample=m_in, out_sample=m_out,
            backtest=bt_full,
        ))
        print(
            f"  k={k:.1f}  IN 손익비={m_in.profit_factor:.2f} 승률={m_in.win_rate:.1%}"
            f"  OUT 손익비={m_out.profit_factor:.2f} 승률={m_out.win_rate:.1%}"
            f"  전체 손익={bt_full.net_pnl_total:+,}원"
        )
    return results


def print_summary(all_results: list[OptimizeResult]) -> Optional[OptimizeResult]:
    """종목×k 교차 테이블 출력. out-of-sample 손익 기준 최적 반환."""
    symbols = sorted({r.symbol for r in all_results})
    k_vals  = sorted({r.k for r in all_results})
    col_w = 14

    header = f"{'종목':>8}" + "".join(f"  k={k:<{col_w-4}}" for k in k_vals)
    print("\n" + "=" * len(header))
    print("Out-of-sample 순손익(원)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    best: Optional[OptimizeResult] = None
    for sym in symbols:
        row = f"{sym:>8}"
        for k in k_vals:
            match = next((r for r in all_results if r.symbol == sym and r.k == k), None)
            if match:
                row += f"  {match.out_sample.total_pnl:>{col_w},}"
                if best is None or match.out_sample.total_pnl > best.out_sample.total_pnl:
                    best = match
            else:
                row += f"  {'N/A':>{col_w}}"
        print(row)
    print("=" * len(header))
    if best:
        print(
            f"최적(out-of-sample): {best.symbol}  k={best.k}"
            f"  손익비={best.out_sample.profit_factor:.2f}"
            f"  전체 손익={best.backtest.net_pnl_total:+,}원"
        )
    return best


def save_csv(all_results: list[OptimizeResult], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["종목", "k", "구분", "거래수", "승률", "손익비", "순손익(원)", "MDD(원)"])
        for r in all_results:
            for label, m in [("in", r.in_sample), ("out", r.out_sample)]:
                w.writerow([r.symbol, r.k, label, m.total_trades,
                             f"{m.win_rate:.1%}", f"{m.profit_factor:.2f}",
                             m.total_pnl, m.max_drawdown])
    print(f"CSV 저장: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="변동성 돌파 k값 최적화")
    parser.add_argument("--symbol", default="005930", help="종목코드, 쉼표 구분")
    parser.add_argument("--start",  default="20230101", help="시작일 YYYYMMDD")
    parser.add_argument("--end",    default="20241231", help="종료일 YYYYMMDD")
    parser.add_argument("--k",      default="", help="탐색할 k값, 쉼표 구분 (기본: 0.3~0.7)")
    parser.add_argument("--csv",    default="", help="결과 CSV 저장 경로")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbol.split(",") if s.strip()]
    k_grid  = [float(k.strip()) for k in args.k.split(",") if k.strip()] or K_GRID

    all_results: list[OptimizeResult] = []
    for sym in symbols:
        try:
            all_results.extend(optimize_symbol(sym, args.start, args.end, k_grid))
        except Exception as e:
            print(f"[{sym}] 오류: {e}")

    if not all_results:
        print("결과 없음.")
        sys.exit(1)

    print_summary(all_results)
    if args.csv:
        save_csv(all_results, args.csv)


if __name__ == "__main__":
    main()
