"""Morning digest: what changed in 24h, where I'm more expensive, what competitors ran out of."""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone, translation
from django.utils.html import escape
from django.utils.translation import gettext as _

from apps.accounts.models import Organization
from apps.alerts import telegram
from apps.alerts.services import recipients
from apps.catalog.models import CompetitorOffer, Product
from apps.pricing.models import PriceSnapshot
from apps.pricing.services import fmt

from .models import DigestLog


@dataclass
class DigestData:
    changes: list[dict] = field(default_factory=list)
    more_expensive: list[dict] = field(default_factory=list)
    out_of_stock: list[dict] = field(default_factory=list)
    tracked_products: int = 0


def collect(org: Organization, now: datetime | None = None) -> DigestData:
    now = now or timezone.now()
    since = now - timedelta(hours=24)
    data = DigestData()
    snaps = (
        PriceSnapshot.objects.for_org(org)
        .accepted()
        .filter(checked_at__gte=since, kind=PriceSnapshot.Kind.CHANGE)
        .select_related("offer__product", "offer__store")
        .order_by("-checked_at")
    )
    for snap in snaps:
        prev = (
            PriceSnapshot.objects.accepted()
            .filter(offer_id=snap.offer_id, checked_at__lt=snap.checked_at)
            .order_by("-checked_at")
            .first()
        )
        if prev is None or prev.price == snap.price:
            continue
        data.changes.append(
            {
                "product": snap.offer.product.name,
                "store": snap.offer.store.name,
                "old": prev.price,
                "new": snap.price,
            }
        )
    products = Product.objects.for_org(org).filter(is_active=True).prefetch_related("offers")
    data.tracked_products = len(products)
    for product in products:
        market = product.market_min()
        if market is not None and product.my_price and product.my_price > market:
            data.more_expensive.append(
                {"product": product.name, "mine": product.my_price, "market": market, "diff": product.my_price - market}
            )
    data.more_expensive.sort(key=lambda r: r["diff"], reverse=True)
    for offer in (
        CompetitorOffer.objects.for_org(org)
        .filter(is_active=True, last_in_stock=False)
        .select_related("product", "store")
    ):
        data.out_of_stock.append({"product": offer.product.name, "store": offer.store.name})
    return data


def render_text(org: Organization, data: DigestData, lang: str, limit: int = 10) -> str:
    with translation.override(lang):
        lines = [
            "☀️ <b>" + _("Morning digest — %(org)s") % {"org": escape(org.name)} + "</b>",
            _("Tracked products: %(n)d") % {"n": data.tracked_products},
            "",
            "<b>" + _("Price changes in 24h: %(n)d") % {"n": len(data.changes)} + "</b>",
        ]
        for c in data.changes[:limit]:
            arrow = "📉" if c["new"] < c["old"] else "📈"
            lines.append(f"{arrow} {escape(c['product'])} — {escape(c['store'])}: {fmt(c['old'])} → {fmt(c['new'])}")
        if len(data.changes) > limit:
            lines.append(_("…and %(n)d more") % {"n": len(data.changes) - limit})
        lines += ["", "<b>" + _("Where I'm more expensive: %(n)d") % {"n": len(data.more_expensive)} + "</b>"]
        for r in data.more_expensive[:limit]:
            lines.append(f"💸 {escape(r['product'])}: {fmt(r['mine'])} vs {fmt(r['market'])} (+{fmt(r['diff'])})")
        lines += ["", "<b>" + _("Out of stock at competitors: %(n)d") % {"n": len(data.out_of_stock)} + "</b>"]
        for r in data.out_of_stock[:limit]:
            lines.append(f"🚫 {escape(r['product'])} — {escape(r['store'])}")
    return "\n".join(lines)


def send_digest(org: Organization, force: bool = False, now: datetime | None = None) -> int:
    now = now or timezone.now()
    local_date = now.astimezone(zoneinfo.ZoneInfo(org.timezone)).date()
    if not force:
        try:
            with transaction.atomic():
                log = DigestLog.objects.create(organization=org, date=local_date)
        except IntegrityError:
            return 0
    data = collect(org, now)
    sent = 0
    for link in recipients(org):
        if telegram.send_message(link.chat_id, render_text(org, data, link.language)):
            sent += 1
    if not force:
        log.recipients = sent
        log.save(update_fields=["recipients"])
    return sent


def due_organizations(now: datetime | None = None) -> list[Organization]:
    now = now or timezone.now()
    due = []
    for org in Organization.objects.filter(digest_enabled=True):
        local = now.astimezone(zoneinfo.ZoneInfo(org.timezone))
        if (
            local.time() >= org.digest_time
            and not DigestLog.objects.filter(organization=org, date=local.date()).exists()
        ):
            due.append(org)
    return due
