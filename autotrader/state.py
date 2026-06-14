"""상태 영속화: SQLite state.db로 재시작 시 복원.

저장 대상:
  daily_state  — 일일 거래 횟수, 실현 손익 (RiskGate 카운터 복원용)
  sent_orders  — 전송된 주문 ID (IdempotencyGuard 복원용)
  positions    — 보유 포지션 추정 (engine.local 복원용)

⚠️ 저장 실패는 봇을 죽이지 않는다. 단, 복원 실패 시 당일 카운터 0에서 재시작.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Generator


_DB_PATH = Path("state.db")


@dataclass
class DailyState:
    trades_today: int
    realized_pnl_today: int


@dataclass
class SavedPosition:
    symbol: str
    entry_price: int
    qty: int


class StateManager:
    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db = db_path
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as cx:
            cx.executescript("""
                CREATE TABLE IF NOT EXISTS daily_state (
                    date TEXT PRIMARY KEY,
                    trades_today INTEGER DEFAULT 0,
                    realized_pnl_today INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sent_orders (
                    order_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    PRIMARY KEY (order_id)
                );
                CREATE TABLE IF NOT EXISTS positions (
                    date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    entry_price INTEGER NOT NULL,
                    qty INTEGER NOT NULL,
                    PRIMARY KEY (date, symbol)
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    exit_time TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    entry_price INTEGER NOT NULL,
                    exit_price INTEGER NOT NULL,
                    qty INTEGER NOT NULL,
                    pnl INTEGER NOT NULL,
                    reason TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS control_flags (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT (datetime('now'))
                );
            """)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        cx = sqlite3.connect(str(self._db), timeout=5)
        try:
            cx.row_factory = sqlite3.Row
            yield cx
            cx.commit()
        except Exception:
            cx.rollback()
            raise
        finally:
            cx.close()

    # ---------------- daily_state ----------------
    def save_daily_state(self, today: date, trades: int, pnl: int) -> None:
        try:
            with self._conn() as cx:
                cx.execute(
                    "INSERT OR REPLACE INTO daily_state (date, trades_today, realized_pnl_today) "
                    "VALUES (?, ?, ?)",
                    (today.strftime("%Y%m%d"), trades, pnl),
                )
        except Exception:
            pass

    def load_daily_state(self, today: date) -> DailyState:
        try:
            with self._conn() as cx:
                row = cx.execute(
                    "SELECT trades_today, realized_pnl_today FROM daily_state WHERE date = ?",
                    (today.strftime("%Y%m%d"),),
                ).fetchone()
                if row:
                    return DailyState(
                        trades_today=row["trades_today"],
                        realized_pnl_today=row["realized_pnl_today"],
                    )
        except Exception:
            pass
        return DailyState(trades_today=0, realized_pnl_today=0)

    # ---------------- sent_orders ----------------
    def add_sent_order(self, order_id: str, today: date) -> None:
        try:
            with self._conn() as cx:
                cx.execute(
                    "INSERT OR IGNORE INTO sent_orders (order_id, date) VALUES (?, ?)",
                    (order_id, today.strftime("%Y%m%d")),
                )
        except Exception:
            pass

    def load_sent_orders(self, today: date) -> set[str]:
        try:
            with self._conn() as cx:
                rows = cx.execute(
                    "SELECT order_id FROM sent_orders WHERE date = ?",
                    (today.strftime("%Y%m%d"),),
                ).fetchall()
                return {row["order_id"] for row in rows}
        except Exception:
            return set()

    # ---------------- positions ----------------
    def save_position(self, today: date, symbol: str, entry_price: int, qty: int) -> None:
        try:
            with self._conn() as cx:
                cx.execute(
                    "INSERT OR REPLACE INTO positions (date, symbol, entry_price, qty) "
                    "VALUES (?, ?, ?, ?)",
                    (today.strftime("%Y%m%d"), symbol, entry_price, qty),
                )
        except Exception:
            pass

    def delete_position(self, today: date, symbol: str) -> None:
        try:
            with self._conn() as cx:
                cx.execute(
                    "DELETE FROM positions WHERE date = ? AND symbol = ?",
                    (today.strftime("%Y%m%d"), symbol),
                )
        except Exception:
            pass

    def load_positions(self, today: date) -> list[SavedPosition]:
        try:
            with self._conn() as cx:
                rows = cx.execute(
                    "SELECT symbol, entry_price, qty FROM positions WHERE date = ?",
                    (today.strftime("%Y%m%d"),),
                ).fetchall()
                return [
                    SavedPosition(
                        symbol=row["symbol"],
                        entry_price=row["entry_price"],
                        qty=row["qty"],
                    )
                    for row in rows
                ]
        except Exception:
            return []

    # ---------------- trades ----------------
    def record_trade(
        self,
        today: date,
        exit_time: str,
        symbol: str,
        entry_price: int,
        exit_price: int,
        qty: int,
        pnl: int,
        reason: str,
    ) -> None:
        try:
            with self._conn() as cx:
                cx.execute(
                    "INSERT INTO trades (date, exit_time, symbol, entry_price, exit_price, qty, pnl, reason) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (today.strftime("%Y%m%d"), exit_time, symbol, entry_price, exit_price, qty, pnl, reason),
                )
        except Exception:
            pass

    def get_trades(self, today: date) -> list[dict]:
        try:
            with self._conn() as cx:
                rows = cx.execute(
                    "SELECT exit_time, symbol, entry_price, exit_price, qty, pnl, reason "
                    "FROM trades WHERE date = ? ORDER BY id",
                    (today.strftime("%Y%m%d"),),
                ).fetchall()
                return [dict(row) for row in rows]
        except Exception:
            return []

    # ---------------- control_flags ----------------
    def set_control_flag(self, key: str, value: str) -> None:
        try:
            with self._conn() as cx:
                cx.execute(
                    "INSERT OR REPLACE INTO control_flags (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                    (key, value),
                )
        except Exception:
            pass

    def get_control_flag(self, key: str) -> "Optional[str]":
        try:
            with self._conn() as cx:
                row = cx.execute(
                    "SELECT value FROM control_flags WHERE key = ?", (key,)
                ).fetchone()
                return row["value"] if row else None
        except Exception:
            return None

    def clear_control_flag(self, key: str) -> None:
        try:
            with self._conn() as cx:
                cx.execute("DELETE FROM control_flags WHERE key = ?", (key,))
        except Exception:
            pass

    # ---------------- 정리 (오래된 데이터) ----------------
    def cleanup_old_data(self, keep_days: int = 30) -> None:
        """30일 이전 데이터 삭제 (디스크 공간 관리)."""
        try:
            from datetime import timedelta
            cutoff = (date.today() - timedelta(days=keep_days)).strftime("%Y%m%d")
            with self._conn() as cx:
                cx.execute("DELETE FROM daily_state WHERE date < ?", (cutoff,))
                cx.execute("DELETE FROM sent_orders WHERE date < ?", (cutoff,))
                cx.execute("DELETE FROM positions WHERE date < ?", (cutoff,))
        except Exception:
            pass
