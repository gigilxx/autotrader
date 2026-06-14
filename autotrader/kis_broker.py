"""한국투자증권(KIS) Open API 실제 연동 구현.

한투 공식 저장소(koreainvestment/open-trading-api)의 샘플 코드 기준으로 작성.
execution.Broker 프로토콜(get_account, send_order)을 만족하며, 현재가 조회도 제공.

응답 필드 확정 기준 (2025~2026 공식 저장소):
  현재가: stck_prpr / stck_oprc / stck_hgpr / stck_lwpr
  일봉: stck_bsop_date / stck_oprc / stck_hgpr / stck_lwpr / stck_clpr (최신 우선 정렬)
  잔고: output2[0].dnca_tot_amt / output1[].pdno / hldg_qty / pchs_avg_pric
  시장가: ORD_DVSN = "01"
  체결조회: tot_ccld_qty / avg_prvs (모의 실응답으로 재확인 권장)

⚠️ KIS는 사양을 예고 없이 바꿀 수 있으니 운영 전 공식 문서로 재확인할 것.
⚠️ 보안: appkey/appsecret/계좌번호는 절대 하드코딩하지 말고 환경변수/파일로 주입.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

from .models import (
    AccountSnapshot, DailyBar, Environment, FilledOrder,
    OrderRequest, Position, Quote, Side,
)

_PROD_URL = "https://openapi.koreainvestment.com:9443"
_VPS_URL  = "https://openapivts.koreainvestment.com:29443"

_MIN_INTERVAL = {Environment.REAL: 0.05, Environment.MOCK: 0.5}

_TOKEN_CACHE_FILE = Path("_token_cache.json")


class KISError(Exception):
    """KIS API 호출 실패. 호출부에서 잡아 HealthMonitor.record_api_error()로 연결 권장."""


@dataclass
class KISCredentials:
    appkey: str
    appsecret: str
    cano: str
    acnt_prdt_cd: str
    env: Environment = Environment.MOCK


class KISBroker:
    def __init__(self, creds: KISCredentials) -> None:
        self.creds = creds
        self.base_url = _PROD_URL if creds.env == Environment.REAL else _VPS_URL
        self._token: Optional[str] = None
        self._token_expire: datetime = datetime.min
        self._last_call = 0.0
        self._lock = threading.Lock()
        self._load_token_cache()

    # ---------------- 토큰 캐시 ----------------
    def _load_token_cache(self) -> None:
        """재시작 시 발급 횟수를 줄이기 위해 파일에서 토큰 로드."""
        try:
            if _TOKEN_CACHE_FILE.exists():
                data = json.loads(_TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
                expire = datetime.fromisoformat(data["expire"])
                if datetime.now() < expire:
                    self._token = data["token"]
                    self._token_expire = expire
        except Exception:
            pass

    def _save_token_cache(self) -> None:
        try:
            _TOKEN_CACHE_FILE.write_text(
                json.dumps({"token": self._token, "expire": self._token_expire.isoformat()}),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ---------------- 인증 ----------------
    def _ensure_token(self) -> str:
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
        expires_in = int(data.get("expires_in", 86400))
        self._token_expire = datetime.now() + timedelta(seconds=expires_in - 300)
        self._save_token_cache()
        return self._token

    def _headers(self, tr_id: str) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "authorization": f"Bearer {self._ensure_token()}",
            "appkey": self.creds.appkey,
            "appsecret": self.creds.appsecret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    def _throttle(self) -> None:
        with self._lock:
            min_gap = _MIN_INTERVAL[self.creds.env]
            elapsed = time.monotonic() - self._last_call
            if elapsed < min_gap:
                time.sleep(min_gap - elapsed)
            self._last_call = time.monotonic()

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        self._throttle()
        try:
            r = requests.get(
                f"{self.base_url}{path}",
                headers=self._headers(tr_id),
                params=params,
                timeout=10,
            )
        except requests.RequestException as e:
            raise KISError(f"GET 실패 {path}: {e}") from e
        if r.status_code != 200:
            raise KISError(f"GET {path} 실패: {r.status_code} {r.text}")
        return r.json()

    def _post(self, path: str, tr_id: str, body: dict) -> dict:
        self._throttle()
        try:
            r = requests.post(
                f"{self.base_url}{path}",
                headers=self._headers(tr_id),
                data=json.dumps(body),
                timeout=10,
            )
        except requests.RequestException as e:
            raise KISError(f"POST 실패 {path}: {e}") from e
        if r.status_code != 200:
            raise KISError(f"POST {path} 실패: {r.status_code} {r.text}")
        return r.json()

    # ---------------- 현재가 / 일봉 ----------------
    def get_quote(self, symbol: str) -> Quote:
        """현재가 스냅샷. tr_id FHKST01010100 (실전/모의 동일).

        필드 확정: stck_prpr(현재가) / stck_oprc(시가) / stck_hgpr(고가) / stck_lwpr(저가)
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
        return self.get_quote(symbol).price

    def get_daily_bars(self, symbol: str, adj: str = "0") -> list[DailyBar]:
        """최근 일봉 목록. tr_id FHKST01010400.

        정렬: 최신 우선(내림차순). index[0] = 오늘 또는 가장 최근 거래일.
        필드 확정: stck_bsop_date / stck_oprc / stck_hgpr / stck_lwpr / stck_clpr
        adj: "0"=수정주가, "1"=원주가.
        """
        path = "/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": adj,
        }
        rows = self._get(path, "FHKST01010400", params).get("output", [])
        bars: list[DailyBar] = []
        for row in rows:
            bars.append(DailyBar(
                date=row.get("stck_bsop_date", ""),
                open=int(row.get("stck_oprc", "0") or "0"),
                high=int(row.get("stck_hgpr", "0") or "0"),
                low=int(row.get("stck_lwpr", "0") or "0"),
                close=int(row.get("stck_clpr", "0") or "0"),
                volume=int(row.get("acml_vol", "0") or "0"),  # 누적 거래량(주)
            ))
        return bars

    # ---------------- 잔고 ----------------
    def get_account(self) -> AccountSnapshot:
        """주식잔고조회. tr_id: 실전 TTTC8434R / 모의 VTTC8434R.

        output1 = 보유종목 목록, output2 = 계좌요약(예수금).
        필드 확정: dnca_tot_amt / pdno / hldg_qty / pchs_avg_pric
        ⚠️ 보유종목이 많으면 연속조회(tr_cont) 필요(현재 미구현, 소규모 계좌 가정).
        """
        path = "/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = "TTTC8434R" if self.creds.env == Environment.REAL else "VTTC8434R"
        params = {
            "CANO": self.creds.cano,
            "ACNT_PRDT_CD": self.creds.acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        data = self._get(path, tr_id, params)

        out2 = data.get("output2") or [{}]
        cash = int(float(out2[0].get("dnca_tot_amt", "0") or "0"))

        positions: dict[str, Position] = {}
        for row in data.get("output1", []):
            qty = int(float(row.get("hldg_qty", "0") or "0"))
            if qty <= 0:
                continue
            symbol = row["pdno"]
            positions[symbol] = Position(
                symbol=symbol,
                qty=qty,
                avg_price=float(row.get("pchs_avg_pric", "0") or "0"),
            )
        return AccountSnapshot(cash=cash, positions=positions)

    # ---------------- 주문 ----------------
    def send_order(self, order: OrderRequest) -> str:
        """현금 주문 전송. 성공 시 KIS 주문번호(ODNO) 반환.

        tr_id: 매수 실전 TTTC0012U / 모의 VTTC0012U
               매도 실전 TTTC0011U / 모의 VTTC0011U
        ORD_DVSN: 00=지정가, 01=시장가
        """
        is_buy = order.side == Side.BUY
        if self.creds.env == Environment.REAL:
            tr_id = "TTTC0012U" if is_buy else "TTTC0011U"
        else:
            tr_id = "VTTC0012U" if is_buy else "VTTC0011U"

        if order.price is None:
            ord_dvsn, ord_unpr = "01", "0"
        else:
            ord_dvsn, ord_unpr = "00", str(order.price)

        body = {
            "CANO": self.creds.cano,
            "ACNT_PRDT_CD": self.creds.acnt_prdt_cd,
            "PDNO": order.symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(order.qty),
            "ORD_UNPR": ord_unpr,
            "EXCG_ID_DVSN_CD": "KRX",
            "SLL_TYPE": "" if is_buy else "01",
            "CNDT_PRIC": "",
        }
        data = self._post("/uapi/domestic-stock/v1/trading/order-cash", tr_id, body)

        if str(data.get("rt_cd")) != "0":
            raise KISError(f"주문 거부: {data.get('msg_cd')} {data.get('msg1')}")

        return data.get("output", {}).get("ODNO", "")

    # ---------------- 체결 조회 ----------------
    def get_order_fill(self, odno: str, symbol: str) -> FilledOrder:
        """주문번호로 체결 내역 조회. 미체결이면 filled_qty=0 반환.

        tr_id: 실전 TTTC8001R / 모의 VTTC8001R (당일 체결 내역 조회)
        ⚠️ 모의계좌 실응답으로 tot_ccld_qty / avg_prvs 필드 재확인 권장.
        """
        path = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        tr_id = "TTTC8001R" if self.creds.env == Environment.REAL else "VTTC8001R"
        params = {
            "CANO": self.creds.cano,
            "ACNT_PRDT_CD": self.creds.acnt_prdt_cd,
            "INQR_STRT_DT": datetime.now().strftime("%Y%m%d"),
            "INQR_END_DT":  datetime.now().strftime("%Y%m%d"),
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": symbol,
            "CCLD_DVSN": "01",
            "ORD_GNO_BRNO": "",
            "ODNO": odno,
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        try:
            data = self._get(path, tr_id, params)
        except KISError:
            return FilledOrder(odno=odno, filled_qty=0, avg_price=0.0, status="pending")

        rows = data.get("output1", [])
        if not rows:
            return FilledOrder(odno=odno, filled_qty=0, avg_price=0.0, status="pending")

        filled_qty = int(float(rows[0].get("tot_ccld_qty", "0") or "0"))
        avg_price  = float(rows[0].get("avg_prvs", "0") or "0")
        ord_qty    = int(float(rows[0].get("ord_qty", str(filled_qty)) or str(filled_qty)))

        if filled_qty <= 0:
            status = "pending"
        elif filled_qty < ord_qty:
            status = "partial"
        else:
            status = "filled"

        return FilledOrder(odno=odno, filled_qty=filled_qty, avg_price=avg_price, status=status)

    def get_order_status(self, order_no: str, symbol: str) -> FilledOrder:
        """주문번호로 체결 상태 조회. get_order_fill의 별칭(동일 엔드포인트).

        ⚠️ VERIFY: KIS 공식 저장소 examples_llm/domestic_stock/inquire_ccnl/ 기준 확인 권장.
            tot_ccld_qty / avg_prvs 필드는 모의계좌 실응답으로 재확인 필요.
        """
        return self.get_order_fill(order_no, symbol)

    def wait_for_fill(self, odno: str, symbol: str, expected_qty: int,
                      max_wait: float = 3.0) -> FilledOrder:
        """체결 확인 폴링. 최대 max_wait초 대기 후 현재 체결 상태 반환."""
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            fill = self.get_order_fill(odno, symbol)
            if fill.filled_qty > 0:
                return fill
            time.sleep(1.0)
        return self.get_order_fill(odno, symbol)


def credentials_from_env() -> KISCredentials:
    """환경변수에서 자격증명 로드. (코드/깃에 키를 절대 넣지 말 것)"""
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
