"""pykrx 기반 OHLCV 데이터 로더.

한국거래소 공식 데이터를 무료로 수집한다 (KIS 계좌 불필요).

사용:
    from backtest.data_loader import get_daily_ohlcv, get_kospi200_tickers

    df = get_daily_ohlcv("005930", "20230101", "20241231")
    print(df.head())
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    from pykrx import stock as _pykrx_stock
    _PYKRX_AVAILABLE = True
except ImportError:
    _PYKRX_AVAILABLE = False
    logger.warning("pykrx 미설치 — pip install pykrx")


def _require_pykrx() -> None:
    if not _PYKRX_AVAILABLE:
        raise ImportError("pykrx가 필요합니다: pip install pykrx")


def get_daily_ohlcv(symbol: str, start: str, end: str) -> pd.DataFrame:
    """종목 일봉 OHLCV DataFrame 반환.

    Args:
        symbol: 종목코드 (예: "005930")
        start:  시작일 YYYYMMDD
        end:    종료일 YYYYMMDD

    Returns:
        컬럼: date(str YYYYMMDD), open, high, low, close, volume (int)
        날짜 오름차순 정렬.
    """
    _require_pykrx()
    try:
        df = _pykrx_stock.get_market_ohlcv(start, end, symbol)
    except Exception as e:
        raise RuntimeError(f"pykrx 데이터 조회 실패 {symbol} [{start}~{end}]: {e}") from e

    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    df = df.reset_index()
    # pykrx 컬럼명 정규화
    col_map = {
        "날짜": "date", "시가": "open", "고가": "high",
        "저가": "low",  "종가": "close", "거래량": "volume",
    }
    df = df.rename(columns=col_map)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(int)
    df = df[["date", "open", "high", "low", "close", "volume"]].sort_values("date").reset_index(drop=True)
    return df


@lru_cache(maxsize=1)
def get_kospi200_tickers() -> list[str]:
    """코스피200 구성 종목 코드 반환 (pykrx, 캐시됨).

    네트워크 실패 시 하드코딩 기본 목록으로 폴백.
    """
    _require_pykrx()
    try:
        tickers = _pykrx_stock.get_index_portfolio_deposit_file("1028")
        if tickers:
            return list(tickers)
    except Exception as e:
        logger.warning("KOSPI200 목록 조회 실패: %s — 기본 목록 사용", e)

    # 폴백: 대형주 30개
    return [
        "005930", "000660", "005380", "035420", "051910",
        "006400", "068270", "105560", "055550", "003550",
        "012330", "096770", "028260", "066570", "017670",
        "030200", "011170", "009150", "018260", "000270",
        "032830", "086790", "003490", "034020", "036460",
        "010130", "047050", "033780", "011200", "024110",
    ]


def get_prev_day_range(symbol: str, date_str: str) -> Optional[tuple[int, int]]:
    """특정 날짜의 전일 고저 반환. 목표가 계산용."""
    _require_pykrx()
    try:
        end = date_str
        # 직전 거래일 확인을 위해 충분한 이전 데이터 조회
        start_ts = pd.Timestamp(date_str) - pd.Timedelta(days=10)
        start = start_ts.strftime("%Y%m%d")
        df = get_daily_ohlcv(symbol, start, end)
        idx = df[df["date"] == date_str].index
        if idx.empty or idx[0] == 0:
            return None
        prev = df.iloc[idx[0] - 1]
        return int(prev["high"]), int(prev["low"])
    except Exception:
        return None
