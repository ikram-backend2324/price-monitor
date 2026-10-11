from __future__ import annotations

import secrets
from datetime import time, timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    username = None  # type: ignore[assignment]
    email = models.EmailField(_("email"), unique=True)
    language = models.CharField(max_length=5, choices=settings.LANGUAGES, default="ru")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []  # type: ignore[misc]

    objects = UserManager()  # type: ignore[misc,assignment]

    def __str__(self) -> str:
        return self.email

    @property
    def default_membership(self) -> Membership | None:
        return self.memberships.select_related("organization").order_by("created_at").first()


class Organization(TimeStampedModel):
    name = models.CharField(_("name"), max_length=200)
    slug = models.SlugField(unique=True, max_length=220)
    timezone = models.CharField(max_length=64, default="Asia/Tashkent")
    digest_time = models.TimeField(_("digest time"), default=time(9, 0))
    digest_enabled = models.BooleanField(_("send morning digest"), default=True)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "org"
            slug, i = base, 1
            while Organization.objects.filter(slug=slug).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)


class Role(models.TextChoices):
    OWNER = "owner", _("Owner")
    MANAGER = "manager", _("Manager")
    VIEWER = "viewer", _("Viewer")


class Membership(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "organization"], name="uniq_membership")]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization} ({self.role})"

    @property
    def can_edit(self) -> bool:
        return self.role in (Role.OWNER, Role.MANAGER)


def _invite_token() -> str:
    return secrets.token_urlsafe(24)


def _invite_expiry():
    return timezone.now() + timedelta(days=7)


class Invitation(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MANAGER)
    token = models.CharField(max_length=64, unique=True, default=_invite_token)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    expires_at = models.DateTimeField(default=_invite_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Invite {self.email} → {self.organization}"

    @property
    def is_valid(self) -> bool:
        return self.accepted_at is None and self.expires_at > timezone.now()
