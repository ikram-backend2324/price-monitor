from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:
    from apps.accounts.models import Organization


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantQuerySet(models.QuerySet):
    """QuerySet for models that carry an ``organization`` foreign key.

    Every tenant-facing view/API must go through ``for_org`` so that data of one
    organization can never leak into another.
    """

    org_lookup = "organization"

    def for_org(self, org: Organization | None):
        if org is None:
            return self.none()
        return self.filter(**{self.org_lookup: org})
