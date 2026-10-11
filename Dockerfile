# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# PriceWatch image. Two targets:
#   app      — web, celery fast/default workers, beat, bot (small)
#   browser  — app + Chromium for the Playwright worker (larger)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM base AS app
COPY . .
RUN DJANGO_SETTINGS_MODULE=config.settings SECRET_KEY=build python manage.py compilemessages -v0 \
    && DJANGO_SETTINGS_MODULE=config.settings SECRET_KEY=build python manage.py collectstatic --noinput -v0 \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /app/media && chown -R app:app /app
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
USER app
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]

FROM app AS browser
USER root
# Chromium + its system libraries, installed for the 'app' user
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium && chown -R app:app /ms-playwright
USER app
