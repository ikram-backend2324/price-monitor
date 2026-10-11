from .views import health


class HealthCheckMiddleware:
    """Answer /health/ before host validation.

    Load balancers (Render, Docker, UptimeRobot) probe with internal IPs or
    hostnames that are not in ALLOWED_HOSTS; they must still get a real answer.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/health/":
            return health(request)
        return self.get_response(request)
