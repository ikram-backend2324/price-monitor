"""Polite HTTP fetching: robots.txt, per-domain rate limit, UA rotation, proxies,
retries with exponential backoff + jitter, Retry-After support, optional Playwright."""

from __future__ import annotations

import itertools
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

import httpx
from django.conf import settings
from django.utils import timezone

from . import ratelimit, robots
from .adapters.base import ScrapeError

if TYPE_CHECKING:
    from apps.catalog.models import Store

log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
    "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1",
]

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_INLINE_WAIT = 30.0  # seconds we are willing to sleep inside a task


class RobotsDisallowed(ScrapeError):
    pass


class RateLimited(ScrapeError):
    """Too many requests — the caller should reschedule after ``retry_after`` seconds."""

    def __init__(self, message: str, retry_after: float, http_status: int | None = None):
        super().__init__(message, http_status)
        self.retry_after = retry_after


class FetchError(ScrapeError):
    pass


@dataclass
class FetchResponse:
    url: str
    status_code: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)

    def json(self):
        import json

        return json.loads(self.text)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, (dt - timezone.now()).total_seconds())


_proxy_cycle: itertools.cycle | None = None


def next_proxy() -> str | None:
    global _proxy_cycle
    proxies = [p for p in settings.SCRAPER["PROXY_URLS"] if p]
    if not proxies:
        return None
    if _proxy_cycle is None:
        _proxy_cycle = itertools.cycle(random.sample(proxies, len(proxies)))
    return next(_proxy_cycle)


class Fetcher:
    def __init__(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int | None = None,
        transport: httpx.BaseTransport | None = None,
        respect_robots: bool | None = None,
    ) -> None:
        cfg = settings.SCRAPER
        self.sleep = sleep
        self.max_retries = cfg["MAX_RETRIES"] if max_retries is None else max_retries
        self.timeout = cfg["TIMEOUT"]
        self.transport = transport
        self.respect_robots = cfg["RESPECT_ROBOTS"] if respect_robots is None else respect_robots
        self.user_agent = random.choice(USER_AGENTS)

    # -- helpers -----------------------------------------------------------
    def _client(self) -> httpx.Client:
        proxy = next_proxy()
        return httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            transport=self.transport,
            proxy=proxy if self.transport is None else None,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
                "Accept-Language": "ru-RU,ru;q=0.9,uz;q=0.8,en;q=0.7",
            },
        )

    def _backoff(self, attempt: int) -> float:
        base = settings.SCRAPER["BACKOFF_BASE"]
        return base * (2**attempt) + random.uniform(0, base)

    def _polite_wait(self, url: str, store: Store | None) -> None:
        domain = store.domain if store else httpx.URL(url).host
        per_minute = store.rate_limit_per_minute if store else 20
        wait = ratelimit.acquire(domain, per_minute)
        if wait > MAX_INLINE_WAIT:
            raise RateLimited(f"Rate limit for {domain}: retry in {wait:.0f}s", retry_after=wait)
        jitter = random.uniform(settings.SCRAPER["MIN_DELAY"], settings.SCRAPER["MAX_DELAY"])
        if wait + jitter > 0:
            self.sleep(wait + jitter)

    # -- public API --------------------------------------------------------
    def get(
        self,
        url: str,
        *,
        render: bool = False,
        store: Store | None = None,
        headers: dict[str, str] | None = None,
        check_robots: bool = True,
    ) -> FetchResponse:
        if check_robots and self.respect_robots:
            with self._client() as client:
                if not robots.is_allowed(url, self.user_agent, client=client):
                    raise RobotsDisallowed(f"robots.txt disallows {url}")

        self._polite_wait(url, store)
        if render:
            from .browser import render_page

            return render_page(url, user_agent=self.user_agent, wait_selector=getattr(store, "wait_selector", ""))

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with self._client() as client:
                    resp = client.get(url, headers=headers)
            except httpx.TransportError as exc:
                last_exc = exc
                log.info("network error %s (attempt %d): %s", url, attempt + 1, exc)
                if attempt < self.max_retries:
                    self.sleep(self._backoff(attempt))
                    continue
                raise FetchError(f"Network error: {exc.__class__.__name__}: {exc}") from exc

            if resp.status_code in RETRY_STATUSES:
                retry_after = parse_retry_after(resp.headers.get("Retry-After"))
                if attempt >= self.max_retries or (retry_after is not None and retry_after > MAX_INLINE_WAIT):
                    if resp.status_code in (429, 503):
                        raise RateLimited(
                            f"HTTP {resp.status_code} from server",
                            retry_after=retry_after or self._backoff(attempt + 2),
                            http_status=resp.status_code,
                        )
                    raise FetchError(f"HTTP {resp.status_code}", http_status=resp.status_code)
                self.sleep(retry_after if retry_after is not None else self._backoff(attempt))
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code}", http_status=resp.status_code)
            return FetchResponse(
                url=str(resp.url), status_code=resp.status_code, text=resp.text, headers=dict(resp.headers)
            )
        raise FetchError(f"Gave up after retries: {last_exc}")  # pragma: no cover
