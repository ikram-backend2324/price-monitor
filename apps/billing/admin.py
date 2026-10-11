from django.contrib import admin, messages

from . import services
from .models import PaymentTransaction, Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "price_uzs",
        "max_offers",
        "min_check_interval_minutes",
        "max_members",
        "excel_reports",
        "api_access",
    )


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("organization", "plan", "status", "expires_at")
    list_filter = ("status", "plan")
    search_fields = ("organization__name",)
    actions = ["extend_30_days"]

    @admin.action(description="Activate / extend current plan for 30 days")
    def extend_30_days(self, request, queryset):
        for sub in queryset:
            services.activate_plan(sub.organization, sub.plan.code, months=1, by=request.user)
        self.message_user(request, f"Extended {queryset.count()} subscription(s)", messages.SUCCESS)


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "organization", "plan", "months", "amount_uzs", "provider", "status", "created_at")
    list_filter = ("status", "provider")
    actions = ["mark_paid"]

    @admin.action(description="Mark as paid and activate plan")
    def mark_paid(self, request, queryset):
        for tx in queryset.filter(status=PaymentTransaction.Status.PENDING):
            tx.status = PaymentTransaction.Status.PAID
            tx.save(update_fields=["status", "updated_at"])
            services.activate_plan(tx.organization, tx.plan.code, months=tx.months, by=request.user)
        self.message_user(request, "Payments confirmed", messages.SUCCESS)
