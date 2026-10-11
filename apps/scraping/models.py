from django.db import models
from django.utils.translation import gettext_lazy as _


class ScrapeRun(models.Model):
    """One fetch attempt. Light-weight: written on every check (snapshots only on change)."""

    class Status(models.TextChoices):
        SUCCESS = "success", _("Success")
        UNCHANGED = "unchanged", _("Unchanged")
        FAILED = "failed", _("Failed")
        ROBOTS = "robots", _("Blocked by robots.txt")
        RATE_LIMITED = "rate_limited", _("Rate limited")
        SUSPICIOUS = "suspicious", _("Suspicious value")

    offer = models.ForeignKey("catalog.CompetitorOffer", on_delete=models.CASCADE, related_name="runs")
    store = models.ForeignKey("catalog.Store", on_delete=models.CASCADE, related_name="runs")
    started_at = models.DateTimeField(db_index=True)
    duration_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices)
    error = models.CharField(max_length=500, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    adapter = models.CharField(max_length=16, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["store", "started_at"], name="run_store_time_idx")]

    def __str__(self) -> str:
        return f"{self.offer_id} {self.status} {self.started_at:%H:%M:%S}"

    @property
    def ok(self) -> bool:
        return self.status in (self.Status.SUCCESS, self.Status.UNCHANGED, self.Status.SUSPICIOUS)


class ScraperHealthEvent(models.Model):
    class Kind(models.TextChoices):
        DEGRADED = "SCRAPER_DEGRADED", _("Scraper degraded")
        RECOVERED = "SCRAPER_RECOVERED", _("Scraper recovered")
        OFFER_FAILING = "OFFER_FAILING", _("Link keeps failing")

    store = models.ForeignKey("catalog.Store", on_delete=models.CASCADE, related_name="health_events")
    offer = models.ForeignKey("catalog.CompetitorOffer", null=True, blank=True, on_delete=models.CASCADE)
    kind = models.CharField(max_length=32, choices=Kind.choices)
    details = models.TextField(blank=True)
    success_rate = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    notified = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.kind} {self.store}"
