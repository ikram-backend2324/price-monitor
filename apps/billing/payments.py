"""Payment provider interface.

Click and Payme integrations are left as documented stubs: they need merchant
credentials and a signed contract with the provider. ``ManualProvider`` is used
today — the admin confirms the payment and activates the plan in Django admin.
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass

from django.conf import settings

from .models import PaymentTransaction, Plan


@dataclass
class PaymentIntent:
    transaction: PaymentTransaction
    redirect_url: str | None
    instructions: str


class PaymentProvider(abc.ABC):
    code: str = "base"

    @abc.abstractmethod
    def create_payment(self, org, plan: Plan, months: int = 1) -> PaymentIntent: ...

    @abc.abstractmethod
    def handle_callback(self, payload: dict) -> PaymentTransaction | None:
        """Process a provider webhook; return the updated transaction."""

    def _new_transaction(self, org, plan: Plan, months: int) -> PaymentTransaction:
        return PaymentTransaction.objects.create(
            organization=org,
            plan=plan,
            months=months,
            amount_uzs=plan.price_uzs * months,
            provider=self.code,
            external_id=uuid.uuid4().hex,
        )


class ManualProvider(PaymentProvider):
    """Bank transfer / cash: an admin marks the payment as paid in the admin panel."""

    code = "manual"

    def create_payment(self, org, plan, months=1):
        tx = self._new_transaction(org, plan, months)
        return PaymentIntent(
            transaction=tx,
            redirect_url=None,
            instructions=(
                f"Invoice #{tx.id}: {tx.amount_uzs:,} UZS. Pay by bank transfer and send the receipt "
                "to support — your plan will be activated within one business day."
            ),
        )

    def handle_callback(self, payload):  # pragma: no cover - manual flow has no callbacks
        return None


class ClickProvider(PaymentProvider):  # pragma: no cover - stub until merchant credentials exist
    """Click.uz SHOP API: prepare/complete callbacks signed with MD5 of secret key.

    TODO: implement when CLICK_SERVICE_ID / CLICK_MERCHANT_ID / CLICK_SECRET_KEY are issued.
    Docs: https://docs.click.uz/
    """

    code = "click"

    def create_payment(self, org, plan, months=1):
        raise NotImplementedError("Click integration requires merchant credentials")

    def handle_callback(self, payload):
        raise NotImplementedError


class PaymeProvider(PaymentProvider):  # pragma: no cover - stub until merchant credentials exist
    """Payme Merchant API (JSON-RPC: CheckPerformTransaction, CreateTransaction, PerformTransaction...).

    TODO: implement when PAYME_MERCHANT_ID / PAYME_KEY are issued. Docs: https://developer.help.paycom.uz/
    """

    code = "payme"

    def create_payment(self, org, plan, months=1):
        raise NotImplementedError("Payme integration requires merchant credentials")

    def handle_callback(self, payload):
        raise NotImplementedError


PROVIDERS: dict[str, type[PaymentProvider]] = {
    "manual": ManualProvider,
    "click": ClickProvider,
    "payme": PaymeProvider,
}


def get_provider(code: str | None = None) -> PaymentProvider:
    code = code or str(getattr(settings, "PAYMENT_PROVIDER", "manual"))
    return PROVIDERS[code]()
