"""자동 정지(auto-halt): 무인 운용 중 이상 징후를 감지하면 스스로 멈춘다.

사람이 못 보는 상태이므로, 버튼식이 아니라 봇이 자동으로 킬스위치를 내려야 한다.
- API 연속 에러
- 시세 데이터 정지(staleness)
(일일 최대손실 정지는 risk_gate에서 처리.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .kill_switch import KillSwitch


@dataclass
class HealthConfig:
    max_consecutive_api_errors: int = 5
    max_quote_staleness_sec: float = 60.0  # 이 시간 이상 시세 갱신 없으면 정지


class HealthMonitor:
    def __init__(self, kill: KillSwitch, cfg: Optional[HealthConfig] = None) -> None:
        self.kill = kill
        self.cfg = cfg or HealthConfig()
        self._consec_errors = 0
        self._last_quote_ts: Optional[float] = None

    def record_api_error(self) -> None:
        self._consec_errors += 1
        if self._consec_errors >= self.cfg.max_consecutive_api_errors:
            self.kill.trip(f"API 연속 에러 {self._consec_errors}회")

    def record_api_success(self) -> None:
        self._consec_errors = 0

    def record_quote(self, now_ts: float) -> None:
        """시세 수신 시각 갱신(epoch 초)."""
        self._last_quote_ts = now_ts

    def check_feed(self, now_ts: float) -> None:
        """주기적으로 호출해 시세 정지를 감지."""
        if self._last_quote_ts is None:
            return
        if now_ts - self._last_quote_ts > self.cfg.max_quote_staleness_sec:
            self.kill.trip("시세 데이터 정지(staleness)")
