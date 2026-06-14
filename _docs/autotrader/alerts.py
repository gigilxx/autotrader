"""알림 인터페이스. 실제 전송(텔레그램)은 추상화해서 주입한다.

⚠️ 공식 문서 확인 필요: 텔레그램 봇 토큰/chat_id 발급, python-telegram-bot 사용법.
"""
from __future__ import annotations

from typing import Callable, Protocol


class AlertSender(Protocol):
    def send(self, message: str) -> None: ...


class ConsoleAlertSender:
    """개발/모의용: 콘솔 출력."""

    def send(self, message: str) -> None:
        print(f"[ALERT] {message}")


class TelegramAlertSender:
    """실제 텔레그램 전송 골격.

    라이브러리 의존을 격리하기 위해 전송 함수를 주입받는다.
    알림 전송 실패가 봇 자체를 죽이지 않도록 예외를 삼킨다.
    """

    def __init__(self, send_fn: Callable[[str], None]) -> None:
        self._send_fn = send_fn

    def send(self, message: str) -> None:
        try:
            self._send_fn(message)
        except Exception as e:  # noqa: BLE001  (알림 실패는 치명적이지 않게)
            print(f"[ALERT-FALLBACK] 전송 실패({e}): {message}")
