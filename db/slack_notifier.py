"""Slack Incoming Webhook 기반 알림.

원칙:
- Webhook URL 미설정 시 NullNotifier로 fallback → 봇은 Slack 없이도 구동 가능.
- 전송 실패로 트레이더 루프가 절대 죽으면 안 됨 → 타임아웃 + try/except.
- 노이즈 방지: 4가지 레벨(info/trade/warn/critical)만 노출하고
  모든 tick·모든 trade를 보내지 않는다.
- Slack Block Kit을 쓰지 않고 단순 text + emoji — 의존성·스키마 복잡도 최소화.

Webhook 발급:
  Slack Workspace → Apps → "Incoming Webhooks" → 채널 선택 → URL 발급
  .env 의 SLACK_WEBHOOK_URL 에 붙여넣기.
"""
from __future__ import annotations

import json
import logging
from typing import Optional
from urllib import error, request

from config import (
    SLACK_TIMEOUT_SEC, SLACK_USERNAME, SLACK_WEBHOOK_URL,
)

log = logging.getLogger(__name__)

# 레벨별 emoji·색상(Slack 기본 render용)
_LEVEL = {
    "info":     ("ℹ️",  "#4a90e2"),
    "trade":    ("💱", "#7ed321"),
    "warn":     ("⚠️",  "#f5a623"),
    "critical": ("🚨", "#d0021b"),
}


class NullNotifier:
    """Webhook 미설정 시 사용하는 NoOp."""

    def __init__(self, *_args, **_kwargs):
        self.enabled = False

    def send(self, *_args, **_kwargs) -> bool: return False
    def info(self, *_args, **_kwargs) -> bool: return False
    def trade(self, *_args, **_kwargs) -> bool: return False
    def warn(self, *_args, **_kwargs) -> bool: return False
    def critical(self, *_args, **_kwargs) -> bool: return False


class SlackNotifier:
    """Slack Incoming Webhook 클라이언트.

    메서드 시그니처는 모두 `(text, *, fields=None)` 형태로 통일.
    `fields`는 key=value 딕셔너리 — 메시지 본문 밑에 한 줄씩 붙는다.
    """

    def __init__(self, webhook_url: str, username: str = SLACK_USERNAME):
        if not webhook_url:
            raise ValueError("SlackNotifier requires a non-empty webhook_url")
        self.webhook_url = webhook_url
        self.username = username
        self.enabled = True

    # ─────────────── 저수준 전송 ───────────────
    def _post(self, payload: dict) -> bool:
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=SLACK_TIMEOUT_SEC) as resp:
                ok = 200 <= resp.status < 300
                if not ok:
                    log.warning("Slack webhook non-2xx: %s", resp.status)
                return ok
        except (error.URLError, error.HTTPError, TimeoutError) as e:
            log.warning("Slack webhook failed: %s", e)
            return False
        except Exception as e:  # 최후 방어 — 트레이더 절대 죽지 않게
            log.warning("Slack webhook unexpected error: %s", e)
            return False

    # ─────────────── 퍼블릭 API ───────────────
    def send(
        self,
        text: str,
        level: str = "info",
        fields: Optional[dict] = None,
    ) -> bool:
        emoji, color = _LEVEL.get(level, _LEVEL["info"])
        lines = [f"{emoji} *{text}*"]
        if fields:
            # 각 필드는 "• key: value" 한 줄씩. 숫자는 보기 좋게 포맷.
            for k, v in fields.items():
                lines.append(f"• *{k}*: {_fmt(v)}")
        payload = {
            "username": self.username,
            "attachments": [{
                "color": color,
                "text": "\n".join(lines),
                "mrkdwn_in": ["text"],
            }],
        }
        return self._post(payload)

    def info(self, text: str, fields: Optional[dict] = None) -> bool:
        return self.send(text, level="info", fields=fields)

    def trade(self, text: str, fields: Optional[dict] = None) -> bool:
        return self.send(text, level="trade", fields=fields)

    def warn(self, text: str, fields: Optional[dict] = None) -> bool:
        return self.send(text, level="warn", fields=fields)

    def critical(self, text: str, fields: Optional[dict] = None) -> bool:
        return self.send(text, level="critical", fields=fields)


def _fmt(v) -> str:
    """숫자는 천단위·소수점 정리, 나머지는 str."""
    if isinstance(v, float):
        if abs(v) >= 100:
            return f"{v:,.2f}"
        if abs(v) >= 1:
            return f"{v:.4f}"
        return f"{v:.6f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def build_notifier() -> SlackNotifier | NullNotifier:
    """Factory. URL 없으면 NullNotifier."""
    if not SLACK_WEBHOOK_URL:
        log.info("SLACK_WEBHOOK_URL 미설정 — NullNotifier 사용")
        return NullNotifier()
    try:
        return SlackNotifier(SLACK_WEBHOOK_URL)
    except Exception as e:
        log.warning("SlackNotifier 초기화 실패 — NullNotifier fallback: %s", e)
        return NullNotifier()
