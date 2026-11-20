#!/bin/sh
# Apply db/migrations/*.sql once each (re-running 003 deletes all alerts).
set -eu
export PGPASSWORD=postgres
echo "Waiting for Postgres..."
until pg_isready -h postgres -U postgres -d ticker_alert_db >/dev/null 2>&1; do
  sleep 1
done

psql -h postgres -U postgres -d ticker_alert_db -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
  filename TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SQL

echo "Applying migrations..."
for f in /migrations/*.sql; do
  name="$(basename "$f")"
  applied="$(psql -h postgres -U postgres -d ticker_alert_db -Atc \
    "SELECT 1 FROM schema_migrations WHERE filename = '$name' LIMIT 1" || true)"
  if [ "$applied" = "1" ]; then
    echo "  skip $name (already applied)"
    continue
  fi
  echo "  -> $name"
  psql -h postgres -U postgres -d ticker_alert_db -v ON_ERROR_STOP=1 -f "$f"
  psql -h postgres -U postgres -d ticker_alert_db -v ON_ERROR_STOP=1 -c \
    "INSERT INTO schema_migrations (filename) VALUES ('$name') ON CONFLICT DO NOTHING"
done
echo "Migrations complete."
