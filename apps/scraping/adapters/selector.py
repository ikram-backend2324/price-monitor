from __future__ import annotations

import re
from dataclasses import dataclass

from selectolax.parser import HTMLParser

from ..price_parser import parse_price
from .base import BaseAdapter, ParseError, ScrapeResult


@dataclass
class SelectorConfig:
    price_selector: str
    old_price_selector: str = ""
    title_selector: str = ""
    in_stock_selector: str = ""
    out_of_stock_selector: str = ""
    out_of_stock_text: str = ""
    price_regex: str = ""

    @classmethod
    def from_store(cls, store) -> SelectorConfig:
        return cls(
            price_selector=store.price_selector,
            old_price_selector=store.old_price_selector,
            title_selector=store.title_selector,
            in_stock_selector=store.in_stock_selector,
            out_of_stock_selector=store.out_of_stock_selector,
            out_of_stock_text=store.out_of_stock_text,
            price_regex=store.price_regex,
        )


def _text(tree: HTMLParser, selector: str) -> str | None:
    if not selector:
        return None
    node = tree.css_first(selector)
    if node is None:
        return None
    return node.attributes.get("content") or node.text(separator=" ", strip=True)


def _clean_price(raw: str | None, regex: str):
    if raw is None:
        return None
    if regex:
        m = re.search(regex, raw)
        if m:
            raw = m.group(1) if m.groups() else m.group(0)
    return parse_price(raw)


def parse_with_selectors(html: str, cfg: SelectorConfig) -> ScrapeResult:
    if not cfg.price_selector:
        raise ParseError("Store has no price selector configured")
    tree = HTMLParser(html)
    raw_price = _text(tree, cfg.price_selector)
    price = _clean_price(raw_price, cfg.price_regex)
    old_price = _clean_price(_text(tree, cfg.old_price_selector), cfg.price_regex)
    title = _text(tree, cfg.title_selector) or ""

    in_stock = True
    if cfg.out_of_stock_selector and tree.css_first(cfg.out_of_stock_selector) is not None:
        in_stock = False
    elif cfg.in_stock_selector:
        in_stock = tree.css_first(cfg.in_stock_selector) is not None
    if in_stock and cfg.out_of_stock_text:
        body = (tree.body.text(separator=" ") if tree.body else "").lower()
        phrases = [p.strip().lower() for p in cfg.out_of_stock_text.split(",") if p.strip()]
        if any(p in body for p in phrases):
            in_stock = False

    if price is None and in_stock:
        raise ParseError(f"Price selector {cfg.price_selector!r} matched nothing usable (raw={raw_price!r})")
    if old_price is not None and price is not None and old_price <= price:
        old_price = None
    return ScrapeResult(
        price=price,
        old_price=old_price,
        in_stock=in_stock,
        title=title.strip(),
        raw={"source": "selector", "raw_price": raw_price},
    )


class SelectorAdapter(BaseAdapter):
    """Configured from the admin with CSS selectors — connect a new shop without code."""

    code = "selector"

    def parse(self, html: str, url: str) -> ScrapeResult:
        if self.store is None:
            raise ParseError("SelectorAdapter needs a Store with selectors")
        result = parse_with_selectors(html, SelectorConfig.from_store(self.store))
        result.currency = self.store.currency
        return result
