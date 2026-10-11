from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("products", views.ProductViewSet, basename="product")
router.register("offers", views.OfferViewSet, basename="offer")
router.register("snapshots", views.SnapshotViewSet, basename="snapshot")
router.register("alerts", views.AlertEventViewSet, basename="alert")
router.register("stores", views.StoreViewSet, basename="store")

urlpatterns = [
    path("v1/", include(router.urls)),
    path("v1/auth/token/", views.TokenView.as_view(), name="api-token"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
