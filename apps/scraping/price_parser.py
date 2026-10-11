"""Robust price string → Decimal normalization.

Handles the formats seen on Uzbek and international shops::

    "1 299 000 сум", "1.299.000", "1,299,000", "1 299 000 so'm", "1 299 000,50",
    "1299000.50", "UZS 1 299 000", "$12.99", "12,99 €", "от 99 000 сум",
    non-breaking / thin spaces, apostrophe thousands separators ("1'299'000").
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Characters used as thousands separators besides '.' and ','
_SPACE_SEPARATORS = "     '’`"
_NUMBER_RE = re.compile(r"\d[\d" + re.escape(_SPACE_SEPARATORS) + r".,]*")


def parse_price(value: object) -> Decimal | None:
    """Return the first price found in ``value`` or ``None``.

    Numbers (int/float/Decimal) are passed through. Ranges like ``"99 000 – 120 000"``
    return the first value.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, Decimal)):
        return Decimal(value) if value >= 0 else None
    if isinstance(value, float):
        return Decimal(str(value)) if value >= 0 else None

    text = str(value).strip()
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    token = match.group(0)
    # Strip trailing separators (e.g. "1 299 000 " or "99.")
    token = token.rstrip(_SPACE_SEPARATORS + ".,")
    for ch in _SPACE_SEPARATORS:
        token = token.replace(ch, "")

    token = _normalize_separators(token)
    try:
        result = Decimal(token)
    except InvalidOperation:
        return None
    return result if result >= 0 else None


def _normalize_separators(token: str) -> str:
    has_dot, has_comma = "." in token, "," in token
    if has_dot and has_comma:
        # The right-most separator is the decimal one.
        if token.rfind(".") > token.rfind(","):
            return token.replace(",", "")
        return token.replace(".", "").replace(",", ".")
    sep = "." if has_dot else "," if has_comma else None
    if sep is None:
        return token
    parts = token.split(sep)
    if len(parts) > 2:
        # "1.299.000" — repeated separator is always thousands
        return token.replace(sep, "")
    integer, fraction = parts
    if len(fraction) == 3 and integer != "0":
        # "1.299" / "99,000" — treat as thousands (UZS prices have no fractions)
        return integer + fraction
    return integer + "." + fraction
