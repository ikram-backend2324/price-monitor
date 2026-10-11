from django.contrib import admin

from .models import AlertEvent, AlertRule, TelegramLink


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ("__str__", "organization", "kind", "threshold", "scope", "is_active")
    list_filter = ("kind", "scope", "is_active")


@admin.register(AlertEvent)
class AlertEventAdmin(admin.ModelAdmin):
    list_display = ("rule", "offer", "organization", "created_at", "sent", "channel")
    list_filter = ("sent", "channel", "rule__kind")
    raw_id_fields = ("offer", "snapshot", "rule")


@admin.register(TelegramLink)
class TelegramLinkAdmin(admin.ModelAdmin):
    list_display = ("user", "chat_id", "username", "language", "is_active")
    search_fields = ("user__email", "username")
