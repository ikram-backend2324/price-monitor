"""Scrape pipeline: fetch → validate → deduplicate → store → alerts → health."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.catalog.models import CompetitorOffer, Store
from apps.pricing.models import PriceSnapshot

from .adapters import ScrapeError, ScrapeResult, get_adapter
from .http import Fetcher, RateLimited, RobotsDisallowed
from .models import ScraperHealthEvent, ScrapeRun

log = logging.getLogger(__name__)


@dataclass
class Outcome:
    status: str
    snapshot: PriceSnapshot | None = None
    retry_after: float | None = None
    recheck_in: int | None = None
    error: str = ""


def is_suspicious(new: ScrapeResult, previous_price: Decimal | None) -> bool:
    if new.price is None:
        return False
    if new.price == 0:
        return True
    if previous_price:
        ratio = Decimal(settings.SCRAPER["SUSPICIOUS_RATIO"])
        return new.price > previous_price * ratio or new.price * ratio < previous_price
    return False


def _same_state(snapshot: PriceSnapshot | None, result: ScrapeResult) -> bool:
    return (
        snapshot is not None
        and snapshot.price == result.price
        and snapshot.old_price == result.old_price
        and snapshot.in_stock == result.in_stock
    )


def _close(a: Decimal | None, b: Decimal | None, tolerance: Decimal = Decimal("0.01")) -> bool:
    if a is None or b is None:
        return a == b
    if b == 0:
        return a == 0
    return abs(a - b) / b <= tolerance


def scrape_offer(offer: CompetitorOffer, fetcher: Fetcher | None = None) -> Outcome:
    """Check one offer end to end. Safe to call from tasks, the bot and the admin."""
    fetcher = fetcher or Fetcher()
    store = offer.store
    started = timezone.now()
    t0 = time.monotonic()
    adapter = get_adapter(store, fetcher)

    def record(status: str, error: str = "", http_status: int | None = None) -> None:
        ScrapeRun.objects.create(
            offer=offer,
            store=store,
            started_at=started,
            duration_ms=int((time.monotonic() - t0) * 1000),
            status=status,
            error=error[:500],
            http_status=http_status,
            adapter=adapter.code,
        )

    try:
        result = adapter.fetch(offer.url)
    except RobotsDisallowed as exc:
        offer.robots_blocked = True
        offer.last_status = CompetitorOffer.Status.BLOCKED
        offer.last_error = str(exc)[:500]
        offer.last_checked_at = started
        offer.save(update_fields=["robots_blocked", "last_status", "last_error", "last_checked_at", "updated_at"])
        record(ScrapeRun.Status.ROBOTS, str(exc))
        return Outcome("robots", error=str(exc))
    except RateLimited as exc:
        record(ScrapeRun.Status.RATE_LIMITED, str(exc), exc.http_status)
        return Outcome("rate_limited", retry_after=exc.retry_after, error=str(exc))
    except ScrapeError as exc:
        _register_failure(offer, str(exc), started)
        record(ScrapeRun.Status.FAILED, str(exc), exc.http_status)
        return Outcome("failed", error=str(exc))
    except Exception as exc:  # unexpected adapter bug — keep the worker alive
        log.exception("Unexpected scrape error for offer %s", offer.pk)
        msg = f"{exc.__class__.__name__}: {exc}"
        _register_failure(offer, msg, started)
        record(ScrapeRun.Status.FAILED, msg)
        return Outcome("failed", error=msg)

    outcome = _store_result(offer, result, started)
    record(
        outcome.status if outcome.status in ScrapeRun.Status.values else ScrapeRun.Status.SUCCESS,
        "",
        result.http_status,
    )
    return outcome


def _register_failure(offer: CompetitorOffer, error: str, when) -> None:
    offer.consecutive_failures += 1
    offer.last_status = CompetitorOffer.Status.FAILED
    offer.last_error = error[:500]
    offer.last_checked_at = when
    offer.save(update_fields=["consecutive_failures", "last_status", "last_error", "last_checked_at", "updated_at"])
    if offer.consecutive_failures == settings.SCRAPER["DEGRADED_CONSECUTIVE_FAILURES"]:
        event = ScraperHealthEvent.objects.create(
            store=offer.store,
            offer=offer,
            kind=ScraperHealthEvent.Kind.OFFER_FAILING,
            details=f"{offer.consecutive_failures} failures in a row for {offer.url}: {error[:300]}",
        )
        _notify_health(event)


@transaction.atomic
def _store_result(offer: CompetitorOffer, result: ScrapeResult, now) -> Outcome:
    offer = CompetitorOffer.objects.select_for_update().select_related("product", "store").get(pk=offer.pk)
    previous = offer.last_snapshot
    pending = offer.pending_snapshot

    offer.consecutive_failures = 0
    offer.last_checked_at = now
    offer.last_error = ""
    offer.robots_blocked = False
    if result.title:
        offer.last_title = result.title[:500]

    # --- confirm or reject a pending suspicious value -----------------------
    if pending is not None:
        offer.pending_snapshot = None
        if _close(result.price, pending.price) and result.in_stock == pending.in_stock:
            pending.is_suspicious = False
            pending.save(update_fields=["is_suspicious"])
            return _accept(offer, pending, previous, now, confirmed=True)
        pending.rejected = True
        pending.save(update_fields=["rejected"])

    # --- sanity check --------------------------------------------------------
    prev_price = previous.price if previous else None
    if is_suspicious(result, prev_price):
        snap = PriceSnapshot.objects.create(
            offer=offer,
            price=result.price,
            old_price=result.old_price,
            in_stock=result.in_stock,
            title=result.title[:500],
            currency=result.currency or "UZS",
            raw_payload=result.raw,
            checked_at=now,
            kind=PriceSnapshot.Kind.CHANGE,
            is_suspicious=True,
        )
        offer.pending_snapshot = snap
        offer.last_status = CompetitorOffer.Status.SUSPICIOUS
        offer.save()
        return Outcome("suspicious", snapshot=snap, recheck_in=settings.SCRAPER["RECHECK_SUSPICIOUS_SECONDS"])

    # --- deduplicate ---------------------------------------------------------
    if previous is not None and _same_state(previous, result):
        same_day = timezone.localdate(previous.checked_at) == timezone.localdate(now)
        if same_day:
            offer.last_status = CompetitorOffer.Status.OK
            offer.save()
            return Outcome("unchanged", snapshot=previous)
        kind = PriceSnapshot.Kind.DAILY
    else:
        kind = PriceSnapshot.Kind.INITIAL if previous is None else PriceSnapshot.Kind.CHANGE

    snap = PriceSnapshot.objects.create(
        offer=offer,
        price=result.price,
        old_price=result.old_price,
        in_stock=result.in_stock,
        title=result.title[:500],
        currency=result.currency or "UZS",
        raw_payload=result.raw,
        checked_at=now,
        kind=kind,
    )
    return _accept(offer, snap, previous, now, confirmed=False, evaluate=kind == PriceSnapshot.Kind.CHANGE)


def _accept(offer, snap: PriceSnapshot, previous, now, confirmed: bool, evaluate: bool = True) -> Outcome:
    offer.last_snapshot = snap
    offer.last_price = snap.price
    offer.last_old_price = snap.old_price
    offer.last_in_stock = snap.in_stock
    offer.last_status = CompetitorOffer.Status.OK
    offer.save()
    if evaluate:
        from apps.alerts.services import evaluate_snapshot

        transaction.on_commit(lambda: evaluate_snapshot(snap.pk, previous.pk if previous else None))
    return Outcome("success", snapshot=snap)


# --- Health ------------------------------------------------------------------


def store_success_rate(store: Store, since) -> tuple[float | None, int]:
    agg = ScrapeRun.objects.filter(store=store, started_at__gte=since).aggregate(
        total=Count("id"),
        ok=Count(
            "id",
            filter=Q(status__in=[ScrapeRun.Status.SUCCESS, ScrapeRun.Status.UNCHANGED, ScrapeRun.Status.SUSPICIOUS]),
        ),
    )
    total = agg["total"] or 0
    if total == 0:
        return None, 0
    return agg["ok"] / total, total


def check_store_health(min_runs: int = 5) -> list[ScraperHealthEvent]:
    """Mark stores degraded when success rate over the last hour < threshold."""
    threshold = settings.SCRAPER["DEGRADED_SUCCESS_RATE"]
    since = timezone.now() - timedelta(hours=1)
    events = []
    for store in Store.objects.filter(is_active=True):
        rate, total = store_success_rate(store, since)
        if rate is None or total < min_runs:
            continue
        if rate < threshold and store.health_status != Store.Health.DEGRADED:
            store.health_status = Store.Health.DEGRADED
            store.save(update_fields=["health_status", "updated_at"])
            event = ScraperHealthEvent.objects.create(
                store=store,
                kind=ScraperHealthEvent.Kind.DEGRADED,
                success_rate=rate,
                details=f"Success rate {rate:.0%} over {total} checks in the last hour",
            )
            _notify_health(event)
            events.append(event)
        elif rate >= threshold and store.health_status != Store.Health.OK:
            was_degraded = store.health_status == Store.Health.DEGRADED
            store.health_status = Store.Health.OK
            store.save(update_fields=["health_status", "updated_at"])
            if was_degraded:
                event = ScraperHealthEvent.objects.create(
                    store=store,
                    kind=ScraperHealthEvent.Kind.RECOVERED,
                    success_rate=rate,
                    details=f"Success rate back to {rate:.0%}",
                )
                _notify_health(event)
                events.append(event)
    return events


def _notify_health(event: ScraperHealthEvent) -> None:
    from apps.alerts.telegram import send_admin_message

    icon = "✅" if event.kind == ScraperHealthEvent.Kind.RECOVERED else "⚠️"
    text = f"{icon} <b>{event.kind}</b>\nStore: {event.store.name} ({event.store.domain})\n{event.details}"
    if send_admin_message(text):
        event.notified = True
        event.save(update_fields=["notified"])
