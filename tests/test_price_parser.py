from decimal import Decimal

import pytest

from apps.scraping.price_parser import parse_price


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1 299 000 сум", "1299000"),
        ("1 299 000 сум", "1299000"),  # non-breaking spaces
        ("1 299 000", "1299000"),  # narrow no-break spaces
        ("1.299.000", "1299000"),
        ("1,299,000", "1299000"),
        ("1 299 000 so'm", "1299000"),
        ("1 299 000 so‘m", "1299000"),
        ("1'299'000", "1299000"),
        ("1 299 000,50", "1299000.50"),
        ("1299000.50", "1299000.50"),
        ("1.299.000,50", "1299000.50"),
        ("1,299,000.50", "1299000.50"),
        ("UZS 1 299 000", "1299000"),
        ("Цена: 89 900 сум", "89900"),
        ("от 99 000 сум", "99000"),
        ("99 000 – 120 000 сум", "99000"),
        ("$12.99", "12.99"),
        ("12,99 €", "12.99"),
        ("1.299", "1299"),  # 3-digit group → thousands (UZS has no fractions)
        ("0.5", "0.5"),
        ("2490000", "2490000"),
        ("  7 969 000  ", "7969000"),
        ("8 699 000 сум/мес", "8699000"),
    ],
)
def test_formats(raw, expected):
    assert parse_price(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [None, "", "   ", "Нет в наличии", "free", True, -5])
def test_returns_none(raw):
    assert parse_price(raw) is None


def test_numbers_pass_through():
    assert parse_price(1299000) == Decimal(1299000)
    assert parse_price(12.5) == Decimal("12.5")
    assert parse_price(Decimal("10")) == Decimal("10")
