"""Minimal Telegram Bot API client used by Django/Celery to *send* messages.

The interactive bot (commands, callbacks) lives in ``bot/`` and runs separately.
Without ``TELEGRAM_BOT_TOKEN`` messages are only logged (demo mode).
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import httpx
from django.conf import settings

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"


def is_configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN)


def public_url_allowed(url: str) -> bool:
    """Telegram rejects URL buttons pointing to localhost/private hosts."""
    host = urlsplit(url).hostname or ""
    return not (host in ("localhost", "127.0.0.1", "0.0.0.0") or host.endswith(".local") or "." not in host)


def send_message(chat_id: int | str | None, text: str, buttons: list[list[dict]] | None = None) -> bool:
    if chat_id is None:
        return False
    if not is_configured():
        log.info("[telegram disabled] to %s: %s", chat_id, text.replace("\n", " | ")[:500])
        return False
    payload: dict = {"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        resp = httpx.post(API.format(token=settings.TELEGRAM_BOT_TOKEN, method="sendMessage"), json=payload, timeout=15)
    except httpx.HTTPError as exc:
        log.warning("Telegram send failed: %s", exc)
        return False
    if resp.status_code != 200:
        log.warning("Telegram API %s: %s", resp.status_code, resp.text[:300])
        return False
    return True


def send_admin_message(text: str) -> bool:
    if not settings.ADMIN_TELEGRAM_CHAT_ID:
        log.warning("[admin alert] %s", text.replace("\n", " | "))
        return False
    return send_message(settings.ADMIN_TELEGRAM_CHAT_ID, text)
