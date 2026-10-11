from __future__ import annotations

from django.db import transaction

from .models import Membership, Organization, Role, User


@transaction.atomic
def create_organization(owner: User, name: str, plan_code: str | None = None) -> Organization:
    """Create an organization with an owner, a subscription and sane defaults."""
    from apps.alerts.services import create_default_alert_rules
    from apps.billing.services import activate_plan, start_trial
    from apps.pricing.models import PricingRule

    org = Organization.objects.create(name=name)
    Membership.objects.create(user=owner, organization=org, role=Role.OWNER)
    if plan_code:
        activate_plan(org, plan_code, months=12)
    else:
        start_trial(org)
    create_default_alert_rules(org)
    PricingRule.objects.create(
        organization=org,
        name="Default: undercut cheapest by 1 000",
        strategy=PricingRule.Strategy.UNDERCUT_MIN_BY_AMOUNT,
        amount=1000,
        min_margin_percent=5,
    )
    return org
