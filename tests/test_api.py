from decimal import Decimal

import pytest
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.billing.services import start_trial
from apps.catalog.models import CompetitorOffer

from .factories import OfferFactory, ProductFactory, SnapshotFactory


@pytest.fixture
def api(owner, org):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=owner).key}")
    return c


@pytest.mark.django_db
class TestApi:
    def test_requires_auth(self, client, db):
        assert client.get("/api/v1/products/").status_code == 401

    def test_token_endpoint(self, client, owner):
        resp = client.post("/api/v1/auth/token/", {"username": "owner@a.test", "password": "pass12345!"})
        assert resp.status_code == 200 and resp.json()["token"]

    def test_plan_gating(self, api, org):
        start_trial(org)
        assert api.get("/api/v1/products/").status_code == 403

    def test_product_crud(self, api, org):
        resp = api.post(
            "/api/v1/products/", {"sku": "API-1", "name": "Api product", "my_price": "1000.00"}, format="json"
        )
        assert resp.status_code == 201, resp.content
        pid = resp.json()["id"]
        resp = api.patch(f"/api/v1/products/{pid}/", {"my_price": "900.00"}, format="json")
        assert resp.json()["my_price"] == "900.00"
        assert (
            api.post("/api/v1/products/", {"sku": "API-1", "name": "dup", "my_price": "1"}, format="json").status_code
            == 400
        )
        assert api.delete(f"/api/v1/products/{pid}/").status_code == 204

    def test_offer_create_detects_store_and_enforces_interval(self, api, org, queued):
        product = ProductFactory(organization=org)
        resp = api.post(
            "/api/v1/offers/",
            {"product": product.pk, "url": "https://uzum.uz/ru/product/x-55", "check_interval_minutes": 1},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        offer = CompetitorOffer.objects.get(pk=resp.json()["id"])
        assert offer.store.domain == "uzum.uz"
        assert offer.check_interval_minutes == 30  # business plan floor
        assert api.get(f"/api/v1/offers/?product={product.pk}").json()["count"] == 1

    def test_recommendation_history_and_check(self, api, org, queued):
        product = ProductFactory(organization=org, cost_price=None)
        offer = OfferFactory(product=product, last_price=Decimal(50000), last_in_stock=True)
        SnapshotFactory(offer=offer, price=Decimal(50000))
        rec = api.get(f"/api/v1/products/{product.pk}/recommendation/").json()
        assert rec["price"] == "49000.00" and rec["steps"]
        assert len(api.get(f"/api/v1/products/{product.pk}/history/?days=7").json()) == 1
        assert api.post(f"/api/v1/products/{product.pk}/check/").json() == {"queued": 1}
        assert api.get(f"/api/v1/snapshots/?product={product.pk}").json()["count"] == 1
        assert api.get(f"/api/v1/snapshots/?offer={offer.pk}").json()["count"] == 1

    def test_read_only_lists(self, api):
        assert api.get("/api/v1/alerts/").status_code == 200
        assert api.get("/api/v1/stores/").status_code == 200

    def test_viewer_cannot_write(self, viewer, org):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=viewer).key}")
        assert c.get("/api/v1/products/").status_code == 200
        assert c.post("/api/v1/products/", {"sku": "V", "name": "v", "my_price": "1"}, format="json").status_code == 403

    def test_organization_header(self, api, org, other_org):
        assert api.get("/api/v1/products/", HTTP_X_ORGANIZATION=other_org.slug).status_code == 403
        assert api.get("/api/v1/products/", HTTP_X_ORGANIZATION=org.slug).status_code == 200

    def test_schema_and_docs(self, client, db):
        assert client.get("/api/schema/").status_code == 200
        assert client.get("/api/docs/").status_code == 200
