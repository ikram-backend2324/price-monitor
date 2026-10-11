import json
from decimal import Decimal

import pytest

from apps.catalog.models import Store
from apps.scraping.adapters import REGISTRY, ParseError, get_adapter, register
from apps.scraping.adapters.base import BaseAdapter, ScrapeResult
from apps.scraping.adapters.demo import api_url, parse_demo_payload
from apps.scraping.adapters.jsonld import parse_jsonld_page
from apps.scraping.adapters.selector import SelectorConfig, parse_with_selectors
from apps.scraping.adapters.uzum import parse_uzum_html, product_id_from_url

from .conftest import fixture_text


def ld(obj) -> str:
    return f'<html><head><script type="application/ld+json">{json.dumps(obj)}</script></head><body></body></html>'


class TestJsonLd:
    def test_simple_offer(self):
        html = ld(
            {
                "@context": "https://schema.org",
                "@type": "Product",
                "name": "Phone",
                "offers": {
                    "@type": "Offer",
                    "price": "1299000",
                    "priceCurrency": "UZS",
                    "availability": "https://schema.org/InStock",
                },
            }
        )
        r = parse_jsonld_page(html)
        assert r.price == Decimal("1299000")
        assert r.in_stock is True
        assert r.title == "Phone"
        assert r.currency == "UZS"

    def test_graph_and_aggregate_offer_out_of_stock(self):
        html = ld(
            {
                "@graph": [
                    {"@type": "BreadcrumbList"},
                    {
                        "@type": ["Product"],
                        "name": "TV",
                        "offers": {
                            "@type": "AggregateOffer",
                            "lowPrice": 5490000,
                            "offers": [
                                {"@type": "Offer", "price": 5690000, "availability": "OutOfStock"},
                                {"@type": "Offer", "price": 5490000, "availability": "OutOfStock"},
                            ],
                        },
                    },
                ]
            }
        )
        r = parse_jsonld_page(html)
        assert r.price == Decimal("5490000")
        assert r.in_stock is False

    def test_strikethrough_old_price(self):
        html = ld(
            {
                "@type": "Product",
                "name": "Kettle",
                "offers": {
                    "@type": "Offer",
                    "price": "349000",
                    "priceSpecification": [
                        {"@type": "UnitPriceSpecification", "price": "349000"},
                        {
                            "@type": "UnitPriceSpecification",
                            "priceType": "https://schema.org/StrikethroughPrice",
                            "price": "399000",
                        },
                    ],
                },
            }
        )
        r = parse_jsonld_page(html)
        assert r.old_price == Decimal("399000")

    def test_broken_json_with_trailing_comma(self):
        html = (
            '<script type="application/ld+json">{"@type":"Product","name":"X","offers":{"price":"10 000",},}</script>'
        )
        assert parse_jsonld_page(html).price == Decimal("10000")

    def test_meta_tag_fallback(self):
        html = (
            '<html><head><meta property="og:title" content="Fridge">'
            '<meta property="product:price:amount" content="7290000">'
            '<meta property="product:availability" content="in stock"></head></html>'
        )
        r = parse_jsonld_page(html)
        assert r.price == Decimal("7290000")
        assert r.in_stock is True
        assert r.title == "Fridge"

    def test_microdata_fallback(self):
        html = '<div itemscope itemtype="https://schema.org/Product"><span itemprop="price" content="45000">45 000</span></div>'
        assert parse_jsonld_page(html).price == Decimal("45000")

    def test_no_product(self):
        with pytest.raises(ParseError):
            parse_jsonld_page("<html><body>Hello</body></html>")


