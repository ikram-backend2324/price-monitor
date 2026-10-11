from django.conf import settings
from django.utils import translation

from .models import Membership

SESSION_KEY = "current_org_id"


class CurrentOrganizationMiddleware:
    """Attach ``request.organization`` / ``request.membership`` for the logged-in user.

    The active organization is stored in the session; falls back to the user's
    first membership. Anonymous users get ``None``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.organization = None
        request.membership = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            qs = Membership.objects.select_related("organization").filter(user=user)
            org_id = request.session.get(SESSION_KEY)
            membership = qs.filter(organization_id=org_id).first() if org_id else None
            if membership is None:
                membership = qs.order_by("created_at").first()
            if membership is not None:
                request.membership = membership
                request.organization = membership.organization
            # Use the user's preferred language unless the URL or cookie picks one explicitly.
            if not request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME) and user.language:
                translation.activate(user.language)
                request.LANGUAGE_CODE = user.language
        return self.get_response(request)
