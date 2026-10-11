"""User of organization A must never see or modify data of organization B."""

import pytest
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.alerts.models import AlertRule
from apps.catalog.models import Product

from .factories import OfferFactory, ProductFactory, SnapshotFactory


@pytest.fixture
def b_data(other_org):
    product = ProductFactory(organization=other_org, sku="SECRET-B", name="Secret B product")
    offer = OfferFactory(product=product)
    SnapshotFactory(offer=offer)
    return product, offer


@pytest.mark.django_db
class TestWebIsolation:
    def test_product_list_excludes_other_org(self, client_a, org, b_data):
        ProductFactory(organization=org, name="Mine A")
        html = client_a.get("/products/").content.decode()
        assert "Mine A" in html
        assert "Secret B product" not in html

    def test_product_detail_404(self, client_a, b_data):
        product, offer = b_data
        assert client_a.get(f"/products/{product.pk}/").status_code == 404
        assert client_a.get(f"/products/{product.pk}/chart.json").status_code == 404
        assert client_a.get(f"/products/{product.pk}/edit/").status_code == 404

    def test_cannot_modify_other_org(self, client_a, b_data):
        product, offer = b_data
        assert client_a.post(f"/products/{product.pk}/delete/").status_code == 404
        assert client_a.post(f"/offers/{offer.pk}/delete/").status_code == 404
        assert client_a.post(f"/products/{product.pk}/apply-price/", {"price": "1"}).status_code == 404
        assert Product.objects.filter(pk=product.pk).exists()

    def test_rules_isolated(self, client_a, other_org):
        rule_b = AlertRule.objects.filter(organization=other_org).first()
        assert client_a.post(f"/alerts/{rule_b.pk}/delete/").status_code == 404

    def test_export_contains_only_own(self, client_a, org, b_data):
        ProductFactory(organization=org, sku="MINE-1")
        body = client_a.get("/export.csv").content.decode("utf-8-sig")
        assert "MINE-1" in body and "SECRET-B" not in body

    def test_switch_to_foreign_org_ignored(self, client_a, other_org, org):
        client_a.post(f"/org/{other_org.pk}/switch/")
        assert client_a.get("/").context["current_org"] == org


@pytest.mark.django_db
class TestApiIsolation:
    @pytest.fixture
    def api(self, owner, org):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=owner).key}")
        return c

    def test_lists_exclude_other_org(self, api, org, b_data):
        ProductFactory(organization=org, sku="MINE-API")
        skus = [p["sku"] for p in api.get("/api/v1/products/").json()["results"]]
        assert skus == ["MINE-API"]
        assert api.get("/api/v1/offers/").json()["count"] == 0
        assert api.get("/api/v1/snapshots/").json()["count"] == 0

    def test_detail_404(self, api, b_data):
        product, offer = b_data
        assert api.get(f"/api/v1/products/{product.pk}/").status_code == 404
        assert api.delete(f"/api/v1/offers/{offer.pk}/").status_code == 404

    def test_cannot_attach_offer_to_foreign_product(self, api, b_data):
        product, _ = b_data
        resp = api.post("/api/v1/offers/", {"product": product.pk, "url": "https://x.test/p/1"}, format="json")
        assert resp.status_code == 400
