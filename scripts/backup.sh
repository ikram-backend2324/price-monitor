#!/usr/bin/env bash
# Daily PostgreSQL backup: dump → gzip → (optional) upload to S3-compatible storage → keep 14 local copies.
# Cron (as the deploy user):  15 3 * * * cd /opt/pricewatch && ./scripts/backup.sh >> backups/backup.log 2>&1
# Optional upload: install `rclone`, configure a remote named "backup" (rclone config), set RCLONE_REMOTE=backup:pricewatch
set -euo pipefail
cd "$(dirname "$0")/.."
source .env
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p backups
FILE="backups/pricewatch-${STAMP}.sql.gz"
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

$COMPOSE exec -T db pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --no-owner --format=plain | gzip -9 > "$FILE"
echo "$(date -Is) backup written: $FILE ($(du -h "$FILE" | cut -f1))"

if [ -n "${RCLONE_REMOTE:-}" ]; then
  rclone copy "$FILE" "$RCLONE_REMOTE/" && echo "$(date -Is) uploaded to $RCLONE_REMOTE"
fi

ls -1t backups/pricewatch-*.sql.gz | tail -n +15 | xargs -r rm --
