from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlsplit

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantQuerySet, TimeStampedModel


def normalize_domain(value: str) -> str:
    """'https://www.Uzum.uz/ru/product/1' -> 'uzum.uz'."""
    value = value.strip().lower()
    if "//" in value:
        value = urlsplit(value).hostname or ""
    value = value.split("/")[0].split(":")[0]
    return value[4:] if value.startswith("www.") else value


class Store(TimeStampedModel):
    """A competitor website. Global (shared by all tenants), managed by system admins."""

    class Adapter(models.TextChoices):
        DEMO = "demo", "Demo shop (JSON API)"
        JSONLD = "jsonld", "Universal JSON-LD (schema.org)"
        SELECTOR = "selector", "CSS selectors (configured below)"
        UZUM = "uzum", "Uzum Market"

    class Health(models.TextChoices):
        OK = "ok", _("OK")
        DEGRADED = "degraded", _("Degraded")
        UNKNOWN = "unknown", _("Unknown")

    name = models.CharField(_("name"), max_length=120)
    domain = models.CharField(_("domain"), max_length=190, unique=True, help_text="e.g. uzum.uz (no www)")
    adapter = models.CharField(max_length=16, choices=Adapter.choices, default=Adapter.JSONLD)
    is_active = models.BooleanField(default=True)
    requires_browser = models.BooleanField(
        _("requires browser"), default=False, help_text="Render with Playwright (slow; only for JS-only sites)"
    )
    rate_limit_per_minute = models.PositiveIntegerField(default=20)
    currency = models.CharField(max_length=3, default="UZS")
    # SelectorAdapter configuration
    price_selector = models.CharField(max_length=255, blank=True)
    old_price_selector = models.CharField(max_length=255, blank=True)
    title_selector = models.CharField(max_length=255, blank=True)
    in_stock_selector = models.CharField(
        max_length=255, blank=True, help_text="Element present ⇒ in stock (e.g. 'button.add-to-cart')"
    )
    out_of_stock_selector = models.CharField(
        max_length=255, blank=True, help_text="Element present ⇒ out of stock (takes priority)"
    )
    out_of_stock_text = models.CharField(
        max_length=255, blank=True, help_text="Comma-separated phrases meaning 'out of stock'"
    )
    price_regex = models.CharField(
        max_length=255, blank=True, help_text=r"Optional regex with one group to cut the price, e.g. ([\d\s]+)\s*сум"
    )
    wait_selector = models.CharField(
        max_length=255, blank=True, help_text="Browser mode: wait for this selector before reading the page"
    )
    health_status = models.CharField(max_length=16, choices=Health.choices, default=Health.UNKNOWN)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.domain = normalize_domain(self.domain)
        super().save(*args, **kwargs)

    @classmethod
    def for_url(cls, url: str) -> Store | None:
        host = normalize_domain(url)
        candidates = [host]
        parts = host.split(".")
        candidates += [".".join(parts[i:]) for i in range(1, len(parts) - 1)]
        return cls.objects.filter(domain__in=candidates).order_by("-domain").first()


class Category(TimeStampedModel):
    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(_("name"), max_length=120)

    objects = TenantQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="uniq_category_name")]

    def __str__(self) -> str:
        return self.name


class Product(TimeStampedModel):
    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="products")
    sku = models.CharField("SKU", max_length=64)
    name = models.CharField(_("name"), max_length=255)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")
    my_price = models.DecimalField(_("my price"), max_digits=14, decimal_places=2, default=Decimal("0"))
    cost_price = models.DecimalField(_("cost price"), max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="UZS")
    is_active = models.BooleanField(default=True)

    objects = TenantQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "sku"], name="uniq_product_sku")]

    def __str__(self) -> str:
        return f"{self.sku} — {self.name}"

    def set_my_price(self, price: Decimal, user=None, source: str = "manual") -> None:
        price = Decimal(price)
        if price == self.my_price:
            return
        self.my_price = price
        self.save(update_fields=["my_price", "updated_at"])
        MyPriceChange.objects.create(product=self, price=price, changed_by=user, source=source)

    def market_min(self):
        """Lowest current in-stock competitor price (``None`` if unknown)."""
        prices = [
            o.last_price
            for o in self.offers.all()
            if o.is_active and o.last_price is not None and o.last_in_stock is not False
        ]
        return min(prices) if prices else None


class MyPriceChange(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="my_price_history")
    price = models.DecimalField(max_digits=14, decimal_places=2)
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    source = models.CharField(max_length=32, default="manual")

    class Meta:
        ordering = ["changed_at"]

    def __str__(self) -> str:
        return f"{self.product_id}: {self.price} @ {self.changed_at:%Y-%m-%d}"


class OfferQuerySet(TenantQuerySet):
    def due(self, now):
        return self.filter(is_active=True, robots_blocked=False, store__is_active=True).filter(
            models.Q(next_check_at__isnull=True) | models.Q(next_check_at__lte=now)
        )


class CompetitorOffer(TimeStampedModel):
    class Status(models.TextChoices):
        NEW = "new", _("New")
        OK = "ok", _("OK")
        FAILED = "failed", _("Failed")
        BLOCKED = "blocked", _("Blocked by robots.txt")
        SUSPICIOUS = "suspicious", _("Suspicious, re-checking")

    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="offers")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="offers")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="offers")
    url = models.URLField(max_length=1000)
    is_active = models.BooleanField(default=True)
    check_interval_minutes = models.PositiveIntegerField(_("check interval (min)"), default=360)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    last_error = models.CharField(max_length=500, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    robots_blocked = models.BooleanField(default=False)
    # Denormalized "current state" for fast dashboards
    last_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    last_old_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    last_in_stock = models.BooleanField(null=True)
    last_title = models.CharField(max_length=500, blank=True)
    last_snapshot = models.ForeignKey(
        "pricing.PriceSnapshot", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    pending_snapshot = models.ForeignKey(
        "pricing.PriceSnapshot",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Suspicious snapshot awaiting confirmation",
    )

    objects = OfferQuerySet.as_manager()

    class Meta:
        ordering = ["product", "store__name"]
        constraints = [models.UniqueConstraint(fields=["product", "url"], name="uniq_offer_url_per_product")]
        indexes = [models.Index(fields=["is_active", "next_check_at"])]

    def __str__(self) -> str:
        return f"{self.store} — {self.product.sku}"

    def save(self, *args, **kwargs):
        if self.product_id and not self.organization_id:
            self.organization_id = self.product.organization_id
        super().save(*args, **kwargs)
