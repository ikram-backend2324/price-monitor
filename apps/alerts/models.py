from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantQuerySet, TimeStampedModel


class AlertRule(TimeStampedModel):
    class Kind(models.TextChoices):
        PRICE_DROP_PERCENT = "PRICE_DROP_PERCENT", _("Competitor dropped price by ≥ X%")
        CHEAPER_THAN_MINE = "CHEAPER_THAN_MINE", _("Competitor became cheaper than me")
        OUT_OF_STOCK = "OUT_OF_STOCK", _("Competitor ran out of stock")
        BACK_IN_STOCK = "BACK_IN_STOCK", _("Competitor is back in stock")
        PRICE_CHANGED = "PRICE_CHANGED", _("Any price change")

    class Scope(models.TextChoices):
        ALL = "all", _("All products")
        CATEGORY = "category", _("Category")
        PRODUCT = "product", _("Product")

    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="alert_rules")
    name = models.CharField(_("name"), max_length=120, blank=True)
    kind = models.CharField(_("type"), max_length=32, choices=Kind.choices)
    threshold = models.DecimalField(
        _("threshold"), max_digits=7, decimal_places=2, default=0, help_text=_("Percent for price drop rules")
    )
    scope = models.CharField(_("scope"), max_length=16, choices=Scope.choices, default=Scope.ALL)
    category = models.ForeignKey("catalog.Category", null=True, blank=True, on_delete=models.CASCADE)
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.CASCADE)
    notify_telegram = models.BooleanField(_("Telegram"), default=True)
    notify_email = models.BooleanField(_("Email"), default=False)
    is_active = models.BooleanField(_("active"), default=True)

    objects = TenantQuerySet.as_manager()

    class Meta:
        ordering = ["kind"]

    def __str__(self) -> str:
        return self.name or self.get_kind_display()

    def applies_to(self, product) -> bool:
        if self.scope == self.Scope.PRODUCT:
            return self.product_id == product.id
        if self.scope == self.Scope.CATEGORY:
            return bool(product.category_id) and self.category_id == product.category_id
        return True


class AlertEvent(models.Model):
    class Channel(models.TextChoices):
        TELEGRAM = "telegram", "Telegram"
        EMAIL = "email", "Email"
        LOG = "log", _("Log only (no channel configured)")

    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="alert_events")
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name="events")
    offer = models.ForeignKey("catalog.CompetitorOffer", on_delete=models.CASCADE, related_name="alert_events")
    snapshot = models.ForeignKey("pricing.PriceSnapshot", on_delete=models.CASCADE, related_name="alert_events")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent = models.BooleanField(default=False, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    channel = models.CharField(max_length=16, choices=Channel.choices, blank=True)
    delivery_error = models.CharField(max_length=300, blank=True)

    objects = TenantQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["rule", "snapshot"], name="uniq_event_per_rule_snapshot")]

    def __str__(self) -> str:
        return f"{self.rule.kind} {self.offer}"


def _link_code() -> str:
    return secrets.token_hex(3).upper()


def _code_expiry():
    return timezone.now() + timedelta(minutes=15)


class TelegramLink(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram")
    chat_id = models.BigIntegerField(null=True, blank=True, unique=True)
    username = models.CharField(max_length=64, blank=True)
    code = models.CharField(max_length=12, default=_link_code, db_index=True)
    code_expires_at = models.DateTimeField(default=_code_expiry)
    language = models.CharField(max_length=5, choices=settings.LANGUAGES, default="ru")
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"{self.user} ↔ {self.chat_id or 'not linked'}"

    @property
    def is_linked(self) -> bool:
        return self.chat_id is not None

    def regenerate_code(self) -> str:
        self.code = _link_code()
        self.code_expires_at = _code_expiry()
        self.save(update_fields=["code", "code_expires_at", "updated_at"])
        return self.code
