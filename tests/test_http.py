from datetime import timedelta
from email.utils import format_datetime

import httpx
import pytest
from django.utils import timezone

from apps.catalog.models import Store
from apps.scraping import ratelimit, robots
from apps.scraping.adapters import get_adapter
from apps.scraping.http import Fetcher, FetchError, RateLimited, RobotsDisallowed, parse_retry_after

URL = "https://shop.test/product/1"
LD = '<script type="application/ld+json">{"@type":"Product","name":"A","offers":{"price":"5000"}}</script>'


@pytest.fixture
def fetcher():
    sleeps = []
    f = Fetcher(sleep=sleeps.append, max_retries=2)
    f.sleeps = sleeps
    return f


@pytest.fixture
def allow_robots(respx_mock):
    respx_mock.get("https://shop.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    return respx_mock


def test_success(fetcher, allow_robots):
    allow_robots.get(URL).mock(return_value=httpx.Response(200, text=LD))
    assert fetcher.get(URL).text == LD


def test_retries_on_503_then_success(fetcher, allow_robots):
    route = allow_robots.get(URL)
    route.side_effect = [httpx.Response(503), httpx.Response(502), httpx.Response(200, text="ok")]
    assert fetcher.get(URL).text == "ok"
    assert route.call_count == 3


def test_respects_retry_after(fetcher, allow_robots):
    allow_robots.get(URL).side_effect = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, text="ok"),
    ]
    fetcher.get(URL)
    assert 2.0 in fetcher.sleeps


def test_long_retry_after_raises_rate_limited(fetcher, allow_robots):
    allow_robots.get(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "600"}))
    with pytest.raises(RateLimited) as exc:
        fetcher.get(URL)
    assert exc.value.retry_after == 600


def test_persistent_503_becomes_rate_limited(fetcher, allow_robots):
    allow_robots.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(RateLimited):
        fetcher.get(URL)


def test_persistent_500_is_fetch_error(fetcher, allow_robots):
    allow_robots.get(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(FetchError):
        fetcher.get(URL)


def test_404_no_retry(fetcher, allow_robots):
    route = allow_robots.get(URL).mock(return_value=httpx.Response(404))
    with pytest.raises(FetchError) as exc:
        fetcher.get(URL)
    assert exc.value.http_status == 404
    assert route.call_count == 1


def test_network_error_retries(fetcher, allow_robots):
    route = allow_robots.get(URL)
    route.side_effect = [httpx.ConnectError("boom"), httpx.Response(200, text="ok")]
    assert fetcher.get(URL).text == "ok"


def test_network_error_gives_up(fetcher, allow_robots):
    allow_robots.get(URL).side_effect = httpx.ConnectError("boom")
    with pytest.raises(FetchError):
        fetcher.get(URL)


def test_robots_disallow(fetcher, respx_mock):
    respx_mock.get("https://shop.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /product/")
    )
    with pytest.raises(RobotsDisallowed):
        fetcher.get(URL)


def test_robots_403_means_disallow(fetcher, respx_mock):
    respx_mock.get("https://shop.test/robots.txt").mock(return_value=httpx.Response(403))
    with pytest.raises(RobotsDisallowed):
        fetcher.get(URL)


def test_robots_cached(fetcher, respx_mock):
    robots_route = respx_mock.get("https://shop.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx_mock.get(URL).mock(return_value=httpx.Response(200, text="ok"))
    fetcher.get(URL)
    fetcher.get(URL)
    assert robots_route.call_count == 1


def test_robots_missing_allows(respx_mock):
    respx_mock.get("https://shop.test/robots.txt").mock(return_value=httpx.Response(404))
    assert robots.is_allowed(URL)


def test_robots_unreachable_allows(respx_mock):
    respx_mock.get("https://shop.test/robots.txt").mock(side_effect=httpx.ConnectError("x"))
    assert robots.is_allowed(URL)


def test_robots_can_be_disabled(settings):
    settings.SCRAPER = {**settings.SCRAPER, "RESPECT_ROBOTS": False}
    assert robots.is_allowed(URL)


@pytest.mark.django_db
def test_adapter_fetch_end_to_end(fetcher, allow_robots):
    allow_robots.get(URL).mock(return_value=httpx.Response(200, text=LD))
    store = Store.objects.create(name="S", domain="shop.test", adapter="jsonld")
    result = get_adapter(store, fetcher).fetch(URL)
    assert result.price == 5000 and result.http_status == 200


def test_parse_retry_after():
    assert parse_retry_after("120") == 120
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None
    future = format_datetime(timezone.now() + timedelta(seconds=60), usegmt=True)
    assert 50 < parse_retry_after(future) <= 61


def test_memory_token_bucket():
    bucket = ratelimit.MemoryBucket()
    # capacity = min(per_minute, 5) tokens available immediately
    waits = [bucket.acquire("d", 60, now=0) for _ in range(6)]
    assert waits[:5] == [0, 0, 0, 0, 0]
    assert waits[5] == pytest.approx(1.0)  # 60/min → one token per second
    assert bucket.acquire("d", 60, now=10) == 0  # refilled
    assert bucket.acquire("other", 60, now=0) == 0  # per-domain buckets


def test_rate_limit_too_long_raises(fetcher, allow_robots, monkeypatch):
    monkeypatch.setattr(ratelimit, "acquire", lambda domain, per_minute: 120.0)
    with pytest.raises(RateLimited):
        fetcher.get(URL)


def test_proxy_rotation(settings):
    from apps.scraping import http as http_mod

    settings.SCRAPER = {**settings.SCRAPER, "PROXY_URLS": ["http://p1:1", "http://p2:2"]}
    http_mod._proxy_cycle = None
    got = {http_mod.next_proxy() for _ in range(4)}
    assert got == {"http://p1:1", "http://p2:2"}
    http_mod._proxy_cycle = None
