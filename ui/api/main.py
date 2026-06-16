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
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from autotrader.state import StateManager

_DB_PATH          = Path(os.getenv("STATE_DB", "state.db"))
_LOG_PATH         = Path(os.getenv("LOG_FILE", "logs/autotrader.log"))
_IMPORTANT_LOG    = Path(os.getenv("IMPORTANT_LOG", "logs/important.log"))
_SECRET_KEY       = os.getenv("UI_SECRET_KEY", "")
_sm               = StateManager(_DB_PATH)

app = FastAPI(title="AutoTrader API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 개발용 — 배포 시 특정 도메인으로 제한
    allow_methods=["*"],
    allow_headers=["*"],
)

_bearer = HTTPBearer(auto_error=False)


# ─── DB 헬퍼 ──────────────────────────────────────────────
@contextmanager
def _db() -> Generator[sqlite3.Connection, None, None]:
    cx = sqlite3.connect(str(_DB_PATH), timeout=5, check_same_thread=False)
    cx.row_factory = sqlite3.Row
    # WAL 모드: 읽기/쓰기 동시성 향상
    cx.execute("PRAGMA journal_mode=WAL")
    try:
        yield cx
    finally:
        cx.close()


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
        with _db() as cx:
            row = cx.execute(
                "SELECT trades_today, realized_pnl_today FROM daily_state WHERE date = ?",
                (today,),
            ).fetchone()
            trades_today = row["trades_today"] if row else 0
            realized_pnl = row["realized_pnl_today"] if row else 0

            kill_flag = cx.execute(
                "SELECT value FROM control_flags WHERE key IN ('kill_requested', 'kill_active')"
            ).fetchone()
            is_killed = kill_flag is not None

            positions = cx.execute(
                "SELECT symbol, entry_price, qty FROM positions WHERE date = ?",
                (today,),
            ).fetchall()

        return {
            "date": today,
            "is_killed": is_killed,
            "trades_today": trades_today,
            "realized_pnl": realized_pnl,
            "position_count": len(positions),
            "positions": [dict(p) for p in positions],
        }
    except Exception as e:
        return {"error": str(e)}


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
    try:
        with _db() as cx:
            rows = cx.execute(
                "SELECT exit_time, symbol, entry_price, exit_price, qty, pnl, reason "
                "FROM trades WHERE date = ? ORDER BY id",
                (today,),
            ).fetchall()
        return {"trades": [dict(r) for r in rows]}
    except Exception as e:
        return {"trades": [], "error": str(e)}


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
    _sm.set_control_flag("watchlist_override", ",".join(symbols))
    return {"ok": True, "symbols": symbols}


# ─── 시장 필터 ────────────────────────────────────────────
@app.get("/market-filter")
def get_market_filter() -> dict:
    with _db() as cx:
        summary_row = cx.execute(
            "SELECT value, updated_at FROM control_flags WHERE key = 'market_filter_summary'"
        ).fetchone()
        ok_row = cx.execute(
            "SELECT value FROM control_flags WHERE key = 'market_filter_ok'"
        ).fetchone()
    if not summary_row:
        return {"available": False, "summary": None, "ok": None, "updated_at": None}
    return {
        "available": True,
        "summary": summary_row["value"],
        "ok": ok_row["value"] == "1" if ok_row else None,
        "updated_at": summary_row["updated_at"],
    }


# ─── k값 ──────────────────────────────────────────────────
@app.get("/config/k")
def get_k_value() -> dict:
    with _db() as cx:
        pending_row = cx.execute(
            "SELECT value FROM control_flags WHERE key = 'k_value'"
        ).fetchone()
        current_row = cx.execute(
            "SELECT value FROM control_flags WHERE key = 'current_k'"
        ).fetchone()
    return {
        "current_k": float(current_row["value"]) if current_row else None,
        "pending_k": float(pending_row["value"]) if pending_row else None,
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
