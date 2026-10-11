"""Adapter registry: Store.adapter code → adapter class."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BaseAdapter, ParseError, ScrapeError, ScrapeResult
from .demo import DemoShopAdapter
from .jsonld import JsonLdAdapter
from .selector import SelectorAdapter
from .uzum import UzumAdapter

if TYPE_CHECKING:
    from apps.catalog.models import Store

    from ..http import Fetcher

REGISTRY: dict[str, type[BaseAdapter]] = {
    cls.code: cls for cls in (DemoShopAdapter, JsonLdAdapter, SelectorAdapter, UzumAdapter)
}

# Domains that get a dedicated adapter even when no Store row says so.
DOMAIN_DEFAULTS = {"uzum.uz": "uzum"}


def register(cls: type[BaseAdapter]) -> type[BaseAdapter]:
    """Decorator for third-party adapters: ``@register class MyShopAdapter(BaseAdapter): code = 'myshop'``."""
    REGISTRY[cls.code] = cls
    return cls


def get_adapter(store: Store | None, fetcher: Fetcher) -> BaseAdapter:
    code = store.adapter if store else "jsonld"
    if store and store.domain in DOMAIN_DEFAULTS and code == "jsonld":
        code = DOMAIN_DEFAULTS[store.domain]
    cls = REGISTRY.get(code, JsonLdAdapter)
    return cls(store, fetcher)


__all__ = [
    "REGISTRY",
    "BaseAdapter",
    "ParseError",
    "ScrapeError",
    "ScrapeResult",
    "get_adapter",
    "register",
]
