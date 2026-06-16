"""FastAPI 백엔드 — 봇 상태 API + 킬스위치.

봇 프로세스와 SQLite(state.db)를 공유하므로 별도 프로세스로 실행한다.

실행:
    uvicorn ui.api.main:app --host 0.0.0.0 --port 8000 --reload

엔드포인트:
    GET  /status                봇 상태
    GET  /positions             현재 보유 포지션
    GET  /pnl/today             오늘 손익·거래횟수·남은 한도
    GET  /trades                오늘 거래 내역
    GET  /logs?n=50             최근 로그 N줄
    GET  /watchlist             관심종목 목록
    POST /watchlist             관심종목 변경  (Bearer 인증)
    GET  /market-filter         시장 필터 상태 (KODEX200 vs MA)
    GET  /config/k              k값 조회
    POST /config/k              k값 변경  (Bearer 인증)
    POST /positions/{sym}/enter 강제 진입  (Bearer 인증)
    POST /kill                  킬스위치 작동  (Bearer 인증)
    POST /resume                킬스위치 해제  (Bearer 인증)
    WS   /ws/status             상태 실시간 스트림 (10초 간격)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from autotrader.state import StateManager

_DB_PATH          = Path(os.getenv("STATE_DB", "state.db"))
_LOG_PATH         = Path(os.getenv("LOG_FILE", "logs/autotrader.log"))
_IMPORTANT_LOG    = Path(os.getenv("IMPORTANT_LOG", "logs/important.log"))
_SECRET_KEY       = os.getenv("UI_SECRET_KEY", "")
_KIS_ENV          = os.getenv("KIS_ENV", "mock").lower()
_MAX_WATCHLIST    = 4 if _KIS_ENV != "real" else 40
_sm               = StateManager(_DB_PATH)
_STOCK_MASTER_PATH = Path(__file__).parent.parent.parent / "data" / "stock_master.json"

app = FastAPI(title="AutoTrader API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 개발용 — 배포 시 특정 도메인으로 제한
    allow_methods=["*"],
    allow_headers=["*"],
)

_bearer = HTTPBearer(auto_error=False)


def _today_str() -> str:
    return date.today().strftime("%Y%m%d")


# ─── 인증 ──────────────────────────────────────────────────
def _require_auth(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    if not _SECRET_KEY:
        return  # SECRET_KEY 미설정 시 인증 생략 (개발용)
    if creds is None or creds.credentials != _SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="인증 실패")


# ─── 상태 조회 ─────────────────────────────────────────────
def _get_status_dict() -> dict:
    today = _today_str()
    try:
        today_d = date.fromisoformat(f"{today[:4]}-{today[4:6]}-{today[6:]}")
        ds = _sm.load_daily_state(today_d)
        positions = _sm.load_positions(today_d)
        is_killed = _sm.is_kill_active()
        return {
            "date": today,
            "is_killed": is_killed,
            "trades_today": ds.trades_today,
            "realized_pnl": ds.realized_pnl_today,
            "position_count": len(positions),
            "positions": [{"symbol": p.symbol, "entry_price": p.entry_price, "qty": p.qty} for p in positions],
        }
    except Exception as e:
        return {"error": str(e)}


@lru_cache(maxsize=1)
def _load_stock_master() -> list[dict]:
    try:
        return json.loads(_STOCK_MASTER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


# ─── 종목 검색 ────────────────────────────────────────────
@app.get("/stocks/search")
def search_stocks(q: str = "") -> dict:
    q = q.strip()
    if not q:
        return {"stocks": []}
    stocks = _load_stock_master()
    q_lower = q.lower()
    results = [
        s for s in stocks
        if q_lower in s["code"] or q_lower in s["name"].lower()
    ]
    return {"stocks": results[:20]}


@app.get("/stocks/info")
def get_stocks_info(codes: str = "") -> dict:
    """쉼표 구분 종목코드 목록의 이름·시장 정보 반환."""
    if not codes:
        return {"info": {}}
    code_list = [c.strip() for c in codes.split(",") if re.match(r"^\d{6}$", c.strip())]
    stocks = _load_stock_master()
    info = {s["code"]: {"name": s["name"], "market": s["market"]} for s in stocks if s["code"] in code_list}
    return {"info": info}


@app.get("/config/env")
def get_env_config() -> dict:
    return {"env": _KIS_ENV, "max_watchlist": _MAX_WATCHLIST}


@app.get("/status")
def get_status() -> dict:
    return _get_status_dict()


@app.get("/positions")
def get_positions() -> dict:
    s = _get_status_dict()
    return {"positions": s.get("positions", [])}


@app.get("/pnl/today")
def get_pnl_today() -> dict:
    s = _get_status_dict()
    return {
        "date": s.get("date", _today_str()),
        "trades_today": s.get("trades_today", 0),
        "realized_pnl": s.get("realized_pnl", 0),
    }


@app.get("/trades")
def get_trades() -> dict:
    today = _today_str()
    today_d = date.fromisoformat(f"{today[:4]}-{today[4:6]}-{today[6:]}")
    return {"trades": _sm.get_trades(today_d)}


@app.get("/logs")
def get_logs(n: int = 50) -> dict:
    if not _LOG_PATH.exists():
        return {"lines": []}
    try:
        lines = _LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"lines": lines[-n:]}
    except Exception as e:
        return {"lines": [], "error": str(e)}


@app.get("/important-logs")
def get_important_logs(n: int = 200) -> dict:
    if not _IMPORTANT_LOG.exists():
        return {"lines": [], "note": "important.log 없음 — 봇 첫 실행 후 생성됩니다"}
    try:
        lines = _IMPORTANT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"lines": lines[-n:]}
    except Exception as e:
        return {"lines": [], "error": str(e)}


# ─── 제어 (인증 필요) ─────────────────────────────────────
@app.post("/kill")
def kill(_auth: None = Depends(_require_auth)) -> dict:
    """킬스위치 작동 요청을 state.db에 기록. 봇이 5초 이내 감지."""
    try:
        _sm.set_control_flag("kill_requested", "1")
        return {"ok": True, "message": "킬스위치 요청 기록됨"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/positions/{symbol}/close")
def close_position(symbol: str, _auth: None = Depends(_require_auth)) -> dict:
    """특정 종목 수동 청산 요청. 봇이 5초 이내 감지."""
    try:
        _sm.set_control_flag(f"force_close_{symbol}", "1")
        return {"ok": True, "message": f"{symbol} 청산 요청 기록됨"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/resume")
def resume(_auth: None = Depends(_require_auth)) -> dict:
    """킬스위치 해제 요청을 state.db에 기록. kill_active는 봇이 직접 처리."""
    try:
        _sm.set_control_flag("resume_requested", "1")
        _sm.clear_control_flag("kill_requested")
        return {"ok": True, "message": "킬스위치 해제 요청 기록됨"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pydantic 모델 ─────────────────────────────────────────
class WatchlistBody(BaseModel):
    symbols: list[str]

class KValueBody(BaseModel):
    k: float


# ─── 관심종목 ─────────────────────────────────────────────
@app.get("/watchlist")
def get_watchlist() -> dict:
    raw = _sm.get_control_flag("watchlist_override")
    if raw:
        symbols = [s.strip() for s in raw.split(",") if s.strip()]
    else:
        wl_env = os.getenv("WATCHLIST", "")
        symbols = [s.strip() for s in wl_env.split(",") if s.strip()]
    return {"symbols": symbols}


@app.post("/watchlist")
def set_watchlist(body: WatchlistBody, _auth: None = Depends(_require_auth)) -> dict:
    symbols = [s.strip() for s in body.symbols if re.match(r"^\d{6}$", s.strip())]
    if not symbols:
        raise HTTPException(status_code=400, detail="관심종목은 최소 1개 이상이어야 합니다")
    if len(symbols) > _MAX_WATCHLIST:
        env_label = "모의투자" if _KIS_ENV != "real" else "실전"
        raise HTTPException(
            status_code=400,
            detail=f"{env_label} 최대 {_MAX_WATCHLIST}종목 (요청: {len(symbols)}개)",
        )
    _sm.set_control_flag("watchlist_override", ",".join(symbols))
    return {"ok": True, "symbols": symbols}


# ─── 시장 필터 ────────────────────────────────────────────
@app.get("/market-filter")
def get_market_filter() -> dict:
    summary_entry = _sm.get_control_flag_with_time("market_filter_summary")
    if not summary_entry:
        return {"available": False, "summary": None, "ok": None, "updated_at": None}
    ok_val = _sm.get_control_flag("market_filter_ok")
    return {
        "available": True,
        "summary": summary_entry["value"],
        "ok": ok_val == "1" if ok_val is not None else None,
        "updated_at": summary_entry["updated_at"],
    }


# ─── k값 ──────────────────────────────────────────────────
@app.get("/config/k")
def get_k_value() -> dict:
    pending = _sm.get_control_flag("k_value")
    current = _sm.get_control_flag("current_k")
    return {
        "current_k": float(current) if current is not None else None,
        "pending_k": float(pending) if pending is not None else None,
    }


@app.post("/config/k")
def set_k_value(body: KValueBody, _auth: None = Depends(_require_auth)) -> dict:
    if not (0.1 <= body.k <= 1.0):
        raise HTTPException(status_code=400, detail="k값은 0.1~1.0 사이여야 합니다")
    _sm.set_control_flag("k_value", str(body.k))
    return {"ok": True, "k": body.k}


# ─── 강제 진입 ────────────────────────────────────────────
@app.post("/positions/{symbol}/enter")
def force_entry(symbol: str, _auth: None = Depends(_require_auth)) -> dict:
    if not re.match(r"^\d{6}$", symbol):
        raise HTTPException(status_code=400, detail="유효하지 않은 종목코드 (6자리 숫자)")
    _sm.set_control_flag(f"force_entry_{symbol}", "1")
    return {"ok": True, "message": f"{symbol} 강제 진입 요청 기록됨 (5초 내 처리)"}


# ─── WebSocket 실시간 스트림 ───────────────────────────────
@app.websocket("/ws/status")
async def ws_status(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            data = await asyncio.get_event_loop().run_in_executor(None, _get_status_dict)
            await ws.send_json(data)
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        pass
    except Exception:
        await ws.close()


# ─── 진입점 ───────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ui.api.main:app", host="0.0.0.0", port=8000, reload=True)
