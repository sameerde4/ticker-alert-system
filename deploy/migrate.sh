#!/bin/sh
set -eu
export PGPASSWORD=postgres
echo "Waiting for Postgres..."
until pg_isready -h postgres -U postgres -d ticker_alert_db >/dev/null 2>&1; do
  sleep 1
done
echo "Applying migrations..."
for f in /migrations/*.sql; do
  echo "  -> $f"
  psql -h postgres -U postgres -d ticker_alert_db -v ON_ERROR_STOP=1 -f "$f"
done
echo "Migrations complete."
