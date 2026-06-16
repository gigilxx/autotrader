"""KOSPI + KOSDAQ 종목 마스터 JSON 생성 스크립트.

pykrx 라이브러리와 KRX 자격증명(KRX_ID, KRX_PW)을 사용해
전 종목 정보를 받아 JSON으로 갱신한다. T12 자동완성 기능에서 사용.

사용법:
    KRX_ID=아이디 KRX_PW=비밀번호 python scripts/build_stock_master.py

출력: data/stock_master.json
형식: [{"code": "005930", "name": "삼성전자", "market": "KOSPI"}, ...]

참고:
    pykrx 1.2.8+ 은 KRX 계정(data.krx.co.kr) 로그인이 필요합니다.
    자격증명 없이 실행하면 data/stock_master.json 에 기존 시드 데이터가
    유지됩니다 (이미 주요 종목 ~180개 포함).
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

OUTPUT = Path(__file__).parent.parent / "data" / "stock_master.json"


def get_recent_trading_day() -> str:
    """가장 최근 거래일(월~금)을 YYYYMMDD 형식으로 반환."""
    d = date.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def build() -> None:
    if not os.getenv("KRX_ID") or not os.getenv("KRX_PW"):
        print(
            "KRX_ID/KRX_PW env not set - skipping full refresh.\n"
            f"Seed data retained: {OUTPUT}"
        )
        return

    try:
        from pykrx import stock
    except ImportError:
        print("pykrx 미설치: pip install pykrx")
        raise SystemExit(1)

    base_date = get_recent_trading_day()
    print(f"기준일: {base_date}")

    results: list[dict] = []
    for market in ("KOSPI", "KOSDAQ"):
        try:
            tickers = stock.get_market_ticker_list(base_date, market=market)
            for code in tickers:
                try:
                    name = stock.get_market_ticker_name(code)
                    results.append({"code": code, "name": name, "market": market})
                except Exception as e:
                    print(f"  {code} 이름 조회 실패: {e}")
            print(f"{market}: {len(tickers)}개 로드")
        except Exception as e:
            print(f"{market} 목록 조회 실패: {e}")

    if not results:
        print("종목 데이터 없음 — 기존 파일 유지")
        return

    results.sort(key=lambda x: x["code"])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장 완료: {OUTPUT} ({len(results)}개 종목)")


if __name__ == "__main__":
    build()
