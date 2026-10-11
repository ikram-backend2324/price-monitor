"""robots.txt compliance with a 24h cache."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)

BOT_NAME = "PriceWatchBot"


def _robots_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


def get_robots_text(url: str, client: httpx.Client | None = None) -> str:
    robots_url = _robots_url(url)
    key = f"robots:{robots_url}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    text = ""
    try:
        own_client = client is None
        client = client or httpx.Client(timeout=10, follow_redirects=True)
        try:
            resp = client.get(robots_url, headers={"User-Agent": BOT_NAME})
        finally:
            if own_client:
                client.close()
        if resp.status_code == 200:
            text = resp.text
        elif resp.status_code in (401, 403):
            # Access to robots.txt forbidden ⇒ treat site as disallowed (RFC 9309 §2.3.1.3)
            text = "User-agent: *\nDisallow: /"
    except httpx.HTTPError as exc:
        log.info("robots.txt unavailable for %s: %s", robots_url, exc)
        # Unreachable robots ⇒ do not cache for long, allow crawling
        cache.set(key, "", 600)
        return ""
    cache.set(key, text, settings.SCRAPER["ROBOTS_CACHE_SECONDS"])
    return text


def is_allowed(url: str, user_agent: str = BOT_NAME, client: httpx.Client | None = None) -> bool:
    if not settings.SCRAPER["RESPECT_ROBOTS"]:
        return True
    text = get_robots_text(url, client)
    if not text.strip():
        return True
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(user_agent, url) and parser.can_fetch(BOT_NAME, url)
