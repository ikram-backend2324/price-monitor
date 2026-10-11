from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.forms import InvitationForm
from apps.accounts.models import Invitation, Membership, Role
from apps.alerts.models import AlertEvent, AlertRule, TelegramLink
from apps.billing import services as billing
from apps.billing.models import Plan
from apps.billing.payments import get_provider
from apps.catalog.models import Category, CompetitorOffer, Product, Store
from apps.pricing.models import PriceSnapshot, PricingRule
from apps.pricing.services import recommend_price
from apps.reports import exporting, importing
from apps.scraping.models import ScraperHealthEvent, ScrapeRun
from apps.scraping.services import store_success_rate

from .forms import (
    AlertRuleForm,
    ImportForm,
    OfferForm,
    OrganizationSettingsForm,
    PricingRuleForm,
    ProductForm,
)


def org_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.organization is None:
            return redirect("create_org")
        return view(request, *args, **kwargs)

    return wrapper


def editor_required(view):
    @org_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.membership.can_edit:
            raise PermissionDenied(_("Viewers cannot change data"))
        return view(request, *args, **kwargs)

    return wrapper


def owner_required(view):
    @org_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.membership.role != Role.OWNER:
            raise PermissionDenied(_("Only the owner can do this"))
        return view(request, *args, **kwargs)

    return wrapper


def _products_with_offers(org):
    return (
        Product.objects.for_org(org)
        .select_related("category")
        .prefetch_related(Prefetch("offers", queryset=CompetitorOffer.objects.select_related("store")))
    )


def _recent_changes(org, limit=15, since=None):
    qs = (
        PriceSnapshot.objects.for_org(org)
        .accepted()
        .filter(kind=PriceSnapshot.Kind.CHANGE)
        .select_related("offer__product", "offer__store")
        .order_by("-checked_at")
    )
    if since:
        qs = qs.filter(checked_at__gte=since)
    rows = []
    for snap in qs[:limit]:
        prev = (
            PriceSnapshot.objects.accepted()
            .filter(offer_id=snap.offer_id, checked_at__lt=snap.checked_at)
            .order_by("-checked_at")
            .only("price", "in_stock")
            .first()
        )
        rows.append({"snap": snap, "prev": prev})
    return rows


# --- Dashboard ------------------------------------------------------------------


@org_required
def home(request):
    org = request.organization
    products = list(_products_with_offers(org).filter(is_active=True))
    more_expensive = 0
    for p in products:
        m = p.market_min()
        if m is not None and p.my_price and p.my_price > m:
            more_expensive += 1
    day_ago = timezone.now() - timedelta(hours=24)
    changes_24h = (
        PriceSnapshot.objects.for_org(org)
        .accepted()
        .filter(kind=PriceSnapshot.Kind.CHANGE, checked_at__gte=day_ago)
        .count()
    )
    store_ids = CompetitorOffer.objects.for_org(org).values_list("store_id", flat=True).distinct()
    stores = Store.objects.filter(id__in=store_ids)
    healthy = sum(1 for s in stores if s.health_status != Store.Health.DEGRADED)
    context = {
        "kpi": {
            "products": len(products),
            "offers": CompetitorOffer.objects.for_org(org).filter(is_active=True).count(),
            "more_expensive": more_expensive,
            "changes_24h": changes_24h,
            "healthy_stores": healthy,
            "total_stores": stores.count(),
        },
        "feed": _recent_changes(org, 12),
        "alerts": AlertEvent.objects.for_org(org).select_related("rule", "offer__product", "offer__store")[:8],
        "limits": billing.get_limits(org),
        "subscription": billing.get_subscription(org),
    }
    return render(request, "dashboard/home.html", context)


@org_required
def feed(request):
    return render(request, "dashboard/partials/feed.html", {"feed": _recent_changes(request.organization, 12)})


# --- Products -------------------------------------------------------------------


