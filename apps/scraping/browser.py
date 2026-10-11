"""Playwright rendering for JS-only sites. Runs only on the ``browser`` queue worker."""

from __future__ import annotations

import logging
import threading

from django.conf import settings

log = logging.getLogger(__name__)
_local = threading.local()


def _get_browser():  # pragma: no cover - requires Chromium
    browser = getattr(_local, "browser", None)
    if browser is None or not browser.is_connected():
        from playwright.sync_api import sync_playwright

        _local.pw = sync_playwright().start()
        proxies = [p for p in settings.SCRAPER["PROXY_URLS"] if p]
        launch_kwargs = {"headless": True, "args": ["--disable-dev-shm-usage", "--no-sandbox"]}
        if proxies:
            launch_kwargs["proxy"] = {"server": proxies[0]}
        _local.browser = _local.pw.chromium.launch(**launch_kwargs)
    return _local.browser


def render_page(url: str, user_agent: str, wait_selector: str = ""):  # pragma: no cover - requires Chromium
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
            page.wait_for_selector(wait_selector, timeout=15000)
        else:
            page.wait_for_load_state("networkidle", timeout=15000)
        status = response.status if response else 0
        if status >= 400:
            raise FetchError(f"HTTP {status}", http_status=status)
        return FetchResponse(url=page.url, status_code=status or 200, text=page.content())
    finally:
        context.close()
