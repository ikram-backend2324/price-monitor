"""Playwright rendering for JS-only sites. Runs only on the ``browser`` queue worker.

Playwright's sync API runs an asyncio loop in the calling thread, which makes
Django refuse ORM calls from that thread afterwards (SynchronousOnlyOperation).
So the browser lives in one dedicated thread per worker process and callers
just submit render jobs to it.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings

log = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright")
_local = threading.local()


def _get_browser():  # pragma: no cover - requires Chromium
    browser = getattr(_local, "browser", None)
    if browser is None or not browser.is_connected():
        from playwright.sync_api import sync_playwright

        _local.pw = sync_playwright().start()
        proxies = [p for p in settings.SCRAPER["PROXY_URLS"] if p]
        launch_kwargs: dict = {"headless": True, "args": ["--disable-dev-shm-usage", "--no-sandbox"]}
        if proxies:
            launch_kwargs["proxy"] = {"server": proxies[0]}
        _local.browser = _local.pw.chromium.launch(**launch_kwargs)
    return _local.browser


def _render(url: str, user_agent: str, wait_selector: str):  # pragma: no cover - requires Chromium
    from .http import FetchError, FetchResponse

    browser = _get_browser()
    context = browser.new_context(user_agent=user_agent, locale="ru-RU", java_script_enabled=True)
    page = context.new_page()
    # Don't download images/fonts/media: faster and lighter for the target site.
    page.route(
        "**/*",
        lambda route: route.abort() if route.request.resource_type in {"image", "media", "font"} else route.continue_(),
    )
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=settings.SCRAPER["TIMEOUT"] * 1000)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=15000)
            except Exception:  # parse what rendered; the adapter decides if it is usable
                log.info("wait_selector %r not found on %s", wait_selector, url)
        else:
            page.wait_for_load_state("networkidle", timeout=15000)
        status = response.status if response else 0
        if status >= 400:
            raise FetchError(f"HTTP {status}", http_status=status)
        return FetchResponse(url=page.url, status_code=status or 200, text=page.content())
    finally:
        context.close()


def render_page(url: str, user_agent: str, wait_selector: str = ""):  # pragma: no cover - requires Chromium
    timeout = settings.SCRAPER["TIMEOUT"] + 30
    return _executor.submit(_render, url, user_agent, wait_selector).result(timeout=timeout)
