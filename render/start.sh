#!/usr/bin/env bash
# Entry point of the all-in-one Render demo container.
set -uo pipefail

python manage.py migrate --noinput || exit 1

# Demo data: idempotent (does nothing if the demo organization exists).
# DEMO_RESET_ON_START=1 recreates it on every deploy/restart (fresh data for each showing).
if [ "${DEMO_RESET_ON_START:-0}" = "1" ]; then
  python manage.py seed_demo --no-admin --reset
else
  python manage.py seed_demo --no-admin
fi

# Optional private admin account (password never in the repo — set it in the Render dashboard).
# Applied on every start: change the variables in the Render dashboard and the login changes too.
# Old admin accounts lose admin rights, so only the e-mail from the environment can open /admin/.
python manage.py ensure_superuser --demote-others

# Demo shop on loopback: three "shops" answer on 127.0.0.2/3/4 (see DEMO_SHOP_HOSTS).
(cd demo_shop && exec uvicorn main:app --host 0.0.0.0 --port 8001 --log-level warning) &

# One Celery process with embedded Beat; threads keep memory low.
celery -A config worker -B -Q default,fast -n demo@%h \
  --pool threads --concurrency "${CELERY_CONCURRENCY:-4}" \
  --scheduler django_celery_beat.schedulers:DatabaseScheduler \
  --loglevel INFO &

if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
  python -m bot.main &
fi

gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-10000}" \
  --workers 1 --threads 4 --timeout 60 --access-logfile - &

# If any process dies, exit so Render restarts the whole container.
wait -n
echo "A process exited — restarting container"
exit 1
