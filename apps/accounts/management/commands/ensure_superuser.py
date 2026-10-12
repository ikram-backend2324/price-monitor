"""Create or update the admin account from DJANGO_SUPERUSER_EMAIL / DJANGO_SUPERUSER_PASSWORD.

Runs on every start of the Render demo, so changing these variables in the
hosting dashboard and restarting is enough to change the admin login.
"""

import os

from django.core.management.base import BaseCommand

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Ensure a superuser with the e-mail/password from the environment exists"

    def add_arguments(self, parser):
        parser.add_argument("--email", default=os.environ.get("DJANGO_SUPERUSER_EMAIL", ""))
        parser.add_argument("--password", default=os.environ.get("DJANGO_SUPERUSER_PASSWORD", ""))
        parser.add_argument(
            "--demote-others",
            action="store_true",
            help="Remove admin rights from other superusers (e.g. after changing the admin e-mail)",
        )

    def handle(self, *args, email, password, demote_others, **options):
        email = email.strip().lower()
        if not email or not password:
            self.stdout.write("DJANGO_SUPERUSER_EMAIL/PASSWORD not set — skipping")
            return
        user, created = User.objects.get_or_create(email=email)
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()
        self.stdout.write(f"Superuser {email} {'created' if created else 'updated'}")
        if demote_others:
            n = User.objects.filter(is_superuser=True).exclude(pk=user.pk).update(is_superuser=False, is_staff=False)
            if n:
                self.stdout.write(f"Removed admin rights from {n} other account(s)")
