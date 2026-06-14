"""한국투자증권(KIS) Open API 실제 연동 구현.

한투 공식 저장소(koreainvestment/open-trading-api)의 샘플 코드 기준으로 작성.
execution.Broker 프로토콜(get_account, send_order)을 만족하며, 현재가 조회도 제공.

⚠️ 검증 안내:
- 엔드포인트·tr_id·도메인·호출제한은 공식 저장소(2025~2026 기준)에서 확인했으나,
  KIS는 사양을 예고 없이 바꿀 수 있으니 운영 전 공식 문서로 재확인할 것.
- 응답 필드명(stck_prpr, dnca_tot_amt, hldg_qty 등)은 표준값을 사용했으나,
  실제 모의계좌 응답으로 한 번 찍어보고 확정하는 것을 강력 권장(아래 주석의 # VERIFY).
- 보안: appkey/appsecret/계좌번호는 절대 하드코딩하지 말고 환경변수/파일로 주입.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests

from .models import AccountSnapshot, DailyBar, Environment, OrderRequest, Position, Quote, Side

# 공식 저장소 기준 도메인
_PROD_URL = "https://openapi.koreainvestment.com:9443"   # 실전
_VPS_URL = "https://openapivts.koreainvestment.com:29443"  # 모의

# 호출 최소 간격(초) — 공식 코드: 모의 0.5s, 실전 0.05s
_MIN_INTERVAL = {Environment.REAL: 0.05, Environment.MOCK: 0.5}


class KISError(Exception):
    """KIS API 호출 실패. 호출부에서 잡아 HealthMonitor.record_api_error()로 연결 권장."""


@dataclass
class KISCredentials:
    appkey: str
    appsecret: str
    cano: str          # 종합계좌번호 앞 8자리
    acnt_prdt_cd: str  # 계좌상품코드 뒤 2자리 (위탁계좌 보통 "01")
    env: Environment = Environment.MOCK  # 기본 모의


class KISBroker:
    def __init__(self, creds: KISCredentials) -> None:
        self.creds = creds
        self.base_url = _PROD_URL if creds.env == Environment.REAL else _VPS_URL
        self._token: Optional[str] = None
        self._token_expire: datetime = datetime.min
        self._last_call = 0.0
        self._lock = threading.Lock()

    # ---------------- 인증 ----------------
    def _ensure_token(self) -> str:
        """토큰 발급/캐시. 만료 임박 시 재발급.

        ⚠️ KIS는 토큰 발급도 빈도 제한이 있으니 자주 재발급하지 말 것
        (운영 시 토큰을 파일/DB에 캐시해 프로세스 재시작에도 재사용 권장).
        """
        if self._token and datetime.now() < self._token_expire:
            return self._token

        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.creds.appkey,
            "appsecret": self.creds.appsecret,
        }
        try:
            r = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
        except requests.RequestException as e:
            raise KISError(f"토큰 요청 실패: {e}") from e

        if r.status_code != 200:
            raise KISError(f"토큰 발급 실패: {r.status_code} {r.text}")

        data = r.json()
        self._token = data["access_token"]
        # expires_in(초) 기준, 5분 여유를 두고 만료 처리
        expires_in = int(data.get("expires_in", 86400))
        self._token_expire = datetime.now() + timedelta(seconds=expires_in - 300)
        return self._token

    def _headers(self, tr_id: str) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "authorization": f"Bearer {self._ensure_token()}",
            "appkey": self.creds.appkey,
            "appsecret": self.creds.appsecret,
            "tr_id": tr_id,
            "custtype": "P",  # 개인
        }

    def _throttle(self) -> None:
        """호출 최소 간격 보장(레이트 리밋)."""
        with self._lock:
            min_gap = _MIN_INTERVAL[self.creds.env]
            elapsed = time.monotonic() - self._last_call
            if elapsed < min_gap:
                time.sleep(min_gap - elapsed)
            self._last_call = time.monotonic()

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        self._throttle()
        try:
            r = requests.get(f"{self.base_url}{path}", headers=self._headers(tr_id),
                             params=params, timeout=10)
        except requests.RequestException as e:
            raise KISError(f"GET 실패 {path}: {e}") from e
        if r.status_code != 200:
            raise KISError(f"GET {path} 실패: {r.status_code} {r.text}")
        return r.json()

    def _post(self, path: str, tr_id: str, body: dict) -> dict:
        self._throttle()
        try:
            r = requests.post(f"{self.base_url}{path}", headers=self._headers(tr_id),
                              data=json.dumps(body), timeout=10)
        except requests.RequestException as e:
            raise KISError(f"POST 실패 {path}: {e}") from e
        if r.status_code != 200:
            raise KISError(f"POST {path} 실패: {r.status_code} {r.text}")
        return r.json()

    # ---------------- 현재가 / 일봉 ----------------
    def get_quote(self, symbol: str) -> Quote:
        """현재가 스냅샷(현재가·당일 시가·고저). tr_id FHKST01010100 (실전/모의 동일).

        VERIFY: 출력 필드 stck_prpr(현재가)/stck_oprc(시가)/stck_hgpr(고가)/stck_lwpr(저가).
        """
        path = "/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol}
        o = self._get(path, "FHKST01010100", params)["output"]
        return Quote(
            price=int(o["stck_prpr"]),
            open=int(o["stck_oprc"]),
            high=int(o["stck_hgpr"]),
            low=int(o["stck_lwpr"]),
        )

    def get_current_price(self, symbol: str) -> int:
        """현재가(원)만 필요할 때."""
        return self.get_quote(symbol).price

    def get_daily_bars(self, symbol: str, adj: str = "0") -> list[DailyBar]:
        """최근 일봉 목록(보통 최신이 앞). tr_id FHKST01010400.

        VERIFY: 출력 리스트 필드 stck_bsop_date/stck_oprc/stck_hgpr/stck_lwpr/stck_clpr,
        정렬 순서(최신 우선 여부)도 실응답으로 확인할 것.
        """
        path = "/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_PERIOD_DIV_CODE": "D",  # D:일 / W:주 / M:월
            "FID_ORG_ADJ_PRC": adj,      # 0:수정주가, 1:원주가 (VERIFY)
        }
        rows = self._get(path, "FHKST01010400", params).get("output", [])
        bars: list[DailyBar] = []
        for r in rows:
            bars.append(DailyBar(
                date=r.get("stck_bsop_date", ""),
                open=int(r.get("stck_oprc", "0")),
                high=int(r.get("stck_hgpr", "0")),
                low=int(r.get("stck_lwpr", "0")),
                close=int(r.get("stck_clpr", "0")),
            ))
        return bars

    # ---------------- 잔고 ----------------
    def get_account(self) -> AccountSnapshot:
        """주식잔고조회 → AccountSnapshot.

        tr_id: 실전 TTTC8434R / 모의 VTTC8434R.
        ⚠️ output1=보유종목, output2=계좌요약. 종목 많으면 연속조회(tr_cont) 필요(미구현).
        """
        path = "/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = "TTTC8434R" if self.creds.env == Environment.REAL else "VTTC8434R"
        params = {
            "CANO": self.creds.cano,
            "ACNT_PRDT_CD": self.creds.acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",   # 종목별
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        data = self._get(path, tr_id, params)

        # VERIFY: output2의 예수금총금액 필드 dnca_tot_amt
        out2 = data.get("output2") or [{}]
        cash = int(float(out2[0].get("dnca_tot_amt", "0")))

        positions: dict[str, Position] = {}
        for row in data.get("output1", []):
            # VERIFY: pdno(종목코드), hldg_qty(보유수량), pchs_avg_pric(매입평균가)
            qty = int(float(row.get("hldg_qty", "0")))
            if qty <= 0:
                continue
            symbol = row["pdno"]
            positions[symbol] = Position(
                symbol=symbol,
                qty=qty,
                avg_price=float(row.get("pchs_avg_pric", "0")),
            )
        return AccountSnapshot(cash=cash, positions=positions)

    # ---------------- 주문 ----------------
    def send_order(self, order: OrderRequest) -> bool:
        """현금 주문. 성공 시 True.

        tr_id: 매수 실전 TTTC0012U/모의 VTTC0012U, 매도 실전 TTTC0011U/모의 VTTC0011U.
        ORD_DVSN: 00=지정가, 01=시장가(VERIFY). 지정가면 ORD_UNPR=가격, 시장가면 "0".
        """
        is_buy = order.side == Side.BUY
        if self.creds.env == Environment.REAL:
            tr_id = "TTTC0012U" if is_buy else "TTTC0011U"
        else:
            tr_id = "VTTC0012U" if is_buy else "VTTC0011U"

        if order.price is None:
            ord_dvsn, ord_unpr = "01", "0"   # 시장가 (VERIFY: 01=시장가)
        else:
            ord_dvsn, ord_unpr = "00", str(order.price)  # 지정가

        body = {
            "CANO": self.creds.cano,
            "ACNT_PRDT_CD": self.creds.acnt_prdt_cd,
            "PDNO": order.symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(order.qty),
            "ORD_UNPR": ord_unpr,
            "EXCG_ID_DVSN_CD": "KRX",
            "SLL_TYPE": "" if is_buy else "01",  # 매도 시 01:일반매도
            "CNDT_PRIC": "",
        }
        data = self._post("/uapi/domestic-stock/v1/trading/order-cash", tr_id, body)

        # rt_cd "0" = 정상
        if str(data.get("rt_cd")) != "0":
            raise KISError(f"주문 거부: {data.get('msg_cd')} {data.get('msg1')}")
        return True


import os


def credentials_from_env() -> KISCredentials:
    """환경변수에서 자격증명 로드. (코드/깃에 키를 절대 넣지 말 것)

    필요한 환경변수:
      KIS_APPKEY, KIS_APPSECRET, KIS_CANO(8자리), KIS_ACNT_PRDT_CD(2자리, 예 "01")
      KIS_ENV = "mock"(기본) | "real"
    """
    env = Environment.REAL if os.getenv("KIS_ENV", "mock").lower() == "real" else Environment.MOCK
    missing = [k for k in ("KIS_APPKEY", "KIS_APPSECRET", "KIS_CANO", "KIS_ACNT_PRDT_CD")
               if not os.getenv(k)]
    if missing:
        raise KISError(f"환경변수 누락: {', '.join(missing)}")
    return KISCredentials(
        appkey=os.environ["KIS_APPKEY"],
        appsecret=os.environ["KIS_APPSECRET"],
        cano=os.environ["KIS_CANO"],
        acnt_prdt_cd=os.environ["KIS_ACNT_PRDT_CD"],
        env=env,
    )
