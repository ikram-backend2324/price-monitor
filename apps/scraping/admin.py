from django.contrib import admin

from .models import ScraperHealthEvent, ScrapeRun


@admin.register(ScrapeRun)
class ScrapeRunAdmin(admin.ModelAdmin):
    list_display = ("offer", "store", "status", "http_status", "duration_ms", "started_at", "error")
    list_filter = ("status", "store")
    raw_id_fields = ("offer",)
    date_hierarchy = "started_at"


@admin.register(ScraperHealthEvent)
class ScraperHealthEventAdmin(admin.ModelAdmin):
    list_display = ("kind", "store", "offer", "success_rate", "created_at", "notified")
    list_filter = ("kind", "store")
    raw_id_fields = ("offer",)
