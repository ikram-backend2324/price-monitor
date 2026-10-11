from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantQuerySet, TimeStampedModel


class Plan(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=64)
    price_uzs = models.PositiveBigIntegerField(default=0, help_text="Monthly price in UZS")
    max_offers = models.PositiveIntegerField(help_text="Max tracked competitor links")
    min_check_interval_minutes = models.PositiveIntegerField(help_text="Fastest allowed check interval")
    max_members = models.PositiveIntegerField(default=1)
    telegram_alerts = models.BooleanField(default=True)
    excel_reports = models.BooleanField(default=False)
    api_access = models.BooleanField(default=False)
    trial_days = models.PositiveIntegerField(default=0)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_public = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self) -> str:
        return self.name


class Subscription(TimeStampedModel):
    class Status(models.TextChoices):
        TRIAL = "trial", _("Trial")
        ACTIVE = "active", _("Active")
        EXPIRED = "expired", _("Expired")
        CANCELLED = "cancelled", _("Cancelled")

    organization = models.OneToOneField("accounts.Organization", on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TRIAL)
    started_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return f"{self.organization} — {self.plan} ({self.status})"

    @property
    def is_usable(self) -> bool:
        if self.status not in (self.Status.TRIAL, self.Status.ACTIVE):
            return False
        return self.expires_at is None or self.expires_at > timezone.now()

    @property
    def days_left(self) -> int | None:
        if self.expires_at is None:
            return None
        return max(0, (self.expires_at - timezone.now()).days)


class PaymentTransaction(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PAID = "paid", _("Paid")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="payments")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    months = models.PositiveSmallIntegerField(default=1)
    amount_uzs = models.PositiveBigIntegerField()
    provider = models.CharField(max_length=32, default="manual")
    external_id = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    payload = models.JSONField(default=dict, blank=True)

    objects = TenantQuerySet.as_manager()

    def __str__(self) -> str:
        return f"{self.organization} {self.plan} {self.amount_uzs} UZS ({self.status})"
