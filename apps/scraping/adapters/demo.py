"""Adapter for the bundled demo-shop service (fake shops used for demos and tests).

Product page:  http://<shop>.demo:8001/product/<sku>
JSON API:      http://<shop>.demo:8001/api/product/<sku>
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit

from ..price_parser import parse_price
from .base import BaseAdapter, ParseError, ScrapeResult
from .jsonld import parse_jsonld_page


def api_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path
    if path.startswith("/product/"):
        path = "/api" + path
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def parse_demo_payload(text: str) -> ScrapeResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError("demo-shop: invalid JSON") from exc
    if "price" not in data:
        raise ParseError("demo-shop: no price in payload")
    return ScrapeResult(
        price=parse_price(data.get("price")),
        old_price=parse_price(data.get("old_price")),
        in_stock=bool(data.get("in_stock", True)),
        title=data.get("title", ""),
        currency=data.get("currency", "UZS"),
        raw={"source": "demo", **{k: data.get(k) for k in ("sku", "shop", "updated_at")}},
    )


class DemoShopAdapter(BaseAdapter):
    code = "demo"

    def fetch(self, url: str) -> ScrapeResult:
        response = self.fetcher.get(api_url(url), store=self.store, headers={"Accept": "application/json"})
        result = self.parse(response.text, url)
        result.http_status = response.status_code
        return result

    def parse(self, html: str, url: str) -> ScrapeResult:
        if html.lstrip().startswith("{"):
            return parse_demo_payload(html)
        return parse_jsonld_page(html, url)