@org_required
def product_list(request):
    org = request.organization
    q = request.GET.get("q", "").strip()
    flt = request.GET.get("filter", "")
    category = request.GET.get("category", "")
    qs = _products_with_offers(org)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    if category:
        qs = qs.filter(category_id=category)
    rows = []
    for p in qs:
        market = p.market_min()
        diff = ((p.my_price - market) / market * 100) if market and p.my_price else None
        row = {"product": p, "market": market, "diff": diff, "offers": len(p.offers.all())}
        if flt == "expensive" and not (diff is not None and diff > 0):
            continue
        if flt == "cheaper" and not (diff is not None and diff <= 0):
            continue
        if flt == "nooffers" and row["offers"]:
            continue
        rows.append(row)
    page = Paginator(rows, 25).get_page(request.GET.get("page"))
    template = (
        "dashboard/partials/product_rows.html" if request.headers.get("HX-Request") else "dashboard/products.html"
    )
    return render(
        request,
        template,
        {"page": page, "q": q, "filter": flt, "category": category, "categories": Category.objects.for_org(org)},
    )


@org_required
def product_detail(request, pk):
    org = request.organization
    product = get_object_or_404(_products_with_offers(org), pk=pk)
    offers = list(product.offers.all())
    snapshots = (
        PriceSnapshot.objects.filter(offer__product=product).select_related("offer__store").order_by("-checked_at")[:50]
    )
    return render(
        request,
        "dashboard/product_detail.html",
        {
            "product": product,
            "offers": offers,
            "snapshots": snapshots,
            "rec": recommend_price(product),
            "market": product.market_min(),
            "offer_form": OfferForm(
                initial={"check_interval_minutes": billing.get_limits(org).min_check_interval_minutes}
            ),
        },
    )


@org_required
def chart_data(request, pk):
    product = get_object_or_404(Product.objects.for_org(request.organization), pk=pk)
    try:
        days = max(1, min(int(request.GET.get("days", 30)), 365))
    except ValueError:
        days = 30
    since = timezone.now() - timedelta(days=days)
    datasets = []
    for offer in product.offers.select_related("store"):
        prev = (
            PriceSnapshot.objects.accepted().filter(offer=offer, checked_at__lt=since).order_by("-checked_at").first()
        )
        points = []
        if prev and prev.price is not None:
            points.append({"x": since.isoformat(), "y": float(prev.price), "in_stock": prev.in_stock})
        for s in PriceSnapshot.objects.accepted().filter(offer=offer, checked_at__gte=since).order_by("checked_at"):
            if s.price is not None:
                points.append({"x": s.checked_at.isoformat(), "y": float(s.price), "in_stock": s.in_stock})
        if offer.last_price is not None:
            points.append(
                {"x": timezone.now().isoformat(), "y": float(offer.last_price), "in_stock": offer.last_in_stock}
            )
        datasets.append({"label": offer.store.name, "data": points})
    mine = []
    changes = list(product.my_price_history.filter(changed_at__gte=since))
    before = product.my_price_history.filter(changed_at__lt=since).order_by("-changed_at").first()
    start_price = before.price if before else (changes[0].price if changes else product.my_price)
    mine.append({"x": since.isoformat(), "y": float(start_price)})
    mine += [{"x": c.changed_at.isoformat(), "y": float(c.price)} for c in changes]
    mine.append({"x": timezone.now().isoformat(), "y": float(product.my_price)})
    return JsonResponse({"mine": {"label": _("My price"), "data": mine}, "competitors": datasets})


