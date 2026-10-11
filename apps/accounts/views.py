from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .forms import EmailAuthenticationForm, InviteAcceptForm, SignupForm
from .middleware import SESSION_KEY
from .models import Invitation, Membership, User
from .services import create_organization


class LoginView(auth_views.LoginView):
    authentication_form = EmailAuthenticationForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = User.objects.create_user(
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
            language=(getattr(request, "LANGUAGE_CODE", "ru") or "ru")[:2],
        )
        create_organization(user, form.cleaned_data["organization_name"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, _("Welcome! Your 14-day trial has started."))
        return redirect("dashboard:home")
    return render(request, "accounts/signup.html", {"form": form})


def accept_invite(request, token):
    invite = get_object_or_404(Invitation, token=token)
    if not invite.is_valid:
        return render(request, "accounts/invite_invalid.html", status=410)
    existing = User.objects.filter(email=invite.email.lower()).first()
    form = InviteAcceptForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if existing is None:
            password = form.cleaned_data.get("password")
            if not password or len(password) < 8:
                form.add_error("password", _("Choose a password of at least 8 characters."))
                return render(request, "accounts/invite_accept.html", {"invite": invite, "form": form})
            existing = User.objects.create_user(email=invite.email, password=password)
        elif request.user != existing:
            messages.info(
                request, _("Please log in as %(email)s to accept the invitation.") % {"email": existing.email}
            )
            return redirect(f"/login/?next=/invite/{token}/")
        Membership.objects.get_or_create(
            user=existing, organization=invite.organization, defaults={"role": invite.role}
        )
        invite.accepted_at = timezone.now()
        invite.save(update_fields=["accepted_at"])
        login(request, existing, backend="django.contrib.auth.backends.ModelBackend")
        request.session[SESSION_KEY] = invite.organization_id
        return redirect("dashboard:home")
    return render(request, "accounts/invite_accept.html", {"invite": invite, "form": form, "existing": existing})


@login_required
@require_POST
def switch_organization(request, org_id):
    if Membership.objects.filter(user=request.user, organization_id=org_id).exists():
        request.session[SESSION_KEY] = org_id
    return redirect("dashboard:home")


@login_required
def create_org(request):
    if request.method == "POST" and request.POST.get("name", "").strip():
        org = create_organization(request.user, request.POST["name"].strip()[:200])
        request.session[SESSION_KEY] = org.id
        return redirect("dashboard:home")
    return render(request, "accounts/create_org.html")
