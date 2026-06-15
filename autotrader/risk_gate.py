"""리스크 게이트 (핵심): 주문 신호를 받아 허가/차단을 판정.

설계 원칙:
- 매도(청산)는 리스크를 '줄이는' 행위이므로 절대 막지 않는다.
  (손절·강제청산이 한도에 걸려 막히면 더 위험해짐.)
- 매수(신규 진입)만 한도/정지 상태로 통제한다.
- 일일 실현손익이 한도에 닿으면 킬스위치를 내려 당일 매매를 중단한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .config import RiskConfig
from .kill_switch import KillSwitch
from .models import AccountSnapshot, OrderRequest, Side

logger = logging.getLogger("autotrader.risk_gate")


@dataclass
class Decision:
    approved: bool
    reason: str


class RiskGate:
    def __init__(self, cfg: RiskConfig, kill: KillSwitch) -> None:
        self.cfg = cfg
        self.kill = kill
        self._day: Optional[date] = None
        self._trades_today = 0
        self._realized_pnl_today = 0

    # --- 일자 관리 ---
    def roll_day(self, today: date) -> None:
        """거래일이 바뀌면 일일 카운터 초기화."""
        if self._day != today:
            self._day = today
            self._trades_today = 0
            self._realized_pnl_today = 0

    # --- 상태 갱신 ---
    def register_entry_fill(self) -> None:
        """진입 체결 시 거래 횟수 증가."""
        self._trades_today += 1

    def register_realized_pnl(self, pnl_won: int) -> None:
        """청산 실현손익(비용 차감 후) 반영. 한도 도달 시 킬스위치."""
        self._realized_pnl_today += pnl_won
        if self._realized_pnl_today <= -self.cfg.daily_max_loss_won:
            msg = (
                f"일일 최대손실 도달: {self._realized_pnl_today:,}원 "
                f"(한도 -{self.cfg.daily_max_loss_won:,}원)"
            )
            logger.warning("킬스위치 트립 — %s", msg)
            self.kill.trip(msg)

    @property
    def realized_pnl_today(self) -> int:
        return self._realized_pnl_today

    @property
    def trades_today(self) -> int:
        return self._trades_today

    # --- 핵심: 주문 판정 ---
    def evaluate(self, order: OrderRequest, account: AccountSnapshot) -> Decision:
        # 청산(매도)은 항상 허용 — 절대 막지 않는다.
        if order.side == Side.SELL:
            return Decision(True, "청산 주문 — 항상 허용")

        # 이하 신규 진입(매수) 판정
        if self.kill.halted:
            return Decision(False, f"정지 상태 — 신규 진입 차단: {self.kill.reason}")

        if self._realized_pnl_today <= -self.cfg.daily_max_loss_won:
            return Decision(False, "일일 최대손실 한도 도달 — 신규 진입 금지")

        if self._trades_today >= self.cfg.max_trades_per_day:
            return Decision(False, f"1일 최대 거래 {self.cfg.max_trades_per_day}회 초과")

        if account.position_count() >= self.cfg.max_concurrent_positions:
            return Decision(False, "동시 보유 종목 수 한도 초과")

        if order.qty <= 0:
            return Decision(False, "수량 0 이하")

        # 무인 운용에서 슬리피지 통제를 위해 신규 진입은 지정가만 허용.
        # (체결 보장보다 가격 통제를 우선. 필요 시 정책 변경 가능 — 가정 참고.)
        if order.price is None:
            return Decision(False, "신규 진입은 지정가 필요 — 시장가 금지")

        notional = order.qty * order.price
        if notional > account.cash:
            return Decision(False, f"현금 부족: 필요 {notional:,}원 > 보유 {account.cash:,}원")

        return Decision(True, "허가")
