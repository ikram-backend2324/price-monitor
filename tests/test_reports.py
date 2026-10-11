from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest
from django.utils import timezone

from apps.alerts.models import TelegramLink
from apps.reports import digest
from apps.reports.models import DigestLog
from apps.reports.tasks import send_due_digests

from .factories import OfferFactory, ProductFactory, SnapshotFactory


@pytest.fixture
def data(org):
    product = ProductFactory(organization=org, name="Fridge", my_price=Decimal(120_000))
    offer = OfferFactory(product=product, last_price=Decimal(100_000), last_in_stock=True)
    now = timezone.now()
    SnapshotFactory(offer=offer, price=Decimal(110_000), checked_at=now - timedelta(hours=30))
    SnapshotFactory(offer=offer, price=Decimal(100_000), checked_at=now - timedelta(hours=2))
    OfferFactory(product=product, last_price=Decimal(90_000), last_in_stock=False)
    return product


@pytest.mark.django_db
def test_collect(org, data):
    d = digest.collect(org)
    assert len(d.changes) == 1 and d.changes[0]["new"] == Decimal(100_000)
    assert d.more_expensive[0]["diff"] == Decimal(20_000)
    assert len(d.out_of_stock) == 1
    assert d.tracked_products == 1


@pytest.mark.django_db
@pytest.mark.parametrize("lang, word", [("ru", "Утренний"), ("uz", "dayjest"), ("en", "Morning")])
def test_render_languages(org, data, lang, word):
    text = digest.render_text(org, digest.collect(org), lang)
    assert "Fridge" in text
    if lang == "en":
        assert word in text


@pytest.mark.django_db
def test_send_once_per_day(settings, org, data, owner, respx_mock):
    settings.TELEGRAM_BOT_TOKEN = "1:x"
    route = respx_mock.post("https://api.telegram.org/bot1:x/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    TelegramLink.objects.create(user=owner, chat_id=777, language="en")
    assert digest.send_digest(org) == 1
    assert digest.send_digest(org) == 0
    assert route.call_count == 1
    assert DigestLog.objects.get(organization=org).recipients == 1
    assert digest.send_digest(org, force=True) == 1


@pytest.mark.django_db
def test_due_organizations(org):
    tz = ZoneInfo(org.timezone)
    org.digest_time = time(9, 0)
    org.save()
    before = datetime(2026, 10, 12, 8, 59, tzinfo=tz)
    after = datetime(2026, 10, 12, 9, 1, tzinfo=tz)
    assert org not in digest.due_organizations(before)
    assert org in digest.due_organizations(after)
    DigestLog.objects.create(organization=org, date=after.date())
    assert org not in digest.due_organizations(after)


@pytest.mark.django_db
def test_task(org):
    org.digest_time = time(0, 0)
    org.save()
    assert send_due_digests() == 0  # nobody linked, but the day is logged
    assert DigestLog.objects.filter(organization=org).exists()
