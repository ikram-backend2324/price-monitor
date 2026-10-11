"""Create a ready-to-show demo: organization, user, 25 products × 3 competitors, 30 days of history."""

from __future__ import annotations

import json
import random
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Organization, User
from apps.accounts.services import create_organization
from apps.alerts.models import AlertEvent
from apps.alerts.services import evaluate_snapshot
from apps.billing.services import ensure_default_plans
from apps.catalog.models import Category, CompetitorOffer, MyPriceChange, Product, Store
from apps.pricing.models import PriceSnapshot

CATALOG_PATH = Path(settings.BASE_DIR) / "demo_shop" / "catalog.json"
DEMO_EMAIL = "demo@pricewatch.local"
ADMIN_EMAIL = "admin@pricewatch.local"
ORG_NAME = "Demo Electronics"

SHOP_STORES = {
    "techbozor": {"name": "TechBozor", "adapter": Store.Adapter.DEMO},
    "megasavdo": {"name": "Mega Savdo", "adapter": Store.Adapter.JSONLD},
    "smartmarket": {
        "name": "Smart Market",
        "adapter": Store.Adapter.SELECTOR,
        "price_selector": ".product-price",
        "old_price_selector": ".product-old-price",
        "title_selector": ".product-title",
        "in_stock_selector": ".add-to-cart",
        "out_of_stock_selector": ".out-of-stock",
        "out_of_stock_text": "нет в наличии, mavjud emas",
    },
}


def r1000(value: float) -> Decimal:
    step = 1000 if value >= 100_000 else 100
    return Decimal(int(round(value / step) * step))


def ensure_stores() -> dict[str, Store]:
    stores = {}
    for code, cfg in SHOP_STORES.items():
        host = settings.DEMO_SHOP_HOSTS[code].split(":")[0]
        defaults: dict[str, object] = dict(cfg)
        defaults.update({"rate_limit_per_minute": 120, "health_status": Store.Health.OK, "notes": "Bundled demo shop"})
        stores[code], _ = Store.objects.update_or_create(domain=host, defaults=defaults)
    Store.objects.update_or_create(
        domain="uzum.uz",
        defaults={
            "name": "Uzum Market",
            "adapter": Store.Adapter.UZUM,
            "requires_browser": True,
            "rate_limit_per_minute": 6,
            "wait_selector": '[data-test-id="text__product-price"]',
            "notes": "Nuxt SPA: rendered with Playwright. See apps/scraping/adapters/uzum.py",
        },
    )
    return stores


