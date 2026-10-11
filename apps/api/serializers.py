from rest_framework import serializers

from apps.alerts.models import AlertEvent
from apps.catalog.models import Category, CompetitorOffer, Product, Store
from apps.pricing.models import PriceSnapshot


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ["id", "name", "domain", "adapter", "requires_browser", "health_status"]


class OfferSerializer(serializers.ModelSerializer):
    store = StoreSerializer(read_only=True)
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.none())

    class Meta:
        model = CompetitorOffer
        fields = [
            "id",
            "product",
            "store",
            "url",
            "is_active",
            "check_interval_minutes",
            "last_price",
            "last_old_price",
            "last_in_stock",
            "last_title",
            "last_status",
            "last_checked_at",
            "next_check_at",
            "consecutive_failures",
        ]
        read_only_fields = [
            "store",
            "last_price",
            "last_old_price",
            "last_in_stock",
            "last_title",
            "last_status",
            "last_checked_at",
            "next_check_at",
            "consecutive_failures",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org = self.context.get("organization")
        if org is not None:
            self.fields["product"].queryset = Product.objects.for_org(org)


class ProductSerializer(serializers.ModelSerializer):
    category = serializers.SlugRelatedField(
        slug_field="name", queryset=Category.objects.none(), required=False, allow_null=True
    )
    market_min = serializers.SerializerMethodField()
    offers = OfferSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "category",
            "my_price",
            "cost_price",
            "currency",
            "is_active",
            "market_min",
            "offers",
        ]
        read_only_fields = ["currency"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org = self.context.get("organization")
        if org is not None:
            self.fields["category"].queryset = Category.objects.for_org(org)

    def get_market_min(self, obj) -> str | None:
        value = obj.market_min()
        return str(value) if value is not None else None

    def validate_sku(self, value):
        org = self.context["organization"]
        qs = Product.objects.for_org(org).filter(sku=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("SKU already exists")
        return value


class SnapshotSerializer(serializers.ModelSerializer):
    store = serializers.CharField(source="offer.store.name", read_only=True)

    class Meta:
        model = PriceSnapshot
        fields = [
            "id",
            "offer",
            "store",
            "price",
            "old_price",
            "in_stock",
            "title",
            "currency",
            "kind",
            "is_suspicious",
            "checked_at",
        ]


class AlertEventSerializer(serializers.ModelSerializer):
    kind = serializers.CharField(source="rule.kind", read_only=True)

    class Meta:
        model = AlertEvent
        fields = ["id", "kind", "offer", "snapshot", "payload", "created_at", "sent", "channel"]


class RecommendationSerializer(serializers.Serializer):
    price = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    rule_name = serializers.CharField()
    strategy = serializers.CharField()
    market_min = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    market_avg = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    competitors = serializers.IntegerField()
    floor = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    steps = serializers.ListField(child=serializers.CharField())
