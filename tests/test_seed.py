import pytest
from django.core.management import call_command

from apps.accounts.models import Organization, User
from apps.alerts.models import AlertEvent
from apps.catalog.models import CompetitorOffer, Product, Store
from apps.pricing.models import PriceSnapshot


@pytest.mark.django_db
def test_seed_demo(settings):
    settings.DEMO_USER_PASSWORD = "demo-pass-1"
    call_command("seed_demo", "--products", "4", "--days", "10", "--no-admin")
    user = User.objects.get(email="demo@pricewatch.local")
    assert user.check_password("demo-pass-1")
    org = Organization.objects.get(name="Demo Electronics")
    assert org.subscription.plan.code == "enterprise"
    assert Product.objects.filter(organization=org).count() == 4
    assert CompetitorOffer.objects.filter(organization=org).count() == 12
    assert PriceSnapshot.objects.filter(offer__organization=org).count() >= 12 * 10
    assert CompetitorOffer.objects.filter(organization=org, last_price__isnull=True).count() == 0
    assert Store.objects.filter(domain="uzum.uz", adapter="uzum", requires_browser=True).exists()
    assert (
        AlertEvent.objects.filter(organization=org, sent=True).count()
        == AlertEvent.objects.filter(organization=org).count()
    )
    # idempotent without --reset, recreated with --reset
    call_command("seed_demo", "--products", "2", "--days", "3", "--no-admin")
    assert Product.objects.filter(organization=org).count() == 4
    call_command("seed_demo", "--products", "2", "--days", "3", "--no-admin", "--reset")
    assert Product.objects.filter(organization__name="Demo Electronics").count() == 2
