"""알림 인터페이스.

실제 전송(텔레그램)은 requests로 Bot API 직접 호출.
토큰이 없으면 ConsoleAlertSender로 자동 폴백.
알림 실패는 봇 자체를 죽이지 않는다.
"""
from __future__ import annotations

import os
from typing import Protocol

import requests


class AlertSender(Protocol):
    def send(self, message: str) -> None: ...
    def send_urgent(self, message: str) -> None: ...


class ConsoleAlertSender:
    """개발/모의용: 콘솔 출력."""

    def send(self, message: str) -> None:
        print(f"[ALERT] {message}")

    def send_urgent(self, message: str) -> None:
        print(f"[ALERT-URGENT] {message}")


class TelegramAlertSender:
    """텔레그램 Bot API 직접 호출 (requests). 실패해도 봇은 계속 돌아간다."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id

    def send(self, message: str) -> None:
        try:
            requests.post(
                self._url,
                json={"chat_id": self._chat_id, "text": message},
                timeout=5,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[ALERT-FALLBACK] 전송 실패({e}): {message}")

    def send_urgent(self, message: str) -> None:
        self.send(f"🚨 {message}")


def build_alert_sender() -> AlertSender:
    """환경변수 여부에 따라 텔레그램 또는 콘솔 알림 반환."""
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return TelegramAlertSender(token, chat_id)
    return ConsoleAlertSender()
