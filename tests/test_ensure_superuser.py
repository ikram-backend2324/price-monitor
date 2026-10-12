import pytest
from django.core.management import call_command

from apps.accounts.models import User


@pytest.mark.django_db
def test_create_update_and_demote():
    call_command("ensure_superuser", email="First@x.test", password="pass-1-long")
    u = User.objects.get(email="first@x.test")
    assert u.is_superuser and u.check_password("pass-1-long")
    # new password for the same e-mail
    call_command("ensure_superuser", email="first@x.test", password="pass-2-long")
    u.refresh_from_db()
    assert u.check_password("pass-2-long")
    # new e-mail: old admin loses rights
    call_command("ensure_superuser", email="second@x.test", password="pass-3-long", demote_others=True)
    u.refresh_from_db()
    assert not u.is_superuser and not u.is_staff
    assert User.objects.get(email="second@x.test").is_superuser


@pytest.mark.django_db
def test_skips_without_values():
    call_command("ensure_superuser", email="", password="")
    assert not User.objects.exists()
