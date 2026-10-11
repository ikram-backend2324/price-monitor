from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.core.views import health

urlpatterns = [
    path("health/", health, name="health"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("api/", include("apps.api.urls")),
    path(settings.ADMIN_URL, admin.site.urls),
    # Language is chosen by cookie / user profile, not by URL prefix.
    path("", include("apps.accounts.urls")),
    path("", include("apps.dashboard.urls")),
]

admin.site.site_header = "PriceWatch admin"
admin.site.site_title = "PriceWatch"
