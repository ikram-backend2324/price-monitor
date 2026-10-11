from django.contrib import admin

from .models import PriceSnapshot, PricingRule


@admin.register(PriceSnapshot)
class PriceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("offer", "price", "old_price", "in_stock", "kind", "is_suspicious", "checked_at")
    list_filter = ("kind", "is_suspicious", "in_stock")
    raw_id_fields = ("offer",)
    date_hierarchy = "checked_at"


@admin.register(PricingRule)
class PricingRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "strategy", "scope", "min_margin_percent", "is_active")
    list_filter = ("strategy", "scope", "is_active")
