#!/bin/sh
# Wait for Postgres/Redis, optionally run migrations, then exec the command.
set -e

wait_for() {
  host="$1"; port="$2"; name="$3"
  i=0
  until python -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(s.connect_ex(('$host', $port)))" 2>/dev/null; do
    i=$((i+1))
    if [ "$i" -gt 60 ]; then echo "Timed out waiting for $name ($host:$port)"; exit 1; fi
    sleep 1
  done
}

wait_for "${DB_HOST:-db}" "${DB_PORT:-5432}" postgres
wait_for "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}" redis

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
fi

exec "$@"
