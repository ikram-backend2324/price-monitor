"""Reusable, layout-independent extraction helpers (JSON-LD, meta tags, microdata)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

from selectolax.parser import HTMLParser

from ..price_parser import parse_price

OUT_OF_STOCK_MARKERS = ("outofstock", "soldout", "discontinued", "preorder_unavailable")
IN_STOCK_MARKERS = ("instock", "limitedavailability", "onlineonly", "instoreonly", "preorder")


def load_json_loose(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Common breakages: trailing commas, HTML comments, raw newlines in strings
        cleaned = re.sub(r"<!--|-->", "", text)
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        cleaned = cleaned.replace("\n", " ").replace("\r", " ")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in node:
                yield from _walk(node[key])


def _is_type(node: dict, name: str) -> bool:
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(isinstance(x, str) and x.split("/")[-1].lower() == name.lower() for x in types)


def find_jsonld_products(tree: HTMLParser) -> list[dict]:
    products = []
    for script in tree.css('script[type="application/ld+json"]'):
        data = load_json_loose(script.text(deep=True, strip=False) or "")
        for node in _walk(data):
            if _is_type(node, "Product") or _is_type(node, "ProductGroup"):
                products.append(node)
    return products


def availability_in_stock(value: Any) -> bool | None:
    if value is None:
        return None
    s = str(value).lower().replace(" ", "").split("/")[-1]
    if any(m in s for m in OUT_OF_STOCK_MARKERS):
        return False
    if any(m in s for m in IN_STOCK_MARKERS):
        return True
    return None


def _offers(product: dict) -> list[dict]:
    offers = product.get("offers")
    if offers is None and "hasVariant" in product:  # ProductGroup
        offers = [v.get("offers") for v in product["hasVariant"] if isinstance(v, dict)]
    result: list[dict] = []
    for node in _walk(offers):
        if _is_type(node, "AggregateOffer") and "offers" in node:
            result.extend(n for n in _walk(node["offers"]))
        result.append(node)
    return [o for o in result if isinstance(o, dict)]


def product_from_jsonld(product: dict) -> dict[str, Any]:
    """Return {price, old_price, in_stock, currency, title} from a schema.org Product."""
    offers = _offers(product)
    prices: list[tuple[Decimal, dict]] = []
    old_price = None
    in_stock_flags = []
    currency = None
    for offer in offers:
        price = parse_price(offer.get("price"))
        if price is None:
            price = parse_price(offer.get("lowPrice"))
        if price is None and isinstance(offer.get("priceSpecification"), (dict, list)):
            for spec in _walk(offer["priceSpecification"]):
                ptype = str(spec.get("priceType", "")).lower()
                if "strikethrough" in ptype or "listprice" in ptype:
                    old_price = parse_price(spec.get("price"))
                elif price is None:
                    price = parse_price(spec.get("price"))
        elif isinstance(offer.get("priceSpecification"), (dict, list)):
            for spec in _walk(offer["priceSpecification"]):
                ptype = str(spec.get("priceType", "")).lower()
                if "strikethrough" in ptype or "listprice" in ptype:
                    old_price = parse_price(spec.get("price"))
        flag = availability_in_stock(offer.get("availability"))
        if flag is not None:
            in_stock_flags.append(flag)
        currency = currency or offer.get("priceCurrency")
        if price is not None and price > 0:
            prices.append((price, offer))
    price = min(p for p, _ in prices) if prices else None
    if old_price is not None and price is not None and old_price <= price:
        old_price = None
    title = product.get("name") or ""
    return {
        "price": price,
        "old_price": old_price,
        "in_stock": any(in_stock_flags) if in_stock_flags else None,
        "currency": (currency or "").upper()[:3] or None,
        "title": str(title).strip(),
    }


def meta_content(tree: HTMLParser, *names: str) -> str | None:
    for name in names:
        for attr in ("property", "name", "itemprop"):
            node = tree.css_first(f'meta[{attr}="{name}"]')
            if node is not None and node.attributes.get("content"):
                return node.attributes["content"]
    return None


def meta_product(tree: HTMLParser) -> dict[str, Any]:
    """Fallback: OpenGraph/product meta tags and schema.org microdata."""
    price_raw = meta_content(tree, "product:price:amount", "og:price:amount", "price")
    if price_raw is None:
        node = tree.css_first('[itemprop="price"]')
        if node is not None:
            price_raw = node.attributes.get("content") or node.text()
    availability = meta_content(tree, "product:availability", "og:availability", "availability")
    if availability is None:
        node = tree.css_first('[itemprop="availability"]')
        if node is not None:
            availability = node.attributes.get("href") or node.attributes.get("content")
    title_node = tree.css_first("title")
    title = meta_content(tree, "og:title") or (title_node.text() if title_node is not None else "")
    flag = availability_in_stock(availability)
    if availability and flag is None and "out" in availability.lower():
        flag = False
    return {
        "price": parse_price(price_raw),
        "old_price": None,
        "in_stock": flag,
        "currency": (meta_content(tree, "product:price:currency", "og:price:currency", "priceCurrency") or "")[:3]
        or None,
        "title": (title or "").strip(),
    }
