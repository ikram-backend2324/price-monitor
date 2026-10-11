import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from django.core import mail
from django.utils import timezone

from apps.alerts import services, telegram
from apps.alerts.models import AlertEvent, AlertRule, TelegramLink
from apps.alerts.tasks import deliver_pending_alerts

from .factories import CategoryFactory, OfferFactory, ProductFactory, SnapshotFactory

K = AlertRule.Kind


@pytest.fixture
def offer(org):
    return OfferFactory(product=ProductFactory(organization=org, my_price=Decimal(100_000)))


def snaps(offer, prev_price, new_price, prev_stock=True, new_stock=True):
    now = timezone.now()
    prev = SnapshotFactory(offer=offer, price=prev_price, in_stock=prev_stock, checked_at=now - timedelta(hours=1))
    new = SnapshotFactory(offer=offer, price=new_price, in_stock=new_stock, checked_at=now)
    return prev, new


@pytest.mark.django_db
class TestEvaluate:
    def kinds(self, offer, *args, **kw):
        prev, new = snaps(offer, *args, **kw)
        return sorted(e.rule.kind for e in services.evaluate_snapshot(new.pk, prev.pk))

    def test_price_drop_and_cheaper(self, offer):
        assert self.kinds(offer, Decimal(120_000), Decimal(99_000)) == [K.CHEAPER_THAN_MINE, K.PRICE_DROP_PERCENT]

    def test_small_drop_ignored(self, offer):
        assert self.kinds(offer, Decimal(150_000), Decimal(148_000)) == []

    def test_already_cheaper_no_repeat(self, offer):
        # was 95k (already cheaper than my 100k) → 94k: only PRICE_DROP? 1% < 5% → nothing
        assert self.kinds(offer, Decimal(95_000), Decimal(94_000)) == []

    def test_stock_transitions(self, offer):
        assert self.kinds(offer, Decimal(120_000), Decimal(120_000), new_stock=False) == [K.OUT_OF_STOCK]
        assert self.kinds(offer, Decimal(120_000), Decimal(120_000), prev_stock=False) == [K.BACK_IN_STOCK]

    def test_price_changed_rule_and_scope(self, org, offer):
        cat = CategoryFactory(organization=org)
        AlertRule.objects.create(organization=org, kind=K.PRICE_CHANGED, scope="category", category=cat)
        assert K.PRICE_CHANGED not in self.kinds(offer, Decimal(120_000), Decimal(125_000))
        offer.product.category = cat
        offer.product.save()
        assert K.PRICE_CHANGED in self.kinds(offer, Decimal(125_000), Decimal(130_000))

    def test_product_scope(self, org, offer):
        rule = AlertRule.objects.create(organization=org, kind=K.PRICE_CHANGED, scope="product", product=offer.product)
        assert rule.applies_to(offer.product)
        assert not rule.applies_to(ProductFactory(organization=org))

    def test_inactive_rule(self, org, offer):
        AlertRule.objects.filter(organization=org).update(is_active=False)
        assert self.kinds(offer, Decimal(120_000), Decimal(50_000)) == []

    def test_no_duplicate_events(self, offer):
        prev, new = snaps(offer, Decimal(120_000), Decimal(90_000))
        services.evaluate_snapshot(new.pk, prev.pk)
        assert services.evaluate_snapshot(new.pk, prev.pk) == []


@pytest.mark.django_db
class TestDelivery:
    @pytest.fixture
    def linked(self, owner):
        return TelegramLink.objects.create(user=owner, chat_id=555, language="ru")

    def make_events(self, offer):
        offer.last_price, offer.last_in_stock = Decimal(90_000), True
        offer.save()
        prev, new = snaps(offer, Decimal(120_000), Decimal(90_000))
        return services.evaluate_snapshot(new.pk, prev.pk)

    def test_grouped_into_one_message(self, settings, offer, linked, respx_mock):
        settings.TELEGRAM_BOT_TOKEN = "123:abc"
        route = respx_mock.post("https://api.telegram.org/bot123:abc/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        events = self.make_events(offer)
        assert len(events) == 2
        assert deliver_pending_alerts() == 1
        assert route.call_count == 1
        payload = json.loads(route.calls[0].request.content)
        assert payload["chat_id"] == 555
        assert offer.product.name in payload["text"]
        buttons = [b for row in payload["reply_markup"]["inline_keyboard"] for b in row]
        assert any(b.get("callback_data", "").startswith("apply:") for b in buttons)
        assert any(b.get("callback_data", "").startswith("mute:") for b in buttons)
        assert all(e.sent and e.channel == "telegram" for e in AlertEvent.objects.all())

    def test_anti_spam_window(self, settings, offer, linked, respx_mock):
        settings.TELEGRAM_BOT_TOKEN = "123:abc"
        route = respx_mock.post("https://api.telegram.org/bot123:abc/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        self.make_events(offer)
        services.deliver_pending()
        # new event for the same product within 30 minutes → held back
        prev, new = snaps(offer, Decimal(90_000), Decimal(80_000))
        services.evaluate_snapshot(new.pk, prev.pk)
        assert services.deliver_pending() == 0
        assert AlertEvent.objects.filter(sent=False).exists()
        # 31 minutes later → sent as one batch
        assert services.deliver_pending(now=timezone.now() + timedelta(minutes=31)) == 1
        assert route.call_count == 2

    def test_without_token_logged(self, offer, linked):
        self.make_events(offer)
        services.deliver_pending()
        assert set(AlertEvent.objects.values_list("channel", flat=True)) == {"log"}

    def test_email_channel(self, org, offer):
        AlertRule.objects.filter(organization=org).update(notify_email=True, notify_telegram=False)
        self.make_events(offer)
        services.deliver_pending()
        assert len(mail.outbox) == 1
        assert offer.product.name in mail.outbox[0].subject

    def test_open_button_uses_url_for_public_site(self, settings, offer):
        settings.SITE_URL = "https://pricewatch.uz"
        events = self.make_events(offer)
        text, buttons = services.build_group_message(offer.product, events, "en")
        assert buttons[0][0]["url"].startswith("https://pricewatch.uz/products/")
        assert "Your price" in text


def test_public_url_allowed():
    assert telegram.public_url_allowed("https://pricewatch.uz/x")
    assert not telegram.public_url_allowed("http://localhost:8000/x")
    assert not telegram.public_url_allowed("http://web/x")


def test_send_message_http_error(settings, respx_mock):
    settings.TELEGRAM_BOT_TOKEN = "1:x"
    respx_mock.post("https://api.telegram.org/bot1:x/sendMessage").mock(return_value=httpx.Response(400, text="bad"))
    assert telegram.send_message(1, "hi") is False
    respx_mock.post("https://api.telegram.org/bot1:x/sendMessage").mock(side_effect=httpx.ConnectError("x"))
    assert telegram.send_message(1, "hi") is False


def test_admin_message(settings, respx_mock):
    assert telegram.send_admin_message("x") is False  # not configured
    settings.TELEGRAM_BOT_TOKEN = "1:x"
    settings.ADMIN_TELEGRAM_CHAT_ID = "42"
    respx_mock.post("https://api.telegram.org/bot1:x/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert telegram.send_admin_message("degraded") is True


@pytest.mark.django_db
def test_link_code(owner):
    link = TelegramLink.objects.create(user=owner)
    assert len(link.code) == 6 and not link.is_linked
    new_code = link.regenerate_code()
    assert len(new_code) == 6 and link.code_expires_at > timezone.now()
