from decimal import Decimal

import pytest

from apps.pricing.models import PricingRule
from apps.pricing.services import calculate, pick_rule, recommend_price

from .factories import CategoryFactory, OfferFactory, ProductFactory

S = PricingRule.Strategy
D = Decimal


def rule(strategy, **kw):
    defaults = {
        "name": "r",
        "strategy": strategy,
        "amount": D(0),
        "percent": D(0),
        "min_margin_percent": D(5),
        "round_to": 1000,
    }
    defaults.update(kw)
    return PricingRule(**defaults)


PRICES = [D(1_250_000), D(1_199_000), D(1_310_000)]


def test_undercut_amount():
    rec = calculate(PRICES, rule(S.UNDERCUT_MIN_BY_AMOUNT, amount=D(1000)), cost_price=D(900_000))
    assert rec.price == D(1_198_000)
    assert rec.market_min == D(1_199_000)
    assert rec.competitors == 3
    assert any("1 198 000" in s for s in rec.steps)


def test_undercut_percent_rounds_down():
    rec = calculate(PRICES, rule(S.UNDERCUT_MIN_BY_PERCENT, percent=D(2)), cost_price=None)
    # 1 199 000 * 0.98 = 1 175 020 → floor to 1 175 000
    assert rec.price == D(1_175_000)


def test_match_min():
    assert calculate(PRICES, rule(S.MATCH_MIN), None).price == D(1_199_000)


def test_average_rounds_half_up():
    rec = calculate(PRICES, rule(S.AVERAGE), None)
    # (1 250 000 + 1 199 000 + 1 310 000) / 3 = 1 253 000
    assert rec.price == D(1_253_000)


def test_margin_floor_wins():
    rec = calculate(
        [D(100_000)], rule(S.UNDERCUT_MIN_BY_AMOUNT, amount=D(5000), min_margin_percent=D(20)), cost_price=D(90_000)
    )
    # floor = 90 000 * 1.2 = 108 000 > 95 000
    assert rec.price == D(108_000)
    assert rec.floor == D(108_000)


def test_round_to_one():
    assert calculate([D("999.4")], rule(S.MATCH_MIN, round_to=1), None).price == D(999)


def test_no_prices():
    rec = calculate([], rule(S.MATCH_MIN), D(10))
    assert rec.price is None and rec.explanation


@pytest.mark.django_db
def test_rule_specificity(org):
    cat = CategoryFactory(organization=org)
    product = ProductFactory(organization=org, category=cat)
    PricingRule.objects.filter(organization=org).delete()
    all_rule = PricingRule.objects.create(organization=org, name="all", strategy=S.MATCH_MIN)
    assert pick_rule(product) == all_rule
    cat_rule = PricingRule.objects.create(
        organization=org, name="cat", strategy=S.AVERAGE, scope="category", category=cat
    )
    assert pick_rule(product) == cat_rule
    prod_rule = PricingRule.objects.create(
        organization=org, name="p", strategy=S.MATCH_MIN, scope="product", product=product
    )
    assert pick_rule(product) == prod_rule
    prod_rule.is_active = False
    prod_rule.save()
    assert pick_rule(product) == cat_rule


@pytest.mark.django_db
def test_default_rule_when_none(org):
    PricingRule.objects.filter(organization=org).delete()
    assert pick_rule(ProductFactory(organization=org)).name == "Default"


@pytest.mark.django_db
def test_recommend_price_ignores_out_of_stock(org):
    product = ProductFactory(organization=org, cost_price=None)
    OfferFactory(product=product, last_price=D(50_000), last_in_stock=False)
    OfferFactory(product=product, last_price=D(80_000), last_in_stock=True)
    rec = recommend_price(product)
    assert rec.market_min == D(80_000)
    assert rec.price == D(79_000)  # default rule of create_organization: min − 1000
