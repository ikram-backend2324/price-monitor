from __future__ import annotations

import logging
import random
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.billing.models import Subscription
from apps.billing.services import effective_interval
from apps.catalog.models import CompetitorOffer
from apps.core import locks

from . import services

log = logging.getLogger(__name__)

SCRAPE_LOCK_TTL = 300


def enqueue_offer(offer: CompetitorOffer, countdown: float = 0) -> bool:
    """Queue a check unless one is already queued/running for this offer."""
    if not locks.acquire(f"scrape:{offer.pk}", SCRAPE_LOCK_TTL):
        return False
    task = scrape_offer_browser if offer.store.requires_browser or offer.store.adapter == "uzum" else scrape_offer_fast
    try:
        task.apply_async(args=[offer.pk], countdown=countdown)
    except Exception:
        locks.release(f"scrape:{offer.pk}")
        raise
    return True


@shared_task(name="scraping.schedule_due_offers")
def schedule_due_offers() -> int:
    """Run every minute by Beat: queue offers whose check time has come, spreading load."""
    with locks.lock("schedule-due-offers", 55) as got:
        if not got:
            return 0
        now = timezone.now()
        usable = Q(organization__subscription__status__in=[Subscription.Status.TRIAL, Subscription.Status.ACTIVE]) & (
            Q(organization__subscription__expires_at__isnull=True) | Q(organization__subscription__expires_at__gt=now)
        )
        offers = list(
            CompetitorOffer.objects.due(now)
            .filter(usable)
            .select_related("store", "organization__subscription__plan")
            .order_by("next_check_at")[: settings.SCRAPER["SCHEDULE_BATCH"]]
        )
        queued = 0
        for offer in offers:
            interval = effective_interval(offer)
            # Jitter (±10%) so offers added together don't stay synchronized forever.
            jitter = random.uniform(-0.1, 0.1) * interval
            offer.next_check_at = now + timedelta(minutes=interval + jitter)
            offer.save(update_fields=["next_check_at"])
            if enqueue_offer(offer, countdown=random.uniform(0, 50)):
                queued += 1
        if queued:
            log.info("Queued %d offers", queued)
        return queued


def _run(task, offer_id: int) -> str:
    try:
        offer = CompetitorOffer.objects.select_related("store", "product").get(pk=offer_id)
    except CompetitorOffer.DoesNotExist:
        locks.release(f"scrape:{offer_id}")
        return "missing"
    try:
        outcome = services.scrape_offer(offer)
    finally:
        locks.release(f"scrape:{offer_id}")
    if outcome.status == "rate_limited" and outcome.retry_after:
        enqueue_offer(offer, countdown=min(outcome.retry_after, 3600))
    elif outcome.status == "suspicious" and outcome.recheck_in:
        enqueue_offer(offer, countdown=outcome.recheck_in)
    return outcome.status


@shared_task(name="scraping.scrape_offer_fast", bind=True, acks_late=True, soft_time_limit=120, time_limit=150)
def scrape_offer_fast(self, offer_id: int) -> str:
    return _run(self, offer_id)


@shared_task(name="scraping.scrape_offer_browser", bind=True, acks_late=True, soft_time_limit=180, time_limit=240)
def scrape_offer_browser(self, offer_id: int) -> str:
    return _run(self, offer_id)


@shared_task(name="scraping.check_scraper_health")
def check_scraper_health() -> int:
    return len(services.check_store_health())


def check_product_now(product) -> int:
    """Out-of-schedule check (bot /check, 'Check now' button)."""
    count = 0
    for offer in product.offers.filter(is_active=True, robots_blocked=False).select_related("store"):
        if enqueue_offer(offer):
            count += 1
    return count
