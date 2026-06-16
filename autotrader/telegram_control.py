"""텔레그램 제어 봇 — 명령어 수신 + 킬스위치 제어.

등록된 TELEGRAM_CHAT_ID의 명령만 수락한다.
봇 프로세스와 state.db를 공유해 control_flags를 통해 제어한다.

지원 명령:
    /status   현재 상태·포지션·손익 요약
    /kill     킬스위치 작동 (확인 단계 포함)
    /confirm_kill  킬스위치 최종 확인
    /resume   킬스위치 해제
    /trades   오늘 거래 내역
    /help     명령어 목록

실행 (봇과 별도 프로세스):
    python -m autotrader.telegram_control

환경변수:
    TELEGRAM_TOKEN   봇 토큰
    TELEGRAM_CHAT_ID 허용 채팅 ID
    STATE_DB         state.db 경로 (기본 state.db)
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
load_dotenv()

from .state import StateManager

logger = logging.getLogger("autotrader.telegram_control")

_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
_DB_PATH = Path(os.getenv("STATE_DB", "state.db"))

_sm = StateManager(_DB_PATH)

_PENDING_KILL: set[int] = set()  # /kill 확인 대기 중인 chat_id


# ─── DB 헬퍼 (복잡한 읽기 쿼리용) ──────────────────────────
@contextmanager
def _db():
    cx = sqlite3.connect(str(_DB_PATH), timeout=5, check_same_thread=False)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA journal_mode=WAL")
    try:
        yield cx
    finally:
        cx.close()


def _today() -> str:
    return date.today().strftime("%Y%m%d")


def _get_watchlist() -> list[str]:
    raw = _sm.get_control_flag("watchlist_override")
    if raw:
        return [s.strip() for s in raw.split(",") if s.strip()]
    return [s.strip() for s in os.getenv("WATCHLIST", "").split(",") if s.strip()]


def _set_watchlist(symbols: list[str]) -> None:
    _sm.set_control_flag("watchlist_override", ",".join(symbols))


def _require_env() -> None:
    missing = [k for k in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID") if not os.getenv(k)]
    if missing:
        print(f"환경변수 누락: {', '.join(missing)}")
        sys.exit(1)


# ─── 상태 조회 헬퍼 ─────────────────────────────────────────
def _build_status_text() -> str:
    today = _today()
    try:
        with _db() as cx:
            row = cx.execute(
                "SELECT trades_today, realized_pnl_today FROM daily_state WHERE date = ?",
                (today,),
            ).fetchone()
            trades = row["trades_today"] if row else 0
            pnl    = row["realized_pnl_today"] if row else 0

            kill_row = cx.execute(
                "SELECT value FROM control_flags WHERE key IN ('kill_requested', 'kill_active')"
            ).fetchone()
            is_killed = kill_row is not None

            pos_rows = cx.execute(
                "SELECT symbol, entry_price, qty FROM positions WHERE date = ?",
                (today,),
            ).fetchall()

        status = "⛔ 정지(킬스위치)" if is_killed else "🟢 실행 중"
        lines = [
            f"봇 상태: {status}",
            f"거래: {trades}건 | 손익: {pnl:+,}원",
        ]
        if pos_rows:
            lines.append("보유 포지션:")
            for p in pos_rows:
                lines.append(f"  {p['symbol']} {p['qty']}주 @ {p['entry_price']:,}원")
        else:
            lines.append("보유 포지션: 없음")
        return "\n".join(lines)
    except Exception as e:
        return f"상태 조회 실패: {e}"


def _build_trades_text() -> str:
    today = _today()
    try:
        with _db() as cx:
            rows = cx.execute(
                "SELECT exit_time, symbol, entry_price, exit_price, qty, pnl, reason "
                "FROM trades WHERE date = ? ORDER BY id",
                (today,),
            ).fetchall()
        if not rows:
            return "오늘 거래 없음"
        lines = [f"오늘 거래 ({len(rows)}건):"]
        for r in rows:
            sign = "+" if r["pnl"] > 0 else ""
            lines.append(
                f"  [{r['exit_time']}] {r['symbol']} {r['qty']}주"
                f" {r['entry_price']:,}→{r['exit_price']:,}"
                f" {sign}{r['pnl']:,}원 ({r['reason']})"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"거래 내역 조회 실패: {e}"


_HELP_TEXT = """\
명령어 목록:
  /status        현재 봇 상태
  /kill          킬스위치 작동 (확인 필요)
  /resume        킬스위치 해제
  /trades        오늘 거래 내역
  /market        시장 필터 상태 (KODEX200 vs MA)
  /watchlist     관심종목 목록
  /watch_add     종목 추가  예) /watch_add 000660
  /watch_del     종목 제거  예) /watch_del 000660
  /k             돌파계수 조회·변경  예) /k 0.5
  /help          이 도움말"""


# ─── 명령어 핸들러 ──────────────────────────────────────────
def _cmd_status(chat_id: int, parts: list[str]) -> str:
    return _build_status_text()


def _cmd_kill(chat_id: int, parts: list[str]) -> str:
    _PENDING_KILL.add(chat_id)
    return "⚠️ 킬스위치를 작동하시겠습니까?\n/confirm_kill 로 최종 확인하세요."


def _cmd_confirm_kill(chat_id: int, parts: list[str]) -> str:
    if chat_id not in _PENDING_KILL:
        return "먼저 /kill 을 입력하세요."
    _PENDING_KILL.discard(chat_id)
    _sm.set_control_flag("kill_requested", "1")
    return "🚨 킬스위치 요청 완료. 봇이 5초 이내 정지합니다."


def _cmd_resume(chat_id: int, parts: list[str]) -> str:
    _PENDING_KILL.discard(chat_id)
    _sm.set_control_flag("resume_requested", "1")
    _sm.clear_control_flag("kill_requested")
    # kill_active는 봇이 resume_requested 처리 시 직접 삭제 (I-1 경쟁조건 방지)
    return "✅ 킬스위치 해제 요청 완료."


def _cmd_trades(chat_id: int, parts: list[str]) -> str:
    return _build_trades_text()


def _cmd_help(chat_id: int, parts: list[str]) -> str:
    return _HELP_TEXT


def _cmd_market(chat_id: int, parts: list[str]) -> str:
    summary = _sm.get_control_flag("market_filter_summary")
    if summary:
        return summary
    return "시장 필터 데이터 없음\n(오늘 08:55 prepare_day 이후 확인 가능)"


def _cmd_watchlist(chat_id: int, parts: list[str]) -> str:
    wl = _get_watchlist()
    return "관심종목:\n" + "\n".join(f"  {s}" for s in wl)


def _cmd_watch_add(chat_id: int, parts: list[str]) -> str:
    if len(parts) < 2:
        return "사용법: /watch_add 종목코드  예) /watch_add 000660"
    sym = parts[1].strip().upper()
    wl = _get_watchlist()
    if sym not in wl:
        wl.append(sym)
        _set_watchlist(wl)
    return f"✅ {sym} 추가 (다음 장 목표가 계산)\n관심종목: {', '.join(wl)}"


def _cmd_watch_del(chat_id: int, parts: list[str]) -> str:
    if len(parts) < 2:
        return "사용법: /watch_del 종목코드  예) /watch_del 000660"
    sym = parts[1].strip().upper()
    wl = _get_watchlist()
    if sym in wl:
        wl.remove(sym)
        _set_watchlist(wl)
    return f"✅ {sym} 제거 (보유 중이면 즉시 청산)\n관심종목: {', '.join(wl)}"


def _cmd_k(chat_id: int, parts: list[str]) -> str:
    if len(parts) < 2:
        current = _sm.get_control_flag("k_value") or os.getenv("K_VALUE", "0.5")
        return f"현재 k값: {current}\n변경: /k 0.5  (0.1~1.0, 다음 prepare_day 적용)"
    try:
        k = float(parts[1])
        if not (0.1 <= k <= 1.0):
            return "k값은 0.1~1.0 사이여야 합니다."
    except ValueError:
        return f"잘못된 값: {parts[1]}"
    _sm.set_control_flag("k_value", str(k))
    return f"✅ k값 → {k} (5초 내 적용, 미진입 종목 목표가 즉시 재계산)"


_HANDLERS: dict[str, Callable[[int, list[str]], str]] = {
    "/status":       _cmd_status,
    "/kill":         _cmd_kill,
    "/confirm_kill": _cmd_confirm_kill,
    "/resume":       _cmd_resume,
    "/trades":       _cmd_trades,
    "/help":         _cmd_help,
    "/market":       _cmd_market,
    "/watchlist":    _cmd_watchlist,
    "/watch_add":    _cmd_watch_add,
    "/watch_del":    _cmd_watch_del,
    "/k":            _cmd_k,
}


def _handle_command(chat_id: int, text: str) -> str:
    if str(chat_id) != _CHAT_ID:
        logger.warning("미허가 chat_id: %s (허가된 ID: %s)", chat_id, _CHAT_ID)
        return "⛔ 허가되지 않은 사용자"

    parts = text.strip().split()
    cmd = parts[0].lower()
    handler = _HANDLERS.get(cmd)
    if handler:
        return handler(chat_id, parts)

    _PENDING_KILL.discard(chat_id)
    return f"알 수 없는 명령: {cmd}\n/help 로 도움말 확인"


def main() -> None:
    _require_env()

    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
    except ImportError:
        print("python-telegram-bot 미설치: pip install python-telegram-bot")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)

    async def _reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        text = update.message.text or ""
        chat_id = update.message.chat_id
        resp = _handle_command(chat_id, text)
        await update.message.reply_text(resp)

    app = Application.builder().token(_TOKEN).build()
    for cmd in ("status", "kill", "confirm_kill", "resume", "trades", "help",
                "market", "watchlist", "watch_add", "watch_del", "k"):
        app.add_handler(CommandHandler(cmd, _reply))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _reply))

    async def _set_commands(_app):
        from telegram import BotCommand
        await _app.bot.set_my_commands([
            BotCommand("status",       "현재 봇 상태·포지션·손익"),
            BotCommand("kill",         "킬스위치 작동 (확인 필요)"),
            BotCommand("confirm_kill", "킬스위치 최종 확인"),
            BotCommand("resume",       "킬스위치 해제"),
            BotCommand("trades",       "오늘 거래 내역"),
            BotCommand("market",       "시장 필터 상태 (KODEX200 vs MA)"),
            BotCommand("watchlist",    "관심종목 목록"),
            BotCommand("watch_add",    "종목 추가  예) /watch_add 000660"),
            BotCommand("watch_del",    "종목 제거  예) /watch_del 000660"),
            BotCommand("k",            "돌파계수 조회·변경  예) /k 0.5"),
            BotCommand("help",         "명령어 목록"),
        ])

    app.post_init = _set_commands

    logger.info("텔레그램 봇 시작 (chat_id=%s)", _CHAT_ID)
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
