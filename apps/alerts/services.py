"""Alert evaluation and grouped delivery."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone, translation
from django.utils.html import escape
from django.utils.translation import gettext as _

from apps.pricing.models import PriceSnapshot
from apps.pricing.services import fmt, recommend_price

from . import telegram
from .models import AlertEvent, AlertRule, TelegramLink

log = logging.getLogger(__name__)
K = AlertRule.Kind


def create_default_alert_rules(org) -> None:
    defaults = [
        (K.PRICE_DROP_PERCENT, Decimal("5")),
        (K.CHEAPER_THAN_MINE, Decimal("0")),
        (K.OUT_OF_STOCK, Decimal("0")),
        (K.BACK_IN_STOCK, Decimal("0")),
    ]
    for kind, threshold in defaults:
        AlertRule.objects.get_or_create(
            organization=org, kind=kind, scope=AlertRule.Scope.ALL, defaults={"threshold": threshold}
        )


def _matches(rule: AlertRule, snap: PriceSnapshot, prev: PriceSnapshot | None, my_price: Decimal) -> dict | None:
    """Return event payload if ``rule`` fires for the transition prev → snap."""
    new, old = snap.price, prev.price if prev else None
    if rule.kind == K.PRICE_DROP_PERCENT:
        if new is not None and old and new < old and snap.in_stock:
            pct = (old - new) / old * 100
            if pct >= rule.threshold:
                return {"old": str(old), "new": str(new), "pct": f"{pct:.1f}"}
    elif rule.kind == K.PRICE_CHANGED:
        if new is not None and old is not None and new != old:
            return {"old": str(old), "new": str(new)}
    elif rule.kind == K.CHEAPER_THAN_MINE:
        if new is not None and my_price and snap.in_stock and new < my_price:
            was_cheaper = prev is not None and prev.price is not None and prev.in_stock and prev.price < my_price
            gap = (my_price - new) / my_price * 100
            if not was_cheaper and gap >= rule.threshold:
                return {"new": str(new), "mine": str(my_price), "pct": f"{gap:.1f}"}
    elif rule.kind == K.OUT_OF_STOCK:
        if prev is not None and prev.in_stock and not snap.in_stock:
            return {"old": str(old) if old else None}
    elif rule.kind == K.BACK_IN_STOCK:
        if prev is not None and not prev.in_stock and snap.in_stock:
            return {"new": str(new) if new is not None else None}
    return None


def evaluate_snapshot(snapshot_id: int, previous_id: int | None) -> list[AlertEvent]:
    snap = PriceSnapshot.objects.select_related("offer__product", "offer__store").get(pk=snapshot_id)
    prev = PriceSnapshot.objects.filter(pk=previous_id).first() if previous_id else None
    offer = snap.offer
    product = offer.product
    events = []
    rules = AlertRule.objects.filter(organization_id=offer.organization_id, is_active=True)
    for rule in rules:
        if not rule.applies_to(product):
            continue
        payload = _matches(rule, snap, prev, product.my_price)
        if payload is None:
            continue
        payload.update({"store": offer.store.name, "product": product.name, "sku": product.sku, "url": offer.url})
        try:
            with transaction.atomic():
                events.append(
                    AlertEvent.objects.create(
                        organization_id=offer.organization_id, rule=rule, offer=offer, snapshot=snap, payload=payload
                    )
                )
        except IntegrityError:
            continue
    return events


# --- Formatting ----------------------------------------------------------------


def _money(value) -> str:
    return fmt(Decimal(value)) if value not in (None, "") else "—"


def format_event_line(event: AlertEvent) -> str:
    p = event.payload
    store = escape(p.get("store", ""))
    kind = event.rule.kind
    if kind == K.PRICE_DROP_PERCENT:
        return "📉 " + _("%(store)s: %(old)s → %(new)s (−%(pct)s%%)") % {
            "store": store,
            "old": _money(p.get("old")),
            "new": _money(p.get("new")),
            "pct": p.get("pct"),
        }
    if kind == K.PRICE_CHANGED:
        return "🔄 " + _("%(store)s: %(old)s → %(new)s") % {
            "store": store,
            "old": _money(p.get("old")),
            "new": _money(p.get("new")),
        }
    if kind == K.CHEAPER_THAN_MINE:
        return "⚠️ " + _("%(store)s is cheaper than you: %(new)s vs your %(mine)s") % {
            "store": store,
            "new": _money(p.get("new")),
            "mine": _money(p.get("mine")),
        }
    if kind == K.OUT_OF_STOCK:
        return "🚫 " + _("%(store)s: out of stock") % {"store": store}
    if kind == K.BACK_IN_STOCK:
        return "✅ " + _("%(store)s: back in stock at %(new)s") % {"store": store, "new": _money(p.get("new"))}
    return f"• {store}"  # pragma: no cover


def build_group_message(product, events: list[AlertEvent], lang: str) -> tuple[str, list[list[dict]]]:
    with translation.override(lang):
        rec = recommend_price(product)
        lines = [f"🔔 <b>{escape(product.name)}</b> <code>{escape(product.sku)}</code>"]
        lines += [format_event_line(e) for e in events]
        lines.append(_("Your price: %(p)s") % {"p": fmt(product.my_price)})
        buttons_row: list[dict] = []
        url = f"{settings.SITE_URL}/products/{product.pk}/"
        if telegram.public_url_allowed(url):
            buttons_row.append({"text": _("Open product"), "url": url})
        else:
            buttons_row.append({"text": _("Open product"), "callback_data": f"open:{product.pk}"})
        buttons = [buttons_row]
        if rec.price is not None and rec.price != product.my_price:
            lines.append(_("Recommended: %(p)s") % {"p": fmt(rec.price)})
            buttons.append(
                [
                    {
                        "text": _("Apply %(p)s") % {"p": fmt(rec.price)},
                        "callback_data": f"apply:{product.pk}:{int(rec.price)}",
                    }
                ]
            )
        buttons.append([{"text": _("Mute this alert"), "callback_data": f"mute:{events[0].rule_id}"}])
    return "\n".join(lines), buttons


def recipients(org) -> list[TelegramLink]:
    return list(
        TelegramLink.objects.filter(
            user__memberships__organization=org, chat_id__isnull=False, is_active=True
        ).select_related("user")
    )


def deliver_pending(now=None) -> int:
    """Send pending events grouped per product, max one message per product per window."""
    from apps.billing.services import get_limits

    now = now or timezone.now()
    window = timedelta(minutes=settings.ALERT_GROUP_WINDOW_MINUTES)
    pending = (
        AlertEvent.objects.filter(sent=False)
        .select_related("rule", "offer__product", "offer__store", "organization")
        .order_by("created_at")
    )
    groups: dict[tuple[int, int], list[AlertEvent]] = defaultdict(list)
    for event in pending:
        groups[(event.organization_id, event.offer.product_id)].append(event)

    sent_messages = 0
    for (_org_id, product_id), events in groups.items():
        org = events[0].organization
        recently = AlertEvent.objects.filter(
            organization=org, offer__product_id=product_id, sent=True, sent_at__gte=now - window
        ).exists()
        if recently:
            continue
        product = events[0].offer.product
        channel = AlertEvent.Channel.LOG
        errors = []
        limits = get_limits(org)
        if limits.telegram_alerts and any(e.rule.notify_telegram for e in events):
            for link in recipients(org):
                text, buttons = build_group_message(product, events, link.language)
                if telegram.send_message(link.chat_id, text, buttons):
                    channel = AlertEvent.Channel.TELEGRAM
                    sent_messages += 1
                else:
                    errors.append(f"tg:{link.chat_id}")
        if any(e.rule.notify_email for e in events):
            emails = list(org.memberships.values_list("user__email", flat=True))
            if emails:
                text, _buttons = build_group_message(product, events, "ru")
                plain = text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
                send_mail(f"PriceWatch: {product.name}", plain, None, emails, fail_silently=True)
                if channel == AlertEvent.Channel.LOG:
                    channel = AlertEvent.Channel.EMAIL
        AlertEvent.objects.filter(pk__in=[e.pk for e in events]).update(
            sent=True, sent_at=now, channel=channel, delivery_error=",".join(errors)[:300]
        )
    return sent_messages
