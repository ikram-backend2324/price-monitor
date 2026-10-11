"""Plan limits and subscription lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _

from .models import Plan, Subscription
from .plans import DEFAULT_PLANS


class LimitExceeded(Exception):
    """Raised when an action would exceed the organization's plan limits."""


@dataclass(frozen=True)
class Limits:
    plan_code: str
    plan_name: str
    max_offers: int
    min_check_interval_minutes: int
    max_members: int
    telegram_alerts: bool
    excel_reports: bool
    api_access: bool
    usable: bool


FALLBACK = Limits("none", "No plan", 0, 1440, 1, False, False, False, False)


def ensure_default_plans() -> None:
    for data in DEFAULT_PLANS:
        Plan.objects.update_or_create(code=data["code"], defaults=data)


def get_subscription(org) -> Subscription | None:
    try:
        return org.subscription
    except Subscription.DoesNotExist:
        return None


def get_limits(org) -> Limits:
    sub = get_subscription(org)
    if sub is None:
        return FALLBACK
    p = sub.plan
    return Limits(
        plan_code=p.code,
        plan_name=p.name,
        max_offers=p.max_offers,
        min_check_interval_minutes=p.min_check_interval_minutes,
        max_members=p.max_members,
        telegram_alerts=p.telegram_alerts,
        excel_reports=p.excel_reports,
        api_access=p.api_access,
        usable=sub.is_usable,
    )


def offers_used(org) -> int:
    from apps.catalog.models import CompetitorOffer

    return CompetitorOffer.objects.filter(organization=org, is_active=True).count()


def check_offer_limit(org, adding: int = 1) -> None:
    limits = get_limits(org)
    used = offers_used(org)
    if used + adding > limits.max_offers:
        raise LimitExceeded(
            _("Your plan %(plan)s allows %(max)d tracked links (used %(used)d). Upgrade to add more.")
            % {"plan": limits.plan_name, "max": limits.max_offers, "used": used}
        )


def check_member_limit(org) -> None:
    limits = get_limits(org)
    count = org.memberships.count() + org.invitations.filter(accepted_at__isnull=True).count()
    if count + 1 > limits.max_members:
        raise LimitExceeded(
            _("Your plan allows %(max)d team members. Upgrade to invite more.") % {"max": limits.max_members}
        )


def effective_interval(offer) -> int:
    """Check interval in minutes, never faster than the plan allows."""
    limits = get_limits(offer.organization)
    return max(offer.check_interval_minutes, limits.min_check_interval_minutes)


def start_trial(org) -> Subscription:
    ensure_default_plans()
    plan = Plan.objects.get(code="free")
    sub = Subscription.objects.update_or_create(
        organization=org,
        defaults={
            "plan": plan,
            "status": Subscription.Status.TRIAL,
            "started_at": timezone.now(),
            "expires_at": timezone.now() + timedelta(days=plan.trial_days or 14),
        },
    )[0]
    org.subscription = sub  # refresh the cached reverse relation
    return sub


def activate_plan(org, plan_code: str, months: int = 1, by=None) -> Subscription:
    """Manual activation (by admin) or after a confirmed payment."""
    ensure_default_plans()
    plan = Plan.objects.get(code=plan_code)
    sub = get_subscription(org)
    now = timezone.now()
    base = sub.expires_at if sub and sub.is_usable and sub.plan_id == plan.id and sub.expires_at else now
    expires = max(base, now) + timedelta(days=30 * months)
    sub, _created = Subscription.objects.update_or_create(
        organization=org,
        defaults={"plan": plan, "status": Subscription.Status.ACTIVE, "expires_at": expires, "activated_by": by},
    )
    org.subscription = sub
    return sub


def expire_subscriptions() -> int:
    now = timezone.now()
    return Subscription.objects.filter(
        status__in=[Subscription.Status.TRIAL, Subscription.Status.ACTIVE], expires_at__lt=now
    ).update(status=Subscription.Status.EXPIRED)
