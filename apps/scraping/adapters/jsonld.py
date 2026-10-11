from __future__ import annotations

from selectolax.parser import HTMLParser

from .base import BaseAdapter, ParseError, ScrapeResult
from .extract import find_jsonld_products, meta_product, product_from_jsonld


def parse_jsonld_page(html: str, url: str = "") -> ScrapeResult:
    tree = HTMLParser(html)
    data: dict = {}
    for product in find_jsonld_products(tree):
        candidate = product_from_jsonld(product)
        if candidate["price"] is not None or candidate["in_stock"] is False:
            data = candidate
            break
    if not data or data["price"] is None:
        meta = meta_product(tree)
        for key, value in meta.items():
            if data.get(key) in (None, "") and value not in (None, ""):
                data[key] = value
    if not data or (data.get("price") is None and data.get("in_stock") is not False):
        raise ParseError("No schema.org Product price found on page")
    return ScrapeResult(
        price=data.get("price"),
        old_price=data.get("old_price"),
        in_stock=True if data.get("in_stock") is None else bool(data["in_stock"]),
        title=data.get("title") or "",
        currency=data.get("currency") or "UZS",
        raw={"source": "jsonld", **{k: str(v) if v is not None else None for k, v in data.items()}},
    )


class JsonLdAdapter(BaseAdapter):
    """Universal adapter: works on any shop exposing schema.org Product/Offer markup."""

    code = "jsonld"

    def parse(self, html: str, url: str) -> ScrapeResult:
        return parse_jsonld_page(html, url)
