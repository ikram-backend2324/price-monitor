from celery import shared_task

from . import services


@shared_task(name="billing.expire_subscriptions")
def expire_subscriptions() -> int:
    return services.expire_subscriptions()
