"""Recommended price calculation."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from django.utils.translation import gettext as _

from .models import PricingRule

DEFAULT_RULE = PricingRule(
    name="Default",
    strategy=PricingRule.Strategy.UNDERCUT_MIN_BY_AMOUNT,
    amount=Decimal("1000"),
    min_margin_percent=Decimal("5"),
    round_to=1000,
)


@dataclass
class Recommendation:
    price: Decimal | None
    rule_name: str
    strategy: str
    market_min: Decimal | None = None
    market_avg: Decimal | None = None
    competitors: int = 0
    floor: Decimal | None = None
    steps: list[str] = field(default_factory=list)

    @property
    def explanation(self) -> str:
        return "\n".join(self.steps)


def _round(value: Decimal, step: int, mode) -> Decimal:
    if step <= 1:
        return value.quantize(Decimal("1"), rounding=mode)
    step_d = Decimal(step)
    return (value / step_d).quantize(Decimal("1"), rounding=mode) * step_d


def pick_rule(product) -> PricingRule:
    rules = list(PricingRule.objects.filter(organization_id=product.organization_id, is_active=True))
    for scope, match in (
        (PricingRule.Scope.PRODUCT, lambda r: r.product_id == product.id),
        (PricingRule.Scope.CATEGORY, lambda r: product.category_id and r.category_id == product.category_id),
        (PricingRule.Scope.ALL, lambda r: True),
    ):
        candidates = [r for r in rules if r.scope == scope and match(r)]
        if candidates:
            return max(candidates, key=lambda r: r.priority)
    return DEFAULT_RULE


def fmt(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}".replace(",", " ")


def calculate(prices: list[Decimal], rule: PricingRule, cost_price: Decimal | None) -> Recommendation:
    rec = Recommendation(price=None, rule_name=rule.name, strategy=rule.get_strategy_display())
    rec.competitors = len(prices)
    if not prices:
        rec.steps.append(_("No in-stock competitor prices yet — nothing to recommend."))
        return rec
    rec.market_min = min(prices)
    rec.market_avg = sum(prices, Decimal(0)) / len(prices)
    rec.steps.append(
        _("Competitors in stock: %(n)d, cheapest %(min)s, average %(avg)s")
        % {"n": len(prices), "min": fmt(rec.market_min), "avg": fmt(rec.market_avg)}
    )

    S = PricingRule.Strategy
    if rule.strategy == S.UNDERCUT_MIN_BY_AMOUNT:
        candidate = rec.market_min - rule.amount
        rec.steps.append(_("Strategy: cheapest − %(a)s = %(c)s") % {"a": fmt(rule.amount), "c": fmt(candidate)})
        mode = ROUND_FLOOR
    elif rule.strategy == S.UNDERCUT_MIN_BY_PERCENT:
        candidate = rec.market_min * (Decimal(100) - rule.percent) / Decimal(100)
        rec.steps.append(_("Strategy: cheapest − %(p)s%% = %(c)s") % {"p": rule.percent, "c": fmt(candidate)})
        mode = ROUND_FLOOR
    elif rule.strategy == S.MATCH_MIN:
        candidate = rec.market_min
        rec.steps.append(_("Strategy: match the cheapest = %(c)s") % {"c": fmt(candidate)})
        mode = ROUND_FLOOR
    else:
        candidate = rec.market_avg
        rec.steps.append(_("Strategy: market average = %(c)s") % {"c": fmt(candidate)})
        mode = ROUND_HALF_UP

    price = _round(candidate, rule.round_to, mode)
    if price != candidate:
        rec.steps.append(_("Rounded to %(step)s: %(p)s") % {"step": fmt(Decimal(rule.round_to)), "p": fmt(price)})

    if cost_price:
        floor = _round(
            cost_price * (Decimal(100) + rule.min_margin_percent) / Decimal(100), rule.round_to, ROUND_CEILING
        )
        rec.floor = floor
        if price < floor:
            rec.steps.append(
                _("Below minimum margin %(m)s%% (floor %(f)s) — raised to the floor.")
                % {"m": rule.min_margin_percent, "f": fmt(floor)}
            )
            price = floor
        else:
            rec.steps.append(
                _("Margin check passed (floor %(f)s at %(m)s%% margin).")
                % {"f": fmt(floor), "m": rule.min_margin_percent}
            )
    else:
        rec.steps.append(_("Cost price is not set — margin is not checked."))

    rec.price = max(price, Decimal(0))
    rec.steps.append(_("Recommended price: %(p)s") % {"p": fmt(rec.price)})
    return rec


def recommend_price(product) -> Recommendation:
    prices = [
        o.last_price
        for o in product.offers.filter(is_active=True)
        if o.last_price is not None and o.last_in_stock is not False
    ]
    return calculate(prices, pick_rule(product), product.cost_price)
