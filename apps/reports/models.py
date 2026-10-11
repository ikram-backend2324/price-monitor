from django.db import models


class DigestLog(models.Model):
    """Ensures the morning digest is sent once per organization per local day."""

    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="digests")
    date = models.DateField()
    sent_at = models.DateTimeField(auto_now_add=True)
    recipients = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "date"], name="uniq_digest_per_day")]
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.organization} {self.date}"
