from celery import shared_task

from . import digest


@shared_task(name="reports.send_due_digests")
def send_due_digests() -> int:
    total = 0
    for org in digest.due_organizations():
        total += digest.send_digest(org)
    return total
