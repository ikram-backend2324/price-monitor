from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import AlertEvent, AlertRule
from apps.catalog.models import CompetitorOffer, Store
from apps.pricing.models import PriceSnapshot
from apps.scraping import services, tasks
from apps.scraping.adapters import ParseError, ScrapeResult
from apps.scraping.http import RateLimited, RobotsDisallowed
from apps.scraping.models import ScraperHealthEvent, ScrapeRun

from .factories import OfferFactory, ProductFactory, StoreFactory


class StubAdapter:
    code = "stub"

    def __init__(self, results):
        self.results = list(results)

    def fetch(self, url):
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def offer(org):
    product = ProductFactory(organization=org, my_price=Decimal("100000"), cost_price=Decimal("60000"))
    return OfferFactory(product=product, store=StoreFactory(domain="pipeline.test"))


def run(monkeypatch, offer, *results, django_capture_on_commit_callbacks=None):
    stub = StubAdapter(results)
    monkeypatch.setattr(services, "get_adapter", lambda store, fetcher: stub)
    outcomes = []
    for _ in results:
        outcomes.append(services.scrape_offer(CompetitorOffer.objects.get(pk=offer.pk), fetcher=object()))
    return outcomes


def R(price, in_stock=True, old=None):
    return ScrapeResult(
        price=Decimal(price) if price is not None else None, old_price=old, in_stock=in_stock, title="T"
    )


@pytest.mark.django_db(transaction=True)
class TestPipeline:
    def test_initial_then_unchanged_is_deduplicated(self, monkeypatch, offer):
        outcomes = run(monkeypatch, offer, R(95000), R(95000))
        assert [o.status for o in outcomes] == ["success", "unchanged"]
        assert PriceSnapshot.objects.filter(offer=offer).count() == 1
        assert ScrapeRun.objects.filter(offer=offer).count() == 2
        offer.refresh_from_db()
        assert offer.last_price == Decimal(95000)
        assert offer.last_status == CompetitorOffer.Status.OK

    def test_daily_control_snapshot(self, monkeypatch, offer):
        run(monkeypatch, offer, R(95000))
        PriceSnapshot.objects.filter(offer=offer).update(checked_at=timezone.now() - timedelta(days=1, hours=1))
        outcome = run(monkeypatch, offer, R(95000))[0]
        assert outcome.status == "success"
        assert outcome.snapshot.kind == PriceSnapshot.Kind.DAILY
        assert PriceSnapshot.objects.filter(offer=offer).count() == 2
        assert not AlertEvent.objects.exists()

    def test_change_creates_snapshot_and_alerts(self, monkeypatch, offer):
        run(monkeypatch, offer, R(120000), R(90000))
        snaps = PriceSnapshot.objects.filter(offer=offer).order_by("checked_at")
        assert [s.kind for s in snaps] == [PriceSnapshot.Kind.INITIAL, PriceSnapshot.Kind.CHANGE]
        kinds = set(AlertEvent.objects.values_list("rule__kind", flat=True))
        # 25% drop and became cheaper than my 100 000
        assert AlertRule.Kind.PRICE_DROP_PERCENT in kinds
        assert AlertRule.Kind.CHEAPER_THAN_MINE in kinds

    def test_out_of_stock_alert(self, monkeypatch, offer):
        run(monkeypatch, offer, R(120000), R(120000, in_stock=False), R(120000))
        kinds = list(AlertEvent.objects.order_by("created_at").values_list("rule__kind", flat=True))
        assert kinds == [AlertRule.Kind.OUT_OF_STOCK, AlertRule.Kind.BACK_IN_STOCK]

    def test_suspicious_value_confirmed(self, monkeypatch, offer):
        outcomes = run(monkeypatch, offer, R(120000), R(10000))
        assert outcomes[1].status == "suspicious"
        assert outcomes[1].recheck_in == 600
        offer.refresh_from_db()
        assert offer.last_price == Decimal(120000)  # not accepted yet
        assert offer.pending_snapshot is not None
        assert not AlertEvent.objects.exists()
        # re-check sees the same value → confirmed
        outcome = run(monkeypatch, offer, R(10000))[0]
        assert outcome.status == "success"
        offer.refresh_from_db()
        assert offer.last_price == Decimal(10000)
        assert offer.pending_snapshot is None
        assert AlertEvent.objects.filter(rule__kind=AlertRule.Kind.PRICE_DROP_PERCENT).exists()

    def test_suspicious_value_rejected(self, monkeypatch, offer):
        run(monkeypatch, offer, R(120000), R(10000))
        run(monkeypatch, offer, R(120000))
        offer.refresh_from_db()
        assert offer.last_price == Decimal(120000)
        assert PriceSnapshot.objects.filter(offer=offer, rejected=True).count() == 1
        assert not AlertEvent.objects.exists()

    def test_zero_price_is_suspicious(self, monkeypatch, offer):
        assert run(monkeypatch, offer, R(0))[0].status == "suspicious"

    def test_failures_trigger_offer_failing_event(self, monkeypatch, offer):
        run(monkeypatch, offer, *[ParseError("layout changed")] * 5)
        offer.refresh_from_db()
        assert offer.consecutive_failures == 5
        assert offer.last_status == CompetitorOffer.Status.FAILED
        assert ScraperHealthEvent.objects.filter(kind=ScraperHealthEvent.Kind.OFFER_FAILING).count() == 1
        # success resets the counter
        run(monkeypatch, offer, R(1000))
        offer.refresh_from_db()
        assert offer.consecutive_failures == 0

    def test_unexpected_exception_is_contained(self, monkeypatch, offer):
        outcome = run(monkeypatch, offer, ValueError("bug"))[0]
        assert outcome.status == "failed"
        assert "ValueError" in outcome.error

    def test_robots_blocked(self, monkeypatch, offer):
        assert run(monkeypatch, offer, RobotsDisallowed("no"))[0].status == "robots"
        offer.refresh_from_db()
        assert offer.robots_blocked and offer.last_status == CompetitorOffer.Status.BLOCKED

    def test_rate_limited(self, monkeypatch, offer):
        outcome = run(monkeypatch, offer, RateLimited("slow down", retry_after=90))[0]
        assert outcome.status == "rate_limited" and outcome.retry_after == 90


