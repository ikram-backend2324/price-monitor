"""Synchronous Django-side operations for the bot (called through ``sync_to_async``).

Kept free of aiogram imports so they are easy to unit-test.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone, translation
from django.utils.html import escape

from apps.accounts.models import Membership
from apps.alerts.models import AlertRule, TelegramLink
from apps.catalog.models import Product
from apps.pricing.services import fmt, recommend_price

CODE_LEN = 6


@dataclass
class Account:
    link: TelegramLink
    membership: Membership | None

    @property
    def lang(self) -> str:
        return self.link.language

    @property
    def org(self):
        return self.membership.organization if self.membership else None


def get_account(chat_id: int) -> Account | None:
    link = TelegramLink.objects.select_related("user").filter(chat_id=chat_id, is_active=True).first()
    if link is None:
        return None
    membership = link.user.memberships.select_related("organization").order_by("created_at").first()
    return Account(link, membership)


@transaction.atomic
def link_account(chat_id: int, username: str, code: str) -> Account | None:
    code = (code or "").strip().upper()
    if len(code) != CODE_LEN:
        return None
    link = (
        TelegramLink.objects.select_for_update()
        .select_related("user")
        .filter(code=code, code_expires_at__gte=timezone.now())
        .first()
    )
    if link is None:
        return None
    # A chat can be linked to only one user
    TelegramLink.objects.filter(chat_id=chat_id).exclude(pk=link.pk).update(chat_id=None)
    link.chat_id = chat_id
    link.username = (username or "")[:64]
    link.code_expires_at = timezone.now()  # one-time code
    link.save()
    return get_account(chat_id)


def set_language(chat_id: int, lang: str) -> bool:
    if lang not in ("ru", "uz", "en"):
        return False
    return bool(TelegramLink.objects.filter(chat_id=chat_id).update(language=lang))


def products_text(account: Account, limit: int = 30) -> str | None:
    products = list(
        Product.objects.for_org(account.org).filter(is_active=True).prefetch_related("offers").order_by("name")[:limit]
    )
    if not products:
        return None
    lines = []
    for p in products:
        market = p.market_min()
        mark = ""
        if market is not None and p.my_price:
            mark = "🔴" if p.my_price > market else "🟢"
        lines.append(
            f"{mark} <code>{escape(p.sku)}</code> {escape(p.name[:40])}\n    {fmt(p.my_price)} | {fmt(market)}"
        )
    return "\n".join(lines)


def find_product(account: Account, sku: str) -> Product | None:
    return Product.objects.for_org(account.org).filter(sku__iexact=sku.strip()).first()


def queue_check(product: Product) -> int:
    from apps.scraping.tasks import check_product_now

    return check_product_now(product)


def product_summary(product_id: int, account: Account) -> str | None:
    product = Product.objects.for_org(account.org).filter(pk=product_id).prefetch_related("offers__store").first()
    if product is None:
        return None
    with translation.override(account.lang):
        rec = recommend_price(product)
    lines = [f"📦 <b>{escape(product.name)}</b> <code>{escape(product.sku)}</code>", f"💰 {fmt(product.my_price)}"]
    for o in product.offers.all():
        stock = "✅" if o.last_in_stock else ("🚫" if o.last_in_stock is False else "❔")
        lines.append(f"{stock} {escape(o.store.name)}: {fmt(o.last_price)}")
    if rec.price is not None:
        lines.append(f"🎯 {fmt(rec.price)}")
    return "\n".join(lines)


def digest_text(account: Account) -> str:
    from apps.reports.digest import collect, render_text

    return render_text(account.org, collect(account.org), account.lang)


def apply_price(account: Account, product_id: int, price: int) -> Product | None:
    """Returns the product, or raises PermissionError for viewers."""
    if account.membership is None or not account.membership.can_edit:
        raise PermissionError
    product = Product.objects.for_org(account.org).filter(pk=product_id).first()
    if product is None or price <= 0:
        return None
    product.set_my_price(Decimal(price), user=account.link.user, source="telegram")
    return product


def mute_rule(account: Account, rule_id: int) -> AlertRule | None:
    if account.membership is None or not account.membership.can_edit:
        raise PermissionError
    rule = AlertRule.objects.for_org(account.org).filter(pk=rule_id).first()
    if rule is None:
        return None
    rule.is_active = False
    rule.save(update_fields=["is_active", "updated_at"])
    return rule
