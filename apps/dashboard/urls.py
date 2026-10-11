from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("feed/", views.feed, name="feed"),
    path("products/", views.product_list, name="products"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("products/<int:pk>/chart.json", views.chart_data, name="chart_data"),
    path("products/<int:pk>/check/", views.check_now, name="check_now"),
    path("products/<int:pk>/apply-price/", views.apply_price, name="apply_price"),
    path("products/<int:pk>/offers/new/", views.offer_create, name="offer_create"),
    path("offers/<int:pk>/toggle/", views.offer_toggle, name="offer_toggle"),
    path("offers/<int:pk>/delete/", views.offer_delete, name="offer_delete"),
    path("import/", views.import_view, name="import"),
    path("import/template.<str:fmt>", views.import_template, name="import_template"),
    path("export.<str:fmt>", views.export, name="export"),
    path("alerts/", views.alert_rules, name="alerts"),
    path("alerts/<int:pk>/toggle/", views.alert_rule_toggle, name="alert_toggle"),
    path("alerts/<int:pk>/delete/", views.alert_rule_delete, name="alert_delete"),
    path("pricing/", views.pricing_rules, name="pricing"),
    path("pricing/<int:pk>/delete/", views.pricing_rule_delete, name="pricing_delete"),
    path("billing/", views.billing_view, name="billing"),
    path("billing/request/", views.billing_request, name="billing_request"),
    path("scrapers/", views.scraper_health, name="health"),
    path("telegram/", views.telegram_view, name="telegram"),
    path("team/", views.team, name="team"),
    path("team/<int:pk>/remove/", views.member_remove, name="member_remove"),
    path("settings/", views.org_settings, name="settings"),
]
