from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _

from .models import Invitation, Role, User


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label=_("Email"), widget=forms.EmailInput(attrs={"autofocus": True}))


class SignupForm(forms.Form):
    email = forms.EmailField(label=_("Email"))
    password = forms.CharField(label=_("Password"), widget=forms.PasswordInput)
    organization_name = forms.CharField(label=_("Company name"), max_length=200)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(_("A user with this email already exists."))
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        password_validation.validate_password(password)
        return password


class InviteAcceptForm(forms.Form):
    password = forms.CharField(label=_("Password"), widget=forms.PasswordInput, required=False)


class InvitationForm(forms.ModelForm):
    class Meta:
        model = Invitation
        fields = ["email", "role"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [(Role.MANAGER, Role.MANAGER.label), (Role.VIEWER, Role.VIEWER.label)]
