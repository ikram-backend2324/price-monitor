from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Organization
from apps.alerts.models import AlertRule
from apps.catalog.models import Category, CompetitorOffer, Product
from apps.pricing.models import PricingRule

INPUT = (
    "w-full rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 "
    "px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
)


class StyledMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "h-4 w-4 rounded border-slate-300 text-indigo-600")
            else:
                widget.attrs.setdefault("class", INPUT)


class TenantFormMixin(StyledMixin):
    """Limits FK choices to the current organization."""

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        if "category" in self.fields:
            self.fields["category"].queryset = Category.objects.for_org(organization)
        if "product" in self.fields:
            self.fields["product"].queryset = Product.objects.for_org(organization)


class ProductForm(TenantFormMixin, forms.ModelForm):
    new_category = forms.CharField(label=_("…or new category"), required=False, max_length=120)

    class Meta:
        model = Product
        fields = ["sku", "name", "category", "my_price", "cost_price", "is_active"]

    def clean_sku(self):
        sku = self.cleaned_data["sku"].strip()
        qs = Product.objects.for_org(self.organization).filter(sku=sku)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("A product with this SKU already exists."))
        return sku

    def save(self, commit=True):
        product = super().save(commit=False)
        product.organization = self.organization
        new_cat = self.cleaned_data.get("new_category", "").strip()
        if new_cat:
            product.category, _c = Category.objects.get_or_create(organization=self.organization, name=new_cat)
        if commit:
            product.save()
        return product


class OfferForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = CompetitorOffer
        fields = ["url", "check_interval_minutes"]
        widgets = {"url": forms.URLInput(attrs={"placeholder": "https://uzum.uz/ru/product/..."})}


class AlertRuleForm(TenantFormMixin, forms.ModelForm):
    class Meta:
        model = AlertRule
        fields = ["kind", "threshold", "scope", "category", "product", "notify_telegram", "notify_email", "is_active"]

    def clean(self):
        data = super().clean()
        if data.get("scope") == AlertRule.Scope.CATEGORY and not data.get("category"):
            self.add_error("category", _("Choose a category"))
        if data.get("scope") == AlertRule.Scope.PRODUCT and not data.get("product"):
            self.add_error("product", _("Choose a product"))
        return data


class PricingRuleForm(TenantFormMixin, forms.ModelForm):
    class Meta:
        model = PricingRule
        fields = [
            "name",
            "strategy",
            "amount",
            "percent",
            "min_margin_percent",
            "round_to",
            "scope",
            "category",
            "product",
            "priority",
            "is_active",
        ]


class OrganizationSettingsForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "digest_enabled", "digest_time"]
        widgets = {"digest_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}


class ImportForm(StyledMixin, forms.Form):
    file = forms.FileField(label=_("CSV or Excel file"))
    check_interval_minutes = forms.IntegerField(label=_("Check interval (min)"), initial=360, min_value=5)
