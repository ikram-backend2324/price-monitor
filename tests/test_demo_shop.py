import random
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from apps.scraping.adapters.demo import parse_demo_payload
from apps.scraping.adapters.jsonld import parse_jsonld_page
from apps.scraping.adapters.selector import SelectorConfig, parse_with_selectors
from demo_shop import main


@pytest.fixture
def shop():
    main.STATE.clear()
    main.STATE.update(main.initial_state(seed=1))
    return TestClient(main.app)


def test_catalog_size():
    assert len(main.CATALOG["products"]) >= 30
    assert set(main.SHOPS) == {"techbozor", "megasavdo", "smartmarket"}


def test_health_and_robots(shop):
    assert shop.get("/health").json()["status"] == "ok"
    assert "Disallow: /admin/" in shop.get("/robots.txt").text


def test_api_by_host_and_query(shop):
    a = shop.get("/api/product/PH-SAM-A55", headers={"host": "megasavdo.demo:8001"}).json()
    b = shop.get("/api/product/PH-SAM-A55?shop=smartmarket").json()
    assert a["shop"] == "megasavdo" and b["shop"] == "smartmarket"
    assert shop.get("/api/product/NOPE").status_code == 404


def test_pages_parse_with_every_adapter(shop):
    sku = "TV-SAM-55Q"
    api = parse_demo_payload(shop.get(f"/api/product/{sku}?shop=techbozor").text)
    ld = parse_jsonld_page(shop.get(f"/product/{sku}?shop=megasavdo").text)
    sel = parse_with_selectors(
        shop.get(f"/product/{sku}?shop=smartmarket").text,
        SelectorConfig(
            price_selector=".product-price",
            old_price_selector=".product-old-price",
            title_selector=".product-title",
            in_stock_selector=".add-to-cart",
            out_of_stock_selector=".out-of-stock",
        ),
    )
    for result, code in ((api, "techbozor"), (ld, "megasavdo"), (sel, "smartmarket")):
        item = main.STATE[code][sku]
        assert result.price == Decimal(item["price"])
        assert result.in_stock == item["in_stock"]
    assert "Samsung" in sel.title
    assert shop.get("/?shop=smartmarket").status_code == 200


def test_mutate_changes_prices():
    state = main.initial_state(seed=3)
    before = {(c, s): (i["price"], i["in_stock"]) for c, items in state.items() for s, i in items.items()}
    changed = main.mutate(state, share=0.5, rng=random.Random(5))
    after = {(c, s): (i["price"], i["in_stock"]) for c, items in state.items() for s, i in items.items()}
    assert changed > 10
    assert sum(before[k] != after[k] for k in before) > 5
    for items in state.values():
        for i in items.values():
            assert i["base"] * 0.69 <= i["price"] <= i["base"] * 1.31 or i["old_price"]


def test_force_mutate_endpoint(shop):
    assert shop.post("/_mutate?share=0.3").json()["changed"] >= 0
