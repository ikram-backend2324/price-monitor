from __future__ import annotations

import abc
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.catalog.models import Store

    from ..http import Fetcher


class ScrapeError(Exception):
    """Page fetched but data could not be extracted (layout changed, product removed...)."""

    def __init__(self, message: str, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


class ParseError(ScrapeError):
    pass


@dataclass
class ScrapeResult:
    price: Decimal | None
    old_price: Decimal | None = None
    in_stock: bool = True
    title: str = ""
    currency: str = "UZS"
    raw: dict[str, Any] = field(default_factory=dict)
    http_status: int | None = 200

    def as_dict(self) -> dict[str, Any]:
        return {
            "price": str(self.price) if self.price is not None else None,
            "old_price": str(self.old_price) if self.old_price is not None else None,
            "in_stock": self.in_stock,
            "title": self.title,
            "currency": self.currency,
        }


class BaseAdapter(abc.ABC):
    """A site-specific extractor.

    ``fetch`` downloads the page (through the shared polite ``Fetcher``) and
    delegates to ``parse``. Keep all layout-dependent logic in ``parse`` so a
    markup change only touches one function and can be tested on a saved fixture.
    """

    code: str = "base"

    def __init__(self, store: Store | None, fetcher: Fetcher):
        self.store = store
        self.fetcher = fetcher

    def fetch(self, url: str) -> ScrapeResult:
        response = self.fetcher.get(url, render=bool(self.store and self.store.requires_browser), store=self.store)
        result = self.parse(response.text, url)
        result.http_status = response.status_code
        if self.store and not result.currency:
            result.currency = self.store.currency
        return result

    @abc.abstractmethod
    def parse(self, html: str, url: str) -> ScrapeResult: ...