@editor_required
def product_create(request):
    form = ProductForm(request.POST or None, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        product.my_price_history.create(price=product.my_price, changed_by=request.user, source="created")
        messages.success(request, _("Product created. Now add competitor links."))
        return redirect("dashboard:product_detail", pk=product.pk)
    return render(request, "dashboard/form.html", {"form": form, "title": _("New product")})


@editor_required
def product_edit(request, pk):
    product = get_object_or_404(Product.objects.for_org(request.organization), pk=pk)
    old_price = product.my_price
    form = ProductForm(request.POST or None, instance=product, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        if product.my_price != old_price:
            product.my_price_history.create(price=product.my_price, changed_by=request.user)
        messages.success(request, _("Saved"))
        return redirect("dashboard:product_detail", pk=product.pk)
    return render(request, "dashboard/form.html", {"form": form, "title": product.name})


@editor_required
@require_POST
def product_delete(request, pk):
    product = get_object_or_404(Product.objects.for_org(request.organization), pk=pk)
    product.delete()
    messages.success(request, _("Product deleted"))
    return redirect("dashboard:products")


@editor_required
@require_POST
def apply_price(request, pk):
    product = get_object_or_404(Product.objects.for_org(request.organization), pk=pk)
    try:
        price = Decimal(request.POST.get("price", ""))
    except InvalidOperation:
        price = recommend_price(product).price
    if price is not None and price > 0:
        product.set_my_price(price, user=request.user, source="recommendation")
        messages.success(request, _("Price updated to %(p)s") % {"p": f"{price:,.0f}".replace(",", " ")})
    return redirect("dashboard:product_detail", pk=pk)


@editor_required
@require_POST
def check_now(request, pk):
    from apps.scraping.tasks import check_product_now

    product = get_object_or_404(Product.objects.for_org(request.organization), pk=pk)
    n = check_product_now(product)
    msg = _("Queued %(n)d checks — refresh in a minute.") % {"n": n}
    if request.headers.get("HX-Request"):
        return HttpResponse(f'<span class="text-emerald-600 text-sm">{msg}</span>')
    messages.info(request, msg)
    return redirect("dashboard:product_detail", pk=pk)


@editor_required
@require_POST
def offer_create(request, pk):
    org = request.organization
    product = get_object_or_404(Product.objects.for_org(org), pk=pk)
    form = OfferForm(request.POST)
    if form.is_valid():
        try:
            billing.check_offer_limit(org)
        except billing.LimitExceeded as exc:
            messages.error(request, str(exc))
            return redirect("dashboard:product_detail", pk=pk)
        url = form.cleaned_data["url"]
        if product.offers.filter(url=url).exists():
            messages.warning(request, _("This link is already tracked"))
            return redirect("dashboard:product_detail", pk=pk)
        offer = form.save(commit=False)
        offer.product = product
        offer.organization = org
        offer.store = importing._store_for(url)
        offer.save()
        from apps.scraping.tasks import enqueue_offer

        enqueue_offer(offer)
        messages.success(request, _("Link added: %(store)s. First check is queued.") % {"store": offer.store.name})
    else:
        messages.error(request, _("Invalid link: %(e)s") % {"e": form.errors.as_text()})
    return redirect("dashboard:product_detail", pk=pk)


@editor_required
@require_POST
def offer_toggle(request, pk):
    offer = get_object_or_404(CompetitorOffer.objects.for_org(request.organization), pk=pk)
    if not offer.is_active:
        try:
            billing.check_offer_limit(request.organization)
        except billing.LimitExceeded as exc:
            messages.error(request, str(exc))
            return redirect("dashboard:product_detail", pk=offer.product_id)
    offer.is_active = not offer.is_active
    offer.save(update_fields=["is_active", "updated_at"])
    return redirect("dashboard:product_detail", pk=offer.product_id)


@editor_required
@require_POST
def offer_delete(request, pk):
    offer = get_object_or_404(CompetitorOffer.objects.for_org(request.organization), pk=pk)
    product_id = offer.product_id
    offer.delete()
    return redirect("dashboard:product_detail", pk=product_id)


# --- Import / export ------------------------------------------------------------


@editor_required
def import_view(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    report = None
    if request.method == "POST" and form.is_valid():
        f = form.cleaned_data["file"]
        try:
            rows = importing.read_rows(f, f.name)
        except Exception as exc:
            messages.error(request, _("Could not read file: %(e)s") % {"e": exc})
        else:
            interval = max(
                form.cleaned_data["check_interval_minutes"],
                billing.get_limits(request.organization).min_check_interval_minutes,
            )
            report = importing.import_rows(request.organization, rows, default_interval=interval)
    return render(request, "dashboard/import.html", {"form": form, "report": report})


@org_required
def import_template(request, fmt):
    if fmt == "xlsx":
        resp = HttpResponse(
            importing.template_xlsx(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        resp = HttpResponse(importing.template_csv(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="pricewatch-import-template.{fmt}"'
    return resp


@org_required
def export(request, fmt):
    org = request.organization
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    if fmt == "xlsx":
        if not billing.get_limits(org).excel_reports:
            messages.error(request, _("Excel reports are available on the Business plan. CSV export is free."))
            return redirect("dashboard:billing")
        resp = HttpResponse(
            exporting.export_excel(org),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        resp = HttpResponse(exporting.export_csv(org), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="pricewatch-{org.slug}-{stamp}.{fmt}"'
    return resp


# --- Rules ----------------------------------------------------------------------


@org_required
def alert_rules(request):
    org = request.organization
    form = AlertRuleForm(request.POST or None, organization=org)
    if request.method == "POST":
        if not request.membership.can_edit:
            raise PermissionDenied
        if form.is_valid():
            rule = form.save(commit=False)
            rule.organization = org
            rule.save()
            messages.success(request, _("Alert rule added"))
            return redirect("dashboard:alerts")
    return render(
        request,
        "dashboard/alerts.html",
        {
            "rules": AlertRule.objects.for_org(org).select_related("category", "product"),
            "events": AlertEvent.objects.for_org(org).select_related("rule", "offer__product", "offer__store")[:50],
            "form": form,
        },
    )


@editor_required
@require_POST
def alert_rule_toggle(request, pk):
    rule = get_object_or_404(AlertRule.objects.for_org(request.organization), pk=pk)
    rule.is_active = not rule.is_active
    rule.save(update_fields=["is_active", "updated_at"])
    return redirect("dashboard:alerts")


@editor_required
@require_POST
def alert_rule_delete(request, pk):
    get_object_or_404(AlertRule.objects.for_org(request.organization), pk=pk).delete()
    return redirect("dashboard:alerts")


@org_required
def pricing_rules(request):
    org = request.organization
    form = PricingRuleForm(request.POST or None, organization=org)
    if request.method == "POST":
        if not request.membership.can_edit:
            raise PermissionDenied
        if form.is_valid():
            rule = form.save(commit=False)
            rule.organization = org
            rule.save()
            messages.success(request, _("Pricing rule added"))
            return redirect("dashboard:pricing")
    return render(
        request,
        "dashboard/pricing.html",
        {"rules": PricingRule.objects.for_org(org).select_related("category", "product"), "form": form},
    )


@editor_required
@require_POST
def pricing_rule_delete(request, pk):
    get_object_or_404(PricingRule.objects.for_org(request.organization), pk=pk).delete()
    return redirect("dashboard:pricing")


# --- Billing / health / telegram / team / settings ------------------------------


@org_required
def billing_view(request):
    org = request.organization
    return render(
        request,
        "dashboard/billing.html",
        {
            "plans": Plan.objects.filter(is_public=True),
            "subscription": billing.get_subscription(org),
            "limits": billing.get_limits(org),
            "used": billing.offers_used(org),
            "members": org.memberships.count(),
            "payments": org.payments.select_related("plan").order_by("-created_at")[:10],
        },
    )


@owner_required
@require_POST
def billing_request(request):
    plan = get_object_or_404(Plan, code=request.POST.get("plan"), is_public=True)
    months = max(1, min(int(request.POST.get("months", 1) or 1), 12))
    intent = get_provider("manual").create_payment(request.organization, plan, months)
    messages.info(request, intent.instructions)
    return redirect("dashboard:billing")


@org_required
def scraper_health(request):
    org = request.organization
    since = timezone.now() - timedelta(hours=1)
    store_ids = CompetitorOffer.objects.for_org(org).values_list("store_id", flat=True).distinct()
    rows = []
    for store in Store.objects.filter(id__in=store_ids):
        rate, total = store_success_rate(store, since)
        rows.append(
            {
                "store": store,
                "rate": rate,
                "total": total,
                "offers": CompetitorOffer.objects.for_org(org).filter(store=store).count(),
                "failing": CompetitorOffer.objects.for_org(org)
                .filter(store=store, consecutive_failures__gte=3)
                .count(),
                "last_run": ScrapeRun.objects.filter(store=store).order_by("-started_at").first(),
            }
        )
    failing = (
        CompetitorOffer.objects.for_org(org)
        .filter(Q(consecutive_failures__gt=0) | Q(robots_blocked=True))
        .select_related("product", "store")[:50]
    )
    events = ScraperHealthEvent.objects.filter(store_id__in=store_ids).select_related("store")[:20]
    runs = (
        ScrapeRun.objects.filter(offer__organization=org, started_at__gte=since)
        .values("status")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    return render(request, "dashboard/health.html", {"rows": rows, "failing": failing, "events": events, "runs": runs})


@login_required
def telegram_view(request):
    from django.conf import settings

    link, _created = TelegramLink.objects.get_or_create(user=request.user, defaults={"language": request.user.language})
    if request.method == "POST":
        if request.POST.get("action") == "unlink":
            link.chat_id = None
            link.save(update_fields=["chat_id", "updated_at"])
        link.regenerate_code()
        return redirect("dashboard:telegram")
    if link.code_expires_at < timezone.now() and not link.is_linked:
        link.regenerate_code()
    return render(
        request,
        "dashboard/telegram.html",
        {
            "link": link,
            "bot_username": settings.TELEGRAM_BOT_USERNAME,
            "bot_configured": bool(settings.TELEGRAM_BOT_TOKEN),
        },
    )


@org_required
def team(request):
    org = request.organization
    form = InvitationForm(request.POST or None)
    invite_url = None
    if request.method == "POST":
        if request.membership.role != Role.OWNER:
            raise PermissionDenied
        if form.is_valid():
            try:
                billing.check_member_limit(org)
            except billing.LimitExceeded as exc:
                messages.error(request, str(exc))
            else:
                invite = form.save(commit=False)
                invite.organization = org
                invite.invited_by = request.user
                invite.save()
                invite_url = request.build_absolute_uri(f"/invite/{invite.token}/")
                from django.core.mail import send_mail

                send_mail(
                    _("Invitation to %(org)s on PriceWatch") % {"org": org.name},
                    _("You have been invited. Accept: %(url)s") % {"url": invite_url},
                    None,
                    [invite.email],
                    fail_silently=True,
                )
                messages.success(request, _("Invitation created. Send the link to your colleague."))
                form = InvitationForm()
    return render(
        request,
        "dashboard/team.html",
        {
            "members": org.memberships.select_related("user"),
            "invites": Invitation.objects.filter(organization=org, accepted_at__isnull=True),
            "form": form,
            "invite_url": invite_url,
        },
    )


@owner_required
@require_POST
def member_remove(request, pk):
    membership = get_object_or_404(Membership, pk=pk, organization=request.organization)
    if membership.role == Role.OWNER:
        messages.error(request, _("The owner cannot be removed"))
    else:
        membership.delete()
    return redirect("dashboard:team")


@org_required
def org_settings(request):
    org = request.organization
    form = OrganizationSettingsForm(request.POST or None, instance=org)
    if request.method == "POST":
        lang = request.POST.get("language")
        if lang in dict(request.user._meta.get_field("language").choices):
            request.user.language = lang
            request.user.save(update_fields=["language"])
        if request.membership.role == Role.OWNER and form.is_valid():
            form.save()
        messages.success(request, _("Settings saved"))
        resp = redirect("dashboard:settings")
        if lang:
            resp.set_cookie("django_language", lang, max_age=365 * 24 * 3600)
        return resp
    from apps.alerts.telegram import is_configured

    token = None
    if billing.get_limits(org).api_access:
        from rest_framework.authtoken.models import Token

        token = Token.objects.get_or_create(user=request.user)[0]
    return render(
        request, "dashboard/settings.html", {"form": form, "telegram_configured": is_configured(), "api_token": token}
    )
