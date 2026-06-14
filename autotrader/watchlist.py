"""대상 종목 선정.

전략:
  1. 코스피200 구성 종목 중 변동성 돌파에 유리한 종목을 고른다.
  2. 유동성 기준: 평균 거래대금 상위 + 변동폭(일 변동률) 적당한 종목.
  3. KIS API 없이도 KOSPI200_BASE 상수로 즉시 시작 가능.

사용:
  from autotrader.watchlist import top_by_volume, KOSPI200_BASE

  # KIS 연결 전 — 하드코딩 목록에서 직접 고르기
  symbols = KOSPI200_BASE[:5]

  # KIS 연결 후 — 거래량 기준 자동 선별
  from autotrader.kis_broker import KISBroker, credentials_from_env
  broker = KISBroker(credentials_from_env())
  symbols = top_by_volume(broker, n=3)
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("autotrader.watchlist")

# 코스피200 대형주 중 변동성 돌파에 자주 쓰이는 유동성 우량 종목
# (거래대금 상위, 스프레드 좁음, 시총 충분) — 운영 전 직접 검토 권장
KOSPI200_BASE: list[str] = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "005380",  # 현대차
    "035420",  # NAVER
    "051910",  # LG화학
    "006400",  # 삼성SDI
    "068270",  # 셀트리온
    "105560",  # KB금융
    "055550",  # 신한지주
    "003550",  # LG
    "012330",  # 현대모비스
    "096770",  # SK이노베이션
    "028260",  # 삼성물산
    "066570",  # LG전자
    "017670",  # SK텔레콤
    "030200",  # KT
    "011170",  # 롯데케미칼
    "009150",  # 삼성전기
    "018260",  # 삼성에스디에스
    "000270",  # 기아
]

# 변동성 돌파에서 피해야 할 특성
# - 평균 거래대금 < 100억: 슬리피지 큼
# - 일 변동폭 < 0.5%: 목표가가 당일 시가에 너무 가까워 의미 없음
# - 일 변동폭 > 5%: 갭·VI 위험
_MIN_VOLUME_WON = 10_000_000_000   # 평균 거래대금 최소 100억
_MIN_RANGE_PCT  = 0.005             # 일 평균 변동폭 최소 0.5%
_MAX_RANGE_PCT  = 0.05              # 일 평균 변동폭 최대 5%


def top_by_volume(
    broker,
    candidates: Optional[list[str]] = None,
    n: int = 3,
    lookback: int = 20,
) -> list[str]:
    """최근 lookback 거래일 평균 거래대금 상위 n개 종목 반환.

    Args:
        broker: KISBroker 인스턴스 (KIS API 연결 필요)
        candidates: 검색 대상 종목 목록 (None이면 KOSPI200_BASE 전체)
        n: 반환할 종목 수
        lookback: 평균 계산에 사용할 거래일 수

    Returns:
        유동성 필터를 통과한 상위 n개 종목코드 리스트.
        API 오류 시 빈 리스트 반환 (호출부에서 폴백 처리 필요).
    """
    if candidates is None:
        candidates = KOSPI200_BASE

    scores: list[tuple[str, float]] = []

    for sym in candidates:
        try:
            bars = broker.get_daily_bars(sym)
            recent = bars[:lookback]
            if len(recent) < 5:
                continue

            avg_volume_won = _avg_volume_won(recent)
            avg_range_pct  = _avg_range_pct(recent)

            if avg_volume_won < _MIN_VOLUME_WON:
                logger.debug("%s 제외: 거래대금 %.0f억", sym, avg_volume_won / 1e8)
                continue
            if not (_MIN_RANGE_PCT <= avg_range_pct <= _MAX_RANGE_PCT):
                logger.debug("%s 제외: 변동폭 %.2f%%", sym, avg_range_pct * 100)
                continue

            scores.append((sym, avg_volume_won))
            logger.info("%s 통과: 거래대금 %.0f억, 변동폭 %.2f%%",
                        sym, avg_volume_won / 1e8, avg_range_pct * 100)
        except Exception as e:  # noqa: BLE001
            logger.warning("종목 %s 조회 실패: %s", sym, e)

    scores.sort(key=lambda x: x[1], reverse=True)
    result = [sym for sym, _ in scores[:n]]

    if not result:
        logger.warning("유동성 필터 통과 종목 없음 — 기본 목록 상위 %d개 사용", n)
        return KOSPI200_BASE[:n]

    return result


def _avg_volume_won(bars) -> float:
    """평균 거래대금(원) = 종가 × 거래량 평균. DailyBar.volume(acml_vol) 사용."""
    pairs = [(b.close, b.volume) for b in bars if b.close > 0 and b.volume > 0]
    if not pairs:
        return 0.0
    return sum(c * v for c, v in pairs) / len(pairs)


def _avg_range_pct(bars) -> float:
    """평균 일 변동폭 = (고가 - 저가) / 저가."""
    ranges = []
    for b in bars:
        if b.low > 0 and b.high > b.low:
            ranges.append((b.high - b.low) / b.low)
    return sum(ranges) / len(ranges) if ranges else 0.0


def print_candidates(broker, n: int = 5) -> None:
    """후보 종목 정보 출력 (수동 검토용)."""
    candidates = KOSPI200_BASE
    print(f"{'종목코드':>8}  {'평균변동폭':>10}  {'비고'}")
    print("-" * 40)
    for sym in candidates[:20]:
        try:
            bars = broker.get_daily_bars(sym)[:20]
            rng = _avg_range_pct(bars) * 100
            vol = _avg_volume_won(bars) / 1e8
            flag = ""
            if not (_MIN_RANGE_PCT * 100 <= rng <= _MAX_RANGE_PCT * 100):
                flag = "변동폭 부적합"
            print(f"{sym:>8}  {rng:>9.2f}%  {vol:>6.0f}억  {flag}")
        except Exception as e:  # noqa: BLE001
            print(f"{sym:>8}  조회 실패: {e}")
