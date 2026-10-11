from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from django.core.cache import cache

from apps.accounts.models import Role
from apps.accounts.services import create_organization
from apps.billing.services import activate_plan
from apps.scraping import ratelimit

from .factories import MembershipFactory, UserFactory

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _settings(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.SCRAPER = {
        **settings.SCRAPER,
        "MIN_DELAY": 0,
        "MAX_DELAY": 0,
        "BACKOFF_BASE": 0.01,
        "RATE_LIMIT_BACKEND": "memory",
        "PROXY_URLS": [],
    }
    settings.TELEGRAM_BOT_TOKEN = ""
    settings.ADMIN_TELEGRAM_CHAT_ID = ""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    settings.LANGUAGE_CODE = "en"
    cache.clear()
    ratelimit.get_bucket.cache_clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def queued(monkeypatch):
    """Never run real scrapes from views/tasks during tests; record what was queued."""
    from apps.scraping import tasks

    calls = mock.Mock()
    monkeypatch.setattr(tasks.scrape_offer_fast, "apply_async", calls)
    monkeypatch.setattr(tasks.scrape_offer_browser, "apply_async", calls)
    return calls


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def owner(db):
    return UserFactory(email="owner@a.test", language="en")


@pytest.fixture
def org(owner):
    organization = create_organization(owner, "Org A")
    activate_plan(organization, "business")
    return organization


@pytest.fixture
def client_a(client, owner, org):
    client.force_login(owner)
    return client


@pytest.fixture
def other_org(db):
    user = UserFactory(email="owner@b.test", language="en")
    organization = create_organization(user, "Org B")
    activate_plan(organization, "business")
    return organization


@pytest.fixture
def viewer(org):
    return MembershipFactory(organization=org, role=Role.VIEWER, user__email="viewer@a.test").user
