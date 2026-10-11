from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing import services
from apps.billing.models import PaymentTransaction, Plan, Subscription
from apps.billing.payments import ManualProvider, get_provider
from apps.billing.tasks import expire_subscriptions

from .factories import OfferFactory, ProductFactory


@pytest.mark.django_db
def test_plans_seeded_by_migration():
    assert set(Plan.objects.values_list("code", flat=True)) >= {"free", "start", "business", "enterprise"}


@pytest.mark.django_db
def test_new_org_gets_trial(owner):
    from apps.accounts.services import create_organization

    org = create_organization(owner, "Trial Co")
    limits = services.get_limits(org)
    assert limits.plan_code == "free" and limits.max_offers == 20 and limits.usable
    assert org.subscription.status == Subscription.Status.TRIAL
    assert 13 <= org.subscription.days_left <= 14


@pytest.mark.django_db
def test_offer_limit(org):
    services.activate_plan(org, "start")
    Plan.objects.filter(code="start").update(max_offers=2)
    org.subscription.refresh_from_db()
    product = ProductFactory(organization=org)
    OfferFactory(product=product)
    services.check_offer_limit(org)
    OfferFactory(product=product)
    with pytest.raises(services.LimitExceeded):
        services.check_offer_limit(org)


@pytest.mark.django_db
def test_member_limit(org):
    Plan.objects.filter(code="business").update(max_members=1)
    org.subscription.refresh_from_db()
    with pytest.raises(services.LimitExceeded):
        services.check_member_limit(org)


@pytest.mark.django_db
def test_activate_extends_same_plan(org):
    first = org.subscription.expires_at
    services.activate_plan(org, "business", months=1)
    assert org.subscription.expires_at > first + timedelta(days=29)


@pytest.mark.django_db
def test_expire(org):
    Subscription.objects.filter(organization=org).update(expires_at=timezone.now() - timedelta(minutes=1))
    assert expire_subscriptions() == 1
    org.subscription.refresh_from_db()
    assert not org.subscription.is_usable
    assert not services.get_limits(org).usable


@pytest.mark.django_db
def test_no_subscription_fallback(db):
    from apps.accounts.models import Organization

    org = Organization.objects.create(name="Bare")
    assert services.get_limits(org) == services.FALLBACK


@pytest.mark.django_db
def test_manual_provider(org):
    plan = Plan.objects.get(code="start")
    intent = get_provider("manual").create_payment(org, plan, months=3)
    assert isinstance(get_provider(), ManualProvider)
    assert intent.transaction.amount_uzs == plan.price_uzs * 3
    assert intent.transaction.status == PaymentTransaction.Status.PENDING
    assert str(intent.transaction.id) in intent.instructions