@pytest.mark.django_db
class TestHealth:
    def _runs(self, store, offer, ok, failed):
        now = timezone.now()
        for status, n in ((ScrapeRun.Status.SUCCESS, ok), (ScrapeRun.Status.FAILED, failed)):
            for _ in range(n):
                ScrapeRun.objects.create(offer=offer, store=store, started_at=now, status=status)

    def test_degraded_then_recovered(self, offer):
        store = offer.store
        self._runs(store, offer, ok=2, failed=8)
        events = services.check_store_health()
        assert [e.kind for e in events] == [ScraperHealthEvent.Kind.DEGRADED]
        store.refresh_from_db()
        assert store.health_status == Store.Health.DEGRADED
        assert services.check_store_health() == []  # no duplicate event
        ScrapeRun.objects.all().delete()
        self._runs(store, offer, ok=10, failed=0)
        events = services.check_store_health()
        assert [e.kind for e in events] == [ScraperHealthEvent.Kind.RECOVERED]

    def test_too_few_runs_ignored(self, offer):
        self._runs(offer.store, offer, ok=0, failed=3)
        assert services.check_store_health() == []

    def test_task_wrapper(self, offer):
        assert tasks.check_scraper_health() == 0


@pytest.mark.django_db
class TestScheduler:
    def test_schedules_due_offers_once(self, org, queued):
        due = OfferFactory(product=ProductFactory(organization=org), next_check_at=None)
        OfferFactory(product=ProductFactory(organization=org), next_check_at=timezone.now() + timedelta(hours=1))
        OfferFactory(product=ProductFactory(organization=org), next_check_at=None, is_active=False)
        assert tasks.schedule_due_offers() == 1
        due.refresh_from_db()
        # business plan: min interval 30, offer interval 60 → ~60 min ± 10%
        delta = (due.next_check_at - timezone.now()).total_seconds() / 60
        assert 50 <= delta <= 67
        assert queued.call_count == 1
        # second run: lock prevents duplicates and offer is no longer due
        assert tasks.schedule_due_offers() == 0

    def test_plan_interval_floor(self, org):
        from apps.billing.services import effective_interval

        offer = OfferFactory(product=ProductFactory(organization=org), check_interval_minutes=5)
        assert effective_interval(offer) == 30

    def test_expired_subscription_not_scheduled(self, org, queued):
        org.subscription.expires_at = timezone.now() - timedelta(days=1)
        org.subscription.save()
        OfferFactory(product=ProductFactory(organization=org), next_check_at=None)
        assert tasks.schedule_due_offers() == 0

    def test_browser_store_goes_to_browser_queue(self, org, monkeypatch):
        from unittest import mock

        fast, browser = mock.Mock(), mock.Mock()
        monkeypatch.setattr(tasks.scrape_offer_fast, "apply_async", fast)
        monkeypatch.setattr(tasks.scrape_offer_browser, "apply_async", browser)
        offer = OfferFactory(product=ProductFactory(organization=org), store=StoreFactory(requires_browser=True))
        assert tasks.enqueue_offer(offer)
        assert browser.called and not fast.called
        assert not tasks.enqueue_offer(offer)  # locked while queued

    def test_run_task_reschedules_suspicious(self, org, monkeypatch):
        offer = OfferFactory(product=ProductFactory(organization=org))
        monkeypatch.setattr(services, "scrape_offer", lambda o: services.Outcome("suspicious", recheck_in=600))
        calls = []
        monkeypatch.setattr(tasks, "enqueue_offer", lambda o, countdown=0: calls.append(countdown))
        assert tasks.scrape_offer_fast.run(offer.pk) == "suspicious"
        assert calls == [600]

    def test_run_task_missing_offer(self, db):
        assert tasks.scrape_offer_fast.run(999999) == "missing"

    def test_check_product_now(self, org, queued):
        product = ProductFactory(organization=org)
        OfferFactory(product=product)
        OfferFactory(product=product)
        assert tasks.check_product_now(product) == 2
