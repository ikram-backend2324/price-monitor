from django.db.models import Prefetch
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.accounts.models import Membership
from apps.alerts.models import AlertEvent
from apps.billing import services as billing
from apps.catalog.models import CompetitorOffer, Product, Store
from apps.pricing.models import PriceSnapshot
from apps.pricing.services import recommend_price
from apps.reports.importing import _store_for

from .serializers import (
    AlertEventSerializer,
    OfferSerializer,
    ProductSerializer,
    RecommendationSerializer,
    SnapshotSerializer,
    StoreSerializer,
)


def resolve_membership(request) -> Membership | None:
    qs = Membership.objects.select_related("organization").filter(user=request.user)
    slug = request.headers.get("X-Organization")
    if slug:
        return qs.filter(organization__slug=slug).first()
    return qs.order_by("created_at").first()


class HasOrganizationWithApi(permissions.BasePermission):
    message = "API access requires the Business plan or higher."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        membership = resolve_membership(request)
        if membership is None:
            return False
        request.org_membership = membership
        return billing.get_limits(membership.organization).api_access

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.org_membership.can_edit


class TenantViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated, HasOrganizationWithApi]

    @property
    def organization(self):
        return self.request.org_membership.organization

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if hasattr(self.request, "org_membership"):
            ctx["organization"] = self.organization
        return ctx

    def require_editor(self):
        if not self.request.org_membership.can_edit:
            raise PermissionDenied("Viewer role is read-only")


class ProductViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    TenantViewSet,
):
    """Your products with current competitor prices."""

    serializer_class = ProductSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Product.objects.none()
        return (
            Product.objects.for_org(self.organization)
            .select_related("category")
            .prefetch_related(Prefetch("offers", queryset=CompetitorOffer.objects.select_related("store")))
            .order_by("sku")
        )

    def perform_create(self, serializer):
        self.require_editor()
        serializer.save(organization=self.organization)

    def perform_update(self, serializer):
        self.require_editor()
        old = serializer.instance.my_price
        product = serializer.save()
        if product.my_price != old:
            product.my_price_history.create(price=product.my_price, changed_by=self.request.user, source="api")

    def perform_destroy(self, instance):
        self.require_editor()
        instance.delete()

    @extend_schema(responses=RecommendationSerializer)
    @action(detail=True, methods=["get"])
    def recommendation(self, request, pk=None):
        rec = recommend_price(self.get_object())
        return Response(RecommendationSerializer(rec).data)

    @extend_schema(
        parameters=[OpenApiParameter("days", int, description="History depth in days (default 30)")],
        responses=SnapshotSerializer(many=True),
    )
    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        from datetime import timedelta

        from django.utils import timezone

        product = self.get_object()
        days = int(request.query_params.get("days", 30))
        snaps = (
            PriceSnapshot.objects.accepted()
            .filter(offer__product=product, checked_at__gte=timezone.now() - timedelta(days=days))
            .select_related("offer__store")
            .order_by("checked_at")
        )
        return Response(SnapshotSerializer(snaps, many=True).data)

    @extend_schema(request=None, responses={202: dict})
    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        from apps.scraping.tasks import check_product_now

        self.require_editor()
        queued = check_product_now(self.get_object())
        return Response({"queued": queued}, status=status.HTTP_202_ACCEPTED)


class OfferViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    TenantViewSet,
):
    """Competitor links. The store is detected from the URL domain."""

    serializer_class = OfferSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CompetitorOffer.objects.none()
        qs = CompetitorOffer.objects.for_org(self.organization).select_related("store").order_by("id")
        product = self.request.query_params.get("product")
        return qs.filter(product_id=product) if product else qs

    def perform_create(self, serializer):
        self.require_editor()
        try:
            billing.check_offer_limit(self.organization)
        except billing.LimitExceeded as exc:
            raise ValidationError(str(exc)) from exc
        url = serializer.validated_data["url"]
        minimum = billing.get_limits(self.organization).min_check_interval_minutes
        interval = max(serializer.validated_data.get("check_interval_minutes", 360), minimum)
        serializer.save(organization=self.organization, store=_store_for(url), check_interval_minutes=interval)

    def perform_update(self, serializer):
        self.require_editor()
        serializer.save()

    def perform_destroy(self, instance):
        self.require_editor()
        instance.delete()


class SnapshotViewSet(mixins.ListModelMixin, TenantViewSet):
    serializer_class = SnapshotSerializer

    @extend_schema(parameters=[OpenApiParameter("offer", int), OpenApiParameter("product", int)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PriceSnapshot.objects.none()
        qs = PriceSnapshot.objects.for_org(self.organization).select_related("offer__store").order_by("-checked_at")
        if offer := self.request.query_params.get("offer"):
            qs = qs.filter(offer_id=offer)
        if product := self.request.query_params.get("product"):
            qs = qs.filter(offer__product_id=product)
        return qs


class AlertEventViewSet(mixins.ListModelMixin, TenantViewSet):
    serializer_class = AlertEventSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AlertEvent.objects.none()
        return AlertEvent.objects.for_org(self.organization).select_related("rule")


class StoreViewSet(mixins.ListModelMixin, TenantViewSet):
    serializer_class = StoreSerializer

    def get_queryset(self):
        return Store.objects.filter(is_active=True)


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class TokenView(ObtainAuthToken):
    """Exchange email + password for an API token (`username` field = email)."""

    throttle_classes = [LoginThrottle]
