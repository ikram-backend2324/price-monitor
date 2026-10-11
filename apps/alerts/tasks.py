from celery import shared_task

from . import services


@shared_task(name="alerts.deliver_pending_alerts")
def deliver_pending_alerts() -> int:
    return services.deliver_pending()
