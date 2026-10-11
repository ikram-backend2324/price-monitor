from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value):
    """1299000 → '1 299 000' (thin-space grouping used in Uzbekistan)."""
    if value is None or value == "":
        return "—"
    try:
        value = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    return f"{value:,.0f}".replace(",", " ")


@register.filter
def pct(value, digits=1):
    if value is None:
        return "—"
    try:
        value = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{int(digits)}f}%"


@register.filter
def percent_of(part, total):
    try:
        return round(float(part) * 100 / float(total))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


@register.filter
def rate(value):
    if value is None:
        return "—"
    return f"{value * 100:.0f}%"
