from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import AlertRule, TelegramLink
from bot import services
from bot.texts import TEXTS, t

from .factories import OfferFactory, ProductFactory


@pytest.fixture
def link(owner):
    return TelegramLink.objects.create(user=owner, code="ABC123", language="en")


@pytest.mark.django_db
class TestBotServices:
    def test_link_account(self, link, org):
        account = services.link_account(100, "seller", "abc123")
        assert account.org == org and account.lang == "en"
        link.refresh_from_db()
        assert link.chat_id == 100 and link.username == "seller"
        # code is one-time
        assert services.link_account(101, "x", "ABC123") is None

    def test_bad_or_expired_code(self, link):
        assert services.link_account(1, "", "zzz") is None
        TelegramLink.objects.filter(pk=link.pk).update(code_expires_at=timezone.now() - timedelta(minutes=1))
        assert services.link_account(1, "", "ABC123") is None

    def test_chat_moves_to_new_user(self, link, other_org):
        services.link_account(100, "", "ABC123")
        other_user = other_org.memberships.get().user
        TelegramLink.objects.create(user=other_user, code="DEF456")
        services.link_account(100, "", "DEF456")
        link.refresh_from_db()
        assert link.chat_id is None

    def test_products_and_summary(self, link, org):
        services.link_account(100, "", "ABC123")
        account = services.get_account(100)
        assert services.products_text(account) is None
        product = ProductFactory(organization=org, sku="TG-1", my_price=Decimal(200), cost_price=None)
        OfferFactory(product=product, last_price=Decimal(150), last_in_stock=True)
        text = services.products_text(account)
        assert "TG-1" in text and "🔴" in text
        assert services.find_product(account, "tg-1") == product
        assert "TG-1" in services.product_summary(product.pk, account)
        assert services.product_summary(999999, account) is None
        assert product.name in services.digest_text(account)  # listed under "more expensive"

    def test_apply_price_and_permissions(self, link, org, viewer):
        services.link_account(100, "", "ABC123")
        account = services.get_account(100)
        product = ProductFactory(organization=org)
        services.apply_price(account, product.pk, 77000)
        product.refresh_from_db()
        assert product.my_price == Decimal(77000)
        assert product.my_price_history.filter(source="telegram").exists()
        assert services.apply_price(account, 999999, 1) is None
        vlink = TelegramLink.objects.create(user=viewer, code="VVV111")
        services.link_account(200, "", vlink.code)
        with pytest.raises(PermissionError):
            services.apply_price(services.get_account(200), product.pk, 1)

    def test_mute_rule(self, link, org):
        services.link_account(100, "", "ABC123")
        rule = AlertRule.objects.filter(organization=org).first()
        assert services.mute_rule(services.get_account(100), rule.pk) == rule
        rule.refresh_from_db()
        assert not rule.is_active

    def test_set_language(self, link):
        services.link_account(100, "", "ABC123")
        assert services.set_language(100, "uz")
        assert not services.set_language(100, "de")
        assert services.get_account(100).lang == "uz"

    def test_queue_check(self, link, org, queued):
        product = ProductFactory(organization=org)
        OfferFactory(product=product)
        assert services.queue_check(product) == 1


def test_texts_complete():
    for key, variants in TEXTS.items():
        assert set(variants) == {"ru", "uz", "en"}, key
    assert "SKU" in t("check_usage", "en")
    assert t("check_usage", "xx") == TEXTS["check_usage"]["ru"]
