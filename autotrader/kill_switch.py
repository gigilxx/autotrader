"""킬스위치: 봇 전체의 정지 상태를 한 곳에서 관리.

리스크 게이트·자동정지·잔고대조 등 어느 모듈이든 trip()을 호출하면
전체가 정지되고, 등록된 알림 콜백으로 통보한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class KillSwitch:
    halted: bool = False
    reason: str = ""
    _on_trip: Optional[Callable[[str], None]] = None

    def set_alert(self, cb: Callable[[str], None]) -> None:
        """정지 발생 시 호출할 알림 콜백 등록."""
        self._on_trip = cb

    def trip(self, reason: str) -> None:
        """정지. 이미 정지 상태면 중복 알림하지 않는다."""
        if self.halted:
            return
        self.halted = True
        self.reason = reason
        if self._on_trip is not None:
            self._on_trip(reason)

    def reset(self) -> None:
        """수동 해제(예: 새 거래일). 신중히 사용."""
        self.halted = False
        self.reason = ""
