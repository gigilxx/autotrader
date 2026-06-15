"""시장 필터 — KODEX 200(069500) 기준 코스피 추세 판단.

KODEX 200 종가가 N일 이동평균 위이면 상승 추세(거래 허용),
아래이면 하락/횡보(당일 신규 진입 차단).

prepare_day()에서 1회 호출한다.
데이터 조회 실패 시 거래 허용으로 폴백(봇이 멈추지 않도록).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("autotrader.market_filter")

KODEX200 = "069500"


@dataclass
class MarketFilterResult:
    ok: bool
    current: float
    ma: float
    ma_days: int
    symbol: str

    def summary(self) -> str:
        status = "🟢 상승 추세 (거래 허용)" if self.ok else "🔴 하락/횡보 (진입 차단)"
        return (
            f"시장 필터: {status}\n"
            f"KODEX200: {self.current:,.0f}원\n"
            f"{self.ma_days}일 MA: {self.ma:,.0f}원"
        )


def check_market(
    broker,
    ma_days: int = 20,
    symbol: str = KODEX200,
) -> MarketFilterResult:
    """KODEX 200 종가 기준 시장 추세 판단. 실패 시 ok=True 반환."""
    def _fallback(reason: str) -> MarketFilterResult:
        logger.warning("시장 필터 폴백(허용): %s", reason)
        return MarketFilterResult(ok=True, current=0.0, ma=0.0, ma_days=ma_days, symbol=symbol)

    try:
        bars = broker.get_daily_bars(symbol)
    except Exception as e:
        return _fallback(f"일봉 조회 실패: {e}")

    if not bars:
        return _fallback("일봉 데이터 없음")

    sorted_bars = sorted(bars, key=lambda b: b.date)
    closes = [b.close for b in sorted_bars if b.close > 0]

    if len(closes) < 2:
        return _fallback(f"데이터 부족: {len(closes)}일")

    usable = min(len(closes), ma_days)
    ma = sum(closes[-usable:]) / usable
    current = closes[-1]
    ok = current > ma

    logger.info(
        "시장 필터: KODEX200 %.0f원 / %d일MA %.0f원 → %s",
        current, usable, ma, "허용" if ok else "차단",
    )
    return MarketFilterResult(ok=ok, current=current, ma=ma, ma_days=usable, symbol=symbol)