class TestSelector:
    CFG = SelectorConfig(
        price_selector=".price",
        old_price_selector=".old",
        title_selector="h1",
        in_stock_selector=".buy",
        out_of_stock_selector=".oos",
        out_of_stock_text="нет в наличии",
        price_regex=r"([\d\s]+)\s*сум",
    )

    def test_in_stock(self):
        html = '<h1>Mouse</h1><div class="price">Цена 899 000 сум</div><div class="old">999 000 сум</div><button class="buy">Buy</button>'
        r = parse_with_selectors(html, self.CFG)
        assert (r.price, r.old_price, r.in_stock, r.title) == (Decimal("899000"), Decimal("999000"), True, "Mouse")

    def test_out_of_stock_by_selector(self):
        html = '<h1>Mouse</h1><div class="price">899 000 сум</div><div class="oos">Sold out</div>'
        assert parse_with_selectors(html, self.CFG).in_stock is False

    def test_out_of_stock_by_text(self):
        cfg = SelectorConfig(price_selector=".price", out_of_stock_text="Нет в наличии")
        html = '<body><div class="price">899 000</div><p>Товара нет в наличии</p></body>'
        assert parse_with_selectors(html, cfg).in_stock is False

    def test_missing_price_raises(self):
        with pytest.raises(ParseError):
            parse_with_selectors("<div>nothing</div>", SelectorConfig(price_selector=".price"))

    def test_no_selector_configured(self):
        with pytest.raises(ParseError):
            parse_with_selectors("<div/>", SelectorConfig(price_selector=""))


class TestDemo:
    def test_api_url(self):
        assert api_url("http://techbozor.demo:8001/product/A1?shop=techbozor") == (
            "http://techbozor.demo:8001/api/product/A1?shop=techbozor"
        )

    def test_payload(self):
        r = parse_demo_payload(
            json.dumps({"sku": "A1", "title": "T", "price": 1000, "old_price": None, "in_stock": False})
        )
        assert r.price == Decimal(1000) and r.in_stock is False and r.title == "T"

    def test_bad_payload(self):
        with pytest.raises(ParseError):
            parse_demo_payload("not json")
        with pytest.raises(ParseError):
            parse_demo_payload("{}")


class TestUzum:
    def test_in_stock_fixture(self):
        r = parse_uzum_html(fixture_text("uzum_in_stock.html"), "https://uzum.uz/ru/product/smartfon-poco-x8-2664408")
        assert r.price == Decimal("8699000")
        assert r.old_price == Decimal("9500000")
        assert r.in_stock is True
        assert r.title.startswith("Смартфон POCO X8 Pro Max")
        assert r.raw["product_id"] == "2664408"

    def test_out_of_stock_fixture(self):
        r = parse_uzum_html(
            fixture_text("uzum_out_of_stock.html"), "https://uzum.uz/ru/product/smartfon-samsung-galaxy-735185"
        )
        assert r.in_stock is False
        assert r.price == Decimal("7969000")

    def test_og_title_fallback(self):
        html = (
            '<html><head><meta property="og:title" content="Смартфон Redmi 15 за 2090000 сум по лучшей цене. Uzum Market">'
            '<meta property="product:availability" content="in stock"></head><body></body></html>'
        )
        r = parse_uzum_html(html)
        assert r.price == Decimal("2090000")
        assert r.title == "Смартфон Redmi 15"

    def test_spa_shell_raises(self):
        with pytest.raises(ParseError):
            parse_uzum_html('<html><body><div id="__nuxt"></div></body></html>')

    def test_product_id(self):
        assert product_id_from_url("https://uzum.uz/ru/product/smartfon-infinix-gt-1779911?skuId=6157392") == "1779911"
        assert product_id_from_url("https://example.com/") is None


@pytest.mark.django_db
class TestRegistry:
    def test_get_adapter_by_store(self):
        for code in ("demo", "jsonld", "selector", "uzum"):
            store = Store(domain=f"{code}.test", adapter=code)
            assert get_adapter(store, fetcher=None).code == code

    def test_uzum_domain_default(self):
        assert get_adapter(Store(domain="uzum.uz", adapter="jsonld"), fetcher=None).code == "uzum"

    def test_no_store_uses_jsonld(self):
        assert get_adapter(None, fetcher=None).code == "jsonld"

    def test_register_custom_adapter(self):
        @register
        class Custom(BaseAdapter):
            code = "custom-test"

            def parse(self, html, url):
                return ScrapeResult(price=Decimal(1))

        assert REGISTRY["custom-test"] is Custom
        REGISTRY.pop("custom-test")

    def test_store_for_url_matches_subdomain(self):
        Store.objects.create(name="Uzum", domain="uzum.uz", adapter="uzum")
        assert Store.for_url("https://www.uzum.uz/ru/product/x-1").domain == "uzum.uz"
        assert Store.for_url("https://m.uzum.uz/ru/product/x-1").domain == "uzum.uz"
        assert Store.for_url("https://other.uz/") is None
