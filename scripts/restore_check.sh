#!/usr/bin/env bash
# Prove that a backup can actually be restored: load it into a throw-away Postgres and count rows.
# Usage: ./scripts/restore_check.sh backups/pricewatch-20261012-031500.sql.gz
set -euo pipefail
FILE="${1:?usage: restore_check.sh <backup.sql.gz>}"
NAME="pw-restore-check-$$"
docker run -d --rm --name "$NAME" -e POSTGRES_PASSWORD=check -e POSTGRES_DB=restore postgres:16-alpine >/dev/null
trap 'docker stop "$NAME" >/dev/null' EXIT
until docker exec "$NAME" pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
sleep 2
gunzip -c "$FILE" | docker exec -i "$NAME" psql -q -U postgres -d restore >/dev/null
docker exec "$NAME" psql -U postgres -d restore -t -c \
  "select 'products', count(*) from catalog_product union all
   select 'offers', count(*) from catalog_competitoroffer union all
   select 'snapshots', count(*) from pricing_pricesnapshot union all
   select 'users', count(*) from accounts_user;"
echo "Restore check OK: $FILE"
