from django import forms
from django.contrib import admin
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import Category, CompetitorOffer, MyPriceChange, Product, Store


class SelectorTestForm(forms.Form):
    url = forms.URLField(label="Product URL", widget=forms.URLInput(attrs={"size": 100}))
    ignore_robots = forms.BooleanField(required=False, initial=False, label="Ignore robots.txt (debug only)")


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "domain",
        "adapter",
        "requires_browser",
        "rate_limit_per_minute",
        "health_status",
        "is_active",
        "test_link",
    )
    list_filter = ("adapter", "health_status", "is_active", "requires_browser")
    search_fields = ("name", "domain")
    fieldsets = (
        (None, {"fields": ("name", "domain", "adapter", "is_active", "currency", "notes")}),
        ("Politeness", {"fields": ("rate_limit_per_minute", "requires_browser", "wait_selector")}),
        (
            "CSS selectors (SelectorAdapter)",
            {
                "fields": (
                    "price_selector",
                    "old_price_selector",
                    "title_selector",
                    "in_stock_selector",
                    "out_of_stock_selector",
                    "out_of_stock_text",
                    "price_regex",
                ),
                "description": "Configure these when Adapter = 'CSS selectors'. Then use “Test selectors on URL”.",
            },
        ),
        ("Health", {"fields": ("health_status",)}),
    )

    def get_urls(self):
        return [
            path("<int:pk>/test/", self.admin_site.admin_view(self.test_view), name="catalog_store_test"),
        ] + super().get_urls()

    @admin.display(description="Test")
    def test_link(self, obj):
        return format_html(
            '<a class="button" href="{}">Test selectors on URL</a>', reverse("admin:catalog_store_test", args=[obj.pk])
        )

    def test_view(self, request, pk):
        from apps.scraping.adapters import ScrapeError, get_adapter
        from apps.scraping.http import Fetcher

        store = get_object_or_404(Store, pk=pk)
        sample = store.offers.values_list("url", flat=True).first()
        form = SelectorTestForm(request.POST or None, initial={"url": sample})
        result = error = None
        if request.method == "POST" and form.is_valid():
            fetcher = Fetcher(max_retries=1, respect_robots=not form.cleaned_data["ignore_robots"])
            try:
                result = get_adapter(store, fetcher).fetch(form.cleaned_data["url"])
            except ScrapeError as exc:
                error = str(exc)
            except Exception as exc:  # show anything to the admin rather than a 500
                error = f"{exc.__class__.__name__}: {exc}"
        context = {
            **self.admin_site.each_context(request),
            "title": f"Test extraction — {store.name}",
            "store": store,
            "form": form,
            "result": result,
            "error": error,
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/catalog/store_test.html", context)


class OfferInline(admin.TabularInline):
    model = CompetitorOffer
    extra = 0
    fields = ("store", "url", "is_active", "check_interval_minutes", "last_price", "last_in_stock", "last_status")
    readonly_fields = ("last_price", "last_in_stock", "last_status")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "organization", "category", "my_price", "cost_price", "is_active")
    list_filter = ("organization", "is_active")
    search_fields = ("sku", "name")
    inlines = [OfferInline]


@admin.register(CompetitorOffer)
class CompetitorOfferAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "store",
        "last_price",
        "last_in_stock",
        "last_status",
        "consecutive_failures",
        "last_checked_at",
        "next_check_at",
    )
    list_filter = ("store", "last_status", "is_active", "robots_blocked")
    search_fields = ("url", "product__sku", "product__name")
    raw_id_fields = ("product", "last_snapshot", "pending_snapshot")
    actions = ["check_now"]

    @admin.action(description="Check now")
    def check_now(self, request, queryset):
        from apps.scraping.tasks import enqueue_offer

        n = sum(1 for offer in queryset.select_related("store") if enqueue_offer(offer))
        self.message_user(request, f"Queued {n} checks")


admin.site.register(Category)
admin.site.register(MyPriceChange)
