from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantQuerySet, TimeStampedModel


class SnapshotQuerySet(TenantQuerySet):
    org_lookup = "offer__organization"

    def accepted(self):
        return self.filter(is_suspicious=False)


class PriceSnapshot(models.Model):
    """A stored observation of a competitor offer.

    Written only when something changed, plus one daily control snapshot,
    so history stays compact (light-weight checks live in ``ScrapeRun``).
    """

    class Kind(models.TextChoices):
        INITIAL = "initial", _("Initial")
        CHANGE = "change", _("Change")
        DAILY = "daily", _("Daily control")

    offer = models.ForeignKey("catalog.CompetitorOffer", on_delete=models.CASCADE, related_name="snapshots")
    price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    old_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    in_stock = models.BooleanField(default=True)
    title = models.CharField(max_length=500, blank=True)
    currency = models.CharField(max_length=3, default="UZS")
    raw_payload = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField(db_index=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.CHANGE)
    is_suspicious = models.BooleanField(default=False)
    rejected = models.BooleanField(default=False, help_text="Suspicious value not confirmed by re-check")

    objects = SnapshotQuerySet.as_manager()

    class Meta:
        ordering = ["-checked_at"]
        indexes = [models.Index(fields=["offer", "checked_at"], name="snapshot_offer_time_idx")]

    def __str__(self) -> str:
        return f"{self.offer_id} {self.price} @ {self.checked_at:%Y-%m-%d %H:%M}"

    @property
    def discount_percent(self) -> Decimal | None:
        if self.price and self.old_price and self.old_price > self.price:
            return ((self.old_price - self.price) / self.old_price * 100).quantize(Decimal("0.1"))
        return None


class PricingRule(TimeStampedModel):
    class Strategy(models.TextChoices):
        UNDERCUT_MIN_BY_AMOUNT = "undercut_amount", _("Undercut the cheapest competitor by an amount")
        UNDERCUT_MIN_BY_PERCENT = "undercut_percent", _("Undercut the cheapest competitor by a percent")
        MATCH_MIN = "match_min", _("Match the cheapest competitor")
        AVERAGE = "average", _("Market average")

    class Scope(models.TextChoices):
        ALL = "all", _("All products")
        CATEGORY = "category", _("Category")
        PRODUCT = "product", _("Product")

    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="pricing_rules")
    name = models.CharField(_("name"), max_length=120)
    strategy = models.CharField(_("strategy"), max_length=32, choices=Strategy.choices)
    amount = models.DecimalField(_("amount (UZS)"), max_digits=14, decimal_places=2, default=Decimal("0"))
    percent = models.DecimalField(_("percent"), max_digits=5, decimal_places=2, default=Decimal("0"))
    min_margin_percent = models.DecimalField(_("min margin %"), max_digits=5, decimal_places=2, default=Decimal("5"))
    round_to = models.PositiveIntegerField(_("round to (UZS)"), default=1000)
    scope = models.CharField(_("scope"), max_length=16, choices=Scope.choices, default=Scope.ALL)
    category = models.ForeignKey("catalog.Category", null=True, blank=True, on_delete=models.CASCADE)
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.CASCADE)
    is_active = models.BooleanField(_("active"), default=True)
    priority = models.PositiveSmallIntegerField(default=0, help_text="Higher wins within the same scope")

    objects = TenantQuerySet.as_manager()

    class Meta:
        ordering = ["-priority", "name"]

    def __str__(self) -> str:
        return self.name
