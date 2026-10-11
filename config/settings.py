"""Django settings for PriceWatch.

All configuration comes from environment variables (see .env.example).
"""

from __future__ import annotations

from pathlib import Path

import environ
from celery.schedules import crontab
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    PROXY_URLS=(list, []),
)
# ENV_FILE lets local (non-Docker) runs use e.g. .env.local; real environment variables always win.
environ.Env.read_env(BASE_DIR / env.str("ENV_FILE", default=".env"), overwrite=False)

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
SITE_URL = env("SITE_URL", default="http://localhost:8000").rstrip("/")

# Render.com sets RENDER_EXTERNAL_HOSTNAME (e.g. pricewatch-demo.onrender.com): trust it automatically.
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")
    if "SITE_URL" not in env.ENVIRON:
        SITE_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "django_celery_beat",
    "apps.core",
    "apps.accounts",
    "apps.billing",
    "apps.catalog",
    "apps.scraping",
    "apps.pricing",
    "apps.alerts",
    "apps.reports",
    "apps.dashboard",
    "apps.api",
]

MIDDLEWARE = [
    "apps.core.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.middleware.CurrentOrganizationMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "apps.accounts.context_processors.organization",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = env("REDIS_URL", default="")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "pw",
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "login"

# --- i18n -----------------------------------------------------------------
LANGUAGE_CODE = "ru"
LANGUAGES = [("ru", _("Russian")), ("uz", _("Uzbek")), ("en", _("English"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = env("TIME_ZONE", default="Asia/Tashkent")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="PriceWatch <noreply@pricewatch.local>")

# --- Security (production) ------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = env.bool("SECURE_COOKIES", default=True)
    CSRF_COOKIE_SECURE = env.bool("SECURE_COOKIES", default=True)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
ADMIN_URL = env("ADMIN_URL", default="admin/")

# --- DRF ------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "1000/hour", "login": "10/minute"},
}
SPECTACULAR_SETTINGS = {
    "TITLE": "PriceWatch API",
    "DESCRIPTION": "Competitor price monitoring API. Authenticate with `Authorization: Token <key>`.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- Celery ---------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL or "memory://")
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=not REDIS_URL)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ROUTES = {
    "scraping.scrape_offer_fast": {"queue": "fast"},
    "scraping.scrape_offer_browser": {"queue": "browser"},
}
# Default periodic tasks; synced into django-celery-beat tables by `setup_periodic_tasks`.
CELERY_BEAT_SCHEDULE = {
    "schedule-due-offers": {"task": "scraping.schedule_due_offers", "schedule": crontab()},
    "check-scraper-health": {"task": "scraping.check_scraper_health", "schedule": crontab(minute="*/5")},
    "deliver-alerts": {"task": "alerts.deliver_pending_alerts", "schedule": crontab()},
    "send-digests": {"task": "reports.send_due_digests", "schedule": crontab(minute="*/5")},
    "expire-subscriptions": {"task": "billing.expire_subscriptions", "schedule": crontab(minute=10, hour=0)},
}

# --- Scraping -------------------------------------------------------------
SCRAPER = {
    "TIMEOUT": env.float("SCRAPER_TIMEOUT", default=20.0),
    "MAX_RETRIES": env.int("SCRAPER_MAX_RETRIES", default=3),
    "BACKOFF_BASE": env.float("SCRAPER_BACKOFF_BASE", default=1.0),
    "RESPECT_ROBOTS": env.bool("SCRAPER_RESPECT_ROBOTS", default=True),
    "ROBOTS_CACHE_SECONDS": 24 * 3600,
    "PROXY_URLS": env("PROXY_URLS"),
    "RATE_LIMIT_BACKEND": env("SCRAPER_RATE_LIMIT_BACKEND", default="redis" if REDIS_URL else "memory"),
    "MIN_DELAY": env.float("SCRAPER_MIN_DELAY", default=0.3),
    "MAX_DELAY": env.float("SCRAPER_MAX_DELAY", default=1.5),
    "SUSPICIOUS_RATIO": 5,
    "RECHECK_SUSPICIOUS_SECONDS": 600,
    "DEGRADED_SUCCESS_RATE": 0.7,
    "DEGRADED_CONSECUTIVE_FAILURES": 5,
    "SCHEDULE_BATCH": env.int("SCRAPER_SCHEDULE_BATCH", default=1000),
}

# --- Telegram -------------------------------------------------------------
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_BOT_USERNAME = env("TELEGRAM_BOT_USERNAME", default="")
ADMIN_TELEGRAM_CHAT_ID = env("ADMIN_TELEGRAM_CHAT_ID", default="")
ALERT_GROUP_WINDOW_MINUTES = env.int("ALERT_GROUP_WINDOW_MINUTES", default=30)

DEMO_USER_PASSWORD = env("DEMO_USER_PASSWORD", default="demo12345")
# shop code -> host[:port] where the demo-shop answers (docker network aliases by default)
DEMO_SHOP_HOSTS = dict(
    item.split("=", 1)
    for item in env.list(
        "DEMO_SHOP_HOSTS",
        default=["techbozor=techbozor.demo:8001", "megasavdo=megasavdo.demo:8001", "smartmarket=smartmarket.demo:8001"],
    )
)

# --- Logging & Sentry -----------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {"httpx": {"level": "WARNING"}},
}

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:  # pragma: no cover - depends on external service
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        send_default_pii=False,
    )
