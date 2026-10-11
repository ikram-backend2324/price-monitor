"""Uzum Market (uzum.uz) adapter.

Research notes (Oct 2026, see docs/DECISIONS.md):
* Product pages are a client-rendered Nuxt SPA. Plain HTML for a browser
  User-Agent is an empty shell; there is no price in JSON-LD (the Product node
  is empty) and ``product:price:amount`` meta is always ``0``.
* Product data is loaded from ``graphql.uzum.uz`` with an anonymous token from
  ``id.uzum.uz`` — an internal API we deliberately do not call directly.
* The old public REST endpoint ``api.uzum.uz/api/v2/product/{id}`` returns 404.
* robots.txt allows ``/ru/product/`` and ``/uz/product/``.

So the store is marked ``requires_browser=True`` and we read the rendered DOM.
All layout-dependent logic lives in :func:`parse_uzum_html` — when Uzum changes
markup, fix this one function and refresh ``tests/fixtures/uzum_*.html``.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from ..price_parser import parse_price
from .base import BaseAdapter, ParseError, ScrapeResult
from .extract import availability_in_stock, meta_content

PRICE_SEL = '[data-test-id="text__product-price"]'
OLD_PRICE_SEL = '[data-test-id="text__product-old-price"]'
TITLE_SEL = '[data-test-id="text__product-name"]'
CART_SEL = '[data-test-id="button__add-to-cart"]'
OUT_OF_STOCK_PHRASES = ("нет в наличии", "mavjud emas", "sotuvda yo'q", "out of stock", "товар закончился")
# og:title looks like "Смартфон ... за 8699000 сум со скидкой 8%. Uzum Market"
OG_PRICE_RE = re.compile(r"(?:за|uchun)?\s*(\d[\d\s]*)\s*(?:сум|so['’]m|sum)", re.IGNORECASE)
PRODUCT_ID_RE = re.compile(r"/product/[^/?#]*?-(\d+)(?:[/?#]|$)")


def product_id_from_url(url: str) -> str | None:
    m = PRODUCT_ID_RE.search(url)
    return m.group(1) if m else None


def _text(tree: HTMLParser, selector: str) -> str | None:
    node = tree.css_first(selector)
    return node.text(separator=" ", strip=True) if node is not None else None


def parse_uzum_html(html: str, url: str = "") -> ScrapeResult:
    tree = HTMLParser(html)
    raw: dict = {"source": "uzum", "product_id": product_id_from_url(url)}

    price_text = _text(tree, PRICE_SEL)
    price = parse_price(price_text)
    raw["price_text"] = price_text
    if price is None or price == 0:
        og_title = meta_content(tree, "og:title") or ""
        m = OG_PRICE_RE.search(og_title)
        if m:
            price = parse_price(m.group(1))
            raw["price_from"] = "og:title"
    if price is None or price == 0:
        meta_amount = parse_price(meta_content(tree, "product:price:amount"))
        price = meta_amount if meta_amount else None

    old_price = parse_price(_text(tree, OLD_PRICE_SEL))
    if old_price is not None and price is not None and old_price <= price:
        old_price = None

    in_stock = availability_in_stock(meta_content(tree, "product:availability"))
    if in_stock is None:
        avail = (meta_content(tree, "product:availability") or "").lower()
        in_stock = False if "out" in avail else None
    cart_text = (_text(tree, CART_SEL) or "").lower()
    if any(p in cart_text for p in OUT_OF_STOCK_PHRASES):
        in_stock = False
    if in_stock is None:
        if price is None and not cart_text:
            # Nothing rendered at all: never mistake an empty SPA shell for "out of stock".
            raise ParseError("Uzum: page not rendered (no price, availability or cart button)")
        in_stock = price is not None

    title = _text(tree, TITLE_SEL) or ""
    if not title:
        og_title = meta_content(tree, "og:title") or ""
        title = re.split(r"\s+за\s+\d", og_title)[0]

    if price is None and in_stock:
        raise ParseError("Uzum: price element not found (layout changed or page not rendered)")
    return ScrapeResult(
        price=price, old_price=old_price, in_stock=in_stock, title=title.strip(), currency="UZS", raw=raw
    )


class UzumAdapter(BaseAdapter):
    code = "uzum"

    def fetch(self, url: str) -> ScrapeResult:
        # Uzum needs JS rendering regardless of the store flag.
        response = self.fetcher.get(url, render=True, store=self.store)
        result = self.parse(response.text, url)
        result.http_status = response.status_code
        return result

    def parse(self, html: str, url: str) -> ScrapeResult:
        return parse_uzum_html(html, url)
