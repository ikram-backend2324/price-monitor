from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),
    path("invite/<str:token>/", views.accept_invite, name="accept_invite"),
    path("org/new/", views.create_org, name="create_org"),
    path("org/<int:org_id>/switch/", views.switch_organization, name="switch_org"),
]
