from django.contrib import admin

from .models import DigestLog


@admin.register(DigestLog)
class DigestLogAdmin(admin.ModelAdmin):
    list_display = ("organization", "date", "sent_at", "recipients")
