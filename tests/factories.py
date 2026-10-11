from decimal import Decimal

import factory
from django.utils import timezone

from apps.accounts.models import Membership, Organization, Role, User
from apps.catalog.models import Category, CompetitorOffer, Product, Store
from apps.pricing.models import PriceSnapshot


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    password = factory.PostGenerationMethodCall("set_password", "pass12345!")

    @factory.post_generation
    def _save(obj, create, extracted, **kwargs):
        if create:
            obj.save()


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization

    name = factory.Sequence(lambda n: f"Org {n}")


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Membership

    user = factory.SubFactory(UserFactory)
    organization = factory.SubFactory(OrganizationFactory)
    role = Role.OWNER


class StoreFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Store
        django_get_or_create = ("domain",)

    name = factory.Sequence(lambda n: f"Shop {n}")
    domain = factory.Sequence(lambda n: f"shop{n}.test")
    adapter = Store.Adapter.JSONLD
    rate_limit_per_minute = 600


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Category {n}")


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    organization = factory.SubFactory(OrganizationFactory)
    sku = factory.Sequence(lambda n: f"SKU-{n}")
    name = factory.Sequence(lambda n: f"Product {n}")
    my_price = Decimal("100000")
    cost_price = Decimal("70000")


class OfferFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CompetitorOffer

    product = factory.SubFactory(ProductFactory)
    organization = factory.SelfAttribute("product.organization")
    store = factory.SubFactory(StoreFactory)
    url = factory.Sequence(lambda n: f"https://shop.test/product/{n}")
    check_interval_minutes = 60


class SnapshotFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PriceSnapshot

    offer = factory.SubFactory(OfferFactory)
    price = Decimal("100000")
    in_stock = True
    checked_at = factory.LazyFunction(timezone.now)
    kind = PriceSnapshot.Kind.CHANGE