class Command(BaseCommand):
    help = "Seed the demo organization with products, competitors and 30 days of price history"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete the demo organization first")
        parser.add_argument("--products", type=int, default=25)
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--no-admin", action="store_true", help="Do not create admin@pricewatch.local")
        parser.add_argument("--seed", type=int, default=7)

    @transaction.atomic
    def handle(self, *args, **opts):
        rng = random.Random(opts["seed"])
        ensure_default_plans()
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        stores = ensure_stores()
        password = settings.DEMO_USER_PASSWORD

        if opts["reset"]:
            Organization.objects.filter(name=ORG_NAME, memberships__user__email=DEMO_EMAIL).delete()

        user, created = User.objects.get_or_create(email=DEMO_EMAIL, defaults={"first_name": "Demo", "language": "ru"})
        user.set_password(password)
        user.save()
        if not opts["no_admin"] and not User.objects.filter(email=ADMIN_EMAIL).exists():
            User.objects.create_superuser(ADMIN_EMAIL, password)
            self.stdout.write(f"Superuser {ADMIN_EMAIL} created (same password as demo user)")

        org = Organization.objects.filter(name=ORG_NAME, memberships__user=user).first()
        if org is not None:
            self.stdout.write(self.style.WARNING("Demo organization already exists — use --reset to recreate."))
            return
        org = create_organization(user, ORG_NAME, plan_code="enterprise")

        now = timezone.now()
        start = now - timedelta(days=opts["days"])
        snapshots: list[PriceSnapshot] = []
        offer_last: dict[int, PriceSnapshot] = {}

        for item in catalog["products"][: opts["products"]]:
            category, _ = Category.objects.get_or_create(organization=org, name=item["category"])
            base = item["price"]
            my_price = r1000(base * rng.uniform(0.98, 1.07))
            product = Product.objects.create(
                organization=org,
                sku=item["sku"],
                name=item["name"],
                category=category,
                my_price=my_price,
                cost_price=r1000(base * rng.uniform(0.78, 0.86)),
            )
            # my price history: initial + maybe one change
            initial_mine = r1000(float(my_price) * rng.uniform(1.0, 1.05))
            MyPriceChange.objects.create(product=product, price=initial_mine, source="seed")
            MyPriceChange.objects.filter(product=product).update(changed_at=start)
            if initial_mine != my_price:
                change = MyPriceChange.objects.create(product=product, price=my_price, source="seed")
                MyPriceChange.objects.filter(pk=change.pk).update(changed_at=start + timedelta(days=rng.randint(5, 25)))

            for code, store in stores.items():
                host = settings.DEMO_SHOP_HOSTS[code]
                offer = CompetitorOffer.objects.create(
                    organization=org,
                    product=product,
                    store=store,
                    url=f"http://{host}/product/{item['sku']}?shop={code}",
                    check_interval_minutes=5,
                    next_check_at=now + timedelta(seconds=rng.randint(30, 300)),
                )
                snapshots += self._history(offer, base * catalog["shops"][code]["factor"], start, now, rng)

        PriceSnapshot.objects.bulk_create(snapshots, batch_size=1000)
        # denormalized "current state" on offers
        for offer in CompetitorOffer.objects.filter(organization=org):
            last = PriceSnapshot.objects.filter(offer=offer).order_by("-checked_at").first()
            if last:
                offer_last[offer.pk] = last
                CompetitorOffer.objects.filter(pk=offer.pk).update(
                    last_snapshot=last,
                    last_price=last.price,
                    last_old_price=last.old_price,
                    last_in_stock=last.in_stock,
                    last_title=last.title,
                    last_checked_at=last.checked_at,
                    last_status=CompetitorOffer.Status.OK,
                )

        # Alerts for the last 2 days of history so the dashboard has something to show.
        recent = PriceSnapshot.objects.filter(
            offer__organization=org, kind=PriceSnapshot.Kind.CHANGE, checked_at__gte=now - timedelta(days=2)
        ).order_by("checked_at")
        for snap in recent:
            prev = (
                PriceSnapshot.objects.filter(offer_id=snap.offer_id, checked_at__lt=snap.checked_at)
                .order_by("-checked_at")
                .first()
            )
            for event in evaluate_snapshot(snap.pk, prev.pk if prev else None):
                AlertEvent.objects.filter(pk=event.pk).update(
                    sent=True, sent_at=snap.checked_at, channel=AlertEvent.Channel.LOG, created_at=snap.checked_at
                )

        n_products = Product.objects.filter(organization=org).count()
        n_offers = CompetitorOffer.objects.filter(organization=org).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo ready: {n_products} products, {n_offers} competitor links, {len(snapshots)} snapshots.\n"
                f"Log in as {DEMO_EMAIL} / {password}"
            )
        )

    def _history(self, offer, base: float, start, now, rng: random.Random) -> list[PriceSnapshot]:
        """Plausible random walk: occasional price moves, promos and stock-outs."""
        snaps = []
        price = float(r1000(base * rng.uniform(0.96, 1.05)))
        old_price = None
        in_stock = True
        out_days = 0
        day = start
        title = offer.product.name

        def snap(at, kind):
            snaps.append(
                PriceSnapshot(
                    offer=offer,
                    price=Decimal(price),
                    old_price=Decimal(old_price) if old_price else None,
                    in_stock=in_stock,
                    title=title,
                    checked_at=at,
                    kind=kind,
                    raw_payload={"source": "seed"},
                )
            )

        snap(start, PriceSnapshot.Kind.INITIAL)
        while True:
            day += timedelta(days=1)
            if day > now:
                break
            changed = False
            if out_days:
                out_days -= 1
                if out_days == 0:
                    in_stock = True
                    changed = True
            elif rng.random() < 0.03:
                in_stock = False
                out_days = rng.randint(1, 3)
                changed = True
            roll = rng.random()
            if roll < 0.10 and old_price is None:
                old_price = price
                price = float(r1000(price * rng.uniform(0.82, 0.94)))
                changed = True
            elif roll < 0.16 and old_price is not None:
                price, old_price = old_price, None
                changed = True
            elif roll < 0.40:
                price = float(r1000(price * (1 + rng.uniform(-0.06, 0.05))))
                price = max(float(r1000(base * 0.75)), min(price, float(r1000(base * 1.25))))
                changed = True
            at = day.replace(hour=rng.randint(6, 22), minute=rng.randint(0, 59))
            if at > now:
                at = now - timedelta(minutes=rng.randint(5, 60))
            snap(at, PriceSnapshot.Kind.CHANGE if changed else PriceSnapshot.Kind.DAILY)
        return snaps
